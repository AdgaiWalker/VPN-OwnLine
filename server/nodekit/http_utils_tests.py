"""http_utils 单元测试。"""
import io
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import http_utils


class HttpUtilsTests(unittest.TestCase):
    def test_validate_origin_safe(self):
        handler = MagicMock()
        handler.headers = {"Host": "example.com:8443", "Origin": "https://example.com:8443"}
        self.assertTrue(http_utils.validate_origin(handler))

    def test_validate_origin_rejects_cross_site(self):
        handler = MagicMock()
        handler.headers = {"Sec-Fetch-Site": "cross-site", "Host": "example.com"}
        self.assertFalse(http_utils.validate_origin(handler))

    def test_validate_origin_rejects_host_mismatch(self):
        handler = MagicMock()
        handler.headers = {"Host": "example.com", "Origin": "https://attacker.com"}
        self.assertFalse(http_utils.validate_origin(handler))

    def test_parse_json_body_success(self):
        handler = MagicMock()
        payload = b'{"name": "test-node", "enabled": true}'
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        code, body = http_utils.parse_json_body(handler)
        self.assertEqual(code, 200)
        self.assertEqual(body.get("name"), "test-node")

    def test_parse_json_body_invalid_json(self):
        handler = MagicMock()
        payload = b'{invalid-json}'
        handler.headers = {"Content-Length": str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        code, body = http_utils.parse_json_body(handler)
        self.assertEqual(code, 400)
        self.assertIsNone(body)


if __name__ == "__main__":
    unittest.main()
