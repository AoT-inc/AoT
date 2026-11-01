# -*- coding: utf-8 -*-
"""웹 접속 기록 — 사용자가 지금 어느 기기로 어느 화면을 보고 있는가 (2026-10).

외부 AI(MCP)는 사용자가 **대화하는** 기기를 알 수 없다(원격 커넥터는 그 회사
서버가 호출한다). 대신 사용자가 **웹으로 접속한** 기기와 화면은 웹 서버가 평소
받는 요청에 이미 드러난다. 이 모듈은 그 요청을 해석해 브라우저 세션마다 마지막
상태를 남기고, MCP 도구(get_screen)가 키 주인 본인의 기록만 읽는다.

신호:
  - 페이지 열기(문서 요청)  → 지금 화면
  - 위젯 갱신 요청이 계속 옴 → 화면이 켜져 있음. 백그라운드 탭은
    aot-poll-visibility.js 가 setInterval 갱신을 멈춘다.
  - GET 외 요청             → 사람이 마지막으로 조작한 시각

저장: 본 DB 가 아니라 DATABASE_PATH 의 별도 파일. 날아가도 되는 휘발성 상태라
마이그레이션을 두지 않는다. 웹 워커 여럿과 MCP 프로세스가 같은 파일을 보므로
프로세스 메모리가 아니라 SQLite(WAL)다. 기록 실패는 요청을 절대 막지 않는다.
"""
import hashlib
import logging
import os
import re
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

#: 같은 브라우저에 대해 이보다 자주 쓰지 않는다 — 화면이 바뀌거나 조작이
#: 있으면 바로 쓴다. 라즈베리파이에서 위젯 갱신마다 쓰지 않으려는 것.
WRITE_INTERVAL_S = 10.0
#: 이 안에 요청이 있었으면 "보는 중" — 위젯 갱신 주기(보통 수 초~30초)보다 넉넉히.
VIEWING_WITHIN_S = 75.0
#: 이 안이면 "열려 있으나 조용함"(갱신이 없는 페이지일 수 있다).
OPEN_WITHIN_S = 30 * 60.0
#: 읽을 때 보는 범위와, 이보다 오래된 행은 지운다.
KEEP_S = 12 * 3600.0

_DB_ENV = 'AOT_WEB_PRESENCE_DB'
_lock = threading.Lock()
_last_write = {}          # browser_key -> (ts, page_path)
_visible_sync = {}        # browser_key -> (보이는 탭의 표식, 그 탭이 마지막으로 동기화한 시각)
#: 보이는 탭이 이만큼 안에 동기화했으면 숨은 탭은 그 화면을 대신하지 않는다(초).
#: 보이는 화면의 동기화 간격(수 초)보다 넉넉하게.
VISIBLE_TAB_WINDOW_S = 20.0
_ready_paths = set()


def db_path():
    """기록 파일 경로. 시험은 환경변수로 바꾼다."""
    override = os.environ.get(_DB_ENV)
    if override:
        return override
    from aot.config import DATABASE_PATH
    return os.path.join(DATABASE_PATH, 'web_presence.db')


def _connect():
    path = db_path()
    conn = sqlite3.connect(path, timeout=1.0)
    conn.row_factory = sqlite3.Row
    if path not in _ready_paths:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute(
            'CREATE TABLE IF NOT EXISTS presence ('
            ' browser_key TEXT PRIMARY KEY, user_id TEXT NOT NULL,'
            ' device TEXT, form TEXT, page_path TEXT, page_kind TEXT,'
            ' page_ref TEXT, page_at REAL, seen_at REAL, acted_at REAL)')
        conn.execute('CREATE INDEX IF NOT EXISTS presence_user '
                     'ON presence(user_id)')
        # P2 — 화면 쪽 JS 가 보고하는 세부 상태와 이 기기의 "AI 조작 허용",
        # 그리고 사용자가 확인해 준 화면의 유효 시각. 별도 파일이라 마이그레이션
        # 체인이 없다 — 빠진 칸만 붙인다.
        have = {r[1] for r in conn.execute('PRAGMA table_info(presence)')}
        for col, decl in (('client_state', 'TEXT'), ('client_at', 'REAL'),
                          ('ai_allowed', 'INTEGER DEFAULT 0'),
                          ('grant_until', 'REAL'),
                          # 그 브라우저가 쓴 주소(https://호스트) — 화면이 백그라운드라
                          # 명령이 멈춰 있을 때 AI 가 건넬 링크를 만든다(2026-10-11).
                          ('origin', 'TEXT'),
                          # 화면이 지금 보이는가(document.visibilityState) — 동기화가
                          # 알려 준다. NULL 은 모름(예전 JS) = 보이는 것으로 친다.
                          ('visible', 'INTEGER'),
                          # 화면 따라가기 — 'off' | 'ask' | 'auto'(NULL = auto).
                          # "AI 화면 조작 허용" 과 따로 둔다(2026-10-12 A6).
                          ('follow_mode', 'TEXT')):
            if col not in have:
                conn.execute('ALTER TABLE presence ADD COLUMN %s %s' % (col, decl))
        conn.execute(
            'CREATE TABLE IF NOT EXISTS command ('
            ' id TEXT PRIMARY KEY, user_id TEXT NOT NULL, browser_key TEXT NOT NULL,'
            ' action TEXT NOT NULL, args TEXT, status TEXT NOT NULL, token TEXT,'
            ' created_at REAL, expires_at REAL, delivered_at REAL, done_at REAL,'
            ' result TEXT)')
        conn.execute('CREATE INDEX IF NOT EXISTS command_key '
                     'ON command(browser_key, status)')
        # 명령의 출처(follow = 읽기에 딸려 연 것, explicit = AI 가 screen_action 으로
        # 부른 것)와, 다른 대시보드로 옮긴 뒤에 풀리는 명령의 기다리는 대시보드 id
        # (`after_ref`) — 이 파일도 마이그레이션 체인이 없다.
        have = {r[1] for r in conn.execute('PRAGMA table_info(command)')}
        for col, decl in (('source', 'TEXT'), ('after_ref', 'TEXT')):
            if col not in have:
                conn.execute('ALTER TABLE command ADD COLUMN %s %s' % (col, decl))
        conn.commit()
        _ready_paths.add(path)
    return conn


