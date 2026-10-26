"""自测：装完之后，这台到底通不通。

三条检查按顺序短路：端口 → 握手 → 出口（或落地）。
任何一步失败立即返回对应 health，不做后面的事。
"""
import ipaddress
import json
import socket
import subprocess
import urllib.request

CTL_KEY = "/root/.ssh/node_ctl"


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

    if role == "relay":
        landing = node.get("landing") or {}
        if landing.get("host"):
            if tcp_ok(landing["host"], landing.get("port") or 443):
                return {"health": "ok", "detail": "中转：入口与落地都可达"}
            return {"health": "landing", "detail": "入口通，但连不上落地"}
        return {"health": "ok", "detail": "中转：入口可达（未配置落地检查）"}

    ip = remote_exit_ip(host, node.get("ssh_user") or "root")
    if not ip:
        return {"health": "ok", "detail": "入口通，但取不到出口 IP"}

    cc = country_of(ip)
    if cc == "CN":
        return {"health": "role_mismatch", "exit_ip": ip, "exit_country": cc,
                "detail": "出口在中国，这台翻不了墙，应该设为中转"}

    return {"health": "ok", "exit_ip": ip, "exit_country": cc, "detail": "出口 %s (%s)" % (ip, cc or "?")}
