"""Uploaded fixed supervisor. Reads installation hashes/tokens through stdin, never logs them."""

import hashlib
import fcntl
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import shutil
from pathlib import Path

BASE = Path("/var/lib/ownline-installer")


def write(path, obj):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(obj))
    temp.chmod(0o600)
    os.replace(temp, path)


def source_matches(archive, source, expected_release):
    """Before a retry, verify both the immutable archive and extracted code."""
    if (
        not archive.is_file()
        or hashlib.sha256(archive.read_bytes()).hexdigest() != expected_release
    ):
        return False
    expected = set()
    try:
        with tarfile.open(archive) as tar:
            for item in tar.getmembers():
                path = source / item.name
                if (
                    not item.isfile()
                    or item.issym()
                    or item.islnk()
                    or not path.resolve().is_relative_to(source.resolve())
                ):
                    return False
                if path.is_symlink() or not path.is_file():
                    return False
                expected.add(item.name)
                with tar.extractfile(item) as original, path.open("rb") as actual:
                    old, new = hashlib.sha256(), hashlib.sha256()
                    for chunk in iter(lambda: original.read(1048576), b""):
                        old.update(chunk)
                    for chunk in iter(lambda: actual.read(1048576), b""):
                        new.update(chunk)
                    if old.digest() != new.digest():
                        return False
        for path in source.rglob("*"):
            if path.is_symlink():
                return False
            relative = path.relative_to(source)
            if (
                path.is_file()
                and relative.parts[0] != "packages"
                and relative.as_posix() not in expected
            ):
                return False
        return True
    except (OSError, tarfile.TarError):
        return False


