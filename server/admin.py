#!/usr/bin/env python3
import datetime, json, os, re, subprocess, sys, threading, time, urllib.parse, uuid
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
sys.path.insert(0, WEB)
NODES = os.path.join(DATA, "nodes.json")
CADDY = "/etc/caddy/Caddyfile"
JOBS = {}

def load_nodes():
    with open(NODES, encoding="utf-8") as f:
        return json.load(f)

_NODES_LOCK = threading.Lock()


def _write_nodes(nodes):
    tmp = NODES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, NODES)          # 原子替换：写一半断电也不会留下坏 JSON


def save_nodes(nodes):
    with _NODES_LOCK:
        _write_nodes(nodes)


def update_nodes(mutator):
    """读-改-写 全程持锁，避免两个任务同时改导致丢更新。"""
    with _NODES_LOCK:
        nodes = mutator(load_nodes())
        _write_nodes(nodes)
        return nodes

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
            m = re.search(r"/s/([0-9a-fA-F]{8,32})", f.read())
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
    domain = settings.get("domain") or (host_header or "").split(":")[0] or "v.goodloop.si"
    port = settings.get("sub_port")
    if port:
        port_part = "" if int(port) in (80, 443) else (":%s" % port)
    elif ":8443" in (host_header or ""):
        port_part = ":8443"
    elif domain and not (host_header or "").endswith(":443"):
        port_part = ":8443"
    else:
        port_part = ""
    return domain, token, "https://%s%s/s/%s" % (domain, port_part, token)


