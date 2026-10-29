# v0.1.1

第二个可以给别人用的版本。核心是**安全收口**和**测试可复现**。

> 从 `v0.1.0` 升级的机器，先看文末「升级注意」——数据目录换了位置。

## 这一版改了什么

### 1. 数据目录拆出去（安全）

`/opt/web` 同时当网站根目录和数据目录时，`file_server` 会把同目录的
`tc.json`（云厂商 SecretKey）和 `nodes.json`（所有节点密钥）发出去。

现在：

```
/opt/web        代码 + 静态页
/opt/web-data   数据（700）：nodes.json / servers.json / usage.json
                status.json / quota.json / iphealth.json / tc.json / .jobs/
```

- 7 个后端文件统一读 `LADDER_DATA`，默认 `/opt/web-data`
- Caddy 新增 `@pubjson` 路由，只从数据目录发前端要的四个 JSON
- `@sensitive` 规则保留作第二道防线

### 2. 移除「粘贴别人的节点」

`/api/paste` 和面板入口都删掉了。原因：没有对方机器的控制权，无法验真
（Reality 任何握手都会成功），也不能换密钥、查流量、排故障——
一个永远不能确认可用的节点，维护成本大于收益。详见 `docs/09-ROLES-AND-SOURCES.md`。

### 3. 测试可复现

- 修掉两套过期测试：`advise_tests.py` 的断言与代码文案不一致；
  `verify_tests.py` 硬读 `/opt/web/nodes.json`、还要求一个已不存在的「（中转）」节点
- 全部测试改为离线桩，不再依赖生产文件
- 新增 `scripts/test.sh`：**6 套 122 项，一条命令，全离网**

### 4. 文档

数据目录口径统一、README 目录修正、发布说明断链修复、
`10-CODE-REVIEW` 补上「离线桩当时只是写进了记录」的更正。

## 验收

```bash
bash scripts/test.sh                                  # 6 套 122 项全过
python3 scripts/drift.py walker-sv walker-bj          # 两台都与模板一致
./scripts/verify.sh https://<域名> admin <密码> <token>  # 0 失败
```

## 升级注意（从 v0.1.0）

改数据目录是**不兼容变更**，按顺序做：

```bash
# 1. 换代码（先不要重启）
cd /opt/ladder && sudo git fetch --tags && sudo git checkout v0.1.1

# 2. 建数据目录并搬过去
sudo mkdir -p /opt/web-data && sudo chmod 700 /opt/web-data
sudo mv /opt/web/nodes.json /opt/web/servers.json /opt/web/usage.json \
        /opt/web/status.json /opt/web/quota.json /opt/web/iphealth.json \
        /opt/web/tc.json /opt/web/retired-nodes-*.json /opt/web/.jobs \
        /opt/web-data/ 2>/dev/null

# 3. Caddyfile 加 @pubjson（照 deploy/Caddyfile.example 的那一段加，
#    保留你自己的域名 / token / basic_auth 哈希，不要整份覆盖）
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl restart caddy

# 4. 更新代码并重启
sudo cp -r server/providers server/nodekit /opt/web/
sudo cp server/*.py server/*.sh /opt/web/
sudo systemctl restart admin   # sing-box 配置没变，不用重启
sudo systemctl restart probe.timer usage-refresh.timer ipcheck.timer
```

验证：

```bash
curl -s -o /dev/null -w '%{http_code}\n' -u admin:密码 https://域名:8443/status.json   # 200
curl -s -o /dev/null -w '%{http_code}\n' -u admin:密码 https://域名:8443/tc.json       # 404
curl -s -o /dev/null -w '%{http_code}\n' -u admin:密码 https://域名:8443/nodes.json    # 404
```

## 已知限制

- 只测过 Ubuntu 22.04+ / Debian 12+；CentOS 7 明确不支持
- subconverter-ng 需手动装，版本未锁
- 云厂商自动化只实现了腾讯云轻量（`open_port()` 只支持 TCP）
- 多用户 / 计费**不做**，那是另一个行业

## 为什么值得读

不是代码，是 `docs/08-LESSONS.md`：**七个最贵的 bug**，
共同点是「把意图当成了系统的行为」。代码别人三天能写出来，这些教训写不出来。
