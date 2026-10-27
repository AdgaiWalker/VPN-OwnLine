# 威胁模型

这套系统的边界在哪里，谁能做什么。

---

## 资产分级

| 资产 | 泄露后果 | 保护手段 |
|---|---|---|
| 节点 UUID + Reality 公钥 | 别人能蹭你的流量 | 不公开；只出现在订阅里 |
| 订阅 token | 同上 | 随机 10 位；可一键轮换；旧 token 404 |
| 面板密码 | 能改配置、删节点 | Basic Auth + Cloudflare 前置 |
| 云 API 密钥 | **能删机器**（若给了写权限）| 文件 600；只放在主控 |
| 根域名 + CF 账号 | 整个链路被接管 | 与你日常账号隔离 |

---

## 攻击面

### 1. 面板入口（唯一暴露的管理接口）

```
https://v.example.com  →  Basic Auth  →  单页 HTML
```

- 密码走 bcrypt 存储，Caddy 校验
- 前缀 `/api/*` 同一套认证
- **单因素**。想要更强：Cloudflare Access（邮箱验证）、或加 TOTP

**实际风险**：密码弱 → 被爆破。云上建议开 Cloudflare 的 WAF 或加 IP 白名单。

### 2. 订阅链接（会发给别人）

```
https://v.example.com/s/<token>
```

- token 泄露 = 别人能用你的节点（但不能管理）
- **轮换 token 不会踢掉已连接的设备**（设备上已存了节点参数）
- 真要踢人：换节点 UUID（"更换密钥"）

这个区别很多人搞混，面板上已经分开成两个按钮。

### 3. 节点端口（443）

Reality 的设计就是"看起来是个正常网站"。主动探测拿不到任何东西——
不带正确参数就是一次普通的 TLS 握手，回落到 `www.apple.com`。

**唯一的暴露**：如果攻击者已经知道你的 UUID 和公钥，就能连。所以订阅链接的保密等级 = 节点密码。

### 4. 云 API

只读密钥：只能查。
写权限：能重置密码、开防火墙、**删机器**。

**建议**：如果只是给自己用，写权限可以不给——代价是"密码错了要手动去控制台重置"。

---

## 我们不防的

| 威胁 | 为什么 |
|---|---|
| 你的服务器被云厂商封 | 不在技术可控范围；只能换 IP |
| 定向的流量分析 | Reality 能过被动检测，但扛不住国家级定向分析 |
| 客户端设备被控 | 与服务器无关 |
| 域名被 DNS 污染 | 换域名，或直接用 IP（但 CF 就没法用了）|

---

## 最低限度自查

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://v.example.com/         # 要 401
curl -s -o /dev/null -w '%{http_code}\n' https://v.example.com/sub     # 要 404
curl -s -o /dev/null -w '%{http_code}\n' https://v.example.com/s/0000  # 要 404
stat -c '%a' /opt/web/tc.json                                           # 要 600
```

---

## 网站根目录 = 数据目录，所以要挡掉几样东西

面板把 `/opt/web` 同时当**网站根目录**和**数据目录**用，
所以 `file_server` 会把同目录下的 `.json` 也发出去（有 Basic Auth，但没必要给）。

Caddyfile 里有一段必须保留：

```caddy
@sensitive path /tc.json /nodes.json /retired-nodes-*.json
handle @sensitive {
    respond 404
}
```

| 文件 | 里面是什么 | 挡掉后影响 |
|---|---|---|
| `tc.json` | 云厂商 SecretId / SecretKey | 无（后端自己读，不走 HTTP）|
| `nodes.json` | 所有节点的 UUID / 公钥 / 密码 | 无 |
| `retired-nodes-*.json` | 已删除节点的历史参数 | 无 |

**不能挡的**：`status.json`、`servers.json`、`usage.json`、`quota.json` —— 面板前端直接 fetch 这四个。

> 更好的做法是把数据和网站分到两个目录。目前没做，因为要改后端所有路径常量。
> 在那之前，这条 Caddy 规则是唯一的口子。

---

## 待办：把数据目录从网站根目录拆出去

现在的状态是**堵了口子，没治病**。真正的解法有两个，都还没做：

### 方案 A：改 `root` 指向只读静态目录

```caddy
handle {
    basic_auth { ... }
    root * /opt/web/public      # 只有 index.html / icon.png / qr-sub.png
    file_server
}
```

数据和代码留在 `/opt/web`，但网站根目录只指向 `public/`。
**改动最小**，但要把 `rotate.sh` 里写二维码的路径一起改掉。

### 方案 B：数据搬到 `/opt/web-data`

代码里所有数据路径改成一个常量：

```python
DATA = os.environ.get("LADDER_DATA", "/opt/web-data")
```

涉及 7 个文件：`admin.py`、`probe.py`、`ipcheck.py`、`usage_refresh.py`、
`providers/tc3.py`、`providers/tencent.py`、`nodekit/verify_cli.py`。

Caddyfile 还要给 `status.json` / `servers.json` / `usage.json` / `quota.json`
单独开一条从 `/opt/web-data` 发的路由（面板前端直接 fetch 这四个）。

**更彻底**，但要在生产上停几秒服务，且必须真机验证。

> 2026-10-27 尝试做方案 B，脚本写好了、备份也规划好了，
> 但当时从本机到服务器的 SSH 全部超时（连 github.com:22 也超时，
> 说明是本地网络问题），迁移没有执行。**生产未受任何影响，已确认面板、接口、订阅均正常。**
> 脚本留在跑那台机器上，等 SSH 恢复后再做。
