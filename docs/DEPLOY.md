# 从零部署

假定：一台 Ubuntu 22.04+ 的 VPS（1 核 1G），一个域名。

## 第 1 步：域名与 Cloudflare

1. 域名 NS 托管到 Cloudflare
2. 加 A 记录：`v` → 源站 IP，**开启代理（橙色云）**
3. SSL/TLS → 模式选 **Full**
4. Rules → Origin Rules → 新建：
   - 匹配 `hostname = v.example.com`
   - Destination Port → **Rewrite to 8443**
5. SSL/TLS → Edge Certificates → 打开 **Always Use HTTPS**

## 第 2 步：装依赖

```bash
# sing-box
curl -fsSL -o /tmp/sb.tgz https://github.com/SagerNet/sing-box/releases/latest/download/sing-box-linux-amd64.tar.gz
mkdir -p /opt/sing-box && tar xzf /tmp/sb.tgz -C /opt/sing-box --strip-components=1

# caddy（官方源）
apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy

# subconverter-ng
# 从 https://github.com/subconverter-ng/subconverter-ng/releases 下载，
# 解压到 /opt/subconv，监听 127.0.0.1:25500
```

## 第 3 步：部署代码

```bash
mkdir -p /opt/web
cp -r server/providers /opt/web/
cp server/*.py server/*.sh /opt/web/
cp web/index.html /opt/web/
chmod 755 /opt/web/*.sh
cp config/*.example.json /opt/web/   # 去掉 .example 并按需修改
```

`providers/` 是云厂商适配层。没有云账号也能跑——`generic` 会兜底，
只是少了"自动开防火墙 / 自动重置密码"。

## 第 4 步：接上订阅

Caddyfile 里的 `<URLENCODED_VLESS_LIST>` 换成你的节点列表：

```bash
# 每条节点一行 vless://...，用 | 连接，再整体 URL 编码
python3 -c "import urllib.parse,sys;print(urllib.parse.quote(open('nodes.txt').read().strip()))"
```

生成后填进 `deploy/Caddyfile.example`，另存为 `/etc/caddy/Caddyfile`，然后：

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

> **关于 `web/qr-sub.png`**：仓库里那张是**占位图**，不是真二维码。
> 它会在你第一次跑 `/opt/web/rotate.sh` 时被 `qrencode` 生成的订阅二维码覆盖。
> `web/icon.png` 是网页图标，直接可用。

## 第 5 步：起服务

```bash
cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now admin probe.timer usage-refresh.timer
```

## 第 6 步：验证

```bash
curl -s -o /dev/null -w '%{http_code}\n' -u admin:你的密码 https://v.example.com/     # 200
curl -s -o /dev/null -w '%{http_code}\n' https://v.example.com/                        # 401
curl -s -o /dev/null -w '%{http_code}\n' -A 'Clash' https://v.example.com/s/<token>    # 200
```

## 第 7 步（可选）：接腾讯云

只读密钥即可看流量；要"自动重置密码/自动开防火墙"需要写权限。

1. 访问管理 → 用户 → 新建子用户 `readonlybot`，开启编程访问
2. 关联策略 `QcloudLighthouseReadOnlyAccess`
3. 拿到 SecretId / SecretKey，写入 `/opt/web/tc.json`，`chmod 600`
4. 若要自动化密码重置，再关联 `QcloudLighthouseFullAccess`


## 第 8 步：验收

```bash
./scripts/verify.sh https://v.example.com 你的用户名 你的密码 你的token
```

全部 ✅ 才算装好。清单见 [07-ACCEPTANCE.md](07-ACCEPTANCE.md)。
