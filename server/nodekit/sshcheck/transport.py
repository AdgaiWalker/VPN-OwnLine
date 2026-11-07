"""One SSH implementation for passwords and in-memory keys; no agent/askpass layer."""

import base64
import hashlib
import io
import ipaddress
import json
import re
import socket
import time

import paramiko

from .problem import Problem


def fingerprint(key):
    return "SHA256:" + base64.b64encode(
        hashlib.sha256(key.asbytes()).digest()
    ).decode().rstrip("=")


def normalize(body, allowed_targets=()):
    host = str(body.get("host", "")).strip().lower().rstrip(".")
    if len(host) > 253 or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host):
        raise Problem("INVALID_HOST", "请输入公网 IPv4 或服务器域名。")
    try:
        port = int(body.get("ssh_port", 22))
    except (ValueError, TypeError):
        raise Problem("INVALID_PORT", "SSH 端口必须为 1–65535。")
    if not 1 <= port <= 65535:
        raise Problem("INVALID_PORT", "SSH 端口必须为 1–65535。")
    user = str(body.get("username", "root")).strip()
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,31}", user):
        raise Problem("INVALID_USER", "请输入有效的服务器用户名。")
    try:
        addresses = sorted(
            {
                x[4][0]
                for x in socket.getaddrinfo(
                    host, port, socket.AF_INET, socket.SOCK_STREAM
                )
            }
        )
    except OSError:
        raise Problem("DNS_FAILED", "无法解析服务器地址。") from None
    if not addresses or any(
        not ipaddress.ip_address(x).is_global and x not in allowed_targets
        for x in addresses
    ):
        raise Problem(
            "TARGET_NOT_ALLOWED",
            "此安装入口只允许公网目标；隔离测试目标需由入口管理员预先配置。",
            403,
        )
    pin = str(body.get("fingerprint", ""))
    if pin and not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", pin):
        raise Problem("INVALID_FINGERPRINT", "服务器指纹格式不正确。")
    return {
        "host": host,
        "address": addresses[0],
        "ssh_port": port,
        "username": user,
        "fingerprint": pin,
        "target_key": f"{addresses[0]}:{port}",
    }


def credentials(body):
    password, key, phrase = (
        str(body.get(k) or "") for k in ("password", "private_key", "passphrase")
    )
    if len(password) > 4096 or len(key) > 65536 or len(phrase) > 4096:
        raise Problem("CREDENTIAL_TOO_LARGE", "登录信息超过允许大小。")
    if bool(password) == bool(key):
        raise Problem("AUTH_REQUIRED", "请选择密码或私钥中的一种登录方式。")
    return {"password": password, "private_key": key, "passphrase": phrase}


class PinPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        actual = fingerprint(key)
        if not self.expected:
            raise Problem(
                "HOST_KEY_CONFIRMATION",
                "首次连接，请通过云控制台等可信途径核对服务器指纹。",
                409,
                {"fingerprint": actual},
            )
        if actual != self.expected:
            raise Problem(
                "HOST_KEY_CHANGED", "服务器指纹与已确认结果不同，请重新核对。", 409
            )


class SSH:
    def __init__(self, target, secret):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(PinPolicy(target["fingerprint"]))
        key = None
        if secret.get("private_key"):
            for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
                try:
                    key = cls.from_private_key(
                        io.StringIO(secret["private_key"]),
                        password=secret.get("passphrase") or None,
                    )
                    break
                except (paramiko.SSHException, ValueError):
                    pass
            if key is None:
                raise Problem("INVALID_KEY", "私钥或私钥口令不正确。")
        sock = None
        try:
            # Address was resolved/validated before connecting; no second DNS resolution here.
            sock = socket.create_connection(
                (target["address"], target["ssh_port"]), timeout=10
            )
            self.client.connect(
                target["host"],
                port=target["ssh_port"],
                username=target["username"],
                password=secret.get("password") or None,
                pkey=key,
                sock=sock,
                allow_agent=False,
                look_for_keys=False,
                timeout=10,
                banner_timeout=10,
                auth_timeout=10,
            )
        except Problem:
            if sock:
                sock.close()
            self.client.close()
            raise
        except paramiko.AuthenticationException:
            if sock:
                sock.close()
            self.client.close()
            raise Problem(
                "SSH_AUTH_FAILED", "SSH 登录失败，请核对用户名、密码或私钥。"
            ) from None
        except (OSError, paramiko.SSHException):
            if sock:
                sock.close()
            self.client.close()
            raise Problem(
                "SSH_UNAVAILABLE", "无法连接 SSH，请检查端口、网络和服务器状态。", 503
            ) from None
        self.host_key = self.client.get_transport().get_remote_server_key()
        self.fingerprint = fingerprint(self.host_key)
        self.client.get_transport().set_keepalive(15)

    def close(self):
        self.client.close()

    def run(self, command, data=b"", timeout=30):
        channel = self.client.get_transport().open_session(timeout=10)
        channel.settimeout(1)
        try:
            channel.exec_command(command)
            if data:
                channel.sendall(data)
            channel.shutdown_write()
            out, err = bytearray(), bytearray()
            deadline = time.monotonic() + timeout
            while True:
                if channel.recv_ready():
                    out.extend(channel.recv(65536))
                if channel.recv_stderr_ready():
                    err.extend(channel.recv_stderr(65536))
                if len(out) + len(err) > 2_000_000:
                    raise Problem("REMOTE_OUTPUT_LIMIT", "目标返回的数据超过限制。")
                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                    and not channel.recv_stderr_ready()
                ):
                    return channel.recv_exit_status(), bytes(out), bytes(err)
                if time.monotonic() > deadline:
                    raise Problem("SSH_TIMEOUT", "目标响应超时，请复查原任务。", 503)
                time.sleep(0.02)
        finally:
            channel.close()

    def python(self, source, payload=None, timeout=30):
        import shlex

        command = "python3 -c " + shlex.quote(source)
        code, out, _ = self.run(
            command,
            json.dumps(payload).encode() if payload is not None else b"",
            timeout,
        )
        if code:
            raise Problem(
                "REMOTE_CHECK_FAILED", "目标检查未完成，请核对权限与 Python 环境。"
            )
        try:
            return json.loads(out)
        except ValueError:
            raise Problem(
                "REMOTE_RESPONSE_INVALID", "目标返回的检查结果无效。"
            ) from None
