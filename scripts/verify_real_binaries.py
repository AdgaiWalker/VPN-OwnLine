#!/usr/bin/env python3
"""Real-binary contract and chaos verification suite (Docker --network none).

Runs inside the isolated ownline-phase4-lab container against real pinned
sing-box (1.14.4), caddy (2.10.2), mihomo (v1.19.34), iptables, tc netem,
and tcpdump with zero external internet access.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]

_CONTAINER_SCRIPT = r'''
import base64
import concurrent.futures
import http.client
import http.server
import ipaddress
import json
import os
from pathlib import Path
import random
import select
import shutil
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

os.makedirs("/opt/web", exist_ok=True)
os.makedirs("/opt/web-data", exist_ok=True)
os.makedirs("/opt/sing-box", exist_ok=True)
os.makedirs("/var/log", exist_ok=True)
os.makedirs("/etc/caddy", exist_ok=True)
os.makedirs("/var/lib/ownline", exist_ok=True)
os.chmod("/opt/web-data", 0o700)

with open("/tmp/ownline-src.tgz", "rb") as f:
    import tarfile
    with tarfile.open(fileobj=f, mode="r:gz") as tf:
        tf.extractall("/opt/web")

sys.path.insert(0, "/opt/web")
from nodekit import provenance, reconcile, remote_config, repair, subscriptions, templates, verify  # noqa: E402


def run_cmd(cmd, *, check=True, timeout=20, input_text=None):
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True, check=check, timeout=timeout)


def setup_loopback_addrs():
    for addr in ("10.201.0.1/32", "10.201.0.2/32", "10.201.0.10/32", "10.202.0.2/32", "10.203.0.2/32", "10.204.0.2/32", "1.1.1.1/32"):
        subprocess.run(["ip", "addr", "add", addr, "dev", "lo"], capture_output=True, text=True, check=False)
    hosts_path = Path("/etc/hosts")
    hosts = hosts_path.read_text()
    if "camouflage.local" not in hosts:
        hosts_path.write_text(hosts + "\n10.201.0.10 camouflage.local\n")


def wait_https(sni_host, connect_ip, port, timeout=8.0):
    ctx = ssl._create_unverified_context()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = http.client.HTTPSConnection(sni_host, port, context=ctx, timeout=1.0)
            conn._create_connection = lambda address, timeout=None, *a: socket.create_connection((connect_ip, port), timeout)
            conn.request("GET", "/", headers={"Host": sni_host})
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status == 200:
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"HTTPS listener {sni_host} ({connect_ip}:{port}) not ready in {timeout}s")


def gen_reality_pair():
    out = run_cmd(["/usr/local/bin/sing-box", "generate", "reality-keypair"]).stdout
    priv = pub = ""
    for line in out.splitlines():
        if line.startswith("PrivateKey:"):
            priv = line.split(":", 1)[1].strip()
        elif line.startswith("PublicKey:"):
            pub = line.split(":", 1)[1].strip()
    assert priv and pub, out
    return priv, pub


def free_port(host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def wait_tcp(host, port, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"TCP listener {host}:{port} not ready in {timeout}s")


def start_proc(cmd, log_path):
    lf = open(log_path, "w", encoding="utf-8")
    p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
    return p, lf


def stop_proc(proc_tuple):
    if not proc_tuple:
        return
    p, lf = proc_tuple
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=2)
    lf.close()


class _EchoServer:
    def __init__(self, bind_ip="10.203.0.2", port=18080):
        self.bind_ip = bind_ip
        self.port = port
        self.hits = 0
        self.udp_hits = 0
        self.lock = threading.Lock()
        self._httpd = None
        self._udp_sock = None
        self._stop = threading.Event()

    def start(self):
        parent = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with parent.lock:
                    parent.hits += 1
                parsed = urllib.parse.urlparse(self.path)
                peer = self.client_address[0]
                if parsed.path == "/ip":
                    body = peer.encode("utf-8")
                    ctype = "text/plain"
                else:
                    qs = urllib.parse.parse_qs(parsed.query)
                    nonce = (qs.get("nonce") or [""])[0]
                    body = json.dumps({"nonce": nonce, "peer_ip": peer}).encode("utf-8")
                    ctype = "application/json"
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def log_message(self, *args):
                return

        class ReuseHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._httpd = ReuseHTTPServer((self.bind_ip, self.port), Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_sock.bind((self.bind_ip, 19999))
        self._udp_sock.settimeout(0.2)

        def udp_loop():
            while not parent._stop.is_set():
                try:
                    data, addr = self._udp_sock.recvfrom(4096)
                    with parent.lock:
                        parent.udp_hits += 1
                    self._udp_sock.sendto(b"UDP:" + data, addr)
                except socket.timeout:
                    continue
                except OSError:
                    break

        threading.Thread(target=udp_loop, daemon=True).start()

    def reset_counts(self):
        with self.lock:
            self.hits = 0
            self.udp_hits = 0

    def stop(self):
        self._stop.set()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._udp_sock:
            self._udp_sock.close()


class _MockWebshareProxy:
    def __init__(self, listen_ip="10.202.0.2", socks_port=11080, http_port=13128, egress_ip="10.204.0.2", user="wuser", password="wpass"):
        self.listen_ip = listen_ip
        self.socks_port = socks_port
        self.http_port = http_port
        self.egress_ip = egress_ip
        self.user = user
        self.password = password
        self.socks_tcp_count = 0
        self.http_connect_count = 0
        self.udp_associate_count = 0
        self.lock = threading.Lock()
        self._socks_srv = None
        self._http_srv = None

    def _dial_bound(self, host, port):
        up = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        up.settimeout(6)
        up.bind((self.egress_ip, 0))
        up.connect((host, port))
        return up

    def _relay(self, a, b):
        try:
            while True:
                r, _, _ = select.select([a, b], [], [], 8)
                if not r:
                    break
                for src in r:
                    dst = b if src is a else a
                    chunk = src.recv(16384)
                    if not chunk:
                        return
                    dst.sendall(chunk)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass

    def start(self):
        parent = self

        class SocksHandler(socketserver.BaseRequestHandler):
            def handle(self):
                conn = self.request
                conn.settimeout(6)
                hdr = conn.recv(2)
                if len(hdr) < 2 or hdr[0] != 5:
                    return
                methods = conn.recv(hdr[1])
                if 2 in methods:
                    conn.sendall(b"\x05\x02")
                    ver = conn.recv(1)
                    if not ver:
                        return
                    ulen = conn.recv(1)[0]
                    u = conn.recv(ulen).decode("utf-8", errors="replace")
                    plen = conn.recv(1)[0]
                    p = conn.recv(plen).decode("utf-8", errors="replace")
                    if u != parent.user or p != parent.password:
                        conn.sendall(b"\x01\x01")
                        return
                    conn.sendall(b"\x01\x00")
                elif 0 in methods:
                    conn.sendall(b"\x05\x00")
                else:
                    conn.sendall(b"\x05\xff")
                    return
                req = conn.recv(4)
                if len(req) < 4:
                    return
                _, cmd, _, atyp = req
                if atyp == 1:
                    dst_host = socket.inet_ntoa(conn.recv(4))
                elif atyp == 3:
                    dlen = conn.recv(1)[0]
                    dst_host = conn.recv(dlen).decode("utf-8", errors="replace")
                elif atyp == 4:
                    dst_host = socket.inet_ntop(socket.AF_INET6, conn.recv(16))
                else:
                    conn.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                    return
                dst_port = struct.unpack("!H", conn.recv(2))[0]
                if cmd == 3:
                    with parent.lock:
                        parent.udp_associate_count += 1
                    conn.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                    return
                if cmd != 1:
                    conn.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                    return
                try:
                    up = parent._dial_bound(dst_host, dst_port)
                except OSError:
                    conn.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
                    return
                with parent.lock:
                    parent.socks_tcp_count += 1
                conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                parent._relay(conn, up)

        class HttpProxyHandler(socketserver.BaseRequestHandler):
            def handle(self):
                conn = self.request
                conn.settimeout(6)
                buf = b""
                while b"\r\n\r\n" not in buf and len(buf) < 16384:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buf += chunk
                head, _, rest = buf.partition(b"\r\n\r\n")
                lines = head.decode("latin1").split("\r\n")
                first = lines[0].split()
                if len(first) < 3:
                    return
                method, target = first[0].upper(), first[1]
                expected = "Basic " + base64.b64encode(f"{parent.user}:{parent.password}".encode()).decode()
                auth_ok = any(ln.lower().startswith("proxy-authorization:") and ln.split(":", 1)[1].strip() == expected for ln in lines[1:])
                if not auth_ok:
                    conn.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
                    return
                if method == "CONNECT":
                    h, _, pt = target.rpartition(":")
                    dst_host, dst_port = h.strip("[]"), int(pt)
                    try:
                        up = parent._dial_bound(dst_host, dst_port)
                    except OSError:
                        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        return
                    with parent.lock:
                        parent.http_connect_count += 1
                    conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    if rest:
                        up.sendall(rest)
                    parent._relay(conn, up)
                else:
                    u = urllib.parse.urlparse(target)
                    dst_host = u.hostname
                    dst_port = u.port or 80
                    path_q = u.path or "/"
                    if u.query:
                        path_q += "?" + u.query
                    try:
                        up = parent._dial_bound(dst_host, dst_port)
                    except OSError:
                        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        return
                    with parent.lock:
                        parent.http_connect_count += 1
                    req_bytes = f"{method} {path_q} HTTP/1.1\r\nHost: {dst_host}:{dst_port}\r\nConnection: close\r\n\r\n".encode()
                    up.sendall(req_bytes + rest)
                    parent._relay(conn, up)

        class TSrv(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._socks_srv = TSrv((self.listen_ip, self.socks_port), SocksHandler)
        self._http_srv = TSrv((self.listen_ip, self.http_port), HttpProxyHandler)
        threading.Thread(target=self._socks_srv.serve_forever, daemon=True).start()
        threading.Thread(target=self._http_srv.serve_forever, daemon=True).start()

    def stop(self):
        for s in (self._socks_srv, self._http_srv):
            if s:
                s.shutdown()
                s.server_close()


def socks5_get(proxy_host, proxy_port, url, timeout=5.0):
    r = subprocess.run(
        ["curl", "-fsS", "--max-time", str(timeout), "--socks5-hostname", f"{proxy_host}:{proxy_port}", url],
        capture_output=True, text=True, check=False,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def socks5_try_udp_associate(proxy_host, proxy_port, target_ip="10.203.0.2", target_port=19999):
    tcp = socket.create_connection((proxy_host, proxy_port), timeout=4)
    tcp.settimeout(4)
    try:
        tcp.sendall(b"\x05\x01\x00")
        assert tcp.recv(2) == b"\x05\x00"
        tcp.sendall(b"\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00")
        resp = tcp.recv(10)
        if len(resp) < 4 or resp[1] != 0:
            return "rejected_handshake"
        bnd_port = struct.unpack("!H", resp[8:10])[0]
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(1.0)
        try:
            pkt = b"\x00\x00\x00\x01" + socket.inet_aton(target_ip) + struct.pack("!H", target_port) + b"ping"
            udp.sendto(pkt, (proxy_host, bnd_port or proxy_port))
            try:
                reply, _ = udp.recvfrom(2048)
                return f"unexpected_reply:{reply!r}"
            except socket.timeout:
                return "dropped_or_rejected"
        finally:
            udp.close()
    finally:
        tcp.close()


def run_suite_1_singbox_and_reconcile(priv1, pub1, priv2, pub2):
    cert, key = remote_config.generate_self_signed_cert_pem("camouflage.local")
    Path("/opt/sing-box/hy2.crt").write_text(cert)
    Path("/opt/sing-box/hy2.key").write_text(key)
    hy2_cfg = {"port": 10443, "password": "hy2-pw-1", "obfs_password": "obfs-pw-1", "sni": "camouflage.local"}
    warp_wg = {"server": "10.201.0.99", "server_port": 2408, "private_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "local_address": ["172.16.0.2/32"]}
    warp_socks = {"type": "socks", "server": "127.0.0.1", "server_port": 40000}
    isp_socks_noudp = {"type": "socks", "server": "10.202.0.2", "server_port": 11080, "username": "wuser", "password": "wpass"}
    isp_socks_udp = {"type": "socks", "server": "10.202.0.2", "server_port": 11080, "username": "wuser", "password": "wpass", "udp": True}
    isp_http = {"type": "http", "server": "10.202.0.2", "server_port": 13128, "username": "wuser", "password": "wpass"}
    landing1 = {"host": "10.201.0.1", "port": 10443, "uuid": "11111111-1111-4111-8111-111111111111", "pbk": pub1, "sid": "abcd1234", "sni": "camouflage.local"}
    landing2 = {"host": "10.201.0.3", "port": 10443, "uuid": "22222222-2222-4222-8222-222222222222", "pbk": pub1, "sid": "abcd5678", "sni": "camouflage.local"}

    cases = [
        ("exit_direct", templates.exit_config(10443, landing1["uuid"], "camouflage.local", priv1, "abcd1234"),
         {"name": "n", "role": "exit", "port": 10443, "uuid": landing1["uuid"], "sni": "camouflage.local", "sid": "abcd1234"}, None),
        ("exit_direct_hy2", templates.exit_config(10443, landing1["uuid"], "camouflage.local", priv1, "abcd1234", hy2=hy2_cfg),
         {"name": "n", "role": "exit", "port": 10443, "uuid": landing1["uuid"], "sni": "camouflage.local", "sid": "abcd1234", "hy2_enabled": True},
         {"type": "hysteria2", "port": 10443, "password": "hy2-pw-1", "obfs_password": "obfs-pw-1", "sni": "camouflage.local"}),
        ("exit_warp_wg_hy2", templates.exit_config(10443, landing1["uuid"], "camouflage.local", priv1, "abcd1234", hy2=hy2_cfg, warp=warp_wg),
         {"name": "n", "role": "exit", "port": 10443, "uuid": landing1["uuid"], "sni": "camouflage.local", "sid": "abcd1234", "hy2_enabled": True, "warp_enabled": True, "warp": warp_wg},
         {"type": "hysteria2", "port": 10443, "password": "hy2-pw-1", "obfs_password": "obfs-pw-1", "sni": "camouflage.local"}),
        ("exit_warp_socks", templates.exit_config(10443, landing1["uuid"], "camouflage.local", priv1, "abcd1234", warp=warp_socks),
         {"name": "n", "role": "exit", "port": 10443, "uuid": landing1["uuid"], "sni": "camouflage.local", "sid": "abcd1234", "warp_enabled": True, "warp": warp_socks}, None),
        ("exit_isp_socks_noudp", templates.exit_config(10443, landing1["uuid"], "camouflage.local", priv1, "abcd1234", hy2=hy2_cfg, isp=isp_socks_noudp),
         {"name": "n", "role": "exit", "port": 10443, "uuid": landing1["uuid"], "sni": "camouflage.local", "sid": "abcd1234", "hy2_enabled": True, "isp": isp_socks_noudp},
         {"type": "hysteria2", "port": 10443, "password": "hy2-pw-1", "obfs_password": "obfs-pw-1", "sni": "camouflage.local"}),
        ("exit_isp_socks_udp", templates.exit_config(10443, landing1["uuid"], "camouflage.local", priv1, "abcd1234", isp=isp_socks_udp),
         {"name": "n", "role": "exit", "port": 10443, "uuid": landing1["uuid"], "sni": "camouflage.local", "sid": "abcd1234", "isp": isp_socks_udp}, None),
        ("exit_isp_http", templates.exit_config(10443, landing1["uuid"], "camouflage.local", priv1, "abcd1234", isp=isp_http),
         {"name": "n", "role": "exit", "port": 10443, "uuid": landing1["uuid"], "sni": "camouflage.local", "sid": "abcd1234", "isp": isp_http}, None),
        ("relay_single", templates.relay_config(10444, "33333333-3333-4333-8333-333333333333", "camouflage.local", priv2, "ef123456", landing1),
         {"name": "r", "role": "relay", "port": 10444, "uuid": "33333333-3333-4333-8333-333333333333", "sni": "camouflage.local", "sid": "ef123456", "landing": landing1}, None),
        ("relay_dual", templates.relay_config(10444, "33333333-3333-4333-8333-333333333333", "camouflage.local", priv2, "ef123456", landing1, fallback_landing=landing2),
         {"name": "r2", "role": "relay", "port": 10444, "uuid": "33333333-3333-4333-8333-333333333333", "sni": "camouflage.local", "sid": "ef123456", "landing": landing1, "fallback_landing": landing2}, None),
    ]

    with tempfile.TemporaryDirectory() as td:
        for label, cfg, node, hy2_node in cases:
            p = Path(td) / f"{label}.json"
            p.write_text(json.dumps(cfg))
            chk = run_cmd(["/usr/local/bin/sing-box", "check", "-c", str(p)], check=False)
            assert chk.returncode == 0, f"{label} sing-box check failed: {chk.stderr} {chk.stdout}"
            if label != "relay_dual":
                params = remote_config.extract_live_params(cfg, fallback_node=node)
                desired = reconcile.build_desired_config(node, params, hy2_node=hy2_node)
                diffs = reconcile.diff_configs(cfg, desired, redact=True)
                assert not diffs, f"{label} reconcile diff non-empty: {diffs}"

    return {"ok": True, "checked_configs": len(cases)}


def run_suite_2_caddy_stealth_and_admin():
    Path("/opt/web/index.html").write_text("<html>OwnLine-Phase4</html>")
    Path("/opt/web-data/nodes.json").write_text(json.dumps([
        {"name": "test-exit", "health": "ok", "role": "exit", "source": "external", "host": "198.51.100.1", "port": 443,
         "uuid": "11111111-1111-4111-8111-111111111111", "pbk": "PUB", "sid": "abcd1234", "sni": "camouflage.local"}
    ]))
    Path("/opt/web-data/settings.json").write_text(json.dumps({"sub_token": "phase4token123456"}))
    Path("/opt/web-data/status.json").write_text("{}")

    script = Path("/opt/web/install.sh").read_text()
    template = script.split('cat > "$CADDY_STAGED" << CADDYEOF\n', 1)[1].split("\nCADDYEOF", 1)[0]
    pw_hash = run_cmd(["/usr/local/bin/caddy", "hash-password"], input_text="phase4-secret\n").stdout.strip()
    caddy_cfg = template.replace("$SETUP_JOB", "phase4").replace("$PASS_HASH", pw_hash).replace("${DOMAIN}", "localhost").replace("$TLS_DIRECTIVE", "tls internal") + "\n"
    Path("/etc/caddy/Caddyfile").write_text(caddy_cfg)
    val = run_cmd(["/usr/local/bin/caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"], check=False)
    assert val.returncode == 0, val.stderr

    admin_proc = start_proc(["python3", "/opt/web/admin.py"], "/tmp/suite2-admin.log")
    caddy_proc = None
    try:
        wait_tcp("127.0.0.1", 8099, timeout=8)
        caddy_home = Path("/tmp/suite2-caddy-home")
        caddy_home.mkdir(exist_ok=True)
        env = dict(os.environ, HOME=str(caddy_home))
        lf = open("/tmp/suite2-caddy.log", "w", encoding="utf-8")
        p_cad = subprocess.Popen(["/usr/local/bin/caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"], stdout=lf, stderr=subprocess.STDOUT, env=env)
        caddy_proc = (p_cad, lf)
        wait_tcp("127.0.0.1", 8443, timeout=8)

        port80_refused = False
        try:
            with socket.create_connection(("127.0.0.1", 80), timeout=0.6):
                port80_refused = False
        except OSError:
            port80_refused = True
        assert port80_refused, "Port 80 unexpectedly open under stealth Caddyfile"

        ctx = ssl._create_unverified_context()

        def https_call(path, auth=False):
            conn = http.client.HTTPSConnection("localhost", 8443, context=ctx, timeout=5)
            conn._create_connection = lambda address, timeout=None, *a: socket.create_connection(("127.0.0.1", 8443), timeout)
            headers = {"Host": "localhost:8443"}
            if auth:
                headers["Authorization"] = "Basic " + base64.b64encode(b"admin:phase4-secret").decode()
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            body = resp.read().decode("utf-8", errors="replace")
            conn.close()
            return resp.status, hdrs, body

        st, hdrs, _ = https_call("/", auth=False)
        assert st == 401, st
        assert "server" not in hdrs, hdrs
        assert hdrs.get("x-content-type-options") == "nosniff", hdrs
        assert hdrs.get("x-frame-options") == "DENY", hdrs
        assert hdrs.get("referrer-policy") == "no-referrer", hdrs
        assert https_call("/sub", auth=False)[0] == 404
        assert https_call("/s/phase4token123456", auth=False)[0] == 200
        st_rec, _, body_rec = https_call("/api/reconcile/status", auth=True)
        assert st_rec == 200 and json.loads(body_rec).get("unmanaged_count") == 1, (st_rec, body_rec)
        st_nodes, _, body_nodes = https_call("/api/nodes", auth=True)
        assert st_nodes == 200 and json.loads(body_nodes)[0]["capability"]["mode"] == "external"
        return {"ok": True, "port80_closed": port80_refused, "server_header_stripped": True}
    finally:
        stop_proc(caddy_proc)
        stop_proc(admin_proc)


def run_suite_3_mihomo_profiles(pub1):
    nodes = [
        {"name": "sv-exit", "host": "10.201.0.1", "port": 10443, "uuid": "11111111-1111-4111-8111-111111111111", "pbk": pub1, "sid": "abcd1234",
         "sni": "camouflage.local", "role": "exit", "health": "ok", "isp": {"type": "socks", "server": "10.202.0.2", "server_port": 11080}},
        {"name": "sv-exit-HY2", "type": "hysteria2", "host": "10.201.0.1", "port": 10443, "password": "hy2-pw-1", "obfs_password": "obfs-pw-1",
         "sni": "camouflage.local", "role": "exit", "health": "ok"},
        {"name": "bj-relay", "host": "10.201.0.2", "port": 10444, "uuid": "33333333-3333-4333-8333-333333333333", "pbk": pub1, "sid": "ef123456",
         "sni": "camouflage.local", "role": "relay", "health": "ok"},
    ]
    with tempfile.TemporaryDirectory() as td:
        shutil.copy("/etc/mihomo/geoip.metadb", os.path.join(td, "geoip.metadb"))
        profiles = ("all", "pro", "office", "lite", "direct")
        for prof in profiles:
            yaml_text = subscriptions.render_clash_yaml(nodes, profile=prof)
            yp = Path(td) / f"{prof}.yaml"
            yp.write_text(yaml_text)
            chk = run_cmd(["/usr/local/bin/mihomo", "-t", "-d", td, "-f", str(yp)], check=False)
            assert chk.returncode == 0, f"mihomo -t failed for profile={prof}:\n{chk.stdout}\n{chk.stderr}"
    return {"ok": True, "validated_profiles": list(profiles)}


def make_single_mihomo_yaml(node, mixed_port, pub1, external_controller=None):
    # Render using real subscriptions.render_clash_yaml directly
    text = subscriptions.render_clash_yaml([node] if isinstance(node, dict) else node, profile="lite" if isinstance(node, dict) else "office")
    text = text.replace("mixed-port: 7890", f"mixed-port: {mixed_port}", 1)
    text = text.replace("http://www.gstatic.com/generate_204", "http://10.203.0.2:18080/ip")
    if external_controller:
        text = text.replace("ipv6: false", f"ipv6: false\nexternal-controller: {external_controller}", 1)
        text = text.replace("interval: 120", "interval: 1")
    return text


class _LocalDohServer:
    def __init__(self, bind_ip="1.1.1.1", port=443):
        self.bind_ip = bind_ip
        self.port = port
        self._srv = None
        self.queries = 0

    @staticmethod
    def _parse_qname(pkt, off=12):
        labels = []
        while off < len(pkt):
            ln = pkt[off]
            off += 1
            if ln == 0:
                break
            labels.append(pkt[off:off + ln].decode("ascii", "replace"))
            off += ln
        qtype, _ = struct.unpack("!HH", pkt[off:off + 4])
        return ".".join(labels), qtype, off + 4

    def _dns_reply(self, query_bytes):
        if len(query_bytes) < 16:
            return b""
        txid = struct.unpack("!H", query_bytes[:2])[0]
        qname, qtype, qend = self._parse_qname(query_bytes)
        question = query_bytes[12:qend]
        records = {"camouflage.local": "10.201.0.10"}
        if qtype == 1 and qname in records:
            ip_bytes = socket.inet_aton(records[qname])
            ans = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x02\x58\x00\x04" + ip_bytes
            return struct.pack("!HHHHHH", txid, 0x8180, 1, 1, 0, 0) + question + ans
        return struct.pack("!HHHHHH", txid, 0x8180, 1, 0, 0, 0) + question

    def start(self):
        run_cmd([
            "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
            "-keyout", "/tmp/p4-doh.key", "-out", "/tmp/p4-doh.crt",
            "-days", "1", "-subj", "/CN=1.1.1.1",
            "-addext", "subjectAltName=IP:1.1.1.1",
        ])
        os.makedirs("/usr/local/share/ca-certificates", exist_ok=True)
        shutil.copy("/tmp/p4-doh.crt", "/usr/local/share/ca-certificates/p4-doh.crt")
        run_cmd(["update-ca-certificates"])

        parent = self

        class DohHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                parent.queries += 1
                resp = parent._dns_reply(body)
                self.send_response(200 if resp else 400)
                self.send_header("Content-Type", "application/dns-message")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                dns_b64 = (urllib.parse.parse_qs(parsed.query).get("dns") or [""])[0]
                pad = "=" * ((4 - len(dns_b64) % 4) % 4)
                raw = base64.urlsafe_b64decode(dns_b64 + pad) if dns_b64 else b""
                parent.queries += 1
                resp = parent._dns_reply(raw)
                self.send_response(200 if resp else 400)
                self.send_header("Content-Type", "application/dns-message")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *args):
                return

        class DohSrv(socketserver.ThreadingMixIn, http.server.HTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._srv = DohSrv((self.bind_ip, self.port), DohHandler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain("/tmp/p4-doh.crt", "/tmp/p4-doh.key")
        self._srv.socket = ctx.wrap_socket(self._srv.socket, server_side=True)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()


def run_suites_4_5_6_dataplane_and_chaos(priv1, pub1, priv2, pub2):
    echo = _EchoServer()
    echo.start()
    doh = _LocalDohServer()
    doh.start()
    isp_proxy = _MockWebshareProxy()
    isp_proxy.start()

    cam_dir = tempfile.mkdtemp(prefix="p4-cam-")
    mihomo_dir = tempfile.mkdtemp(prefix="p4-mh-")
    shutil.copy("/etc/mihomo/geoip.metadb", os.path.join(mihomo_dir, "geoip.metadb"))
    Path(cam_dir, "Caddyfile").write_text(
        "https://camouflage.local:443 {\n  bind 10.201.0.10\n  tls internal\n  respond \"ok\" 200\n}\n"
    )
    cam_proc = None
    exit_proc = None
    relay_proc = None
    sb_cli_proc = None
    mh_proc = None
    try:
        cam_env = dict(os.environ, HOME=cam_dir)
        lf_cam = open("/tmp/cam-caddy.log", "w", encoding="utf-8")
        p_cam = subprocess.Popen(["/usr/local/bin/caddy", "run", "--config", os.path.join(cam_dir, "Caddyfile"), "--adapter", "caddyfile"], stdout=lf_cam, stderr=subprocess.STDOUT, env=cam_env)
        cam_proc = (p_cam, lf_cam)
        wait_https("camouflage.local", "10.201.0.10", 443, timeout=8)

        uuid1 = "11111111-1111-4111-8111-111111111111"
        uuid2 = "33333333-3333-4333-8333-333333333333"
        hy2_cfg = {"port": 10443, "password": "hy2-pw-1", "obfs_password": "obfs-pw-1", "sni": "camouflage.local"}
        isp_socks = {"type": "socks", "server": "10.202.0.2", "server_port": 11080, "username": "wuser", "password": "wpass"}
        isp_http = {"type": "http", "server": "10.202.0.2", "server_port": 13128, "username": "wuser", "password": "wpass"}

        vless_exit_node = {"name": "sv-vless", "host": "10.201.0.1", "port": 10443, "uuid": uuid1, "pbk": pub1, "sid": "abcd1234", "sni": "camouflage.local", "role": "exit", "health": "ok", "isp": isp_socks}
        hy2_exit_node = {"name": "sv-hy2", "type": "hysteria2", "host": "10.201.0.1", "port": 10443, "password": "hy2-pw-1", "obfs_password": "obfs-pw-1", "sni": "camouflage.local", "role": "exit", "health": "ok"}
        relay_node = {"name": "bj-relay", "host": "10.201.0.2", "port": 10444, "uuid": uuid2, "pbk": pub2, "sid": "ef123456", "sni": "camouflage.local", "role": "relay", "health": "ok", "landing": vless_exit_node}

        exit_socks_cfg = templates.exit_config(10443, uuid1, "camouflage.local", priv1, "abcd1234", hy2=hy2_cfg, isp=isp_socks)
        Path("/opt/sing-box/config.json").write_text(json.dumps(exit_socks_cfg))
        exit_proc = start_proc(["/usr/local/bin/sing-box", "run", "-c", "/opt/sing-box/config.json"], "/tmp/sb-exit.log")
        wait_tcp("10.201.0.1", 10443, timeout=8)

        # Relay server
        relay_cfg = templates.relay_config(10444, uuid2, "camouflage.local", priv2, "ef123456", vless_exit_node)
        Path("/tmp/sb-relay.json").write_text(json.dumps(relay_cfg))
        relay_proc = start_proc(["/usr/local/bin/sing-box", "run", "-c", "/tmp/sb-relay.json"], "/tmp/sb-relay.log")
        wait_tcp("10.201.0.2", 10444, timeout=8)

        # Suite 4.1: mihomo -> VLESS Reality -> Exit -> Webshare SOCKS5 -> Echo
        mh_port_v = free_port()
        Path(mihomo_dir, "vless.yaml").write_text(make_single_mihomo_yaml(vless_exit_node, mh_port_v, pub1))
        mh_proc = start_proc(["/usr/local/bin/mihomo", "-d", mihomo_dir, "-f", os.path.join(mihomo_dir, "vless.yaml")], "/tmp/mh-vless.log")
        wait_tcp("127.0.0.1", mh_port_v, timeout=8)
        rc, out, err = socks5_get("127.0.0.1", mh_port_v, "http://10.203.0.2:18080/echo?nonce=p4_vless")
        sb_log = Path("/var/log/sing-box.log").read_text() if Path("/var/log/sing-box.log").exists() else ""
        assert rc == 0, (rc, out, err, "DOH_Q=", doh.queries, "ISP_TCP=", isp_proxy.socks_tcp_count, "MIHOMO=", Path("/tmp/mh-vless.log").read_text(), "SB_LOG=", sb_log)
        d = json.loads(out)
        assert d == {"nonce": "p4_vless", "peer_ip": "10.204.0.2"}, d
        stop_proc(mh_proc)
        mh_proc = None

        # Suite 4.2: mihomo -> Hysteria2 QUIC -> Exit -> Webshare SOCKS5 -> Echo
        mh_port_h = free_port()
        Path(mihomo_dir, "hy2.yaml").write_text(make_single_mihomo_yaml(hy2_exit_node, mh_port_h, pub1))
        mh_proc = start_proc(["/usr/local/bin/mihomo", "-d", mihomo_dir, "-f", os.path.join(mihomo_dir, "hy2.yaml")], "/tmp/mh-hy2.log")
        wait_tcp("127.0.0.1", mh_port_h, timeout=8)
        rc, out, err = socks5_get("127.0.0.1", mh_port_h, "http://10.203.0.2:18080/echo?nonce=p4_hy2")
        assert rc == 0, (rc, out, err)
        d = json.loads(out)
        assert d == {"nonce": "p4_hy2", "peer_ip": "10.204.0.2"}, d
        stop_proc(mh_proc)
        mh_proc = None

        # Suite 4.3: sing-box Client -> sing-box Relay -> sing-box Exit -> Webshare SOCKS5 -> Echo
        sb_r_port = free_port()
        Path("/tmp/sb-cli-relay.json").write_text(json.dumps(verify._client_cfg(relay_node, sb_r_port)))
        sb_cli_proc = start_proc(["/usr/local/bin/sing-box", "run", "-c", "/tmp/sb-cli-relay.json"], "/tmp/sb-cli-r.log")
        wait_tcp("127.0.0.1", sb_r_port, timeout=8)
        rc, out, err = socks5_get("127.0.0.1", sb_r_port, "http://10.203.0.2:18080/echo?nonce=p4_relay")
        assert rc == 0, (rc, out, err)
        assert json.loads(out) == {"nonce": "p4_relay", "peer_ip": "10.204.0.2"}
        stop_proc(sb_cli_proc)
        sb_cli_proc = None

        # Suite 4.4: UDP over non-UDP ISP is rejected locally inside Exit without hitting Webshare
        sb_e_port = free_port()
        Path("/tmp/sb-cli-exit.json").write_text(json.dumps(verify._client_cfg(vless_exit_node, sb_e_port)))
        sb_cli_proc = start_proc(["/usr/local/bin/sing-box", "run", "-c", "/tmp/sb-cli-exit.json"], "/tmp/sb-cli-e.log")
        wait_tcp("127.0.0.1", sb_e_port, timeout=8)
        isp_proxy.udp_associate_count = 0
        echo.reset_counts()
        _ = socks5_try_udp_associate("127.0.0.1", sb_e_port)
        assert isp_proxy.udp_associate_count == 0, f"UDP escaped to upstream ISP: {isp_proxy.udp_associate_count}"
        assert echo.udp_hits == 0, f"UDP escaped to target: {echo.udp_hits}"

        # Suite 5 (SOCKS5): tcpdump + iptables DROP and REJECT => strictly 0 bytes native leak
        def measure_leak(iptables_rule_args, test_tag):
            pcap = f"/tmp/leak_{test_tag}.pcap"
            run_cmd(["iptables", "-I", "OUTPUT", *iptables_rule_args])
            td_proc = None
            try:
                time.sleep(0.3)
                echo.reset_counts()
                td_proc = subprocess.Popen(
                    ["tcpdump", "-i", "lo", "-U", "-nn", "-w", pcap, "dst host 10.203.0.2 and dst port 18080"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                time.sleep(0.4)
                for idx in range(5):
                    rc_f, _, _ = socks5_get("127.0.0.1", sb_e_port, f"http://10.203.0.2:18080/echo?nonce={test_tag}_{idx}", timeout=1.5)
                    assert rc_f != 0, f"Faulted ISP call unexpectedly succeeded under {test_tag}"
                _ = socks5_try_udp_associate("127.0.0.1", sb_e_port)
                time.sleep(0.2)
            finally:
                if td_proc is not None:
                    td_proc.terminate()
                    td_proc.wait(timeout=4)
                run_cmd(["iptables", "-D", "OUTPUT", *iptables_rule_args])
            pkts = run_cmd(["tcpdump", "-r", pcap, "-nn"], check=False).stdout.strip().splitlines()
            assert len(pkts) == 0, f"Native leak packets captured ({test_tag}): {pkts}"
            assert echo.hits == 0 and echo.udp_hits == 0, (echo.hits, echo.udp_hits)

        measure_leak(["-d", "10.202.0.2", "-p", "tcp", "--dport", "11080", "-j", "DROP"], "socks_drop")
        measure_leak(["-d", "10.202.0.2", "-p", "tcp", "--dport", "11080", "-j", "REJECT", "--reject-with", "tcp-reset"], "socks_rst")

        # Suite 4.5 & Suite 5 (HTTP CONNECT): swap Exit to HTTP ISP and prove zero native leak too
        stop_proc(exit_proc)
        exit_proc = None
        exit_http_cfg = templates.exit_config(10443, uuid1, "camouflage.local", priv1, "abcd1234", isp=isp_http)
        Path("/opt/sing-box/config.json").write_text(json.dumps(exit_http_cfg))
        exit_proc = start_proc(["/usr/local/bin/sing-box", "run", "-c", "/opt/sing-box/config.json"], "/tmp/sb-exit-http.log")
        wait_tcp("10.201.0.1", 10443, timeout=8)
        rc, out, err = socks5_get("127.0.0.1", sb_e_port, "http://10.203.0.2:18080/echo?nonce=p4_http")
        assert rc == 0, (rc, out, err)
        assert json.loads(out) == {"nonce": "p4_http", "peer_ip": "10.204.0.2"}
        assert isp_proxy.http_connect_count >= 1
        measure_leak(["-d", "10.202.0.2", "-p", "tcp", "--dport", "13128", "-j", "REJECT", "--reject-with", "tcp-reset"], "http_rst")

        stop_proc(sb_cli_proc)
        sb_cli_proc = None
        stop_proc(relay_proc)
        relay_proc = None
        stop_proc(exit_proc)
        exit_proc = None

        # Suite 6: Chaos netem + Reality->HY2 fallback + real verify & repair
        exit_direct_cfg = templates.exit_config(10443, uuid1, "camouflage.local", priv1, "abcd1234", hy2=hy2_cfg)
        Path("/opt/sing-box/config.json").write_text(json.dumps(exit_direct_cfg))
        exit_proc = start_proc(["/usr/local/bin/sing-box", "run", "-c", "/opt/sing-box/config.json"], "/tmp/sb-exit-chaos.log")
        wait_tcp("10.201.0.1", 10443, timeout=8)

        # Inject real kernel tc netem (25% loss + 180ms jitter) on UDP+TCP traffic to port 10443
        chaos_method = "tc_netem"
        run_cmd(["tc", "qdisc", "del", "dev", "lo", "root"], check=False)
        tc1 = run_cmd(["tc", "qdisc", "add", "dev", "lo", "root", "handle", "1:", "prio", "bands", "4"], check=False)
        tc2 = run_cmd(["tc", "qdisc", "add", "dev", "lo", "parent", "1:4", "handle", "40:", "netem", "delay", "180ms", "30ms", "loss", "25%"], check=False)
        tc3 = run_cmd(["tc", "filter", "add", "dev", "lo", "protocol", "ip", "parent", "1:0", "prio", "4", "u32", "match", "ip", "dport", "10443", "0xffff", "flowid", "1:4"], check=False)
        assert tc1.returncode == 0 and tc2.returncode == 0 and tc3.returncode == 0, (tc1.stderr, tc2.stderr, tc3.stderr)

        try:
            # Verify HY2 succeeds under 25% loss + 180ms jitter
            sb_h_port = free_port()
            Path("/tmp/sb-cli-hy2.json").write_text(json.dumps(verify._client_cfg(hy2_exit_node, sb_h_port)))
            sb_cli_proc = start_proc(["/usr/local/bin/sing-box", "run", "-c", "/tmp/sb-cli-hy2.json"], "/tmp/sb-cli-h.log")
            wait_tcp("127.0.0.1", sb_h_port, timeout=8)
            hy2_ok = False
            for attempt in range(4):
                rc_h, out_h, _ = socks5_get("127.0.0.1", sb_h_port, f"http://10.203.0.2:18080/echo?nonce=chaos_{attempt}", timeout=6)
                if rc_h == 0 and json.loads(out_h).get("nonce") == f"chaos_{attempt}":
                    hy2_ok = True
                    break
            assert hy2_ok, "HY2 failed under 25% loss + 180ms jitter"
            stop_proc(sb_cli_proc)
            sb_cli_proc = None
        finally:
            run_cmd(["tc", "qdisc", "del", "dev", "lo", "root"], check=False)

        # Mihomo fallback group failover when Reality 10443/tcp is blocked
        mh_port_fb = free_port()
        mh_ctl_port = free_port()
        Path(mihomo_dir, "fallback.yaml").write_text(
            make_single_mihomo_yaml([vless_exit_node, hy2_exit_node], mh_port_fb, pub1, external_controller=f"127.0.0.1:{mh_ctl_port}")
        )
        mh_proc = start_proc(["/usr/local/bin/mihomo", "-d", mihomo_dir, "-f", os.path.join(mihomo_dir, "fallback.yaml")], "/tmp/mh-fb.log")
        wait_tcp("127.0.0.1", mh_port_fb, timeout=8)
        run_cmd(["iptables", "-I", "OUTPUT", "-d", "10.201.0.1", "-p", "tcp", "--dport", "10443", "-j", "REJECT", "--reject-with", "tcp-reset"])
        try:
            # Wait for 1s fallback healthcheck to detect TCP 10443 dead and switch to HY2
            fb_ok = False
            for _ in range(15):
                time.sleep(0.5)
                rc_fb, out_fb, _ = socks5_get("127.0.0.1", mh_port_fb, "http://10.203.0.2:18080/echo?nonce=failover", timeout=3)
                if rc_fb == 0 and json.loads(out_fb).get("nonce") == "failover":
                    fb_ok = True
                    break
            assert fb_ok, "Mihomo fallback group did not fail over from blocked Reality TCP to HY2 UDP"
        finally:
            run_cmd(["iptables", "-D", "OUTPUT", "-d", "10.201.0.1", "-p", "tcp", "--dport", "10443", "-j", "REJECT", "--reject-with", "tcp-reset"])
            stop_proc(mh_proc)
            mh_proc = None

        # Suite 6b: Real verify.proxy_probe + verify.run + repair.repair_node with real sing-box, flock, & provenance
        orig_urls = verify.PROBE_URLS
        orig_country = verify.country_of
        verify.PROBE_URLS = ("http://10.203.0.2:18080/ip",)
        verify.country_of = lambda ip: "US"
        secret = bytes.fromhex("ab" * 32)
        os.makedirs("/etc/sing-box", exist_ok=True)
        os.makedirs("/tmp/p4-bin", exist_ok=True)

        # Hand sing-box process lifecycle cleanly to our /tmp/p4-bin/systemctl shim
        stop_proc(exit_proc)
        exit_proc = None

        systemctl_path = Path("/tmp/p4-bin/systemctl")
        systemctl_path.write_text("""#!/usr/bin/env python3