# ── 해석 ──────────────────────────────────────────────────────────────────────

def describe_device(ua):
    """User-Agent → ("iPhone · Safari", "phone"). 모르면 ("Browser", "desktop")."""
    ua = ua or ''
    if 'iPad' in ua or ('Macintosh' in ua and 'Mobile/' in ua):
        os_name, form = 'iPad', 'tablet'
    elif 'iPhone' in ua:
        os_name, form = 'iPhone', 'phone'
    elif 'Android' in ua:
        os_name, form = 'Android', 'phone' if 'Mobile' in ua else 'tablet'
    elif 'Windows' in ua:
        os_name, form = 'Windows PC', 'desktop'
    elif 'Macintosh' in ua or 'Mac OS X' in ua:
        os_name, form = 'Mac', 'desktop'
    elif 'CrOS' in ua:
        os_name, form = 'Chromebook', 'desktop'
    elif 'Linux' in ua:
        os_name, form = 'Linux PC', 'desktop'
    else:
        os_name, form = None, 'desktop'

    if 'Edg/' in ua or 'EdgiOS' in ua or 'EdgA/' in ua:
        browser = 'Edge'
    elif 'SamsungBrowser' in ua:
        browser = 'Samsung Internet'
    elif 'Firefox/' in ua or 'FxiOS' in ua:
        browser = 'Firefox'
    elif 'CriOS' in ua or 'Chrome/' in ua:
        browser = 'Chrome'
    elif 'Safari/' in ua:
        browser = 'Safari'
    else:
        browser = None

    parts = [p for p in (os_name, browser) if p]
    return (' · '.join(parts) if parts else 'Browser'), form


_UUID = r'[0-9a-fA-F-]{8,36}'
#: 경로 앞부분 → 화면 종류. 위에서부터 맞춘다.
_PAGE_RULES = (
    (re.compile(r'^/dashboard/(%s)' % _UUID), 'dashboard'),
    (re.compile(r'^/dashboard/?$'), 'dashboard'),
    (re.compile(r'^/(?:input|data)(?:/|$)'), 'inputs'),
    (re.compile(r'^/output(?:/|$)'), 'outputs'),
    (re.compile(r'^/function(?:/|$)'), 'functions'),
    (re.compile(r'^/device(?:/|$)'), 'devices'),
    (re.compile(r'^/plots(?:/|$)'), 'plots'),
    (re.compile(r'^/geo/programs'), 'crop programs'),
    (re.compile(r'^/geo/journal'), 'plot journal'),
    (re.compile(r'^/geo/facility'), 'facilities'),
    (re.compile(r'^/(?:geo|map)(?:/|$)'), 'map'),
    (re.compile(r'^/notes(?:/|$)'), 'notes'),
    (re.compile(r'^/camera(?:/|$)'), 'camera'),
    (re.compile(r'^/(?:settings|admin)(?:/|$)'), 'settings'),
    (re.compile(r'^/ai(?:/|$)'), 'AI'),
    (re.compile(r'^/(?:logview|audit_log)(?:/|$)'), 'logs'),
)


#: screen_action navigate 가 갈 수 있는 화면 → 주소. 위 _PAGE_RULES 의 이름과 같다.
#: 설정·관리 화면은 일부러 없다 — 계정·권한·시스템을 외부 AI 가 열게 하지 않는다.
NAVIGABLE = {
    'dashboard': '/dashboard',
    'inputs': '/input',
    'outputs': '/output',
    'functions': '/function',
    'devices': '/device',
    'plots': '/plots',
    'map': '/geo/design',
    'notes': '/notes',
    'crop programs': '/geo/programs',
    'plot journal': '/geo/journal',
}


#: 탭이 있는 페이지 → Tab.page_type. 탭은 주소의 `?tab_id=` 로 고른다(없으면 그
#: 사람에게 보이는 첫 탭). 대시보드는 Dashboard 행이 곧 탭이라 여기 없다.
TAB_PAGE_TYPES = {
    'inputs': 'input',
    'outputs': 'output',
    'functions': 'function',
    'crop programs': 'program',
}


def classify_page(path, tab_id=None):
    """경로(+탭) → (화면 종류, 참조 id). 대시보드는 그 대시보드 id, 탭이 있는
    페이지는 주소의 tab_id(없으면 None = 첫 탭)를 참조로 준다."""
    path = path or '/'
    for rx, kind in _PAGE_RULES:
        m = rx.match(path)
        if m:
            ref = m.group(1) if m.groups() else None
            if kind in TAB_PAGE_TYPES and tab_id:
                ref = str(tab_id)[:64]
            return kind, ref
    seg = path.strip('/').split('/')[0]
    return (seg or 'home'), None


#: 페이지가 열릴 때 스스로 보내는 POST — 사람의 조작이 아니다. 화면 문구
#: 번역(`/api/v1/locale/user_strings/translate`)이 대시보드를 열 때마다 나간다
#: (2026-10-10 개발 서버 실측). 화면 연동 동기화(`/api/v1/screen/sync`)도 화면이
#: 스스로 보내는 것이다.
_PASSIVE_POST_PREFIXES = ('/api/v1/locale/', '/api/v1/screen/')


