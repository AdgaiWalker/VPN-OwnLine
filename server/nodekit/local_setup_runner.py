"""Direct, pinned SSH installation from a local source checkout."""
import io
import json
import secrets

import bcrypt

from .installations import InstallError, emit_bundle, verify_delivery
from .sshcheck.transport import SSH, normalize, credentials
from .local_setup_progress import StageReader


VERIFY = r'''
import json,sys,subprocess
sys.path.insert(0,'/opt/web')
from nodekit import verify
from pathlib import Path
services = all(subprocess.run(['systemctl','is-active','--quiet',s]).returncode == 0 for s in ('admin','caddy','sing-box'))
nodes=json.loads(Path('/opt/web-data/nodes.json').read_text())
results=[verify.run(n) for n in nodes if n.get('local') is True]
print(json.dumps({'ok':services and len(results)>=2 and all(r.get('health')=='ok' for r in results)}))
'''


def install(checked, source, on_progress=None):
    """No SSH credentials leave process memory or enter remote command text."""
    login, identity = checked['login'], checked['identity']
    report = on_progress or (lambda stage: None)
    report('connect')
    ssh = SSH(normalize(login), credentials(login))
    jid = secrets.token_hex(16)
    directory = '/tmp/ownline-local-' + jid
    password, token = secrets.token_urlsafe(24), secrets.token_hex(32)
    domain = identity[0].replace('.', '-') + '.sslip.io'
    try:
        # Atomic exclusion and identity recheck precede all target writes.
        command = """set -eu
test "$(cat /etc/machine-id)" = '%s'
mkdir /run/ownline-local-install.lock
""" % identity[2]
        code, _, _ = ssh.run(command)
        if code:
            raise InstallError('目标身份变化或已有安装任务，未安装')
        result = None
        try:
            report('upload')
            stream = io.BytesIO()
            emit_bundle(source / 'server', stream)
            code, _, _ = ssh.run("umask 077; mkdir '%s' && tar xzf - -C '%s'" % (directory, directory), stream.getvalue(), timeout=120)
            if code:
                raise InstallError('源码传输未完成')
            # Reuse the direct install's existing-conflict guard in the same shell.
            guard = r'''
set -eu
for p in /opt/web /opt/web-data /opt/sing-box /etc/caddy/Caddyfile /var/lib/ownline-installer; do
 [ ! -e "$p" ] && [ ! -L "$p" ] || exit 3
done
for s in caddy sing-box admin; do
 for d in /etc/systemd/system /lib/systemd/system /usr/lib/systemd/system; do
  [ ! -e "$d/$s.service" ] && [ ! -L "$d/$s.service" ] || exit 3
 done
 systemctl is-active --quiet "$s" && exit 3
done
'''
            payload = '\n'.join((jid, token, bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), domain, identity[0])) + '\n'
            report('preflight')
            code, _, _ = ssh.run(guard + "\nbash '%s/deploy/install.sh' --setup-stdin" % directory,
                                  payload.encode(), timeout=1800, on_stdout=StageReader(report))
            if code:
                raise InstallError('目标安装未完成，请检查原服务器状态')
            report('server_verify')
            if ssh.python(VERIFY, timeout=180).get('ok') is not True:
                raise InstallError('服务端代理验收未通过')
            report('delivery_verify')
            delivery = verify_delivery({'domain': domain, 'sub_token': token}, identity[0], password)
            result = {'verified': True, 'delivery': delivery}
        finally:
            # Only this invocation's staging directory and lock are removed.
            if result is not None:
                report('cleanup')
            try:
                code, _, _ = ssh.run("rm -rf '%s'; rmdir /run/ownline-local-install.lock" % directory, timeout=20)
                if code:
                    raise InstallError('临时安装文件清理未完成')
            except Exception:
                if result is not None:
                    raise
        return result
    finally:
        ssh.close()
