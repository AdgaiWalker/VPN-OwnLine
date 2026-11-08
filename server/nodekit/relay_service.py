"""中转节点业务编排服务。

深度封装中转切流 (switch)、手动绑定 (bind) 与解绑 (unbind) 的领域逻辑与状态流转。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


class RelayService:
    @staticmethod
    def switch(
        nodes: List[Dict[str, Any]],
        name: str,
        target_host: str,
        remote_cfg_mod: Any,
        logger: Any,
    ) -> Tuple[int, Dict[str, Any], Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]]]:
        """中转节点实时切流。"""
        if not target_host:
            return 400, {"ok": False, "error": "缺少 target 目标主机地址"}, None

        relay_node = (
            next((n for n in nodes if n.get("name") == name and n.get("type") != "hysteria2"), None)
            if name
            else next((n for n in nodes if n.get("role") == "relay" and n.get("type") != "hysteria2"), None)
        )
        if not relay_node:
            return 404, {"ok": False, "error": "未找到可切换的中转入口节点"}, None

        target_exit = next(
            (
                n
                for n in nodes
                if (n.get("host") == target_host or n.get("ip") == target_host)
                and n.get("type") != "hysteria2"
            ),
            None,
        )
        if not target_exit:
            return 404, {"ok": False, "error": "未找到匹配的目标海外出口服务器"}, None

        fallback_exit = next(
            (
                n
                for n in nodes
                if n.get("type") != "hysteria2"
                and n.get("role") not in ("relay", "standalone")
                and (n.get("exit_country") or "").upper() != "CN"
                and n.get("host") not in (target_exit.get("host"), relay_node.get("host"))
            ),
            None,
        )

        sync_res = remote_cfg_mod.switch_relay(relay_node, target_exit, fallback_exit_node=fallback_exit)
        if not sync_res.get("ok"):
            logger.log(
                "WARN",
                "RELAY",
                "中转切流失败 [%s ➔ %s]: %s"
                % (relay_node.get("name"), target_host, sync_res.get("error")),
            )
            return (
                502,
                {
                    "ok": False,
                    "error": sync_res.get("error") or "远端中转切换失败",
                    "rolled_back": sync_res.get("rolled_back", False),
                    "verify": sync_res.get("verify"),
                },
                None,
            )

        def _apply_switch(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            for n in ns:
                if n.get("name") == relay_node.get("name"):
                    n["role"] = "relay"
                    n["landing"] = sync_res["landing"]
                    n["landing_policy"] = sync_res["landing_policy"]
                    n["health"] = "ok"
                    n["exit_ip"] = sync_res["exit_ip"]
                    n["exit_country"] = sync_res["exit_country"]
                    n["health_detail"] = sync_res["health_detail"]
            return ns

        logger.log(
            "INFO",
            "RELAY",
            "管理员完成真实中转切流: 节点 [%s] ➔ 目标 [%s]"
            % (relay_node.get("name"), target_exit.get("name") or target_host),
        )
        return (
            200,
            {
                "ok": True,
                "node": relay_node.get("name"),
                "active_target": sync_res["landing"]["host"],
                "verify": sync_res.get("verify"),
            },
            _apply_switch,
        )

    @staticmethod
    def bind(
        nodes: List[Dict[str, Any]],
        name: str,
        target_host: str,
        remote_cfg_mod: Any,
        logger: Any,
    ) -> Tuple[int, Dict[str, Any], Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]]]:
        """中转节点手动绑定落地节点。"""
        if not name or not target_host:
            return 400, {"ok": False, "error": "缺少节点名称 (name) 或落地目标 (target)"}, None

        relay_node = next((n for n in nodes if n.get("name") == name and n.get("type") != "hysteria2"), None)
        if not relay_node:
            return 404, {"ok": False, "error": "未找到指定的中转入口服务器"}, None

        target_exit = next(
            (
                n
                for n in nodes
                if (n.get("host") == target_host or n.get("ip") == target_host)
                and n.get("type") != "hysteria2"
            ),
            None,
        )
        if not target_exit:
            return 404, {"ok": False, "error": "未找到匹配的目标海外出口服务器"}, None

        fallback_exit = next(
            (
                n
                for n in nodes
                if n.get("type") != "hysteria2"
                and n.get("role") not in ("relay", "standalone")
                and (n.get("exit_country") or "").upper() != "CN"
                and n.get("host") not in (target_exit.get("host"), relay_node.get("host"))
            ),
            None,
        )

        sync_res = remote_cfg_mod.bind_relay(relay_node, target_exit, fallback_exit_node=fallback_exit)
        if not sync_res.get("ok"):
            logger.log(
                "WARN",
                "RELAY",
                "中转手动绑定失败 [%s ➔ %s]: %s"
                % (name, target_host, sync_res.get("error")),
            )
            return (
                502,
                {
                    "ok": False,
                    "error": sync_res.get("error") or "远端中转手动绑定失败",
                    "rolled_back": sync_res.get("rolled_back", False),
                    "verify": sync_res.get("verify"),
                },
                None,
            )

        def _apply_bind(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            for n in ns:
                if n.get("name") == name:
                    n["role"] = "relay"
                    n["landing"] = sync_res["landing"]
                    n["landing_policy"] = sync_res["landing_policy"]
                    n["health"] = "ok"
                    n["exit_ip"] = sync_res["exit_ip"]
                    n["exit_country"] = sync_res["exit_country"]
                    n["health_detail"] = sync_res["health_detail"]
            return ns

        logger.log(
            "INFO",
            "RELAY",
            "建立中转加速专线并完成真实出网验真: 节点 [%s] ➔ 落地 [%s]"
            % (name, target_exit["name"]),
        )
        return (
            200,
            {
                "ok": True,
                "message": "已成功建立中转加速专线并通过真实出网验证",
                "verify": sync_res.get("verify"),
            },
            _apply_bind,
        )

    @staticmethod
    def unbind(
        nodes: List[Dict[str, Any]],
        name: str,
        remote_cfg_mod: Any,
        logger: Any,
    ) -> Tuple[int, Dict[str, Any], Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]]]:
        """中转节点解除落地绑定。"""
        if not name:
            return 400, {"ok": False, "error": "缺少节点名称 (name)"}, None

        relay_node = next((n for n in nodes if n.get("name") == name and n.get("type") != "hysteria2"), None)
        if not relay_node:
            return 404, {"ok": False, "error": "未找到指定的中转入口服务器"}, None

        sync_res = remote_cfg_mod.unbind_relay(relay_node)
        if not sync_res.get("ok"):
            logger.log(
                "WARN",
                "RELAY",
                "中转解除绑定失败 [%s]: %s" % (name, sync_res.get("error")),
            )
            return (
                502,
                {
                    "ok": False,
                    "error": sync_res.get("error") or "远端中转解绑失败",
                    "rolled_back": sync_res.get("rolled_back", False),
                    "verify": sync_res.get("verify"),
                },
                None,
            )

        def _apply_unbind(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            for n in ns:
                if n.get("name") == name:
                    n["role"] = "standalone"
                    n.pop("landing", None)
                    n.pop("landing_policy", None)
                    n.pop("exit_ip", None)
                    n.pop("exit_country", None)
                    n["health"] = sync_res.get("health", "unknown")
                    n["health_detail"] = sync_res.get("health_detail", "国内独立服务器（未绑定中转，不进订阅）")
            return ns

        logger.log("INFO", "RELAY", "解除中转加速并已同步远端配置: 节点 [%s] 恢复为独立服务器" % name)
        return (
            200,
            {
                "ok": True,
                "message": "已解除中转关系，远端配置已还原为独立服务器",
            },
            _apply_unbind,
        )
