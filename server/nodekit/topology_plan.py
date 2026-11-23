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


INTENT_PRESETS: Dict[str, Dict[str, Any]] = {
    "budget_basic": {
        "title": "极简入门：单台海外节点（Reality + HY2 双通道）",
        "rationale": "最低成本（0~99 元/年），默认双协议抗普通丢包，适合个人日常联网。",
        "required_vault_slots": ["ssh", "panel_auth"],
        "apply_plan_template": {
            "rotate_initial_password": {"new_panel_handle": "<vh_panel_auth>"},
            "verify": {"quick": False, "check_subscription": True},
        },
    },
    "ai_clean_ip": {
        "title": "AI 防封专线：单台海外 + Webshare 静态住宅出口",
        "rationale": "为海外节点挂载真实美国家宽 IP（约 +85 元/年），彻底解决 ChatGPT/Claude 机房风控拒访。",
        "required_vault_slots": ["ssh", "panel_auth", "webshare_isp"],
        "apply_plan_template": {
            "rotate_initial_password": {"new_panel_handle": "<vh_panel_auth>"},
            "residential_isp": {"isp_handle": "<vh_webshare_isp>"},
            "verify": {"quick": False, "check_subscription": True},
        },
    },
    "peak_stable": {
        "title": "晚高峰抗丢包：海外落地 + 国内轻量中转专线",
        "rationale": "利用国内云机 BGP 骨干网转发至海外出口，消除晚高峰跨国骨干丢包与卡顿。",
        "required_vault_slots": ["ssh", "panel_auth"],
        "apply_plan_template": {
            "rotate_initial_password": {"new_panel_handle": "<vh_panel_auth>"},
            "relay": {"method": "reverse_join", "role": "relay", "name": "国内中继-01"},
            "verify": {"quick": False, "check_subscription": True},
        },
    },
    "full_stack": {
        "title": "全配稳定版：国内中转 + 海外落地 + Webshare 静态住宅",
        "rationale": "兼顾晚高峰低延迟与纯净住宅出口，适合重度 AI 办公与稳定性优先场景。",
        "required_vault_slots": ["ssh", "panel_auth", "webshare_isp"],
        "apply_plan_template": {
            "rotate_initial_password": {"new_panel_handle": "<vh_panel_auth>"},
            "residential_isp": {"isp_handle": "<vh_webshare_isp>"},
            "relay": {"method": "reverse_join", "role": "relay", "name": "国内中继-01"},
            "verify": {"quick": False, "check_subscription": True},
        },
    },
}

_AI_KEYWORDS = ("chatgpt", "openai", "claude", "ai", "住宅", "家宽", "webshare", "isp", "防封", "解锁")
_RELAY_KEYWORDS = ("中转", "专线", "晚高峰", "丢包", "卡顿", "稳定", "relay", "peak", "domestic", "latency")
_BUDGET_KEYWORDS = ("便宜", "入门", "基础", "省钱", "免费", "0元", "budget", "basic", "cheap", "single")


def resolve_intent_preset(intent_text: str) -> Dict[str, Any]:
    """Deterministically map natural-language user intent or preset ID to a topology preset."""
    raw = str(intent_text or "").strip()
    assert_plan_has_no_raw_secrets(raw, _path="intent")
    low = raw.lower()
    if low in INTENT_PRESETS:
        return {"preset": low, "matched_by": "preset_id"}

    wants_ai = any(k in low for k in _AI_KEYWORDS)
    wants_relay = any(k in low for k in _RELAY_KEYWORDS)
    if wants_ai and wants_relay:
        return {"preset": "full_stack", "matched_by": "keyword"}
    if wants_ai:
        return {"preset": "ai_clean_ip", "matched_by": "keyword"}
    if wants_relay:
        return {"preset": "peak_stable", "matched_by": "keyword"}
    if any(k in low for k in _BUDGET_KEYWORDS):
        return {"preset": "budget_basic", "matched_by": "keyword"}
    return {"preset": "budget_basic", "matched_by": "default"}


def build_intent_blueprint(intent_text: str) -> Dict[str, Any]:
    """Return a zero-secret declarative onboarding + apply blueprint for a user goal."""
    resolved = resolve_intent_preset(intent_text)
    spec = copy.deepcopy(INTENT_PRESETS[resolved["preset"]])
    return {
        "ok": True,
        "preset": resolved["preset"],
        "matched_by": resolved["matched_by"],
        "title": spec["title"],
        "rationale": spec["rationale"],
        "required_vault_slots": spec["required_vault_slots"],
        "apply_plan_template": spec["apply_plan_template"],
        "onboarding_ref": "web/src/data/onboarding.json",
        "security_note": "所有敏感凭据必须通过 python3 ownline.py vault request 获取句柄，禁止传入明文。",
    }