def patch_remote(node, uuid_new=None, port_new=None):
    host = node.get("host", "")
    try:
        if node.get("local") is True or host in ("127.0.0.1", "localhost", "198.51.100.12"):
            script = _py_patch(uuid_new, port_new)
            r = subprocess.run(["python3", "-c", script], capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return False, (r.stderr or "python 失败")[:200]
            r2 = subprocess.run(["systemctl", "restart", "sing-box"], capture_output=True, text=True, timeout=60)
            if r2.returncode != 0:
                return False, "重启 sing-box 失败"
            time.sleep(2)
            act = subprocess.run(["systemctl", "is-active", "sing-box"], capture_output=True, text=True)
            return (act.stdout.strip() == "active"), ("服务状态: " + act.stdout.strip())
        u = node.get("ssh_user")
        if not u:
            return False, "这台没有控制权限"
        base = verify_mod.ssh_cmd(u, host, timeout=10)
        if node.get("os") == "windows":
            cmd = base + ['powershell -NoProfile -Command "%s"' % _ps_patch(uuid_new, port_new).replace('"', '\\"')]
        else:
            script = _py_patch(uuid_new, port_new)
            enc = _b64.b64encode(script.encode()).decode()
            remote = ("echo %s | base64 -d > /tmp/sbpatch.py && python3 /tmp/sbpatch.py && "
                      "systemctl restart sing-box && sleep 2 && systemctl is-active sing-box") % enc
            cmd = base + [remote]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out = (r.stdout or "").strip()
        return (r.returncode == 0 and "active" in out), (out or r.stderr)[-200:]
    except Exception as e:
        return False, str(e)[:200]

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

        # 订阅路由：/s/<token>, /s/<token>/clash, /s/<token>/sr, /sub
        token = get_sub_token()
        client_ip = (self.headers.get("X-Forwarded-For") or self.client_address[0] or "").split(",")[0].strip()
        if path.startswith("/s/") or path == "/sub":
            parts = path.split("/")
            req_token = parts[2] if len(parts) > 2 else ""
            if path.startswith("/s/") and req_token != token:
                logger.log("WARN", "SUB", f"非法订阅 Token 请求 (IP={client_ip}, Token={req_token})")
                return self._json(404, {"ok": False, "error": "invalid subscription token"})

            q = urllib.parse.parse_qs(qs)
            ua = self.headers.get("User-Agent", "Unknown")
            is_clash = (
                path.endswith("/clash")
                or (q.get("target") or [""])[0] == "clash"
                or bool(re.search(r"(?i)(clash|mihomo|stash|flclash|verge)", ua))
            )
            profile = (q.get("profile") or q.get("mode") or ["all"])[0].lower()
            nodes = load_nodes()
            fmt = "Clash YAML" if is_clash else "Base64"
            usage_data = _load_json("usage.json", {})
            sub_count = sum(1 for n in nodes if subs_mod.in_subscription(n, usage_data=usage_data))
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

            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if path == "/backup":
            nodes = load_nodes()
            settings = _load_json("settings.json", {})
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
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

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
        if path == "/settings":
            settings = _load_json("settings.json", {})
            domain, token, sub_url = _build_sub_url(settings, self.headers.get("Host"))
            return self._json(200, {
                "ok": True,
                "domain": domain,
                "sub_token": token,
                "sub_url": sub_url,
            })
        if path == "/relay/status":
            nodes = load_nodes()
            status = _load_json("status.json", {})
            bj = next((n for n in nodes if n.get("role") == "relay" and "北京" in n.get("name", "")), None)
            landing_policy = (bj or {}).get("landing_policy") or {
                "primary": {"host": "43.153.56.137", "name": "硅谷", "port": 443},
                "fallback": {"host": "43.163.4.104", "name": "新加坡", "port": 8443},
                "active_target": "43.153.56.137"
            }
            primary_st = status.get("硅谷") or {}
            fallback_st = status.get("新加坡") or {}
            return self._json(200, {
                "ok": True,
                "node": (bj or {}).get("name", "北京"),
                "landing_policy": landing_policy,
                "primary": {
                    "name": "硅谷",
                    "host": "43.153.56.137",
                    "ok": primary_st.get("ok", True),
                    "ms": primary_st.get("ms"),
                },
                "fallback": {
                    "name": "新加坡",
                    "host": "43.163.4.104",
                    "ok": fallback_st.get("ok", True),
                    "ms": fallback_st.get("ms"),
                },
                "active_target": landing_policy.get("active_target", "43.153.56.137"),
                "auto_failover": True,
            })
        if path == "/quota/guard":
            usage = _load_json("usage.json", {})
            eval_res = quota_mod.evaluate_all(usage)
            guards = []
            for ip, u in eval_res.items():
                if ip.startswith("_") or not isinstance(u, dict):
                    continue
                guards.append({
                    "ip": ip,
                    "name": u.get("name", ip),
                    "used_gb": u.get("used_gb", 0.0),
                    "total_gb": u.get("total_gb", 1024.0),
                    "percent": u.get("percent", 0.0),
                    "status": u.get("status", "normal"),
                })
            return self._json(200, {
                "ok": True,
                "watermarks": eval_res.get("_summary", {}).get("watermarks", {"warning": 75, "tripped": 85}),
                "guards": guards,
            })
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
        host = (self.headers.get("Host") or "").split(":")[0]
        return bool(host) and (host in src)

    def do_POST(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "跨站请求被拒绝"})
        path = self.path.rstrip("/")
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

        if path == "/rotate":
            msg = "旧订阅地址已失效；已连接的设备不受影响（要踢人请用「更换密钥」）"
            if body.get("dry_run"):
                return self._json(200, {"ok": True, "dry_run": True, "message": msg,
                                        "would": "作废旧订阅地址并生成新地址"})
            try:
                new_token = os.urandom(5).hex()
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
                logger.log("WARN", "ADMIN", "轮换订阅 Token: 新 Token=%s (新订阅: %s)" % (new_token, new_url))
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
                    continue
                valid_nodes.append(item)
            if not valid_nodes:
                return self._json(400, {"ok": False, "error": "备份中没有有效的节点数据"})
            with _NODES_LOCK:
                _write_nodes(valid_nodes)
            if body.get("sub_token"):
                try:
                    settings = _load_json("settings.json", {})
                    settings["sub_token"] = body["sub_token"]
                    _save_json(os.path.join(DATA, "settings.json"), settings)
                except Exception:
                    pass
            render()
            logger.log("WARN", "ADMIN", f"恢复备份成功：还原了 {len(valid_nodes)} 个节点")
            return self._json(200, {"ok": True, "restored_count": len(valid_nodes), "message": f"成功恢复 {len(valid_nodes)} 个节点"})

        if path == "/removenode":
            name = (body.get("name") or "").strip()
            nodes = load_nodes()
            if len(nodes) <= 1:
                return self._json(400, {"ok": False, "error": "至少保留一个节点"})
            target = next((n for n in nodes if n["name"] == name), None)
            if not target:
                return self._json(404, {"ok": False, "error": "没找到这个节点"})
            host = target.get("host")

            to_remove = {name}
            if name.endswith("-HY2"):
                base_name = name[:-4]
                if any(n["name"] == base_name for n in nodes):
                    to_remove.add(base_name)
            else:
                hy2_name = name + "-HY2"
                if any(n["name"] == hy2_name for n in nodes):
                    to_remove.add(hy2_name)

            update_nodes(lambda ns: [n for n in ns if n["name"] not in to_remove])
            try:
                render()
            except Exception as e:
                return self._json(500, {"ok": False, "error": "订阅更新失败: %s" % e})
            stopped = None
            u = target.get("ssh_user")
            still_has_host = any(n.get("host") == host for n in load_nodes())
            if u and not still_has_host and target.get("local") is not True and host != "198.51.100.12":
                base = verify_mod.ssh_cmd(u, host, timeout=8)
                if target.get("os") == "windows":
                    remote_cmd = 'powershell -NoProfile -Command "Stop-ScheduledTask -TaskName sing-box; Disable-ScheduledTask -TaskName sing-box"'
                else:
                    remote_cmd = "systemctl disable --now sing-box 2>/dev/null || sudo -n systemctl disable --now sing-box"
                try:
                    r = subprocess.run(base + [remote_cmd], capture_output=True, text=True, timeout=40)
                    stopped = (r.returncode == 0)
                except Exception:
                    stopped = False
            logger.log("WARN", "NODE", "删除节点: %s (关联条目: %s)" % (name, ", ".join(to_remove)))
            return self._json(200, {"ok": True, "remaining": len(load_nodes()), "stopped": stopped, "removed": list(to_remove)})

        if path == "/editnode":
            name = (body.get("name") or "").strip()
            nodes = load_nodes()
            target = next((n for n in nodes if n["name"] == name), None)
            if not target:
                return self._json(404, {"ok": False, "error": "没找到这个节点"})
            newname = (body.get("newname") or "").strip()
            newkey = bool(body.get("newkey"))
            port_raw = body.get("port")
            new_port = None
            if port_raw not in (None, ""):
                try:
                    new_port = int(port_raw)
                    if new_port < 1 or new_port > 65535:
                        raise ValueError()
                except Exception:
                    return self._json(400, {"ok": False, "error": "端口必须是 1-65535"})
            new_uuid = str(uuid.uuid4()) if newkey else None
            need_remote = bool(new_uuid) or (new_port is not None and new_port != target.get("port"))
            if need_remote:
                ok, msg = patch_remote(target, uuid_new=new_uuid, port_new=new_port)
                if not ok:
                    return self._json(500, {"ok": False, "error": "服务器上改配置失败：" + msg})
            def _apply(ns):
                for n in ns:
                    if n["name"] == name:
                        if new_uuid:
                            n["uuid"] = new_uuid
                        if new_port is not None:
                            n["port"] = new_port
                        if newname and newname != name:
                            n["name"] = newname
                        if "enabled" in body:
                            n["enabled"] = bool(body["enabled"])
                        if "expire_at" in body:
                            n["expire_at"] = body["expire_at"]
                        if "lifecycle" in body and isinstance(body["lifecycle"], dict):
                            n["lifecycle"] = dict(body["lifecycle"])
                        if "state" in body:
                            lc = dict(n.get("lifecycle") or {})
                            lc["state"] = body["state"]
                            n["lifecycle"] = lc
                        if "landing_policy" in body and isinstance(body["landing_policy"], dict):
                            n["landing_policy"] = dict(body["landing_policy"])
                return ns

            update_nodes(_apply)
            target = next((n for n in load_nodes() if n["name"] == (newname or name)), target)
            try:
                render()
            except Exception as e:
                return self._json(500, {"ok": False, "error": "订阅更新失败: %s" % e})
            logger.log("INFO", "NODE", "编辑节点 %s: 新名称=%s, 端口=%s, 更换密钥=%s" %
                       (name, newname or "未改", new_port or "未改", "是" if newkey else "否"))
            return self._json(200, {"ok": True, "node": target})

        if path == "/relay/switch":
            target_host = (body.get("target") or "").strip()
            if not target_host:
                return self._json(400, {"ok": False, "error": "缺少 target 目标主机地址"})
            def _apply_switch(ns):
                for n in ns:
                    if n.get("role") == "relay" and "北京" in n.get("name", ""):
                        lp = dict(n.get("landing_policy") or {})
                        lp["active_target"] = target_host
                        n["landing_policy"] = lp
                return ns
            update_nodes(_apply_switch)
            logger.log("INFO", "RELAY", "管理员执行中转落地演练切流: 目标=%s" % target_host)
            return self._json(200, {"ok": True, "active_target": target_host})

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
                    return self._json(200, {"ok": True, "message": "所有节点健康，无需自愈", "results": []})
            else:
                target = next((n for n in nodes if n.get("name") == name), None)
                if not target:
                    return self._json(404, {"ok": False, "error": "没找到这个节点"})
                targets = [target]

            results = []
            for t in targets:
                r = repair_mod.repair_node(t)
                results.append(r)
                def _apply(ns):
                    for n in ns:
                        if n.get("name") == t.get("name"):
                            n["health"] = t.get("health")
                            if t.get("exit_ip"):
                                n["exit_ip"] = t["exit_ip"]
                                n["exit_country"] = t.get("exit_country", "")
                            if t.get("health_detail"):
                                n["health_detail"] = t["health_detail"]
                    return ns
                update_nodes(_apply)
                lvl = "INFO" if r.get("ok") else "WARN"
                logger.log(lvl, "REPAIR", "自愈节点 [%s]: %s -> %s (%s)" %
                           (t.get("name"), r.get("before"), r.get("after"), r.get("detail")))
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
            if role not in ("auto", "exit", "relay"):
                return self._json(400, {"ok": False, "error": "角色只支持 auto / exit / relay"})

            # 装前 3 秒连通性排雷与大白话提示（非演练模式下检测 22 端口）
            if not dry_run and not port_reachable(ip, 22, timeout=3):
                return self._json(400, {
                    "ok": False,
                    "error": f"无法连接服务器 {ip} 的 22 端口，请检查：1. 服务器是否已在云控制台开机；2. 安全组/防火墙是否放行了 22 端口（TCP）。"
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
                "port": port, "role": role, "node": node, "landing": landing,
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
