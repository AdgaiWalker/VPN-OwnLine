#!/usr/bin/env python3
import json, os, re, subprocess, sys, threading, time, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = "/opt/web"
MAX_BODY = 1_000_000  # 1MB：私钥最多几 KB，超了就是有人在搞事
from nodekit import verify as verify_mod  # noqa: E402
from nodekit import links as links_mod  # noqa: E402
from nodekit import advise as advise_mod  # noqa: E402
from nodekit import hints as hints_mod  # noqa: E402
sys.path.insert(0, WEB)
NODES = os.path.join(WEB, "nodes.json")
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

BAD_HEALTH = {"port", "tls", "role_mismatch", "landing", "timeout"}


def render():
    # 中转不进订阅；故障节点也不进（unknown 视为未验证，仍然保留）
    nodes = [n for n in load_nodes()
             if (n.get("role") or "exit") != "relay" and n.get("health") not in BAD_HEALTH]
    src = urllib.parse.quote("|".join(vless(n) for n in nodes), safe="")
    with open(CADDY, encoding="utf-8") as f:
        txt = f.read()
    new = re.sub(r"url=[^&\s]+", "url=" + src, txt, count=1)
    with open(CADDY, "w", encoding="utf-8") as f:
        f.write(new)
    subprocess.run(["systemctl", "reload", "caddy"], check=True, capture_output=True)

def _gen_node():
    """生成一套节点参数（uuid / reality 密钥对 / short_id）。"""
    binp = "/opt/sing-box/sing-box"
    uid = subprocess.check_output([binp, "generate", "uuid"], text=True).strip()
    kp = subprocess.check_output([binp, "generate", "reality-keypair"], text=True)
    priv = re.search(r"PrivateKey:\s*(\S+)", kp).group(1)
    pub = re.search(r"PublicKey:\s*(\S+)", kp).group(1)
    return {"uuid": uid, "private_key": priv, "pbk": pub,
            "sid": os.urandom(4).hex(), "sni": "www.apple.com"}


def _write_job(jid, data, secret):
    """任务写文件（0600），凭据单独一个文件：不进 argv、不进日志。"""
    d = os.path.join(WEB, ".jobs")
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
                except Exception as e:
                    j["log"].append("parse error: %s" % e)
            j["log"].append(line)
            j["log"] = j["log"][-60:]
        rc = p.wait()
        if rc != 0 or (not j.get("node") and not dry):
            j["state"] = "error"
            j["error"] = "installation failed"
            j["hint"] = hints_mod.hint_from_log(j["log"])
        else:
            j["state"] = "done"
            if j.get("node"):
                verify_async(j["node"].get("name"))
            if dry and not j.get("node"):
                j["warn"] = "dry_run"
                j["log"].append("演练完成：未对目标机做任何修改")
                return
            j["warn"] = "port_blocked" if any("PORT_BLOCKED" in l for l in j["log"]) else ""
            if j["warn"] == "port_blocked" and j.get("node"):
                st, msg = open_firewall(j["node"]["host"], j["node"]["port"])
                j["log"].append("防火墙: " + msg)
                if st in ("opened", "already"):
                    time.sleep(3)
                    if port_reachable(j["node"]["host"], j["node"]["port"]):
                        j["warn"] = ""
                        j["log"].append("端口已通，节点可用")
                    else:
                        j["log"].append("端口仍不通：可能有云端安全组之外的拦截")
                else:
                    j["log"].append("没能自动放行，需要手动去控制台加规则")
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

