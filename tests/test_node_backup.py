import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import admin


class NodeBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.nodes = self.data / 'nodes.json'
        self.nodes.write_text(json.dumps([{'name': 'old', 'host': '198.51.100.1', 'port': 443}]))
        (self.data / 'settings.json').write_text(json.dumps({'sub_token': 'aaaabbbb'}))
        self.patches = [patch.object(admin, 'DATA', str(self.data)), patch.object(admin, 'NODES', str(self.nodes)),
                        patch.object(admin, 'render'), patch.object(admin.logger, 'log'),
                        patch.object(admin.subs_mod, 'in_subscription', return_value=False)]
        for p in self.patches:
            p.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), admin.H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def request(self, method, path, payload=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, None if payload is None else json.dumps(payload), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        content = json.loads(response.read())
        result = (response.status, dict(response.getheaders()), content)
        conn.close()
        return result

    def test_backup_no_cache_and_restore_subscription_token(self):
        status, headers, backup = self.request('GET', '/backup')
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Cache-Control'), 'no-store')
        self.assertEqual(backup['sub_token'], 'aaaabbbb')
        backup['nodes'][0]['name'] = 'restored'
        backup['sub_token'] = 'dddd1111'
        status, _, result = self.request('POST', '/restore', backup)
        self.assertEqual(status, 200)
        self.assertTrue(result['ok'])
        self.assertEqual(json.loads(self.nodes.read_text())[0]['name'], 'restored')
        self.assertEqual(json.loads((self.data / 'settings.json').read_text())['sub_token'], 'dddd1111')
        self.assertEqual(os.stat(self.data / 'settings.json').st_mode & 0o777, 0o600)

    def test_invalid_backup_never_partially_overwrites_nodes(self):
        original = self.nodes.read_text()
        backup = {'nodes': [{'name': 'valid', 'host': '198.51.100.2', 'port': 443}, {'name': 'invalid'}]}
        status, _, _ = self.request('POST', '/restore', backup)
        self.assertEqual(status, 400)
        self.assertEqual(self.nodes.read_text(), original)
        backup = {'nodes': [{'name': 'valid', 'host': '198.51.100.2', 'port': 443}], 'sub_token': 'invalid-token'}
        status, _, _ = self.request('POST', '/restore', backup)
        self.assertEqual(status, 400)
        self.assertEqual(self.nodes.read_text(), original)

    def test_partial_restore_reports_subscription_save_failure(self):
        backup = {'nodes': [{'name': 'new', 'host': '198.51.100.3', 'port': 443}], 'sub_token': 'ccccdddd'}
        with patch.object(admin, '_save_json', side_effect=OSError('disk full')):
            status, _, result = self.request('POST', '/restore', backup)
        self.assertEqual(status, 500)
        self.assertIn('节点配置已写入', result['error'])
        self.assertEqual(json.loads(self.nodes.read_text())[0]['name'], 'new')
        self.assertEqual(json.loads((self.data / 'settings.json').read_text())['sub_token'], 'aaaabbbb')

    def test_tencent_discovery_is_one_shot_and_does_not_persist_credentials(self):
        payload = {'secret_id': 'fixture-id', 'secret_key': 'fixture-key'}
        with patch.object(admin.tencent_discovery_mod, 'discover', return_value={'instances': [], 'incomplete_regions': []}) as discover:
            status, _, result = self.request('POST', '/tencent/instances', payload)
        self.assertEqual(status, 200)
        discover.assert_called_once_with('fixture-id', 'fixture-key')
        self.assertNotIn('fixture-key', json.dumps(result))
        for path in self.data.iterdir():
            if path.is_file():
                self.assertNotIn('fixture-key', path.read_text())


if __name__ == '__main__':
    unittest.main()
