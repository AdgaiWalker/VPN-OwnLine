# VPN-OwnLine · 长青 (Evergreen)

> **Turn Tencent Cloud & personal VPS into your private, dedicated, and self-healing cross-border line.**  
> **专注腾讯云全自动化装配（已完整就绪），兼备通用 VPS 极简接入（其他服务器均可用），未来演进全云生态自动化托管。**  
>
> 🌐 **[English Documentation](#english-documentation)** | 🇨🇳 **[中文说明文档](#chinese-documentation)**  
>
> **Project / 项目**: `VPN-OwnLine` · **Brand / 品牌**: `Evergreen (长青)`  
> **Core Docs / 核心文档**: [01-PRD](docs/核心文档/01-PRD-产品需求规格说明书.md) · [02-Roadmap / 白皮书](docs/核心文档/02-产品规划-产品定位与全流程规划白皮书.md) · [03-Architecture / 技术方案](docs/核心文档/03-技术方案-全自动化装配中枢架构方案.md) · [04-Standards / 验收标准](docs/核心文档/04-工程规范与验收标准.md)

---

<a name="english-documentation"></a>
## English Documentation

### 1. What is VPN-OwnLine?

**VPN-OwnLine** (Brand: *Evergreen / 长青*) is an automated, self-hosted assembly appliance and lifecycle management hub that turns user-owned cloud instances into private, unblockable cross-border dedicated lines.

* **Current Implementation & Scope**: We focus primarily on **Tencent Cloud (Lighthouse / CVM)** for full-stack automation (automated instance discovery, API firewall management, real-time traffic package polling, and physical circuit breaker). Concurrently, **any generic Linux VPS** is fully supported via root SSH credentials. Comprehensive automation across all major cloud providers (Alibaba Cloud, AWS, Oracle Cloud, GCP) is on our strategic roadmap.
* **NOT a commercial VPN / proxy service**: Zero shared nodes, zero recurring traffic fees, zero user traffic logging. All traffic flows strictly point-to-point between your personal VPS and your own devices.
* **NOT a client-side proxy app**: It does not replace native clients like Shadowrocket (iOS/macOS) or Clash Verge Rev / FlClash (Win/Android/Linux). (Note: `sing-box` runs exclusively as a high-performance backend server daemon, not as a client).
* **WHAT IT REALLY IS**: An **automated assembly mother machine and lifecycle management hub** for personal cross-border lines. It packages server selection, environment probing, Reality/Hysteria2 masquerading, port arbitration, multi-landing failover, and strict quota protection into a single-click "home appliance" experience.

### 2. Cloud Provider Support & Roadmap

| Cloud Provider | Integration Level | Capabilities | Current Status |
|---|---|---|---|
| **Tencent Cloud (Lighthouse / CVM)** | **Full Automation** | CAM instance auto-discovery, API firewall rule opening, real-time traffic package telemetry, 85% physical circuit breaker | 🟢 **Production Ready (Completed)** |
| **Generic Linux VPS (Any Provider)** | **Generic SSH Access** | Enter IP + root password: 30s silent deployment, dual Reality+HY2 protocols, multi-landing failover | 🟢 **Fully Usable (All Hosts Supported)** |
| **Alibaba / AWS / Oracle / GCP** | **Multi-Cloud Architecture** | Native API auto-discovery, quota telemetry, and automated firewall arbitration | 🟡 **Strategic Roadmap (Future Vision)** |

### 3. Core Pillars & Safeguards

1. **🛡️ 85% Strict Circuit Breaker (Anti-Overcharge)**: Real-time telemetry via Tencent Lighthouse API. At 85% quota, it executes remote physical shutdown (`systemctl stop sing-box`) and removes the node from active subscription to guarantee **zero unexpected overage bills**.
2. **🌐 Domain Memory Hub (Permanent Subscription)**: Cloud servers expire and IPs rotate, but your subscription URL never breaks. Client devices import once and roam forever.
3. **🔄 Multi-Landing Relay & Auto-Failover**: Inland relay nodes automatically balance between primary and backup overseas exits (e.g., Beijing ➜ Silicon Valley / backup Singapore) using sing-box native `urltest`.
4. **⚡ Pre-flight 3-Second Port Probe**: Probes port 22 connectivity before installation and translates low-level Linux/SSH errors into plain human instructions.
5. **📱 One-Click Native Client Import**: Native URL Scheme triggers direct popup in Safari to import into Shadowrocket (`shadowrocket://add/sub://...`) and Clash (`clash://install-config?...`).

### 4. Architecture

```
              Browser / Native Client (Safari / Shadowrocket / Clash)
                               │  https://<domain>:8443 or https://<ip>.sslip.io:8443
                               ▼
                    ┌──────────────────────┐
                    │  Caddy (:80 / :8443) │──► admin.py (Node Management API + Native Subscriptions)
                    │  Reverse Proxy / SSL │    (Base64 & Clash YAML auto-routing by User-Agent)
                    └──────────┬───────────┘
                               │ SSH / Port & Quota Probes
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
             Node A         Node B         Node C     sing-box + Reality (443/tcp) & HY2 (443/udp)
```

### 5. 1-Click Bootstrap Installation

On a clean Ubuntu 22.04+ or Debian 12+ cloud VPS, run:

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```

* Automatically provisions official Let's Encrypt certificates via `<ip>.sslip.io` through Caddy.
* Generates dual Reality (443/tcp) + Hysteria2 (443/udp) protocols with BBR acceleration enabled.

### 6. Repository Directory Layout

```
deploy/                 One-click bootstrap, local installer, and systemd unit files
docs/核心文档/           The 4 foundational pillars (PRD, Roadmap, Architecture, DoD Standards)
server/                 Python 3 standard library backend (API, Probes, Circuit Breaker, Lifecycle)
server/nodekit/         Pure functional modules (subscriptions, quota_guard, relay_guard, repair, jev)
web/index.html          OpenDesign paper serif single-page console (zero build step, bilingual UI)
scripts/test.sh         13 offline test suites (272 tests, 100% PASS)
scripts/verify.sh       21 live end-to-end integration acceptance tests
```

---

<a name="chinese-documentation"></a>
## 中文说明文档

### 1. 什么是 VPN-OwnLine（长青）？

**VPN-OwnLine（长青）** 是一个为无命令行技术背景的个人、外贸业务团队及科研学者打造的**个人专属出海专线全自动化装配母机**。

* **当前实现范围与定位**：系统现阶段**以腾讯云（轻量应用服务器 Lighthouse / CVM）为核心交付全自动化能力**（CAM 实例自动探测发现、API 自动化放行安全组、真实用量包监控与 85% 水位真机熔断断流）；同时**通用支持任意其他厂商的 Linux 云主机**（只需输入 IP 与 root 密码，30 秒静默装配入网）；未来演进路线图将逐步扩展覆盖阿里云、AWS、甲骨文云等全云生态的自动化接管。
* **它不是商业代理 / 机场**：不售卖共享节点，不赚取流量费，不记录用户隐私。流量 100% 仅在用户自购的服务器与个人设备间流通，保障纯净独享 IP 与防封号隔离。
* **它不是本地翻墙客户端**：不替代手机上的 Shadowrocket（小火箭），也不替代电脑/安卓上的 Clash Verge Rev 或 FlClash（注：`sing-box` 仅作为服务端高性能运行内核，客户端不使用 sing-box）。
* **它的真正身份**：**「把裸服务器自动化加工为专属独享防封号专线的装配母机」**。将原本高门槛的云主机选购、编译部署、伪装证书、端口仲裁、动态容灾与流量监控，彻底封装为如家用电饭煲般的单页面流水线。

### 2. 云厂商支持状态与演进路线

| 云厂商 / 基础设施 | 支持等级 | 核心能力 | 当前状态 |
|---|---|---|---|
| **腾讯云（轻量云 Lighthouse / CVM）** | **深度全自动化** | CAM 实例自动探测发现、API 自动化放行安全组端口、真实用量包监控、85% 水位刚性真机断流熔断 | 🟢 **现行基准（已完整就绪运行）** |
| **通用 Linux VPS（任意其他云主机）** | **通用极简接入** | 仅需输入服务器 IP 与 root 密码：30 秒静默装配入网、双协议出口、双落地容灾自愈 | 🟢 **完全可用（其他服务器均可直接使用）** |
| **阿里云 / AWS / 甲骨文云等** | **未来规划演进** | 原生 API 自动纳管、流量包监控与安全组放行 | 🟡 **路线图规划（未来演进为全云生态）** |

### 3. 五大核心保障

1. **🛡️ 85% 刚性断流熔断（绝无超额天价账单）**：真实采集云厂商用量包（如腾讯云 Lighthouse API）。达到 85% 刚性水位时，自动远程真机断流（`systemctl stop sing-box`）并在订阅层同步剔除，宁可断流也绝不产生超额按量扣费。
2. **🌐 域名记忆中枢（一条订阅终身漫游）**：服务器会到期、IP 会变，但一条订阅用到老。换机增删节点客户端零感知。
3. **🔄 双落地中继与无感自愈**：国内中继节点基于 `urltest` 自动配置主备双落地出口（如北京 ➜ 硅谷，备用新加坡），主链路受阻无感自动倒换。
4. **⚡ 装前 3 秒连通性排雷**：点击安装前置 3 秒 TCP 22 探活，底层错误自动转译为“密码错误”、“请在控制台放行22端口”等大白话指引。
5. **📱 客户端一键唤醒直达**：手机端点击按钮瞬间唤醒 Shadowrocket 与 Clash，消灭繁琐的复制粘贴。

### 4. 快速开始（一键远程自举）

准备一台全新的 Ubuntu 22.04+ 或 Debian 12+ 境外服务器，执行以下命令即可全自动安装主控面板并生成首批专线节点：

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```

### 5. 工业级工程与验收标准

* **全离网单测门禁**：`./scripts/test.sh` $\to$ **13 套组件、272 项用例 100% 通过**。
* **端到端真机验收**：`./scripts/verify.sh` $\to$ **21 项系统验收 100% 通过（0 失败）**。

---

## 许可证 / License

MIT License.