def classify_request(method, path, accept, fetch_dest, xrw, mimetype,
                     readonly_posts=frozenset()):
    """요청 하나 → 'page' | 'act' | 'poll' | None(기록 안 함).

    readonly_posts: 본문이 커서 POST 로 보내지만 읽기만 하는 경로. 위젯 갱신
    (`/data_batch`)이 그렇다 — 조작으로 세면 화면을 켜 두기만 해도 "방금
    조작함" 이 된다(2026-10-10 개발 서버 실측). app._READONLY_POST_PATHS 를 받는다.
    """
    if path.startswith('/static/') or path in ('/favicon.ico', '/favicon.png'):
        return None
    # 로그인·로그아웃은 세션 쿠키를 바꾼다 — 바뀌기 전 쿠키로 남기면 같은
    # 브라우저가 "알 수 없는 화면" 으로 하나 더 생긴다(2026-10-10 실측).
    if path.startswith(('/login', '/logout')):
        return None
    if method not in ('GET', 'HEAD'):
        if path in readonly_posts or path.startswith(_PASSIVE_POST_PREFIXES):
            return 'poll'
        return 'act'
    is_html = (mimetype or '').startswith('text/html')
    if fetch_dest:
        # 보안 연결(https·localhost)이면 브라우저가 요청 목적을 알려 준다.
        if fetch_dest == 'document':
            return 'page' if is_html else 'poll'
        return 'poll'
    # 평문 http(현장 LAN)에는 Sec-Fetch-* 가 없다 — 문서 이동은 Accept 가
    # text/html 로 시작하고 XHR 표지가 없다. fetch()·$.ajax 는 */* 나 json.
    if is_html and not xrw and (accept or '').startswith('text/html'):
        return 'page'
    return 'poll'


def browser_key(cookie_value):
    """브라우저 하나의 열쇠 — 브라우저가 보낸 세션 쿠키 값의 해시. 원문은
    남기지 않는다(세션을 훔치는 데 쓰일 수 있다).

    서버 쪽 `session.sid` 를 쓰지 않는 이유: 세션을 건너뛰는 자산 라우트
    (custom.css·번역 스크립트 등, app.extension_session)는 빈 세션을 받아 sid 가
    없거나 새로 생긴다. 그 요청이 같은 브라우저인데 다른 열쇠로 남아 "보는 중인
    다른 화면" 이 하나 더 생겼다(2026-10-10 개발 서버 실측). 쿠키는 어느 요청에나
    같은 값으로 실려 온다."""
    if not cookie_value:
        return None
    return hashlib.sha256(cookie_value.encode('utf-8', 'replace')).hexdigest()[:24]


# ── 기록 ──────────────────────────────────────────────────────────────────────

def record(user_id, key, ua, path, kind, now=None, tab_id=None, origin=None):
    """요청 하나를 반영한다. 묶음 간격 안이고 화면·조작 변화가 없으면 건너뛴다.

    tab_id: 문서 요청 주소의 `?tab_id=` — 같은 페이지에서 탭만 바꿔도 다른
    화면이다(입력·출력·함수 페이지는 탭을 주소로 고른다)."""
    if not user_id or not key or kind is None:
        return False
    now = time.time() if now is None else now
    page_kind = page_ref = None
    if kind == 'page':
        page_kind, page_ref = classify_page(path, tab_id)
        if tab_id:
            path = '%s?tab_id=%s' % (path, str(tab_id)[:64])
    with _lock:
        last = _last_write.get(key)
        if (kind == 'poll' and last is not None
                and now - last[0] < WRITE_INTERVAL_S):
            return False
        if kind == 'page' and last is not None and last[1] == path \
                and now - last[0] < WRITE_INTERVAL_S:
            return False
        _last_write[key] = (now, path if kind == 'page' else
                            (last[1] if last else None))
        if len(_last_write) > 5000:
            _last_write.clear()
    device, form = describe_device(ua)
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    'INSERT INTO presence (browser_key, user_id, device, form,'
                    ' seen_at) VALUES (?, ?, ?, ?, ?)'
                    ' ON CONFLICT(browser_key) DO UPDATE SET'
                    ' user_id=excluded.user_id, device=excluded.device,'
                    ' form=excluded.form, seen_at=excluded.seen_at',
                    (key, user_id, device, form, now))
                if kind == 'page':
                    # 문서를 막 열었다 = 그 화면이 앞에 있다.
                    conn.execute(
                        'UPDATE presence SET page_path=?, page_kind=?,'
                        ' page_ref=?, page_at=?, visible=1 WHERE browser_key=?',
                        (path[:300], page_kind, page_ref, now, key))
                    if origin:
                        conn.execute('UPDATE presence SET origin=?'
                                     ' WHERE browser_key=?', (origin[:200], key))
                elif kind == 'act':
                    conn.execute('UPDATE presence SET acted_at=?'
                                 ' WHERE browser_key=?', (now, key))
                if int(now) % 97 == 0:
                    conn.execute('DELETE FROM presence WHERE seen_at < ?',
                                 (now - KEEP_S,))
        finally:
            conn.close()
        return True
    except sqlite3.Error as exc:
        logger.debug('web presence write skipped: %s', exc)
        return False


def record_flask_request(request, response, user, readonly_posts=frozenset()):
    """after_request 에서 부른다. 어떤 실패도 요청에 영향을 주지 않는다."""
    try:
        if not getattr(user, 'is_authenticated', False):
            return
        user_id = getattr(user, 'unique_id', None)
        kind = classify_request(
            request.method, request.path,
            request.headers.get('Accept', ''),
            request.headers.get('Sec-Fetch-Dest', ''),
            request.headers.get('X-Requested-With', ''),
            response.mimetype, readonly_posts)
        if kind is None or response.status_code >= 400:
            return
        from flask import current_app
        cookie = request.cookies.get(
            current_app.config.get('SESSION_COOKIE_NAME') or 'session')
        key = browser_key(cookie)
        if key is None:
            return
        record(user_id, key, request.headers.get('User-Agent', ''),
               request.path, kind, tab_id=request.args.get('tab_id'),
               origin=(request.host_url or '').rstrip('/') or None)
    except Exception:
        logger.debug('web presence hook failed', exc_info=True)


# ── 읽기 ──────────────────────────────────────────────────────────────────────

def recent(user_id, now=None):
    """키 주인 본인의 최근 접속 행(최근 활동 순)."""
    if not user_id:
        return []
    now = time.time() if now is None else now
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                'SELECT * FROM presence WHERE user_id=? AND seen_at>=?'
                ' ORDER BY seen_at DESC LIMIT 20',
                (user_id, now - KEEP_S)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning('web presence read failed: %s', exc)
        return []
    return [dict(r) for r in rows]


