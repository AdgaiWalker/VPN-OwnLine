"""原子 JSON 存储器与并发同步模块。

提供安全的读-写-原子替换能力，杜绝写一半断电产生坏 JSON 文件。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

_GLOBAL_FILE_LOCKS: Dict[str, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()


def _get_lock(path_str: str) -> threading.Lock:
    with _REGISTRY_LOCK:
        if path_str not in _GLOBAL_FILE_LOCKS:
            _GLOBAL_FILE_LOCKS[path_str] = threading.Lock()
        return _GLOBAL_FILE_LOCKS[path_str]


class AtomicJsonStore:
    """原子化 JSON 文件持久化引擎。"""

    @classmethod
    def load(cls, path: Union[str, Path], default: Any = None) -> Any:
        p = Path(path)
        if not p.exists():
            return default
        lock = _get_lock(str(p.resolve()))
        with lock:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return default

    @classmethod
    def dump(cls, path: Union[str, Path], data: Any, indent: int = 1) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        lock = _get_lock(str(p.resolve()))
        with lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)

    @classmethod
    def update(cls, path: Union[str, Path], mutator: Callable[[Any], Any], default: Any = None) -> Any:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _get_lock(str(p.resolve()))
        with lock:
            current = default
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        current = json.load(f)
                except Exception:
                    current = default
            updated = mutator(current)
            tmp = p.with_suffix(p.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(updated, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
            return updated
