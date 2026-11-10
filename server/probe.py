#!/usr/bin/env python3
"""每 60 秒探活一次，写 status.json。

只做两件事：TCP 通不通、TLS 有没有真的握手完成。
配置值不进 shell —— 节点数据是外部输入，拼命令等于给自己开后门。
"""
import base64
import json
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, "/opt/web")
from nodekit import verify as verify_mod  # noqa: E402
from nodekit import logger  # noqa: E402

NODES = os.environ.get("LADDER_DATA", "/opt/web-data") + "/nodes.json"
OUT = os.environ.get("LADDER_DATA", "/opt/web-data") + "/status.json"

REMOTE_PROBE_PY = """
import base64, concurrent.futures, json, socket, subprocess, sys, time
targets = json.loads(base64.b64decode(sys.argv[2]).decode())
vantage_host = sys.argv[3] if len(sys.argv) > 3 else ""
vantage_name = base64.b64decode(sys.argv[4]).decode("utf-8", errors="replace") if len(sys.argv) > 4 else ""

def probe_one(t):
    host, port, sni = t["host"], int(t["port"]), t.get("sni") or t["host"]
    tcp_ms = None
    for _ in range(2):
        t0 = time.time()
        try:
            s = socket.create_connection((str(host), port), timeout=2.5)
            ms = max(1, int((time.time() - t0) * 1000))
            s.close()
            if tcp_ms is None or ms < tcp_ms:
                tcp_ms = ms
            if ms < 400:
                break
        except Exception:
            pass
    if tcp_ms is None:
        return t["name"], {"cn_ok": False, "cn_ms": 0, "cn_reason": "port", "self_probe": bool(host == vantage_host), "vantage": vantage_name}
    ok = False
    for attempt in range(2):
        try:
            p = subprocess.run(["openssl", "s_client", "-connect", "%s:%d" % (host, port), "-servername", sni],
                               input="", capture_output=True, text=True, timeout=5)
            so = p.stdout or ""
            if ("Cipher is" in so) and ("Cipher is (NONE)" not in so):
                ok = True
                break
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.5)
    if not ok:
        return t["name"], {"cn_ok": False, "cn_ms": 0, "cn_reason": "tls", "self_probe": bool(host == vantage_host), "vantage": vantage_name}
    return t["name"], {
        "cn_ok": True,
        "cn_ms": tcp_ms,
        "cn_reason": "",
        "self_probe": bool(host == vantage_host),
        "vantage": vantage_name,
    }

with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(targets))) as ex:
    out = dict(ex.map(probe_one, targets))
print(json.dumps(out))
"""


def cn_probe(nodes, preferred_vantage=None):
    """从国内受控节点网络视角如实测量各节点握手与真实毫秒延迟。支持动态指定探测基准节点。"""
    vantage = None
    if preferred_vantage:
        vantage = next((
            n for n in nodes
            if n.get("source") != "external"
            and n.get("host")
            and (n.get("name") == preferred_vantage or n.get("host") == preferred_vantage)
            and (n.get("role") in ("relay", "standalone") or n.get("region_type") == "cn")
        ), None)

    if not vantage:
        settings_path = os.environ.get("LADDER_DATA", "/opt/web-data") + "/settings.json"
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    cfg_pref = json.load(f).get("probe_vantage")
                    if cfg_pref:
                        vantage = next((
                            n for n in nodes
                            if n.get("source") != "external"
                            and n.get("host")
                            and (n.get("name") == cfg_pref or n.get("host") == cfg_pref)
                            and (n.get("role") in ("relay", "standalone") or n.get("region_type") == "cn")
                        ), None)
            except Exception:
                pass

    if not vantage:
        vantage = next((
            n for n in nodes
            if n.get("source") != "external"
            and n.get("host")
            and (n.get("role") in ("relay", "standalone") or n.get("region_type") == "cn")
        ), None)

    if not vantage:
        return {}
    targets = [
        {"name": n["name"], "host": n["host"], "port": int(n.get("port") or 443), "sni": n.get("sni") or ""}
        for n in nodes if n.get("type") != "hysteria2" and n.get("host")
    ]
    if not targets:
        return {}
    script = base64.b64encode(REMOTE_PROBE_PY.encode("utf-8")).decode("ascii")
    payload = base64.b64encode(json.dumps(targets).encode("utf-8")).decode("ascii")
    vname_b64 = base64.b64encode(str(vantage.get("name") or "").encode("utf-8")).decode("ascii")
    remote = "python3 -c 'import base64,sys;exec(base64.b64decode(sys.argv[1]))' %s %s %s %s" % (
        script, payload, vantage["host"], vname_b64
    )
    cmd = verify_mod.ssh_cmd(
        vantage.get("ssh_user") or "root",
        vantage["host"],
        timeout=6,
        port=vantage.get("ssh_port") or 22,
    ) + [remote]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if p.returncode != 0:
            return {}
        lines = (p.stdout or "").strip().splitlines()
        return json.loads(lines[-1]) if lines else {}
    except Exception:
        return {}


