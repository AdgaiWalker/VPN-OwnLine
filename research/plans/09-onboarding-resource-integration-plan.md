# 09 · 从 0 到 1 资源融入产品与安全收口方案

> 状态：A 线 + B1 + B2 + D3 `[STATUS: IMPLEMENTED]`（2026-11-23） · B3 / B4 `[STATUS: PROPOSED]` · 起始基线：`v0.8.1`（`89268a0`）
> 原则：如无必要，勿增实体；产品即说明书；按需显现；先证明再改生产链路。

## 1. 目的

帮零基础用户从「手里没有服务器」开始，以最低成本、零泄密风险搭起自有节点，同时降低作者长期维护负担。

当前问题：选型、端口、家宽、客户端等资源散落在仓库文档里，且部分文档过时或有安全隐患；产品内多处把用户外跳到这些文档。

## 2. 已确认的决策（2026-11-23）

| # | 事项 | 决策 | 理由 |
|---|---|---|---|
| D1 | 本地首装腾讯云发现范围 | 开放轻量应用服务器 + CVM 合并发现 | 产品资料一直推荐轻量服务器，首装却只查 CVM（`web/src/js/local-setup.js:171`），用户会看到空列表。后端 `discover_for_local_setup()` 已支持合并查询与部分结果保留 |
| D2 | 共享美区 Apple ID（`idapp.app`，商家提供） | 保留为主推路径，强化防误操作提示；官方路径（自注册美区账号 + 购买 Shadowrocket \$2.99）折叠为备选 | 账号属于商家，用户自身账号不受影响，且零成本。唯一真实风险是误在系统「设置」顶部登录，导致 iCloud 与「查找」被接管、可被远程锁机或抹除；次要体验风险是商家账号被封后无法更新软件 |
| D3 | 归档 `docs/小白10分钟自建专属节点指南.md` | 归档 | 第 78 行教用户把服务器密码发进 AI 对话，与「凭据不进对话」冲突 |
| D3 | 归档 `deploy/restore_master.sh` | 归档 | 依赖的 `server/backup_remote.sh` 已停用，脚本不可用；执行后会创建 root 无沙箱服务且不写归属签名。面板已有加密备份/恢复 |
| D4 | 推进顺序 | A 线 → B1 冷启动 + B2 改域名脚本修复；B3 先实证 | 先解决用户可见痛点，生产升级链路先证明再动 |

## 3. 已撤回的结论（经代码证伪）

- **Windows 因 `fcntl` 崩溃**：撤回。本地引擎导入闭包不含 `server/nodekit/store.py`；`installations.py` 已对 `fcntl` 做兜底。
- **仅改名「腾讯云（轻量 / CVM）」**：撤回。只改名不改逻辑会误导用户；已由 D1 改为真正开放轻量发现。
- **新增 `onboarding_guide.py` 与 `ownline.py guide` 子命令**：撤回。本地 Agent 在仓库内可直接读文件，无需新命令。
- **「零外跳」验收指标**：改为「核心流程零跳转仓库内过时文档」，官方购买页仍需外跳。

## 4. 范围

### 4.1 本次做

- **A 线**：资源融入产品 + 文档减法（含 D1、D2、D3 文档部分）
- **B1**：发布包冷启动（`ownline.py` 自动进入或自举 `.venv`）
- **B2**：`server/change_domain.sh`、`server/rotate.sh` 权限与加锁写入修复
- **D3 脚本部分**：归档 `deploy/restore_master.sh`

### 4.2 本次不做（单独排期）

- **B3**：热升级不同步 systemd 单元与 Caddy 配置（已确认存在，见 §7），先容器实证与 ADR，再改 `deploy/release.py`
- **B4**：GitHub Actions 三平台矩阵、`hypothesis` 补装（CI 实跑 234 项，本地 242 项）、Node 20 告警清理

## 5. A 线：资源融入产品

### A1 单一数据源

