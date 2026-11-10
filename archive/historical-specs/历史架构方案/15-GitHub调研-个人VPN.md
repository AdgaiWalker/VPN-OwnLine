# 15 · 个人 VPN / 一台电脑变成梯子 —— GitHub 调研

| 项 | 内容 |
|---|---|
| 日期 | 2026-10-29 |
| 问题 | 如果目标是「任何人有一台电脑，就能把它变成自己的 VPN，再当梯子用」，有哪些成熟方法和代码可以复用？ |
| 前提 | **主打个人自用**：不卖服务、不做多用户、不追求商用 SLA |
| 数据 | GitHub API 实时查询，star / 更新时间截至 2026-10-29 |

---

> **2026-10-30 修正**：§1 第 1、2 条（「不要再自研面板」「默认运行时用 3x-ui」）已被 `16-技术方案-v2` §1 推翻。
> 原判断：用 3x-ui 替代自研面板 → 证据：3x-ui 没有「填 IP 密码自动装 + 国内机自动借道」，历史故障集中在 subconverter / Caddyfile 改写而不在面板 → 改为：保留自研极简面板，删除 subconverter 和胶水层。本文其余调研内容仍然有效。

## 0. 先把「一台电脑」拆成三个物理问题

协议不是第一问题。先回答这三条，方案会自己浮出来：

| 问题 | 答案 | 含义 |
|---|---|---|
| ① 这台电脑有公网 IP 吗？ | 有（VPS / 云主机 / 公网宽带） | 可以直接做服务端，别人能连进来 |
| | 没有（家里 / 公司 / CGNAT） | 需要 NAT 穿透或中转，不能直接当入口 |
| ② 这台电脑在墙外吗？ | 在（海外） | 可以当出口，直接翻墙 |
| | 不在（国内） | **不能单独当梯子**；只能做入口/中转，必须借一台海外落地 |
| ③ 几个人用？ | 1 个人 / 家人 2~3 人 | 单机、单订阅就够 |
| | 10 人以上 | 才需要 Marzban / Remnawave 这类多用户面板 |

> 一句话：**“任何电脑都能变 VPN”在物理上不成立。**
> 国内、NAT 后的电脑可以做“入口”，但出口必须在墙外。
> 产品要么解决 NAT 穿透，要么明确只支持“有公网 IP 的海外电脑”。

---

## 1. 结论先行

1. **不要再自研面板。** 现在这套 `admin.py + Caddy + subconverter + 单页 HTML` 对一个人来说是四层额外的故障点，历史上 14 个故障大半出在这些胶水层。
2. **默认运行时：3x-ui 单面板**。单二进制 + SQLite + 内置订阅 + Telegram/Discord Bot + fail2ban + Windows 支持；48.8k star、日更。一个人用也够，是目前最稳的“一台电脑变 VPN”底座。
3. **如果确定不要面板**：用 fscarmen/sing-box。一条命令、不需要域名、支持 HY2 Realm；代价是 7k 行 bash、没有备份/告警。
4. **NAT 场景用 Headscale/Tailscale 的 exit node**，不要自己写穿透。
5. **我们保留自己的“验证优先”部分**：`nodekit/templates.py`、`nodekit/verify.py`（真实出口 IP 才算 ok）、`scripts/drift.py`、`docs/08-LESSONS.md`。这些是别人没有的。

---

## 2. 候选清单

### A. 一键脚本（无面板，最接近“一台电脑 → 一个节点”）

