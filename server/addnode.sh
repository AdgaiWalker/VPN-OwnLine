#!/bin/bash
# 用法：addnode.sh <job.json>
set -uo pipefail

J="${1:?need job config}"
get() { python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));v=d.get(sys.argv[2]);print("" if v is None else v)' "$J" "$1"; }

IP=$(get ip); UNAME=$(get user); AUTH=$(get auth_type); NAME=$(get name)
PORT=$(get port); ROLE=$(get role); SECRET=$(get secret_file); DRY=$(get dry_run)
DRY=$(echo "$DRY" | tr 'A-Z' 'a-z')

[ -n "$IP" ] || { echo "缺少服务器地址"; exit 2; }
[ -n "$SECRET" ] && [ -f "$SECRET" ] || { echo "缺少凭据文件"; exit 2; }
PORT="${PORT:-443}"
ROLE="${ROLE:-auto}"
UNAME="${UNAME:-root}"

VER="1.14.4"
GH="github.com/SagerNet/sing-box/releases/download/v$VER/sing-box-$VER-linux"
CACHE_DIR="/opt/sing-box/pkg"
KH="/opt/sing-box/known_hosts"
touch "$KH" 2>/dev/null || true
chmod 600 "$KH" 2>/dev/null || true
# 首次连接记下指纹（TOFU），之后同一台必须对得上 —— 防中间人偷密码
OPTS=(-o UserKnownHostsFile="$KH" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o ServerAliveInterval=10)

if [ "$AUTH" = "key" ]; then
  SSH=(ssh -i "$SECRET" -o IdentitiesOnly=yes -o BatchMode=yes)
else
  SSH=(sshpass -f "$SECRET" ssh)
fi
rsh() { "${SSH[@]}" "${OPTS[@]}" "$UNAME@$IP" "$@"; }

echo "STEP 1 正在连接服务器"
CONN=""
for try in 1 2; do
  if CONN=$(rsh -o NumberOfPasswordPrompts=1 "uname -m" 2>&1); then break; fi
  if [ "$try" = "1" ]; then echo "  第一次没连上，3 秒后重试"; sleep 3; fi
done
if ! printf '%s' "$CONN" | grep -qE "^(x86_64|aarch64|arm64)"; then
  echo "连接失败：$CONN"; exit 1
fi

echo "  正在预检系统"
PF="/tmp/pf.$$.txt"
PROBE_CMD=$(python3 -c 'import sys; sys.path.insert(0,"/opt/web"); from nodekit import preflight; print(preflight.PROBE_CMD)')
rsh "$PROBE_CMD" > "$PF" 2>&1 || true
if ! PF_OUT=$(python3 /opt/web/nodekit/preflight_cli.py "$PF"); then
  echo "$PF_OUT"; rm -f "$PF"; exit 1
fi
eval "$PF_OUT"
rm -f "$PF"
echo "  预检通过：架构 $ARCH"
if [ "$DRY" = "true" ]; then echo "演练模式：预检通过，未安装"; exit 0; fi
# 先保证目标机有 curl，再做“能不能直连国外”的判断。
# 否则一台没装 curl 的干净机器会被误判成“出不去”，装上不该装的中转配置。
echo "  检查目标机依赖"
rsh "command -v curl >/dev/null 2>&1 || (command -v apt-get >/dev/null 2>&1 && apt-get update -qq && apt-get install -y -qq curl) || (command -v yum >/dev/null 2>&1 && yum install -y -q curl) || true" >/dev/null 2>&1

echo "  检查能不能直连国外"
EGRESS=$(rsh "curl -s --max-time 8 https://api.ipify.org 2>/dev/null || curl -s --max-time 8 https://ipinfo.io/ip 2>/dev/null || curl -s --max-time 8 http://ifconfig.me/ip 2>/dev/null" | tr -d '\r' | tail -1)
DIRECT=0
if printf '%s' "$EGRESS" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
  DIRECT=1
  echo "  能直连，出口 $EGRESS"
else
  echo "  直连不了国外，会自动借道另一台节点"
fi
HAS_LANDING=$(python3 - "$J" <<'PYLANDING'
import json, sys
job = json.load(open(sys.argv[1], encoding="utf-8"))
landing = job.get("landing") or {}
print("1" if (landing.get("host") and landing.get("uuid")) or landing.get("link") else "0")
PYLANDING
)
if [ "$DIRECT" != "1" ] && [ "$HAS_LANDING" != "1" ]; then
  echo "这台连不了国外，但还没有可用的海外节点可以借道。请先装一台海外机器，或手动指定落地节点。"
  exit 4
fi


