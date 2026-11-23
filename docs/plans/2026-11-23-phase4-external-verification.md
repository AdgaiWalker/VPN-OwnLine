# Phase 4 · 真二进制混沌验证与外部环境核验基准

> Status: PARTIAL | Updated: 2026-11-23
> 日期：2026-11-23  
> 目标：以**真实编译二进制（sing-box / caddy / mihomo）**、**Linux 内核网络混沌工具（iptables / tc netem / tcpdump）**、**性质模糊测试（Hypothesis）**与**外部长周期可观测基准**作为独立裁判，替代纯 Mock 单元测试。

---

## 一、真二进制 Docker 混沌实验（`--network none` 离线隔离环境）

构建定义：[Dockerfile.phase4](../../tests/docker/Dockerfile.phase4)  
自动化执行器：[verify_real_binaries.py](../../scripts/verify_real_binaries.py)

### 1.1 固定版本与校验摘要（Linux ARM64 实验镜像 `ownline-phase4-lab:latest`）

| 组件 | 版本 | 校验算法与摘要（arm64） |
|---|---|---|
| `sing-box` | `1.14.4` | `SHA-256`: `436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26` |
| `caddy` | `2.10.2` | `SHA-512`: `6ce061a690312ab38367df3c5d5f89a2e4a263e7300d300d87356211bb81e79b15933e6d6203e03fbf26f15cc0311f264805f336147dbdd24938d84b57a4421c` |
| `mihomo` | `v1.19.34` | `SHA-256`: `daaf78a6240a282cdfd75bcbf98fe321f6bd52765cc29e79f344191198f0b50f` |

容器运行时仅授予 `--cap-add NET_ADMIN --cap-add NET_RAW` 并强制 `--network none`，完全不触碰宿主机端口、文件系统与公网。

### 1.2 六大实测套件与结果

| 套件 | 真实执行对象 | 验证结论 |
|---|---|---|
| Suite 1 · 配置与收敛往返 | `sing-box check -c` + `reconcile` | 全部 9 类模板组合（`exit_direct` / `exit_direct_hy2` / `exit_warp_wg_hy2` / `exit_warp_socks` / `exit_isp_socks_noudp` / `exit_isp_socks_udp` / `exit_isp_http` / `relay_single` / `relay_dual`）通过真实内核语法检查；往返 `diff_configs == []` |
| Suite 2 · 隐身网关与控制面 | `caddy run` + `admin.py` | `:80` 拒绝连接；未认证 `/` 返回 `401` 且不含 `Server` 标头；注入 `nosniff`/`DENY`/`no-referrer`；`/sub` 返回 `404`；`/s/<token>` 返回 `200`；鉴权 `/api/reconcile/status` 与 `/api/nodes` 返回 `200` |
| Suite 3 · 客户端订阅核验 | `mihomo -t -d ...` | `all` / `pro` / `office` / `lite` / `direct` 全部 5 类 Clash YAML 通过真实 `mihomo` 校验（附离线 `/etc/mihomo/geoip.metadb`） |
| Suite 4 · 端到端数据面 | `mihomo` / `sing-box` + 伪装 Caddy + 本地 DoH + 模拟 Webshare | `mihomo -> VLESS Reality`、`mihomo -> Hysteria2 QUIC`、`sing-box Relay -> Exit`、SOCKS5 与 HTTP CONNECT ISP 均实测通畅（出口 `peer_ip == 10.204.0.2`）；通过本地 DoH（`1.1.1.1:443` 经 `isp-out`）完成真实握手；UDP 经非 UDP ISP 在 `sing-box` 服务端被直接拒绝，`udp_escaped == 0` |
| Suite 5 · Fail-Closed 物理零泄漏 | `iptables` + `tcpdump` | 对 ISP 上游分别注入 `DROP`（SOCKS5）与 `REJECT --reject-with tcp-reset`（SOCKS5 & HTTP CONNECT），同时向客户端发起多轮 TCP + UDP 请求；`tcpdump -i lo` 抓包实测目标端口 `native_leak_bytes == 0` |
| Suite 6 · 混沌丢包与真自愈 | `tc netem` + `mihomo fallback` + `verify` + `repair` | 通过 `tc qdisc netem delay 180ms 30ms loss 25%` 实测 HY2 正常完成 HTTP 回显；`iptables` 复位 `:10443/tcp` 后 `mihomo` `fallback` 自动切换至 HY2；`verify.run` + `repair.repair_node` 持真实 `provenance` HMAC 与 `flock` 成功重启恢复（恢复不可用时诚实返回 `ok=False`） |

