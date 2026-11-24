"""节点控制面统一深模块 (Node Control Plane Deep Module).

掌控全系统节点拓扑、生命周期流转、原子持久化与订阅分发渲染的单一权威深模块。
对外暴露极简领域接口，内部封装 AtomicJsonStore 事务落盘、远端出网验真同步与自动渲染回调。
"""
from __future__ import annotations

import ipaddress
import re
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Union

from .store import AtomicJsonStore

_PROXY_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


def _is_valid_proxy_server(host: str) -> bool:
    s = str(host or "").strip()
    if not s or len(s) > 253 or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in s):
        return False
    if "://" in s or "/" in s or "@" in s or "\\" in s:
        return False
    bare = s[1:-1] if s.startswith("[") and s.endswith("]") else s
    try:
        ipaddress.ip_address(bare)
        return True
    except ValueError:
        pass
    return bool(_PROXY_HOSTNAME_RE.fullmatch(s))


# =====================================================================
# 1. 领域异常定义 (Domain Exceptions)
# =====================================================================

class NodeManagerError(Exception):
    """节点控制面异常基类。包含 HTTP 映射状态码与结构化详情。"""

    def __init__(self, message: str, status_code: int = 400, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}


class NodeNotFoundError(NodeManagerError):
    def __init__(self, message: str = "没找到这个节点"):
        super().__init__(message, status_code=404)


class CleanupPendingError(NodeManagerError):
    def __init__(self, message: str = "请先移出订阅并完成服务器人工清理"):
        super().__init__(message, status_code=400)


class NodeValidationError(NodeManagerError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message, status_code=status_code)


class NodeConflictError(NodeManagerError):
    def __init__(self, message: str):
        super().__init__(message, status_code=409)


class RemoteSyncError(NodeManagerError):
    def __init__(self, message: str, rolled_back: bool = False, verify: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            status_code=502,
            data={"rolled_back": rolled_back, "verify": verify},
        )


# =====================================================================
# 2. 持久化接缝与适配器 (Storage Seam & Adapters)
# =====================================================================

class NodeStore(Protocol):
    """节点持久化接缝协议。"""

    def load(self) -> List[Dict[str, Any]]: ...
    def dump(self, nodes: List[Dict[str, Any]]) -> None: ...
    def update(self, mutator: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]) -> List[Dict[str, Any]]: ...


