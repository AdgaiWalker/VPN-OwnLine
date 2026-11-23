"""声明式状态收敛引擎与节点可控边界单一真理源。

提供：
1. node_capability(node): 统一判定节点控制能力（managed / external / reverse_join / windows_frozen / cleanup_pending）；
2. build_desired_config(node, live_params, hy2_node=None): 由声明式底账推导期望的 sing-box 配置；
3. diff_configs(actual, desired, redact=True): 结构化差异比对（自动脱敏密钥）；
4. inspect_node_drift / inspect_cluster_drift / reconcile_node: 只读漂移检测与原子收敛（失败自动回滚）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from . import provenance as prov_mod
from . import quota_guard
from . import remote_config as _remote_cfg
from . import templates
from . import verify as verify_mod

_SENSITIVE_KEYS = frozenset({
    "private_key",
    "public_key",
    "password",
    "obfs_password",
    "uuid",
    "short_id",
})


def node_capability(node: Any) -> Dict[str, Any]:
    """返回节点唯一权威控制能力描述。"""
    if not isinstance(node, dict):
        return {
            "mode": "invalid",
            "controllable": False,
            "can_reconcile": False,
            "can_mutate_remote": False,
            "can_auto_repair": False,
            "can_quota_stop": False,
            "reason": "节点数据无效",
        }

    source = node.get("source")
    if source == "external":
        return {
            "mode": "external",
            "controllable": False,
            "can_reconcile": False,
            "can_mutate_remote": False,
            "can_auto_repair": False,
            "can_quota_stop": False,
            "reason": "外部节点无 SSH 控制权限，仅支持订阅分发与连通探测",
        }
    if source == "reverse_join":
        return {
            "mode": "reverse_join",
            "controllable": False,
            "can_reconcile": False,
            "can_mutate_remote": False,
            "can_auto_repair": False,
            "can_quota_stop": False,
            "reason": "免密反向接入节点仅支持订阅分发与连通探测，请在目标机本机运维",
        }
    if prov_mod.is_windows(node):
        return {
            "mode": "windows_frozen",
            "controllable": False,
            "can_reconcile": False,
            "can_mutate_remote": False,
            "can_auto_repair": False,
            "can_quota_stop": False,
            "reason": "Windows 受控分支已冻结，仅支持观测与人工运维",
        }
    if node.get("cleanup_pending"):
        return {
            "mode": "cleanup_pending",
            "controllable": False,
            "can_reconcile": False,
            "can_mutate_remote": False,
            "can_auto_repair": False,
            "can_quota_stop": False,
            "reason": "节点待人工清理，已禁止远端变更",
        }

    return {
        "mode": "managed",
        "controllable": True,
        "can_reconcile": True,
        "can_mutate_remote": True,
        "can_auto_repair": True,
        "can_quota_stop": quota_guard.supports_quota_control(node),
        "reason": "",
    }


def canonical_sha256(cfg: Dict[str, Any]) -> str:
    """计算配置对象在键顺序无关规范化后的 SHA-256。"""
    encoded = json.dumps(cfg, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_desired_config(
    node: Dict[str, Any],
    live_params: Dict[str, Any],
    *,
    hy2_node: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """由节点声明式底账及不可变入站私钥生成期望的 sing-box 配置。"""
    private_key = live_params.get("private_key") or ""
    if not private_key:
        raise ValueError("现网配置缺少入站 Reality private_key，无法推导期望配置")

    port = int(node.get("port") or live_params.get("port") or 443)
    uuid = node.get("uuid") or live_params.get("uuid") or ""
    sni = node.get("sni") or live_params.get("sni") or "www.apple.com"
    sid = str(node.get("sid") or live_params.get("sid") or "")

    landing = node.get("landing")
    if node.get("role") == "relay" and isinstance(landing, dict) and landing.get("host"):
        landing_cfg = dict(landing)
        landing_cfg.setdefault("sni", landing_cfg.get("host") or "www.apple.com")
        landing_cfg.setdefault("port", 443)
        fallback = node.get("fallback_landing")
        if isinstance(fallback, dict) and fallback.get("host"):
            fallback_cfg = dict(fallback)
            fallback_cfg.setdefault("sni", fallback_cfg.get("host") or "www.apple.com")
            fallback_cfg.setdefault("port", 443)
        else:
            fallback_cfg = None
        return templates.relay_config(
            port=port,
            uuid=uuid,
            sni=sni,
            private_key=private_key,
            sid=sid,
            landing=landing_cfg,
            fallback_landing=fallback_cfg,
        )

    live_hy2 = live_params.get("hy2") if isinstance(live_params.get("hy2"), dict) else None
    desired_hy2 = None
    if hy2_node is not None:
        hy2_enabled = (hy2_node.get("enabled", True) is not False) and (node.get("hy2_enabled", True) is not False)
        if hy2_enabled:
            pw = hy2_node.get("password") or (live_hy2 or {}).get("password") or ""
            obfs = hy2_node.get("obfs_password") or (live_hy2 or {}).get("obfs_password") or ""
            if pw and obfs:
                desired_hy2 = {
                    "port": int(hy2_node.get("port") or (live_hy2 or {}).get("port") or port),
                    "password": pw,
                    "obfs_password": obfs,
                    "sni": hy2_node.get("sni") or (live_hy2 or {}).get("sni") or "www.apple.com",
                }
    elif node.get("hy2_enabled") is True and live_hy2:
        desired_hy2 = dict(live_hy2)

    raw_isp = node.get("isp")
    desired_isp = (
        dict(raw_isp)
        if isinstance(raw_isp, dict) and raw_isp.get("server") and raw_isp.get("server_port")
        else None
    )

    desired_warp = None
    if node.get("warp_enabled") is True:
        warp_cand = node.get("warp") or live_params.get("warp")
        if isinstance(warp_cand, dict) and (warp_cand.get("private_key") or warp_cand.get("type") == "socks"):
            desired_warp = warp_cand

    return templates.exit_config(
        port=port,
        uuid=uuid,
        sni=sni,
        private_key=private_key,
        sid=sid,
        hy2=desired_hy2,
        isp=desired_isp,
        warp=desired_warp,
    )


def _is_sensitive_path(path: str) -> bool:
    if not path:
        return False
    for segment in path.replace("[", ".").split("."):
        if segment in _SENSITIVE_KEYS:
            return True
    return False


def diff_configs(actual: Any, desired: Any, path: str = "", *, redact: bool = True) -> List[str]:
    """逐字段比较 JSON 结构差异（忽略字典键序，默认对凭据字段脱敏）。"""
    diffs: List[str] = []
    if type(actual) is not type(desired) and not (
        isinstance(actual, (int, float)) and not isinstance(actual, bool)
        and isinstance(desired, (int, float)) and not isinstance(desired, bool)
    ):
        diffs.append("%s: 类型不同 %s vs %s" % (path or "根", type(actual).__name__, type(desired).__name__))
        return diffs

    if isinstance(actual, dict):
        for k in sorted(set(actual) | set(desired)):
            sub_path = ("%s.%s" % (path, k)) if path else k
            if k not in actual:
                diffs.append("%s: 现网缺失" % sub_path)
            elif k not in desired:
                diffs.append("%s: 期望未声明" % sub_path)
            else:
                diffs.extend(diff_configs(actual[k], desired[k], sub_path, redact=redact))
        return diffs

    if isinstance(actual, list):
        if len(actual) != len(desired):
            diffs.append("%s: 元素数不同 现网 %d vs 期望 %d" % (path or "根", len(actual), len(desired)))
        for idx in range(min(len(actual), len(desired))):
            diffs.extend(diff_configs(actual[idx], desired[idx], "%s[%d]" % (path, idx), redact=redact))
        return diffs

    if actual != desired:
        if redact and _is_sensitive_path(path):
            diffs.append("%s: [REDACTED] 不一致" % (path or "根"))
        else:
            diffs.append("%s: 现网 %r vs 期望 %r" % (path or "根", actual, desired))
    return diffs


def _inspect_node_drift_internal(
    node: Dict[str, Any],
    *,
    hy2_node: Optional[Dict[str, Any]] = None,
    runner=None,
    cfg_path: Optional[str] = None,
    remote_cfg_mod: Any = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    rc = remote_cfg_mod or _remote_cfg
    cap = node_capability(node)
    base = {
        "name": (node or {}).get("name") or "",
        "host": (node or {}).get("host") or "",
        "capability": cap,
    }
    if not cap["controllable"]:
        return {
            **base,
            "ok": True,
            "status": "unmanaged",
            "diffs": [],
            "diff_count": 0,
            "reason": cap["reason"],
        }, None

    ok_read, err_read, live_cfg = rc.read_live_config(node, runner=runner, cfg_path=cfg_path)
    if not ok_read:
        return {
            **base,
            "ok": False,
            "status": "error",
            "error": err_read,
            "diffs": [],
            "diff_count": 0,
        }, None

    try:
        live_params = rc.extract_live_params(live_cfg, fallback_node=node)
        desired = build_desired_config(node, live_params, hy2_node=hy2_node)
    except ValueError as exc:
        return {
            **base,
            "ok": False,
            "status": "error",
            "error": str(exc),
            "diffs": [],
            "diff_count": 0,
        }, None

    diffs = diff_configs(live_cfg, desired, redact=True)
    return {
        **base,
        "ok": True,
        "status": "in_sync" if not diffs else "drifted",
        "diffs": diffs,
        "diff_count": len(diffs),
        "actual_sha256": canonical_sha256(live_cfg),
        "desired_sha256": canonical_sha256(desired),
    }, desired


def inspect_node_drift(
    node: Dict[str, Any],
    *,
    hy2_node: Optional[Dict[str, Any]] = None,
    runner=None,
    cfg_path: Optional[str] = None,
    remote_cfg_mod: Any = None,
) -> Dict[str, Any]:
    """只读检查单个节点现网配置与期望配置的偏移。"""
    result, _ = _inspect_node_drift_internal(
        node,
        hy2_node=hy2_node,
        runner=runner,
        cfg_path=cfg_path,
        remote_cfg_mod=remote_cfg_mod,
    )
    return result


def reconcile_node(
    node: Dict[str, Any],
    *,
    hy2_node: Optional[Dict[str, Any]] = None,
    apply: bool = False,
    runner=None,
    verifier=None,
    cfg_path: Optional[str] = None,
    bin_path: Optional[str] = None,
    master_secret: Optional[bytes | str] = None,
    remote_cfg_mod: Any = None,
) -> Dict[str, Any]:
    """对受控节点执行声明式状态比对；apply=True 时才通过归属门禁下发并验真，失败自动回滚。"""
    rc = remote_cfg_mod or _remote_cfg
    verifier = verifier or verify_mod.run
    report, desired = _inspect_node_drift_internal(
        node,
        hy2_node=hy2_node,
        runner=runner,
        cfg_path=cfg_path,
        remote_cfg_mod=rc,
    )
    if not report.get("ok") or report.get("status") != "drifted":
        return {**report, "changed": False, "applied": False}

    if not apply:
        return {**report, "changed": False, "applied": False, "dry_run": True}

    hy2_in = None
    if desired:
        hy2_ib = next((ib for ib in desired.get("inbounds", []) if ib.get("type") == "hysteria2"), None)
        if hy2_ib:
            hy2_in = {
                "sni": (hy2_ib.get("tls") or {}).get("server_name") or "www.apple.com",
                "port": int(hy2_ib.get("listen_port") or 443),
            }

    applied, apply_err = rc.apply_config(
        node,
        desired,
        runner=runner,
        cfg_path=cfg_path,
        bin_path=bin_path,
        ensure_hy2_cert=hy2_in,
        master_secret=master_secret,
    )
    if not applied:
        return {
            **report,
            "ok": False,
            "status": "error",
            "error": apply_err,
            "changed": False,
            "applied": False,
        }

    vr = verifier(node) or {"health": "proxy", "detail": "探测无响应"}
    if vr.get("health") != "ok":
        rolled_back = rc.rollback_config(
            node,
            runner=runner,
            cfg_path=cfg_path,
            bin_path=bin_path,
            master_secret=master_secret,
        )
        rb_note = "已自动回滚原配置" if rolled_back else "自动回滚未确认成功，请人工检查"
        return {
            **report,
            "ok": False,
            "status": "rolled_back",
            "changed": False,
            "applied": False,
            "rolled_back": rolled_back,
            "verify": vr,
            "error": "状态收敛后代理出网探测未通过（%s），%s" % (vr.get("detail") or vr.get("health"), rb_note),
        }

    return {
        **report,
        "ok": True,
        "status": "converged",
        "changed": True,
        "applied": True,
        "verify": vr,
    }


def _find_companion_hy2(nodes: List[Dict[str, Any]], primary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    gid = primary.get("group_id")
    if gid:
        return next(
            (n for n in nodes if n is not primary and n.get("group_id") == gid and n.get("type") == "hysteria2"),
            None,
        )
    host = primary.get("host")
    comp_name = (primary.get("name") or "") + "-HY2"
    return next(
        (
            n
            for n in nodes
            if n is not primary
            and n.get("type") == "hysteria2"
            and (n.get("name") == comp_name or (host and n.get("host") == host))
        ),
        None,
    )


def _find_primary_for_hy2(nodes: List[Dict[str, Any]], hy2_node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    gid = hy2_node.get("group_id")
    if gid:
        hit = next((n for n in nodes if n is not hy2_node and n.get("group_id") == gid and n.get("type") != "hysteria2"), None)
        if hit:
            return hit
    host = hy2_node.get("host")
    name = hy2_node.get("name") or ""
    base = name[:-4] if name.endswith("-HY2") else ""
    return next(
        (
            n
            for n in nodes
            if n is not hy2_node
            and n.get("type") != "hysteria2"
            and ((base and n.get("name") == base) or (host and n.get("host") == host))
        ),
        None,
    )


def inspect_cluster_drift(
    nodes: List[Dict[str, Any]],
    *,
    target_name: Optional[str] = None,
    runner=None,
    remote_cfg_mod: Any = None,
) -> Dict[str, Any]:
    """检查全集群（或指定节点）的声明式配置漂移现状（只读）。"""
    node_list = list(nodes or [])
    results: List[Dict[str, Any]] = []
    seen_ids = set()

    for n in node_list:
        if target_name and n.get("name") != target_name:
            continue
        if n.get("type") == "hysteria2":
            primary = _find_primary_for_hy2(node_list, n)
            if primary is not None:
                if not target_name:
                    continue
                target_primary = primary
                companion_hy2 = n
            else:
                target_primary = n
                companion_hy2 = None
        else:
            target_primary = n
            companion_hy2 = _find_companion_hy2(node_list, n)

        marker = id(target_primary)
        if marker in seen_ids:
            continue
        seen_ids.add(marker)
        results.append(
            inspect_node_drift(
                target_primary,
                hy2_node=companion_hy2,
                runner=runner,
                remote_cfg_mod=remote_cfg_mod,
            )
        )

    return {
        "ok": True,
        "in_sync_count": sum(1 for r in results if r.get("status") == "in_sync"),
        "drifted_count": sum(1 for r in results if r.get("status") == "drifted"),
        "unmanaged_count": sum(1 for r in results if r.get("status") == "unmanaged"),
        "error_count": sum(1 for r in results if r.get("status") == "error"),
        "results": results,
    }
