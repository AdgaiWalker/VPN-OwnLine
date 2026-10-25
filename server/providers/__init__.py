"""云厂商适配层入口。"""
import importlib

# 顺序即优先级。generic 永远排最后，它是兜底（只会给手动操作指引）。
_MODULES = ["tencent", "generic"]


def load_all():
    out = []
    for name in _MODULES:
        try:
            mod = importlib.import_module("providers." + name)
            p = mod.Provider()
            if p.available():
                out.append(p)
        except Exception:
            continue
    return out


def open_port(ip, port, dry_run=False):
    """问遍所有 provider，谁能开谁开。返回 (状态, 说明, 谁开的)。"""
    for p in load_all():
        try:
            st, msg = p.open_port(ip, port, dry_run=dry_run)
        except Exception:
            continue
        if st != "skip":
            return st, msg, p.name
    return "skip", "没有接入这台机器的云厂商，请到服务商面板手动放行 TCP %s" % port, ""


def reset_password(ip, dry_run=False):
    """问遍所有 provider，谁能重置谁重置。返回 (状态, 说明, 附加数据, 谁做的)。"""
    for p in load_all():
        try:
            st, msg, extra = p.reset_password(ip, dry_run=dry_run)
        except Exception:
            continue
        if st != "skip":
            return st, msg, extra, p.name
    return "skip", "这台不是托管在已接入的云上，只能手动重置密码", {}, ""
