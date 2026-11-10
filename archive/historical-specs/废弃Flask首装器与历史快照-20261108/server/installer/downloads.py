"""Verified third-party downloads; caches are private and never enter the release bundle."""

import hashlib
import http.client
import os
import tempfile
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from pathlib import Path

from .state import Problem

MIRRORS = ("https://ghproxy.net/", "https://ghfast.top/")
PACKAGES = {
    "sing-box": {
        "version": "1.14.4",
        "algorithm": "sha256",
        "hashes": {
            "amd64": "699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968",
            "arm64": "436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26",
        },
        "url": "https://github.com/SagerNet/sing-box/releases/download/v{version}/sing-box-{version}-linux-{arch}.tar.gz",
        "filename": "sing-box-{version}-linux-{arch}.tar.gz",
    },
    "caddy": {
        "version": "2.10.2",
        "algorithm": "sha512",
        "hashes": {
            "amd64": "747df7ee74de188485157a383633a1a963fd9233b71fbb4a69ddcbcc589ce4e2cc82dacf5dbbe136cb51d17e14c59daeb5d9bc92487610b0f3b93680b2646546",
            "arm64": "6ce061a690312ab38367df3c5d5f89a2e4a263e7300d300d87356211bb81e79b15933e6d6203e03fbf26f15cc0311f264805f336147dbdd24938d84b57a4421c",
        },
        "url": "https://github.com/caddyserver/caddy/releases/download/v{version}/caddy_{version}_linux_{arch}.tar.gz",
        "filename": "caddy_{version}_linux_{arch}.tar.gz",
    },
}
MAX_BYTES = 100 * 1024 * 1024


def package(kind, machine):
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine)
    if not arch or kind not in PACKAGES:
        raise Problem("UNSUPPORTED_PACKAGE", "服务器架构或程序版本不受支持。")
    spec = PACKAGES[kind]
    args = {"version": spec["version"], "arch": arch}
    official = spec["url"].format(**args)
    return {
        "filename": spec["filename"].format(**args),
        "algorithm": spec["algorithm"],
        "digest": spec["hashes"][arch],
        "urls": [prefix + official for prefix in MIRRORS] + [official],
    }


def valid(path, spec):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        return False
    digest = hashlib.new(spec["algorithm"])
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == spec["digest"]


class HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise urllib.error.URLError("insecure download redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(spec, destination, opener=None):
    """Try each fixed HTTPS source; reject partial, oversized or altered downloads."""
    opener = opener or urllib.request.build_opener(HTTPSOnlyRedirect()).open
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for url in spec["urls"]:
        fd, name = tempfile.mkstemp(prefix="download-", dir=destination.parent)
        temporary = Path(name)
        try:
            digest = hashlib.new(spec["algorithm"])
            request = urllib.request.Request(
                url, headers={"User-Agent": "VPN-OwnLine/1"}
            )
            with os.fdopen(fd, "wb") as output, opener(request, timeout=15) as response:
                length = 0
                while chunk := response.read(1024 * 1024):
                    length += len(chunk)
                    if length > MAX_BYTES:
                        raise ValueError("download too large")
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != spec["digest"]:
                continue
            os.replace(temporary, destination)
            return destination
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            temporary.unlink(missing_ok=True)
    return None


# This fixed program runs on the target only after the user starts installation.
# It receives only public package metadata, not SSH credentials, via stdin.
TARGET_FETCH = r"""
import hashlib,http.client,json,os,tempfile,urllib.request,urllib.error
from pathlib import Path
from urllib.parse import urlsplit
class HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  if urlsplit(newurl).scheme!='https':raise urllib.error.URLError('insecure redirect')
  return super().redirect_request(req,fp,code,msg,headers,newurl)
open_url=urllib.request.build_opener(HTTPSOnlyRedirect()).open
spec=json.load(__import__('sys').stdin);root=Path('/run/ownline-installer/packages')
root.mkdir(mode=0o700,parents=True,exist_ok=True);destination=root/spec['filename']
def valid(path):
 if not path.is_file() or path.stat().st_size>104857600:return False
 h=hashlib.new(spec['algorithm'])
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()==spec['digest']
if valid(destination):print(json.dumps({'path':str(destination)}));raise SystemExit
for url in spec['urls']:
 fd,name=tempfile.mkstemp(prefix='download-',dir=root);tmp=Path(name)
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'VPN-OwnLine/1'})
  with os.fdopen(fd,'wb') as out,open_url(req,timeout=15) as response:
   size=0
   while chunk:=response.read(1048576):
    size+=len(chunk)
    if size>104857600:raise ValueError('oversize')
    out.write(chunk)
  if valid(tmp):os.replace(tmp,destination);print(json.dumps({'path':str(destination)}));raise SystemExit
 except (OSError,ValueError,http.client.HTTPException):pass
 finally:tmp.unlink(missing_ok=True)
print(json.dumps({'path':None}))
"""


def prepare(ssh, kind, machine, source, data, required=True):
    spec = package(kind, machine)
    result = ssh.python(TARGET_FETCH, spec, timeout=120)
    if result.get("path"):
        return result["path"]
    local = Path(source) / "packages" / spec["filename"]
    cached = Path(data) / "packages" / spec["filename"]
    if not valid(local, spec):
        local = cached if valid(cached, spec) else fetch(spec, cached)
    if local is None or not valid(local, spec):
        if required:
            raise Problem(
                "DEPENDENCY_UNAVAILABLE",
                "无法获取已校验的 %s 安装包；请检查网络后复查原任务。" % kind,
                503,
            )
        return None
    remote = "/run/ownline-installer/packages/" + spec["filename"]
    sftp = ssh.client.open_sftp()
    try:
        sftp.put(str(local), remote)
        sftp.chmod(remote, 0o600)
    finally:
        sftp.close()
    return remote
