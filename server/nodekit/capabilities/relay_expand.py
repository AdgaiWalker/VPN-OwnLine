"""Capability plugin: expand relay/exit nodes via reverse-join, SSH-managed addnode, or pair."""

import time

from . import CapabilityError, CapabilitySpec


def _handle(ctx, params):
    panel_handle = (params.get("panel_handle") or "").strip() or None
    dashboard_url = str(params.get("dashboard_url") or "").strip()
    method = str(params.get("method") or "reverse_join").strip().lower()
    if method not in ("reverse_join", "ssh_managed", "pair_only"):
        raise CapabilityError("RELAY_METHOD_INVALID", f"不支持的扩容方式: {method}", 400)

    role = str(params.get("role") or "relay").strip()
    if role not in ("relay", "exit", "auto"):
        raise CapabilityError("NODE_ROLE_INVALID", f"不支持的节点角色: {role}", 400)
    name = str(params.get("name") or "").strip()
    port_raw = params.get("port")
    port = int(port_raw) if port_raw not in (None, "") else (8443 if role == "relay" else 443)
    landing_host = str(params.get("landing_host") or params.get("target") or "").strip()
    fallback_host = str(params.get("fallback_host") or params.get("fallback") or "").strip()
    relay_name = str(params.get("relay_name") or name or "").strip()
    auto_pair = bool(params.get("auto_pair", True))
    insecure_tls = bool(params.get("insecure_tls", False))

    client, info = ctx.borrow_panel(panel_handle, dashboard_url=dashboard_url, insecure_tls=insecure_tls)
    st_nodes, nodes_payload = client.get_json("/api/nodes")
    if ctx.dry_run and params.get("_initial_gate_pending") and st_nodes in (303, 403):
        return {
            "ok": True,
            "dry_run": True,
            "deferred_until_password_change": True,
            "method": method,
            "role": role,
            "name": name,
            "port": port,
            "landing_host": landing_host,
        }
    if st_nodes != 200 or not isinstance(nodes_payload, list):
        raise CapabilityError("PANEL_NODES_FAILED", "读取节点列表失败。", status=st_nodes if st_nodes >= 400 else 502)

    if ctx.dry_run:
        st_relay, relay_status = client.get_json("/api/relay/status")
        return {
            "ok": True,
            "dry_run": True,
            "method": method,
            "role": role,
            "name": name,
            "port": port,
            "landing_host": landing_host,
            "existing_nodes": len(nodes_payload),
            "relay_status": relay_status if st_relay == 200 else {},
        }

    if method == "pair_only":
        if relay_name and landing_host:
            body = {"name": relay_name, "target": landing_host}
            if fallback_host:
                body["fallback"] = fallback_host
            code, res = client.post_json("/api/relay/bind", body)
        else:
            code, res = client.post_json("/api/relay/auto-pair", {})
        if code != 200 or not isinstance(res, dict) or res.get("ok") is not True:
            msg = (res.get("error") or res.get("message")) if isinstance(res, dict) else None
            raise CapabilityError("RELAY_PAIR_FAILED", msg or "中转配对失败。", status=code if code >= 400 else 502)
        return {"ok": True, "method": "pair_only", "relay_result": res}

    if method == "reverse_join":
        body = {"role": "exit" if role == "auto" else role, "port": port}
        if name:
            body["name"] = name
        if landing_host:
            body["landing_host"] = landing_host
        code, res = client.post_json("/api/node/join-token", body)
        if code != 200 or not isinstance(res, dict) or res.get("ok") is not True:
            msg = (res.get("error") or res.get("message")) if isinstance(res, dict) else None
            raise CapabilityError("JOIN_TOKEN_FAILED", msg or "生成反向入网命令失败。", status=code if code >= 400 else 502)
        return {
            "ok": True,
            "method": "reverse_join",
            "name": res.get("name") or name,
            "role": res.get("role") or role,
            "port": res.get("port") or port,
            "landing": res.get("landing"),
            "expires_in": res.get("expires_in"),
            "join_command": res.get("command") or "",
        }

    # method == "ssh_managed"
    ssh_handle = str(params.get("ssh_handle") or "").strip()
    if not ssh_handle:
        raise CapabilityError("SSH_HANDLE_REQUIRED", "SSH 纳管扩容必须提供 ssh 凭据句柄（ssh_handle）。", 400)
    ssh_secret = ctx.borrow(ssh_handle, "ssh")
    fingerprint = str(params.get("fingerprint") or "").strip()
    check_req = {
        "host": ssh_secret["host"],
        "username": ssh_secret.get("username") or "root",
        "ssh_port": int(ssh_secret.get("ssh_port") or 22),
    }
    if ssh_secret.get("private_key"):
        check_req["private_key"] = ssh_secret["private_key"]
        if ssh_secret.get("passphrase"):
            check_req["passphrase"] = ssh_secret["passphrase"]
    else:
        check_req["password"] = ssh_secret.get("password") or ""
    if fingerprint:
        check_req["fingerprint"] = fingerprint

    chk_code, chk_res = client.post_json("/api/node/check", check_req)
    check_req.clear()
    if chk_code != 200 or not isinstance(chk_res, dict) or chk_res.get("ok") is not True:
        err_code = chk_res.get("code") if isinstance(chk_res, dict) else "NODE_CHECK_FAILED"
        msg = (chk_res.get("message") or chk_res.get("error")) if isinstance(chk_res, dict) else "目标节点预检失败。"
        detail = {}
        if isinstance(chk_res, dict) and chk_res.get("fingerprint"):
            detail["fingerprint"] = chk_res["fingerprint"]
        raise CapabilityError(err_code or "NODE_CHECK_FAILED", msg, status=chk_code if chk_code >= 400 else 400, detail=detail)

    ticket = chk_res.get("check_ticket")
    if not ticket:
        raise CapabilityError("CHECK_TICKET_MISSING", "预检通过但未返回有效 check_ticket。", 400)

    node_name = name or f"节点-{ssh_secret['host']}"
    add_req = {
        "check_ticket": ticket,
        "name": node_name,
        "role": role,
        "port": port,
        "self_bootstrap": False,
    }
    if landing_host:
        add_req["landing"] = {"host": landing_host}
    add_code, add_res = client.post_json("/api/addnode", add_req)
    if add_code != 200 or not isinstance(add_res, dict) or add_res.get("ok") is not True:
        msg = (add_res.get("error") or add_res.get("message")) if isinstance(add_res, dict) else None
        raise CapabilityError("ADDNODE_FAILED", msg or "提交节点纳管任务失败。", status=add_code if add_code >= 400 else 500)

    job_id = str(add_res.get("job") or "")
    job_timeout = max(5, int(params.get("job_timeout_seconds") or 120))
    poll_step = min(1.0, max(0.05, float(params.get("poll_interval") or 0.5)))
    deadline = time.monotonic() + job_timeout
    job_state = {"state": "queued"}
    while time.monotonic() < deadline and job_id:
        jc, jd = client.get_json(f"/api/node/job?id={job_id}")
        if jc == 200 and isinstance(jd, dict):
            job_state = jd
            if jd.get("state") in ("done", "error", "failed"):
                break
        time.sleep(poll_step)

    if job_state.get("state") != "done":
        raise CapabilityError(
            job_state.get("error_code") or "ADDNODE_JOB_INCOMPLETE",
            job_state.get("error") or f"节点纳管任务未完成 (state={job_state.get('state')})。",
            status=502,
        )

    paired = None
    if role == "relay" and auto_pair:
        if landing_host:
            pb_code, pb_res = client.post_json("/api/relay/bind", {"name": node_name, "target": landing_host})
        else:
            pb_code, pb_res = client.post_json("/api/relay/auto-pair", {})
        paired = pb_res if pb_code == 200 else {"ok": False, "error": pb_res.get("error") if isinstance(pb_res, dict) else "pair failed"}

    return {
        "ok": True,
        "method": "ssh_managed",
        "job_id": job_id,
        "state": job_state.get("state"),
        "node_name": node_name,
        "role": role,
        "port": port,
        "health": job_state.get("health") or "unknown",
        "paired": paired,
    }


CAPABILITY = CapabilitySpec(
    name="relay-expand",
    title="国内中继/海外节点扩容与专线配对",
    description="支持反向免密自举（生成一次性入网命令）、SSH 盲签纳管以及国内中转-海外落地自动配对。",
    required_slots=("panel_auth",),
    params_schema={
        "panel_handle": {"type": "vault_handle:panel_auth", "required": True},
        "method": {"type": "enum:reverse_join|ssh_managed|pair_only", "required": False, "default": "reverse_join"},
        "name": {"type": "string", "required": False},
        "role": {"type": "enum:relay|exit|auto", "required": False, "default": "relay"},
        "port": {"type": "integer", "required": False},
        "landing_host": {"type": "string", "required": False},
        "fallback_host": {"type": "string", "required": False},
        "ssh_handle": {"type": "vault_handle:ssh", "required": False},
        "fingerprint": {"type": "string", "required": False},
        "auto_pair": {"type": "boolean", "required": False, "default": True},
        "insecure_tls": {"type": "boolean", "required": False, "default": False},
    },
    handler=_handle,
    supports_dry_run=True,
)
