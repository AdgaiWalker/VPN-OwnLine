# 🚀 Evergreen · OwnLine (长青 · 个人专线)

> **帮小白轻松搭建安全、可控、便宜的专属 VPN 节点。**  
> 💡 **核心成本**：搭建普通节点每年仅需 **0 ~ 99 元**（服务器可完全白嫖），在此基础上只需再加 **85 元/年**（12 美元）挂载美国家宽 IP，即可升级为彻底防封的家庭住宅节点。  
> 资产 100% 自有，独享原生纯净 IP，非合租、非机场，不卖流量，2 分钟全自动装配，一个私有网页多端同步。

[![Release: v0.6.1](https://img.shields.io/badge/Release-v0.6.1-blue.svg)](https://github.com/AdgaiWalker/VPN-OwnLine/releases/tag/v0.6.1)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Core: sing--box](https://img.shields.io/badge/Core-sing--box%201.11+-orange.svg)](https://github.com/SagerNet/sing-box)
[![Gateway: Caddy](https://img.shields.io/badge/Gateway-Caddy%202.10-cyan.svg)](https://github.com/caddyserver/caddy)
[![Tests: 797 Passed](https://img.shields.io/badge/Tests-797%20Passed%20(100%25)-success.svg)]()
[![Delivery: Guarded](https://img.shields.io/badge/Delivery-Guarded-blue.svg)](research/06-trusted-delivery-plan.md)
[![Production: Verified](https://img.shields.io/badge/Production-Verified-success.svg)](research/06-trusted-delivery-plan.md)
[![Mac Install: Tested](https://img.shields.io/badge/Mac%20Install-Tested-success.svg)](research/07-mac-install-acceptance.md)

---

## ⚡ 它是如何工作的？

```mermaid
flowchart LR
    Client["你的手机 / 电脑\n(小火箭 / FlClash)"] -->|"防封锁加密连接"| Server["你的独立云服务器\n(独享纯净 IP)"] -->|"安全直达"| Out["Google / ChatGPT / GitHub"]
```

* **安全（官方原版，零数据收集）**：只安装知名开源安全底座（[sing-box](https://github.com/SagerNet/sing-box) 与 [Caddy](https://github.com/caddyserver/caddy) 原版），绝无后门；不记录上网历史，密码与密钥物理不出机。
* **可控（资产自有，一个网页多端同步）**：服务器是你自己的，独享纯净 IP，哪怕本仓库关闭也永久可用；手机电脑扫码一键连通。
* **便宜（几块钱起步，不卖流量）**：自备海外云服务器（0 元至几块钱/月），不收月租、不卖流量，彻底告别商业机场按月按量割韭菜。

---

## 📋 准备清单与花费预估

> 💡 **核心成本区间**：搭建普通节点每年仅需 **0 ~ 99 元**（服务器可完全白嫖），在此基础上只需再加 **85 元/年**（12 美元）挂载美国家宽 IP，即可升级为彻底防封的家庭住宅节点。

在开始前，你只需准备以下原材料（丰俭由人）：

| 原材料类别 | 推荐方案 | 预估花费 | 说明与官方链接 |
| :--- | :--- | :--- | :--- |
| **1. 海外云服务器**<br>*(必选 · 强烈推荐**美西地区**如硅谷/洛杉矶，光缆直连且对 AI 支持最纯净)* | **甲骨文云 Oracle** | **0 元 / 月 (永久白嫖)** | [Oracle Always Free](https://www.oracle.com/cloud/free/)（官方永久免费额度，需外币信用卡） |
| | **阿里云高校计划** | **0 元 或 9.9 元/月** | [阿里云「云工开物」](https://university.aliyun.com/)（高校学生与青年开发者专享算力补贴） |
| | **大促特惠活动机** | **约 8 ~ 11 元/月** | 腾讯云 1024 程序员节等官方活动特惠机（实测 **99元/年 硅谷**、**138元/年 新加坡**）；日常优惠可常刷 **[LINUX DO 社区](https://linux.do/)** 关注神价爆料 |
| | **RackNerd** | **约 7 元 / 月** | [RackNerd](https://www.racknerd.com/)（便宜实惠的海外年付小主机） |
| **2. 客户端上网软件**<br>*(必选 · 免费开源)* | **安卓 / Windows / Mac** | **0 元 完全免费** | [FlClash](https://github.com/chen08209/FlClash)（纯净开源，控制台提供免翻下载直链） |
| | **电脑专业版** | **0 元 完全免费** | [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)（适合喜欢规则分流的高阶用户） |
| | **iPhone / iPad** | **免费通道** | [Shadowrocket (小火箭)](https://apps.apple.com/app/shadowrocket/id932747118)（控制台内提供免费美区通道，一键自动配好） |
| **3. 真实美国家庭宽带**<br>*(⭐ 唯一刚需付费项 · 彻底解决 AI 封号)* | **Webshare 静态住宅 (ISP)** | **约 $12 / 年 (+7元/月)** | [Webshare](https://www.webshare.io/)（**唯一必须付费项**，挂载真实美国家宽，彻底根除 ChatGPT/Claude 机房 IP 拒访与封号风险） |

---

## 🚀 2 分钟极速装配

材料就绪后，选择以下任意一种方式完成部署：

### Mac 本地网页安装

在仓库根目录双击 **`启动安装.command`**，自动打开只监听本机的安装页面。需要 Python 3.10+；首次启动会按 `requirements.lock` 安装本地依赖。随后在网页输入目标服务器的 root 登录信息，核对 SSH 指纹，完成连接检查后点击安装。

SSH 连接由 Mac 直接发往目标服务器；密码、私钥和私钥口令不写入文件或日志。安装会下载目标依赖并申请 HTTPS 证书，需要云安全组放通 SSH、80/TCP、8443/TCP、443/TCP、443/UDP。仅支持空白 Ubuntu 22.04+ / Debian 12+ 服务器，不接管已有服务。

安装期间保持 Mac 和启动窗口运行。页面显示实际阶段和耗时，点击“查看安装记录”可展开完整记录，刷新后继续读取当前任务。失败时页面会直接显示原因和下一步。安装与验收通过后，页面优先显示管理入口和初始密码。保存密码后，可关闭本地服务，内存中的任务和交付信息随之清除。

此入口已完成 Mac → 空白 Debian 12 云机的网页首装、首次改密、客户端导入和 Reality/HY2 独立出网验证。后续修复了状态文件读取的权限冲突，并增加真实安装进度。797 项离线检查、普通用户 Caddy 隔离集成及浏览器流程验收通过。修复后的云机首装待复验。详见[验收记录](research/07-mac-install-acceptance.md)。

### 方式 1：交给本地 AI Agent 全自动装配（⭐ 最推荐 · 小白首选）
不用打开云服务器黑框终端，不用学任何 Linux 命令。  
在 **Cursor / Claude Code / Antigravity / Windsurf** 等 AI 工具中，直接把下面这句话连同你的服务器信息发给 AI：
```text
克隆 https://github.com/AdgaiWalker/VPN-OwnLine.git，通过 SSH 连接我的服务器 [IP:端口:密码]，帮我全自动装配好，并把管理网址和初始账号密码发给我。
```
> AI 会自动帮你完成环境检测、安全加固与服务验证，装好后直接把管理后台链接和密码交还给你。

---

### 方式 2：自备服务器终端一行命令装配（工程师极客）
如果你熟悉终端，登录云服务器网页命令行（Ubuntu 22.04 / Debian 12），粘贴并回车：
```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```
* **运行完毕后，屏幕直接打出你的专属管理后台网址与密码**：
  ```text
  专属管理地址: https://43.153.56.137:8443/
  面板账号:   admin
  初始密码:   xxxxxxxxxxxxxxxxxxxx
  ```

---

### 共同的下一步：登录后台，一键连接上网

用浏览器打开上述得到的管理网址（`https://服务器IP:8443/`），输入账号密码登录：

* **页面正上方会提供你的专属订阅链接和二维码**：
  ```text
  专属订阅链接: https://43.153.56.137:8443/s/c2763f350db2d011
  ```
  > **如何连通**：
  > * **手机（小火箭）**：点网页上的【一键连接本机】或手机扫码，App 自动唤醒并写入线路，轻按开关即通。
  > * **电脑（FlClash）**：点【复制订阅链接】，在软件里粘贴保存，就会自动刷出绿色可用线路，点连接即通。

> 💡 **避坑提示**：  
> 1. 第一次用 IP 网址打开时，浏览器提示“证书不安全”属于正常现象，点击「高级 ➔ 继续访问」即可。  
> 2. 如果网页一直转圈打不开，是因为云厂商默认关了端口，去云控制台把防火墙（安全组）的 **8443** 和 **443** 端口放行即可。

---

## 🧱 开源基石致敬

安装、升级及节点控制的归属校验、失败恢复和兼容规则见 [可信交付方案与执行清单](research/06-trusted-delivery-plan.md)。旧节点的现有连接继续保留；无法确认服务归属时，在线修改会被拒绝，需要先核实归属。

本项目建立在以下卓越的开源技术之上：
* [sing-box](https://github.com/SagerNet/sing-box) - 下一代通用代理核心引擎
* [Caddy](https://github.com/caddyserver/caddy) - 现代化自动证书管理与反向代理网关
* [Shadowrocket](https://apps.apple.com/app/shadowrocket/id932747118) / [FlClash](https://github.com/chen08209/FlClash) / [Clash Meta](https://github.com/MetaCubeX/mihomo) - 客户端标准生态

---

## ⚖️ 免责声明

本项目为开源私有网络管理与自动化部署工具，仅供个人合规网络管理与技术研究。使用者自备服务器并遵守当地法律法规。本项目不提供、不托管、不中转任何网络代理服务，不对任何使用者行为承担连带法律责任。
