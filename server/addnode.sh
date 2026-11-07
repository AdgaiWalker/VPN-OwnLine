#!/bin/bash
# 用法：addnode.sh <job.json>
set -uo pipefail

J="${1:?need job config}"
get() { python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));v=d.get(sys.argv[2]);print("" if v is None else v)' "$J" "$1"; }

IP=$(get ip); UNAME=$(get user); AUTH=$(get auth_type); NAME=$(get name)
PORT=$(get port); ROLE=$(get role); SECRET=$(get secret_file); DRY=$(get dry_run)
SSH_PORT=$(get ssh_port); PIN_HOSTS=$(get pin_hosts_file); PASSPHRASE_FILE=$(get passphrase_file); EXPECT_MACHINE=$(get machine_id); JOB_ID=$(get job_id)
DRY=$(echo "$DRY" | tr 'A-Z' 'a-z')

[ -n "$IP" ] || { echo "缺少服务器地址"; exit 2; }
[ -n "$SECRET" ] && [ -f "$SECRET" ] || { echo "缺少凭据文件"; exit 2; }
PORT="${PORT:-443}"
ROLE="${ROLE:-auto}"
UNAME="${UNAME:-root}"
[[ "$UNAME" =~ ^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$ ]] || { echo "SSH 用户名格式不正确"; exit 2; }
SSH_PORT="${SSH_PORT:-22}"
[[ "$SSH_PORT" =~ ^[0-9]{1,5}$ ]] && [ "$SSH_PORT" -ge 1 ] && [ "$SSH_PORT" -le 65535 ] || { echo "SSH 端口无效"; exit 2; }
if [ -n "$EXPECT_MACHINE" ]; then [[ "$EXPECT_MACHINE" =~ ^[a-f0-9]{32}$ ]] || { echo "服务器身份无效"; exit 2; }; fi
if [ -z "$JOB_ID" ]; then JOB_ID="$$"; fi
[[ "$JOB_ID" =~ ^[a-zA-Z0-9_-]{1,64}$ ]] || { echo "任务标识无效"; exit 2; }
REMOTE_ARCHIVE="/tmp/ownline-node-$JOB_ID.tgz"

VER="1.14.4"
GH="github.com/SagerNet/sing-box/releases/download/v$VER/sing-box-$VER-linux"
CACHE_DIR="/opt/sing-box/pkg"
KH="/opt/sing-box/known_hosts"
touch "$KH" 2>/dev/null || true
chmod 600 "$KH" 2>/dev/null || true
if [ -n "$PIN_HOSTS" ]; then
  [ -f "$PIN_HOSTS" ] || { echo "缺少已确认的服务器指纹"; exit 2; }
  OPTS=(-p "$SSH_PORT" -o UserKnownHostsFile="$PIN_HOSTS" -o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=20 -o ServerAliveInterval=10)
else
  # Legacy callers keep their existing known-hosts policy; new installs must pin.
  OPTS=(-p "$SSH_PORT" -o UserKnownHostsFile="$KH" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o ServerAliveInterval=10)
fi

if [ "$AUTH" = "key" ]; then
  if [ -n "$PASSPHRASE_FILE" ]; then
    [ -f "$PASSPHRASE_FILE" ] || { echo "缺少私钥口令"; exit 2; }
    SSH=(sshpass -P 'Enter passphrase' -f "$PASSPHRASE_FILE" ssh -i "$SECRET" -o IdentitiesOnly=yes)
  else
    SSH=(ssh -i "$SECRET" -o IdentitiesOnly=yes -o BatchMode=yes)
  fi
else
  SSH=(sshpass -f "$SECRET" ssh)
fi
rsh() { "${SSH[@]}" "${OPTS[@]}" "$UNAME@$IP" "$@"; }

if [ -n "$EXPECT_MACHINE" ] && ! rsh "test \"\$(cat /etc/machine-id 2>/dev/null)\" = '$EXPECT_MACHINE'"; then
  echo "服务器身份与检查时不同，已停止安装"; exit 3
fi

echo "STEP 1 正在连接服务器"
CONN=""
for try in 1 2; do
  if CONN=$(rsh -o NumberOfPasswordPrompts=1 "uname -m" 2>&1); then break; fi
  if [ "$try" = "1" ]; then echo "  第一次没连上，3 秒后重试"; sleep 3; fi
