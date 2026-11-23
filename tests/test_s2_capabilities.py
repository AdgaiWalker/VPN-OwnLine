import base64
import contextlib
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.parse

from server import local_setup, ownline_cli
from server.nodekit import local_diag
from server.nodekit.capabilities import CapabilityContext, CapabilityError, CapabilityRegistry, CapabilitySpec
from server.nodekit.local_vault import BlindVault
from server.nodekit.topology_plan import assert_plan_has_no_raw_secrets, execute_topology_plan

ROOT = Path(__file__).resolve().parents[1]


class _FakeMasterPanel:
    """In-process master panel simulating password gate, editnode, join-token, relay, reconcile, and sub."""

    def __init__(self, initial_user="admin", initial_pass="temp-initial-pass-001", sub_token="a" * 64):
        self.username = initial_user
        self.password = initial_pass
        self.sub_token = sub_token
        self.initial_locked = True
        self.password_rotations = 0
        self.isp_mutations = []
        self.relay_bindings = []
        self.verify_calls = []
        self.nodes = [
            {
                "name": "美国硅谷",
                "type": "vless",
                "role": "exit",
                "host": "198.51.100.10",
                "port": 443,
                "uuid": "11111111-1111-4111-8111-111111111111",
                "pbk": "PUBKEY123",
                "sid": "abcd1234",
                "sni": "www.apple.com",
                "health": "ok",
                "exit_ip": "198.51.100.10",
                "exit_country": "US",
                "capability": {"controllable": True, "can_mutate_remote": True, "can_verify": True},
            }
        ]
        self.server = None
        self.thread = None

    def start(self):
        panel = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, obj, ctype="application/json; charset=utf-8"):
                raw = obj if isinstance(obj, bytes) else (obj.encode("utf-8") if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False).encode("utf-8"))
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _check_auth(self):
                expected = "Basic " + base64.b64encode(f"{panel.username}:{panel.password}".encode("utf-8")).decode("ascii")
                return self.headers.get("Authorization") == expected

            def do_GET(self):
                if self.path == f"/s/{panel.sub_token}":
                    self._send(200, "vless://11111111-1111-4111-8111-111111111111@198.51.100.10:443?security=reality#exit\n", "text/plain; charset=utf-8")
                    return
                if self.path == f"/s/{panel.sub_token}/clash":
                    yaml = "proxies:\n  - name: 美国硅谷\nproxy-groups:\n  - name: AI\nrules:\n  - MATCH,AI\n"
                    self._send(200, yaml, "text/yaml; charset=utf-8")
                    return
                if not self._check_auth():
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return
                if panel.initial_locked:
                    self._send(403, {"ok": False, "error": "请先修改初始管理密码"})
                    return
                if self.path == "/api/nodes":
                    self._send(200, panel.nodes)
                elif self.path == "/api/settings":
                    self._send(200, {"ok": True, "sub_token": panel.sub_token})
                elif self.path == "/api/reconcile/status":
                    self._send(200, {"ok": True, "in_sync_count": len(panel.nodes), "drifted_count": 0})
                elif self.path == "/api/relay/status":
                    relay_node = next((n for n in panel.nodes if n.get("role") == "relay"), None)
                    self._send(200, {"ok": True, "configured": relay_node is not None, "node": (relay_node or {}).get("name"), "active_target": "198.51.100.10"})
                elif self.path.startswith("/api/node/job?id="):
                    self._send(200, {"ok": True, "state": "done", "health": "ok"})
                else:
                    self._send(404, {"ok": False, "error": "not found"})

            def do_POST(self):
                if not self._check_auth():
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if self.path == "/api/password/change":
                    if body.get("current") != panel.password:
                        self._send(403, {"ok": False, "error": "当前密码不正确"})
                        return
                    panel.password = body["new"]
                    if body.get("username"):
                        panel.username = body["username"]
                    panel.initial_locked = False
                    panel.password_rotations += 1
                    self._send(200, {"ok": True, "username": panel.username, "message": "凭据已更新"})
                    return
                if panel.initial_locked:
                    self._send(403, {"ok": False, "error": "请先修改初始管理密码"})
                    return
                if self.path == "/api/editnode":
                    target = next((n for n in panel.nodes if n["name"] == body.get("name")), None)
                    if not target:
                        self._send(404, {"ok": False, "error": "not found"})
                        return
                    isp_val = body.get("isp")
                    panel.isp_mutations.append(isp_val)
                    if isp_val:
                        # Intentionally include username/password in server echo to prove capability strips them!
                        target["isp"] = {
                            "type": "socks",
                            "server": "168.158.185.30",
                            "server_port": 6297,
                            "username": "ws-user-canary-secret",
                            "password": "ws-pass-canary-secret",
                        }
                        target["exit_ip"] = "168.158.185.30"
                        target["exit_country"] = "US"
                        target["health_detail"] = "静态住宅出口 168.158.185.30"
                    else:
                        target.pop("isp", None)
                        target["exit_ip"] = target["host"]
                    self._send(200, {"ok": True, "node": target})
                    return
                if self.path == "/api/node/join-token":
                    name = body.get("name") or "国内中继-01"
                    role = body.get("role") or "relay"
                    port = body.get("port") or 8443
                    self._send(200, {
                        "ok": True,
                        "token": "join-tok-xyz",
                        "name": name,
                        "role": role,
                        "port": port,
                        "expires_in": 900,
                        "landing": {"host": "198.51.100.10", "port": 443},
                        "command": f"curl -fsSL https://127.0.0.1:{panel.server.server_port}/join/join-tok-xyz | bash",
                    })
                    return
                if self.path == "/api/node/check":
                    fp = "SHA256:" + "C" * 43
                    if body.get("fingerprint") != fp:
                        self._send(409, {"ok": False, "code": "HOST_KEY_CONFIRMATION", "message": "需要核对指纹", "fingerprint": fp})
                        return
                    self._send(200, {"ok": True, "check_ticket": "chk-relay-99", "result": {"ready_for_install": True}})
                    return
                if self.path == "/api/addnode":
                    panel.nodes.append({
                        "name": body.get("name"),
                        "type": "vless",
                        "role": body.get("role") or "relay",
                        "host": "198.51.100.55",
                        "port": int(body.get("port") or 8443),
                        "health": "ok",
                        "capability": {"controllable": True, "can_verify": True},
                    })
                    self._send(200, {"ok": True, "job": "abc123def456"})
                    return
                if self.path == "/api/relay/bind":
                    panel.relay_bindings.append(dict(body))
                    self._send(200, {"ok": True, "binding": body})
                    return
                if self.path == "/api/verify":
                    panel.verify_calls.append(body.get("name"))
                    n = next((x for x in panel.nodes if x["name"] == body.get("name")), None)
                    self._send(200, {"ok": True, "result": {"health": "ok", "exit_ip": (n or {}).get("exit_ip", "198.51.100.10"), "detail": "ok"}})
                    return
                self._send(404, {"ok": False, "error": "not found"})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)


