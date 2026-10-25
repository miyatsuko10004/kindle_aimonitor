#!/usr/bin/env python3
"""E-ink friendly AI agent usage dashboard for an old Kindle on the LAN.

Collects subscription usage and local agent sessions itself (collectors.py) and
renders plain server-side HTML: no JavaScript, no gradients, black and white only,
so the Kindle "Experimental Browser" (old WebKit) can show it. Access needs a token.
No third-party dependencies.
"""
import argparse
import hmac
import math
import html
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / '.kindle_token'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_lock = threading.Lock()
_snapshot = None
_error = None
NAMES = {'codex': 'Codex', 'claude': 'Claude Code', 'claude-code': 'Claude Code', 'antigravity': 'Antigravity'}
STATES = {'running': '起動中', 'started': '起動中', 'active': '処理中', 'busy': '処理中', 'idle': '待機中',
          'waiting': '待機中', 'recent': '最近活動', 'stopped': '停止', 'unknown': '不明'}
WEEKDAYS = '月火水木金土日'
MAX_AGENTS = 8
CHROME = os.environ.get('KINDLE_CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
GRAY_PROFILE = '/System/Library/ColorSync/Profiles/Generic Gray Profile.icc'
# Kindle Paperwhite 4 panel, portrait. The dashboard is drawn landscape and rotated.
SCREEN_W, SCREEN_H = 1072, 1448
SCALE = 1.65
# The Kindle status bar (clock, battery) keeps redrawing the top of the portrait
# screen, so that strip of the image is left blank.
STATUS_BAR = 70
_image = None


def load_token():
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_urlsafe(12)
    TOKEN_FILE.write_text(token)
    os.chmod(TOKEN_FILE, 0o600)
    return token


def refresh_loop(interval, rotate):
    global _snapshot, _error, _image
    from collectors import collect
    while True:
        try:
            data = collect()
            data['generatedAt'] = datetime.now(timezone.utc).isoformat()
            with _lock:
                _snapshot, _error = data, None
        except Exception:
            with _lock:
                _error = '情報の取得に失敗しました。次回の更新で再試行します。'
        try:
            png = render_image(current_status(), rotate)
            with _lock:
                _image = png
        except (OSError, subprocess.SubprocessError) as exc:
            print('image render failed: %s' % exc, flush=True)
        time.sleep(interval)


def render_image(data, rotate):
    """Screenshot the image-mode page with headless Chrome, rotate it for a
    landscape Kindle and convert it to 8-bit grayscale for eips."""
    if not os.path.exists(CHROME):
        raise OSError('Chrome not found: ' + CHROME)
    width, height = round(SCREEN_H / SCALE), round(SCREEN_W / SCALE)
    with tempfile.TemporaryDirectory(prefix='kindle_aimonitor_') as tmp:
        page, shot = os.path.join(tmp, 'dash.html'), os.path.join(tmp, 'dash.png')
        with open(page, 'w', encoding='utf-8') as f:
            f.write(render_page(data, '', 0, image_side='right' if rotate == 270 else 'left'))
        subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
                        '--user-data-dir=' + os.path.join(tmp, 'profile'),
                        '--window-size=%d,%d' % (width, height), '--force-device-scale-factor=%s' % SCALE,
                        '--screenshot=' + shot, 'file://' + page],
                       check=True, capture_output=True, timeout=60)
        subprocess.run(['sips', '-r', str(rotate), '-m', GRAY_PROFILE, shot],
                       check=True, capture_output=True, timeout=30)
        # Chrome may round the size by a pixel; eips wants the exact panel size.
        subprocess.run(['sips', '-z', str(SCREEN_H), str(SCREEN_W), shot],
                       check=True, capture_output=True, timeout=30)
        with open(shot, 'rb') as f:
            return f.read()


def current_status():
    with _lock:
        data = dict(_snapshot) if _snapshot else None
        if data is not None and _error:
            data['error'] = _error
        return data


def parse_time(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, timezone.utc)
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, OverflowError, OSError):
        return None


def hhmm(value):
    d = parse_time(value)
    return d.astimezone().strftime('%H:%M') if d else '—'


