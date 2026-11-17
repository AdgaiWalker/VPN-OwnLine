"""服务独占性加密存证模块 (Provenance Manifest & Verification).

本模块为 Evergreen (OwnLine) 节点服务提供不可伪造的加密存证 (HMAC-SHA256)。
在主控端装配节点或更新配置时，将签名存证写入目标主机的特定元数据路径；
在执行自愈重启、端口解除或进程看门狗之前，严密验证该存证。
任何未持有合法存证或签名被篡改的服务，均严禁执行停止、重启或杀死进程等高危操作。
"""
from __future__ import annotations

import hashlib
import hmac
import base64
import json
import os
import re
import secrets
import shlex
import stat
import time
from typing import Any, Dict, Optional, Tuple

PROVENANCE_PATH_LINUX = "/etc/sing-box/.evergreen-provenance.json"
PROVENANCE_PATH_WIN = r"C:\ProgramData\sing-box\.evergreen-provenance.json"
SYSTEM_IDENTIFIER = "Evergreen-OwnLine"


def load_master_secret(data_dir=None, create=False) -> bytes:
    """读取独立主控签名密钥；仅首装可显式创建，不依赖订阅令牌。"""
    directory = os.fspath(data_dir or os.environ.get("LADDER_DATA", "/opt/web-data"))
    path = os.path.join(directory, "master_secret")
    if create:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="ascii") as f:
                f.write(secrets.token_hex(32) + "\n")
                f.flush()
                os.fsync(f.fileno())
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r", encoding="ascii") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("主控签名密钥文件权限必须为 0600")
        value = f.read(128).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("主控签名密钥格式无效")
    return bytes.fromhex(value)


def secret_for_node(node, data_dir=None) -> bytes:
    """目标独立密钥优先；没有目标密钥时使用本机专用签名密钥。"""
    value = node.get("control_secret")
    if value is None:
        return load_master_secret(data_dir=data_dir)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("节点签名密钥格式无效")
    return bytes.fromhex(value)


def node_identity(node) -> str:
    """归属标识不随节点改名或协议伴生记录变化。"""
    value = node.get("provenance_id") or str(node.get("host") or "").strip().lower().rstrip(".")
    if not isinstance(value, str) or not value or len(value) > 253 or any(ord(c) < 33 for c in value):
        raise ValueError("节点缺少稳定归属标识")
    return value


def config_path(node):
    return r"C:\proxy\config.json" if is_windows(node) else "/opt/sing-box/config.json"


def is_windows(node):
    return node.get("os") == "windows" or node.get("ssh_user") == "Administrator"


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
    if not master_secret:
        return False, "未提供主控签名密钥"
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


def verify_target(node, execute_remote_fn, master_secret=None, cfg_path=None, provenance_path=None):
    """只读核验签名、稳定目标标识和现网配置，返回锁内复核所需的快照。"""
    try:
        secret = secret_for_node(node) if master_secret is None else master_secret
        if not secret:
            raise ValueError("empty secret")
        expected_id = node_identity(node)
    except (OSError, ValueError, UnicodeError):
        return False, "未提供有效的独立主控签名密钥或节点标识", None
    cfg = cfg_path or config_path(node)
    prov = provenance_path or get_provenance_path(node)
    if is_windows(node):
        q_cfg, q_prov = cfg.replace("'", "''"), prov.replace("'", "''")
        command = ("$ErrorActionPreference='Stop'; "
                   f"@{{config=[Convert]::ToBase64String([IO.File]::ReadAllBytes('{q_cfg}')); "
                   f"provenance=[Convert]::ToBase64String([IO.File]::ReadAllBytes('{q_prov}'))}} | ConvertTo-Json -Compress")
    else:
        source = ("import base64,json,sys; from pathlib import Path; "
                  "print(json.dumps({k:base64.b64encode(Path(p).read_bytes()).decode('ascii') "
                  "for k,p in zip(('config','provenance'),sys.argv[1:])}))")
        command = "python3 -c %s %s %s" % (shlex.quote(source), shlex.quote(cfg), shlex.quote(prov))
    try:
        result = execute_remote_fn(node, command, timeout=12)
        if result is None or result.returncode != 0:
            raise ValueError("read failed")
        payload = json.loads(result.stdout)
        raw_cfg = base64.b64decode(payload["config"], validate=True)
        raw_prov = base64.b64decode(payload["provenance"], validate=True)
        if len(raw_cfg) > 2_000_000 or len(raw_prov) > 16384:
            raise ValueError("too large")
        manifest = json.loads(raw_prov)
        ok, reason = verify_provenance(manifest, secret)
        if not ok:
            return False, reason, None
        if manifest.get("node_id") != expected_id:
            return False, "存证目标标识与当前节点不匹配", None
        digest = compute_config_sha256(raw_cfg)
        if not hmac.compare_digest(str(manifest.get("config_sha256", "")), digest):
            return False, "存证与目标现网配置摘要不匹配", None
        return True, "", {"manifest": manifest, "config_sha256": digest,
                          "manifest_sha256": compute_config_sha256(raw_prov),
                          "config_path": cfg, "provenance_path": prov}
    except Exception:
        return False, "无法读取有效存证及现网配置，未执行服务变更", None


