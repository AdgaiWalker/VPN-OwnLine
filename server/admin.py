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
from nodekit.relay_service import RelayService  # noqa: E402
from nodekit.hy2_service import Hy2Service  # noqa: E402
from nodekit.node_service import NodeService  # noqa: E402
from nodekit.node_manager import FileNodeStore, NodeManager, NodeManagerError  # noqa: E402
import reset_admin_password as password_mod  # noqa: E402
import tencent_discovery as tencent_discovery_mod  # noqa: E402
sys.path.insert(0, WEB)
NODES = os.path.join(DATA, "nodes.json")
CADDY = "/etc/caddy/Caddyfile"
JOBS = {}
INITIAL_PASSWORD_MARKER = Path(DATA) / '.initial-password-required'
_PASSWORD_LOCK = threading.Lock()
_PASSWORD_ATTEMPTS = deque()

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

def vless(n):
    q = ("encryption=none&flow=xtls-rprx-vision&security=reality"
         "&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp&headerType=none" % (n["sni"], n["pbk"], n["sid"]))
    return "vless://%s@%s:%s?%s#%s" % (n["uuid"], n["host"], n["port"], q, urllib.parse.quote(n["name"]))


def hy2(n):
    """Hysteria2 / QUIC 节点的分享链接。字段与 vless 不同：密码 + 混淆。"""
    q = ("insecure=1&sni=%s&alpn=h3&obfs=salamander&obfs-password=%s"
         % (n["sni"], n["obfs_password"]))
    return "hysteria2://%s@%s:%s?%s#%s" % (n["password"], n["host"], n["port"], q,
                                          urllib.parse.quote(n["name"]))


def link(n):
    return hy2(n) if n.get("type") == "hysteria2" else vless(n)

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
        src = urllib.parse.quote("|".join(link(n) for n in nodes), safe="")
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
        uid = str(uuid.uuid4())
        priv = os.urandom(32).hex()
        pub = os.urandom(32).hex()
    return {
        "uuid": uid,
        "private_key": priv,
        "pbk": pub,
        "sid": os.urandom(4).hex(),
        "sni": "www.apple.com",
        "hy2_password": os.urandom(12).hex(),
        "obfs_password": os.urandom(8).hex(),
        "hy2_sni": "www.bing.com",
    }


