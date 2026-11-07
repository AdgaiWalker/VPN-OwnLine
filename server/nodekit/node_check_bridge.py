"""Run the optional SSH preflight worker with bounded, private IPC."""

import json
import os
from pathlib import Path
import subprocess

WEB = Path("/opt/ownline-nodecheck")
PYTHON = Path("/usr/bin/python3")
DEPS = WEB / "deps"
WORKER = WEB / "sshcheck/node_check.py"


def available():
    return os.access(PYTHON, os.X_OK) and WORKER.is_file() and (DEPS / "paramiko/__init__.py").is_file()


def check(body):
    if not available():
        return {"ok": False, "code": "UNAVAILABLE", "message": "连接检查暂不可用。"}
    try:
        payload = json.dumps(body, ensure_ascii=False)
        payload_size = len(payload.encode("utf-8"))
    except (TypeError, UnicodeError, ValueError):
        return {"ok": False, "code": "INVALID_BODY", "message": "登录信息格式不正确。"}
    if payload_size > 150000:
        return {"ok": False, "code": "BODY_TOO_LARGE", "message": "登录信息过长。"}
    try:
        proc = subprocess.run(
            [str(PYTHON), "-m", "sshcheck.node_check"], cwd=str(WEB),
            input=payload, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=45,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(WEB) + ":" + str(DEPS),
                 "PYTHONNOUSERSITE": "1", "LANG": "C.UTF-8"},
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
