# v0.1.0

第一个可以给别人用的版本。

## 这是什么

一个人的自建代理出口：把腾讯云轻量变成客户端里能用的节点，
面板管节点，订阅分发给设备。

**它不是一个下载即用的产品**，是一套把决策、代价、失败模式都写清楚的做法，
外加一份参考实现。

## 怎么用

三段提示词，粘进任何能执行命令的 AI harness：

| 什么时候 | 用哪个 |
|---|---|
| 第一次装 | [`prompt/install.md`](../prompt/install.md) |
| 日常加节点 | [`prompt/operate.md`](../prompt/operate.md) |
| 出问题 | [`prompt/troubleshoot.md`](../prompt/troubleshoot.md) |

不想让 AI 碰你的机器，也可以自己跑 `deploy/install.sh`。

## 这一版有什么

- 通用接入：任意 Linux + 密码或私钥
- 面板：加/删/改名/换密钥、流量、探活、决策建议
- 订阅：按 UA 分发 clash / v2ray，一键轮换 token
- **Hysteria2（QUIC）**：模板可选入站，实测同一节点 12.02 → 17.58 Mbps
- 配置漂移检查：`scripts/drift.py` 比对线上与模板

## 验收

```bash
./scripts/verify.sh https://<域名> admin <密码> <token>
```

**14 通到 0 失败**才算装好。真机演练记录见 `docs/` 与仓库外的演练文档。

## 已知限制

- 只测过 Ubuntu 22.04+ / Debian 12+；CentOS 7 明确不支持
- subconverter-ng 需手动装，版本未锁
- 云厂商自动化只实现了腾讯云轻量
- 多用户/计费**不做**，那是另一个行业

## 为什么值得读

不是代码，是 `docs/08-LESSONS.md` 和这几天的演练记录：
**7 个"看起来能跑但其实是坏的"的坑**，其中 5 个是"页面不报错"。

代码别人三天能写出来，这些教训写不出来。
