"""Automated tests for Quick Feedback API contracts and dual prefix matching."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin


class FeedbackApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_data = admin.DATA
        admin.DATA = self.temp_dir.name
        self.feedback_file = os.path.join(self.temp_dir.name, "feedback.jsonl")

    def tearDown(self):
        admin.DATA = self.orig_data
        self.temp_dir.cleanup()

    def test_post_feedback_dual_prefix(self):
        for endpoint in ("/feedback", "/api/feedback"):
            handler = MagicMock()
            captured = {}

            def fake_json(status, data):
                captured["status"] = status
                captured["data"] = data

            handler._json = fake_json
            handler._origin_ok = lambda: True
            handler.path = endpoint
            handler.headers = {"Content-Length": "100", "X-Forwarded-For": "1.2.3.4"}
            handler.client_address = ("127.0.0.1", 12345)

            body = {
                "type": "connection",
                "message": f"Test message for {endpoint}",
                "contact": "test@example.com",
                "diagnostics": {"version": "v0.6.0", "node_count": 2}
            }
            body_bytes = json.dumps(body).encode()
            handler.headers = {"Content-Length": str(len(body_bytes)), "X-Forwarded-For": "1.2.3.4"}
            handler.rfile = MagicMock()
            handler.rfile.read = lambda n: body_bytes

            admin.H.do_POST(handler)
            self.assertEqual(captured["status"], 200, f"{endpoint} should return 200")
            self.assertTrue(captured["data"]["ok"])
            self.assertIn("id", captured["data"])

        # Verify entries in feedback.jsonl
        self.assertTrue(os.path.exists(self.feedback_file))
        with open(self.feedback_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["type"], "connection")
        self.assertEqual(lines[0]["contact"], "test@example.com")
        self.assertEqual(lines[0]["diagnostics"]["version"], "v0.6.0")

    def test_post_feedback_validation(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler._origin_ok = lambda: True
        handler.path = "/api/feedback"
        handler.client_address = ("127.0.0.1", 12345)

        # 1. Empty message
        body_bytes = json.dumps({"type": "bug", "message": ""}).encode()
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = MagicMock()
        handler.rfile.read = lambda n: body_bytes
        admin.H.do_POST(handler)
        self.assertEqual(captured["status"], 400)
        self.assertFalse(captured["data"]["ok"])

        # 2. Oversized message
        captured.clear()
        long_msg = "x" * 4500
        body_bytes = json.dumps({"type": "bug", "message": long_msg}).encode()
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = MagicMock()
        handler.rfile.read = lambda n: body_bytes
        admin.H.do_POST(handler)
        self.assertEqual(captured["status"], 400)
        self.assertFalse(captured["data"]["ok"])

    def test_get_feedback_dual_prefix(self):
        # Prepopulate feedback file
        os.makedirs(self.temp_dir.name, exist_ok=True)
        with open(self.feedback_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "fb1", "type": "suggestion", "message": "Hello"}) + "\n")

        for endpoint in ("/feedback", "/api/feedback"):
            handler = MagicMock()
            captured = {}

            def fake_json(status, data):
                captured["status"] = status
                captured["data"] = data

            handler._json = fake_json
            handler.path = endpoint
            handler.headers = {}

            admin.H.do_GET(handler)
            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            self.assertEqual(len(captured["data"]["feedback"]), 1)
            self.assertEqual(captured["data"]["feedback"][0]["id"], "fb1")


if __name__ == "__main__":
    unittest.main()
