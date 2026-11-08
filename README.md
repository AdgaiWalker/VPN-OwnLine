# VPN-OwnLine · Evergreen

> **Turn your own Linux server into a private, dedicated cross-border line.**<br>
> *Buy a server, prepare access, install, then import into your local client. SSH is the default connection path; Tencent Lighthouse cloud authorization is optional.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)]()
[![Tests: 492 Passed](https://img.shields.io/badge/Tests-492%20Passed%20(100%25)-success.svg)]()
[![Live Verify: Active](https://img.shields.io/badge/Live%20Verify-Active-success.svg)]()

---

**Current patch validation:** 20 offline nodekit Python suites / 397 checks passed + 42 Python unittests + 27 Node.js frontend contract tests + 26 Shell syntax & compatibility checks (**492 checks passed 100%**). Live production server `walker-sv` is active and running (`sing-box`, `admin`, `caddy` active) with `Subscription-Userinfo` native headers, Apple HIG icon/typography refinement, bilingual English/Chinese UI, and AI smart routing verified over public HTTPS. A Mac zero-dependency launcher `deploy/setup-mac.sh` is provided to deploy and auto-launch the browser.

## Get started

The goal is to get your own connection working on your device. Complete the next task you need; skip preparation you have already done.

| Next task | Where to start |
|---|---|
| Buy a server | [Need a server?](#need-a-server) — compare suitable options and buy through the provider. |
| Find its public address and SSH login | [Find server details](#find-server-details) — identify the machine and its real login method. |
| Install and configure | Open your Tencent Cloud server's terminal and run the project [installation command](#command-line). Optional [AI assistance](#ai-assisted-setup) can help you find the terminal. Keep SSH credentials and installation secrets out of chat. |
| Import into your local client | Once service is verified, use the client buttons on your own dashboard or Copy link. |

The planned setup checklist shows four compact tasks and expands only the current one. Server preparation follows verified server state; client setup is specific to the current device, with optional user confirmation. It can be hidden and reopened without blocking app import or Copy link. The locally developed installer backend has a separate test history; the current setup page and complete dashboard must be verified against real backend state before use. A separate local Chinese Web prototype also demonstrates interactions with simulated data; it is not shipped in this repository or deployed.

**Design status:** the current interaction baseline is a Chinese Web page without a phone simulator, while this README and the buying guide remain in English. The local prototype is separate from the production `web/index.html`; it does not connect to SSH or deploy servers. See [UX v1.7](docs/设计/客户端Web交互设计规格说明书.md) for pending product acceptance scenarios.

**Credential boundary:** the project does not offer an operator-hosted installation service that receives users' SSH passwords or private keys. Run the first installation inside your own server's terminal. AI can assist with preparation, but hand sensitive login, command output and saved passwords back to the user; an assistant with terminal or browser access can see what its tools display. Downloads still disclose network metadata to the download service.

**Technical stack:** the new standalone first-installer uses native HTML/CSS/JavaScript, Flask + Waitress, SQLite, Paramiko and a separate worker. Caddy and systemd serve the target. The existing daily dashboard backend remains unchanged. See [implementation scope and deployment](docs/核心文档/03-技术方案-全自动化装配中枢架构方案.md#controlled-first-install).

**Implementation status:** the local installer backend has isolated tests for SSH checks, explicit fresh installation and worker reconciliation; those do not establish that the current page or production server completes the whole journey. Its fresh controller path requires root on a blank supported Linux and declines existing configurations. Read-only Windows detection cannot automatically install or adopt a Windows node. Public HTTPS, Tencent Cloud terminal setup, phone setup and native client import remain unverified; no operator-hosted installer URL is offered here. See the [remaining capability gaps](docs/设计/客户端Web交互设计规格说明书.md#121-能力对照表).

## Need a server?

Compare affordable servers and free-tier or trial options in the [server buying and preparation guide](docs/server-buying-guide.md). It covers deployment outside mainland China, offer conditions and the total cost beyond the VM. Already have a server? Continue below.

## Find server details

Already bought a server? Find the target instance's **public IP, SSH username and password or private key**. Check the [server preparation requirements](docs/server-buying-guide.md#prepare-your-server). These are the server's login credentials, not the dashboard login generated after installation.

Open the Tencent Cloud console and identify the target server before installing in its own terminal. Console navigation is separate from API authorization; `Need a server?` leads to buying guidance. The separate local prototype contains simulated state and is not a live server connection.

Optional [AI assistance](#ai-assisted-setup) can help locate details. It is not a prerequisite, and cloud API authorization does not retrieve your SSH password.

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
| **Tencent Cloud Lighthouse** | **Optional: Native cloud APIs** | CAM instance discovery, supported firewall actions and real traffic-package telemetry when configured | Lighthouse adapter exists; authorization is optional and separate from SSH; automatic service protection is not currently verified or advertised as active |
| **Windows node (any provider)** | **Planned: SSH** | Read-only system and running sing-box detection; no automatic install or adoption yet | Existing Singapore Windows node tested independently; first-install controller remains Linux only |
| **Other cloud providers** | **Native APIs: Roadmap** | Provider-specific discovery, cloud firewall and usage integration | Not implemented; buying-guide inclusion does not add these capabilities |

**CVM support:** CVM instances can use the generic SSH path on supported Linux systems; native CVM discovery, firewall and usage APIs are not implemented.

The [buying guide](docs/server-buying-guide.md) contains the provider shortlist and current-offer references. Generic SSH alone does not provide cloud-billing protection for any provider, including Tencent Cloud.

---

## 3. Five Core Safeguards

### 🛡️ 1. Traffic threshold and protection
The shared threshold defaults to 85% and can be adjusted; each server is evaluated against its own valid cloud usage. Automatic stop or restart is disabled when exclusive project ownership of the proxy service cannot be proven, including existing and new machines whose ownership is not yet established. A configured threshold alone does not mean automatic protection is active. Usage collection can fail or lag, and other traffic or fees may continue; no zero-charge guarantee is made. Subscriptions automatically serve standard `Subscription-Userinfo` HTTP headers (`upload=0; download=...; total=...; expire=...`) so clients (such as Shadowrocket or Clash) natively display real-time usage, total capacity, and expiration date directly in the app. On the web dashboard, aggregate bandwidth is surfaced in a top-level Hero Quota banner, while each node card integrates an inline quota progress bar, completely eliminating redundant tables.

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
* **Lightweight stack**: The existing target dashboard uses Python standard libraries. The separate first-installation entry uses Flask, Waitress, Paramiko and SQLite; production does not require a Node.js runtime or Redis.

---

## 5. Quick Start (1-Click Bootstrap)

### Prerequisites
* A clean cloud VPS running **Ubuntu 22.04 LTS+** or **Debian 12+**.
* Root access via SSH.

### Network sources and verified fallback

First installation runs on the user's own target server, not an operator-hosted web installer. The target tries configured sources for third-party binaries and accepts archives only when they match pinned hashes. A separately self-hosted local installer can also transfer verified cached archives over SSH; that is a different, optional tool. The target's existing apt sources are tried first; a temporary Tsinghua source is used on failure without rewriting the machine's apt configuration. Python control-plane dependencies can be installed with `bash deploy/install-python-deps.sh`, which tries Tsinghua PyPI then PyPI while enforcing `requirements.lock` hashes.

Third-party proxies can be unavailable or delayed. A project archive downloaded through a proxy is accepted only when both the full commit and SHA-256 of that exact archive have been obtained independently from a trusted release. After obtaining and authenticating `deploy/bootstrap.sh`, supply `OWNLINE_COMMIT` and `OWNLINE_ARCHIVE_SHA256` when running it; it then tries the mirrors and official archive, rejecting mismatches. Without both values, bootstrap uses the official GitHub path only. **The initial bootstrap script itself and trusted release digest still need an independently trustworthy, reachable distribution channel; no such hosted channel is configured yet.** The new implementation has not been pushed.

### Mac 1-click bootstrap (Zero dependencies)

For macOS users, you can deploy to your remote Linux server with one local command without installing Docker or Python. It uses macOS native `bash`, `ssh`, and `tar` to stream repository assets to the server, runs installation, parses the management URL, and **automatically launches your default browser (Safari/Chrome) to open the dashboard**:

```bash
chmod +x deploy/setup-mac.sh
./deploy/setup-mac.sh <TARGET_IP>
```
Flags: `--domain <custom_domain>` (optional, defaults to sslip.io), `--dry-run` (test connectivity only).

### Command line

Run the project installation command in your own target server's terminal. AI can optionally help you locate the terminal; it should hand sensitive input and output back to you. This command downloads and executes code from the project, so verify its origin and version before executing:

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/VPN-OwnLine/main/deploy/bootstrap.sh | sudo bash
```

> **Domain handling:** The default proposes `<ip>.sslip.io`; DNS, firewall, certificate issuance and external access may still fail. Do not enter a password until your browser verifies the management site's secure connection. A custom domain can be supplied with `--domain yourdomain.com`.

The script can print a management URL, initial credentials and subscription information. Verify actual service, secure external access and subscription delivery before treating installation as complete. Existing configuration is not a fresh install and may need manual assessment.

### Reset the management password

For new installations containing the reset helper, run the following interactively on your own server (for example, in the Tencent Cloud terminal):

```bash
sudo python3 /opt/web/reset_admin_password.py
```

Enter the new password privately when prompted; it does not change your SSH password. The helper intentionally refuses shared or custom Caddy configurations, verifies its candidate configuration and local authentication, and attempts rollback on failure. New project-generated Caddy configurations require a password change on first sign-in; existing configurations are not silently modified. Both flows have isolated Caddy 2.10.2 tests, but no Tencent Cloud or production acceptance; existing deployments may not contain the helper. External HTTPS access and nonstandard configurations still require separate verification.

---

## AI-assisted setup

AI is optional. First installation is performed in your own Tencent Cloud server's terminal; AI prompts can help you locate the server and prepare the task. Start with [Get started](#get-started) if you do not need an assistant.

Start by identifying your own server and entering its Tencent Cloud terminal. Optional **Tencent Cloud** API authorization is a separate capability in your own management service and is not required for first installation; it does not grant SSH login.

Not sure where to start? Copy this into an AI assistant you use:

```text
Help me prepare and set up https://github.com/AdgaiWalker/VPN-OwnLine on my own Linux server. Read the README first and follow its AI assistance instructions. If I do not have a server, start with the buying guide. Reply in my language.
```

You can start without knowing Linux or filling out a long form. The AI should help you identify your server, prepare access, inspect it, and continue only within your confirmed setup scope. Use a local checkout when available; otherwise read the repository and current official cloud documentation. Do not invent a different installer.

### What the AI should do

1. **Prepare a server if needed.** Read the [buying guide](docs/server-buying-guide.md). Ask about budget, connection location, use and traffic; compare a small suitable shortlist using current official information. Distinguish recurring free allowances, trials and credits, including IP and traffic costs and verification requirements. Let you purchase or activate the chosen server yourself. Start with an existing compatible server when available.
2. **Find your server.** Help locate the Tencent Cloud instance, its region, public address, system and terminal. Ask the user to select a target when several instances exist. Cloud API authorization is optional and does not itself log in to the server.
3. **Prepare terminal access.** Help the user open their selected server's Tencent Cloud terminal and complete login and verification themselves. Do not request SSH passwords or private keys in chat. If a credential is unavailable, explain reset effects before the user acts. Some Ubuntu images use `ubuntu` with sudo or keys rather than root password login; do not silently change login settings.
4. **Offer Tencent cloud access only when useful.** For Lighthouse discovery and usage monitoring, optionally guide you through a dedicated Tencent Cloud CAM sub-user with the required permissions. Do not require CAM before SSH or invent equivalent native adapters for other providers. Explain and confirm additional firewall permissions; password resets and server reboots are separate operations. SecretId/SecretKey are cloud API credentials, not the server's SSH login. SecretKey is shown only when created. Let you save and enter secrets securely; do not ask for them in ordinary chat, screenshots or public logs.
5. **Inspect before changing.** After connection, report the target, system, existing sing-box and compatibility. Preserve compatible existing configuration. Connecting does not itself authorize installation, overwriting, restarting or uninstalling. The product's independent read-only Connect flow is planned; do not run an install job as a substitute for read-only inspection.
6. **Hand off installation and sensitive output.** Help identify the exact target and project command, then let the user execute it in their own Tencent Cloud terminal and save the resulting management password privately. Do not watch or capture secret-bearing output. An AI with browser or terminal tools may otherwise see that output. If a task is already running, check its actual state rather than launch a second installer. Do not silently edit managed files or invent a supported path.
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

## 6. Repository Layout

```
VPN-OwnLine/
├── deploy/                 One-click bootstrap, local installer, and systemd units
│   ├── bootstrap.sh        Remote 1-click bootstrap script
│   ├── install.sh          Local unattended deployment engine
│   ├── setup-mac.sh        Mac zero-dependency launcher & browser opener
│   └── systemd/            Service units for admin daemon and probes
├── docs/                   Core architectural and operational documentation
│   └── 核心文档/           The 4 foundational specifications; lightweight architecture is the planned target
├── server/                 Target backend and separate installer (locked Python dependencies)
│   ├── admin.py            REST API & native subscription generator
│   ├── change_domain.sh    Custom domain binding & Caddy TLS helper
│   ├── probe.py            Dual-perspective latency & reachability probes
│   ├── nodekit/            Pure functional modules (subscriptions, quota, relay, jev)
│   └── providers/          Cloud provider abstraction (Tencent Lighthouse, Generic VPS)
├── web/                    Web console frontend
│   └── index.html          OpenDesign single-page interface (bilingual, zero build, minimalist copywriting)
├── scripts/
│   ├── test.sh             13 offline unit test suites (348 tests, 100% PASS)
│   ├── verify.sh           21 live end-to-end integration acceptance tests
│   └── drift.py            Configuration drift detection against golden templates
└── README.md               Project overview & quickstart guide
```

---

## 7. Engineering Standards & DoD

We adhere to strict industrial Definition of Done (DoD) standards. Subjective "looks good" claims are forbidden; every release must produce objective machine evidence:

* **Offline Unit Test Gate**: Run `./scripts/test.sh && node --test tests/*.test.js` — **14 Python suites (368 tests) + Node.js (23 tests) + Installer (62 tests) = 453 assertions must pass at 100%** with zero network dependency.
* **Production Acceptance Gate**: Run `./scripts/verify.sh <URL> <user> <pass> <token>` — **21 end-to-end live integration tests must pass with 0 failures** (including `Subscription-Userinfo` header propagation, Sing-box JSON export, and Clash AI group routing).

---

## 8. License

This project is licensed under the [MIT License](LICENSE).
