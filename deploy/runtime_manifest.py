#!/usr/bin/env python3
"""Canonical source-to-runtime layout shared by first install and upgrades."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


REQUIRED = (
    "admin.py", "addnode.sh", "nodekit/__init__.py", "nodekit/system_updater.py",
    "index.html", "change-password.html", "backup-crypto.js", "requirements.lock",
    "deploy/install.sh", "deploy/upgrade.sh", "deploy/runtime_manifest.py", "deploy/release.py",
)
WEB_FILES = ("index.html", "change-password.html", "backup-crypto.js", "icon.png", "qr-sub.png")


def runtime_files(source):
    """Return every managed file without following source symlinks."""
    source = Path(source)
    files = {}
    for path in sorted((source / "server").glob("*")):
        if path.suffix in (".py", ".sh") and path.is_file():
            files[path.name] = path
    for origin, target in (("server/nodekit", "nodekit"), ("server/providers", "providers"),
                           ("web/assets", "assets"), ("deploy", "deploy"), ("scripts", "scripts")):
        directory = source / origin
        for path in sorted(directory.rglob("*")) if directory.exists() else ():
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_symlink():
                raise ValueError("release contains a symlink: " + str(path.relative_to(source)))
            if path.is_file():
                files[str(Path(target) / path.relative_to(directory))] = path
    for name in WEB_FILES:
        if (source / "web" / name).is_file():
            files[name] = source / "web" / name
    if (source / "requirements.lock").is_file():
        files["requirements.lock"] = source / "requirements.lock"
    missing = set(REQUIRED) - files.keys()
    if missing:
        raise ValueError("release is incomplete: " + ", ".join(sorted(missing)))
    for path in files.values():
        if path.is_symlink():
            raise ValueError("release contains a symlink: " + str(path.relative_to(source)))
    return files


def _destination(root, relative):
    """Do not follow runtime symlinks when overlaying managed paths."""
    path = root
    parts = Path(relative).parts
    for part in parts[:-1]:
        path = path / part
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        path.mkdir(exist_ok=True)
    path = path / parts[-1]
    if path.is_symlink():
        path.unlink()
    return path


def validate_runtime(directory):
    directory = Path(directory)
    for name in REQUIRED:
        if not (directory / name).is_file():
            raise ValueError("runtime is incomplete: " + name)
    for name in json.loads((directory / ".runtime-manifest.json").read_text()):
        path = directory / name
        if path.suffix == ".py":
            ast.parse(path.read_bytes(), filename=name)
        elif path.suffix == ".sh":
            subprocess.run(["/bin/bash", "-n", str(path)], check=True, capture_output=True)


def stage_runtime(source, destination, preserve=None):
    """Build a complete candidate before any active runtime path is changed."""
    files = runtime_files(source)
    destination = Path(destination)
    if destination.exists():
        raise ValueError("staging directory already exists")
    if preserve is not None:
        shutil.copytree(preserve, destination, symlinks=True)
    else:
        destination.mkdir(parents=True)
    for name, source_path in files.items():
        path = _destination(destination, name)
        shutil.copy2(source_path, path)
        executable = path.suffix == ".sh" or (path.suffix == ".py" and "/" not in name)
        os.chmod(path, 0o755 if executable else 0o644)
    manifest = _destination(destination, ".runtime-manifest.json")
    manifest.write_text(json.dumps(sorted(files)) + "\n")
    os.chmod(manifest, 0o644)
    validate_runtime(destination)
    return destination


def install_runtime(source, destination):
    """First install uses the same manifest, including executable upgrade tools."""
    destination = Path(destination)
    files = runtime_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name, source_path in files.items():
        path = _destination(destination, name)
        shutil.copy2(source_path, path)
        executable = path.suffix == ".sh" or (path.suffix == ".py" and "/" not in name)
        os.chmod(path, 0o755 if executable else 0o644)
    (destination / ".runtime-manifest.json").write_text(json.dumps(sorted(files)) + "\n")
    validate_runtime(destination)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: runtime_manifest.py SOURCE_REPOSITORY DESTINATION")
    install_runtime(*sys.argv[1:])
