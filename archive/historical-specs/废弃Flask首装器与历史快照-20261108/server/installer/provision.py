"""Immutable source bundle, target supervisor and independently verified delivery."""

import base64
import hashlib
import json
import os
import secrets
import shlex
import ssl
import tarfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import bcrypt

from .state import Problem


def bundle(source, data_dir):
    source, output = Path(source), Path(data_dir) / "releases"
    output.mkdir(mode=0o700, exist_ok=True)
    import gzip
    import tempfile

    descriptor, temporary = tempfile.mkstemp(
        prefix="bundle-", suffix=".tmp", dir=output
    )
    try:
        # Stream the archive to private disk: concurrent checks must not each hold a full tar in RAM.
        with os.fdopen(descriptor, "wb") as raw_archive:
            with gzip.GzipFile(
                filename="", fileobj=raw_archive, mode="wb", mtime=0
            ) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|") as tar:
                    for name in ("server", "web", "deploy"):
                        directory = source / name
                        if not directory.exists():
                            continue
                        for path in sorted(directory.rglob("*")):
                            relative = path.relative_to(source)
                            if (
                                not path.is_file()
                                or path.is_symlink()
                                or any(
                                    part.startswith(".") or part == "__pycache__"
                                    for part in relative.parts
                                )
                            ):
                                continue
                            if name == "server" and (
                                path.suffix not in (".py", ".sh")
                                or path.name.endswith("_tests.py")
                            ):
                                continue
                            if name == "web" and path.suffix not in (
                                ".html",
                                ".css",
                                ".js",
                                ".svg",
                                ".png",
                                ".jpg",
                                ".ico",
                            ):
                                continue
                            if name == "deploy" and path.suffix not in (
                                ".sh",
                                ".service",
                                ".timer",
                            ):
                                continue
                            info = tarfile.TarInfo(str(relative))
                            info.size = path.stat().st_size
                            info.mode = 0o755 if path.suffix == ".sh" else 0o644
                            with path.open("rb") as content:
                                tar.addfile(info, content)
        digest = hashlib.sha256()
        with open(temporary, "rb") as archive:
            for chunk in iter(lambda: archive.read(1048576), b""):
                digest.update(chunk)
        release = digest.hexdigest()
        final = output / (release + ".tar.gz")
        os.replace(temporary, final)
        return release, str(final)
    finally:
        Path(temporary).unlink(missing_ok=True)


def deploy(ssh, jid, request, archive, delivery, tls_internal=False, prepared=None):
    root = "/var/lib/ownline-installer"
    sftp = ssh.client.open_sftp()
    try:
        for directory in (root, root + "/jobs", root + "/jobs/" + jid):
            try:
                sftp.mkdir(directory, 0o700)
            except OSError:
                sftp.stat(directory)
        with sftp.file(root + "/jobs/" + jid + "/source.tar.gz", "wb") as f:
            f.write(Path(archive).read_bytes())
        sftp.chmod(root + "/jobs/" + jid + "/source.tar.gz", 0o600)
        with tarfile.open(archive) as package:
            supervisor = package.extractfile("server/installer/remote.py").read()
        with sftp.file(root + "/jobs/" + jid + "/remote.py", "wb") as f:
            f.write(supervisor)
    finally:
        sftp.close()
    start(ssh, jid, request, delivery, tls_internal, prepared)


def start(ssh, jid, request, delivery, tls_internal=False, prepared=None, resume=False):
    root = "/var/lib/ownline-installer"
    params = {
        "job_id": jid,
        "release_id": request["release_id"],
        "sub_token": delivery["sub_token"],
        "password_hash": bcrypt.hashpw(
            delivery["password"].encode(), bcrypt.gensalt()
        ).decode(),
        "domain": request["domain"],
        "public_ip": request["address"],
        "tls_internal": tls_internal,
        "prepared": prepared or {},
        "resume": resume,
    }
    code, out, _ = ssh.run(
        "python3 " + shlex.quote(root + "/jobs/" + jid + "/remote.py"),
        json.dumps(params).encode(),
        timeout=60,
    )
    if code:
        raise Problem("REMOTE_START_FAILED", "目标安装任务未能启动。")
    try:
        answer = json.loads(out)
    except ValueError:
        raise Problem("REMOTE_START_FAILED", "目标未返回任务启动结果。") from None
    if answer.get("error"):
        raise Problem(
            answer["error"], "目标状态已变化或不允许安全续装，请检查原任务。", 409
        )


