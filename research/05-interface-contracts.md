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
* **物理符号实现**：`server/nodekit/links.py:parse_isp_proxy`、`server/nodekit/node_manager.py` ｜ 测试：`tests/isp-mount.test.js`、`server/nodekit/tests.py`
```json
// Request (支持标准 URL 串、Webshare curl 命令、四段式导出 ip:port:user:pass 或已结构化对象)
{
  "name": "硅谷出海-01",
  "isp": {
    "type": "socks",
    "server": "168.158.185.30",
    "server_port": 6297,
    "username": "dora2026",
    "password": "secretpassword"
  }
}
// 或传入 Webshare 原始导出文本：
// { "name": "硅谷出海-01", "isp": "168.158.185.30:6297:dora2026:secretpassword" }
// { "name": "硅谷出海-01", "isp": "curl --proxy \"http://dora2026:pass@168.158.185.30:6297/\" https://ipv4.webshare.io/" }

// Response 200 OK
{
  "ok": true,
  "node": {
    "name": "硅谷出海-01",
    "isp": {
      "type": "socks",
      "server": "168.158.185.30",
      "server_port": 6297,
      "username": "dora2026"
    }
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

### 4.18 Mac 首装按产品发现云实例（ADR-023） `[STATUS: IMPLEMENTED]`

本地 POST `/api/tencent/instances` 在 4.17 的基础上接受可选 `product`。非空取值为 `cvm` 或 `lighthouse`，只查询对应产品。省略或传 `null` 时查询两种产品。其他值返回 HTTP 400 和 `TENCENT_PRODUCT_UNSUPPORTED`。会话检查、凭据处理和响应字段沿用 4.17。

Mac 页的「腾讯云 CVM」发送 `product: "cvm"`。选定实例后在当前方式内回填 `host`，复用 4.15 的 SSH 检查和安装确认。完整结果只有一台时可直接带入，部分结果仍须用户选择。

### 4.19 多维度流量时序与智能使用规划接口（ADR-024） `[STATUS: IMPLEMENTED]`

管理后台新增 GET `/api/traffic/stats` 与 `/traffic/stats`（支持 Caddy `handle_path` 双前缀归一化）。响应包含 `Cache-Control: no-store` 与当前聚合流量状态：

```json
{
  "total": {
    "today_gb": 1.25,
    "yesterday_gb": 4.50,
    "this_week_gb": 18.30,
    "this_month_gb": 291.50,
    "this_year_gb": 291.50,
    "total_quota_gb": 512.0,
    "guidance": {
      "days_remaining": 2,
      "remaining_gb": 220.5,
      "daily_budget_gb": 110.25,
      "pace": "abundant",
      "badge": "余量极其充裕",
      "text": "离重置还有 2 天，剩余 220.5 GB。日均可用 110.25 GB/天，可随心看高清/测速。"
    }
  },
  "nodes": {
    "43.153.56.137": {
      "host": "43.153.56.137",
      "region": "硅谷",
      "used_gb": 291.5,
      "total_gb": 512.0,
      "start": "2026-10-23",
      "end": "2026-11-23",
      "today_gb": 1.25,
      "yesterday_gb": 4.50,
      "this_week_gb": 18.30,
      "this_month_gb": 291.50,
      "this_year_gb": 291.50,
      "guidance": { ... }
    }
  },
  "updated_at": "2026-11-21T06:30:00Z"
}
```

接口纯函数计算，优先消费 `vnstat --json`（若宿主环境安装了 vnstat），并以 `usage_refresh.py` 记录的时序快照（`traffic_history.json`）作为高可靠通用保底，支持计费周期清零重置检测。前端出海总流量仪表盘通过此接口直出四维使用量与行动指南。

### 4.20 流量传感器单一真理源对齐与住宅出口断路器协议（ADR-025） `[STATUS: IMPLEMENTED]`

1. **传感器单一真理源（SSOT）聚合协议**：
   `aggregate_all_traffic_stats(usage, history, active_nodes=...)` 接收可选的 `active_nodes`。
   - 过滤 `nodes.json` 之外的无效或历史云实例；
   - 总额度 `total_quota_gb`、月度用量 `this_month_gb` 以及 `guidance` 仅计算角色非 `relay` 的活动出海落地机；
   - `guidance.remaining_gb` 严格等于 `total_quota_gb - this_month_gb`，与控制台顶部进度条 100% 像素级对齐；
   - `guidance` 新增 `today_used_gb` 与 `pacing_ratio`（今日偏差比率）字段，用于动态阻尼调节。

2. **住宅代理出口断路路由**：
   sing-box 落地机模板在挂载 `isp` 住宅出站时，`route` 显式设置 `"final": "isp-out"` 与 `[{"outbound": "isp-out"}]`，防止在网络异常或规则未命中时流量静默降级走宿主机原生公网 IP。

### 4.21 链路木桶短板感知与重置语义协议（ADR-026） `[STATUS: IMPLEMENTED]`

1. **节点重置标签规范**：
   节点卡片将 `reset_day` 渲染为 `每月 X 号重置`，与顶栏相对倒计时 `离重置还有 X 天` 形成正交的语义隔离，禁止使用易引起倒计时误读的 `X日重置`。

2. **拓扑木桶短板反馈对象**：
   当链路上存在 `relay` 专线中转机且其中转机剩余配额低于落地机可用余量时，`guidance` 注入 `bottleneck` 对象并触发 `跳板短板预警`：
   ```json
   {
     "is_relay_bottleneck": true,
     "relay_name": "北京",
     "relay_remaining_gb": 10.5,
     "egress_remaining_gb": 213.72
   }
   ```
   提示使用者优先防范跳板熔断。当 `days_remaining <= 2` 时，指引文案强制转为周期切换安全余量警告。

### 4.22 住宅数据面 DoH/UDP 收敛、零泄漏 Clash DNS 与真实代理探活契约（ADR-028） `[STATUS: IMPLEMENTED]`

1. **sing-box 1.14 住宅出站 DNS 与 UDP 边界（`server/nodekit/templates.py`）**：
   - `exit_config(..., isp=...)` 必须注入基于 `https` DoH（`server: 1.1.1.1`, `detour: "isp-out"`, `strategy: "ipv4_only"`）的 `dns` 配置，前置 `sniff` 与 `hijack-dns`，并在 `not (bool(isp.get("udp")) and isp_type != "http")` 时显式注入 `{"network": "udp", "action": "reject"}`，末尾保持 `final: "isp-out"`。
   - `exit_config(..., warp=...)` 在 `route.rules` 前置 `{"action": "sniff"}` 且显式声明 `final: "direct"`。

2. **Clash DNS 防泄漏与 ISP 能力反映（`server/nodekit/subscriptions.py`）**：
   - `render_clash_yaml` 必须包含 `respect-rules: true`、`proxy-server-nameserver`、`direct-nameserver`，默认 `nameserver` 使用境外 DoH（`https://1.1.1.1/dns-query` 等），并按 `nameserver-policy` 分流国内域名；对挂载非 UDP ISP 的 VLESS 节点渲染 `udp: false`。

