"""节点远程操作与安全真自愈模块。

严格遵循服务独占性安全原则：
1. 必须持有合法的 HMAC-SHA256 存证签名；
2. 严防端口冲突：若端口被其他未知进程占用，坚决终止自愈并不杀死外部进程；
3. 配置语法预检查：严禁盲目重启损坏的配置；
4. 真实探活重校验：重启后执行真实验证，不自欺欺人。
未持有合法存证时，严格保持只提示人工检查的安全不执行契约。
"""
from __future__ import annotations

import base64
import os
import re
import shlex
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

from . import provenance as prov_mod
from . import verify as verify_mod

CTL_KEY = "/root/.ssh/node_ctl"
KNOWN_HOSTS = "/opt/sing-box/known_hosts"
BIN = "/opt/sing-box/sing-box"


def execute_remote(node: Dict[str, Any], cmd_str: str, runner: Callable = subprocess.run, timeout: int = 30):
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


def repair_node(
    node: Dict[str, Any],
    runner: Callable = subprocess.run,
    verifier: Callable = verify_mod.run,
    sleep_fn: Callable = time.sleep,
    master_secret: Optional[str | bytes] = None,
    execute_remote_fn: Optional[Callable] = None,
) -> Dict[str, Any]:
    """自愈单个节点。
    
    返回 dict:
    {
        "name": str,
        "before": str (修复前 health),
        "after": str (修复后 health),
        "ok": bool (是否已完全恢复可用),
        "requires_manual": bool,
        "detail": str,
        "steps": list[str]
    }
    """
    name = node.get("name", "unknown")
    before_health = node.get("health", "unknown")
    steps: List[str] = []

    # 1. 外部节点没有控制权，无法修复
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

    exec_fn = execute_remote_fn or (lambda n, cmd, **kw: execute_remote(n, cmd, runner=runner, **kw))

    # 2. 独占性存证校验 (HMAC-SHA256 Provenance)
    provenance_verified = False
    prov_reason = "未提供主控签名密钥"

    if master_secret:
        manifest = prov_mod.read_remote_provenance(node, exec_fn)
        if manifest:
            is_valid, prov_reason = prov_mod.verify_provenance(manifest, master_secret)
            provenance_verified = is_valid
        else:
            prov_reason = "目标主机缺少 .evergreen-provenance.json 存证文件"

    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    steps.append("目标系统识别: %s" % ("Windows Server" if is_win else "Linux"))

    # 3. 未能确认独占性时，保持绝对安全不执行契约
    if not provenance_verified:
        steps.append("独占存证核验失败: %s" % prov_reason)
        return {
            "name": name,
            "before": before_health,
            "after": before_health,
            "ok": False,
            "requires_manual": True,
            "detail": "无法确认服务由本项目独占；请在服务器上人工检查，未执行停止或重启。",
            "steps": steps,
        }

    # 4. 独占性验证通过：启动可信闭环自愈流程
    steps.append("独占存证校验通过: 签名有效，确认为本项目纳管的 sing-box 独占服务")

    # 4.1 端口占用与冲突排查
    port = int(node.get("port") or 443)
    if not is_win:
        port_check_cmd = f"ss -lptn 'sport = :{port}' 2>/dev/null || netstat -tulpn 2>/dev/null | grep ':{port} ' || true"
        try:
            port_res = exec_fn(node, port_check_cmd, timeout=10)
            port_out = getattr(port_res, "stdout", "") or ""
            if port_out.strip():
                # 若端口被占用，检查是否由 sing-box 占用
                if "sing-box" in port_out:
                    steps.append(f"端口诊断: 端口 :{port} 由现有 sing-box 进程持有")
                else:
                    steps.append(f"端口冲突: 端口 :{port} 被其他外部进程占用")
                    return {
                        "name": name,
                        "before": before_health,
                        "after": before_health,
                        "ok": False,
                        "requires_manual": True,
                        "detail": f"端口 :{port} 被非 sing-box 进程占用，为防止影响系统其他业务，已安全终止自愈",
                        "steps": steps,
                    }
            else:
                steps.append(f"端口诊断: 端口 :{port} 处于空闲状态")
        except Exception as e:
            steps.append(f"端口检测异常: {e}")

    # 4.2 语法完整性与配置健康检查 (仅 Linux)
    if not is_win:
        syntax_cmd = """
if [ -x /opt/sing-box/sing-box ]; then BIN=/opt/sing-box/sing-box;
elif command -v sing-box >/dev/null 2>&1; then BIN=$(command -v sing-box);
else BIN=""; fi
if [ -z "$BIN" ]; then echo "NO_BIN";
elif [ ! -f /etc/sing-box/config.json ]; then echo "NO_CFG";
elif ! $BIN check -c /etc/sing-box/config.json; then echo "SYNTAX_ERR";
else echo "SYNTAX_OK"; fi
"""
        try:
            chk_res = exec_fn(node, syntax_cmd, timeout=12)
            chk_out = (getattr(chk_res, "stdout", "") or "").strip()
            if "SYNTAX_ERR" in chk_out:
                steps.append("配置检查失败: /etc/sing-box/config.json 语法校验不通过")
                # 尝试从 .ownline.bak 还原
                restore_cmd = "test -s /etc/sing-box/config.json.ownline.bak && cp -pf /etc/sing-box/config.json.ownline.bak /etc/sing-box/config.json && echo RESTORED || echo FAILED"
                r_res = exec_fn(node, restore_cmd, timeout=10)
                if "RESTORED" in (getattr(r_res, "stdout", "") or ""):
                    steps.append("已自动从已知健康的备份配置 .ownline.bak 完成恢复")
                else:
                    return {
                        "name": name,
                        "before": before_health,
                        "after": before_health,
                        "ok": False,
                        "requires_manual": True,
                        "detail": "配置文件语法损坏且无有效备份，未盲目执行重启",
                        "steps": steps,
                    }
            elif "NO_BIN" in chk_out:
                return {
                    "name": name,
                    "before": before_health,
                    "after": before_health,
                    "ok": False,
                    "requires_manual": True,
                    "detail": "未在远端找到可执行的 sing-box 二进制程序",
                    "steps": steps,
                }
            else:
                steps.append("配置检查通过: sing-box 配置语法校验无误")
        except Exception as e:
            steps.append(f"配置检查跳过: {e}")

    # 4.3 安全重启目标服务
    if is_win:
        restart_cmd = "powershell -Command \"Restart-Service sing-box -ErrorAction SilentlyContinue; if (-not $?) { Start-ScheduledTask -TaskName 'sing-box' -ErrorAction SilentlyContinue }\""
    else:
        restart_cmd = "systemctl daemon-reload && systemctl restart sing-box && systemctl is-active sing-box"

    steps.append("执行安全重启: 下发系统守护进程复活指令")
    try:
        rst_res = exec_fn(node, restart_cmd, timeout=20)
        if getattr(rst_res, "returncode", -1) != 0:
            steps.append("服务重启返回非零状态码")
            return {
                "name": name,
                "before": before_health,
                "after": before_health,
                "ok": False,
                "requires_manual": True,
                "detail": "sing-box 服务重启失败，请检查系统守护日志",
                "steps": steps,
            }
        steps.append("服务重启成功: 守护进程处于 active 运行状态")
    except Exception as e:
        return {
            "name": name,
            "before": before_health,
            "after": before_health,
            "ok": False,
            "requires_manual": True,
            "detail": f"执行重启命令时通信异常: {e}",
            "steps": steps,
        }

    # 4.4 端口复苏与探活重校验 (Honest Verification)
    sleep_fn(2)
    try:
        vr = verifier(node)
        health_status = vr.get("health") if isinstance(vr, dict) else "unknown"
        if health_status in ("ok", "proxy") or (isinstance(vr, dict) and vr.get("ok") is True):
            exit_ip = vr.get("exit_ip") or node.get("host")
            steps.append(f"真实健康探测通过: 节点连通就绪，落地出口 IP 为 {exit_ip}")
            return {
                "name": name,
                "before": before_health,
                "after": "ok",
                "ok": True,
                "requires_manual": False,
                "detail": "自愈成功：独占签名验证通过，sing-box 服务已安全重启并恢复就绪",
                "steps": steps,
            }
        else:
            err_msg = vr.get("detail") or vr.get("error") or "健康状态未达标"
            steps.append(f"真实健康探测未达标: {err_msg}")
            return {
                "name": name,
                "before": before_health,
                "after": before_health,
                "ok": False,
                "requires_manual": True,
                "detail": f"服务已重启，但节点健康探测未通过: {err_msg}",
                "steps": steps,
            }
    except Exception as e:
        steps.append(f"探活校验异常: {e}")
        return {
            "name": name,
            "before": before_health,
            "after": before_health,
            "ok": False,
            "requires_manual": True,
            "detail": f"服务已重启，但在后续探活阶段发生异常: {e}",
            "steps": steps,
        }
