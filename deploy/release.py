#!/usr/bin/env python3
"""Official release transport and transactional runtime replacement."""
import ast
import ctypes
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

from runtime_manifest import stage_runtime


REPOSITORY = "AdgaiWalker/VPN-OwnLine"
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_EXPANDED = 300 * 1024 * 1024
OFFICIAL_HOSTS = {"github.com", "codeload.github.com"}


def official_url(target, branch="main"):
    reference = branch if target in (None, "", "latest") else target
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", reference)
            or any(part in ("", ".", "..") for part in reference.split("/"))):
        raise ValueError("invalid release reference")
    kind = "heads" if target in (None, "", "latest") else "tags"
    return ("https://codeload.github.com/" + REPOSITORY + "/tar.gz/refs/" + kind + "/"
            + urllib.parse.quote(reference, safe=""))


def _official_https(url):
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS
            and parsed.port in (None, 443) and not parsed.username and not parsed.password)


class _OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not _official_https(new_url):
            raise ValueError("release redirected outside official HTTPS hosts")
        return super().redirect_request(request, response, code, message, headers, new_url)


def download_official(target, destination, branch=None, opener=None):
    """No mirror fallback exists without an independently trusted archive digest."""
    opener = opener or urllib.request.build_opener(_OfficialRedirects()).open
    branch = os.environ.get("LADDER_BRANCH", "main") if branch is None else branch
    request = urllib.request.Request(official_url(target, branch), headers={"User-Agent": "OwnLine-Updater"})
    digest, size = hashlib.sha256(), 0
    try:
        with opener(request, timeout=120) as response:
            if not _official_https(response.geturl()):
                raise ValueError("release redirected outside official HTTPS hosts")
            with open(destination, "wb") as output:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_ARCHIVE:
                        raise ValueError("release archive is too large")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
        if not size:
            raise ValueError("empty release archive")
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise
    return digest.hexdigest()


def extract_archive(archive, destination):
    """Accept one ordinary source tree; reject traversal, links and special files."""
    destination = Path(destination)
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as bundle:
        members, total, roots, names = [], 0, set(), set()
        for member in bundle.getmembers():
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or not (member.isdir() or member.isfile()) or member.name in names):
                raise ValueError("unsafe release archive member")
            names.add(member.name)
            roots.add(path.parts[0])
            total += member.size
            if total > MAX_EXPANDED or len(names) > 20000:
                raise ValueError("release expands beyond limits")
            members.append((member, path))
        if len(roots) != 1:
            raise ValueError("release must contain one source tree")
        for member, relative in members:
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)
    return destination / roots.pop()


def runtime_version(directory):
    path = Path(directory) / "nodekit/system_updater.py"
    for item in ast.parse(path.read_bytes()).body:
        if isinstance(item, ast.Assign) and any(isinstance(name, ast.Name) and name.id == "CURRENT_VERSION" for name in item.targets):
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                return item.value.value
    raise ValueError("release has no declared runtime version")


def _stamp(directory):
    try:
        stamp = json.loads((Path(directory) / ".release.json").read_text())
        return stamp if isinstance(stamp, dict) else {}
    except (OSError, ValueError):
        return {}


def probe_runtime(expected, attempts=5):
    for _ in range(attempts):
        for port in (8099, 8000):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/api/system/version" % port, timeout=3) as response:
                    info = json.loads(response.read(16384))
                if (info.get("ok") is True and info.get("version") == expected["version"]
                        and (not expected.get("release_id") or info.get("release_id") == expected["release_id"])):
                    return True
            except (OSError, ValueError):
                pass
        time.sleep(1)
    return False


def restart_admin():
    authorize_restart()
    subprocess.run(["systemctl", "restart", "admin.service"], check=True, capture_output=True, timeout=30)


