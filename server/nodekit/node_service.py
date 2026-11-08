"""节点管理业务服务。

提供节点移除 (removenode) 与编辑 (editnode) 的深度领域逻辑，包含 ISP 代理同步与生命周期校验。
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple


class NodeService:
    @staticmethod
    def remove_node(
        nodes: List[Dict[str, Any]],
        name: str,
        cleanup_confirmed: bool,
        logger: Any,
    ) -> Tuple[int, Dict[str, Any], Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]]]:
        """移除或标记待清理节点。"""
        target = next((n for n in nodes if n.get("name") == name), None)
        if not target:
            return 404, {"ok": False, "error": "没找到这个节点"}, None

        to_remove = {name}
        if name.endswith("-HY2"):
            base_name = name[:-4]
            if any(n.get("name") == base_name for n in nodes):
                to_remove.add(base_name)
        else:
            hy2_name = name + "-HY2"
            if any(n.get("name") == hy2_name for n in nodes):
                to_remove.add(hy2_name)

        if cleanup_confirmed is True:
            if not target.get("cleanup_pending") or not all(
                n.get("cleanup_pending") for n in nodes if n.get("name") in to_remove
            ):
                return 400, {"ok": False, "error": "请先移出订阅并完成服务器人工清理"}, None

            logger.log("WARN", "NODE", "用户确认已人工清理，移除节点记录: %s" % name)
            return (
                200,
                {
                    "ok": True,
                    "cleanup_pending": False,
                    "confirmed_by_user": True,
                    "message": "已按你的确认移除记录；服务器清理结果未由系统验证",
                },
                lambda ns: [n for n in ns if n.get("name") not in to_remove],
            )

        def _mark_cleanup(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            for n in ns:
                if n.get("name") in to_remove:
                    n["enabled"] = False
                    n["cleanup_pending"] = True
                    n.pop("quota_control_managed", None)
            return ns

        logger.log("WARN", "NODE", "节点已移出订阅，待用户人工清理: %s" % name)
        return (
            200,
            {
                "ok": True,
                "cleanup_pending": True,
                "stopped": None,
                "message": "已移出订阅；服务器未作改动，请人工清理后确认",
            },
            _mark_cleanup,
        )

    @staticmethod
    def edit_node(
        nodes: List[Dict[str, Any]],
        name: str,
        body: Dict[str, Any],
        links_mod: Any,
        remote_cfg_mod: Any,
        logger: Any,
    ) -> Tuple[int, Dict[str, Any], Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]]]:
        """编辑节点参数（重命名、使能、生命周期、ISP 代理挂载等）。"""
        target = next((n for n in nodes if n.get("name") == name), None)
        if not target:
            return 404, {"ok": False, "error": "没找到这个节点"}, None

        if target.get("cleanup_pending") and body.get("enabled") is True:
            return 409, {"ok": False, "error": "节点待人工清理，不能重新启用"}, None

        newname = (body.get("newname") or "").strip()
        newkey = bool(body.get("newkey"))
        port_raw = body.get("port")
        new_port = None
        if port_raw not in (None, ""):
            try:
                new_port = int(port_raw)
                if new_port < 1 or new_port > 65535:
                    raise ValueError()
            except Exception:
                return 400, {"ok": False, "error": "端口必须是 1-65535"}, None

        new_uuid = str(uuid.uuid4()) if newkey else None
        need_remote = bool(new_uuid) or (new_port is not None and new_port != target.get("port"))
        if need_remote:
            return 409, {"ok": False, "error": "无法确认服务独占，暂不能修改服务器端口或密钥；请人工检查"}, None

        parsed_isp = None
        isp_changed = False
        if "isp" in body:
            isp_changed = True
            raw_isp = body["isp"]
            if raw_isp in (None, ""):
                parsed_isp = None
            elif isinstance(raw_isp, str):
                try:
                    parsed_isp = links_mod.parse_isp_proxy(raw_isp)
                except links_mod.LinkError as e:
                    return 400, {"ok": False, "error": str(e)}, None
            elif isinstance(raw_isp, dict):
                if not raw_isp.get("server") or not raw_isp.get("server_port"):
                    return 400, {"ok": False, "error": "ISP 代理缺少服务器地址或端口"}, None
                try:
                    port_num = int(raw_isp["server_port"])
                    if port_num < 1 or port_num > 65535:
                        raise ValueError()
                except Exception:
                    return 400, {"ok": False, "error": "端口号无效"}, None
                parsed_isp = {
                    "type": raw_isp.get("type", "socks"),
                    "server": str(raw_isp["server"]),
                    "server_port": port_num,
                }
                if raw_isp.get("username"):
                    parsed_isp["username"] = str(raw_isp["username"])
                if raw_isp.get("password"):
                    parsed_isp["password"] = str(raw_isp["password"])
            else:
                return 400, {"ok": False, "error": "ISP 代理参数格式不正确"}, None

        isp_sync_res = None
        if isp_changed:
            isp_sync_res = remote_cfg_mod.sync_isp(target, parsed_isp)
            if not isp_sync_res.get("ok"):
                logger.log("WARN", "NODE", "节点 [%s] 静态住宅代理同步失败: %s" % (name, isp_sync_res.get("error")))
                return (
                    502,
                    {
                        "ok": False,
                        "error": isp_sync_res.get("error") or "远端静态住宅出口同步失败",
                        "rolled_back": isp_sync_res.get("rolled_back", False),
                        "verify": isp_sync_res.get("verify"),
                    },
                    None,
                )

        def _apply(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            for n in ns:
                if n.get("name") == name:
                    if new_uuid:
                        n["uuid"] = new_uuid
                    if new_port is not None:
                        n["port"] = new_port
                    if newname and newname != name:
                        n["name"] = newname
                    if "enabled" in body:
                        n["enabled"] = bool(body["enabled"])
                    if "expire_at" in body:
                        n["expire_at"] = body["expire_at"]
                    if "lifecycle" in body and isinstance(body["lifecycle"], dict):
                        n["lifecycle"] = dict(body["lifecycle"])
                    if "state" in body:
                        lc = dict(n.get("lifecycle") or {})
                        lc["state"] = body["state"]
                        n["lifecycle"] = lc
                    if "landing_policy" in body and isinstance(body["landing_policy"], dict):
                        n["landing_policy"] = dict(body["landing_policy"])
                    if isp_changed:
                        if parsed_isp is None:
                            n.pop("isp", None)
                        else:
                            n["isp"] = dict(parsed_isp)
                        if isp_sync_res:
                            n["health"] = "ok"
                            if isp_sync_res.get("exit_ip"):
                                n["exit_ip"] = isp_sync_res["exit_ip"]
                            if isp_sync_res.get("exit_country"):
                                n["exit_country"] = isp_sync_res["exit_country"]
                            if isp_sync_res.get("health_detail"):
                                n["health_detail"] = isp_sync_res["health_detail"]
            return ns

        logger.log(
            "INFO",
            "NODE",
            "编辑节点 %s: 新名称=%s, 端口=%s, 更换密钥=%s"
            % (name, newname or "未改", new_port or "未改", "是" if newkey else "否"),
        )
        return 200, {"ok": True, "target_name": newname or name}, _apply
