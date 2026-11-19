# 05 - 物理接口与数据契约规范 (Interface Contracts)

> **版本**：v1.0.0 · 2026-11-09  
> **指导原则**：人机协同契约（用户主导意图与边界，系统负责底层协议闭环与物理实现）  
> **核心范式**：强类型输入约束、零敏感信息落盘、结构化自举交付

---

## 一、 腾讯云只读扫描与实例发现契约 `[STATUS: IMPLEMENTED]`

### 接口定义：`POST /api/tencent/instances` 或 `POST /tencent/instances`
* **适用场景**：通过用户创建的最小权限 CAM 子账号，跨新加坡、香港、硅谷、东京等轻量地域并发扫描云主机资产。
* **安全约束**：`secret_id` 与 `secret_key` 仅在单次请求上下文内存中消费，严禁写入磁盘文件、SQLite 或系统日志。若请求体未提供密钥，接口自动回退至服务器本地预置的 `tc.json` 内存读取，前端无需输入即可一键扫描。
* **物理符号实现**：`server/admin.py:H.do_POST` ｜ `server/tencent_discovery.py:discover` ｜ 测试：`tests/test_delivery_contract.py`

#### 1.1 请求体契约 (Request Payload)
```json
{
  "secret_id": "AKIDxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "secret_key": "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
}
```

#### 1.2 成功响应契约 (Response 200 OK)
```json
{
  "ok": true,
  "regions_scanned": 12,
  "instances": [
    {
      "id": "lhins-xxxxxxxx",
      "name": "HK-Lighthouse-01",
      "region": "ap-hongkong",
      "region_name": "中国香港",
      "public_ip": "43.153.56.137",
      "status": "RUNNING",
      "os": "Ubuntu 22.04 LTS",
      "bundle": "1核1G-30Mbps-1024GB",
      "firewall_ready": true
    }
  ]
}
```

#### 1.3 异常响应契约 (Error Response)
```json
{
  "ok": false,
  "code": "TENCENT_AUTH_FAILED",
  "error": "腾讯云密钥无效或缺少只读权限，请检查子账号策略。"
}
```

---

## 二、 目标主机装配与独立面板自举契约 `[STATUS: IMPLEMENTED]`

### 接口定义：`POST /api/addnode` 或 `POST /addnode`
* **适用场景**：在选定目标云服务器后，触发异步安装 Worker，完成环境预检、内核部署与独立 Web 控制台跑起。
* **物理符号实现**：`server/admin.py:run_job` ｜ 测试：`tests/test_delivery_contract.py`, `tests/install-progress.test.js`

#### 2.1 请求体契约 (Request Payload)
```json
{
  "ip": "43.153.56.137",
  "ssh_port": 22,
  "user": "root",
  "auth_type": "password",
  "pass": "UserServerRootPassword123!",
  "name": "香港专线-01",
  "role": "exit",
  "enable_hy2": true,
  "self_bootstrap": true,
  "dry_run": false
}
```
*注：`self_bootstrap: true` 指示装配引擎在目标主机上准备独立 Web 控制台与 Caddy 网关资产。*

#### 2.2 启动任务响应契约 (Response 200 OK)
```json
{
  "ok": true,
  "job": "8f3b2e1a9c0d"
}
```

#### 2.3 任务状态轮询契约：`GET /api/node/job?id=8f3b2e1a9c0d` 或 `GET /api/job?id=8f3b2e1a9c0d`
* **最终完成态响应**（向终端用户交付专属私有资产）：
```json
{
  "ok": true,
  "state": "done",
  "step": 4,
  "stepname": "安装就绪",
  "delivery": {
    "dashboard_url": "https://43.153.56.137:8443/",
    "username": "admin",
    "temp_password": "xK9#mQ2$vL5*pZ8!wR3^",
    "sub_token": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "direct_sub_url": "https://43.153.56.137:8443/s/a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "deep_links": {
      "shadowrocket": "shadowrocket://add/sub://aHR0cHM6Ly80My4xNTMuNTYuMTM3Ojg0NDMvc...==?title=%E9%A6%99%E6%B8%AF%E4%B8%93%E7%BA%BF-01",
      "clash": "clash://install-config?url=https%3A%2F%2F43.153.56.137%3A8443%2Fs%2Fa1b2c3d4...%2Fclash&name=%E9%A6%99%E6%B8%AF%E4%B8%93%E7%BA%BF-01"
    }
  }
}
```

