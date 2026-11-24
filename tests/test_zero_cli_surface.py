"""Offline gates preventing CLI-mindset regressions, runtime path breaks, and docs contradictions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

import ownline
from scripts import build_installer
from server.nodekit import runtime_paths

ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN_DEFAULT_TOKENS = (
    "journalctl",
    "authorized_keys",
    "requirements.lock",
    "install-python-deps.sh",
    "vault request --mode tty",
    "返回命令行",
    "请在终端",
    "python3 ownline.py",
    "sudo bash",
    "curl -I",
    "配 sudo 免密",
    "一键自愈修复",
)


def _strip_designated_advanced_blocks(html: str) -> str:
    """Strip explicitly collapsed advanced/agent/paste sections before scanning default UI surface."""
    cleaned = re.sub(
        r'<details id="ssh-help-details">.*?</details>',
        "",
        html,
        flags=re.S,
    )
    cleaned = re.sub(
        r'<details id="vault-webshare-guide"[^>]*>.*?</details>',
        "",
        cleaned,
        flags=re.S,
    )
    cleaned = re.sub(
        r'<details class="inner install-guide" id="tc-install-guide"[^>]*>.*?</details>',
        "",
        cleaned,
        flags=re.S,
    )
    cleaned = re.sub(
        r'<div id="box-reverse-join"[^>]*>.*?<!-- Mode 2: Direct SSH Connection',
        '<!-- Mode 2: Direct SSH Connection',
        cleaned,
        flags=re.S,
    )
    cleaned = re.sub(r'<pre id="ai-ssh-prompt-text"[^>]*>.*?</pre>', "", cleaned, flags=re.S)
    cleaned = re.sub(r'<pre id="ai-prompt-text"[^>]*>.*?</pre>', "", cleaned, flags=re.S)
    cleaned = re.sub(r'<textarea id="isp-smart-input"[^>]*>', "<textarea>", cleaned, flags=re.S)
    cleaned = re.sub(r'<input id="vault-isp-proxy"[^>]*>', "<input>", cleaned, flags=re.S)
    return cleaned


class ZeroCliSurfaceGateTests(unittest.TestCase):
    def test_no_cli_leakage_in_default_web_surfaces_and_hints(self):
        for rel in (
            "web/index.html",
            "web/local-setup.html",
            "web/local-vault.html",
            "web/change-password.html",
        ):
            raw = (ROOT / rel).read_text(encoding="utf-8")
            surface = _strip_designated_advanced_blocks(raw)
            for token in _FORBIDDEN_DEFAULT_TOKENS:
                self.assertNotIn(token, surface, f"CLI leak token {token!r} found in default UI of {rel}")

        hints_src = (ROOT / "server/nodekit/hints.py").read_text(encoding="utf-8")
        for token in _FORBIDDEN_DEFAULT_TOKENS:
            self.assertNotIn(token, hints_src, f"CLI leak token {token!r} found in server/nodekit/hints.py")

    def test_80_tcp_and_non_root_sudo_truth_consistent_across_surfaces(self):
        onboarding = json.loads((ROOT / "web/src/data/onboarding.json").read_text(encoding="utf-8"))
        ports_joined = " ".join(onboarding["server_requirements"]["ports"])
        self.assertIn("80/TCP", ports_joined)
        self.assertNotIn("仅绑定自定义域名", ports_joined)
        self.assertIn("ubuntu", onboarding["server_requirements"]["os"])
        self.assertNotIn("change_domain.sh", onboarding["custom_domain"]["note"])

        setup_html = (ROOT / "web/local-setup.html").read_text(encoding="utf-8")
        self.assertIn("80/TCP", setup_html)
        self.assertIn('id="copy-password"', setup_html)
        self.assertIn("信任并锁定", setup_html)

        panel_html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn("navigator.language", (ROOT / "web/change-password.html").read_text(encoding="utf-8"))
        self.assertRegex(panel_html, r'id="tab-btn-ssh-direct"[^>]*aria-pressed="true"')

    def test_runtime_paths_and_frozen_entrypoint_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Mock a macOS PyInstaller BUNDLE layout: Resources holds real files, Frameworks has symlinks
            contents = tmp_path / "OwnLine-Setup.app" / "Contents"
            fw = contents / "Frameworks"
            res = contents / "Resources"
            fw.mkdir(parents=True)
            (res / "server").mkdir(parents=True)
            (res / "server" / "admin.py").write_text("# real\n", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(fw), create=True), \
                 patch.object(sys, "platform", "darwin"):
                self.assertTrue(runtime_paths.is_frozen())
                self.assertEqual(runtime_paths.bundle_root(), res.resolve())

            home_dir = tmp_path / "home"
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(res), create=True), \
                 patch.dict(os.environ, {"HOME": str(home_dir), "OWNLINE_STATE_DIR": ""}), \
                 patch.object(Path, "home", return_value=home_dir):
                st_dir = runtime_paths.writable_state_dir()
                self.assertEqual(st_dir, home_dir / ".ownline")
                self.assertTrue(st_dir.is_dir())

            # Windowed (--noconsole) sys.stdout/stderr None safety + frozen default ['ui']
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "stdout", None), \
                 patch.object(sys, "stderr", None):
                try:
                    argv = ownline._prepare_stdio_and_argv([])
                    self.assertEqual(argv, ["ui"])
                    self.assertIsNotNone(sys.stdout)
                    self.assertIsNotNone(sys.stderr)
                finally:
                    if sys.stdout and not sys.stdout.closed:
                        sys.stdout.close()
                    if sys.stderr and not sys.stderr.closed:
                        sys.stderr.close()

            with patch.object(sys, "frozen", True, create=True):
                self.assertIsNone(
                    ownline.ensure_runtime_python(
                        ["ui"],
                        has_deps_fn=lambda: False,
                        bootstrap_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("frozen must skip bootstrap")),
                    )
                )

    def test_installer_staging_payload_succeeds_without_symlinks_or_private_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = build_installer.stage_payload(ROOT, Path(tmp) / "stage")
            self.assertTrue((stage / "server" / "admin.py").is_file())
            self.assertTrue((stage / "deploy" / "install.sh").is_file())
            self.assertTrue((stage / "web" / "local-setup.html").is_file())
            self.assertTrue((stage / "requirements.lock").is_file())
            self.assertFalse((stage / ".ops-private").exists())
            self.assertFalse((stage / "tests").exists())
            self.assertEqual(build_installer.main(["--check-stage"]), 0)


if __name__ == "__main__":
    unittest.main()
