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
ROLE="${ROLE:-exit}"
UNAME="${UNAME:-root}"

VER="1.14.4"
GH="github.com/SagerNet/sing-box/releases/download/v$VER/sing-box-$VER-linux"
CACHE_DIR="/opt/sing-box/pkg"
OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20 -o ServerAliveInterval=10)

if [ "$AUTH" = "key" ]; then
  SSH=(ssh -i "$SECRET" -o IdentitiesOnly=yes -o BatchMode=yes)
else
  SSH=(sshpass -p "$(cat "$SECRET")" ssh)
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
PROBE_CMD='cat /etc/os-release 2>/dev/null; echo "---ARCH---"; uname -m; echo "---SYSTEMD---"; command -v systemctl || echo none; echo "---DISK---"; df -mP / | tail -1; echo "---TOOLS---"; command -v curl || echo none; command -v tar || echo none; echo "---INSTALLED---"; test -x /opt/sing-box/sing-box && echo yes || echo no'
rsh "$PROBE_CMD" > "$PF" 2>&1 || true
if ! PF_OUT=$(python3 /opt/web/nodekit/preflight_cli.py "$PF"); then
  echo "$PF_OUT"; rm -f "$PF"; exit 1
fi
eval "$PF_OUT"
rm -f "$PF"
echo "  预检通过：架构 $ARCH"
if [ "$DRY" = "true" ]; then echo "演练模式：预检通过，未安装"; exit 0; fi

echo "STEP 2 正在下载 sing-box"
EXPECT=$(awk -v a="linux-$ARCH.tar.gz" '$2 ~ a {print $1}' "$CACHE_DIR/SHA256SUMS" 2>/dev/null | head -1 || true)
if [ -n "$EXPECT" ]; then echo "  指纹: ${EXPECT:0:16}…"; else echo "  警告：没有这个架构的指纹，跳过校验"; fi

rsh "command -v curl >/dev/null 2>&1 || (command -v apt-get >/dev/null 2>&1 && apt-get update -qq && apt-get install -y -qq curl) || (command -v yum >/dev/null 2>&1 && yum install -y -q curl) || true" >/dev/null 2>&1

DL_OK=0
for pair in \
  "20|https://$GH-${ARCH}.tar.gz" \
  "240|https://ghfast.top/https://$GH-${ARCH}.tar.gz" \
  "240|https://gh-proxy.com/https://$GH-${ARCH}.tar.gz" \
  "240|https://ghproxy.net/https://$GH-${ARCH}.tar.gz" ; do
  MT="${pair%%|*}"; U="${pair#*|}"
  echo "  尝试(${MT}s): $U"
  if rsh "curl -fsSL --connect-timeout 6 --max-time $MT -o /tmp/sb.tgz '$U'" >/dev/null 2>&1; then
    if [ -n "$EXPECT" ]; then
      GOT=$(rsh "sha256sum /tmp/sb.tgz 2>/dev/null | cut -d' ' -f1" | tr -d '\r')
      if [ "$GOT" != "$EXPECT" ]; then echo "  校验失败，换下一个源"; rsh "rm -f /tmp/sb.tgz" >/dev/null 2>&1; continue; fi
      echo "  下载成功，SHA256 校验通过"
    else
      echo "  下载成功（无指纹）"
    fi
    DL_OK=1; break
  fi
done
if [ "$DL_OK" != "1" ]; then echo "全部下载源都失败"; exit 3; fi

CONFIG=$(python3 - "$J" "$PORT" <<'PYCFG'
import json, sys
sys.path.insert(0, "/opt/web")
from nodekit import templates, links
cfg_path, port = sys.argv[1], int(sys.argv[2])
job = json.load(open(cfg_path, encoding="utf-8"))
node = job.get("node") or {}
landing = job.get("landing") or None
if landing and not landing.get("uuid"):
    landing = links.parse(landing.get("link", ""))
if job.get("role") == "relay" and landing:
    conf = templates.relay_config(port, node["uuid"], node["sni"], node["private_key"], node["sid"], landing)
else:
    conf = templates.exit_config(port, node["uuid"], node["sni"], node["private_key"], node["sid"])
errs = templates.validate(conf)
if errs:
    sys.stderr.write("配置校验失败: %s\n" % ",".join(errs))
    sys.exit(1)
print(json.dumps(conf, ensure_ascii=False))
PYCFG
)
if [ -z "$CONFIG" ]; then echo "生成配置失败"; exit 4; fi

REMOTE=$(cat <<'EOS'
set -e
echo "STEP 3 正在安装并启动"
mkdir -p /opt/sing-box
tar xzf /tmp/sb.tgz -C /opt/sing-box --strip-components=1
rm -f /tmp/sb.tgz
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
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow __PORT__/tcp >/dev/null 2>&1 || true; fi
if command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --permanent --add-port=__PORT__/tcp >/dev/null 2>&1 || true; firewall-cmd --reload >/dev/null 2>&1 || true; fi
AUTH_HOME=$(getent passwd "$UNAME" | cut -d: -f6)
mkdir -p "$AUTH_HOME/.ssh"; touch "$AUTH_HOME/.ssh/authorized_keys"
grep -qF "__CTL_PUB__" "$AUTH_HOME/.ssh/authorized_keys" 2>/dev/null || echo "__CTL_PUB__" >> "$AUTH_HOME/.ssh/authorized_keys"
chmod 700 "$AUTH_HOME/.ssh"; chmod 600 "$AUTH_HOME/.ssh/authorized_keys"
chown -R "$UNAME" "$AUTH_HOME/.ssh" 2>/dev/null || true
echo PROVISION_OK
EOS
)
REMOTE="${REMOTE//__CONFIG__/$CONFIG}"
REMOTE="${REMOTE//__PORT__/$PORT}"
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

python3 - "$J" <<'PYOUT'
import json, sys
job = json.load(open(sys.argv[1], encoding="utf-8"))
node = job.get("node") or {}
out = {
    "name": job.get("name"),
    "host": job.get("ip"),
    "port": int(job.get("port") or 443),
    "uuid": node.get("uuid"),
    "sni": node.get("sni"),
    "pbk": node.get("pbk"),
    "sid": node.get("sid"),
    "ssh_user": job.get("user") or "root",
    "role": job.get("role") or "exit",
    "landing": job.get("landing") or None,
    "source": "builtin",
    "health": "unknown",
}
print(json.dumps(out, ensure_ascii=False))
PYOUT