def page_link(row):
    """그 화면이 마지막으로 연 페이지의 주소 — 그 브라우저가 실제로 쓴 호스트로.

    폰에서 AI 앱으로 대화하는 동안 AoT 탭은 백그라운드라 명령을 가져가지 못한다.
    이 링크를 누르면 같은 브라우저(같은 쿠키)로 그 페이지가 열리고, 열린 화면이
    밀린 명령을 바로 가져간다. 주소를 모르면 None(링크 없이 안내만 한다)."""
    origin = (row or {}).get('origin')
    path = (row or {}).get('page_path')
    if not origin or not path or not str(path).startswith('/'):
        return None
    return origin + path


def link_to(row, path):
    """그 브라우저가 쓴 호스트로 만든 임의 경로의 주소 — 다른 대시보드로 옮길 때, 화면이
    백그라운드면 그 대시보드를 바로 여는 링크를 건넨다. 주소를 모르면 None."""
    origin = (row or {}).get('origin')
    if not origin or not path or not str(path).startswith('/'):
        return None
    return origin + path


def is_visible(row):
    """그 화면이 보인다고 알려 왔는가. 모르면(NULL — 예전 JS·동기화 전) 보인다고 친다."""
    v = (row or {}).get('visible')
    return v is None or bool(v)


def state_of(row, now):
    """'viewing' | 'open' | 'away'. 최근 요청이 있어도 화면이 숨었다고 알려 온
    탭(다른 앱·다른 탭이 앞)은 '보는 중' 이 아니다(2026-10-12 A6)."""
    gap = now - (row.get('seen_at') or 0)
    if gap <= VIEWING_WITHIN_S and is_visible(row):
        return 'viewing'
    if gap <= VIEWING_WITHIN_S:
        return 'open'
    if gap <= OPEN_WITHIN_S:
        return 'open'
    return 'away'


def pick_likely(rows, now):
    """(행 위치 또는 None, confidence). 보는 중인 화면 중 사람이 가장 최근에
    손댄 곳. 둘 이상이 1분 안팎으로 겹치면 ambiguous — 짐작하지 않는다."""
    if not rows:
        return None, 'none'

    def touched(r):
        return max(r.get('acted_at') or 0, r.get('page_at') or 0)

    viewing = [i for i, r in enumerate(rows) if state_of(r, now) == 'viewing']
    if len(viewing) == 1:
        return viewing[0], 'high'
    if len(viewing) > 1:
        ranked = sorted(viewing, key=lambda i: touched(rows[i]), reverse=True)
        if touched(rows[ranked[0]]) - touched(rows[ranked[1]]) >= 60:
            return ranked[0], 'high'
        return None, 'ambiguous'
    open_ = [i for i, r in enumerate(rows) if state_of(r, now) == 'open']
    if open_:
        return max(open_, key=lambda i: rows[i].get('seen_at') or 0), 'low'
    return None, 'none'



# ── 화면 조작 (P2) ────────────────────────────────────────────────────────────
#
# 외부 AI 가 screen_action 으로 명령을 넣으면, 그 화면의 JS(aot-screen-link.js)가
# 짧은 주기로 /api/v1/screen/sync 를 불러 가져가 실행하고 결과를 돌려준다. 서버가
# 브라우저로 먼저 보낼 길이 없어서(SocketIO·Redis 없음, 워커 여럿) 화면이 가져간다.
#
# 위치 확인(사용자 2026-10-10): 짐작한 화면에 바로 실행하지 않는다. 처음 명령은
# 'proposed' 로 두고 두 길 중 먼저 온 쪽으로 진행한다.
#   - 대화: AI 가 사용자에게 기기·화면을 묻고, 동의를 받으면 받은 token 으로 다시 부른다.
#   - 화면: 그 화면에 [허용] 카드가 뜬다. 화면 앞의 사람이 누르는 것이라 위치와
#     허락이 한 번에 확인된다.
# 확인된 화면은 GRANT_S 동안 다시 묻지 않는다(음성으로 이어 말할 때마다 묻지 않게).

#: 확인된 화면을 다시 묻지 않는 시간.
GRANT_S = 10 * 60.0
#: 확인을 기다리는 명령의 수명 — 묻고 답하는 데 충분히.
PROPOSE_TTL_S = 3 * 60.0
#: 실행 대기 명령의 수명. 백그라운드 탭(같은 휴대폰에서 AI 앱으로 넘어간 경우)은
#: 폴링이 멈췄다가 돌아오면 가져간다.
QUEUE_TTL_S = 10 * 60.0
#: 사람 한 명이 1분에 넣을 수 있는 명령 수.
RATE_PER_MIN = 12
#: 명령이 있거나 막 끝났을 때 화면이 당겨 묻는 주기, 평소 주기(ms).
POLL_FAST_MS = 1000
POLL_IDLE_MS = 2000


def _now(now):
    return time.time() if now is None else now


#: 화면 따라가기 설정값. 없으면 자동(사용자 2026-10-12: 기본 "자동").
FOLLOW_MODES = ('off', 'ask', 'auto')
FOLLOW_DEFAULT = 'auto'


def follow_mode(row):
    """그 화면(기기)의 따라가기 설정 — 'off' | 'ask' | 'auto'."""
    v = str((row or {}).get('follow_mode') or '').strip().lower()
    return v if v in FOLLOW_MODES else FOLLOW_DEFAULT


def screen_brief(row, label=None):
    """후보로 돌려줄 화면 하나 — get_screen 의 screen(열쇠 앞 12자)과 기기 이름."""
    out = {'screen': (row.get('browser_key') or '')[:12],
           'device': row.get('device') or 'browser'}
    if label:
        out['page'] = label
    return out


def resolve_screen(user_id, screen, now=None):
    """get_screen 이 준 `screen`(열쇠 앞 12자) → 그 사용자의 접속 행, 없으면 None."""
    if not user_id or not screen or len(screen) < 8:
        return None
    for r in recent(user_id, now=_now(now)):
        if r['browser_key'].startswith(screen):
            return r
    return None


def has_grant(row, now=None):
    return bool(row and (row.get('grant_until') or 0) > _now(now))


