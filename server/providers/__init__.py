# -*- coding: utf-8 -*-
"""云厂商适配层入口。

重要区分：
- "skip"  = 这台机器不归我管（没有对应云，或不是那家云的机器）
- "error" = 我管，但调用失败了（凭据过期、API 报错、网络不通）
"""
from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional, Tuple
from .base import Provider

_MODULES = ["tencent", "generic"]


class ProviderRegistry:
    """云厂商适配器注册中心与路由分发器。"""

    def __init__(self, modules: Optional[List[str]] = None) -> None:
        self.modules = list(modules or _MODULES)

    def load_all(self, errors: Optional[List[str]] = None) -> List[Provider]:
        out = []
        for name in self.modules:
            try:
                mod = importlib.import_module("providers." + name)
                p = getattr(mod, "Provider")()
                if p.available():
                    out.append(p)
            except Exception as e:
                if errors is not None:
                    errors.append("%s 加载失败: %s" % (name, str(e)[:80]))
        return out

    def open_port(
        self, ip: str, port: int, proto: str = "TCP", dry_run: bool = False
    ) -> Tuple[str, str, str]:
        proto = (proto or "TCP").upper()
        errs: List[str] = []
        for p in self.load_all(errs):
            try:
                st, msg = p.open_port(ip, port, proto=proto, dry_run=dry_run)
            except Exception as e:
                errs.append("%s.open_port: %s" % (getattr(p, "name", "?"), str(e)[:80]))
                continue
            if st != "skip":
                return st, msg, p.name
        if errs:
            return "error", "云 API 调用失败：%s" % "；".join(errs), ""
        return (
            "skip",
            "没有接入这台机器的云厂商，请到服务商面板手动放行 %s %s" % (proto, port),
            "",
        )

    def reset_password(
        self, ip: str, dry_run: bool = False
    ) -> Tuple[str, str, Dict[str, Any], str]:
        errs: List[str] = []
        for p in self.load_all(errs):
            try:
                st, msg, extra = p.reset_password(ip, dry_run=dry_run)
            except Exception as e:
                errs.append("%s.reset_password: %s" % (getattr(p, "name", "?"), str(e)[:80]))
                continue
            if st != "skip":
                return st, msg, extra, p.name
        if errs:
            return "error", "云 API 调用失败：%s" % "；".join(errs), {}, ""
        return "skip", "这台不是托管在已接入的云上，只能手动重置密码", {}, ""


_DEFAULT_REGISTRY = ProviderRegistry()


def load_all(errors: Optional[List[str]] = None) -> List[Provider]:
    """errors 传一个 list 进来，加载失败会记在里面（不传就只是静默跳过）。"""
    return _DEFAULT_REGISTRY.load_all(errors=errors)


def open_port(
    ip: str, port: int, proto: str = "TCP", dry_run: bool = False
) -> Tuple[str, str, str]:
    """返回 (状态, 说明, 谁开的)。状态可能是 opened / already / skip / error。"""
    return _DEFAULT_REGISTRY.open_port(ip, port, proto=proto, dry_run=dry_run)


def reset_password(
    ip: str, dry_run: bool = False
) -> Tuple[str, str, Dict[str, Any], str]:
    return _DEFAULT_REGISTRY.reset_password(ip, dry_run=dry_run)
