"""Remove only a locally signed installation and its project-owned systemd units."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from nodekit import provenance
else:
    from . import provenance


# Recovery is stopped first so it cannot revive a runtime during removal.
SERVICES = (
    "ownline-upgrade-recovery.timer", "ownline-upgrade-recovery.service",
    "probe.timer", "usage-refresh.timer", "ipcheck.timer", "backup-remote.timer",
    "admin.service", "probe.service", "usage-refresh.service", "ipcheck.service",
    "backup-remote.service", "sing-box.service", "caddy.service",
)


def _normalized(raw):
    return [line.strip() for line in raw.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _template_directory():
    runtime = Path(__file__).resolve().parents[1]
    candidates = (runtime / "deploy/systemd", runtime.parent / "deploy/systemd")
    return next(path for path in candidates if path.is_dir())


def _owned_unit(name, raw):
    lines = _normalized(raw)
    if name == "caddy.service":
        starts = [line.split("=", 1)[1] for line in lines if line.startswith("ExecStart=")]
        if len(starts) != 1:
            return False
        command = shlex.split(starts[0])
        if (not command or command[0] not in ("/usr/bin/caddy", "/usr/local/bin/caddy")
                or "run" not in command or "--config" not in command):
            return False
        index = command.index("--config")
        if index + 1 >= len(command) or command[index + 1] != "/etc/caddy/Caddyfile":
            return False
        return not any(line.startswith(("ExecStop", "ExecStartPre=", "ExecStartPost=")) for line in lines)
    if name == "ownline-upgrade-recovery.service":
        commands = [line for line in lines if line.startswith("Exec")]
        return commands == ["ExecStart=/usr/bin/python3 /opt/ownline-upgrade/release.py --recover"]
    if name == "ownline-upgrade-recovery.timer":
        return ("Unit=ownline-upgrade-recovery.service" in lines
                and not any(line.startswith("Exec") for line in lines))
    return lines == _normalized((_template_directory() / name).read_text())


def _prepare(root, runner):
    data = root / "opt/web-data"
    raw_nodes = (data / "nodes.json").read_bytes()
    records = json.loads(raw_nodes)
    local = [node for node in records if node.get("local") is True]
    identities = {(str(node.get("host", "")).strip().lower().rstrip("."), provenance.node_identity(node))
                  for node in local}
    if (not local or len(identities) != 1 or not next(iter(identities))[0]
            or any(node.get("source") == "external" for node in local)):
        raise ValueError("local target identity is ambiguous")
    node = local[0]
    secret = provenance.load_master_secret(data)
    raw_secret = (data / "master_secret").read_bytes()
    if bytes.fromhex(raw_secret.decode("ascii").strip()) != secret:
        raise ValueError("local signing key changed")
    execute = lambda n, script, **kw: runner(["bash", "-c", script], capture_output=True, text=True, **kw)
    ok, _, snapshot = provenance.verify_target(
        node, execute, secret, cfg_path=str(root / "opt/sing-box/config.json"),
        provenance_path=str(root / "etc/sing-box/.evergreen-provenance.json"))
    if not ok:
        raise ValueError("local service ownership is not verified")
    caddy = root / "etc/caddy/Caddyfile"
    raw_caddy = caddy.read_bytes()
    reset_path = Path(__file__).resolve().parents[1] / "reset_admin_password.py"
    spec = importlib.util.spec_from_file_location("ownline_maintenance_caddy", reset_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    domain, _, _ = module.inspect_credentials(raw_caddy.decode("utf-8"))
    raw_settings = (data / "settings.json").read_bytes()
    if domain != json.loads(raw_settings).get("domain"):
        raise ValueError("Caddy domain does not match this installation")
    verified_files = {caddy: raw_caddy, data / "nodes.json": raw_nodes,
                      data / "master_secret": raw_secret, data / "settings.json": raw_settings}
    units = []
    for name in SERVICES:
        directories = tuple(root / relative for relative in ("etc/systemd/system", "lib/systemd/system", "usr/lib/systemd/system"))
        if any((directory / (name + ".d")).exists() for directory in directories):
            raise ValueError("custom systemd overrides require manual removal")
        path = next((directory / name for directory in directories if (directory / name).exists()), None)
        if path is None:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("systemd unit must be an ordinary file")
        raw = path.read_bytes()
        if not _owned_unit(name, raw.decode("utf-8")):
            raise ValueError("systemd unit is not project-owned")
        verified_files[path] = raw
        units.append((name, path))
    if not {"sing-box.service", "admin.service", "caddy.service"}.issubset({name for name, _ in units}):
        raise ValueError("required local service unit is missing")
    return node, snapshot, units, verified_files


def uninstall(*, purge=False, dry_run=False, root=Path("/"), runner=subprocess.run):
    """Validate all ownership before crossing the single service-mutation Seam."""
    root = Path(root).absolute()
    try:
        node, snapshot, units, files = _prepare(root, runner)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration):
        raise PermissionError("本机签名、目标或项目配置核验失败；未停止、禁用或清理任何服务") from None
    if dry_run:
        return {"ok": True, "dry_run": True, "services": [name for name, _ in units]}
    # Exclude upgrades and password changes until both service shutdown and purge finish.
    locks = []
    try:
        for path in (root / "opt/.web-upgrade.lock", root / "run/ownline-reset-admin.lock"):
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            handle = os.fdopen(descriptor, "a")
            locks.append(handle)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        body = ""
        for path, raw in files.items():
            body += "test \"$(sha256sum %s | cut -d' ' -f1)\" = %s\n" % (shlex.quote(str(path)), hashlib.sha256(raw).hexdigest())
        for name, _ in units:
            body += (f"systemctl stop {shlex.quote(name)}\n"
                     f"state=$(systemctl show {shlex.quote(name)} -p ActiveState --value)\n"
                     'case "$state" in inactive|failed) ;; *) exit 78 ;; esac\n')
        # No unit or runtime removal occurs until every stop is confirmed.
        for name, _ in units:
            body += f"systemctl disable {shlex.quote(name)}\n"
        for _, path in units:
            if path.parent == root / "etc/systemd/system":
                body += f"rm -f {shlex.quote(str(path))}\n"
        body += "systemctl daemon-reload\n"
        if purge:
            directories = ("opt/web", "opt/web-data", "opt/sing-box", "opt/ownline-upgrade")
            body += "rm -rf -- " + " ".join(shlex.quote(str(root / path)) for path in directories) + "\n"
            body += "rm -f -- " + " ".join(shlex.quote(str(root / path)) for path in
                         ("etc/caddy/Caddyfile", "etc/sing-box/.evergreen-provenance.json", "opt/.web-upgrade-journal.json")) + "\n"
        script = provenance.guarded_script(node, snapshot, body)
        script = script.replace("/run/ownline-service.lock", str(root / "run/ownline-service.lock"))
        result = runner(["bash", "-c", script], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError("卸载未完成；归属变化或服务停止未确认，未报告成功")
        return {"ok": True, "purged": bool(purge), "services": [name for name, _ in units]}
    finally:
        for handle in reversed(locks):
            handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true", required=True)
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("请使用 root 权限运行卸载")
    try:
        result = uninstall(purge=args.purge, dry_run=args.dry_run)
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