3. **真实端到端探活、泄漏拦截与控制面 `/api/ping` 契约（`server/nodekit/verify.py`, `server/probe.py`, `server/admin.py`, `server/nodekit/repair.py`）**：
   - `verify.proxy_probe(node)` 通过本机临时 `sing-box` 客户端实测出口 IP 与 TTFB（支持 VLESS Reality 与 Hysteria2）；若挂载 `isp` 后测得出口 IP 仍等于 `node["host"]`，`verify.run` 与 `probe.probe_node` 返回 `isp_leak`。
   - `repair.repair_node` 严格禁止将 `health == "proxy"` 等非 `ok` 状态判定为自愈成功。
   - `GET /api/ping` 返回 `204 No Content`（仅用于客户端网关 RTT 测速）；`POST /api/ping` 触发 `probe.run_probe_cycle` 并返回最新 `status.json`。
   - `ipcheck.py` 优先检测节点 `exit_ip`；`traffic_stats.py` 固定输出 `+08:00` 时区 ISO 时间戳。


### 4.23 抗主动探测隐身网关、后端并发限流与最小权限运行态契约（ADR-029） `[STATUS: IMPLEMENTED]`

1. **隐身 Caddyfile 模板与凭据检查契约（`deploy/install.sh`, `deploy/Caddyfile.example`, `server/reset_admin_password.py`）**：
   - 新生成 Caddyfile 全局配置必须包含 `auto_https disable_redirects` 与 `servers { protocols h1 h2 }`，不得监听 `:80`，并在 `(app)` 内注入 `header -Server`、`header X-Content-Type-Options "nosniff"`、`header X-Frame-Options "DENY"`、`header Referrer-Policy "no-referrer"`，文件权限为 `0640 root:caddy`（存在 `caddy` 组时）。
   - `reset_admin_password.inspect_credentials` 同时严格校验传统 `:80` 模板与无 `:80` 隐身模板，拒绝任何混合、额外站点块或头指令缺失配置；`maintenance.py` 与 `adopt_legacy.py` 复用同一校验入口。

