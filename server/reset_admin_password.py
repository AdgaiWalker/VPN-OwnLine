#!/usr/bin/env python3
"""Reset only the standard, project-owned single-site Caddy administrator.

Run on the user's server in an interactive terminal: sudo python3 /opt/web/reset_admin_password.py
Custom/shared configurations are intentionally not supported.
"""

import base64
import fcntl
import getpass
import http.client
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import subprocess
import sys
import tempfile

CADDYFILE = Path('/etc/caddy/Caddyfile')
LOCKFILE = Path('/run/ownline-reset-admin.lock')
INITIAL_PASSWORD_MARKER = Path('/opt/web-data/.initial-password-required')
HASH = r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}'


def inspect_credentials(raw):
    """Accept only the exact generated single-site structure; never rewrite a shared Caddyfile."""
    if not re.match(r'\A# ownline-setup-job:[A-Za-z0-9_-]*\n', raw):
        raise ValueError('配置没有项目安装标记')
    # Ignore project comments and whitespace, not Caddyfile directives or tokens.
    lines = [' '.join(line.strip().split()) for line in raw.splitlines()
             if line.strip() and not line.strip().startswith('#')]
    template = [
        '(app) {', 'redir /p / 308', 'redir /p/* / 308',
        'handle /s/* {', 'reverse_proxy 127.0.0.1:8099', '}',
        '@blocked path /sub*', 'handle @blocked {', 'respond 404', '}',
        'handle_path /api/* {', 'basic_auth {', 'USER HASH', '}',
        'reverse_proxy 127.0.0.1:8099', '}',
        '@sensitive path /tc.json /nodes.json /retired-nodes-*.json',
        'handle @sensitive {', 'respond 404', '}',
        '@pubjson path /status.json /servers.json /usage.json /quota.json',
        'handle @pubjson {', 'basic_auth {', 'USER HASH', '}',
        'header Cache-Control "no-store"', 'root * /opt/web-data', 'file_server', '}',
        'handle {', 'basic_auth {', 'USER HASH', '}',
        'header Cache-Control "no-store"', 'root * /opt/web', 'file_server', '}', '}',
        ':80 {', 'redir https://DOMAIN:8443{uri} 308', '}',
        'https://DOMAIN:8443 {', 'TLS', 'import app', '}',
    ]
    initial_gate = '# ownline-managed-password-v1\n' in raw
    if initial_gate:
        blocked_end = template.index('handle_path /api/* {')
        template[blocked_end:blocked_end] = [
            'handle /change-password {', 'basic_auth {', 'USER HASH', '}',
            'root * /opt/web', 'rewrite * /change-password.html', 'file_server', '}',
            'handle /api/password/* {', 'basic_auth {', 'USER HASH', '}',
            'reverse_proxy 127.0.0.1:8099', '}',
        ]
        # The gate must apply to API, status JSON and ordinary static resources.
        for target in ('handle_path /api/* {', 'handle @pubjson {', 'handle {'):
            start = template.index(target)
            auth_end = template.index('}', start) + 1
            template[auth_end:auth_end] = ['forward_auth 127.0.0.1:8099 {', 'uri /password-gate', '}']
    user_hash_pairs = [m.groups() for line in lines if (m := re.fullmatch(r'([A-Za-z0-9_.-]{1,64}) (' + HASH + r')', line))]
    expected_matches = 5 if initial_gate else 3
    if len(user_hash_pairs) != expected_matches:
        raise ValueError('认证配置不符合受支持模板')
    usernames = {u for u, _ in user_hash_pairs}
    hashes = {h for _, h in user_hash_pairs}
    if len(usernames) != 1 or len(hashes) != 1:
        raise ValueError('认证配置不符合受支持模板')
    username = user_hash_pairs[0][0]
    hash_val = user_hash_pairs[0][1]
    domain_matches = [m.group(1) for line in lines if (m := re.fullmatch(
        r'https://([A-Za-z0-9.-]+):8443 \{', line))]
    if len(domain_matches) != 1:
        raise ValueError('管理地址不符合受支持模板')
    domain = domain_matches[0]
    normalized = []
    for line in lines:
        line = line.replace(hash_val, 'HASH').replace(username + ' HASH', 'USER HASH').replace('https://' + domain + ':8443', 'https://DOMAIN:8443')
        normalized.append(line)
    if 'tls internal' not in normalized:
        template.remove('TLS')
    else:
        normalized = ['TLS' if line == 'tls internal' else line for line in normalized]
    if normalized != template:
        raise ValueError('检测到自定义或共享 Caddy 配置，不做修改')
    return domain, username, hash_val


def inspect_config(raw):
    """Accept only the exact generated single-site structure; never rewrite a shared Caddyfile."""
    domain, _, hash_val = inspect_credentials(raw)
    return domain, hash_val


