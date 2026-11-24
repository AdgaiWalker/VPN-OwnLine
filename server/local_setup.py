"""Loopback-only cross-platform local setup, update check, and blind credential vault."""
import argparse
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import http.client
import json
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socketserver
import threading
import urllib.parse
import webbrowser

from server import tencent_discovery
from server.nodekit import local_diag, runtime_paths, system_updater
from server.nodekit.capabilities import CapabilityContext, CapabilityError, CapabilityRegistry, RemotePanelClient
from server.nodekit.installations import InstallError
from server.nodekit.local_setup_guard import LocalSetupGuard
from server.nodekit.local_setup_session import LocalSetupSession
from server.nodekit.local_vault import BlindVault, VaultError
from server.nodekit.sshcheck.problem import Problem
from server.nodekit.topology_plan import assert_plan_has_no_raw_secrets, execute_topology_plan


def _lazy_check(body, allowed_targets=()):
    try:
        from server.nodekit.sshcheck.first_check import check as first_check
    except ModuleNotFoundError:
        raise InstallError('缺少本地 SSH 依赖（paramiko / bcrypt），请先按 requirements.lock 安装依赖。') from None
    return first_check(body, allowed_targets)


def _lazy_install(checked, source, on_progress=None):
    try:
        from server.nodekit.local_setup_runner import install as run_install
    except ModuleNotFoundError:
        raise InstallError('缺少本地 SSH 依赖（paramiko / bcrypt），请先按 requirements.lock 安装依赖。') from None
    return run_install(checked, source, on_progress=on_progress)

ROOT = runtime_paths.bundle_root()
TZ_CN = timezone(timedelta(hours=8))


def _default_state_path():
    override = os.environ.get('OWNLINE_LOCAL_STATE', '').strip()
    if override:
        return Path(override)
    return runtime_paths.writable_state_dir() / 'local_agent.json'


class _LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.server_address[1]


