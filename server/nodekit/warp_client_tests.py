"""WARP 注册客户端单测 (100% 离线，纯 Mock)。"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from . import warp_client
except ImportError:
    from nodekit import warp_client


class TestWarpClient(unittest.TestCase):
    def test_generate_keypair_returns_valid_base64_32bytes(self):
        priv, pub = warp_client.generate_keypair()
        self.assertTrue(isinstance(priv, str) and len(priv) >= 40)
        self.assertTrue(isinstance(pub, str) and len(pub) >= 40)
        # 确保两次生成结果不同
        priv2, pub2 = warp_client.generate_keypair()
        self.assertNotEqual(priv, priv2)
        self.assertNotEqual(pub, pub2)

    def test_rfc7748_fallback_scalarmult(self):
        priv_bytes = bytes([1] * 32)
        base_point = (9).to_bytes(32, "little")
        pub = warp_client._rfc7748_scalarmult(priv_bytes, base_point)
        self.assertEqual(len(pub), 32)

    @patch("urllib.request.urlopen")
    def test_register_warp_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "mock-client-id-1234",
            "account": {"id": "mock-acc-5678"},
            "config": {
                "peers": [{
                    "public_key": "MOCK_PEER_PUBKEY_TEST=",
                    "endpoint": {"host": "engage.cloudflareclient.com:2408"}
                }],
                "interface": {
                    "addresses": {
                        "v4": "172.16.0.2",
                        "v6": "2606:4700:110:8f38:17f5:3836:2127:5811"
                    }
                }
            }
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = warp_client.register_warp(keypair=("TEST_PRIV=", "TEST_PUB="))
        self.assertTrue(res["ok"])
        self.assertEqual(res["private_key"], "TEST_PRIV=")
        self.assertEqual(res["public_key"], "TEST_PUB=")
        self.assertEqual(res["peer_public_key"], "MOCK_PEER_PUBKEY_TEST=")
        self.assertEqual(res["server"], "engage.cloudflareclient.com")
        self.assertEqual(res["server_port"], 2408)
        self.assertIn("172.16.0.2/32", res["local_address"])
        self.assertIn("2606:4700:110:8f38:17f5:3836:2127:5811/128", res["local_address"])

    @patch("urllib.request.urlopen")
    def test_register_warp_network_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        res = warp_client.register_warp(timeout=1.0)
        self.assertFalse(res["ok"])
        self.assertIn("Connection refused", res["error"])


if __name__ == "__main__":
    unittest.main()
