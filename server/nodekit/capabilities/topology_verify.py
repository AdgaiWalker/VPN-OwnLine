"""Capability plugin: end-to-end topology, drift, and client subscription verification."""

from . import CapabilityError, CapabilitySpec


def _mask_token(token: str) -> str:
    t = str(token or "").strip()
    if len(t) >= 12:
        return t[:4] + "****" + t[-4:]
    return "****" if t else ""


def _handle(ctx, params):
    panel_handle = (params.get("panel_handle") or "").strip() or None
    dashboard_url = str(params.get("dashboard_url") or "").strip()
    quick = bool(params.get("quick", False) or ctx.dry_run)
    check_subscription = bool(params.get("check_subscription", True))
    include_sub_url = bool(params.get("include_sub_url", False))
    requested_names = params.get("node_names") if isinstance(params.get("node_names"), list) else None
    insecure_tls = bool(params.get("insecure_tls", False))

    client, info = ctx.borrow_panel(panel_handle, dashboard_url=dashboard_url, insecure_tls=insecure_tls)

    st_nodes, nodes = client.get_json("/api/nodes")
    if ctx.dry_run and params.get("_initial_gate_pending") and st_nodes in (303, 403):
        return {
            "ok": True,
            "dry_run": True,
            "deferred_until_password_change": True,
            "check_subscription": check_subscription,
        }
    if st_nodes != 200 or not isinstance(nodes, list):
        raise CapabilityError("PANEL_NODES_FAILED", "读取节点列表失败。", status=st_nodes if st_nodes >= 400 else 502)

    st_set, settings = client.get_json("/api/settings")
    if st_set != 200 or not isinstance(settings, dict):
        settings = {}

    sub_token = str(settings.get("sub_token") or "").strip()
    if sub_token and not include_sub_url:
        ctx.register_secret(sub_token)

    st_rec, reconcile_status = client.get_json("/api/reconcile/status")
    drifted_count = reconcile_status.get("drifted_count", 0) if st_rec == 200 and isinstance(reconcile_status, dict) else None

    st_rel, relay_status = client.get_json("/api/relay/status")
    relay_summary = {}
    if st_rel == 200 and isinstance(relay_status, dict):
        relay_summary = {
            "configured": bool(relay_status.get("configured")),
            "node": relay_status.get("node"),
            "active_target": relay_status.get("active_target"),
            "auto_failover": bool(relay_status.get("auto_failover")),
        }

    verify_results = []
    if not quick:
        targets = []
        for n in nodes:
            if not isinstance(n, dict) or n.get("type") == "hysteria2":
                continue
            if requested_names is not None and n.get("name") not in requested_names:
                continue
            cap = n.get("capability")
            if isinstance(cap, dict) and cap.get("can_verify") is False:
                continue
            if n.get("source") == "external":
                continue
            targets.append(n)
        for t in targets:
            vc, vr = client.post_json("/api/verify", {"name": t.get("name")})
            item = {"name": t.get("name"), "http_status": vc}
            if vc == 200 and isinstance(vr, dict) and isinstance(vr.get("result"), dict):
                res = vr["result"]
                item.update({
                    "health": res.get("health") or "unknown",
                    "exit_ip": res.get("exit_ip") or "",
                    "detail": res.get("detail") or "",
                })
            else:
                item["health"] = "error"
                item["detail"] = (vr.get("error") if isinstance(vr, dict) else "") or "verify failed"
            verify_results.append(item)

    sub_report = {"checked": False, "ok": True}
    if check_subscription and sub_token:
        uri_status, _, uri_text = client.get_text(f"/s/{sub_token}", use_auth=False)
        clash_status, _, clash_text = client.get_text(f"/s/{sub_token}/clash", use_auth=False)
        uri_lines = [line.strip() for line in uri_text.splitlines() if line.strip()]
        has_valid_uri = any(line.startswith(("vless://", "hysteria2://")) for line in uri_lines)
        clash_ok = (
            clash_status == 200
            and "proxies:" in clash_text
            and "proxy-groups:" in clash_text
            and "rules:" in clash_text
        )
        masked_token = _mask_token(sub_token)
        sub_report = {
            "checked": True,
            "ok": uri_status == 200 and has_valid_uri and clash_ok,
            "uri_status": uri_status,
            "uri_count": len(uri_lines),
            "clash_status": clash_status,
            "clash_ok": clash_ok,
            "sub_url_masked": f"{info['dashboard_url']}/s/{masked_token}",
        }
        if include_sub_url:
            sub_report["sub_url"] = f"{info['dashboard_url']}/s/{sub_token}"

    healthy_nodes = sum(1 for n in nodes if isinstance(n, dict) and n.get("health") == "ok")
    verify_ok = all(r.get("health") == "ok" for r in verify_results) if verify_results else True
    drift_ok = (drifted_count == 0) if drifted_count is not None else True

    return {
        "ok": verify_ok and drift_ok and sub_report.get("ok", True),
        "dry_run": ctx.dry_run,
        "node_count": len(nodes),
        "healthy_nodes": healthy_nodes,
        "drifted_count": drifted_count,
        "relay": relay_summary,
        "verify_results": verify_results,
        "subscription": sub_report,
    }


CAPABILITY = CapabilitySpec(
    name="topology-verify",
    title="全链路拓扑漂移、节点出网与订阅验真",
    description="核对声明式配置零漂移、中转拓扑状态，触发节点实际出网探测并验收 /s/<token> 与 Clash 订阅渲染。",
    required_slots=("panel_auth",),
    params_schema={
        "panel_handle": {"type": "vault_handle:panel_auth", "required": True},
        "node_names": {"type": "array:string", "required": False},
        "quick": {"type": "boolean", "required": False, "default": False},
        "check_subscription": {"type": "boolean", "required": False, "default": True},
        "include_sub_url": {"type": "boolean", "required": False, "default": False},
        "insecure_tls": {"type": "boolean", "required": False, "default": False},
    },
    handler=_handle,
    supports_dry_run=True,
)
