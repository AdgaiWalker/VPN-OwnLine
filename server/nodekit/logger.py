"""轻量结构化运行日志器。

日志文件存于 /opt/web-data/events.log，单文件限制行数（默认保留最新 1000 行）。
提供统一的 log(level, source, message) 函数、read_logs(limit, level, source) 与 get_syslog(service, lines)。
"""
import datetime
import json
import os
import subprocess
import threading

DATA = os.environ.get("LADDER_DATA", "/opt/web-data")
LOG_FILE = os.path.join(DATA, "events.log")
MAX_LINES = 1000
_LOCK = threading.Lock()

ALLOWED_SERVICES = {
    "sing-box", "caddy", "admin", "probe", "backup-remote",
    "usage-refresh", "ipcheck"
}


def log(level, source, message):
    """写入一条日志。level: INFO / WARN / ERROR / SUCCESS"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "ts": now,
        "level": (level or "INFO").upper(),
        "src": (source or "SYS").upper(),
        "msg": str(message).strip()
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _LOCK:
        try:
            os.makedirs(DATA, mode=0o700, exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


def rotate_if_needed(max_lines=MAX_LINES):
    """超限时截断保留最新 max_lines 行"""
    with _LOCK:
        try:
            if not os.path.exists(LOG_FILE):
                return
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > max_lines:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-max_lines:])
        except Exception:
            pass


def read_logs(limit=100, level_filter=None, src_filter=None):
    """读取最近的日志，倒序排列（最新的在最前）"""
    with _LOCK:
        if not os.path.exists(LOG_FILE):
            return []
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            out = []
            lvl = level_filter.upper() if level_filter else None
            src = src_filter.upper() if src_filter else None
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if lvl and lvl != "ALL":
                        if lvl == "BAD" and item.get("level") not in ("WARN", "ERROR"):
                            continue
                        elif lvl != "BAD" and item.get("level") != lvl:
                            continue
                    if src and src != "ALL" and item.get("src") != src:
                        continue
                    out.append(item)
                    if len(out) >= limit:
                        break
                except Exception:
                    continue
            return out
        except Exception:
            return []


def get_syslog(service, lines=50):
    """安全读取系统服务日志（白名单限制）。"""
    service = str(service or "").strip().lower()
    if service not in ALLOWED_SERVICES:
        return {"ok": False, "error": f"不允许查询该服务: {service}"}
    try:
        lines_int = min(max(int(lines), 10), 300)
    except Exception:
        lines_int = 50

    # 特殊处理 sing-box：若存在独立日志文件优先读取
    if service == "sing-box" and os.path.exists("/var/log/sing-box.log"):
        try:
            cmd = ["tail", "-n", str(lines_int), "/var/log/sing-box.log"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return {"ok": True, "service": service, "source": "file", "lines": r.stdout.splitlines()}
        except Exception:
            pass

    try:
        cmd = ["journalctl", "-u", f"{service}.service", "--no-pager", "-n", str(lines_int)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr or "journalctl 失败"}
        return {"ok": True, "service": service, "source": "journalctl", "lines": r.stdout.splitlines()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