class _DummySession:
    def __init__(self, delivery):
        self._delivery = delivery

    def status(self):
        return {"state": "done", "delivery": dict(self._delivery)}


class S2CapabilitiesTests(unittest.TestCase):
    def test_event_registry_and_skill_doc_contract(self):
        doc_path = ROOT / "docs" / "02-本地诊断事件表.md"
        self.assertEqual(doc_path.read_text(encoding="utf-8"), local_diag.render_events_markdown())
        skill = (ROOT / "skills" / "ownline-local" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: ownline-local", skill)
        self.assertIn("ownline.py vault request", skill)
        self.assertIn("ownline.py apply", skill)
        self.assertNotIn("[IP:端口:密码]", skill)

    def test_pluggable_add_and_remove_single_file_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp)
            plugin_file = pdir / "demo_ping.py"
            plugin_file.write_text(
                "from server.nodekit.capabilities import CapabilitySpec\n"
                "def _run(ctx, params):\n"
                "    return {'ok': True, 'echo': params.get('msg', 'pong')}\n"
                "CAPABILITY = CapabilitySpec(\n"
                "    name='demo-ping', title='Demo', description='Test',\n"
                "    required_slots=(), params_schema={}, handler=_run,\n"
                ")\n",
                encoding="utf-8",
            )
            reg = CapabilityRegistry.discover(pdir)
            self.assertEqual([s["name"] for s in reg.list_specs()], ["demo-ping"])
            res = reg.execute("demo-ping", {"msg": "hello"}, ctx=CapabilityContext(vault=BlindVault()))
            self.assertEqual(res, {"ok": True, "echo": "hello"})

            # Deleting that single file cleanly removes the capability.
            plugin_file.unlink()
            reg_after = CapabilityRegistry.discover(pdir)
            self.assertEqual(reg_after.list_specs(), [])
            with self.assertRaises(CapabilityError):
                reg_after.get("demo-ping")

    def test_dynamic_canary_scrub_blocks_raw_quoted_and_base64_leaks(self):
        vault = BlindVault()
        raw_secret = "canary-secret-!@#-9988"
        sub = vault.put_direct("panel_auth", {"dashboard_url": "https://panel.test:8443", "password": raw_secret})
        quoted = urllib.parse.quote(raw_secret, safe="")
        b64 = base64.b64encode(raw_secret.encode("utf-8")).decode("ascii")

        def _leaky_handler(ctx, params):
            ctx.borrow(params["handle"], "panel_auth")
            return {
                "ok": True,
                "raw": raw_secret,
                "quoted": quoted,
                "b64": b64,
                "nested": [f"prefix-{raw_secret}-suffix"],
                "password": "explicit-key-value",
            }

        reg = CapabilityRegistry()
        reg.register(CapabilitySpec(
            name="leaky-test", title="Leaky", description="Canary",
            required_slots=("panel_auth",), params_schema={}, handler=_leaky_handler,
        ))
        out = reg.execute("leaky-test", {"handle": sub["handle"]}, ctx=CapabilityContext(vault=vault))
        serialized = json.dumps(out, ensure_ascii=False)
        for canary in (raw_secret, quoted, b64, "explicit-key-value"):
            self.assertNotIn(canary, serialized)
        self.assertEqual(out["raw"], "[REDACTED]")
        self.assertEqual(out["password"], "[REDACTED]")

    def test_raw_secret_gate_rejects_plaintext_in_plan_and_cli(self):
        for bad in (
            {"password": "abc"},
            {"nested": {"private_key": "x"}},
            {"target": "1.2.3.4:8080:wsuser:wspass"},
            {"url": "socks5://wsuser:wspass@1.2.3.4:1080"},
        ):
            with self.assertRaises(CapabilityError) as ctx:
                assert_plan_has_no_raw_secrets(bad)
            self.assertEqual(ctx.exception.code, "RAW_SECRET_FORBIDDEN")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ownline_cli.main(["cap", "run", "panel-password", "--param", "new=plain-password-1234", "--json"])
        self.assertEqual(rc, 1)
        data = json.loads(out.getvalue())
        self.assertEqual(data["code"], "RAW_SECRET_FORBIDDEN")
        self.assertNotIn("plain-password-1234", out.getvalue())

    def test_end_to_end_topology_apply_from_delivery_to_isp_relay_verify_zero_leaks(self):
        temp_pwd = "temp-initial-pass-001"
        new_panel_pwd = "ChosenStrongPass!2026"
        ws_user = "ws-user-canary-secret"
        ws_pass = "ws-pass-canary-secret"
        ssh_pass = "ssh-relay-canary-secret"
        sub_token = "a1b2c3d4" * 8

        panel = _FakeMasterPanel(initial_user="admin", initial_pass=temp_pwd, sub_token=sub_token)
        panel_url = panel.start()
        with tempfile.TemporaryDirectory() as tmp:
            diag_file = Path(tmp) / "diag.jsonl"
            state_file = Path(tmp) / "state.json"

            session = _DummySession({
                "kind": "standalone",
                "dashboard_url": panel_url + "/",
                "username": "admin",
                "temp_password": temp_pwd,
                "sub_token": sub_token,
            })
            server = local_setup.create_server(session=session, diag_log=diag_file)
            local_setup._write_state_file(state_file, server)
            th = threading.Thread(target=server.serve_forever, daemon=True)
            th.start()
            try:
                # 1. Verify cap list works.
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = ownline_cli.main(["cap", "list", "--json"], state_path=state_file, diag_log=diag_file)
                self.assertEqual(rc, 0)
                cap_names = {c["name"] for c in json.loads(out.getvalue())["capabilities"]}
                self.assertTrue({"panel-password", "residential-isp", "relay-expand", "topology-verify"}.issubset(cap_names))

                # 2. Populate vault handles via headless TTY flow.
                def _tty_put(slot, secrets_list, extra_args=()):
                    it = iter(secrets_list)
                    cap_out, cap_err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(cap_out), contextlib.redirect_stderr(cap_err):
                        code = ownline_cli.main(
                            ["vault", "request", "--slot", slot, "--mode", "tty", *extra_args, "--json"],
                            state_path=state_file,
                            diag_log=diag_file,
                            prompt_fn=lambda _: "",
                            secret_prompt_fn=lambda _: next(it),
                        )
                    self.assertEqual(code, 0, cap_out.getvalue())
                    return json.loads(cap_out.getvalue()), cap_out.getvalue() + cap_err.getvalue()

                new_panel_res, raw_1 = _tty_put("panel_auth", [new_panel_pwd], ("--hint", panel_url))
                isp_res, raw_2 = _tty_put("webshare_isp", [f"socks5://{ws_user}:{ws_pass}@168.158.185.30:6297"])
                ssh_res, raw_3 = _tty_put("ssh", [ssh_pass], ("--hint", "198.51.100.55"))

                plan = {
                    "rotate_initial_password": {"new_panel_handle": new_panel_res["handle"]},
                    "residential_isp": {"isp_handle": isp_res["handle"]},
                    "relay": {"method": "reverse_join", "role": "relay", "name": "北京中继-01"},
                    "verify": {"quick": False, "check_subscription": True},
                }
                plan_str = json.dumps(plan, ensure_ascii=False)

                # 3. Dry-run preview must NOT rotate password or bind ISP.
                dry_out = io.StringIO()
                with contextlib.redirect_stdout(dry_out):
                    rc = ownline_cli.main(["apply", "--plan-json", plan_str, "--dry-run", "--json"], state_path=state_file, diag_log=diag_file)
                self.assertEqual(rc, 0, dry_out.getvalue())
                self.assertEqual(panel.password_rotations, 0)
                self.assertEqual(panel.isp_mutations, [])
                self.assertTrue(panel.initial_locked)

                # 4. Live apply rotates initial temp password -> chains new handle -> mounts ISP -> expands relay -> verifies!
                live_out = io.StringIO()
                with contextlib.redirect_stdout(live_out):
                    rc = ownline_cli.main(["apply", "--plan-json", plan_str, "--json"], state_path=state_file, diag_log=diag_file)
                self.assertEqual(rc, 0, live_out.getvalue())
                res = json.loads(live_out.getvalue())
                self.assertTrue(res["ok"])
                self.assertFalse(panel.initial_locked)
                self.assertEqual(panel.password_rotations, 1)
                self.assertEqual(len(panel.isp_mutations), 1)
                self.assertIn(ws_pass, panel.isp_mutations[0])
                self.assertIn("美国硅谷", panel.verify_calls)

                # 5. Also verify ssh_managed HOST_KEY_CONFIRMATION retry path via active panel handle!
                active_panel_handle = res["active_panel_handle"]
                fail_out = io.StringIO()
                with contextlib.redirect_stdout(fail_out):
                    rc = ownline_cli.main(
                        [
                            "cap", "run", "relay-expand", "--json",
                            "--params-json", json.dumps({
                                "panel_handle": active_panel_handle,
                                "method": "ssh_managed",
                                "name": "广州中继-02",
                                "role": "relay",
                                "landing_host": "198.51.100.10",
                                "ssh_handle": ssh_res["handle"],
                                "poll_interval": 0.05,
                            }),
                        ],
                        state_path=state_file,
                        diag_log=diag_file,
                    )
                self.assertEqual(rc, 2)
                err_obj = json.loads(fail_out.getvalue())
                self.assertEqual(err_obj["code"], "HOST_KEY_CONFIRMATION")
                fp = err_obj["detail"]["fingerprint"]

                ok_out = io.StringIO()
                with contextlib.redirect_stdout(ok_out):
                    rc = ownline_cli.main(
                        [
                            "cap", "run", "relay-expand", "--json",
                            "--params-json", json.dumps({
                                "panel_handle": active_panel_handle,
                                "method": "ssh_managed",
                                "name": "广州中继-02",
                                "role": "relay",
                                "landing_host": "198.51.100.10",
                                "ssh_handle": ssh_res["handle"],
                                "fingerprint": fp,
                                "poll_interval": 0.05,
                            }),
                        ],
                        state_path=state_file,
                        diag_log=diag_file,
                    )
                self.assertEqual(rc, 0)
                ok_obj = json.loads(ok_out.getvalue())
                self.assertEqual(ok_obj["node_name"], "广州中继-02")
                self.assertEqual(panel.relay_bindings[-1]["name"], "广州中继-02")

                # 6. Zero-leak canary assertion across EVERY output and diag log!
                all_outputs = "\n".join([
                    raw_1,
                    raw_2,
                    raw_3,
                    dry_out.getvalue(),
                    live_out.getvalue(),
                    fail_out.getvalue(),
                    ok_out.getvalue(),
                    diag_file.read_text(encoding="utf-8"),
                ])
                for canary in (temp_pwd, new_panel_pwd, ws_user, ws_pass, ssh_pass, sub_token):
                    self.assertNotIn(canary, all_outputs)
                    self.assertNotIn(base64.b64encode(canary.encode()).decode(), all_outputs)
            finally:
                server.shutdown()
                server.server_close()
                th.join(timeout=2)
                panel.stop()

    def test_intent_to_blueprint_presets_matching_and_raw_secret_rejection(self):
        from server.nodekit.topology_plan import build_intent_blueprint

        cases = (
            ("用 ChatGPT 防封不要被拒访问", "ai_clean_ip", ["ssh", "panel_auth", "webshare_isp"]),
            ("晚高峰打视频太卡了要稳定中转", "peak_stable", ["ssh", "panel_auth"]),
            ("既要晚高峰稳定又要跑 Claude 和 AI 防封", "full_stack", ["ssh", "panel_auth", "webshare_isp"]),
            ("先搞个最便宜的基础节点", "budget_basic", ["ssh", "panel_auth"]),
            ("full_stack", "full_stack", ["ssh", "panel_auth", "webshare_isp"]),
        )
        for text, expected_preset, expected_slots in cases:
            bp = build_intent_blueprint(text)
            self.assertTrue(bp["ok"])
            self.assertEqual(bp["preset"], expected_preset, text)
            self.assertEqual(bp["required_vault_slots"], expected_slots)
            assert_plan_has_no_raw_secrets(bp["apply_plan_template"])

        # CLI `plan --list --json` & `plan --intent ... --json` work without starting daemon
        list_out = io.StringIO()
        with contextlib.redirect_stdout(list_out):
            rc = ownline_cli.main(["plan", "--list", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(set(json.loads(list_out.getvalue())["presets"]), {"budget_basic", "ai_clean_ip", "peak_stable", "full_stack"})

        intent_out = io.StringIO()
        with contextlib.redirect_stdout(intent_out):
            rc2 = ownline_cli.main(["plan", "--intent", "我要稳定中转加上 Webshare 防封", "--json"])
        self.assertEqual(rc2, 0)
        self.assertEqual(json.loads(intent_out.getvalue())["preset"], "full_stack")

        bad_out = io.StringIO()
        with contextlib.redirect_stdout(bad_out):
            rc_bad = ownline_cli.main(["plan", "--intent", "socks5://u:secretpass@1.2.3.4:1080", "--json"])
        self.assertEqual(rc_bad, 1)
        self.assertEqual(json.loads(bad_out.getvalue())["code"], "RAW_SECRET_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
