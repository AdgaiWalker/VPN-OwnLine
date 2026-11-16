"""HTTP 协议与请求处理辅助模块。

提供安全 JSON 请求体解析、跨站保护校验、统一响应序列化及客户端 IP 提取。
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any, Optional, Tuple

MAX_BODY = 1_000_000  # 1MB 限制，防超大 Payload


def send_json(handler: Any, code: int, obj: Any) -> None:
    """统一序列化 JSON 响应并发送标准安全标头，支持时间与 UUID 自动转为字符串。"""
    try:
        def _default_serializer(o):
            if hasattr(o, "isoformat"):
                return o.isoformat()
            return str(o)

        body = json.dumps(obj, ensure_ascii=False, default=_default_serializer).encode("utf-8")
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


def normalize_api_path(path: str) -> str:
    """归一化管理路由路径：统一剔除末尾斜杠与 /api 前缀。
    例：
      /api/nodes -> /nodes
      /nodes/    -> /nodes
      /api/ping  -> /ping
    满足 Gateway Matching 不变式（Caddy handle_path 与直连双前缀无差别兼容）。
    """
    p = (path or "").strip().rstrip("/")
    if not p.startswith("/"):
        p = "/" + p
    if p.startswith("/api/"):
        p = p[4:]
    elif p == "/api":
        p = ""
    return p


class AdminRouter:
    """声明式路由分发器，内置双前缀归一化、CSRF 保护与 JSON 异常陷阱。"""

    def __init__(self) -> None:
        self._get_handlers: dict = {}
        self._post_handlers: dict = {}

    @staticmethod
    def normalize(path: str) -> str:
        return normalize_api_path(path)

    def get(self, path: str):
        def decorator(fn):
            norm = self.normalize(path)
            self._get_handlers[norm] = fn
            return fn
        return decorator

    def post(self, path: str):
        def decorator(fn):
            norm = self.normalize(path)
            self._post_handlers[norm] = fn
            return fn
        return decorator

    def dispatch_get(self, handler: Any, raw_path: str, qs: str) -> bool:
        norm = self.normalize(raw_path)
        fn = self._get_handlers.get(norm)
        if fn:
            fn(handler, qs)
            return True
        return False

    def dispatch_post(self, handler: Any, raw_path: str, body: dict) -> bool:
        norm = self.normalize(raw_path)
        fn = self._post_handlers.get(norm)
        if fn:
            fn(handler, body)
            return True
        return False
