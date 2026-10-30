#!/usr/bin/env bash
# 3 分钟异地灾难一键自举重建脚本 (restore_master.sh)
#
# 用途：
#   当主控节点彻底损毁/丢失时，新开任意一台空白 Ubuntu 22.04/24.04 VPS，
#   单行命令从北京备份仓库拉取最新备份包并自动装配满血复活。
#
# 用法：
#   bash restore_master.sh --source=49.233.210.101 --user=backup --key=/root/.ssh/id_ed25519
#
set -euo pipefail

SOURCE_HOST="${1:-49.233.210.101}"
BACKUP_USER="${2:-backup}"
SSH_KEY="${3:-/root/.ssh/id_ed25519}"
DEST_DATA="/opt/web-data"
DEST_WEB="/opt/web"

echo "============================================================"
echo "🚑 启动梯子主控异地灾难恢复引擎 (Restore Master)"
echo "============================================================"
echo "备份源服务器 : ${SOURCE_HOST}"
echo "恢复数据目录 : ${DEST_DATA}"
echo "恢复程序目录 : ${DEST_WEB}"
echo "------------------------------------------------------------"

# 1. 确保基础目录与权限
mkdir -p "${DEST_DATA}" "${DEST_WEB}" "/etc/caddy" "/tmp/ladder_restore"

# 2. 从异地拉取最新备份
echo "📦 [1/5] 从异地机器拉取最新备份包..."
if [ -f "/tmp/ladder_backup.tar.gz" ]; then
    echo "  发现本地离线备份包，直接使用 /tmp/ladder_backup.tar.gz"
else
    SSH_OPT="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
    [ -f "${SSH_KEY}" ] && SSH_OPT="${SSH_OPT} -i ${SSH_KEY}"
    
    LATEST_REMOTE="$(ssh ${SSH_OPT} "${BACKUP_USER}@${SOURCE_HOST}" "ls -t /home/backup/backups/*.tar.gz 2>/dev/null | head -1" || true)"
    if [ -z "${LATEST_REMOTE}" ]; then
        echo "❌ 未能在 ${SOURCE_HOST} 找到任何备份包！"
        exit 1
    fi
    echo "  找到最新备份: ${LATEST_REMOTE}"
    scp ${SSH_OPT} "${BACKUP_USER}@${SOURCE_HOST}:${LATEST_REMOTE}" /tmp/ladder_backup.tar.gz
fi

# 3. 解包恢复数据与配置
echo "📂 [2/5] 解压并恢复数据文件..."
tar -xzf /tmp/ladder_backup.tar.gz -C /tmp/ladder_restore/
if [ -d "/tmp/ladder_restore/web-data" ]; then
    cp -r /tmp/ladder_restore/web-data/* "${DEST_DATA}/"
fi
if [ -d "/tmp/ladder_restore/web" ]; then
    cp -r /tmp/ladder_restore/web/* "${DEST_WEB}/"
fi
if [ -f "/tmp/ladder_restore/Caddyfile" ]; then
    cp /tmp/ladder_restore/Caddyfile /etc/caddy/Caddyfile
fi
chmod 700 "${DEST_DATA}"
echo "  数据文件还原完成。"

# 4. 依赖环境检查与配置安装
echo "⚙️ [3/5] 检查与安装 Caddy / sing-box / Python 环境..."
command -v python3 >/dev/null || (apt-get update && apt-get install -y python3)
command -v caddy >/dev/null || (apt-get install -y debian-keyring debian-archive-keyring apt-transport-https && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg && \
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list && \
    apt-get update && apt-get install -y caddy)

# 5. 配置并启动 systemd 服务
echo "🚀 [4/5] 注册并启动 admin 与 caddy 服务..."
cat << 'EOF' > /etc/systemd/system/admin.service
[Unit]
Description=Rotate endpoint for ladder page
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/web
ExecStart=/usr/bin/python3 /opt/web/admin.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now admin
systemctl enable --now caddy
systemctl restart admin caddy

# 6. 自检验证
echo "🔍 [5/5] 执行健康自检..."
sleep 2
if systemctl is-active --quiet admin && systemctl is-active --quiet caddy; then
    echo "============================================================"
    echo "✅ 恭喜！梯子主控已在 3 分钟内成功灾后重建并拉起！"
    echo "   admin 服务 : active"
    echo "   caddy 服务 : active"
    echo "============================================================"
    exit 0
else
    echo "❌ 服务启动存在异常，请检查 journalctl -u admin 或 caddy"
    exit 1
fi
