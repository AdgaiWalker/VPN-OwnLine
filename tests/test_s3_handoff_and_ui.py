import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from server import local_setup

ROOT = Path(__file__).resolve().parents[1]


class S3AgentHandoffAndUiTests(unittest.TestCase):
    def _http(self, origin, token, method, path, body=None):
        import urllib.parse
        parsed = urllib.parse.urlsplit(origin)
        conn = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=5)
        headers = {"Host": parsed.netloc, "Cookie": "ownline_setup=" + token}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            headers["Origin"] = origin
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_sigkill_agent_mid_flight_then_fallback_ui_reattaches_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "agent_state.json"
            diag_file = Path(tmp) / "diag.jsonl"
            env = dict(os.environ, OWNLINE_LOCAL_STATE=str(state_file), OWNLINE_DIAG_LOG=str(diag_file))

            # 1. Start real detached local daemon process (simulating Agent-spawned daemon).
            daemon = subprocess.Popen(
                [sys.executable, "-B", "-m", "server.local_setup", "--no-browser", "--state-file", str(state_file), "--diag-log", str(diag_file)],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            agent = None
            try:
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline and not state_file.is_file():
                    time.sleep(0.05)
                self.assertTrue(state_file.is_file(), "daemon state file not written")
                state_before = json.loads(state_file.read_text(encoding="utf-8"))
                origin = state_before["origin"]
                token = state_before["token"]

                # 2. Launch a simulated Agent blocking in browser vault request, then SIGKILL it mid-flight.
                agent = subprocess.Popen(
                    [sys.executable, str(ROOT / "ownline.py"), "vault", "request", "--slot", "ssh", "--hint", "198.51.100.44", "--mode", "browser", "--no-browser", "--timeout", "120", "--json"],
                    cwd=str(ROOT),
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.35)
                self.assertIsNone(agent.poll(), "agent exited prematurely before SIGKILL")
                os.kill(agent.pid, signal.SIGKILL)
                agent.wait(timeout=3)

                # 3. User opens fallback UI (启动安装.command / ownline.py ui) -> must reattach without overwriting daemon!
                opened = []
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = local_setup.main(
                        ["--state-file", str(state_file), "--diag-log", str(diag_file)],
                        open_browser_fn=opened.append,
                    )
                self.assertEqual(rc, 0)
                self.assertEqual(opened, [origin])
                self.assertIn("已接管", out.getvalue())

                state_after = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(state_after["pid"], state_before["pid"])
                self.assertEqual(state_after["port"], state_before["port"])
                self.assertEqual(state_after["token"], token)

                # Daemon continues serving live fallback HTML, status, and diagnostic reattach event.
                st_page, html_bytes = self._http(origin, token, "GET", "/")
                self.assertEqual(st_page, 200)
                self.assertIn(b"step-rail", html_bytes)
                st_api, _ = self._http(origin, token, "GET", "/api/status")
                self.assertEqual(st_api, 200)

                diag_lines = [json.loads(ln) for ln in diag_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
                self.assertTrue(
                    any(e["event"] == "fallback_ui_opened" and e["detail"].get("reattached") is True for e in diag_lines),
                    f"missing reattached fallback_ui_opened event in {diag_lines}",
                )

                # Clean daemon quit via HTTP API.
                st_quit, _ = self._http(origin, token, "POST", "/api/quit", {})
                self.assertEqual(st_quit, 200)
                daemon.wait(timeout=5)
                self.assertFalse(state_file.exists())
            finally:
                if agent and agent.poll() is None:
                    agent.kill()
                    agent.wait(timeout=2)
                if daemon.poll() is None:
                    daemon.terminate()
                    daemon.wait(timeout=3)

    def test_stale_state_file_returns_none_on_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "stale.json"
            stale.write_text(json.dumps({"pid": 999999, "port": 1, "origin": "http://127.0.0.1:1", "token": "dead"}), encoding="utf-8")
            self.assertIsNone(local_setup._probe_running_daemon(stale))

    def test_synthesized_local_pages_have_lucide_icons_no_emojis_and_progressive_disclosure(self):
        emoji_re = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
        for rel in ("web/local-setup.html", "web/local-vault.html"):
            html = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIsNone(emoji_re.search(html), f"emoji found in {rel}")
            self.assertIn('<symbol id="i-shield"', html)
            self.assertIn(":user-invalid", html)
            self.assertIn("prefers-reduced-motion: no-preference", html)

        setup_html = (ROOT / "web/local-setup.html").read_text(encoding="utf-8")
        self.assertIn('<details id="ssh-help-details">', setup_html)
        self.assertNotIn('<details id="ssh-help-details" open', setup_html)
        self.assertIn('id="step-rail"', setup_html)


if __name__ == "__main__":
    unittest.main()