2. **Cloudflare 源站隔离契约（`scripts/ops/cf_origin_lock.sh`）**：
   - 脚本仅操作专用 `OWNLINE-ORIGIN-<port>` 链及 `INPUT` 中 `-p tcp --dport <port>` 跳转规则；显式拒绝操作 `22` 与 `443` 端口，仅放行回环接口/回环地址、`ESTABLISHED,RELATED` 及官方 Cloudflare IPv4/IPv6 CIDR，其余直接 `DROP`。支持 `--enable`、`--disable`、`--status` 及开机回落选项 `--fallback`。

3. **后端 HTTP 并发保护、公共限流与证书规范（`server/admin.py`, `server/nodekit/http_utils.py`, `server/nodekit/remote_config.py`, `server/nodekit/join_token.py`）**：
   - `admin.py` 主循环使用 `HardenedThreadingHTTPServer`（`request_queue_size=64`、`daemon_threads=True`、`max_concurrent_requests=32`，信号量耗尽返回 `503`）。
   - 未鉴权公开路由（`/s/*`、`/sub`、`/join/*`、`/node/join`、`/join/register`）按 `extract_client_ip`（优先 `CF-Connecting-IP`）实施每分钟 60 次滑动窗口限流，超限返回 HTTP `429` JSON；`http_utils.send_json` 统一附带 `X-Content-Type-Options`、`X-Frame-Options` 与 `Referrer-Policy` 标头。
   - `remote_config.generate_self_signed_cert_pem` 与 `join_token.py` 生成 365 天有效期的 RSA 2048 自签证书，新装 HY2 默认 SNI 对齐 `www.apple.com`；`remote_config._build_apply_script` 在目标主机存在 `sing-box` 组时对暂存配置与 `hy2.key` 设置 `0640 root:sing-box`。

4. **systemd 最小权限单元不变式（`deploy/systemd/{sing-box,caddy,admin}.service`）**：
   - `sing-box.service` 以 `sing-box:sing-box` 运行并保留 `ConditionPathExists=!/var/lib/ownline/quota-paused`；`caddy.service` 以 `caddy:caddy` 运行并限定读写 `/var/lib/caddy`；`admin.service` 启用 `ProtectSystem=strict` 与 `StateDirectory=ownline`，全部单元保持与 `maintenance._owned_unit` 完全一致。

### 4.24 声明式状态收敛、节点能力真值源与遗留接口收敛契约（ADR-030） `[STATUS: IMPLEMENTED]`