---

## 三、 L1/L2/L3 按需模块动态加载与卸载契约 `[STATUS: IMPLEMENTED]`

### 3.1 极速抢跑模块（L1 - HY2 Toggle）：`POST /api/hy2/toggle`
* **物理符号实现**：`server/nodekit/hy2_service.py` ｜ 测试：`server/nodekit/hy2_service_tests.py`
```json
// Request
{
  "name": "香港专线-01",
  "enabled": true
}
// Response 200 OK
{
  "ok": true,
  "name": "香港专线-01",
  "hy2_enabled": true,
  "port": 443
}
```

### 3.2 国内 BGP 专线中转跳板模块（L2 - Relay Bind）：`POST /api/relay/bind`
* **物理符号实现**：`server/nodekit/relay_service.py` ｜ 测试：`server/nodekit/relay_service_tests.py`
```json
// Request
{
  "name": "北京中转-01",
  "target": "43.153.56.137"
}
// Response 200 OK
{
  "ok": true,
  "name": "北京中转-01",
  "target": "43.153.56.137"
}
```

### 3.3 住宅原生 IP 落地挂载模块（L3 - ISP Mount）：`POST /api/editnode`
* **物理符号实现**：`server/nodekit/node_service.py` ｜ 测试：`tests/isp-mount.test.js`
```json
// Request
{
  "name": "硅谷出海-01",
  "isp_proxy": "socks5://user:pass@residential.isp.provider:1080"
}
// Response 200 OK
{
  "ok": true,
  "node": {
    "name": "硅谷出海-01",
    "isp_proxy": "socks5://user:pass@residential.isp.provider:1080"
  }
}
```

---

## 四、 客户端协议与体验交互契约 `[STATUS: IMPLEMENTED]`

### 4.1 配额与周期自感知响应头（HTTP Header Contract）
* **物理符号实现**：`server/nodekit/subscriptions.py:SubscriptionUserInfo` ｜ 测试：`tests/test_delivery_contract.py`
客户端向 `/s/<token>` 请求订阅时，响应注入标准 `Subscription-Userinfo`：
```http
HTTP/1.1 200 OK
Content-Type: text/plain; charset=utf-8
Cache-Control: no-store
Subscription-Userinfo: upload=10485760; download=21474836480; total=1073741824000; expire=1794700800
```

### 4.2 移动端 URL Scheme 唤醒规范
* **物理符号实现**：`server/nodekit/links.py:build_deep_links` ｜ 测试：`tests/test_delivery_contract.py`
* **iOS Shadowrocket 一键导入**：
  `shadowrocket://add/sub://<BASE64_URL>?title=<URL_ENCODED_TITLE>`
* **全平台 Clash 一键导入**：
  `clash://install-config?url=<URL_ENCODED_SUB_URL>&name=<URL_ENCODED_NAME>`

### 4.3 受控节点与管理中枢直连豁免契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/nodekit/subscriptions.py:render_clash_yaml` ｜ 测试：`server/nodekit/subscriptions_tests.py`
为防止客户端分流规则将海外受控节点/管理面板的访问流量打入代理隧道自身（避免协议切换时隧道自我掐断），Clash 订阅生成器必须在 `rules:` 首部自动注入所有受控节点 IP 及其出口 IP 的 32 位直连规则：
```yaml
rules:
  - IP-CIDR,<node_host_or_ip>/32,DIRECT,no-resolve
```

