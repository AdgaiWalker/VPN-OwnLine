"""Evergreen · OwnLine 系统版本与平滑升级控制器
负责：
1. 本地版本与 Commit 查询 (SSOT: v0.5.0)
2. 远端版本探测 (带内存缓存，防 GitHub API 频控)
3. 触发安全升级进程 (原子沙箱、独立子进程、防并发重入)
"""
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

CURRENT_VERSION = "v0.5.0"
REPO_NAME = "AdgaiWalker/VPN-OwnLine"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_NAME}/releases/latest"
CACHE_TTL = 3600  # 1小时缓存，防止 GitHub API 限流

_CACHE_LOCK = threading.Lock()
_CACHE = {
    "ts": 0,
    "data": None
}

_UPGRADE_LOCK = threading.Lock()
_UPGRADING = False


def parse_version_tuple(v_str):
    """解析语义化版本元组，例如 'v0.5.0' -> (0, 5, 0)。非标准格式回退为 (0, 0, 0)。"""
    if not v_str:
        return (0, 0, 0)
    cleaned = str(v_str).strip().lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", cleaned)
    if not m:
        return (0, 0, 0)
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    return (major, minor, patch)


def is_newer_version(latest, current=CURRENT_VERSION):
    """判断 latest 是否比 current 新。"""
    t_latest = parse_version_tuple(latest)
    t_current = parse_version_tuple(current)
    return t_latest > t_current


def get_commit_hash(base_dir=None):
    """获取当前代码仓库的简短 commit hash。"""
    try:
        cmd = ["git", "rev-parse", "--short", "HEAD"]
        cwd = base_dir or str(Path(__file__).resolve().parent.parent.parent)
        res = subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.DEVNULL, timeout=2)
        return res.decode("utf-8").strip()
    except Exception:
        return None


def get_version_info(base_dir=None):
    """获取当前系统版本详情（零网络调用）。"""
    return {
        "ok": True,
        "version": CURRENT_VERSION,
        "commit": get_commit_hash(base_dir=base_dir) or "release",
        "app": "Evergreen · OwnLine",
    }


def check_update(force=False, mock_fetcher=None, current=CURRENT_VERSION):
    """
    检查系统是否有新版本。
    force: 是否强制跳过 1 小时缓存
    mock_fetcher: 用于离网单元测试的模拟返回函数
    """
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CACHE["data"] and (now - _CACHE["ts"] < CACHE_TTL):
            cached = dict(_CACHE["data"])
            cached["cached"] = True
            return cached

    payload = None
    if mock_fetcher:
        try:
            payload = mock_fetcher()
        except Exception as e:
            return {
                "ok": False,
                "error": f"检查更新失败: {e}",
                "current_version": current,
                "has_update": False,
            }
    else:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "User-Agent": f"Evergreen-OwnLine/{current}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    raw = resp.read().decode("utf-8")
                    payload = json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return {
                    "ok": False,
                    "error": "GitHub API 请求频次受限，请稍后再试",
                    "current_version": current,
                    "has_update": False,
                }
            return {
                "ok": False,
                "error": f"上游接口响应异常 ({e.code})",
                "current_version": current,
                "has_update": False,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"网络连接超时或无法访问 GitHub: {e}",
                "current_version": current,
                "has_update": False,
            }

    if not payload or not isinstance(payload, dict):
        return {
            "ok": False,
            "error": "未获取到有效的发布信息",
            "current_version": current,
            "has_update": False,
        }

    latest_tag = payload.get("tag_name") or payload.get("name") or ""
    changelog = payload.get("body") or ""
    published_at = payload.get("published_at") or ""
    html_url = payload.get("html_url") or f"https://github.com/{REPO_NAME}/releases"

    has_up = is_newer_version(latest_tag, current=current)

    result = {
        "ok": True,
        "current_version": current,
        "latest_version": latest_tag or current,
        "has_update": has_up,
        "changelog": changelog.strip(),
        "published_at": published_at,
        "release_url": html_url,
        "cached": False,
    }

    with _CACHE_LOCK:
        _CACHE["ts"] = now
        _CACHE["data"] = result

    return result


def is_upgrading():
    """是否正在升级中。"""
    global _UPGRADING
    return _UPGRADING


def reset_upgrade_state_for_tests():
    """测试重置钩子。"""
    global _UPGRADING
    _UPGRADING = False


def trigger_upgrade(target_version=None, script_path=None, runner=None):
    """
    触发后台异步平滑升级。
    target_version: 目标 Tag（如 'v0.5.0'），为空时拉取最新 Release / main 分支。
    script_path: 指定升级脚本路径。
    runner: 测试可注入的执行函数。
    """
    global _UPGRADING
    if not _UPGRADE_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "升级任务已在进行中，请勿重复操作"}

    try:
        if _UPGRADING:
            return {"ok": False, "error": "升级任务已在进行中，请勿重复操作"}
        _UPGRADING = True
    finally:
        _UPGRADE_LOCK.release()

    script = script_path
    if not script:
        candidates = [
            "/opt/web/deploy/upgrade.sh",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../deploy/upgrade.sh")),
        ]
        for c in candidates:
            if os.path.isfile(c) and os.access(c, os.X_OK):
                script = c
                break

    if runner:
        try:
            res = runner(script, target_version)
            return {"ok": True, "status": "upgrading", "target_version": target_version or "latest", "detail": res}
        except Exception as e:
            with _UPGRADE_LOCK:
                _UPGRADING = False
            return {"ok": False, "error": f"启动升级失败: {e}"}

    if not script or not os.path.exists(script):
        with _UPGRADE_LOCK:
            _UPGRADING = False
        return {"ok": False, "error": "未找到有效的升级执行脚本 (deploy/upgrade.sh)"}

    try:
        # 使用独立的子进程会话启动，服务重启时进程树不被 kill
        cmd = ["bash", script]
        if target_version:
            cmd.append(str(target_version))
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return {
            "ok": True,
            "status": "upgrading",
            "target_version": target_version or "latest",
            "message": "升级任务已在后台启动，服务将自动平滑重载",
        }
    except Exception as e:
        with _UPGRADE_LOCK:
            _UPGRADING = False
        return {"ok": False, "error": f"无法启动升级脚本: {e}"}
