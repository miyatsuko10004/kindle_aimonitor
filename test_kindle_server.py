import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

import kindle_server as ks

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
SAMPLE = {
    'generatedAt': '2026-10-25T11:59:00+00:00',
    'providers': [
        {'id': 'codex', 'name': 'Codex', 'status': 'live',
         'windows': [{'name': '5時間', 'usedPercent': 42.4, 'resetsAt': '2026-10-25T14:30:00+00:00'}]},
        {'id': 'claude', 'name': 'Claude Code', 'status': 'unknown', 'windows': [], 'error': 'HTTP 401'},
    ],
    'agents': [{'provider': 'claude', 'status': 'active', 'model': 'claude-opus-5-5',
                'cwd': '/Users/someone/secret/project-x'}],
}


class RenderTest(unittest.TestCase):
    def test_renders_quota_and_reset(self):
        page = ks.render_page(SAMPLE, 'tok', 60, now=NOW)
        self.assertIn('42%', page)
        self.assertIn('あと2時間31分', page)
        self.assertIn('HTTP 401', page)
        self.assertNotIn('<script', page)

    def test_hides_full_path(self):
        page = ks.render_page(SAMPLE, 'tok', 60, now=NOW)
        self.assertIn('project-x', page)
        self.assertNotIn('/Users/someone', page)

    def test_escapes_html(self):
        data = dict(SAMPLE, agents=[{'provider': 'codex', 'model': '<b>x</b>', 'status': 'idle'}])
        page = ks.render_page(data, 'tok', 60, now=NOW)
        self.assertNotIn('<b>x</b>', page)

    def test_loading_message_before_first_collect(self):
        page = ks.render_page(None, 'tok', 60, now=NOW)
        self.assertIn('初回データを収集しています', page)

    def test_image_mode_has_no_refresh_and_keeps_status_bar_blank(self):
        page = ks.render_page(SAMPLE, '', 0, now=NOW, image_side='right')
        self.assertNotIn('http-equiv="refresh"', page)
        self.assertIn('padding-right', page)
        self.assertIn('電源ボタンで終了', page)

    def test_stale_quota_is_not_shown_as_current_zero(self):
        provider = {'id': 'antigravity', 'status': 'stale',
                    'windows': [{'name': 'Gemini', 'usedPercent': 0}]}
        result = ks.render_provider(provider, NOW)
        self.assertIn('現在の残量は不明', result)
        self.assertNotIn('0%', result)

    def test_antigravity_selects_highest_usage_without_averaging(self):
        provider = {'id': 'antigravity', 'status': 'live', 'windows': [
            {'name': 'Low', 'usedPercent': 20}, {'name': 'High', 'usedPercent': 90}]}
        result = ks.render_provider(provider, NOW)
        self.assertIn('gauge-value">90%', result)
        self.assertLess(result.index('High'), result.index('Low'))

    def test_nonfinite_gauge_is_unknown(self):
        for value in (float('nan'), float('inf'), None, True):
            self.assertIn('現在値は不明', ks.gauge(value, '5時間'))

    def test_remaining_past(self):
        self.assertEqual(ks.remaining('2026-10-25T11:00:00+00:00', NOW), 'リセット済み')


class AuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ks.Handler.token = 'secret-token'
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), ks.Handler)
        cls.base = 'http://127.0.0.1:%d' % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def get(self, path):
        return ks.OPENER.open(self.base + path, timeout=3)

    def test_rejects_missing_or_wrong_token(self):
        for path in ('/', '/?k=wrong'):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get(path)
            self.assertEqual(ctx.exception.code, 403)

    def test_serves_with_token(self):
        with mock.patch.object(ks, 'current_status', return_value=SAMPLE):
            for path in ('/?k=secret-token', '/t/secret-token'):
                body = self.get(path).read().decode()
                self.assertIn('Codex', body)
                self.assertIn('/t/secret-token', body)

    def test_image_endpoint(self):
        with mock.patch.object(ks, '_image', None):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get('/img/secret-token.png')
            self.assertEqual(ctx.exception.code, 503)
        with mock.patch.object(ks, '_image', b'\x89PNG fake'):
            response = self.get('/img/secret-token.png')
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertEqual(response.read(), b'\x89PNG fake')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get('/img/wrong.png')
            self.assertEqual(ctx.exception.code, 403)

    def test_rejects_wrong_path_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get('/t/wrong')
        self.assertEqual(ctx.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
