# 失败模式清单

我们真踩过的坑。每条都是：现象 → 原因 → 解法。

---

## 1. 页面打不开，Cloudflare 报 525

**现象**：浏览器显示 `SSL handshake failed`，源站本机 curl 正常。

**原因**：Cloudflare 的 SSL 模式是 **Full (Strict)**，而源站 Caddy 用的是 `tls internal`（自签证书）。

**解法**：SSL/TLS → 改成 **Full**。不是 Flexible（会死循环），不是 Full Strict（自签不认）。

---

## 2. 页面能开，订阅 400

**现象**：`/s/<token>` 返回 400 Bad Request。

**原因**：Origin Rule 没配，或者 destination port 没改成 8443——Cloudflare 还在回源 443，
而 443 被 sing-box 占着。

**解法**：Rules → Origin Rules → hostname 匹配 → Destination Port 改写 8443。

---

## 3. 改了页面代码，刷新还是旧的

**现象**：部署了新 HTML，浏览器看还是老的。

**原因**：Cloudflare 缓存了静态资源。

**解法**：Caddy 里给静态响应加 `Cache-Control: no-store`。（我们踩了两次）

---

## 4. 国内机器装不上，卡在下载

**现象**：日志显示 `curl: (56) Recv failure: Connection timed out`。

**原因**：目标机器在国内，连 github.com 超时。

**解法**：
- 用镜像（`ghfast.top` 实测最快，1.8 MB/s；`gh-proxy.com` 90 KB/s；`ghproxy.net` 7.7 KB/s）
- **必须校验 SHA256**——镜像站理论上可以投毒
- **不要**改成"从海外服务器 scp 推过去"：跨国传输实测只有 12 KB/s，31MB 要 40 分钟

---

## 5. 安装卡住 40 分钟没有任何输出

**原因**：`scp` 大文件跨国，没有任何进度提示，看起来像死了。

**教训**：**任何可能超过 30 秒的操作都必须有超时**。
现在的做法：每个下载源 `--connect-timeout 6 --max-time 240`，失败就换下一个。

---

## 6. 安装失败，但日志里一个字都没有

**现象**：日志只有 `STEP 1 正在连接服务器`，然后就没有然后了。

**原因**：
```bash
sshpass ... ssh ... "uname -m" 2>/dev/null   # 错误信息被扔进垃圾桶
set -e                                        # 一出错静默退出
```

**解法**：把 stderr 接回来，显式判断返回码，打印真实原因：
```bash
if ! OUT=$(sshpass ... 2>&1); then
  echo "连接失败：$OUT"; exit 1
fi
```

**这是最贵的 bug**——用户看到"失败"却看不到原因，只能截图来问。

---

## 7. 装好了，节点是红的

**现象**：安装成功，但页面显示"不通"。

**原因**：**云防火墙没放行端口**。服务器本机 `ss -tlnp` 能看到监听，但外网连不进。

**解法**：
- 腾讯云：接口自动开（`CreateFirewallRules`）
- 其他云：手动去控制台开

**探活必须能区分**"端口没放行"和"服务没起来"，否则用户不知道该查哪儿。

---

## 8. 重置密码报"没有权限"

**现象**：`UnauthorizedOperation.NoPermission`

**原因**：子账号只有 `QcloudLighthouseReadOnlyAccess`。

**解法**：加 `QcloudLighthouseFullAccess`。**这条权限包含删除机器**，要跟用户说清楚。

---

## 9. 装了 3x-ui 触发云厂商安全告警

**现象**：手机收到"恶意文件 /tmp/3x.sh"的告警短信。

**原因**：云厂商的安全产品对面板类软件（对外开放管理端口的）高度敏感。

**教训**：不要在这些机器上装第三方面板。自建的最小实现反而更安全。

---

## 10. Reality 特定版本不兼容

**现象**：某些客户端报 `REALITY authentication failed`。

**原因**：sing-box 26.10.10 自带的 Xray Reality 与 mihomo/sing-box 客户端不兼容。

**解法**：用 25.9.11 / 1.14.x 这类经过验证的版本，别追最新。

---

## 11. 重装把在用的节点干掉了

**现象**：用户在"添加节点"里选了正在用的机器，一路下一步，把生产节点重装了。

**原因**：列表默认选中第一项，且没有二次确认。

**教训**：**危险操作的默认值必须是安全的那一个**。现在：不预选、下一步禁用、重装要二次确认并标红。

---

## 12. 日志把磁盘写满

**现象**：`/var/log/sing-box.log` 持续增长。

**原因**：探活每 60 秒握手一次，服务端每次都记一条 `REALITY: processed invalid connection`（正常行为）。

**解法**：logrotate，`size 5M` + `rotate 3`。
注意 `/var/log` 若是 group-writable，必须写 `su root root`，否则 logrotate 拒绝执行。

---

## 13. SSH 偶发 banner 超时

**现象**：`Connection timed out during banner exchange`

**原因**：短时间内重复连接，触发 sshd 的并发限制。

**解法**：安装脚本对首次连接做一次自动重试（等 3 秒）。

---

## 排查顺序（面板打不开时）

```bash
systemctl is-active caddy admin sing-box                      # 1 进程
curl -sk -o /dev/null -w '%{http_code}' --resolve v.example.com:8443:127.0.0.1 \
  -u admin:密码 https://v.example.com:8443/                    # 2 本机
curl -s -o /dev/null -w '%{http_code}' https://v.example.com/  # 3 外网
```

| 本机 | 外网 | 结论 |
|---|---|---|
| 200 | 525 | CF 的 SSL 模式 |
| 200 | 400 | Origin Rule 端口 |
| 200 | 200 | 正常（问题在别处）|
| 连不上 | — | 服务没起 / 端口没放行 |