def auto_confirmed(row, now=None):
    """[허용] 카드 없이 바로 실행해도 되는 화면인가 (사용자 결정 2026-10-20).

    그 기기에서 "AI 화면 조작 허용" 을 켠 것 자체가 허락이다 — 켠 사람은 이미 화면 앞에
    있었고 그 선택은 localStorage 에 남아 동기화마다 서버에 다시 실린다. 예전에는 그 위에
    10분짜리 확인(GRANT_S)을 한 번 더 요구했고, 15분 쉬었다 시작하는 대화는 첫 질문에서
    카드가 떠 막혔다. 끄면 동기화가 남은 명령을 전부 거두므로(`sync`) 그 즉시 아무것도
    실행되지 않는다.

    다만 **최근에 동기화한 화면만**이다(`OPEN_WITHIN_S`). 켠 채로 닫힌 브라우저의 행은
    12시간 남는데, 그 화면에 넣어 둔 명령이 한참 뒤 누가 그 브라우저를 열 때 실행되면 안
    된다 — 그런 행에는 예전처럼 확인을 요구한다. 기기별 따라가기 '묻기'(ask)는 이 판정과
    별개로 호출한 쪽이 존중한다(사용자가 고른 설정이다).
    """
    if not row or not row.get('ai_allowed'):
        return False
    return state_of(row, _now(now)) != 'away'


def extend_grant(key, now=None):
    """확인된 화면을 쓸 때마다 유효 시간을 다시 채운다 — 대화가 이어지는 동안
    중간에 다시 묻지 않게(슬라이딩)."""
    now = _now(now)
    conn = _connect()
    try:
        with conn:
            conn.execute('UPDATE presence SET grant_until=? WHERE browser_key=?'
                         ' AND grant_until>?', (now + GRANT_S, key, now))
    finally:
        conn.close()


def recently_sent(key, action, item_id, within_s=90.0, now=None):
    """같은 화면에 같은 대상을 방금 보냈는가 — 강조(highlight)처럼 화면 상태에 남지 않는
    동작이 한 질문 안에서 거듭 나가지 않게. 창 열기는 이것이 아니라 화면이 알려 온 열린
    창과 비교한다(`pending_open_item`)."""
    import json
    now = _now(now)
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT args FROM command WHERE browser_key=? AND action=? AND"
            " created_at>=? AND status NOT IN ('rejected','expired','failed','superseded')",
            (key, action, now - within_s)).fetchall()
    finally:
        conn.close()
    for r in rows:
        try:
            if json.loads(r['args'] or '{}').get('id') == item_id:
                return True
        except ValueError:
            continue
    return False


#: 아직 화면에 닿지 않았거나 실행 중인 명령 — 화면 상태(`client_state`)에는 아직 없지만
#: 곧 그렇게 될 것이다. 중복 판정은 이것까지 합쳐 "곧 화면에 있을 것" 으로 본다.
_UNFINISHED = ('proposed', 'queued', 'delivered', 'held')


def pending_open_item(key, within_s=45.0, now=None):
    """이 화면에 열려고 보냈는데 아직 끝나지 않은 지도 창의 대상(args), 없으면 None.

    예전 `last_opened_item` 은 끝난 명령까지 90초 동안 "화면에 열려 있다" 고 보았다 —
    그 사이 사용자나 다른 명령이 화면을 바꿔도 모르고 같은 대상을 건너뛰어 화면이
    어긋났다(2026-10-18: 3포장을 건너뛴 화면은 2포장이었다). 끝난 명령은 이제 화면이
    동기화로 알려 오는 열린 창(`client_state`)이 맡고, 여기는 아직 끝나지 않은 것만 본다.
    """
    import json
    now = _now(now)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT args FROM command WHERE browser_key=? AND action='open_map_item'"
            " AND created_at>=? AND status IN (%s)"
            " ORDER BY created_at DESC LIMIT 1" % ','.join('?' * len(_UNFINISHED)),
            (key, now - within_s) + _UNFINISHED).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        args = json.loads(row['args'] or '{}') or None
    except ValueError:
        return None
    # 창 없이 지도만 옮기는 명령(modal=False — 날씨 설명)은 '창을 열려는 중' 이 아니다.
    return None if args and args.get('modal') is False else args


def pending_dashboard(key, within_s=20.0, now=None, include_queued=False):
    """방금 이 화면을 옮기라고 보낸 대시보드 id — 화면이 이미 받아 가서(delivered) 새
    페이지가 뜨는 중이거나 막 끝난(done) 것. 아직 서버의 페이지 기록(`page_ref`)이 옛
    대시보드를 가리키는 짧은 사이에 다음 따라가기가 또 옮기지 않도록 한다. 아직 받아
    가지 않은(queued) 이동은 다음 명령이 대체할 수 있어 여기 세지 않는다.

    include_queued=True 면 받아 가지 않은 이동도 센다 — 이동 직후에 올리는 AI 카드를 도착 뒤로 미루려는
    쪽이 쓴다(받아 간 뒤에 카드를 올리면 새 페이지가 뜨며 카드가 지워진다, 2026-10-30)."""
    import json
    now = _now(now)
    states = ('queued', 'delivered', 'done') if include_queued else ('delivered', 'done')
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT args FROM command WHERE browser_key=? AND action='navigate'"
            " AND created_at>=? AND status IN (%s)"
            " ORDER BY created_at DESC LIMIT 1" % ','.join('?' * len(states)),
            (key, now - within_s) + states).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        url = str((json.loads(row['args'] or '{}') or {}).get('url') or '')
    except ValueError:
        return None
    m = re.match(r'^/dashboard/(%s)$' % _UUID, url)
    return m.group(1) if m else None


def last_map_widget(key, within_s=1800.0, now=None):
    """이 화면에서 마지막으로 다룬 지도 위젯 id — 다음 지도 명령도 그 지도에서
    하도록(사용자가 보던 지도 A 를 두고 B·C 를 움직이지 않게)."""
    import json
    now = _now(now)
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT args FROM command WHERE browser_key=? AND action IN"
            " ('open_map_item','map_control') AND status='done' AND created_at>=?"
            " ORDER BY created_at DESC LIMIT 1", (key, now - within_s)).fetchall()
    finally:
        conn.close()
    for r in rows:
        try:
            return json.loads(r['args'] or '{}').get('widget_id')
        except ValueError:
            return None
    return None


