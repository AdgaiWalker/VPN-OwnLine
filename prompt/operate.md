# 提示词 ②：用

> 用法：系统装好之后，日常加节点、看状态、换锁都用这段。
> 关键在于：**所有操作都走面板 API，不要直接改文件**。

---

# 上下文

我已经用 `prompt/install.md` 装好了 ladder。

- 面板地址：`https://<域名>/`
- 账号：`admin`
- 密码：`<密码>`

# 规则（重要）

所有操作通过面板 HTTP API 完成。**不要 ssh 上去改 `nodes.json`，不要手改 sing-box 配置。**
理由：面板和 AI 是同一个系统的两个入口，都走 API 才不会出现"两套真相"。

用 Basic Auth 调用：`curl -u admin:<密码> ...`

# 可用接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/nodes` | 当前所有节点（含 health / exit_ip / advice）|
| POST | `/api/addnode` | 加一台机器 |
| POST | `/api/removenode` | 删一个节点，body `{"name":"..."}` |
| POST | `/api/editnode` | 改名 / 改端口 |
| POST | `/api/rotate` | 换订阅 token，先 `{"dry_run":true}` |
| POST | `/api/verify` | 复验某个节点，body `{"name":"..."}` |

# 常见任务怎么做

**「加一台机器」**
先 `GET /api/nodes` 看这台是不是已经加过（按 host 查重）→ 再 `POST /api/addnode` → 最后再 `GET /api/nodes` 确认新节点 `health`。

**「现在哪条能用」**
`GET /api/nodes`，按 health 分三组：能用 / 有问题 / 未验证。每组列出名字和一条建议。
不要说"都正常"这种话——有问题的要指名。

**「换订阅地址」**
先 `POST /api/rotate {"dry_run":true}`，把返回的文案给我看，我确认后再真跑。
换完提醒我：**已连接的设备不受影响，旧链接会立刻失效。**

**「删掉某个节点」**
**先问我确认**，再 `POST /api/removenode`。
删之前提醒我一句：这会停掉那台机器上的服务，但**不会卸载**，配置文件还在。

# 边界

- 删除、换锁这类不可逆动作，**执行前必须问我**
- 不要直接读写 `/opt/web/nodes.json`
- 不要在输出里打印完整 password / pbk / uuid，需要指代时说名字

# 完成判据

每次操作后重新 `GET /api/nodes`，用「改之前 N 条 → 改之后 N 条」两行对比告诉我结果。
