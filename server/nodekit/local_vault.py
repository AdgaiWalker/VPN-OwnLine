"""In-memory blind credential vault issuing opaque handles for local Agents."""

import copy
import re
import secrets
import threading
import time
import urllib.parse

from .links import LinkError, parse_isp_proxy

SUPPORTED_SLOTS = ("ssh", "tencent_api", "webshare_isp", "panel_auth")
_PEM_HEADER_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")
_PEM_FOOTER_RE = re.compile(r"-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----")


class VaultError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _mask_secret_id(value):
    text = str(value or "").strip()
    if len(text) >= 10:
        return text[:4] + "****" + text[-4:]
    return "****"


def _validate_and_summarize(slot, payload):
    if not isinstance(payload, dict):
        raise VaultError("VAULT_PAYLOAD_INVALID", "凭据输入格式无效。")

    if slot == "ssh":
        host = str(payload.get("host") or "").strip()
        if not host or len(host) > 253 or any(ch.isspace() or ord(ch) < 32 for ch in host):
            raise VaultError("VAULT_SSH_HOST_REQUIRED", "请填写有效的服务器公网 IP 或域名。")
        username = str(payload.get("username") or "root").strip() or "root"
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,31}", username):
            raise VaultError("VAULT_SSH_USER_INVALID", "SSH 用户名格式无效。")
        try:
            ssh_port = int(payload.get("ssh_port", 22))
        except (TypeError, ValueError):
            raise VaultError("VAULT_SSH_PORT_INVALID", "SSH 端口必须为 1-65535。") from None
        if not 1 <= ssh_port <= 65535:
            raise VaultError("VAULT_SSH_PORT_INVALID", "SSH 端口必须为 1-65535。")
        password = str(payload.get("password") or "")
        private_key = str(payload.get("private_key") or "").strip()
        passphrase = str(payload.get("passphrase") or "")
        if len(password) > 4096 or len(private_key) > 65536 or len(passphrase) > 4096:
            raise VaultError("VAULT_CREDENTIAL_TOO_LARGE", "凭据内容超过允许大小。")
        if bool(password) == bool(private_key):
            raise VaultError("VAULT_SSH_CREDENTIAL_REQUIRED", "请在密码和 SSH 私钥中选择一种填写。")
        if password and _PEM_HEADER_RE.search(password):
            raise VaultError("VAULT_SSH_KEY_INVALID", "检测到截断的 SSH 私钥头，请完整粘贴 PEM 私钥内容。")
        if private_key and (not _PEM_HEADER_RE.search(private_key) or not _PEM_FOOTER_RE.search(private_key)):
            raise VaultError("VAULT_SSH_KEY_INVALID", "请粘贴完整的 PEM 格式 SSH 私钥。")
        secret = {"host": host, "username": username, "ssh_port": ssh_port}
        if private_key:
            secret["private_key"] = private_key
            if passphrase:
                secret["passphrase"] = passphrase
        else:
            secret["password"] = password
        summary = {
            "host": host,
            "username": username,
            "ssh_port": ssh_port,
            "auth_type": "private_key" if private_key else "password",
        }
        return secret, summary

    if slot == "tencent_api":
        secret_id = str(payload.get("secret_id") or "").strip()
        secret_key = str(payload.get("secret_key") or "").strip()
        if not secret_id or not secret_key:
            raise VaultError("VAULT_TENCENT_REQUIRED", "请同时输入腾讯云 SecretId 与 SecretKey。")
        if len(secret_id) > 256 or len(secret_key) > 256:
            raise VaultError("VAULT_CREDENTIAL_TOO_LARGE", "腾讯云密钥长度超过限制。")
        secret = {"secret_id": secret_id, "secret_key": secret_key}
        summary = {"secret_id_masked": _mask_secret_id(secret_id)}
        return secret, summary

    if slot == "webshare_isp":
        raw_url = str(payload.get("proxy_url") or "").strip()
        if raw_url:
            try:
                parsed = parse_isp_proxy(raw_url)
            except LinkError as exc:
                raise VaultError("VAULT_ISP_INVALID", str(exc)) from None
        else:
            host = str(payload.get("host") or "").strip()
            protocol = str(payload.get("protocol") or "socks").strip().lower()
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
            if not host or any(ch.isspace() or ord(ch) < 32 for ch in host):
                raise VaultError("VAULT_ISP_INVALID", "请粘贴 Webshare 代理串或填写有效代理主机。")
            try:
                port = int(payload.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            if not 1 <= port <= 65535:
                raise VaultError("VAULT_ISP_INVALID", "住宅代理端口必须为 1-65535。")
            if protocol not in ("socks", "socks5", "http", "https"):
                raise VaultError("VAULT_ISP_INVALID", "住宅代理协议仅支持 socks5 或 http。")
            parsed = {
                "type": "socks" if "socks" in protocol else "http",
                "server": host,
                "server_port": port,
            }
            if username:
                parsed["username"] = username
            if password:
                parsed["password"] = password

        scheme = "socks5" if parsed["type"] == "socks" else "http"
        userinfo = ""
        if parsed.get("username") or parsed.get("password"):
            u = urllib.parse.quote(parsed.get("username", ""), safe="")
            p = urllib.parse.quote(parsed.get("password", ""), safe="")
            userinfo = f"{u}:{p}@"
        normalized_url = f"{scheme}://{userinfo}{parsed['server']}:{parsed['server_port']}"
        secret = dict(parsed)
        secret["proxy_url"] = normalized_url
        summary = {
            "host": parsed["server"],
            "port": parsed["server_port"],
            "protocol": parsed["type"],
            "has_auth": bool(parsed.get("username") or parsed.get("password")),
        }
        return secret, summary

    if slot == "panel_auth":
        password = str(payload.get("password") or "")
        if not password:
            raise VaultError("VAULT_PANEL_PASSWORD_REQUIRED", "请输入管理面板密码。")
        if len(password) > 4096:
            raise VaultError("VAULT_CREDENTIAL_TOO_LARGE", "密码长度超过限制。")
        username = str(payload.get("username") or "admin").strip() or "admin"
        dashboard_url = str(payload.get("dashboard_url") or "").strip()
        if dashboard_url:
            parsed_url = urllib.parse.urlparse(dashboard_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise VaultError("VAULT_DASHBOARD_URL_INVALID", "管理后台地址必须为有效的 https:// URL。")
        secret = {"dashboard_url": dashboard_url, "username": username, "password": password}
        summary = {"dashboard_url": dashboard_url, "username": username}
        return secret, summary

    raise VaultError("VAULT_SLOT_UNSUPPORTED", f"不支持的凭据类型: {slot}")


class BlindVault:
    """Ephemeral in-memory store: plaintext secrets never leave this process or hit disk."""

    def __init__(self, *, default_ttl=600, request_ttl=300, max_handles=32, clock=time.monotonic, on_event=None):
        self.default_ttl = max(1, int(default_ttl))
        self.request_ttl = max(1, int(request_ttl))
        self.max_handles = max(1, int(max_handles))
        self._clock = clock
        self._on_event = on_event
        self._lock = threading.Lock()
        self._requests = {}
        self._handles = {}

    def _dispatch_events(self, events):
        if not self._on_event:
            return
        for name, detail in events:
            try:
                self._on_event(name, detail)
            except Exception:
                pass

    def _purge_locked(self):
        now = self._clock()
        events = []
        for req_id, req in list(self._requests.items()):
            if req["state"] == "pending" and req["expires_at"] <= now:
                req["state"] = "expired"
                events.append(("vault_expired", {"kind": "request", "slot": req["slot"], "request_id": req_id}))
            elif req["state"] != "pending" and now - req["updated_at"] > max(self.request_ttl, 600):
                del self._requests[req_id]
        for handle, entry in list(self._handles.items()):
            if entry["expires_at"] <= now:
                entry["secret"].clear()
                del self._handles[handle]
                events.append(("vault_expired", {"kind": "handle", "slot": entry["slot"]}))
        return events

    def _store_handle_locked(self, slot, secret, summary, *, label="", ttl=None):
        if len(self._handles) >= self.max_handles:
            raise VaultError("VAULT_FULL", "内存凭据数量已达上限，请先清理闲置句柄。", 429)
        handle_ttl = max(1, int(ttl)) if ttl is not None else self.default_ttl
        handle = "vh_" + secrets.token_urlsafe(18)
        now = self._clock()
        self._handles[handle] = {
            "handle": handle,
            "slot": slot,
            "label": str(label or ""),
            "secret": secret,
            "summary": summary,
            "created_at": now,
            "expires_at": now + handle_ttl,
        }
        return handle, handle_ttl

    def create_request(self, slot, *, label="", target_hint="", ttl=None):
        if slot not in SUPPORTED_SLOTS:
            raise VaultError("VAULT_SLOT_UNSUPPORTED", f"不支持的凭据类型: {slot}")
        req_ttl = max(1, int(ttl)) if ttl is not None else self.request_ttl
        req_id = "vr_" + secrets.token_urlsafe(16)
        with self._lock:
            events = self._purge_locked()
            now = self._clock()
            self._requests[req_id] = {
                "request_id": req_id,
                "slot": slot,
                "label": str(label or ""),
                "target_hint": str(target_hint or ""),
                "state": "pending",
                "handle": None,
                "summary": None,
                "expires_at": now + req_ttl,
                "updated_at": now,
            }
            events.append(("vault_request_created", {"slot": slot, "request_id": req_id}))
        self._dispatch_events(events)
        return {
            "request_id": req_id,
            "slot": slot,
            "label": str(label or ""),
            "target_hint": str(target_hint or ""),
            "state": "pending",
            "expires_in_seconds": req_ttl,
        }

    def submit_request(self, request_id, payload, *, handle_ttl=None):
        with self._lock:
            events = self._purge_locked()
            req = self._requests.get(request_id)
            if req is None:
                self._dispatch_events(events)
                raise VaultError("VAULT_REQUEST_NOT_FOUND", "凭据输入请求不存在或已失效。", 404)
            if req["state"] == "expired":
                self._dispatch_events(events)
                raise VaultError("VAULT_REQUEST_EXPIRED", "凭据输入请求已超时，请重新发起。", 410)
            if req["state"] != "pending":
                self._dispatch_events(events)
                raise VaultError("VAULT_REQUEST_NOT_PENDING", "该凭据输入请求已完成或已取消。", 409)
            secret, summary = _validate_and_summarize(req["slot"], payload)
            handle, ttl_seconds = self._store_handle_locked(
                req["slot"], secret, summary, label=req["label"], ttl=handle_ttl
            )
            req["state"] = "submitted"
            req["handle"] = handle
            req["summary"] = copy.deepcopy(summary)
            req["updated_at"] = self._clock()
            events.append(("vault_submitted", {"slot": req["slot"], "handle": handle, "summary": copy.deepcopy(summary)}))
        self._dispatch_events(events)
        return {
            "handle": handle,
            "slot": req["slot"],
            "summary": copy.deepcopy(summary),
            "expires_in_seconds": ttl_seconds,
        }

    def cancel_request(self, request_id):
        with self._lock:
            events = self._purge_locked()
            req = self._requests.get(request_id)
            if req is None:
                self._dispatch_events(events)
                raise VaultError("VAULT_REQUEST_NOT_FOUND", "凭据输入请求不存在或已失效。", 404)
            if req["state"] == "pending":
                req["state"] = "cancelled"
                req["updated_at"] = self._clock()
                events.append(("vault_cancelled", {"slot": req["slot"], "request_id": request_id}))
            result = self._format_request_locked(req)
        self._dispatch_events(events)
        return result

    def _format_request_locked(self, req):
        now = self._clock()
        out = {
            "request_id": req["request_id"],
            "slot": req["slot"],
            "label": req["label"],
            "target_hint": req["target_hint"],
            "state": req["state"],
            "expires_in_seconds": max(0, int(req["expires_at"] - now)) if req["state"] == "pending" else 0,
        }
        if req["state"] == "submitted":
            out["handle"] = req["handle"]
            out["summary"] = copy.deepcopy(req["summary"])
        return out

    def request_status(self, request_id):
        with self._lock:
            events = self._purge_locked()
            req = self._requests.get(request_id)
            if req is None:
                self._dispatch_events(events)
                raise VaultError("VAULT_REQUEST_NOT_FOUND", "凭据输入请求不存在或已失效。", 404)
            result = self._format_request_locked(req)
        self._dispatch_events(events)
        return result

    def put_direct(self, slot, payload, *, label="", ttl=None):
        if slot not in SUPPORTED_SLOTS:
            raise VaultError("VAULT_SLOT_UNSUPPORTED", f"不支持的凭据类型: {slot}")
        secret, summary = _validate_and_summarize(slot, payload)
        with self._lock:
            events = self._purge_locked()
            handle, ttl_seconds = self._store_handle_locked(slot, secret, summary, label=label, ttl=ttl)
            events.append(("vault_submitted", {"slot": slot, "handle": handle, "summary": copy.deepcopy(summary)}))
        self._dispatch_events(events)
        return {
            "handle": handle,
            "slot": slot,
            "summary": copy.deepcopy(summary),
            "expires_in_seconds": ttl_seconds,
        }

    def describe(self, handle):
        with self._lock:
            events = self._purge_locked()
            entry = self._handles.get(handle)
            if entry is None:
                self._dispatch_events(events)
                raise VaultError("VAULT_HANDLE_INVALID", "凭据句柄无效或已过期，请重新输入。", 404)
            now = self._clock()
            result = {
                "handle": entry["handle"],
                "slot": entry["slot"],
                "label": entry["label"],
                "summary": copy.deepcopy(entry["summary"]),
                "expires_in_seconds": max(0, int(entry["expires_at"] - now)),
            }
        self._dispatch_events(events)
        return result

    def borrow(self, handle, *, expected_slot=None, consume=False):
        with self._lock:
            events = self._purge_locked()
            entry = self._handles.get(handle)
            if entry is None:
                self._dispatch_events(events)
                raise VaultError("VAULT_HANDLE_INVALID", "凭据句柄无效或已过期，请重新输入。", 404)
            if expected_slot and entry["slot"] != expected_slot:
                self._dispatch_events(events)
                raise VaultError(
                    "VAULT_SLOT_MISMATCH",
                    f"凭据类型不匹配：需要 {expected_slot}，收到 {entry['slot']}。",
                    400,
                )
            secret_copy = dict(entry["secret"])
            if consume:
                slot = entry["slot"]
                entry["secret"].clear()
                del self._handles[handle]
                events.append(("vault_consumed", {"slot": slot, "handle": handle}))
        self._dispatch_events(events)
        return secret_copy

    def list_handles(self):
        with self._lock:
            events = self._purge_locked()
            now = self._clock()
            out = [
                {
                    "handle": entry["handle"],
                    "slot": entry["slot"],
                    "label": entry["label"],
                    "summary": copy.deepcopy(entry["summary"]),
                    "expires_in_seconds": max(0, int(entry["expires_at"] - now)),
                }
                for entry in self._handles.values()
            ]
        self._dispatch_events(events)
        return out

    def clear(self, handle=None):
        with self._lock:
            events = self._purge_locked()
            cleared = 0
            if handle is not None:
                entry = self._handles.pop(handle, None)
                if entry is not None:
                    slot = entry["slot"]
                    entry["secret"].clear()
                    cleared = 1
                    events.append(("vault_cleared", {"scope": "single", "slot": slot, "cleared": 1}))
            else:
                for entry in self._handles.values():
                    entry["secret"].clear()
                    cleared += 1
                self._handles.clear()
                for req in self._requests.values():
                    if req["state"] == "pending":
                        req["state"] = "cancelled"
                        req["updated_at"] = self._clock()
                events.append(("vault_cleared", {"scope": "all", "cleared": cleared}))
        self._dispatch_events(events)
        return cleared