echo "STEP 2 正在下载 sing-box"
EXPECT=$(awk -v a="linux-$ARCH.tar.gz" '$2 ~ a {print $1}' "$CACHE_DIR/SHA256SUMS" 2>/dev/null | head -1 || true)
if [ -z "$EXPECT" ]; then
  echo "缺少这个架构的校验指纹，拒绝安装（防止下载包被替换）"
  exit 3
fi
echo "  指纹: ${EXPECT:0:16}…"


DL_OK=0
for pair in \
  "20|https://$GH-${ARCH}.tar.gz" \
  "240|https://ghfast.top/https://$GH-${ARCH}.tar.gz" \
  "240|https://gh-proxy.com/https://$GH-${ARCH}.tar.gz" \
  "240|https://ghproxy.net/https://$GH-${ARCH}.tar.gz" ; do
  MT="${pair%%|*}"; U="${pair#*|}"
  echo "  尝试(${MT}s): $U"
  if rsh "curl -fsSL --connect-timeout 6 --max-time $MT -o /tmp/sb.tgz '$U'" >/dev/null 2>&1; then
    GOT=$(rsh "sha256sum /tmp/sb.tgz 2>/dev/null | cut -d' ' -f1" | tr -d '\r')
    if [ "$GOT" != "$EXPECT" ]; then
      echo "  校验失败（期望 ${EXPECT:0:12}… 实际 ${GOT:0:12}…），换下一个源"
      rsh "rm -f /tmp/sb.tgz" >/dev/null 2>&1
      continue
    fi
    echo "  下载成功，SHA256 校验通过"
    DL_OK=1; break
  fi
done
if [ "$DL_OK" != "1" ]; then echo "全部下载源都失败"; exit 3; fi

CONFIG=$(TARGET_DIRECT="$DIRECT" python3 - "$J" "$PORT" <<'PYCFG'
import json, os, sys
sys.path.insert(0, "/opt/web")
from nodekit import templates, links
cfg_path, port = sys.argv[1], int(sys.argv[2])
job = json.load(open(cfg_path, encoding="utf-8"))
node = job.get("node") or {}
landing = job.get("landing") or None
if landing and not landing.get("uuid"):
    landing = links.parse(landing.get("link", ""))
role = job.get("role") or "auto"
direct = 1 if os.environ.get("TARGET_DIRECT") == "1" else 0
if role == "auto":
    role = "exit" if direct else "relay"
if role == "relay" and landing:
    conf = templates.relay_config(port, node["uuid"], node["sni"], node["private_key"], node["sid"], landing)
else:
    hy2_opts = {
        "port": port,
        "password": node.get("hy2_password") or node["uuid"],
        "obfs_password": node.get("obfs_password") or "tz-obfs",
        "sni": node.get("hy2_sni") or "www.bing.com",
    }
    conf = templates.exit_config(port, node["uuid"], node["sni"], node["private_key"], node["sid"], hy2=hy2_opts)
errs = templates.validate(conf)
if errs:
    sys.stderr.write("配置校验失败: %s\n" % ",".join(errs))
    sys.exit(1)
print(json.dumps(conf, ensure_ascii=False))
PYCFG
)
if [ -z "$CONFIG" ]; then echo "生成配置失败"; exit 4; fi

CFG_TMP="/tmp/cfg.$$.json"
printf '%s' "$CONFIG" > "$CFG_TMP"
if [ -x /opt/sing-box/sing-box ]; then
  if ! /opt/sing-box/sing-box check -c "$CFG_TMP" > /tmp/cfgchk.$$ 2>&1; then
    echo "配置校验失败：$(tail -1 /tmp/cfgchk.$$)"
    rm -f "$CFG_TMP" "/tmp/cfgchk.$$"
    exit 4
  fi
  echo "  配置校验通过"
fi
rm -f "$CFG_TMP" "/tmp/cfgchk.$$"

HAS_HY2=0
if [ "$ROLE" = "exit" ] || ([ "$ROLE" = "auto" ] && [ "$DIRECT" = "1" ]); then
  HAS_HY2=1
fi