### 1.3 真二进制曝光并修复的三类真实生产缺陷

1. **Caddy 401 响应仍泄漏 `Server: Caddy`**：仅在 `(app)` 中写 `header -Server` 对 `200 OK` 生效，`basic_auth` 触发的 `401` 走 Caddy 错误路径，仍原样发送 `server: Caddy`。此前被 Cloudflare 边缘代理掩盖；直连/自签环境直接暴露指纹。已通过追加 `handle_errors { header -Server }`（[install.sh](../../deploy/install.sh)、[Caddyfile.example](../../deploy/Caddyfile.example)、[reset_admin_password.py](../../server/reset_admin_password.py)）根除。
2. **Clash `office` / `lite` 订阅无法加载**：`subscriptions.py` 在 `- MATCH,"🛡️ 安全办公"` 与 `- MATCH,"🚀 智能优选"` 内层多写了字面双引号，真实 `mihomo -t` 报错 `proxy ["🛡️ 安全办公"] not found`；此前全靠正则字符串断言的 Mock 测试未能发现。已去掉内层双引号并补齐 5 类配置全检回归。
3. **`repair.py` 在 `sing-box` 宕机时必定误报端口冲突**：`ss -lptn 'sport = :PORT'` 在端口**完全空闲**时仍输出表头 `State Recv-Q Send-Q ...`，导致 `if port_out.strip():` 恒为真且不含 `sing-box`，使真实 Linux 主机在节点真正需要自愈时稳定中止重启。已改用 `ss -lptn -H` 并在 Python 中显式过滤表头行。

---

## 二、性质模糊测试（Hypothesis）与边界加固

测试文件：[test_phase4_property_fuzz.py](../../tests/test_phase4_property_fuzz.py)  
覆盖核心纯函数与边界修复（测试依赖 `hypothesis==6.170.17` 仅装于本地 `.venv`，不污染生产 `requirements.lock`）：

- **`links.parse_isp_proxy` / `links.parse`**：拦截 `":8080:u:p"`、`":8080"`、`user:1234:pass@1.2.3.4:8080` 冒号凭据错认、空白或控制字符主机名及非 ASCII Unicode 数字导致的 `int()` 崩溃。
- **`quota_guard.parse_reset_day`**：拦截 `bool`（如 `True` 不再误返 `1`）、`NaN` / `±Inf` 及非法日历日期（如 `"2026-02-29"`、`"2026-02-31"`、`"foo-bar-15"`），同时正确保留闰日 `"2024-02-29"` / `"2028-02-29"`。
- **`traffic_stats`**：拦截 `NaN` / `Inf` / 负值 / 布尔污染历史快照，并修复 `aggregate_all_traffic_stats` 中当原始 `used` / `total` 含超过 2 位小数时顶栏已用与 `guidance.remaining_gb` 之间最大 `0.01 GB` 的舍入偏差（由 Hypothesis 随机样本直接捕获）。
- **`reconcile.diff_configs` / `canonical_sha256`**：验证 6 类敏感字段在任意随机密钥串下严格脱敏为 `[REDACTED]`，且规范化摘要在任意键序打乱后完全一致。

---

## 三、Day-0 外部与控制面真实基线（2026-11-23）

### 3.1 外部可用性与隐身基线（[external_probe.py](../../scripts/ops/external_probe.py)）