1. **节点可控能力单一真值源（`server/nodekit/reconcile.py:node_capability` & `GET /api/nodes`）**：
   - `/api/nodes`（及 `admin.nodes_with_advice()`）中每个节点对象必须携带 `capability` 字段：
     ```json
     {
       "mode": "managed | external | reverse_join | windows_frozen | cleanup_pending | invalid",
       "controllable": true,
       "can_reconcile": true,
       "can_mutate_remote": true,
       "can_auto_repair": true,
       "can_quota_stop": true,
       "reason": ""
     }
     ```
   - `source == "external"`、`source == "reverse_join"`、`provenance.is_windows(node)` 与 `cleanup_pending == True` 四类节点的上述 5 项布尔权限必须全部为 `false`，且不得通过 `allow_windows` 等参数绕过；`remote_config.check_controllable`、`repair.repair_node` 与 `quota_guard.supports_quota_control` 在进入任何远端 SSH/脚本流程前优先拦截。

2. **声明式配置比对与收敛 API（`server/admin.py`, `server/nodekit/node_manager.py`）**：
   - `GET /api/reconcile/status`（可选查询参数 `?name=<node_name>`）：调用 `reconcile.inspect_cluster_drift` 执行只读漂移核验，返回 `200` 及 `{ok, in_sync_count, drifted_count, unmanaged_count, error_count, results[]}`；每条 `result` 包含 `actual_sha256`、`desired_sha256`（键序无关规范化摘要）与默认已对凭据字段脱敏的 `diffs[]`（替换敏感值为 `[REDACTED]`）。
   - `POST /api/reconcile/apply`：请求体 `{"name": "<node_name>", "dry_run": true}`；当且仅当显式传入 `"dry_run": false` 时通过 `NodeManager.reconcile_node(..., apply=True)`（内部持锁 `flock`）执行 `apply_config` 下发并在随后立即调用 `verify.run`。若校验未返回 `"ok"`，自动触发 `rollback_config` 并返回 `"status": "rolled_back"`（HTTP `502`）；对不可控节点返回 `"status": "unmanaged"`（HTTP `409`）。

3. **配置漂移检查 CLI 与双布局运行支持（`scripts/drift.py`）**：
   - 原 SSH 往返校验模式 `drift.py <ssh-host...>` 通过 `extract_live_params` 与 `templates.exit_config` / `relay_config` 比对现网运行配置与模板；新增 `drift.py --nodes <nodes.json> [--name <node>] [--reconcile] [--json]` 支持仓库源码布局与部署布局（`/opt/web`）直接检查与受控收敛，发现 `drifted` / `error` / `rolled_back` 时退出码为 `1`。

4. **反向自举最小权限与遗留路径清理不变式（`server/nodekit/join_token.py`, `server/admin.py`）**：
   - `join_token.generate_install_script` 生成的 systemd 单元必须以 `User=sing-box`、`ProtectSystem=strict` 与仅含 `CAP_NET_BIND_SERVICE` 运行；目录 `/opt/sing-box` 权限 `0750 root:sing-box`，`/opt/sing-box/config.json` 与 `hy2.key` 权限 `0640 root:sing-box`。
   - `admin.py` 移除 `_b64`、`_py_patch`、`_ps_patch`、`patch_remote` 死代码，`render()` 保持显式空操作；`deploy/install.sh` 与 `deploy/Caddyfile.example` 不再包含 `subconverter` 配置字段或生效规则。

### 4.25 真二进制混沌门禁、外部 SLA 探测与账单对账契约（ADR-031） `[STATUS: IMPLEMENTED]`

