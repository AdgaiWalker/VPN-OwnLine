"""Node SSH preflight must be read-only and never expose credentials."""

import unittest
from unittest.mock import patch

from server.nodekit.sshcheck import node_check
from server.nodekit.sshcheck.problem import Problem
from server.nodekit.sshcheck.transport import PinPolicy, fingerprint
import paramiko


class FakeSSH:
    def __init__(self, target, secret):
        self.target = target
        self.secret = secret
        self.fingerprint = "SHA256:" + "A" * 43
        self.host_key = paramiko.RSAKey.generate(1024)
        self.closed = False
        self.info = {
            "os": "ubuntu", "version": "22.04", "architecture": "x86_64",
            "root": True, "systemd": True, "existing_singbox": False,
            "singbox_service": "inactive", "machine_id": "a" * 32,
        }

    def python(self, command, timeout):
        assert command == node_check.NODE_PROBE
        assert timeout == 20
        return self.info

    def close(self):
        self.closed = True


class NodeCheckTests(unittest.TestCase):
    def setUp(self):
        self.target = {"host": "fixture.example", "address": "8.8.8.8", "ssh_port": 22, "username": "root"}
        self.secret = {"password": "test-secret", "private_key": "", "passphrase": ""}
        self.fake = FakeSSH(self.target, self.secret)
        self.patches = [
            patch.object(node_check, "normalize", return_value=self.target),
            patch.object(node_check, "credentials", return_value=self.secret),
            patch.object(node_check, "SSH", return_value=self.fake),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_read_only_result_does_not_claim_install_or_expose_credentials(self):
        result = node_check.check({})
        self.assertTrue(result["ready_for_install"])
        self.assertFalse(result["existing_singbox"])
        self.assertNotIn("test-secret", repr(result))
        self.assertTrue(self.fake.closed)

    def test_running_service_counts_as_existing_even_without_known_files(self):
        self.fake.info["singbox_service"] = "active"
        self.assertTrue(node_check.check({})["existing_singbox"])
        self.assertFalse(node_check.check({})["ready_for_install"])
        self.fake.info["singbox_service"] = "failed"
        self.assertTrue(node_check.check({})["existing_singbox"])

    def test_unknown_service_is_not_reported_as_clean(self):
        self.fake.info["singbox_service"] = "unrecognized"
        result = node_check.check({})
        self.assertEqual(result["singbox_service"], "unknown")
        self.assertFalse(result["ready_for_install"])

    def test_invalid_target_output_fails_closed_and_connection_closes(self):
        self.fake.info["root"] = "true"
        with self.assertRaises(Problem) as caught:
            node_check.check({})
        self.assertEqual(caught.exception.code, "REMOTE_RESPONSE_INVALID")
        self.assertTrue(self.fake.closed)

    def test_unconfirmed_or_changed_host_key_is_rejected(self):
        key = paramiko.RSAKey.generate(1024)
        with self.assertRaises(Problem) as missing:
            PinPolicy("").missing_host_key(None, "fixture", key)
        self.assertEqual(missing.exception.code, "HOST_KEY_CONFIRMATION")
        self.assertEqual(missing.exception.detail["fingerprint"], fingerprint(key))
        with self.assertRaises(Problem) as changed:
            PinPolicy("SHA256:" + "B" * 43).missing_host_key(None, "fixture", key)
        self.assertEqual(changed.exception.code, "HOST_KEY_CHANGED")
        PinPolicy(fingerprint(key)).missing_host_key(None, "fixture", key)


if __name__ == "__main__":
    unittest.main()
