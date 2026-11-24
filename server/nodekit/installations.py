"""Checked-target capabilities and bounded in-memory installation input."""
import base64
import hashlib
import http.client
import ipaddress
import secrets
import socket
import ssl
import threading
import time
try:
    import fcntl
except ImportError:  # Windows lacks POSIX fcntl; pin_known_host checks explicitly.
    fcntl = None
import os
import subprocess


class InstallError(ValueError):
    def __init__(self, message="", *, code=None):
        super().__init__(message)
        self.code = code


class CheckedTargets:
    def __init__(self, ttl=600, limit=32, clock=time.monotonic):
        self.ttl, self.limit, self.clock = ttl, limit, clock
        self._items = {}
        self._lock = threading.Lock()
        self._timer = None

    def _schedule(self):
        if self.clock is not time.monotonic or self._timer is not None or not self._items:
            return
        delay = max(0.01, min(item[0] for item in self._items.values()) - self.clock())
        self._timer = threading.Timer(delay, self._purge)
        self._timer.daemon = True
        self._timer.start()

    def _purge(self):
        with self._lock:
            self._timer = None
            self._expire()
            self._schedule()

    def _expire(self):
        now = self.clock()
        for key in list(self._items):
            if self._items[key][0] <= now:
                del self._items[key]

    @staticmethod
    def identity(result):
        import re
        if result.get("ready_for_install") is not True:
            raise InstallError("服务器未满足安全安装条件，请重新检查")
        address = str(ipaddress.ip_address(result["address"]))
        if not ipaddress.ip_address(address).is_global:
            raise InstallError("安装目标必须为公网地址")
        key = base64.b64decode(result["host_key"], validate=True)
        fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
        if fingerprint != result["fingerprint"] or not re.fullmatch(r"[a-f0-9]{32}", result["machine_id"]):
            raise InstallError("检查结果缺少可信服务器身份")
        if not re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521))", result["host_key_type"]):
            raise InstallError("服务器 SSH 密钥类型无效")
        return (address, result["fingerprint"], result["machine_id"], result["host_key_type"], result["host_key"])

    def remember(self, login, result):
        try:
            identity = self.identity(result)
            request = {k: login.get(k, "") for k in ("host", "username", "ssh_port", "password", "private_key", "passphrase")}
            request.update(host=identity[0], fingerprint=identity[1])
            request["username"] = result.get("username") or login.get("username") or "root"
            request["ssh_port"] = int(result.get("ssh_port") or login.get("ssh_port") or 22)
            token = secrets.token_hex(32)
            with self._lock:
                self._expire()
                if len(self._items) >= self.limit:
                    raise InstallError("待安装检查过多，请稍后重试")
                self._items[token] = (self.clock() + self.ttl, request, identity)
                self._schedule()
            return token
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, InstallError):
                raise
            raise InstallError("检查结果缺少可信服务器身份") from None

    def take(self, token):
        with self._lock:
            self._expire()
            record = self._items.pop(token, None)
            if not self._items and self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if record is None:
            raise InstallError("连接检查已过期或已使用，请重新检查")
        return {"login": record[1], "identity": record[2]}

    @staticmethod
    def recheck(checked, checker):
        response = checker(checked["login"])
        try:
            current = CheckedTargets.identity(response["result"]) if response.get("ok") else None
        except (KeyError, TypeError, ValueError):
            current = None
        if current != checked["identity"]:
            raise InstallError("服务器身份或安装条件已变化，未执行安装，请重新检查")
        return response["result"]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, address, port=8443):
        super().__init__(hostname, port, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def pin_known_host(checked, filename, runner=subprocess.run):
    """Keep the checked public host key for later node_ctl operations too."""
    if fcntl is None:
        raise InstallError("当前平台不支持 POSIX known_hosts 文件锁")
    from pathlib import Path
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    address, _, _, kind, key = checked["identity"]
    port = int(checked["login"]["ssh_port"])
    label = address if port == 22 else "[%s]:%s" % (address, port)
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if path.is_symlink():
            raise InstallError("管理 SSH 指纹文件无效")
        existing = []
        if path.exists():
            result = runner(["ssh-keygen", "-F", label, "-f", str(path)], capture_output=True, text=True, timeout=5)
            if result.returncode not in (0, 1):
                raise InstallError("无法核对已有管理 SSH 指纹")
            existing = [line.split() for line in result.stdout.splitlines() if line and not line.startswith("#")]
        if existing:
            if any(len(fields) != 3 or fields[1:] != [kind, key] for fields in existing):
                raise InstallError("服务器指纹与管理记录不同，未安装，请人工核对")
            return
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "a") as output:
            output.write("\n%s %s %s\n" % (label, kind, key))
            output.flush()
            os.fsync(output.fileno())
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _verify_delivery(candidate, address, password, connection_factory):
    """TLS, unauthenticated gate, authenticated page and target subscription."""
    expected_domain = address.replace(".", "-") + ".sslip.io"
    if candidate.get("domain") != expected_domain or not candidate.get("sub_token"):
        raise InstallError("独立后台交付信息无效")
    token = candidate["sub_token"]
    import re
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise InstallError("独立后台订阅凭据无效")
    authorization = "Basic " + base64.b64encode(("admin:" + password).encode()).decode()
    for path, headers, expected in (("/change-password", {}, 401),
                                    ("/change-password", {"Authorization": authorization}, 200),
                                    ("/s/" + token, {}, 200)):
        connection = connection_factory(expected_domain, address)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status != expected:
                raise InstallError("独立后台登录或订阅验收未通过")
            if path.startswith("/s/") and not response.read(1000000):
                raise InstallError("独立后台订阅为空")
        finally:
            connection.close()
    base = "https://" + expected_domain + ":8443"
    return {"kind": "standalone", "dashboard_url": base + "/", "username": "admin",
            "temp_password": password, "sub_token": token, "direct_sub_url": base + "/s/" + token}


