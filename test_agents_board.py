import tempfile
import time
import unittest
from unittest import mock

import agents_board as ab

MODELS_YAML = '''tiers:
  judgment: claude-opus-5.5
  multimodal: gemini-3.8-flash   # comment
roles:
  pj-em:
    layer: pj
    tier: multimodal
  hq-orchestrator:
    tier: judgment
'''


def row(**kw):
    base = {'source': 'herdr', 'id': 'p1', 'session': None, 'place': 'ws', 'name': '', 'kind': 'agy',
            'status': 'idle', 'cwd': '/w', 'model': None, 'model_note': None, 'since': None}
    base.update(kw)
    return base


class RoleModelTest(unittest.TestCase):
    def test_parses_tiers_and_roles(self):
        with tempfile.NamedTemporaryFile('w', suffix='.yaml') as f:
            f.write(MODELS_YAML)
            f.flush()
            roles = ab.role_models(f.name)
        self.assertEqual(roles, {'pj-em': 'gemini-3.8-flash', 'hq-orchestrator': 'claude-opus-5.5'})
        self.assertEqual(ab.model_for_role('pj-em-fujitsu-bank', roles), 'gemini-3.8-flash')
        self.assertIsNone(ab.model_for_role('pj-emx', roles))

    def test_missing_file_is_empty(self):
        self.assertEqual(ab.role_models('/nonexistent/models.yaml'), {})


class MergeTest(unittest.TestCase):
    @mock.patch.object(ab, 'screen_model', return_value=None)
    def test_joins_by_session_and_keeps_blocked(self, _):
        herdr = [row(session='s1', kind='claude', status='blocked')]
        sessions = [row(source='claude', id='s1', session='s1', kind='claude', status='working',
                        model='claude-opus-5-5', name='review')]
        rows = ab.merge(herdr, sessions, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'blocked')
        self.assertEqual(rows[0]['model'], 'claude-opus-5-5')
        self.assertEqual(rows[0]['name'], 'review')

    @mock.patch.object(ab, 'screen_model', return_value=None)
    def test_joins_codex_by_directory_when_no_session(self, _):
        herdr = [row(kind='codex', cwd='/repo')]
        sessions = [row(source='codex', id='c1', session='c1', kind='codex', cwd='/repo', model='gpt-6-astra')]
        rows = ab.merge(herdr, sessions, {})
        self.assertEqual([r['model'] for r in rows], ['gpt-6-astra'])

    @mock.patch.object(ab, 'screen_model', return_value=None)
    def test_configured_model_is_marked(self, _):
        rows = ab.merge([row(name='pj-em-x')], [], {'pj-em': 'gemini-3.8-flash'})
        self.assertEqual((rows[0]['model'], rows[0]['model_note']), ('gemini-3.8-flash', '設定'))

    def test_hex_names_are_hidden(self):
        self.assertEqual(ab.readable_name('af1b47b42bda122f508f0aa00'), '')
        self.assertEqual(ab.readable_name('em-jcn-ai'), 'em-jcn-ai')


class ModelPatternTest(unittest.TestCase):
    def test_footer_model(self):
        self.assertEqual(ab.MODEL_PATTERN.findall('│ ~/w  Gemini 3.8 Flash  ctx 12% │')[-1].strip(), 'Gemini 3.8 Flash')


class AgmsgTest(unittest.TestCase):
    def test_groups_unanswered_and_drops_bodies(self):
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        messages = [
            {'from': 'agy', 'to': 'you', 'at': now, 'body': 'secret plan A'},
            {'from': 'agy', 'to': 'you', 'at': now, 'body': 'secret plan B'},
            {'from': 'bot', 'to': 'human', 'at': now, 'body': 'q'},
            {'from': 'human', 'to': 'bot', 'at': now, 'body': 'a'},
        ]

        def fake(cmd, timeout=8):
            if cmd[-1] == 'teams':
                return [{'name': 'team1'}]
            if 'members' in cmd:
                return [{'name': 'you', 'types': ['agmsg-app']}]
            return messages
        with mock.patch.object(ab, 'run_jsonl', side_effect=fake), mock.patch('os.path.exists', return_value=True):
            summary = ab.agmsg_summary('/fake/api.sh')
        self.assertEqual(len(summary['pending']), 1)
        self.assertEqual(summary['pending'][0]['count'], 2)
        self.assertNotIn('body', summary['pending'][0])


class RenderTest(unittest.TestCase):
    def test_board_html(self):
        now = time.time()
        board = {'generatedAt': '2026-10-27T00:00:00+00:00', 'herdr': True,
                 'rows': [row(status='blocked', place='<b>pj</b>', model='m', since=now - 600),
                          row(id='p2', status='working')],
                 'agmsg': {'teams': [], 'pending': []}}
        page = ab.render_board(board, 'tok', 300, now=now, image_side='right')
        self.assertIn('回答待ち', page)
        self.assertIn('class="sum hot"', page)
        self.assertIn('10分', page)
        self.assertNotIn('<b>pj</b>', page)
        self.assertNotIn('http-equiv="refresh"', page)

    def test_loading(self):
        self.assertIn('初回データ', ab.render_board(None, 'tok', 300))


if __name__ == '__main__':
    unittest.main()
