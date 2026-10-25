# 架构与数据流

## 组件

| 组件 | 端口 | 职责 |
|---|---|---|
| Caddy | 80 / 8443 | TLS 终止、Basic Auth、静态页、订阅路由 |
| admin.py | 127.0.0.1:8099 | 节点增删改、安装任务、任务日志流 |
| subconverter-ng | 127.0.0.1:25500 | 把 vless 列表转成 clash/v2ray 订阅 |
| sing-box（本机）| 443 | 本机也是一个节点 |
| probe.timer | — | 每 60 秒探测所有节点 |
| usage-refresh.timer | — | 每 10 分钟拉腾讯云流量与到期 |

## 为什么端口是 8443

Cloudflare 免套餐只代理 80/443，回源也只能指 80/443。
若不改端口，源站 443 会和节点 443 打架（同一台机器既是面板又是节点）。
所以：**面板走 8443，节点占 443**，Cloudflare 用 Origin Rule 把回源端口改成 8443。

链路完整依赖四项，缺一即挂：

```
1. CF DNS: A 记录 v → 源站 IP，橙色云（已代理）
2. CF SSL: Full（不是 Flexible，会死循环；不是 Full Strict，源站是自签）
3. CF Origin Rule: destination port → 8443
4. 云防火墙: 放行 TCP 8443
```

## 数据文件

| 文件 | 写入者 | 内容 |
|---|---|---|
| `nodes.json` | admin.py | 节点列表（host/port/uuid/pbk/sid/sni） |
| `servers.json` | usage_refresh.py | 云上所有实例（含 region、到期、状态） |
| `usage.json` | usage_refresh.py | 以 **IP 为键**的流量与到期 |
| `status.json` | probe.py | 每个节点的探活结果与耗时 |
| `tc.json` | 人工 | 腾讯云密钥 |

**为什么 usage.json 用 IP 做键**：节点可以改名，IP 不会。改名后流量不会错位。

## 安装任务模型

```
POST /api/addnode  →  {job: "abc123"}        立刻返回，不阻塞
GET  /api/job?id=  →  {state, step, log}     每 800ms 轮询
```

addnode.sh 在标准输出打 `STEP 1..4 <描述>`，admin.py 逐行读、累进 log，
前端据此渲染四步进度条。**不能用 $(...) 捕获输出**，否则会等全部结束才显示。

## 探活判定

```
TCP 连不上        → reason=port  （端口没放行 / 机器失联）
TCP 通，TLS 失败  → reason=tls   （服务没起来）
两者都通          → ok=true，记录耗时
```

注意：探活不是 Reality 客户端，服务端会记一条 `REALITY: processed invalid connection`，
这是**预期行为**（Reality 识别到非法握手后回落到真实网站）。已配 logrotate 控制体积。

## 安全边界

- `/api/*` 全部走 Basic Auth；无认证一律 401
- `/sub*` 直接 404，防止绕过 token 调用转换器
- `/s/*` 非当前 token 一律 404
- 订阅 token 与节点 UUID 相互独立：**换 token 只影响订阅，不踢设备；换 UUID 才踢设备**