def _write_job(jid, data, secret):
    """任务写文件（0600），凭据单独一个文件：不进 argv、不进日志。"""
    d = os.path.join(DATA, ".jobs")
    os.makedirs(d, mode=0o700, exist_ok=True)
    cfg = os.path.join(d, jid + ".json")
    sec = cfg + ".secret"
    fd = os.open(sec, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secret.rstrip("\n") + "\n")
    data["secret_file"] = sec
    fd = os.open(cfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    return cfg


def run_job(jid, cfg_path):
    j = JOBS[jid]
    j["state"] = "running"
    dry = False
    try:
        dry = bool(json.load(open(cfg_path, encoding="utf-8")).get("dry_run"))
    except Exception:
        pass
    try:
        p = subprocess.Popen(["/opt/web/addnode.sh", cfg_path], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in p.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("STEP "):
                parts = line.split(" ", 2)
                try:
                    j["step"] = int(parts[1])
                except Exception:
                    pass
                j["stepname"] = parts[2] if len(parts) > 2 else ""
            elif line.startswith("{"):
                try:
                    node = json.loads(line)
                    update_nodes(lambda ns: [x for x in ns if x["name"] != node["name"]] + [node])
                    render()
                    j["node"] = node
                    logger.log("INFO", "NODE", "成功添加节点: %s (%s)" % (node.get("name"), node.get("host")))
                except Exception as e:
                    j["log"].append("parse error: %s" % e)
            j["log"].append(line)
            j["log"] = j["log"][-60:]
        rc = p.wait()
        if rc != 0 or (not j.get("node") and not dry):
            j["state"] = "error"
            j["error"] = "installation failed"
            err_msg = j["log"][-1] if j.get("log") else "未知错误"
            logger.log("ERROR", "NODE", "添加节点任务失败 (jid=%s): %s" % (jid, err_msg))
            j["hint"] = hints_mod.hint_from_log(j["log"])
        else:
            # 先处理完端口/防火墙，再自测，最后才标 done。
            # 顺序反了，前端会在防火墙还没开、自测还没跑完时就看到“完成”。
            if dry and not j.get("node"):
                j["state"] = "done"
                j["warn"] = "dry_run"
                j["log"].append("演练完成：未对目标机做任何修改")
                return

            j["warn"] = "port_blocked" if any("PORT_BLOCKED" in l for l in j["log"]) else ""
            if j["warn"] == "port_blocked" and j.get("node"):
                host = j["node"]["host"]
                port = j["node"]["port"]
                role = j["node"].get("role") or "exit"
                st, msg = open_firewall(host, port, proto="TCP")
                j["log"].append("防火墙(TCP): " + msg)
                if role == "exit":
                    st_u, msg_u = open_firewall(host, port, proto="UDP")
                    j["log"].append("防火墙(UDP): " + msg_u)
                if st in ("opened", "already"):
                    time.sleep(3)
                    if port_reachable(host, port):
                        j["warn"] = ""
                        j["log"].append("端口已通，重新自测")
                    else:
                        j["log"].append("端口仍不通：可能有云端安全组之外的拦截")
                else:
                    j["log"].append("没能自动放行，需要手动去控制台加规则")

            if j.get("node"):
                host = j["node"]["host"]
                matching = [n for n in load_nodes() if n.get("host") == host]
                for n in matching:
                    try:
                        r = verify_node(n)
                        if n.get("name") == j["node"].get("name"):
                            j["verify"] = r
                            j["node"]["health"] = r.get("health", "unknown")
                            if r.get("exit_ip"):
                                j["node"]["exit_ip"] = r["exit_ip"]
                                j["node"]["exit_country"] = r.get("exit_country", "")
                            if r.get("detail"):
                                j["node"]["health_detail"] = r["detail"]
                    except Exception as e:
                        if n.get("name") == j["node"].get("name"):
                            j["verify"] = {"health": "unknown", "detail": str(e)[:80]}
            j["state"] = "done"
    except Exception as e:
        j["state"] = "error"
        j["error"] = str(e)[:200]
    finally:
        for f in (cfg_path, cfg_path + ".secret"):
            try:
                os.remove(f)
            except Exception:
                pass


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
        n["advice"] = advise_mod.advise(n, status.get(n.get("name")), usage.get(n.get("host")))
        n["lifecycle"] = lifecycle_mod.get_lifecycle_state(n)
        out.append(n)
    return out


class H(BaseHTTPRequestHandler):
    timeout = 30  # 单连接最长 30 秒，防慢速攻击占线程
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        path = path.rstrip("/")

        # This gate is also invoked by Caddy before every management route.
        if path == '/password-gate':
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
        if path in ('/api/password/state', '/password/state'):
            return self._json(200, {'ok': True, 'required': INITIAL_PASSWORD_MARKER.exists()})
        if path in ('/api/user', '/user'):
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

        # 订阅路由：仅放行携带合法高熵 token 的 /s/<token>[/clash|/sr]，拒绝裸 /sub 与空 token
        token = get_sub_token()
        client_ip = (self.headers.get("X-Forwarded-For") or self.client_address[0] or "").split(",")[0].strip()
        if path.startswith("/s/") or path == "/sub":
            parts = path.split("/")
            req_token = parts[2] if (path.startswith("/s/") and len(parts) > 2) else ""
            if not token or not req_token or not hmac.compare_digest(req_token, token):
                logger.log("WARN", "SUB", f"非法订阅请求 (IP={client_ip})")
                return self._json(404, {"ok": False, "error": "invalid subscription token"})

            q = urllib.parse.parse_qs(qs)
            ua = self.headers.get("User-Agent", "Unknown")
            if path.endswith("/singbox") or (q.get("target") or [""])[0] == "singbox":
                return self._json(404, {"ok": False, "error": "singbox subscription format is not supported"})
            is_clash = (
                path.endswith("/clash")
                or (q.get("target") or [""])[0] == "clash"
                or bool(re.search(r"(?i)(clash|mihomo|stash|flclash|verge)", ua))
            )
            profile = (q.get("profile") or q.get("mode") or ["all"])[0].lower()
            nodes = load_nodes()
            fmt = "Clash YAML" if is_clash else "Base64"
            usage_data = _load_json("usage.json", {})
            userinfo = subs_mod.subscription_userinfo(usage_data, nodes=nodes)
            eligible_hosts = quota_mod.controllable_hosts(nodes)
            sub_count = sum(1 for n in nodes if subs_mod.in_subscription(
                n, usage_data=usage_data, controllable_hosts=eligible_hosts))
            logger.log("INFO", "SUB", f"拉取订阅 (IP={client_ip}, 格式={fmt}, 场景={profile}, UA={ua[:30]}, 节点数={sub_count})")
            if is_clash:
                content = subs_mod.render_clash_yaml(nodes, profile=profile, usage_data=usage_data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/yaml; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="clash.yaml"')
            else:
                content = subs_mod.render_v2ray_base64(nodes, profile=profile, usage_data=usage_data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="subscription.txt"')

            if userinfo:
                self.send_header("Subscription-Userinfo", userinfo)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/backup":
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

        if path in ("/qr", "/api/qr"):
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

        if path in ("/nodes", ""):
            return self._json(200, nodes_with_advice())
        if path == "/logs":
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
        if path == "/syslogs":
            q = urllib.parse.parse_qs(qs)
            service = (q.get("service") or ["sing-box"])[0]
            try:
                lines = int((q.get("lines") or ["50"])[0])
            except Exception:
                lines = 50
            res = logger.get_syslog(service, lines=lines)
            return self._json(200 if res.get("ok") else 400, res)
        if path == "/ping":
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

        if path == "/probe/vantage":
            settings = _load_json("settings.json", {})
            return self._json(200, {"ok": True, "vantage": settings.get("probe_vantage")})
        if path == "/settings":
            settings = _load_json("settings.json", {})
            domain, token, sub_url = _build_sub_url(settings, self.headers.get("Host"))
            return self._json(200, {
                "ok": True,
                "domain": domain,
                "sub_token": token,
                "sub_url": sub_url,
                "probe_vantage": settings.get("probe_vantage"),
                "quota_threshold": quota_mod.quota_threshold(),
                "tencent_discovery": True,
                "backup_restore_supported": True,
                "node_check_supported": node_check_bridge.available(),
            })
        if path == "/relay/status":
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
        if path == "/quota/guard":
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
                })
            return self._json(200, {
                "ok": True,
                "watermarks": eval_res.get("_summary", {}).get("watermarks", {"warning": 75, "tripped": 85}),
                "usage_fresh": quota_mod.usage_is_fresh(usage),
                "guards": guards,
            })
        if path == "/node/job":
            q = urllib.parse.parse_qs(qs)
            jid = (q.get("id") or [""])[0]
            if not re.fullmatch(r"[a-f0-9]{12}", jid):
                return self._json(400, {"ok": False, "error": "任务编号无效"})
            job = JOBS.get(jid)
            if not job:
                return self._json(404, {"ok": False, "error": "任务状态未知"})
            # Do not return raw logs or node credentials in the progress view.
            verification = job.get("verify") or {}
            return self._json(200, {"ok": True, "state": job.get("state", "unknown"),
                                    "step": job.get("step", 0),
                                    "health": verification.get("health", "unknown")})
        if path == "/job":
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
            return self._json(200, out)
        self._json(404, {"ok": False, "error": "not found"})

    def _origin_ok(self):
        """只靠 Basic Auth 时，第三方网页也能让浏览器带上凭据发 POST。
        浏览器跨站请求一定带 Origin（或 Referer），核对它的主机名。"""
        src = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not src:
            return True                      # 命令行 / curl：没有 Origin
        parsed = urllib.parse.urlsplit(src)
        host = (self.headers.get("Host") or "").lower()
        return parsed.scheme in ("http", "https") and bool(host) and parsed.netloc.lower() == host

    def do_POST(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "跨站请求被拒绝"})
        path = self.path.rstrip("/")
        if INITIAL_PASSWORD_MARKER.exists() and path not in (
            '/api/password/change', '/password/change', '/api/credentials/change', '/credentials/change'
        ):
            return self._json(403, {'ok': False, 'error': '请先修改初始管理密码'})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"ok": False, "error": "请求体过大"})
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            return self._json(400, {"ok": False, "error": "请求体不是合法 JSON"})
        if not isinstance(body, dict):
            return self._json(400, {"ok": False, "error": "请求体必须是对象"})

        if path in ('/api/password/change', '/password/change', '/api/credentials/change', '/credentials/change'):
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

        if path == "/node/check":
            # Credentials stay in the request/worker memory and never enter a job file.
            if self.headers.get_content_type() != "application/json":
                return self._json(415, {"ok": False, "code": "INVALID_TYPE", "message": "请使用安全的管理页面。"})
            result = node_check_bridge.check(body)
            if result.get("ok"):
                return self._json(200, result)
            status = 409 if result.get("code") == "HOST_KEY_CONFIRMATION" else 503 if result.get("code") == "UNAVAILABLE" else 400
            return self._json(status, result)

        if path == "/tencent/instances":
            try:
                return self._json(200, tencent_discovery_mod.discover(body.get("secret_id"), body.get("secret_key")))
            except tencent_discovery_mod.Problem as e:
                return self._json(e.status, {"ok": False, "error": e.message})

        if path == "/quota/settings":
            try:
                quota_mod.save_quota_threshold(body.get("threshold"))
            except ValueError as e:
                return self._json(400, {"ok": False, "error": str(e)})
            except OSError:
                return self._json(500, {"ok": False, "error": "保护阈值保存失败"})
            return self._json(200, {"ok": True, "threshold": quota_mod.quota_threshold()})

        if path == "/rotate":
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

        if path == "/restore":
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

        if path == "/removenode":
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

        if path == "/editnode":
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

        if path == "/relay/switch":
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

        if path == "/relay/bind":
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

        if path == "/relay/unbind":
            name = (body.get("name") or "").strip()
            try:
                resp = node_manager.unbind_relay(name)
                return self._json(200, resp)
            except NodeManagerError as e:
                payload = {"ok": False, "error": e.message}
                if e.data:
                    payload.update(e.data)
                return self._json(e.status_code, payload)

        if path == "/hy2/toggle":
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

        if path == "/ping":
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

        if path == "/probe/vantage":
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

        if path == "/resetpw":
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

        if path == "/render":
            render()
            return self._json(200, {"ok": True})


        if path == "/verify":
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

        if path == "/repair":
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
            master_secret = settings.get("master_secret") or settings.get("sub_token") or "ownline_default_secret"
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

        if path == "/addnode":
            ip = (body.get("ip") or "").strip()
            user = (body.get("user") or "root").strip() or "root"
            auth_type = (body.get("auth_type") or "password").strip()
            pwd = body.get("pass") or ""
            key_text = body.get("private_key") or ""
            name = (body.get("name") or "").strip() or ("节点-" + ip)
            role = (body.get("role") or "auto").strip()
            landing = body.get("landing") or None
            dry_run = bool(body.get("dry_run"))
            if not _valid_host(ip):
                return self._json(400, {"ok": False, "error": "地址格式不对（IP 或域名）"})
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,31}", user):
                return self._json(400, {"ok": False, "error": "SSH 用户名格式不正确"})
            if auth_type not in ("password", "key"):
                return self._json(400, {"ok": False, "error": "认证方式只支持 password 或 key"})
            if auth_type == "password" and not pwd:
                return self._json(400, {"ok": False, "error": "密码或私钥至少填一个"})
            if auth_type == "key" and "PRIVATE KEY" not in key_text:
                return self._json(400, {"ok": False, "error": "私钥格式不对，应为 OpenSSH 或 PEM"})
            try:
                port = int(body.get("port") or 443)
            except Exception:
                return self._json(400, {"ok": False, "error": "端口必须是 1-65535"})
            if not (0 < port < 65536):
                return self._json(400, {"ok": False, "error": "端口必须是 1-65535"})
            try:
                ssh_port = int(body.get("ssh_port") or 22)
            except Exception:
                return self._json(400, {"ok": False, "error": "SSH 端口必须是 1-65535"})
            if not (0 < ssh_port < 65536):
                return self._json(400, {"ok": False, "error": "SSH 端口必须是 1-65535"})
            if role not in ("auto", "exit", "relay"):
                return self._json(400, {"ok": False, "error": "角色只支持 auto / exit / relay"})

            # 装前 3 秒连通性排雷与大白话提示（非演练模式下检测目标 SSH 端口）
            if not dry_run and not port_reachable(ip, ssh_port, timeout=3):
                return self._json(400, {
                    "ok": False,
                    "error": f"无法连接服务器 {ip} 的 {ssh_port} 端口，请检查：1. 服务器是否已在云控制台开机；2. 安全组/防火墙是否放行了 {ssh_port} 端口（TCP）。"
                })

            # 防呆约束：中国大陆服务器禁止误设为直接出口
            if role == "exit":
                srvs = _load_json("servers.json", {}).get("servers", [])
                matched_srv = next((s for s in srvs if s.get("ip") == ip), None)
                if matched_srv and matched_srv.get("regionId", "").startswith("ap-"):
                    reg = matched_srv.get("region", "")
                    if reg in ("北京", "广州", "上海", "南京", "成都", "重庆"):
                        return self._json(400, {
                            "ok": False,
                            "error": f"服务器位于中国大陆（{reg}），受 GFW 拦截无法作为出口节点，请将角色设为「中转（relay）」"
                        })

            if not landing:
                # 不指定落地时，自动挑一台最快的海外节点当出口。
                # 目标机是不是直连由 addnode.sh 现场判断；这里只负责准备候选。
                landing = subs_mod.pick_landing(load_nodes(), _load_json("status.json", {}))
            if role == "relay" and not landing:
                return self._json(400, {"ok": False, "error": "中转必须先指定落地节点"})
            node = _gen_node()
            jid = uuid.uuid4().hex[:12]
            cfg_path = _write_job(jid, {
                "ip": ip, "user": user, "auth_type": auth_type, "name": name,
                "port": port, "ssh_port": ssh_port, "role": role, "node": node, "landing": landing,
                "dry_run": dry_run,
            }, secret=(key_text if auth_type == "key" else pwd))
            JOBS[jid] = {"state": "queued", "step": 0, "stepname": "", "log": []}
            t = threading.Thread(target=run_job, args=(jid, cfg_path), daemon=True)
            t.start()
            return self._json(200, {"ok": True, "job": jid})

        self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
