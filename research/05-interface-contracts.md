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
    * 响应体：`{"ok": true, "status": "upgrading", "target_version": "v0.6.0", "message": "升级任务已在后台启动"}`
    * 执行链路：独立后台子进程沙箱拉取代码，校验完整性，备份快照，原子同步至 `/opt/web`（严禁触碰 `/opt/web-data`），重启 `admin.service`，自检通过后完成收敛；若失败自动回滚。前端心跳探活自愈重载。

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



