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

    def test_normalize_api_path(self):
        self.assertEqual(http_utils.normalize_api_path("/api/nodes"), "/nodes")
        self.assertEqual(http_utils.normalize_api_path("/nodes/"), "/nodes")
        self.assertEqual(http_utils.normalize_api_path("/api/ping"), "/ping")
        self.assertEqual(http_utils.normalize_api_path("/ping"), "/ping")
        self.assertEqual(http_utils.normalize_api_path("/api"), "")

    def test_admin_router_dispatch(self):
        router = http_utils.AdminRouter()
        called_get = []
        called_post = []

        @router.get("/nodes")
        def handle_nodes(h, qs):
            called_get.append(qs)

        @router.post("/nodes/toggle")
        def handle_toggle(h, body):
            called_post.append(body)

        # 验证 /api/nodes 自动派发至 /nodes 处理函数
        self.assertTrue(router.dispatch_get(None, "/api/nodes", "v=1"))
        self.assertEqual(called_get, ["v=1"])

        # 验证 bare /nodes 同样派发成功
        self.assertTrue(router.dispatch_get(None, "/nodes", "v=2"))
        self.assertEqual(called_get, ["v=1", "v=2"])

        # 验证 POST /api/nodes/toggle 派发
        self.assertTrue(router.dispatch_post(None, "/api/nodes/toggle", {"idx": 0}))
        self.assertEqual(called_post, [{"idx": 0}])

        # 未注册路由返回 False
        self.assertFalse(router.dispatch_get(None, "/unknown", ""))


if __name__ == "__main__":
    unittest.main()
