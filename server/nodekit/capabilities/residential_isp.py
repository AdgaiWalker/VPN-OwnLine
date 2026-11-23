"""Capability plugin: bind or unbind a Webshare static residential proxy on an exit node."""

from . import CapabilityError, CapabilitySpec


def _pick_exit_node(nodes, requested_name):
    candidates = [n for n in (nodes or []) if isinstance(n, dict)]
    if requested_name:
        target = next((n for n in candidates if n.get("name") == requested_name), None)
        if target is None:
            raise CapabilityError("NODE_NOT_FOUND", f"未找到节点: {requested_name}", 404)
        if target.get("role") == "relay" or target.get("type") == "hysteria2":
            raise CapabilityError("NODE_NOT_EXIT", f"节点 {requested_name} 不是海外落地出口节点，不能挂载住宅 IP。", 400)
        cap = target.get("capability")
        if isinstance(cap, dict) and cap.get("can_mutate_remote") is False:
            raise CapabilityError("NODE_READONLY", cap.get("reason") or f"节点 {requested_name} 为只读托管节点。", 409)
        return target

    for n in candidates:
        if n.get("role") == "relay" or n.get("type") == "hysteria2":
            continue
        if (n.get("country") or "").upper() == "CN" or (n.get("exit_country") or "").upper() == "CN":
            continue
        cap = n.get("capability")
        if isinstance(cap, dict) and cap.get("can_mutate_remote") is False:
            continue
        if n.get("cleanup_pending") or n.get("source") in ("external", "reverse_join"):
            continue
        return n
    raise CapabilityError("EXIT_NODE_UNAVAILABLE", "未找到可变更远端配置的主控出海落地节点。", 404)


def _handle(ctx, params):
    panel_handle = (params.get("panel_handle") or "").strip() or None
    dashboard_url = str(params.get("dashboard_url") or "").strip()
    requested_node = str(params.get("node_name") or "").strip()
    unbind = bool(params.get("unbind", False))
    insecure_tls = bool(params.get("insecure_tls", False))
    isp_handle = str(params.get("isp_handle") or "").strip()

    isp_secret = None
    isp_summary = None
    if not unbind:
        if not isp_handle:
            raise CapabilityError("ISP_HANDLE_REQUIRED", "挂载静态住宅代理必须提供 webshare_isp 凭据句柄（isp_handle）。", 400)
        if ctx.dry_run:
            desc = ctx.vault.describe(isp_handle)
            if desc.get("slot") != "webshare_isp":
                raise CapabilityError("VAULT_SLOT_MISMATCH", "isp_handle 必须是 webshare_isp 类型句柄。", 400)
            isp_summary = dict(desc.get("summary") or {}, bound=True)
        else:
            isp_secret = ctx.borrow(isp_handle, "webshare_isp")
            isp_summary = {
                "host": isp_secret.get("server", ""),
                "port": isp_secret.get("server_port", 0),
                "protocol": isp_secret.get("type", "socks"),
                "has_auth": bool(isp_secret.get("username") or isp_secret.get("password")),
                "bound": True,
            }
    else:
        isp_summary = {"bound": False}

    client, info = ctx.borrow_panel(panel_handle, dashboard_url=dashboard_url, insecure_tls=insecure_tls)
    st, nodes_payload = client.get_json("/api/nodes")
    if ctx.dry_run and params.get("_initial_gate_pending") and st in (303, 403):
        return {
            "ok": True,
            "dry_run": True,
            "deferred_until_password_change": True,
            "action": "unbind" if unbind else "bind",
            "node_name": requested_node or "(auto-select primary overseas exit)",
            "dashboard_url": info["dashboard_url"],
            "isp_summary": isp_summary,
        }
    if st != 200 or not isinstance(nodes_payload, list):
        raise CapabilityError("PANEL_NODES_FAILED", "读取节点列表失败。", status=st if st >= 400 else 502)

    target = _pick_exit_node(nodes_payload, requested_node)
    target_name = target.get("name") or ""

    if ctx.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "action": "unbind" if unbind else "bind",
            "node_name": target_name,
            "dashboard_url": info["dashboard_url"],
            "isp_summary": isp_summary,
        }

    req_body = {"name": target_name, "isp": None if unbind else isp_secret["proxy_url"]}
    code, res = client.post_json("/api/editnode", req_body)
    req_body.clear()
    if code != 200 or not isinstance(res, dict) or res.get("ok") is not True:
        msg = (res.get("error") or res.get("message")) if isinstance(res, dict) else None
        raise CapabilityError(
            "ISP_SYNC_FAILED",
            msg or f"住宅代理配置下发失败 (HTTP {code})。",
            status=code if code >= 400 else 502,
        )

    updated = res.get("node") if isinstance(res.get("node"), dict) else {}
    return {
        "ok": True,
        "action": "unbind" if unbind else "bind",
        "node_name": updated.get("name") or target_name,
        "health": updated.get("health") or "unknown",
        "exit_ip": updated.get("exit_ip") or "",
        "exit_country": updated.get("exit_country") or "",
        "health_detail": updated.get("health_detail") or "",
        "isp_summary": isp_summary,
    }


CAPABILITY = CapabilitySpec(
    name="residential-isp",
    title="Webshare 静态住宅 IP 挂载与解绑",
    description="通过盲签 webshare_isp 句柄将静态住宅代理配置为海外落地节点的唯一纯净出口，返回脱敏出口状态。",
    required_slots=("panel_auth", "webshare_isp"),
    params_schema={
        "panel_handle": {"type": "vault_handle:panel_auth", "required": True},
        "isp_handle": {"type": "vault_handle:webshare_isp", "required": False},
        "node_name": {"type": "string", "required": False},
        "unbind": {"type": "boolean", "required": False, "default": False},
        "insecure_tls": {"type": "boolean", "required": False, "default": False},
    },
    handler=_handle,
    supports_dry_run=True,
)
