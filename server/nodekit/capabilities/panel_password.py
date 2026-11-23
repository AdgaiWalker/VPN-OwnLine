"""Capability plugin: rotate panel password & issue a fresh active panel_auth handle."""

import re

from . import CapabilityError, CapabilitySpec


def _handle(ctx, params):
    new_handle = str(params.get("new_panel_handle") or "").strip()
    if not new_handle:
        raise CapabilityError("NEW_PANEL_HANDLE_REQUIRED", "缺少新密码凭据句柄（new_panel_handle）。", 400)
    current_handle = (params.get("current_panel_handle") or params.get("panel_handle") or "").strip() or None
    dashboard_url = str(params.get("dashboard_url") or "").strip()
    insecure_tls = bool(params.get("insecure_tls", False))

    new_secret = ctx.borrow(new_handle, "panel_auth")
    new_pwd = str(new_secret.get("password") or "")
    new_user = str(new_secret.get("username") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", new_user or "admin"):
        raise CapabilityError("PANEL_USERNAME_INVALID", "用户名格式无效（1-64 位字母、数字、下划线、点或横线）。", 400)
    try:
        pwd_bytes = len(new_pwd.encode("utf-8"))
    except UnicodeEncodeError:
        pwd_bytes = 999
    if len(new_pwd) < 12 or pwd_bytes > 72 or any(c in new_pwd for c in "\r\n\x00"):
        raise CapabilityError("PANEL_PASSWORD_WEAK", "新面板密码至少 12 位且不超过 72 字节，不可包含换行符。", 400)

    resolved_url = dashboard_url or str(new_secret.get("dashboard_url") or "").strip()
    target_info = ctx.resolve_panel_target(current_handle, dashboard_url=resolved_url)
    target_url = target_info["dashboard_url"]
    target_user = new_user or target_info["username"]

    if ctx.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "dashboard_url": target_url,
            "username": target_user,
            "source": target_info["source"],
        }

    client, client_info = ctx.borrow_panel(current_handle, dashboard_url=target_url, insecure_tls=insecure_tls)
    old_pwd = client._password
    if new_pwd == old_pwd and target_user == client_info["username"]:
        raise CapabilityError("PANEL_PASSWORD_UNCHANGED", "新密码不能与当前密码完全相同。", 400)

    body = {"current": old_pwd, "new": new_pwd, "confirm": new_pwd}
    if target_user and target_user != client_info["username"]:
        body["username"] = target_user
    code, res = client.post_json("/api/password/change", body)
    body.clear()
    if code != 200 or not isinstance(res, dict) or res.get("ok") is not True:
        msg = (res.get("error") or res.get("message")) if isinstance(res, dict) else None
        raise CapabilityError(
            "PANEL_PASSWORD_CHANGE_FAILED",
            msg or f"面板改密未成功 (HTTP {code})。",
            status=code if code >= 400 else 500,
        )

    final_user = str(res.get("username") or target_user or "admin")
    stored = ctx.store_panel_session(target_url, final_user, new_pwd, label="已更新的管理面板")
    return {
        "ok": True,
        "dashboard_url": target_url,
        "username": final_user,
        "active_panel_handle": stored["handle"],
        "summary": stored["summary"],
        "message": res.get("message") or "面板凭据已更新并刷新本机句柄。",
    }


CAPABILITY = CapabilitySpec(
    name="panel-password",
    title="面板初始改密与凭据接管",
    description="使用内存首装交付密码或已有句柄向管理面板发起改密，并颁发新句柄供后续编排自动沿用。",
    required_slots=("panel_auth",),
    params_schema={
        "new_panel_handle": {"type": "vault_handle:panel_auth", "required": True},
        "current_panel_handle": {"type": "vault_handle:panel_auth", "required": False},
        "dashboard_url": {"type": "string", "required": False},
        "insecure_tls": {"type": "boolean", "required": False, "default": False},
    },
    handler=_handle,
    supports_dry_run=True,
)