### 4.4 节点配额与月度重置日数据契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/admin.py:nodes_with_advice`, `server/admin.py:H.do_POST (/api/quota/guard)` ｜ `server/nodekit/quota_guard.py:parse_reset_day` ｜ 测试：`server/nodekit/quota_guard_tests.py`, `tests/node-quota-reset.test.js`
* 接口 `/api/quota/guard` 与 `/api/nodes` 自动归一化解析云 API 返回的计费结算周期（`end`），并向实体注入 `reset_day: int`（1~31）。前端卡片据此呈现 `X日重置`，并彻底剔除冗余计算的剩余流量文本。

### 4.5 系统版本与平滑升级控制面契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/admin.py:H.do_GET`, `server/admin.py:H.do_POST`, `server/nodekit/system_updater.py`, `deploy/upgrade.sh` ｜ 测试：`server/nodekit/system_updater_tests.py`, `tests/test_system_updater_api.py`, `tests/system-updater-ui.test.js`
* **版本查询（支持双前缀）**：
  * `GET /api/system/version` 与 `GET /system/version`：返回 `{"ok": true, "version": "v0.5.0", "commit": "...", "app": "Evergreen · OwnLine"}`。
* **检查更新（内置 1 小时缓存）**：
  * `GET /api/system/check_update[?force=1]` 与 `GET /system/check_update`：后端请求上游 GitHub Releases API 比对语义化版本号，返回：
    ```json
    {
      "ok": true,
      "current_version": "v0.5.0",
      "latest_version": "v0.6.0",
      "has_update": true,
      "changelog": "更新说明文本",
      "published_at": "2026-11-12T00:00:00Z",
      "release_url": "https://github.com/AdgaiWalker/VPN-OwnLine/releases/tag/v0.6.0",
      "cached": false
    }
    ```
* **一键平滑升级**：
  * `POST /api/system/upgrade` 与 `POST /system/upgrade`（受 Basic Auth 保护）：
    * 请求体：`{"target_version": "v0.6.0"}`（可选）
    * 响应体包含 `job_id`，通过 `GET /api/system/upgrade-status?id=<job_id>` 或裸路径查询 `running`、`succeeded`、`failed`。任务 ID 为 32 位十六进制；状态记录保存在数据目录中。
    * 执行链路：独立 systemd 单元拉取代码并在非 Git 部署下备份快照，重启服务后核对健康状态与指定版本；下载、版本核对或自检失败不报告成功。前端只在对应任务成功后刷新。

### 4.6 客户端本地网关 RTT 探活契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/admin.py:H.do_GET (/api/ping, /ping)`, `server/admin.py:H.do_HEAD` ｜ `web/src/js/07b-local-ping.js:probeDeviceLocalLatency` ｜ 测试：`tests/test_ping_api.py`, `tests/local-ping.test.js`
* **适用场景**：供浏览器前端使用原生 `fetch` + `AbortController` 测量当前设备直连管理网关的纯净单跳往返延迟（RTT），消除本地 WiFi/蜂窝抖动的测量盲区，且绝不触发 sing-box Reality 伪装端口跨境重定向兜底。
* **接口规范**：
  * 方法：`GET` / `HEAD`
  * 路径（支持双前缀）：`/api/ping` 与 `/ping`
  * 响应标头：
    * `HTTP/1.1 204 No Content`
    * `Cache-Control: no-store, no-cache, must-revalidate`
    * `Access-Control-Allow-Origin: *`
    * `Content-Length: 0`
  * 空响应体，网络传输载荷 0 字节，消除编解码开销与跨域限制。

