# -*- coding: utf-8 -*-
"""云厂商适配层入口。

重要区分：
- "skip"  = 这台机器不归我管（没有对应云，或不是那家云的机器）
- "error" = 我管，但调用失败了（凭据过期、API 报错、网络不通）

以前两者都当 skip，结果是"腾讯云 API 挂了"被显示成"这台不是腾讯云的机器"。
"""
import importlib

_MODULES = ["tencent", "generic"]


def load_all(errors=None):
    """errors 传一个 list 进来，加载失败会记在里面（不传就只是静默跳过）。"""
    out = []
    for name in _MODULES:
        try:
            mod = importlib.import_module("providers." + name)
            p = mod.Provider()
            if p.available():
                out.append(p)
        except Exception as e:
            if errors is not None:
                errors.append("%s 加载失败: %s" % (name, str(e)[:80]))
    return out


def open_port(ip, port, proto="TCP", dry_run=False):
    """返回 (状态, 说明, 谁开的)。状态可能是 opened / already / skip / error。"""
    proto = (proto or "TCP").upper()
    errs = []
    for p in load_all(errs):
        try:
            st, msg = p.open_port(ip, port, proto=proto, dry_run=dry_run)
        except Exception as e:
            errs.append("%s.open_port: %s" % (getattr(p, "name", "?"), str(e)[:80]))
            continue
        if st != "skip":
            return st, msg, p.name
    if errs:
        return "error", "云 API 调用失败：%s" % "；".join(errs), ""
    return "skip", "没有接入这台机器的云厂商，请到服务商面板手动放行 %s %s" % (proto, port), ""


def reset_password(ip, dry_run=False):
    errs = []
    for p in load_all(errs):
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
