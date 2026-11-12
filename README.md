# 🚀 Evergreen · OwnLine (常青·自连)

> **“不用到处找东西，12 刀配一个真家宽，一个私有地址多端同步。”**  
> 个人专属私有出海专线自动化装配中枢。资产 100% 自有，不卖流量，非商业机场。

[![Release: v0.5.0](https://img.shields.io/badge/Release-v0.5.0-blue.svg)](https://github.com/AdgaiWalker/VPN-OwnLine/releases/tag/v0.5.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Core: sing--box](https://img.shields.io/badge/Core-sing--box%201.11+-orange.svg)](https://github.com/SagerNet/sing-box)
[![Gateway: Caddy](https://img.shields.io/badge/Gateway-Caddy%202.10-cyan.svg)](https://github.com/caddyserver/caddy)
[![Tests: 582 Passed](https://img.shields.io/badge/Tests-582%20Passed%20(100%25)-success.svg)]()

---

## ⚡ 运行流程

```text
[ 自备云服务器 ] ────( 一行命令全自动装配 )────► [ 生成专属独立控制台 URL ]
                                                      │
                                                      ▼ (0.1秒深链接唤起)
                                             [ 手机 / 电脑一键直连 ]
```

---

## 📱 推荐客户端

控制台内置免外币美区账号通道与免翻下载直链，导入即可使用：

* **iOS / iPadOS (推荐)**：[Shadowrocket (小火箭)](https://apps.apple.com/app/shadowrocket/id932747118)
* **Mac / Win / 安卓 (推荐)**：[FlClash](https://github.com/chen08209/FlClash)
* **桌面进阶**：[Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)

---

## 💰 预估月费

费用由云厂商直接收取，丰俭由人：

* **0 元 / 月** ➔ [甲骨文云 Oracle](https://www.oracle.com/cloud/free/)（Always Free 永久免费）
* **约 7 元 / 月** ➔ [RackNerd](https://www.racknerd.com/)（年付促销型 VPS）
* **约 24 元 / 月** ➔ [腾讯云轻量](https://cloud.tencent.com/product/lighthouse)（微信 / 支付宝直付，省心推荐）
* **+7 元 / 月 (可选)** ➔ [Webshare](https://www.webshare.io/)（$12/年美国家宽 IP，彻底规避 AI 封号）

---

## 🛡️ 实现原理与数据边界（为什么可信？）

本项目恪守“零信任、无中心、全透明”原则，所有运行链路均可在你的服务器上完整审计：

```text
[ 你的手机 / 电脑 ]
        │
        │ (VLESS Reality: 外观与访问 Apple 物理完全一致，抗 DPI 探测)
        ▼
[ 你的自备云服务器 ]
  ├── 核心代理：sing-box 官方原版二进制（零魔改，无私货）
  ├── 安全网关：Caddy 官方反代（自动化申请与轮换合法 Let's Encrypt 证书）
  └── 控制面板：纯 Python 3 原生轻量服务（仅监听本机环回端口）
        │
        ├──(直连出口)────────────► [ 目标外网：Google / GitHub ]
        └──(可选: 挂载 Webshare 家宽)─► [ 严格风控平台：OpenAI / Claude / 跨境网银 ]
```

* **纯净开源底座**：直接拉取 [SagerNet/sing-box](https://github.com/SagerNet/sing-box) 与 [Caddy](https://github.com/caddyserver/caddy) 官方 Release 二进制，控制面仅依赖 Python 3 标准库，无任何第三方黑盒组件。
* **单机完全自治**：代码不包含任何遥测（Telemetry）或数据上报。装配完成后，**哪怕本 GitHub 仓库被删除，你的独立服务器依然不受任何影响，永远独立运转**。
* **凭据物理不出机**：管理员密码采用 `bcrypt` 单向哈希存储，所有节点配置与密钥物理隔离在 `/opt/web-data`，严禁且物理上不可能跨机回传。

---

## ⚖️ 事实对比

| 维度 | 商业公共机场 | 自己搜教程搭建 | Evergreen · OwnLine |
| :--- | :--- | :--- | :--- |
| **IP 属性** | 万人共用，易被封号 | 独享机房 IP，仍有标记 | **独享原生 IP · 可选真美国家宽** |
| **数据安全** | 流量经由他人中转 | 私有，但维护繁琐 | **100% 自有资产，零日志，防嗅探** |
| **装配耗时** | 即买即用，但常被墙 | 需 2~4 小时排障配置 | **单行命令 / 本地 Agent，2 分钟交付** |
| **多端维护** | 节点更新需手动刷新 | 每次变更逐台重新配置 | **单一私有管理地址，全端自动同步** |

---

## 🚀 极速起步

### 方式 1：自备服务器终端直接运行
登录目标 Ubuntu 22.04 / Debian 12 机器，粘贴并运行：
```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```
> 终端将直接输出专属管理地址（`https://服务器IP:8443/`）与初始管理员强密码。

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
* [Shadowrocket](https://apps.apple.com/app/shadowrocket/id932747118) / [FlClash](https://github.com/chen08209/FlClash) / [Clash Meta (mihomo)](https://github.com/MetaCubeX/mihomo) - 客户端标准生态

---

## ⚖️ 免责声明

本项目为开源私有云网络管理与自动化部署工具，仅供个人合规网络管理、学术科研与私有云运维技术研究。使用者自备服务器并遵守当地法律法规。本项目不提供、不托管、不中转任何网络代理服务，不对任何使用者行为承担连带法律责任。

