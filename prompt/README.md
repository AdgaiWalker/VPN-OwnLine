# AI 辅助说明入口

主安装流程统一收口至[项目 README](../README.md#2-分钟极速装配)，支持 **macOS / Windows / Linux**：借助本地 AI Agent 与本机盲签凭据库（`ownline.py`）全自动装配，或直接打开本机图形回退页（`启动安装.command` / `启动安装.bat` / `python3 ownline.py ui`），亦保留服务器终端单行脚本（`deploy/bootstrap.sh`）。

- 选购云服务器、客户端与静态住宅代理参考：[项目 README 准备清单](../README.md#准备清单与花费预估)。
- 自备任意兼容 Linux VPS（Ubuntu 22.04+ / Debian 12+）新增节点任务书：[AI 辅助服务器接入任务书](ssh_setup.md)。
- 本地诊断事件单一事实源文档：[本地诊断事件注册表](../docs/02-本地诊断事件表.md)。
- 本地引擎、盲签凭据库与控制面接口契约：[接口契约规格](../research/05-interface-contracts.md)。

安全边界：所有 SSH 密码、SSH 私钥、腾讯云只读 API 密钥、Webshare 静态住宅代理与面板密码，均仅在用户本机 `127.0.0.1` 网页或终端隐身输入（`getpass`）中进入内存句柄，不进入 AI 对话历史与磁盘日志。
