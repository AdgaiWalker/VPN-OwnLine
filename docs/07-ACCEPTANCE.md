# 验收清单

分两种：**你自己搭完怎么验**，和 **AI 帮你搭完你怎么验**。

---

## 一、人工验收（照着敲，每条都有明确结果）

### 基础

| # | 命令 / 动作 | 期望 |
|---|---|---|
| 1 | `systemctl is-active caddy admin sing-box` | 三个都 `active` |
| 2 | `curl -s -o /dev/null -w '%{http_code}' https://v.example.com/` | **401** |
| 3 | 浏览器输密码打开 | 页面正常，节点列表出现 |
| 4 | `curl -s -o /dev/null -w '%{http_code}' https://v.example.com/sub` | **404** |
| 5 | `curl -s -o /dev/null -w '%{http_code}' https://v.example.com/s/0000000000` | **404** |

### 订阅

| # | 命令 | 期望 |
|---|---|---|
| 6 | `curl -s -A 'Clash' https://v.example.com/s/<token> \| grep -c 'reality-opts'` | 等于节点数 |
| 7 | `curl -s https://v.example.com/s/<token> \| base64 -d \| grep -c '^vless://'` | 等于节点数 |

### 节点

| # | 动作 | 期望 |
|---|---|---|
| 8 | 手机扫码导入 | 节点全部出现，能连 |
| 9 | 面板上删掉一个节点 | 列表少一个，订阅也少一个 |
| 10 | 面板上改节点名 | 名字变了，流量数字不串（ADR-004 的验证点）|

### 自动化

| # | 动作 | 期望 |
|---|---|---|
| 11 | 加一台新机器，密码故意输错 | 弹"密码不对"，可点"自动重置并重装" |
| 12 | 加一台没开端口的腾讯云机器 | 自动开防火墙，最后是绿点 |
| 13 | 手动关掉某台机器的 sing-box | 60 秒内变红，且提示"服务没起来" |
| 14 | `systemctl start usage-refresh` | `usage.json` 的 `_ts` 更新 |

---

## 二、AI 交付验收

让 AI 按提示词搭完之后，**不要看它说得多好，看这五条**：

### 1. 它能自己证明跑通了吗

要求它贴出：

```
curl -s -o /dev/null -w '%{http_code}' https://你的域名/          → 401
curl -s -A 'Clash' https://你的域名/s/你的token | head -20        → 有 proxies
```

**只给截图不给命令输出的，一律打回。**

### 2. 危险操作有防护吗

在页面上故意试试：

- 打开"添加节点"，**不应该**有默认选中的机器
- 选一台已经在用的机器，**应该**弹二次确认
- 点"删除"，**应该**是弹层而不是浏览器原生 confirm

### 3. 失败会说人话吗

故意输错密码 → 应该告诉你"密码不对，去控制台重置"，而不是 `Error 500` 或 `Permission denied (publickey)`。

**AI 最容易偷懒的地方就是这个**：把异常直接抛给用户。

### 4. 厂商耦合在哪儿

问它一句：**"如果我把服务器换成阿里云，哪些代码要改？"**

- 合格答案：改 `providers/`，加一个文件
- 不合格答案：要改 `admin.py` / 前端 / 安装脚本

### 5. 它有没有偷偷简化

对照 [03-FAILURE-MODES.md](03-FAILURE-MODES.md) 逐条问：

> "国内机器连不上 GitHub 你怎么处理？"
> "探活显示红但服务是好的，怎么区分？"
> "日志会不会撑爆磁盘？"

答不上来的，说明它只是抄了个骨架。

---

## 三、一条命令的总验收

```bash
bash scripts/verify.sh https://v.example.com 你的用户名 你的密码 你的token
```

输出全绿才算过。脚本在 `scripts/verify.sh`。