REMOTE=$(cat <<'EOS'
set -e
echo "STEP 3 正在安装并启动"
mkdir -p /opt/sing-box
tar xzf /tmp/sb.tgz -C /opt/sing-box --strip-components=1
rm -f /tmp/sb.tgz

if [ "__HAS_HY2__" = "1" ] && [ ! -f /opt/sing-box/hy2.key ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -keyout /opt/sing-box/hy2.key -out /opt/sing-box/hy2.crt -days 3650 -subj "/CN=www.bing.com" 2>/dev/null || true
  chmod 600 /opt/sing-box/hy2.key 2>/dev/null || true
fi

# 开启 BBR 拥塞控制
if modprobe tcp_bbr 2>/dev/null; then
  echo "tcp_bbr" > /etc/modules-load.d/bbr.conf 2>/dev/null || true
  cat > /etc/sysctl.d/99-bbr.conf << 'BBR'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
BBR
  sysctl -p /etc/sysctl.d/99-bbr.conf 2>/dev/null || true
fi

cat > /opt/sing-box/config.json <<'JSONCFG'
__CONFIG__
JSONCFG
cat > /etc/systemd/system/sing-box.service <<'UNIT'
[Unit]
Description=sing-box service
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/sing-box/sing-box run -c /opt/sing-box/config.json
Restart=on-failure
RestartSec=5
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable sing-box >/dev/null 2>&1 || true
systemctl restart sing-box
sleep 2
systemctl is-active sing-box
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow __PORT__/tcp >/dev/null 2>&1 || true
  if [ "__HAS_HY2__" = "1" ]; then ufw allow __PORT__/udp >/dev/null 2>&1 || true; fi
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port=__PORT__/tcp >/dev/null 2>&1 || true
  if [ "__HAS_HY2__" = "1" ]; then firewall-cmd --permanent --add-port=__PORT__/udp >/dev/null 2>&1 || true; fi
  firewall-cmd --reload >/dev/null 2>&1 || true
fi
AUTH_HOME=$(getent passwd "__UNAME__" | cut -d: -f6)
mkdir -p "$AUTH_HOME/.ssh"; touch "$AUTH_HOME/.ssh/authorized_keys"
grep -qF "__CTL_PUB__" "$AUTH_HOME/.ssh/authorized_keys" 2>/dev/null || echo "__CTL_PUB__" >> "$AUTH_HOME/.ssh/authorized_keys"
chmod 700 "$AUTH_HOME/.ssh"; chmod 600 "$AUTH_HOME/.ssh/authorized_keys"
chown -R "__UNAME__" "$AUTH_HOME/.ssh" 2>/dev/null || true
echo PROVISION_OK
EOS
)
REMOTE="${REMOTE//__CONFIG__/$CONFIG}"
REMOTE="${REMOTE//__PORT__/$PORT}"
REMOTE="${REMOTE//__UNAME__/$UNAME}"
REMOTE="${REMOTE//__HAS_HY2__/$HAS_HY2}"
REMOTE="${REMOTE//__CTL_PUB__/$(cat /root/.ssh/node_ctl.pub)}"

B64=$(printf '%s' "$REMOTE" | base64 -w0)
if [ "$UNAME" = "root" ]; then
  OUT=$(rsh "echo $B64 | base64 -d | bash" 2>&1)
else
  OUT=$(rsh "echo $B64 | base64 -d | sudo -n bash" 2>&1)
fi
echo "$OUT"
if ! printf '%s' "$OUT" | grep -q PROVISION_OK; then
  echo "安装失败：服务没有启动成功"
  exit 5
fi

echo "STEP 4 正在检查端口"
if timeout 8 bash -c "</dev/tcp/$IP/$PORT" 2>/dev/null; then echo REACHABLE; else echo PORT_BLOCKED; fi

TARGET_DIRECT_2="$DIRECT" python3 - "$J" <<'PYOUT'
import json, os, sys
job = json.load(open(sys.argv[1], encoding="utf-8"))
node = job.get("node") or {}
direct = os.environ.get("TARGET_DIRECT_2") == "1"
role = job.get("role") or "auto"
actual_role = "exit" if (role == "exit" or (role == "auto" and direct)) else "relay"

vless_out = {
    "name": job.get("name"),
    "host": job.get("ip"),
    "port": int(job.get("port") or 443),
    "uuid": node.get("uuid"),
    "sni": node.get("sni"),
    "pbk": node.get("pbk"),
    "sid": node.get("sid"),
    "ssh_user": job.get("user") or "root",
    "role": actual_role,
    "landing": job.get("landing") or None,
    "source": "builtin",
    "health": "unknown",
}
print(json.dumps(vless_out, ensure_ascii=False))

if actual_role == "exit":
    hy2_out = {
        "name": job.get("name") + "-HY2",
        "type": "hysteria2",
        "host": job.get("ip"),
        "port": int(job.get("port") or 443),
        "password": node.get("hy2_password") or node.get("uuid"),
        "sni": node.get("hy2_sni") or "www.bing.com",
        "obfs_password": node.get("obfs_password") or "tz-obfs",
        "ssh_user": job.get("user") or "root",
        "role": "exit",
        "landing": None,
        "source": "builtin",
        "health": "unknown",
    }
    print(json.dumps(hy2_out, ensure_ascii=False))
PYOUT
