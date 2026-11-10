# 02 · GitHub 调研报告

> 调研时间：2026-10-26
> 调研目标：找现成的「服务器 → 节点」与「订阅聚合」方案，判断哪些能复用
> 方法：github-explore 脚本，6 组查询，自动过滤 fork / archived，设置 star 下限
> 局限：**只看了元数据与描述，没有 clone 代码、没有实测**。所有结论都是"值得进一步验证"，不是"已验证可用"。

---

## 一、结论先行

**三层里有两层有现成的，一层没有。**

| 层 | 现状 | 建议 |
|---|---|---|
| 安装器（服务器 → 节点） | 有，且成熟 | **抄兼容性逻辑，不整体引入** |
| 订阅聚合（多来源合成一个订阅） | 有，且活跃 | **优先验证 Sub-Store** |
| 决策层（现在该用哪条） | **没有** | 自己写，约 50 行 |

---

## 二、第 1 层：安装器

| 项目 | star | 语言 | 最近提交 | 说明 |
|---|---|---|---|---|
| fscarmen/sing-box | 5,879 | Shell | 2026-10-22 | Sing-box 全家桶，一键多协议，支持 Reality / Hysteria2 / TUIC / Trojan / Shadowsocks / AnyTLS / ShadowTLS / VMess / VLESS / NaiveProxy |
| wulabing/Xray_onekey | 9,253 | Shell | — | Xray + Nginx + VLESS/XTLS 老牌脚本 |
| aleskxyz/reality-ezpz | 1,576 | Shell | 2026-01-06 | 专做 Reality，sing-box / xray 双后端，支持 Letsencrypt 与多种传输 |
| hello-yunshu/Xray_bash_onekey | 664 | Shell | — | 支持 Reality / VLESS WS / gRPC + TLS |

**要抄的四件事**（这些是他们踩过的坑）：

1. 发行版判断（Ubuntu / Debian / CentOS / Alpine 的包管理器差异）
2. 在「没有 curl、没有 tar」的机器上怎么装依赖
3. 没有 systemd 时的降级方案
4. CPU 架构识别（x86_64 / arm64 / armv7）

**不整体引入的原因**：它们是**交互式菜单脚本**，我们要的是**被程序调用的非交互接口**。直接装会在"无人值守"场景卡住。

---

## 三、第 2 层：订阅聚合（本次最大发现）

| 项目 | star | 语言 | 最近提交 | 说明 |
|---|---|---|---|---|
| **sub-store-org/Sub-Store** | **10,757** | JavaScript | **2026-10-26** | 高级订阅管理器，支持 QX / Loon / Surge / Stash / Egern / Shadowrocket |
| 7Sageer/sublink-worker | 5,520 | — | — | Worker 版订阅聚合 |
| SubConv/SubConv | 409 | — | — | Clash 订阅转换 |
| lonelam/subconverter-rs | 320 | — | — | subconverter 的 Rust 重写版 |

**为什么它重要**：

我们的"互相用"需求，本质是：

```
我的订阅 + 朋友给的 vless 链接 + 另一个朋友的订阅
        ↓
     一个合并订阅
```

**Sub-Store 已经把这个做完了。** 我们可能只需要给它一个界面，而不是自己写聚合逻辑。

---

## 四、第 3 层：面板（不建议引入）

| 项目 | star | 评价 |
|---|---|---|
| MHSanaei/3x-ui | 48,580 | 我们试过：安装脚本被腾讯云主机安全判定为恶意文件，触发告警。**不碰** |
| alireza0/s-ui | 10,145 | sing-box 面板，功能全但重 |
| hiddify/Hiddify-Manager | 9,411 | 一站式，含 DB |
| Gozargah/Marzban | 7,476 | 多用户做得最好，但依赖 Python + 数据库 |

**结论**：这些解决的是"多用户 + 计费 + 配额"，是**"给别人用"阶段**的东西。我们现在只给自己用，引入任何一个都是净负担。

**留作将来参考的只有 Marzban** —— 等真到"给别人用"那天，直接用它，别自己写。

---

## 五、四判据评估

| 项目 | 一条命令装卸 | 配置驱动 | 不绑死 | 有日志 | 结论 |
|---|---|---|---|---|---|
| fscarmen/sing-box | ✅ | ⚠️ 交互式 | ✅ | ✅ | 抄逻辑 |
| reality-ezpz | ✅ | ✅ 支持非交互 | ✅ | ✅ | 可参考 |
| Sub-Store | ✅ | ✅ | ✅ | ✅ | **值得引入** |
| 3x-ui | ✅ | ❌ | ⚠️ | ✅ | 不碰 |
| Marzban | ❌ 重 | ✅ | ⚠️ | ✅ | 以后再说 |
| 自研决策层 | — | — | — | — | 自己写 |

---

## 六、明确不采用的

| 不采用 | 理由 |
|---|---|
| Cloudflare Workers 类方案（sublink-worker 等） | 不是"有 root 的 Linux"，是另一类东西；且要绑 Cloudflare 账号 |
| 任何需要注册账号的面板 | 违背"不绑死" |
| 3x-ui | 已踩过坑（云厂商安全告警） |
| Marzban / Hiddify | 现阶段过重 |

---

## 七、下一步：三个选项

| 选项 | 内容 | 成本 | 验证什么 |
|---|---|---|---|
| **A（推荐）** | 试 Sub-Store：把"我的订阅 + 一条伪造的朋友链接"合成一个 | 半天 | "互相用"能不能零成本实现 |
| B | 读 fscarmen 脚本，补 addnode.sh 的私钥与多发行版支持 | 一天 | "任意服务器"能不能真做到 |
| C | 写决策层：读 4 个 JSON 拼成一句话 | 两小时 | 打开面板就知道该连哪条 |

**推荐 A 的理由**：它是最新提出的需求（互相用），且**验证成本最低**——能用就白送一个功能，不能用才知道要自己写多少。

---

## 八、附录：原始查询

```
1. "sing-box install script"                    stars>=100  → 6 条
2. "x-ui vless panel"                            stars>=200  → 6 条
3. "marzban"                                     stars>=100  → 6 条
4. "subscription converter clash v2ray"          stars>=200  → 6 条
5. "sub-store subscription manager"              stars>=200  → 4 条
6. "vless reality one click install"             stars>=50   → 6 条
```

过滤条件：`fork:false archived:false` + star 下限。
工具：`github-explore/scripts/find_repos.py`、`repo_summary.py`。

---

## 九、这份报告的局限（必须说）

1. **没读过一行代码**。所有判断基于 star、描述、最近提交。
2. **star 是滞后指标**。3x-ui 有 48k star，但给我们造成过实际故障。
3. **许可证未确认**（脚本返回 undefined）。真要复用代码前，必须先看 LICENSE。
4. **没测过任何项目**。A/B/C 三个选项都是"验证计划"，不是"结论"。

> 这一点和方法论第 6 条一致：**能装 ≠ 能用，能用 ≠ 适合你。**
