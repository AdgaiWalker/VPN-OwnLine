"""Declarative topology plan compiler, raw-secret gate, and multi-step orchestrator."""

import copy
import re
from typing import Any, Dict, List

from .capabilities import CapabilityContext, CapabilityError, CapabilityRegistry, RemotePanelClient
from .local_vault import VaultError

FORBIDDEN_SECRET_KEYS = frozenset({
    "password",
    "passwd",
    "passphrase",
    "private_key",
    "secret_key",
    "secret_id",
    "proxy_url",
    "temp_password",
    "current",
    "new",
    "confirm",
    "secret",
})

_PEM_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----")
_URL_CRED_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@'\"]+:[^\s/@'\"]+@")
_FOUR_PART_PROXY_RE = re.compile(
    r"^\s*(?:(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9.-]+\.[A-Za-z]{2,}):(\d{1,5}):([^\s:]+):([^\s]+)\s*$"
)


def assert_plan_has_no_raw_secrets(obj: Any, _path: str = "") -> None:
    """Fail closed before execution if any plaintext credential appears in CLI params or plan."""
    if obj is None or isinstance(obj, (bool, int, float)):
        return
    if isinstance(obj, str):
        if _PEM_RE.search(obj) or _URL_CRED_RE.search(obj) or _FOUR_PART_PROXY_RE.match(obj):
            raise CapabilityError(
                "RAW_SECRET_FORBIDDEN",
                f"检测到明文凭据格式（{_path or 'input'}），禁止在参数或编排计划中直接传入明文，请先使用 ownline.py vault request 获取句柄。",
                400,
            )
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_str = str(k)
            lower = key_str.strip().lower()
            next_path = f"{_path}.{key_str}" if _path else key_str
            if lower in FORBIDDEN_SECRET_KEYS and v not in (None, "", False):
                raise CapabilityError(
                    "RAW_SECRET_FORBIDDEN",
                    f"禁止在编排计划或命令行参数中传递明文字段 `{next_path}`，请先通过 ownline.py vault request 获取句柄。",
                    400,
                )
            assert_plan_has_no_raw_secrets(v, next_path)
        return
    if isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            assert_plan_has_no_raw_secrets(item, f"{_path}[{idx}]")
        return