def _provenance_module():
    directory = Path(__file__).resolve().parent
    candidates = (directory / "upgrade_provenance.py", directory.parent / "nodekit/provenance.py",
                  directory.parent / "server/nodekit/provenance.py")
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise PermissionError("missing trusted ownership verifier")
    spec = importlib.util.spec_from_file_location("ownline_upgrade_provenance", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authorize_restart(data_dir=None, cfg_path="/opt/sing-box/config.json", manifest_path=None, provenance_module=None):
    """A release update never adopts an unsigned existing proxy installation."""
    provenance = provenance_module or _provenance_module()
    directory = Path(data_dir or os.environ.get("LADDER_DATA", "/opt/web-data"))
    try:
        secret = provenance.load_master_secret(directory)
        manifest = json.loads(Path(manifest_path or provenance.PROVENANCE_PATH_LINUX).read_bytes())
        nodes = json.loads((directory / "nodes.json").read_bytes())
        identities = {provenance.node_identity(node) for node in nodes if node.get("local") is True}
        content = Path(cfg_path).read_bytes()
        valid, _ = provenance.verify_provenance(manifest, secret)
        if (not valid or len(identities) != 1 or manifest.get("node_id") not in identities
                or len(content) > 2_000_000
                or manifest.get("config_sha256") != provenance.compute_config_sha256(content)):
            raise ValueError("ownership mismatch")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise PermissionError("服务归属未通过 HMAC、目标身份及配置校验，未切换或重启服务") from None


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_exchange(left, right):
    """Exchange directories without an absent-active window; no rename-pair fallback."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        operation = getattr(library, "renameat2", None)
    elif sys.platform == "darwin":
        operation = getattr(library, "renameatx_np", None)
    else:
        operation = None
    if operation is None:
        raise OSError(errno.ENOTSUP, "atomic directory exchange is unavailable")
    operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    operation.restype = ctypes.c_int
    # Linux RENAME_EXCHANGE and macOS RENAME_SWAP both use bit 1.
    cwd = -2 if sys.platform == "darwin" else -100
    if operation(cwd, os.fsencode(left), cwd, os.fsencode(right), 2) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _atomic_json(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".transaction-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _identity(directory):
    digest = hashlib.sha256()
    for name in ("admin.py", "nodekit/system_updater.py", ".release.json"):
        path = Path(directory) / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()


def _journal_path(active):
    return active.parent / ("." + active.name + "-upgrade-journal.json")


def _lock_path(active):
    return active.parent / ("." + active.name + "-upgrade.lock")


def _load_journal(active):
    path = _journal_path(active)
    if not path.exists():
        return None
    if path.is_symlink():
        raise ValueError("upgrade journal is a symlink")
    value = json.loads(path.read_bytes())
    slot = Path(value["slot"])
    if (value.get("active") != str(active) or slot.name != "candidate"
            or slot.parent.parent != active.parent
            or not slot.parent.name.startswith("." + active.name + "-release-")
            or slot.is_symlink() or slot.parent.is_symlink()
            or value.get("phase") not in ("prepared", "switched", "rollback", "committed")):
        raise ValueError("invalid upgrade recovery journal")
    return value


def _finish_transaction(active, journal, status):
    # Clear the durable recovery obligation before removing its retained directory.
    _journal_path(active).unlink()
    _fsync_directory(active.parent)
    shutil.rmtree(Path(journal["slot"]).parent, ignore_errors=True)
    if journal.get("job_id") and journal.get("status_dir"):
        write_status(status, journal.get("target"), job_id=journal["job_id"],
                     status_dir=journal["status_dir"], recovered=True)


def _recover_locked(active, restart, probe, exchange):
    journal = _load_journal(active)
    if journal is None:
        return False
    slot = Path(journal["slot"])
    current = _identity(active)
    if journal["phase"] == "committed":
        if current != journal["new_identity"]:
            raise RuntimeError("committed runtime identity changed; recovery requires attention")
        _finish_transaction(active, journal, "succeeded")
        return False
    changed = current == journal["new_identity"]
    if changed:
        if _identity(slot) != journal["old_identity"]:
            raise RuntimeError("previous runtime identity changed; recovery requires attention")
        exchange(active, slot)
        _fsync_directory(active.parent)
        _fsync_directory(slot.parent)
        journal["phase"] = "rollback"
        _atomic_json(_journal_path(active), journal)
    elif current != journal["old_identity"]:
        raise RuntimeError("active runtime identity is unknown; recovery requires attention")
    # A crash before exchange leaves the complete previous runtime in place.
    if changed or journal["phase"] != "prepared":
        restart()
        if not probe(journal["previous"]):
            raise RuntimeError("restored runtime failed version verification")
    _finish_transaction(active, journal, "failed")
    return changed


def recover_release(web_dir="/opt/web", *, restart=None, probe=None, exchange=None):
    """Stable entry point used after worker interruption and at subsequent startup."""
    active = Path(web_dir).absolute()
    with open(_lock_path(active), "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False  # The live worker still owns its transaction.
        return _recover_locked(active, restart or restart_admin, probe or probe_runtime, exchange or atomic_exchange)


def upgrade_release(target, web_dir="/opt/web", *, fetch=None, restart=None, probe=None, stage=None, exchange=None, rename=None):
    """Stage completely, journal durably, atomically exchange, then verify or recover."""
    production_restart = restart is None
    fetch, restart, probe = fetch or download_official, restart or restart_admin, probe or probe_runtime
    # `rename` remains an injection alias; its Adapter must now satisfy atomic exchange.
    stage, exchange = stage or stage_runtime, exchange or rename or atomic_exchange
    active = Path(web_dir).absolute()
    if active.is_symlink() or not active.is_dir():
        raise ValueError("active runtime must be an ordinary directory")
    with open(_lock_path(active), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _recover_locked(active, restart, probe, exchange)
        previous = {**_stamp(active), "version": runtime_version(active)}
        temporary = Path(tempfile.mkdtemp(prefix="." + active.name + "-release-", dir=active.parent))
        try:
            archive = temporary / "release.tar.gz"
            release_id = fetch(target, archive)
            source = extract_archive(archive, temporary / "source")
            candidate = temporary / "candidate"
            stage(source, candidate, preserve=active)
            expected = {"version": runtime_version(candidate), "release_id": release_id}
            if target not in (None, "", "latest") and expected["version"] != target:
                raise ValueError("release version does not match requested tag")
            if (candidate / ".release.json").is_symlink():
                (candidate / ".release.json").unlink()
            _atomic_json(candidate / ".release.json", {**expected, "source_ref": target or "latest"})
            # Flush all staged ordinary files before recording the switch obligation.
            for path in candidate.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    with path.open("rb") as handle:
                        os.fsync(handle.fileno())
            for directory in sorted((p for p in candidate.rglob("*") if p.is_dir() and not p.is_symlink()),
                                    key=lambda p: len(p.parts), reverse=True):
                _fsync_directory(directory)
            _fsync_directory(candidate)
            if production_restart:
                authorize_restart()
            journal = {"active": str(active), "slot": str(candidate), "phase": "prepared",
                       "old_identity": _identity(active), "new_identity": _identity(candidate),
                       "previous": previous, "expected": expected, "target": target,
                       "job_id": os.environ.get("OWNLINE_UPGRADE_JOB_ID"),
                       "status_dir": os.environ.get("OWNLINE_UPGRADE_STATUS_DIR")}
            _atomic_json(_journal_path(active), journal)
            try:
                exchange(active, candidate)
                _fsync_directory(active.parent)
                _fsync_directory(candidate.parent)
                journal["phase"] = "switched"
                _atomic_json(_journal_path(active), journal)
                restart()
                if not probe(expected):
                    raise RuntimeError("new runtime failed version verification")
                journal["phase"] = "committed"
                _atomic_json(_journal_path(active), journal)
                _finish_transaction(active, journal, "succeeded")
            except BaseException as failure:
                try:
                    restored = _recover_locked(active, restart, probe, exchange)
                except BaseException as rollback_error:
                    raise RuntimeError("upgrade failed; rollback requires attention: " + str(rollback_error)) from failure
                if restored:
                    raise RuntimeError("upgrade failed; previous runtime restored and verified") from failure
                raise
            return expected
        finally:
            # A pending journal owns its slot across process death and failed recovery.
            if not _journal_path(active).exists():
                shutil.rmtree(temporary, ignore_errors=True)


def write_status(status, target, *, job_id=None, status_dir=None, **fields):
    job_id = job_id or os.environ.get("OWNLINE_UPGRADE_JOB_ID")
    directory = status_dir or os.environ.get("OWNLINE_UPGRADE_STATUS_DIR")
    if not job_id or not directory:
        return
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("invalid upgrade job id")
    path = Path(directory) / (job_id + ".json")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    previous = {}
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    descriptor, temporary = tempfile.mkstemp(prefix=".status-", dir=path.parent)
    with os.fdopen(descriptor, "w") as output:
        json.dump({**previous, "ok": True, "status": status, "target_version": target or "latest", **fields}, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def install_recovery_runtime(stable_dir="/opt/ownline-upgrade", unit_dir="/etc/systemd/system", runner=None):
    """Install code-only recovery tools outside the directory being exchanged."""
    runner = runner or subprocess.run
    stable, units = Path(stable_dir), Path(unit_dir)
    if stable.is_symlink():
        raise ValueError("recovery directory is a symlink")
    stable.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(stable, 0o700)
    current = Path(__file__).resolve().parent
    provenance = _provenance_module()
    for source, name in ((current / "release.py", "release.py"),
                         (current / "runtime_manifest.py", "runtime_manifest.py"),
                         (Path(provenance.__file__), "upgrade_provenance.py")):
        descriptor, temporary = tempfile.mkstemp(prefix=".helper-", dir=stable)
        with os.fdopen(descriptor, "wb") as output:
            output.write(source.read_bytes())
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, stable / name)
    _atomic_json(stable / "context.json", {"web_dir": "/opt/web",
                 "data_dir": os.environ.get("LADDER_DATA", "/opt/web-data")})
    service = """[Unit]
Description=Recover an interrupted OwnLine runtime update
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 %s --recover
[Install]
WantedBy=multi-user.target
""" % (stable / "release.py")
    timer = """[Unit]
Description=Check pending OwnLine runtime recovery
[Timer]
OnBootSec=20s
OnUnitActiveSec=20s
Unit=ownline-upgrade-recovery.service
[Install]
WantedBy=timers.target
"""
    units.mkdir(parents=True, exist_ok=True)
    for name, content in (("ownline-upgrade-recovery.service", service), ("ownline-upgrade-recovery.timer", timer)):
        path = units / name
        descriptor, temporary = tempfile.mkstemp(prefix=".ownline-unit-", dir=units)
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    _fsync_directory(stable)
    _fsync_directory(units)
    runner(["systemctl", "daemon-reload"], check=True, capture_output=True, timeout=30)
    runner(["systemctl", "enable", "ownline-upgrade-recovery.service"], check=True, capture_output=True, timeout=30)
    runner(["systemctl", "enable", "--now", "ownline-upgrade-recovery.timer"], check=True, capture_output=True, timeout=30)
    return stable / "release.py"


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "latest"
    def interrupted(signum, frame):
        raise RuntimeError("upgrade interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        if os.geteuid() != 0:
            raise PermissionError("upgrade requires root")
        if target == "--prepare":
            stable = Path("/opt/ownline-upgrade/release.py")
            if stable.is_file():
                subprocess.run([sys.executable, str(stable), "--recover"], check=True, timeout=120)
            helper = install_recovery_runtime()
            os.execv(sys.executable, [sys.executable, str(helper), sys.argv[2] if len(sys.argv) > 2 else "latest"])
            return 1
        if target == "--recover":
            context_path = Path(__file__).resolve().parent / "context.json"
            context = json.loads(context_path.read_text()) if context_path.is_file() else {}
            if context.get("data_dir"):
                os.environ["LADDER_DATA"] = context["data_dir"]
            recover_release(context.get("web_dir", "/opt/web"))
            return 0
        write_status("running", target)
        result = upgrade_release(target)
        write_status("succeeded", target, **result)
        print("升级成功，已验证运行版本。")
        return 0
    except Exception as error:
        write_status("failed", target, error=str(error)[:300])
        print("升级失败: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
