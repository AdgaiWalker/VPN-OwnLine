import contextlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from types import SimpleNamespace
from unittest.mock import patch

import ownline
from server import ownline_cli

ROOT = Path(__file__).resolve().parents[1]
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


class OnboardingSsotAndBackwardCompatTests(unittest.TestCase):
    def test_onboarding_json_ssot_valid_urls_dates_and_injected_fragments(self):
        data = json.loads((ROOT / "web/src/data/onboarding.json").read_text(encoding="utf-8"))
        self.assertRegex(data["checked_at"], r"^\d{4}-\d{2}-\d{2}$")

        urls = [item["url"] for item in data["vps_options"]]
        urls += [item["url"] for item in data["clients"]]
        urls.append(data["webshare_isp"]["url"])
        urls.append(data["ios_apple_id"]["shared_url"])
        urls.append(data["custom_domain"]["url"])
        bad_query_keys = {"ref", "aff", "affiliate", "invite", "code", "via", "r"}
        for url in urls:
            parsed = urllib.parse.urlsplit(url)
            self.assertEqual(parsed.scheme, "https", url)
            self.assertTrue(parsed.netloc, url)
            qs = urllib.parse.parse_qs(parsed.query)
            self.assertFalse(bad_query_keys & {k.lower() for k in qs}, f"referral param in {url}")

        for item in data["vps_options"]:
            self.assertRegex(item["checked_at"], r"^\d{4}-\d{2}-\d{2}$")

        setup_html = (ROOT / "web/local-setup.html").read_text(encoding="utf-8")
        vault_html = (ROOT / "web/local-vault.html").read_text(encoding="utf-8")
        panel_html = (ROOT / "web/index.html").read_text(encoding="utf-8")

        self.assertIn('id="no-server-guide"', setup_html)
        self.assertIn("Oracle Cloud Always Free", setup_html)
        self.assertIn("腾讯云", setup_html)
        self.assertNotIn("server-buying-guide.md", setup_html)

        self.assertIn('id="vault-webshare-guide"', vault_html)
        self.assertIn("Static Residential", vault_html)
        self.assertIn("ip:port:user:pass", vault_html)

        self.assertIn('id="panel-onboarding-guide"', panel_html)
        self.assertIn("Spaceship", panel_html)
        self.assertNotIn("server-buying-guide.md", panel_html)
        self.assertIn("只在 App Store 里登录，千万不要在手机「设置」最上方登录", panel_html)
        self.assertIn("下载完成后立即退出该账号", panel_html)

        setup_js = (ROOT / "web/src/js/local-setup.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"product\s*=\s*['\"]cvm['\"]", setup_js))

    def test_backward_compat_links_archived_legacy_and_zero_plaintext_prompts(self):
        self.assertTrue((ROOT / "docs/server-buying-guide.md").is_file())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn('id="ai-assisted-setup"', readme)

        self.assertFalse((ROOT / "docs/小白10分钟自建专属节点指南.md").exists())
        self.assertTrue((ROOT / "archive/historical-specs/小白10分钟自建专属节点指南.md").is_file())
        self.assertFalse((ROOT / "deploy/restore_master.sh").exists())
        self.assertTrue((ROOT / "archive/historical-specs/restore_master.sh").is_file())

        for rel in (
            "README.md",
            "prompt/ssh_setup.md",
            "skills/ownline-local/SKILL.md",
            "web/local-setup.html",
            "web/index.html",
        ):
            content = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("[IP:端口:密码]", content, rel)
            self.assertNotIn("填入新服务器 IP、密码、密钥", content, rel)

        for rel in (
            "web/src/data/onboarding.json",
            "ownline.py",
            "server/change_domain.sh",
            "web/local-setup.html",
            "web/local-vault.html",
        ):
            content = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIsNone(EMOJI_RE.search(content), f"unexpected emoji in {rel}")


