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

NODES = os.environ.get("LADDER_DATA", "/opt/web-data") + "/nodes.json"
OUT = os.environ.get("LADDER_DATA", "/opt/web-data") + "/status.json"

REMOTE_PROBE_PY = """
import base64, json, socket, subprocess, sys, time
targets = json.loads(base64.b64decode(sys.argv[2]).decode())
out = {}
for t in targets:
    t0 = time.time()
    host, port, sni = t["host"], int(t["port"]), t.get("sni") or t["host"]
    try:
        s = socket.create_connection((str(host), port), timeout=4)
        s.close()
    except Exception:
        out[t["name"]] = {"cn_ok": False, "cn_ms": 0, "cn_reason": "port"}
        continue
    try:
        p = subprocess.run(["openssl", "s_client", "-connect", "%s:%d" % (host, port), "-servername", sni],
                           input="", capture_output=True, text=True, timeout=10)
        so = p.stdout or ""
        ok = ("Cipher is" in so) and ("Cipher is (NONE)" not in so)
    except Exception:
        ok = False
    if not ok:
        out[t["name"]] = {"cn_ok": False, "cn_ms": 0, "cn_reason": "tls"}
    else:
        out[t["name"]] = {"cn_ok": True, "cn_ms": int((time.time() - t0) * 1000), "cn_reason": ""}
print(json.dumps(out))
"""


def cn_probe(nodes):
    """借第一台国内中转机（role=relay），从国内视角对所有 TCP 节点做一次握手探活。"""
    vantage = next((n for n in nodes if n.get("role") == "relay" and n.get("ssh_user") and n.get("host")), None)
    if not vantage:
        return {}
    targets = [
        {"name": n["name"], "host": n["host"], "port": int(n.get("port") or 443), "sni": n.get("sni") or ""}
        for n in nodes if n.get("type") != "hysteria2" and n.get("host")
    ]
    if not targets:
        return {}
    script = base64.b64encode(REMOTE_PROBE_PY.encode()).decode()
    payload = base64.b64encode(json.dumps(targets).encode()).decode()
    remote = "python3 -c 'import base64,sys;exec(base64.b64decode(sys.argv[1]))' %s %s" % (script, payload)
    cmd = verify_mod.ssh_cmd(vantage["ssh_user"], vantage["host"], timeout=6) + [remote]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if p.returncode != 0:
            return {}
        lines = (p.stdout or "").strip().splitlines()
        return json.loads(lines[-1]) if lines else {}
    except Exception:
        return {}


def tcp_ok(host, port, timeout=4):
    try:
        s = socket.create_connection((str(host), int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


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
    out = {}
    for n in nodes:
        # Hysteria2 是 QUIC/UDP，443 端口同时跑着 Reality，
        # 用 TCP+TLS 探活会给出"假绿灯"，所以不做探活，交给客户端实测。
        if n.get("type") == "hysteria2":
            continue
        t0 = time.time()
        host, port = n.get("host"), n.get("port")
        if not tcp_ok(host, port):
            out[n["name"]] = {"ok": False, "ms": 0, "reason": "port"}
            continue
        if not tls_ok(host, port, n.get("sni")):
            out[n["name"]] = {"ok": False, "ms": 0, "reason": "tls"}
            continue
        out[n["name"]] = {"ok": True, "ms": int((time.time() - t0) * 1000), "reason": ""}

    cn = cn_probe(nodes)
    for name, cinfo in cn.items():
        if name in out and isinstance(cinfo, dict):
            out[name].update(cinfo)

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


if __name__ == "__main__":
    main()