def replace_hash(raw, new_hash, new_user=None):
    domain, old_user, old_hash = inspect_credentials(raw)
    if not re.fullmatch(HASH, new_hash):
        raise ValueError('新密码哈希无效')
    target_user = old_user
    if new_user is not None:
        target_user = new_user.strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', target_user):
            raise ValueError('用户名格式无效，仅支持 1-64 位字母、数字、下划线、点或横线')
    new, count = re.subn(r'(?m)^([ \t]*)' + re.escape(old_user) + r'([ \t]+)' + re.escape(old_hash) + r'([ \t]*)$',
                         lambda match: match.group(1) + target_user + match.group(2) + new_hash + match.group(3), raw)
    expected = 5 if '# ownline-managed-password-v1\n' in raw else 3
    if count != expected or inspect_credentials(new) != (domain, target_user, new_hash):
        raise ValueError('新配置检查失败')
    return domain, new


def run_quiet(args, *, input_bytes=None):
    return subprocess.run(args, input=input_bytes, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, check=False, timeout=30)


def hash_password(password):
    result = run_quiet(['caddy', 'hash-password'], input_bytes=password.encode() + b'\n')
    result_hash = result.stdout.decode('ascii', errors='replace').strip()
    if result.returncode or not re.fullmatch(HASH, result_hash):
        raise RuntimeError('密码哈希生成失败')
    return result_hash


def local_login(domain, password, path='/', username='admin'):
    """Verify Caddy on loopback only; this is not an external TLS verification."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    def request(authorization=None):
        conn = http.client.HTTPSConnection(domain, 8443, context=context, timeout=8)
        # Connect only to loopback while sending the configured domain as TLS SNI.
        conn._create_connection = lambda _address, timeout, *args: socket.create_connection(
            ('127.0.0.1', 8443), timeout, *args)
        headers = {'Host': domain + ':8443'}
        if authorization:
            headers['Authorization'] = authorization
        try:
            conn.request('GET', path, headers=headers)
            response = conn.getresponse()
            response.read(1)
            return response.status
        finally:
            conn.close()
    authorization = 'Basic ' + base64.b64encode(((username or 'admin') + ':' + password).encode()).decode()
    return request() == 401 and request(authorization) == 200


def private_temp(path, content, original_stat):
    fd, name = tempfile.mkstemp(prefix='.ownline-caddy-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, stat.S_IMODE(original_stat.st_mode))
        os.chown(name, original_stat.st_uid, original_stat.st_gid)
        return Path(name)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def reset(path, password, username=None):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1:
        raise RuntimeError('Caddyfile 不是受支持的 root 所有普通文件')
    original = path.read_text(encoding='utf-8')
    domain, current_user, _ = inspect_credentials(original)
    target_user = username or current_user
    domain, candidate = replace_hash(original, hash_password(password), new_user=target_user)
    staged = private_temp(path, candidate, st)
    try:
        check = run_quiet(['caddy', 'validate', '--config', str(staged), '--adapter', 'caddyfile'])
        if check.returncode:
            raise RuntimeError('新配置未通过 Caddy 校验，原配置未修改')
        current = path.lstat()
        if (current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid,
            current.st_nlink, current.st_mtime_ns) != (st.st_dev, st.st_ino, st.st_mode,
            st.st_uid, st.st_gid, st.st_nlink, st.st_mtime_ns) or path.read_text(encoding='utf-8') != original:
            raise RuntimeError('配置已被其他操作修改，未执行重置')
        os.replace(staged, path)
        try:
            reload_result = run_quiet(['systemctl', 'reload', 'caddy'])
            probe = '/change-password' if '# ownline-managed-password-v1\n' in candidate else '/'
            if reload_result.returncode or not local_login(domain, password, probe, username=target_user):
                raise RuntimeError('重载或本机认证验证失败')
        except Exception as error:
            if path.read_text(encoding='utf-8') != candidate:
                raise RuntimeError('重载失败且配置被其他操作修改，请手动检查，不自动覆盖') from error
            rollback = private_temp(path, original, st)
            try:
                os.replace(rollback, path)
            finally:
                rollback.unlink(missing_ok=True)
            if run_quiet(['systemctl', 'reload', 'caddy']).returncode:
                raise RuntimeError('已还原原文件，但 Caddy 重载失败，请检查服务状态') from error
            raise RuntimeError('重载或本机认证失败，已还原原配置') from error
    finally:
        staged.unlink(missing_ok=True)


def main():
    if os.geteuid() != 0 or not sys.stdin.isatty():
        raise RuntimeError('请在服务器终端使用 sudo 交互运行，不支持通过管道输入密码')
    print('只修改长青管理网页密码；服务器 SSH 密码不会改变。')
    first = getpass.getpass('请输入新的管理密码（至少 12 个字符）：')
    second = getpass.getpass('再次输入新密码：')
    if first != second or len(first) < 12 or len(first.encode()) > 72 or any(c in first for c in '\r\n\x00'):
        raise RuntimeError('两次密码不一致，或密码长度不符合要求')
    with open(LOCKFILE, 'w', encoding='utf-8') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reset(CADDYFILE, first)
        INITIAL_PASSWORD_MARKER.unlink(missing_ok=True)
    print('管理密码已更新并通过本机认证验证。公网安全连接仍需单独验证。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('未完成：' + str(exc), file=sys.stderr)
        sys.exit(1)
