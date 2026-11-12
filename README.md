# 🚀 Evergreen · OwnLine (常青·自连)

> **“不用到处找东西，12 刀配美国家宽，一个私有地址多端同步。”**  
> 个人专属私有出海专线自动化装配中枢。资产 100% 自有，不卖流量，非商业机场。

[![Release: v0.5.0](https://img.shields.io/badge/Release-v0.5.0-blue.svg)](https://github.com/AdgaiWalker/VPN-OwnLine/releases/tag/v0.5.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Core: sing--box](https://img.shields.io/badge/Core-sing--box%201.11+-orange.svg)](https://github.com/SagerNet/sing-box)
[![Gateway: Caddy](https://img.shields.io/badge/Gateway-Caddy%202.10-cyan.svg)](https://github.com/caddyserver/caddy)
[![Tests: 582 Passed](https://img.shields.io/badge/Tests-582%20Passed%20(100%25)-success.svg)]()

---

## ⚡ 实现原理与拓扑

```mermaid
flowchart TD
    A["自备云服务器 (Ubuntu / Debian)"] -->|"一行命令全自动装配"| B["专属独立控制台 URL (8443)"]
    B -->|"扫码 / 0.1 秒深链接唤起"| C["手机 / 电脑客户端 (小火箭 / FlClash)"]
    C -->|"原生独立 IP / 美国家宽"| D["目标外网 (Google / Claude / OpenAI)"]
```

* **纯净开源底座**：直接校验拉取 [sing-box](https://github.com/SagerNet/sing-box) 与 [Caddy](https://github.com/caddyserver/caddy) 官方 Release 原生二进制，默认 VLESS Reality 伪装（抗 DPI），支持 Hysteria 2。
* **单机完全自治**：零遥测、零数据回传。哪怕本 GitHub 仓库被删除，你的独立服务器依然不受任何影响，永远独立运转。
* **凭据物理不出机**：管理密码 bcrypt 哈希存储，所有节点配置与私钥仅保存在你自己服务器的 `/opt/web-data`，物理上杜绝泄露。

---

## 📋 准备清单与预估成本

在开始前，你只需准备以下原材料（费用由云厂商直接收取，丰俭由人）：

1. **一台云服务器 (必选)**：
   * **0 元 / 月** ➔ [甲骨文云 Oracle](https://www.oracle.com/cloud/free/)（Always Free 永久免费）
   * **约 7 元 / 月** ➔ [RackNerd](https://www.racknerd.com/)（年付促销 VPS）
   * **约 24 元 / 月** ➔ [腾讯云轻量](https://cloud.tencent.com/product/lighthouse)（微信 / 支付宝直付，省心推荐）
2. **一个客户端工具 (必选)**：
   * **iOS / iPadOS (推荐)**：[Shadowrocket (小火箭)](https://apps.apple.com/app/shadowrocket/id932747118)（控制台内嵌免外币美区账号通道，一键深链接写入）
   * **Mac / Windows / Android (推荐)**：[FlClash](https://github.com/chen08209/FlClash)（控制台提供免翻直链，一键导入）
   * **桌面进阶**：[Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)（规则分流与策略组）
3. **真实美国家宽 (可选 · 防封号顶配)**：
   * **+7 元 / 月** ➔ [Webshare](https://www.webshare.io/)（$12/年静态 ISP 原生住宅 IP，彻底规避 OpenAI / Claude 封号）

---

## 🚀 极速起步

材料就绪后，选择以下任意一种方式完成部署：

### 方式 1：自备服务器终端直接运行
登录你的服务器（Ubuntu 22.04 / Debian 12），粘贴并回车：
```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```
> 终端将直接输出专属管理地址（`https://服务器IP:8443/`）与初始管理员强密码。浏览器打开，按提示扫码或点击一键导入。

### 方式 2：交给本地 AI Agent 全自动执行
在 **Cursor / Claude Code / Antigravity / Windsurf** 中，将此指令连同服务器信息发给 Agent：
```text
克隆 https://github.com/AdgaiWalker/VPN-OwnLine.git，通过 SSH 连接我的服务器 [IP:端口:密码/私钥]，完成全自动装配并返回管理地址与初始凭据。
```

---

## 🧱 开源基石致敬

本项目建立在以下卓越的开源技术之上：
* [sing-box](https://github.com/SagerNet/sing-box) - 下一代通用代理核心引擎
* [Caddy](https://github.com/caddyserver/caddy) - 现代化自动证书管理与反向代理网关
* [Shadowrocket](https://apps.apple.com/app/shadowrocket/id932747118) / [FlClash](https://github.com/chen08209/FlClash) / [Clash Meta](https://github.com/MetaCubeX/mihomo) - 客户端标准生态

---

## ⚖️ 免责声明

本项目为开源私有网络管理与自动化部署工具，仅供个人合规网络管理与技术研究。使用者自备服务器并遵守当地法律法规。本项目不提供、不托管、不中转任何网络代理服务，不对任何使用者行为承担连带法律责任。
