# 废弃 Flask 首装器与历史快照归档及恢复说明

**归档时间**：2026-11-08  
**归档原因**：贯彻《运维/AGENTS.md》及项目核心决策（五大决策之首——架构彻底收敛至单轨，如无必要勿增实体）。首装与部署全面基于 `deploy/setup-mac.sh` / `deploy/install.sh` 极简交付，废弃半成品 Flask 安装器，主控收敛至 Python 标准库 `server/admin.py` + 纯原生单页 `web/index.html`。节点 SSH 预检核心能力已解耦并迁至 `server/nodekit/sshcheck/`，单测已迁移至 `tests/`。

---

## 一、归档目录清单

```
归档/废弃Flask首装器与历史快照-20261108/
├── server/
│   └── installer/                    # 原 Flask 安装器服务端实现（provision, state, service, downloads 等）
├── deploy/
│   └── installer/                    # 原 systemd 服务定义（ownline-setup-api.service, ownline-setup-worker.service）
├── tests/
│   └── installer/                    # 原针对 Flask 路由与安装流水线的测试（smoke.py, test_installer.py, test_downloads.py）
├── web/
│   └── index.apple-hig.baseline.html # 历史快照参考基线
└── .installer-local/                 # 历史临时下载缓存与运行状态
```

---

## 二、应急回滚与恢复步骤

若后续有特殊需求需临时恢复 Flask 安装器，按以下步骤还原：

1. **移回工作区目录**：
   ```bash
   REPO="/Users/happy/Desktop/梯子/仓库"
   ARCHIVE="/Users/happy/Desktop/梯子/归档/废弃Flask首装器与历史快照-20261108"

   cp -r "$ARCHIVE/server/installer" "$REPO/server/"
   cp -r "$ARCHIVE/deploy/installer" "$REPO/deploy/"
   cp -r "$ARCHIVE/tests/installer"  "$REPO/tests/"
   cp "$ARCHIVE/web/index.apple-hig.baseline.html" "$REPO/web/"
   ```

2. **恢复 Python 依赖**：
   在 `requirements.in` 中重新引入 `Flask>=3.1,<4` 和 `waitress>=3,<4`，并使用 `uv pip compile` 重新生成 `requirements.lock`。

3. **恢复调用桥接**：
   将 `server/nodekit/node_check_bridge.py` 中的 `WORKER` 指向 `WEB / "installer/node_check.py"`，命令修改为 `[str(PYTHON), "-m", "installer.node_check"]`。

4. **运行回归验证**：
   ```bash
   cd "$REPO"
   .venv/bin/python -m unittest tests/test_node_check.py
   ```
