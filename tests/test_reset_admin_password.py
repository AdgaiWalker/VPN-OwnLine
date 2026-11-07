import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('reset_admin_password', ROOT / 'server/reset_admin_password.py')
reset_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reset_tool)
OLD = '$2b$14$' + 'a' * 53
NEW = '$2b$14$' + 'b' * 53


def template():
    script = (ROOT / 'deploy/install.sh').read_text(encoding='utf-8')
    body = script.split('cat > "$CADDY_STAGED" << CADDYEOF\n', 1)[1].split('\nCADDYEOF', 1)[0]
    return (body.replace('$SETUP_JOB', 'testjob').replace('$PASS_HASH', OLD)
            .replace('${DOMAIN}', 'example.test').replace('$TLS_DIRECTIVE', '') + '\n')


class ResetConfigTests(unittest.TestCase):
    def test_install_persists_marker_before_atomic_config_publish(self):
        script = (ROOT / 'deploy/install.sh').read_text(encoding='utf-8')
        guard = script.index('if [ -f /etc/caddy/Caddyfile ] &&')
        marker = script.index("path = directory + '/.initial-password-required'", guard)
        gate = script.index('cat > "$CADDY_STAGED" << CADDYEOF', marker)
        publish = script.index('mv -f "$CADDY_STAGED" /etc/caddy/Caddyfile', gate)
        self.assertLess(guard, marker)
        self.assertLess(marker, gate)
        self.assertLess(gate, publish)
        self.assertIn('os.fsync(dirfd)', script[marker:gate])
        self.assertIn('caddy validate --config "$CADDY_STAGED"', script[gate:publish])

    def test_generated_template_changes_only_password_hashes(self):
        before = template().replace('(app) {', '# unrelated historical hash: ' + OLD + '\n(app) {')
        domain, after = reset_tool.replace_hash(before, NEW)
        self.assertEqual(domain, 'example.test')
        self.assertEqual(after.count(NEW), 5)
        self.assertEqual(after.replace(NEW, OLD), before)
        self.assertIn('# unrelated historical hash: ' + OLD, after)
        self.assertEqual(reset_tool.inspect_config(template().replace('\n\t\n\timport app', '\n\ttls internal\n\timport app'))[0], domain)

    def test_supports_custom_username_and_updating_username(self):
        before = template()
        domain, user, old_hash = reset_tool.inspect_credentials(before)
        self.assertEqual(domain, 'example.test')
        self.assertEqual(user, 'admin')
        self.assertEqual(old_hash, OLD)

        domain2, after = reset_tool.replace_hash(before, NEW, new_user='walker')
        self.assertEqual(domain2, 'example.test')
        self.assertIn('walker ' + NEW, after)
        self.assertNotIn('admin ' + NEW, after)
        d3, u3, h3 = reset_tool.inspect_credentials(after)
        self.assertEqual(u3, 'walker')
        self.assertEqual(h3, NEW)

    def test_refuses_custom_or_shared_configs(self):
        for candidate in (template() + '\nother.example {\n respond 200\n}\n',
                          template().replace('# ownline-setup-job:testjob', '# another-project'),
                          template().replace('root * /opt/web-data', 'root * /other'),
                          template().replace(OLD, NEW, 1),
                          template().replace('import app', 'import app\n\timport app')):
            with self.subTest(candidate=candidate[-50:]):
                with self.assertRaises(ValueError):
                    reset_tool.replace_hash(candidate, NEW)

    def test_hash_password_never_appears_in_command_arguments(self):
        with mock.patch.object(reset_tool, 'run_quiet', return_value=types.SimpleNamespace(
                returncode=0, stdout=(NEW + '\n').encode())) as run:
            self.assertEqual(reset_tool.hash_password('example long password'), NEW)
        self.assertEqual(run.call_args.args[0], ['caddy', 'hash-password'])
        self.assertEqual(run.call_args.kwargs['input_bytes'], b'example long password\n')

    def test_transaction_success_and_reload_failure_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'Caddyfile'
            real_lstat = Path.lstat

            def owner_root(path):
                actual = real_lstat(path)
                return types.SimpleNamespace(**{name: (0 if name == 'st_uid' else getattr(actual, name))
                    for name in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_mtime_ns')})

            with mock.patch.object(Path, 'lstat', owner_root), mock.patch.object(reset_tool.os, 'chown'), \
                 mock.patch.object(reset_tool, 'hash_password', return_value=NEW), \
                 mock.patch.object(reset_tool, 'local_login', return_value=True):
                config.write_text(template(), encoding='utf-8')
                with mock.patch.object(reset_tool, 'run_quiet', return_value=types.SimpleNamespace(returncode=0)):
                    reset_tool.reset(config, 'example long password')
                self.assertEqual(config.read_text(encoding='utf-8').count(NEW), 5)

                config.write_text(template(), encoding='utf-8')
                with mock.patch.object(reset_tool, 'run_quiet', side_effect=[
                    types.SimpleNamespace(returncode=0), types.SimpleNamespace(returncode=1),
                    types.SimpleNamespace(returncode=0)]):
                    with self.assertRaisesRegex(RuntimeError, '已还原原配置'):
                        reset_tool.reset(config, 'example long password')
                self.assertEqual(config.read_text(encoding='utf-8'), template())

                with mock.patch.object(reset_tool, 'run_quiet', return_value=types.SimpleNamespace(returncode=0)), \
                     mock.patch.object(reset_tool, 'local_login', return_value=False):
                    with self.assertRaisesRegex(RuntimeError, '已还原原配置'):
                        reset_tool.reset(config, 'example long password')
                self.assertEqual(config.read_text(encoding='utf-8'), template())


if __name__ == '__main__':
    unittest.main()
