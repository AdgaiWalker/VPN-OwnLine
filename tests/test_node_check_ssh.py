"""Loopback SSH integration: no real server or remote commands are used."""

import json
import socket
import threading
import time
import unittest

import paramiko

from server.nodekit.sshcheck.node_check import check
from server.nodekit.sshcheck.problem import Problem
from server.nodekit.sshcheck.transport import fingerprint


class FakeServer(paramiko.ServerInterface):
    def __init__(self):
        self.auth_calls = 0
        self.exec_event = threading.Event()

    def check_auth_password(self, username, password):
        self.auth_calls += 1
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("root", "fixture-password") else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.exec_event.set()
        return True


class LoopbackNodeCheckTests(unittest.TestCase):
    def setUp(self):
        self.key = paramiko.RSAKey.generate(2048)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(3)
        self.listener.settimeout(10)
        self.addCleanup(self.listener.close)
        self.port = self.listener.getsockname()[1]
        self.servers = []
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def handle_client(self, conn):
        try:
            transport = paramiko.Transport(conn)
            transport.add_server_key(self.key)
            server = FakeServer()
            with self.lock:
                self.servers.append(server)
            transport.start_server(server=server)
            chan = transport.accept(10)
            if chan and server.exec_event.wait(10):
                data = {"os": "ubuntu", "version": "22.04", "architecture": "x86_64",
                        "root": True, "systemd": True, "existing_singbox": False,
                        "singbox_service": "inactive", "machine_id": "a" * 32}
                chan.sendall(json.dumps(data).encode())
                chan.send_exit_status(0)
                wait_until = time.monotonic() + 2.0
                while not chan.closed and transport.is_active() and time.monotonic() < wait_until:
                    time.sleep(0.02)
                chan.close()
            transport.close()
        except (OSError, EOFError, paramiko.SSHException):
            pass

    def serve(self):
        threads = []
        for _ in range(3):
            try:
                conn, _ = self.listener.accept()
                t = threading.Thread(target=self.handle_client, args=(conn,), daemon=True)
                t.start()
                threads.append(t)
            except (OSError, socket.timeout):
                break
        for t in threads:
            t.join(10)

    def test_unconfirmed_and_changed_host_never_receive_password(self):
        body = {"host": "127.0.0.1", "ssh_port": self.port, "username": "root", "password": "fixture-password"}
        with self.assertRaises(Problem) as missing:
            check(body, allowed_targets=("127.0.0.1",))
        self.assertEqual(missing.exception.code, "HOST_KEY_CONFIRMATION")
        with self.assertRaises(Problem) as mismatch:
            check({**body, "fingerprint": "SHA256:" + "B" * 43}, allowed_targets=("127.0.0.1",))
        self.assertEqual(mismatch.exception.code, "HOST_KEY_CHANGED")
        result = check({**body, "fingerprint": fingerprint(self.key)}, allowed_targets=("127.0.0.1",))
        self.thread.join(10)
        with self.lock:
            calls = [server.auth_calls for server in self.servers]
        self.assertEqual(calls, [0, 0, 1])
        self.assertEqual(result["os"], "ubuntu")
        self.assertTrue(result["ready_for_install"])


if __name__ == "__main__":
    unittest.main()
