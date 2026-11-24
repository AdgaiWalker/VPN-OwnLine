#!/usr/bin/env python3
"""Stage minimal payload and build zero-Python standalone OwnLine installers."""

from __future__ import annotations

import argparse
import http.client
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import zipfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.nodekit.installations import emit_bundle

_ALLOWED_SCRIPTS = (
    "scripts/drift.py",
    "scripts/verify.sh",
    "scripts/ops/cf_origin_lock.sh",
)
_ALLOWED_WEB_FILES = (
    "web/index.html",
    "web/local-setup.html",
    "web/local-vault.html",
    "web/change-password.html",
    "web/backup-crypto.js",
    "web/icon.png",
)


def _copy_regular(src: Path, dst: Path) -> None:
    if src.is_symlink() or not src.is_file():
        raise RuntimeError(f"refusing non-regular or symlinked file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def stage_payload(root: Path, stage_dir: Path) -> Path:
    """Copy the exact deployable source + built web payload without secrets or caches."""
    build_web = root / "scripts" / "build_web.py"
    if build_web.is_file():
        res = subprocess.run([sys.executable, str(build_web), "--check"], cwd=str(root), capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stdout or res.stderr or "web/index.html is out of sync with web/src/")

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    server_dir = root / "server"
    for p in sorted(server_dir.rglob("*")):
        if "__pycache__" in p.parts or p.suffix == ".pyc" or not p.is_file():
            continue
        rel = p.relative_to(server_dir)
        top_ok = len(rel.parts) == 1 and p.suffix in (".py", ".sh")
        sub_ok = len(rel.parts) >= 2 and rel.parts[0] in ("nodekit", "providers")
        if top_ok or sub_ok:
            _copy_regular(p, stage_dir / p.relative_to(root))

    deploy_dir = root / "deploy"
    for p in sorted(deploy_dir.rglob("*")):
        if "__pycache__" in p.parts or p.suffix == ".pyc" or not p.is_file():
            continue
        _copy_regular(p, stage_dir / p.relative_to(root))

    for rel_str in _ALLOWED_SCRIPTS:
        _copy_regular(root / rel_str, stage_dir / rel_str)

    for rel_str in _ALLOWED_WEB_FILES:
        src = root / rel_str
        if src.is_file():
            _copy_regular(src, stage_dir / rel_str)

    assets_dir = root / "web" / "assets"
    if assets_dir.is_dir():
        for p in sorted(assets_dir.rglob("*")):
            if p.is_file():
                _copy_regular(p, stage_dir / p.relative_to(root))

    _copy_regular(root / "requirements.lock", stage_dir / "requirements.lock")

    for item in stage_dir.rglob("*"):
        if item.is_symlink():
            raise RuntimeError(f"staged payload must not contain symlinks: {item}")

    bundle_buf = io.BytesIO()
    emit_bundle(stage_dir / "server", bundle_buf)
    if bundle_buf.tell() <= 0:
        raise RuntimeError("emit_bundle verification produced an empty archive")
    return stage_dir


def resolve_smoke_binary(target: Path) -> Path:
    """Resolve executable inside a macOS .app bundle, output directory, or direct path."""
    path = Path(target)
    if path.is_dir() and path.suffix != ".app":
        for name in ("OwnLine-Setup.app", "OwnLine-Setup.exe", "OwnLine-Setup"):
            cand = path / name
            if cand.exists():
                path = cand
                break
    if path.is_dir() and path.suffix == ".app":
        candidate = path / "Contents" / "MacOS" / "OwnLine-Setup"
        if candidate.is_file():
            return candidate
    if path.is_file():
        return path
    raise FileNotFoundError(f"smoke binary not found: {target}")


def smoke_test_binary(target: Path, *, timeout_sec: float = 20.0) -> dict:
    """Run the frozen installer under an empty PATH (zero external Python) and exercise HTTP lifecycle."""
    binary = resolve_smoke_binary(target)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        empty_bin = tmp_path / "empty_bin"
        empty_bin.mkdir(parents=True, exist_ok=True)
        fake_home = tmp_path / "home"
        fake_home.mkdir(parents=True, exist_ok=True)
        state_file = tmp_path / "state" / "local_agent.json"
        diag_log = tmp_path / "state" / "local_diag.jsonl"

        env = {}
        for keep_key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"):
            if keep_key in os.environ:
                env[keep_key] = os.environ[keep_key]
        env["PATH"] = str(empty_bin)
        env["HOME"] = str(fake_home)
        env["USERPROFILE"] = str(fake_home)
        env["PYTHONUTF8"] = "1"
        env["OWNLINE_DIAG_LOG"] = str(diag_log)

        if shutil.which("python3", path=env["PATH"]) or shutil.which("python", path=env["PATH"]):
            raise AssertionError("smoke environment must not expose python on PATH")

        doc_proc = subprocess.run(
            [str(binary), "doctor", "--json"],
            cwd=str(tmp_path),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        if doc_proc.returncode != 0:
            raise AssertionError(f"frozen doctor failed (rc={doc_proc.returncode}): {doc_proc.stdout}\n{doc_proc.stderr}")
        if not diag_log.is_file():
            raise AssertionError("frozen doctor did not emit diag log")
        doc_events = [json.loads(line) for line in diag_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        doc_detail = next((e.get("detail") for e in reversed(doc_events) if e.get("event") == "local_cli_doctor"), None)
        if not isinstance(doc_detail, dict) or not doc_detail.get("ok") or not doc_detail.get("frozen") or not doc_detail.get("bundle_ready"):
            raise AssertionError(f"frozen doctor diagnostic invalid: {doc_detail}")

        cmd = [
            str(binary),
            "ui",
            "--no-browser",
            "--force-new",
            "--port",
            "0",
            "--state-file",
            str(state_file),
            "--diag-log",
            str(diag_log),
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(tmp_path),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + timeout_sec
            state = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    out, err = proc.communicate(timeout=2)
                    raise RuntimeError(f"installer exited prematurely ({proc.returncode}): {out}\n{err}")
                if state_file.is_file():
                    try:
                        parsed = json.loads(state_file.read_text(encoding="utf-8"))
                        if isinstance(parsed, dict) and parsed.get("origin") and parsed.get("token"):
                            state = parsed
                            break
                    except ValueError:
                        pass
                time.sleep(0.1)

            if state is None:
                raise RuntimeError("timed out waiting for frozen installer state file")

            origin = state["origin"]
            token = state["token"]
            parsed_url = urllib.parse.urlsplit(origin)
            headers = {"Host": parsed_url.netloc, "Cookie": f"ownline_setup={token}"}

            conn = http.client.HTTPConnection("127.0.0.1", parsed_url.port, timeout=5)
            try:
                conn.request("GET", "/", headers={"Host": parsed_url.netloc})
                resp = conn.getresponse()
                html = resp.read().decode("utf-8", errors="replace")
                if resp.status != 200 or 'id="no-server-guide"' not in html:
                    raise AssertionError(f"unexpected GET / status={resp.status}")

                conn.request("GET", "/api/status", headers=headers)
                st_resp = conn.getresponse()
                st_data = json.loads(st_resp.read().decode("utf-8"))
                if st_resp.status != 200 or st_data.get("state") != "idle":
                    raise AssertionError(f"unexpected /api/status: {st_resp.status} {st_data}")

                conn.request(
                    "POST",
                    "/api/quit",
                    body=b"{}",
                    headers={
                        **headers,
                        "Origin": origin,
                        "Content-Type": "application/json",
                        "Content-Length": "2",
                    },
                )
                q_resp = conn.getresponse()
                q_resp.read()
                if q_resp.status != 200:
                    raise AssertionError(f"unexpected /api/quit status={q_resp.status}")
            finally:
                conn.close()

            rc = proc.wait(timeout=10)
            if rc != 0:
                _, err = proc.communicate(timeout=2)
                raise AssertionError(f"installer did not exit cleanly (rc={rc}): {err}")
            if state_file.exists():
                raise AssertionError("installer did not remove its state file on /api/quit")
            return {"ok": True, "origin": origin, "binary": str(binary)}
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def build_installer(*, root: Path, version: str, out_dir: Path) -> tuple[Path, Path]:
    """Build macOS .app.zip or Windows .exe.zip via PyInstaller and return (binary_or_app, zip_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stage_dir = stage_payload(root, tmp_path / "payload")
        work_dir = tmp_path / "build"
        dist_dir = tmp_path / "dist"
        spec_dir = tmp_path / "spec"

        add_data_entries = [
            (stage_dir / "server", "server"),
            (stage_dir / "deploy", "deploy"),
            (stage_dir / "web", "web"),
            (stage_dir / "scripts", "scripts"),
            (stage_dir / "requirements.lock", "."),
        ]

        pyinstaller_args = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--name",
            "OwnLine-Setup",
            "--workpath",
            str(work_dir),
            "--distpath",
            str(dist_dir),
            "--specpath",
            str(spec_dir),
        ]
        if sys.platform != "darwin":
            pyinstaller_args.append("--onefile")

        for src, dest in add_data_entries:
            pyinstaller_args.extend(["--add-data", f"{src}{os.pathsep}{dest}"])

        for pkg in ("paramiko", "bcrypt", "cryptography", "nacl"):
            pyinstaller_args.extend(["--collect-all", pkg])

        for hidden in (
            "server.ownline_cli",
            "server.local_setup",
            "server.tencent_discovery",
            "server.nodekit",
            "server.nodekit.local_diag",
            "server.nodekit.local_setup_guard",
            "server.nodekit.local_setup_progress",
            "server.nodekit.local_setup_runner",
            "server.nodekit.local_setup_session",
            "server.nodekit.local_vault",
            "server.nodekit.installations",
            "server.nodekit.capabilities",
            "server.nodekit.topology_plan",
            "server.nodekit.sshcheck.first_check",
            "server.nodekit.sshcheck.node_check",
            "server.nodekit.sshcheck.transport",
            "server.nodekit.sshcheck.problem",
        ):
            pyinstaller_args.extend(["--hidden-import", hidden])

        pyinstaller_args.append(str(root / "ownline.py"))
        subprocess.run(pyinstaller_args, cwd=str(root), check=True)

        if sys.platform == "darwin":
            app_bundle = dist_dir / "OwnLine-Setup.app"
            if not app_bundle.is_dir():
                raise RuntimeError(f"missing macOS app bundle: {app_bundle}")
            raw_arch = platform.machine().lower()
            arch = "arm64" if raw_arch in ("arm64", "aarch64") else ("x64" if raw_arch in ("x86_64", "amd64") else raw_arch)
            zip_path = out_dir / f"OwnLine-Setup-{version}-macOS-{arch}.zip"
            copied_app = out_dir / "OwnLine-Setup.app"
            if copied_app.exists():
                shutil.rmtree(copied_app)
            shutil.copytree(app_bundle, copied_app, symlinks=True)
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(copied_app), str(zip_path)], check=True)
            return copied_app, zip_path

        exe_name = "OwnLine-Setup.exe" if os.name == "nt" else "OwnLine-Setup"
        built_bin = dist_dir / exe_name
        if not built_bin.is_file():
            raise RuntimeError(f"missing standalone binary: {built_bin}")
        os_tag = "Windows" if os.name == "nt" else platform.system()
        raw_arch = platform.machine().lower()
        arch = "x64" if raw_arch in ("amd64", "x86_64") else raw_arch
        zip_path = out_dir / f"OwnLine-Setup-{version}-{os_tag}-{arch}.zip"
        copied_bin = out_dir / exe_name
        shutil.copy2(built_bin, copied_bin)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(copied_bin, arcname=exe_name)
        return copied_bin, zip_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Stage and build standalone zero-Python installers.")
    parser.add_argument("--check-stage", action="store_true", help="Verify clean payload staging and emit_bundle offline")
    parser.add_argument("--build", action="store_true", help="Build standalone executable with PyInstaller")
    parser.add_argument("--smoke", help="Smoke-test built executable/.app with blank PATH")
    parser.add_argument("--version", default=os.environ.get("GITHUB_REF_NAME") or "v0.9.0")
    parser.add_argument("--out-dir", default="dist-installer")
    args = parser.parse_args(argv)

    if args.check_stage:
        with tempfile.TemporaryDirectory() as tmp:
            stage_payload(ROOT, Path(tmp) / "stage")
        print("OK: staged installer payload verified with emit_bundle")
        return 0

    if args.build:
        target, zip_path = build_installer(root=ROOT, version=args.version, out_dir=ROOT / args.out_dir)
        print(json.dumps({"target": str(target), "zip": str(zip_path)}, ensure_ascii=False))
        return 0

    if args.smoke:
        res = smoke_test_binary(Path(args.smoke))
        print(json.dumps(res, ensure_ascii=False))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