done
if ! printf '%s' "$CONN" | grep -qE "^(x86_64|aarch64|arm64)"; then
  if printf '%s' "$CONN" | grep -qiE "(permission denied|authentication failed)"; then
    echo "连接失败：用户名或 root 密码错误（Permission denied），请在云控制台重置 root 密码后再试"; exit 1
  elif printf '%s' "$CONN" | grep -qiE "(connection timed out|no route to host)"; then
    echo "连接失败：网络超时无法连接，请确认服务器已开机且云厂商安全组已放行 ${SSH_PORT} 端口"; exit 1
  elif printf '%s' "$CONN" | grep -qiE "(connection refused)"; then
    echo "连接失败：连接被拒绝（Connection refused），目标服务器未开启 SSH 服务或端口未开放"; exit 1
  else
    echo "连接失败：$CONN"; exit 1
  fi
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
# 不将已有 sing-box 当作可接管服务，避免覆盖其他业务。
if ! rsh "command -v systemctl >/dev/null 2>&1 && systemctl list-units --all --no-legend --no-pager >/dev/null 2>&1 || { echo '无法检查系统服务'; exit 3; }; for p in /opt/sing-box /etc/systemd/system/sing-box.service /lib/systemd/system/sing-box.service /usr/lib/systemd/system/sing-box.service; do if [ -e \"\$p\" ]; then echo '检测到已有 sing-box，未安装；请人工检查'; exit 3; fi; done; if systemctl is-active --quiet sing-box 2>/dev/null; then echo '检测到运行中的 sing-box，未安装'; exit 3; fi"; then
  echo "目标服务器的既有服务检查未通过，已停止安装"; exit 3
fi
if [ "$DRY" = "true" ]; then echo "演练模式：预检通过，未安装"; exit 0; fi
if [ -n "$PIN_HOSTS" ]; then
  if ! rsh "mkdir /run/ownline-node-install.lock"; then
    echo "目标上已有安装任务或待确认状态，请检查后再试"; exit 3
  fi
  cleanup_remote_lock() { rsh "rmdir /run/ownline-node-install.lock 2>/dev/null || true" >/dev/null 2>&1 || true; }
  trap cleanup_remote_lock EXIT
fi
read -r CTL_TYPE CTL_KEY _ < /root/.ssh/node_ctl.pub || { echo "无法读取管理公钥"; exit 6; }
[[ "$CTL_TYPE" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521)$ ]] && [[ "$CTL_KEY" =~ ^[A-Za-z0-9+/=]+$ ]] || { echo "管理公钥格式无效"; exit 6; }
CTL_PUB="$CTL_TYPE $CTL_KEY"
if ! rsh "h=\$(getent passwd '$UNAME' | cut -d: -f6); [ -n \"\$h\" ] && [ -d \"\$h\" ] && [ ! -L \"\$h/.ssh\" ] && [ ! -L \"\$h/.ssh/authorized_keys\" ]"; then
  echo "无法安全确认 SSH 授权路径，请人工检查"; exit 6
fi
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
LOCAL_PKG="$CACHE_DIR/sing-box-$VER-linux-$ARCH.tar.gz"
if [ -f "$LOCAL_PKG" ]; then
  LOCAL_SHA=$(sha256sum "$LOCAL_PKG" 2>/dev/null | cut -d' ' -f1)
  if [ "$LOCAL_SHA" = "$EXPECT" ]; then
    echo "  优先从主控本地缓存同步安装包 ($LOCAL_PKG)"
    if rsh "cat > '$REMOTE_ARCHIVE'" < "$LOCAL_PKG" 2>/dev/null; then
      GOT=$(rsh "sha256sum '$REMOTE_ARCHIVE' 2>/dev/null | cut -d' ' -f1" | tr -d '\r')
      if [ "$GOT" = "$EXPECT" ]; then
        echo "  本地缓存同步成功，SHA256 校验通过"
        DL_OK=1
      else
        rsh "rm -f '$REMOTE_ARCHIVE'" >/dev/null 2>&1 || true
      fi
    fi
  fi
fi

if [ "$DL_OK" != "1" ]; then
  for pair in \
    "20|https://$GH-${ARCH}.tar.gz" \
    "240|https://ghfast.top/https://$GH-${ARCH}.tar.gz" \
    "240|https://gh-proxy.com/https://$GH-${ARCH}.tar.gz" \
    "240|https://ghproxy.net/https://$GH-${ARCH}.tar.gz" ; do
    MT="${pair%%|*}"; U="${pair#*|}"
    echo "  尝试(${MT}s): $U"
    if rsh "curl -fsSL --connect-timeout 6 --max-time $MT -o '$REMOTE_ARCHIVE' '$U'" >/dev/null 2>&1; then
      GOT=$(rsh "sha256sum '$REMOTE_ARCHIVE' 2>/dev/null | cut -d' ' -f1" | tr -d '\r')
      if [ "$GOT" != "$EXPECT" ]; then
        echo "  校验失败（期望 ${EXPECT:0:12}… 实际 ${GOT:0:12}…），换下一个源"
        rsh "rm -f '$REMOTE_ARCHIVE'" >/dev/null 2>&1
        continue
      fi
      echo "  下载成功，SHA256 校验通过"
      DL_OK=1; break
    fi
  done