- 探针目标：`https://v.goodloop.si:8443/`（数据落盘至受 `.gitignore` 保护的 `.ops-private/external_probe_history.jsonl`）
- Day-0 首次采样（`2026-11-23T13:33:02+08:00`）：`ok=true`、`status=401`、`rtt_ms=1713.3`、`server_header=cloudflare`、`stealth_ok=true`。

### 3.2 账单与流量内部对账基线（[billing_reconcile.py](../../scripts/ops/billing_reconcile.py)）

- 现网 `walker-sv`（`43.153.56.137`，硅谷主出口）`/opt/web-data/usage.json` 采集戳：`2026-11-23T05:28:01Z`：
  - 当周期已用：`309.49 GB / 512.0 GB`（账单截止 `2026-11-23`，剩余 `1` 天，`remaining_gb = 202.51 GB`，文案处于周期切换安全余量保护模式）。
  - 内部一致性对账（`usage.json` vs `/api/traffic/stats`）：`delta_gb=0.0`、`delta_pct=0.0%`、`reset_day_match=true`、`status=aligned`。

---

## 四、需按真实日历与真机执行的外部核验规程

受限于自然时间跨度与真实外部人员参与，下列 3 项由工具固化并由操作者按周期完成终验：

### 4.1 连续 7 天外部定时拨测（建议通过 `/schedule` 创建）

每 30 分钟（覆盖国内晚高峰 20:00–24:00）本机或外部探测机执行一次，如挂载本机代理监听则附加 `--socks5` 与 `--isp-expected-ip` 验证零出口泄漏：

```bash
.venv/bin/python scripts/ops/external_probe.py \
  --url https://v.goodloop.si:8443/ \
  --socks5 127.0.0.1:7890 \
  --isp-expected-ip 168.158.185.30 \
  --report
```

**达标线（7 天汇总 `--report --days 7`）**：`availability_pct >= 99.0%`、`disconnect_rate_pct <= 1.0%`、`stealth_pass_rate_pct == 100.0%`、`isp_leak_count == 0`。

### 4.2 腾讯云月底/切日账单实对账

在每月重置日前后从腾讯云轻量应用服务器控制台导出或读取流量包已用总量后运行：

```bash
ssh walker-sv "curl -s http://127.0.0.1:8099/api/traffic/stats" > .ops-private/cycle_end_stats.json
.venv/bin/python scripts/ops/billing_reconcile.py \
  --panel-file .ops-private/cycle_end_stats.json \
  --host 43.153.56.137 \
  --official-gb <腾讯云控制台实测GB> \
  --official-reset-day <账单重置日> \
  --strict
```

**达标线**：`status == "aligned"`（`|delta_pct| <= 5.0%` 且 `reset_day_match == true`）。

### 4.3 3–5 名非技术真实用户无提示端到端盲测规程

**招募对象**：3–5 名日常不使用终端与 SSH 的普通用户（覆盖 iOS 小火箭与 macOS/Windows Clash Verge 或 FlClash）。  
**约束**：仅提供面板访问口令（或一条订阅链接）与待测账号；**全程禁止工程师口头提醒步骤**，仅记录卡点。

| 编号 | 独立完成任务 | 成功判据 | 实测耗时（分钟） | 卡点原话记录 |
|---|---|---|---|---|
| U1 | 首次登录改密 -> 识别住宅 IP 挂载区并粘入 Webshare 凭据 -> 一键复制或导入订阅到客户端 | 客户端 5 分钟内成功打开 Google / ChatGPT，且国内微信/代码助手直连不断线 | 待填写 | 待填写 |
| U2 | 判断面板“今日已用 / 剩余天数 / 每月 X 号重置”含义 | 用户准确复述“重置日为每月固定几号”而非倒计时，无误解 | 待填写 | 待填写 |
| U3 | 识别并应对“疑似故障或流量预警”状态 | 用户无需看服务器日志，能根据面板卡片状态准确采取自愈或联系管理员 | 待填写 | 待填写 |

**收敛准则**：若 ≥2 名测试者在同一文案/按钮处卡顿超过 90 秒或产生理解错误，将该卡点录入下一轮文案与 UI 精简项。
