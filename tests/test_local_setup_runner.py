import unittest
from pathlib import Path
from unittest.mock import patch

from server.nodekit import local_setup_runner as runner
from server.nodekit.installations import InstallError


class FakeSSH:
    commands = []
    code = 0
    verified = True
    closed = False
    fail_install = False
    cleanup_error = False
    def __init__(self, *args):
        pass
    def run(self, command, data=b'', **kwargs):
        self.commands.append((command, data))
        if kwargs.get('on_stdout'):
            kwargs['on_stdout'](b'private remote log\n__OWNLINE_STAGE_V1__:depen')
            kwargs['on_stdout'](b'dencies\n')
            if self.fail_install:
                return 1, b'secret', b'secret'
        if command.startswith('rm -rf') and self.cleanup_error:
            raise RuntimeError('private cleanup log')
        return self.code, b'', b''
    def python(self, *args, **kwargs):
        return {'ok': self.verified}
    def close(self):
        type(self).closed = True


class RunnerTests(unittest.TestCase):
    def setUp(self):
        FakeSSH.commands, FakeSSH.code, FakeSSH.verified, FakeSSH.closed = [], 0, True, False
        FakeSSH.fail_install = FakeSSH.cleanup_error = False
        self.stages = []
        self.checked = {'login': {'password': 'ssh-secret'}, 'identity': ('8.8.8.8', '', 'a'*32)}

    def install(self):
        with patch.object(runner, 'SSH', FakeSSH), patch.object(runner, 'normalize', return_value={}), \
             patch.object(runner, 'credentials', return_value={}), \
             patch.object(runner, 'emit_bundle', side_effect=lambda path, out: out.write(b'archive')), \
             patch.object(runner, 'verify_delivery', return_value={'dashboard_url': 'https://verified.test'}):
            return runner.install(self.checked, Path('/source'), on_progress=self.stages.append)

    def test_direct_transport_and_cleanup(self):
        self.assertTrue(self.install()['verified'])
        self.assertTrue(FakeSSH.closed)
        self.assertIn('rmdir /run/ownline-local-install.lock', FakeSSH.commands[-1][0])
        self.assertTrue(all('ssh-secret' not in command and b'ssh-secret' not in data for command, data in FakeSSH.commands))
        self.assertEqual(self.stages, ['connect', 'upload', 'preflight', 'dependencies', 'server_verify', 'delivery_verify', 'cleanup'])

    def test_identity_or_lock_failure_never_uploads(self):
        FakeSSH.code = 3
        with self.assertRaises(InstallError):
            self.install()
        self.assertEqual(len(FakeSSH.commands), 1)
        self.assertTrue(FakeSSH.closed)

    def test_proxy_failure_does_not_deliver(self):
        FakeSSH.verified = False
        with self.assertRaises(InstallError):
            self.install()
        self.assertIn('rmdir', FakeSSH.commands[-1][0])

    def test_failure_keeps_its_stage_even_when_cleanup_also_fails(self):
        FakeSSH.fail_install = FakeSSH.cleanup_error = True
        with self.assertRaisesRegex(InstallError, '目标安装未完成'):
            self.install()
        self.assertEqual(self.stages[-1], 'dependencies')
        self.assertTrue(FakeSSH.closed)

    def test_cleanup_failure_never_reports_verified_delivery(self):
        FakeSSH.cleanup_error = True
        with self.assertRaises(RuntimeError):
            self.install()
        self.assertEqual(self.stages[-1], 'cleanup')
        self.assertTrue(FakeSSH.closed)


if __name__ == '__main__':
    unittest.main()
