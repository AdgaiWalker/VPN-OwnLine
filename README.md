# 🚀 Evergreen · OwnLine (常青·自连)

> **Own your private line. 一键装配属于你自己的独立高速出海专线。**  
> 告别公共合租与封号风险。自备任意云服务器，2 分钟全自动装配出海内核与专属管理控制台。

[![Release: v0.4.0](https://img.shields.io/badge/Release-v0.4.0-blue.svg)](https://github.com/AdgaiWalker/VPN-OwnLine/releases/tag/v0.4.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Core: sing--box](https://img.shields.io/badge/Core-sing--box%201.11+-orange.svg)](https://github.com/SagerNet/sing-box)
[![Gateway: Caddy](https://img.shields.io/badge/Gateway-Caddy%202.10-cyan.svg)](https://github.com/caddyserver/caddy)
[![Tests: 552 Passed](https://img.shields.io/badge/Tests-552%20Passed%20(100%25)-success.svg)]()

---

## ⚡ 30 秒了解它如何工作

OwnLine 不是商业机场，也不碰你的任何网络流量。它是一个**全自动去中心化装配流水线**：

1. **自备主机**：你在腾讯云/AWS等正规云厂商自备一台轻量服务器（每月约 20 余元，原生纯净独立 IP）；
2. **全自动装机**：只需在云终端执行一行命令，系统在 2 分钟内自动部署 `sing-box` 代理内核、配置 `Caddy` 安全网关，并**在你的服务器上生成一个专属的私有管理控制台 URL**；
3. **一键开箱即用**：手机扫码或点击一键唤醒小火箭（Shadowrocket）/ Clash，10 秒完成连通。

```
[ 自备云服务器 ] ────( 一行命令全自动装配 )────► [ 生成专属独立控制台 URL ]
                                                      │
                                                      ▼ (0.1秒深链接唤起)
                                             [ 手机 / 电脑一键直连起飞 ]
```

---

## 📋 准备清单

在开始前，你只需准备好以下三样东西：

1. **一台全新的 Linux 云服务器**（推荐 Ubuntu 22.04 或 Debian 12）：
   * 选型参考：腾讯云轻量（香港/新加坡/硅谷）、阿里云海外、搬瓦工等；
   * ⚠️ **开通防火墙**：在云厂商控制台的【防火墙/安全组】放行 **`80`、`443`、`8443`**（TCP/UDP）。
2. **一个客户端软件**：
   * iPhone / iPad：Shadowrocket（小火箭）
   * Windows / macOS / Android：Clash Verge 或 FLClash
3. **（可选进阶）**：
   * 国内服务器（用作中转跳板专线，晚高峰彻底拉直延迟）；
   * 原生静态住宅 IP（做跨境电商/登敏感 AI 账号防风控）。

---

## 🚀 极速装配（双轨模式）

### 轨道 A：自备主机一键直装（人类极简模式）

登录你的服务器网页终端（如腾讯云 Lighthouse 控制台自带的 WebShell），直接粘贴并回车执行：

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```

> **💡 全球智能测速与镜像自适应：**  
> 脚本会自动探测当前服务器网络质量。若在国内跳板机或海外直连缓慢，**全自动无感切入清华大学镜像源与 GitHub 加速节点**，彻底杜绝安装超时卡死。

安装完成后，终端将自动打印属于你的 **专属管理地址** 与 **初始随机强密码**：
```text
─────────────────────────────────────────────────────────────
安装成功！

  专属管理地址: https://你的服务器IP:8443/
  面板账号:   admin
  初始密码:   xxxxxxxxxxxxxxxxxxxx (一次性强随机密码)
─────────────────────────────────────────────────────────────
```

---

### 轨道 B：AI 协助全自动配置（智能体托管模式）

如果你希望通过腾讯云 API 让 Agent 自动发现你的主机并协助开机配置：

直接复制下方提示词，发送给你的 AI 助手（Claude / ChatGPT / Cursor 等）：

> **📋 点击复制 AI 辅助提示词：**
> ```text
> 请协助我在腾讯云控制台为本项目创建一个最小权限的 CAM 子账号（仅限轻量应用服务器只读/防火墙必要权限）。创建 API 密钥时请由我本人操作并自行保存，切勿在对话中输出 SecretId、SecretKey、密码或私钥。
> 官方项目地址：https://github.com/AdgaiWalker/VPN-OwnLine
> ```

获取专属子账号凭据后，直接在 OwnLine 面板点击 **【读取实例列表】**，即可全自动同步并管理你的主机资产。

---

## 📱 客户端连接与下载（开箱即用）

在浏览器打开你的管理地址并登录后，页面提供针对你设备的免配置直连通道：

| 客户端平台 | 软件从哪里来？ | 怎么连？ |
| :--- | :--- | :--- |
| **iPhone / iPad** | 国区 App Store 搜不到？面板内集成 **免外币共享美区 Apple ID 获取通道** 免费下载正版小火箭 | 点击网页上的 **【一键连接本机】**，自动唤醒小火箭写入配置，打开开关即连 |
| **Mac / Windows** | 提供开源纯净版 **FLClash / Clash Verge** 官方免翻镜像直链 | 点击 **【复制订阅链接】**，客户端内粘贴保存即可 |
| **Android** | 提供开源 **Clash Meta for Android** 纯净直链 | 扫描面板上的 **专属订阅二维码** 导入 |

---

## 🧩 底层核心积木（按需开启，丰俭由人）

平时保持极简，根据具体使用场景按需在面板点击开关：

* 🛡️ **VLESS Reality 真实伪装（默认标配）**：偷跑 Apple/Bing 真实证书，无特征码，抗阻断能力极强。
* ⚡ **Hysteria 2（HY2）极速引擎**：基于 UDP/QUIC。晚高峰国际骨干网丢包严重时一键开启，顶着丢包跑满物理带宽，4K 秒开。
* 🔀 **国内 BGP 专线中转（Relay）**：跨海延迟高？支持绑定国内服务器作为跳板机，内网级直达海外出口。
* 🏠 **ISP 住宅原生 IP 落地**：针对 ChatGPT/Claude、海外银行、跨境电商等严苛风控，一键伪装为真实美国家庭宽带。
* 🛑 **防超额流量熔断（Quota Guard）**：设置月度流量保护红线（默认达到 90% 自动断网），绝不产生云厂商天价扣费。
* 🔄 **安全弹射（Rotate Token）**：怀疑订阅泄露？一键销毁旧凭据，未经授权的设备瞬间全部断联。
* 🖥️ **macOS Sequoia 风格账户管理**：支持密码强度评估、防浏览器幽灵自动填充、密码显隐切换。

---

## 🛠️ 卡点速查与常见排障

1. **导入后提示“连接超时 / 无法访问网络”？**
   * 99% 是因为云厂商防火墙没放行。前往云控制台确认放行：`80/tcp`（证书验证）、`8443/tcp`（面板与订阅）、`443/tcp`（Reality 代理）、`443/udp`（HY2 极速代理）。
2. **忘记了 Web 管理面板密码？**
   * 登录服务器终端，执行一键交互式重置：
     ```bash
     sudo python3 /opt/web/reset_admin_password.py
     ```
3. **在微信内打开提示无法访问？**
   * 点击微信右上角 `···`，选择 **“在浏览器中打开”**，即可正常唤起小火箭或下载客户端。

---

## 🧱 开源基石致敬

本项目建立在以下卓越的开源技术之上：
* [sing-box](https://github.com/SagerNet/sing-box) - 下一代通用代理核心引擎
* [Caddy](https://github.com/caddyserver/caddy) - 现代化自动证书管理与反向代理网关
* [Shadowrocket](https://apps.apple.com/) / [Clash Meta (mihomo)](https://github.com/MetaCubeX/mihomo) - 客户端标准生态

---

## ⚖️ 免责声明

本项目为开源私有云网络管理与自动化部署工具，仅供个人合规网络管理、学术科研与私有云运维技术研究。使用者自备服务器并遵守当地法律法规。本项目不提供、不托管、不中转任何网络代理服务，不对任何使用者行为承担连带法律责任。