### 4.7 本地 Agent 节点纳管任务书与提示词契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`prompt/ssh_setup.md` ｜ `web/src/html/04-modals.html:#ai-ssh-prompt-text` ｜ `web/src/js/03-connection.js:setupAiPrompt` ｜ `README.md` ｜ 测试：`tests/ssh-ai-prompt.test.js`
* **适用场景**：面向具备本地终端执行权限的 AI 编程助手（Cursor / Claude Code / Antigravity 等），提供标准化的任务书输入格式与自治执行边界，实现零人工跑腿的端到端服务器扫雷与节点纳管。
* **输入契约 (Agent Input Payload)**：
  * 用户向 Agent 提供的服务器信息（支持自然语言文本、控制台截图 OCR 文本、邮件原文）：
    * 必填项：目标服务器公网 IP 或域名
    * 认证凭据：初始 root 密码、或者非 root 账户名（如 `ubuntu`/`ec2-user`）与私钥文件路径（如 `~/.ssh/my-key.pem`）
* **执行约束与不变式 (Agent Invariants)**：
  1. **零人工指令**：严禁向用户抛出分步操作要求，必须由 Agent 自主在后台通过 SSH / Shell 运行命令完成；
  2. **系统镜像门禁**：仅支持原版 Ubuntu 22.04 LTS+ 或 Debian 12+，遇到不支持系统应主动报告拦截；
  3. **端口防火墙基准**：必须确保放行 `22/tcp`（管理）、`443/tcp` 与 `443/udp`（Reality/HY2 代理）、`8443/udp`（HY2 备用）；
  4. **权限归一化**：自动确保目标主机开启 `PermitRootLogin yes`，或建立基于 SSH 公钥的免密登录互信，目录权限严格保持 `~/.ssh` 700 与 `authorized_keys` 600；
  5. **终态验真**：接入后必须调用 `server/nodekit/verify.py` 验证端到端出网通畅性。

### 4.8 单双机分级拓扑与专线自愈数据契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/nodekit/node_manager.py`, `server/nodekit/relay_service.py`, `server/nodekit/subscriptions.py` ｜ 测试：`server/nodekit/relay_service_tests.py`, `server/nodekit/node_manager_tests.py`
* **适用场景**：统一纳管单机直连（Reality + HY2 并联降级）与双机中转（Domestic BGP Relay + 故障自愈）的领域模型与订阅生成。
* **数据契约（Node 实体扩展字段）**：
  * `role`: 节点角色枚举，取值 `exit`（海外出口落地）、`relay`（国内中转专线入口）、`standalone`（未绑定的国内独立机）；
  * `landing`: 当 `role == 'relay'` 时的目标海外落地机字典：
    ```json
    {
      "host": "43.153.56.137",
      "port": 443,
      "uuid": "62c6f3ad-d5ef-4458-9073-f7d4a912d7b8",
      "pbk": "3mLI_hMVHkltukgxfvSvMB7DrT2SwAu8J_dsm6GCNwE",
      "sid": "87370495",
      "sni": "www.apple.com"
    }
    ```
  * `landing_primary` / `landing_standby`: 中转自愈的主用与备用海外落地目标主机名；
  * `landing_active`: 当前承载流量的活跃落地目标；
  * `last_failover_ts`: 最近一次故障转移发生的时间戳（Unix 秒数）；
  * `failover_policy`: 包含 `cooldown_seconds: 300`，定义自愈切回主落地的冷却观察期。
* **订阅分发人话命名契约**：
  * 单机模式：`🇺🇸 硅谷直连 (Reality 稳定)` 与 `🇺🇸 硅谷-HY2 (HY2 极速)`；
  * 双机中转模式：`🇨🇳 北京专线 ➔ 🇺🇸 硅谷 (极速防卡顿)` 与 `🇨🇳 北京专线 ➔ 🇸🇬 新加坡 (备用专线)`；
  * 客户端策略组注入带有 `tolerance: 50` 容差的 `url-test` 测速与 `fallback` 故障转移。

