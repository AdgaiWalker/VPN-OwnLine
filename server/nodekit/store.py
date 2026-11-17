"""原子 JSON 存储器与并发同步模块。

提供安全的读-写-原子替换能力，杜绝写一半断电产生坏 JSON 文件。
"""
from __future__ import annotations

import json
import os
import threading
import fcntl
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

_GLOBAL_FILE_LOCKS: Dict[str, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()


def _get_lock(path_str: str) -> threading.Lock:
    with _REGISTRY_LOCK:
        if path_str not in _GLOBAL_FILE_LOCKS:
            _GLOBAL_FILE_LOCKS[path_str] = threading.Lock()
        return _GLOBAL_FILE_LOCKS[path_str]


@contextmanager
def _file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _get_lock(str(path.resolve())):
        fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _write(path, data, indent):
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=indent)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class AtomicJsonStore:
    """原子化 JSON 文件持久化引擎。"""

    @classmethod
    def load(cls, path: Union[str, Path], default: Any = None) -> Any:
        p = Path(path)
        if not p.exists():
            return default
        with _file_lock(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return default

    @classmethod
    def dump(cls, path: Union[str, Path], data: Any, indent: int = 1) -> None:
        p = Path(path)
        with _file_lock(p):
            _write(p, data, indent)

    @classmethod
    def update(cls, path: Union[str, Path], mutator: Callable[[Any], Any], default: Any = None) -> Any:
        p = Path(path)
        with _file_lock(p):
            current = default
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    current = json.load(f)
            updated = mutator(current)
            _write(p, updated, 1)
            return updated
