"""系统配置路径与目录常量集中管理模块。

统一 DATA 目录、WEB 根目录及核心状态文件的路径解析，杜绝各脚本重复拼接与硬编码。
"""
from __future__ import annotations

import os
from pathlib import Path

WEB_DIR = Path(os.environ.get("LADDER_WEB", "/opt/web"))
DATA_DIR = Path(os.environ.get("LADDER_DATA", "/opt/web-data"))

NODES_FILE = DATA_DIR / "nodes.json"
STATUS_FILE = DATA_DIR / "status.json"
SERVERS_FILE = DATA_DIR / "servers.json"
USAGE_FILE = DATA_DIR / "usage.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
EVENTS_LOG_FILE = DATA_DIR / "events.log"
ALERT_FILE = DATA_DIR / "alert.json"
ALERT_STATE_FILE = DATA_DIR / "alert_state.json"
IPHEALTH_FILE = DATA_DIR / "iphealth.json"
CADDYFILE = Path(os.environ.get("CADDYFILE_PATH", "/etc/caddy/Caddyfile"))