| 项目 | Star | 最近更新 | 许可 | 能做什么 | 可复用什么 | 限制 |
|---|---:|---|---|---|---|---|
| [fscarmen/sing-box](https://github.com/fscarmen/sing-box) | 5.9k | 2026-10-26 | GPL-3.0 | 一键装 11 种协议：Reality / Hysteria2 / TUIC / Trojan / SS / AnyTLS / ShadowTLS / VMess / VLESS / NaiveProxy；**不需要域名**；自带多客户端订阅；Argo 隧道；HY2 Realm（NAT/CGNAT 打洞）；WARP 解锁 | 安装流程、协议默认值、订阅模板、防火墙/升级/卸载逻辑 | 仅 Linux；bash 大脚本；没有备份/告警；GPL |
| [233boy/sing-box](https://github.com/233boy/sing-box) | 5.1k | 2026-06-04 | GPL-3.0 | 同类，CLI 极简：`sing-box add vless reality`；多协议多配置并行 | 命令设计、配置管理思路 | 更新慢（4 个月）；92 个 open issue；仅 Linux |
| [wulabing/Xray_onekey](https://github.com/wulabing/Xray_onekey) | 9.3k | 2026-08-15 | MIT | 经典 Xray 一键（VLESS+WS+TLS 为主） | 老牌稳定性、TLS 自动化 | 偏旧范式（要域名/证书），不是 Reality 优先 |

### B. 面板（有 UI，适合多机/要图形界面）

| 项目 | Star | 最近更新 | 许可 | 能做什么 | 可复用什么 | 限制 |
|---|---:|---|---|---|---|---|
| [MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui) | 48.8k | 2026-10-29 | GPL-3.0 | Xray 面板；Reality / Hysteria2 / AmneziaWG / TUIC / SS / WireGuard；**Windows + Linux**；SQLite 单文件；自带订阅服务器；多节点管理；Telegram/Discord 机器人；fail2ban | 整个运行时 + 面板 + 订阅；个人用可直接替换现有 admin/Caddy/subconverter | 功能多、配置项多；258 open issues；面板要加固；GPL |
| [alireza0/s-ui](https://github.com/alireza0/s-ui) | 10.2k | 2026-10-25 | GPL-3.0 | sing-box 面板；多协议/多客户端；订阅 link/json/clash；API；Linux/Windows/macOS（macOS experimental） | 若想保留 sing-box 内核、又要 UI，这是最顺的替换 | 作者标注“非生产”；macOS 实验性；生态比 3x-ui 小 |
| [hiddify/Hiddify-Manager](https://github.com/hiddify/Hiddify-Manager) | 9.4k | 2026-10-28 | GPL-3.0 | 多用户反审查面板；20+ 协议；自动备份（6h）/自动更新/Telegram Bot；Xray + sing-box 双核心 | 运维自动化（备份、更新、机器人）的设计 | 仅 Ubuntu 22.04；为多用户设计，一个人用太重 |
| [Gozargah/Marzban](https://github.com/Gozargah/Marzban) | 7.5k | 2026-10-14 | AGPL-3.0 | Xray 多用户面板 | 多用户/订阅模型 | 个人自用不需要；AGPL |

### C. 桌面 App（把“部署服务器”做成 GUI）

| 项目 | Star | 最近更新 | 许可 | 能做什么 | 可复用什么 | 限制 |
|---|---:|---|---|---|---|---|
| [amnezia-vpn/amnezia-client](https://github.com/amnezia-vpn/amnezia-client) | 15.6k | 2026-10-29 | GPL-3.0 | 桌面/手机客户端；**输入 IP + SSH 账号密码，自动在服务器上装 Docker 容器并连上**；支持 OpenVPN / WireGuard / IKEv2 / AmneziaWG / XRay | “客户端即安装器”的 UX；协议选择与容器编排 | 服务器需 Linux + Docker；无订阅 URL；XRay 配置能力不如专门面板；GPL |
| [OutlineFoundation/outline-apps](https://github.com/OutlineFoundation/outline-apps) | 9.3k | 2026-10-26 | Apache-2.0 | Outline Manager（Win/Mac/Linux）一键在云上建 Shadowsocks 服务；Outline Client 全平台 | 面向非技术用户的“管理端 + 客户端”体验 | 只有 Shadowsocks，特征明显；抗封锁弱；依赖云厂商 |

### D. Mesh / NAT / exit node（解决“电脑没有公网 IP”）

| 项目 | Star | 最近更新 | 许可 | 能做什么 | 可复用什么 | 限制 |
|---|---:|---|---|---|---|---|
| [juanfont/headscale](https://github.com/juanfont/headscale) | 45.2k | 2026-10-29 | BSD-3 | 自建 Tailscale 控制面；NAT 穿透；exit node；单 tailnet，明确面向个人 | 整个控制面；配合官方 Tailscale 客户端 | 需要一台公网控制机；DERP 中继受网络影响；WireGuard 特征在墙内不一定稳 |
| [tailscale/tailscale](https://github.com/tailscale/tailscale) | 38.3k | 2026-10-29 | BSD-3 | 官方客户端；exit node / subnet router | 客户端与 exit node 能力 | 控制面是商业服务（除非用 Headscale） |
| [netbirdio/netbird](https://github.com/netbirdio/netbird) | 30.3k | 2026-10-29 | 其他 | WireGuard 零信任 overlay；NAT 穿透 | 自建控制面 + 客户端 | 偏企业；比 Tailscale 重 |
| [EasyTier/EasyTier](https://github.com/EasyTier/EasyTier) | 14.4k | 2026-10-29 | LGPL-3.0 | 去中心化 mesh VPN，WireGuard 兼容 | 无中心节点的组网 | 不是抗审查代理；适合内网互联 |

### E. 协议核心 / 新协议

| 项目 | Star | 许可 | 说明 |
|---|---:|---|---|
| [SagerNet/sing-box](https://github.com/SagerNet/sing-box) | 39.4k | GPL 系（GitHub 标 Other） | 现有项目的核心；Reality / HY2 / TUIC / AnyTLS 都支持；继续用 |
| [XTLS/Xray-core](https://github.com/XTLS/Xray-core) | 42.4k | MPL-2.0 | Reality 参考实现；3x-ui / Marzban 的内核 |
| [HyNetworks/hysteria](https://github.com/HyNetworks/hysteria) | 22.8k | MIT | Hysteria2；QUIC、抗丢包；现有 HY2 节点来自它 |
| [TrustTunnel/TrustTunnel](https://github.com/TrustTunnel/TrustTunnel) | 3.5k | Apache-2.0 | AdGuard 开源的“像 HTTPS 的 VPN”协议；服务端 Linux/macOS；客户端全平台；安装脚本 + 配置向导 + 订阅端点。**2025-11 才创建，1.3.0 还在 beta，抗GFW无公开证据，先观察** |

### F. 运维配套（一个人稳定运行的关键）

| 项目 | Star | 能做什么 | 放在哪 |
|---|---:|---|---|
| [louislam/uptime-kuma](https://github.com/louislam/uptime-kuma) | 93.1k | 探活 + 告警（Telegram/邮件/Webhook） | 一台小机器或群晖；节点定时 push |
| [restic/restic](https://github.com/restic/restic) | 36.9k | 加密增量备份到 S3/B2/本地 | 主控/节点配置每天备份 |
| [sub-store-org/Sub-Store](https://github.com/sub-store-org/Sub-Store) | 10.8k | 多订阅合并/转换 | 只有多台机器、需要合并订阅时才用 |
| [hiddify/hiddify-app](https://github.com/hiddify/hiddify-app) | 33.5k | 全平台客户端，支持 sing-box/Xray/Reality/Hysteria | 给家人/非技术用户的客户端备选 |

---

## 3. 谁最接近“一台电脑 → 个人 VPN”

| 方案 | 一键安装 | 无需域名 | NAT 穿透 | 跨平台服务端 | 订阅 | 运维/告警 | 成熟度 | 结论 |
|---|---|---|---|---|---|---|---|---|
| fscarmen/sing-box | ✅ | ✅ | ⚠️（HY2 Realm） | ❌ 仅 Linux | ✅ | ⚠️ 无备份/告警 | 高（5.9k，活跃） | **无面板首选** |
| 233boy/sing-box | ✅ | ✅ | ❌ | ❌ | ⚠️ 链接为主 | ❌ | 中（更新慢） | 备选 |
| 3x-ui | ✅ | ✅（Reality） | ❌ | ✅ Windows | ✅ 内置 | ✅ Bot/fail2ban | 很高（48.8k） | **稳定 / 有 UI 首选** |
| s-ui | ✅ | ✅ | ❌ | ✅ Win，macOS 实验 | ✅ 内置 | ⚠️ | 中高（10.2k） | sing-box 派 UI 备选 |
| Hiddify Manager | ✅ | ✅ | ❌ | ❌ Ubuntu | ✅ | ✅ 自动备份/Bot | 高 | 多用户才用 |
| Amnezia | ✅ GUI | ✅ | ❌ | ❌ Linux 服务器 | ❌ | ❌ | 高（15.6k） | 非技术用户部署体验最佳 |
| Outline | ✅ GUI | ❌ 需云 | ❌ | ❌ 云主机 | ❌ | ❌ | 高 | 抗封锁弱，不推荐做梯子 |
| TrustTunnel | ✅ | ⚠️ 可自签，推荐域名 | ❌ | ✅ Linux/macOS | ✅ | ❌ | 低（beta） | 观察 |
| Headscale + Tailscale | ⚠️ | ✅ | ✅ | ✅ 全平台客户端 | ❌ | ⚠️ | 高 | **NAT/家里电脑首选** |

---

## 4. 四条可选路线

### 路线 A：3x-ui 单面板（推荐默认，稳定优先）

```
一台电脑（公网 IP，墙外）
  ├─ 3x-ui（单二进制 + SQLite，systemd）
  ├─ Reality(443/tcp) + Hysteria2(443/udp) + 可选 AmneziaWG
  ├─ 内置订阅服务器：一条 URL / 二维码
  └─ 内置 Telegram/Discord Bot + fail2ban
```

- 复用：3x-ui 整个运行时、订阅、监控、升级；不用自己写 admin/Caddy/subconverter
- 我们自己做：**安装预设（默认只开 Reality + HY2）、中文向导、备份/恢复、版本锁定、真实出口验证**
- 适合：一个人、1 台海外机器、希望有网页管理；Windows 也能跑
- 代价：面板是攻击面（只监听 127.0.0.1 + SSH 隧道可解）；Xray 配置项多

### 路线 B：fscarmen/sing-box 无面板（极简优先）

```
一台电脑（公网 IP，墙外）
  ├─ sing-box：Reality(443/tcp) + Hysteria2(443/udp)
  ├─ 一条命令安装 / 升级 / 卸载（sb 菜单）
  └─ 一个订阅 URL（Clash / sing-box / v2ray / Shadowrocket）
```

- 复用：fscarmen 的安装与协议模板（或 233boy 的 CLI 设计）
- 我们自己做：**默认值、中文错误信息、真实出口验证、备份/恢复、一键换密钥**
- 适合：一个人、1 台海外机器、不想碰面板
- 代价：7k 行 bash 依赖；没有面板/告警；仅 Linux

### 路线 C：3x-ui 多节点（2~5 台机器）

```
主控（3x-ui, SQLite）
  ├─ 本机 inbound：Reality + HY2
  ├─ 节点 2/3：装 3x-ui 后用 API 接入（多节点）
  └─ 一个订阅 URL / 二维码 / Telegram Bot
```

- 复用：3x-ui 整个面板 + 订阅 + 监控 + fail2ban
- 我们自己做：安装预设（默认只开 Reality + HY2）、备份、升级锁定、中文向导
- 适合：想要网页管理、或机器 ≥2 台
- 代价：面板攻击面；功能多；Windows 也能跑但生态偏 Linux

### 路线 D：Headscale + Tailscale exit node（电脑在 NAT 后）

```
海外家里的电脑 / 办公室电脑
  └─ Tailscale 客户端 + 开启 exit node
        ↑
国内设备 ── Tailscale/Headscale ──> 出口
```

- 复用：Headscale 控制面 + 官方客户端；零端口、零域名
- 适合：电脑在海外、没有公网 IP（家宽/CGNAT）
- 代价：WireGuard 特征在墙内可能被识别；DERP 中继速度不稳；国内控制面连通性要实测

> 如果电脑在**国内**：以上都救不了。它只能做入口，出口必须是海外机器（现有 T3 借道逻辑）。

---

## 5. 建议的产品形态（个人自用）

**一句话：把“装一个节点”做成一条命令，而不是一个平台。**

```
curl -fsSL https://.../install.sh | bash
  → 检测系统 / 架构 / 公网 IP / 能否直连国外
  → 装运行时（默认 3x-ui；--minimal 用 sing-box）
  → 预设 Reality + HY2，生成一个 client
  → 打印：订阅 URL、二维码、面板地址（面板默认只监听 127.0.0.1）
  → 写入 systemd + 每日备份 + 健康检查

vpn status     # 端口、进程、真实出口 IP
vpn qr         # 当前订阅二维码
vpn rotate     # 换 UUID/密码，踢掉所有设备
vpn backup     # 配置 + 密钥打包（加密）
vpn upgrade    # 锁版本升级，失败自动回滚
vpn uninstall  # 停服务 + 删配置（--purge 才删干净）
```

**从现有仓库保留：**

| 保留 | 原因 |
|---|---|
| `nodekit/templates.py` | sing-box 模式下配置形状的唯一来源，已被 drift 验证；3x-ui 模式下作为默认参数参考 |
| `nodekit/verify.py` | “真起客户端取出口 IP”的判定逻辑，别人家大多只测 TCP/TLS；可移植到 3x-ui 的订阅验收 |
| `nodekit/preflight.py` | 系统/架构/磁盘预检，错误信息是中文 |
| `scripts/drift.py` | 线上配置 vs 模板对账 |
| `scripts/test.sh` | 122 项离线回归 |
| `docs/08-LESSONS.md` | 七条教训，产品化时最值钱的部分 |

**从现有仓库删掉：**

| 删掉 | 原因 |
|---|---|
| `server/admin.py` + `web/index.html` | 3x-ui/s-ui 已经做得更好；自研面板是最大维护负担 |
| `deploy/Caddyfile` + subconverter | 订阅可由 3x-ui/fscarmen 内置；少两个服务 |
| `server/providers/tencent.py` | 个人自用不需要云 API 自动化；手动开防火墙更简单 |
| 多节点 SSH 编排 | 只有 ≥2 台才需要；先不做 |

---

## 6. 许可证与风险（必须先想清楚）

| 风险 | 说明 | 对策 |
|---|---|---|
| **GPL-3.0** | fscarmen、233boy、3x-ui、s-ui、Hiddify、Amnezia 都是 GPL-3.0；当前仓库是 MIT | 不要拷代码进 MIT 仓库；用“安装时下载上游”的方式调用；或整体改为 GPL-3.0 |
| 供应链 | `curl \| bash` 脚本、GitHub 下载二进制 | 锁版本 + SHA256（现有 install.sh 已有）；优先用 release 资产 |
| 面板暴露 | 3x-ui/s-ui 的 Web 面板是攻击面 | 只监听 127.0.0.1 + SSH 隧道，或 Cloudflare Access；强密码 + fail2ban |
| 脚本维护者 | 5k star 的个人脚本可能停更 | 选活跃项目（fscarmen 10-26 仍在更新）；锁版本，不追 latest |
| 新协议 | TrustTunnel 才 1 年、beta | 先不上生产；作为观察项 |
| 物理限制 | 国内电脑不能当海外出口 | 安装时检测并明确拒绝，不制造“连上没网”的节点（现有逻辑已这样做） |

---

## 7. 下一步：需要你确认的三件事

1. **“一台电脑”指哪种？**
   - A. 海外 VPS / 云主机（有公网 IP）
   - B. 海外家里的电脑（NAT 后）
   - C. 国内任意电脑（只能做入口/中转）
2. **要不要网页面板？**
   - 不要 → 路线 A（fscarmen/233boy + `vpn` CLI）
   - 要 → 路线 B（3x-ui）
3. **现在这套生产要不要保留？**
   - 建议先并行：新方案在备用机验证，不改线上；稳定后再决定是否迁移。

> 调研结论：**最值得复用的是 fscarmen/sing-box 的安装与协议层、3x-ui 的面板与订阅层、Headscale 的 NAT 层；最不该继续自研的是面板、订阅转换和云厂商适配。**