### 4.9 AI 业务 IP 粘滞防护与国内 AI 直连规则契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/nodekit/subscriptions.py:render_clash_yaml` ｜ 测试：`server/nodekit/subscriptions_tests.py`
* **适用场景**：面向 OpenAI、Claude、Anthropic、Google AI 等海外严格风控平台，提供 100% 防封号的静态出口保护；面向国内大模型提供 0 代理消耗的快速直连。
* **规则与策略组契约 (Clash YAML Specification)**：
  1. **AI 业务组纯净单选（IP 粘滞不变式）**：
     * `🤖 AI 业务` 策略组必须声明为 `type: select`；
     * 代理列表优先收敛并注入美区/住宅/海外单一稳定节点；
     * **禁止项**：严禁在 `🤖 AI 业务` 中混入 `自动选择`（url-test）或 `🛡️ 故障转移`（fallback），彻底根除跨国 IP 随机漂移与 Session 瞬移；
  2. **国内 AI 服务强制直连**：
     * `DOMAIN-KEYWORD,deepseek,DIRECT`
     * `DOMAIN-KEYWORD,moonshot,DIRECT`
     * `DOMAIN-KEYWORD,kimi,DIRECT`
     * `DOMAIN-KEYWORD,zhipu,DIRECT`
     * `DOMAIN-KEYWORD,doubao,DIRECT`
     * 与现有微信（wechat/weixin）及国内白名单共同构成直连防线，不走海外节点，避免触发国产 AI 区域限制。

### 4.10 反向自举入网凭据（Pre-Auth Token）与免密注册契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/nodekit/join_token.py` ｜ 测试：`server/nodekit/join_token_tests.py`、`tests/test_join_token_api.py`
* **适用场景**：用户纳管自备 Linux VPS 时，无需向控制台输入任何 root 密码或私钥；终端一行 curl 命令自动拉取脚本并在本地生成密钥对，私钥物理不出机，单向 HTTPS 注册并原子核销。
* **API 接口与状态机契约**：
  1. **Token 签发 (`POST /api/node/join-token`)**：
     * 请求：`{"name": "节点名称", "role": "exit" | "relay"}`
     * 响应：包含高熵 `token`、限制 HTTPS 重定向的 `command`、`expires_in`；主控必须有目标机信任的证书。
  2. **自举脚本下载 (`GET /join/<token>`)**：
     * 只读校验 Token 真实性与时效性（15分钟），成功输出动态 Shell 安装脚本；无效或过期返回 404；
  3. **节点入网注册与消费即焚 (`POST /join/register` 或 `POST /api/node/join`)**：
     * 请求：`{"token": "...", "host": "...", "port": 443, "uuid": "...", "pbk": "...", "sid": "...", "sni": "...", "role": "...", "hy2_password": "..."}`
     * 校验逻辑：服务端通过 `consume_token` 线程安全核销 Token（若已被使用过或已过期，立即驳回 HTTP 403，杜绝重放攻击）；
     * 纳管调用：调用 `NodeManager.add_node` 持锁落盘；初始健康状态为 `unknown`，反向自举配置未安装 WARP 时 `warp_enabled` 为 false。自举前拒绝覆盖已有服务或配置，检查证书、生成私密配置、校验并启动成功后才登记；登记失败后已启动服务须人工处理。

### 4.11 落地机 WARP WireGuard 出站与 AI 服务智能清洁分流契约 `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/nodekit/templates.py:exit_config`、`server/nodekit/warp_client.py` ｜ 测试：`server/nodekit/templates_tests.py`、`server/nodekit/warp_client_tests.py`
* **适用场景**：出海出口机免费借道 Cloudflare 官方 WireGuard 清洁 IP，解决普通廉价机房 VPS 被 OpenAI、Claude、Anthropic 拒绝访问或封禁的问题。
* **配置字段与分流规则契约**：
  1. **端点声明 (sing-box 1.11+ / 1.14+ 现代架构)**：当 `warp` 配置存在且为 WireGuard 时，注入 `endpoints: [{"type": "wireguard", "tag": "warp-out", "address": local_address, "private_key": private_key, "peers": [{"address": server, "port": server_port, "public_key": peer_public_key, "allowed_ips": ["0.0.0.0/0", "::/0"]}]}]`；
  2. **路由规则**：常规业务走 `tag: "direct"` 原生网卡出口；针对 `openai.com`、`chatgpt.com`、`oaistatic.com`、`anthropic.com`、`claude.ai` 等高风控域名自动路由至 `warp-out`。

