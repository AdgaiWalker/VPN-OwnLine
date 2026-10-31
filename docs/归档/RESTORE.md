# 灾难恢复

## 场景 1：服务器被墙了（最常见）

症状：页面打不开、所有节点不通、但服务器 SSH 还能连（或者也断了）。

**换 IP 流程**：

```
1. 云控制台给实例换公网 IP（或新建实例）
2. Cloudflare DNS → A 记录 v → 改成新 IP
3. 等 1~2 分钟 DNS 生效
4. 节点机若也换了 IP，面板上「编辑」改地址
```

**注意**：节点机的 UUID/密钥不用动，改 IP 就够。

## 场景 2：Cloudflare 配置被改了

页面显示 525 / 522 / 400，但服务器本身正常。

**必查四项**（漏一项就挂）：

```
□ DNS: A 记录 v 是橙色云（不是灰云）
□ SSL/TLS 模式 = Full（不是 Flexible，不是 Full Strict）
□ Origin Rule: hostname = v.example.com → destination port 8443
□ 云防火墙: 放行 TCP 8443
```

## 场景 3：整台服务器没了

需要重建：

```bash
1. 新机器装依赖（docs/DEPLOY.md 第 2 步）
2. 恢复四个文件：nodes.json / tc.json / Caddyfile / index.html
3. 起服务：systemctl enable --now admin probe.timer usage-refresh.timer caddy
4. 节点机不用动（它们还在跑，参数都在 nodes.json 里）
5. CF 改 A 记录到新 IP
```

节点机上的 sing-box 是独立运行的，**主控服务器挂了不影响已连接的设备**。

## 场景 4：订阅链接泄露

```
管理 → 维护 → 作废旧订阅
```

旧 token 立即 404。已连接的设备不受影响（要继续用）。
想同时断开所有设备 → 对每个节点「更换密钥」。

## 场景 5：忘了面板密码

```bash
caddy hash-password --plaintext '新密码'
# 把输出的 $2a$14$... 替换进 /etc/caddy/Caddyfile 的 basic_auth 块
systemctl reload caddy
```

## 恢复后的自检

```bash
curl -s -o /dev/null -w 'page=%{http_code}\n'   -u admin:密码 https://v.example.com/
curl -s -o /dev/null -w 'sub=%{http_code}\n'    -A 'Clash' https://v.example.com/s/<token>
cat /opt/web-data/status.json   # 每个节点都应该是 ok:true
```
