"""自测：装完之后，这台到底通不通。

三条检查按顺序短路：端口 → 握手 → 出口（或落地）。
任何一步失败立即返回对应 health，不做后面的事。
"""
import ipaddress
import json
import os
import random
import re
import socket
import subprocess
import tempfile
import time
import urllib.request

CTL_KEY = "/root/.ssh/node_ctl"
KNOWN_HOSTS = "/opt/sing-box/known_hosts"
BIN = "/opt/sing-box/sing-box"


def ssh_cmd(user, host, timeout=10, port=22):
    """统一的受控节点 SSH 命令前缀：首次记住指纹（TOFU），后续严格比对。"""
    cmd = ["ssh"]
    ssh_port = int(port or 22)
    if ssh_port != 22:
        cmd += ["-p", str(ssh_port)]
    cmd += [
        "-i", CTL_KEY, "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=" + KNOWN_HOSTS,
        "-o", "ConnectTimeout=%d" % int(timeout),
        "%s@%s" % (user or "root", host),
    ]
    return cmd


def tcp_ok(host, port, timeout=6, retries=4, retry_interval=0.25):
    """统一的 TCP 端口探测，支持服务重启中的快速重试（避免进程刚启动时误判失败）。"""
    start_time = time.time()
    for attempt in range(max(1, retries)):
        try:
            rem = max(0.5, timeout - (time.time() - start_time))
            s = socket.create_connection((str(host), int(port)), timeout=min(rem, 2.0))
            s.close()
            return True
        except Exception:
            if attempt < retries - 1:
                time.sleep(retry_interval)
    return False


def tls_ok(host, port, sni, timeout=8):
    # 参数用列表传，不拼 shell：host / sni 来自节点数据（可能是粘贴来的外部输入）。
    cmd = ["openssl", "s_client", "-connect", "%s:%s" % (host, int(port)),
           "-servername", sni or host]
    try:
        p = subprocess.run(cmd, input="", capture_output=True, text=True, timeout=timeout + 4)
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


def remote_exit_ip(host, user="root", timeout=10, port=22):
    """从节点上取它自己的公网出口 IP。取不到返回空串（不当作失败）。"""
    cmd = ssh_cmd(user, host, timeout=timeout, port=port) + [
        "curl -s --max-time 8 https://api.ipify.org || curl -s --max-time 8 https://ifconfig.me/ip",
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
    """通过 HTTPS 查询出口 IP 所属国家代码（2 位大写字母，失败返回空串）。"""
    if not is_ip(ip):
        return ""
    headers = {"User-Agent": "curl/8.0"}
    try:
        req = urllib.request.Request("https://ipwho.is/%s" % ip, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
        cc = str(d.get("country_code") or "").strip().upper()
        if d.get("success") is not False and re.fullmatch(r"[A-Z]{2}", cc):
            return cc
    except Exception:
        pass
    try:
        req = urllib.request.Request("https://ipinfo.io/%s/country" % ip, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as r:
            cc = r.read().decode("utf-8", errors="replace").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", cc):
            return cc
    except Exception:
        pass
    return ""


def _client_cfg(node, socks_port):
    if node.get("type") == "hysteria2":
        ob = {
            "type": "hysteria2", "tag": "out",
            "server": node["host"], "server_port": int(node.get("port") or 443),
            "password": node["password"],
            "tls": {"enabled": True, "server_name": node.get("sni") or node["host"],
                    "alpn": ["h3"], "insecure": True},
        }
        if node.get("obfs_password"):
            ob["obfs"] = {"type": "salamander", "password": node["obfs_password"]}
    else:
        ob = {
            "type": "vless", "tag": "out",
            "server": node["host"], "server_port": int(node["port"]), "uuid": node["uuid"],
            "flow": node.get("flow") or "xtls-rprx-vision",
            "tls": {"enabled": True, "server_name": node.get("sni") or node["host"],
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "reality": {"enabled": True, "public_key": node["pbk"], "short_id": node["sid"]}},
        }
    return {
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "tag": "in", "listen": "127.0.0.1", "listen_port": socks_port}],
        "outbounds": [ob],
    }


def proxy_exit_ip(node, timeout=8):
    """真的连一次：本机起个 socks，走这条节点出去，看能不能取到出口 IP。
    取到 → 说明这条节点真的能用；取不到 → 说明不能用（不管端口和握手多漂亮）。"""
    port = random.randint(20000, 45000)
    fd, path = tempfile.mkstemp(prefix="ownline-px-", suffix=".json")
    p = None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_client_cfg(node, port), f)
        p = subprocess.Popen([BIN, "run", "-c", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        if p is not None:
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
    is_hy2 = (node.get("type") == "hysteria2")

    # Hysteria2 走 QUIC/UDP，不能拿 TCP+TLS 探活去短路（否则要么误判死，要么被同端口 Reality 假绿灯骗过）
    if not is_hy2:
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
                    "detail": "出口还在国内，这条帮不上你"}
        return {"health": "ok", "exit_ip": ip, "exit_country": cc, "detail": "出口 %s (%s)" % (ip, cc or "?")}

    # 代理不通：机器还活着吗？
    if is_hy2 and tcp_ok(host, port):
        return {"health": "proxy", "detail": "机器活着，但 Hysteria2 连不通（UDP 端口未放行或密码不对）"}
    if remote_exit_ip(host, node.get("ssh_user") or "root", port=node.get("ssh_port") or 22):
        return {"health": "proxy", "detail": "机器活着，但代理连不通（密钥或路由不对）"}
    return {"health": "blocked", "detail": "代理和 SSH 都不通，可能被墙" }
