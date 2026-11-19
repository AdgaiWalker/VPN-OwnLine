import json
import unittest
from unittest.mock import MagicMock, patch

from server import tencent_discovery
from server.providers import tc3


class TencentDiscoveryTests(unittest.TestCase):
    def test_reads_both_products_and_filters_nonpublic_addresses(self):
        def query(action, payload, secret_id, secret_key, region, *, service, direct):
            self.assertEqual((secret_id, secret_key), ('fixture-id', 'fixture-key'))
            self.assertTrue(direct)
            if action == 'DescribeRegions':
                if service == 'region':
                    self.assertEqual(payload, {'Product': 'cvm'})
                    self.assertIsNone(region)
                else:
                    self.assertEqual(service, 'lighthouse')
                return {'Response': {'RegionSet': [{'Region': 'ap-tokyo', 'RegionName': '东京'}]}}
            self.assertEqual(action, 'DescribeInstances')
            self.assertEqual(region, 'ap-tokyo')
            address = 'PublicIpAddresses' if service == 'cvm' else 'PublicAddresses'
            return {'Response': {'TotalCount': 2, 'InstanceSet': [
                {'InstanceId': service, 'InstanceName': service, address: ['10.0.0.1', '8.8.8.8']},
                {'InstanceId': 'private-only', address: ['192.168.1.3', '::1']},
            ]}}

        with patch.object(tc3, 'call', side_effect=query):
            result = tencent_discovery.discover_for_local_setup('fixture-id', 'fixture-key')
        self.assertEqual({item['id'] for item in result['instances']}, {'cvm', 'lighthouse'})
        self.assertTrue(all(item['ip'] == '8.8.8.8' for item in result['instances']))
        self.assertEqual(result['incomplete_regions'], [])
        self.assertNotIn('fixture-key', json.dumps(result))

    def test_cvm_filter_does_not_call_lighthouse(self):
        responses = [
            {'Response': {'RegionSet': [{'Region': 'ap-tokyo'}]}},
            {'Response': {'InstanceSet': [{'InstanceId': 'ins-fixture', 'PublicIpAddresses': ['8.8.8.8']}]}},
        ]
        with patch.object(tc3, 'call', side_effect=responses) as query:
            result = tencent_discovery.discover_for_local_setup('fixture-id', 'fixture-key', product='cvm')
        self.assertEqual([call.kwargs['service'] for call in query.call_args_list], ['region', 'cvm'])
        self.assertEqual([item['id'] for item in result['instances']], ['ins-fixture'])
        self.assertEqual(result['incomplete_regions'], [])

    def test_missing_product_permissions_keep_the_other_products_results(self):
        def query(action, payload, secret_id, secret_key, region, *, service, direct):
            if service != 'lighthouse':
                return {'Response': {'Error': {'Code': 'UnauthorizedOperation', 'Message': 'fixture-secret'}}}
            if action == 'DescribeRegions':
                return {'Response': {'RegionSet': [{'Region': 'ap-tokyo'}]}}
            return {'Response': {'InstanceSet': [{'InstanceId': 'lhins-test', 'PublicAddresses': ['8.8.8.8']}]}}

        with patch.object(tc3, 'call', side_effect=query):
            result = tencent_discovery.discover_for_local_setup('fixture-id', 'fixture-key')
        self.assertEqual(result['instances'][0]['id'], 'lhins-test')
        self.assertEqual(result['incomplete_regions'], ['云服务器 CVM'])
        self.assertNotIn('fixture-secret', json.dumps(result))

    def test_local_signed_request_binds_endpoint_and_blocks_proxy_and_redirect(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"Response":{}}'
        with patch.object(tc3.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = response
            tc3.call('DescribeInstances', {}, 'fixture-id', 'fixture-key', 'ap-tokyo', service='cvm', direct=True)
        proxy, redirect = build.call_args.args
        self.assertEqual(proxy.proxies, {})
        self.assertIsNone(redirect.redirect_request(None, None, 307, '', {}, 'https://other.test'))
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://cvm.tencentcloudapi.com')
        self.assertIn('/cvm/tc3_request', request.get_header('Authorization'))
        self.assertEqual(request.get_header('X-tc-version'), '2017-03-12')
        self.assertNotIn('fixture-key', request.get_header('Authorization'))


if __name__ == '__main__':
    unittest.main()
