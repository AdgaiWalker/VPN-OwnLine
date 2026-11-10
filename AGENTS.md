# 给 AI Agent 的最高行动纲领与开发法典 (AGENTS.md)

> **版本**：v2.0.0 · 2026-11-10  
> **适用范围**：所有在此仓库中进行架构设计、文档研究、代码开发与运维排障的 AI Agent。  
> **核心哲学**：**“做成家用电饭煲，绝不做成飞机驾驶舱”** —— 插电、放米、按煮饭。消灭工程师自嗨与技术黑话，按需双向唤醒，开箱即用。

---

## 一、 战略与产品定位铁律 (Strategic Baseline)

1. **去中心化自备云主机，坚决不当商业机场**：
   * 本项目是 **“去中心化私有云网络装配工具与资源整合编排器”**。
   * 用户自备服务器（腾讯云轻量/AWS等），资产 100% 归用户所有，100% 独享纯净原生 IP。
   * **严禁编写任何中心化代理中转、多租户翻墙流量转发、商业化代付或代收费逻辑**。平台零 CapEx，零法律连带风险。
2. **极简体验与按需唤醒 (Progressive Demand Awakening)**：
   * **否决生活场景标签**：严禁给节点添加“看剧专用/ChatGPT专用”等过度设计的虚假标签，坚持以真实地理区域（硅谷/香港/新加坡）与网络属性（直连/专线中转/HY2极速）命名。
   * **双向唤醒原则**：平时界面极度克制；弱网丢包时**系统主动提醒**一键开启 HY2/专线；或由用户在对话框表达意图（如外贸防封），**Agent 负责精准映射**并调配 L3 住宅原生 IP 模块。
3. **双门户彻底隔离**：
   * 访客端（User Portal）仅暴露一键直连、订阅获取、真实测速与小白客户端指引。
   * 运维控制台（Admin Console）必须经过管理员凭据认证，方可解锁节点调度、中转级联与底层日志。

---

## 二、 架构基准与代码真理 (CodeGraph & Architectural Anchors)

在动手写任何代码或分析架构前，**必须遵循以下物理约束**：

1. **优先调用 CodeGraph MCP 确立真理**：
   * 严禁依赖模糊内存或大范围盲目 Grep 瞎猜代码调用链。
   * 涉及核心逻辑变更前，必须使用 `codegraph_explore` 探测真实符号调用拓扑与**爆炸半径 (Blast Radius)**。
2. **控制面收敛于 `NodeManager`**：
   * 节点数据的所有增删改查、中转绑定、HY2 开关，必须经由 [`server/nodekit/node_manager.py`](file:///Users/happy/Desktop/梯子/仓库/server/nodekit/node_manager.py) 的 `NodeManager` 接口。
   * 严禁绕过排他文件锁（`flock`）直接读写 `nodes.json`，彻底杜绝并发写文件截断与竞争。
3. **安全自愈铁律（HMAC-SHA256 存证校验）**：
   * 目标服务器包含 `/etc/sing-box/.evergreen-provenance.json` 存证文件。
   * 任何自动化脚本在对目标服务器执行 `systemctl restart sing-box` 或解除端口占用的高危自愈操作前，必须通过 [`server/nodekit/provenance.py: verify_provenance`](file:///Users/happy/Desktop/梯子/仓库/server/nodekit/provenance.py) 校验存证签名。
   * **非本系统专属签名的进程绝不擅自越权干涉**，严禁误杀用户同机运行的其他私有业务。
4. **自签名通用证书规范**：
   * 生成 Hysteria 2 证书时，必须调用 `generate_self_signed_cert_pem` 生成 RSA 2048 跨平台兼容证书，禁止采用 sing-box 不兼容的非标证书格式。

---

## 三、 研究与交付的“双轨同步机制” (Dual-Track Sync)

彻底消灭“文档与代码脱节断层（Doc-Code Drift）”：

1. **原子级同提交（Atomic Commit Rule）**：
   * 任何改动核心业务接口（`admin.py`、`addnode.sh`、`remote_config.py`）的代码，**必须在同一个 Git Commit 中同步更新 [`research/05-interface-contracts.md`](file:///Users/happy/Desktop/梯子/仓库/research/05-interface-contracts.md)**。
2. **ADR 决策只追加不篡改**：
   * 架构路线有重大调整时，在 [`research/04-adr-decisions.md`](file:///Users/happy/Desktop/梯子/仓库/research/04-adr-decisions.md) 顺序追加新条目（如 ADR-006），保留完整决策演进考古链，禁止直接删改历史决策。
3. **状态诚实性（No False Implementation）**：
   * 尚未编写代码的设想或协议，文档中必须显式标为 `[STATUS: PROPOSED]`；
   * 只有经过单测验证且有真实代码支撑的特性，方可标为 `[STATUS: IMPLEMENTED]`。

---

## 四、 绝对红线与事故血泪教训 (Red Lines)

1. **零敏感凭据落盘**：
   * 腾讯云 `SecretId / SecretKey`、服务器 root 密码，仅限单次 HTTP 请求的内存即时消费，**严禁持久化存储于 `nodes.json`、SQLite 数据库或打印到日志**。
2. **不许“假通过”（No False Greens）**：
   * 命令执行未报错不等于功能可用。
   * 任何修改必须跑通 `./scripts/test.sh`（全量 525+ 项门禁 100% 绿灯）。
   * 涉及现网服务时，必须实际检查端口监听（`ss -tulpn`）、接口响应（HTTP 200/401）与日志流无未捕获异常。
3. **云安全组白名单必查**：
   * 腾讯云轻量服务器默认仅放行 22 端口。部署或交付新节点时，必须前置验证或引导放行 **`80/tcp`（证书申请）、`8443/tcp`（控制面板与订阅）、`443/tcp`（Reality 代理）、`443/udp`（HY2 极速抢跑）**。
4. **首登强制改密安全门禁**：
   * 新服务器初次装配完成，磁盘自动生成 `.initial-password-required`。
   * 网关必须拦截非改密请求并重定向至 `/change-password`。用户修改高强度密码后标记清除，杜绝弱口令公网暴露。
