"""Failure-focused checks for mirrors, integrity, caching, and safe resume."""

import contextlib
import hashlib
import http.client
import io
import json
import tempfile
import subprocess
import os
import tarfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from server.installer import downloads, remote
from server.installer.state import Problem


class DownloadsTests(unittest.TestCase):
    def test_plain_http_redirect_is_rejected(self):
        handler = downloads.HTTPSOnlyRedirect()
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(
                None, None, 302, "Found", {}, "http://example.com/file"
            )

    def test_failed_and_tampered_sources_fall_back_to_verified_content(self):
        payload = b"known trusted package"
        spec = {
            "algorithm": "sha256",
            "digest": hashlib.sha256(payload).hexdigest(),
            "urls": [
                "https://failed.invalid/a",
                "https://interrupted.invalid/a",
                "https://tampered.invalid/a",
                "https://good.invalid/a",
            ],
        }
        seen = []

        def open_url(request, **kwargs):
            seen.append(request.full_url)
            if len(seen) == 1:
                raise urllib.error.URLError("offline")
            if len(seen) == 2:
                raise http.client.IncompleteRead(b"partial")
            return io.BytesIO(b"tampered" if len(seen) == 3 else payload)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "verified"
            self.assertEqual(output, downloads.fetch(spec, output, open_url))
            self.assertEqual(payload, output.read_bytes())
            self.assertEqual(4, len(seen))
            self.assertEqual(["verified"], [p.name for p in output.parent.iterdir()])

    def test_all_invalid_sources_leave_no_published_or_temporary_file(self):
        spec = {
            "algorithm": "sha256",
            "digest": "0" * 64,
            "urls": ["https://bad.invalid"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "package"
            self.assertIsNone(
                downloads.fetch(spec, target, lambda *a, **kw: io.BytesIO(b"bad"))
            )
            self.assertEqual([], list(target.parent.iterdir()))

    def test_target_failure_falls_back_to_verified_controller_cache(self):
        payload = b"verified cached content"
        spec = {
            "filename": "package.tar.gz",
            "algorithm": "sha256",
            "digest": hashlib.sha256(payload).hexdigest(),
            "urls": [],
        }
        ssh = Mock()
        ssh.python.return_value = {"path": None}
        sftp = ssh.client.open_sftp.return_value
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(downloads, "package", return_value=spec),
        ):
            source = Path(tmp) / "source"
            (source / "packages").mkdir(parents=True)
            cached = source / "packages/package.tar.gz"
            cached.write_bytes(payload)
            result = downloads.prepare(
                ssh, "sing-box", "aarch64", source, Path(tmp) / "data"
            )
        self.assertEqual("/run/ownline-installer/packages/package.tar.gz", result)
        sftp.put.assert_called_once_with(str(cached), result)
        sftp.close.assert_called_once()

    def test_missing_or_corrupt_cache_is_replaced_by_verified_controller_download(self):
        payload = b"trusted fallback download"
        spec = {
            "filename": "package.tar.gz",
            "algorithm": "sha256",
            "digest": hashlib.sha256(payload).hexdigest(),
            "urls": [],
        }
        ssh = Mock()
        ssh.python.return_value = {"path": None}
        sftp = ssh.client.open_sftp.return_value
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            (source / "packages").mkdir(parents=True)
            (source / "packages/package.tar.gz").write_bytes(b"corrupt cache")
            data = Path(tmp) / "data"

            def download(_, destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                return destination

            with (
                patch.object(downloads, "package", return_value=spec),
                patch.object(downloads, "fetch", side_effect=download) as fetch,
            ):
                result = downloads.prepare(ssh, "sing-box", "aarch64", source, data)
            fetch.assert_called_once()
            self.assertEqual(payload, (data / "packages/package.tar.gz").read_bytes())
            sftp.put.assert_called_once_with(
                str(data / "packages/package.tar.gz"), result
            )

    def test_all_sources_down_are_reported_without_unverified_upload(self):
        spec = {
            "filename": "package.tar.gz",
            "algorithm": "sha256",
            "digest": "0" * 64,
            "urls": [],
        }
        ssh = Mock()
        ssh.python.return_value = {"path": None}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(downloads, "package", return_value=spec),
        ):
            with self.assertRaises(Problem) as error:
                downloads.prepare(ssh, "sing-box", "aarch64", tmp, tmp)
            self.assertEqual("DEPENDENCY_UNAVAILABLE", error.exception.code)
        ssh.client.open_sftp.assert_not_called()

    def test_product_bundle_excludes_third_party_cache(self):
        from server.installer import provision
        import tarfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            (root / "server").mkdir(parents=True)
            (root / "server/a.py").write_text("pass")
            (root / "packages").mkdir()
            (root / "packages/sing-box-1.14.4-linux-arm64.tar.gz").write_bytes(
                b"package"
            )
            data = Path(tmp) / "data"
            data.mkdir()
            _, archive = provision.bundle(root, data)
            with tarfile.open(archive) as tar:
                self.assertEqual(["server/a.py"], tar.getnames())


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.jid = "a" * 32
        self.base = self.root / "state"
        self.job = self.base / "jobs" / self.jid
        (self.job / "source").mkdir(parents=True)
        (self.job / "source/deploy").mkdir()
        (self.job / "source/deploy/install.sh").write_text("trusted code")
        with tarfile.open(self.job / "source.tar.gz", "w:gz") as archive:
            archive.add(
                self.job / "source/deploy/install.sh", arcname="deploy/install.sh"
            )
        self.release = hashlib.sha256(
            (self.job / "source.tar.gz").read_bytes()
        ).hexdigest()
        (self.root / "machine/run").mkdir(parents=True)
        (self.base / "owner.json").write_text(
            json.dumps(
                {
                    "job_id": self.jid,
                    "release_id": self.release,
                    "domain": "example.com",
                }
            )
        )
        self.file = self.job / "state.json"
        self.params = {
            "job_id": self.jid,
            "release_id": self.release,
            "domain": "example.com",
            "resume": True,
        }

    def state(self, **updates):
        data = {
            "state": "failed",
            "exit_code": 81,
            "stage": 1,
            "caddyfile_hash": None,
            "attempt": 0,
        }
        data.update(updates)
        self.file.write_text(json.dumps(data))

    def invoke(self):
        actual_path = Path

        def mapped(path):
            if str(path).startswith(("/opt/", "/etc/caddy/", "/run/ownline-installer")):
                return self.root / "machine" / str(path).lstrip("/")
            return actual_path(path)

        out = io.StringIO()
        with (
            patch.object(remote, "BASE", self.base),
            patch.object(remote, "Path", side_effect=mapped),
            patch.object(remote.subprocess, "run") as run,
            contextlib.redirect_stdout(out),
        ):
            remote.start(dict(self.params))
        return json.loads(out.getvalue()), run

    def test_safe_network_failure_restarts_once_with_same_job(self):
        self.state()
        result, run = self.invoke()
        self.assertEqual("starting", result["state"])
        run.assert_called_once()
        updated = json.loads(self.file.read_text())
        self.assertEqual("ownline-install-" + self.jid + "-r1", updated["unit"])
        result, run = self.invoke()
        self.assertEqual("UNSAFE_RESUME", result["error"])
        run.assert_not_called()

    def test_other_failures_and_new_configs_block_resume(self):
        self.state(exit_code=1, stage=4)
        result, run = self.invoke()
        self.assertEqual("UNSAFE_RESUME", result["error"])
        run.assert_not_called()
        self.state()
        config = self.root / "machine/opt/sing-box/config.json"
        config.parent.mkdir(parents=True)
        config.write_text("{}")
        result, run = self.invoke()
        self.assertEqual("UNSAFE_RESUME", result["error"])
        run.assert_not_called()

    def test_changed_caddy_config_blocks_resume(self):
        self.state()
        caddy = self.root / "machine/etc/caddy/Caddyfile"
        caddy.parent.mkdir(parents=True)
        caddy.write_text("new settings")
        result, run = self.invoke()
        self.assertEqual("TARGET_CHANGED", result["error"])
        run.assert_not_called()

    def test_modified_source_blocks_resume(self):
        self.state()
        (self.job / "source/deploy/install.sh").write_text("changed code")
        result, run = self.invoke()
        self.assertEqual("RELEASE_MISMATCH", result["error"])
        run.assert_not_called()


class EntrypointTests(unittest.TestCase):
    def test_product_mirror_rejects_corrupt_archive_and_uses_verified_fallback(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "release.tar.gz"
            marker = tmp / "installed"
            script = b'#!/usr/bin/env bash\nprintf "ok" > "$TEST_INSTALL_MARKER"\n'
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("release/deploy/install.sh")
                info.size = len(script)
                tar.addfile(info, io.BytesIO(script))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            fake = tmp / "bin"
            fake.mkdir()
            counter = tmp / "counter"
            (fake / "id").write_text('#!/bin/sh\nprintf "0\\n"\n')
            (fake / "curl").write_text("""#!/bin/sh
count=0; [ ! -f "$TEST_COUNTER" ] || count=$(cat "$TEST_COUNTER")
count=$((count+1)); printf '%s' "$count" > "$TEST_COUNTER"
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then shift; out=$1; fi
  shift
done
if [ "$count" -eq 1 ]; then printf corrupt > "$out"; else cp "$TEST_ARCHIVE" "$out"; fi
""")
            for executable in fake.iterdir():
                executable.chmod(0o755)
            env = dict(
                os.environ,
                PATH=str(fake) + os.pathsep + os.environ["PATH"],
                OWNLINE_COMMIT="a" * 40,
                OWNLINE_ARCHIVE_SHA256=digest,
                TEST_ARCHIVE=str(archive),
                TEST_COUNTER=str(counter),
                TEST_INSTALL_MARKER=str(marker),
            )
            result = subprocess.run(
                ["bash", str(root / "deploy/bootstrap.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("2", counter.read_text())
            self.assertEqual("ok", marker.read_text())
            marker.unlink()
            counter.unlink()
            env["OWNLINE_ARCHIVE_SHA256"] = "0" * 64
            result = subprocess.run(
                ["bash", str(root / "deploy/bootstrap.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(
                marker.exists(), "unverified product code must not execute"
            )

    def test_python_dependencies_fall_back_without_changing_pip_config(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fake = tmp / "python"
            trace = tmp / "trace"
            fake.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_TRACE"
case "$*" in *tuna.tsinghua*) exit 1;; *) exit 0;; esac
""")
            fake.chmod(0o755)
            result = subprocess.run(
                ["bash", str(root / "deploy/install-python-deps.sh"), str(fake)],
                env=dict(os.environ, TEST_TRACE=str(trace)),
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            lines = trace.read_text().splitlines()
            self.assertEqual(2, len(lines))
            self.assertTrue(
                all(
                    "--require-hashes" in line and "--index-url" in line
                    for line in lines
                )
            )
            self.assertIn("pypi.org/simple", lines[1])


@unittest.skipUnless(
    os.environ.get("OWNLINE_APT_FIXTURE"), "requires disposable Docker fixture"
)
class AptMirrorIntegrationTests(unittest.TestCase):
    def test_real_debian_mirror_keeps_system_sources_and_checks_signatures(self):
        name = os.environ["OWNLINE_APT_FIXTURE"]
        self.assertTrue(name.startswith("ownline-smoke-"))
        script = (Path(__file__).resolve().parents[2] / "deploy/install.sh").read_text()
        section = script[
            script.index("APT_PACKAGES=") : script.index("\nif ! command -v caddy")
        ]
        program = r"""import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
section=json.load(sys.stdin)['section'];source=Path('/etc/apt/sources.list.d/debian.sources');before=hashlib.sha256(source.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);trace=p/'trace';fake=p/'apt-get'
 fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$APT_TRACE\"\nn=$(wc -l < \"$APT_TRACE\")\nif [ \"$n\" -eq 1 ]; then exit 100; fi\nexec /usr/bin/apt-get \"$@\"\n");fake.chmod(0o755)
 script="set -euo pipefail\nDRY_RUN=0\nSB_ARCH=arm64\nrun(){ \"$@\"; }\nwarn(){ :; }\ndie(){ exit 1; }\n"+section
 r=subprocess.run(['/bin/bash'],input=script,text=True,capture_output=True,timeout=180,env=dict(os.environ,PATH=str(p)+':'+os.environ['PATH'],APT_TRACE=str(trace),DEBIAN_FRONTEND='noninteractive'))
 assert r.returncode==0, r.stderr[-1500:]
 lines=trace.read_text().splitlines();assert len(lines)==3 and 'Dir::Etc::sourcelist=/run/ownline-installer/apt/sources.list' in lines[1] and 'install' in lines[2]
 fallback=Path('/run/ownline-installer/apt/sources.list').read_text();assert '[signed-by=/usr/share/keyrings/debian-archive-keyring.gpg]' in fallback and 'bookworm-security' in fallback
 assert hashlib.sha256(source.read_bytes()).hexdigest()==before
"""
        result = subprocess.run(
            ["docker", "exec", "-i", name, "python3", "-c", program],
            input=json.dumps({"section": section}),
            capture_output=True,
            text=True,
            timeout=200,
        )
        self.assertEqual(0, result.returncode, result.stderr[-1800:])
