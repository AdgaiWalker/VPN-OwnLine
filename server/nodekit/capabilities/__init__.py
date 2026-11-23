"""Pluggable capability registry, authenticated panel client, and dynamic canary guard."""

import base64
from dataclasses import dataclass, field
import http.client
import importlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import ssl
from typing import Any, Callable, Dict, Optional, Tuple
import urllib.parse

from ..local_diag import redact_payload

_ALWAYS_SCRUB_KEYS = frozenset({
    "password",
    "passwd",
    "passphrase",
    "private_key",
    "secret",
    "secret_key",
    "secret_id",
    "temp_password",
    "proxy_url",
    "authorization",
    "cookie",
    "current",
    "new",
    "confirm",
})


class CapabilityError(ValueError):
    def __init__(self, code, message, status=400, detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    title: str
    description: str
    required_slots: Tuple[str, ...]
    params_schema: Dict[str, Any]
    handler: Callable[["CapabilityContext", Dict[str, Any]], Dict[str, Any]]
    supports_dry_run: bool = True

    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "required_slots": list(self.required_slots),
            "params_schema": dict(self.params_schema),
            "supports_dry_run": bool(self.supports_dry_run),
        }


def _is_loopback_host(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class RemotePanelClient:
    """In-memory Basic-Auth HTTP/HTTPS client bound to a managed OwnLine control panel."""

    def __init__(self, base_url: str, username: str, password: str, *, insecure_tls: bool = False, timeout: int = 30):
        raw = str(base_url or "").strip().rstrip("/")
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or not parsed.netloc:
            raise CapabilityError("PANEL_INVALID_URL", "管理后台地址无效，必须是合法的 https:// URL。", 400)
        if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
            raise CapabilityError("PANEL_INSECURE_URL", "非本机回环的管理后台仅允许使用 https:// 连接。", 400)

        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.netloc = parsed.netloc
        self.insecure_tls = bool(insecure_tls)
        self.timeout = max(2, int(timeout))
        self._username = str(username or "admin")
        self._password = str(password or "")
        token = base64.b64encode(f"{self._username}:{self._password}".encode("utf-8")).decode("ascii")
        self._auth_header = "Basic " + token
        self._ssl_ctx = None
        if self.scheme == "https":
            self._ssl_ctx = ssl._create_unverified_context() if self.insecure_tls else ssl.create_default_context()

    def _connect(self, timeout=None):
        eff_timeout = timeout or self.timeout
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, context=self._ssl_ctx, timeout=eff_timeout)
        return http.client.HTTPConnection(self.host, self.port, timeout=eff_timeout)

    def _raw_request(self, method: str, path: str, body=None, *, use_auth: bool = True, timeout=None) -> Tuple[int, Dict[str, str], bytes]:
        if not path.startswith("/"):
            path = "/" + path
        headers = {"Host": self.netloc, "Accept": "application/json"}
        if use_auth and self._auth_header:
            headers["Authorization"] = self._auth_header
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Origin"] = self.base_url
            headers["Content-Type"] = "application/json"
        conn = None
        try:
            conn = self._connect(timeout=timeout)
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            resp_headers = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, resp_headers, raw
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise CapabilityError("PANEL_UNREACHABLE", f"无法连接管理后台: {type(exc).__name__}", 502) from None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def get_json(self, path: str, *, timeout=None) -> Tuple[int, Any]:
        status, _, raw = self._raw_request("GET", path, use_auth=True, timeout=timeout)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            data = {"ok": False, "error": "管理后台返回的不是有效 JSON"}
        return status, data

    def post_json(self, path: str, body: dict, *, timeout=None) -> Tuple[int, Any]:
        status, _, raw = self._raw_request("POST", path, body=body, use_auth=True, timeout=timeout)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            data = {"ok": False, "error": "管理后台返回的不是有效 JSON"}
        return status, data

    def get_text(self, path: str, *, use_auth: bool = False, timeout=None) -> Tuple[int, Dict[str, str], str]:
        status, headers, raw = self._raw_request("GET", path, use_auth=use_auth, timeout=timeout)
        return status, headers, raw.decode("utf-8", errors="replace")

    def close(self):
        self._auth_header = ""
        self._password = ""


