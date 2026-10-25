"""Read-only local subscription/session adapters; never return credentials or prompts."""
import base64
import concurrent.futures
import datetime as dt
import errno
import glob
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import time
import urllib.error
import urllib.request

HOME = Path.home()


def stamp(value=None):
    if value is None:
        value = time.time()
    if isinstance(value, str):
        return value
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text())


def tail_records(path, limit=2_000_000):
    with open(path, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - limit))
        if size > limit:
            f.readline()
        for line in f:
            try:
                yield json.loads(line)
            except (ValueError, UnicodeError):
                continue


def request_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=7) as response:
        return json.load(response)


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False


def process_identity(pid, expected):
    if not alive(pid):
        return False
    try:
        r = subprocess.run(['ps', '-p', str(int(pid)), '-o', 'comm='], capture_output=True,
                           text=True, timeout=2)
        if r.returncode:
            return None
        return expected.lower() in r.stdout.strip().lower()
    except (OSError, subprocess.TimeoutExpired):
        return None


def provider(name, identifier):
    return {'id': identifier, 'name': name, 'windows': [], 'source': 'unavailable',
            'status': 'unknown', 'error': None, 'updatedAt': None}


def safe_error(exc):
    # Exception strings from network/credential parsers may contain confidential data.
    if isinstance(exc, urllib.error.HTTPError):
        return '認証またはサービス応答エラー (HTTP %s)' % exc.code
    return '取得できません (%s)' % type(exc).__name__


def window(name, used, reset):
    return {'name': name, 'usedPercent': max(0, min(100, float(used))),
            'resetsAt': stamp(reset) if reset else None}


def codex():
    p = provider('Codex', 'codex')
    agents = []
    rates = None
    paths = []
    db = HOME / '.codex/state_5.sqlite'
    if db.exists():
        try:
            with sqlite3.connect('file:%s?mode=ro' % db, uri=True, timeout=1) as c:
                rows = c.execute('SELECT id,rollout_path,cwd,model,agent_nickname,agent_role,updated_at FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 50').fetchall()
            for sid, path, cwd, model, nickname, role, updated in rows:
                if not Path(path).is_file():
                    continue
                paths.append(path)
                if time.time() - max(updated, Path(path).stat().st_mtime) > 86400:
                    continue
                status, event_time = 'unknown', updated
                for record in tail_records(path):
                    payload = record.get('payload') or {}
                    if record.get('type') == 'turn_context':
                        model = payload.get('model') or model
                    if record.get('type') == 'event_msg':
                        if payload.get('type') == 'task_started':
                            status, event_time = 'running', record.get('timestamp')
                        elif payload.get('type') in ('task_complete', 'turn_aborted'):
                            status, event_time = 'idle', record.get('timestamp')
                # Task events are durable telemetry, not proof the process still exists.
                lock = HOME / '.codex/thread-writer-locks' / (sid + '.lock')
                live_lock = False
                if lock.exists():
                    try:
                        import fcntl
                        with lock.open('rb') as f:
                            try:
                                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                fcntl.flock(f, fcntl.LOCK_UN)
                            except BlockingIOError:
                                live_lock = True
                    except OSError:
                        pass
                if not live_lock:
                    if time.time() - Path(path).stat().st_mtime > 600:
                        continue
                    status = 'recent'
                agents.append({'id': sid, 'name': nickname or role or 'Codex', 'provider': 'codex',
                               'model': model or None, 'cwd': cwd, 'status': 'active' if status == 'running' else status,
                               'source': 'session task events + writer lock' if live_lock else 'session activity (inferred)',
                               'updatedAt': stamp(event_time), 'modelSource': 'session metadata', 'modelEvidence': 'セッションに記録されたモデル'})
        except (sqlite3.Error, OSError):
            pass
    try:
        a = read_json(HOME / '.codex/auth.json')['tokens']
        d = request_json('https://chatgpt.com/backend-api/wham/usage', {
            'Authorization': 'Bearer ' + a['access_token'], 'ChatGPT-Account-Id': a['account_id'],
            'User-Agent': 'agent-dashboard/1.0'})
        limits = d.get('rate_limit') or {}
        for key, name in [('primary_window', '5時間'), ('secondary_window', '週間')]:
            v = limits.get(key)
            if v:
                p['windows'].append(window(name, v['used_percent'], v.get('reset_at')))
        if not p['windows']:
            raise ValueError('No usage windows')
        p.update(source='OAuth usage API (非公開)', status='live', updatedAt=stamp())
    except Exception as exc:
        p['error'] = safe_error(exc)
        # Most recent emitted rate-limit event is an explicit cached fallback.
        latest = ''
        for path in paths[:12]:
            for record in tail_records(path):
                payload = record.get('payload') or {}
                if payload.get('type') == 'token_count' and payload.get('rate_limits'):
                    at = record.get('timestamp', '')
                    if at > latest:
                        rates, latest = payload['rate_limits'], at
        if rates:
            for key, name in [('primary', '5時間'), ('secondary', '週間')]:
                v = rates.get(key)
                if v:
                    p['windows'].append(window(name, v['used_percent'], v.get('resets_at')))
            expired = any(w['resetsAt'] and dt.datetime.fromisoformat(w['resetsAt']).timestamp() < time.time() for w in p['windows'])
            old = not latest or time.time() - dt.datetime.fromisoformat(latest.replace('Z', '+00:00')).timestamp() > 300
            p.update(source='session rate_limits cache', status='stale' if expired or old else 'cached', updatedAt=latest)
    return p, agents


