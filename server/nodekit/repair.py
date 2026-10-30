"""节点故障一键自愈与修复模块。

针对常见故障场景自动自愈：
1. 冲突进程排查与清理（如旧测试残留的 3x-ui / xray 强占端口）
2. 服务异常重启与开机自启恢复（Linux systemd / Windows TaskScheduler）
3. 配置语法完整性校验（/opt/sing-box/sing-box check）
4. 端到端真实代理出口验真（验证修复后是否真实通达外网）
"""
import base64
import os
import subprocess
import time
from . import verify as verify_mod

CTL_KEY = "/root/.ssh/node_ctl"
KNOWN_HOSTS = "/opt/sing-box/known_hosts"
BIN = "/opt/sing-box/sing-box"

# 常见需要清理的残留冲突进程签名
CONFLICT_PROCESSES_WIN = ["3x-ui.exe", "xray-windows-amd64.exe", "xray.exe"]
CONFLICT_PROCESSES_LINUX = ["3x-ui", "xray-linux", "xray"]


def build_repair_command_linux():
    """构造 Linux 机器上的清理与拉起指令。"""
    kill_cmd = "pkill -f " + " 2>/dev/null || true; pkill -f ".join(CONFLICT_PROCESSES_LINUX) + " 2>/dev/null || true"
    check_and_restart = (
        "if [ -f /opt/sing-box/sing-box ] && [ -f /opt/sing-box/config.json ]; then "
        "/opt/sing-box/sing-box check -c /opt/sing-box/config.json >/dev/null 2>&1 || exit 12; "
        "fi; "
        "systemctl daemon-reload 2>/dev/null || true; "
        "systemctl enable --now sing-box 2>/dev/null || sudo -n systemctl enable --now sing-box 2>/dev/null || true; "
        "systemctl restart sing-box 2>/dev/null || sudo -n systemctl restart sing-box; "
        "sleep 1; "
        "systemctl is-active sing-box 2>/dev/null || sudo -n systemctl is-active sing-box"
    )
    return "%s; %s" % (kill_cmd, check_and_restart)


def build_repair_command_windows():
    """构造 Windows 机器上的清理与任务计划拉起指令。"""
    kill_parts = ["taskkill /F /IM %s 2>nul" % p for p in CONFLICT_PROCESSES_WIN]
    sch_parts = [
        "schtasks /change /tn sing-box /enable 2>nul",
        "schtasks /run /tn sing-box 2>nul",
    ]
    return "cmd.exe /c \"" + " & ".join(kill_parts + sch_parts) + "\""


def execute_remote(node, cmd_str, runner=subprocess.run, timeout=30):
    """在目标机器上执行自愈命令，支持传入 mock runner 供离线单测。"""
    host = node.get("host", "")
    is_local = node.get("local") is True or host in ("127.0.0.1", "localhost", "198.51.100.12")
    if is_local:
        return runner(["bash", "-c", cmd_str], capture_output=True, text=True, timeout=timeout)

    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    user = node.get("ssh_user") or ("Administrator" if is_win else "root")
    base = verify_mod.ssh_cmd(user, host, timeout=timeout)
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
            "detail": "外部节点没有 SSH 控制权限，无法自愈修复",
            "steps": ["检查权限：外部节点无控制权限，跳过"],
        }

    # 2. 检查操作系统与执行清理/重启
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    steps.append("目标系统识别: %s" % ("Windows Server" if is_win else "Linux"))

    if is_win:
        cmd = build_repair_command_windows()
        steps.append("清理冲突进程 (3x-ui / xray) 并重启 sing-box 计划任务")
    else:
        cmd = build_repair_command_linux()
        steps.append("校验 sing-box 配置语法，重启 sing-box.service")

    try:
        r = execute_remote(node, cmd, runner=runner, timeout=35)
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if r.returncode == 12:
            return {
                "name": name,
                "before": before_health,
                "after": "config_error",
                "ok": False,
                "detail": "服务器配置语法错误，自愈停止，请检查 config.json",
                "steps": steps + ["配置校验失败 (sing-box check 报错)"],
            }
        steps.append("远程命令执行完成 (返回码 %d)" % r.returncode)
    except Exception as e:
        steps.append("远程执行失败: %s" % str(e)[:100])

    # 3. 稍候让服务监听就绪
    sleep_fn(1)

    # 4. 跑端到端验真
    steps.append("开始端到端真实代理出口验真")
    try:
        vr = verifier(node)
        new_health = vr.get("health", "unknown")
        detail = vr.get("detail", "")
        steps.append("验真结果: health=%s, detail=%s" % (new_health, detail))
    except Exception as e:
        new_health = "unknown"
        detail = "验真异常: " + str(e)[:80]
        steps.append(detail)

    # 5. 更新节点健康状态字段
    node["health"] = new_health
    if vr.get("exit_ip"):
        node["exit_ip"] = vr["exit_ip"]
        node["exit_country"] = vr.get("exit_country", "")
    if detail:
        node["health_detail"] = detail

    return {
        "name": name,
        "before": before_health,
        "after": new_health,
        "ok": (new_health == "ok"),
        "detail": detail,
        "steps": steps,
        "verify": vr,
    }
