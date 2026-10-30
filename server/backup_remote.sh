#!/bin/bash
# 异地冷备：每天将硅谷主控配置打包推送到国内北京节点（/opt/ladder-backup/）
# 零成本异地容灾，主控整机销毁也能从北京机器瞬间拉取全套配置重建
set -euo pipefail

DATA="${LADDER_DATA:-/opt/web-data}"
NODES="$DATA/nodes.json"
STAMP=$(date +%Y%m%d)
TMP_TAR="/tmp/ladder-backup-$STAMP.tar.gz"
KH="/opt/sing-box/known_hosts"
KEY="/root/.ssh/node_ctl"

# 从 nodes.json 自动寻找中转节点作为异地备份机
RELAY_HOST=$(python3 -c 'import json,sys; nodes=json.load(open("'"$NODES"'")); r=next((n for n in nodes if n.get("role")=="relay" and n.get("host")), None); print(r["host"] if r else "")')
RELAY_USER=$(python3 -c 'import json,sys; nodes=json.load(open("'"$NODES"'")); r=next((n for n in nodes if n.get("role")=="relay" and n.get("host")), None); print(r.get("ssh_user") or "root" if r else "root")')

if [ -z "$RELAY_HOST" ]; then
  echo "未发现中转节点，跳过异地推送"
  exit 0
fi

echo "==> 打包主控关键数据"
tar -czf "$TMP_TAR" \
  -C / \
  opt/web-data \
  opt/sing-box/config.json \
  opt/sing-box/hy2.crt \
  opt/sing-box/hy2.key \
  etc/caddy/Caddyfile 2>/dev/null || true
chmod 600 "$TMP_TAR"

echo "==> 推送备份到 $RELAY_USER@$RELAY_HOST:/opt/ladder-backup/$STAMP.tar.gz"
SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KH" -o ConnectTimeout=15)
scp "${SSH_OPTS[@]}" "$TMP_TAR" "$RELAY_USER@$RELAY_HOST:/opt/ladder-backup/$STAMP.tar.gz"

echo "==> 清理 7 天前旧备份"
ssh "${SSH_OPTS[@]}" "$RELAY_USER@$RELAY_HOST" "find /opt/ladder-backup -name '*.tar.gz' -mtime +7 -delete 2>/dev/null || true; ls -lh /opt/ladder-backup"

rm -f "$TMP_TAR"
echo "==> 异地备份完成: $STAMP.tar.gz"
