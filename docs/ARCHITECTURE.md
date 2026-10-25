# 实现细节

设计理由见 [00-WHY.md](00-WHY.md)，这里只讲"具体怎么接起来的"。

## 组件与端口

| 组件 | 端口 | 职责 |
|---|---|---|
| Caddy | 80 / 8443 | TLS、Basic Auth、静态页、订阅路由 |
| admin.py | 127.0.0.1:8099 | 节点增删改、安装任务、任务日志流 |
| subconverter-ng | 127.0.0.1:25500 | vless 列表 → clash / v2ray |
| sing-box | 443 | 本机也是一个节点 |
| probe.timer | — | 每 60 秒探活 |
| usage-refresh.timer | — | 每 10 分钟拉流量 |

## 数据文件

| 文件 | 写入者 | 内容 |
|---|---|---|
| `nodes.json` | admin.py | 节点列表 |
| `servers.json` | usage_refresh.py | 云上实例（含 provider、region、到期）|
| `usage.json` | usage_refresh.py | 以 **IP 为键**的流量与到期 |
| `status.json` | probe.py | 探活结果 |
| `tc.json` | 人工 | 云密钥（可选，没有就只支持手动）|

## 订阅是怎么生成的

```
nodes.json ──render()──> Caddyfile 里那条 rewrite 的 url= 参数
                            │
                /s/<token> ─┴─> subconverter ──> clash / v2ray
```

每次节点变动，admin.py 会把节点列表重新拼成 `vless://...|vless://...` 写进 Caddyfile
（先 URL 编码），然后 reload Caddy。**节点参数不存数据库，只存这一处。**

## 安装任务模型

```
POST /api/addnode  →  {job: "abc123"}      立刻返回
GET  /api/job?id=  →  {state, step, log}   每 800ms 轮询
```

`addnode.sh` 在 stdout 打 `STEP 1..4 <描述>`，admin.py 逐行读、累进 log。
**不能用 $(...) 捕获输出**，否则会等脚本全部结束才显示，进度条就没了。

任务状态存在内存，**重启 admin 会丢**——前端要能处理"任务不存在"，否则会卡在"安装中"。

## 探活判定

```
TCP 连不上        → reason=port   前端显示「端口没放行」
TCP 通，TLS 失败  → reason=tls    前端显示「服务没起来」
两者都通          → ok=true + 耗时
```

探活不是 Reality 客户端，服务端会记一条 `REALITY: processed invalid connection`——**这是正常的**。

## 安装脚本的四步

```
STEP 1 连接服务器      密码/端口/架构（含一次自动重试）
STEP 2 下载 sing-box    4 个源依次试，每个下完立即 sha256sum 校验
STEP 3 安装并启动      解压、写配置、systemd、放行本机防火墙、装控制公钥
STEP 4 检查端口        从主控回连，判断是否被云防火墙挡住
```

第 4 步失败会触发 `providers.open_port()`，能自动开就开，不能就提示手动。

## 控制通道

安装完成后，`addnode.sh` 会把主控的公钥 `/root/.ssh/node_ctl.pub` 写进节点的
`authorized_keys`。之后所有操作（改名、改端口、换密钥、删除）都走这把钥匙，**不再需要密码**。

密码只在"第一次接入"时用一次。
