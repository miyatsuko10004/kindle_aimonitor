"""Agent board: who is working, waiting for an answer, or idle — and on which model.

Sources (all local, read-only, no network):
- herdr: panes running agents, with idle / working / blocked / done / unknown states.
- Claude Code session registry and Codex threads (collectors.py), for agents
  started outside herdr (agmsg app, desktop app, plain terminals).
- agmsg: team activity and messages to a human that have not been answered.
- An optional models.yaml (role -> tier -> model) fills in models that no
  session records, e.g. Antigravity. Those are marked as configured, not observed.

Message bodies are never read into the board; only who, where, and when.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import collectors

HOME = Path.home()
AGMSG_API = os.environ.get('KINDLE_AGMSG_API', str(HOME / '.agents/skills/agmsg/scripts/api.sh'))
MODELS_YAML = os.environ.get('KINDLE_MODELS_YAML', str(HOME / 'develop/neovista-git/consultingwork/hq/models.yaml'))
HUMANS = {'human', 'you'}
# Display order: what needs the human first.
ORDER = {'blocked': 0, 'working': 1, 'done': 2, 'idle': 3, 'unknown': 4}
LABELS = {'blocked': '回答待ち', 'working': '稼働中', 'done': '完了', 'idle': '待機中', 'unknown': '不明'}
KINDS = {'claude': 'Claude', 'claude-code': 'Claude', 'codex': 'Codex', 'agy': 'Antigravity',
         'antigravity': 'Antigravity', 'gemini': 'Gemini', 'grok': 'Grok'}
_since = {}  # (source, id) -> (status, first time this status was seen)


def run_json(cmd, timeout=8):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def run_jsonl(cmd, timeout=8):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def role_models(path=MODELS_YAML):
    """role -> model from a tiers/roles models.yaml, parsed without PyYAML."""
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return {}
    tiers, roles, section, role = {}, {}, None, None
    for line in lines:
        text = line.split('#', 1)[0].rstrip()
        if not text.strip():
            continue
        if not text.startswith(' '):
            section, role = text.rstrip(':'), None
            continue
        m = re.match(r'^  ([\w.-]+):\s*(.*)$', text)
        if m:
            if section == 'tiers' and m.group(2):
                tiers[m.group(1)] = m.group(2).strip()
            elif section == 'roles':
                role = m.group(1)
            continue
        m = re.match(r'^    tier:\s*([\w.-]+)', text)
        if m and section == 'roles' and role:
            roles[role] = m.group(1)
    return {r: tiers[t] for r, t in roles.items() if t in tiers}


def model_for_role(name, mapping):
    best = max((r for r in mapping if name == r or name.startswith(r + '-')), key=len, default=None)
    return mapping.get(best)


def claude_model(session_id):
    for path in glob.glob(str(HOME / '.claude/projects/*' / (session_id + '.jsonl'))):
        model = None
        for r in collectors.tail_records(path):
            message = r.get('message') or {}
            if r.get('type') == 'assistant' and message.get('model'):
                model = message['model']
        return model
    return None


MODEL_PATTERN = re.compile(r'\b((?:Gemini|Claude|GPT|Grok)[\w.\- ]{0,24}?(?:\d[\w.]*)(?: (?:Pro|Flash|Opus|Sonnet|Haiku|Mini|Lite))?(?: \((?:High|Medium|Low)\))?)', re.I)


def screen_model(pane_id):
    """Model name from the bottom lines of an agent's screen (Antigravity shows it
    in its footer). Only the matched model name is kept, never the screen text."""
    try:
        text = subprocess.run(['herdr', 'agent', 'read', pane_id, '--lines', '8'],
                              capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = MODEL_PATTERN.findall(text)
    return found[-1].strip() if found else None


def readable_name(name):
    # herdr auto-generates hex ids for unnamed agents; they mean nothing on a wall display.
    return '' if re.fullmatch(r'[0-9a-f]{16,}', name or '') else (name or '')


def herdr_entries():
    if not shutil.which('herdr'):
        return []
    workspaces = run_json(['herdr', 'workspace', 'list']) or {}
    labels = {w.get('workspace_id'): w.get('label') for w in (workspaces.get('result') or {}).get('workspaces') or []}
    agents = run_json(['herdr', 'agent', 'list']) or {}
    entries = []
    for a in (agents.get('result') or {}).get('agents') or []:
        session = (a.get('agent_session') or {}).get('value')
        entries.append({'source': 'herdr', 'id': a.get('pane_id') or session, 'session': session,
                        'place': labels.get(a.get('workspace_id')) or a.get('workspace_id') or '—',
                        'name': readable_name(a.get('name')), 'kind': a.get('agent') or '',
                        'status': a.get('agent_status') if a.get('agent_status') in ORDER else 'unknown',
                        'cwd': a.get('cwd'), 'model': None, 'model_note': None, 'since': None})
    return entries


def session_entries():
    entries = []
    for a in collectors.claude_sessions():
        entries.append({'source': 'claude', 'id': a.get('id'), 'session': a.get('id'),
                        'place': os.path.basename(str(a.get('cwd') or '').rstrip('/')) or '—',
                        'name': a.get('name') or '', 'kind': 'claude',
                        'status': {'running': 'working', 'idle': 'idle'}.get(a.get('status'), 'unknown'),
                        'cwd': a.get('cwd'), 'model': a.get('model'), 'model_note': None,
                        'since': a.get('updatedAt')})
    codex, _ = collectors.codex_sessions()
    for a in codex:
        entries.append({'source': 'codex', 'id': a.get('id'), 'session': a.get('id'),
                        'place': os.path.basename(str(a.get('cwd') or '').rstrip('/')) or '—',
                        'name': a.get('name') if a.get('name') != 'Codex' else '', 'kind': 'codex',
                        'status': {'active': 'working', 'idle': 'idle', 'recent': 'idle'}.get(a.get('status'), 'unknown'),
                        'cwd': a.get('cwd'), 'model': a.get('model'), 'model_note': None,
                        'since': a.get('updatedAt')})
    return entries


def merge(herdr, sessions, roles):
    """herdr knows 'blocked'; session records know the model. Join them by session id."""
    by_session = {e['session']: e for e in sessions if e.get('session')}
    used = set()
    for e in herdr:
        s = by_session.get(e.get('session'))
        if not s and not e.get('session'):
            # herdr does not record a session id for every agent (e.g. Codex):
            # fall back to the same agent kind in the same directory.
            kind = 'claude' if e['kind'] in ('claude', 'claude-code') else e['kind']
            s = next((x for x in sessions if x['kind'] == kind and x.get('cwd') == e.get('cwd')
                      and x.get('session') not in used), None)
        if s:
            used.add(s['session'])
            e['model'] = s.get('model')
            e['name'] = e['name'] or s.get('name') or ''
        if not e['model'] and e['kind'] in ('claude', 'claude-code') and e.get('session'):
            e['model'] = claude_model(e['session'])
        if not e['model'] and e.get('id'):
            e['model'] = screen_model(e['id'])
    rows = herdr + [s for s in sessions if s.get('session') not in used]
    for e in rows:
        if not e['model']:
            configured = model_for_role(e.get('name') or '', roles)
            if configured:
                e['model'], e['model_note'] = configured, '設定'
    return rows


def track_since(rows, now):
    seen = set()
    for e in rows:
        key = (e['source'], e['id'])
        seen.add(key)
        previous = _since.get(key)
        if previous and previous[0] == e['status']:
            e['since'] = previous[1]
        else:
            # A recorded change time is better than "first seen by this server".
            start = collectors_time(e.get('since')) if not previous else None
            _since[key] = (e['status'], start or now)
            e['since'] = _since[key][1]
    for key in list(_since):
        if key not in seen:
            del _since[key]


def collectors_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def agmsg_summary(api=AGMSG_API, limit=40):
    """Per team: last activity, and messages to a human with no later reply. Bodies are dropped."""
    if not os.path.exists(api):
        return {'teams': [], 'pending': []}
    teams, pending = [], []
    for t in run_jsonl([api, 'get', 'teams']):
        name = t.get('name')
        if not name:
            continue
        humans = set(HUMANS)
        for m in run_jsonl([api, 'get', 'teams', name, 'members']):
            if 'agmsg-app' in (m.get('types') or []):
                humans.add(m.get('name'))
        messages = run_jsonl([api, 'get', 'teams', name, 'messages', '--limit', str(limit)])
        if not messages:
            continue
        last = messages[-1].get('at')
        teams.append({'team': name, 'last': last, 'count': len(messages)})
        for i, m in enumerate(messages):
            if m.get('to') in humans and m.get('from') not in humans:
                answered = any(n.get('from') == m.get('to') and n.get('to') == m.get('from') for n in messages[i + 1:])
                if not answered:
                    pending.append({'team': name, 'from': m.get('from'), 'to': m.get('to'), 'at': m.get('at')})
    teams.sort(key=lambda x: x['last'] or '', reverse=True)
    # Questions older than a few days were answered elsewhere or abandoned.
    cutoff = time.time() - 3 * 86400
    grouped = {}
    for p in pending:
        if (collectors_time(p['at']) or 0) < cutoff:
            continue
        key = (p['team'], p['from'], p['to'])
        g = grouped.setdefault(key, dict(p, count=0))
        g['count'] += 1
        g['at'] = max(g['at'] or '', p['at'] or '')
    pending = sorted(grouped.values(), key=lambda x: x['at'] or '', reverse=True)
    return {'teams': teams, 'pending': pending}


def collect_board():
    now = time.time()
    rows = merge(herdr_entries(), session_entries(), role_models())
    track_since(rows, now)
    rows.sort(key=lambda e: (ORDER.get(e['status'], 9), -(e.get('since') or 0)))
    return {'rows': rows, 'agmsg': agmsg_summary(), 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'herdr': shutil.which('herdr') is not None}


def elapsed(since, now):
    if not since:
        return '—'
    minutes = max(0, int((now - since) // 60))
    if minutes < 60:
        return '%d分' % minutes
    if minutes < 1440:
        return '%d時間' % (minutes // 60)
    return '%d日' % (minutes // 1440)


def ago(value, now):
    t = collectors_time(value)
    return elapsed(t, now) + '前' if t else '—'


def esc(value):
    import html
    return html.escape(str(value), quote=True)


def render_board(board, token='', refresh=300, now=None, image_side=None, max_rows=12):
    """Board HTML for the browser, or (image_side='left'/'right') for the eips image."""
    from kindle_server import SCALE, STATUS_BAR, WEEKDAYS
    now = now or time.time()
    local = datetime.fromtimestamp(now).astimezone()
    link = '/t/%s/agents' % esc(token)
    body = []
    if not board:
        body.append('<div class="alert">初回データを収集しています。しばらくお待ちください。</div>')
    else:
        rows = board.get('rows') or []
        counts = {k: sum(1 for r in rows if r['status'] == k) for k in ORDER}
        cells = []
        for key in ('blocked', 'working', 'done', 'idle'):
            hot = ' hot' if key == 'blocked' and counts[key] else ''
            cells.append('<td class="sum%s"><div class="n">%d</div><div class="l">%s</div></td>' % (hot, counts[key], LABELS[key]))
        body.append('<table class="summary"><tr>%s</tr></table>' % ''.join(cells))
        if not board.get('herdr'):
            body.append('<div class="note">herdr が見つからないため、回答待ちは判定できません</div>')
        trs = []
        for r in rows[:max_rows]:
            model = esc(r.get('model') or '不明') + (' <span class="tag">設定</span>' if r.get('model_note') else '')
            trs.append('<tr class="%s"><td class="st">%s</td><td>%s</td><td>%s</td><td>%s</td><td class="model">%s</td><td class="el">%s</td></tr>'
                       % (r['status'], LABELS.get(r['status'], '不明'), esc(r.get('place') or '—'), esc(r.get('name') or '—'),
                          esc(KINDS.get(r.get('kind'), r.get('kind') or '—')), model, elapsed(r.get('since'), now)))
        if not trs:
            trs.append('<tr><td colspan="6" class="empty">確認できるエージェントはありません</td></tr>')
        more = len(rows) - max_rows
        body.append('<table class="board"><tr><th>状態</th><th>場所</th><th>名前</th><th>種類</th><th>モデル</th><th>経過</th></tr>%s</table>%s'
                    % (''.join(trs), '<div class="note">ほか %d 件</div>' % more if more > 0 else ''))
        ag = board.get('agmsg') or {}
        pend = ''.join('<tr><td>%s</td><td>%s → %s%s</td><td class="el">%s</td></tr>'
                       % (esc(p['team']), esc(p['from']), esc(p['to']),
                          ' (%d件)' % p['count'] if p.get('count', 1) > 1 else '', ago(p['at'], now))
                       for p in ag.get('pending', [])[:4])
        teams = ''.join('<tr><td>%s</td><td class="el">%s</td></tr>' % (esc(t['team']), ago(t['last'], now))
                        for t in ag.get('teams', [])[:4])
        body.append('<table class="lower"><tr><td class="half"><h2>agmsg 人間への問い合わせ</h2><table class="mini">%s</table></td>'
                    '<td class="half"><h2>agmsg 最近動いたチーム</h2><table class="mini">%s</table></td></tr></table>'
                    % (pend or '<tr><td>未返信の問い合わせはありません</td></tr>', teams or '<tr><td>—</td></tr>'))
    updated = local.strftime('%H:%M') if not board else datetime.fromisoformat(board['generatedAt']).astimezone().strftime('%H:%M')
    if image_side:
        head = '<style>body{padding-%s:%dpx !important}</style>' % (image_side, round(STATUS_BAR / SCALE) + 12)
        foot = '収集 %s ・ 電源ボタンで終了' % updated
    else:
        head = '<meta http-equiv="refresh" content="%d;url=%s">' % (refresh, link)
        foot = '収集 %s ・ %d秒ごとに自動更新' % (updated, refresh)
    date = '%d月%d日(%s)' % (local.month, local.day, WEEKDAYS[local.weekday()])
    return BOARD_PAGE % {'head': head, 'link': link, 'date': date, 'now': local.strftime('%H:%M'),
                         'body': ''.join(body), 'foot': foot}


BOARD_PAGE = '''<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
%(head)s
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Board</title>
<style>
*{box-sizing:border-box;-webkit-box-sizing:border-box}
html,body{margin:0;padding:0;background:#fff;color:#000}
body{font-family:"Helvetica Neue",Arial,"Hiragino Kaku Gothic ProN",sans-serif;font-size:15px;padding:10px 18px}
a{color:#000;text-decoration:none}
table{border-collapse:collapse;width:100%%}
td,th{padding:0;vertical-align:middle}
.top{border-bottom:3px solid #000;margin-bottom:8px}
.top td{padding:0 0 8px}
.date{font-size:19px;font-weight:bold;width:32%%}
.title{text-align:center;font-size:13px;letter-spacing:3px;font-weight:bold}
.upd{text-align:right;width:32%%}
.upd a{font-size:34px;font-weight:bold;line-height:1;letter-spacing:-1px}
.summary{table-layout:fixed;margin-bottom:8px}
.sum{border:2px solid #000;text-align:center;padding:4px 0}
.sum+.sum{border-left:0}
.sum .n{font-size:30px;font-weight:bold;line-height:1}
.sum .l{font-size:12px;margin-top:2px}
.sum.hot{background:#000;color:#fff}
.board{table-layout:fixed}
.board th{text-align:left;font-size:10px;font-weight:normal;border-bottom:1px solid #000;padding:3px 5px}
.board th:nth-child(1){width:11%%}.board th:nth-child(2){width:20%%}.board th:nth-child(3){width:22%%}
.board th:nth-child(4){width:12%%}.board th:nth-child(5){width:25%%}.board th:nth-child(6){width:10%%}
.board td{font-size:13px;padding:3px 5px;border-bottom:1px solid #bbb;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.board tr.blocked td{background:#000;color:#fff;font-weight:bold}
.board tr.working .st{font-weight:bold}
.board tr.idle td,.board tr.unknown td{color:#444}
.model{font-family:monospace;font-size:12px !important}
.tag{font-family:sans-serif;font-size:9px;border:1px solid currentColor;padding:0 2px}
.el{text-align:right;white-space:nowrap}
.empty{text-align:center;color:#444}
.lower{table-layout:fixed;margin-top:8px}
.half{vertical-align:top;width:50%%;padding-right:12px}
.half+.half{padding:0 0 0 12px;border-left:1px solid #999}
h2{font-size:13px;margin:0 0 3px;border-bottom:2px solid #000;padding-bottom:3px}
.mini td{font-size:12px;padding:2px 0;border-bottom:1px solid #ddd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.note{font-size:11px;margin-top:4px}
.alert{border:2px solid #000;padding:8px;margin-bottom:10px;font-size:15px}
.foot{margin-top:4px;font-size:10px;text-align:right}
</style></head><body>
<table class="top"><tr><td class="date">%(date)s</td><td class="title">AGENT BOARD</td>
<td class="upd"><a href="%(link)s">%(now)s</a></td></tr></table>
%(body)s
<div class="foot">%(foot)s</div>
</body></html>
'''
