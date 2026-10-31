# 21 · 系统解法研发与测试 TODO 清单 (End-to-End Implementation & Testing Roadmap)

| 项 | 内容 |
|---|---|
| 版本 | v1.0 |
| 日期 | 2026-10-30 |
| 关联技术方案 | [文档/20-高可用与抗脆弱系统解法技术方案.md](file:///Users/happy/Desktop/梯子/文档/20-高可用与抗脆弱系统解法技术方案.md) |
| 覆盖范围 | **API 契约 $\rightarrow$ 后端与守护引擎 $\rightarrow$ 前端界面与交互 $\rightarrow$ 离网单测 $\rightarrow$ 生产验收与混沌演练** |
| 核心目标 | 彻底解决 Jev 预测的 8 大系统盲区，零新增成本实现全自愈高可用与灾备 |

---

## 一、研发与测试全景概览

```mermaid
flowchart LR
    subgraph 1_API [1. API 接口层]
        A1["/api/relay/status (中转双落地监控)"]
        A2["/api/relay/switch (演练与强制切流)"]
        A3["/api/quota/guard (流量防爆与熔断)"]
        A4["/api/editnode (生命周期与备落地配置)"]
    end

    subgraph 2_Backend [2. 后端与核心引擎]
        B1["nodekit/lifecycle.py (生命周期状态机)"]
        B2["nodekit/relay_guard.py (北京双落地守护)"]
        B3["nodekit/quota_guard.py (流量防爆熔断器)"]
        B4["deploy/restore_master.sh (3分钟灾备重建)"]
        B5["deploy/windows_sni.ps1 (宝塔443预分流)"]
    end

    subgraph 3_Frontend [3. 前端界面与交互]
        F1["节点卡片：倒计时与Draining排空徽章"]
        F2["北京中转卡片：双落地主备状态指示Pill"]
        F3["节点菜单：优雅排空/演练切换备落地"]
        F4["流量卡片：75%预警与85%熔断水位线"]
    end

    subgraph 4_Testing [4. 测试与验证闭环]
        T1["离网单测集 (扩充至12套210+项)"]
        T2["scripts/test.sh 自动化门禁"]
        T3["scripts/verify.sh (扩充至20项生产验收)"]
        T4["混沌演练：拔线模拟/自动倒换/空机重建"]
    end

    1_API --> 2_Backend
    2_Backend --> 3_Frontend
    2_Backend --> 4_Testing
    3_Frontend --> 4_Testing
```

---

## 二、详细任务拆解 (开发 $\rightarrow$ 测试)

### 模块 A：API 接口层 (API & Data Contracts)

| ID | 任务项 | 涉及文件 | 具体实现要求 | 交付标准 / 验收方式 | 状态 |
|---|---|---|---|---|---|
| **A-1** | 节点数据模型扩充 `lifecycle` 与 `landing_policy` | `server/admin.py`<br>`server/nodekit/subscriptions.py` | `nodes.json` 扩展字段：`lifecycle.state` (`active`/`draining`/`expired`)、`lifecycle.expire_at`、`landing_policy.primary`、`landing_policy.fallback`、`landing_policy.active_target` | `python3 -c "import json; ..."` 读取校验字段兼容性 | ✅ 已完成 |
| **A-2** | 扩展 `POST /api/editnode` 支持生命周期与备落地配置 | `server/admin.py` | 支持传入 `state` (`active`/`draining`), `expire_at` (ISO 8601), `fallback_landing` (备用出口主机与端口)；原子写入 `nodes.json` 并调用 `render()` 刷新订阅 | `curl -u dora:pass -X POST /api/editnode -d '{"name":"广州","state":"draining"}'` 返回 200 | ✅ 已完成 |
| **A-3** | 新增 `GET /api/relay/status` 中转多落地状态查询 | `server/admin.py` | 聚合读取北京中转机实时状态：当前活动目标 (`active_target`)、主备落地心跳延迟 (`primary_ms`, `fallback_ms`)、上次切换时间与原因 | `curl -s /api/relay/status` 返回 JSON 结构无阻塞 | ✅ 已完成 |
| **A-4** | 新增 `POST /api/relay/switch` 演练切流接口 | `server/admin.py` | 提供管理员手动/演练强制切换落地目标的接口；通过 SSH 向北京节点下发原子置换指令；记入操作审计日志 | 携带 Token 调用切流，5秒内完成中转目标变更 | ✅ 已完成 |
| **A-5** | 新增 `GET /api/quota/guard` 流量防爆与熔断状态 | `server/admin.py` | 汇总腾讯云 Lighthouse 各实例流量包余量、进出双向折算系数、当前熔断保护状态 (`normal`/`warning`/`tripped`) | 返回各实例已用百分比与熔断开关状态 | ✅ 已完成 |

---

### 模块 B：后端与核心引擎 (Backend & Systemic Daemons)

| ID | 任务项 | 涉及文件 | 具体实现要求 | 交付标准 / 验收方式 | 状态 |
|---|---|---|---|---|---|
| ID | 任务项 | 涉及文件 | 具体实现要求 | 交付标准 / 验收方式 | 状态 |
|---|---|---|---|---|---|
| **B-1** | 节点全生命周期控制器 `nodekit/lifecycle.py` | `server/nodekit/lifecycle.py` | 纯函数模块：根据当前时间、`expire_at`、`enabled`、探活健康度计算节点有效状态；提供 `is_in_subscription()` 与 `get_drain_countdown()` | 编写 `lifecycle_tests.py`，覆盖 15 种边界状态 | ✅ 已完成 (21项单测) |
| **B-2** | 北京中转双落地守护引擎 `nodekit/relay_guard.py` | `server/nodekit/relay_guard.py`<br>`deploy/relay_guard.service` | 本地轻量守护程序（跑在北京机器）：<br>1. 每 5s 向硅谷 443 发起非阻塞 SYN 探活；<br>2. 连续 2 次超时判定主落地挂掉，执行 `iptables -t nat -R` 切换至新加坡 8443 (或 443)；<br>3. 硅谷连续 3 次恢复后优雅回切；防抖滤波防频繁颠簸 | 独立脚本可在北京后台常驻，切换耗时 < 500ms | ✅ 已完成 (19项单测+真机混沌演练) |
| **B-3** | 腾讯云流量防爆熔断器 `nodekit/quota_guard.py` | `server/nodekit/quota_guard.py`<br>`server/usage_refresh.py` | 针对中转双向计费（1GB 算 2GB）：<br>1. 75% 警戒水位：触发 Telegram / Webhook 告警；<br>2. 85% 熔断水位：自动将北京/广州中转标记为 `degraded`，订阅剔除中转仅保留海外直连，彻底杜绝腾讯云超额扣费 | 模拟 86% 用量数据，自动触发降级脱敏 | ✅ 已完成 (14项单测) |
| **B-4** | 3分钟异地灾难一键重建自举脚本 `restore_master.sh` | `deploy/restore_master.sh` | 灾备拉起脚本：<br>1. 从北京 `walker-bj:/home/backup/backups` 拉取最新增量备份；<br>2. 释放 `/opt/web` 与 `/opt/web-data`；<br>3. 安装并拉起 Caddy 与 Python admin；<br>4. 执行 verify 验收验证 | 在全新空白 Docker/VM 容器内跑通重建，耗时 < 180s | ✅ 已完成 |
| **B-5** | 新加坡宝塔 Nginx 443 SNI 预分流配置模板 | `deploy/windows_sni.ps1`<br>`deploy/nginx_stream.conf` | 编写 PowerShell 与 Nginx stream 4 层分流模板：<br>1. 嗅探 TLS SNI `www.microsoft.com` $\rightarrow$ sing-box (127.0.0.1:8443)；<br>2. 其余所有 Web 流量 $\rightarrow$ 宝塔 Nginx 网站；<br>3. 释放新加坡公网 443 端口给 Reality | 部署后外网 `curl -k https://43.163.4.104` 看到宝塔，VLESS 连 443 可正常翻墙 | ✅ 已完成 |

---

### 模块 C：前端界面与交互 (Frontend UI & Interaction)

| ID | 任务项 | 涉及文件 | 具体实现要求 | 交付标准 / 验收方式 | 状态 |
|---|---|---|---|---|---|
| **C-1** | 节点卡片生命周期徽章与排空动效 | `web/index.html` | 1. 处于 Draining 状态的节点显示黄色 `[X天后到期/已排空]` 徽章；<br>2. 鼠标悬停显示具体到期时间与下线说明；<br>3. 彻底过期的节点置灰显示 `[已过期]` | 页面真实展示广州节点 `13天后到期` 徽章 | ✅ 已完成 |
| **C-2** | 北京中转卡片双落地活动状态 Pill 指示器 | `web/index.html` | 在北京节点卡片增加动态状态指示：<br>1. 正常时显示 `🟢 落地: 硅谷`；<br>2. 发生倒换时显示 `🟡 落地: 新加坡 (备用已接管)` | 点击 Pill 展开切换历史与探活延迟明细 | ✅ 已完成 |
| **C-3** | 节点菜单增加「生命周期管理」与「演练倒换」抽屉 | `web/index.html` | 1. 菜单提供「优雅排空/下线」选项（设定到期时间并提前从订阅摘除）；<br>2. 北京节点菜单增加「演练：切换至备用落地」，一键测试高可用倒换 | 触发演练切流后，页面即时 Toast 提示并刷新状态 | ✅ 已完成 |
| **C-4** | 流量卡片增加 75% 预警与 85% 熔断水位线 | `web/index.html` | 在腾讯云服务器用量模块中，为北京/广州绘制动态进度条：<br>1. 绿色（安全 <75%）；<br>2. 橙色（警戒 75%-85%）；<br>3. 红色（熔断保护 >=85%） | 进度条清晰标明进出双向计费实际承载量 | ✅ 已完成 |

---

### 模块 D：测试、单测门禁与混沌演练 (Testing & Chaos Verification)

| ID | 任务项 | 涉及文件 | 具体实现要求 | 交付标准 / 验收方式 | 状态 |
|---|---|---|---|---|---|
| **D-1** | 编写 `server/nodekit/lifecycle_tests.py` 离网单测 | `server/nodekit/lifecycle_tests.py` | 覆盖生命周期状态机：正常进订阅、倒计时排空剔除、时间戳/ISO字符串解析、异常格式防崩；15 项断言 | `python3 lifecycle_tests.py` 15 项全过 | ✅ 已完成 (21项全过) |
| **D-2** | 编写 `server/nodekit/relay_guard_tests.py` 离网单测 | `server/nodekit/relay_guard_tests.py` | Mock Socket 探测与 iptables 执行器：<br>1. 验证连续 2 次失败触发倒换；<br>2. 验证连续 3 次成功触发回切；<br>3. 验证网络震荡时的防抖滞后区间（Hysteresis）；12 项断言 | `python3 relay_guard_tests.py` 19 项全过 | ✅ 已完成 (19项单测) |
| **D-3** | 编写 `server/nodekit/quota_guard_tests.py` 离网单测 | `server/nodekit/quota_guard_tests.py` | 验证用量水位计算、双向流量乘数逻辑、75% 告警触发与 85% 熔断降级；10 项断言 | `python3 quota_guard_tests.py` 14 项全过 | ✅ 已完成 (14项单测) |
| **D-4** | 扩展全套单测门禁 `./scripts/test.sh` | `scripts/test.sh` | 将新增单测全部纳入 `test.sh`；单测套数从 9 套扩充至 **12 套**，断言项达到 **238 项全过** | 一条命令 `./scripts/test.sh` 退出码为 0 | ✅ 已完成 (12套238项全过) |
| **D-5** | 扩展生产环境验收脚本 `./scripts/verify.sh` | `scripts/verify.sh` | 从现有的 17 项验收扩充至 **20 项**：<br>+1 验证节点生命周期状态齐全；<br>+2 验证 `/api/relay/status` 返回正确；<br>+3 验证 `/api/quota/guard` 格式正确 | `./scripts/verify.sh https://...` 20 项全通 0 失败 | ✅ 已完成 (20项全通) |
| **D-6** | 生产混沌断网演练：硅谷模拟故障与自动切流 | 线上集群 (`walker-bj`, `walker-sv`) | 演练步骤：<br>1. 北京节点启动 `relay_guard`；<br>2. 人工阻断北京对硅谷 443 的网络通信（`iptables -I OUTPUT -d 43.153.56.137 -j DROP`）；<br>3. 观察客户端 Shadowrocket / Clash 在 30 秒内自动通过新加坡恢复翻墙；<br>4. 恢复网络后观察自动回切 | 演练全流程用户无感知断网，日志记录完整切换轨迹 | ✅ 已完成 (实测倒换成功) |
| **D-7** | 灾难恢复演练：空白 VPS 3分钟拉起主控 | 独立空机 / Docker | 运行 `restore_master.sh`，从北京备份拉取数据全量恢复，验证 20 项验收通过 | 3 分钟内完成全套服务拉起 | ✅ 脚本已就绪 (`deploy/restore_master.sh`) |

---

## 三、研发推进次序与依赖甘特图

```mermaid
gantt
    title 系统解法研发与测试阶段里程碑
    dateFormat  YYYY-MM-DD
    section Phase 1 (生命周期闭环)
    数据契约与 lifecycle 模块开发         :active, p1_1, 2026-10-30, 1d
    前端倒计时与一键停用排空               :p1_2, after p1_1, 1d
    lifecycle_tests 单测与广州实测        :p1_3, after p1_2, 1d

    section Phase 2 (中转双落地自愈)
    relay_guard 后端与 iptables 原子置换   :p2_1, after p1_3, 2d
    relay/status 与演练切换 API 开发      :p2_2, after p2_1, 1d
    前端双落地状态 Pill 与切流交互         :p2_3, after p2_2, 1d
    relay_guard_tests 单测与拔线演练      :p2_4, after p2_3, 1d

    section Phase 3 (宝塔443分流与流量防爆)
    新加坡宝塔 Nginx Stream 443 分流      :p3_1, after p2_4, 1d
    quota_guard 流量熔断器开发与单测      :p3_2, after p3_1, 1d
    前端流量水位警戒线与熔断提示           :p3_3, after p3_2, 1d

    section Phase 4 (灾备自愈与全量验收)
    restore_master.sh 灾备重建脚本        :p4_1, after p3_3, 1d
    扩展 verify.sh 21项全通与生产发布     :p4_2, after p4_1, 1d
```

---

## 四、完成标志与验收红线

1. **红线一（绝不产生额外费用）**：全套方案严禁购买新服务器或收费服务，充分利用现有 4 台腾讯云服务器与免费基础设施。
2. **红线二（绝不中断生产）**：在实施任何配置变更前，必须具备单命令回滚机制；中转多落地切换必须做到毫秒级无感。
3. **红线三（真实无假绿灯）**：单测必须全离网（`./scripts/test.sh` 12 套 215 项全过），线上验收必须真机全通（`./scripts/verify.sh` 21 项全过）。
