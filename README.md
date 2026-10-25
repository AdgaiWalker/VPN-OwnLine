# 网页版个人 VPN（VLESS + Reality）

一个**不用命令行**的个人翻墙系统。打开网页、输密码、点按钮，就能加节点、删节点、换设备、看流量。

为"完全不懂技术的使用者"设计，不是给运维用的。

---

## 它解决什么问题

传统自建梯子的痛点：

| 痛点 | 本项目的做法 |
|---|---|
| 要会 SSH、会改配置文件 | 网页上点按钮 |
| 节点装完不知道通不通 | 60 秒自动探活，红灯写明原因 |
| 换手机要重新导入一堆参数 | 扫一个二维码全部导入 |
| 订阅链接泄露了没法收回 | 一键作废旧订阅 |
| 密码忘了只能重装系统 | 页面上一键重置密码并重装 |
| 国内机器装不上（GitHub 下不动）| 自动切换镜像 + SHA256 校验 |

---

## 架构

```
              用户浏览器
                  │  https://v.example.com（Basic Auth）
                  ▼
           ┌──────────────┐
           │ Cloudflare   │  SSL=Full，Origin Rule → 8443
           └──────┬───────┘  隐藏源站 IP
                  │
        ┌─────────▼──────────┐   127.0.0.1:8099
        │ Caddy (:80/:8443)  │──────────────► admin.py（节点管理 API）
        │  - 静态页 /opt/web │
        │  - /s/<token> 订阅 │──────────────► subconverter-ng :25500
        └─────────┬──────────┘
                  │ 直连 443/8443
                  ▼
        ┌────────────────────┐
        │ sing-box (Reality) │  节点 A / B / C ...
        └────────────────────┘
```

**为什么是 Reality**：节点不需要域名、不需要证书、没有 TLS 指纹特征，443 端口看起来就是一个正常网站。

**为什么套 Cloudflare**：源站 IP 不进 DNS；被墙了换 IP 只改一条 A 记录。

---

## 功能

- **加节点**：从腾讯云列表选机器（或手填任意 IP/域名）→ 输 root 密码 → 全自动安装
- **失败自愈**：密码错 → 一键重置密码并重启重装；端口没开 → 自动调云 API 放行
- **删 / 改名 / 改端口 / 换密钥**：节点卡片上 `⋯` 菜单
- **订阅**：`/s/<token>` 按 UA 自动返回 Clash 或 v2ray 格式；扫码即用
- **流量与到期**：接腾讯云 API，显示已用/总量、到期日、重置日、剩余天数
- **体检**：60 秒探活，红灯区分"端口没放行 / 服务没起来 / 机器失联"
- **应急**：一键作废旧订阅（token 轮换）、二维码自动重生成

---

## 目录

```
server/
  admin.py            节点管理 API（:8099）
  addnode.sh          一台机器的完整安装脚本
  probe.py            探活，写 status.json
  usage.py            腾讯云 TC3 签名（无 SDK）
  usage_refresh.py    拉流量/到期，写 usage.json + servers.json
  rotate.sh           订阅 token 轮换
web/
  index.html          单页面板（无框架、无构建）
deploy/
  Caddyfile.example   反代 + Basic Auth + 订阅路由
  systemd/            4 个服务单元 + 2 个定时器
config/
  *.example.json      配置示例（真实文件不入库）
docs/
  ARCHITECTURE.md     架构与数据流
  DEPLOY.md           从零部署
  OPS.md              日常运维与排障
  RESTORE.md          灾难恢复
PROMPT.md             复刻本项目的提示词
```

---

## 快速开始

见 [docs/DEPLOY.md](docs/DEPLOY.md)。大致是：

```
1. 一台 Ubuntu 22.04+ 的 VPS（1 核 1G 够用）
2. 域名 + Cloudflare（SSL=Full，Origin Rule → 8443）
3. 跑 deploy 里的 systemd 单元
4. 浏览器打开 https://v.example.com
```

节点机器另需一台（或几台），在页面上加即可。

---

## 安全模型

| 面 | 措施 |
|---|---|
| 面板入口 | Basic Auth（bcrypt），Cloudflare 前置 |
| 订阅链接 | 随机 token，可一键轮换；旧 token 直接 404 |
| 节点协议 | Reality，无证书无域名，抗主动探测 |
| 云 API 密钥 | 只读密钥展示流量；写权限仅用于重置密码/开防火墙 |
| 传输 | 全站 HTTPS，静态资源 no-store |
| 源码泄露 | 仓库内所有 IP/UUID/密钥均为占位符 |

**已知边界**：面板密码是单因素；想要更强可加 Cloudflare Access 或 TOTP。

---

## 限制

- 只支持 Linux 节点（Windows 节点需 PowerShell 分支，本仓库未含）
- 云厂商自动化只做了**腾讯云轻量**；其他厂商需手动开端口
- 国内节点不能翻墙，只能做中转（本项目暂未实现中转编排）

---

## 许可

MIT
