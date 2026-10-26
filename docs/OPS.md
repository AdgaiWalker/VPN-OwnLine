# 日常运维与排障

## 换一家云

不用改核心代码。按 [02-PROVIDERS.md](02-PROVIDERS.md) 写一个 `providers/xxx.py`，
注册一行，重启 admin 即可。`generic` 会一直兜底，所以写错了也不会让系统崩。

## 加一台节点

1. 打开面板 → 管理 → 常用 → 添加节点
2. 选列表里的机器（腾讯云会自动列出），或点「＋ 其他服务器」手填 IP/域名
3. 输 root 密码
4. 下一步 → 开始安装 → 等进度条走完

**失败怎么办**：弹窗会写明原因。

| 提示 | 含义 | 处理 |
|---|---|---|
| 密码不对 | SSH 认证失败 | 点「自动重置并重装」 |
| 端口没放行 | 装好了但外网连不进 | 腾讯云自动开；其他厂商手动开 |
| 服务没起来 | 端口通但 sing-box 没跑 | 看原始输出，多半是架构不支持 |
| 连不上 22 端口 | 机器失联或防火墙挡了 | 查机器状态 |

## 加一台中转节点

1. 面板 → 管理 → 添加节点 → 地址填国内那台
2. **角色选「中转（跳板）」**
3. 落地：从下拉里选一台海外出口（或粘贴一条 vless 链接）
4. 装完自检应显示「中转：入口与落地都可达」

**注意**：中转**不会**出现在订阅里。客户端里看不到它，这是有意的——
本期没做链式转发，进了订阅只会让人误选后"连上没网"。

## 粘贴别人的节点

管理 → 粘贴节点 → 一行一条 → 「加入订阅」。

- 只支持 `vless://` + `reality`
- 缺 `pbk` / `sid` / `sni` 会拒绝，并说明缺哪个
- 外部节点显示「未验证（外部节点）」——**不给绿灯**，因为 Reality 任何握手都会成功，
  探活对别人的节点是假阳性（见 [09-ROLES-AND-SOURCES.md](09-ROLES-AND-SOURCES.md)）
- 外部节点没有「更换密钥」：我们对它没有控制权

## 节点状态怎么读

| 状态 | 含义 | 下一步 |
|---|---|---|
| ok | 正常 | — |
| port | 端口不通 | 查防火墙 / 服务 |
| tls | 握手失败 | 服务没起来 |
| role_mismatch | 国内机设成了出口 | 改成中转 |
| landing | 连不上落地 | 查落地节点 |
| blocked | 可能被墙 | 换 IP |
| unknown | 未验证（外部节点）| — |

## 删节点

节点卡片 `⋯` → 删除。会 SSH 进去停服务、把开机自启关掉。
**机器不会被删**，只是不再是节点。

## 换密钥（踢掉所有设备）

`⋯` → 更换密钥。会生成新 UUID 并重启 sing-box。
**所有已导入的设备会立刻断线**，需要重新扫码。

适合场景：设备丢了、订阅被转发给了别人。

## 作废旧订阅

管理 → 维护 → 作废旧订阅。会换新 token，
旧链接直接 404，二维码自动重绘。

注意：作废订阅**不会**让已连接的设备断线——设备上已经存了节点参数。
要真正踢人，用「换密钥」。

## 页面打不开怎么查

按顺序排查，**任何一环断了都会 400/525**：

```bash
# 1. 源站进程活着吗
systemctl is-active caddy admin sing-box

# 2. 本机 8443 通吗（绕过 Cloudflare）
curl -sk -o /dev/null -w '%{http_code}\n' -u admin:密码 --resolve v.example.com:8443:127.0.0.1 https://v.example.com:8443/

# 3. Cloudflare 回源对不对
curl -s -o /dev/null -w '%{http_code}\n' https://v.example.com/

# 4. 云防火墙放行 8443 了吗
# 控制台 → 防火墙 → 看有没有 TCP 8443
```

- 本机 200、外网 525 → CF 的 SSL 模式不是 Full，或 Origin Rule 没生效
- 本机 200、外网 400 → 源站端口对不上（Origin Rule 写错）
- 本机 404、外网 404 → Caddyfile 里 site 块的域名写错

## 流量数字不对

`/opt/web/usage.json` 由 `usage-refresh.timer` 每 10 分钟刷新。
手动触发：

```bash
systemctl start usage-refresh.service
journalctl -u usage-refresh -n 20 --no-pager
```

若提示无权限，检查 `tc.json` 的密钥是否还有效、是否被禁用。

## 日志在哪

| 内容 | 位置 |
|---|---|
| 面板 API | `journalctl -u admin` |
| Caddy | `journalctl -u caddy` |
| sing-box（本机节点）| `/var/log/sing-box.log`（已配轮转）|
| 探活 | `journalctl -u probe` |
| 安装过程 | 页面上的「原始输出」或 `journalctl -u admin` |

## 备份

需要备份的就四个文件：

```
/opt/web/nodes.json     节点参数
/opt/web/tc.json        云密钥
/etc/caddy/Caddyfile    订阅与路由
/opt/web/index.html     面板
```

其余（servers.json / usage.json / status.json）都是可再生的缓存。