def last_view_miss(key, within_s=120.0, now=None):
    """마지막으로 끝난 화면 이동 명령이 "그 자리로 갔지만 사용자에게 안 보인다" 로 끝났으면 (대상 이름, 이유).

    따라가기(읽기 조회가 넣는 강조·스크롤)는 화면이 몇 초 뒤 실행해 도구 응답은 결과를 기다리지 않는다 —
    그 결과를 다음 get_screen 이 알려, AI 가 안 보이는 것을 보인다고 말하지 않게 한다. 가장 최근에 끝난 화면 이동 명령이
    보이는 쪽으로 끝났으면 없다."""
    import json
    now = _now(now)
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT args, result FROM command WHERE browser_key=? AND status='done' AND created_at>=?"
            " AND action IN ('highlight','map_control','open_map_item','open_widget_settings')"
            " ORDER BY created_at DESC LIMIT 1", (key, now - within_s)).fetchall()
    finally:
        conn.close()
    for r in rows:
        try:
            msg = str((json.loads(r['result'] or '{}') or {}).get('message') or '')
            m = re.match(r'^@@(\{.*?\})@@', msg)
            meta = json.loads(m.group(1)) if m else {}
            if meta.get('in_view') is False:
                args = json.loads(r['args'] or '{}') or {}
                return (str(args.get('name') or '')[:60], str(meta.get('view_note') or '')[:80])
        except ValueError:
            continue
    return None


def recent_command_count(user_id, now=None):
    now = _now(now)
    conn = _connect()
    try:
        # 새 명령이 대체한 것(superseded)은 화면에 가지 않았으니 세지 않는다 — 한 질문에
        # 대상 여럿을 읽으면 앞의 것들이 대체되는데 그것까지 세면 곧 한도에 걸린다.
        return conn.execute("SELECT COUNT(*) FROM command WHERE user_id=?"
                            " AND created_at>=? AND status!='superseded'",
                            (user_id, now - 60)).fetchone()[0]
    finally:
        conn.close()


#: 새 명령이 대체하는 동작 — 화면을 어디로 옮기거나 무엇을 보여 주는 것들.
_SUPERSEDES = ('open_map_item', 'highlight', 'navigate')
FOLLOW_SOURCE = 'follow'
EXPLICIT_SOURCE = 'explicit'


def add_command(user_id, key, action, args, confirmed, now=None, source=None,
                hold_for=None, ttl_s=None, supersede=True):
    """명령 하나를 넣는다. confirmed 면 바로 실행 대기, 아니면 확인 대기.
    (id, token) 을 돌려준다 — token 은 확인 대기일 때만.

    source: 'follow'(읽기에 딸려 연 것) | 'explicit'(AI 가 화면 조작을 직접 부른 것).
    감사 기록(`screen.command`)에 실려, 나중에 "이 창은 누가 열었나" 를 가른다.

    hold_for: 대시보드 id. 주면 명령을 **붙잡아 둔다**('held') — 그 화면이 그 대시보드에
    도착했다고 동기화로 알려 올 때 실행 대기로 풀린다(`sync`). 대시보드를 옮긴 뒤에
    열 창 명령을 같이 넣을 때 쓴다: 화면이 명령 여럿을 한 번에 받아 동시에 돌리므로
    같이 내보내면 이동이 페이지를 다시 읽는 바람에 뒤의 명령이 조용히 사라진다.

    화면 이동·창 열기·강조는 같은 화면의 **아직 끝나지 않은 따라가기 명령을 대체한다**
    ('superseded'). 한 질문에 대상 여럿을 연달아 읽으면(AI 는 병렬로 부른다) 창이 4초
    간격으로 줄줄이 열리고 마지막 화면이 AI 의 마지막 설명과 어긋났다(2026-10-18).
    대체되는 것은 따라가기가 넣은 것뿐이다 — AI 가 직접 부른 명령은 호출자가 결과를
    기다리고 있어 건드리지 않는다. supersede=False 는 이동 명령 바로 뒤에 같은 호출이 넣는
    짝(대시보드 도착을 기다리는 열기)이 방금 넣은 이동을 대체하지 않게 한다.
    """
    import json
    import secrets
    import uuid
    now = _now(now)
    cid = uuid.uuid4().hex[:16]
    token = None if confirmed else secrets.token_hex(4)
    status = 'queued' if confirmed else 'proposed'
    ttl = ttl_s or (QUEUE_TTL_S if confirmed else PROPOSE_TTL_S)
    if hold_for:
        status, token = 'held', None
    conn = _connect()
    try:
        with conn:
            if (supersede and action in _SUPERSEDES
                    and source in (FOLLOW_SOURCE, EXPLICIT_SOURCE)):
                conn.execute(
                    "UPDATE command SET status='superseded', done_at=?,"
                    " result='{\"reason\":\"replaced by a newer open\"}'"
                    " WHERE browser_key=? AND source=? AND action IN (%s)"
                    " AND status IN ('proposed','queued','held')"
                    % ','.join('?' * len(_SUPERSEDES)),
                    (now, key, FOLLOW_SOURCE) + _SUPERSEDES)
            conn.execute(
                'INSERT INTO command (id, user_id, browser_key, action, args,'
                ' status, token, created_at, expires_at, source, after_ref)'
                ' VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (cid, user_id, key, action, json.dumps(args, ensure_ascii=False),
                 status, token, now, now + ttl, source, hold_for))
    finally:
        conn.close()
    return cid, token


