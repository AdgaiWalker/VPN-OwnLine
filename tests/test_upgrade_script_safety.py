"""Exercise upgrade status and rollback with an offline fake service."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UpgradeScriptTests(unittest.TestCase):
    def test_version_mismatch_rolls_back_and_matching_version_succeeds(self):
        for reported, expected in (("v0.6.0", "succeeded"), ("v0.5.0", "failed")):
            with self.subTest(reported=reported), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                bindir = root / "bin"
                bindir.mkdir()
                web = root / "web"
                web.mkdir()
                (web / "admin.py").write_text("old")
                archive = root / "release.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    for path, content in (("release/server/admin.py", b"new"),
                                          ("release/server/nodekit/__init__.py", b"")):
                        info = tarfile.TarInfo(path)
                        info.size = len(content)
                        tar.addfile(info, io.BytesIO(content))
                commands = {
                    "id": "echo 0",
                    "flock": "exit 0",
                    "systemctl": "exit 0",
                    "sleep": "exit 0",
                    "curl": 'case "$*" in *127.0.0.1*) printf \'{"ok":true,"version":"%s"}\' "$REPORTED_VERSION";; *) cat "$ARCHIVE";; esac',
                }
                for name, body in commands.items():
                    target = bindir / name
                    target.write_text("#!/bin/sh\n" + body + "\n")
                    target.chmod(0o755)
                script = (ROOT / "deploy/upgrade.sh").read_text()
                script = script.replace('/opt/web.rollback', str(root / 'rollback'))
                script = script.replace('/opt/web', str(web))
                script = script.replace('/etc/caddy/Caddyfile', str(root / 'absent-caddy'))
                script_path = root / 'upgrade.sh'
                script_path.write_text(script)
                job_id = 'a' * 32
                env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                           RUNNING_IN_TMP='1', OWNLINE_UPGRADE_JOB_ID=job_id,
                           OWNLINE_UPGRADE_STATUS_DIR=str(root / 'status'),
                           ARCHIVE=str(archive), REPORTED_VERSION=reported)
                run = subprocess.run(['bash', str(script_path), 'v0.6.0'], env=env,
                                     capture_output=True, text=True, timeout=20)
                status = json.loads((root / 'status' / (job_id + '.json')).read_text())
                self.assertEqual(status['status'], expected, run.stderr)
                self.assertEqual(run.returncode == 0, expected == 'succeeded')
                self.assertEqual((web / 'admin.py').read_text(), 'new' if expected == 'succeeded' else 'old')
