"""sing-box 配置模板：出口（exit）与中转（relay）。

生成的配置会被 sing-box 自己的 check 校验，校验不过不推送到目标机。

只生成 dict，不落盘——落盘与 systemd 由 provision 负责。
"""

import re


def _inbound(port, uuid, sni, private_key, sid):
    return {
        "type": "vless",
        "tag": "vless-reality",
        "listen": "::",
        "listen_port": int(port),
        "users": [{"uuid": uuid, "flow": "xtls-rprx-vision"}],
        "tls": {
            "enabled": True,
            "server_name": sni,
            "reality": {
                "enabled": True,
                "handshake": {"server": sni, "server_port": 443},
                "private_key": private_key,
                "short_id": [sid],
            },
        },
    }


def exit_config(port, uuid, sni, private_key, sid):
    """海外落地节点：只出不进（直连出网）。"""
    return {
        "log": {"level": "warn", "output": "/var/log/sing-box.log", "timestamp": True},
        "inbounds": [_inbound(port, uuid, sni, private_key, sid)],
        "outbounds": [{"type": "direct", "tag": "direct"}],
    }


def relay_config(port, uuid, sni, private_key, sid, landing):
    """国内中转：所有流量交给 landing 再出去。"""
    lb = {
        "type": "vless",
        "tag": "landing",
        "server": landing["host"],
        "server_port": int(landing["port"]),
        "uuid": landing["uuid"],
        "flow": landing.get("flow") or "xtls-rprx-vision",
        "tls": {
            "enabled": True,
            "server_name": landing["sni"],
            "utls": {"enabled": True, "fingerprint": "chrome"},
            "reality": {
                "enabled": True,
                "public_key": landing["pbk"],
                "short_id": landing["sid"],
            },
        },
    }
    return {
        "log": {"level": "warn", "output": "/var/log/sing-box.log", "timestamp": True},
        "inbounds": [_inbound(port, uuid, sni, private_key, sid)],
        "outbounds": [lb, {"type": "direct", "tag": "direct"}],
        "route": {"rules": [{"outbound": "landing"}]},
    }


def validate(cfg):
    """返回错误列表（空列表 = 合法）。只做结构检查，不校验运行时。"""
    errs = []
    ibs = cfg.get("inbounds") or []
    if not ibs:
        return ["缺少 inbounds"]
    ib = ibs[0]
    if not (0 < int(ib.get("listen_port") or 0) < 65536):
        errs.append("inbound 端口不合法")
    users = ib.get("users") or []
    if not users or not users[0].get("uuid"):
        errs.append("缺少 uuid")
    reality = (ib.get("tls") or {}).get("reality") or {}
    if not reality.get("private_key"):
        errs.append("缺少 reality private_key")
    sids = reality.get("short_id") or []
    if not sids:
        errs.append("缺少 short_id")
    for sid in sids:
        if not re.fullmatch(r"[0-9a-fA-F]{1,32}", str(sid)):
            errs.append("short_id 必须是十六进制：%s" % sid)
    if not (ib.get("tls") or {}).get("server_name"):
        errs.append("缺少 sni")
    for ob in cfg.get("outbounds") or []:
        if ob.get("type") == "vless":
            tls = ob.get("tls") or {}
            r = tls.get("reality") or {}
            if not (ob.get("server") and ob.get("uuid")):
                errs.append("落地节点缺少 server 或 uuid")
            if not r.get("public_key"):
                errs.append("落地节点缺少 public_key")
            if not re.fullmatch(r"[0-9a-fA-F]{1,32}", str(r.get("short_id") or "")):
                errs.append("落地节点 short_id 必须是十六进制")
    return errs
