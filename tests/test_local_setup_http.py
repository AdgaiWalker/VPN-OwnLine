import http.client
import json
import threading
import unittest
from contextlib import closing
from socketserver import _SocketWriter
from unittest.mock import patch

from server.local_setup import create_server
from server import tencent_discovery


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

    def test_disconnected_client_does_not_trigger_a_second_response(self):
        headers = {'Cookie': self.cookie, 'Origin': self.server.guard.origin, 'Content-Type': 'application/json'}
        with patch.object(_SocketWriter, 'write', side_effect=BrokenPipeError) as write:
            with closing(http.client.HTTPConnection('127.0.0.1', self.server.server_port)) as connection:
                connection.request('POST', '/api/check', body='{}', headers=headers)
                with self.assertRaises(http.client.RemoteDisconnected):
                    connection.getresponse()
            write.assert_called_once()
        self.assertTrue(self.session.checked)

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

    def test_tencent_query_uses_local_session_and_does_not_return_keys(self):
        endpoint = '/api/tencent/instances'
        headers = {'Origin': self.server.guard.origin, 'Content-Type': 'application/json'}
        body = json.dumps({'secret_id': 'fixture-id', 'secret_key': 'fixture-key', 'product': 'cvm'})
        result = {'instances': [{'ip': '8.8.8.8'}], 'incomplete_regions': []}
        with patch.object(tencent_discovery, 'discover_for_local_setup', return_value=result) as discover:
            self.assertEqual(self.request('POST', endpoint, headers, body)[0], 403)
            headers['Cookie'] = self.cookie
            headers['Origin'] = 'https://other.test'
            self.assertEqual(self.request('POST', endpoint, headers, body)[0], 403)
            discover.assert_not_called()
            headers['Origin'] = self.server.guard.origin
            status, response_headers, response = self.request('POST', endpoint, headers, body)
            self.assertEqual(status, 200)
            self.assertEqual(dict(response_headers)['Cache-Control'], 'no-store')
            self.assertEqual(json.loads(response), result)
            discover.assert_called_once_with('fixture-id', 'fixture-key', product='cvm')
        self.assertFalse(self.session.checked)
        self.assertEqual(json.loads(self.request('GET', '/api/status', headers)[2]), {'state': 'idle'})

    def test_tencent_query_has_safe_errors_for_missing_credentials(self):
        headers = {'Cookie': self.cookie, 'Origin': self.server.guard.origin, 'Content-Type': 'application/json'}
        with patch.object(tencent_discovery.tc3, 'call') as cloud:
            code, _, body = self.request('POST', '/api/tencent/instances', headers, '{"secret_id":"fixture-id"}')
        self.assertEqual(code, 400)
        self.assertEqual(json.loads(body)['code'], 'TENCENT_CREDENTIALS_REQUIRED')
        self.assertNotIn(b'fixture-id', body)
        cloud.assert_not_called()

    def test_tencent_query_rejects_an_unsupported_product_before_network_access(self):
        headers = {'Cookie': self.cookie, 'Origin': self.server.guard.origin, 'Content-Type': 'application/json'}
        with patch.object(tencent_discovery.tc3, 'call') as cloud:
            payload = json.dumps({'secret_id': 'fixture-id', 'secret_key': 'fixture-key', 'product': ['cvm']})
            code, _, body = self.request('POST', '/api/tencent/instances', headers, payload)
            self.assertEqual(code, 400)
            self.assertEqual(json.loads(body)['code'], 'TENCENT_PRODUCT_UNSUPPORTED')
            cloud.assert_not_called()


if __name__ == '__main__':
    unittest.main()
