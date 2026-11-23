"""Cross-platform redacted local diagnostic JSONL log and code-driven event registry."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import threading

TZ_CN = timezone(timedelta(hours=8))
MAX_LOG_BYTES = 2 * 1024 * 1024

EVENT_REGISTRY = {
    "local_ui_started": {
        "stage": "lifecycle",
        "severity": "info",
        "summary": "启动本地安装与盲签守护进程",
    },
    "local_ui_stopped": {
        "stage": "lifecycle",
        "severity": "info",
        "summary": "关闭本地守护进程并清空内存凭据",
    },
    "local_cli_doctor": {
        "stage": "diagnostics",
        "severity": "info",
        "summary": "运行本地环境与构建自检",
    },
    "local_update_checked": {
        "stage": "update",
        "severity": "info",
        "summary": "检查远端系统版本更新",
    },
    "vault_request_created": {
        "stage": "vault",
        "severity": "info",
        "summary": "创建盲签凭据输入请求",
    },
    "vault_submitted": {
        "stage": "vault",
        "severity": "info",
        "summary": "用户凭据已存入本机内存并生成不透明句柄",
    },
    "vault_cancelled": {
        "stage": "vault",
        "severity": "warn",
        "summary": "用户取消盲签凭据输入",
    },
    "vault_consumed": {
        "stage": "vault",
        "severity": "info",
        "summary": "一次性消耗内存凭据句柄",
    },
    "vault_expired": {
        "stage": "vault",
        "severity": "warn",
        "summary": "盲签请求或内存句柄到期并清除",
    },
    "vault_cleared": {
        "stage": "vault",
        "severity": "info",
        "summary": "清空指定或全部内存凭据句柄",
    },
    "vault_tty_fallback": {
        "stage": "vault",
        "severity": "info",
        "summary": "无图形桌面环境下启用终端隐身输入回退",
    },
    "ssh_check_started": {
        "stage": "ssh_check",
        "severity": "info",
        "summary": "开始检测目标服务器 SSH 连通性与系统条件",
    },
    "ssh_check_passed": {
        "stage": "ssh_check",
        "severity": "info",
        "summary": "目标服务器身份、环境与 SSH 预检通过",
    },
    "ssh_check_failed": {
        "stage": "ssh_check",
        "severity": "error",
        "summary": "目标服务器 SSH 预检或连接未通过",
    },
    "ssh_fingerprint_prompted": {
        "stage": "ssh_check",
        "severity": "warn",
        "summary": "需要人工核对首次连接的服务器 SSH 指纹",
    },
    "tencent_lookup_started": {
        "stage": "cloud_discovery",
        "severity": "info",
        "summary": "开始通过只读 API 查询腾讯云 CVM 实例",
    },
    "tencent_lookup_done": {
        "stage": "cloud_discovery",
        "severity": "info",
        "summary": "完成腾讯云 CVM 实例列表读取",
    },
    "tencent_lookup_failed": {
        "stage": "cloud_discovery",
        "severity": "error",
        "summary": "读取腾讯云 CVM 实例列表失败",
    },
    "install_started": {
        "stage": "install",
        "severity": "info",
        "summary": "用户已确认目标并触发首次安装任务",
    },
    "install_stage_changed": {
        "stage": "install",
        "severity": "info",
        "summary": "安装任务进入下一阶段",
    },
    "install_done": {
        "stage": "install",
        "severity": "info",
        "summary": "首次安装与交付验收全部通过",
    },
    "install_attention": {
        "stage": "install",
        "severity": "error",
        "summary": "安装或交付验收未完成，等待人工核查",
    },
    "fallback_ui_opened": {
        "stage": "ui",
        "severity": "info",
        "summary": "打开本机图形回退界面",
    },
}

SECRET_KEY_TOKENS = (
    "password",
    "passwd",
    "passphrase",
    "private_key",
    "secret",
    "secret_id",
    "secret_key",
    "token",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "temp_password",
    "sub_token",
    "proxy_url",
    "isp_proxy",
    "raw_input",
)
_SECRET_EXACT_KEYS = frozenset(SECRET_KEY_TOKENS)
_SAFE_META_KEYS = frozenset({"auth_type", "credential_type", "token_ttl"})

_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)",
    re.M,
)
_HTTP_AUTH_RE = re.compile(r"\b(Basic|Bearer)\s+[A-Za-z0-9+/=._-]{4,}", re.I)
_URL_CREDS_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^\s/@'\"]+):([^\s/@'\"]+)@")
_BARE_USERPASS_HOST_RE = re.compile(
    r"(?<![A-Za-z0-9+.-]://)\b([^\s:@'\"/]{1,64}):([^\s:@'\"/]{1,128})@([A-Za-z0-9.-]+:\d{1,5})\b"
)
_FOUR_PART_PROXY_RE = re.compile(
    r"\b((?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9.-]+\.[A-Za-z]{2,}):(\d{1,5}):([^\s:'\"]+):([^\s'\"]+)"
)
_AKID_RE = re.compile(r"\bAKID[A-Za-z0-9]{10,}\b")
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|passphrase|secret_key|secret_id|secret|private_key|temp_password|sub_token|token)\s*([=:])\s*(['\"]?)([^\s,;'\"]{1,256})\3"
)

_LOG_LOCK = threading.Lock()


def _repo_root():
    return Path(__file__).resolve().parents[2]


def default_log_path(root=None):
    override = os.environ.get("OWNLINE_DIAG_LOG", "").strip()
    if override:
        return Path(override)
    base = Path(root) if root is not None else _repo_root()
    return base / ".ops-private" / "local_diag.jsonl"


def _is_secret_key(key):
    lower = str(key).strip().lower()
    if not lower or lower in _SAFE_META_KEYS:
        return False
    if lower in _SECRET_EXACT_KEYS:
        return True
    parts = [p for p in re.split(r"[-_.\s]+", lower) if p]
    return any(part in _SECRET_EXACT_KEYS for part in parts) or any(
        tok in lower for tok in ("password", "passwd", "passphrase", "private_key", "secret", "cookie", "credential", "sub_token", "proxy_url", "isp_proxy", "raw_input")
    )


def redact_text(text):
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text
    out = _PEM_BLOCK_RE.sub("[REDACTED]", text)
    out = _HTTP_AUTH_RE.sub(lambda m: m.group(1) + " [REDACTED]", out)
    out = _URL_CREDS_RE.sub(lambda m: m.group(1) + "[REDACTED]@", out)
    out = _BARE_USERPASS_HOST_RE.sub(lambda m: "[REDACTED]@" + m.group(3), out)
    out = _FOUR_PART_PROXY_RE.sub(lambda m: f"{m.group(1)}:{m.group(2)}:[REDACTED]", out)
    out = _AKID_RE.sub("[REDACTED]", out)
    out = _INLINE_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
    return out


def redact_payload(obj, _depth=0):
    if _depth > 8:
        return "[REDACTED]"
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, bytes):
        return redact_text(obj.decode("utf-8", errors="replace"))
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            key_str = str(k)
            if _is_secret_key(key_str):
                cleaned[key_str] = "[REDACTED]"
            else:
                cleaned[key_str] = redact_payload(v, _depth + 1)
        return cleaned
    if isinstance(obj, (list, tuple, set)):
        return [redact_payload(item, _depth + 1) for item in list(obj)[:100]]
    return redact_text(str(obj))


def _chmod_0600(path):
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def emit_event(event, detail=None, *, log_path=None, severity=None):
    if event not in EVENT_REGISTRY:
        raise ValueError(f"unregistered diagnostic event: {event}")
    meta = EVENT_REGISTRY[event]
    sev = severity if severity in ("info", "warn", "error") else meta["severity"]
    safe_detail = redact_payload(detail) if isinstance(detail, dict) else (
        {"message": redact_text(detail)} if detail is not None else {}
    )
    record = {
        "ts": datetime.now(TZ_CN).isoformat(timespec="seconds"),
        "event": event,
        "stage": meta["stage"],
        "severity": sev,
        "detail": safe_detail,
    }
    target = Path(log_path) if log_path is not None else default_log_path()
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _LOG_LOCK:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if target.exists() and target.stat().st_size >= MAX_LOG_BYTES:
                backup = target.with_name(target.name + ".1")
                if backup.exists():
                    backup.unlink()
                target.replace(backup)
        except OSError:
            pass
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line)
        _chmod_0600(target)
    return record


def read_recent_events(limit=50, *, log_path=None):
    bounded = min(max(int(limit), 1), 200)
    target = Path(log_path) if log_path is not None else default_log_path()
    if not target.is_file():
        return []
    try:
        raw_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    parsed = []
    for line in raw_lines[-bounded * 2:]:
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            parsed.append(redact_payload(item))
    return parsed[-bounded:]


def render_events_markdown():
    lines = [
        "# 本地诊断事件注册表 (Local Diagnostic Event Registry)",
        "",
        "> 单一事实源：由 `server/nodekit/local_diag.py` (`EVENT_REGISTRY`) 代码驱动生成；新增或调整事件后须同步更新本文档，离线门禁强制校验完全一致。",
        "",
        "| 事件代码 (`event`) | 所属阶段 (`stage`) | 级别 (`severity`) | 语义说明 |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for code, meta in EVENT_REGISTRY.items():
        lines.append(
            f"| `{code}` | `{meta['stage']}` | `{meta['severity']}` | {meta['summary']} |"
        )
    lines.append("")
    return "\n".join(lines)
