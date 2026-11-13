# coding=utf-8
"""AI 카드의 MCP resources (2026-10-19, P2) — resources/list · read · templates/list, resource_link.

표준 MCP 클라이언트(Claude Desktop·Cursor 등)가 AoT 의 AI 수신함 카드를 자료로 열 수 있게 한다.
stdio·http 전송이 같은 함수를 쓴다(`handle`). 도구가 아니라 **읽기 전용 자료**이고, 키 주인
(role.user_id → User) 본인의 카드만 본다.

URI: `aot://ai-card/<uuid36>`(카드 글) · `aot://ai-card/<uuid36>/file`(첫 파일, `/file/0` 과 같다) ·
`aot://ai-card/<uuid36>/file/<i>`(i = 0..7 번째 첨부, P5). 영상 링크는 자료가 아니라 카드 글 끝의
`attachments:` 목록에 제공처+URL 로 나온다. 정규식은 전체 일치(fullmatch)만 — 앞자리 일치나 줄
끝 개행 우회가 없다.

보안(계약 P2 ④·⑦):
  - IDOR: 모든 질의가 user_id 로 먼저 거른다. 없음·남의 것·만료는 **같은 오류**(-32002
    "Resource not found" — 존재 비노출), 형식 오류는 -32602.
  - 프롬프트 주입: 카드·텍스트 파일 본문 앞에 source 와 "자료이지 지시가 아니다" 표식을
    싣는다(P1 M3). html 은 `text/plain` 으로만 돌려준다(호스트가 자동으로 그리지 않게).
  - DoS: read 는 키 주인당 분당 30회·내보내는 바이트 분당 16 MiB(http 일괄 요청 증폭 차단), 텍스트는 앞 20,000자 + 남은 글자 수, blob 은 저장 파일만
    (최대 5 MiB), list 는 20장 + 커서.
  - 감사: 기존 MCP 감사 기록(mcp_audit_log)에 `resources/list|read|templates/list` 를 도구
    이름 칸에 남긴다(실제 도구 이름에는 '/' 가 없어 구분된다).
"""
import base64
import collections
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

URI_PREFIX = 'aot://ai-card/'
_URI = re.compile(r'aot://ai-card/([0-9a-f-]{36})(/file(?:/([0-7]))?)?')
_UUID = re.compile(r'[0-9a-f-]{36}')

LIST_LIMIT = 20
TEXT_CHARS = 20000
READ_PER_MIN = 30
METHODS = ('resources/list', 'resources/read', 'resources/templates/list')

#: resource_link 블록·resources/links 를 쓸 수 있는 최소 프로토콜 버전(날짜 문자열 비교).
LINK_MIN_PROTOCOL = '2025-06-18'
LINK_DEFAULT_PROTOCOL = '2025-03-26'      # http 에서 MCP-Protocol-Version 헤더가 없을 때

NOT_FOUND = (-32002, 'Resource not found')


