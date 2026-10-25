#!/usr/bin/env python3
import json, os, re, subprocess, sys, threading, time, urllib.parse, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = "/opt/web"
sys.path.insert(0, WEB)
NODES = os.path.join(WEB, "nodes.json")
CADDY = "/etc/caddy/Caddyfile"
JOBS = {}

def load_nodes():
    with open(NODES, encoding="utf-8") as f:
        return json.load(f)

def save_nodes(nodes):
    with open(NODES, "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=1)

def vless(n):
    q = ("encryption=none&flow=xtls-rprx-vision&security=reality"
         "&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp&headerType=none" % (n["sni"], n["pbk"], n["sid"]))
    return "vless://%s@%s:%s?%s#%s" % (n["uuid"], n["host"], n["port"], q, urllib.parse.quote(n["name"]))

def render():
    nodes = load_nodes()
    src = urllib.parse.quote("|".join(vless(n) for n in nodes), safe="")
    with open(CADDY, encoding="utf-8") as f:
        txt = f.read()
    new = re.sub(r"url=[^&\s]+", "url=" + src, txt, count=1)
    with open(CADDY, "w", encoding="utf-8") as f:
        f.write(new)
    subprocess.run(["systemctl", "reload", "caddy"], check=True, capture_output=True)

def _hint_from_log(lines):
    txt = "\n".join(lines).lower()
    if "permission denied" in txt:
        return "密码不对，或者这台机器不允许 root 用密码登录。\n去腾讯云控制台 → 实例 → 重置密码（用户选 root），再用新密码试。"
    if "curl:" in txt or "recv failure" in txt or "could not resolve host" in txt or "failed to connect" in txt:
        return "服务器下载 sing-box 失败。\n多半是这台机器连不上 GitHub（国内机器常见）。换成从我们服务器推给它。"
    if "ssh: connect" in txt and ("timed out" in txt or "refused" in txt):
        return "连不上这台机器的 22 端口。\n可能是防火墙没放行，或者机器没开机。"
    if "connection timed out" in txt:
        return "网络超时，中途断了。"
    if "sudo: a password is required" in txt:
        return "登录的这个用户不是 root，而且 sudo 需要密码。\n把用户名改成 root 再试。"
    if "host key verification failed" in txt:
        return "这台机器的主机指纹变了（可能重装过系统）。"
    if "unsupported arch" in txt:
        return "这台机器的 CPU 架构不支持，目前只支持 x86_64 和 arm64。"
    if "no space left" in txt:
        return "服务器磁盘满了。"
    return "看下面的原始输出。常见原因：密码错、22 端口没开、服务器不是 Linux、或者这台机器不接受密码登录。"

def run_job(jid, args):
    j = JOBS[jid]
    j["state"] = "running"
    try:
        p = subprocess.Popen(["/opt/web/addnode.sh"] + args, stdout=subprocess.PIPE,
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
                    nodes = [n for n in load_nodes() if n["name"] != node["name"]]
                    nodes.append(node)
                    save_nodes(nodes)
                    render()
                    j["node"] = node
                except Exception as e:
                    j["log"].append("parse error: %s" % e)
            j["log"].append(line)
            j["log"] = j["log"][-60:]
        rc = p.wait()
        if rc != 0 or not j.get("node"):
            j["state"] = "error"
            j["error"] = "installation failed"
            j["hint"] = _hint_from_log(j["log"])
        else:
            j["state"] = "done"
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

class H(BaseHTTPRequestHandler):
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
            return self._json(200, load_nodes())
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

    def do_POST(self):
        path = self.path.rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            body = {}

        if path == "/rotate":
            try:
                r = subprocess.run(["/opt/web/rotate.sh"], capture_output=True, text=True, timeout=90)
                url = ""
                for line in r.stdout.splitlines():
                    if line.startswith("新订阅地址:"):
                        url = line.split(":", 1)[1].strip()
                return self._json(200, {"ok": r.returncode == 0 and bool(url), "url": url})
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
            new_nodes = [n for n in nodes if n["name"] != name]
            save_nodes(new_nodes)
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
            return self._json(200, {"ok": True, "remaining": len(new_nodes), "stopped": stopped})

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
            if new_uuid:
                target["uuid"] = new_uuid
            if new_port is not None:
                target["port"] = new_port
            if newname and newname != target["name"]:
                if any(n["name"] == newname for n in nodes):
                    return self._json(400, {"ok": False, "error": "已有同名节点"})
                target["name"] = newname
            save_nodes(nodes)
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

        if path == "/addnode":
            ip = (body.get("ip") or "").strip()
            user = (body.get("user") or "root").strip() or "root"
            pwd = body.get("pass") or ""
            name = (body.get("name") or "").strip() or ("节点-" + ip)
            port = str(body.get("port") or 443)
            if not _valid_host(ip):
                return self._json(400, {"ok": False, "error": "地址格式不对（IP 或域名）"})
            if not pwd:
                return self._json(400, {"ok": False, "error": "密码不能为空"})
            jid = uuid.uuid4().hex[:12]
            JOBS[jid] = {"state": "queued", "step": 0, "stepname": "", "log": []}
            t = threading.Thread(target=run_job, args=(jid, [ip, user, pwd, name, port]), daemon=True)
            t.start()
            return self._json(200, {"ok": True, "job": jid})

        self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, *args):
        pass

ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
