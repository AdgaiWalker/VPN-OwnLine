"""Read-only checks for a new controller, in addition to node checks."""

from . import node_check
from .problem import Problem
from .transport import SSH, credentials, normalize


CONTROLLER_PROBE = r'''
import json, shutil, subprocess
from pathlib import Path
paths = ['/opt/web', '/opt/web-data', '/etc/caddy/Caddyfile',
         '/etc/systemd/system/admin.service', '/var/lib/ownline-installer',
         '/etc/systemd/system/caddy.service', '/lib/systemd/system/caddy.service',
         '/usr/lib/systemd/system/caddy.service']
try:
 machine_id = Path('/etc/machine-id').read_text().strip()
 states = []
 for name in ('caddy', 'admin'):
  service = subprocess.run(['systemctl', 'is-active', name],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True, timeout=5)
  state = service.stdout.strip()
  if service.returncode not in (0, 3, 4) or state not in ('active', 'inactive', 'failed', 'activating', 'deactivating', 'unknown'):
   raise OSError('service state unavailable')
  states.append(state)
 print(json.dumps({'machine_id': machine_id,
                   'existing_controller': any(s not in ('inactive', 'unknown') for s in states) or
                   any(Path(p).exists() or Path(p).is_symlink() for p in paths),
                   'disk_ok': shutil.disk_usage('/').free >= 500 * 1024 * 1024}))
except (OSError, subprocess.SubprocessError):
 print(json.dumps({'error': 'probe_failed'}))
'''


def check(body, allowed_targets=()):
    """Fail closed if controller files or the checked host identity differ."""
    result = node_check.check(body, allowed_targets)
    if not result.get("ready_for_install"):
        return result
    pinned = dict(body, host=result["address"], fingerprint=result["fingerprint"])
    target = normalize(pinned, allowed_targets)
    ssh = SSH(target, credentials(body))
    use_sudo = (result.get("root") is not True) and (result.get("sudo_nopasswd") is True)
    try:
        info = ssh.python(CONTROLLER_PROBE, timeout=20, sudo=True) if use_sudo else ssh.python(CONTROLLER_PROBE, timeout=20)
        if (not isinstance(info, dict) or type(info.get("existing_controller")) is not bool
                or type(info.get("disk_ok")) is not bool
                or info.get("machine_id") != result["machine_id"]
                or ssh.fingerprint != result["fingerprint"]):
            raise Problem("TARGET_CHANGED", "服务器身份或状态无法确认，请重新检查。", 409)
        result["existing_controller"] = info["existing_controller"]
        if info["existing_controller"]:
            result["ready_for_install"] = False
            result["message"] = "检测到已有管理配置，未进行安装。"
        elif not info["disk_ok"]:
            result["ready_for_install"] = False
            result["message"] = "目标服务器可用磁盘空间不足 500 MiB。"
        return result
    finally:
        ssh.close()
