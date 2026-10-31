# 长青 · 个人专线 (VPN-OwnLine)

> **把云服务器自动化装配为你个人的专属出海专线**  
> *Turn any cloud VPS into your private, dedicated, and self-healing cross-border line.*  
>
> 项目品牌：**长青 (Evergreen)** · 开源项目：**VPN-OwnLine（个人专线）**  
> 核心文档：[核心文档/01-PRD-产品需求规格说明书.md](docs/核心文档/01-PRD-产品需求规格说明书.md) · [02-产品规划白皮书](docs/核心文档/02-产品规划-产品定位与全流程规划白皮书.md) · [03-技术架构方案](docs/核心文档/03-技术方案-全自动化装配中枢架构方案.md) · [04-工程规范与验收标准](docs/核心文档/04-工程规范与验收标准.md)

---

## 先说给谁

**适合**：

- 手上有 2 台以上服务器，散在不同云 / 不同国家
- 有家人或小团队（2~5 人）共用，但他们不懂技术
- 会一点 Linux，愿意每月花一小时维护
- 在意"节点参数不经过任何第三方"

**不适合**（详见 [docs/06-WHEN-NOT-TO-USE.md](docs/06-WHEN-NOT-TO-USE.md)）：

- 只有一台设备、一个节点 → 直接装客户端
- 需要 10 人以上共用 → 用成熟面板（Marzban 之类）
- 需要商用稳定性 → 用专线
- 不想碰命令行 → 用商业服务

---

## 它解决的到底是什么问题

自建梯子的门槛不在"搭起来"，在**长期维护**：

| 真实痛点 | 这套做法 |
|---|---|
| 加一台机器要 SSH、改配置、重启 | 网页上选机器、输密码、点一下 |
| 装完不知道通不通 | 60 秒自动探活，红灯写明**原因** |
| 换手机要重填一堆参数 | 扫一个二维码 |
| 订阅泄露了收不回来 | 一键轮换 token |
| 国内机器装不上（GitHub 下不动）| 自动切镜像 + SHA256 校验 |
| 换一家云，自动化全部失效 | provider 抽象，加一个文件即可 |

---

## 三条路径，先选再动手

| 路径 | 拓扑 | 成本 | 适用 |
|---|---|---|---|
| **T1** | 单机单节点 | $5/月 | 90% 的人，**不需要本仓库** |
| **T2** | 主控 + 多节点 | $15/月起 | 本仓库实现的形态 |
| **T3** | 自动借道 / 落地分离 | +0 台 | 国内机器自动借道海外节点（已内置，无需单独选角色）|

详见 [docs/01-TOPOLOGY.md](docs/01-TOPOLOGY.md)。

---

> 仓库里的 `web/qr-sub.png` 是占位图，装完跑 `rotate.sh` 会生成真实订阅二维码。

## 架构（T2）

```
              浏览器 / 客户端
                 │  https://v.example.com:8443 或 https://<ip>.sslip.io:8443
                 ▼
          ┌──────────────┐
          │ (可选 CDN)   │  Cloudflare SSL=Full，Origin Rule → 8443
          └──────┬───────┘  或直连 Let's Encrypt 证书
                 │
       ┌─────────▼──────────┐
       │ Caddy (:80/:8443)  │──► admin.py 节点管理 API + 原生内置订阅（Base64 / Clash YAML）
       │  静态页 / 订阅路由  │
       └─────────┬──────────┘
                 │ SSH / 探针
      ┌──────────┼──────────┐
      ▼          ▼          ▼
   节点 A     节点 B     节点 C     sing-box + Reality (443/tcp) & Hysteria2 (443/udp)
```

**核心取舍**：节点 443 独占（TCP Reality + UDP Hysteria2），面板挪到 8443，订阅由 admin.py 原生按 User-Agent 分发 Base64 与 Clash YAML，彻底剔除外部 subconverter 胶水层。

---

## 一键自举部署（首台海外机器）

只要一台全新 Ubuntu 22.04+ 或 Debian 12+ 海外服务器，一条命令全自动完成面板 + 本地出口双协议节点部署：

```bash
curl -fsSL https://raw.githubusercontent.com/AdgaiWalker/ladder-web-panel/main/deploy/bootstrap.sh | sudo bash
```
> 无需提前购买域名：自动基于 `<ip>.sslip.io` 通过 Caddy 申请官方 Let's Encrypt 正式证书；若有自有域名可追加 `--domain v.example.com`。

---

## 目录

```
deploy/
  bootstrap.sh          一键远程自举脚本（拉取仓库并部署）
  install.sh            本地一键安装脚本（环境预检、下载校验、生成节点、开启 BBR、配置服务）
  Caddyfile.example     Caddy 静态反向代理模板
  systemd/              各后台守护进程与定时器 unit 文件

docs/
  00-WHY.md             每个技术选择的理由和代价（ADR）
  01-TOPOLOGY.md        三种拓扑，怎么选
  02-PROVIDERS.md       云厂商接入规范，怎么加一家
  03-FAILURE-MODES.md   14 个真实踩过的坑
  04-SECURITY.md        威胁模型
  05-COSTS-RISKS.md     成本、风险、合规
  06-WHEN-NOT-TO-USE.md 什么时候别用
  07-ACCEPTANCE.md      验收清单（人工 + AI 交付）
  08-LESSONS.md         七个最贵的 bug（只读一页就读这个）
  09-ROLES-AND-SOURCES.md 节点从哪来、坏了怎么读状态
  DEPLOY.md             从零部署
  OPS.md                日常运维与排障
  RESTORE.md            灾难恢复

server/
  admin.py              节点管理 API + 原生内置订阅（Base64 / Clash YAML）
  addnode.sh            单机安装脚本（双协议生成、BBR 开启、防火墙放行、SHA256 校验）
  probe.py              探活（海外直连 + 国内中转双视角探测）
  alert.py              连续失败防抖告警 + 故障恢复通知 + 探针心跳
  backup_remote.sh      跨地域异地自动加密打包备份
  log.sh                运行日志与服务日志查看工具（支持彩色高亮与实时追踪）
  usage_refresh.py      流量与到期刷新
  rotate.sh             订阅 token 轮换（更新 settings.json 与二维码）
  providers/            ★ 云厂商适配层
    base.py             接口定义（含 TCP / UDP 协议支持）
    generic.py          通用兜底（只给手动指引）
    tencent.py          腾讯云轻量实现
    tc3.py              腾讯云签名（无 SDK）

web/index.html          单页面板（无框架、无构建，动态绑定订阅与双视角状态）

prompt/README.md        复刻提示词（可选加速器，不是交付物）
scripts/verify.sh       一条命令验收
scripts/test.sh         跑全部本地单测（全离网）
scripts/drift.py        线上状态与模板配置一致性巡检
```

