#!/bin/bash
set -euo pipefail
IP="$1"; UNAME="$2"; PASS="$3"; NAME="$4"; PORT="${5:-443}"
VER="1.14.4"
GH="github.com/SagerNet/sing-box/releases/download/v$VER/sing-box-$VER-linux"
CACHE_DIR="/opt/sing-box/pkg"

echo "STEP 1 正在连接服务器"
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20 -o ServerAliveInterval=10"

CONN_OUT=""
for try in 1 2; do
  if CONN_OUT=$(sshpass -p "$PASS" ssh $OPTS -o NumberOfPasswordPrompts=1 -o ConnectionAttempts=2 "$UNAME@$IP" "uname -m" 2>&1); then break; fi
  if [ "$try" = "1" ]; then echo "  第一次没连上，3 秒后重试"; sleep 3; fi
done
if [ -z "$CONN_OUT" ] || ! printf "%s" "$CONN_OUT" | grep -qE "^(x86_64|aarch64|arm64)"; then
  echo "连接失败：$CONN_OUT"
  exit 1
fi
RAWARCH=$(printf '%s' "$CONN_OUT" | tr -d '\r' | tail -1)
case "$RAWARCH" in
  x86_64) ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "unsupported arch：$RAWARCH"; exit 1 ;;
esac

echo "STEP 2 正在下载 sing-box"
EXPECT=$(awk -v a="linux-$ARCH.tar.gz" '$2 ~ a {print $1}' "$CACHE_DIR/SHA256SUMS" 2>/dev/null | head -1 || true)
if [ -n "$EXPECT" ]; then echo "  指纹: ${EXPECT:0:16}…"; else echo "  警告：没有这个架构的指纹，跳过校验"; fi
if [ "$UNAME" = "root" ]; then SSH="bash"; else SSH="sudo -n bash"; fi
sshpass -p "$PASS" ssh $OPTS "$UNAME@$IP" "$SSH -s" <<EOS
set -e
command -v curl >/dev/null 2>&1 || { command -v apt-get >/dev/null 2>&1 && apt-get update -qq && apt-get install -y -qq curl; } || { command -v yum >/dev/null 2>&1 && yum install -y -q curl; } || true
cd /tmp
ok=0
for pair in \
  "20|https://$GH-${ARCH}.tar.gz" \
  "240|https://ghfast.top/https://$GH-${ARCH}.tar.gz" \
  "240|https://gh-proxy.com/https://$GH-${ARCH}.tar.gz" \
  "240|https://ghproxy.net/https://$GH-${ARCH}.tar.gz" ; do
  mt="\${pair%%|*}"; u="\${pair#*|}"
  echo "  尝试(\${mt}s): \$u"
  if curl -fsSL --connect-timeout 6 --max-time \$mt -o /tmp/sb.tgz "\$u" 2>/dev/null; then
    if [ -z "$EXPECT" ]; then ok=1; echo "  下载成功（没有指纹，跳过校验）"; break; fi
    if echo "$EXPECT  /tmp/sb.tgz" | sha256sum -c - >/dev/null 2>&1; then ok=1; echo "  下载成功，SHA256 校验通过"; break;
    else echo "  校验失败（文件可能被改过），换下一个源"; rm -f /tmp/sb.tgz; fi
  fi
done
[ "\$ok" = "1" ] || { echo "全部下载源都失败"; exit 3; }
EOS

UUID=$(/opt/sing-box/sing-box generate uuid)
KP=$(/opt/sing-box/sing-box generate reality-keypair)
PRIV=$(printf '%s\n' "$KP" | sed -n 's/^PrivateKey: //p')
PUB=$(printf '%s\n' "$KP" | sed -n 's/^PublicKey: //p')
SID=$(openssl rand -hex 4)
SNI="www.apple.com"
CTL_PUB=$(cat /root/.ssh/node_ctl.pub)

CONFIG=$(cat <<JSON
{
  "log": {"level": "warn", "output": "/var/log/sing-box.log", "timestamp": true},
  "inbounds": [{
    "type": "vless", "tag": "vless-reality", "listen": "::", "listen_port": ${PORT},
    "users": [{"uuid": "${UUID}", "flow": "xtls-rprx-vision"}],
    "tls": {"enabled": true, "server_name": "${SNI}",
      "reality": {"enabled": true,
        "handshake": {"server": "${SNI}", "server_port": 443},
        "private_key": "${PRIV}", "short_id": ["${SID}"]}}
  }],
  "outbounds": [{"type": "direct", "tag": "direct"}]
}
JSON
)

REMOTE=$(cat <<EOS
set -e
echo "STEP 3 正在安装并启动"
mkdir -p /opt/sing-box
tar xzf /tmp/sb.tgz -C /opt/sing-box --strip-components=1
rm -f /tmp/sb.tgz
cat > /opt/sing-box/config.json <<'JSONCFG'
${CONFIG}
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
systemctl enable --now sing-box
sleep 2
systemctl is-active sing-box
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow ${PORT}/tcp >/dev/null 2>&1 || true; fi
if command -v firewall-cmd >/dev/null 2>&1; then firewall-cmd --permanent --add-port=${PORT}/tcp >/dev/null 2>&1 || true; firewall-cmd --reload >/dev/null 2>&1 || true; fi
AUTH_HOME=\$(getent passwd "${UNAME}" | cut -d: -f6)
mkdir -p "\$AUTH_HOME/.ssh"; touch "\$AUTH_HOME/.ssh/authorized_keys"
grep -qF "${CTL_PUB}" "\$AUTH_HOME/.ssh/authorized_keys" 2>/dev/null || echo "${CTL_PUB}" >> "\$AUTH_HOME/.ssh/authorized_keys"
chmod 700 "\$AUTH_HOME/.ssh"; chmod 600 "\$AUTH_HOME/.ssh/authorized_keys"
chown -R "${UNAME}" "\$AUTH_HOME/.ssh" 2>/dev/null || true
echo PROVISION_OK
EOS
)

B64=$(printf '%s' "$REMOTE" | base64 -w0)
if [ "$UNAME" = "root" ]; then
  sshpass -p "$PASS" ssh $OPTS "$UNAME@$IP" "echo $B64 | base64 -d | bash"
else
  sshpass -p "$PASS" ssh $OPTS "$UNAME@$IP" "echo $B64 | base64 -d | sudo -n bash"
fi

echo "STEP 4 正在检查端口"
if timeout 8 bash -c "</dev/tcp/$IP/$PORT" 2>/dev/null; then echo REACHABLE; else echo PORT_BLOCKED; fi

printf '{"name":"%s","host":"%s","port":%s,"uuid":"%s","sni":"%s","pbk":"%s","sid":"%s","ssh_user":"%s","added":"%s"}\n' \
  "$NAME" "$IP" "$PORT" "$UUID" "$SNI" "$PUB" "$SID" "$UNAME" "$(date -u +%FT%TZ)"
