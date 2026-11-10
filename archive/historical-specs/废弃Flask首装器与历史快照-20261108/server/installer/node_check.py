"""Read-only SSH inspection for adding a node to an existing management server.

This is deliberately separate from the first-installation probe: an existing
management service or Caddy configuration does not itself make a node unsafe.
This module does not install, write files on the target, or persist credentials.
"""

import re
import json
import sys

from .state import Problem
from .transport import SSH, credentials, normalize


NODE_PROBE = r'''
import json, os, platform, subprocess
from pathlib import Path
os_info = {}
try:
 for line in Path('/etc/os-release').read_text().splitlines():
  if '=' in line:
   key, value = line.split('=', 1)
   os_info[key] = value.strip('"')
except OSError:
 pass
paths = ['/opt/sing-box/sing-box', '/opt/sing-box/config.json',
 '/etc/systemd/system/sing-box.service', '/lib/systemd/system/sing-box.service',
 '/usr/lib/systemd/system/sing-box.service']
try:
 machine_id = Path('/etc/machine-id').read_text().strip()
except OSError:
 machine_id = ''
try:
 p = subprocess.run(['systemctl', 'is-active', 'sing-box'], stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, timeout=5)
 service = p.stdout.strip() if p.returncode in (0, 3, 4) else 'unknown'
except (OSError, subprocess.SubprocessError):
 service = 'unknown'
print(json.dumps({'os': os_info.get('ID', ''), 'version': os_info.get('VERSION_ID', ''),
 'architecture': platform.machine(), 'root': os.geteuid() == 0,
 'systemd': Path('/run/systemd/system').exists(),
 'existing_singbox': Path('/opt/sing-box').exists() or any(Path(path).exists() for path in paths),
 'machine_id': machine_id,
 'singbox_service': service}))
'''


def check(body, allowed_targets=()):
    """Inspect a pinned public SSH target; raises Problem on any uncertainty."""
    target = normalize(body, allowed_targets)
    secret = credentials(body)
    ssh = SSH(target, secret)
    try:
        info = ssh.python(NODE_PROBE, timeout=20)
        if not isinstance(info, dict):
            raise ValueError("probe must return an object")
        for key in ("root", "systemd", "existing_singbox"):
            if type(info.get(key)) is not bool:
                raise ValueError("invalid probe state")
        for key in ("os", "version", "architecture", "singbox_service", "machine_id"):
            if not isinstance(info.get(key), str) or not re.fullmatch(r"[A-Za-z0-9._-]{0,64}", info[key]):
                raise ValueError("invalid probe value")
        service = info["singbox_service"]
        if service not in ("active", "inactive", "failed", "unknown", "activating", "deactivating"):
            service = "unknown"
        # A failed or unavailable service query must not imply a clean machine.
        existing = info["existing_singbox"] or service in ("active", "failed", "activating", "deactivating")
        try:
            version = tuple(int(part) for part in info["version"].split("."))
        except ValueError:
            version = ()
        supported = (info["os"] == "ubuntu" and version >= (22, 4)) or (info["os"] == "debian" and version >= (12,))
        ready = (supported and info["architecture"] in ("x86_64", "aarch64", "arm64")
                 and info["root"] and info["systemd"] and not existing
                 and service == "inactive" and bool(re.fullmatch(r"[a-f0-9]{32}", info["machine_id"])))
        return {
            "target": target["host"],
            "address": target["address"],
            "ssh_port": target["ssh_port"],
            "username": target["username"],
            "fingerprint": ssh.fingerprint,
            "host_key_type": ssh.host_key.get_name(),
            "host_key": ssh.host_key.get_base64(),
            "machine_id": info["machine_id"],
            "os": info["os"],
            "version": info["version"],
            "architecture": info["architecture"],
            "root": info["root"],
            "systemd": info["systemd"],
            "existing_singbox": existing,
            "singbox_service": service,
            "ready_for_install": bool(ready),
            "message": "只读检查完成；尚未安装。",
        }
    except (KeyError, TypeError, ValueError):
        raise Problem("REMOTE_RESPONSE_INVALID", "服务器返回的检查结果无效。") from None
    finally:
        ssh.close()


def main():
    # Payload is passed through stdin rather than argv or temporary files.
    try:
        body = json.load(sys.stdin)
        if not isinstance(body, dict):
            raise Problem("INVALID_BODY", "请求内容必须是对象。")
        result = {"ok": True, "result": check(body)}
    except Problem as exc:
        result = {"ok": False, "code": exc.code, "message": exc.message}
        if exc.code == "HOST_KEY_CONFIRMATION" and isinstance(exc.detail, dict):
            result["fingerprint"] = exc.detail.get("fingerprint", "")
    except Exception:
        # Third-party errors may contain secrets; never relay their raw text.
        result = {"ok": False, "code": "CHECK_FAILED", "message": "连接检查未完成，请检查后重试。"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
