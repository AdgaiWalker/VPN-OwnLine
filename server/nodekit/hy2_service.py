"""Hysteria2 (HY2) 极速通道服务。

深度封装 HY2 节点启用/停用、端口协调、防火墙放行及远端配置同步。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


class Hy2Service:
    @staticmethod
    def toggle(
        nodes: List[Dict[str, Any]],
        host: str,
        name: str,
        enabled: bool,
        remote_cfg_mod: Any,
        open_firewall_fn: Any,
        logger: Any,
    ) -> Tuple[int, Dict[str, Any], Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]]]:
        """切换 HY2 状态。"""
        if not host and not name:
            return 400, {"ok": False, "error": "缺少 host 或 name"}, None

        base_name = name[:-4] if name.endswith("-HY2") else name
        vless_node = next(
            (
                n
                for n in nodes
                if n.get("type") != "hysteria2"
                and (
                    (host and (n.get("host") == host or n.get("ip") == host))
                    or (base_name and n.get("name") == base_name)
                )
            ),
            None,
        )
        if not vless_node:
            return 404, {"ok": False, "error": "未找到对应的海外出口主节点"}, None

        target_host = vless_node.get("host")
        existing_hy2 = next(
            (
                n
                for n in nodes
                if n.get("type") == "hysteria2"
                and (n.get("host") == target_host or n.get("name") == vless_node.get("name", "") + "-HY2")
            ),
            None,
        )

        sync_res = remote_cfg_mod.toggle_hy2(
            vless_node,
            existing_hy2_node=existing_hy2,
            enabled=enabled,
            open_firewall_fn=open_firewall_fn,
        )
        if not sync_res.get("ok"):
            logger.log(
                "WARN",
                "NODE",
                "切换 HY2 失败 [%s -> %s]: %s"
                % (vless_node.get("name"), "开启" if enabled else "关闭", sync_res.get("error")),
            )
            return (
                502,
                {
                    "ok": False,
                    "error": sync_res.get("error") or "远端切换 HY2 失败",
                    "rolled_back": sync_res.get("rolled_back", False),
                    "verify": sync_res.get("verify"),
                },
                None,
            )

        hy2_record = sync_res.get("hy2_node")

        def _apply_hy2(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            out_list = []
            placed_hy2 = False
            for n in ns:
                is_same_host = n.get("host") == target_host
                is_hy2_item = n.get("type") == "hysteria2" and (
                    is_same_host or n.get("name") == vless_node.get("name", "") + "-HY2"
                )
                if is_hy2_item:
                    if enabled and hy2_record:
                        out_list.append(hy2_record)
                        placed_hy2 = True
                    else:
                        updated_hy2 = dict(n)
                        updated_hy2["enabled"] = False
                        out_list.append(updated_hy2)
                        placed_hy2 = True
                elif n.get("name") == vless_node.get("name"):
                    updated_vless = dict(n)
                    updated_vless["hy2_enabled"] = enabled
                    out_list.append(updated_vless)
                else:
                    out_list.append(n)
            if enabled and hy2_record and not placed_hy2:
                out_list.append(hy2_record)
            return out_list

        state_str = "开启" if enabled else "关闭"
        logger.log(
            "INFO",
            "NODE",
            "切换 HY2 极速通道并完成远端同步: %s ➔ %s"
            % (vless_node.get("name") or target_host, state_str),
        )
        return (
            200,
            {
                "ok": True,
                "enabled": enabled,
                "message": f"HY2 极速通道已{state_str}并通过远端校验",
                "verify": sync_res.get("verify"),
            },
            _apply_hy2,
        )
