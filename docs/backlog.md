# Open Backlog & Technical Debt

> 唯一活态未闭环问题账本。仅登记尚未解决的技术债、产品缺口与待外部验真项；一旦闭环即从本表删除对应行（历史由 Git 提交与 `docs/adr.md` 留存）。禁止在本表保留已闭环项，且每项须在 30 天内复核一次 `Last-Reviewed`。

| ID | Priority | Status | Item | Entrypoint | Last-Reviewed |
|---|---|---|---|---|---|
| BL-02 | P1 | VERIFYING | 7 天外网自动拨测数据累积、月底云账单面板实对账与 3–5 名非 CLI 用户零终端盲测（指标：终端打开次数=0，记录停顿超15秒断崖） | `.github/workflows/external-probe.yml, scripts/ops/external_probe.py, server/nodekit/quota_guard.py, docs/plans/2026-11-23-phase4-external-verification.md` | 2026-11-24 |
| BL-06 | P2 | OPEN | 客户端终端到各节点真实直连 RTT（超越控制台网关 RTT） | `web/src/js/07b-local-ping.js, server/probe.py` | 2026-11-24 |
| BL-07 | P2 | OPEN | 国内弱网环境前置测速与无感切换镜像加速 | `deploy/install.sh, ownline.py` | 2026-11-24 |
