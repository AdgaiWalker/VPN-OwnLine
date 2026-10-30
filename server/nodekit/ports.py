#!/usr/bin/env python3
"""端口动态决策与智能避让模块（活的端口函数，拒绝写死代码）。

职责：
1. 不写死 443 或 8443，根据操作系统类型（Linux/Windows）、业务共存状态（宝塔/Nginx/IIS）动态决策；
2. 支持显式指定端口、智能推荐空闲端口与避让冲突端口；
3. 将 TCP (Reality) 与 UDP (Hysteria2) 端口解耦，避免同一端口不同协议的策略冲突。
"""
import socket
import typing

DEFAULT_TCP_PREFERRED = 443
DEFAULT_TCP_FALLBACKS = (8443, 20443, 4433, 2083, 2087)
DEFAULT_UDP_PREFERRED = 443
DEFAULT_UDP_FALLBACKS = (8443, 20443, 4433, 2083, 53)


def is_port_free_local(port: int, proto: str = "tcp") -> bool:
    """本地探测端口是否处于空闲未占用状态。"""
    sock_type = socket.SOCK_STREAM if proto.lower() == "tcp" else socket.SOCK_DGRAM
    try:
        with socket.socket(socket.AF_INET, sock_type) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", int(port)))
            return True
    except (OSError, socket.error):
        return False


def resolve_node_ports(
    node: dict,
    os_type: str = "linux",
    has_web_server: bool = False,
    occupied_ports: typing.Optional[typing.Set[int]] = None,
) -> dict:
    """动态决定服务器开启哪些端口的“活的函数”。

    输入：
    - node: 节点现有元数据（可能包含自定义 port, hy2_port 等）
    - os_type: 操作系统类型 ('linux', 'windows', 'darwin')
    - has_web_server: 是否已有宝塔、Nginx、IIS 或 Caddy 占用 80/443
    - occupied_ports: 已知被占用的端口集合

    返回：
    {
        "tcp_port": int,      # Reality 入站监听端口
        "hy2_port": int,      # Hysteria2 入站监听端口
        "reason": str,        # 决策原因与依据
        "is_custom": bool,    # 是否由用户显式指定
        "is_fallback": bool,  # 是否触发了冲突避让
    }
    """
    occupied = set(occupied_ports or [])
    user_port = node.get("port")
    user_hy2_port = node.get("hy2_port")

    # 1. 如果用户显式指定了有效端口，尊重用户配置
    if user_port and str(user_port).isdigit() and int(user_port) > 0:
        p = int(user_port)
        hy2_p = int(user_hy2_port) if (user_hy2_port and str(user_hy2_port).isdigit()) else p
        return {
            "tcp_port": p,
            "hy2_port": hy2_p,
            "reason": f"用户显式指定端口 ({p})",
            "is_custom": True,
            "is_fallback": False,
        }

    # 2. 如果是 Windows 机器，或者明确已知有 Web 业务 (宝塔/Nginx/IIS 占用 443)
    is_windows = (os_type.lower() == "windows" or "windows" in node.get("name", "").lower())
    if is_windows or has_web_server or (443 in occupied):
        # 寻找首个未被占用的备选端口
        target_port = 8443
        for cand in DEFAULT_TCP_FALLBACKS:
            if cand not in occupied:
                target_port = cand
                break

        return {
            "tcp_port": target_port,
            "hy2_port": target_port,
            "reason": f"{'Windows 系统' if is_windows else '已有 Web 业务占用 443'}，动态避让至非标空闲端口 {target_port}",
            "is_custom": False,
            "is_fallback": True,
        }

    # 3. 干净的标准 Linux 环境：优先使用标准 443 伪装端口
    return {
        "tcp_port": DEFAULT_TCP_PREFERRED,
        "hy2_port": DEFAULT_UDP_PREFERRED,
        "reason": "干净 Linux 环境，优先启用标准 443 (Reality) 与 443/UDP (Hysteria2) 完美伪装",
        "is_custom": False,
        "is_fallback": False,
    }


def suggest_safe_ports(node_list: typing.List[dict]) -> typing.List[int]:
    """为新机器推荐不会与现有集群节点或默认业务冲突的安全端口列表。"""
    used_ports = {int(n.get("port")) for n in node_list if n.get("port") and str(n.get("port")).isdigit()}
    candidates = [443, 8443, 20443, 4433, 2083, 2087, 8888]
    return [p for p in candidates if p not in used_ports]