def verify_delivery(candidate, address, password, connection_factory=PinnedHTTPS, *, attempts=10, pause=2, sleep=time.sleep):
    """Allow bounded certificate/startup propagation without reinstalling the host."""
    last_kind = "other"
    for attempt in range(attempts):
        try:
            return _verify_delivery(candidate, address, password, connection_factory)
        except ssl.SSLError:
            last_kind = "tls"
        except (OSError, http.client.HTTPException):
            last_kind = "net"
        except InstallError:
            if attempt + 1 == attempts:
                raise
            last_kind = "other"
        if attempt + 1 == attempts:
            if last_kind == "tls":
                raise InstallError(
                    "独立后台 HTTPS 证书尚未签发，请确认云安全组已放行 80/TCP 与 8443/TCP 端口",
                    code="DELIVERY_TLS_CERT",
                ) from None
            if last_kind == "net":
                raise InstallError(
                    "独立后台管理端口暂不可达，请确认云安全组已放行 8443/TCP 与 80/TCP 端口",
                    code="DELIVERY_UNREACHABLE",
                ) from None
            raise InstallError("独立后台 TLS、登录或订阅验收未通过，请核对管理入口") from None
        sleep(pause)
    raise InstallError("独立后台验收未通过")


def emit_bundle(server_directory, output):
    """Stream the deployed code as a source-layout bundle; never include data."""
    from pathlib import Path
    import tarfile
    server = Path(server_directory)
    source_layout = (server.parent / "server/admin.py").is_file()
    project = server.parent if source_layout else server
    web = project / "web" if source_layout else server
    candidates = []
    for pattern in ("*.py", "*.sh"):
        candidates += [(p, "server/" + p.name) for p in server.glob(pattern)]
    for directory, prefix in ((server / "nodekit", "server/nodekit"),
                              (server / "providers", "server/providers"),
                              (project / "deploy", "deploy"), (project / "scripts", "scripts"),
                              (web / "assets", "web/assets")):
        for path in directory.rglob("*") if directory.exists() else ():
            if "__pycache__" not in path.parts and path.suffix != ".pyc" and path.is_file():
                candidates.append((path, prefix + "/" + path.relative_to(directory).as_posix()))
    for name in ("index.html", "change-password.html", "backup-crypto.js", "icon.png", "qr-sub.png"):
        if (web / name).is_file():
            candidates.append((web / name, "web/" + name))
    candidates.append((project / "requirements.lock", "requirements.lock"))
    required = {"server/admin.py", "server/bootstrap_target.py", "deploy/install.sh", "deploy/upgrade.sh", "requirements.lock"}
    if not required.issubset({name for _, name in candidates}):
        raise InstallError("当前安装缺少完整后台发布资源，请先更新主控")
    with tarfile.open(fileobj=output, mode="w|gz") as archive:
        for path, name in sorted(candidates, key=lambda item: item[1]):
            if path.is_symlink() or not path.is_file():
                raise InstallError("发布资源不完整或包含符号链接")
            archive.add(path, arcname=name, recursive=False)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3 or sys.argv[1] != "bundle":
        raise SystemExit("usage: installations.py bundle SERVER_DIRECTORY")
    emit_bundle(sys.argv[2], sys.stdout.buffer)