1. **真二进制容器实验门禁（`scripts/verify_real_binaries.py`, `tests/docker/Dockerfile.phase4`）**：
   - 在 `--network none --cap-add NET_ADMIN --cap-add NET_RAW` 容器中对真实 `sing-box 1.14.4`、`caddy 2.10.2` 与 `mihomo v1.19.34` 运行 6 大验证套件：全部通过退出码 `0`，任一套件（含 `tcpdump` 原生泄漏抓包非零字节、`mihomo -t` 错误、Caddy `:80` 开放或 `401` 返回 `Server: Caddy`、`repair_node` 在端口空闲或恢复失败时行为异常）立即失败退出非 0。
   - **Caddy 隐身模板契约补充**：`deploy/install.sh` 与 `deploy/Caddyfile.example` 的 `(app)` 片段必须包含 `handle_errors { header -Server }`；`reset_admin_password.inspect_credentials` 对启用安全标头的新模版同时严格兼容带/不带 `handle_errors` 两种形态。
   - **Clash `MATCH` 规则契约**：`subscriptions.render_clash_yaml` 在全部模式（`all`、`pro`、`office`、`lite`、`direct`）下输出的规则策略名不得包裹额外双引号（如 `MATCH,🛡️ 安全办公` / `MATCH,🚀 智能优选`）。
   - **端口占用检测契约**：`repair.repair_node` 必须使用 `ss -lptn -H 'sport = :{port}'` 并剔除任何 `State` / `Netid` / `Proto` 表头行，确保空端口不被误判为外部占用。

2. **解析与会计稳健性补充契约（`server/nodekit/{links,quota_guard,traffic_stats,verify}.py`）**：
   - `links.parse_isp_proxy` 拒绝空/含空白/含 ASCII 控制字符的主机名，且带 `@` / `//` 的 URL 不进入四段式冒号拆解。
   - `quota_guard.parse_reset_day` 拒绝 `bool`、非有限浮点（`NaN`/`±Inf`）及不存在的公历日期（如 `2026-02-29`），正常接受合法闰日（如 `2028-02-29` -> `29`）与 `1..31`。
   - `traffic_stats` 通过 `_safe_nonneg_float` 免疫 `NaN`/`Inf`/负值/布尔，且 `aggregate_all_traffic_stats` 以舍入后 `round(tot_total, 2) - round(tot_month, 2)` 计算 `guidance.remaining_gb` 对齐顶栏展示；`verify.PROBE_URLS` 允许在隔离自测环境中替换探测目标地址。

3. **外部 SLA 探测与云账单对账工具（`scripts/ops/{external_probe,billing_reconcile}.py`）**：
   - `external_probe.py [--url URL] [--socks5 HOST:PORT] [--isp-expected-ip IP] [--report] [--days 7] [--out PATH] [--json]`：记录 `+08:00` 时区探针结果至 JSONL，汇总窗口内样本数、`availability_pct`、`disconnect_rate_pct`、`p50_ms`、`p95_ms`、`stealth_pass_rate_pct` 与 `isp_leak_count`。
   - `billing_reconcile.py [--panel-file FILE | --panel-gb GB] [--official-file CSV_OR_JSON | --official-gb GB] [--strict] [--json]`：比对面板月用量/重置日与云厂商官方账单，按 `delta_pct <= 5%`（且重置日不冲突）判定 `aligned`、`<= 15%` 判定 `minor_drift`、其余判定 `discrepancy`（退出码 `1`）。

### 4.26 跨平台本地控制引擎 (`ownline.py`)、盲签凭据库与本地诊断契约（ADR-032 / S1） `[STATUS: IMPLEMENTED]`

1. **本地脱敏诊断日志与事件注册表契约（`server/nodekit/local_diag.py`, `docs/02-本地诊断事件表.md`）**：
   - `emit_event(event, detail, *, log_path, severity)` 仅接受 `EVENT_REGISTRY` 中声明的事件码，未注册事件立即抛出 `ValueError`；`docs/02-本地诊断事件表.md` 必须与 `local_diag.render_events_markdown()` 完全一致并受自动化单测强校验。
   - `redact_payload` 与 `redact_text` 在写入 `.ops-private/local_diag.jsonl`（权限 `0600`，单文件上限 `2 MiB` 滚动 `.1`）前强制擦除密码、私钥 PEM、`Basic`/`Bearer` 凭证、`scheme://u:p@host`、Webshare 四段式 `ip:port:u:p`、腾讯云 `AKID...` 及密钥字典键为 `[REDACTED]`，同时保留 `host`、`auth_type`、`code` 等非敏感排障字段。

