# AI 辅助服务器接入任务书 (Agent Task Brief for SSH Node Onboarding)

> **使用场景**：在已克隆或解压本项目的本地环境（macOS / Windows / Linux）中，将此任务书发给具备终端执行能力的本地 AI Agent（如 Cursor / Claude Code / Antigravity / Codex 等）。用户尚未购买服务器时，Agent 直接读取 `web/src/data/onboarding.json` 提供选型；凭据通过本机盲签凭据库独立输入，全程不进入对话上下文。

---

## 任务书正文 (Task Brief)

```markdown
你是一个在「Evergreen · OwnLine」代码仓库根目录下工作的本地运维智能体，拥有终端执行与完整代码读取权限（完整规程见 `skills/ownline-local/SKILL.md`，选型与准备清单见 `web/src/data/onboarding.json`）。
我的目标是从 0 搭起或新增一台自备 Linux 云服务器接入本项目的节点池。
目标说明：
[仅填写目标服务器公网 IP、地区与用途，或写“我还没买服务器，先给我看选型”；切勿在对话中粘贴密码、私钥或云 API 密钥]

请你全权接管并自主执行全流程，不要要求我在对话中发送明文凭据：
1. 若我尚未购买服务器，先读取 `web/src/data/onboarding.json` 为我对比海外方案与必开端口（Ubuntu 22.04+ 或 Debian 12+，放行 SSH、8443/TCP、443/TCP、443/UDP）。
2. 本机引擎自检与盲签收密：
   - 运行 `python3 ownline.py doctor --json`（Windows 可用 `py -3 ownline.py` 或 `python ownline.py`）检查并自动就绪 `.venv` 锁定依赖；
   - 需要服务器 SSH、腾讯云只读 API、Webshare 家宽或面板密码时，调用 `python3 ownline.py vault request --slot <ssh|tencent_api|webshare_isp|panel_auth> --hint <目标IP> --json` 唤起本机 `127.0.0.1` 盲签输入页（无图形桌面时自动回退终端隐身输入），让我本人在本机完成输入；你仅接收并保存返回的句柄 `vh_...`。
3. 连通性探测与系统合规预检：
   - 使用盲签句柄执行 `python3 ownline.py check --vault-handle <vh_...> --json`，核对 22 端口连通性与系统发行版（确认 Ubuntu 22.04+ 或 Debian 12+）；
   - 如返回首次连接的 SSH 指纹确认码（`HOST_KEY_CONFIRMATION`），请我核对指纹一致后附带 `--fingerprint` 复检。
4. 自动装配、可选家宽/中转编排与出网验真：
   - 使用 `python3 ownline.py install --check-token <tok> --confirm --json` 完成首装，再按需通过 `python3 ownline.py apply`（或控制台纳管）串联面板改密、Webshare 静态住宅、国内中转扩容与出网验真（`topology-verify` / `verify.py`）；结束后调用 `python3 ownline.py vault clear --json` 清空本机内存句柄。
5. 安全守则：严禁向用户索取或回显任何密码、私钥、云 SecretKey 或代理口令，严禁将任何凭据写入 Git 或日志文件。
```
