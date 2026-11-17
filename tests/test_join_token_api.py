"""Automated regression and contract tests for Pre-Auth Reverse Join API."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin
from nodekit import join_token


class FakeFile:
    def __init__(self):
        self.buf = io.BytesIO()

    def write(self, data):
        self.buf.write(data)

    def getvalue(self):
        return self.buf.getvalue()


class JoinTokenApiTests(unittest.TestCase):
    def setUp(self):
        join_token.clear_all_tokens_for_testing()

    def tearDown(self):
        join_token.clear_all_tokens_for_testing()

    def test_get_join_script_valid_token(self):
        rec = join_token.create_token(name="us-west", role="exit")
        token = rec["token"]

        handler = MagicMock()
        fake_wfile = FakeFile()
        handler.wfile = fake_wfile
        handler.headers = {"Host": "proxy.example.com:8443"}
        handler.path = f"/join/{token}"

        admin.H.do_GET(handler)

        handler.send_response.assert_called_with(200)
        output = fake_wfile.getvalue().decode("utf-8")
        self.assertIn("#!/usr/bin/env bash", output)
        self.assertIn(token, output)
        self.assertIn("https://proxy.example.com:8443", output)

    def test_get_join_script_invalid_token(self):
        handler = MagicMock()
        fake_wfile = FakeFile()
        handler.wfile = fake_wfile
        handler.headers = {"Host": "127.0.0.1"}
        handler.path = "/join/badtoken00000000000000000000000000000000000000000000000000000000"

        admin.H.do_GET(handler)
        handler.send_response.assert_called_with(404)
        output = fake_wfile.getvalue().decode("utf-8")
        self.assertIn("Error: Token is invalid or expired", output)

    def test_post_create_join_token(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {"Host": "v.example.com"}

        for ep in ("/node/join-token", "/api/node/join-token"):
            captured.clear()
            handler.path = ep
            with patch("nodekit.http_utils.parse_json_body", return_value={"name": "sg-node", "role": "relay"}):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            token = captured["data"]["token"]
            self.assertEqual(len(token), 64)
            self.assertEqual(captured["data"]["name"], "sg-node")
            self.assertEqual(captured["data"]["role"], "relay")
            self.assertIn(f"--proto-redir '=https' https://v.example.com/join/{token} | bash", captured["data"]["command"])

    def test_join_host_rejects_shell_metacharacters(self):
        self.assertIsNone(admin.join_base_url('example.com";id;"'))
        self.assertEqual(admin.join_base_url('[2001:db8::1]:8443'), 'https://[2001:db8::1]:8443')

    def test_post_join_register_lifecycle_and_replay_protection(self):
        rec = join_token.create_token(name="jp-exit", role="exit")
        token = rec["token"]

        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {"Host": "v.example.com"}
        handler.path = "/join/register"

        payload = {
            "token": token,
            "host": "198.51.100.22",
            "port": 443,
            "uuid": "00000000-0000-0000-0000-000000000001",
            "pbk": "test-pbk",
            "sid": "abcd1234",
            "sni": "www.apple.com",
            "hy2_password": "mypassword123",
            "obfs_password": "obfspassword123",
        }

        with patch.object(admin.node_manager, "add_node") as mock_add_node:
            with patch("nodekit.http_utils.parse_json_body", return_value=payload):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            self.assertEqual(captured["data"]["node"]["name"], "jp-exit")
            self.assertEqual(captured["data"]["node"]["host"], "198.51.100.22")
            # Should have called add_node twice: once for vless, once for companion hy2
            self.assertEqual(mock_add_node.call_count, 2)
            vless_arg = mock_add_node.call_args_list[0][0][0]
            hy2_arg = mock_add_node.call_args_list[1][0][0]
            self.assertEqual(vless_arg["name"], "jp-exit")
            self.assertEqual(vless_arg["type"], "vless")
            self.assertEqual(vless_arg["health"], "unknown")
            self.assertFalse(vless_arg["warp_enabled"])
            self.assertEqual(hy2_arg["health"], "unknown")
            self.assertEqual(hy2_arg["name"], "jp-exit-HY2")
            self.assertEqual(hy2_arg["type"], "hysteria2")

        # Second attempt with same token (Replay Attack) must be rejected with 403
        captured.clear()
        with patch.object(admin.node_manager, "add_node") as mock_add_node:
            with patch("nodekit.http_utils.parse_json_body", return_value=payload):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 403)
            self.assertFalse(captured["data"]["ok"])
            self.assertIn("入网凭据无效或已过期", captured["data"]["error"])
            self.assertEqual(mock_add_node.call_count, 0)


if __name__ == "__main__":
    unittest.main()
