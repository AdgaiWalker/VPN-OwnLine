import base64
import hashlib
import threading
import time
import unittest

from server.nodekit.installations import InstallError
from server.nodekit.local_setup_session import LocalSetupSession


def result(machine="a" * 32):
    key = b"test-host-key"
    return {"ready_for_install": True, "address": "8.8.8.8", "username": "root",
            "ssh_port": 22, "machine_id": machine, "host_key_type": "ssh-ed25519",
            "host_key": base64.b64encode(key).decode(),
            "fingerprint": "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")}


class LocalSetupSessionTests(unittest.TestCase):
    def wait(self, session):
        for _ in range(100):
            status = session.status()
            if status["state"] != "running":
                return status
            time.sleep(0.005)
        self.fail("task did not finish")

    def test_changed_identity_does_not_call_installer(self):
        seen = []
        checks = iter([result(), result("b" * 32)])
        session = LocalSetupSession(lambda _: next(checks), lambda _: seen.append(True))
        token = session.check({"host": "8.8.8.8", "password": "secret"})["check_token"]
        session.start(token)
        self.assertEqual(self.wait(session)["state"], "attention")
        self.assertEqual(seen, [])

    def test_only_verified_delivery_completes(self):
        session = LocalSetupSession(lambda _: result(), lambda _: {"verified": False})
        token = session.check({"host": "8.8.8.8", "password": "secret"})["check_token"]
        session.start(token)
        self.assertEqual(self.wait(session)["state"], "attention")
        with self.assertRaises(InstallError):
            session.start(token)

    def test_verified_delivery_and_credentials_are_cleared(self):
        captured = []

        def install(checked):
            captured.append(checked)
            return {"verified": True, "delivery": {"dashboard_url": "https://example.test"}}

        session = LocalSetupSession(lambda _: result(), install)
        token = session.check({"host": "8.8.8.8", "password": "secret"})["check_token"]
        session.start(token)
        self.assertEqual(self.wait(session)["state"], "done")
        for _ in range(100):
            if not captured[0]["login"]:
                break
            time.sleep(0.005)
        self.assertEqual(captured[0]["login"], {})

    def test_running_job_cannot_be_started_twice(self):
        gate = threading.Event()
        session = LocalSetupSession(lambda _: result(), lambda _: (gate.wait(1) or {}) and {})
        token = session.check({"host": "8.8.8.8", "password": "secret"})["check_token"]
        session.start(token)
        with self.assertRaises(InstallError):
            session.start(token)
        gate.set()
        self.assertEqual(self.wait(session)["state"], "attention")


if __name__ == "__main__":
    unittest.main()