---

## 快速开始

**需要什么**：一台 Ubuntu 22.04+ 的 VPS（1 核 1G 够）、一个域名、30 分钟。

### 路线 A：把活交给 AI（推荐）

把 [`prompt/install.md`](prompt/install.md) 整段粘进你的 AI harness（Claude Code / Codex / Cursor 等能执行命令的），
填三个参数：服务器 IP、登录方式、域名。剩下的它做，你只看两个输出：`--dry-run` 的预演，和 `verify.sh` 的验收。

装完之后，日常操作用 [`prompt/operate.md`](prompt/operate.md)，出问题用 [`prompt/troubleshoot.md`](prompt/troubleshoot.md)。

> 给 AI 的边界写在 [`docs/AGENT-CONTRACT.md`](docs/AGENT-CONTRACT.md)：能碰哪些路径、什么必须停下来问。

### 路线 B：自己动手

不想让 AI 碰你的机器，就手动来：

```bash
git clone https://github.com/AdgaiWalker/ladder-web-panel.git ladder && cd ladder

# 先看看它会做什么
sudo ./deploy/install.sh v.example.com --dry-run

# 真装
sudo ./deploy/install.sh v.example.com
```

装完会打印面板地址、账号密码、订阅地址。然后：

| 步 | 做什么 | 大约 |
|---|---|---|
| 1 | 域名接到 Cloudflare，Origin Rule 把 8443 改写出去（见 [DEPLOY 第 1 步](docs/DEPLOY.md)）| 10 min |
| 2 | 跑 `install.sh` | 5 min |
| 3 | 手动装 subconverter-ng（脚本会提示）| 3 min |
| 4 | 浏览器打开面板，加第一台机器 | 5 min |
| 5 | 手机导入订阅 | 1 min |
| 6 | 跑 `./scripts/verify.sh` 验收 | 2 min |

**不接 Cloudflare 也能跑**，但源站 IP 会暴露。取舍见 [docs/05-COSTS-RISKS.md](docs/05-COSTS-RISKS.md)。

更细的手工步骤、每一环为什么这么配：[docs/DEPLOY.md](docs/DEPLOY.md)。

---

## 删除一个节点，到底删了什么

这是被问得最多的问题，所以写在 README 里，而不是藏在文档深处。

面板上的「删除」**不等于卸载**。它做的是三件事：

| 动作 | 服务进程 | 开机自启 | 配置文件 | 节点记录 |
|---|---|---|---|---|
| 面板「删除」 | 停止 | 关闭 | **保留** | 删除 |
| 手动卸载 | 停止 | 关闭 | 删除 | 删除 |

- **配置文件还在**：Linux 上是 `/opt/sing-box/`，Windows 上是 `C:\proxy\`。端口也还占着。
  想彻底清掉，手动删目录。PRD 里规划的 `--purge` 参数**还没实现**。
- **想恢复**：面板「删除」只从 `nodes.json` 移除记录，**不会自动归档节点参数**（`--purge` 也还没实现）。
  删之前先备份 `nodes.json`；误删只能重装，重装会换 UUID。
- **重装同一台会换 UUID**，已连接的设备会掉线。这是"重装"和"重启"的区别，别混。


---

## 关于"用 AI 生成"

仓库里有一段 474 字的提示词（[prompt/README.md](prompt/README.md)），能让你快速得到一个雏形。

但要说清楚：**提示词不是交付物**。同一段提示词给不同 AI，出来的是不同代码；
同一个 AI 跑两次也不一样。能复现的是这个仓库的代码。

用提示词的时候，务必配 [docs/07-ACCEPTANCE.md](docs/07-ACCEPTANCE.md) 里的"AI 交付验收"——
尤其是第 4 条：**问它"换成阿里云要改哪里"**，答不上来的说明它只是抄了个骨架。

---

## 云厂商支持

| 云 | 列机器 | 看流量 | 开防火墙 | 重置密码 |
|---|---|---|---|---|
| 腾讯云轻量 | ✅ | ✅ | ✅ | ✅ |
| 任意机器（SSH）| 手动填 | — | 手动 | 手动 |
| 其他云 | 加一个 provider 文件即可（[规范](docs/02-PROVIDERS.md)）|

---

## 免责

- 本项目只提供技术实现，不对使用场景的合法性负责
- 自建涉及成本、封号、被封 IP 等风险，见 [docs/05-COSTS-RISKS.md](docs/05-COSTS-RISKS.md)
- 请自行确认所在地法律法规

MIT License
