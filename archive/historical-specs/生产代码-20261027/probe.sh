#!/bin/bash
set -u
chk() {
  local host=$1 port=$2 sni=$3 t0 t1 out ms
  t0=$(date +%s%N)
  out=$(echo | timeout 6 openssl s_client -connect "$host:$port" -servername "$sni" 2>&1)
  t1=$(date +%s%N)
  if grep -q CONNECTED <<< "$out"; then
    ms=$(( (t1 - t0) / 1000000 ))
    echo "true $ms"
  else
    echo "false 0"
  fi
}
read -r sg_ok sg_ms <<< "$(chk 43.163.4.104 8443 www.microsoft.com)"
read -r sv_ok sv_ms <<< "$(chk 43.153.56.137 443 www.apple.com)"
printf '{"sg":{"ok":%s,"ms":%s},"sv":{"ok":%s,"ms":%s},"ts":"%s"}\n' \
  "$sg_ok" "$sg_ms" "$sv_ok" "$sv_ms" "$(date -u +%FT%TZ)" > /tmp/status.$$.json
mv /tmp/status.$$.json /opt/web/status.json