### 4.12 免密反向自举中转配对与高端口契约 (ADR-016) `[STATUS: IMPLEMENTED]`
* **物理符号实现**：`server/nodekit/join_token.py`、`server/admin.py` ｜ 测试：`server/nodekit/join_token_tests.py`
* **契约内容**：
  1. **国内中继端口规范**：当 `role == "relay"` 时，入网 Token 默认监听端口设定为 `8443`（避开非备案 80/443 拦截）；
  2. **中转拉取即成型**：支持在生成 Token 时指定目标海外落地节点元数据，并在动态自举脚本中直接写入 Reality 入站与落地 Outbound 及路由规则，无需主控发起反向 SSH 推送；
  3. **控制边界防护**：`remote_config.check_controllable` 强制校验，未保存 SSH 凭据的反向自举节点禁止发起在线配置改写。

### 4.13 可信安装、归属与发布契约（ADR-018） `[STATUS: IMPLEMENTED]`

本节更新第二节的安装任务与交付条件，公开路径均保留 `/api/*` 和裸路径。

**检查与凭据**：`POST /node/check` 请求保持 `host/username/ssh_port/password/private_key/passphrase/fingerprint`。只有 `result.ready_for_install == true` 且完整身份验证通过时，响应附加 `check_ticket`（64 位十六进制）与 `expires_in: 600`。票据在服务端绑定解析 IP、SSH host key、machine_id、用户与内存凭据；一次性使用，过期和进程重启后重新检查。响应不返回密码、私钥或私钥口令。

**启动安装**：`POST /addnode` 推荐请求：

```json
{"check_ticket":"<64hex>","name":"东京节点","role":"auto","port":443,"self_bootstrap":true,"dry_run":false}
```

旧 SSH 参数仍由同一只读检查适配；必须确认指纹，检查失败时不安装。票据入口不接受客户端替换已检查目标。独立后台保留 TCP 80/8443，代理不能占用；同名节点或同目标并行安装被拒绝。`landing.link` 在主控统一解析为结构化落地参数。演练不放行云端端口、不写目标配置、不交付资产。

**状态与交付**：`GET /node/job?id=<12hex>` 继续返回 `state/step/stepname/health`，错误时增加安全的 `error/error_code`。`done` 的非演练任务要求所有代理记录真实出网通过：

- `self_bootstrap=false`：`delivery={"kind":"managed_node","node_name":"..."}`，不声称存在目标后台。
- `self_bootstrap=true`：部署完整独立后台，目标命名为 `<IPv4用横线连接>.sslip.io:8443`；经固定目标地址的可信 TLS、匿名登录门禁、管理员认证和独立订阅验收后，才返回 `delivery.kind="standalone"` 及第二节其余交付字段。目标订阅令牌独立生成，不回退主控令牌。证书和启动传播采用有限重试。
- 失败或未知结果为 `error`，不返回 `delivery`；重启后的未知任务不自动重装。

**归属和节点组**：节点可持有稳定 `provenance_id`、协议组 `group_id` 及受保护的目标 `control_secret`；这些字段不能作为“已验证”的布尔替代。现网 HMAC、目标标识和配置摘要全部验证后才允许控制；锁内再次确认配置和存证未变。旧未签名服务拒绝控制。主控签名密钥独立于 `sub_token`，令牌轮换不破坏归属。配置回滚必须恢复配套存证。改名不改变协议组，删除、暂停与 HY2 切换按组处理。

