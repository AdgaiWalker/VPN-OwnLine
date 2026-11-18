#!/usr/bin/env python3
import base64, datetime, hmac, json, os, re, secrets, subprocess, sys, tempfile, threading, time, urllib.parse, uuid
from collections import deque
from pathlib import Path
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = "/opt/web"
DATA = os.environ.get("LADDER_DATA", "/opt/web-data")
MAX_BODY = 1_000_000  # 1MB：私钥最多几 KB，超了就是有人在搞事
from nodekit import verify as verify_mod  # noqa: E402
from nodekit import advise as advise_mod  # noqa: E402
from nodekit import hints as hints_mod  # noqa: E402
from nodekit import subscriptions as subs_mod  # noqa: E402
from nodekit import logger  # noqa: E402
from nodekit import repair as repair_mod  # noqa: E402
from nodekit import lifecycle as lifecycle_mod  # noqa: E402
from nodekit import quota_guard as quota_mod  # noqa: E402
from nodekit import node_check_bridge  # noqa: E402
from nodekit import links as links_mod  # noqa: E402
from nodekit import templates as templates_mod  # noqa: E402
from nodekit import remote_config as remote_cfg_mod  # noqa: E402
from nodekit import http_utils  # noqa: E402
from nodekit import system_updater as updater_mod  # noqa: E402
from nodekit import ai_feedback as ai_feedback_mod  # noqa: E402
from nodekit import join_token as join_token_mod  # noqa: E402
from nodekit import installations as install_mod  # noqa: E402
from nodekit.node_manager import FileNodeStore, NodeManager, NodeManagerError  # noqa: E402
import reset_admin_password as password_mod  # noqa: E402
import tencent_discovery as tencent_discovery_mod  # noqa: E402
sys.path.insert(0, WEB)
NODES = os.path.join(DATA, "nodes.json")
CADDY = "/etc/caddy/Caddyfile"
JOBS = {}
CHECKED_TARGETS = install_mod.CheckedTargets()
_INSTALL_LOCK = threading.Lock()
INITIAL_PASSWORD_MARKER = Path(DATA) / '.initial-password-required'
_PASSWORD_LOCK = threading.Lock()
_PASSWORD_ATTEMPTS = deque()


def join_base_url(host):
    host = (host or "").strip()
    if not re.fullmatch(r"(?:[A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]{1,5})?", host):
        return None
    return "https://" + host

node_manager = NodeManager(
    store=FileNodeStore(lambda: NODES),
    remote_cfg_mod=remote_cfg_mod,
    links_mod=links_mod,
    logger=logger,
    open_firewall_fn=lambda ip, port, proto="TCP": open_firewall(ip, port, proto),
    on_change=lambda: render(),
)


def load_nodes():
    return node_manager.list_nodes()


def save_nodes(nodes):
    node_manager.save_nodes(nodes)


def update_nodes(mutator):
    """读-改-写 全程持锁，避免两个任务同时改导致丢更新。"""
    return node_manager.update_nodes(mutator)

def get_sub_token():
    """获取订阅 token：优先读 settings.json，兜底从 Caddyfile 解析。"""
    try:
        s = _load_json("settings.json", {})
        if s.get("sub_token"):
            return str(s["sub_token"])
    except Exception:
        pass
    try:
        with open(CADDY, encoding="utf-8") as f:
            m = re.search(r"/s/([0-9a-fA-F]{8,64})", f.read())
            if m:
                return m.group(1)
    except Exception:
        pass
    return ""

def render():
    # 只要 nodes.json 变动，先保证内部数据一致
    # 若配置为 builtin（原生内置订阅），完全无需正则改写 Caddyfile 或 reload
    settings = _load_json("settings.json", {})
    if settings.get("sub_backend", "builtin") == "builtin":
        return
    # 兼容过渡阶段：若显式指定 subconverter，保留旧逻辑
    try:
        nodes = [n for n in load_nodes() if subs_mod.in_subscription(n)]
        src = urllib.parse.quote("|".join(links_mod.build_link(n) for n in nodes), safe="")
        with open(CADDY, encoding="utf-8") as f:
            txt = f.read()
        new = re.sub(r"url=[^&\s]+", "url=" + src, txt, count=1)
        if new != txt:
            with open(CADDY, "w", encoding="utf-8") as f:
                f.write(new)
            subprocess.run(["systemctl", "reload", "caddy"], check=True, capture_output=True)
    except Exception:
        pass

def _gen_node():
    """生成一套节点参数（uuid / reality 密钥对 / short_id / hy2 password / obfs）。"""
    binp = "/opt/sing-box/sing-box"
    try:
        uid = subprocess.check_output([binp, "generate", "uuid"], text=True).strip()
        kp = subprocess.check_output([binp, "generate", "reality-keypair"], text=True)
        priv = re.search(r"PrivateKey:\s*(\S+)", kp).group(1)
        pub = re.search(r"PublicKey:\s*(\S+)", kp).group(1)
    except Exception:
        raise RuntimeError("sing-box 密钥生成失败，未启动安装") from None
    cert, cert_key = remote_cfg_mod.generate_self_signed_cert_pem("www.bing.com")
    return {
        "uuid": uid,
        "private_key": priv,
        "pbk": pub,
        "sid": os.urandom(4).hex(),
        "sni": "www.apple.com",
        "hy2_password": os.urandom(12).hex(),
        "obfs_password": os.urandom(8).hex(),
        "hy2_sni": "www.bing.com",
        "hy2_cert_b64": base64.b64encode(cert.encode()).decode(),
        "hy2_key_b64": base64.b64encode(cert_key.encode()).decode(),
        "initial_password": secrets.token_urlsafe(16),
    }


def _write_job(jid, data, secret):
    """Compatibility adapter: installation inputs live only in worker memory."""
    spec = dict(data)
    spec["private_key" if data.get("auth_type") == "key" else "password"] = secret
    return spec


