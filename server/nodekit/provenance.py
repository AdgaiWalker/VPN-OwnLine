"""服务独占性加密存证模块 (Provenance Manifest & Verification).

本模块为 Evergreen (OwnLine) 节点服务提供不可伪造的加密存证 (HMAC-SHA256)。
在主控端装配节点或更新配置时，将签名存证写入目标主机的特定元数据路径；
在执行自愈重启、端口解除或进程看门狗之前，严密验证该存证。
任何未持有合法存证或签名被篡改的服务，均严禁执行停止、重启或杀死进程等高危操作。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shlex
import time
from typing import Any, Dict, Optional, Tuple

PROVENANCE_PATH_LINUX = "/etc/sing-box/.evergreen-provenance.json"
PROVENANCE_PATH_WIN = r"C:\ProgramData\sing-box\.evergreen-provenance.json"
SYSTEM_IDENTIFIER = "Evergreen-OwnLine"


def compute_config_sha256(config_content: str | bytes) -> str:
    """计算配置内容的 SHA-256 摘要。"""
    if isinstance(config_content, str):
        data = config_content.encode("utf-8")
    else:
        data = config_content
    return hashlib.sha256(data).hexdigest()


def compute_signature(node_id: str, installed_at: int, config_sha256: str, master_secret: str | bytes) -> str:
    """计算存证的 HMAC-SHA256 签名。"""
    if isinstance(master_secret, str):
        secret_bytes = master_secret.encode("utf-8")
    else:
        secret_bytes = master_secret
    payload = f"{SYSTEM_IDENTIFIER}:{node_id}:{installed_at}:{config_sha256}".encode("utf-8")
    return hmac.new(secret_bytes, payload, hashlib.sha256).hexdigest()


def sign_provenance(
    node_id: str,
    config_sha256: str,
    master_secret: str | bytes,
    installed_at: Optional[int] = None,
    master_id: str = "walker-master-01",
) -> Dict[str, Any]:
    """生成包含加密签名的服务独占性存证字典。"""
    ts = int(time.time()) if installed_at is None else int(installed_at)
    sig = compute_signature(node_id, ts, config_sha256, master_secret)
    return {
        "system": SYSTEM_IDENTIFIER,
        "master_id": master_id,
        "node_id": node_id,
        "installed_at": ts,
        "config_sha256": config_sha256,
        "signature": sig,
    }


def verify_provenance(manifest: Any, master_secret: str | bytes) -> Tuple[bool, str]:
    """严密校验节点存证字典的完整性与签名有效性。

    返回 (is_valid, reason)
    """
    if not isinstance(manifest, dict):
        return False, "存证内容不是有效的 JSON 字典"

    if manifest.get("system") != SYSTEM_IDENTIFIER:
        return False, f"系统标识符不匹配: {manifest.get('system')}"

    node_id = manifest.get("node_id")
    installed_at = manifest.get("installed_at")
    config_sha256 = manifest.get("config_sha256")
    provided_sig = manifest.get("signature")

    if not all([node_id, installed_at, config_sha256, provided_sig]):
        return False, "存证元数据缺失关键字段 (node_id/installed_at/config_sha256/signature)"

    try:
        ts = int(installed_at)
    except (TypeError, ValueError):
        return False, "installed_at 时间戳非法"

    expected_sig = compute_signature(str(node_id), ts, str(config_sha256), master_secret)
    if not hmac.compare_digest(expected_sig, str(provided_sig)):
        return False, "HMAC-SHA256 存证签名不匹配，疑似配置被非主控进程篡改"

    return True, "独占签名合法有效"


def get_provenance_path(node: Dict[str, Any]) -> str:
    """获取目标主机的存证落盘绝对路径。"""
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    return PROVENANCE_PATH_WIN if is_win else PROVENANCE_PATH_LINUX


def read_remote_provenance(
    node: Dict[str, Any],
    execute_remote_fn: Any,
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """从目标节点读取存证文件内容。"""
    path = get_provenance_path(node)
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")
    if is_win:
        cmd = f'powershell -Command "if (Test-Path \'{path}\') {{ Get-Content -Raw \'{path}\' }}"'
    else:
        cmd = f"test -f {shlex.quote(path)} && cat {shlex.quote(path)} || true"

    try:
        res = execute_remote_fn(node, cmd, timeout=timeout)
        stdout = getattr(res, "stdout", "") or ""
        text = stdout.strip()
        if not text:
            return None
        return json.loads(text)
    except Exception:
        return None


def inject_remote_provenance(
    node: Dict[str, Any],
    config_content: str | bytes,
    master_secret: str | bytes,
    execute_remote_fn: Any,
    timeout: int = 15,
) -> bool:
    """在目标节点生成并持久化写入独占存证文件。"""
    node_id = node.get("id") or node.get("name") or node.get("host") or "unknown_node"
    config_sha = compute_config_sha256(config_content)
    manifest = sign_provenance(node_id, config_sha, master_secret)
    content_json = json.dumps(manifest, indent=2, ensure_ascii=False)

    path = get_provenance_path(node)
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")

    if is_win:
        escaped = content_json.replace("`", "``").replace('"', '`"')
        cmd = f'powershell -Command "New-Item -ItemType Directory -Force -Path (Split-Path \'{path}\') | Out-Null; [IO.File]::WriteAllText(\'{path}\', @\'{escaped}\'@)"'
    else:
        dir_path = os.path.dirname(path)
        quoted_content = shlex.quote(content_json)
        cmd = f"mkdir -p {shlex.quote(dir_path)} && printf %s {quoted_content} > {shlex.quote(path)} && chmod 600 {shlex.quote(path)}"

    try:
        res = execute_remote_fn(node, cmd, timeout=timeout)
        return getattr(res, "returncode", -1) == 0
    except Exception:
        return False
