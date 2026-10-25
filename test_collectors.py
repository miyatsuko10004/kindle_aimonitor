import unittest
from unittest.mock import patch
import collectors

class CollectorTests(unittest.TestCase):
    def test_errors_never_echo_tokens(self):
        self.assertNotIn('secret-token', collectors.safe_error(ValueError('secret-token')))

    def test_malformed_protobuf_is_ignored(self):
        for value in (b'\xff', b'\x0a\xff', b'\x00', b'garbage'):
            self.assertEqual(collectors.quota_models(value), [])

    def test_missing_windows_are_unknown(self):
        p = collectors.provider('Test', 'test')
        self.assertEqual(p['windows'], [])
        self.assertEqual(p['status'], 'unknown')
        self.assertIsNone(p['updatedAt'])

    def test_provider_failure_does_not_hide_others(self):
        def successful(name, identifier):
            return collectors.provider(name, identifier), []
        with patch.object(collectors, 'codex', side_effect=RuntimeError('private-secret')), \
             patch.object(collectors, 'claude', return_value=successful('Claude Code', 'claude')), \
             patch.object(collectors, 'antigravity', return_value=successful('Antigravity', 'antigravity')):
            result = collectors.collect()
        self.assertEqual(len(result['providers']), 3)
        codex = next(p for p in result['providers'] if p['id'] == 'codex')
        self.assertIsNotNone(codex['error'])
        self.assertNotIn('private-secret', codex['error'])

if __name__ == '__main__':
    unittest.main()
