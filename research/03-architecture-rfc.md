# 03 - 系统技术方案与去中心化自举架构 RFC (Architecture RFC)

> **版本**：v1.0.0 · 2026-11-09  
> **状态**：PROPOSED / 架构方案征求意见稿  
> **指导哲学**：家用电饭煲哲学（插电、放米、按煮饭；消灭工程师自嗨，开箱即用，按需唤醒）  
> **代码基准**：基于 CodeGraph 索引符号（`NodeManager`、`apply_config`、`provenance`、`Caddy 2.10`、`sing-box 1.11+`）

---

## 一、 系统全景拓扑架构 (System Topology)

系统彻底摒弃传统“中心化多租户共享代理”架构，采用 **“装配母舰控制面 + 去中心化私有子舰独立自举”** 拓扑：

```mermaid
flowchart TD
    subgraph MasterControl["【母舰控制面 / 装配中枢】(Master Node)"]
        direction TB
        M_UI["前端 Web 界面 (web/index.html)"]
        M_Admin["控制核心 (server/admin.py)"]
        M_NodeMgr["NodeManager 深模块 (带 flock 锁)"]
        M_Disc["腾讯云轻量 API 只读发现 (tencent_discovery.py)"]
        M_Pipe["自动化装配任务引擎 (addnode.sh / Job Worker)"]

        M_UI --> M_Admin
        M_Admin --> M_NodeMgr
        M_Admin --> M_Disc
        M_Admin --> M_Pipe
    end

    subgraph TargetVPS["【目标服务器 / 独立自举子舰】(Target Self-Bootstrapped Node)"]
        direction TB
        T_Caddy["Caddy 2.10 (端口 80/8443)<br>• 自动申请/续期 TLS 证书<br>• HTTP Basic Auth 门禁<br>• 隔离反代 8099"]
        T_Admin["私有 admin.py (监听 127.0.0.1:8099)<br>• 专属用户凭据管理<br>• Subscription-Userinfo 注入<br>• 本地 Deep Link 分发"]
        T_Singbox["sing-box 内核 (端口 443 TCP/UDP)<br>• VLESS Reality (偷跑证书)<br>• Hysteria 2 (QUIC 极速抢跑)"]
        T_Guard["QuotaGuard 熔断看门狗<br>• 真实流量采集<br>• 达到阈值自动断网保护"]
        T_Prov["独占签名存证 (/etc/sing-box/.evergreen-provenance.json)"]

        T_Caddy -->|安全反代| T_Admin
        T_Admin -->|本地控制| T_Singbox
        T_Guard -.->|达到阈值休眠| T_Singbox
        T_Prov -.->|HMAC 存证校验| T_Singbox
    end

    subgraph ClientEco["【客户端生态】(Client Ecosystem)"]
        direction LR
        C_iOS["iOS: Shadowrocket (小火箭)<br>Deep Link 自动写入"]
        C_PC["PC/Mac: FLClash / Clash Verge<br>原生 YAML 订阅拉取"]
    end

    M_Pipe ==>|SSH 探针注入 + 克隆自举| TargetVPS
    TargetVPS -->|交付独立私有 URL: https://新IP:8443| MasterControl
    TargetVPS ===>|无感深链接直连| ClientEco
```

---

## 二、 4 阶段全自动自举状态机 (The 4-Stage Bootstrapping Engine)

当用户或 Agent 在控制端触发一台新云服务器的装配时，后台异步作业（Job）严格执行 4 级状态流水线：

```mermaid
sequenceDiagram
    autonumber
    actor Trigger as 用户 / Agent
    participant Master as 装配母舰 (Master)
    participant Target as 目标主机 (Target VPS)
    participant Cloud as 云安全组网关

    Trigger->>Master: 提交新机器 IP + 凭据 (或腾讯云一键发现)
    Note over Master,Target: 【阶段一: 预检与宿主准入】
    Master->>Target: SSH 免密建立，注入轻量只读探针 (node_check)
    Target-->>Master: 确认是空白 Linux (无已有服务冲突) 并回传网络时延
    Note over Master,Target: 【阶段二: 智能依赖与网络自适应】
    Master->>Target: 海外直连测速；若劣化则强行下发清华源 + ghproxy 镜像
    Master->>Target: 并发安装 Systemd、Caddy 2.10、sing-box 1.11+
    Note over Master,Target: 【阶段三: 业务内核与密码学装配】
    Master->>Target: 推送 web/ 静态资产与 server/ 控制核心至 /opt/web
    Master->>Target: 生成 x25519 Reality 密钥对 + RSA 2048 HY2 证书 (generate_self_signed_cert_pem)
    Master->>Target: 本地生成 20 位随机强密码 + Bcrypt 哈希写入 Caddyfile + 注入 HMAC-SHA256 存证 (provenance)
    Master->>Target: 启动 sing-box.service、admin.service 与 caddy.service
    Note over Master,Target: 【阶段四: 交付闭环与自检】
    Target-->>Master: 自检全部核心端口通过 (HTTP 200/401 就绪)
    Master-->>Trigger: 交付专属独立私有 URL (https://新IP:8443/) + 初始密码
```

