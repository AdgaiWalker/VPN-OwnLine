#!/usr/bin/env python3
"""Stage S2 black-box verification in isolated ownline-phase4-lab container (--network none).

Runs real unmodified server/admin.py, caddy 2.10.2, sing-box 1.14.4, mihomo v1.19.34,
reset_admin_password.py, NodeManager, remote_config, reconcile, join_token, SubscriptionEngine,
server/local_setup.py daemon, and ownline.py CLI with zero plaintext secret leakage.
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
import fcntl
import http.client
import http.server
import json
import os
from pathlib import Path
import pty
import select
import shutil
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import urllib.parse

for d in ("/opt/ownline-repo", "/opt/web", "/opt/web-data", "/opt/sing-box", "/etc/caddy", "/etc/sing-box", "/tmp/s2-caddy-home", "/tmp/s2-site", "/tmp/s2-bin"):
    os.makedirs(d, exist_ok=True)
os.chmod("/opt/web-data", 0o700)

with open("/tmp/ownline-s2-src.tgz", "rb") as f:
    import tarfile
    with tarfile.open(fileobj=f, mode="r:gz") as tf:
        tf.extractall("/opt/ownline-repo")

# Install runtime layout using repo canonical manifest.
sys.path.insert(0, "/opt/ownline-repo/deploy")
import runtime_manifest  # noqa: E402
runtime_manifest.install_runtime("/opt/ownline-repo", "/opt/web")
if not os.path.exists("/opt/sing-box/sing-box"):
    shutil.copy2("/usr/local/bin/sing-box", "/opt/sing-box/sing-box")
    os.chmod("/opt/sing-box/sing-box", 0o755)

sys.path.insert(0, "/opt/web")
from nodekit import provenance, templates  # noqa: E402

def run_cmd(cmd, *, check=True, timeout=30, input_text=None, env=None):
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True, check=check, timeout=timeout, env=env)

# Loopback addresses matching Phase 4 topology + Reality camouflage target + local DoH.
for addr in ("10.201.0.1/32", "10.201.0.10/32", "10.202.0.2/32", "10.203.0.2/32", "10.204.0.2/32", "1.1.1.1/32"):
    subprocess.run(["ip", "addr", "add", addr, "dev", "lo"], capture_output=True, text=True, check=False)
hosts_path = Path("/etc/hosts")
hosts = hosts_path.read_text()
if "camouflage.local" not in hosts:
    hosts_path.write_text(hosts + "\n10.201.0.10 camouflage.local\n")

# Isolated-container sitecustomize for --network none probe redirection (no real production code edits).
Path("/tmp/s2-site/sitecustomize.py").write_text(
    "try:\n"
    "    from nodekit import verify\n"
    "    verify.PROBE_URLS = ('http://10.203.0.2:18080/ip',)\n"
    "    verify.country_of = lambda ip: 'US' if ip else ''\n"
    "except Exception:\n"
    "    pass\n",
    encoding="utf-8",
)

# 1. Start local HTTPS camouflage target (10.201.0.10:443), IP echo server (10.203.0.2:18080),
#    and mock Webshare SOCKS5 proxy (10.202.0.2:11080 -> egress 10.204.0.2).
cam_dir = tempfile.mkdtemp(prefix="s2-cam-")
cert_p, key_p = os.path.join(cam_dir, "cert.pem"), os.path.join(cam_dir, "key.pem")
run_cmd(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
         "-subj", "/CN=camouflage.local", "-keyout", key_p, "-out", cert_p])
cam_lf = open("/tmp/s2-cam.log", "w", encoding="utf-8")
cam_proc = subprocess.Popen(
    ["openssl", "s_server", "-accept", "10.201.0.10:443", "-cert", cert_p, "-key", key_p, "-www", "-quiet"],
    stdin=subprocess.DEVNULL, stdout=cam_lf, stderr=subprocess.STDOUT,
)

class EchoHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        ip = self.client_address[0]
        raw = ip.encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

echo_srv = socketserver.ThreadingTCPServer(("10.203.0.2", 18080), EchoHandler)
echo_th = threading.Thread(target=echo_srv.serve_forever, daemon=True)
echo_th.start()

WS_USER = "wsuser-bb-91"
WS_PASS = "wspass-bb-secret-99"
TEMP_PWD = "temp-blackbox-init-7788"
NEW_PANEL_PWD = "UserChosenPanel!2026bb"
SUB_TOKEN = "b2c3d4e5" * 8

class Socks5Proxy:
    def __init__(self):
        self.tcp_hits = 0
        self.lock = threading.Lock()
        self.srv = None

    def start(self):
        parent = self
        class H(socketserver.BaseRequestHandler):
            def handle(self):
                conn = self.request
                conn.settimeout(6)
                hdr = conn.recv(2)
                if len(hdr) < 2 or hdr[0] != 5:
                    return
                methods = conn.recv(hdr[1])
                if 2 not in methods:
                    conn.sendall(b"\x05\xff")
                    return
                conn.sendall(b"\x05\x02")
                if not conn.recv(1):
                    return
                ulen = conn.recv(1)[0]
                u = conn.recv(ulen).decode("utf-8", "replace")
                plen = conn.recv(1)[0]
                p = conn.recv(plen).decode("utf-8", "replace")
                if u != WS_USER or p != WS_PASS:
                    conn.sendall(b"\x01\x01")
                    return
                conn.sendall(b"\x01\x00")
                req = conn.recv(4)
                if len(req) < 4:
                    return
                _, cmd, _, atyp = req
                if atyp == 1:
                    dst_host = socket.inet_ntoa(conn.recv(4))
                elif atyp == 3:
                    dlen = conn.recv(1)[0]
                    dst_host = conn.recv(dlen).decode("utf-8", "replace")
                else:
                    conn.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                    return
                dst_port = struct.unpack("!H", conn.recv(2))[0]
                if cmd != 1:
                    conn.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                    return
                up = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                up.settimeout(6)
                up.bind(("10.204.0.2", 0))
                up.connect((dst_host, dst_port))
                with parent.lock:
                    parent.tcp_hits += 1
                conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                try:
                    while True:
                        r, _, _ = select.select([conn, up], [], [], 8)
                        if not r:
                            break
                        for s in r:
                            d = up if s is conn else conn
                            chunk = s.recv(16384)
                            if not chunk:
                                return
                            d.sendall(chunk)
                finally:
                    conn.close()
                    up.close()

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.srv = socketserver.ThreadingTCPServer(("10.202.0.2", 11080), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

ws_proxy = Socks5Proxy()
ws_proxy.start()

class LocalDohServer:
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
            "-keyout", "/tmp/s2-doh.key", "-out", "/tmp/s2-doh.crt",
            "-days", "1", "-subj", "/CN=1.1.1.1",
            "-addext", "subjectAltName=IP:1.1.1.1",
        ])
        os.makedirs("/usr/local/share/ca-certificates", exist_ok=True)
        shutil.copy("/tmp/s2-doh.crt", "/usr/local/share/ca-certificates/s2-doh.crt")
        run_cmd(["update-ca-certificates"])
        parent = self

        class DohHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return
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

        class DohSrv(socketserver.ThreadingMixIn, http.server.HTTPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._srv = DohSrv((self.bind_ip, self.port), DohHandler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain("/tmp/s2-doh.crt", "/tmp/s2-doh.key")
        self._srv.socket = ctx.wrap_socket(self._srv.socket, server_side=True)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()

doh_srv = LocalDohServer()
doh_srv.start()

# 2. Install local systemctl shim handling both caddy reload and sing-box restart.
systemctl_shim = Path("/tmp/s2-bin/systemctl")
systemctl_shim.write_text("""#!/usr/bin/env python3
import os, signal, socket, subprocess, sys, time
from pathlib import Path

