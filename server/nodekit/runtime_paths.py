"""Cross-platform path resolution for source checkouts and frozen installers."""

import os
from pathlib import Path
import sys


def is_frozen() -> bool:
    """Return True when executing inside a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None))


def bundle_root() -> Path:
    """Return read-only asset root (repository root or frozen _MEIPASS)."""
    if is_frozen():
        meipass = Path(sys._MEIPASS).resolve()
        if sys.platform == "darwin" and meipass.name == "Frameworks":
            resources = meipass.parent / "Resources"
            admin_py = resources / "server" / "admin.py"
            if admin_py.is_file() and not admin_py.is_symlink():
                return resources.resolve()
        return meipass
    return Path(__file__).resolve().parents[2]


def writable_state_dir(root=None) -> Path:
    """Return writable directory for local state and redacted diagnostics."""
    if root is not None:
        return Path(root) / ".ops-private"
    override = os.environ.get("OWNLINE_STATE_DIR", "").strip()
    if override:
        path = Path(override)
        _ensure_private_dir(path)
        return path
    if is_frozen():
        path = Path.home() / ".ownline"
        _ensure_private_dir(path)
        return path
    return bundle_root() / ".ops-private"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
