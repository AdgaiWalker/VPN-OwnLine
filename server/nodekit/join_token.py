"""免密反向自举入网凭据（Pre-Auth Token）管理器。

负责生成一次性高熵入网 Token、生成动态安装 Shell 脚本、
核验证书与参数并完成一次性核销（消费即焚）。
"""
from __future__ import annotations

import hmac
import re
import secrets
import threading
import time
from typing import Any, Dict, Optional

# 默认 Token 有效期：15 分钟 (900 秒)
DEFAULT_TTL = 900
TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_LOCK = threading.Lock()
_TOKENS: Dict[str, Dict[str, Any]] = {}


def _clean_expired_locked(now: float) -> None:
    expired = [t for t, data in _TOKENS.items() if data.get("expires_at", 0) <= now]
    for t in expired:
        _TOKENS.pop(t, None)


def create_token(
    name: str = "",
    role: str = "exit",
    landing: Optional[Dict[str, Any]] = None,
    port: Optional[int] = None,
    expires_in: int = DEFAULT_TTL,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """生成一个新的高熵一次性入网 Token。"""
    now = time.time() if now_ts is None else float(now_ts)
    token = secrets.token_hex(32)
    role_norm = "relay" if str(role).lower() == "relay" else "exit"
    default_port = 8443 if role_norm == "relay" else 443
    actual_port = int(port) if port else default_port
    record = {
        "token": token,
        "name": (name or "").strip(),
        "role": role_norm,
        "port": actual_port,
        "landing": landing,
        "created_at": now,
        "expires_at": now + max(60, int(expires_in)),
    }
    with _LOCK:
        _clean_expired_locked(now)
        _TOKENS[token] = record
    return dict(record)


def verify_token(token: str, now_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """验证 Token 是否合法且未过期（只读检查，不核销）。"""
    if not token or not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        return None
    now = time.time() if now_ts is None else float(now_ts)
    with _LOCK:
        _clean_expired_locked(now)
        record = _TOKENS.get(token)
        if not record or record.get("expires_at", 0) <= now:
            return None
        return dict(record)


def consume_token(token: str, now_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """原子验证并核销 Token（消费即焚，防重放攻击）。"""
    if not token or not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        return None
    now = time.time() if now_ts is None else float(now_ts)
    with _LOCK:
        _clean_expired_locked(now)
        record = _TOKENS.pop(token, None)
        if not record or record.get("expires_at", 0) <= now:
            return None
        return dict(record)


def clear_all_tokens_for_testing() -> None:
    """仅供单测清空状态。"""
    with _LOCK:
        _TOKENS.clear()


def generate_install_script(
    token: str,
    server_url: str,
    role: str = "exit",
    landing: Optional[Dict[str, Any]] = None,
    port: Optional[int] = None,
) -> str:
    """生成供客户端 curl | bash 执行的原生轻量反向注册脚本。
    
    全程在远端本地安全生成密钥对与自签证书，通过单向 HTTPS POST 回传元数据。
    主控服务器与客户端均无需暴露或存储 root 密码。
    """
    server_url = (server_url or "").rstrip("/")
    is_relay = str(role).lower() == "relay"
    listen_port = int(port) if port else (8443 if is_relay else 443)

    if is_relay:
        cert_step = ""
        hy2_inbound = ""
        hy2_payload = ""
        if landing and landing.get("host") and landing.get("uuid") and landing.get("pbk") and landing.get("sid"):
            outbounds_json = f"""[
    {{
      "type": "vless",
      "tag": "landing",
      "server": "{landing['host']}",
      "server_port": {int(landing.get('port') or 443)},
      "uuid": "{landing['uuid']}",
      "flow": "{landing.get('flow') or 'xtls-rprx-vision'}",
      "tls": {{
        "enabled": true,
        "server_name": "{landing.get('sni') or 'www.apple.com'}",
        "utls": {{"enabled": true, "fingerprint": "chrome"}},
        "reality": {{
          "enabled": true,
          "public_key": "{landing['pbk']}",
          "short_id": "{landing['sid']}"
        }}
      }}
    }},
    {{"type": "direct", "tag": "direct"}}
  ]"""
            route_json = ',\n  "route": {"rules": [{"outbound": "landing"}]}'
        else:
            outbounds_json = '[{"type": "direct", "tag": "direct"}]'
            route_json = ""
    else:
        cert_step = 'openssl req -x509 -nodes -newkey rsa:2048 -keyout /opt/sing-box/hy2.key -out /opt/sing-box/hy2.crt -days 3650 -subj "/CN=www.bing.com" 2>/dev/null'
        hy2_inbound = f""",
    {{
      "type": "hysteria2",
      "tag": "hy2",
      "listen": "::",
      "listen_port": {listen_port},
      "users": [{{"password": "$HY2_PW"}}],
      "tls": {{
        "enabled": true,
        "server_name": "www.bing.com",
        "alpn": ["h3"],
        "certificate_path": "/opt/sing-box/hy2.crt",
        "key_path": "/opt/sing-box/hy2.key"
      }},
      "obfs": {{"type": "salamander", "password": "$OBFS_PW"}}
    }}"""
        hy2_payload = """,
  "hy2_password": "$HY2_PW",
  "obfs_password": "$OBFS_PW\""""
        outbounds_json = '[{"type": "direct", "tag": "direct"}]'
        route_json = ""

    return f"""#!/usr/bin/env bash
# Evergreen · OwnLine 一键免密反向自举脚本
# Token: {token}
set -euo pipefail
umask 077

if [ "$(id -u)" != "0" ]; then
  echo "[ERROR] 本脚本需要 root 权限，请使用 sudo 或切换至 root 执行。" >&2
  exit 1
fi

command -v systemctl >/dev/null && command -v pgrep >/dev/null || {{
  echo "[ERROR] 缺少 systemctl 或 pgrep，无法安全检查现有服务。" >&2
  exit 1
}}
if ! systemctl show --property=Version >/dev/null 2>&1; then
  echo "[ERROR] 无法检查 systemd 服务，停止安装。" >&2
  exit 1
fi
occupied() {{ [ -e "$1" ] || [ -L "$1" ]; }}
if occupied /opt/sing-box/config.json || occupied /opt/sing-box/hy2.key || \
   occupied /opt/sing-box/hy2.crt || occupied /etc/systemd/system/sing-box.service || \
   occupied /run/systemd/system/sing-box.service || occupied /lib/systemd/system/sing-box.service || \
   occupied /usr/lib/systemd/system/sing-box.service || \
   systemctl cat sing-box.service >/dev/null 2>&1 || pgrep -x sing-box >/dev/null 2>&1; then
  echo "[ERROR] 检测到已有 sing-box 服务或配置，停止安装以保护现有业务。" >&2
  exit 1
fi

if ! curl -fsS --proto '=https' --connect-timeout 10 --max-time 30 "{server_url}/join/{token}" >/dev/null; then
  echo "[ERROR] 无法验证主控 HTTPS 证书或入网凭据，请检查证书和链接。" >&2
  exit 1
fi

echo "==> [1/5] 检查系统环境与网络..."
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) SBOX_ARCH="amd64" ;;
  aarch64|arm64) SBOX_ARCH="arm64" ;;
  *) echo "[ERROR] 暂不支持架构: $ARCH" >&2; exit 1 ;;
esac

echo "==> [2/5] 准备 sing-box 原版二进制..."
BIN="/usr/local/bin/sing-box"
# VERIFIED BINARY DOWNLOAD BEGIN
SINGBOX_VERSION="1.14.4"
case "$SBOX_ARCH" in
  amd64) EXPECTED_SHA="699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968" ;;
  arm64) EXPECTED_SHA="436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26" ;;
esac
# An arbitrary pre-existing executable is not proof of the pinned release.
SBOX_TMP="$(mktemp -d)"
trap 'rm -rf "$SBOX_TMP"' EXIT
DL_URL="https://github.com/SagerNet/sing-box/releases/download/v${{SINGBOX_VERSION}}/sing-box-${{SINGBOX_VERSION}}-linux-${{SBOX_ARCH}}.tar.gz"
FOUND=0
for PREFIX in '' 'https://ghfast.top/' 'https://ghproxy.net/'; do
  if curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 8 --max-time 120 -o "$SBOX_TMP/archive.tar.gz" "${{PREFIX}}${{DL_URL}}"; then
    ACTUAL_SHA="$(sha256sum "$SBOX_TMP/archive.tar.gz" | awk '{{print $1}}')"
    if [ "$ACTUAL_SHA" = "$EXPECTED_SHA" ]; then
      FOUND=1
      break
    fi
  fi
  rm -f "$SBOX_TMP/archive.tar.gz"
done
if [ "$FOUND" != 1 ]; then
  echo "[ERROR] 无法获取通过固定摘要校验的 sing-box，未安装或启动服务。" >&2
  exit 1
fi
# Extract only the expected executable after authenticating the complete archive.
tar -xOf "$SBOX_TMP/archive.tar.gz" "sing-box-${{SINGBOX_VERSION}}-linux-${{SBOX_ARCH}}/sing-box" > "$SBOX_TMP/sing-box"
chmod 755 "$SBOX_TMP/sing-box"
"$SBOX_TMP/sing-box" version | grep -Fq "sing-box version $SINGBOX_VERSION"
if [ -L "$BIN" ] || {{ [ -e "$BIN" ] && ! cmp -s "$BIN" "$SBOX_TMP/sing-box"; }}; then
  echo "[ERROR] 已有不同的 sing-box 可执行文件，未覆盖；请先人工核对。" >&2
  exit 1
fi
[ -e "$BIN" ] || install -m 755 "$SBOX_TMP/sing-box" "$BIN"
# VERIFIED BINARY DOWNLOAD END

echo "==> [3/5] 本地物理生成 Reality / Hysteria 2 密钥对 (私钥物理不出机)..."
KP="$("$BIN" generate reality-keypair)"
PRIV_KEY="$(echo "$KP" | grep -i "PrivateKey" | awk '{{print $2}}')"
PUB_KEY="$(echo "$KP" | grep -i "PublicKey" | awk '{{print $2}}')"
UUID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || openssl rand -hex 16 | sed 's/\\(..\\)/\\1-/g; s/-$//')"
SID="$(openssl rand -hex 4 2>/dev/null || date +%s | md5sum | head -c 8)"
HY2_PW="$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 16)"
OBFS_PW="$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 16)"

PUBLIC_IP="$(curl -s4 --max-time 5 https://api.ipify.org || curl -s4 --max-time 5 https://icanhazip.com || true)"
if [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{{print $7}}' | head -1)"
fi

echo "==> [4/5] 生成本地 sing-box 配置与 systemd 服务..."
mkdir -p /opt/sing-box /var/log
{cert_step}

cat <<EOF > /opt/sing-box/config.json
{{
  "log": {{"level": "warn", "output": "/var/log/sing-box.log", "timestamp": true}},
  "inbounds": [
    {{
      "type": "vless",
      "tag": "vless-reality",
      "listen": "::",
      "listen_port": {listen_port},
      "users": [{{"uuid": "$UUID", "flow": "xtls-rprx-vision"}}],
      "tls": {{
        "enabled": true,
        "server_name": "www.apple.com",
        "reality": {{
          "enabled": true,
          "handshake": {{"server": "www.apple.com", "server_port": 443}},
          "private_key": "$PRIV_KEY",
          "short_id": ["$SID"]
        }}
      }}
    }}{hy2_inbound}
  ],
  "outbounds": {outbounds_json}{route_json}
}}
EOF
chmod 600 /opt/sing-box/config.json

"$BIN" check -c /opt/sing-box/config.json

cat <<EOF > /etc/systemd/system/sing-box.service
[Unit]
Description=sing-box service
After=network.target nss-lookup.target

[Service]
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_SYS_PTRACE CAP_DAC_READ_SEARCH
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
ExecStart=$BIN run -c /opt/sing-box/config.json
Restart=on-failure
RestartSec=3s
LimitNOFILE=infinity

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sing-box >/dev/null 2>&1
systemctl start sing-box
systemctl is-active --quiet sing-box

echo "==> [5/5] 向主控端登记入网凭据..."
PAYLOAD="$(cat <<EOF
{{
  "token": "{token}",
  "host": "$PUBLIC_IP",
  "port": {listen_port},
  "uuid": "$UUID",
  "pbk": "$PUB_KEY",
  "sid": "$SID",
  "sni": "www.apple.com",
  "role": "{role}",
  "type": "vless"{hy2_payload}
}}
EOF
)"

RESP="$(curl -fsS --proto '=https' --connect-timeout 10 --max-time 30 -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "{server_url}/join/register" 2>/dev/null || true)"

if echo "$RESP" | grep -q '"ok":\\s*true\\|"ok":true'; then
  echo "========================================================="
  echo "  [SUCCESS] 节点接入成功！"
  echo "  公网 IP: $PUBLIC_IP"
  echo "  监听端口: {listen_port}"
  echo "  服务已启动，主控面板将显示待验证状态。"
  echo "========================================================="
else
  echo "[ERROR] 注册回传失败；本机服务已启动但尚未纳管，请检查主控连接和证书后人工处理。: $RESP" >&2
  exit 1
fi
"""
