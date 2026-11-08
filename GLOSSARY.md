# 领域名词字典 (Domain Glossary)

本字典定义 VPN-OwnLine / 长青 系统的统一领域词汇。所有模块、接口设计与文档严禁混用模糊术语（如 "service", "boundary", "component", "API"）。

---

### 1. 核心实体与概念

- **Node (节点)**
  - 拥有 IP、端口与安全配置的单台服务器载体。
  - 属性包括：`name` (名称), `host` (主机名/IP), `port` (入站端口), `role` (角色), `type` (协议类型), `health` (健康状态)。

- **Role (节点角色)**
  - `exit` (出口节点): 部署在海外、直接向最终目标网站发起出网请求的节点。
  - `relay` (中转节点): 部署在国内、接收客户端流量并借道专线转发至海外出口的节点。
  - `standalone` (独立服务器): 未挂载中转专线或海外出口的独立节点，默认不计入出海订阅。

- **Protocol Type (协议类型)**
  - `vless` (Reality): 基于 TCP XTLS-Vision 的隐蔽直连协议，标准端口 443。
  - `hysteria2` (HY2): 基于 UDP QUIC 的极速传输协议，支持端口与混淆密码。

- **Relay Binding (中转借道与倒换)**
  - 中转节点与海外出口节点建立的专线隧道转发关系。
  - `landing` (落地目标): 中转专线所指向的海外宿主出口节点。
  - `landing_policy` (落地策略): 描述倒换策略（如 `fixed` 固定落地，`dual` 双落地高可用）。

- **Egress & ISP Proxy (出网与静态住宅挂载)**
  - `isp` (ISP 代理): 挂载在出口节点下游的住宅 SOCKS5/HTTP 代理，用于规避风控。

- **Quota & Traffic (额度与流量)**
  - `Subscription-Userinfo`: 遵从客户端标准的用户配额与到期信息标头 (`upload`, `download`, `total`, `expire`)。
  - `Host Traffic (保底流量)`: 通过 `/proc/net/dev` 物理网卡 TX/RX 字节统计的真实消耗流量。
  - `Circuit Breaker (流量熔断)`: 当节点流量超出额度设定时自动移出订阅的保护机制。

- **Probe (探活与观测)**
  - `Remote Probe (国内视角探活)`: 借道国内受控节点向各出口测量真实 TCP 握手与 TLS 密钥协商延迟。
  - `Self Probe (内网自测)`: 探活源与探活目标为同一机器时的客观标记。

---

### 2. 架构设计契约 (Codebase Design Principles)

- **Module (模块)**: 具有明确 Interface 与 Implementation 的行为单元。
- **Interface (接口)**: 调用方使用模块所需知晓的一切（类型契约、前置条件、异常模型）。
- **Depth (深度)**: 小接口、深实现。通过紧凑的接口对外提供丰富的行为与杠杆。
- **Seam (接缝)**: 行为可变但无需修改调用方代码的切分点。
- **Adapter (适配器)**: 在接缝处满足接口的具体实现（如各云厂商 Provider 适配器）。
- **Locality (局部性)**: 逻辑、错误处理与状态集中在单一模块，一处修改到处生效。
- **Leverage (杠杆率)**: 调用方通过极简接口获取强大系统能力的倍率。
