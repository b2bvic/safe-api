import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from safe_api import CircuitBreakerTripped, SafeAPIClient, ScopeViolation


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return b'{"id": 1}'


class SafeAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1], prefix='.test-')
        self.addCleanup(self.temp.cleanup)

    def client(self, **options):
        return SafeAPIClient('https://api.example.com', log_dir=self.temp.name,
                             execute=False, **options)

    def test_dry_run_logs_without_network(self):
        client = self.client(allowed_endpoints=['/contacts'])
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            result = client.post('/contacts', {'name': 'Example'})
        self.assertTrue(result['dry_run'])
        self.assertEqual(client.log_tail()[0]['action'], 'DRY_RUN')

    def test_explicit_empty_allowlist_blocks_all_writes(self):
        with self.assertRaises(ScopeViolation):
            self.client(allowed_endpoints=[]).post('/contacts', {})

    def test_scope_blocks_query_paths_and_traversal(self):
        client = self.client(blocked_endpoints=['/billing'])
        for endpoint in ['/billing?x=1', '/contacts/../billing', '/contacts/%2e%2e/billing',
                         '//other.example/contacts', 'https://other.example/contacts',
                         '/contacts//1', '/contacts#fragment', '/contacts\\..\\billing',
                         '/contacts\n/1', '/contacts\x7f/1', '/contacts\x85/1']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ScopeViolation):
                client.post(endpoint, {})

    def test_allowlist_and_method_blocks_apply_to_record_paths(self):
        client = self.client(allowed_endpoints=['/contacts'],
                             blocked_methods={'/contacts': ['DELETE']})
        self.assertTrue(client.put('/contacts/1?view=full', {})['dry_run'])
        with self.assertRaises(ScopeViolation):
            client.delete('/contacts/1')
        with self.assertRaises(ScopeViolation):
            client.patch('/tasks/1', {})

    def test_duplicate_checker_skips_and_logs(self):
        client = self.client(dedup_checker=lambda *args: {'id': 1})
        with patch('urllib.request.urlopen', side_effect=AssertionError('network')):
            self.assertTrue(client.post('/contacts', {})['skipped'])
        self.assertEqual(client.log_tail()[0]['action'], 'SKIPPED_DUPLICATE')

    def test_execute_sends_one_request_and_logs_response(self):
        client = self.client(auth_header='Bearer synthetic')
        client.execute_mode = True
        with patch('urllib.request.urlopen', return_value=Response()) as send, patch('time.sleep'):
            self.assertEqual(client.post('/contacts', {'name': 'Example'}), {'id': 1})
        self.assertEqual(send.call_count, 1)
        request = send.call_args.args[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data), {'name': 'Example'})
        self.assertEqual(client.log_tail()[0]['response_status'], 200)

    def test_failures_trip_before_next_write_and_create_incident(self):
        client = self.client(max_failures=2)
        client.execute_mode = True
        error = urllib.error.HTTPError('https://api.example.com', 500, 'failure', {}, io.BytesIO(b'{}'))
        with patch('urllib.request.urlopen', side_effect=error) as send:
            client.post('/contacts', {})
            client.post('/contacts', {})
            with self.assertRaises(CircuitBreakerTripped):
                client.post('/contacts', {})
        self.assertEqual(send.call_count, 2)
        self.assertEqual([e['action'] for e in client.log_tail()], ['FAILED', 'FAILED'])
        self.assertEqual(len(list(Path(self.temp.name).glob('incident-*.json'))), 1)
        client.reset_breaker()
        client.execute_mode = False
        self.assertTrue(client.post('/contacts', {})['dry_run'])

    def test_rate_limit_trips_before_another_request(self):
        client = self.client(max_writes_per_minute=1)
        client.execute_mode = True
        with patch('urllib.request.urlopen', return_value=Response()) as send, patch('time.sleep'):
            client.post('/contacts', {})
            with self.assertRaises(CircuitBreakerTripped):
                client.post('/contacts', {})
        self.assertEqual(send.call_count, 1)


if __name__ == '__main__':
    unittest.main()
