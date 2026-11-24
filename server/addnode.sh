#!/bin/bash
# 用法：addnode.sh <job.json>
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${1:-}" = "--stdin" ]; then
  JOB_JSON=$(cat)
else
  JOB_JSON=$(cat "${1:?need job config}")
fi
get() { printf '%s' "$JOB_JSON" | python3 -c 'import json,sys; v=json.load(sys.stdin);
for part in sys.argv[1].split("."): v=v.get(part) if isinstance(v,dict) else None
print("" if v is None else v)' "$1"; }

IP=$(get ip); UNAME=$(get user); AUTH=$(get auth_type); NAME=$(get name)
PORT=$(get port); ROLE=$(get role); SECRET=$(get secret_file); DRY=$(get dry_run)
SSH_PORT=$(get ssh_port); PIN_HOSTS=$(get pin_hosts_file); PASSPHRASE_FILE=$(get passphrase_file); EXPECT_MACHINE=$(get machine_id); JOB_ID=$(get job_id)
DRY=$(echo "$DRY" | tr 'A-Z' 'a-z')

[ -n "$IP" ] || { echo "缺少服务器地址"; exit 2; }
PASSWORD=$(get password); PRIVATE_KEY=$(get private_key); PASSPHRASE=$(get passphrase)
HOST_KEY_TYPE=$(get host_key_type); HOST_KEY=$(get host_key)
if [ -n "$SECRET" ] && [ -f "$SECRET" ]; then
  if [ "$AUTH" = "key" ]; then PRIVATE_KEY=$(cat "$SECRET"); else PASSWORD=$(cat "$SECRET"); fi
fi
[ -n "$PASSWORD$PRIVATE_KEY" ] || { echo "缺少内存认证信息"; exit 2; }
SELF_BOOTSTRAP=$(get self_bootstrap)
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
[ -n "$HOST_KEY_TYPE" ] && [ -n "$HOST_KEY" ] || { echo "缺少已确认的服务器指纹"; exit 2; }
rsh() {
  python3 "$SCRIPT_DIR/nodekit/ssh_memory.py" 6 "$@" 6< <(printf '%s' "$JOB_JSON")
}
rsh_root() {
  if [ "$UNAME" = "root" ]; then
    rsh "$1"
  else
    local quoted
    quoted=$(python3 -c 'import shlex,sys; print(shlex.quote(sys.argv[1]))' "$1")
    rsh "sudo -n bash -c $quoted"
  fi
}

if [ -n "$EXPECT_MACHINE" ] && ! rsh "test \"\$(cat /etc/machine-id 2>/dev/null)\" = '$EXPECT_MACHINE'"; then
  echo "服务器身份与检查时不同，已停止安装"; exit 3
fi

echo "STEP 1 正在连接服务器"
CONN=""
for try in 1 2; do
  if CONN=$(rsh "uname -m" 2>&1); then break; fi
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
rsh_root "$PROBE_CMD" > "$PF" 2>&1 || true
if ! PF_OUT=$(python3 /opt/web/nodekit/preflight_cli.py "$PF"); then
  echo "$PF_OUT"; rm -f "$PF"; exit 1
fi
eval "$PF_OUT"
rm -f "$PF"
echo "  预检通过：架构 $ARCH"
if [ "$SELF_BOOTSTRAP" = "True" ] || [ "$SELF_BOOTSTRAP" = "true" ]; then
  if ! rsh_root "for p in /opt/web /opt/web-data /etc/caddy/Caddyfile /etc/systemd/system/admin.service; do [ ! -e \"\$p\" ] || exit 3; done"; then
    echo "目标已有管理配置，未覆盖"; exit 3
  fi
fi
# 不将已有 sing-box 当作可接管服务，避免覆盖其他业务。
if ! rsh_root "command -v systemctl >/dev/null 2>&1 && systemctl list-units --all --no-legend --no-pager >/dev/null 2>&1 || { echo '无法检查系统服务'; exit 3; }; for p in /opt/sing-box /etc/systemd/system/sing-box.service /lib/systemd/system/sing-box.service /usr/lib/systemd/system/sing-box.service; do if [ -e \"\$p\" ]; then echo '检测到已有 sing-box，未安装；请人工检查'; exit 3; fi; done; if systemctl is-active --quiet sing-box 2>/dev/null; then echo '检测到运行中的 sing-box，未安装'; exit 3; fi"; then
  echo "目标服务器的既有服务检查未通过，已停止安装"; exit 3
fi
if [ "$DRY" = "true" ]; then echo "演练模式：预检通过，未安装"; exit 0; fi
if [ -n "$HOST_KEY" ]; then
  if ! rsh_root "mkdir /run/ownline-node-install.lock"; then
    echo "目标上已有安装任务或待确认状态，请检查后再试"; exit 3
  fi
  cleanup_remote_lock() { rsh_root "rmdir /run/ownline-node-install.lock 2>/dev/null || true" >/dev/null 2>&1 || true; }
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
rsh_root "command -v curl >/dev/null 2>&1 || (command -v apt-get >/dev/null 2>&1 && apt-get update -qq && apt-get install -y -qq curl) || (command -v yum >/dev/null 2>&1 && yum install -y -q curl) || true" >/dev/null 2>&1

echo "  检查能不能直连国外"
EGRESS=$(rsh "curl -s --max-time 8 https://api.ipify.org 2>/dev/null || curl -s --max-time 8 https://ipinfo.io/ip 2>/dev/null || curl -s --max-time 8 http://ifconfig.me/ip 2>/dev/null" | tr -d '\r' | tail -1)
DIRECT=0
if printf '%s' "$EGRESS" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
  DIRECT=1
  echo "  能直连，出口 $EGRESS"
else
  echo "  直连不了国外，会自动借道另一台节点"
fi
HAS_LANDING=$(printf '%s' "$JOB_JSON" | python3 -c 'import json,sys; j=json.load(sys.stdin); l=j.get("landing") or {}; print("1" if (l.get("host") and l.get("uuid")) or l.get("link") else "0")')

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

CONFIG=$(TARGET_DIRECT="$DIRECT" python3 - /dev/fd/6 "$PORT" 6< <(printf '%s' "$JOB_JSON") <<'PYCFG'
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
        "sni": node.get("hy2_sni") or "www.apple.com",
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

MANIFEST=$(printf '%s\n%s' "$CONFIG" "$JOB_JSON" | python3 -c 'import json,sys; sys.path.insert(0,"/opt/web"); from nodekit import provenance as p; cfg=sys.stdin.readline(); job=json.load(sys.stdin); secret=bytes.fromhex(job["control_secret"]); m=p.sign_provenance(job["ip"],p.compute_config_sha256(cfg),secret); assert p.verify_provenance(m,secret)[0]; print(json.dumps(m))')
[ -n "$MANIFEST" ] || { echo "服务归属存证生成失败"; exit 4; }
CERT_B64=$(get node.hy2_cert_b64); KEY_B64=$(get node.hy2_key_b64)

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

getent group sing-box >/dev/null || groupadd --system sing-box
getent passwd sing-box >/dev/null || useradd --system --gid sing-box --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin sing-box
chmod 755 /opt/sing-box /opt/sing-box/sing-box
touch /var/log/sing-box.log
chown sing-box:sing-box /var/log/sing-box.log
chmod 640 /var/log/sing-box.log

umask 077
if [ "__HAS_HY2__" = "1" ]; then
  printf '%s' '__CERT_B64__' | base64 -d > /opt/sing-box/hy2.crt
  printf '%s' '__KEY_B64__' | base64 -d > /opt/sing-box/hy2.key
  test -s /opt/sing-box/hy2.key && test -s /opt/sing-box/hy2.crt
  chown root:sing-box /opt/sing-box/hy2.key /opt/sing-box/hy2.crt
  chmod 640 /opt/sing-box/hy2.key
  chmod 644 /opt/sing-box/hy2.crt
fi
mkdir -p /etc/sing-box
cat > /etc/sing-box/.evergreen-provenance.json <<'PROVENANCE'
__MANIFEST__
PROVENANCE

cat > /opt/sing-box/config.json <<'JSONCFG'
__CONFIG__
JSONCFG
chown root:sing-box /opt/sing-box/config.json
chmod 640 /opt/sing-box/config.json
cat > /etc/systemd/system/sing-box.service <<'UNIT'
[Unit]
Description=sing-box service
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/var/lib/ownline/quota-paused

[Service]
Type=simple
User=sing-box
Group=sing-box
WorkingDirectory=/opt/sing-box
ExecStart=/opt/sing-box/sing-box run -c /opt/sing-box/config.json
Restart=on-failure
RestartSec=5
LimitNOFILE=1048576
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ReadOnlyPaths=/opt/sing-box
ReadWritePaths=/var/log/sing-box.log
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
ProtectProc=invisible
ProcSubset=pid
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @mount @reboot @swap @clock @module @raw-io @debug @cpu-emulation @obsolete
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
chmod 644 /etc/systemd/system/sing-box.service
systemctl daemon-reload
systemctl enable sing-box >/dev/null 2>&1 || true
/opt/sing-box/sing-box check -c /opt/sing-box/config.json
systemctl start sing-box
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
REMOTE="${REMOTE//__CERT_B64__/$CERT_B64}"
REMOTE="${REMOTE//__KEY_B64__/$KEY_B64}"
REMOTE="${REMOTE//__MANIFEST__/$MANIFEST}"

if [ "$UNAME" = "root" ]; then
  OUT=$(printf '%s' "$REMOTE" | rsh "bash -s" 2>&1)
else
  OUT=$(printf '%s' "$REMOTE" | rsh "sudo -n bash -s" 2>&1)
fi
echo "$OUT"
if ! printf '%s' "$OUT" | grep -q PROVISION_OK; then
  echo "安装失败：服务没有启动成功"
  exit 5
fi

echo "STEP 4 正在检查端口"
if timeout 8 bash -c "</dev/tcp/$IP/$PORT" 2>/dev/null; then echo REACHABLE; else echo PORT_BLOCKED; fi

if [ "$SELF_BOOTSTRAP" = "True" ] || [ "$SELF_BOOTSTRAP" = "true" ]; then
  echo "STEP 4 正在部署独立管理后台"
  SOURCE_DIR="/tmp/ownline-source-$JOB_ID"
  rsh "install -d -m 700 '$SOURCE_DIR'" || exit 7
  python3 "$SCRIPT_DIR/nodekit/installations.py" bundle "$SCRIPT_DIR" | rsh "tar xzf - -C '$SOURCE_DIR'" || exit 7
  BOOTSTRAP_JSON=$(printf '%s' "$JOB_JSON" | python3 -c 'import json,sys; j=json.load(sys.stdin); allowed=("job_id","ip","name","user","ssh_port","port","role","landing","control_secret","sub_token","panel_hash","self_bootstrap"); out={k:j.get(k) for k in allowed}; out["actual_role"]="exit" if j["role"]=="exit" or (j["role"]=="auto" and sys.argv[1]=="1") else "relay"; out["node"]={"pbk":j["node"]["pbk"]}; print(json.dumps(out))' "$DIRECT")
  if ! printf '%s' "$BOOTSTRAP_JSON" | rsh_root "python3 '$SOURCE_DIR/server/bootstrap_target.py'"; then
    echo "独立后台部署未完成，请检查服务器状态"; exit 7
  fi
  rsh_root "rm -rf '$SOURCE_DIR'" >/dev/null 2>&1 || true
fi

TARGET_DIRECT_2="$DIRECT" python3 - /dev/fd/6 6< <(printf '%s' "$JOB_JSON") <<'PYOUT'
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
    "warp_enabled": False,
    "hy2_enabled": actual_role == "exit",
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
        "sni": node.get("hy2_sni") or "www.apple.com",
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
