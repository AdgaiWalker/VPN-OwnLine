"""Run the optional SSH preflight worker with bounded, private IPC."""

import json
import os
from pathlib import Path
import subprocess

"""Run the optional SSH preflight worker with bounded, private IPC."""

import json
import os
from pathlib import Path
import subprocess
import sys

CUR_DIR = Path(__file__).resolve().parent
PYTHON = Path(sys.executable if sys.executable and os.access(sys.executable, os.X_OK) else "/usr/bin/python3")


def _get_worker():
    candidates = [
        CUR_DIR / "sshcheck" / "node_check.py",
        Path("/opt/web/nodekit/sshcheck/node_check.py"),
        Path("/opt/ownline-nodecheck/sshcheck/node_check.py"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _get_deps_dir():
    candidates = [
        Path("/opt/ownline-nodecheck/deps"),
        CUR_DIR / "deps",
    ]
    for c in candidates:
        if (c / "paramiko/__init__.py").is_file():
            return c
    return None


def available():
    worker = _get_worker()
    if not worker:
        return False
    try:
        import paramiko
        return True
    except ImportError:
        deps = _get_deps_dir()
        return deps is not None


def check(body):
    if not available():
        return {"ok": False, "code": "UNAVAILABLE", "message": "连接检查暂不可用。"}
    worker = _get_worker()
    if not worker:
        return {"ok": False, "code": "UNAVAILABLE", "message": "连接检查暂不可用。"}
    worker_pkg_dir = worker.parent.parent
    deps_dir = _get_deps_dir()
    pythonpath_parts = [str(worker_pkg_dir)]
    if deps_dir:
        pythonpath_parts.append(str(deps_dir))
    existing_pp = os.environ.get("PYTHONPATH", "")
    if existing_pp:
        pythonpath_parts.append(existing_pp)
    pythonpath = ":".join(pythonpath_parts)

    try:
        payload = json.dumps(body, ensure_ascii=False)
        payload_size = len(payload.encode("utf-8"))
    except (TypeError, UnicodeError, ValueError):
        return {"ok": False, "code": "INVALID_BODY", "message": "登录信息格式不正确。"}
    if payload_size > 150000:
        return {"ok": False, "code": "BODY_TOO_LARGE", "message": "登录信息过长。"}
    try:
        proc = subprocess.run(
            [str(PYTHON), "-m", "sshcheck.node_check"],
            cwd=str(worker_pkg_dir),
            input=payload,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=45,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": pythonpath,
                "PYTHONNOUSERSITE": "1",
                "LANG": "C.UTF-8",
            },
            check=False,
        )
        if proc.returncode != 0 or len(proc.stdout) > 16384:
            raise ValueError("worker failed")
        result = json.loads(proc.stdout)
        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise ValueError("worker result invalid")
        return result
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"ok": False, "code": "UNAVAILABLE", "message": "连接检查暂不可用。"}
