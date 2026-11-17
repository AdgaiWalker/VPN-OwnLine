import http.client
import threading
import unittest

from server.local_setup import create_server


class Session:
    def __init__(self):
        self.checked = False
    def status(self):
        return {'state': 'idle'}
    def check(self, body):
        self.checked = True
        return {'result': {'ready_for_install': False, 'message': '未安装'}}


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.server = create_server(session=self.session)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.host = self.server.guard.host
        self.cookie = 'ownline_setup=' + self.server.guard.token

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, headers=None, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, response.getheaders(), response.read()
        connection.close()
        return result

    def test_page_and_session_gate(self):
        status, headers, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'OwnLine', body)
        self.assertIn('HttpOnly', dict(headers)['Set-Cookie'])
        self.assertEqual(self.request('GET', '/api/status')[0], 403)
        self.assertEqual(self.request('GET', '/api/status', {'Cookie': self.cookie})[0], 200)
        self.assertEqual(self.request('GET', '/', {'Host': 'evil.example'})[0], 403)

    def test_cross_origin_never_reaches_ssh_check(self):
        headers = {'Cookie': self.cookie, 'Origin': 'https://evil.example', 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', '/api/check', headers, '{}')[0], 403)
        self.assertFalse(self.session.checked)
        headers['Origin'] = self.server.guard.origin
        self.assertEqual(self.request('POST', '/api/check', headers, '{}')[0], 200)
        self.assertTrue(self.session.checked)

    def test_invalid_body_and_unknown_route(self):
        headers = {'Cookie': self.cookie, 'Origin': self.server.guard.origin, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', '/api/check', headers, '[]')[0], 400)
        self.assertEqual(self.request('POST', '/api/unknown', headers, '{}')[0], 404)


if __name__ == '__main__':
    unittest.main()