def remaining(value, now):
    d = parse_time(value)
    if not d:
        return 'リセット不明'
    minutes = int((d - now).total_seconds() // 60) + 1
    if minutes <= 0:
        return 'リセット済み'
    days, hours, mins = minutes // 1440, minutes % 1440 // 60, minutes % 60
    if days:
        return 'あと%d日%d時間' % (days, hours)
    if hours:
        return 'あと%d時間%d分' % (hours, mins)
    return 'あと%d分' % mins


def esc(value):
    return html.escape(str(value), quote=True)


def bar(percent):
    width = max(0, min(100, percent))
    return ('<div class="track"><div class="fill" style="width:%d%%"></div></div>' % round(width))


def valid_percent(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def gauge(percent, label):
    valid = valid_percent(percent)
    value = max(0, min(100, percent)) if valid else 0
    pct = '%d%%' % round(value) if valid else '—'
    arc = ('<circle cx="85" cy="85" r="70" fill="none" stroke="#000" stroke-width="10" '
           'stroke-dasharray="%.2f 439.83" transform="rotate(-90 85 85)"/>' % (439.83 * value / 100)) if valid else ''
    return ('<div class="gauge"><svg viewBox="0 0 170 170" aria-hidden="true">'
            '<circle cx="85" cy="85" r="70" fill="none" stroke="#ccc" stroke-width="10"/>%s</svg>'
            '<div class="gauge-text"><div class="gauge-label">%s</div><div class="gauge-value">%s</div>'
            '<div class="gauge-label">%s</div></div></div>'
            % (arc, esc(label), pct, '使用率' if valid else '現在値は不明'))


def render_provider(p, now):
    name = p.get('name') or NAMES.get(p.get('id'), p.get('id') or '不明')
    status = p.get('status')
    windows = p.get('windows') or []
    known = status in ('live', 'ok', 'available', 'success')
    badge = '取得済み' if known else ('前回値' if windows else '取得不可')
    out = ['<div class="card"><div class="pname">%s</div><div class="badge">%s</div>' % (esc(name), badge)]
    if not windows or not known:
        out.append(gauge(None, '利用枠'))
        out.append('<div class="note">%s</div>' % esc('前回値のため現在の残量は不明' if windows else p.get('error') or '利用枠を取得できていません'))
        if p.get('updatedAt'):
            out.append('<div class="note">前回確認 %s</div>' % hhmm(p['updatedAt']))
        return ''.join(out) + '</div>'
    if p.get('id') == 'antigravity':
        # 異なる利用枠を平均せず、使用率が最も高いモデルを表示する。
        windows = sorted(windows, key=lambda w: w.get('usedPercent') if valid_percent(w.get('usedPercent')) else -1, reverse=True)
    else:
        windows = sorted(windows, key=lambda w: 0 if w.get('name') == '5時間' else 1)
    primary = windows[0]
    out.append(gauge(primary.get('usedPercent'), primary.get('name') or '利用枠'))
    reset = remaining(primary.get('resetsAt'), now)
    out.append('<div class="gauge-reset">%s</div>' % esc('リセット ' + reset if reset.startswith('あと') else reset))
    if p.get('id') == 'antigravity':
        out.append('<div class="note">使用率が高いモデルから表示</div>')
    for w in windows[1:2]:
        used = w.get('usedPercent')
        valid = valid_percent(used)
        pct = '%d%%' % round(max(0, min(100, used))) if valid else '—'
        out.append('<div class="secondary"><table><tr><td class="wname">%s</td><td class="pct">%s</td></tr></table>%s'
                   '<div class="reset">%s</div></div>'
                   % (esc(w.get('name') or '利用枠'), pct, bar(used) if valid else '', esc(remaining(w.get('resetsAt'), now))))
    if len(windows) > 2:
        out.append('<div class="note">ほか %d 枠</div>' % (len(windows) - 2))
    if p.get('error'):
        out.append('<div class="note">%s</div>' % esc(p['error']))
    return ''.join(out) + '</div>'


def render_agents(agents, limit=MAX_AGENTS):
    if not agents:
        return '<div class="note">確認できるエージェントはありません</div>'
    order = {'active': 0, 'busy': 0, 'running': 1, 'started': 1, 'recent': 2}
    agents = sorted(agents, key=lambda a: order.get(a.get('status'), 3))
    rows = []
    for a in agents[:limit]:
        active = a.get('status') in ('active', 'busy', 'running')
        # Show only the last path component: full paths stay on the Mac.
        cwd = os.path.basename(str(a.get('cwd') or '').rstrip('/')) or '—'
        rows.append('<tr><td>%s%s</td><td>%s</td><td class="model">%s</td><td>%s</td></tr>'
                    % ('● ' if active else '○ ', esc(NAMES.get(a.get('provider'), a.get('provider') or '不明')),
                       esc(cwd), esc(a.get('model') or '不明'), esc(STATES.get(a.get('status'), a.get('status') or '不明'))))
    more = len(agents) - limit
    tail = '<div class="note">ほか %d 件</div>' % more if more > 0 else ''
    return '<table class="agents"><tr><th>サービス</th><th>ディレクトリ</th><th>モデル</th><th>状態</th></tr>%s</table>%s' % (''.join(rows), tail)


def render_page(data, token, refresh, now=None, image_side=None):
    """HTML for the browser, or (image_side='left'/'right') for the eips image,
    where that side is kept blank for the Kindle status bar."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone()
    date = '%d月%d日(%s)' % (local.month, local.day, WEEKDAYS[local.weekday()])
    link = '/t/' + esc(token)
    body = []
    if not data:
        body.append('<div class="alert">初回データを収集しています。しばらくお待ちください。</div>')
    else:
        if data.get('error'):
            body.append('<div class="alert">%s</div>' % esc(data['error']))
        providers = {p.get('id'): p for p in data.get('providers') or []}
        if 'claude-code' in providers and 'claude' not in providers:
            providers['claude'] = providers['claude-code']
        cards = [render_provider(providers.get(i) or {'id': i, 'name': NAMES[i]}, now)
                 for i in ('codex', 'claude', 'antigravity')]
        body.append('<table class="grid"><tr><td class="col">%s</td><td class="col">%s</td><td class="col">%s</td></tr></table>'
                    % (cards[0], cards[1], cards[2]))
        agents = data.get('agents') or []
        body.append('<h2>エージェント <span class="count">%d件</span></h2>%s' % (len(agents), render_agents(agents, limit=3 if image_side else MAX_AGENTS)))
    updated = hhmm(data.get('generatedAt')) if data else '—'
    if image_side:
        head = '<style>body{padding-%s:%dpx !important}</style>' % (image_side, round(STATUS_BAR / SCALE) + 12)
        foot = '収集 %s ・ 1分ごとに更新 ・ 電源ボタンで終了' % updated
    else:
        head = '<meta http-equiv="refresh" content="%d;url=%s">' % (refresh, link)
        foot = '収集 %s ・ %d秒ごとに自動更新 ・ 時刻をタップで再読込' % (updated, refresh)
    return PAGE % {'head': head, 'link': link, 'date': date, 'now': local.strftime('%H:%M'),
                   'foot': foot, 'body': ''.join(body)}


PAGE = '''<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
%(head)s
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Monitor</title>
<style>
*{box-sizing:border-box;-webkit-box-sizing:border-box}
html,body{margin:0;padding:0;background:#fff;color:#000}
body{font-family:"Helvetica Neue",Arial,"Hiragino Kaku Gothic ProN",sans-serif;font-size:17px;padding:10px 18px}
a{color:#000;text-decoration:none}
table{border-collapse:collapse;width:100%%}
td,th{padding:0;vertical-align:middle}
.top{border-bottom:3px solid #000;margin-bottom:8px}
.top td{padding:0 0 10px}
.date{font-size:19px;font-weight:bold;width:32%%}
.title{text-align:center;font-size:13px;letter-spacing:3px;font-weight:bold}
.upd{text-align:right;width:32%%}
.upd a{display:inline-block;font-size:34px;font-weight:bold;line-height:1;letter-spacing:-1px}
.grid{table-layout:fixed;margin-bottom:10px}
.grid .col{vertical-align:top;width:33.33%%;padding:0 12px;border-right:1px solid #999}
.grid .col:first-child{padding-left:0}
.grid .col:last-child{padding-right:0;border-right:0}
.card{padding:3px 0}
.pname{font-size:23px;font-weight:bold;letter-spacing:-.5px}
.badge{font-size:11px;margin-top:4px}
.gauge{width:140px;height:140px;position:relative;margin:8px auto}
.gauge svg{width:140px;height:140px;display:block}
.gauge-text{position:absolute;top:31px;left:12px;width:116px;text-align:center}
.gauge-label{max-width:100px;margin:auto;word-wrap:break-word;font-size:11px;line-height:14px;overflow-wrap:break-word}
.gauge-value{font-size:36px;font-weight:bold;line-height:40px;letter-spacing:-2px}
.gauge-reset{text-align:center;font-size:12px;margin-bottom:6px}
.secondary{margin-top:6px}
.wname{font-size:12px;word-wrap:break-word}
.pct{font-size:20px;font-weight:bold;text-align:right;white-space:nowrap;padding-left:6px}
.reset{font-size:11px;text-align:right;margin-top:3px}
.track{height:7px;background:#ccc;margin-top:4px}
.fill{height:100%%;background:#000}
.note{font-size:11px;margin-top:5px;overflow-wrap:break-word;word-wrap:break-word}
.alert{border:2px solid #000;padding:8px;margin-bottom:10px;font-size:15px}
h2{font-size:17px;margin:2px 0 0;border-bottom:2px solid #000;padding:0 0 6px}
.count{font-size:12px;font-weight:normal;margin-left:8px}
.agents{table-layout:fixed;width:100%%}
.agents th{text-align:left;font-size:10px;font-weight:normal;border-bottom:1px solid #000;padding:5px 6px}
.agents th:first-child{width:21%%}
.agents th:nth-child(2){width:29%%}
.agents th:nth-child(3){width:36%%}
.agents th:last-child{width:14%%}
.agents td{font-size:12px;padding:3px 6px;border-bottom:1px solid #bbb;overflow-wrap:break-word;word-wrap:break-word}
.model{font-family:monospace;font-size:11px !important}
.foot{margin-top:4px;font-size:10px;text-align:right}
@media (max-width:700px){body{padding:12px}.grid .col{display:block;width:100%%;padding:14px 0;border-right:0;border-bottom:1px solid #999}.date{font-size:15px}.title{font-size:10px;letter-spacing:1px}.upd a{font-size:28px}}
</style></head><body>
<table class="top"><tr><td class="date">%(date)s</td><td class="title">AI MONITOR</td>
<td class="upd"><a href="%(link)s">%(now)s</a></td></tr></table>
%(body)s
<div class="foot">%(foot)s</div>
</body></html>
'''


class Handler(BaseHTTPRequestHandler):
    token = ''
    refresh = 60

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/health':
            return self.respond(b'ok', 'text/plain')
        # The token goes in the path (/t/<token>): the Kindle's app:// launcher
        # mangles URLs that carry their own query string. ?k= stays for old bookmarks.
        if url.path.startswith('/img/') and url.path.endswith('.png'):
            if not hmac.compare_digest(url.path[5:-4].encode(), self.token.encode()):
                return self.send_error(403, 'token required')
            with _lock:
                png = _image
            if png is None:
                return self.send_error(503, 'image not ready')
            return self.respond(png, 'image/png')
        if url.path.startswith('/t/'):
            given = url.path[3:]
        elif url.path in ('/', '/index.html'):
            given = (parse_qs(url.query).get('k') or [''])[0]
        else:
            return self.send_error(404)
        if not hmac.compare_digest(given.encode(), self.token.encode()):
            return self.send_error(403, 'token required')
        page = render_page(current_status(), self.token, self.refresh)
        self.respond(page.encode('utf-8'), 'text/html; charset=utf-8')

    def respond(self, body, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description='Kindle向けAIエージェント利用状況ダッシュボード')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--refresh', type=int, default=60, help='収集と画面更新の秒数')
    parser.add_argument('--rotate', type=int, choices=(90, 270), default=270,
                        help='画像の回転。270=kindleロゴが左、90=ロゴが右')
    args = parser.parse_args()
    Handler.token = load_token()
    Handler.refresh = max(15, args.refresh)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=refresh_loop, args=(Handler.refresh, args.rotate), daemon=True).start()
    print('Kindle view on port %d (started %s)' % (args.port, time.strftime('%H:%M:%S')), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()
