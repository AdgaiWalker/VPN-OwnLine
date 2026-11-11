"""Automated tests for Client Ping RTT API endpoint."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin


class PingApiTests(unittest.TestCase):
    def test_get_ping_returns_204_no_content(self):
        handler = MagicMock()
        sent_status = []
        sent_headers = {}

        def fake_send_response(code):
            sent_status.append(code)

        def fake_send_header(k, v):
            sent_headers[k] = v

        handler.send_response = fake_send_response
        handler.send_header = fake_send_header
        handler.end_headers = MagicMock()

        for path in ("/api/ping", "/ping"):
            sent_status.clear()
            sent_headers.clear()
            handler.path = path
            admin.H.do_GET(handler)
            self.assertEqual(sent_status, [204], f"{path} must return HTTP 204")
            self.assertEqual(sent_headers.get("Content-Length"), "0")
            self.assertIn("no-store", sent_headers.get("Cache-Control", ""))

    def test_head_ping_delegates_to_get(self):
        handler = MagicMock()
        sent_status = []
        handler.send_response = lambda code: sent_status.append(code)
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.do_GET = lambda: admin.H.do_GET(handler)

        handler.path = "/api/ping"
        admin.H.do_HEAD(handler)
        self.assertEqual(sent_status, [204])


if __name__ == "__main__":
    unittest.main()