- 新增一份结构化资源数据文件（建议 `web/src/data/onboarding.json`），条目覆盖：
  1. 海外主机选型（免费层 / 高校补贴 / 大促 / 低价年付 / 情报社区）
  2. 系统与端口要求（Ubuntu 22.04+ / Debian 12+；SSH、8443/TCP、443/TCP、443/UDP；自定义域名另需 80/TCP）
  3. 单机直连 vs 国内中转的适用场景
  4. Webshare `Static Residential` 家宽选型与可粘贴格式
  5. 各端客户端（FlClash、Clash Verge Rev、Shadowrocket）与美区账号获取路径（共享账号为主、官方注册为备选）
  6. 可选自定义域名（默认 `sslip.io` 免域名）
- 每条必含：官方链接（无推荐码）、`checked_at` 核实日期、价格只写区间并标注「以官方为准」。
- 扩展 `scripts/build_web.py` 在构建时把片段注入 `web/local-setup.html`、`web/local-vault.html`、`web/index.html`。
- `skills/ownline-local/SKILL.md` 写明该文件路径，Agent 回答「从 0 开始买什么」时只引用该文件内容。

### A2 按需显现（不新增界面、不增加首屏元素）

| 位置 | 触发时机 | 改动 |
|---|---|---|
| `web/src/html/local-setup.html` | 用户展开 | 用默认折叠的「还没有服务器」替换外跳 `docs/server-buying-guide.md` 的链接 |
| `web/src/html/local-setup.html` + `web/src/js/local-setup.js` | 选择腾讯云 | 按钮改为「腾讯云」；去掉写死的 `product = 'cvm'`，合并查询两类实例；列表为空时提示改用 SSH 直连 |
| `web/src/html/local-vault.html` + `web/src/js/local-vault.js` | 仅请求 `webshare_isp` 槽位时 | 显示 Webshare 选型要点与可粘贴格式 |
| `web/src/html/04-modals.html` | 添加节点 / 腾讯云面板 | 替换两处外跳（`#ai-assisted-setup`、`server-buying-guide.md`）为面板内折叠说明 |
| `web/src/html/04-modals.html` + `web/src/js/01-i18n.js` | iOS 客户端未安装 | D2：保留共享账号入口，提示改为「只在 App Store 里登录，千万不要在手机设置最上方登录」与「下载完成后立即退出该账号」；官方路径折叠为备选 |

- `server/ownline_cli.py` 的 `tencent-instances --product` 增加合并选项并设为默认，与网页行为一致。
- 只读 CAM 策略指引需覆盖轻量与 CVM 两类产品的查询接口。

### A3 文档减法（保留已发布版本的链接兼容）

- 归档 `docs/小白10分钟自建专属节点指南.md` → `archive/historical-specs/`。
- `docs/server-buying-guide.md` 原路径保留为短跳转页（`v0.8.1` 已部署的 `index.html` 与 `local-setup.html` 写死链接此路径）。
- `README.md` 补回 `ai-assisted-setup` 锚点（`v0.8.1` 已部署页面链接此锚点），README 只保留价值说明、快速启动与必要链接。
- 收敛 `docs/README.md`（移除 `setup-mac.sh` 等过时描述）与 `prompt/ssh_setup.md`（对齐 `ownline.py install / apply` 闭环），与 `SKILL.md` 同源。

### A4 契约测试

- 注入片段与数据源逐字一致；每条资源含 `checked_at` 与官方链接。
- 旧链接路径仍存在：`docs/server-buying-guide.md`、README `ai-assisted-setup` 锚点。
- 本地首装腾讯云请求不再写死 `product`。
- 网页与任务书中不得出现引导用户在对话中发送密码的文案。

## 6. B 线：冷启动与旁路脚本

### B1 发布包冷启动