import os, signal, socket, subprocess, sys, time
from pathlib import Path

PIDF = Path("/tmp/p4-sb.pid")
FAIL_SENTINEL = Path("/tmp/p4-fail-start")

def read_pid():
    try:
        return int(PIDF.read_text().strip())
    except Exception:
        return None

def alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def stop_sb():
    pid = read_pid()
    if alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not alive(pid):
                break
            time.sleep(0.1)
        if alive(pid):
            os.kill(pid, signal.SIGKILL)
    PIDF.unlink(missing_ok=True)

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "daemon-reload":
    sys.exit(0)
if cmd == "is-active":
    sys.exit(0 if alive(read_pid()) else 3)
if cmd == "stop":
    stop_sb()
    sys.exit(0)
if cmd in ("start", "restart"):
    stop_sb()
    if FAIL_SENTINEL.exists():
        sys.exit(1)
    lf = open("/tmp/sb-managed.log", "w", encoding="utf-8")
    p = subprocess.Popen(
        ["/usr/local/bin/sing-box", "run", "-c", "/opt/sing-box/config.json"],
        stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
        close_fds=True, start_new_session=True,
    )
    PIDF.write_text(str(p.pid))
    for _ in range(40):
        try:
            with socket.create_connection(("10.201.0.1", 10443), timeout=0.3):
                sys.exit(0)
        except OSError:
            time.sleep(0.1)
    sys.exit(1)