def confirm_by_token(user_id, token, now=None):
    """대화로 받은 동의 — token 이 맞는 확인 대기 명령을 실행 대기로 올리고, 그
    화면에 GRANT_S 를 준다. 명령 행(dict) 또는 None."""
    now = _now(now)
    if not token:
        return None
    conn = _connect()
    try:
        with conn:
            row = conn.execute('SELECT * FROM command WHERE user_id=? AND token=?',
                               (user_id, token)).fetchone()
            if row is None:
                return None
            if row['status'] == 'proposed' and (row['expires_at'] or 0) > now:
                conn.execute("UPDATE command SET status='queued', expires_at=?"
                             " WHERE id=?", (now + QUEUE_TTL_S, row['id']))
                conn.execute('UPDATE presence SET grant_until=? WHERE browser_key=?',
                             (now + GRANT_S, row['browser_key']))
            row = conn.execute('SELECT * FROM command WHERE id=?',
                               (row['id'],)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_command(cid):
    conn = _connect()
    try:
        row = conn.execute('SELECT * FROM command WHERE id=?', (cid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def wait_finished(cid, timeout_s=7.0, step_s=0.25):
    """명령이 끝날(done/failed/rejected/expired) 때까지 잠깐 기다린다. 마지막 행."""
    deadline = time.time() + timeout_s
    row = get_command(cid)
    while row and row['status'] in ('queued', 'delivered', 'proposed') \
            and time.time() < deadline:
        time.sleep(step_s)
        row = get_command(cid)
    return row


def sync(user_id, key, state=None, allowed=False, results=(), answers=(),
         now=None, visible=None, follow=None, tab=None):
    """화면 하나의 동기화 — 상태를 받고, 결과·화면 확인을 반영하고, 가져갈 명령을
    돌려준다. 반환: {'commands': [...], 'poll_ms': int}.

    visible: 화면이 보이는가(document.visibilityState). None 이면 모름 — 그대로 둔다.
    follow: 이 기기의 따라가기 설정('off'|'ask'|'auto'). 모르는 값·None 은 그대로 둔다."""
    import json
    now = _now(now)
    out = []
    finished = []
    # 같은 브라우저의 탭들은 세션 쿠키가 같아 한 화면(browser_key)으로 보인다. 보이는 탭이
    # 방금 동기화했으면 숨은 탭은 화면 상태·페이지를 덮어쓰지 못하고 명령도 가져가지
    # 못한다 — 숨은 탭이 이동 명령을 받아 실행하고 '완료' 를 보고하는데 사용자가 보는
    # 탭은 그대로였다(2026-10-14 사용자 시험: 맥 크롬 탭 둘, 나주·영양).
    # 탭은 화면이 페이지를 열 때마다 만드는 표식(`tab`)으로 가른다 — 같은 탭이 뒤로 숨는
    # 것과 다른 탭이 뒤에서 동기화하는 것은 표식 없이는 구분되지 않는다. 표식이 없는 옛
    # 화면은 예전처럼 둔다.
    tab = str(tab)[:40] if tab else None
    with _lock:
        active = _visible_sync.get(key)
        if visible and tab:
            _visible_sync[key] = (tab, now)
            if len(_visible_sync) > 5000:
                _visible_sync.clear()
    behind = (visible is False and tab is not None and active is not None
              and active[0] != tab and now - active[1] < VISIBLE_TAB_WINDOW_S)
    conn = _connect()
    try:
        with conn:
            if behind:
                conn.execute('UPDATE presence SET ai_allowed=?, seen_at=?'
                             ' WHERE browser_key=? AND user_id=?',
                             (1 if allowed else 0, now, key, user_id))
            else:
                conn.execute(
                    'UPDATE presence SET client_state=?, client_at=?, ai_allowed=?,'
                    ' seen_at=? WHERE browser_key=? AND user_id=?',
                    (json.dumps(state or {}, ensure_ascii=False)[:8000], now,
                     1 if allowed else 0, now, key, user_id))
                _page_from_state(conn, key, user_id, state, now)
            if visible is not None and not behind:
                conn.execute('UPDATE presence SET visible=? WHERE browser_key=?'
                             ' AND user_id=?', (1 if visible else 0, key, user_id))
            mode = str(follow or '').strip().lower()
            if mode in FOLLOW_MODES:
                conn.execute('UPDATE presence SET follow_mode=? WHERE browser_key=?'
                             ' AND user_id=?', (mode, key, user_id))
            if not allowed:
                # 이 기기에서 끈 순간 — 남은 명령은 하나도 실행되지 않게 거둔다.
                conn.execute(
                    "UPDATE command SET status='rejected', done_at=?,"
                    " result='{\"reason\":\"ai control turned off on this device\"}'"
                    " WHERE browser_key=? AND status IN "
                    "('proposed','queued','delivered','held')",
                    (now, key))
                conn.execute('UPDATE presence SET grant_until=NULL'
                             ' WHERE browser_key=?', (key,))
                return {'commands': [], 'poll_ms': POLL_IDLE_MS}
            for r in results or ():
                ok = bool(r.get('ok'))
                msg = str(r.get('message') or '')[:300]
                hit = conn.execute(
                    "UPDATE command SET status=?, done_at=?, result=? WHERE id=?"
                    " AND browser_key=? AND status IN ('queued','delivered')",
                    ('done' if ok else 'failed', now,
                     json.dumps({'message': msg}, ensure_ascii=False),
                     str(r.get('id') or ''), key)).rowcount
                if hit:
                    finished.append(_finished_item(
                        conn, r.get('id'), 'done' if ok else 'failed', msg))
            for a in answers or ():
                cid = str(a.get('id') or '')
                if a.get('allow'):
                    hit = conn.execute(
                        "UPDATE command SET status='queued', expires_at=? WHERE id=?"
                        " AND browser_key=? AND status='proposed' AND expires_at>?",
                        (now + QUEUE_TTL_S, cid, key, now)).rowcount
                    if hit:
                        conn.execute('UPDATE presence SET grant_until=?'
                                     ' WHERE browser_key=?', (now + GRANT_S, key))
                else:
                    hit = conn.execute(
                        "UPDATE command SET status='rejected', done_at=?,"
                        " result='{\"reason\":\"declined on the screen\"}'"
                        " WHERE id=? AND browser_key=? AND status='proposed'",
                        (now, cid, key)).rowcount
                    if hit:
                        finished.append(_finished_item(
                            conn, cid, 'rejected', 'declined on the screen'))
                        # 이동을 거절했으면 그 뒤에 열려던 창도 접는다 — 사용자가 나중에
                        # 그 대시보드로 직접 가면 거절한 창이 저절로 열리면 안 된다.
                        conn.execute(
                            "UPDATE command SET status='rejected', done_at=?,"
                            " result='{\"reason\":\"declined on the screen\"}'"
                            " WHERE browser_key=? AND status='held'", (now, key))
            conn.execute("UPDATE command SET status='expired', done_at=? WHERE"
                         " status IN ('proposed','queued','held') AND expires_at<=?",
                         (now, now))
            if not behind:
                _release_held(conn, key, user_id, now)
            rows = [] if behind else conn.execute(
                "SELECT * FROM command WHERE browser_key=? AND user_id=? AND"
                " status IN ('proposed','queued') ORDER BY created_at",
                (key, user_id)).fetchall()
            for row in rows:
                item = {'id': row['id'], 'action': row['action'],
                        'args': json.loads(row['args'] or '{}'),
                        'ask': row['status'] == 'proposed'}
                out.append(item)
                if row['status'] == 'queued':
                    conn.execute("UPDATE command SET status='delivered',"
                                 " delivered_at=? WHERE id=?", (now, row['id']))
            busy = conn.execute(
                'SELECT COUNT(*) FROM command WHERE browser_key=? AND'
                ' created_at>=?', (key, now - 60)).fetchone()[0]
            if int(now) % 53 == 0:
                conn.execute('DELETE FROM command WHERE created_at<?',
                             (now - KEEP_S,))
    finally:
        conn.close()
    # '_finished' 는 브라우저로 보내지 않는다 — 라우트가 감사 기록에 쓰고 뗀다.
    return {'commands': out, '_finished': finished,
            'poll_ms': POLL_FAST_MS if (out or busy) else POLL_IDLE_MS}


def _release_held(conn, key, user_id, now):
    """대시보드 도착을 기다리던 명령을 푼다 — 그 화면이 지금 그 대시보드에 있으면.

    위치는 문서 요청(`record`)이나 화면의 경로 보고(`_page_from_state`)로 갱신되어 있다.
    풀린 명령은 같은 동기화 응답으로 나간다(바로 아래에서 queued 를 가져간다). 지도
    위젯이 아직 준비 중일 수 있어 기다림은 화면 JS(`openMapItem`)가 맡는다.

    이미 그 페이지에 와 있는데 아직 받아 가지 않은 같은 곳으로의 이동(`navigate`)은 끝낸
    것으로 친다. 안 그러면 화면이 이동과 열기를 한 번에 받아, 이동이 페이지를 다시 읽는
    바람에 열기가 사라진다 — 백그라운드였던 화면이 링크로 돌아온 경우가 그렇다.

    **따라가기가 넣은 이동만** 그렇게 친다. AI 가 직접 부른 이동(`screen_action`)은 같은
    페이지여도 그대로 내보낸다 — 새로 읽어 달라는 뜻일 수 있는데, 실행하지 않고 '이미 그
    페이지' 로 끝내면 AI 는 화면이 바뀌었다고 믿는다(2026-10-20 점검)."""
    import json
    row = conn.execute('SELECT page_kind, page_ref, page_path FROM presence'
                       ' WHERE browser_key=? AND user_id=?', (key, user_id)).fetchone()
    if row is None or row['page_kind'] != 'dashboard' or not row['page_ref']:
        return
    conn.execute("UPDATE command SET status='queued', expires_at=? WHERE browser_key=?"
                 " AND user_id=? AND status='held' AND after_ref=? AND expires_at>?",
                 (now + QUEUE_TTL_S, key, user_id, row['page_ref'], now))
    here = (row['page_path'] or '').split('?')[0]
    for c in conn.execute("SELECT id, args FROM command WHERE browser_key=? AND user_id=?"
                          " AND action='navigate' AND status='queued' AND source=?",
                          (key, user_id, FOLLOW_SOURCE)).fetchall():
        try:
            url = str((json.loads(c['args'] or '{}') or {}).get('url') or '')
        except ValueError:
            continue
        if url.split('?')[0] == here:
            conn.execute("UPDATE command SET status='done', done_at=?, result=?"
                         " WHERE id=?",
                         (now, json.dumps({'message': 'already on that page'}), c['id']))


def _page_from_state(conn, key, user_id, state, now):
    """화면이 보낸 경로가 기록된 페이지와 다르면 화면 쪽을 따른다.

    페이지 위치는 문서 요청(`record`)으로만 남았다. 그런데 페이지는 서버 요청 없이도
    바뀐다 — 브라우저 캐시·뒤로/앞으로 복원. 그러면 위젯 목록(동기화)은 새 페이지 것인데
    페이지는 옛 대시보드로 남아, 화면 조작이 "그 대시보드에 그 위젯이 없다" 로 거절됐다
    (2026-10-14 사용자 시험: 맥 크롬이 영양을 보는데 서버는 나주로 기억). 화면은 경로만
    보내므로(`location.pathname`) 같은 페이지면 그대로 둔다 — 문서 요청이 남긴 탭
    (`?tab_id=`)을 지우지 않게."""
    path = str((state or {}).get('path') or '').strip()[:300]
    if not path.startswith('/'):
        return
    row = conn.execute('SELECT page_path FROM presence WHERE browser_key=? AND user_id=?',
                       (key, user_id)).fetchone()
    if row is None or (row['page_path'] or '').split('?')[0] == path:
        return
    kind, ref = classify_page(path)
    conn.execute('UPDATE presence SET page_path=?, page_kind=?, page_ref=?, page_at=?'
                 ' WHERE browser_key=? AND user_id=?', (path, kind, ref, now, key, user_id))
    with _lock:
        _last_write.pop(key, None)       # 다음 문서 요청이 같은 경로라고 건너뛰지 않게


def _finished_item(conn, cid, status, message):
    """끝난 명령 하나 — 감사 기록용(무엇을, 어떻게 끝났나). 명령 행은 12시간
    뒤 지워지므로(KEEP_S) 흔적은 감사 기록에 남긴다(2026-10-11)."""
    import json
    row = conn.execute('SELECT action, args, source FROM command WHERE id=?',
                       (str(cid or ''),)).fetchone()
    describe = None
    if row is not None:
        try:
            describe = (json.loads(row['args'] or '{}') or {}).get('describe')
        except ValueError:
            describe = None
    return {'id': str(cid or ''), 'action': row['action'] if row else None,
            'describe': describe, 'status': status, 'message': message or '',
            'source': row['source'] if row else None}