def tcp_ping(host, port, timeout=4):
    best_ms = None
    for _ in range(2):
        t0 = time.time()
        try:
            s = socket.create_connection((str(host), int(port)), timeout=timeout)
            ms = max(1, int((time.time() - t0) * 1000))
            s.close()
            if best_ms is None or ms < best_ms:
                best_ms = ms
            if ms < 400:
                break
        except Exception:
            pass
    if best_ms is not None:
        return True, best_ms
    return False, 0


def tcp_ok(host, port, timeout=4):
    ok, _ = tcp_ping(host, port, timeout=timeout)
    return ok


def tls_ok(host, port, sni):
    """必须真的协商出加密套件；普通 HTTP 端口只会打印 CONNECTED，不能算通。"""
    cmd = ["openssl", "s_client", "-connect", "%s:%s" % (host, int(port)),
           "-servername", sni or host]
    try:
        p = subprocess.run(cmd, input="", capture_output=True, text=True, timeout=12)
    except Exception:
        return False
    out = p.stdout or ""
    return ("Cipher is" in out) and ("Cipher is (NONE)" not in out)


def main():
    nodes = json.load(open(NODES, encoding="utf-8"))
    old_status = {}
    if os.path.exists(OUT):
        try:
            old_status = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass

    out = {}
    for n in nodes:
        # Hysteria2 是 QUIC/UDP，443 端口同时跑着 Reality，
        # 用 TCP+TLS 探活会给出"假绿灯"，所以不做探活，交给客户端实测。
        if n.get("type") == "hysteria2":
            continue
        name = n["name"]
        host, port = n.get("host"), n.get("port")
        ok_tcp, tcp_ms = tcp_ping(host, port)
        if not ok_tcp:
            out[name] = {"ok": False, "ms": 0, "reason": "port"}
        elif not tls_ok(host, port, n.get("sni")):
            out[name] = {"ok": False, "ms": 0, "reason": "tls"}
        else:
            out[name] = {"ok": True, "ms": tcp_ms, "reason": ""}

        # 状态变更记录
        old_n = old_status.get(name) or {}
        if old_n:
            if old_n.get("ok") is True and out[name]["ok"] is False:
                logger.log("ERROR", "PROBE", f"节点 [{name}] 变为不通 (原因={out[name]['reason']})")
            elif old_n.get("ok") is False and out[name]["ok"] is True:
                logger.log("SUCCESS", "PROBE", f"节点 [{name}] 恢复通畅 (延迟={out[name]['ms']}ms)")

    cn = cn_probe(nodes)
    for name, cinfo in cn.items():
        if name in out and isinstance(cinfo, dict):
            out[name].update(cinfo)
            old_n = old_status.get(name) or {}
            if old_n:
                if old_n.get("cn_ok") is True and cinfo.get("cn_ok") is False:
                    logger.log("WARN", "PROBE", f"节点 [{name}] 国内握手失败 · 疑似被墙")
                elif old_n.get("cn_ok") is False and cinfo.get("cn_ok") is True:
                    logger.log("SUCCESS", "PROBE", f"节点 [{name}] 国内连接已恢复 ({cinfo.get('cn_ms', 0)}ms)")

    out["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)
    try:
        import alert
        alert.check_and_notify(out)
    except Exception:
        pass
    try:
        logger.rotate_if_needed()
    except Exception:
        pass


if __name__ == "__main__":
    main()