class FileNodeStore:
    """生产环境文件存储适配器：基于 AtomicJsonStore 实现全局文件锁与原子落盘。"""

    def __init__(self, path: Union[str, Path, Callable[[], Union[str, Path]]] = "/opt/web-data/nodes.json"):
        self._path_source = path

    @property
    def path(self) -> Path:
        if callable(self._path_source):
            return Path(self._path_source())
        return Path(self._path_source)

    def load(self) -> List[Dict[str, Any]]:
        return list(AtomicJsonStore.load(self.path, default=[]) or [])

    def dump(self, nodes: List[Dict[str, Any]]) -> None:
        AtomicJsonStore.dump(self.path, nodes)

    def update(self, mutator: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        return list(AtomicJsonStore.update(self.path, mutator, default=[]) or [])


class InMemoryNodeStore:
    """测试环境内存存储适配器：完全解耦磁盘 I/O，支持高速纯内存单测。"""

    def __init__(self, initial_nodes: Optional[List[Dict[str, Any]]] = None):
        self._lock = threading.Lock()
        self._nodes: List[Dict[str, Any]] = deepcopy(initial_nodes or [])

    def load(self) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy(self._nodes)

    def dump(self, nodes: List[Dict[str, Any]]) -> None:
        with self._lock:
            self._nodes = deepcopy(nodes)

    def update(self, mutator: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        with self._lock:
            updated = mutator(deepcopy(self._nodes))
            self._nodes = deepcopy(updated)
            return deepcopy(self._nodes)


# =====================================================================
# 3. 核心深模块 (NodeManager Deep Module)
# =====================================================================

class NodeManager:
    """节点控制面统一深模块。

    小接口：list_nodes, get_node, remove_node, edit_node, switch_relay, bind_relay, unbind_relay, toggle_hy2.
    大实现：隐藏并发读改写持锁、远端配置原子下发、出网验真同步与订阅重新渲染。
    """

    def __init__(
        self,
        store: Optional[NodeStore] = None,
        remote_cfg_mod: Any = None,
        links_mod: Any = None,
        logger: Any = None,
        open_firewall_fn: Optional[Callable[[str, int, str], Any]] = None,
        on_change: Optional[Callable[[], Any]] = None,
    ):
        self.store: NodeStore = store if store is not None else FileNodeStore()
        self.remote_cfg = remote_cfg_mod
        self.links = links_mod
        self.logger = logger
        self.open_firewall = open_firewall_fn
        self.on_change = on_change
        self._mutation_lock = threading.RLock()

    def _log(self, level: str, tag: str, msg: str) -> None:
        if self.logger and hasattr(self.logger, "log"):
            try:
                self.logger.log(level, tag, msg)
            except Exception:
                pass

    def _trigger_on_change(self) -> None:
        if self.on_change and callable(self.on_change):
            try:
                self.on_change()
            except Exception as e:
                self._log("ERROR", "SUB", f"变更后自动触发渲染异常: {e}")

    # -----------------------------------------------------------------
    # 查询接口
    # -----------------------------------------------------------------

    def list_nodes(self, filter_fn: Optional[Callable[[Dict[str, Any]], bool]] = None) -> List[Dict[str, Any]]:
        """获取所有节点列表。"""
        nodes = self.store.load()
        if filter_fn:
            return [n for n in nodes if filter_fn(n)]
        return nodes

    def get_node(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称精准查询节点。"""
        if not name:
            return None
        return next((n for n in self.store.load() if n.get("name") == name), None)

    @staticmethod
    def _group(nodes, target):
        """Read stable groups; recognize a same-host conventional pair in legacy data."""
        group_id = target.get("group_id")
        if group_id:
            return [n for n in nodes if n.get("group_id") == group_id]
        name = target.get("name") or ""
        is_hy2 = target.get("type") == "hysteria2"
        companion = name[:-4] if is_hy2 and name.endswith("-HY2") else name + "-HY2"
        return [n for n in nodes if n is target or (
            n.get("name") == companion
            and n.get("host") == target.get("host")
            and bool(n.get("type") == "hysteria2") != is_hy2
        )]

    @classmethod
    def _ensure_group(cls, nodes, target):
        group = cls._group(nodes, target)
        group_id = target.get("group_id") or next(
            (n["group_id"] for n in group if n.get("group_id")), None
        ) or uuid.uuid4().hex
        for n in group:
            n["group_id"] = group_id
        return group

    @classmethod
    def _rename_plan(cls, nodes, target, newname):
        if not newname or newname == target.get("name"):
            return {}
        names = {target["name"]: newname}
        if target.get("type") != "hysteria2":
            companion = target["name"] + "-HY2"
            if any(n.get("name") == companion for n in cls._group(nodes, target)):
                names[companion] = newname + "-HY2"
        for n in nodes:
            if n.get("name") not in names and n.get("name") in names.values():
                raise NodeConflictError("节点名称已存在")
        return names

    @staticmethod
    def _rename_references(nodes, names):
        for n in nodes:
            refs = [n.get("landing"), n.get("fallback_landing")]
            policy = n.get("landing_policy")
            if isinstance(policy, dict):
                refs.extend(policy.get(key) for key in ("primary", "fallback"))
            for ref in refs:
                if isinstance(ref, dict) and ref.get("name") in names:
                    ref["name"] = names[ref["name"]]

    # -----------------------------------------------------------------
    # 变更接口：直接返回结构化结果，自动落盘与渲染，抛出领域异常
    # -----------------------------------------------------------------

    def add_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """原子纳管新节点（防并发冲突，自动持锁落盘与变更渲染）。"""
        if not isinstance(node, dict):
            raise NodeValidationError("节点数据格式不正确")
        name = (node.get("name") or "").strip()
        host = (node.get("host") or "").strip()
        if not host:
            raise NodeValidationError("缺少节点主机地址")
        if not name:
            name = f"节点-{host}"
        node["name"] = name
        try:
            port = int(node.get("port") or 443)
            if port < 1 or port > 65535:
                raise ValueError()
            node["port"] = port
        except Exception:
            raise NodeValidationError("端口必须是 1-65535")

        if "health" not in node:
            node["health"] = "ok"

        # 默认最佳实践：新入网海外落地机默认开启 WARP AI 清洁出网与 HY2 伴生通道能力
        is_overseas_exit = (
            node.get("role") != "relay"
            and node.get("type") != "hysteria2"
            and (node.get("exit_country") or node.get("country") or "").upper() != "CN"
        )
        if is_overseas_exit:
            if "warp_enabled" not in node:
                node["warp_enabled"] = True
            if "hy2_enabled" not in node:
                node["hy2_enabled"] = True
        elif node.get("type") == "hysteria2":
            if "enabled" not in node:
                node["enabled"] = True

        def _mutator(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            existing = next((n for n in ns if n.get("name") == name), None)
            if existing and existing.get("group_id"):
                node["group_id"] = existing["group_id"]
            filtered = [x for x in ns if x.get("name") != name]
            updated = filtered + [node]
            self._ensure_group(updated, node)
            return updated

        self.store.update(_mutator)
        self._trigger_on_change()
        self._log("INFO", "NODE", f"成功纳管节点: {name} ({host})")
        return {"ok": True, "node": node}

    def remove_node(self, name: str, cleanup_confirmed: bool = False) -> Dict[str, Any]:
        """移除或标记待清理节点。"""
        name = (name or "").strip()
        if not name:
            raise NodeNotFoundError("缺少节点名称")

        def _remove(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            target = next((n for n in ns if n.get("name") == name), None)
            if target is None:
                raise NodeNotFoundError("没找到这个节点")
            group = self._ensure_group(ns, target)
            if cleanup_confirmed is True:
                if not all(n.get("cleanup_pending") for n in group):
                    raise CleanupPendingError("请先移出订阅并完成服务器人工清理")
                return [n for n in ns if n not in group]
            for n in group:
                n["enabled"] = False
                n["cleanup_pending"] = True
                n.pop("quota_control_managed", None)
            return ns

        self.store.update(_remove)
        if cleanup_confirmed is True:
            self._log("WARN", "NODE", f"用户确认已人工清理，移除节点记录: {name}")
            self._trigger_on_change()
            return {
                "ok": True,
                "cleanup_pending": False,
                "confirmed_by_user": True,
                "message": "已按你的确认移除记录；服务器清理结果未由系统验证",
            }

        self._trigger_on_change()
        self._log("WARN", "NODE", f"节点已移出订阅，待用户人工清理: {name}")
        return {
            "ok": True,
            "cleanup_pending": True,
            "stopped": None,
            "message": "已移出订阅；服务器未作改动，请人工清理后确认",
        }

    def edit_node(self, name: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """编辑节点参数（重命名、使能、生命周期、ISP 代理挂载等）。"""
        name = (name or "").strip()
        nodes = self.store.load()
        target = next((n for n in nodes if n.get("name") == name), None)
        if not target:
            raise NodeNotFoundError("没找到这个节点")

        if target.get("cleanup_pending") and body.get("enabled") is True:
            raise NodeConflictError("节点待人工清理，不能重新启用")

        newname = (body.get("newname") or "").strip()
        self._rename_plan(nodes, target, newname)
        newkey = bool(body.get("newkey"))
        port_raw = body.get("port")
        new_port = None
        if port_raw not in (None, ""):
            try:
                new_port = int(port_raw)
                if new_port < 1 or new_port > 65535:
                    raise ValueError()
            except Exception:
                raise NodeValidationError("端口必须是 1-65535")

        new_uuid = str(uuid.uuid4()) if newkey else None
        need_remote = bool(new_uuid) or (new_port is not None and new_port != target.get("port"))
        if need_remote:
            raise NodeConflictError("无法确认服务独占，暂不能修改服务器端口或密钥；请人工检查")

        parsed_isp = None
        isp_changed = False
        if "isp" in body:
            isp_changed = True
            raw_isp = body["isp"]
            if raw_isp in (None, ""):
                parsed_isp = None
            elif isinstance(raw_isp, str):
                if not self.links:
                    raise NodeValidationError("缺少 links 模块支持")
                try:
                    parsed_isp = self.links.parse_isp_proxy(raw_isp)
                except Exception as e:
                    raise NodeValidationError(str(e))
            elif isinstance(raw_isp, dict):
                raw_server = str(raw_isp.get("server") or "").strip()
                if not raw_server or not raw_isp.get("server_port"):
                    raise NodeValidationError("ISP 代理缺少服务器地址或端口")
                if not _is_valid_proxy_server(raw_server):
                    raise NodeValidationError("ISP 代理服务器地址格式无效，请输入合法的 IP 地址或域名")
                try:
                    port_num = int(raw_isp["server_port"])
                    if port_num < 1 or port_num > 65535:
                        raise ValueError()
                except Exception:
                    raise NodeValidationError("端口号无效")
                parsed_isp = {
                    "type": raw_isp.get("type", "socks"),
                    "server": raw_server,
                    "server_port": port_num,
                }
                if raw_isp.get("username"):
                    parsed_isp["username"] = str(raw_isp["username"])
                if raw_isp.get("password"):
                    parsed_isp["password"] = str(raw_isp["password"])
            else:
                raise NodeValidationError("ISP 代理参数格式不正确")

        isp_sync_res = None
        if isp_changed:
            if not self.remote_cfg:
                raise NodeValidationError("缺少 remote_config 模块支持")
            isp_sync_res = self.remote_cfg.sync_isp(target, parsed_isp)
            if not isp_sync_res.get("ok"):
                self._log("WARN", "NODE", f"节点 [{name}] 静态住宅代理同步失败: {isp_sync_res.get('error')}")
                raise RemoteSyncError(
                    isp_sync_res.get("error") or "远端静态住宅出口同步失败",
                    rolled_back=isp_sync_res.get("rolled_back", False),
                    verify=isp_sync_res.get("verify"),
                )

        def _apply_edit(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            current = next((n for n in ns if n.get("name") == name), None)
            if current is None:
                raise NodeNotFoundError("没找到这个节点")
            group = self._group(ns, current)
            if body.get("enabled") is True and any(n.get("cleanup_pending") for n in group):
                raise NodeConflictError("节点待人工清理，不能重新启用")
            rename = self._rename_plan(ns, current, newname)
            group = self._ensure_group(ns, current)
            for n in ns:
                if n is current:
                    if new_uuid:
                        n["uuid"] = new_uuid
                    if new_port is not None:
                        n["port"] = new_port
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
                if n in group:
                    if "enabled" in body:
                        n["enabled"] = bool(body["enabled"])
                        if n.get("type") == "hysteria2" and body["enabled"]:
                            primary = next((x for x in group if x.get("type") != "hysteria2"), {})
                            n["enabled"] = primary.get("hy2_enabled", True) is not False
                    if "expire_at" in body:
                        n["expire_at"] = body["expire_at"]
                    if "lifecycle" in body and isinstance(body["lifecycle"], dict):
                        n["lifecycle"] = dict(body["lifecycle"])
                    if "state" in body:
                        lc = dict(n.get("lifecycle") or {})
                        lc["state"] = body["state"]
                        n["lifecycle"] = lc
                if n.get("name") in rename:
                    n["name"] = rename[n["name"]]
            self._rename_references(ns, rename)
            return ns

        self.store.update(_apply_edit)
        self._trigger_on_change()
        self._log(
            "INFO",
            "NODE",
            f"编辑节点 {name}: 新名称={newname or '未改'}, 端口={new_port or '未改'}, 更换密钥={'是' if newkey else '否'}",
        )
        return {"ok": True, "target_name": newname or name}

    def switch_relay(self, name: str, target_host: str) -> Dict[str, Any]:
        """中转节点实时切流。"""
        target_host = (target_host or "").strip()
        if not target_host:
            raise NodeValidationError("缺少 target 目标主机地址")

        nodes = self.store.load()
        relay_node = (
            next((n for n in nodes if n.get("name") == name and n.get("type") != "hysteria2"), None)
            if name
            else next((n for n in nodes if n.get("role") == "relay" and n.get("type") != "hysteria2"), None)
        )
        if not relay_node:
            raise NodeNotFoundError("未找到可切换的中转入口节点")

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
            raise NodeNotFoundError("未找到匹配的目标海外出口服务器")

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

        if not self.remote_cfg:
            raise NodeValidationError("缺少 remote_config 模块支持")

        sync_res = self.remote_cfg.switch_relay(relay_node, target_exit, fallback_exit_node=fallback_exit)
        if not sync_res.get("ok"):
            self._log(
                "WARN",
                "RELAY",
                f"中转切流失败 [{relay_node.get('name')} ➔ {target_host}]: {sync_res.get('error')}",
            )
            raise RemoteSyncError(
                sync_res.get("error") or "远端中转切换失败",
                rolled_back=sync_res.get("rolled_back", False),
                verify=sync_res.get("verify"),
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

        self.store.update(_apply_switch)
        self._trigger_on_change()
        self._log(
            "INFO",
            "RELAY",
            f"管理员完成真实中转切流: 节点 [{relay_node.get('name')}] ➔ 目标 [{target_exit.get('name') or target_host}]",
        )
        return {
            "ok": True,
            "node": relay_node.get("name"),
            "active_target": sync_res["landing"]["host"],
            "verify": sync_res.get("verify"),
        }

    def bind_relay(self, name: str, target_host: str, fallback_host: Optional[str] = None) -> Dict[str, Any]:
        """中转节点手动绑定落地节点。"""
        name = (name or "").strip()
        target_host = (target_host or "").strip()
        fallback_host = (fallback_host or "").strip() or None

        if not name or not target_host:
            raise NodeValidationError("缺少节点名称 (name) 或落地目标 (target)")

        nodes = self.store.load()
        relay_node = next((n for n in nodes if n.get("name") == name and n.get("type") != "hysteria2"), None)
        if not relay_node:
            raise NodeNotFoundError("未找到指定的中转入口服务器")

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
            raise NodeNotFoundError("未找到匹配的目标海外出口服务器")

        fallback_exit = None
        if fallback_host:
            fallback_exit = next(
                (
                    n
                    for n in nodes
                    if (n.get("host") == fallback_host or n.get("name") == fallback_host)
                    and n.get("type") != "hysteria2"
                ),
                None,
            )
        if not fallback_exit:
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

        if not self.remote_cfg:
            raise NodeValidationError("缺少 remote_config 模块支持")

        sync_res = self.remote_cfg.bind_relay(relay_node, target_exit, fallback_exit_node=fallback_exit)
        if not sync_res.get("ok"):
            self._log(
                "WARN",
                "RELAY",
                f"中转手动绑定失败 [{name} ➔ {target_host}]: {sync_res.get('error')}",
            )
            raise RemoteSyncError(
                sync_res.get("error") or "远端中转手动绑定失败",
                rolled_back=sync_res.get("rolled_back", False),
                verify=sync_res.get("verify"),
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

        self.store.update(_apply_bind)
        self._trigger_on_change()
        self._log(
            "INFO",
            "RELAY",
            f"建立中转加速专线并完成真实出网验真: 节点 [{name}] ➔ 落地 [{target_exit.get('name')}]",
        )
        return {
            "ok": True,
            "message": "已成功建立中转加速专线并通过真实出网验证",
            "verify": sync_res.get("verify"),
        }

    def unbind_relay(self, name: str) -> Dict[str, Any]:
        """中转节点解除落地绑定。"""
        name = (name or "").strip()
        if not name:
            raise NodeValidationError("缺少节点名称 (name)")

        nodes = self.store.load()
        relay_node = next((n for n in nodes if n.get("name") == name and n.get("type") != "hysteria2"), None)
        if not relay_node:
            raise NodeNotFoundError("未找到指定的中转入口服务器")

        if not self.remote_cfg:
            raise NodeValidationError("缺少 remote_config 模块支持")

        sync_res = self.remote_cfg.unbind_relay(relay_node)
        if not sync_res.get("ok"):
            self._log("WARN", "RELAY", f"中转解除绑定失败 [{name}]: {sync_res.get('error')}")
            raise RemoteSyncError(
                sync_res.get("error") or "远端中转解绑失败",
                rolled_back=sync_res.get("rolled_back", False),
                verify=sync_res.get("verify"),
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

        self.store.update(_apply_unbind)
        self._trigger_on_change()
        self._log("INFO", "RELAY", f"解除中转加速并已同步远端配置: 节点 [{name}] 恢复为独立服务器")
        return {
            "ok": True,
            "message": "已解除中转关系，远端配置已还原为独立服务器",
        }

    def auto_pair_relay(self) -> Dict[str, Any]:
        """当系统内恰好存在 1 个未绑定中转的国内节点与至少 1 个海外出口节点时，自动执行专线配对。"""
        with self._mutation_lock:
            nodes = self.store.load()
            dom_unbonded = [
                n
                for n in nodes
                if n.get("type") != "hysteria2"
                and (n.get("role") in ("relay", "standalone") or (n.get("country") or "").upper() == "CN")
                and not (n.get("landing") and n.get("landing", {}).get("host"))
                and not n.get("cleanup_pending")
            ]
            exit_nodes = [
                n
                for n in nodes
                if n.get("type") != "hysteria2"
                and n.get("role") not in ("relay", "standalone")
                and (n.get("exit_country") or n.get("country") or "").upper() != "CN"
                and not n.get("cleanup_pending")
            ]

            if len(dom_unbonded) != 1 or not exit_nodes:
                return {"ok": False, "reason": "不满足单国内+海外出口自动配对条件"}

            relay_node = dom_unbonded[0]
            target_exit = exit_nodes[0]
            fallback_exit = exit_nodes[1] if len(exit_nodes) > 1 else None

            if not self.remote_cfg:
                raise NodeValidationError("缺少 remote_config 模块支持")

            return self.bind_relay(
                name=relay_node.get("name"),
                target_host=target_exit.get("host"),
                fallback_host=fallback_exit.get("host") if fallback_exit else None,
            )

    def toggle_hy2(self, name: str = "", host: str = "", enabled: bool = True) -> Dict[str, Any]:
        """切换海外出口节点的 HY2 极速通道状态。"""
        with self._mutation_lock:
            name = (name or "").strip()
            host = (host or "").strip()
            if not host and not name:
                raise NodeValidationError("缺少 host 或 name")

            nodes = self.store.load()
            base_name = name[:-4] if name.endswith("-HY2") else name
            named = next((n for n in nodes if n.get("name") == name), None)
            named_group = self._group(nodes, named) if named else []
            vless_node = next(
                (
                    n
                    for n in nodes
                    if n.get("type") != "hysteria2"
                    and (
                        (host and (n.get("host") == host or n.get("ip") == host))
                        or (named_group and n in named_group)
                        or (not named and base_name and n.get("name") == base_name)
                    )
                ),
                None,
            )
            if not vless_node:
                raise NodeNotFoundError("未找到对应的海外出口主节点")

            target_host = vless_node.get("host")
            group = self._group(nodes, vless_node)
            if enabled and any(n.get("cleanup_pending") for n in group):
                raise NodeConflictError("节点待人工清理，不能重新启用")
            existing_hy2 = next(
                (
                    n
                    for n in nodes
                    if n.get("type") == "hysteria2"
                    and n in group
                ),
                None,
            )
            hy2_name = (existing_hy2 or {}).get("name") or vless_node["name"] + "-HY2"
            if enabled and any(n.get("name") == hy2_name and n not in group for n in nodes):
                raise NodeConflictError("HY2 伴生节点名称已存在")

            if not self.remote_cfg:
                raise NodeValidationError("缺少 remote_config 模块支持")

            sync_res = self.remote_cfg.toggle_hy2(
                vless_node,
                existing_hy2_node=existing_hy2,
                enabled=enabled,
                open_firewall_fn=self.open_firewall,
            )
            if not sync_res.get("ok"):
                self._log(
                    "WARN",
                    "NODE",
                    f"切换 HY2 失败 [{vless_node.get('name')} -> {'开启' if enabled else '关闭'}]: {sync_res.get('error')}",
                )
                raise RemoteSyncError(
                    sync_res.get("error") or "远端切换 HY2 失败",
                    rolled_back=sync_res.get("rolled_back", False),
                    verify=sync_res.get("verify"),
                )

            hy2_record = sync_res.get("hy2_node")

            def _apply_hy2(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                current = next((n for n in ns if n.get("name") == vless_node.get("name")), None)
                if current is None:
                    raise NodeNotFoundError("未找到对应的海外出口主节点")
                current_group = self._ensure_group(ns, current)
                if hy2_record:
                    hy2_record["group_id"] = current["group_id"]
                    if any(n.get("name") == hy2_record.get("name") and n not in current_group for n in ns):
                        raise NodeConflictError("HY2 伴生节点名称已存在")
                out_list = []
                placed_hy2 = False
                for n in ns:
                    is_hy2_item = n.get("type") == "hysteria2" and n in current_group
                    if is_hy2_item:
                        if enabled and hy2_record:
                            record = dict(hy2_record)
                            record["enabled"] = current.get("enabled", True) is not False
                            out_list.append(record)
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
                    record = dict(hy2_record)
                    record["enabled"] = current.get("enabled", True) is not False
                    out_list.append(record)
                return out_list

            self.store.update(_apply_hy2)
            self._trigger_on_change()
            state_str = "开启" if enabled else "关闭"
            self._log(
                "INFO",
                "NODE",
                f"切换 HY2 极速通道并完成远端同步: {vless_node.get('name') or target_host} ➔ {state_str}",
            )
            return {
                "ok": True,
                "enabled": enabled,
                "message": f"HY2 极速通道已{state_str}并通过远端校验",
                "verify": sync_res.get("verify"),
            }

    def toggle_warp(self, name: str = "", enabled: bool = True) -> Dict[str, Any]:
        """切换海外出口节点的 Cloudflare WARP 清洁出网状态。"""
        with self._mutation_lock:
            name = (name or "").strip()
            if not name:
                raise NodeValidationError("缺少节点名称 (name)")

            nodes = self.store.load()
            target_node = next((n for n in nodes if n.get("name") == name), None)
            if not target_node:
                raise NodeNotFoundError("未找到指定的节点")

            target_warp = None
            if self.remote_cfg and hasattr(self.remote_cfg, "toggle_warp"):
                sync_res = self.remote_cfg.toggle_warp(target_node, enabled=enabled)
                if not sync_res.get("ok"):
                    self._log(
                        "WARN",
                        "WARP",
                        f"切换 WARP 失败 [{name} -> {'开启' if enabled else '关闭'}]: {sync_res.get('error')}",
                    )
                    raise RemoteSyncError(
                        sync_res.get("error") or "远端切换 WARP 失败",
                        rolled_back=sync_res.get("rolled_back", False),
                        verify=sync_res.get("verify"),
                    )
                target_warp = sync_res.get("warp")

            def _apply_warp(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                for n in ns:
                    if n.get("name") == name:
                        n["warp_enabled"] = bool(enabled)
                        if target_warp:
                            n["warp"] = target_warp
                        elif not enabled and "warp" in n:
                            n.pop("warp", None)
                return ns

            self.store.update(_apply_warp)
            self._trigger_on_change()
            state_str = "开启" if enabled else "关闭"
            self._log("INFO", "WARP", f"切换节点 [{name}] WARP 清洁出网: {state_str}")
            return {
                "ok": True,
                "name": name,
                "warp_enabled": bool(enabled),
                "message": f"节点 [{name}] WARP 清洁出网已{state_str}",
            }

    def reconcile_node(self, name: str, apply: bool = False) -> Dict[str, Any]:
        """检查节点现网与声明式底账的配置漂移；apply=True 时执行受控收敛与出网验真。"""
        with self._mutation_lock:
            name = (name or "").strip()
            if not name:
                raise NodeValidationError("缺少节点名称 (name)")
            nodes = self.store.load()
            target = next((n for n in nodes if n.get("name") == name), None)
            if not target:
                raise NodeNotFoundError("没找到这个节点")
            group = self._group(nodes, target)
            primary = target
            if target.get("type") == "hysteria2":
                primary = next((x for x in group if x.get("type") != "hysteria2"), target)
            hy2_node = next((x for x in group if x.get("type") == "hysteria2"), None)

            from . import reconcile as reconcile_mod
            res = reconcile_mod.reconcile_node(
                primary,
                hy2_node=hy2_node,
                apply=apply,
                remote_cfg_mod=self.remote_cfg,
            )
            if apply and res.get("ok") and res.get("changed"):
                vr = res.get("verify") or {}

                def _update_verified(ns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                    for n in ns:
                        if n.get("name") == primary.get("name"):
                            n["health"] = "ok"
                            if vr.get("exit_ip"):
                                n["exit_ip"] = vr["exit_ip"]
                            if vr.get("exit_country"):
                                n["exit_country"] = vr["exit_country"]
                            if vr.get("detail"):
                                n["health_detail"] = vr["detail"]
                    return ns

                self.store.update(_update_verified)
                self._trigger_on_change()
                self._log("INFO", "RECONCILE", f"节点 [{primary.get('name')}] 已完成声明式状态收敛")
            return res

    # -----------------------------------------------------------------
    # 通用事务写能力 (任意 Mutation 原子保护)
    # -----------------------------------------------------------------

    def save_nodes(self, nodes: List[Dict[str, Any]]) -> None:
        """全量保存节点并触发自动渲染。"""
        self.store.dump(nodes)
        self._trigger_on_change()

    def update_nodes(self, mutator: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """全程持锁原子读-改-写并自动触发渲染。"""
        updated = self.store.update(mutator)
        self._trigger_on_change()
        return updated