def guarded_script(node, snapshot, body, wait=10):
    """在目标互斥锁内重比已验证文件，状态改变时禁止任何变更。"""
    cfg, prov = snapshot["config_path"], snapshot["provenance_path"]
    if is_windows(node):
        cfg, prov = cfg.replace("'", "''"), prov.replace("'", "''")
        return f"""$ErrorActionPreference='Stop'
$ownlineMutex = New-Object System.Threading.Mutex($false, 'Global\\OwnLineServiceMutation')
if (-not $ownlineMutex.WaitOne({int(wait) * 1000})) {{ throw 'SERVICE_LOCK_BUSY' }}
try {{
  if ((Get-FileHash -Algorithm SHA256 -LiteralPath '{cfg}').Hash.ToLowerInvariant() -ne '{snapshot['config_sha256']}' -or
      (Get-FileHash -Algorithm SHA256 -LiteralPath '{prov}').Hash.ToLowerInvariant() -ne '{snapshot['manifest_sha256']}') {{ throw 'OWNERSHIP_CHANGED' }}
{body}
}} finally {{ $ownlineMutex.ReleaseMutex(); $ownlineMutex.Dispose() }}
"""
    checks = (f"test \"$(sha256sum {shlex.quote(cfg)} | cut -d' ' -f1)\" = {shlex.quote(snapshot['config_sha256'])}\n"
              f"test \"$(sha256sum {shlex.quote(prov)} | cut -d' ' -f1)\" = {shlex.quote(snapshot['manifest_sha256'])}\n")
    inner = "set -euo pipefail\numask 077\n" + checks + body
    return ("command -v flock >/dev/null 2>&1 || exit 76\n"
            f"flock -x -w {int(wait)} /run/ownline-service.lock bash -c {shlex.quote(inner)}")


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
    """仅续签已验证的同一配置；首装必须在空白目标流程中建立存证。"""
    ok, _, snapshot = verify_target(node, execute_remote_fn, master_secret)
    if not ok or snapshot["config_sha256"] != compute_config_sha256(config_content):
        return False
    node_id = node_identity(node)
    config_sha = compute_config_sha256(config_content)
    manifest = sign_provenance(node_id, config_sha, master_secret)
    content_json = json.dumps(manifest, indent=2, ensure_ascii=False)

    path = get_provenance_path(node)
    is_win = (node.get("os") == "windows") or (node.get("ssh_user") == "Administrator")

    if is_win:
        encoded = base64.b64encode(content_json.encode()).decode("ascii")
        cmd = f"[IO.File]::WriteAllBytes('{path.replace(chr(39), chr(39) * 2)}', [Convert]::FromBase64String('{encoded}'))"
    else:
        dir_path = os.path.dirname(path)
        quoted_content = shlex.quote(content_json)
        cmd = f"mkdir -p {shlex.quote(dir_path)} && printf %s {quoted_content} > {shlex.quote(path)} && chmod 600 {shlex.quote(path)}"

    try:
        res = execute_remote_fn(node, guarded_script(node, snapshot, cmd), timeout=timeout)
        return getattr(res, "returncode", -1) == 0
    except Exception:
        return False
