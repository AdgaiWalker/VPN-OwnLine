import unittest

from server.nodekit.local_setup_guard import LocalSetupGuard


class LocalSetupGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = LocalSetupGuard(32123, "secret-token")

    def test_loopback_mutation_requires_same_origin_and_token(self):
        self.assertTrue(self.guard.allowed("127.0.0.1", "127.0.0.1:32123",
                                         "http://127.0.0.1:32123", "secret-token", True))
        for origin, token in [("http://evil.test", "secret-token"),
                              (None, "secret-token"),
                              ("http://127.0.0.1:32123", "wrong")]:
            self.assertFalse(self.guard.allowed("127.0.0.1", "127.0.0.1:32123",
                                               origin, token, True))

    def test_rejects_nonlocal_peer_and_dns_rebinding_host(self):
        self.assertFalse(self.guard.allowed("192.0.2.1", "127.0.0.1:32123"))
        self.assertFalse(self.guard.allowed("127.0.0.1", "evil.test:32123"))
        self.assertFalse(self.guard.allowed("invalid", "127.0.0.1:32123"))

    def test_sensitive_read_requires_session_token(self):
        self.assertFalse(self.guard.allowed("127.0.0.1", "127.0.0.1:32123", protected=True))
        self.assertTrue(self.guard.allowed("127.0.0.1", "127.0.0.1:32123",
                                          token="secret-token", protected=True))


if __name__ == "__main__":
    unittest.main()
