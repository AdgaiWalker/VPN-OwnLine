"""Loopback-only Mac installation entry. Optional read-only cloud discovery."""
import argparse
import json
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import webbrowser

from server.nodekit.installations import InstallError
from server.nodekit.local_setup_guard import LocalSetupGuard
from server.nodekit.local_setup_session import LocalSetupSession
from server.nodekit.local_setup_runner import install
from server.nodekit.sshcheck.first_check import check
from server.nodekit.sshcheck.problem import Problem
from server import tencent_discovery

ROOT = Path(__file__).resolve().parents[1]


def create_server(port=0, session=None):
    session = session or LocalSetupSession(check, lambda checked, report: install(checked, ROOT, on_progress=report))

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
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            if cookie:
                self.send_header('Set-Cookie', 'ownline_setup=' + self.server.guard.token + '; HttpOnly; SameSite=Strict; Path=/')
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
            return self.server.guard.allowed(self.client_address[0], self.headers.get('Host'),
                                             self.headers.get('Origin'), token, mutation, protected)

        def do_GET(self):
            if not self.authorized(protected=self.path != '/'):
                self.send(403, {'message': '本地会话校验失败，请从启动入口重新打开。'})
            elif self.path == '/':
                self.send(200, (ROOT / 'web/local-setup.html').read_bytes(), 'text/html; charset=utf-8', cookie=True)
            elif self.path == '/api/status':
                self.send(200, session.status())
            else:
                self.send(404, {'message': '接口不存在。'})

        def do_POST(self):
            if not self.authorized(mutation=True):
                self.send(403, {'message': '请求来源不属于本地安装页面。'})
                return
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if not 0 <= length <= 150000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError()
                if self.path == '/api/check':
                    self.send(200, session.check(body))
                elif self.path == '/api/tencent/instances':
                    if session.status()['state'] != 'idle':
                        raise InstallError('已有安装任务，请查看原任务状态')
                    self.send(200, tencent_discovery.discover_for_local_setup(
                        body.get('secret_id'), body.get('secret_key')))
                elif self.path == '/api/install':
                    if body.get('confirm') is not True:
                        raise InstallError('请先确认安装目标')
                    session.start(str(body.get('check_token', '')))
                    self.send(202, {'state': 'running'})
                elif self.path == '/api/quit':
                    if session.status()['state'] == 'running':
                        raise InstallError('安装正在进行，请保持启动窗口运行')
                    self.send(200, {'message': '本地服务已关闭。'})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.send(404, {'message': '接口不存在。'})
            except tencent_discovery.Problem as exc:
                self.send(exc.status, {'code': exc.code, 'message': exc.message})
            except Problem as exc:
                response = {'code': exc.code, 'message': exc.message}
                if exc.code == 'HOST_KEY_CONFIRMATION':
                    response['fingerprint'] = (exc.detail or {}).get('fingerprint')
                self.send(exc.status, response)
            except InstallError as exc:
                self.send(409, {'message': str(exc)})
            except (ValueError, TypeError):
                self.send(400, {'message': '请求内容无效。'})
            except Exception:
                self.send(500, {'message': '连接或检查未完成，请核对服务器信息。'})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.guard = LocalSetupGuard(server.server_port)
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    server = create_server(args.port)
    print('本地安装入口：' + server.guard.origin, flush=True)
    print('安装期间请保持此窗口运行；结束后可在网页点击“关闭本地服务”。', flush=True)
    if not args.no_browser:
        webbrowser.open(server.guard.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