def create_server(
    port=0,
    session=None,
    *,
    vault=None,
    diag_log=None,
    update_checker=None,
    capability_registry=None,
    panel_client_factory=None,
):
    resolved_diag = Path(diag_log) if diag_log is not None else local_diag.default_log_path()

    def _emit(event, detail=None, severity=None):
        try:
            local_diag.emit_event(event, detail, log_path=resolved_diag, severity=severity)
        except Exception:
            pass

    session = session or LocalSetupSession(
        _lazy_check,
        lambda checked, report: _lazy_install(checked, ROOT, on_progress=report),
    )
    active_vault = vault or BlindVault(on_event=lambda ev, dt: _emit(ev, dt))
    checker = update_checker or system_updater.check_update
    capabilities = capability_registry or CapabilityRegistry.discover()
    client_factory = panel_client_factory or RemotePanelClient

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, value, content_type='application/json; charset=utf-8', cookie=False):
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header(
                'Content-Security-Policy',
                "default-src 'none'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            if cookie:
                self.send_header(
                    'Set-Cookie',
                    'ownline_setup=' + self.server.guard.token + '; HttpOnly; SameSite=Strict; Path=/',
                )
            with suppress(BrokenPipeError, ConnectionResetError):
                self.end_headers()
                self.wfile.write(data)

        def authorized(self, mutation=False, protected=False):
            token = ''
            try:
                cookie = SimpleCookie(self.headers.get('Cookie', ''))
                if 'ownline_setup' in cookie:
                    token = cookie['ownline_setup'].value
            except CookieError:
                pass
            return self.server.guard.allowed(
                self.client_address[0],
                self.headers.get('Host'),
                self.headers.get('Origin'),
                token,
                mutation,
                protected,
            )

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if not self.authorized(protected=path not in ('/', '/vault')):
                self.send(403, {'message': '本地会话校验失败，请从启动入口重新打开。'})
                return
            try:
                if path == '/':
                    self.send(200, (ROOT / 'web/local-setup.html').read_bytes(), 'text/html; charset=utf-8', cookie=True)
                elif path == '/vault':
                    self.send(200, (ROOT / 'web/local-vault.html').read_bytes(), 'text/html; charset=utf-8', cookie=True)
                elif path == '/api/status':
                    self.send(200, session.status())
                elif path == '/api/update':
                    force = (query.get('force') or ['0'])[0] in ('1', 'true', 'yes')
                    info = checker(force=force)
                    _emit(
                        'local_update_checked',
                        {
                            'ok': bool(info.get('ok')),
                            'has_update': bool(info.get('has_update')),
                            'current_version': info.get('current_version', ''),
                            'latest_version': info.get('latest_version', ''),
                        },
                    )
                    self.send(200, info)
                elif path == '/api/diag/events':
                    try:
                        limit = int((query.get('limit') or ['50'])[0])
                    except ValueError:
                        limit = 50
                    self.send(200, {'events': local_diag.read_recent_events(limit, log_path=resolved_diag)})
                elif path == '/api/vault/status':
                    req_id = (query.get('id') or [''])[0].strip()
                    if not req_id:
                        raise VaultError('VAULT_REQUEST_ID_REQUIRED', '缺少凭据请求编号。', 400)
                    self.send(200, self.server.vault.request_status(req_id))
                elif path == '/api/vault/handles':
                    self.send(200, {'handles': self.server.vault.list_handles()})
                elif path == '/api/capabilities':
                    self.send(200, {'capabilities': self.server.capabilities.list_specs()})
                else:
                    self.send(404, {'message': '接口不存在。'})
            except VaultError as exc:
                self.send(exc.status, {'code': exc.code, 'message': exc.message})

        def do_POST(self):
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            if not self.authorized(mutation=True):
                self.send(403, {'message': '请求来源不属于本地安装页面。'})
                return
            borrowed = None
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if not 0 <= length <= 150000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError()
                if path == '/api/check':
                    payload = body
                    if body.get('vault_handle'):
                        borrowed = self.server.vault.borrow(
                            str(body['vault_handle']).strip(),
                            expected_slot='ssh',
                        )
                        payload = dict(borrowed)
                        for safe_key in ('host', 'username', 'ssh_port', 'fingerprint'):
                            if safe_key in body and body[safe_key] not in (None, ''):
                                payload[safe_key] = body[safe_key]
                    _emit('ssh_check_started', {'host': payload.get('host', ''), 'using_vault': bool(borrowed)})
                    res = session.check(payload)
                    if res.get('check_token'):
                        _emit('ssh_check_passed', {'host': payload.get('host', '')})
                    else:
                        _emit('ssh_check_failed', {'host': payload.get('host', ''), 'reason': 'precheck_not_ready'})
                    self.send(200, res)
                elif path == '/api/tencent/instances':
                    if session.status()['state'] != 'idle':
                        raise InstallError('已有安装任务，请查看原任务状态')
                    if body.get('vault_handle'):
                        borrowed = self.server.vault.borrow(
                            str(body['vault_handle']).strip(),
                            expected_slot='tencent_api',
                        )
                        sid, skey = borrowed.get('secret_id'), borrowed.get('secret_key')
                    else:
                        sid, skey = body.get('secret_id'), body.get('secret_key')
                    _emit('tencent_lookup_started', {'product': body.get('product') or 'all', 'using_vault': bool(borrowed)})
                    res = tencent_discovery.discover_for_local_setup(sid, skey, product=body.get('product'))
                    _emit('tencent_lookup_done', {'count': len(res.get('instances') or [])})
                    self.send(200, res)
                elif path == '/api/install':
                    if body.get('confirm') is not True:
                        raise InstallError('请先确认安装目标')
                    session.start(str(body.get('check_token', '')))
                    _emit('install_started', {})
                    self.send(202, {'state': 'running'})
                elif path == '/api/vault/request':
                    slot = str(body.get('slot') or '').strip()
                    req = self.server.vault.create_request(
                        slot,
                        label=str(body.get('label') or ''),
                        target_hint=str(body.get('target_hint') or ''),
                        ttl=body.get('ttl'),
                    )
                    req['vault_url'] = (
                        self.server.guard.origin
                        + '/vault?req='
                        + urllib.parse.quote(req['request_id'], safe='')
                    )
                    self.send(201, req)
                elif path == '/api/vault/submit':
                    req_id = str(body.get('request_id') or '').strip()
                    if not req_id:
                        raise VaultError('VAULT_REQUEST_ID_REQUIRED', '缺少凭据请求编号。', 400)
                    res = self.server.vault.submit_request(req_id, body.get('payload'))
                    self.send(200, res)
                elif path == '/api/vault/cancel':
                    req_id = str(body.get('request_id') or '').strip()
                    if not req_id:
                        raise VaultError('VAULT_REQUEST_ID_REQUIRED', '缺少凭据请求编号。', 400)
                    self.send(200, self.server.vault.cancel_request(req_id))
                elif path == '/api/vault/clear':
                    handle = body.get('handle')
                    cleared = self.server.vault.clear(str(handle).strip() if handle else None)
                    self.send(200, {'cleared': cleared})
                elif path == '/api/capabilities/run':
                    cap_name = str(body.get('name') or '').strip()
                    if not cap_name:
                        raise CapabilityError('CAPABILITY_NAME_REQUIRED', '缺少能力模块名称。', 400)
                    params = body.get('params') if body.get('params') is not None else {}
                    if not isinstance(params, dict):
                        raise ValueError()
                    assert_plan_has_no_raw_secrets(params)
                    dry_run = bool(body.get('dry_run', False))
                    ctx = CapabilityContext(
                        vault=self.server.vault,
                        session=session,
                        emit_diag=_emit,
                        dry_run=dry_run,
                        panel_client_factory=self.server.panel_client_factory,
                    )
                    res = self.server.capabilities.execute(cap_name, params, ctx=ctx)
                    self.send(200, res)
                elif path == '/api/topology/apply':
                    plan = body.get('plan')
                    if plan is None:
                        raise ValueError()
                    dry_run = bool(body.get('dry_run', False))
                    res = execute_topology_plan(
                        plan,
                        registry=self.server.capabilities,
                        vault=self.server.vault,
                        session=session,
                        emit_diag=_emit,
                        dry_run=dry_run,
                        panel_client_factory=self.server.panel_client_factory,
                    )
                    self.send(200, res)
                elif path == '/api/quit':
                    if session.status()['state'] == 'running':
                        raise InstallError('安装正在进行，请保持启动窗口运行')
                    self.server.vault.clear()
                    _emit('local_ui_stopped', {})
                    self.send(200, {'message': '本地服务已关闭。'})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.send(404, {'message': '接口不存在。'})
            except CapabilityError as exc:
                payload = {'code': exc.code, 'message': exc.message}
                if exc.detail:
                    payload['detail'] = exc.detail
                self.send(exc.status, payload)
            except VaultError as exc:
                self.send(exc.status, {'code': exc.code, 'message': exc.message})
            except tencent_discovery.Problem as exc:
                _emit('tencent_lookup_failed', {'code': exc.code})
                self.send(exc.status, {'code': exc.code, 'message': exc.message})
            except Problem as exc:
                if exc.code == 'HOST_KEY_CONFIRMATION':
                    _emit('ssh_fingerprint_prompted', {'fingerprint': (exc.detail or {}).get('fingerprint', '')})
                else:
                    _emit('ssh_check_failed', {'code': exc.code})
                response = {'code': exc.code, 'message': exc.message}
                if exc.code == 'HOST_KEY_CONFIRMATION':
                    response['fingerprint'] = (exc.detail or {}).get('fingerprint')
                self.send(exc.status, response)
            except InstallError as exc:
                self.send(409, {'message': str(exc)})
            except (ValueError, TypeError):
                self.send(400, {'message': '请求内容无效。'})
            except Exception:
                _emit('ssh_check_failed', {'code': 'INTERNAL_ERROR'})
                self.send(500, {'message': '连接或检查未完成，请核对服务器信息。'})
            finally:
                if isinstance(borrowed, dict):
                    borrowed.clear()

    server = _LoopbackHTTPServer(('127.0.0.1', port), Handler)
    server.guard = LocalSetupGuard(server.server_port)
    server.vault = active_vault
    server.diag_log = resolved_diag
    server.update_checker = checker
    server.capabilities = capabilities
    server.panel_client_factory = client_factory
    server.emit_diag = _emit
    return server


def _write_state_file(state_path, server):
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        'pid': os.getpid(),
        'port': server.server_port,
        'origin': server.guard.origin,
        'token': server.guard.token,
        'started_at': datetime.now(TZ_CN).isoformat(timespec='seconds'),
    }
    raw = (json.dumps(data, ensure_ascii=False) + '\n').encode('utf-8')
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(raw)
    if os.name == 'posix':
        with suppress(OSError):
            os.chmod(path, 0o600)


