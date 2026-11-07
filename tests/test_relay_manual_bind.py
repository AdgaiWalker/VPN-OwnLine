"""HTTP 集成测试：验证 /relay/*、/hy2/toggle、/rotate 与订阅鉴权的真实控制面—数据面闭环。"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin  # noqa: E402
from nodekit import remote_config as RC  # noqa: E402
from nodekit import templates  # noqa: E402


class ManualRelayAndHy2HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self.relay_sb_dir = self.root / "relay-sb"
        self.relay_sb_dir.mkdir()
        self.exit_sb_dir = self.root / "exit-sb"
        self.exit_sb_dir.mkdir()

        # 构造真实可执行 sing-box 校验桩与 systemctl 桩
        for d in (self.relay_sb_dir, self.exit_sb_dir):
            sb = d / "sing-box"
            sb.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"check\" ] && [ \"$2\" = \"-c\" ]; then\n"
                "  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' \"$3\"\n"
                "  exit $?\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            sb.chmod(0o755)

        systemctl = self.bindir / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        systemctl.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bindir) + os.pathsep + os.environ.get("PATH", ""))

        self.relay_cfg_path = self.relay_sb_dir / "config.json"
        self.exit_cfg_path = self.exit_sb_dir / "config.json"
        self.relay_cfg_path.write_text(
            json.dumps(templates.exit_config(443, "11111111-1111-4111-8111-111111111111",
                                             "www.apple.com", "RELAY_ORIG_PRIV", "a1b2c3d4")),
            encoding="utf-8",
        )
        self.exit_cfg_path.write_text(
            json.dumps(templates.exit_config(443, "22222222-2222-4222-8222-222222222222",
                                             "www.apple.com", "EXIT_ORIG_PRIV", "e5f60718")),
            encoding="utf-8",
        )

        self.initial_nodes = [
            {
                "name": "美西出口",
                "host": "203.0.113.10",
                "port": 443,
                "uuid": "22222222-2222-4222-8222-222222222222",
                "pbk": "US_PUB_KEY",
                "sid": "e5f60718",
                "sni": "www.apple.com",
                "role": "exit",
                "health": "ok",
                "exit_ip": "203.0.113.10",
                "exit_country": "US",
                "quota_control_managed": True,
            },
            {
                "name": "亚太出口",
                "host": "203.0.113.20",
                "port": 8443,
                "uuid": "33333333-3333-4333-8333-333333333333",
                "pbk": "SG_PUB_KEY",
                "sid": "99887766",
                "sni": "www.microsoft.com",
                "role": "exit",
                "health": "ok",
                "exit_ip": "203.0.113.20",
                "exit_country": "SG",
                "quota_control_managed": True,
            },
            {
                "name": "华北入口",
                "host": "198.51.100.10",
                "port": 443,
                "uuid": "11111111-1111-4111-8111-111111111111",
                "pbk": "CN_PUB_KEY",
                "sid": "a1b2c3d4",
                "sni": "www.apple.com",
                "role": "standalone",
                "health": "unknown",
                "quota_control_managed": True,
            },
        ]
        self.nodes_file = self.data_dir / "nodes.json"
        self.nodes_file.write_text(json.dumps(self.initial_nodes), encoding="utf-8")
        (self.data_dir / "settings.json").write_text(
            json.dumps({"domain": "v.example.com", "sub_token": "a" * 64}),
            encoding="utf-8",
        )

        self.verify_ok = True

        def fake_runner(cmd, **kwargs):
            target_dir = self.relay_sb_dir if any("198.51.100.10" in str(x) for x in cmd) else self.exit_sb_dir
            remote_part = cmd[-1]
            if "| bash" in remote_part:
                script = base64.b64decode(remote_part.split()[1]).decode("utf-8")
            else:
                script = remote_part
            # 若外层包含 flock 包装的二次 base64 内层脚本，解码后替换路径再执行
            if "echo " in script and " | base64 -d | bash" in script:
                tok = [t for t in script.replace("'", " ").replace(";", " ").split() if len(t) > 24]
                if tok:
                    inner = base64.b64decode(tok[-1]).decode("utf-8")
                    script = inner
            script = script.replace("/opt/sing-box", str(target_dir))
            return subprocess.run(["bash", "-c", script], env=self.env, capture_output=True, text=True, timeout=15)

        def fake_verifier(node):
            if not self.verify_ok:
                return {"health": "proxy", "detail": "模拟探测不通"}
            landing = node.get("landing") or {}
            out_ip = landing.get("host") or node.get("host")
            cc = "SG" if out_ip == "203.0.113.20" else "US"
            return {"health": "ok", "exit_ip": out_ip, "exit_country": cc, "detail": f"出口 {out_ip} ({cc})"}

        patches = [
            patch.object(admin, "DATA", str(self.data_dir)),
            patch.object(admin, "NODES", str(self.nodes_file)),
            patch.object(admin, "INITIAL_PASSWORD_MARKER", self.data_dir / ".initial-password-required"),
            patch.object(admin.logger, "DATA", str(self.data_dir)),
            patch.object(admin.logger, "LOG_FILE", str(self.data_dir / "events.log")),
            patch.object(admin, "open_firewall", lambda ip, port, proto="TCP": ("already", "已放行")),
            patch.object(RC, "DEFAULT_RUNNER", fake_runner),
            patch.object(RC.verify_mod, "run", side_effect=fake_verifier),
            patch.object(RC.verify_mod, "tcp_ok", return_value=True),
            patch.object(RC.verify_mod, "tls_ok", return_value=True),
        ]

        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), admin.H)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _req(self, method, path, body=None):
        headers = {"Origin": self.base}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw.startswith("{") or raw.startswith("[") else raw)
        except HTTPError as e:
            try:
                raw = e.read().decode("utf-8")
                return e.code, (json.loads(raw) if raw.startswith("{") else raw)
            finally:
                e.close()

    def test_relay_bind_switch_fail_rollback_and_unbind(self):
        # 1. 绑定中转：远端写入 relay 配置并保留原私钥
        code, res = self._req("POST", "/relay/bind", {"name": "华北入口", "target": "203.0.113.10"})
        self.assertEqual(code, 200, res)
        relay_disk = json.loads(self.relay_cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(relay_disk["inbounds"][0]["tls"]["reality"]["private_key"], "RELAY_ORIG_PRIV")
        self.assertEqual(relay_disk["outbounds"][0]["server"], "203.0.113.10")

        nodes = admin.load_nodes()
        cn = next(n for n in nodes if n["name"] == "华北入口")
        self.assertEqual(cn["role"], "relay")
        self.assertEqual(cn["health"], "ok")

        # 2. 动态查询 /relay/status，不含任何硬编码个人 IP
        st_code, st_body = self._req("GET", "/relay/status")
        self.assertEqual(st_code, 200)
        self.assertEqual(st_body["node"], "华北入口")
        self.assertEqual(st_body["active_target"], "203.0.113.10")

        # 3. 演练切流但探测失败 → 返回 502，nodes.json 与远端 config.json 均保持 203.0.113.10
        self.verify_ok = False
        sw_fail_code, sw_fail = self._req("POST", "/relay/switch", {"name": "华北入口", "target": "203.0.113.20"})
        self.assertEqual(sw_fail_code, 502, sw_fail)
        self.assertTrue(sw_fail["rolled_back"])
        relay_after_fail = json.loads(self.relay_cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(relay_after_fail["outbounds"][0]["server"], "203.0.113.10")
        cn_after_fail = next(n for n in admin.load_nodes() if n["name"] == "华北入口")
        self.assertEqual(cn_after_fail["landing"]["host"], "203.0.113.10")

        # 4. 探测恢复后切流成功 → 更新为 203.0.113.20
        self.verify_ok = True
        sw_ok_code, sw_ok = self._req("POST", "/relay/switch", {"name": "华北入口", "target": "203.0.113.20"})
        self.assertEqual(sw_ok_code, 200, sw_ok)
        self.assertEqual(sw_ok["active_target"], "203.0.113.20")

        # 5. 解除中转 → 恢复 standalone，远端移除落地出站且不进订阅
        ub_code, ub_res = self._req("POST", "/relay/unbind", {"name": "华北入口"})
        self.assertEqual(ub_code, 200, ub_res)
        relay_unbound = json.loads(self.relay_cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(relay_unbound["outbounds"], [{"type": "direct", "tag": "direct"}])
        cn_unbound = next(n for n in admin.load_nodes() if n["name"] == "华北入口")
        self.assertEqual(cn_unbound["role"], "standalone")
        self.assertFalse(admin.subs_mod.in_subscription(cn_unbound))

    def test_hy2_toggle_real_config_and_quota_flag(self):
        # 1. 开启 HY2（起初 nodes.json 无美西出口-HY2 记录）
        code_on, res_on = self._req("POST", "/hy2/toggle", {"name": "美西出口", "host": "203.0.113.10", "enabled": True})
        self.assertEqual(code_on, 200, res_on)
        exit_disk = json.loads(self.exit_cfg_path.read_text(encoding="utf-8"))
        self.assertEqual([i["type"] for i in exit_disk["inbounds"]], ["vless", "hysteria2"])
        hy2_node = next(n for n in admin.load_nodes() if n.get("type") == "hysteria2")
        self.assertTrue(hy2_node["enabled"])
        self.assertTrue(hy2_node["quota_control_managed"])

        # 2. 关闭 HY2 → 远端真实移除 hysteria2 入站
        code_off, res_off = self._req("POST", "/hy2/toggle", {"name": "美西出口", "host": "203.0.113.10", "enabled": False})
        self.assertEqual(code_off, 200, res_off)
        exit_disk_off = json.loads(self.exit_cfg_path.read_text(encoding="utf-8"))
        self.assertEqual([i["type"] for i in exit_disk_off["inbounds"]], ["vless"])
        hy2_off = next(n for n in admin.load_nodes() if n.get("type") == "hysteria2")
        self.assertFalse(hy2_off["enabled"])

    def test_rotate_256bit_token_and_sub_auth_hardening(self):
        # 裸 /sub 与错误 token 均返回 404
        self.assertEqual(self._req("GET", "/sub")[0], 404)
        self.assertEqual(self._req("GET", "/s/wrongtoken")[0], 404)

        # 轮换订阅凭据生成 64 位 hex (256-bit)
        rot_code, rot_body = self._req("POST", "/rotate", {})
        self.assertEqual(rot_code, 200, rot_body)
        new_token = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))["sub_token"]
        self.assertEqual(len(new_token), 64)
        # 旧 token 立即失效，新 token 正常拉取
        self.assertEqual(self._req("GET", "/s/" + ("a" * 64))[0], 404)
        self.assertEqual(self._req("GET", f"/s/{new_token}/clash")[0], 200)


if __name__ == "__main__":
    unittest.main()
