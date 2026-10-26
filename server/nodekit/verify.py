"""自测：装完之后，这台到底通不通。

三条检查按顺序短路：端口 → 握手 → 出口（或落地）。
任何一步失败立即返回对应 health，不做后面的事。
"""
import ipaddress
import json
import os
import random
import socket
import subprocess
import time
import urllib.request

CTL_KEY = "/root/.ssh/node_ctl"
BIN = "/opt/sing-box/sing-box"


def tcp_ok(host, port, timeout=6):
    try:
        s = socket.create_connection((str(host), int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def tls_ok(host, port, sni, timeout=8):
    cmd = "echo | timeout %d openssl s_client -connect %s:%s -servername %s 2>&1" % (
        timeout, host, port, sni or host)
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout + 4)
        # 必须真的协商出加密套件：
        #   - 普通 HTTP 只会打印 CONNECTED，没有 Cipher 行
        #   - 握手失败时会打印 Cipher is (NONE)
        out = p.stdout or ""
        return ("Cipher is" in out) and ("Cipher is (NONE)" not in out)
    except Exception:
        return False


def is_ip(s):
    try:
        ipaddress.ip_address(s)
        return True
    except Exception:
        return False


def remote_exit_ip(host, user="root", timeout=10):
    """从节点上取它自己的公网出口 IP。取不到返回空串（不当作失败）。"""
    cmd = [
        "ssh", "-i", CTL_KEY, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=%d" % timeout,
        "%s@%s" % (user, host),
        "curl -s --max-time 8 https://api.ipify.org || curl -s --max-time 8 http://ifconfig.me/ip",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 8)
    except Exception:
        return ""
    out = (p.stdout or "").strip().splitlines()
    if not out:
        return ""
    cand = out[-1].strip()
    return cand if is_ip(cand) else ""


def country_of(ip):
    try:
        url = "http://ip-api.com/json/%s?fields=status,countryCode" % ip
        with urllib.request.urlopen(url, timeout=8) as r:
            d = json.loads(r.read().decode())
        return d.get("countryCode", "") if d.get("status") == "success" else ""
    except Exception:
        return ""


def _client_cfg(node, socks_port):
    return {
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "tag": "in", "listen": "127.0.0.1", "listen_port": socks_port}],
        "outbounds": [{
            "type": "vless", "tag": "out",
            "server": node["host"], "server_port": int(node["port"]), "uuid": node["uuid"],
            "flow": node.get("flow") or "xtls-rprx-vision",
            "tls": {"enabled": True, "server_name": node.get("sni") or node["host"],
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "reality": {"enabled": True, "public_key": node["pbk"], "short_id": node["sid"]}},
        }],
    }


def proxy_exit_ip(node, timeout=15):
    """真的连一次：本机起个 socks，走这条节点出去，看能不能取到出口 IP。
    取到 → 说明这条节点真的能用；取不到 → 说明不能用（不管端口和握手多漂亮）。"""
    port = random.randint(20000, 45000)
    path = "/tmp/px_%d.json" % port
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_client_cfg(node, port), f)
        p = subprocess.Popen([BIN, "run", "-c", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return ""
    try:
        deadline = time.time() + 6
        ready = False
        while time.time() < deadline:
            if tcp_ok("127.0.0.1", port, timeout=1):
                ready = True
                break
            time.sleep(0.3)
        if not ready:
            return ""
        r = subprocess.run(["curl", "-s", "--max-time", str(timeout),
                            "--socks5-hostname", "127.0.0.1:%d" % port,
                            "https://api.ipify.org"], capture_output=True, text=True)
        ip = (r.stdout or "").strip()
        return ip if is_ip(ip) else ""
    except Exception:
        return ""
    finally:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        try:
            os.remove(path)
        except Exception:
            pass


def run(node):
    """返回 {"health": ..., "exit_ip": ..., "exit_country": ..., "detail": ...}"""
    host = node.get("host")
    port = int(node.get("port") or 443)
    sni = node.get("sni") or ""

    if not tcp_ok(host, port):
        return {"health": "port", "detail": "端口连不上"}

    if not tls_ok(host, port, sni):
        return {"health": "tls", "detail": "端口通但握手失败"}

    role = node.get("role") or "exit"

    # 真实代理测试：能取到出口 IP 才算真的能用
    ip = proxy_exit_ip(node)

    if role == "relay":
        if ip:
            cc = country_of(ip)
            return {"health": "ok", "exit_ip": ip, "exit_country": cc,
                    "detail": "中转：经落地出网，出口 %s (%s)" % (ip, cc or "?")}
        landing = node.get("landing") or {}
        if landing.get("host") and tcp_ok(landing["host"], landing.get("port") or 443):
            return {"health": "landing", "detail": "入口和落地都通，但代理连不出去"}
        return {"health": "proxy", "detail": "入口通，但代理连不通"}

    if ip:
        cc = country_of(ip)
        if cc == "CN":
            return {"health": "role_mismatch", "exit_ip": ip, "exit_country": cc,
                    "detail": "出口在中国，这台翻不了墙，应该设为中转"}
        return {"health": "ok", "exit_ip": ip, "exit_country": cc, "detail": "出口 %s (%s)" % (ip, cc or "?")}

    # 代理不通：机器还活着吗？
    if remote_exit_ip(host, node.get("ssh_user") or "root"):
        return {"health": "proxy", "detail": "机器活着，但代理连不通（密钥或路由不对）"}
    return {"health": "blocked", "detail": "代理和 SSH 都不通，可能被墙" }
