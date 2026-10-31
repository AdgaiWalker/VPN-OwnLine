# 接入一家新的云

核心代码不认识任何一家云。所有云相关的能力都在 `server/providers/` 下。

---

## 接口

```python
class Provider:
    name = "base"

    def available(self) -> bool:
        """配置齐全时返回 True，否则这个 provider 会被跳过。"""

    def list_instances(self) -> list:
        """[{"name","ip","id","region","regionId","expire","state","provider"}]"""

    def traffic(self) -> dict:
        """{ip: {"used","total","start","end","overflow","region"}}"""

    def open_port(self, ip, port) -> tuple:
        """(状态, 说明)，状态 ∈ opened / already / fail / skip"""

    def reset_password(self, ip) -> tuple:
        """(状态, 说明, {"password": 新密码})"""
```

`skip` 的语义是"这家云不管这台机器"，调用方会继续问下一个 provider。
**任何异常都不该抛出去**——provider 崩了不应该影响别的 provider。

---

## 注册

编辑 `server/providers/__init__.py`：

```python
_MODULES = ["tencent", "aliyun", "generic"]   # 顺序即优先级
```

`generic` 永远排最后，它是兜底（只给手动操作指引），保证任何一台机器都有反馈。

---

## 三个已实现的 provider

### generic（默认）

不做任何 API 操作。作用是把"该去哪儿点哪个按钮"说清楚：

```python
def open_port(self, ip, port):
    return ("skip", "通用机器：请到服务商控制台 → 防火墙 → 放行 TCP %s" % port)
```

**有它，没有云账号的人也能用这套系统**——只是少了自动化。

### tencent（腾讯云轻量 Lighthouse）

| 能力 | API |
|---|---|
| 列机器 | `DescribeRegions` + `DescribeInstances`（枚举全部地域）|
| 流量 | `DescribeInstancesTrafficPackages` |
| 开端口 | `DescribeFirewallRules` + `CreateFirewallRules` |
| 重置密码 | `ResetInstancesPassword` + `RebootInstances` |

签名在 `tc3.py`，手写的 TC3-HMAC-SHA256，**不依赖任何 SDK**。

权限分两档：

```
只读（QcloudLighthouseReadOnlyAccess）→ 只能看流量和到期
全读写（QcloudLighthouseFullAccess） → 才能开防火墙 / 重置密码
```

> 腾讯云没有"只给重置密码"这一档预设策略。想最小化权限，只能自己建自定义策略，
> 但它的控制台编辑器对粘贴极不友好（我们试了四种方法都没成功）。
> 这是我们选择"给全读写"的真实原因，不是偷懒。

---

## 写一个新的（以阿里云为例）

1. 复制 `providers/tencent.py` → `providers/aliyun.py`
2. 改 `name = "aliyun"`
3. 实现四个方法：
   - `list_instances` → 阿里云 ECS 的 `DescribeInstances`
   - `traffic` → 没有统一接口，可以不实现（返回 `{}`）
   - `open_port` → 安全组 `AuthorizeSecurityGroup`
   - `reset_password` → `ModifyInstanceAttribute` + 重启
4. `available()` 读自己的配置文件（如 `/opt/web-data/aliyun.json`）
5. 注册到 `_MODULES`

**不需要动 `admin.py`、`usage_refresh.py`、前端**——一行都不用改。

---

## 前端会看到什么

面板调 `/api/resetpw` 时不关心是哪家云，只看返回：

```json
{"ok": true, "password": "...", "reboot": true, "provider": "tencent"}
```

失败时：

```json
{"ok": false, "error": "没有重置密码的权限：需要给子账号加「轻量应用服务器全读写」"}
```

这句错误直接显示给用户，所以**要写成"下一步该做什么"，不是错误码**。