class CapabilityContext:
    """Scoped execution context keeping all borrowed secrets in RAM and canary-scrubbed."""

    def __init__(self, *, vault, session=None, emit_diag=None, dry_run=False, panel_client_factory=RemotePanelClient):
        self.vault = vault
        self.session = session
        self._emit_diag = emit_diag
        self.dry_run = bool(dry_run)
        self._panel_client_factory = panel_client_factory
        self._borrowed_dicts = []
        self._borrowed_secrets = set()
        self._clients = []

    def emit(self, event: str, detail=None, severity=None):
        if self._emit_diag:
            self._emit_diag(event, self.scrub_output(detail or {}), severity=severity)

    def register_secret(self, value: Optional[str]):
        if not isinstance(value, str):
            return
        text = value.strip()
        if len(text) < 4:
            return
        self._borrowed_secrets.add(text)
        quoted = urllib.parse.quote(text, safe="")
        if quoted != text and len(quoted) >= 4:
            self._borrowed_secrets.add(quoted)
        try:
            b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
            if len(b64) >= 8:
                self._borrowed_secrets.add(b64)
        except Exception:
            pass

    def borrow(self, handle: str, expected_slot: str, *, consume: bool = False) -> Dict[str, Any]:
        if not handle or not isinstance(handle, str):
            raise CapabilityError("VAULT_HANDLE_REQUIRED", f"缺少 {expected_slot} 凭据句柄。", 400)
        secret = self.vault.borrow(handle.strip(), expected_slot=expected_slot, consume=consume)
        self._borrowed_dicts.append(secret)
        secret_fields = ("password", "private_key", "passphrase", "secret_key", "secret_id", "proxy_url")
        if expected_slot == "webshare_isp":
            secret_fields = secret_fields + ("username",)
        for key in secret_fields:
            if secret.get(key):
                self.register_secret(str(secret[key]))
        return secret

    def resolve_panel_target(self, panel_handle: Optional[str] = None, *, dashboard_url: str = "") -> Dict[str, Any]:
        if panel_handle:
            desc = self.vault.describe(str(panel_handle).strip())
            if desc.get("slot") != "panel_auth":
                raise CapabilityError("VAULT_SLOT_MISMATCH", "panel_handle 不是 panel_auth 凭据句柄。", 400)
            summary = desc.get("summary") or {}
            url = (dashboard_url or summary.get("dashboard_url") or "").strip()
            if not url:
                raise CapabilityError("PANEL_URL_REQUIRED", "缺少管理后台 HTTPS 地址（dashboard_url）。", 400)
            return {
                "dashboard_url": url.rstrip("/"),
                "username": summary.get("username") or "admin",
                "source": "vault",
                "handle": str(panel_handle).strip(),
            }
        if self.session is not None:
            st = self.session.status()
            delivery = st.get("delivery") if st.get("state") == "done" else None
            if isinstance(delivery, dict) and delivery.get("temp_password"):
                url = (dashboard_url or delivery.get("dashboard_url") or "").strip()
                if url:
                    return {
                        "dashboard_url": url.rstrip("/"),
                        "username": delivery.get("username") or "admin",
                        "source": "install_delivery",
                        "handle": "",
                    }
        raise CapabilityError(
            "PANEL_AUTH_REQUIRED",
            "缺少管理面板凭据句柄（请先执行 ownline.py vault request --slot panel_auth）。",
            400,
        )

    def borrow_panel(self, panel_handle: Optional[str] = None, *, dashboard_url: str = "", insecure_tls: bool = False) -> Tuple[RemotePanelClient, Dict[str, Any]]:
        if panel_handle:
            secret = self.borrow(panel_handle, "panel_auth")
            url = (dashboard_url or secret.get("dashboard_url") or "").strip().rstrip("/")
            if not url:
                raise CapabilityError("PANEL_URL_REQUIRED", "缺少管理后台 HTTPS 地址（dashboard_url）。", 400)
            username = secret.get("username") or "admin"
            password = secret.get("password") or ""
            source = "vault"
        elif self.session is not None:
            st = self.session.status()
            delivery = st.get("delivery") if st.get("state") == "done" else None
            if not isinstance(delivery, dict) or not delivery.get("temp_password"):
                raise CapabilityError(
                    "PANEL_AUTH_REQUIRED",
                    "缺少管理面板凭据句柄（请先执行 ownline.py vault request --slot panel_auth）。",
                    400,
                )
            url = (dashboard_url or delivery.get("dashboard_url") or "").strip().rstrip("/")
            username = delivery.get("username") or "admin"
            password = str(delivery["temp_password"])
            self.register_secret(password)
            source = "install_delivery"
        else:
            raise CapabilityError(
                "PANEL_AUTH_REQUIRED",
                "缺少管理面板凭据句柄（请先执行 ownline.py vault request --slot panel_auth）。",
                400,
            )

        client = self._panel_client_factory(url, username, password, insecure_tls=insecure_tls)
        self._clients.append(client)
        return client, {"dashboard_url": url, "username": username, "source": source}

    def store_panel_session(self, dashboard_url: str, username: str, password: str, *, label: str = "当前管理后台") -> Dict[str, Any]:
        self.register_secret(password)
        return self.vault.put_direct(
            "panel_auth",
            {"dashboard_url": dashboard_url, "username": username, "password": password},
            label=label,
        )

    def _scrub_string(self, text: str) -> str:
        out = text
        if self._borrowed_secrets:
            for canary in sorted(self._borrowed_secrets, key=len, reverse=True):
                if canary and canary in out:
                    out = out.replace(canary, "[REDACTED]")
        return out

    def _scrub_walk(self, obj, depth=0):
        if depth > 12:
            return "[REDACTED]"
        if obj is None or isinstance(obj, (bool, int, float)):
            return obj
        if isinstance(obj, str):
            return self._scrub_string(obj)
        if isinstance(obj, bytes):
            return self._scrub_string(obj.decode("utf-8", errors="replace"))
        if isinstance(obj, dict):
            cleaned = {}
            for k, v in obj.items():
                ks = str(k)
                if ks.strip().lower() in _ALWAYS_SCRUB_KEYS:
                    cleaned[ks] = "[REDACTED]"
                else:
                    cleaned[ks] = self._scrub_walk(v, depth + 1)
            return cleaned
        if isinstance(obj, (list, tuple, set)):
            return [self._scrub_walk(item, depth + 1) for item in list(obj)]
        return self._scrub_string(str(obj))

    def scrub_output(self, obj: Any) -> Any:
        return self._scrub_walk(redact_payload(obj))

    def close(self):
        for d in self._borrowed_dicts:
            try:
                d.clear()
            except Exception:
                pass
        self._borrowed_dicts.clear()
        for c in self._clients:
            try:
                c.close()
            except Exception:
                pass
        self._clients.clear()
        self._borrowed_secrets.clear()