class ColdStartAndCliDefaultsTests(unittest.TestCase):
    def test_ensure_runtime_python_skips_when_deps_present_or_disabled_or_help(self):
        exec_calls = []
        boot_calls = []
        self.assertIsNone(
            ownline.ensure_runtime_python(
                ["doctor", "--json"],
                has_deps_fn=lambda: True,
                bootstrap_fn=lambda *a, **k: boot_calls.append(a),
                exec_fn=lambda *a: exec_calls.append(a),
            )
        )
        self.assertEqual(exec_calls, [])
        self.assertEqual(boot_calls, [])

        self.assertIsNone(
            ownline.ensure_runtime_python(
                ["doctor", "--json"],
                environ={"OWNLINE_NO_BOOTSTRAP": "1"},
                has_deps_fn=lambda: False,
                bootstrap_fn=lambda *a, **k: boot_calls.append(a),
                exec_fn=lambda *a: exec_calls.append(a),
            )
        )
        self.assertIsNone(
            ownline.ensure_runtime_python(
                ["--help"],
                environ={},
                has_deps_fn=lambda: False,
                bootstrap_fn=lambda *a, **k: boot_calls.append(a),
                exec_fn=lambda *a: exec_calls.append(a),
            )
        )
        self.assertEqual(exec_calls, [])
        self.assertEqual(boot_calls, [])

    def test_ensure_runtime_python_reexecs_ready_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            venv_py = ownline.venv_python_path(tmp_path)
            venv_py.parent.mkdir(parents=True, exist_ok=True)
            venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
            (tmp_path / "ownline.py").write_text("", encoding="utf-8")

            env = {}
            called = []
            if os.name == "nt":
                rc = ownline.ensure_runtime_python(
                    ["doctor", "--json"],
                    root=tmp_path,
                    environ=env,
                    has_deps_fn=lambda: False,
                    venv_has_deps_fn=lambda p: Path(p) == venv_py,
                    subprocess_runner=lambda cmd, env=None: called.append((cmd, env)) or SimpleNamespace(returncode=0),
                )
                self.assertEqual(rc, 0)
                self.assertEqual(called[0][0][:3], [str(venv_py), "-B", str(tmp_path / "ownline.py")])
                self.assertEqual(called[0][1]["OWNLINE_BOOTSTRAPPED"], "1")
            else:
                rc = ownline.ensure_runtime_python(
                    ["doctor", "--json"],
                    root=tmp_path,
                    environ=env,
                    has_deps_fn=lambda: False,
                    venv_has_deps_fn=lambda p: Path(p) == venv_py,
                    exec_fn=lambda prog, args: called.append((prog, args)),
                )
                self.assertEqual(rc, 0)
                self.assertEqual(env["OWNLINE_BOOTSTRAPPED"], "1")
                self.assertEqual(called, [(str(venv_py), [str(venv_py), "-B", str(tmp_path / "ownline.py"), "doctor", "--json"])])

    def test_bootstrap_venv_fallback_mirrors_and_diag_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "requirements.lock").write_text("bcrypt==5.0.0\n", encoding="utf-8")
            diag_file = tmp_path / "diag.jsonl"
            venv_py = ownline.venv_python_path(tmp_path)
            has_deps = {"ready": False}
            seen_cmds = []

            def fake_runner(cmd, **kwargs):
                seen_cmds.append(cmd)
                if "-m" in cmd and "venv" in cmd:
                    venv_py.parent.mkdir(parents=True, exist_ok=True)
                    venv_py.write_text("", encoding="utf-8")
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                if any("mirrors.tuna.tsinghua.edu.cn" in str(part) for part in cmd):
                    return SimpleNamespace(returncode=1, stdout="", stderr="tuna timeout")
                has_deps["ready"] = True
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                got = ownline.bootstrap_venv(
                    tmp_path,
                    diag_log=diag_file,
                    runner=fake_runner,
                    venv_has_deps_fn=lambda p: has_deps["ready"],
                )
            self.assertEqual(got, venv_py)
            self.assertEqual(stdout_buf.getvalue(), "")
            self.assertEqual(len(seen_cmds), 3)
            self.assertIn("--require-hashes", seen_cmds[1])
            self.assertIn("https://pypi.org/simple", seen_cmds[2])
            events = [json.loads(line) for line in diag_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(events[-1]["event"], "local_env_bootstrapped")

            # Failure case emits local_env_bootstrap_failed without polluting stdout.
            has_deps["ready"] = False
            fail_diag = tmp_path / "diag_fail.jsonl"
            out_fail, err_fail = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out_fail), contextlib.redirect_stderr(err_fail):
                got_fail = ownline.bootstrap_venv(
                    tmp_path,
                    diag_log=fail_diag,
                    runner=lambda cmd, **k: SimpleNamespace(returncode=1, stdout="", stderr="network disabled"),
                    venv_has_deps_fn=lambda p: False,
                )
            self.assertIsNone(got_fail)
            self.assertEqual(out_fail.getvalue(), "")
            self.assertIn("--require-hashes", err_fail.getvalue())
            fail_events = [json.loads(line) for line in fail_diag.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(fail_events[-1]["event"], "local_env_bootstrap_failed")

    def test_cli_tencent_instances_defaults_to_all_products(self):
        parsed = ownline_cli.build_parser().parse_args(["tencent-instances", "--vault-handle", "vh_abc"])
        self.assertEqual(parsed.product, "all")

        posted = []

        class FakeClient:
            def post_json(self, path, body, timeout=None):
                posted.append((path, body))
                return 200, {"instances": [{"name": "lh-1", "ip": "1.2.3.4"}], "incomplete_regions": []}

        buf = io.StringIO()
        with patch.object(ownline_cli, "ensure_daemon", return_value=FakeClient()), contextlib.redirect_stdout(buf):
            rc = ownline_cli.main(["tencent-instances", "--vault-handle", "vh_abc", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(posted, [("/api/tencent/instances", {"vault_handle": "vh_abc"})])


class BypassScriptsHardeningTests(unittest.TestCase):
    def test_change_domain_and_rotate_static_contracts(self):
        cd_text = (ROOT / "server/change_domain.sh").read_text(encoding="utf-8")
        rot_text = (ROOT / "server/rotate.sh").read_text(encoding="utf-8")
        self.assertIn("chmod 640", cd_text)
        self.assertNotIn("chmod 644", cd_text)
        self.assertNotIn("redir https://", cd_text)
        self.assertIn("AtomicJsonStore.update", cd_text)
        self.assertIn("AtomicJsonStore.update", rot_text)

    def test_change_domain_and_rotate_offline_preserve_permissions_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mock_bin = tmp_path / "bin"
            mock_bin.mkdir()
            for name, script in (
                ("id", "#!/bin/sh\necho 0\n"),
                ("getent", "#!/bin/sh\nexit 1\n"),
                ("caddy", "#!/bin/sh\nexit 0\n"),
                ("systemctl", "#!/bin/sh\nexit 0\n"),
                ("qrencode", "#!/bin/sh\ntouch \"$2\" 2>/dev/null || true\n"),
                ("openssl", "#!/bin/sh\nprintf '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\\n'\n"),
            ):
                p = mock_bin / name
                p.write_text(script, encoding="utf-8")
                p.chmod(0o755)

            settings = tmp_path / "settings.json"
            settings.write_text(json.dumps({"domain": "old.example.com", "sub_token": "a" * 64, "sub_port": 8443}), encoding="utf-8")
            settings.chmod(0o600)

            caddyfile = tmp_path / "Caddyfile"
            caddyfile.write_text("https://old.example.com:8443 {\n  import app\n}\n", encoding="utf-8")
            caddyfile.chmod(0o640)

            env = dict(
                os.environ,
                PATH=f"{mock_bin}:{os.environ.get('PATH', '')}",
                LADDER_SETTINGS=str(settings),
                LADDER_CADDYFILE=str(caddyfile),
                LADDER_QR_OUT=str(tmp_path / "qr.png"),
            )

            res_cd = subprocess.run(
                ["bash", str(ROOT / "server/change_domain.sh"), "new.example.com", "--skip-dns-check"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("new.example.com", res_cd.stdout)
            self.assertIn("https://new.example.com:8443 {", caddyfile.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(caddyfile.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
            self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["domain"], "new.example.com")
            self.assertTrue((tmp_path / "settings.json.lock").exists())
            self.assertTrue(any(p.name.startswith("Caddyfile.bak-") for p in tmp_path.iterdir()))

            subprocess.run(
                ["bash", str(ROOT / "server/rotate.sh")],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            rotated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(rotated["sub_token"], "0123456789abcdef" * 4)
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
