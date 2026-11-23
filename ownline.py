#!/usr/bin/env python3
"""Cross-platform entrypoint and locked .venv bootstrap for Evergreen OwnLine."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
_REQUIRED_DEPS = ("paramiko", "bcrypt")
_BOOTSTRAP_COMMANDS = frozenset({"doctor", "ui", "serve", "check", "install", "vault", "tencent-instances"})
_PIP_INDEXES = (
    "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple",
    "https://pypi.org/simple",
)


def venv_python_path(root=ROOT):
    base = Path(root)
    if os.name == "nt":
        return base / ".venv" / "Scripts" / "python.exe"
    return base / ".venv" / "bin" / "python"


def has_locked_deps():
    return all(importlib.util.find_spec(pkg) is not None for pkg in _REQUIRED_DEPS)


def venv_has_deps(venv_py, runner=subprocess.run):
    if not Path(venv_py).is_file():
        return False
    probe_code = (
        "import importlib.util, sys; "
        "raise SystemExit(0 if (importlib.util.find_spec('paramiko') and importlib.util.find_spec('bcrypt')) else 1)"
    )
    try:
        res = runner(
            [str(venv_py), "-B", "-c", probe_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return res.returncode == 0
    except Exception:
        return False


def _emit_bootstrap_diag(event, detail, diag_log=None):
    try:
        from server.nodekit import local_diag

        local_diag.emit_event(event, detail, log_path=diag_log)
    except Exception:
        pass


def bootstrap_venv(root=ROOT, *, diag_log=None, runner=subprocess.run, venv_has_deps_fn=venv_has_deps):
    """Create repo-local .venv and install requirements.lock with --require-hashes."""
    base = Path(root)
    lockfile = base / "requirements.lock"
    if not lockfile.is_file():
        return None
    venv_dir = base / ".venv"
    venv_py = venv_python_path(base)

    if not venv_py.is_file():
        if sys.version_info < (3, 10):
            sys.stderr.write("需要 Python 3.10 或更新版本才能自动初始化本地依赖。\n")
            return None
        sys.stderr.write("首次运行：正在初始化本机隔离 Python 环境 (.venv)...\n")
        sys.stderr.flush()
        try:
            res = runner(
                [sys.executable, "-m", "venv", str(venv_dir)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            if res.returncode != 0 or not venv_py.is_file():
                _emit_bootstrap_diag(
                    "local_env_bootstrap_failed",
                    {"step": "venv", "returncode": res.returncode},
                    diag_log=diag_log,
                )
                sys.stderr.write("无法自动创建 .venv，请确认已安装 python3-venv 后重试。\n")
                return None
        except Exception as exc:
            _emit_bootstrap_diag("local_env_bootstrap_failed", {"step": "venv", "error": type(exc).__name__}, diag_log=diag_log)
            sys.stderr.write(f"创建 .venv 失败: {exc}\n")
            return None

    if not venv_has_deps_fn(venv_py):
        sys.stderr.write("首次运行：正在按 requirements.lock 校验安装锁定依赖...\n")
        sys.stderr.flush()
        installed_index = ""
        last_err = ""
        for index in _PIP_INDEXES:
            cmd = [
                str(venv_py),
                "-m",
                "pip",
                "install",
                "--no-input",
                "--disable-pip-version-check",
                "--timeout",
                "10",
                "--retries",
                "1",
                "--require-hashes",
                "-r",
                str(lockfile),
                "--index-url",
                index,
            ]
            try:
                res = runner(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=300,
                )
                if res.returncode == 0 and venv_has_deps_fn(venv_py):
                    installed_index = index
                    break
                last_err = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or [""]
                last_err = last_err[0][:200]
            except Exception as exc:
                last_err = str(exc)[:200]
            sys.stderr.write("当前依赖源暂不可用，正在尝试下一来源...\n")
            sys.stderr.flush()

        if not installed_index:
            _emit_bootstrap_diag(
                "local_env_bootstrap_failed",
                {"step": "pip", "detail": last_err},
                diag_log=diag_log,
            )
            sys.stderr.write(
                "锁定依赖安装未完成。可手动修复后再重试:\n"
                f"  {venv_py} -m pip install --require-hashes -r {lockfile}\n"
                "Linux/macOS 也可运行: bash deploy/install-python-deps.sh\n"
            )
            sys.stderr.flush()
            return None

        _emit_bootstrap_diag(
            "local_env_bootstrapped",
            {"index": installed_index},
            diag_log=diag_log,
        )

    return venv_py


def _first_subcommand(argv):
    for token in argv:
        if not token.startswith("-"):
            return token
    return ""


def _reexec_into_venv(venv_py, argv_list, *, root=ROOT, environ, exec_fn, subprocess_runner):
    cmd = [str(venv_py), "-B", str(Path(root) / "ownline.py"), *argv_list]
    environ["OWNLINE_BOOTSTRAPPED"] = "1"
    if os.name == "nt":
        proc = subprocess_runner(cmd, env=dict(environ))
        return int(proc.returncode)
    exec_fn(str(venv_py), cmd)
    return 0


def ensure_runtime_python(
    argv=None,
    *,
    root=ROOT,
    diag_log=None,
    environ=None,
    has_deps_fn=has_locked_deps,
    venv_has_deps_fn=venv_has_deps,
    bootstrap_fn=bootstrap_venv,
    exec_fn=os.execv,
    subprocess_runner=subprocess.run,
):
    """Switch headless/system Python to repo .venv when locked deps are missing."""
    argv_list = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    if "-h" in argv_list or "--help" in argv_list:
        return None
    if env.get("OWNLINE_BOOTSTRAPPED") == "1" or env.get("OWNLINE_NO_BOOTSTRAP") == "1":
        return None
    if has_deps_fn():
        return None

    venv_py = venv_python_path(root)
    if venv_py.is_file() and venv_has_deps_fn(venv_py):
        return _reexec_into_venv(venv_py, argv_list, root=root, environ=env, exec_fn=exec_fn, subprocess_runner=subprocess_runner)

    subcmd = _first_subcommand(argv_list)
    if subcmd not in _BOOTSTRAP_COMMANDS:
        return None
    if not (Path(root) / "requirements.lock").is_file():
        return None

    ready_py = bootstrap_fn(root, diag_log=diag_log)
    if ready_py is None:
        return None
    return _reexec_into_venv(ready_py, argv_list, root=root, environ=env, exec_fn=exec_fn, subprocess_runner=subprocess_runner)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    rc = ensure_runtime_python(sys.argv[1:])
    if rc is not None:
        sys.exit(rc)
    from server.ownline_cli import main

    sys.exit(main())
