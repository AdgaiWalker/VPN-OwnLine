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


def exit_config(port, uuid, sni, private_key, sid, hy2=None):
    """海外落地节点：只出不进（直连出网）。

    hy2 可选：{"port": 443, "password": ..., "obfs_password": ..., "sni": ...}
    给了就再加一条 Hysteria2 入站（UDP），和 Reality 共用端口号互不影响。
    """
    inbounds = [_inbound(port, uuid, sni, private_key, sid)]
    if hy2:
        inbounds.append(_hy2_inbound(hy2.get("port", port), hy2["password"],
                                     hy2["obfs_password"], hy2.get("sni", sni)))
    return {
        "log": {"level": "warn", "output": "/var/log/sing-box.log", "timestamp": True},
        "inbounds": inbounds,
        "outbounds": [{"type": "direct", "tag": "direct"}],
    }


def _vless_landing_outbound(landing, tag="landing"):
    return {
        "type": "vless",
        "tag": tag,
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


def relay_config(port, uuid, sni, private_key, sid, landing, fallback_landing=None):
    """国内中转：支持单落地或双落地自动故障倒换 (urltest)。"""
    if fallback_landing:
        outbounds = [
            _vless_landing_outbound(landing, tag="landing-primary"),
            _vless_landing_outbound(fallback_landing, tag="landing-fallback"),
            {
                "type": "urltest",
                "tag": "auto-landing",
                "outbounds": ["landing-primary", "landing-fallback"],
                "url": "https://www.gstatic.com/generate_204",
                "interval": "1m",
                "tolerance": 50,
            },
            {"type": "direct", "tag": "direct"},
        ]
        route = {"rules": [{"outbound": "auto-landing"}]}
    else:
        lb = _vless_landing_outbound(landing, tag="landing")
        outbounds = [lb, {"type": "direct", "tag": "direct"}]
        route = {"rules": [{"outbound": "landing"}]}

    return {
        "log": {"level": "warn", "output": "/var/log/sing-box.log", "timestamp": True},
        "inbounds": [_inbound(port, uuid, sni, private_key, sid)],
        "outbounds": outbounds,
        "route": route,
    }


def _hy2_inbound(port, password, obfs_password, sni,
                 cert_path="/opt/sing-box/hy2.crt", key_path="/opt/sing-box/hy2.key",
                 up_mbps=50, down_mbps=200):
    """Hysteria2 / QUIC 入站。和 Reality 抢同一个端口号不冲突（一个 TCP 一个 UDP）。"""
    return {
        "type": "hysteria2",
        "tag": "hy2",
        "listen": "::",
        "listen_port": int(port),
        "users": [{"password": password}],
        "up_mbps": up_mbps,
        "down_mbps": down_mbps,
        "tls": {
            "enabled": True,
            "server_name": sni,
            "alpn": ["h3"],
            "certificate_path": cert_path,
            "key_path": key_path,
        },
        "obfs": {"type": "salamander", "password": obfs_password},
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
