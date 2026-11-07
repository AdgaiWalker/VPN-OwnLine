"""节点远程操作工具。尚不能验证服务独占时，修复请求仅提示人工检查。"""
import base64
import os
import subprocess
import time
from . import verify as verify_mod

CTL_KEY = "/root/.ssh/node_ctl"
KNOWN_HOSTS = "/opt/sing-box/known_hosts"
BIN = "/opt/sing-box/sing-box"

def execute_remote(node, cmd_str, runner=subprocess.run, timeout=30):
    """在目标机器上执行自愈命令，支持传入 mock runner 供离线单测。"""
    host = node.get("host", "")
    is_local = node.get("local") is True or host in ("127.0.0.1", "localhost", "198.51.100.12")
    if is_local:
        return runner(["bash", "-c", cmd_str], capture_output=True, text=True, timeout=timeout)

    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    user = node.get("ssh_user") or ("Administrator" if is_win else "root")
    base = verify_mod.ssh_cmd(user, host, timeout=timeout, port=node.get("ssh_port") or 22)
    if is_win:
        full_cmd = base + [cmd_str]
    else:
        b64 = base64.b64encode(cmd_str.encode("utf-8")).decode("ascii")
        full_cmd = base + ["echo %s | base64 -d | bash" % b64]
    return runner(full_cmd, capture_output=True, text=True, timeout=timeout)


def repair_node(node, runner=subprocess.run, verifier=verify_mod.run, sleep_fn=time.sleep):
    """自愈单个节点。
    
    返回 dict:
    {
        "name": str,
        "before": str (修复前 health),
        "after": str (修复后 health),
        "ok": bool (是否已完全恢复可用),
        "detail": str,
        "steps": list[str]
    }
    """
    name = node.get("name", "unknown")
    before_health = node.get("health", "unknown")
    steps = []

    # 1. 外部节点无法 SSH 修复
    if node.get("source") == "external":
        return {
            "name": name,
            "before": before_health,
            "after": before_health,
            "ok": False,
            "requires_manual": True,
            "detail": "外部节点没有 SSH 控制权限，无法自愈修复",
            "steps": ["检查权限：外部节点无控制权限，跳过"],
        }

    # 现有节点字段不能证明 sing-box 服务或 Windows 计划任务独占；
    # 不因节点来源、用户身份或布尔标记推断可以停止或重启服务。
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    steps.append("目标系统识别: %s" % ("Windows Server" if is_win else "Linux"))
    return {
        "name": name,
        "before": before_health,
        "after": before_health,
        "ok": False,
        "requires_manual": True,
        "detail": "无法确认服务由本项目独占；请在服务器上人工检查，未执行停止或重启。",
        "steps": steps,
    }
