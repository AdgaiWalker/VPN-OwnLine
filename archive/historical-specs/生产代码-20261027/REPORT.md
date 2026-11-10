# 生产代码快照 · 2026-10-27

从硅谷主控 `/opt/web` 拉下来的**线上真实代码**（28 个文件）。
用途：对照"仓库里发布的"和"线上真在跑的"到底差多少。

> 只拉了代码，**没有**拉 `nodes.json` / `servers.json` / `tc.json` / `usage.json` / `status.json` / `iphealth.json` 这些含凭据或运行态的文件。
> 那几样在 `梯子/备份/20261027/` 里。

---

## 一、结论：差三类，不是一类

| 类别 | 数量 | 说明 |
|---|---|---|
| 完全一致 | 15 | addnode.sh、probe.py、providers/*、nodekit 大部分 |
| 脱敏差异（仓库对、线上是真值）| 3 | admin.py、index.html、rotate.sh —— 只差 IP/域名/token |
| 真实分叉 | 6 | 见第三节 |
| 仅线上有 | 4 | 见第四节，其中一个**不能收** |

---

## 二、脱敏差异（不用管，发布版就该这样）

| 文件 | 仓库（发布版） | 线上（真实） |
|---|---|---|
| admin.py | `198.51.100.12` ×2 处 | `43.153.56.137` |
| index.html | `https://v.example.com/s/CHANGEME0000TOKEN` | `https://v.goodloop.si/s/4e7a8c8b61` |
| rotate.sh | `HOST=v.example.com` | `HOST=v.goodloop.si` |

**这三个"不同"是设计出来的，不是漂移。**

---

## 三、真实分叉（6 个）

### 3.1 线上落后：`nodekit/templates.py`

线上还是老版本——**没有 HY2 支持**。仓库已经有 `exit_config(..., hy2=None)`。

后果：线上以后装新节点不会带 Hysteria2。影响暂时不大（HY2 只有硅谷一台，是手工装的），
但**下次重装硅谷就会丢**。

### 3.2 线上多一行：`nodekit/advise.py`

    + role = node.get("role") or "exit"

一行兜底。**应该回填仓库**。

### 3.3 测试代码分叉（4 个文件）

| 文件 | 仓库（发布版）| 线上 |
|---|---|---|
| `advise_tests.py` | 离线、无硬编码路径 | 硬编码 `/opt/web`，断言文案也不同 |
| `hints_tests.py` | 离线 | 硬编码 `/opt/web` |
| `tests.py` | 离线 | 硬编码 `/opt/web` |
| `verify_tests.py` | **离线桩**：替换网络调用，验证判定分支 | **打真网络**：连真节点测 |

**仓库那一版明显更好**，适合开源。线上那版是早期形态，留在服务器上就行，**不要回填仓库**。

> 反直觉的一点：不是"线上一定比仓库新"。测试这一块，**仓库才是对的**。

---

## 四、仅线上有（4 个）—— 三个要收，一个不能收

| 文件 | 大小 | 判断 |
|---|---|---|
| `ipcheck.py` | 1.8 KB | ✅ **要收进仓库**。每 6 小时查 IP 归属与"是否被标记为机房/代理"，写 `iphealth.json`。是决策提示的依据之一，仓库里现在没有 |
| `nodekit/verify_cli.py` | 646 B | ✅ **要收**。verify 的命令行入口 |
| `probe.sh` | 656 B | ❌ **不能收，而且该删** |
| `usage.py` | 2.6 KB | ❌ **不要收**。与 `providers/tc3.py` 哈希完全相同（`5829a45b`），重复文件 |

### `probe.sh` 为什么是雷

它判断成功用的是：

    if grep -q CONNECTED <<< "$out"

**"CONNECTED" 恰恰是 `06-交付报告` 里第 3 条那个假绿灯**——普通 HTTP 端口也会打印 CONNECTED。
`probe.py` 早期就栽在这上面，后来改成必须看到 `Cipher is` 且不是 `(NONE)`。

**这个旧脚本如果跟着发布，等于把已经修好的 bug 重新发给所有人。**

---

## 五、下一步（2026-10-27 13:50 已全部执行）

| 动作 | 状态 |
|---|---|
| 1 | ✅ `ipcheck.py`、`verify_cli.py` 已收进仓库 `server/` |
| 2 | ⬜ `advise.py` 的 `role` 兜底尚未回填 |
| 3 | ✅ `templates.py` 已反向推送到线上，两边 sha256 一致（`c64a0c96`）|
| 4 | ✅ 线上 `probe.sh` 已删除（备份留在 `/tmp/probe.sh.last-backup`）|
| 5 | ⬜ `usage.py` 未处理（确认无人引用后再删）|

### 原始清单

| 动作 | 方向 |
|---|---|
| 1 | `ipcheck.py`、`verify_cli.py` 收进仓库 `server/` |
| 2 | `advise.py` 那一行 `role` 兜底回填仓库 |
| 3 | `templates.py` **反向同步**：仓库 → 线上（线上是旧的）|
| 4 | 线上删掉 `probe.sh`（它不该存在）|
| 5 | `usage.py` 确认无人引用后删除 |

**注意第 3 条方向是反的**：其他都是"线上 → 仓库"，只有 `templates.py` 是"仓库 → 线上"。