**发布**：`GET /system/version` 增加可空 `release_id`（当前进程启动时冻结的归档 SHA-256）。首装与升级共同清单包含所有升级和恢复资源。应用包只接受官方 HTTPS 来源；固定二进制必须与内置摘要一致。完整暂存检查、原子版本交换、外置恢复记录与版本健康探测共同决定升级结果；异常不得留下不完整活动版本。恢复入口独立于被升级目录。生产默认重启前执行归属校验，未知旧部署不得自动补签。

**订阅规则**：所有 Clash 动态标量安全编码，数字外观的协议字符串保持字符串；服务端 WARP 与客户端 AI 组共用域名数据，包含 `chatgpt.com` 主域及子域。本契约只定义路由和验真行为，不保证第三方网站接受任何特定出口 IP。






生产恢复路径为 `/opt/ownline-upgrade/`、`/opt/.web-upgrade-journal.json` 和 `ownline-upgrade-recovery.service/timer`；timer 间隔 20 秒，不接触 SSH 凭据。Linux 目录交换使用 `renameat2(RENAME_EXCHANGE)`，不支持时在切换前失败。macOS 离线回归使用 `RENAME_SWAP`。旧节点迁移只有显式 `adopt_legacy.py --confirm-exclusive` 操作可建立缺失存证；必须匹配事先核对的配置摘要，且不执行服务重启。

### 4.14 旧代理归属迁移范围（ADR-019） `[STATUS: IMPLEMENTED]`

`adopt_legacy.py --scope installation` 为默认完整安装归属检查；`--scope proxy` 只针对本机代理，不检查或修改 Caddy。两者均需要明确独占确认、唯一的本机节点、现网配置 SHA-256 和服务路径一致。`--check-only` 只读且不建立密钥或存证。不同现网摘要或已有不同签名必须拒绝；运行入口不会自动补充旧记录的 `local` 标记或自动签名。卸载不接受代理范围替代完整网关与单元检查。


### 4.15 Mac 本地首装（ADR-020） `[STATUS: IMPLEMENTED]`

本地独立服务仅绑定 127.0.0.1 随机端口；这些接口不是生产 admin 路由。GET `/` 下发页面与 HttpOnly、SameSite=Strict 会话 cookie；其他 GET 必须验证 cookie 和精确 Host。POST 还必须匹配本地 Origin 和 application/json，输入限 150000 字节，拒绝跨站请求；没有 CORS 放行或第三方遥测。

POST `/api/check` 接收 `host/username/ssh_port/password/private_key/passphrase/fingerprint`；首次指纹需人工核对。返回只读 `result`，满足空白首装条件时附加 `check_token`（600 秒一次性内存能力）。POST `/api/install` 接收 `{check_token,confirm:true}`，不接受替换目标，消费票据后返回 202；安装前重新检查身份与条件。单个进程只允许一个安装任务，失败不能重放。

GET `/api/status` 返回 `idle/running/attention/done`。只有目标本地双协议代理出网、服务状态以及 Mac 到目标的可信 HTTPS、登录、订阅均通过，才返回 `done` 和 `delivery`（standalone dashboard_url、username、temp_password、direct_sub_url）。目标侧代理测试不代表 Mac/手机客户端网络路径已验收。未知异常返回固定安全提示，不转发安装原始日志。POST `/api/quit` 仅在非 running 时退出服务；退出丢失内存任务和交付信息，不自动恢复/重装。

### 4.16 状态快照与本地安装阶段（ADR-021） `[STATUS: IMPLEMENTED]`