---

## 三、 L1 / L2 / L3 按需模块分级架构 (Modular Architecture)

为彻底消灭认知过载，系统底层将所有网络特性严格解耦为 3 层积木，**遵循“平时极度克制，需要时按需唤醒”原则**：

```
┌────────────────────────────────────────────────────────┐
│ L3 跨网落地层: 原生静态住宅 IP 挂载                    │
│   • 适用: 跨境电商 / 严风控 AI (Claude) / 海外银行     │
│   • 依赖: 第三方民用 ISP 住宅出口映射 (需外购 IP 资源)│
├────────────────────────────────────────────────────────┤
│ L2 专线拓扑层: 国内 BGP 入口跳板专线 (Relay)           │
│   • 适用: 晚高峰跨海骨干网丢包 / 跨国延迟拉直          │
│   • 依赖: 引入第 2 台国内机器作为中转节点              │
├────────────────────────────────────────────────────────┤
│ L1 基础自举层 (标配): 独立云主机单机自愈闭环           │
│   • 特性: Reality 伪装 + HY2 抢跑 + QuotaGuard 熔断    │
│   • 成本: 零额外费用 (单台轻量云内部纯内核切换)        │
└────────────────────────────────────────────────────────┘
```

1. **L1 级模块（单机基础态 · 标配）**：
   * **VLESS Reality**：作为默认主干入站，偷跑 Apple/Bing 证书，保证平时稳如磐石。
   * **Hysteria 2 极速引擎**：基于 UDP/QUIC 拥塞控制算法，晚高峰丢包场景下按需抢跑带宽。
   * **QuotaGuard**：内核看门狗。月流量达 90% 自动对 sing-box 执行原子级保护停机，杜绝云账单失控。
2. **L2 级模块（专线级联态 · 按需）**：
   * 基于 `RelayService`：将国内 BGP 跳板机与海外落地机进行配置级联，客户端入站连国内节点，内网直达海外出口。
3. **L3 级模块（纯净住宅态 · 按需）**：
   * 基于外部住宅 ISP 端口穿透协议，将落地出口流量无缝导向民用住宅 ASN，彻底消除 IDC 机房欺诈特征。

---

## 四、 核心安全与零信任边界设计 (Security & Zero-Trust)

1. **API 凭据内存即时消费（Ephemeral Secret Handling）**：
   * 无论是腾讯云 `SecretId / SecretKey`，还是主机 SSH 密码，**严禁持久化存储于 `nodes.json`、SQLite 数据库或打印到日志**。单次扫描/装机请求结束后，在 Python 内存中立即解除引用并触发垃圾回收。
2. **HMAC-SHA256 服务独占性存证（Provenance Signature）**：
   * 目标服务器包含 `/etc/sing-box/.evergreen-provenance.json`。
   * 主控中枢在下发任何重启、自愈重载或端口清理操作前，必须通过 `verify_provenance` 校验签名摘要；**非本系统专属签名的进程绝不擅自越权干涉**，杜绝误杀用户同机运行的其他业务。
3. **首登强制改密门禁（First-Login Gate）**：
   * 新服务器安装完成时，磁盘自动创建 `.initial-password-required` 标记。
   * Caddy 网关通过 `forward_auth` 将所有静态与 API 请求拦截重定向至 `/change-password`。用户完成 12 位以上强密码重构后，标记物理清除，完成安全交接。

---

## 五、 客户端一键唤醒与体验闭环 (Client UX Deep Link)

1. **移动端零参数输入（iOS Shadowrocket）**：
   * 采用深链接协议：`shadowrocket://add/sub://<Base64_Encoded_Sub_URL>`。
   * 用户在 Safari 点击后，直接跳起小火箭，静默写入全部节点。
2. **免开网页的配额透明感知**：
   * 订阅响应头强制注入：
     ```http
     Subscription-Userinfo: upload=0; download=17179869184; total=1073741824000; expire=1794700800
     ```
   * 用户无需登录管理后台，直接在小火箭或 Clash 订阅列表下拉刷新，即可秒级查阅当月已用流量与剩余天数。