def _remove_own_state_file(state_path):
    if not state_path:
        return
    path = Path(state_path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and data.get('pid') == os.getpid():
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _probe_running_daemon(state_path):
    path = Path(state_path)
    if not path.is_file():
        return None
    try:
        info = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(info, dict):
            return None
        origin = str(info.get('origin') or '').rstrip('/')
        token = str(info.get('token') or '')
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or not token:
            return None
        conn = http.client.HTTPConnection('127.0.0.1', parsed.port, timeout=1.5)
        try:
            conn.request(
                'GET',
                '/api/status',
                headers={'Host': parsed.netloc, 'Cookie': 'ownline_setup=' + token},
            )
            resp = conn.getresponse()
            resp.read(4096)
            if resp.status == 200:
                return info
        finally:
            conn.close()
    except Exception:
        return None
    return None


def main(argv=None, *, open_browser_fn=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--force-new', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--state-file', default=None)
    parser.add_argument('--diag-log', default=None)
    args = parser.parse_args(argv)
    open_fn = open_browser_fn or webbrowser.open
    state_path = Path(args.state_file) if args.state_file else _default_state_path()
    resolved_diag = Path(args.diag_log) if args.diag_log else local_diag.default_log_path()

    if not args.force_new:
        existing = _probe_running_daemon(state_path)
        if existing is not None:
            with suppress(Exception):
                local_diag.emit_event(
                    'fallback_ui_opened',
                    {'origin': existing['origin'], 'reattached': True},
                    log_path=resolved_diag,
                )
            print('已接管正在运行的本地安装服务：' + existing['origin'], flush=True)
            if not args.no_browser:
                open_fn(existing['origin'])
            return 0

    server = create_server(args.port, diag_log=resolved_diag)
    _write_state_file(state_path, server)
    server.emit_diag('local_ui_started', {'port': server.server_port, 'headless': bool(args.no_browser)})
    if not args.no_browser:
        server.emit_diag('fallback_ui_opened', {'origin': server.guard.origin, 'reattached': False})
    print('本地安装入口：' + server.guard.origin, flush=True)
    print('安装期间请保持此窗口运行；结束后可在网页点击“关闭本地服务”。', flush=True)
    if not args.no_browser:
        open_fn(server.guard.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.vault.clear()
        _remove_own_state_file(state_path)
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