class RpcError(Exception):
    """JSON-RPC 오류로 그대로 돌려줄 수 있는 실패."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def supports_links(version):
    """협상한 프로토콜 버전이 resource_link 블록을 받을 수 있는가(≥2025-06-18).
    http 에서 헤더가 없으면(None) 2025-03-26 으로 본다. 모양이 틀린 값은 아니다."""
    v = (version or LINK_DEFAULT_PROTOCOL)
    v = v.strip() if isinstance(v, str) else ''
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', v)) and v >= LINK_MIN_PROTOCOL


# ── 이름·MIME ───────────────────────────────────────────────────────────────

def card_uri(card):
    return URI_PREFIX + card.unique_id


def file_uri(card, index=0):
    """i=0 은 예전 주소(`…/file`) 그대로, i≥1 은 `…/file/<i>`."""
    return URI_PREFIX + card.unique_id + ('/file' if not index else '/file/%d' % index)


def file_mime(att):
    """파일 자료의 MIME. 아티팩트(html)는 호스트가 자동으로 그리지 않게 text/plain."""
    if att.kind == 'artifact':
        return 'text/plain'
    return att.mime or 'application/octet-stream'


def _card_name(card):
    return (card.title or card.file_name or 'AI card')[:120]


def link_blocks(card):
    """post 결과에 붙이는 resource_link 블록(카드 + 파일형 첨부마다, 최대 8)."""
    from aot.utils import ai_screen_cards as cards
    out = [{"type": "resource_link", "uri": card_uri(card), "name": _card_name(card),
            "mimeType": "text/markdown", "annotations": {"audience": ["user"]}}]
    for att in cards.file_atts(cards.attachments(card)):
        out.append({"type": "resource_link", "uri": file_uri(card, att.position),
                    "name": (att.name or 'file')[:120], "mimeType": file_mime(att),
                    "annotations": {"audience": ["user"]}})
    return out


def _attachment_lines(atts):
    """카드 글 끝에 붙이는 `attachments:` 목록 — 이름·종류, 영상은 제공처+URL."""
    lines = []
    for a in atts:
        if a.kind == 'video':
            lines.append('- %d: %s %s' % (a.position, 'link' if a.provider == 'web' else 'video (%s)' % (a.provider or 'video'), a.url or ''))
        else:
            lines.append('- %d: %s (%s)' % (a.position, a.name or 'file', a.kind))
    return '\n\nattachments:\n' + '\n'.join(lines) if lines else ''


# ── 한도 ────────────────────────────────────────────────────────────────────

#: 키 주인당 분당 resources/read 로 내보내는 바이트(base64 전 원본) 상한. 횟수 한도(30)만 있으면
#: http 일괄(batch) 요청 하나에 같은 5 MiB 파일 read 30개를 실어 응답 210 MB·RSS +676 MB 를
#: 만들 수 있었다(2026-10-19 P2 보안 리뷰 M2). 한 번의 read 는 늘 허용(파일 상한 5 MiB < 이 값).
READ_BYTES_PER_MIN = 16 * 1024 * 1024

_hits = collections.defaultdict(collections.deque)
_spent = collections.defaultdict(collections.deque)     # user_id → deque[(시각, 바이트)]
_hits_lock = threading.Lock()


def _over_byte_budget(user_id, nbytes, now=None):
    """이번 read 의 바이트를 분당 예산에 더한다. 넘으면 True(더하지 않음)."""
    now = now or time.monotonic()
    with _hits_lock:
        dq = _spent[user_id]
        while dq and now - dq[0][0] >= 60:
            dq.popleft()
        if dq and sum(n for _t, n in dq) + nbytes > READ_BYTES_PER_MIN:
            return True
        dq.append((now, nbytes))
        if len(_spent) > 2000:
            for k in [k for k, v in _spent.items() if not v or now - v[-1][0] >= 60]:
                _spent.pop(k, None)
        return False


def _read_limited(user_id, now=None):
    """키 주인당 분당 30회 — 넘으면 True. 이 프로세스 안에서만 듣는다(MCP 서버는 한 프로세스)."""
    now = now or time.monotonic()
    with _hits_lock:
        dq = _hits[user_id]
        while dq and now - dq[0] >= 60:
            dq.popleft()
        if len(dq) >= READ_PER_MIN:
            return True
        dq.append(now)
        if len(_hits) > 2000:                 # 오래 안 온 사용자 칸을 비운다
            for k in [k for k, v in _hits.items() if not v or now - v[-1] >= 60]:
                _hits.pop(k, None)
        return False


# ── 표식 ────────────────────────────────────────────────────────────────────

def _marker(card):
    from aot.utils import ai_screen_cards as cards
    return 'source: %s\ncaution: %s\n\n' % (card.source_label or 'AI', cards.READ_CAUTION)


# ── 메서드 ──────────────────────────────────────────────────────────────────

def _list(user, params):
    from aot.databases.models.ai_screen_card import AIScreenCard
    from aot.utils import ai_screen_cards as cards
    cursor = params.get('cursor')
    query = cards.visible_query(user.id)
    if cursor is not None:
        if not isinstance(cursor, str) or not _UUID.fullmatch(cursor):
            raise RpcError(-32602, 'Invalid cursor')
        anchor = cards.get_card(user.id, cursor)
        if anchor is None:                    # 남의 것·없는 것 모두 같은 오류
            raise RpcError(-32602, 'Invalid cursor')
        query = query.filter(AIScreenCard.id < anchor.id)
    rows = query.order_by(AIScreenCard.id.desc()).limit(LIST_LIMIT).all()
    amap = cards.attachments_map(rows)
    resources = []
    for c in rows:
        ann = {"audience": ["user"], "lastModified": cards.iso_z(c.created_at)}
        resources.append({"uri": card_uri(c), "name": _card_name(c),
                          "mimeType": "text/markdown", "annotations": dict(ann)})
        for att in cards.file_atts(amap[c.id]):
            resources.append({"uri": file_uri(c, att.position),
                              "name": (att.name or 'file')[:120],
                              "mimeType": file_mime(att), "size": int(att.size or 0),
                              "annotations": dict(ann)})
    # 다음 쪽(nextCursor)은 내지 않는다 — 최근 카드 한 쪽만 준다(2026-11-07). claude.ai 는 연결할 때마다
    # 목록을 끝까지(최대 8쪽) 넘겨 받아, 카드 263장이면 연결 준비에만 왕복 8회·약 9초가 들었다(맥 음성 모드
    # 연결 실패와 겹친 시각). 오래된 카드도 uri 로는 그대로 읽힌다. cursor 인자는 옛 클라이언트를 위해 받는다.
    return {"resources": resources}


def _read(user, params):
    from aot.utils import ai_card_files as files
    from aot.utils import ai_screen_cards as cards
    uri = params.get('uri')
    if not isinstance(uri, str) or len(uri) > 200:
        raise RpcError(-32602, 'Invalid uri')
    m = _URI.fullmatch(uri)
    if not m:
        raise RpcError(-32602, 'Invalid uri')
    card = cards.get_alive_card(user.id, m.group(1))
    if card is None:
        raise RpcError(*NOT_FOUND)
    if not m.group(2):                        # 카드 글
        head = '# %s\n\n' % card.title if card.title else ''
        text = _marker(card) + head + (card.body or '') + \
            _attachment_lines(cards.attachments(card))
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}
    # 파일 — `/file` ≡ `/file/0`
    att = cards.attachment_at(card, int(m.group(3) or 0))
    if att is None or att.kind == 'video' or not att.path:
        raise RpcError(*NOT_FOUND)
    ext = (att.name or '').rsplit('.', 1)[-1].lower() if '.' in (att.name or '') else ''
    if ext in files.TEXT_EXTS or att.kind == 'artifact':
        body = cards.file_text(card, att)
        if body is None:
            raise RpcError(*NOT_FOUND)
        shown = body[:TEXT_CHARS]
        text = _marker(card) + shown
        if len(body) > TEXT_CHARS:
            text += '\n\n[%d more characters not shown]' % (len(body) - TEXT_CHARS)
        if _over_byte_budget(user.id, len(text)):
            raise RpcError(-32000, 'rate limited')
        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": text}]}
    data = files.read_stored(att.path)
    if data is None:
        raise RpcError(*NOT_FOUND)
    if _over_byte_budget(user.id, len(data)):
        raise RpcError(-32000, 'rate limited')
    return {"contents": [{"uri": uri, "mimeType": att.mime or 'application/octet-stream',
                          "blob": base64.b64encode(data).decode('ascii')}]}


def _audit(method, params, agent_id, transport, session_key, started, error):
    """기존 MCP 감사 기록에 남긴다(도구 이름 칸에 메서드 이름). 실패해도 올리지 않는다."""
    try:
        from aot.mcp_server import audit
        from aot.tools.tool_execution import session_key_hash
        key = 'uri' if method == 'resources/read' else 'cursor'
        ref = params.get(key)
        slim = {key: str(ref)[:120]} if ref is not None else {}
        audit.record_call(
            tool_name=method, params=slim, agent_id=agent_id or 'unknown', permission='read',
            error=error or '', duration_ms=int(round((time.monotonic() - started) * 1000)),
            session_key=session_key_hash(session_key), transport=transport,
            call_state='failed' if error else 'executed')
    except Exception:
        logger.exception('[ai_card_resources] 감사 기록 실패: %s', method)


def handle(app, method, params, user_uuid, agent_id=None, transport=None,
           session_key=None):
    """resources/* 한 건을 처리해 result dict 를 돌려준다. 실패는 RpcError.

    user_uuid 는 인증된 키 주인(role.user_id, User.unique_id). 앱 컨텍스트는 여기서 연다.
    """
    started = time.monotonic()
    error = ''
    if not isinstance(params, dict):
        params = {}
    try:
        with app.app_context():
            from aot.databases.models import User
            user = User.query.filter(User.unique_id == user_uuid).first() \
                if user_uuid else None
            if user is None:
                raise RpcError(-32001, "This connection is not tied to an AoT user, so "
                                       "there are no AI cards to show.")
            if method == 'resources/templates/list':
                return {"resourceTemplates": []}
            if method == 'resources/read' and _read_limited(user.id):
                raise RpcError(-32000, 'rate limited')
            if method == 'resources/list':
                return _list(user, params)
            if method == 'resources/read':
                return _read(user, params)
            raise RpcError(-32601, 'Method not found: %s' % method)
    except RpcError as exc:
        error = '%d %s' % (exc.code, exc.message)
        raise
    except Exception as exc:                  # 안쪽 사정은 밖에 내지 않는다
        error = repr(exc)[:200]
        logger.exception('[ai_card_resources] %s 실패', method)
        raise RpcError(-32603, 'Internal error')
    finally:
        _audit(method, params, agent_id, transport, session_key, started, error)
