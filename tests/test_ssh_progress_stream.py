import unittest
from unittest.mock import Mock

from server.nodekit.sshcheck.transport import SSH


class Channel:
    def __init__(self):
        self.chunks = [b'first\n', b'second\n']
        self.closed = False
        self.seen = []
    def settimeout(self, value): pass
    def exec_command(self, value): pass
    def shutdown_write(self): pass
    def recv_ready(self): return bool(self.chunks)
    def recv(self, limit): return self.chunks.pop(0)
    def recv_stderr_ready(self): return False
    def exit_status_ready(self): return not self.chunks
    def recv_exit_status(self):
        assert self.seen == [b'first\n', b'second\n'], 'events must arrive before exit'
        return 0
    def close(self): self.closed = True


class StreamingTests(unittest.TestCase):
    def test_progress_is_delivered_before_command_exits_and_output_is_unchanged(self):
        channel = Channel()
        ssh = SSH.__new__(SSH)
        ssh.client = Mock()
        ssh.client.get_transport.return_value.open_session.return_value = channel
        code, out, err = ssh.run('fixture', on_stdout=channel.seen.append)
        self.assertEqual((code, out, err), (0, b'first\nsecond\n', b''))
        self.assertTrue(channel.closed)


if __name__ == '__main__':
    unittest.main()
