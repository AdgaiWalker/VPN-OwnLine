# 可复现：同一份输入，同一个系统

> 这一页回答一个问题：**别人按我说的做，装出来的东西和我的是一样的吗？**

---

## 1. 「可复现」在这里指什么

不是「AI 能写出类似的代码」，是：

   同一个 tag + 同一份脚本 + 同一条验收命令  →  同一个系统

任何一项不锁，就不算可复现。

| 要素 | 锁在哪 |
|---|---|
| **代码版本** | tag `v0.1.0`（提示词里写死 `git checkout v0.1.0`）|
| **安装步骤** | `deploy/install.sh`，7 步固定顺序 |
| **sing-box 版本** | `install.sh` 顶部 `SINGBOX_VERSION=1.14.4` |
| **系统** | Ubuntu 22.04+ / Debian 12+，`install.sh` 开头检查 |
| **验收标准** | `scripts/verify.sh` → 必须 **0 失败** |

---

## 2. 两条路线，同一结果

| 路线 | 谁在执行 | 走的命令 |
|---|---|---|
| A. 交给 AI | harness 里的 agent | `prompt/install.md` |
| B. 自己动手 | 你 | README「路线 B」|

**两条路线跑的是同一个 `install.sh`。** 这是它们能等价的原因——AI 不是在「生成」，是在「执行」。

---

## 3. 最小复现步骤

    # 1. 锁版本
    git clone <仓库地址> /opt/ladder
    cd /opt/ladder && git checkout v0.1.0

    # 2. 预演（不执行）
    sudo ./deploy/install.sh <域名> --dry-run

    # 3. 执行
    sudo ./deploy/install.sh <域名>

    # 4. 验收（唯一有效的完成证据）
    ./scripts/verify.sh https://<域名> admin <密码> <订阅token>

**第 4 步输出「0 失败」之外的任何结果，都算没装好。**
包括「看起来能用」「页面能打开」「AI 说装好了」。

---

## 4. 哪些部分不能完全复现

诚实列出来，免得你以为这套东西是密封的：

| 环节 | 为什么不可复现 | 影响 |
|---|---|---|
| Cloudflare 配置 | 控制台点击，没有 API 脚本 | 域名/证书环节可能因人而异 |
| 腾讯云防火墙 | 要手动开 TCP 8443 + **UDP 443** | 漏开 UDP 只有 Hysteria2 挂，Reality 正常 |
| subconverter-ng | 需手动下载，版本没锁 | 订阅转换可能有细微差异 |
| 节点本身 | 每台机器的 IP、UUID 都不同 | 正常，这是配置不是代码 |
| AI 的表述 | 同一个 AI 两次说法不同 | 所以只认 `verify.sh` 的输出 |

**前两条是最容易出问题的地方。** 装完打不开，先查这两处。

---

## 5. 换一台机器，怎么确认还是同一个系统

    # 代码层面
    git describe --tags            # 必须是 v0.1.0
    sha256sum deploy/install.sh    # 和发布页一致

    # 运行层面
    systemctl is-active sing-box admin caddy subconverter   # 四个 active
    ss -lntup | grep -E ':(443|8443|8099|25500)'            # 四个端口
    ./scripts/verify.sh ...        # 0 失败

---

## 6. 一句话

> **可复现不是「代码一样」，是「验收输出一样」。**
> 所以这个项目把 `verify.sh` 放进提示词、放进 README、放进 Agent 契约——
> 它是唯一一个不依赖任何人主观判断的结论。
