# v0.2.0

第三个正式版本。核心是**极简稳定自举**、**原生内置订阅**与**双协议自动化**。

> 从 `v0.1.1` 升级的机器，先看文末「升级指南」——无需重新导入现有客户端。

## 这一版改了什么

### 1. 原生内置订阅（彻底删除 subconverter）
- 历史上的多次故障源自 `subconverter-ng` 偶发崩溃与 Caddy 正则重写竞争。
- 现在由 `admin.py` 原生处理订阅路由（`/s/<token>` 与 `/s/<token>/clash`）：
  - 智能分发：Clash / Mihomo / Stash / Verge 客户端自动返回标准 Clash YAML 配置；Shadowrocket / v2rayN 返回 Base64 链接列表。
  - 彻底停用并下线 `subconverter.service`，主控常驻后台服务从 4 个缩减为 2 个（Caddy + admin.py）。

### 2. Token 与设置解耦（Caddy 纯静态化）
- 订阅 Token 与面板域名统一收敛至 `/opt/web-data/settings.json`。
- Caddyfile 成为永久静态反向代理（所有 `/s/*` 由 admin.py 鉴权），不再使用 sed 或正则改写 Caddyfile。
- 换锁轮换（`/api/rotate`）秒级完成，仅写 `settings.json` 并刷新二维码，零 Caddy reload、零下线风险。
- 前端面板 `web/index.html` 动态读取 `/api/settings`，彻底告别写死 Token。

### 3. 一键远程自举与免域名正式证书（M8 / M9）
- 新增 `deploy/bootstrap.sh` 一键自举脚本：
  ```bash
  curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/ladder-web-panel/main/deploy/bootstrap.sh | sudo bash
  ```
- 免域名支持：自动基于 `<ip>.sslip.io` 通过 Caddy 申请官方 Let's Encrypt 正式证书，免去购买域名的资金与时间成本。
- 全自动初始化：一键完成系统环境预检、sing-box 锁定版本安装与 SHA256 校验、本地出口双节点初始化、系统 BBR 拥塞控制开启、防火墙放行、自检与终端二维码渲染。

### 4. VLESS Reality + Hysteria2 (QUIC) 双协议全面自动化（M10 / M11 / M12）
- 出口节点自动生成 Reality (443/tcp) 与 Hysteria2 (443/udp) 双入站并开启 BBR。
- 腾讯云提供商适配器支持 `proto="TCP"|"UDP"` 自动放行。
- `verify.py` 支持 Hysteria2 真机正向与反向验收，杜绝假绿灯。

### 5. 双视角探活与防抖告警（M3 / M4）
- `probe.py` 借道国内中转节点实现端到端真实国内探活（`cn_ok` 与 `cn_ms`），精准识别被墙情况。
- 新增 `alert.py`：连续 2 次探测失败触发防抖告警、故障自愈发送恢复通知、每日探针心跳报告。

### 6. 异地自动冷备（M5）
- 新增 `server/backup_remote.sh` 与系统定时器，每日零成本异地打包备份至第二台机器（保留 7 天）。

## 验收

```bash
bash scripts/test.sh                                  # 6 套 151 项全过
python3 scripts/drift.py walker-sv walker-bj          # 硅谷与北京两台均 100% 一致
./scripts/verify.sh https://<域名>:8443 admin <密码> <token>  # 端到端全通
```

## 升级指南（从 v0.1.1）

本升级为平滑升级，**现有客户端无需重新扫码或导入**：

```bash
# 1. 拉取最新代码
cd /opt/ladder && sudo git fetch --tags && sudo git checkout v0.2.0

# 2. 写入现有 settings.json
TOKEN=$(grep -oE '/s/[a-f0-9]{6,}' /etc/caddy/Caddyfile | head -1 | cut -d/ -f2)
sudo bash -c "cat > /opt/web-data/settings.json << EOF
{
  \"sub_token\": \"$TOKEN\",
  \"domain\": \"$(hostname -f)\",
  \"sub_port\": 8443,
  \"sub_backend\": \"builtin\"
}
EOF"
sudo chmod 600 /opt/web-data/settings.json

# 3. 停用 subconverter 并更新 Caddyfile
sudo systemctl stop subconverter 2>/dev/null || true
sudo systemctl disable subconverter 2>/dev/null || true
# 将 Caddyfile 中的 /s/<token>* 改为 /s/* 直代 8099
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy

# 4. 同步代码并重启主控
sudo cp -r server/providers server/nodekit /opt/web/
sudo cp server/*.py server/*.sh /opt/web/
sudo cp web/index.html /opt/web/
sudo systemctl restart admin
```
