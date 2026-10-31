# VPN-OwnLine · Evergreen

> **Turn Tencent Cloud & personal VPS into your private, dedicated, and self-healing cross-border line.**  
> *First-class automated assembly for Tencent Cloud, generic Linux VPS supported, with multi-cloud automation on the roadmap.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3 Standard Library](https://img.shields.io/badge/Python-3%20Stdlib%20Only-brightgreen.svg)]()
[![Tests: 272 Passed](https://img.shields.io/badge/Tests-272%20Passed%20(100%25)-success.svg)]()
[![Live Verify: 21 Passed](https://img.shields.io/badge/Live%20Verify-21%2F21%20Passed-success.svg)]()

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
| **Tencent Cloud (Lighthouse / CVM)** | **Tier 1: Full Automation** | CAM instance auto-discovery, API automated firewall rules (TCP 22/443/8443, UDP 443), real-time traffic package telemetry, 85% quota physical circuit breaker | 🟢 **Production Ready (Fully Automated)** |
| **Generic Linux VPS (Any Provider)** | **Tier 2: Generic SSH Access** | Enter IP + root password: 30-second silent deployment, dual Reality + Hysteria2 protocols, multi-landing failover | 🟢 **Fully Usable (All Hosts Supported)** |
| **Alibaba Cloud / AWS / Oracle Cloud / GCP** | **Tier 3: Strategic Roadmap** | Native API auto-discovery, automated quota telemetry, and cloud firewall orchestration | 🟡 **Planned (Multi-Cloud Ecosystem)** |

---

## 3. Five Core Safeguards

### 🛡️ 1. 85% Strict Circuit Breaker (Anti-Overcharge)
Pay-as-you-go overage bandwidth on cloud platforms is exorbitantly expensive. VPN-OwnLine polls real traffic package data via cloud APIs (e.g., Tencent Lighthouse API). When monthly traffic reaches **85% of total package allowance**, it automatically executes remote physical shutdown (`systemctl stop sing-box`) and removes the node from active subscriptions—**guaranteeing zero unexpected bills**. Once a new billing cycle begins, services are restored automatically.

### 🌐 2. Domain Memory Hub (Permanent Subscription)
Individual cloud servers may expire and IP addresses may change, but your private line stays evergreen. By decoupling the control plane domain from backend exit nodes, your client subscription URL remains permanently valid. You import the profile to your phone or laptop once, and roam forever.

### 🔄 3. Multi-Landing Relay & Zero-Touch Self-Healing
For inland relay nodes, the system automatically configures dual overseas landing channels (e.g., Beijing ➜ Silicon Valley [primary] + Singapore [backup]). Powered by sing-box native `urltest` health probes, traffic seamlessly fails over to the backup landing within seconds if the primary exit encounters network anomalies.

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
│   ├── test.sh             13 offline unit test suites (272 tests, 100% PASS)
│   ├── verify.sh           21 live end-to-end integration acceptance tests
│   └── drift.py            Configuration drift detection against golden templates
└── README.md               Project overview & quickstart guide
```

---

## 7. Engineering Standards & DoD

We adhere to strict industrial Definition of Done (DoD) standards. Subjective "looks good" claims are forbidden; every release must produce objective machine evidence:

* **Offline Unit Test Gate**: Run `./scripts/test.sh` — **13 test suites, 272 assertions must pass at 100%** with zero network dependency.
* **Production Acceptance Gate**: Run `./scripts/verify.sh <URL> <user> <pass> <token>` — **21 end-to-end live integration tests must pass with 0 failures**.

---

## 8. License

This project is licensed under the [MIT License](LICENSE).