2. **盲签凭据库契约（`server/nodekit/local_vault.py`, `web/local-vault.html`）**：
   - `BlindVault` 严格纯内存运行，支持 `ssh`、`tencent_api`、`webshare_isp`、`panel_auth` 四种槽位（默认句柄 TTL `600s`，输入请求 TTL `300s`）。
   - 所有对外返回接口（`create_request`、`submit_request`、`request_status`、`describe`、`list_handles`）严禁出现 `password`、`private_key`、`passphrase`、`secret_id`、`secret_key`、`proxy_url` 或 Webshare 账号密码原文；`borrow(handle, expected_slot=...)` 仅限同进程执行器在内存中临时读取，跨槽位调用抛出 `VaultError("VAULT_SLOT_MISMATCH", 400)`，调用 `clear()` 或过期时必须立即就地清空凭据字典。

3. **本地守护 HTTP 扩展端点（`server/local_setup.py`）**：
   - 保持 `LocalSetupGuard`（回环 peer、`Host` 精确匹配、变更/敏感读 Cookie + 同源校验）全覆盖：
     - `GET /vault`：输出单屏盲签输入页面 `web/local-vault.html` 并签发 `HttpOnly; SameSite=Strict` 会话 Cookie。
     - `GET /api/vault/status?id=<req_id>` & `GET /api/vault/handles`：返回请求状态与非敏感摘要。
     - `GET /api/update[?force=1]`：按需触发 `system_updater.check_update` 并记录 `local_update_checked` 事件；页面默认初始化与状态轮询期间不得主动请求该接口。
     - `GET /api/diag/events[?limit=50]`：返回脱敏后的近期本地诊断事件列表。
     - `POST /api/vault/{request,submit,cancel,clear}`：创建请求（`201` 含 `vault_url`）、提交明文换取 `vh_...` 句柄、取消或清理句柄。
     - `POST /api/check` & `POST /api/tencent/instances`：支持传入 `{"vault_handle": "vh_..."}` 在内存借用凭据完成探测并在 `finally` 立即清空临时副本（`/api/check` 采用非销毁借用以支持 `409 HOST_KEY_CONFIRMATION` 指纹核对后重试）。
     - `POST /api/quit`：拒绝中断进行中的安装任务，否则调用 `vault.clear()` 清空全量内存句柄并关闭本地服务。

4. **跨平台 CLI 工具接口与启动器（`ownline.py`, `server/ownline_cli.py`, `启动安装.bat`, `启动安装.command`）**：
   - `python3 ownline.py doctor [--check-update] --json`：离线返回平台、Python >= 3.10、依赖（`paramiko`/`bcrypt`）、三份合成前端文件（`index.html`/`local-setup.html`/`local-vault.html`）、版本与守护进程存活状态。
   - `python3 ownline.py vault request --slot {ssh|tencent_api|webshare_isp|panel_auth} [--hint TARGET] [--mode auto|browser|tty] [--json]`：`auto` 模式下，有桌面环境自动启动本地守护进程并打开 `/vault?req=...`，无桌面环境（如 `OWNLINE_HEADLESS=1` 或 SSH 终端）自动切换 `getpass` 隐身输入，标准输出仅打印 `{"ok": true, "mode": ..., "handle": "vh_...", "summary": {...}}`。
   - 提供 `check --vault-handle`、`tencent-instances --vault-handle`、`install --check-token --confirm`、`status`、`logs`、`events [--markdown]`、`update-check`、`ui`、`serve`、`stop` 全量结构化 JSON 子命令；`deploy/setup-mac.sh` 归档至 `archive/prototypes/setup-mac.sh`。

