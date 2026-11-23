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
    """在 Linux 目标机器上执行自愈命令，支持传入 mock runner 供离线单测。"""
    if prov_mod.is_windows(node):
        raise RuntimeError("Windows 受控分支已冻结，拒绝执行远程命令")
    host = node.get("host", "")
    is_local = node.get("local") is True or host in ("127.0.0.1", "localhost", "198.51.100.12")
    if is_local:
        return runner(["bash", "-c", cmd_str], capture_output=True, text=True, timeout=timeout)

    user = node.get("ssh_user") or "root"
    base = verify_mod.ssh_cmd(user, host, timeout=timeout, port=node.get("ssh_port") or 22)
    b64 = base64.b64encode(cmd_str.encode("utf-8")).decode("ascii")
    shell_exec = "bash" if user == "root" else "sudo -n bash"
    full_cmd = base + ["echo %s | base64 -d | %s" % (b64, shell_exec)]
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

    # 1. 外部节点 / 免密反向接入 / 冻结的 Windows 分支均无远程控制权，严禁触发远端命令
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

    if node.get("source") == "reverse_join":
        return {
            "name": name,
            "before": before_health,
            "after": before_health,
            "ok": False,
            "requires_manual": True,
            "detail": "免密反向接入节点未向主控授权 SSH 控制权，请在目标机人工检查，未执行停止或重启。",
            "steps": ["检查权限：免密反向接入节点仅支持观测与订阅，跳过远程自愈"],
        }

    if prov_mod.is_windows(node):
        return {
            "name": name,
            "before": before_health,
            "after": before_health,
            "ok": False,
            "requires_manual": True,
            "detail": "Windows 受控分支已冻结，请在服务器上人工检查，未执行停止或重启。",
            "steps": ["目标系统识别: Windows Server（受控分支已冻结，未执行远程命令）"],
        }

    exec_fn = execute_remote_fn or (lambda n, cmd, **kw: execute_remote(n, cmd, runner=runner, **kw))

    # 所有变更共享同一归属门禁，名称不参与身份匹配。
    provenance_verified, prov_reason, snapshot = prov_mod.verify_target(node, exec_fn, master_secret)

    steps.append("目标系统识别: Linux")

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

    # 4.2 语法完整性与配置健康检查
    cfg = prov_mod.config_path(node)
    syntax_cmd = f"""
if [ ! -x {shlex.quote(BIN)} ]; then echo NO_BIN;
elif [ ! -f {shlex.quote(cfg)} ]; then echo NO_CFG;
elif ! {shlex.quote(BIN)} check -c {shlex.quote(cfg)}; then echo SYNTAX_ERR;
else echo SYNTAX_OK; fi
"""
    try:
        chk_res = exec_fn(node, syntax_cmd, timeout=12)
        chk_out = (getattr(chk_res, "stdout", "") or "").strip()
        if getattr(chk_res, "returncode", -1) != 0 or "SYNTAX_OK" not in chk_out:
            if "SYNTAX_ERR" in chk_out:
                from . import remote_config
                restored = remote_config.rollback_config(node, master_secret=master_secret, execute_remote_fn=exec_fn)
                if restored:
                    provenance_verified, prov_reason, snapshot = prov_mod.verify_target(node, exec_fn, master_secret)
                    if not provenance_verified:
                        raise ValueError("restored ownership unavailable")
                    steps.append("已从签名验证通过的配置和存证备份成对恢复")
                else:
                    raise ValueError("no verified backup")
            else:
                raise ValueError("syntax inspection unavailable")
        else:
            steps.append("配置检查通过: sing-box 配置语法校验无误")
    except Exception:
        return {"name": name, "before": before_health, "after": before_health,
                "ok": False, "requires_manual": True,
                "detail": "无法确认配置及签名备份有效，未盲目执行重启", "steps": steps}

    # 4.3 安全重启目标服务
    restart_cmd = "systemctl daemon-reload && systemctl restart sing-box && systemctl is-active sing-box"

    steps.append("执行安全重启: 下发系统守护进程复活指令")
    try:
        rst_res = exec_fn(node, prov_mod.guarded_script(node, snapshot, restart_cmd), timeout=20)
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
        if health_status == "ok" or (
            isinstance(vr, dict) and vr.get("ok") is True and health_status in ("ok", "unknown", None, "")
        ):
            exit_ip = (vr.get("exit_ip") if isinstance(vr, dict) else None) or node.get("host")
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
            err_msg = (vr.get("detail") if isinstance(vr, dict) else "") or (vr.get("error") if isinstance(vr, dict) else "") or "健康状态未达标"
            steps.append(f"真实健康探测未达标: {err_msg}")
            after_health = health_status if health_status and health_status != "unknown" else before_health
            return {
                "name": name,
                "before": before_health,
                "after": after_health,
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