def patch_remote(node, uuid_new=None, port_new=None):
    host = node.get("host", "")
    try:
        if host == "198.51.100.12":
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
        base = ["ssh", "-i", "/root/.ssh/node_ctl", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=10", "%s@%s" % (u, host)]
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

def open_firewall(ip, port):
    import providers
    st, msg, who = providers.open_port(ip, port)
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
        with open(os.path.join(WEB, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def nodes_with_advice():
    """节点 + 一句建议（依据来自探活与流量）。"""
    status = _load_json("status.json", {})
    usage = _load_json("usage.json", {})
    out = []
    for n in load_nodes():
        n = dict(n)
        n["advice"] = advise_mod.advise(n, status.get(n.get("name")), usage.get(n.get("host")))
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
        if path in ("/nodes", ""):
            return self._json(200, nodes_with_advice())
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
                r = subprocess.run(["/opt/web/rotate.sh"], capture_output=True, text=True, timeout=90)
                url = ""
                for line in r.stdout.splitlines():
                    if line.startswith("新订阅地址:"):
                        url = line.split(":", 1)[1].strip()
                return self._json(200, {"ok": r.returncode == 0 and bool(url), "url": url,
                                  "message": msg})
            except Exception as e:
                return self._json(500, {"ok": False, "error": str(e)})

        if path == "/removenode":
            name = (body.get("name") or "").strip()
            nodes = load_nodes()
            if len(nodes) <= 1:
                return self._json(400, {"ok": False, "error": "至少保留一个节点"})
            target = next((n for n in nodes if n["name"] == name), None)
            if not target:
                return self._json(404, {"ok": False, "error": "没找到这个节点"})
            update_nodes(lambda ns: [n for n in ns if n["name"] != name])
            try:
                render()
            except Exception as e:
                return self._json(500, {"ok": False, "error": "订阅更新失败: %s" % e})
            stopped = None
            u = target.get("ssh_user")
            if u and target.get("host") != "198.51.100.12":
                base = ["ssh", "-i", "/root/.ssh/node_ctl",
                        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                        "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=8",
                        "%s@%s" % (u, target["host"])]
                if target.get("os") == "windows":
                    remote_cmd = 'powershell -NoProfile -Command "Stop-ScheduledTask -TaskName sing-box; Disable-ScheduledTask -TaskName sing-box"'
                else:
                    remote_cmd = "systemctl disable --now sing-box 2>/dev/null || sudo -n systemctl disable --now sing-box"
                try:
                    r = subprocess.run(base + [remote_cmd], capture_output=True, text=True, timeout=40)
                    stopped = (r.returncode == 0)
                except Exception:
                    stopped = False
            return self._json(200, {"ok": True, "remaining": len(load_nodes()), "stopped": stopped})

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
                return ns

            update_nodes(_apply)
            target = next((n for n in load_nodes() if n["name"] == (newname or name)), target)
            try:
                render()
            except Exception as e:
                return self._json(500, {"ok": False, "error": "订阅更新失败: %s" % e})
            return self._json(200, {"ok": True, "node": target})

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

        if path == "/paste":
            raw = (body.get("links") or body.get("link") or "").strip()
            if not raw:
                return self._json(400, {"ok": False, "error": "链接是空的"})
            added, errors = [], []
            nodes = load_nodes()
            for line in [x.strip() for x in raw.splitlines() if x.strip()]:
                try:
                    p = links_mod.parse(line)
                except Exception as e:
                    errors.append(str(e))
                    continue
                in_sub = [n for n in nodes
                          if (n.get("role") or "exit") != "relay" and n.get("health") not in BAD_HEALTH]
                if any(n.get("host") == p["host"] and int(n.get("port") or 0) == p["port"] for n in in_sub):
                    errors.append("这台已经在列表里：%s" % p["host"])
                    continue
                p.update({"role": "exit", "source": "external", "health": "unknown"})
                nodes.append(p)
                added.append(p["name"])
            if added:
                update_nodes(lambda ns: ns + [n for n in nodes if n["name"] in added])
                render()
            return self._json(200, {"ok": bool(added), "added": added, "errors": errors})

        if path == "/verify":
            name = (body.get("name") or "").strip()
            nodes = load_nodes()
            node = next((n for n in nodes if n.get("name") == name), None)
            if not node:
                return self._json(404, {"ok": False, "error": "没找到这个节点"})
            if node.get("source") == "external":
                return self._json(400, {"ok": False, "error": "外部节点无法验证（没有控制权）"})
            r = verify_node(node)
            return self._json(200, {"ok": True, "result": r})

        if path == "/addnode":
            ip = (body.get("ip") or "").strip()
            user = (body.get("user") or "root").strip() or "root"
            auth_type = (body.get("auth_type") or "password").strip()
            pwd = body.get("pass") or ""
            key_text = body.get("private_key") or ""
            name = (body.get("name") or "").strip() or ("节点-" + ip)
            role = (body.get("role") or "exit").strip()
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
            if role not in ("exit", "relay"):
                return self._json(400, {"ok": False, "error": "角色只支持 exit 或 relay"})
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

ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