action = sys.argv[1] if len(sys.argv) > 1 else ""
unit = sys.argv[2] if len(sys.argv) > 2 else ""

def pid_alive(pf):
    try:
        pid = int(pf.read_text().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None

if unit.startswith("caddy"):
    if action == "reload":
        env = dict(os.environ, HOME="/tmp/s2-caddy-home")
        p = subprocess.run(["/usr/local/bin/caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
                           env=env, capture_output=True, text=True)
        sys.exit(p.returncode)
    sys.exit(0)

if unit.startswith("sing-box"):
    pf = Path("/tmp/s2-sb.pid")
    if action == "is-active":
        sys.exit(0 if pid_alive(pf) else 3)
    if action in ("stop", "restart", "start"):
        old = pid_alive(pf)
        if old:
            try:
                os.kill(old, signal.SIGTERM)
                for _ in range(30):
                    os.kill(old, 0)
                    time.sleep(0.1)
            except OSError:
                pass
            pf.unlink(missing_ok=True)
        if action == "stop":
            sys.exit(0)
        lf = open("/tmp/s2-singbox.log", "w", encoding="utf-8")
        proc = subprocess.Popen(
            ["/opt/sing-box/sing-box", "run", "-c", "/opt/sing-box/config.json"],
            stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
            close_fds=True, start_new_session=True,
        )
        pf.write_text(str(proc.pid))
        for _ in range(40):
            try:
                with socket.create_connection(("10.201.0.1", 10443), timeout=0.3):
                    sys.exit(0)
            except OSError:
                time.sleep(0.1)
        sys.exit(1)
sys.exit(0)
""")
systemctl_shim.chmod(0o755)
shutil.copy2(str(systemctl_shim), "/usr/local/bin/systemctl")

# 3. Bootstrap real sing-box config, provenance HMAC, nodes.json, initial-password marker, Caddyfile, and admin.py.
kp = run_cmd(["/opt/sing-box/sing-box", "generate", "reality-keypair"]).stdout
priv1 = [ln.split(":", 1)[1].strip() for ln in kp.splitlines() if ln.startswith("PrivateKey:")][0]
pub1 = [ln.split(":", 1)[1].strip() for ln in kp.splitlines() if ln.startswith("PublicKey:")][0]
uuid1 = "11111111-1111-4111-8111-111111111111"

cfg0 = templates.exit_config(port=10443, uuid=uuid1, sni="camouflage.local", private_key=priv1, sid="abcd1234")
Path("/opt/sing-box/config.json").write_text(json.dumps(cfg0, indent=2), encoding="utf-8")

master_secret = provenance.load_master_secret(data_dir="/opt/web-data", create=True)
cfg_sha = provenance.compute_config_sha256(Path("/opt/sing-box/config.json").read_bytes())
prov_manifest = provenance.sign_provenance("sv-blackbox-1", cfg_sha, master_secret)
Path(provenance.PROVENANCE_PATH_LINUX).write_text(json.dumps(prov_manifest, indent=2), encoding="utf-8")
Path(provenance.PROVENANCE_PATH_LINUX).chmod(0o600)

run_cmd(["systemctl", "start", "sing-box"])

Path("/opt/web-data/nodes.json").write_text(json.dumps([
    {
        "name": "美西黑盒节点",
        "type": "vless",
        "role": "exit",
        "host": "10.201.0.1",
        "port": 10443,
        "uuid": uuid1,
        "pbk": pub1,
        "sid": "abcd1234",
        "sni": "camouflage.local",
        "source": "builtin",
        "local": True,
        "provenance_id": "sv-blackbox-1",
        "health": "ok",
    }
], ensure_ascii=False, indent=2), encoding="utf-8")
Path("/opt/web-data/settings.json").write_text(json.dumps({"sub_token": SUB_TOKEN}), encoding="utf-8")
Path("/opt/web-data/status.json").write_text("{}", encoding="utf-8")
Path("/opt/web-data/.initial-password-required").write_text("1", encoding="utf-8")

install_sh = Path("/opt/ownline-repo/deploy/install.sh").read_text()
caddy_tmpl = install_sh.split('cat > "$CADDY_STAGED" << CADDYEOF\n', 1)[1].split("\nCADDYEOF", 1)[0]
caddy_env = dict(os.environ, HOME="/tmp/s2-caddy-home", PATH="/tmp/s2-bin:" + os.environ.get("PATH", ""))
pw_hash = run_cmd(["/usr/local/bin/caddy", "hash-password"], input_text=TEMP_PWD + "\n", env=caddy_env).stdout.strip()
caddy_cfg = caddy_tmpl.replace("$SETUP_JOB", "s2blackbox").replace("$PASS_HASH", pw_hash).replace("${DOMAIN}", "localhost").replace("$TLS_DIRECTIVE", "tls internal") + "\n"
Path("/etc/caddy/Caddyfile").write_text(caddy_cfg, encoding="utf-8")
val = run_cmd(["/usr/local/bin/caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"], env=caddy_env, check=False)
assert val.returncode == 0, val.stderr

admin_env = dict(os.environ, HOME="/tmp/s2-caddy-home", PATH="/tmp/s2-bin:" + os.environ.get("PATH", ""), PYTHONPATH="/tmp/s2-site:/opt/web")
admin_lf = open("/tmp/s2-admin.log", "w", encoding="utf-8")
admin_proc = subprocess.Popen(["python3", "/opt/web/admin.py"], env=admin_env, stdout=admin_lf, stderr=subprocess.STDOUT)

caddy_lf = open("/tmp/s2-caddy.log", "w", encoding="utf-8")
caddy_proc = subprocess.Popen(["/usr/local/bin/caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"], env=caddy_env, stdout=caddy_lf, stderr=subprocess.STDOUT)

def wait_tcp(host, port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port {host}:{port} not ready")

daemon_proc = None
try:
    wait_tcp("127.0.0.1", 8099)
    wait_tcp("127.0.0.1", 8443)

    # Verify initial-password lock enforces HTTP 403 on mutations before rotation (SNI=localhost matches Caddy tls internal).
    ssl_ctx = ssl._create_unverified_context()
    pre_status = None
    for _ in range(20):
        try:
            c = http.client.HTTPSConnection("localhost", 8443, context=ssl_ctx, timeout=5)
            c.request(
                "POST",
                "/api/editnode",
                body=b'{"name":"test"}',
                headers={
                    "Host": "localhost:8443",
                    "Origin": "https://localhost:8443",
                    "Content-Type": "application/json",
                    "Authorization": "Basic " + base64.b64encode(f"admin:{TEMP_PWD}".encode()).decode(),
                },
            )
            pre_resp = c.getresponse()
            pre_resp.read()
            c.close()
            pre_status = pre_resp.status
            break
        except ssl.SSLError:
            time.sleep(0.15)
    assert pre_status in (303, 403), f"expected 303/403 before password rotation, got {pre_status}"

    # 4. Launch real server.local_setup daemon in separate process holding post-install RAM delivery.
    runner_script = Path("/tmp/s2-daemon.py")
    runner_script.write_text(json.dumps({"TEMP_PWD": TEMP_PWD, "SUB_TOKEN": SUB_TOKEN}))
    runner_code = """
import json, sys, threading
from pathlib import Path
sys.path.insert(0, '/opt/ownline-repo')
from server import local_setup

cfg = json.loads(Path('/tmp/s2-daemon.py').read_text())
class DoneSession:
    def status(self):
        return {
            'state': 'done',
            'delivery': {
                'kind': 'standalone',
                'dashboard_url': 'https://localhost:8443/',
                'username': 'admin',
                'temp_password': cfg['TEMP_PWD'],
                'sub_token': cfg['SUB_TOKEN'],
            },
        }
srv = local_setup.create_server(0, session=DoneSession(), diag_log='/tmp/s2-local-diag.jsonl')
local_setup._write_state_file('/tmp/s2-local-state.json', srv)
srv.serve_forever()
"""
    daemon_lf = open("/tmp/s2-local-daemon.log", "w", encoding="utf-8")
    daemon_proc = subprocess.Popen(["python3", "-c", runner_code], stdout=daemon_lf, stderr=subprocess.STDOUT)
    for _ in range(50):
        if Path("/tmp/s2-local-state.json").is_file():
            break
        time.sleep(0.1)
    assert Path("/tmp/s2-local-state.json").is_file(), "daemon state file missing"

    cli_env = dict(
        os.environ,
        OWNLINE_LOCAL_STATE="/tmp/s2-local-state.json",
        OWNLINE_DIAG_LOG="/tmp/s2-local-diag.jsonl",
        OWNLINE_HEADLESS="1",
    )
    captured_outputs = []

    def run_cli(args, tty_secret=None):
        cmd = ["python3", "/opt/ownline-repo/ownline.py"] + list(args)
        if tty_secret is None:
            p = subprocess.run(cmd, env=cli_env, cwd="/opt/ownline-repo", capture_output=True, text=True, timeout=60)
            captured_outputs.append((args, p.returncode, p.stdout, p.stderr))
            return p.returncode, p.stdout, p.stderr
        master_fd, slave_fd = pty.openpty()
        def _attach_tty():
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        p = subprocess.Popen(
            cmd,
            env=cli_env,
            cwd="/opt/ownline-repo",
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=slave_fd,
            preexec_fn=_attach_tty,
            text=True,
        )
        os.close(slave_fd)
        pty_buf = b""
        sent = False
        deadline = time.time() + 20
        try:
            while time.time() < deadline:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if r:
                    try:
                        chunk = os.read(master_fd, 4096)
                        if chunk:
                            pty_buf += chunk
                    except OSError:
                        pass
                if not sent and (b":" in pty_buf or b"\xff" in pty_buf or len(pty_buf) > 4):
                    os.write(master_fd, (tty_secret + "\n").encode("utf-8"))
                    sent = True
                if p.poll() is not None:
                    break
            if p.poll() is None:
                p.kill()
                raise TimeoutError(f"CLI TTY timeout for {args}: pty={pty_buf!r}")
            out, err = p.communicate(timeout=5)
        finally:
            os.close(master_fd)
        captured_outputs.append((args, p.returncode, out, pty_buf.decode("utf-8", "replace") + (err or "")))
        return p.returncode, out, pty_buf.decode("utf-8", "replace")

    rc, doc_out, doc_err = run_cli(["doctor", "--json"])
    doc = json.loads(doc_out)
    assert rc in (0, 1) and doc["python_ok"] is True and doc["daemon_running"] is True and all(doc["web_bundles"].values()), (doc_out, doc_err)

    rc, cap_out, _ = run_cli(["cap", "list", "--json"])
    assert rc == 0, cap_out
    caps = {c["name"] for c in json.loads(cap_out)["capabilities"]}
    assert {"panel-password", "residential-isp", "relay-expand", "topology-verify"}.issubset(caps)

    rc, vh_panel_out, vh_panel_err = run_cli(
        ["vault", "request", "--slot", "panel_auth", "--hint", "https://localhost:8443/", "--json"],
        tty_secret=NEW_PANEL_PWD,
    )
    assert rc == 0, (vh_panel_out, vh_panel_err)
    h_new_panel = json.loads(vh_panel_out)["handle"]

    rc, vh_isp_out, vh_isp_err = run_cli(
        ["vault", "request", "--slot", "webshare_isp", "--json"],
        tty_secret=f'curl --proxy "socks5://{WS_USER}:{WS_PASS}@10.202.0.2:11080"',
    )
    assert rc == 0, (vh_isp_out, vh_isp_err)
    h_isp = json.loads(vh_isp_out)["handle"]

    plan = {
        "panel": {"insecure_tls": True},
        "rotate_initial_password": {"new_panel_handle": h_new_panel},
        "residential_isp": {"isp_handle": h_isp},
        "relay": {"method": "reverse_join", "role": "relay", "name": "北京黑盒中继-01"},
        "verify": {"quick": False, "check_subscription": True},
    }
    plan_json = json.dumps(plan, ensure_ascii=False)

    # Dry-run MUST leave initial password lock intact.
    rc, dry_out, dry_err = run_cli(["apply", "--plan-json", plan_json, "--dry-run", "--json"])
    assert rc == 0, (dry_out, dry_err)
    assert Path("/opt/web-data/.initial-password-required").exists(), "dry-run mutated password gate!"

    # Live apply: password rotation (real Caddy reload) -> ISP mount (real sing-box + real SOCKS5 probe) -> relay token -> verify!
    rc, apply_out, apply_err = run_cli(["apply", "--plan-json", plan_json, "--json"])
    assert rc == 0, (apply_out, apply_err)
    applied = json.loads(apply_out)
    assert applied["ok"] is True, applied
    assert not Path("/opt/web-data/.initial-password-required").exists(), "initial password marker still exists!"
    assert ws_proxy.tcp_hits >= 1, "sing-box did not probe through real SOCKS5 ISP proxy!"

    step_results = {s["capability"]: s["result"] for s in applied["steps"]}
    assert step_results["residential-isp"]["exit_ip"] == "10.204.0.2", step_results["residential-isp"]
    assert step_results["relay-expand"]["join_command"].startswith("curl "), step_results["relay-expand"]
    assert step_results["topology-verify"]["drifted_count"] == 0, step_results["topology-verify"]
    assert step_results["topology-verify"]["subscription"]["clash_ok"] is True, step_results["topology-verify"]

    # Extra black-box proof: fetch live /s/<token>/clash over HTTPS from Caddy and validate with REAL mihomo -t!
    c2 = http.client.HTTPSConnection("localhost", 8443, context=ssl_ctx, timeout=5)
    c2.request("GET", f"/s/{SUB_TOKEN}/clash", headers={"Host": "localhost:8443"})
    sub_resp = c2.getresponse()
    clash_yaml = sub_resp.read().decode("utf-8")
    c2.close()
    assert sub_resp.status == 200, sub_resp.status
    with tempfile.TemporaryDirectory() as mh_td:
        shutil.copy("/etc/mihomo/geoip.metadb", os.path.join(mh_td, "geoip.metadb"))
        cfg_file = Path(mh_td) / "sub.yaml"
        cfg_file.write_text(clash_yaml, encoding="utf-8")
        chk = run_cmd(["/usr/local/bin/mihomo", "-t", "-d", mh_td, "-f", str(cfg_file)], check=False)
        assert chk.returncode == 0, chk.stdout + chk.stderr

    # Verify old password now fails (401) and new password works (200).
    for pwd, expect_code in ((TEMP_PWD, 401), (NEW_PANEL_PWD, 200)):
        c3 = http.client.HTTPSConnection("localhost", 8443, context=ssl_ctx, timeout=5)
        c3.request("GET", "/api/nodes", headers={"Host": "localhost:8443", "Authorization": "Basic " + base64.b64encode(f"admin:{pwd}".encode()).decode()})
        st3 = c3.getresponse().status
        c3.close()
        assert st3 == expect_code, (pwd, st3, expect_code)

    rc, _, _ = run_cli(["logs", "--limit", "50", "--json"])
    assert rc == 0
    rc, _, _ = run_cli(["vault", "clear", "--json"])
    assert rc == 0
    rc, _, _ = run_cli(["stop", "--json"])
    assert rc == 0

    diag_text = Path("/tmp/s2-local-diag.jsonl").read_text(encoding="utf-8")
    canary_corpus = diag_text + "\n" + "\n".join(o + "\n" + e for _, _, o, e in captured_outputs)
    canaries = [TEMP_PWD, NEW_PANEL_PWD, WS_USER, WS_PASS, SUB_TOKEN]
    leaked = [c_str for c_str in canaries if c_str in canary_corpus or base64.b64encode(c_str.encode()).decode() in canary_corpus]
    assert not leaked, f"secret canaries leaked: {leaked}"

    print("S2_BLACKBOX_REPORT:" + json.dumps({
        "ok": True,
        "initial_gate_enforced_403": True,
        "password_rotated_caddy_reloaded": True,
        "isp_socks_tcp_hits": ws_proxy.tcp_hits,
        "isp_verified_exit_ip": step_results["residential-isp"]["exit_ip"],
        "reconcile_drifted_count": step_results["topology-verify"]["drifted_count"],
        "mihomo_subscription_valid": True,
        "leaked_secrets": 0,
    }, ensure_ascii=False))
finally:
    subprocess.run(["systemctl", "stop", "sing-box"], check=False, capture_output=True)
    for proc in (daemon_proc, caddy_proc, admin_proc, cam_proc):
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    echo_srv.shutdown()
    echo_srv.server_close()
    doh_srv.stop()
    if ws_proxy.srv:
        ws_proxy.srv.shutdown()
        ws_proxy.srv.server_close()
'''


def _build_bundle() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(ROOT / "ownline.py", arcname="ownline.py")
        tf.add(ROOT / "requirements.lock", arcname="requirements.lock")
        for folder in ("server", "web", "deploy", "scripts", "skills"):
            src = ROOT / folder
            if not src.exists():
                continue
            tf.add(
                src,
                arcname=folder,
                filter=lambda ti: None if ("__pycache__" in ti.name or ti.name.endswith(".pyc") or ".ops-private" in ti.name) else ti,
            )
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage S2 isolated Docker black-box verification.")
    parser.add_argument("--image", default="ownline-phase4-lab:latest")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload_b64 = base64.b64encode(_build_bundle()).decode("ascii")
    runner = (
        "import base64, pathlib\n"
        f"pathlib.Path('/tmp/ownline-s2-src.tgz').write_bytes(base64.b64decode({payload_b64!r}))\n"
        + _CONTAINER_SCRIPT
    )

    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--cap-add", "NET_ADMIN", "-i", args.image, "python3", "-"],
        input=runner,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return proc.returncode

    marker = "S2_BLACKBOX_REPORT:"
    report = None
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            report = json.loads(line[len(marker):])
            break
    if report is None:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("OK: S2 Docker black-box verification passed:", json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
