# 提示词 ①：装

> 用法：把 `<尖括号>` 里的内容换成你的，整段粘进 harness。
> 需要 harness 能执行命令（Claude Code / Codex / Cursor / 类似），纯聊天的不行。

---

# 任务

在一台新买的腾讯云轻量服务器上部署 ladder 主控（面板 + 订阅 + 探活）。
你负责执行，我负责提供参数和确认。

# 我提供

- 服务器 IP：`<IP>`
- 登录方式：`<root 密码 / 私钥文件路径>`
- 域名：`<域名>`

# 开始前先确认三件事，有一条不满足就停下来告诉我，不要继续

1. 能 ssh 登录，系统是 Ubuntu 22.04+ 或 Debian 12+
2. 域名已在 Cloudflare：A 记录指向这台机器、**代理开启（橙色云）**、SSL/TLS 模式 = **Full**
3. 机器能访问 GitHub

# 执行步骤

1. 拉代码并锁版本（**需要 sudo**，因为 /opt 普通用户写不进去）：

       sudo git clone <仓库地址> /opt/ladder
       cd /opt/ladder && sudo git checkout v0.1.0

   > 必须锁 tag。不锁的话，装出来的东西和我验收时看到的不是同一份。

2. **先装订阅转换 subconverter-ng**（安装脚本会检查它，没有会直接停下）：
   按 `docs/DEPLOY.md` 第 2 步下载，解压到 `/opt/subconv/`，
   确认 `/opt/subconv/subconverter-ng` 存在且可执行。

3. **先干跑，把输出贴给我，等我确认**：

       cd /opt/ladder && sudo ./deploy/install.sh <域名> --dry-run

4. 我说「继续」之后真装：

       sudo ./deploy/install.sh <域名>

5. 把脚本结尾打印的四样东西复述给我一次（这是唯一允许出现密码的地方）：
   面板地址 / 账号 / 密码 / 订阅地址（从订阅地址末尾取出 token）

6. **加第一台节点**（用面板或 `POST /api/addnode`）。
   如果这台机器就是我唯一的一台，**跳过这一步并告诉我**——订阅检查会自动跳过。

7. **等 60 秒**，让探活跑完一轮（它每分钟跑一次，没有这一轮状态文件是空的）。

8. 运行验收，**把完整输出原样贴给我，不要总结**：

       cd /opt/ladder && ./scripts/verify.sh https://<域名> admin <密码> <订阅token>

   > 如果第 6 步跳过了，这次验收会显示「0 条节点，跳过订阅内容检查」——
   > 那是正常的。等加了第一台机器再跑一次。

# 边界

- 只允许动：`/opt/ladder`、`/opt/web`、`/opt/sing-box`、`/opt/subconv`、`/etc/caddy`、`/etc/systemd`
- **不要动机器上已有的其他服务**（宝塔、nginx、数据库等）
- 除第 4 步外，不要在输出里打印任何密码、密钥、token
- 任何一步失败就**停下来，把原始报错贴给我**，不要自己猜着改

# 完成判据

`verify.sh` 输出 **0 失败** 才算装完。

你说"装好了"不算。我只看 verify 的输出。