def start(params):
    jid, release = params["job_id"], params["release_id"]
    if not re.fullmatch("[0-9a-f]{32}", jid) or not re.fullmatch(
        "[0-9a-f]{64}", release
    ):
        raise ValueError("invalid identifiers")
    root = BASE / "jobs" / jid
    with (root / "operation.lock").open("a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return start_locked(params, jid, release, root)


def start_locked(params, jid, release, root):
    """Check and transition a target job while its short operation lock is held."""
    owner = BASE / "owner.json"
    # A remote atomic claim also excludes installers on another control plane.
    try:
        fd = os.open(owner, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(
                {"job_id": jid, "release_id": release, "domain": params["domain"]}, f
            )
    except FileExistsError:
        original = json.loads(owner.read_text())
        if original != {
            "job_id": jid,
            "release_id": release,
            "domain": params["domain"],
        }:
            print(json.dumps({"error": "TARGET_OWNED"}))
            return
    state_file = root / "state.json"
    previous = None
    if state_file.exists():
        previous = json.loads(state_file.read_text())
        if not params.get("resume"):
            print(json.dumps(previous))
            return  # Never spawn a second process on query/retry.
        # Only network failures before node configuration are safe to replay.
        if (
            previous.get("state") != "failed"
            or previous.get("exit_code") not in (81, 82, 83)
            or previous.get("stage", 99) > 2
        ):
            print(json.dumps({"error": "UNSAFE_RESUME"}))
            return
        if any(
            Path(p).exists()
            for p in (
                "/opt/sing-box/config.json",
                "/opt/web-data/nodes.json",
                "/opt/web-data/settings.json",
            )
        ):
            print(json.dumps({"error": "UNSAFE_RESUME"}))
            return
        caddy = Path("/etc/caddy/Caddyfile")
        current = (
            hashlib.sha256(caddy.read_bytes()).hexdigest() if caddy.exists() else None
        )
        if current != previous.get("caddyfile_hash"):
            print(json.dumps({"error": "TARGET_CHANGED"}))
            return
    elif params.get("resume"):
        print(json.dumps({"error": "UNSAFE_RESUME"}))
        return
    source = root / "source"
    package = root / "source.tar.gz"
    if previous is not None and not source_matches(package, source, release):
        print(json.dumps({"error": "RELEASE_MISMATCH"}))
        return
    if previous is None:
        if hashlib.sha256(package.read_bytes()).hexdigest() != release:
            print(json.dumps({"error": "RELEASE_MISMATCH"}))
            return
        source.mkdir(mode=0o700, exist_ok=True)
        with tarfile.open(package) as tar:
            for item in tar.getmembers():
                path = source / item.name
                if (
                    item.issym()
                    or item.islnk()
                    or not path.resolve().is_relative_to(source.resolve())
                ):
                    raise ValueError("unsafe archive")
            for item in tar.getmembers():
                path = source / item.name
                if item.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif item.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(tar.extractfile(item).read())
                    path.chmod(item.mode & 0o755)
                else:
                    raise ValueError("unsupported archive entry")
    # Prepared dependencies are independently rechecked on the target before use.
    prepared = params.get("prepared", {})
    specs = {
        "sing-box": (
            "sha256",
            {
                "sing-box-1.14.4-linux-amd64.tar.gz": "699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968",
                "sing-box-1.14.4-linux-arm64.tar.gz": "436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26",
            },
        ),
        "caddy": (
            "sha512",
            {
                "caddy_2.10.2_linux_amd64.tar.gz": "747df7ee74de188485157a383633a1a963fd9233b71fbb4a69ddcbcc589ce4e2cc82dacf5dbbe136cb51d17e14c59daeb5d9bc92487610b0f3b93680b2646546",
                "caddy_2.10.2_linux_arm64.tar.gz": "6ce061a690312ab38367df3c5d5f89a2e4a263e7300d300d87356211bb81e79b15933e6d6203e03fbf26f15cc0311f264805f336147dbdd24938d84b57a4421c",
            },
        ),
    }
    for kind, name in prepared.items():
        if name is None:
            continue
        algorithm, allowed = specs[kind]
        file = Path(name)
        if (
            file.parent != Path("/run/ownline-installer/packages")
            or file.name not in allowed
        ):
            raise ValueError("invalid prepared dependency")
        digest = hashlib.new(algorithm)
        with file.open("rb") as content:
            for chunk in iter(lambda: content.read(1048576), b""):
                digest.update(chunk)
        if digest.hexdigest() != allowed[file.name]:
            raise ValueError("prepared dependency hash mismatch")
        destination = source / "packages" / file.name
        destination.parent.mkdir(mode=0o700, exist_ok=True)
        shutil.copyfile(file, destination)
        destination.chmod(0o600)
    attempt = (previous.get("attempt", 0) + 1) if previous else 0
    unit = "ownline-install-" + jid + ("-r" + str(attempt) if attempt else "")
    params["unit"] = unit
    params["attempt"] = attempt
    write(
        state_file,
        {
            "state": "starting",
            "stage": 0,
            "job_id": jid,
            "release_id": release,
            "started": time.time(),
            "unit": unit,
            "attempt": attempt,
        },
    )
    # Only the future server's token/hash enter this root-only tmpfs file, never SSH credentials.
    runtime = Path("/run/ownline-installer")
    runtime.mkdir(mode=0o700, exist_ok=True)
    input_path = runtime / (jid + ".json")
    fd = os.open(input_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(params, f)
    command = [
        "systemd-run",
        "--quiet",
        "--no-block",
        "--unit=" + unit,
        "--property=Type=oneshot",
        "--property=RemainAfterExit=yes",
        sys.executable,
        str(root / "remote.py"),
        "--execute",
        str(input_path),
    ]
    try:
        subprocess.run(
            command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        input_path.unlink(missing_ok=True)
        write(
            state_file,
            {"state": "failed", "stage": 0, "error": "SUPERVISOR_START_FAILED"},
        )
    print(json.dumps({"state": "starting"}))


def execute(input_path):
    path = Path(input_path)
    params = json.loads(path.read_text())
    path.unlink()
    jid, release = params["job_id"], params["release_id"]
    root = BASE / "jobs" / jid
    source = root / "source"
    state_file = root / "state.json"
    status = {
        "state": "running",
        "stage": 0,
        "job_id": jid,
        "release_id": release,
        "pid": os.getpid(),
        "started": time.time(),
        "unit": params.get("unit", "ownline-install-" + jid),
        "attempt": params.get("attempt", 0),
    }
    try:
        payload = (
            "\n".join(
                [
                    jid,
                    params["sub_token"],
                    params["password_hash"],
                    params["domain"],
                    params["public_ip"],
                ]
            )
            + "\n"
        )
        command = ["bash", str(source / "deploy/install.sh"), "--setup-stdin"]
        if params.get("tls_internal"):
            command.append("--tls-internal")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        process.stdin.write(payload.encode())
        process.stdin.close()
        write(state_file, status)
        for raw in process.stdout:
            # Drop all raw output (including installation credentials); persist only fixed phase numbers.
            match = re.search(rb"(?:==>\s*)?(\d{1,2})/10", raw)
            if match:
                status["stage"] = min(10, int(match[1]))
                write(state_file, status)
        rc = process.wait()
        if rc in (81, 82, 83) and status["stage"] <= 2:
            caddy = Path("/etc/caddy/Caddyfile")
            status["caddyfile_hash"] = (
                hashlib.sha256(caddy.read_bytes()).hexdigest()
                if caddy.exists()
                else None
            )
        status.update(
            state="installed" if rc == 0 else "failed",
            exit_code=rc,
            finished=time.time(),
        )
        write(state_file, status)
    except Exception:
        status.update(state="failed", exit_code=-1)
        write(state_file, status)
    return


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--execute":
        execute(sys.argv[2])
    else:
        start(json.load(sys.stdin))