- `ownline.py`：若仓库 `.venv` 已就绪且当前解释器不是它，切换到 `.venv` 执行（POSIX `os.execv`；Windows 子进程转发退出码），以环境变量防止递归。
- `.venv` 缺失或依赖不全且命令需要依赖时：按 `requirements.lock` `--require-hashes` 自举（镜像源顺序与 `deploy/install-python-deps.sh` 一致），进度输出到 stderr；`OWNLINE_NO_BOOTSTRAP=1` 可关闭。
- `启动安装.command` 与 `启动安装.bat` 简化为「版本检查 + 调用 `ownline.py ui`」，删除 `.bat` 中重复的 pip 逻辑；`.bat` 支持 `py -3` / `python`。
- 自举失败（无网络等）时输出明确的手动命令，不留死胡同。
- 新增诊断事件 `local_env_bootstrapped` / `local_env_bootstrap_failed`，登记到 `server/nodekit/local_diag.py` `EVENT_REGISTRY` 并同步 `docs/02-本地诊断事件表.md`。

### B2 旁路脚本修复

- `server/change_domain.sh`：替换 Caddyfile 后按 `deploy/install.sh:729-734` 规则恢复 `root:caddy 0640`；`settings.json` 改为持锁原子写（与 `server/nodekit/store.py` 同一锁文件语义）；移除对已不存在的 `:80` 重定向的替换。
- `server/rotate.sh`：写 `settings.json` 时加同一文件锁。
- 实施前确认 `AtomicJsonStore` 写入后保持 `0600`。

### D3 脚本归档

- `deploy/restore_master.sh` → `archive/historical-specs/`；从测试 Shell 语法清单与发布包中移除。

## 7. B3 待实证：热升级配置漂移

- 已确认：`v0.7.0..v0.8.1` 间 `deploy/systemd/{admin,caddy,sing-box}.service` 与 `deploy/Caddyfile.example` 共变更 123 行；`deploy/release.py` 只安装自身恢复单元，不同步业务服务单元。
- 推断（未验证）：老节点升级后，配额暂停条件不在旧 `sing-box.service` 中，重启后代理可能恢复运行并继续计费。
- 下一步：在 `tests/docker/Dockerfile.phase4` 实验室复现「`v0.7.0` 升级」与「全新安装」，比对单元文件、权限与 `systemd-analyze security`；确认后新增 ADR（`PROPOSED`）再改代码。
- 在此之前，不对外宣称老节点升级后具备熔断保护。

## 8. 验收

- `./scripts/test.sh` 全绿（新增契约测试与事件登记测试计入）；`scripts/build_web.py --check` 一致。
- 浏览器 `1280x800` 与 `390x844`：首装页、盲签页（`webshare_isp`）、面板弹窗零控制台错误、零横向溢出；首屏元素数量不增加。
- 无 `.venv` 的临时解压目录中，系统 Python 运行 `ownline.py doctor --json` 自动完成自举并返回 `ok: true`。
- `change_domain.sh` 执行后 `/etc/caddy/Caddyfile` 为 `0640 root:caddy`，`settings.json` 为 `0600`（容器内验证）。

## 9. 文档同步

- L1：`docs/01-变更记录.md` 追加条目，`README.md` 更新测试徽章。
- L2：本地腾讯云发现默认范围、`tencent-instances` 参数与冷启动行为变更，追加 ADR 至 `research/04-adr-decisions.md` 并同步 `research/05-interface-contracts.md`。

## 10. 风险

| 风险 | 缓解 |
|---|---|
| 资源价格与优惠过期 | 只写区间 + `checked_at` + 「以官方为准」；按季度复核数据文件 |
| 合并查询变慢 | 沿用 60 秒上限与部分结果保留；为空时提示 SSH 直连 |
| 自举修改用户环境 | 仅在仓库 `.venv` 内安装，严格哈希校验，可通过环境变量关闭 |
| 归档文件导致旧链接 404 | 原路径保留短跳转页与 README 锚点 |
