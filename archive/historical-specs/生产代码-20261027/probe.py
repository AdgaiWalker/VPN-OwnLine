#!/usr/bin/env python3
"""每 60 秒探活一次，写 status.json。

只做两件事：TCP 通不通、TLS 有没有真的握手完成。
配置值不进 shell —— 节点数据是外部输入，拼命令等于给自己开后门。
"""
import json
import os
import socket
import subprocess
import time

NODES = "/opt/web/nodes.json"
OUT = "/opt/web/status.json"


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
    out["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