**状态快照**：admin 新增 GET `/status.json`、`/servers.json`、`/usage.json`、`/quota.json`，以及各自的 `/api/*` 前缀。响应保持文件原有 JSON 结构与 `Cache-Control: no-store`；不存在返回 404，读取或解析失败返回 503，首次改密尚未完成返回 403。对外网关仍负责管理员认证与首次改密跳转。接口不是通用文件读取器，不开放 settings、nodes、tc 或任意路径。目录继续为 0700；新装网关的旧 JSON 路径转发 admin，新页面通过 API 读取，已有网关不自动改写。

**安装消息**：使用 `--setup-stdin` 的 install.sh 在实际步骤开始前，向 stdout 写入完整行 `__OWNLINE_STAGE_V1__:<stage>\n`。远端允许的阶段依次为 `preflight/dependencies/core/deploy/address/config/tuning/firewall/gateway/services/selfcheck`。消息最长 128 字节，支持 SSH 分片；其他输出、未知阶段、缺少换行或过长行不进入用户状态。会话忽略重复或逆序阶段，不假设消息等于代理已验收。

**本地 GET `/api/status`**：沿用 4.15 的会话保护及 `idle/running/attention/done`。开始后增加：

```json
{"state":"running","stage":"dependencies","stage_label":"安装系统依赖和管理网关","elapsed_seconds":83,"stage_elapsed_seconds":65,"stages":[{"code":"upload","label":"传输安装程序","elapsed_seconds":18,"state":"done"},{"code":"dependencies","label":"安装系统依赖和管理网关","elapsed_seconds":65,"state":"running"}]}
```

本地阶段还包括 `recheck/connect/upload/server_verify/delivery_verify/cleanup`。历史只含实际报告的阶段，最多 17 项；示例仅节选。耗时为本机单调时钟的非负整秒，终态冻结。`attention` 的最后阶段状态为 attention，同时返回固定安全的 `message/error_code`；SSH_TIMEOUT、SSH_UNAVAILABLE、SSH_AUTH_FAILED、HOST_KEY_CHANGED 为已知原因，其余为 INSTALL_FAILED，均不转发异常原文。只有全部验收与临时文件清理完成后返回 done 和原交付字段。失败清理不得覆盖原失败阶段。

**页面等待**：状态及普通本地请求上限 15 秒，连接检查上限 90 秒；状态轮询约 3 秒，超时后提示并只读重试，不提交第二次安装。关闭服务后，已在途的状态响应不得恢复密码和交付区。页面重载继续读取同一进程的阶段历史；退出进程仍丢失内存状态，不声称支持任务重启恢复。

### 4.17 Mac 首装的腾讯云实例发现（ADR-022） `[STATUS: IMPLEMENTED]`

本地 POST `/api/tencent/instances` 接收 `{secret_id, secret_key}`，使用与本地连接检查相同的 loopback、Host、Origin 和会话 Cookie 校验，要求 JSON 请求和空闲任务。密钥字段为非空字符串，各自最多 256 字符。响应使用 `Cache-Control: no-store`。

成功返回 `{instances, incomplete_regions}`。实例字段为 `id/name/ip/region/os/state/product`，只包含可用于此入口的公网 IPv4 实例。`incomplete_regions` 列出未完成的产品或地域。全部查询失败返回固定错误码及提示，云端异常文本和凭据不进入响应。

读取仅发起腾讯云 `DescribeRegions` 和 `DescribeInstances`。CVM 优先使用地域管理接口，失败后尝试 CVM 地域接口。轻量应用服务器沿用原地域查询。Mac 在 60 秒查询预算内排入请求，单次 HTTPS 连接超时 20 秒。API 密钥不进入 SSH 检查和安装票据。页面点击实例只填充 `host`，后续沿用 4.15 的 SSH 凭据、指纹检查和安装确认。

[CVM 实例清单](https://cloud.tencent.com/document/product/213/15728) · [轻量实例清单](https://cloud.tencent.com/document/product/1207/47573) · [腾讯云地域管理接口](https://cloud.tencent.com/document/api/1596/77930)
