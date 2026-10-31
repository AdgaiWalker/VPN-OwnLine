#!/usr/bin/env python3
"""腾讯云流量包防爆熔断器（纯标准库，零外部依赖）。

职责：
  1. 识别中转与出口节点的流量消耗水位：
     - normal  (< 75%): 正常放行
     - warning (>= 75% 且 < 85%): 预警状态，提示即将用尽
     - tripped (>= 85%): 熔断生效，自动切除中转/超标节点：
       - 在每 10 分钟定时任务中对已超标实例执行远程停机断流；
       - 在订阅下发层自动剔除该节点，客户端平滑退守直连备用机。
"""
import json
import os
import subprocess

try:
    from . import repair
except ImportError:
    try:
        import repair
    except ImportError:
        repair = None

try:
    from . import logger
except ImportError:
    try:
        import logger
    except ImportError:
        logger = None

DEFAULT_WARNING_PCT = 75.0
DEFAULT_TRIPPED_PCT = 85.0
DEFAULT_PACKAGE_SIZE = 1024 ** 4  # 默认 1TB
QUOTA_STATE_FILE = os.environ.get("QUOTA_STATE_FILE", "/opt/web-data/quota_state.json")


def evaluate_instance_quota(instance_data, warning_pct=DEFAULT_WARNING_PCT,
                            tripped_pct=DEFAULT_TRIPPED_PCT):
    """评估单台实例的流量包使用状态。
    支持生产环境真实格式 (used/total in GB) 及备用格式 (traffic_package in bytes)。
    """
    if not isinstance(instance_data, dict):
        return {
            "status": "unknown",
            "percent": 0.0,
            "used_gb": 0.0,
            "total_gb": 1024.0,
            "used_bytes": 0,
            "total_bytes": DEFAULT_PACKAGE_SIZE,
            "is_tripped": False,
            "is_warning": False,
            "reason": "无用量数据",
        }

    # 优先解析生产环境真实字段 (used / total in GB)
    if "used" in instance_data and "total" in instance_data:
        try:
            used_gb = float(instance_data.get("used") or 0.0)
            total_gb = float(instance_data.get("total") or 1024.0)
            used_bytes = int(used_gb * (1024 ** 3))
            total_bytes = int(total_gb * (1024 ** 3))
            pct = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0.0
        except Exception:
            used_gb, total_gb, pct = 0.0, 1024.0, 0.0
            used_bytes, total_bytes = 0, DEFAULT_PACKAGE_SIZE
    else:
        pkg = instance_data.get("traffic_package") or {}
        used_bytes = int(pkg.get("used_bytes") or 0)
        total_bytes = int(pkg.get("total_bytes") or DEFAULT_PACKAGE_SIZE)
        used_gb = round(used_bytes / (1024 ** 3), 2)
        total_gb = round(total_bytes / (1024 ** 3), 2)
        pct = round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0.0

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
        "used_gb": used_gb,
        "total_gb": total_gb,
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
        "watermarks": {"warning": int(warning_pct), "tripped": int(tripped_pct)},
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


def stop_node_proxy(node, runner=subprocess.run):
    """停止远程或本地节点上的代理服务。"""
    if not repair:
        return None
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_win:
        cmd = 'taskkill /f /im sing-box.exe 2>nul & schtasks /end /tn sing-box 2>nul'
    else:
        cmd = 'systemctl stop sing-box'
    return repair.execute_remote(node, cmd, runner=runner, timeout=15)


def start_node_proxy(node, runner=subprocess.run):
    """启动远程或本地节点上的代理服务。"""
    if not repair:
        return None
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_win:
        cmd = 'schtasks /run /tn sing-box 2>nul'
    else:
        cmd = 'systemctl start sing-box'
    return repair.execute_remote(node, cmd, runner=runner, timeout=15)


def enforce_quota(nodes, usage_data, runner=subprocess.run, state_file=QUOTA_STATE_FILE):
    """真机断流与自愈恢复执行器：
    1. 遍历所有节点，检查对应 IP 是否触达 85% 熔断线；
    2. 若超标且当前仍在运行：执行远程停机，避免持续跑流量扣费；
    3. 若恢复且曾被熔断停机：重新拉起服务；
    4. 状态持久化至 state_file。
    """
    state = {}
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
    stopped_ips = set(state.get("stopped_ips") or [])

    actions = []
    # 建立 IP 到受控节点的映射
    for node in nodes or []:
        host = node.get("host")
        if not host or node.get("source") == "external":
            continue
        eval_res = evaluate_instance_quota(usage_data.get(host), tripped_pct=DEFAULT_TRIPPED_PCT)
        
        # 触发熔断断流
        if eval_res["is_tripped"] and host not in stopped_ips:
            stop_node_proxy(node, runner=runner)
            stopped_ips.add(host)
            msg = f"节点 [{node.get('name', host)}] 已消耗 {eval_res['percent']}% 超过熔断线 85%，已执行物理停机断流"
            if logger:
                logger.log("WARN", "QUOTA", msg)
            actions.append({"ip": host, "name": node.get("name"), "action": "stop", "percent": eval_res["percent"]})
        # 恢复放行
        elif not eval_res["is_tripped"] and host in stopped_ips:
            start_node_proxy(node, runner=runner)
            stopped_ips.discard(host)
            msg = f"节点 [{node.get('name', host)}] 流量用量已恢复正常 ({eval_res['percent']}%)，已重新拉起服务"
            if logger:
                logger.log("INFO", "QUOTA", msg)
            actions.append({"ip": host, "name": node.get("name"), "action": "start", "percent": eval_res["percent"]})

    # 持久化状态
    try:
        os.makedirs(os.path.dirname(os.path.abspath(state_file)), exist_ok=True)
        tmp = state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"stopped_ips": sorted(list(stopped_ips))}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, state_file)
    except Exception:
        pass

    return actions
