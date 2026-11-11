#!/usr/bin/env python3
"""腾讯云流量包防爆熔断器（纯标准库，零外部依赖）。

识别真实、近期用量；共享阈值默认 85%，警戒线低于阈值 10 个百分点。
只有已确认独占且可安全控制的服务会执行自动停启；其余显示未覆盖。
超出阈值仅表示需要处理，不代表停机已成功，也不保证避免账单费用。
"""
import json
import math
import os
import subprocess
import tempfile
from datetime import datetime, timezone

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
QUOTA_SETTINGS_FILE = os.path.join(os.environ.get("LADDER_DATA", "/opt/web-data"), "quota_settings.json")
MAX_USAGE_AGE_SECONDS = 30 * 60


def quota_threshold(path=None):
    """共享阈值；配置缺失或损坏时使用默认值。"""
    try:
        with open(path or QUOTA_SETTINGS_FILE, encoding="utf-8") as f:
            value = json.load(f)["threshold"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
            raise ValueError("invalid threshold")
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return int(DEFAULT_TRIPPED_PCT)


def save_quota_threshold(value, path=None):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise ValueError("保护阈值必须是 1 到 100 的整数")
    path = path or QUOTA_SETTINGS_FILE
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".quota-settings-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"threshold": value}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def usage_is_fresh(usage, now=None):
    """仅将近期有效采集视作保护决策依据。"""
    try:
        stamp = datetime.fromisoformat(str(usage["_ts"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return False
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        return -300 <= age <= MAX_USAGE_AGE_SECONDS
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def stopped_hosts(state_file=None):
    try:
        with open(state_file or QUOTA_STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("stopped_ips") or [])
    except (OSError, ValueError, TypeError):
        return set()


def parse_reset_day(val):
    """安全解析每月流量包重置日 (1~31)。支持 YYYY-MM-DD、ISO 时间戳或纯数字/整型。"""
    if val is None or val == "":
        return None
    if isinstance(val, int):
        return val if 1 <= val <= 31 else None
    if isinstance(val, float):
        ival = int(val)
        return ival if 1 <= ival <= 31 and ival == val else None
    if isinstance(val, str):
        val = val.strip()
        parts = val.split("T")[0].split(" ")[0].split("-")
        if len(parts) >= 3 and parts[2].isdigit():
            try:
                day = int(parts[2])
                if 1 <= day <= 31:
                    return day
            except ValueError:
                pass
        if val.isdigit():
            try:
                day = int(val)
                if 1 <= day <= 31:
                    return day
            except ValueError:
                pass
    return None


def supports_quota_control(node):
    # Windows 当前使用按进程名停止，可能影响其他软件，不能视为可安全控制。
    return (node.get("quota_control_managed") is True and node.get("source") != "external"
            and node.get("os") != "windows" and node.get("ssh_user") != "Administrator")


def controllable_hosts(nodes):
    """同一主机所有记录均确认可控，才能安全以主机为单位控制服务。"""
    grouped = {}
    for node in nodes or []:
        if node.get("host"):
            grouped.setdefault(node["host"], []).append(node)
    return {host for host, items in grouped.items() if all(supports_quota_control(n) for n in items)}


def evaluate_instance_quota(instance_data, warning_pct=DEFAULT_WARNING_PCT,
                            tripped_pct=DEFAULT_TRIPPED_PCT):
    """评估单台实例的流量包使用状态。
    支持生产环境真实格式 (used/total in GB) 及备用格式 (traffic_package in bytes)。
    """
    if not isinstance(instance_data, dict):
        return {
            "status": "unknown",
            "percent": None,
            "used_gb": None,
            "total_gb": None,
            "used_bytes": None,
            "total_bytes": None,
            "is_tripped": False,
            "is_warning": False,
            "reason": "无用量数据",
            "reset_day": None,
        }

    # 缺失、错误或非有限数值均为未知；不能据此解除已有熔断。
    try:
        if "used" in instance_data or "total" in instance_data:
            used_gb = float(instance_data["used"])
            total_gb = float(instance_data["total"])
            used_bytes = int(used_gb * (1024 ** 3))
            total_bytes = int(total_gb * (1024 ** 3))
        else:
            pkg = instance_data["traffic_package"]
            used_bytes = int(pkg["used_bytes"])
            total_bytes = int(pkg["total_bytes"])
            used_gb = used_bytes / (1024 ** 3)
            total_gb = total_bytes / (1024 ** 3)
        if not (math.isfinite(used_gb) and math.isfinite(total_gb)
                and used_gb >= 0 and total_gb > 0):
            raise ValueError("无效用量")
        pct = round((used_gb / total_gb) * 100, 1)
    except (KeyError, TypeError, ValueError, OverflowError):
        return evaluate_instance_quota(None, warning_pct, tripped_pct)

    if pct >= tripped_pct:
        status = "tripped"
        is_tripped = True
        is_warning = True
        reason = f"已消耗 {pct:.1f}%，达到保护阈值 {tripped_pct:.0f}%"
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
        "reset_day": parse_reset_day(instance_data.get("reset_day") or instance_data.get("end")),
    }


def evaluate_all(usage_json_data, warning_pct=None, tripped_pct=None):
    """批量评估集群所有机器的配额安全水位。
    返回 {ip: evaluation_dict, "_summary": ...}
    """
    tripped_pct = quota_threshold() if tripped_pct is None else tripped_pct
    warning_pct = max(0, tripped_pct - 10) if warning_pct is None else warning_pct
    results = {}
    any_tripped = False
    any_warning = False

    for ip, data in (usage_json_data or {}).items():
        if ip.startswith("_") or not isinstance(data, dict):
            continue
        eval_res = evaluate_instance_quota(data if usage_is_fresh(usage_json_data) else None, warning_pct=warning_pct, tripped_pct=tripped_pct)
        if eval_res.get("reset_day") is None and isinstance(data, dict):
            eval_res["reset_day"] = parse_reset_day(data.get("reset_day") or data.get("end"))
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


def is_node_circuit_broken(node_host, usage_json_data, tripped_pct=None):
    """判断指定节点的 IP 是否已触发熔断。"""
    if not node_host:
        return False
    if node_host in stopped_hosts():
        return True
    if not usage_is_fresh(usage_json_data):
        return False
    data = usage_json_data.get(node_host)
    if not data:
        return False
    eval_res = evaluate_instance_quota(data, tripped_pct=quota_threshold() if tripped_pct is None else tripped_pct)
    return eval_res["is_tripped"]


def stop_node_proxy(node, runner=subprocess.run):
    """停止远程或本地节点上的代理服务。"""
    if not repair:
        return None
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_win:
        cmd = 'taskkill /f /im sing-box.exe 2>nul & schtasks /end /tn sing-box 2>nul'
    else:
        cmd = ("flock -x -w 5 /run/ownline-service.lock sh -c "
               "'install -d -m 700 /var/lib/ownline && touch /var/lib/ownline/quota-paused && "
               "systemctl stop sing-box && state=$(systemctl show sing-box -p ActiveState --value) && "
               "case \"$state\" in inactive|failed) exit 0 ;; *) exit 1 ;; esac'")
    return repair.execute_remote(node, cmd, runner=runner, timeout=15)


def start_node_proxy(node, runner=subprocess.run):
    """启动远程或本地节点上的代理服务。"""
    if not repair:
        return None
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_win:
        cmd = 'schtasks /run /tn sing-box 2>nul'
    else:
        cmd = ("flock -x -w 5 /run/ownline-service.lock sh -c "
               "'rm -f /var/lib/ownline/quota-paused && "
               "if systemctl start sing-box && systemctl is-active --quiet sing-box; then exit 0; "
               "else touch /var/lib/ownline/quota-paused; systemctl stop sing-box >/dev/null 2>&1 || true; exit 1; fi'")
    return repair.execute_remote(node, cmd, runner=runner, timeout=15)


def enforce_quota(nodes, usage_data, runner=subprocess.run, state_file=QUOTA_STATE_FILE):
    """真机断流与自愈恢复执行器：
    1. 遍历归属已确认的节点，检查对应 IP 是否达到用户设置的阈值；
    2. 若超标且当前仍在运行：执行远程停机，避免持续跑流量扣费；
    3. 若恢复且曾被熔断停机：重新拉起服务；
    4. 状态持久化至 state_file。
    """
    stopped_ips = stopped_hosts(state_file)
    if not usage_is_fresh(usage_data):
        return []
    threshold = quota_threshold()

    actions = []
    # 同一主机的所有记录必须确认可控，避免共享服务被其中一条记录误停。
    by_host = {}
    for node in nodes or []:
        if node.get("host"):
            by_host.setdefault(node["host"], []).append(node)
    eligible_hosts = controllable_hosts(nodes)
    for host, host_nodes in by_host.items():
        node = host_nodes[0]
        # 不能根据节点来源推断 sing-box 为本产品独占，旧记录需重新确认归属。
        if host not in eligible_hosts:
            continue
        eval_res = evaluate_instance_quota((usage_data or {}).get(host), tripped_pct=threshold)
        if eval_res["status"] == "unknown":
            continue

        if eval_res["is_tripped"] and host not in stopped_ips:
            action, execute = "stop", stop_node_proxy
        elif not eval_res["is_tripped"] and host in stopped_ips:
            action, execute = "start", start_node_proxy
        else:
            continue

        # subprocess 默认不因非零返回码抛异常，必须先确认结果再变更状态。
        error = None
        try:
            result = execute(node, runner=runner)
            if result is None or result.returncode != 0:
                error = "远程命令未成功" if result is None else f"远程命令返回码 {result.returncode}"
        except Exception as exc:
            error = f"远程命令异常 ({type(exc).__name__})"
        if error:
            if logger:
                logger.log("ERROR", "QUOTA", f"节点 [{node.get('name', host)}] {action} 失败：{error}，保留原状态，下次重试")
            actions.append({"ip": host, "name": node.get("name"), "action": action,
                            "percent": eval_res["percent"], "ok": False, "error": error})
            continue

        if action == "stop":
            stopped_ips.add(host)
            msg = f"节点 [{node.get('name', host)}] 已消耗 {eval_res['percent']}% 达到保护线 {threshold}%，已暂停代理"
        else:
            stopped_ips.discard(host)
            msg = f"节点 [{node.get('name', host)}] 流量用量已恢复正常 ({eval_res['percent']}%)，已重新拉起服务"
        if logger:
            logger.log("WARN" if action == "stop" else "INFO", "QUOTA", msg)
        actions.append({"ip": host, "name": node.get("name"), "action": action, "percent": eval_res["percent"]})

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
