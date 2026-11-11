"""HTTP 协议与请求处理辅助模块。

提供安全 JSON 请求体解析、跨站保护校验、统一响应序列化及客户端 IP 提取。
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any, Optional, Tuple

MAX_BODY = 1_000_000  # 1MB 限制，防超大 Payload


def send_json(handler: Any, code: int, obj: Any) -> None:
    """统一序列化 JSON 响应并发送标准安全标头。"""
    try:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def parse_json_body(handler: Any, max_length: int = MAX_BODY) -> Tuple[int, Optional[dict]]:
    """安全读取并解析 HTTP POST/PUT 的 JSON 请求体。

    返回:
        (status_code, parsed_dict)
        若成功，返回 (200, dict)；若失败，返回对应错误码和 None（并在 handler 中发送错误响应）。
    """
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        send_json(handler, 400, {"ok": False, "error": "无效的 Content-Length"})
        return 400, None

    if length > max_length:
        send_json(handler, 413, {"ok": False, "error": "请求体过大"})
        return 413, None

    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        send_json(handler, 400, {"ok": False, "error": "请求体不是合法 JSON"})
        return 400, None

    if not isinstance(body, dict):
        send_json(handler, 400, {"ok": False, "error": "请求体必须是对象"})
        return 400, None

    return 200, body


def validate_origin(handler: Any) -> bool:
    """CSRF/跨站请求校验：Sec-Fetch-Site 与 Origin/Referer 双重防护。"""
    fetch_site = handler.headers.get("Sec-Fetch-Site")
    if fetch_site in ("cross-site",):
        return False
    host = (handler.headers.get("Host") or "").lower().strip()
    src = handler.headers.get("Origin") or handler.headers.get("Referer") or ""
    if not src:
        return True
    try:
        parsed = urllib.parse.urlsplit(src)
        return parsed.scheme in ("http", "https") and bool(host) and parsed.netloc.lower() == host
    except Exception:
        return False


def extract_client_ip(handler: Any) -> str:
    """安全解析客户端真实 IP。"""
    forwarded = handler.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    addr = getattr(handler, "client_address", None)
    if addr and len(addr) > 0:
        return str(addr[0]).strip()
    return ""
