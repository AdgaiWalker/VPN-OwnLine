import base64
import hashlib
import threading
import time
import unittest

from server.nodekit.installations import InstallError
from server.nodekit.local_setup_session import LocalSetupSession
from server.nodekit.sshcheck.problem import Problem


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
        session = LocalSetupSession(lambda _: next(checks), lambda _, report: seen.append(True))
        token = session.check({"host": "8.8.8.8", "password": "secret"})["check_token"]
        session.start(token)
        self.assertEqual(self.wait(session)["state"], "attention")
        self.assertEqual(seen, [])

    def test_only_verified_delivery_completes(self):
        session = LocalSetupSession(lambda _: result(), lambda _, report: {"verified": False})
        token = session.check({"host": "8.8.8.8", "password": "secret"})["check_token"]
        session.start(token)
        self.assertEqual(self.wait(session)["state"], "attention")
        with self.assertRaises(InstallError):
            session.start(token)

    def test_verified_delivery_and_credentials_are_cleared(self):
        captured = []

        def install(checked, report):
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
        session = LocalSetupSession(lambda _: result(), lambda _, report: (gate.wait(1) or {}) and {})
        token = session.check({"host": "8.8.8.8", "password": "secret"})["check_token"]
        session.start(token)
        with self.assertRaises(InstallError):
            session.start(token)
        gate.set()
        self.assertEqual(self.wait(session)["state"], "attention")

    def test_real_stage_timing_survives_reads_and_freezes_after_failure(self):
        clock = [10.0]
        reached, finish = threading.Event(), threading.Event()
        captured = []

        def install(checked, report):
            captured.append(checked)
            clock[0] = 15.0
            report('dependencies')
            report('not-a-stage-secret')
            report('upload')  # A delayed or duplicate marker cannot rewind time.
            reached.set()
            finish.wait(2)
            clock[0] = 80.0
            raise Problem('SSH_TIMEOUT', 'secret from remote stderr')

        session = LocalSetupSession(lambda _: result(), install, clock=lambda: clock[0])
        token = session.check({'host': '8.8.8.8', 'password': 'secret'})['check_token']
        session.start(token)
        self.assertTrue(reached.wait(1))
        clock[0] = 75.0
        status = session.status()
        self.assertEqual(status['stage'], 'dependencies')
        self.assertEqual(status['elapsed_seconds'], 65)
        self.assertEqual(status['stage_elapsed_seconds'], 60)
        self.assertEqual(status['stages'][0]['elapsed_seconds'], 5)
        status['stages'][0]['label'] = 'tampered'
        self.assertNotEqual(session.status()['stages'][0]['label'], 'tampered')
        finish.set()
        status = self.wait(session)
        self.assertEqual(status['state'], 'attention')
        self.assertEqual(status['stages'][-1]['state'], 'attention')
        self.assertIn('安装系统依赖', status['message'])
        self.assertNotIn('secret', str(status))
        clock[0] = 1000.0
        self.assertEqual(session.status()['elapsed_seconds'], 70)
        self.assertNotIn('delivery', status)

    def test_success_records_stages_and_stops_the_elapsed_clock(self):
        clock = [0.0]

        def install(checked, report):
            clock[0] = 4.0
            report('delivery_verify')
            clock[0] = 12.0
            report('cleanup')
            clock[0] = 13.0
            return {'verified': True, 'delivery': {'dashboard_url': 'https://example.test'}}

        session = LocalSetupSession(lambda _: result(), install, clock=lambda: clock[0])
        token = session.check({'host': '8.8.8.8', 'password': 'secret'})['check_token']
        session.start(token)
        status = self.wait(session)
        self.assertEqual(status['state'], 'done')
        self.assertTrue(all(s['state'] == 'done' for s in status['stages']))
        clock[0] = 100.0
        session.report('dependencies')
        self.assertEqual(session.status()['elapsed_seconds'], 13)


if __name__ == "__main__":
    unittest.main()
