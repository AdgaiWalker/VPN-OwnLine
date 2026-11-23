#!/usr/bin/env bash
# Cloudflare origin isolation for management port (default 8443/tcp).
# Only manages dedicated OWNLINE-ORIGIN-<port> chain and matching INPUT jump rule.
# Never modifies SSH (22/tcp), proxy (443/tcp,udp), or cloud firewall chains.

set -euo pipefail

ACTION=""
PORT="8443"
ALLOW_FALLBACK=0

usage() {
  cat <<'EOF'
Usage: cf_origin_lock.sh (--enable | --disable | --status) [--port 8443] [--fallback]
EOF
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --enable)   ACTION="enable"; shift ;;
    --disable)  ACTION="disable"; shift ;;
    --status)   ACTION="status"; shift ;;
    --fallback) ALLOW_FALLBACK=1; shift ;;
    --port)
      [ $# -ge 2 ] || die "--port requires a value"
      PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

[ -n "$ACTION" ] || { usage >&2; exit 2; }
[[ "$PORT" =~ ^[0-9]{1,5}$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "Invalid port: $PORT"
if [ "$PORT" -eq 22 ] || [ "$PORT" -eq 443 ]; then
  die "Refusing to modify protected port $PORT"
fi

CHAIN="OWNLINE-ORIGIN-${PORT}"

FALLBACK_V4=(
  "173.245.48.0/20"
  "103.21.244.0/22"
  "103.22.200.0/22"
  "103.31.4.0/22"
  "141.101.64.0/18"
  "108.162.192.0/18"
  "190.93.240.0/20"
  "188.114.96.0/20"
  "197.234.240.0/22"
  "198.41.128.0/17"
  "162.158.0.0/15"
  "104.16.0.0/13"
  "104.24.0.0/14"
  "172.64.0.0/13"
  "131.0.72.0/22"
)

FALLBACK_V6=(
  "2400:cb00::/32"
  "2606:4700::/32"
  "2803:f800::/32"
  "2405:b500::/32"
  "2405:8100::/32"
  "2a06:98c0::/29"
  "2c0f:f248::/32"
)

fetch_cidrs() {
  local url="$1" kind="$2" raw line
  V4_FETCHED=()
  V6_FETCHED=()
  raw=$(curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 6 --max-time 15 "$url" | tr -d '\r') || return 1
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    if [ "$kind" = "v4" ]; then
      [[ "$line" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]] || return 1
      V4_FETCHED+=("$line")
    else
      [[ "$line" =~ ^[0-9a-fA-F:]+/[0-9]{1,3}$ ]] || return 1
      V6_FETCHED+=("$line")
    fi
  done <<EOF
$raw
EOF
  if [ "$kind" = "v4" ]; then
    [ "${#V4_FETCHED[@]}" -ge 10 ] || return 1
  else
    [ "${#V6_FETCHED[@]}" -ge 5 ] || return 1
  fi
}

apply_chain_v4() {
  local tool="iptables -w" cidr
  $tool -N "$CHAIN" 2>/dev/null || $tool -F "$CHAIN"
  $tool -A "$CHAIN" -i lo -j RETURN
  $tool -A "$CHAIN" -s 127.0.0.0/8 -j RETURN
  $tool -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  for cidr in "${V4_CIDRS[@]+"${V4_CIDRS[@]}"}"; do
    $tool -A "$CHAIN" -s "$cidr" -j RETURN
  done
  $tool -A "$CHAIN" -j DROP
  while $tool -D INPUT -p tcp --dport "$PORT" -j "$CHAIN" 2>/dev/null; do :; done
  $tool -I INPUT 1 -p tcp --dport "$PORT" -j "$CHAIN"
}

apply_chain_v6() {
  command -v ip6tables >/dev/null 2>&1 || return 0
  local tool="ip6tables -w" cidr
  $tool -N "$CHAIN" 2>/dev/null || $tool -F "$CHAIN"
  $tool -A "$CHAIN" -i lo -j RETURN
  $tool -A "$CHAIN" -s ::1/128 -j RETURN
  $tool -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  for cidr in "${V6_CIDRS[@]+"${V6_CIDRS[@]}"}"; do
    $tool -A "$CHAIN" -s "$cidr" -j RETURN
  done
  $tool -A "$CHAIN" -j DROP
  while $tool -D INPUT -p tcp --dport "$PORT" -j "$CHAIN" 2>/dev/null; do :; done
  $tool -I INPUT 1 -p tcp --dport "$PORT" -j "$CHAIN"
}

disable_chain() {
  local bin="$1"
  command -v "$bin" >/dev/null 2>&1 || return 0
  local tool="$bin -w"
  while $tool -D INPUT -p tcp --dport "$PORT" -j "$CHAIN" 2>/dev/null; do :; done
  $tool -F "$CHAIN" 2>/dev/null || true
  $tool -X "$CHAIN" 2>/dev/null || true
}

status_chain() {
  local bin="$1" label="$2"
  command -v "$bin" >/dev/null 2>&1 || { echo "=== ${label}: unavailable ==="; return 0; }
  local tool="$bin -w"
  echo "=== ${label} INPUT rules for ${PORT}/tcp ==="
  $tool -S INPUT | grep -E "(${CHAIN}|dport ${PORT})" || echo "(no INPUT jump rule)"
  echo "=== ${label} chain ${CHAIN} ==="
  if ! $tool -L "$CHAIN" -n -v 2>/dev/null; then
    echo "(chain not present)"
  fi
}

case "$ACTION" in
  enable)
    [ "$(id -u)" -eq 0 ] || die "Root privilege required for --enable"
    command -v iptables >/dev/null 2>&1 || die "iptables is required"
    V4_CIDRS=()
    V6_CIDRS=()
    if fetch_cidrs "https://www.cloudflare.com/ips-v4" "v4"; then
      V4_CIDRS=("${V4_FETCHED[@]}")
    elif [ "$ALLOW_FALLBACK" = 1 ]; then
      echo "[WARN] Failed to fetch live Cloudflare IPv4 CIDRs, using built-in fallback list" >&2
      V4_CIDRS=("${FALLBACK_V4[@]}")
    else
      die "Failed to fetch valid Cloudflare IPv4 CIDRs (pass --fallback to allow built-in list)"
    fi

    if fetch_cidrs "https://www.cloudflare.com/ips-v6" "v6"; then
      V6_CIDRS=("${V6_FETCHED[@]}")
    elif [ "$ALLOW_FALLBACK" = 1 ]; then
      echo "[WARN] Failed to fetch live Cloudflare IPv6 CIDRs, using built-in fallback list" >&2
      V6_CIDRS=("${FALLBACK_V6[@]}")
    else
      die "Failed to fetch valid Cloudflare IPv6 CIDRs (pass --fallback to allow built-in list)"
    fi

    apply_chain_v4
    apply_chain_v6
    echo "Enabled Cloudflare origin isolation on ${PORT}/tcp (${#V4_CIDRS[@]} IPv4, ${#V6_CIDRS[@]} IPv6 CIDRs)"
    ;;
  disable)
    [ "$(id -u)" -eq 0 ] || die "Root privilege required for --disable"
    disable_chain iptables
    disable_chain ip6tables
    echo "Disabled Cloudflare origin isolation on ${PORT}/tcp"
    ;;
  status)
    status_chain iptables "IPv4"
    status_chain ip6tables "IPv6"
    ;;
esac
