# Evergreen · OwnLine

不用自己找东西，12 刀配美国家宽，一个私有地址多端同步。  
自备服务器，2 分钟全自动装配出海节点与 Web 控制台。不卖流量，非机场，资产自有。

[![Release: v0.5.0](https://img.shields.io/badge/Release-v0.5.0-blue.svg)](https://github.com/AdgaiWalker/VPN-OwnLine/releases/tag/v0.5.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Core: sing--box](https://img.shields.io/badge/Core-sing--box%201.11+-orange.svg)](https://github.com/SagerNet/sing-box)
[![Gateway: Caddy](https://img.shields.io/badge/Gateway-Caddy%202.10-cyan.svg)](https://github.com/caddyserver/caddy)
[![Tests: 582 Passed](https://img.shields.io/badge/Tests-582%20Passed%20(100%25)-success.svg)]()

---

```text
[ 自备云服务器 ] ────( 一行命令全自动装配 )────► [ 生成专属独立控制台 URL ]
                                                      │
                                                      ▼ (0.1秒深链接唤起)
                                             [ 手机 / 电脑一键直连 ]
```

---

## 极速起步

### 方式 1：自备服务器运行（Ubuntu 22.04 / Debian 12）
```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```
> 终端输出专属管理地址（`https://服务器IP:8443/`）与随机强密码。

### 方式 2：发给本地 Agent（Cursor / Claude Code / Antigravity）
```text
克隆 https://github.com/AdgaiWalker/VPN-OwnLine.git，通过 SSH 连接我的服务器 [IP:端口:密码/私钥]，完成全自动装配并返回管理地址与初始凭据。
```

---

## 预估成本

* **0 元 / 月**：[甲骨文云 Oracle](https://www.oracle.com/cloud/free/)（Always Free 永久免费）
* **约 7 元 / 月**：[RackNerd](https://www.racknerd.com/)（年付促销 VPS）
* **约 24 元 / 月**：[腾讯云轻量](https://cloud.tencent.com/product/lighthouse)（支付宝/微信直付）
* **+7 元 / 月 (可选)**：[Webshare](https://www.webshare.io/)（$12/年静态美国家宽，防 OpenAI/Claude 封号）

---

## 客户端支持

* **iOS / iPadOS**：[Shadowrocket (小火箭)](https://apps.apple.com/app/shadowrocket/id932747118)（控制台内嵌免外币美区账号通道，一键深链接写入）
* **Mac / Windows / Android**：[FlClash](https://github.com/chen08209/FlClash)（控制台提供免翻直链，一键导入）
* **桌面进阶**：[Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)（规则分流与策略组）

---

## 实现原理与数据边界

```text
[ 客户端 ] ──(VLESS Reality / HY2)──► [ 云服务器 (sing-box + Caddy) ] ──(可选 Webshare 家宽)──► [ 目标网站 ]
                                              │
                                   [ 控制台: 8443 (仅管理通道) ]
```

* **代理内核**：[sing-box](https://github.com/SagerNet/sing-box) 官方二进制，默认 VLESS Reality 伪装（抗 DPI），支持 Hysteria 2。
* **安全网关**：[Caddy](https://github.com/caddyserver/caddy) 官方二进制，自动化申请与轮换 Let's Encrypt TLS 证书。
* **控制面**：Python 3 标准库单文件轻量服务，仅监听本地环回端口。
* **数据边界**：零遥测、零数据回传。密码 bcrypt 哈希存储，节点配置与密钥仅保存在本机 `/opt/web-data`。

---

## 开源基石

* [sing-box](https://github.com/SagerNet/sing-box) · [Caddy](https://github.com/caddyserver/caddy) · [Shadowrocket](https://apps.apple.com/app/shadowrocket/id932747118) · [FlClash](https://github.com/chen08209/FlClash) · [Clash Meta](https://github.com/MetaCubeX/mihomo)

---

## 免责声明

本项目仅供个人私有网络管理与技术研究，使用者自备服务器并遵守当地法律法规。本项目不提供、不托管、不中转任何网络代理服务。