def claude():
    p = provider('Claude Code', 'claude')
    agents = []
    for file in (HOME / '.claude/sessions').glob('*.json'):
        try:
            s = read_json(file)
            identity = process_identity(s.get('pid'), 'claude')
            if identity is False:
                continue
            sid = s.get('sessionId')
            cwd = s.get('cwd', '')
            model, model_at = None, None
            project = re.sub(r'[^a-zA-Z0-9]', '-', cwd)
            transcript = HOME / '.claude/projects' / project / (str(sid) + '.jsonl')
            if transcript.exists():
                for r in tail_records(transcript):
                    message = r.get('message') or {}
                    if r.get('type') == 'assistant' and message.get('model'):
                        model, model_at = message['model'], r.get('timestamp')
            status = {'idle': 'idle', 'running': 'running', 'busy': 'running'}.get(s.get('status'), 'started')
            if identity is None:
                status = 'unknown'
            agents.append({'id': sid, 'name': s.get('name') or 'Claude Code', 'provider': 'claude',
                           'model': model, 'modelUpdatedAt': model_at, 'modelSource': 'last assistant response' if model else None,
                           'modelEvidence': '最後に記録されたモデル' if model else None,
                           'cwd': cwd, 'status': status, 'source': 'session registry + process identity' if identity else 'session registry (process identity unverified)',
                           'updatedAt': stamp((s.get('statusUpdatedAt') or s.get('updatedAt') or file.stat().st_mtime * 1000) / 1000)})
        except (OSError, ValueError, TypeError):
            continue
    try:
        credentials = HOME / '.claude/.credentials.json'
        if credentials.exists():
            a = read_json(credentials)
        else:
            result = subprocess.run(['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                                    capture_output=True, text=True, timeout=4, check=True)
            a = json.loads(result.stdout)
        token = a['claudeAiOauth']['accessToken']
        d = request_json('https://api.anthropic.com/api/oauth/usage', {
            'Authorization': 'Bearer ' + token, 'anthropic-beta': 'oauth-2025-04-20',
            'User-Agent': 'agent-dashboard/1.0'})
        for key, name in [('five_hour', '5時間'), ('seven_day', '週間'), ('seven_day_sonnet', '週間 Sonnet'), ('seven_day_opus', '週間 Opus')]:
            v = d.get(key)
            if v and v.get('utilization') is not None:
                p['windows'].append(window(name, v['utilization'], v.get('resets_at')))
        if not p['windows']:
            raise ValueError('No usage windows')
        p.update(source='OAuth usage API (非公開)', status='live', updatedAt=stamp())
    except Exception as exc:
        p['error'] = safe_error(exc)
    return p, agents


def proto_fields(data):
    """Bounded protobuf wire reader, used only for local Antigravity quota cache."""
    def varint(offset):
        value = 0
        for shift in range(0, 70, 7):
            b = data[offset]
            offset += 1
            value |= (b & 127) << shift
            if b < 128:
                return value, offset
        raise ValueError('invalid wire')
    i, fields = 0, []
    while i < len(data):
        tag, i = varint(i)
        n, wire = tag >> 3, tag & 7
        if not n:
            raise ValueError('invalid tag')
        if wire == 0:
            value, i = varint(i)
        elif wire == 2:
            size, i = varint(i)
            if size > len(data) - i:
                raise ValueError('invalid size')
            value, i = data[i:i + size], i + size
        elif wire == 5:
            value = struct.unpack('<f', data[i:i + 4])[0]
            i += 4
        elif wire == 1:
            value = struct.unpack('<d', data[i:i + 8])[0]
            i += 8
        else:
            raise ValueError('unknown wire')
        fields.append((n, value))
    return fields


def quota_models(data, depth=0):
    if depth > 8:
        return []
    try:
        fields = proto_fields(data)
    except (ValueError, IndexError, struct.error):
        return []
    result = []
    values = dict(fields)
    label = values.get(1)
    if isinstance(label, bytes) and isinstance(values.get(15), bytes):
        try:
            label = label.decode()
            quota = dict(proto_fields(values[15]))
            fraction = quota.get(1)
            reset = dict(proto_fields(quota[2])).get(1) if isinstance(quota.get(2), bytes) else None
            if label.startswith(('Gemini ', 'Claude ', 'GPT-')) and isinstance(fraction, float) and 0 <= fraction <= 1:
                result.append(window(label, (1 - fraction) * 100, reset))
        except (UnicodeError, ValueError, IndexError, struct.error):
            pass
    for _, value in fields:
        if isinstance(value, bytes):
            result.extend(quota_models(value, depth + 1))
            # Unified state sync wraps each protobuf entry in a base64 string.
            if len(value) > 40 and re.fullmatch(rb'[A-Za-z0-9+/=]+', value):
                try:
                    result.extend(quota_models(base64.b64decode(value, validate=True), depth + 1))
                except ValueError:
                    pass
    return result


def antigravity_live():
    """Use the existing app's read-only loopback RPC; all CSRF values stay private."""
    processes = subprocess.run(['ps', '-axo', 'pid,comm'], capture_output=True, text=True, timeout=2)
    if processes.returncode:
        raise PermissionError('process inspection unavailable')
    servers = []
    for line in processes.stdout.splitlines():
        if 'language_server_macos' in line and 'antigravity' in line.lower():
            servers.append(int(line.strip().split(None, 1)[0]))
    for pid in servers[:2]:
        args = subprocess.run(['ps', '-p', str(pid), '-o', 'args='], capture_output=True, text=True, timeout=2).stdout
        match = re.search(r'--csrf_token(?:=|\s+)(\S+)', args)
        if not match:
            continue
        sockets = subprocess.run(['lsof', '-nP', '-a', '-p', str(pid), '-iTCP', '-sTCP:LISTEN'],
                                 capture_output=True, text=True, timeout=2).stdout
        for port in re.findall(r':(\d+)\s+\(LISTEN\)', sockets)[:3]:
            try:
                req = urllib.request.Request('http://127.0.0.1:' + port + '/exa.language_server_pb.LanguageServerService/GetUserStatus',
                                             data=b'{}', headers={'Content-Type': 'application/json', 'X-Codeium-Csrf-Token': match.group(1)})
                with urllib.request.urlopen(req, timeout=2) as response:
                    d = json.load(response)
                configs = d.get('userStatus', {}).get('cascadeModelConfigData', {}).get('clientModelConfigs', [])
                windows = []
                for config in configs:
                    quota = config.get('quotaInfo') or {}
                    remaining = quota.get('remainingFraction')
                    if isinstance(remaining, (int, float)) and 0 <= remaining <= 1:
                        windows.append(window(config.get('label') or 'モデル', (1 - remaining) * 100, quota.get('resetTime')))
                if windows:
                    return windows, pid
            except (OSError, ValueError):
                continue
    raise ValueError('no live language server quota')


def antigravity():
    p = provider('Antigravity', 'antigravity')
    agents = []
    try:
        windows, pid = antigravity_live()
        p.update(windows=windows, status='live', source='running app loopback GetUserStatus (非公開)', updatedAt=stamp(),
                 error='モデル別の利用枠。5時間・週間の区分は提供されていません。')
        agents.append({'id': 'antigravity-server-' + str(pid), 'name': 'Antigravity language server',
                       'provider': 'antigravity', 'model': None, 'cwd': None, 'status': 'started',
                       'source': 'live process identity (conversation/model unavailable)', 'updatedAt': stamp()})
    except Exception as exc:
        p['error'] = safe_error(exc)
    for app in ['Antigravity IDE', 'Antigravity']:
        if p['status'] == 'live':
            break
        db = HOME / 'Library/Application Support' / app / 'User/globalStorage/state.vscdb'
        if not db.exists():
            continue
        try:
            with sqlite3.connect('file:%s?mode=ro' % db, uri=True, timeout=1) as c:
                row = c.execute('SELECT value FROM ItemTable WHERE key=?', ('antigravityUnifiedStateSync.userStatus',)).fetchone()
            if row:
                windows = quota_models(base64.b64decode(row[0]))
                if windows:
                    p['windows'] = list({w['name']: w for w in windows}.values())
                    # No provider fetch timestamp is present. DB mtime is explicitly a proxy.
                    modified = max(f.stat().st_mtime for f in [db, Path(str(db) + '-wal')] if f.exists())
                    expired = any(w['resetsAt'] and dt.datetime.fromisoformat(w['resetsAt']).timestamp() < time.time() for w in p['windows'])
                    p.update(status='stale' if expired else 'cached', source=app + ' local protobuf cache (非公開)', updatedAt=None,
                             observedAt=stamp(modified),
                             error='古いモデル別キャッシュ（リセット時刻経過）。現在の残量は不明。' if expired else 'モデル別キャッシュ。使用量の取得時刻は不明。5時間・週間の区分は提供されていません。')
                    break
        except (OSError, sqlite3.Error, ValueError):
            continue
    for folder in ['antigravity-cli', 'antigravity']:
        db = HOME / '.gemini' / folder / 'conversation_summaries.db'
        if not db.exists():
            continue
        try:
            snapshot = False
            try:
                c = sqlite3.connect('file:%s?mode=ro' % db, uri=True, timeout=1)
                c.execute('SELECT 1 FROM conversation_summaries LIMIT 1')
            except sqlite3.Error:
                c = sqlite3.connect('file:%s?mode=ro&immutable=1' % db, uri=True, timeout=1)
                snapshot = True
            with c:
                rows = c.execute('SELECT conversation_id,workspace_uris,status,last_modified_time,agent_name,killed FROM conversation_summaries ORDER BY last_modified_time DESC LIMIT 15').fetchall()
            for sid, workspace, status, modified, name, killed in rows:
                if killed:
                    continue
                try:
                    at = dt.datetime.fromisoformat(modified.replace('Z', '+00:00')).timestamp()
                except (ValueError, AttributeError):
                    continue
                if time.time() - at > 600:
                    continue
                try:
                    uris = json.loads(workspace)
                    cwd = uris[0] if isinstance(uris, list) and uris else workspace
                except ValueError:
                    cwd = workspace
                agents.append({'id': sid, 'name': name or 'Antigravity', 'provider': 'antigravity', 'model': None,
                               'cwd': cwd, 'status': 'recent', 'source': 'conversation summary activity (inferred)' + (' [DB snapshot; WAL excluded]' if snapshot else ''),
                               'updatedAt': stamp(at)})
        except (OSError, sqlite3.Error):
            pass
    if not p['windows']:
        p['error'] = '対応するローカル使用量キャッシュがありません。'
    return p, agents


def collect():
    providers, agents = [], []
    def isolated(item):
        identifier, name, function = item
        try:
            return function()
        except Exception as exc:
            p = provider(name, identifier)
            p['error'] = safe_error(exc)
            return p, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(isolated, [('codex', 'Codex', codex), ('claude', 'Claude Code', claude),
                                           ('antigravity', 'Antigravity', antigravity)]))
    for p, a in results:
        providers.append(p)
        agents.extend(a)
    return {'providers': providers, 'agents': agents, 'updatedAt': stamp()}
