#!/usr/bin/env python3
"""腾讯云流量包防爆熔断器（纯标准库，零外部依赖）。

职责：
  1. 识别中转节点的「进出双向双倍计费」特征（跑 1GB 实际消耗 2GB 配额）。
  2. 水位警戒线管理：
     - normal  (< 75%): 正常放行
     - warning (>= 75% 且 < 85%): 预警状态，提示管理员即将用尽
     - tripped (>= 85%): 熔断生效，自动将国内中转节点降级，
       客户端平滑退守海外直连出口，杜绝产生按量扣费账单。
"""
import json
import os

DEFAULT_WARNING_PCT = 75.0
DEFAULT_TRIPPED_PCT = 85.0
DEFAULT_PACKAGE_SIZE = 1024 ** 4  # 默认 1TB


def evaluate_instance_quota(instance_data, warning_pct=DEFAULT_WARNING_PCT,
                            tripped_pct=DEFAULT_TRIPPED_PCT):
    """评估单台实例的流量包使用状态。
    输入单台字典（来自 usage.json），返回状态字典。
    """
    if not isinstance(instance_data, dict):
        return {
            "status": "unknown",
            "percent": 0.0,
            "used_bytes": 0,
            "total_bytes": DEFAULT_PACKAGE_SIZE,
            "is_tripped": False,
            "is_warning": False,
            "reason": "无用量数据",
        }

    pkg = instance_data.get("traffic_package") or {}
    used_bytes = int(pkg.get("used_bytes") or 0)
    total_bytes = int(pkg.get("total_bytes") or DEFAULT_PACKAGE_SIZE)

    pct = round((used_bytes / total_bytes) * 100, 2) if total_bytes > 0 else 0.0

    if pct >= tripped_pct:
        status = "tripped"
        is_tripped = True
        is_warning = True
        reason = f"已消耗 {pct:.1f}% 超过熔断线 {tripped_pct:.0f}%，已触发安全熔断防扣费"
    elif pct >= warning_pct:
        status = "warning"
        is_tripped = False
        is_warning = True
        reason = f"已消耗 {pct:.1f}% 超过警戒线 {warning_pct:.0f}%，请留意流量余量"
    else:
        status = "normal"
        is_tripped = False
        is_warning = False
        reason = f"用量正常 ({pct:.1f}%)"

    return {
        "status": status,
        "percent": pct,
        "used_bytes": used_bytes,
        "total_bytes": total_bytes,
        "is_tripped": is_tripped,
        "is_warning": is_warning,
        "reason": reason,
    }


def evaluate_all(usage_json_data, warning_pct=DEFAULT_WARNING_PCT,
                 tripped_pct=DEFAULT_TRIPPED_PCT):
    """批量评估集群所有机器的配额安全水位。
    返回 {ip: evaluation_dict, "_summary": ...}
    """
    results = {}
    any_tripped = False
    any_warning = False

    for ip, data in (usage_json_data or {}).items():
        if ip.startswith("_") or not isinstance(data, dict):
            continue
        eval_res = evaluate_instance_quota(data, warning_pct=warning_pct, tripped_pct=tripped_pct)
        eval_res["name"] = data.get("name") or ip
        results[ip] = eval_res
        if eval_res["is_tripped"]:
            any_tripped = True
        if eval_res["is_warning"]:
            any_warning = True

    results["_summary"] = {
        "any_tripped": any_tripped,
        "any_warning": any_warning,
        "watermarks": {"warning": warning_pct, "tripped": tripped_pct},
    }
    return results


def is_node_circuit_broken(node_host, usage_json_data, tripped_pct=DEFAULT_TRIPPED_PCT):
    """判断指定节点的 IP 是否已触发熔断。"""
    if not node_host or not usage_json_data:
        return False
    data = usage_json_data.get(node_host)
    if not data:
        return False
    eval_res = evaluate_instance_quota(data, tripped_pct=tripped_pct)
    return eval_res["is_tripped"]
