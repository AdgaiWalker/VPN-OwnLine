"""Execute the generated installer in a disposable, offline fake host."""
import hashlib
import io
import os
import tarfile
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit.join_token import generate_install_script


class JoinScriptSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "systemd").mkdir()
        self.mock("id", 'echo 0')
        self.mock("uname", 'echo x86_64')
        self.mock("pgrep", 'exit 1')
        self.mock("systemctl", 'case "$1" in cat) exit 1;; show) [ "${FAIL_SYSTEMD:-0}" != 1 ];; start) [ "${FAIL_START:-0}" != 1 ];; *) exit 0;; esac')
        self.mock("getent", 'exit 1')
        self.mock("groupadd", 'echo "groupadd $*" >> "$USER_LOG"')
        self.mock("useradd", 'echo "useradd $*" >> "$USER_LOG"')
        self.mock("chown", 'echo "chown $*" >> "$USER_LOG"')
        self.archive = self.root / "sing-box.tar.gz"
        executable = b'#!/bin/sh\ncase "$1" in version) echo "sing-box version 1.14.4";; generate) printf "PrivateKey: private\\nPublicKey: public\\n";; check) exit "${FAIL_CHECK:-0}";; esac\n'
        with tarfile.open(self.archive, "w:gz") as bundle:
            member = tarfile.TarInfo("sing-box-1.14.4-linux-amd64/sing-box")
            member.size = len(executable)
            bundle.addfile(member, io.BytesIO(executable))
        self.bad_archive = self.root / "bad.tar.gz"
        self.bad_archive.write_bytes(self.archive.read_bytes() + b"tampered")
        self.mock("curl", 'case "$*" in *releases/download*) destination=""; while [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then shift; destination="$1"; break; fi; shift; done; if [ "${MALICIOUS_MIRROR:-0}" = 1 ]; then case "$*" in *ghfast*|*ghproxy*) cp "$BAD_ARCHIVE" "$destination";; *) exit 7;; esac; else cp "$SBOX_ARCHIVE" "$destination"; fi;; *ipify*) echo 198.51.100.2;; *join/register*) echo "$*" > "$CALL_LOG"; [ "${FAIL_TLS:-0}" != 1 ] || exit 60; echo \'{"ok": true}\';; *join/*) [ "${FAIL_PREFLIGHT:-0}" != 1 ];; *) exit 1;; esac')
        (self.bin / "sing-box").write_bytes(executable)
        (self.bin / "sing-box").chmod(0o755)
        script = generate_install_script("a" * 64, "https://example.com", role="exit")
        script = script.replace("699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968", hashlib.sha256(self.archive.read_bytes()).hexdigest())
        for old, new in (("/opt/sing-box", self.root / "config"),
                         ("/etc/systemd/system", self.root / "systemd"),
                         ("/run/systemd/system", self.root / "run-systemd"),
                         ("/usr/lib/systemd/system", self.root / "usr-systemd"),
                         ("/lib/systemd/system", self.root / "lib-systemd"),
                         ("/usr/local/bin/sing-box", self.bin / "sing-box"),
                         ("/var/log", self.root / "log")):
            script = script.replace(old, str(new))
        self.script = self.root / "join.sh"
        self.script.write_text(script)

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)

    def run_script(self, **env):
        variables = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                         CALL_LOG=str(self.root / "registration"), USER_LOG=str(self.root / "user_ops"),
                         SBOX_ARCHIVE=str(self.archive), BAD_ARCHIVE=str(self.bad_archive), **env)
        return subprocess.run(["bash", str(self.script)], env=variables, capture_output=True, text=True, timeout=20)

    def test_existing_assets_are_not_overwritten(self):
        for name in ("config.json", "hy2.crt", "hy2.key"):
            with self.subTest(name=name):
                directory = self.root / "config"
                directory.mkdir(exist_ok=True)
                path = directory / name
                path.write_text("existing")
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text(), "existing")
                self.assertFalse((self.root / "registration").exists())
                path.unlink()
        path = self.root / "config/config.json"
        path.symlink_to(self.root / "missing")
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertTrue(path.is_symlink())

    def test_service_failure_never_registers(self):
        result = self.run_script(FAIL_START="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "registration").exists())

    def test_systemd_or_certificate_preflight_failure_changes_nothing(self):
        for setting in ("FAIL_SYSTEMD", "FAIL_PREFLIGHT"):
            with self.subTest(setting=setting):
                result = self.run_script(**{setting: "1"})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "config").exists())
                self.assertFalse((self.root / "registration").exists())

    def test_untrusted_tls_fails_and_success_uses_private_config(self):
        result = self.run_script(FAIL_TLS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("[SUCCESS]", result.stdout)
        arguments = (self.root / "registration").read_text()
        self.assertNotIn("-k", arguments.split())
        self.assertIn("--proto =https", arguments)
        self.assertEqual((self.root / "config/config.json").stat().st_mode & 0o777, 0o640)

    def test_clean_host_succeeds(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[SUCCESS]", result.stdout)
        self.assertEqual((self.root / "config").stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.root / "config/config.json").stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.root / "config/hy2.key").stat().st_mode & 0o777, 0o640)
        user_ops = (self.root / "user_ops").read_text()
        self.assertIn("groupadd --system sing-box", user_ops)
        self.assertIn("useradd --system --gid sing-box", user_ops)
        self.assertIn("chown root:sing-box", user_ops)

    def test_malicious_mirror_never_installs_or_starts(self):
        original = (self.bin / "sing-box").read_bytes()
        result = self.run_script(MALICIOUS_MIRROR="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "config").exists())
        self.assertFalse((self.root / "registration").exists())
        self.assertEqual((self.bin / "sing-box").read_bytes(), original)

    def test_unverified_existing_executable_is_not_overwritten(self):
        (self.bin / "sing-box").write_text("unrelated executable")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.bin / "sing-box").read_text(), "unrelated executable")
        self.assertFalse((self.root / "config").exists())

    def test_join_and_first_install_use_identical_pinned_release(self):
        production = generate_install_script("a" * 64, "https://example.com")
        install = (Path(__file__).resolve().parents[1] / "deploy/install.sh").read_text()
        for value in ("1.14.4", "699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968", "436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26"):
            self.assertIn(value, production)
            self.assertIn(value, install)
