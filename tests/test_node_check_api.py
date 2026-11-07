"""Exercise management HTTP boundaries without contacting any real host."""

from http.server import ThreadingHTTPServer
import http.client
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin  # noqa: E402


class ManagementNodeCheckAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), admin.H)
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.worker.join(3)

    def post(self, body, headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=3)
        self.addCleanup(conn.close)
        conn.request("POST", "/node/check", body, headers)
        response = conn.getresponse()
        return response.status, response.read().decode()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=3)
        self.addCleanup(conn.close)
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read().decode()

    def test_origin_and_media_type_are_checked_before_worker(self):
        with patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-ownline-test-marker")), patch.object(admin.node_check_bridge, "check") as worker:
            status, _ = self.post('{"password":"fixture-secret"}', {"Content-Type": "application/json", "Origin": "https://evil.example"})
            self.assertEqual(status, 403)
            status, _ = self.post('{"password":"fixture-secret"}', {"Content-Type": "text/plain"})
            self.assertEqual(status, 415)
            worker.assert_not_called()

    def test_result_and_fingerprint_challenge_never_echo_request_secret(self):
        with patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-ownline-test-marker")), patch.object(admin.node_check_bridge, "check") as worker:
            worker.return_value = {"ok": False, "code": "HOST_KEY_CONFIRMATION", "fingerprint": "SHA256:" + "A" * 43}
            status, payload = self.post('{"password":"fixture-secret"}', {"Content-Type": "application/json"})
            self.assertEqual(status, 409)
            self.assertNotIn("fixture-secret", payload)
            worker.assert_called_once_with({"password": "fixture-secret"})

    def test_progress_omits_node_secrets_and_handles_unknown_job(self):
        jobs = {"a" * 12: {"state":"running", "step":2, "log":["private-secret"],
                            "node":{"password":"private-secret"}, "verify":{"health":"unknown"}}}
        with patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-ownline-test-marker")), patch.object(admin, "JOBS", jobs):
            status, body = self.get("/node/job?id=" + "a" * 12)
            self.assertEqual(status, 200)
            self.assertNotIn("private-secret", body)
            self.assertIn('"step": 2', body)
            self.assertEqual(self.get("/node/job?id=" + "b" * 12)[0], 404)


if __name__ == "__main__":
    unittest.main()