def compile_topology_steps(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(plan, dict):
        raise CapabilityError("TOPOLOGY_PLAN_INVALID", "拓扑编排计划必须是 JSON 对象。", 400)
    assert_plan_has_no_raw_secrets(plan)

    panel_cfg = plan.get("panel") if isinstance(plan.get("panel"), dict) else {}
    base_handle = str(panel_cfg.get("handle") or plan.get("panel_handle") or "").strip()
    base_url = str(panel_cfg.get("dashboard_url") or plan.get("dashboard_url") or "").strip()
    base_insecure = bool(panel_cfg.get("insecure_tls", plan.get("insecure_tls", False)))

    steps: List[Dict[str, Any]] = []

    rot = plan.get("rotate_initial_password")
    if rot is not None and rot is not False:
        if not isinstance(rot, dict):
            raise CapabilityError("TOPOLOGY_PLAN_INVALID", "rotate_initial_password 必须是配置对象。", 400)
        step_params = {
            "new_panel_handle": str(rot.get("new_panel_handle") or "").strip(),
            "current_panel_handle": str(rot.get("current_panel_handle") or base_handle or "").strip(),
            "dashboard_url": str(rot.get("dashboard_url") or base_url or "").strip(),
            "insecure_tls": bool(rot.get("insecure_tls", base_insecure)),
        }
        steps.append({"capability": "panel-password", "params": step_params})

    isp = plan.get("residential_isp")
    if isp is not None and isp is not False:
        if not isinstance(isp, dict):
            raise CapabilityError("TOPOLOGY_PLAN_INVALID", "residential_isp 必须是配置对象。", 400)
        step_params = {
            "panel_handle": str(isp.get("panel_handle") or base_handle or "").strip(),
            "isp_handle": str(isp.get("isp_handle") or "").strip(),
            "node_name": str(isp.get("node_name") or "").strip(),
            "unbind": bool(isp.get("unbind", False)),
            "dashboard_url": str(isp.get("dashboard_url") or base_url or "").strip(),
            "insecure_tls": bool(isp.get("insecure_tls", base_insecure)),
        }
        steps.append({"capability": "residential-isp", "params": step_params})

    relay_cfg = plan.get("relay")
    if relay_cfg is not None and relay_cfg is not False:
        relay_items = relay_cfg if isinstance(relay_cfg, list) else [relay_cfg]
        for item in relay_items:
            if not isinstance(item, dict):
                raise CapabilityError("TOPOLOGY_PLAN_INVALID", "relay 项必须是配置对象。", 400)
            step_params = dict(item)
            step_params.setdefault("panel_handle", base_handle)
            step_params.setdefault("dashboard_url", base_url)
            step_params.setdefault("insecure_tls", base_insecure)
            steps.append({"capability": "relay-expand", "params": step_params})

    verify_cfg = plan.get("verify")
    if verify_cfg is not False:
        if verify_cfg is None or verify_cfg is True:
            verify_dict: Dict[str, Any] = {}
        elif isinstance(verify_cfg, dict):
            verify_dict = dict(verify_cfg)
        else:
            raise CapabilityError("TOPOLOGY_PLAN_INVALID", "verify 必须是布尔值或配置对象。", 400)
        verify_dict.setdefault("panel_handle", base_handle)
        verify_dict.setdefault("dashboard_url", base_url)
        verify_dict.setdefault("insecure_tls", base_insecure)
        steps.append({"capability": "topology-verify", "params": verify_dict})

    if not steps:
        raise CapabilityError("TOPOLOGY_PLAN_EMPTY", "拓扑编排计划为空，未包含任何可执行步骤。", 400)
    return steps


def execute_topology_plan(
    plan: Dict[str, Any],
    *,
    registry: CapabilityRegistry,
    vault,
    session=None,
    emit_diag=None,
    dry_run: bool = False,
    panel_client_factory=RemotePanelClient,
) -> Dict[str, Any]:
    steps = compile_topology_steps(plan)
    panel_cfg = plan.get("panel") if isinstance(plan.get("panel"), dict) else {}
    active_panel_handle = str(panel_cfg.get("handle") or plan.get("panel_handle") or "").strip() or None
    if not active_panel_handle and isinstance(plan.get("rotate_initial_password"), dict):
        active_panel_handle = str(plan["rotate_initial_password"].get("current_panel_handle") or "").strip() or None

    if emit_diag:
        emit_diag("topology_plan_started", {"step_count": len(steps), "dry_run": bool(dry_run)})

    completed: List[Dict[str, Any]] = []
    initial_gate_pending = False
    for idx, step in enumerate(steps):
        cap_name = step["capability"]
        params = copy.deepcopy(step["params"])
        if cap_name != "panel-password" and not params.get("panel_handle") and active_panel_handle:
            params["panel_handle"] = active_panel_handle
        if dry_run and initial_gate_pending and cap_name != "panel-password":
            params["_initial_gate_pending"] = True

        ctx = CapabilityContext(
            vault=vault,
            session=session,
            emit_diag=emit_diag,
            dry_run=bool(dry_run),
            panel_client_factory=panel_client_factory,
        )
        try:
            res = registry.execute(cap_name, params, ctx=ctx)
            if cap_name == "panel-password":
                if dry_run:
                    initial_gate_pending = True
                elif res.get("active_panel_handle"):
                    active_panel_handle = str(res["active_panel_handle"])
            completed.append({"step": idx + 1, "capability": cap_name, "result": res})
        except (CapabilityError, VaultError) as exc:
            err_code = getattr(exc, "code", "TOPOLOGY_STEP_FAILED")
            err_msg = getattr(exc, "message", str(exc))
            err_status = getattr(exc, "status", 400)
            extra_detail = getattr(exc, "detail", None) or {}
            if emit_diag:
                emit_diag(
                    "topology_plan_failed",
                    {"failed_step": cap_name, "step": idx + 1, "code": err_code},
                    severity="error",
                )
            raise CapabilityError(
                err_code,
                err_msg,
                status=err_status,
                detail={
                    "failed_step": cap_name,
                    "step_index": idx + 1,
                    "completed_steps": completed,
                    **extra_detail,
                },
            ) from None

    if emit_diag:
        emit_diag("topology_plan_completed", {"step_count": len(completed), "dry_run": bool(dry_run)})

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "active_panel_handle": active_panel_handle or "",
        "steps": completed,
    }
