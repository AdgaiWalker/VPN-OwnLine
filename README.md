# VPN-OwnLine · Evergreen

> **Turn your own Linux server into a private, dedicated cross-border line.**<br>
> *Start with SSH. Optional Tencent Cloud Lighthouse integration adds native cloud capabilities; other providers use generic SSH on compatible hosts.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3 Standard Library](https://img.shields.io/badge/Python-3%20Stdlib%20Only-brightgreen.svg)]()
[![Tests: 301 Passed](https://img.shields.io/badge/Tests-301%20Passed%20(100%25)-success.svg)]()
[![Live Verify: Pending](https://img.shields.io/badge/Live%20Verify-Pending-yellow.svg)]()

---

**Current patch validation:** 13 offline suites / 301 checks passed. This patch has not been deployed; the 21-check production acceptance suite has not been rerun.

## Need a server?

Compare affordable servers and free-tier or trial options in the [server buying and preparation guide](docs/server-buying-guide.md). It covers deployment outside mainland China, offer conditions and the total cost beyond the VM. Already have a server? Continue below.

## AI-assisted setup

Start with your server's **SSH address and login**; `root` is the proposed form default, while some images use another administrative user. Optional **Tencent Cloud** authorization belongs below SSH access and is not required to begin. This entry order is the design target; the current web interface has not been updated in this documentation revision.

Not sure where to start? Copy this into an AI assistant you use:

```text
Help me prepare and set up https://github.com/AdgaiWalker/VPN-OwnLine on my own Linux server. Read the README first and follow its AI assistance instructions. If I do not have a server, start with the buying guide. Reply in my language.
```

You can start without knowing Linux or filling out a long form. The AI should help you identify your server, prepare access, inspect it, and continue only within your confirmed setup scope. Use a local checkout when available; otherwise read the repository and current official cloud documentation. Do not invent a different installer.

### What the AI should do

1. **Prepare a server if needed.** Read the [buying guide](docs/server-buying-guide.md). Ask about budget, connection location, use and traffic; compare a small suitable shortlist using current official information. Distinguish recurring free allowances, trials and credits, including IP and traffic costs and verification requirements. Let you purchase or activate the chosen server yourself. Start with an existing compatible server when available.
2. **Find your server.** Help you locate the actual provider, product and instance, then identify its region, instance ID, public address, system and login method. Ask you to select the target if several servers exist. Generic SSH is the default path, including for Tencent users; cloud authorization is optional. Lighthouse has native cloud integration; Tencent CVM and other compatible Linux hosts use generic SSH without native cloud usage protection.
3. **Prepare SSH access first.** Explain where to enter your username and password or private key securely. An old password cannot be promised recoverable from the console; if it is unavailable, explain the reset options and effects first and let you complete sensitive input and required verification. Some Ubuntu images use `ubuntu` with sudo or keys rather than root password login. First deployment can run as root through sudo, but the current remote installer does not automatically elevate a non-root SSH user and uses SSH port 22. Explain these limitations rather than silently changing login settings. Keep the SSH port separate from the proxy service port.
4. **Offer Tencent cloud access only when useful.** For Lighthouse discovery and usage monitoring, optionally guide you through a dedicated Tencent Cloud CAM sub-user with the required permissions. Do not require CAM before SSH or invent equivalent native adapters for other providers. Explain and confirm additional firewall permissions; password resets and server reboots are separate operations. SecretId/SecretKey are cloud API credentials, not the server's SSH login. SecretKey is shown only when created. Let you save and enter secrets securely; do not ask for them in ordinary chat, screenshots or public logs.
5. **Inspect before changing.** After connection, report the target, system, existing sing-box and compatibility. Preserve compatible existing configuration. Connecting does not itself authorize installation, overwriting, restarting or uninstalling. The product's independent read-only Connect flow is planned; do not run an install job as a substitute for read-only inspection.
6. **Continue after your setup confirmation.** Once you confirm the target and start installation, use the project's existing installation/API path and report actual progress. If a task is already running, observe it rather than launch a second installer. Do not bypass missing features by silently editing managed files over SSH. Explain a capability gap when the current code does not yet support the requested design.
7. **Verify and hand back.** Distinguish SSH reachable, installation finished, service verified and subscription imported. Help you import into Shadowrocket, Clash or FL Clash. The native client handles connection and node selection. Mask credentials in summaries and claim success only with evidence.

Start with [the design specification](docs/设计/客户端Web交互设计规格说明书.md), especially sections 5, 10.7, 10.8 and 12, and [the engineering rules](docs/核心文档/04-工程规范与验收标准.md). The specification includes planned behavior; it is not a claim that every flow is already implemented. No Harness, skill installation or in-product AI runtime is required.

**Tool access matters:** a chat-only assistant can guide you. Actually inspecting a cloud console or executing commands requires an assistant with the relevant tools and your authorization. Being connected through this product does not automatically give your external AI its SSH session or credentials. Account login, sensitive input, additional access grants and disruptive operations must follow the required user confirmation or handoff.

### Useful starting prompts

| Situation | Copy this prompt |
|---|---|
| I do not have a server | Read VPN-OwnLine's README and buying guide. Help me choose an affordable compatible server outside mainland China. Ask about my budget, connection location, intended use and monthly traffic, then compare a small shortlist using current official information. Explain ongoing cost, free-tier limits and verification requirements. I will complete the purchase or activation myself. |
| I cannot find the server or its address | I bought a Linux server. Help me identify its provider and correct instance, public IP, system and SSH login method. Start with read-only inspection; do not change anything yet or require cloud API authorization. |
| I want optional Tencent Cloud integration | I want to add Tencent Lighthouse cloud integration to VPN-OwnLine. Help me prepare a dedicated CAM sub-user. Explain the minimum permissions and guide me through saving API credentials securely; do not request my SecretKey in chat. Keep this separate from SSH access. |
| The server is connected | Help me inspect this connected server using VPN-OwnLine. Keep existing compatible sing-box configuration. Show me what needs to happen before installation, and continue after I confirm the target and start installation. |
| Installation or import failed | Help me diagnose VPN-OwnLine using the current README and design specification. Read status and logs first, mask secrets, and explain the evidence before proposing changes. |

For server passwords and CAM access, consult [Tencent Cloud password reset guidance](https://cloud.tencent.com/document/product/1207/44575), [CAM users and least privilege](https://cloud.tencent.com/document/product/598/13665), and [sub-user API keys](https://cloud.tencent.com/document/product/598/37140). These actions can require user verification; do not treat a prompt as proof that they succeeded.

---

## 1. What is VPN-OwnLine?

**VPN-OwnLine** (Brand: *Evergreen / 长青*) is an automated, self-hosted assembly appliance and lifecycle management hub designed for cross-border e-commerce operators, academic researchers, and individuals who require pure, private, and unblockable dedicated lines without command-line complexity.

### The Three "NOTs"
* **NOT a commercial VPN or proxy provider**: Zero shared nodes, zero recurring traffic markup, zero traffic logging. Your traffic flows strictly point-to-point between your own cloud servers and your personal devices, ensuring clean dedicated IPs and zero risk of account ban contagion.
* **NOT a client-side proxy app**: It does not replace native client software like **Shadowrocket** (iOS/macOS) or **Clash Verge Rev / FlClash** (Windows/Android/Linux). *Note: `sing-box` runs strictly as a high-performance backend server daemon on your VPS, never as a client-side application.*
* **NOT a disposable raw shell script**: Raw scripts dump a fragile connection string and abandon maintenance. VPN-OwnLine acts as a **permanent assembly mother machine**—providing domain memory, telemetry monitoring, remote self-healing, and traffic overage circuit breakers.

---

## 2. Cloud Provider Support & Roadmap

We prioritize real-world reliability over empty promises. Our current architecture is strictly tiered:

| Cloud Provider / Infrastructure | Integration Tier | Key Automated Capabilities | Current Status |
|---|---|---|---|
| **Compatible Linux VPS (Any Provider)** | **Default: Generic SSH** | Address, username (default root) and password/private key; existing remote installation path with current privilege and port limitations | Generic SSH exists; the revised entry order and independent read-only Connect flow are planned |
| **Tencent Cloud Lighthouse** | **Optional: Native cloud APIs** | CAM instance discovery, supported firewall actions, real traffic-package telemetry and 85% quota protection when configured | Lighthouse adapter exists; authorization is optional and separate from SSH |
| **Other cloud providers** | **Native APIs: Roadmap** | Provider-specific discovery, cloud firewall and usage integration | Not implemented; buying-guide inclusion does not add these capabilities |

**CVM support:** CVM instances can use the generic SSH path on supported Linux systems; native CVM discovery, firewall and usage APIs are not implemented.

The [buying guide](docs/server-buying-guide.md) contains the provider shortlist and current-offer references. Generic SSH alone does not provide cloud-billing protection for any provider, including Tencent Cloud.

---

## 3. Five Core Safeguards

### 🛡️ 1. 85% Strict Circuit Breaker (Anti-Overcharge)
Pay-as-you-go overage bandwidth on cloud platforms is exorbitantly expensive. VPN-OwnLine polls real traffic package data via cloud APIs (e.g., Tencent Lighthouse API). When monthly traffic reaches **85% of total package allowance**, it automatically executes remote physical shutdown (`systemctl stop sing-box`) and removes the node from active subscriptions. Stop/start commands must succeed before the saved state changes; failed commands are retried on the next refresh. Missing or invalid usage data does not release an existing circuit breaker. Services are restored after a valid reading falls below the threshold. Polling delays, API failures and SSH failures mean this reduces overage risk rather than guaranteeing zero charges.

### 🌐 2. Domain Memory Hub (Permanent Subscription)
Individual cloud servers may expire and IP addresses may change, but your private line stays evergreen. By decoupling the control plane domain from backend exit nodes, your client subscription URL remains permanently valid. You import the profile to your phone or laptop once, and roam forever.

### 🔄 3. Multi-Landing Relay & Zero-Touch Self-Healing
For inland relay nodes, the system automatically configures dual overseas landing channels (e.g., Beijing ➜ Silicon Valley [primary] + Singapore [backup]). Powered by sing-box native `urltest` health probes, traffic can fail over to the backup landing according to the configured health-check interval if the primary exit encounters network anomalies.

### ⚡ 4. Pre-Flight 3-Second Port Probe
Before initiating any deployment, the engine executes a 3-second TCP port 22 handshake check. If the port is unreachable, it immediately halts and provides human-readable diagnostic instructions (e.g., *"Port 22 is blocked; please verify the server is powered on and security group rules allow TCP 22"*), preventing broken intermediate states.

### 📱 5. One-Click Native Client Awakening
Eliminates fragile copy-pasting. In mobile Safari or desktop browsers, clicking **"Shadowrocket"** or **"Clash"** directly triggers native URL Schemes (`shadowrocket://add/sub://...` and `clash://install-config?...`), immediately loading the encrypted profile into your client application.

---

## 4. Architecture

```
            User Devices (Safari / Shadowrocket / Clash)
                           │  https://<domain>:8443 or https://<ip>.sslip.io:8443
                           ▼
                ┌──────────────────────┐
                │  Caddy (:80 / :8443) │──► admin.py (Management API + Native Subscriptions)
                │  Reverse Proxy / SSL │    (Base64 & Clash YAML auto-routing by User-Agent)
                └──────────┬───────────┘
                           │ SSH / Telemetry & Health Probes
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
         Node A         Node B         Node C     sing-box + Reality (443/tcp) & HY2 (443/udp)
      (Silicon Valley)   (Beijing Relay)  (Singapore)
```

* **Core Protocol Choice**: Dual-protocol deployment on port 443 (TCP: VLESS-Reality with Apple Safari TLS certificate simulation; UDP: Hysteria2 with BBR congestion control).
* **Zero Bloat Stack**: The entire control plane is written in pure **Python 3 Standard Library** without heavy frameworks (no Flask, Django, Node.js, or Redis).

---

## 5. Quick Start (1-Click Bootstrap)

### Prerequisites
* A clean cloud VPS running **Ubuntu 22.04 LTS+** or **Debian 12+**.
* Root access via SSH.

### One-Command Deployment
Run the bootstrap command on your server:

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```

> **Domain Handling**: If you do not have a custom domain, Caddy automatically provisions a valid Let's Encrypt certificate using `<ip>.sslip.io`. To use your own domain, append `--domain yourdomain.com`.

Once complete, the terminal outputs your Web Console URL, admin credentials, and permanent subscription link.

---

## 6. Repository Layout

```
VPN-OwnLine/
├── deploy/                 One-click bootstrap, local installer, and systemd units
│   ├── bootstrap.sh        Remote 1-click bootstrap script
│   ├── install.sh          Local unattended deployment engine
│   └── systemd/            Service units for admin daemon and probes
├── docs/                   Core architectural and operational documentation
│   └── 核心文档/           The 4 foundational specifications (PRD, Roadmap, Arch, DoD)
├── server/                 Control plane backend (Python 3 stdlib only)
│   ├── admin.py            REST API & native subscription generator
│   ├── probe.py            Dual-perspective latency & reachability probes
│   ├── nodekit/            Pure functional modules (subscriptions, quota, relay, jev)
│   └── providers/          Cloud provider abstraction (Tencent Lighthouse, Generic VPS)
├── web/                    Web console frontend
│   └── index.html          OpenDesign paper-serif single-page interface (bilingual, zero build)
├── scripts/
│   ├── test.sh             13 offline unit test suites (301 tests, 100% PASS)
│   ├── verify.sh           21 live end-to-end integration acceptance tests
│   └── drift.py            Configuration drift detection against golden templates
└── README.md               Project overview & quickstart guide
```

---

## 7. Engineering Standards & DoD

We adhere to strict industrial Definition of Done (DoD) standards. Subjective "looks good" claims are forbidden; every release must produce objective machine evidence:

* **Offline Unit Test Gate**: Run `./scripts/test.sh` — **13 test suites, 301 assertions must pass at 100%** with zero network dependency.
* **Production Acceptance Gate**: Run `./scripts/verify.sh <URL> <user> <pass> <token>` — **21 end-to-end live integration tests must pass with 0 failures**.

---

## 8. License

This project is licensed under the [MIT License](LICENSE).