fi
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
    conf = templates.exit_config(port, node["uuid"], node["sni"], node["private_key"], node["sid"], hy2=hy2_opts, isp=node.get("isp"))
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
# 再次检查，避免下载期间出现既有文件后继续覆盖。
command -v systemctl >/dev/null 2>&1 && systemctl list-units --all --no-legend --no-pager >/dev/null 2>&1 || { echo "无法检查系统服务"; exit 3; }
for p in /opt/sing-box/config.json /opt/sing-box/sing-box /etc/systemd/system/sing-box.service /lib/systemd/system/sing-box.service /usr/lib/systemd/system/sing-box.service; do
  if [ -e "$p" ]; then echo "检测到已有 sing-box，未覆盖；请人工检查"; exit 3; fi
done
if systemctl is-active --quiet sing-box 2>/dev/null; then echo "检测到运行中的 sing-box，未覆盖"; exit 3; fi
[ ! -e /opt/sing-box ] || { echo "检测到已有 sing-box 目录，未覆盖"; exit 3; }
mkdir /opt/sing-box
tar xzf "__ARCHIVE__" -C /opt/sing-box --strip-components=1
rm -f "__ARCHIVE__"

if [ "__HAS_HY2__" = "1" ] && [ ! -f /opt/sing-box/hy2.key ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -keyout /opt/sing-box/hy2.key -out /opt/sing-box/hy2.crt -days 3650 -subj "/CN=www.bing.com" 2>/dev/null || true
  chmod 600 /opt/sing-box/hy2.key 2>/dev/null || true
fi

cat > /opt/sing-box/config.json <<'JSONCFG'
__CONFIG__
JSONCFG
cat > /etc/systemd/system/sing-box.service <<'UNIT'
[Unit]
Description=sing-box service
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/var/lib/ownline/quota-paused

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
[ -n "$AUTH_HOME" ] && [ -d "$AUTH_HOME" ] || { echo "无法确认 SSH 用户主目录"; exit 6; }
SSH_DIR="$AUTH_HOME/.ssh"
AUTH_KEYS="$SSH_DIR/authorized_keys"
[ ! -L "$SSH_DIR" ] && [ ! -L "$AUTH_KEYS" ] || { echo "SSH 授权路径是符号链接，请人工检查"; exit 6; }
if [ ! -d "$SSH_DIR" ]; then
  mkdir -m 700 "$SSH_DIR"
  chown "__UNAME__" "$SSH_DIR"
fi
if [ ! -e "$AUTH_KEYS" ]; then
  install -m 600 -o "__UNAME__" /dev/null "$AUTH_KEYS"
fi
[ -f "$AUTH_KEYS" ] || { echo "SSH 授权文件不是普通文件"; exit 6; }
if ! grep -qF "__CTL_PUB__" "$AUTH_KEYS" 2>/dev/null; then
  # Keep an existing final line valid even if it lacked a newline.
  if [ -s "$AUTH_KEYS" ] && [ -n "$(tail -c 1 "$AUTH_KEYS")" ]; then printf '\n' >> "$AUTH_KEYS"; fi
  printf '%s\n' "__CTL_PUB__" >> "$AUTH_KEYS"
fi
echo PROVISION_OK
EOS
)
REMOTE="${REMOTE//__CONFIG__/$CONFIG}"
REMOTE="${REMOTE//__PORT__/$PORT}"
REMOTE="${REMOTE//__UNAME__/$UNAME}"
REMOTE="${REMOTE//__HAS_HY2__/$HAS_HY2}"
REMOTE="${REMOTE//__ARCHIVE__/$REMOTE_ARCHIVE}"
REMOTE="${REMOTE//__CTL_PUB__/$CTL_PUB}"

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
    "ssh_port": int(job.get("ssh_port") or 22),
    "uuid": node.get("uuid"),
    "sni": node.get("sni"),
    "pbk": node.get("pbk"),
    "sid": node.get("sid"),
    "ssh_user": job.get("user") or "root",
    "role": actual_role,
    "landing": job.get("landing") or None,
    "source": "builtin",
    "quota_control_managed": True,
    "health": "unknown",
}
print(json.dumps(vless_out, ensure_ascii=False))

if actual_role == "exit":
    hy2_out = {
        "name": job.get("name") + "-HY2",
        "type": "hysteria2",
        "host": job.get("ip"),
        "port": int(job.get("port") or 443),
        "ssh_port": int(job.get("ssh_port") or 22),
        "password": node.get("hy2_password") or node.get("uuid"),
        "sni": node.get("hy2_sni") or "www.bing.com",
        "obfs_password": node.get("obfs_password") or "tz-obfs",
        "ssh_user": job.get("user") or "root",
        "role": "exit",
        "landing": None,
        "source": "builtin",
        "quota_control_managed": True,
        "health": "unknown",
    }
    print(json.dumps(hy2_out, ensure_ascii=False))
PYOUT