def run_job(jid, spec):
    j = JOBS[jid]
    j["state"] = "running"
    process = None
    checked = spec.pop("checked_target", None)
    try:
        if not checked:
            raise install_mod.InstallError("缺少已验证的安装目标")
        install_mod.CheckedTargets.recheck(checked, node_check_bridge.check)
        if not spec.get("dry_run"):
            install_mod.pin_known_host(checked, verify_mod.KNOWN_HOSTS)
        login = checked["login"]
        identity = checked["identity"]
        spec.update(ip=identity[0], user=login["username"], ssh_port=login["ssh_port"],
                    password=login.get("password", ""), private_key=login.get("private_key", ""),
                    auth_type="key" if login.get("private_key") else "password",
                    passphrase=login.get("passphrase", ""), machine_id=identity[2],
                    host_key_type=identity[3], host_key=identity[4])
        ports = {(int(spec.get("port") or 443), "TCP"), (int(spec.get("port") or 443), "UDP")}
        if spec.get("self_bootstrap"):
            ports.update({(80, "TCP"), (8443, "TCP")})
        for port, protocol in ([] if spec.get("dry_run") else sorted(ports)):
            try:
                status, _ = open_firewall(identity[0], port, proto=protocol)
                if status not in ("opened", "already"):
                    j["log"].append("云防火墙未确认放行 %s/%s，请核对云安全组" % (port, protocol))
            except Exception:
                j["log"].append("云防火墙未确认，请核对云安全组")
        process = subprocess.Popen(["/opt/web/addnode.sh", "--stdin"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
        process.stdin.write(json.dumps(spec, ensure_ascii=False))
        process.stdin.close()
        records, candidate = [], None
        for line in process.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("STEP "):
                parts = line.split(" ", 2)
                j["step"] = int(parts[1])
                j["stepname"] = parts[2] if len(parts) > 2 else ""
            elif line.startswith("{"):
                event = json.loads(line)
                if "delivery" in event:
                    candidate = event["delivery"]
                elif event.get("name") and event.get("host"):
                    records.append(event)
                continue
            # Secret material and raw node events never enter progress logs.
            for key in ("password", "private_key", "passphrase", "control_secret"):
                if spec.get(key):
                    line = line.replace(spec[key], "[redacted]")
            j["log"] = (j["log"] + [line])[-60:]
        if process.wait() != 0:
            raise install_mod.InstallError("目标安装未完成，请检查服务器状态后重新检测")
        if spec.get("dry_run"):
            j.update(state="done", warn="dry_run")
            return
        if not records:
            raise install_mod.InstallError("安装没有返回节点记录，未交付资产")
        main = next((n for n in records if n.get("type") != "hysteria2"), None)
        if main is None:
            raise install_mod.InstallError("安装没有返回主节点，未交付资产")
        for record in records:
            record.update(control_secret=spec["control_secret"], provenance_id=identity[0])
            verification = verify_mod.run(record)
            record.update(health=verification.get("health", "unknown"),
                          health_detail=verification.get("detail", ""))
            for key in ("exit_ip", "exit_country"):
                if verification.get(key):
                    record[key] = verification[key]
            node_manager.add_node(record)
            if record is main:
                j["node"], j["verify"] = record, verification
        if any(record.get("health") != "ok" for record in records):
            raise install_mod.InstallError("节点已安装但真实代理验收未通过，未交付可用资产")
        if spec.get("self_bootstrap"):
            if not candidate:
                raise install_mod.InstallError("独立后台未完成部署，未交付管理地址")
            delivery = install_mod.verify_delivery(candidate, identity[0], spec["node"]["initial_password"])
            delivery["deep_links"] = links_mod.build_deep_links(delivery["direct_sub_url"], name=main["name"])
            j["delivery"] = delivery
        else:
            j["delivery"] = {"kind": "managed_node", "node_name": main["name"]}
        j["state"] = "done"
    except Exception as exc:
        j.update(state="error", error=str(exc) if isinstance(exc, install_mod.InstallError) else
                 "安装或验收未完成，请重新检查服务器状态", error_code=type(exc).__name__)
        j.pop("delivery", None)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if checked:
            checked["login"].clear()
        spec.clear()


import base64 as _b64

def _py_patch(uuid_new, port_new, cfg="/opt/sing-box/config.json"):
    parts = ["import json", "p=%r" % cfg, "d=json.load(open(p))"]
    parts.append("for ib in d.get('inbounds',[]):")
    parts.append("    if ib.get('type')=='vless' and ib.get('users'):")
    if uuid_new:
        parts.append("        ib['users'][0]['uuid']=%r" % uuid_new)
    if port_new:
        parts.append("        ib['listen_port']=%d" % port_new)
    if not uuid_new and not port_new:
        parts.append("        pass")
    parts.append("json.dump(d,open(p,'w'),indent=1)")
    return "\n".join(parts) + "\n"

def _ps_patch(uuid_new, port_new):
    lines = ["$p='C:\\proxy\\config.json'", "$j = Get-Content $p -Raw | ConvertFrom-Json"]
    lines.append("$j.inbounds | Where-Object { $_.type -eq 'vless' } | ForEach-Object {")
    if uuid_new:
        lines.append("  $_.users[0].uuid = '%s'" % uuid_new)
    if port_new:
        lines.append("  $_.listen_port = %d" % port_new)
    lines.append("}")
    lines.append("$j | ConvertTo-Json -Depth 12 | Set-Content $p -Encoding utf8")
    lines.append("Stop-ScheduledTask -TaskName sing-box")
    lines.append("Start-ScheduledTask -TaskName sing-box")
    return "; ".join(lines)

def _build_sub_url(settings, host_header):
    token = settings.get("sub_token") or get_sub_token()
    domain = settings.get("domain") or (host_header or "").split(":")[0] or "localhost"
    port = settings.get("sub_port")
    if port:
        port_part = "" if int(port) in (80, 443) else (":%s" % port)
    elif ":8443" in (host_header or ""):
        port_part = ":8443"
    elif domain and domain != "localhost" and not (host_header or "").endswith(":443"):
        port_part = ":8443"
    else:
        port_part = ""
    return domain, token, "https://%s%s/s/%s" % (domain, port_part, token)


def patch_remote(node, uuid_new=None, port_new=None):
    # 旧 sing-box 的服务与配置可能被其他业务共用，当前无法可靠证明独占。
    return False, "无法确认服务由本项目独占，未修改服务器；请人工检查"

import ipaddress as _ip

def _valid_host(h):
    if not h or len(h) > 253:
        return False
    try:
        _ip.ip_address(h)
        return True
    except Exception:
        pass
    return re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+", h) is not None

import socket as _socket

def open_firewall(ip, port, proto="TCP"):
    import providers
    st, msg, who = providers.open_port(ip, port, proto=proto)
    return (st, msg)


def port_reachable(host, port, timeout=6):
    try:
        s = _socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False

def verify_node(node):
    """跑一次自测，把结果写回 nodes.json。"""
    r = verify_mod.run(node)

    def _apply(nodes):
        for n in nodes:
            if n.get("name") == node.get("name"):
                n["health"] = r["health"]
                if r.get("exit_ip"):
                    n["exit_ip"] = r["exit_ip"]
                    n["exit_country"] = r.get("exit_country", "")
                if r.get("detail"):
                    n["health_detail"] = r["detail"]
        return nodes

    update_nodes(_apply)
    render()
    return r


def verify_async(name):
    def _run():
        try:
            nodes = load_nodes()
            node = next((n for n in nodes if n.get("name") == name), None)
            if node:
                verify_node(node)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def _load_json(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    """Atomically write sensitive settings with owner-only file permissions."""
    fd, tmp = tempfile.mkstemp(prefix=".ownline-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def nodes_with_advice():
    """节点 + 一句建议（依据来自探活与流量），以及全生命周期状态。"""
    status = _load_json("status.json", {})
    usage = _load_json("usage.json", {})
    out = []
    for n in load_nodes():
        n = dict(n)
        host = n.get("host")
        u_data = usage.get(host) if isinstance(usage.get(host), dict) else {}
        reset_day = quota_mod.parse_reset_day(n.get("reset_day") or u_data.get("reset_day") or u_data.get("end"))
        if reset_day is not None:
            n["reset_day"] = reset_day
        n["advice"] = advise_mod.advise(n, status.get(n.get("name")), u_data)
        n["lifecycle"] = lifecycle_mod.get_lifecycle_state(n)
        out.append(n)
    return out


class H(BaseHTTPRequestHandler):
    timeout = 30  # 单连接最长 30 秒，防慢速攻击占线程
    def _json(self, code, obj):
        http_utils.send_json(self, code, obj)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        path = path.rstrip("/")
        norm_path = http_utils.normalize_api_path(path)

        # Ultra-lightweight RTT probe endpoint for client latency measurement
        if norm_path == "/ping":
            self.send_response(204)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # 免密反向自举脚本分发路由（供 VPS 终端一键 curl 执行）
        if path.startswith("/join/"):
            token = path.split("/join/", 1)[1].strip()
            info = join_token_mod.verify_token(token)
            if not info:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Error: Token is invalid or expired\n")
                return
            base_url = join_base_url(self.headers.get("Host") or "127.0.0.1")
            if not base_url:
                return self._json(400, {"ok": False, "error": "无效的主控地址"})
            script = join_token_mod.generate_install_script(
                token=token,
                server_url=base_url,
                role=info.get("role", "exit"),
                landing=info.get("landing"),
                port=info.get("port"),
            )
            content = script.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # This gate is also invoked by Caddy before every management route.
        if norm_path == "/password-gate":
            if INITIAL_PASSWORD_MARKER.exists():
                self.send_response(303)
                self.send_header('Location', '/change-password')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
            else:
                self.send_response(204)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
            return
        if norm_path == "/password/state":
            return self._json(200, {'ok': True, 'required': INITIAL_PASSWORD_MARKER.exists()})
        if norm_path == "/user":
            user = ''
            auth = self.headers.get('Authorization', '')
            if auth.startswith('Basic '):
                try:
                    cred = base64.b64decode(auth[6:].strip()).decode('utf-8', errors='ignore')
                    if ':' in cred:
                        user = cred.split(':', 1)[0]
                except Exception:
                    pass
            if not user and password_mod.CADDYFILE.exists():
                try:
                    _, user, _ = password_mod.inspect_credentials(password_mod.CADDYFILE.read_text(encoding='utf-8'))
                except Exception:
                    try:
                        raw = password_mod.CADDYFILE.read_text(encoding='utf-8')
                        m = re.search(r'basic_auth\s*\{[^}]*?([A-Za-z0-9_.-]{1,64})\s+\$2[aby]?\$', raw, re.DOTALL)
                        if m:
                            user = m.group(1)
                    except Exception:
                        pass
            return self._json(200, {'ok': True, 'username': user or 'admin'})
        if INITIAL_PASSWORD_MARKER.exists() and not path.startswith('/s/'):
            return self._json(403, {'ok': False, 'error': '请先修改初始管理密码'})

        # Caddy runs as an unprivileged user and cannot traverse DATA (0700).
        # Serve only this fixed public snapshot set after the password gate.
        if norm_path in ('/status.json', '/servers.json', '/usage.json', '/quota.json'):
            try:
                with open(os.path.join(DATA, norm_path[1:]), encoding='utf-8') as source:
                    snapshot = json.load(source)
            except FileNotFoundError:
                return self._json(404, {'ok': False, 'error': '状态快照尚未生成'})
            except (OSError, ValueError):
                return self._json(503, {'ok': False, 'error': '状态快照暂不可用'})
            return self._json(200, snapshot)

        # 订阅路由：仅放行携带合法高熵 token 的 /s/<token>[/clash|/sr]，拒绝裸 /sub 与空 token
        token = get_sub_token()
        client_ip = (self.headers.get("X-Forwarded-For") or self.client_address[0] or "").split(",")[0].strip()
        if path.startswith("/s/") or path == "/sub":
            parts = path.split("/")
            req_token = parts[2] if (path.startswith("/s/") and len(parts) > 2) else ""
            if not token or not req_token or not hmac.compare_digest(req_token, token):
                logger.log("WARN", "SUB", f"非法订阅请求 (IP={client_ip})")
                return self._json(404, {"ok": False, "error": "invalid subscription token"})

            ua = self.headers.get("User-Agent", "Unknown")
            nodes = load_nodes()
            usage_data = _load_json("usage.json", {})
            resp = subs_mod.SubscriptionEngine.handle_request(
                nodes=nodes,
                path=path,
                qs=qs,
                user_agent=ua,
                usage_data=usage_data,
            )
            if resp.get("status") == 200:
                logger.log("INFO", "SUB", f"拉取订阅 (IP={client_ip}, 格式={resp['format']}, 场景={resp['profile']}, UA={ua[:30]}, 节点数={resp['node_count']})")
            self.send_response(resp["status"])
            for h_k, h_v in resp["headers"]:
                self.send_header(h_k, h_v)
            self.end_headers()
            self.wfile.write(resp["body"])
            return

        if norm_path == "/backup":
            nodes = load_nodes()
            token = get_sub_token()
            vless_links = [subs_mod.node_uri(n) for n in nodes if subs_mod.in_subscription(n)]
            data = {
                "ok": True,
                "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "node_count": len(nodes),
                "nodes": nodes,
                "sub_token": token,
                "links": vless_links,
            }
            content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="ladder-nodes-backup.json"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if norm_path == "/qr":
            q = urllib.parse.parse_qs(qs)
            raw_url = (q.get("url") or [None])[0]
            if not raw_url:
                settings = _load_json("settings.json", {})
                _, _, raw_url = _build_sub_url(settings, self.headers.get("Host"))
            try:
                p = subprocess.run(["qrencode", "-o", "-", "-s", "8", "-m", "2", "-t", "PNG", raw_url],
                                   capture_output=True, timeout=5)
                if p.returncode == 0 and p.stdout:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(p.stdout)))
                    self.send_header("Cache-Control", "private, no-cache")
                    self.end_headers()
                    self.wfile.write(p.stdout)
                    return
            except Exception:
                pass
            static_qr = os.path.join(WEB, "qr-sub.png")
            if os.path.exists(static_qr):
                try:
                    data = open(static_qr, "rb").read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "private, no-cache")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    pass
            return self._json(404, {"ok": False, "error": "QR code unavailable"})

        if norm_path in ("/nodes", ""):
            return self._json(200, nodes_with_advice())
        if norm_path == "/logs":
            q = urllib.parse.parse_qs(qs)
            try:
                limit = int((q.get("limit") or ["100"])[0])
            except Exception:
                limit = 100
            lvl = (q.get("level") or ["ALL"])[0]
            src = (q.get("src") or ["ALL"])[0]
            return self._json(200, {
                "ok": True,
                "logs": logger.read_logs(limit=limit, level_filter=lvl, src_filter=src)
            })
        if norm_path == "/syslogs":
            q = urllib.parse.parse_qs(qs)
            service = (q.get("service") or ["sing-box"])[0]
            try:
                lines = int((q.get("lines") or ["50"])[0])
            except Exception:
                lines = 50
            res = logger.get_syslog(service, lines=lines)
            return self._json(200 if res.get("ok") else 400, res)
        if norm_path == "/ping":
            try:
                import probe as probe_mod
                nodes = load_nodes()
                settings = _load_json("settings.json", {})
                cn = probe_mod.cn_probe(nodes, preferred_vantage=settings.get("probe_vantage"))
                status = _load_json("status.json", {})
                if cn:
                    for name, cinfo in cn.items():
                        if name in status and isinstance(cinfo, dict):
                            status[name].update(cinfo)
                    status["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    tmp = os.path.join(DATA, "status.json.tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(status, f, ensure_ascii=False)
                    os.replace(tmp, os.path.join(DATA, "status.json"))
                return self._json(200, {"ok": True, "status": status})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if norm_path == "/system/version":
            return self._json(200, updater_mod.get_version_info())
        if norm_path == "/system/upgrade-status":
            job_id = (urllib.parse.parse_qs(qs).get("id") or [""])[0]
            result = updater_mod.upgrade_status(job_id)
            return self._json(200 if result.get("ok") else 404, result)
        if norm_path == "/system/check_update":
            q = urllib.parse.parse_qs(qs)
            force = (q.get("force") or ["0"])[0].lower() in ("1", "true", "yes")
            return self._json(200, updater_mod.check_update(force=force))
        if norm_path in ("/feedback/analysis", "/feedback/summary"):
            fb_file = os.path.join(DATA, "feedback.jsonl")
            items = []
            if os.path.exists(fb_file):
                try:
                    with open(fb_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                items.append(json.loads(line))
                except Exception:
                    pass
            nodes = _load_json("nodes.json", [])
            analysis = ai_feedback_mod.analyze_feedback_entries(items, active_nodes=nodes)
            return self._json(200, analysis)
        if norm_path == "/feedback":
            fb_file = os.path.join(DATA, "feedback.jsonl")
            items = []
            if os.path.exists(fb_file):
                try:
                    with open(fb_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                items.append(json.loads(line))
                except Exception:
                    pass
            return self._json(200, {"ok": True, "feedback": items[-50:][::-1]})
        if norm_path == "/probe/vantage":
            settings = _load_json("settings.json", {})
            return self._json(200, {"ok": True, "vantage": settings.get("probe_vantage")})
        if norm_path == "/settings":
            settings = _load_json("settings.json", {})
            domain, token, sub_url = _build_sub_url(settings, self.headers.get("Host"))
            tc_ready = os.path.exists(os.path.join(DATA, "tc.json"))
            return self._json(200, {
                "ok": True,
                "version": updater_mod.CURRENT_VERSION,
                "domain": domain,
                "sub_token": token,
                "sub_url": sub_url,
                "probe_vantage": settings.get("probe_vantage"),
                "quota_threshold": quota_mod.quota_threshold(),
                "tencent_discovery": True,
                "tencent_configured": tc_ready,
                "backup_restore_supported": True,
                "node_check_supported": node_check_bridge.available(),
            })
        if norm_path == "/relay/status":
            nodes = load_nodes()
            status = _load_json("status.json", {})
            relay_node = next((n for n in nodes if n.get("role") == "relay"), None)
            exits = [
                n for n in nodes
                if n.get("type") != "hysteria2"
                and n.get("role") not in ("relay", "standalone")
                and (n.get("exit_country") or "").upper() != "CN"
            ]
            lp = dict((relay_node or {}).get("landing_policy") or {})
            landing = dict((relay_node or {}).get("landing") or {})
            primary_cfg = lp.get("primary") or (
                {"host": landing["host"], "name": landing.get("name") or landing["host"], "port": landing.get("port", 443)}
                if landing.get("host")
                else ({"host": exits[0]["host"], "name": exits[0].get("name", exits[0]["host"]), "port": exits[0].get("port", 443)} if exits else None)
            )
            fallback_cfg = lp.get("fallback") or (
                {"host": exits[1]["host"], "name": exits[1].get("name", exits[1]["host"]), "port": exits[1].get("port", 443)}
                if len(exits) > 1 and primary_cfg and exits[1].get("host") != primary_cfg.get("host")
                else None
            )
            primary_st = (status.get((primary_cfg or {}).get("name") or "") or {}) if primary_cfg else {}
            fallback_st = (status.get((fallback_cfg or {}).get("name") or "") or {}) if fallback_cfg else {}
            active_target = lp.get("active_target") or landing.get("host") or ((primary_cfg or {}).get("host"))
            return self._json(200, {
                "ok": True,
                "configured": relay_node is not None,
                "node": (relay_node or {}).get("name"),
                "landing_policy": lp,
                "primary": ({
                    "name": primary_cfg.get("name"),
                    "host": primary_cfg.get("host"),
                    "ok": primary_st.get("ok", True),
                    "ms": primary_st.get("ms"),
                } if primary_cfg else None),
                "fallback": ({
                    "name": fallback_cfg.get("name"),
                    "host": fallback_cfg.get("host"),
                    "ok": fallback_st.get("ok", True),
                    "ms": fallback_st.get("ms"),
                } if fallback_cfg else None),
                "active_target": active_target,
                "auto_failover": bool(primary_cfg and fallback_cfg),
            })
        if norm_path == "/quota/guard":
            usage = _load_json("usage.json", {})
            eval_res = quota_mod.evaluate_all(usage)
            stopped = quota_mod.stopped_hosts()
            known_nodes = {}
            for node in load_nodes():
                if node.get("host"):
                    known_nodes.setdefault(node["host"], []).append(node)
            guards = []
            for ip, host_nodes in known_nodes.items():
                node = host_nodes[0]
                u = eval_res.get(ip) or quota_mod.evaluate_instance_quota(None)
                raw_u = usage.get(ip) if isinstance(usage.get(ip), dict) else {}
                used_val = u.get("used_gb") if u.get("used_gb") is not None else raw_u.get("used")
                r_day = u.get("reset_day") or quota_mod.parse_reset_day(node.get("reset_day") or raw_u.get("reset_day") or raw_u.get("end"))
                guards.append({
                    "ip": ip,
                    "name": node.get("name", ip),
                    "used_gb": used_val,
                    "total_gb": u.get("total_gb"),
                    "percent": u.get("percent"),
                    "status": u.get("status", "unknown"),
                    "source": raw_u.get("source", "cloud_api"),
                    "control_supported": all(quota_mod.supports_quota_control(n) for n in host_nodes),
                    "paused": ip in stopped,
                    "reset_day": r_day,
                })
            return self._json(200, {
                "ok": True,
                "watermarks": eval_res.get("_summary", {}).get("watermarks", {"warning": 75, "tripped": 85}),
                "usage_fresh": quota_mod.usage_is_fresh(usage),
                "guards": guards,
            })
        if norm_path == "/node/job":
            q = urllib.parse.parse_qs(qs)
            jid = (q.get("id") or [""])[0]
            if not re.fullmatch(r"[a-f0-9]{12}", jid):
                return self._json(400, {"ok": False, "error": "任务编号无效"})
            job = JOBS.get(jid)
            if not job:
                return self._json(404, {"ok": False, "error": "任务状态未知"})
            # Do not return raw logs or node credentials in the progress view.
            verification = job.get("verify") or {}
            res = {
                "ok": True,
                "state": job.get("state", "unknown"),
                "step": job.get("step", 0),
                "stepname": job.get("stepname", ""),
                "health": verification.get("health", "unknown"),
            }
            if job.get("error"):
                res["error"] = job["error"]
                res["error_code"] = job.get("error_code", "INSTALL_FAILED")
            if job.get("delivery"):
                res["delivery"] = job["delivery"]
            return self._json(200, res)
        if norm_path == "/job":
            q = urllib.parse.parse_qs(qs)
            jid = (q.get("id") or [""])[0]
            j = JOBS.get(jid)
            if not j:
                return self._json(404, {"ok": False, "error": "job not found"})
            out = {"ok": True, "state": j["state"], "step": j.get("step", 0),
                   "stepname": j.get("stepname", ""), "log": j["log"][-14:]}
            if j.get("node"):
                out["node"] = j["node"]
            if j.get("warn"):
                out["warn"] = j["warn"]
            if j.get("error"):
                out["error"] = j["error"]
            if j.get("hint"):
                out["hint"] = j["hint"]
            if j.get("verify"):
                out["verify"] = j["verify"]
            if j.get("delivery"):
                out["delivery"] = j["delivery"]
            return self._json(200, out)
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not http_utils.validate_origin(self):
            return self._json(403, {"ok": False, "error": "跨站请求被拒绝"})
        path = self.path.rstrip("/")
        norm_path = http_utils.normalize_api_path(path)
        if INITIAL_PASSWORD_MARKER.exists() and norm_path not in ('/password/change', '/credentials/change', '/node/join', '/join/register'):
            return self._json(403, {'ok': False, 'error': '请先修改初始管理密码'})

        res = http_utils.parse_json_body(self, MAX_BODY)
        if isinstance(res, tuple) and len(res) == 2:
            if isinstance(res[0], int):
                code, body = res
            else:
                body, code = res[0], (200 if res[0] is not None else 400)
        else:
            body = res if isinstance(res, dict) else {}
        if body is None:
            return

        if norm_path in ('/password/change', '/credentials/change'):
            old = body.get('current')
            new = body.get('new')
            confirm = body.get('confirm')
            req_user = body.get('username')
            new_user = None
            if req_user is not None and isinstance(req_user, str) and req_user.strip():
                new_user = req_user.strip()
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', new_user):
                    return self._json(400, {'ok': False, 'error': '用户名格式无效，仅支持 1-64 位字母、数字、下划线、点或横线'})

            changing_password = bool(new or confirm)
            if changing_password:
                try:
                    valid = (isinstance(old, str) and isinstance(new, str) and isinstance(confirm, str) and
                             new == confirm and (new != old or bool(new_user)) and len(new) >= 12 and
                             len(new.encode()) <= 72 and not any(c in new for c in '\r\n\x00'))
                except UnicodeEncodeError:
                    valid = False
                if not valid:
                    return self._json(400, {'ok': False, 'error': '新密码至少 12 位，两次输入一致且不能与原密码相同'})
            else:
                if not isinstance(old, str) or not new_user:
                    return self._json(400, {'ok': False, 'error': '请输入当前密码以验证身份'})

            if not _PASSWORD_LOCK.acquire(blocking=False):
                return self._json(409, {'ok': False, 'error': '密码修改正在进行，请稍后重试'})
            try:
                now = time.monotonic()
                while _PASSWORD_ATTEMPTS and _PASSWORD_ATTEMPTS[0] < now - 300:
                    _PASSWORD_ATTEMPTS.popleft()
                if len(_PASSWORD_ATTEMPTS) >= 5:
                    return self._json(429, {'ok': False, 'error': '尝试次数过多，请稍后再试'})
                _PASSWORD_ATTEMPTS.append(now)
                with open(password_mod.LOCKFILE, 'w', encoding='utf-8') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    cfg = password_mod.CADDYFILE.read_text(encoding='utf-8')
                    domain, current_user, _ = password_mod.inspect_credentials(cfg)
                    if '# ownline-managed-password-v1\n' not in cfg or not password_mod.local_login(domain, old, '/change-password', username=current_user):
                        return self._json(403, {'ok': False, 'error': '当前密码不正确或配置不受支持'})
                    target_pwd = new if changing_password else old
                    target_user = new_user or current_user
                    password_mod.reset(password_mod.CADDYFILE, target_pwd, username=target_user)
                    INITIAL_PASSWORD_MARKER.unlink(missing_ok=True)
                _PASSWORD_ATTEMPTS.clear()
                return self._json(200, {'ok': True, 'message': '凭据已修改，请使用新凭据重新登录', 'username': target_user})
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                return self._json(500, {'ok': False, 'error': '暂时无法确认结果，请先尝试新密码；仍无法登录时在服务器终端检查'})
            finally:
                _PASSWORD_LOCK.release()

        if norm_path == "/system/upgrade":
            target_version = (body.get("target_version") or "").strip() or None
            res = updater_mod.trigger_upgrade(target_version=target_version)
            code = 200 if res.get("ok") else (409 if "进行中" in res.get("error", "") else 500)
            return self._json(code, res)

        if norm_path == "/feedback":
            fb_type = (body.get("type") or "general").strip()[:32]
            message = (body.get("message") or "").strip()
            contact = (body.get("contact") or "").strip()[:128]
            diagnostics = body.get("diagnostics")

            if not message:
                if diagnostics:
                    message = "一键现场诊断上报（未填写文字描述）"
                else:
                    return self._json(400, {"ok": False, "error": "反馈内容不能为空"})
            if len(message) > 4000:
                return self._json(400, {"ok": False, "error": "反馈内容过长，请控制在 4000 字以内"})

            client_ip = (self.headers.get("X-Forwarded-For") or self.client_address[0] or "").split(",")[0].strip()
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            entry = {
                "id": str(uuid.uuid4())[:8],
                "ts": now_iso,
                "ip": client_ip,
                "type": fb_type,
                "message": message,
                "contact": contact,
                "diagnostics": diagnostics,
            }
            fb_file = os.path.join(DATA, "feedback.jsonl")
            try:
                os.makedirs(DATA, exist_ok=True)
                with open(fb_file, "a", encoding="utf-8") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    fcntl.flock(f, fcntl.LOCK_UN)
            except Exception as e:
                logger.log("ERROR", "FEEDBACK", f"保存反馈失败: {e}")
                return self._json(500, {"ok": False, "error": "反馈写入失败，请稍后重试"})

            logger.log("INFO", "FEEDBACK", f"收到新反馈 [{fb_type}] 来自 {client_ip}")
            return self._json(200, {"ok": True, "message": "反馈已收到，感谢您的建议与支持！", "id": entry["id"]})

        if norm_path == "/node/check":
            # Credentials stay in the request/worker memory and never enter a job file.
            if self.headers.get_content_type() != "application/json":
                return self._json(415, {"ok": False, "code": "INVALID_TYPE", "message": "请使用安全的管理页面。"})
            result = node_check_bridge.check(body)
            if result.get("ok"):
                if (result.get("result") or {}).get("ready_for_install") is True:
                    try:
                        result = dict(result, check_ticket=CHECKED_TARGETS.remember(body, result["result"]), expires_in=600)
                    except install_mod.InstallError as exc:
                        return self._json(400, {"ok": False, "error": str(exc)})
                return self._json(200, result)
            status = 409 if result.get("code") == "HOST_KEY_CONFIRMATION" else 503 if result.get("code") == "UNAVAILABLE" else 400
            return self._json(status, result)

        if norm_path == "/tencent/instances":
            sid = (body.get("secret_id") or "").strip()
            skey = (body.get("secret_key") or "").strip()
            if not sid or not skey:
                tc_file = os.path.join(DATA, "tc.json")
                if os.path.exists(tc_file):
                    try:
                        with open(tc_file, "r", encoding="utf-8") as f:
                            c = json.load(f)
                            sid = sid or (c.get("secret_id") or "").strip()
                            skey = skey or (c.get("secret_key") or "").strip()
                    except Exception:
                        pass
            try:
                return self._json(200, tencent_discovery_mod.discover(sid, skey))
            except tencent_discovery_mod.Problem as e:
                return self._json(e.status, {"ok": False, "error": e.message})

        if norm_path == "/quota/settings":
            try:
                quota_mod.save_quota_threshold(body.get("threshold"))
            except ValueError as e:
                return self._json(400, {"ok": False, "error": str(e)})
            except OSError:
                return self._json(500, {"ok": False, "error": "保护阈值保存失败"})
            return self._json(200, {"ok": True, "threshold": quota_mod.quota_threshold()})

        if norm_path == "/rotate":
            msg = "旧订阅地址已失效；已连接的设备不受影响（要踢人请用「更换密钥」）"
            if body.get("dry_run"):
                return self._json(200, {"ok": True, "dry_run": True, "message": msg,
                                        "would": "作废旧订阅地址并生成新地址"})
            try:
                new_token = secrets.token_hex(32)
                settings = _load_json("settings.json", {})
                settings["sub_token"] = new_token
                _save_json(os.path.join(DATA, "settings.json"), settings)

                domain, token, new_url = _build_sub_url(settings, self.headers.get("Host"))

                try:
                    subprocess.run(["qrencode", "-o", os.path.join(WEB, "qr-sub.png"), "-s", "12", "-m", "2", new_url],
                                   check=False, timeout=10)
                except Exception:
                    pass

                render()
                logger.log("WARN", "ADMIN", "已轮换订阅凭据")
                return self._json(200, {"ok": True, "url": new_url, "message": msg})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if norm_path == "/restore":
            incoming_nodes = body.get("nodes")
            if not isinstance(incoming_nodes, list):
                return self._json(400, {"ok": False, "error": "备份格式不正确：缺少 nodes 节点数组"})
            if len(incoming_nodes) == 0:
                return self._json(400, {"ok": False, "error": "备份文件中不包含任何节点"})
            valid_nodes = []
            for item in incoming_nodes:
                if not isinstance(item, dict) or not item.get("host") or not item.get("port"):
                    return self._json(400, {"ok": False, "error": "备份含无效节点，未进行恢复"})
                # A backup cannot prove current service ownership on this machine.
                restored = dict(item)
                restored.pop("quota_control_managed", None)
                valid_nodes.append(restored)
            if not valid_nodes:
                return self._json(400, {"ok": False, "error": "备份中没有有效的节点数据"})
            token = body.get("sub_token")
            if token is not None and token != "" and (not isinstance(token, str) or not re.fullmatch(r"[0-9a-fA-F]{8,64}", token)):
                return self._json(400, {"ok": False, "error": "备份中的订阅凭据无效，未进行恢复"})
            save_nodes(valid_nodes)
            if body.get("sub_token"):
                try:
                    settings = _load_json("settings.json", {})
                    settings["sub_token"] = body["sub_token"]
                    _save_json(os.path.join(DATA, "settings.json"), settings)
                except Exception:
                    return self._json(500, {"ok": False, "error": "节点配置已写入，但订阅凭据恢复失败；请检查配置后重试"})
            render()
            logger.log("WARN", "ADMIN", f"恢复备份成功：还原了 {len(valid_nodes)} 个节点")
            return self._json(200, {"ok": True, "restored_count": len(valid_nodes), "message": f"已恢复 {len(valid_nodes)} 个节点配置，请检查服务器实际状态"})

        if norm_path == "/node/join-token":
            name = (body.get("name") or "").strip()
            role = (body.get("role") or "exit").strip()
            port_val = body.get("port")
            port = int(port_val) if port_val else (8443 if role == "relay" else 443)
            landing = None
            if role == "relay":
                landing_host = (body.get("landing_host") or body.get("landing_name") or "").strip()
                nodes = load_nodes()
                exit_candidates = [n for n in nodes if n.get("role") != "relay" and n.get("type") != "hysteria2"]
                target_exit = None
                if landing_host:
                    target_exit = next((n for n in exit_candidates if n.get("host") == landing_host or n.get("name") == landing_host), None)
                if not target_exit and exit_candidates:
                    target_exit = exit_candidates[0]
                if target_exit:
                    landing = {
                        "host": target_exit["host"],
                        "port": int(target_exit.get("port") or 443),
                        "uuid": target_exit["uuid"],
                        "sni": target_exit.get("sni", "www.apple.com"),
                        "pbk": target_exit["pbk"],
                        "sid": target_exit["sid"],
                        "name": target_exit.get("name", ""),
                    }
            rec = join_token_mod.create_token(name=name, role=role, landing=landing, port=port)
            base_url = join_base_url(self.headers.get("Host") or "127.0.0.1")
            if not base_url:
                return self._json(400, {"ok": False, "error": "无效的主控地址"})
            command = f"curl -fsSL --proto '=https' --proto-redir '=https' {base_url}/join/{rec['token']} | bash"
            return self._json(200, {
                "ok": True,
                "token": rec["token"],
                "command": command,
                "role": rec["role"],
                "name": rec["name"],
                "port": rec.get("port"),
                "landing": rec.get("landing"),
                "expires_at": rec["expires_at"],
                "expires_in": int(rec["expires_at"] - rec["created_at"]),
            })

        if norm_path in ("/node/join", "/join/register"):
            token = (body.get("token") or "").strip()
            token_info = join_token_mod.consume_token(token)
            if not token_info:
                return self._json(403, {"ok": False, "error": "入网凭据无效或已过期，请重新生成"})

            host = (body.get("host") or "").strip()
            if not host:
                return self._json(400, {"ok": False, "error": "缺少节点公网 IP/主机名"})

            name = (token_info.get("name") or body.get("name") or "").strip()
            if not name:
                name = f"node-{host.replace('.', '-')}"

            role = token_info.get("role") or body.get("role") or "exit"
            port = int(body.get("port") or token_info.get("port") or (8443 if role == "relay" else 443))
            landing = token_info.get("landing") or body.get("landing")

            vless_entry = {
                "name": name,
                "type": body.get("type") or "vless",
                "role": role,
                "host": host,
                "port": port,
                "uuid": body.get("uuid", ""),
                "pbk": body.get("pbk", ""),
                "sid": body.get("sid", ""),
                "sni": body.get("sni", "www.apple.com"),
                "network": "tcp",
                "flow": "xtls-rprx-vision",
                "status": "unknown",
                "source": "reverse_join",
                "health": "unknown",
                "joined_at": int(time.time()),
                "warp_enabled": False,
                "hy2_enabled": bool(body.get("hy2_password")) if role != "relay" else False,
            }
            if landing:
                vless_entry["landing"] = landing
                if landing.get("host"):
                    vless_entry["health_detail"] = f"中转：经落地出网，出口 {landing['host']}"
                    vless_entry["exit_ip"] = landing["host"]

            try:
                node_manager.add_node(vless_entry)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

            hy2_pw = body.get("hy2_password")
            if hy2_pw and role != "relay":
                hy2_entry = {
                    "name": f"{name}-HY2",
                    "type": "hysteria2",
                    "role": role,
                    "host": host,
                    "port": port,
                    "password": hy2_pw,
                    "obfs_password": body.get("obfs_password", ""),
                    "sni": "www.bing.com",
                    "source": "reverse_join",
                    "enabled": True,
                    "health": "unknown",
                    "joined_at": int(time.time()),
                }
                try:
                    node_manager.add_node(hy2_entry)
                except Exception as e:
                    logger.log("WARN", "JOIN", f"伴生 HY2 节点纳管跳过: {e}")

            return self._json(200, {
                "ok": True,
                "message": f"节点 {name} 反向自举纳管成功",
                "node": vless_entry,
            })

        if norm_path in ("/removenode", "/delnode"):
            name = (body.get("name") or "").strip()
            cleanup_confirmed = body.get("cleanup_confirmed") is True
            try:
                resp = node_manager.remove_node(name, cleanup_confirmed=cleanup_confirmed)
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path == "/editnode":
            name = (body.get("name") or "").strip()
            try:
                resp = node_manager.edit_node(name, body)
                target = node_manager.get_node(resp.get("target_name", name))
                return self._json(200, {"ok": True, "node": target})
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path == "/relay/switch":
            name = (body.get("name") or "").strip()
            target_host = (body.get("target") or "").strip()
            try:
                resp = node_manager.switch_relay(name, target_host)
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path == "/relay/bind":
            name = (body.get("name") or "").strip()
            target_host = (body.get("target") or "").strip()
            fallback_host = (body.get("fallback") or "").strip() or None
            try:
                resp = node_manager.bind_relay(name, target_host, fallback_host)
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path == "/relay/unbind":
            name = (body.get("name") or "").strip()
            try:
                resp = node_manager.unbind_relay(name)
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path in ("/relay/auto-pair", "/api/relay/auto-pair"):
            try:
                resp = node_manager.auto_pair_relay()
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path == "/hy2/toggle":
            host = (body.get("host") or "").strip()
            name = (body.get("name") or "").strip()
            enabled = bool(body.get("enabled"))
            try:
                resp = node_manager.toggle_hy2(name=name, host=host, enabled=enabled)
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path in ("/warp/toggle", "/node/warp/toggle"):
            name = (body.get("name") or "").strip()
            enabled = bool(body.get("enabled"))
            try:
                resp = node_manager.toggle_warp(name=name, enabled=enabled)
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if norm_path == "/ping":
            try:
                import probe as probe_mod
                nodes = load_nodes()
                settings = _load_json("settings.json", {})
                cn = probe_mod.cn_probe(nodes, preferred_vantage=settings.get("probe_vantage"))
                status = _load_json("status.json", {})
                if cn:
                    for name, cinfo in cn.items():
                        if name in status and isinstance(cinfo, dict):
                            status[name].update(cinfo)
                    status["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    tmp = os.path.join(DATA, "status.json.tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(status, f, ensure_ascii=False)
                    os.replace(tmp, os.path.join(DATA, "status.json"))
                return self._json(200, {"ok": True, "status": status})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if norm_path == "/probe/vantage":
            name = (body.get("name") or body.get("vantage") or "").strip()
            nodes = load_nodes()
            target = next((n for n in nodes if (n.get("name") == name or n.get("host") == name) and (n.get("role") in ("relay", "standalone") or n.get("region_type") == "cn" or (n.get("country") or "").upper() == "CN")), None)
            if not target:
                return self._json(400, {"ok": False, "error": "未找到指定的国内探测基准节点"})
            settings = _load_json("settings.json", {})
            settings["probe_vantage"] = target["name"]
            _save_json(os.path.join(DATA, "settings.json"), settings)
            logger.log("INFO", "PROBE", "管理员切换国内探测基准锚点为 [%s]" % target["name"])
            try:
                import probe as probe_mod
                cn = probe_mod.cn_probe(nodes, preferred_vantage=target["name"])
                status = _load_json("status.json", {})
                if cn:
                    for k, v in cn.items():
                        if k in status and isinstance(v, dict):
                            status[k].update(v)
                    status["_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    tmp = os.path.join(DATA, "status.json.tmp")
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(status, f, ensure_ascii=False)
                    os.replace(tmp, os.path.join(DATA, "status.json"))
            except Exception:
                pass
            return self._json(200, {"ok": True, "vantage": target["name"]})

        if norm_path == "/resetpw":
            ip = (body.get("ip") or "").strip()
            import providers
            st, msg, extra, who = providers.reset_password(ip, dry_run=bool(body.get("dry_run")))
            if st == "dry":
                return self._json(200, {"ok": True, "dry_run": True, "would": msg, "provider": who})
            if st == "skip":
                return self._json(404, {"ok": False, "error": msg})
            if st == "fail":
                return self._json(403 if ("权限" in msg) else 500, {"ok": False, "error": msg})
            return self._json(200, {"ok": True, "password": extra.get("password", ""),
                                    "reboot": extra.get("reboot", False), "provider": who})

        if norm_path == "/render":
            render()
            return self._json(200, {"ok": True})


        if norm_path == "/verify":
            name = (body.get("name") or "").strip()
            nodes = load_nodes()
            node = next((n for n in nodes if n.get("name") == name), None)
            if not node:
                return self._json(404, {"ok": False, "error": "没找到这个节点"})
            if node.get("source") == "external":
                return self._json(400, {"ok": False, "error": "外部节点无法验证（没有控制权）"})
            r = verify_node(node)
            lvl = "INFO" if r.get("health") == "ok" else "WARN"
            logger.log(lvl, "VERIFY", "节点 [%s] 手动验真: health=%s, 出口IP=%s" %
                       (name, r.get("health"), r.get("exit_ip") or "-"))
            return self._json(200, {"ok": True, "result": r})

        if norm_path == "/repair":
            name = (body.get("name") or "").strip()
            all_bad = bool(body.get("all_bad"))
            nodes = load_nodes()
            if not all_bad and not name:
                return self._json(400, {"ok": False, "error": "请指定节点名称或设置 all_bad=true"})

            targets = []
            if all_bad:
                targets = [n for n in nodes if n.get("health") not in ("ok", "unknown") and n.get("source") != "external"]
                if not targets:
                    return self._json(200, {"ok": True, "message": "没有已识别为异常的节点", "results": []})
            else:
                target = next((n for n in nodes if n.get("name") == name), None)
                if not target:
                    return self._json(404, {"ok": False, "error": "没找到这个节点"})
                targets = [target]

            settings = _load_json("settings.json", {})
            master_secret = None
            results = []
            for t in targets:
                r = repair_mod.repair_node(t, master_secret=master_secret)
                results.append(r)
                if r.get("requires_manual"):
                    logger.log("WARN", "REPAIR", "节点 [%s] 需要人工检查；未执行远程操作" % t.get("name"))
                    continue
                def _apply(ns):
                    for n in ns:
                        if n.get("name") == t.get("name"):
                            n["health"] = r.get("after") or "ok"
                            if r.get("exit_ip"):
                                n["exit_ip"] = r["exit_ip"]
                            if r.get("detail"):
                                n["health_detail"] = r["detail"]
                    return ns
                update_nodes(_apply)
                lvl = "INFO" if r.get("ok") else "WARN"
                logger.log(lvl, "REPAIR", "自愈节点 [%s]: %s -> %s (%s)" %
                           (t.get("name"), r.get("before"), r.get("after"), r.get("detail")))
            if any(not x.get("requires_manual") for x in results):
                render()
            all_ok = all(x.get("ok") for x in results)
            return self._json(200, {"ok": True, "all_ok": all_ok, "results": results})

        if norm_path == "/addnode":
            checked = None
            try:
                ticket = body.get("check_ticket")
                if ticket:
                    checked = CHECKED_TARGETS.take(ticket)
                else:
                    # Legacy callers undergo the same pinned check; never accept unverified SSH input.
                    login = {"host": body.get("ip"), "username": body.get("user") or "root",
                             "ssh_port": body.get("ssh_port") or 22, "password": body.get("pass") or "",
                             "private_key": body.get("private_key") or "", "passphrase": body.get("passphrase") or "",
                             "fingerprint": body.get("fingerprint") or ""}
                    response = node_check_bridge.check(login)
                    if not response.get("ok"):
                        return self._json(409, {"ok": False, "code": response.get("code", "CHECK_REQUIRED"),
                                               "error": response.get("message", "请先完成连接和指纹检查"),
                                               "fingerprint": response.get("fingerprint", "")})
                    checked = CHECKED_TARGETS.take(CHECKED_TARGETS.remember(login, response["result"]))
                ip = checked["identity"][0]
                name = str(body.get("name") or "节点-" + ip).strip()
                role = body.get("role") or "auto"
                port = int(body.get("port") or 443)
                if not name or len(name) > 128 or any(ord(c) < 32 for c in name) or role not in ("auto", "exit", "relay") or not 1 <= port <= 65535:
                    raise install_mod.InstallError("节点名称、角色或端口无效")
                if any(n.get("name") in (name, name + "-HY2") or n.get("host") == ip for n in load_nodes()):
                    raise install_mod.InstallError("该节点名称或服务器已在管理列表中，请先核对")
                if role == "exit":
                    servers = _load_json("servers.json", {}).get("servers", [])
                    server = next((item for item in servers if item.get("ip") == ip), {})
                    if server.get("region") in ("北京", "广州", "上海", "南京", "成都", "重庆"):
                        raise install_mod.InstallError("中国大陆服务器不能作为直接出口，请选择中转角色")
                landing = body.get("landing") or subs_mod.pick_landing(load_nodes(), _load_json("status.json", {}))
                if landing and not landing.get("uuid") and landing.get("link"):
                    landing = links_mod.parse(landing["link"])
                if role == "relay" and not landing:
                    raise install_mod.InstallError("中转必须先指定可用落地节点")
                self_bootstrap = bool(body.get("self_bootstrap", True))
                if self_bootstrap and port in (80, 8443):
                    raise install_mod.InstallError("独立后台保留 80 和 8443 端口，请为代理选择其他端口")
                node = _gen_node()
                panel_hash = ""
                if self_bootstrap:
                    panel_hash = subprocess.check_output(["caddy", "hash-password"],
                                                         input=node["initial_password"] + "\n", text=True, timeout=15).strip()
                    if not re.fullmatch(password_mod.HASH, panel_hash):
                        raise install_mod.InstallError("管理密码初始化失败")
                jid = uuid.uuid4().hex[:12]
                spec = {"checked_target": checked, "name": name, "port": port, "role": role,
                        "node": node, "landing": landing, "dry_run": bool(body.get("dry_run")),
                        "self_bootstrap": self_bootstrap, "panel_hash": panel_hash,
                        "sub_token": secrets.token_hex(32), "control_secret": secrets.token_hex(32),
                        "job_id": uuid.uuid4().hex}
                with _INSTALL_LOCK:
                    for active in JOBS.values():
                        reservation = active.get("_reservation")
                        if active.get("state") in ("queued", "running") and reservation and (reservation[0] == name or reservation[1] == ip):
                            raise install_mod.InstallError("同名节点或目标服务器已有安装任务")
                    if any(n.get("name") in (name, name + "-HY2") or n.get("host") == ip for n in load_nodes()):
                        raise install_mod.InstallError("该节点名称或服务器已在管理列表中")
                    JOBS[jid] = {"state": "queued", "step": 0, "stepname": "", "log": [], "_reservation": (name, ip)}
                    try:
                        threading.Thread(target=run_job, args=(jid, spec), daemon=True).start()
                    except Exception:
                        JOBS.pop(jid, None)
                        raise
                return self._json(200, {"ok": True, "job": jid})
            except (install_mod.InstallError, ValueError, KeyError, TypeError) as exc:
                if checked:
                    checked["login"].clear()
                return self._json(400, {"ok": False, "code": "CHECK_REQUIRED", "error": str(exc) if isinstance(exc, install_mod.InstallError) else "安装输入无效"})
            except (OSError, subprocess.SubprocessError, RuntimeError):
                if checked:
                    checked["login"].clear()
                return self._json(500, {"ok": False, "error": "安装初始化失败，未执行远程安装"})

        self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