sys.exit(0)
""")
        systemctl_path.chmod(0o755)
        Path("/tmp/p4-fail-start").unlink(missing_ok=True)

        run_cmd(["/tmp/p4-bin/systemctl", "start", "sing-box"])
        cfg_bytes = Path("/opt/sing-box/config.json").read_bytes()
        manifest = provenance.sign_provenance("sv-1", provenance.compute_config_sha256(cfg_bytes), secret)
        prov_path = Path(provenance.PROVENANCE_PATH_LINUX)
        prov_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        prov_path.chmod(0o600)

        bash_env = dict(os.environ, PATH="/tmp/p4-bin:" + os.environ.get("PATH", ""))

        def exec_local_bash(node, cmd, timeout=15):
            return subprocess.run(["bash", "-c", cmd], env=bash_env, capture_output=True, text=True, timeout=timeout)

        verify_node = {"name": "sv-exit", "host": "10.201.0.1", "port": 10443, "uuid": uuid1, "pbk": pub1, "sid": "abcd1234",
                       "sni": "camouflage.local", "role": "exit", "source": "builtin", "local": True, "provenance_id": "sv-1"}

        v_ok = verify.run(verify_node)
        assert v_ok["health"] == "ok", v_ok

        # Kill sing-box -> verify fails -> repair restarts with real provenance + flock -> verify passes
        run_cmd(["/tmp/p4-bin/systemctl", "stop", "sing-box"])
        v_dead = verify.run(verify_node)
        assert v_dead["health"] == "port", v_dead
        rep_ok = repair.repair_node(verify_node, execute_remote_fn=exec_local_bash, verifier=verify.run, sleep_fn=lambda _: time.sleep(0.3), master_secret=secret)
        assert rep_ok.get("ok") is True and rep_ok.get("after") == "ok", rep_ok

        # Keep sing-box unrecoverable -> repair MUST report False (zero false green)
        run_cmd(["/tmp/p4-bin/systemctl", "stop", "sing-box"])
        Path("/tmp/p4-fail-start").write_text("1")
        rep_fail = repair.repair_node(verify_node, execute_remote_fn=exec_local_bash, verifier=verify.run, sleep_fn=lambda _: time.sleep(0.3), master_secret=secret)
        assert rep_fail.get("ok") is False, rep_fail
        Path("/tmp/p4-fail-start").unlink(missing_ok=True)
        run_cmd(["/tmp/p4-bin/systemctl", "stop", "sing-box"], check=False)

        verify.PROBE_URLS = orig_urls
        verify.country_of = orig_country

        return {
            "ok": True,
            "suite4": {"socks_tcp": isp_proxy.socks_tcp_count, "http_connect": isp_proxy.http_connect_count, "udp_escaped": isp_proxy.udp_associate_count},
            "suite5": {"native_leak_bytes": 0, "modes_tested": ["socks_drop", "socks_rst", "http_rst"]},
            "suite6": {"chaos_method": chaos_method, "hy2_under_loss": True, "reality_to_hy2_failover": True, "repair_recovery_ok": True, "repair_fail_honest": True},
        }
    finally:
        if os.path.exists("/tmp/p4-bin/systemctl"):
            subprocess.run(["/tmp/p4-bin/systemctl", "stop", "sing-box"], check=False, capture_output=True)
        stop_proc(mh_proc)
        stop_proc(sb_cli_proc)
        stop_proc(relay_proc)
        stop_proc(exit_proc)
        stop_proc(cam_proc)
        isp_proxy.stop()
        doh.stop()
        echo.stop()
        shutil.rmtree(cam_dir, ignore_errors=True)
        shutil.rmtree(mihomo_dir, ignore_errors=True)


setup_loopback_addrs()
priv1, pub1 = gen_reality_pair()
priv2, pub2 = gen_reality_pair()

report = {
    "ok": True,
    "suites": {
        "suite1_singbox_reconcile": run_suite_1_singbox_and_reconcile(priv1, pub1, priv2, pub2),
        "suite2_caddy_stealth_admin": run_suite_2_caddy_stealth_and_admin(),
        "suite3_mihomo_profiles": run_suite_3_mihomo_profiles(pub1),
        "suites4_5_6_dataplane_chaos": run_suites_4_5_6_dataplane_and_chaos(priv1, pub1, priv2, pub2),
    },
}
print("PHASE4_REPORT_JSON:" + json.dumps(report, ensure_ascii=False))
'''


def _build_bundle() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path in sorted((ROOT / "server").glob("*.py")):
            tf.add(path, arcname=path.relative_to(ROOT / "server"))
        for folder in ("nodekit", "providers"):
            src = ROOT / "server" / folder
            if src.exists():
                tf.add(
                    src,
                    arcname=folder,
                    filter=lambda ti: None if "__pycache__" in ti.name or ti.name.endswith(".pyc") else ti,
                )
        for html in ("index.html", "change-password.html"):
            p = ROOT / "web" / html
            if p.exists():
                tf.add(p, arcname=html)
        tf.add(ROOT / "deploy" / "install.sh", arcname="install.sh")
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 4 real-binary Docker chaos lab verification.")
    parser.add_argument("--image", default="ownline-phase4-lab:latest", help="Docker image built from Dockerfile.phase4")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    payload_b64 = base64.b64encode(_build_bundle()).decode("ascii")
    runner = (
        "import base64, pathlib\n"
        f"pathlib.Path('/tmp/ownline-src.tgz').write_bytes(base64.b64decode({payload_b64!r}))\n"
        + _CONTAINER_SCRIPT
    )

    proc = subprocess.run(
        [
            "docker", "run", "--rm", "--pull=never", "-i",
            "--network", "none",
            "--cap-add", "NET_ADMIN",
            "--cap-add", "NET_RAW",
            args.image,
            "python3", "-",
        ],
        input=runner,
        text=True,
        capture_output=True,
        check=False,
        timeout=240,
    )

    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return proc.returncode or 1

    report = None
    for line in proc.stdout.splitlines():
        if line.startswith("PHASE4_REPORT_JSON:"):
            report = json.loads(line.split(":", 1)[1])
            break

    if not report or not report.get("ok"):
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s1 = report["suites"]["suite1_singbox_reconcile"]
        s2 = report["suites"]["suite2_caddy_stealth_admin"]
        s3 = report["suites"]["suite3_mihomo_profiles"]
        s456 = report["suites"]["suites4_5_6_dataplane_chaos"]
        print(f"[PASS] Suite 1: sing-box 1.14.4 check + reconcile ({s1['checked_configs']} configs)")
        print(f"[PASS] Suite 2: caddy 2.10.2 stealth + admin.py (port80_closed={s2['port80_closed']}, server_header_stripped={s2['server_header_stripped']})")
        print(f"[PASS] Suite 3: mihomo v1.19.34 -t profiles={','.join(s3['validated_profiles'])}")
        print(f"[PASS] Suite 4: E2E mihomo+sing-box -> ISP SOCKS5/HTTP & UDP blocked (udp_escaped={s456['suite4']['udp_escaped']})")
        print(f"[PASS] Suite 5: iptables + tcpdump fail-closed proof (native_leak_bytes={s456['suite5']['native_leak_bytes']}, modes={','.join(s456['suite5']['modes_tested'])})")
        print(f"[PASS] Suite 6: chaos ({s456['suite6']['chaos_method']}) HY2+failover + real verify/repair (honest_fail={s456['suite6']['repair_fail_honest']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
