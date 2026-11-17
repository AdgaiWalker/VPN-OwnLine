import unittest
from unittest.mock import patch

from server.nodekit.sshcheck import first_check
from server.nodekit.sshcheck.problem import Problem


class FakeSSH:
    fingerprint = "SHA256:checked"
    info = {"machine_id": "a" * 32, "existing_controller": False, "disk_ok": True}
    closed = False

    def __init__(self, target, secret):
        self.target = target

    def python(self, *args, **kwargs):
        return self.info

    def close(self):
        type(self).closed = True


class FirstCheckTests(unittest.TestCase):
    def setUp(self):
        self.result = {"ready_for_install": True, "address": "8.8.8.8",
                       "fingerprint": FakeSSH.fingerprint, "machine_id": "a" * 32}
        FakeSSH.info = {"machine_id": "a" * 32, "existing_controller": False, "disk_ok": True}
        FakeSSH.closed = False

    def run_check(self):
        with patch.object(first_check.node_check, "check", return_value=dict(self.result)), \
             patch.object(first_check, "normalize", side_effect=lambda body, allowed: body), \
             patch.object(first_check, "credentials", return_value={}), \
             patch.object(first_check, "SSH", FakeSSH):
            return first_check.check({})

    def test_clean_machine(self):
        self.assertTrue(self.run_check()["ready_for_install"])
        self.assertTrue(FakeSSH.closed)

    def test_existing_controller_is_never_ready(self):
        FakeSSH.info["existing_controller"] = True
        self.assertFalse(self.run_check()["ready_for_install"])

    def test_changed_machine_fails_closed(self):
        FakeSSH.info["machine_id"] = "b" * 32
        with self.assertRaises(Problem):
            self.run_check()
        self.assertTrue(FakeSSH.closed)

    def test_insufficient_disk_is_never_ready(self):
        FakeSSH.info["disk_ok"] = False
        self.assertFalse(self.run_check()["ready_for_install"])

    def test_missing_probe_data_fails_closed(self):
        FakeSSH.info = {"machine_id": "a" * 32}
        with self.assertRaises(Problem):
            self.run_check()


if __name__ == "__main__":
    unittest.main()