def status(ssh, jid):
    return ssh.python(
        r"""
import json,subprocess
from pathlib import Path
jid=json.load(__import__('sys').stdin)['job_id'];root=Path('/var/lib/ownline-installer/jobs')/jid
state=root/'state.json'
if not state.exists():print(json.dumps({'state':'not_started'}));raise SystemExit
s=json.loads(state.read_text())
u=subprocess.run(['systemctl','show',s.get('unit','ownline-install-'+jid),'--property=ActiveState','--value'],capture_output=True,text=True).stdout.strip()
if s['state'] in ['running','starting'] and u not in ['active','activating'] and __import__('time').time()-s.get('started',0)>5:s['state']='interrupted'
s['services']={name:subprocess.run(['systemctl','is-active',name],capture_output=True,text=True).stdout.strip() for name in ['admin','caddy','sing-box']}
s['quota_paused']=Path('/var/lib/ownline/quota-paused').exists()
settings=Path('/opt/web-data/settings.json')
if s['state']=='installed' and settings.exists():
 cfg=json.loads(settings.read_text());s['sub_token']=cfg['sub_token']
 s['nodes']=len(json.loads(Path('/opt/web-data/nodes.json').read_text()))
print(json.dumps(s))
""",
        {"job_id": jid},
    )


def reset_delivery(ssh, jid, password):
    # Only an explicit recovery action may rotate this newly installed dashboard's password.
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    answer = ssh.python(
        r"""
import json,os,re,subprocess,tempfile
from pathlib import Path
p=json.load(__import__('sys').stdin);f=Path('/etc/caddy/Caddyfile');raw=f.read_text()
if '# ownline-setup-job:'+p['job_id'] not in raw:print(json.dumps({'ok':False}));raise SystemExit
new,count=re.subn(r'(?m)^(\s*admin )\$2[aby]\$\S+',lambda m:m[1]+p['hash'],raw)
if count<1:print(json.dumps({'ok':False}));raise SystemExit
fd,name=tempfile.mkstemp(prefix='ownline-caddy-',dir='/etc/caddy')
try:
 with os.fdopen(fd,'w') as out:out.write(new)
 os.chmod(name,0o644)
 check=subprocess.run(['caddy','validate','--config',name,'--adapter','caddyfile'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 if check.returncode:print(json.dumps({'ok':False}));raise SystemExit
 os.replace(name,f)
 rc=subprocess.run(['systemctl','reload','caddy'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode
 print(json.dumps({'ok':rc==0}))
finally:
 Path(name).unlink(missing_ok=True)
""",
        {"job_id": jid, "hash": password_hash},
    )
    if not answer.get("ok"):
        raise Problem("DELIVERY_RESET_FAILED", "网页登录信息未能恢复，原任务仍需处理。")


def cleanup(ssh, jid):
    """Remove downloaded binaries after verification, retaining task and source facts."""
    return ssh.python(
        r"""
import json,shutil
from pathlib import Path
jid=json.load(__import__('sys').stdin)['job_id'];root=Path('/var/lib/ownline-installer/jobs')/jid
state=json.loads((root/'state.json').read_text())
if state.get('state')!='installed':print(json.dumps({'ok':False}));raise SystemExit
pack=root/'source/packages'
if pack.is_dir() and not pack.is_symlink():shutil.rmtree(pack)
(root/'source.tar.gz').unlink(missing_ok=True)
cache=Path('/run/ownline-installer/packages')
if cache.is_dir() and not cache.is_symlink():shutil.rmtree(cache)
print(json.dumps({'ok':True}))
""",
        {"job_id": jid},
    )


def verify(url, delivery, ca_file=None):
    if urlsplit(url).scheme != "https":
        raise Problem("HTTPS_REQUIRED", "管理地址必须使用 HTTPS。")
    context = ssl.create_default_context(cafile=ca_file)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
        urllib.request.HTTPSHandler(context=context),
    )
    try:
        opener.open(url, timeout=10)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise Problem("AUTH_NOT_ENFORCED", "管理页未返回预期认证要求。") from None
    else:
        raise Problem("AUTH_NOT_ENFORCED", "管理页缺少预期认证保护。")
    auth = base64.b64encode(("admin:" + delivery["password"]).encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
    try:
        response = opener.open(req, timeout=10)
    except urllib.error.HTTPError as exc:
        if exc.code != 303 or exc.headers.get("Location") != "/change-password":
            raise Problem("DASHBOARD_INVALID", "管理网页响应不符合预期。") from None
        # Only a fixed same-origin first-login path may receive credentials.
        response = opener.open(urllib.request.Request(
            url.rstrip("/") + "/change-password", headers={"Authorization": "Basic " + auth}), timeout=10)
    with response:
        if response.status != 200 or b"VPN-OwnLine" not in response.read(200000):
            raise Problem("DASHBOARD_INVALID", "管理网页响应不符合预期。")
    sub = url.rstrip("/") + "/s/" + delivery["sub_token"] + "/sr"
    with opener.open(sub, timeout=10) as response:
        data = response.read(1000000)
        try:
            decoded = base64.b64decode(data, validate=False)
        except ValueError:
            decoded = b""
        if response.status != 200 or b"vless://" not in decoded:
            raise Problem("SUBSCRIPTION_INVALID", "订阅尚未通过验证。")
    return sub


def fresh_delivery():
    return {
        "username": "admin",
        "password": secrets.token_urlsafe(24),
        "sub_token": secrets.token_hex(32),
    }
