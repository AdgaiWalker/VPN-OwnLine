# Server buying and preparation guide (Moved into Product)

This standalone guide has been retired because its setup notes became outdated relative to the product itself.

All verified buying options, ports, single-node vs domestic relay recommendations, Webshare static residential proxy details, client downloads, and optional domain instructions are now embedded directly inside the application and unified in [web/src/data/onboarding.json](../web/src/data/onboarding.json):

- **Local setup UI**: open the collapsed `"还没有服务器？查看 0~99 元/年选型与必开端口"` panel via `启动安装.command` (macOS), `启动安装.bat` (Windows), or `python3 ownline.py ui` (`py -3` / `python` on Windows).
- **Blind credential vault**: open the collapsed Webshare guide directly inside the `webshare_isp` input card.
- **Control panel UI**: open `"还没有服务器或想看选型与可选域名？"` inside the Add Server view.
- **Local AI Agent**: run `python3 ownline.py doctor --json` and follow [skills/ownline-local/SKILL.md](../skills/ownline-local/SKILL.md) alongside [Get Started](../README.md#ai-assisted-setup).

---

# 服务器选购与准备指引（已融入产品界面）

本外链文档已收口进产品本身，避免仓外说明过期：请直接在本地安装页、盲签输入页或管理后台「添加服务器」中按需展开选型、端口与可选域名指引，或在仓库根目录查阅结构化单源数据 [web/src/data/onboarding.json](../web/src/data/onboarding.json) 与 [快速开始](../README.md#ai-assisted-setup)。