class CapabilityRegistry:
    """Auto-discovers single-file capability plugins under server/nodekit/capabilities/."""

    def __init__(self, specs: Optional[Dict[str, CapabilitySpec]] = None):
        self._specs: Dict[str, CapabilitySpec] = dict(specs or {})

    @classmethod
    def discover(cls, package_dir=None) -> "CapabilityRegistry":
        default_dir = Path(__file__).resolve().parent
        target_dir = Path(package_dir) if package_dir is not None else default_dir
        is_default = target_dir.resolve() == default_dir.resolve()
        specs: Dict[str, CapabilitySpec] = {}
        if not target_dir.is_dir():
            return cls(specs)

        for path in sorted(target_dir.glob("*.py")):
            stem = path.stem
            if stem.startswith("_") or stem.endswith("_tests"):
                continue
            if is_default:
                mod = importlib.import_module(f"{__name__}.{stem}")
            else:
                mod_name = f"_ownline_cap_plugin_{stem}"
                spec = importlib.util.spec_from_file_location(mod_name, str(path))
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            cap = getattr(mod, "CAPABILITY", None)
            if isinstance(cap, CapabilitySpec):
                specs[cap.name] = cap
        return cls(specs)

    def register(self, spec: CapabilitySpec):
        if not isinstance(spec, CapabilitySpec):
            raise TypeError("spec must be CapabilitySpec")
        self._specs[spec.name] = spec

    def list_specs(self):
        return [self._specs[name].metadata() for name in sorted(self._specs)]

    def get(self, name: str) -> CapabilitySpec:
        spec = self._specs.get(name)
        if spec is None:
            raise CapabilityError("CAPABILITY_NOT_FOUND", f"未找到能力模块: {name}", 404)
        return spec

    def execute(self, name: str, params: Optional[Dict[str, Any]], *, ctx: CapabilityContext) -> Dict[str, Any]:
        spec = self.get(name)
        ctx.emit("capability_started", {"name": spec.name, "dry_run": ctx.dry_run})
        try:
            raw = spec.handler(ctx, dict(params or {}))
            clean = ctx.scrub_output(raw)
            ctx.emit("capability_succeeded", {"name": spec.name, "dry_run": ctx.dry_run})
            return clean
        except CapabilityError as exc:
            ctx.emit("capability_failed", {"name": spec.name, "code": exc.code}, severity="error")
            raise CapabilityError(
                exc.code,
                ctx.scrub_output(exc.message),
                status=exc.status,
                detail=ctx.scrub_output(exc.detail),
            ) from None
        except Exception as exc:
            from ..local_vault import VaultError
            if isinstance(exc, VaultError):
                ctx.emit("capability_failed", {"name": spec.name, "code": exc.code}, severity="error")
                raise
            ctx.emit("capability_failed", {"name": spec.name, "code": "CAPABILITY_INTERNAL_ERROR"}, severity="error")
            raise CapabilityError("CAPABILITY_EXECUTION_FAILED", "能力执行未完成，请查看本地诊断日志。", 500) from None
        finally:
            ctx.close()
