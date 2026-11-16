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
    expires_in: int = DEFAULT_TTL,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """生成一个新的高熵一次性入网 Token。"""
    now = time.time() if now_ts is None else float(now_ts)
    token = secrets.token_hex(32)
    role_norm = "relay" if str(role).lower() == "relay" else "exit"
    record = {
        "token": token,
        "name": (name or "").strip(),
        "role": role_norm,
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


def generate_install_script(token: str, server_url: str, role: str = "exit") -> str:
    """生成供客户端 curl | bash 执行的原生轻量反向注册脚本。
    
    全程在远端本地安全生成密钥对与自签证书，通过单向 HTTPS POST 回传元数据。
    主控服务器与客户端均无需暴露或存储 root 密码。
    """
    server_url = (server_url or "").rstrip("/")
    return f"""#!/usr/bin/env bash
# Evergreen · OwnLine 一键免密反向自举脚本
# Token: {token}
set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "❌ 错误: 本脚本需要 root 权限，请使用 sudo 或切换至 root 执行。" >&2
  exit 1
fi

echo "==> [1/5] 检查系统环境与网络..."
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) SBOX_ARCH="amd64" ;;
  aarch64|arm64) SBOX_ARCH="arm64" ;;
  *) echo "❌ 暂不支持架构: $ARCH" >&2; exit 1 ;;
esac

echo "==> [2/5] 准备 sing-box 原版二进制..."
BIN="/usr/local/bin/sing-box"
if [ ! -x "$BIN" ]; then
  mkdir -p /tmp/sbox-install
  cd /tmp/sbox-install
  DL_URL="https://github.com/SagerNet/sing-box/releases/download/v1.11.0/sing-box-1.11.0-linux-${{SBOX_ARCH}}.tar.gz"
  FOUND=0
  for PREFIX in '' 'https://ghfast.top/' 'https://ghproxy.net/'; do
    if curl -fsSL --connect-timeout 8 --max-time 120 "${{PREFIX}}${{DL_URL}}" | tar xz --strip-components=1; then
      FOUND=1
      break
    fi
  done
  if [ "$FOUND" -eq 1 ] && [ -f "./sing-box" ]; then
    install -m 755 ./sing-box "$BIN"
  else
    echo "⚠️ 官方源下载慢，尝试本地包或已有进程..."
  fi
  rm -rf /tmp/sbox-install
fi

if ! command -v "$BIN" >/dev/null 2>&1; then
  echo "❌ 无法安装 sing-box，终止！" >&2
  exit 1
fi

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
openssl req -x509 -nodes -newkey rsa:2048 -keyout /opt/sing-box/hy2.key -out /opt/sing-box/hy2.crt -days 3650 -subj "/CN=www.bing.com" 2>/dev/null || true

cat <<EOF > /opt/sing-box/config.json
{{
  "log": {{"level": "warn", "output": "/var/log/sing-box.log", "timestamp": true}},
  "inbounds": [
    {{
      "type": "vless",
      "tag": "vless-reality",
      "listen": "::",
      "listen_port": 443,
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
    }},
    {{
      "type": "hysteria2",
      "tag": "hy2",
      "listen": "::",
      "listen_port": 443,
      "users": [{{"password": "$HY2_PW"}}],
      "tls": {{
        "enabled": true,
        "server_name": "www.bing.com",
        "alpn": ["h3"],
        "certificate_path": "/opt/sing-box/hy2.crt",
        "key_path": "/opt/sing-box/hy2.key"
      }},
      "obfs": {{"type": "salamander", "password": "$OBFS_PW"}}
    }}
  ],
  "outbounds": [{{"type": "direct", "tag": "direct"}}]
}}
EOF

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
systemctl enable sing-box >/dev/null 2>&1 || true
systemctl restart sing-box || true

echo "==> [5/5] 向主控端登记入网凭据..."
PAYLOAD="$(cat <<EOF
{{
  "token": "{token}",
  "host": "$PUBLIC_IP",
  "port": 443,
  "uuid": "$UUID",
  "pbk": "$PUB_KEY",
  "sid": "$SID",
  "sni": "www.apple.com",
  "role": "{role}",
  "type": "vless",
  "hy2_password": "$HY2_PW",
  "obfs_password": "$OBFS_PW"
}}
EOF
)"

RESP="$(curl -fsSL -k --connect-timeout 10 --max-time 30 -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "{server_url}/join/register" 2>/dev/null || curl -fsSL -k --connect-timeout 10 --max-time 30 -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "{server_url}/api/node/join" 2>/dev/null || true)"

if echo "$RESP" | grep -q '"ok":\\s*true\\|"ok":true'; then
  echo "========================================================="
  echo "  ✅ 节点接入成功！"
  echo "  公网 IP: $PUBLIC_IP"
  echo "  主控面板卡片已点亮，客户端刷新订阅即可使用。"
  echo "========================================================="
else
  echo "❌ 注册回传失败: $RESP" >&2
  exit 1
fi
"""
