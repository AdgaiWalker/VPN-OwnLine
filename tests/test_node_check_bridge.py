"""The management bridge must not leak credentials or invoke a shell."""

import json
import subprocess
import unittest
from unittest.mock import patch

from server.nodekit import node_check_bridge as bridge


class BridgeTests(unittest.TestCase):
    def test_secret_is_sent_only_via_stdin(self):
        with patch.object(bridge, "available", return_value=True), patch.object(bridge.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "result": {}}))
            result = bridge.check({"password": "fixture-secret"})
        self.assertTrue(result["ok"])
        self.assertNotIn("fixture-secret", repr(run.call_args.args))
        self.assertIn("fixture-secret", run.call_args.kwargs["input"])
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertNotIn("fixture-secret", repr(result))

    def test_timeout_and_invalid_worker_output_fail_closed(self):
        with patch.object(bridge, "available", return_value=True), patch.object(bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            self.assertEqual(bridge.check({})["code"], "UNAVAILABLE")
        with patch.object(bridge, "available", return_value=True), patch.object(bridge.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "not-json fixture-secret")
            self.assertNotIn("fixture-secret", repr(bridge.check({})))

    def test_large_payload_is_not_sent_to_worker(self):
        with patch.object(bridge, "available", return_value=True), patch.object(bridge.subprocess, "run") as run:
            self.assertEqual(bridge.check({"private_key": "x" * 151000})["code"], "BODY_TOO_LARGE")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
