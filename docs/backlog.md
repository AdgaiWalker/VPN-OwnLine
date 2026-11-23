# Open Backlog & Technical Debt

> 唯一活态未闭环问题账本。仅登记尚未解决的技术债、产品缺口与待外部验真项；一旦闭环即从本表删除对应行（历史由 Git 提交与 `docs/adr.md` 留存）。禁止在本表保留已闭环项，且每项须在 30 天内复核一次 `Last-Reviewed`。

| ID | Priority | Status | Item | Entrypoint | Last-Reviewed |
|---|---|---|---|---|---|
| BL-01 | P1 | OPEN | 热升级不同步 systemd 单元与 Caddy 配置（B3）：先在 Phase 4 容器实证再改 `release.py` | `deploy/release.py, deploy/systemd/` | 2026-11-23 |
| BL-02 | P1 | VERIFYING | 7 天外网拨测、月底腾讯云账单实对账与 3-5 人盲测（Phase 4 外部核验） | `scripts/ops/external_probe.py, docs/plans/2026-11-23-phase4-external-verification.md` | 2026-11-23 |
| BL-03 | P1 | OPEN | 基于网络体检测出丢包/风控的主动需求唤醒引导（ADR-005 未闭环项） | `server/nodekit/advise.py, web/src/js/07-nodes.js` | 2026-11-23 |
| BL-04 | P1 | OPEN | 自然语言意图到模块装配的映射（ADR-005 未闭环项） | `skills/ownline-local/SKILL.md, server/nodekit/topology_plan.py` | 2026-11-23 |
| BL-05 | P2 | OPEN | 三平台 CI 矩阵（macOS/Windows/Linux）与 CI 补装 `hypothesis`、清理 Node 20 告警（B4） | `.github/workflows/ci.yml` | 2026-11-23 |
| BL-06 | P2 | OPEN | 客户端终端到各节点真实直连 RTT（超越控制台网关 RTT） | `web/src/js/07b-local-ping.js, server/probe.py` | 2026-11-23 |
| BL-07 | P2 | OPEN | 国内弱网环境前置测速与无感切换镜像加速 | `deploy/install.sh, ownline.py` | 2026-11-23 |