### 4.27 可插拔能力包、全链路拓扑编排 (`apply`) 与统一 Agent Skill 契约（ADR-033 / S2） `[STATUS: IMPLEMENTED]`

1. **能力包发现与动态金丝雀防泄漏契约（`server/nodekit/capabilities/__init__.py`）**：
   - `CapabilityRegistry.discover()` 自动扫包加载 `CAPABILITY: CapabilitySpec`，删去对应单文件模块即卸载该能力，无需修改调度代码。
   - `CapabilityContext` 通过 `borrow()`、`borrow_panel()` 与 `store_panel_session()` 在本机内存中借用并追踪秘钥金丝雀，执行退出前由 `scrub_output()` 对明文、URL 编码及 Base64 编码的秘钥内容与敏感键执行 `[REDACTED]` 擦除，并在 `finally` 关闭全部连接及清零临时字典。
   - 四项标准生产能力：`panel-password`（支持从首装 RAM `delivery` 无感接管初始改密并返回新 `active_panel_handle`）、`residential-isp`（挂载/解绑 Webshare 出口并剥离后端回显的账密）、`relay-expand`（`reverse_join` / `ssh_managed` 含 `409 HOST_KEY_CONFIRMATION` / `pair_only`）与 `topology-verify`（零漂移、节点探测及订阅双格式验真）。

2. **声明式拓扑编排器与原始明文阻断门（`server/nodekit/topology_plan.py`）**：
   - `assert_plan_has_no_raw_secrets()` 严格拒绝任何携带 `password`/`passwd`/`passphrase`/`private_key`/`secret_key`/`secret_id`/`proxy_url`/`temp_password`/`current`/`new`/`confirm`/`secret` 字段或 PEM/凭据 URL/四段式代理的计划与命令参数，统一抛出 `CapabilityError("RAW_SECRET_FORBIDDEN", 400)`。
   - `execute_topology_plan()` 顺序编排 `panel-password -> residential-isp -> relay-expand -> topology-verify`；当 `rotate_initial_password` 在非 `dry_run` 模式下生成新的 `active_panel_handle` 时，后续步骤自动继承该新句柄；`dry_run=True` 下若首步包含 `panel-password`，后续预览允许面板返回 Caddy `303` 或直连 `403` 初始密码门锁并标记 `deferred_until_password_change: true`。

3. **守护扩展、CLI 子命令与 Agent Skill 契约（`server/local_setup.py`, `server/ownline_cli.py`, `skills/ownline-local/SKILL.md`）**：
   - 本地守护扩展 `GET /api/capabilities`、`POST /api/capabilities/run`、`POST /api/topology/apply`（均受 `LocalSetupGuard` 保护），且 `server/local_setup.py` 对 `paramiko`/`bcrypt` 采用惰性导入以兼容纯标准库环境。
   - `ownline.py` 新增 `cap list [--json]`、`cap run <name> [--param K=V] [--params-json JSON] [--dry-run] [--json]` 与 `apply (--plan FILE | --plan-json JSON) [--dry-run] [--json]`；遇 `HOST_KEY_CONFIRMATION` 返回退出码 `2`。
   - `skills/ownline-local/SKILL.md` 固化跨平台 Agent 操作规程，并在 [02-本地诊断事件表.md](docs/02-本地诊断事件表.md) 同步新增 `capability_*` 与 `topology_plan_*` 共 6 类事件。

4. **真二进制黑盒门禁（`scripts/verify_s2_blackbox.py`）**：
   - 在 `--network none --cap-add NET_ADMIN` 的 `ownline-phase4-lab:latest` 容器中，串联真实 `caddy 2.10.2`、`reset_admin_password.py`、`admin.py`、`sing-box 1.14.4`（DoH over SOCKS5）、`mihomo v1.19.34` 与 `ownline.py` 端到端黑盒实测，验证 `303/403` 门锁、真 Caddy 改密重载、SOCKS5 真实出口 `10.204.0.2`、配置零漂移及 `leaked_secrets=0`。
