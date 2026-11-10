# 05 - 物理接口与数据契约规范 (Interface Contracts)

> **版本**：v1.0.0 · 2026-11-09  
> **指导原则**：人机协同契约（用户主导意图与边界，系统负责底层协议闭环与物理实现）  
> **核心范式**：强类型输入约束、零敏感信息落盘、结构化自举交付

---

## 一、 腾讯云只读扫描与实例发现契约 `[STATUS: IMPLEMENTED]`

### 接口定义：`POST /api/tencent/instances` 或 `POST /tencent/instances`
* **适用场景**：通过用户创建的最小权限 CAM 子账号，跨新加坡、香港、硅谷、东京等轻量地域并发扫描云主机资产。
* **安全约束**：`secret_id` 与 `secret_key` 仅在单次请求上下文内存中消费，严禁写入磁盘文件、SQLite 或系统日志。
* **物理符号实现**：`server/tencent_discovery.py:discover` ｜ 测试：`tests/test_provider_daemon_architecture.py`

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
