# VPN-OwnLine · 长青 (Evergreen)

> **Turn any cloud VPS into your private, dedicated, and self-healing cross-border line.**  
> **把任意云服务器自动化装配为你个人的专属出海专线。**  
>
> 🌐 **[English Documentation](#english-documentation)** | 🇨🇳 **[中文说明文档](#chinese-documentation)**  
>
> **Project / 项目**: `VPN-OwnLine` · **Brand / 品牌**: `Evergreen (长青)`  
> **Core Docs / 核心文档**: [01-PRD](docs/核心文档/01-PRD-产品需求规格说明书.md) · [02-Roadmap / 白皮书](docs/核心文档/02-产品规划-产品定位与全流程规划白皮书.md) · [03-Architecture / 技术方案](docs/核心文档/03-技术方案-全自动化装配中枢架构方案.md) · [04-Standards / 验收标准](docs/核心文档/04-工程规范与验收标准.md)

---

<a name="english-documentation"></a>
## English Documentation

### 1. What is VPN-OwnLine?

**VPN-OwnLine** (Brand: *Evergreen / 长青*) is an automated, self-hosted assembly appliance and lifecycle management hub that turns user-owned cloud VPS instances into private, unblockable cross-border dedicated lines.

* **NOT a commercial VPN / proxy service**: Zero shared nodes, zero recurring traffic fees, zero user traffic logging. All traffic flows strictly point-to-point between your personal VPS and your own devices.
* **NOT a client-side proxy app**: It does not replace native clients like Shadowrocket (iOS/macOS) or Clash Verge Rev / FlClash (Win/Android/macOS/Linux). (Note: `sing-box` runs exclusively as a high-performance backend server daemon, not as a client).
* **WHAT IT REALLY IS**: An **automated assembly mother machine and lifecycle management hub** for personal cross-border lines. It packages server selection, environment probing, Reality/Hysteria2 masquerading, port arbitration, multi-landing failover, and strict quota protection into a single-click "home appliance" experience.

### 2. Core Pillars & Safeguards

1. **🛡️ 85% Strict Circuit Breaker (Anti-Overcharge)**: Real-time telemetry via Tencent Lighthouse API. At 85% quota, it executes remote physical shutdown (`systemctl stop sing-box`) and removes the node from active subscription to guarantee **zero unexpected overage bills**.
2. **🌐 Domain Memory Hub (Permanent Subscription)**: Cloud servers expire and IPs rotate, but your subscription URL never breaks. Client devices import once and roam forever.
3. **🔄 Multi-Landing Relay & Auto-Failover**: Inland relay nodes automatically balance between primary and backup overseas exits (e.g., Beijing ➜ Silicon Valley / backup Singapore) using sing-box native `urltest`.
4. **⚡ Pre-flight 3-Second Port Probe**: Probes port 22 connectivity before installation and translates low-level Linux/SSH errors into plain human instructions.
5. **📱 One-Click Native Client Import**: Native URL Scheme triggers direct popup in Safari to import into Shadowrocket (`shadowrocket://add/sub://...`) and Clash (`clash://install-config?...`).

### 3. Architecture

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

### 4. 1-Click Bootstrap Installation

On a clean Ubuntu 22.04+ or Debian 12+ cloud VPS, run:

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/ladder-web-panel/main/deploy/bootstrap.sh | sudo bash
```

* Automatically provisions official Let's Encrypt certificates via `<ip>.sslip.io` through Caddy.
* Generates dual Reality (443/tcp) + Hysteria2 (443/udp) protocols with BBR acceleration enabled.

### 5. Repository Directory Layout

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

* **它不是商业代理 / 机场**：不售卖共享节点，不赚取流量费，不记录用户隐私。流量 100% 仅在用户自购的服务器与个人设备间流通，保障纯净独享 IP 与防封号隔离。
* **它不是本地翻墙客户端**：不替代手机上的 Shadowrocket（小火箭），也不替代电脑/安卓上的 Clash Verge Rev 或 FlClash（注：`sing-box` 仅作为服务端高性能运行内核，客户端不使用 sing-box）。
* **它的真正身份**：**「把裸服务器自动化加工为专属独享防封号专线的装配母机」**。将原本高门槛的云主机选购、编译部署、伪装证书、端口仲裁、动态容灾与流量监控，彻底封装为如家用电饭煲般的单页面流水线。

### 2. 五大核心保障

1. **🛡️ 85% 刚性断流熔断（绝无超额天价账单）**：真实采集云厂商用量包（如腾讯云 Lighthouse API）。达到 85% 刚性水位时，自动远程真机断流（`systemctl stop sing-box`）并在订阅层同步剔除，宁可断流也绝不产生超额按量扣费。
2. **🌐 域名记忆中枢（一条订阅终身漫游）**：服务器会到期、IP 会变，但一条订阅用到老。换机增删节点客户端零感知。
3. **🔄 双落地中继与无感自愈**：国内中继节点基于 `urltest` 自动配置主备双落地出口（如北京 ➜ 硅谷，备用新加坡），主链路受阻无感自动倒换。
4. **⚡ 装前 3 秒连通性排雷**：点击安装前置 3 秒 TCP 22 探活，底层错误自动转译为“密码错误”、“请在控制台放行22端口”等大白话指引。
5. **📱 客户端一键唤醒直达**：手机端点击按钮瞬间唤醒 Shadowrocket 与 Clash，消灭繁琐的复制粘贴。

### 3. 快速开始（一键远程自举）

准备一台全新的 Ubuntu 22.04+ 或 Debian 12+ 境外服务器，执行以下命令即可全自动安装主控面板并生成首批专线节点：

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/ladder-web-panel/main/deploy/bootstrap.sh | sudo bash
```

### 4. 工业级工程与验收标准

* **全离网单测门禁**：`./scripts/test.sh` $\to$ **13 套组件、272 项用例 100% 通过**。
* **端到端真机验收**：`./scripts/verify.sh` $\to$ **21 项系统验收 100% 通过（0 失败）**。

---

## 许可证 / License

MIT License.
