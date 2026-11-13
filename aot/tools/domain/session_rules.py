# -*- coding: utf-8 -*-
"""MCP 세션 단위로 응답 맨 앞에 싣는 것 — 설계 docs/design/mcp-domain-surface.md F-16.

claude.ai 는 서버 안내문(instructions)을 모델에 넘기지 않는다 — 도구 설명과 **응답 본문**만 닿는다. 그래서 지침에만
있던 핵심 규칙을 응답으로 옮기되, 매 응답에 반복하지 않고 세션마다 한 번만 싣는다.

- ``rules``      — 세션의 첫 도구 응답에 한 번(②). 말하기·이름·현재 시각·사용자가 말한 시각.
- ``correction`` — 같은 세션에서 규칙을 어긴 바로 그 호출의 응답에 짧은 한 줄(④). 같은 교정은 세션당 한 번.
  (a) 예보를 읽은 직후 AI 가 screen 으로 지도 시간을 직접 옮김 — weather 의 at/focus 로 서버가 옮긴다.
  (b) 같은 호출(같은 인자)이 같은 이유로 또 거절됨 — 거절이 말한 대로 고치지 않고 다시 보냈다.
- 승인 대기 기억(⑤) — 이 세션이 이미 되읽어 물은 승인 번호. 서버가 같은 요청의 기존 대기를 돌려줄 때(`mcp_safety_gate`)
  이 세션이 이미 물었으면 다시 묻지 않게, 다른 대화가 만든 대기면 되읽기를 그대로 싣게 가른다.

세션 열쇠: stdio 는 프로세스마다 하나(`StdioMCPServer._session_key`), HTTP 는 `Mcp-Session-Id` 헤더(initialize 응답에서
준 값을 클라이언트가 되돌려 보낸다). **열쇠가 없으면 싣지 않는다** — 첫 응답을 가릴 수 없어 매 응답에 반복하게 되고,
교정의 "세션당 한 번" 도 지킬 수 없다(그때는 지침과 응답 안 지시(must·next)만 남는다). 열쇠는 사용자와 묶는다
(헤더는 클라이언트가 정하는 값이라 다른 사용자의 같은 값과 섞이면 안 된다).

상태는 이 프로세스의 메모리다(HTTP 서버는 한 프로세스, stdio 는 연결 하나). 재시작하면 새 세션처럼 규칙이 한 번 더
실린다 — 잃어도 되는 값이다. stdout 에 쓰지 않는다(stdio 는 stdout 이 프로토콜이다).
"""
import json
import threading
import time

#: 첫 응답 규칙(②) — 지침(SPEAKING·UUID·TIME·MAP TIME)의 핵심만, 짧게. 응답 크기 상한 안(약 100토큰).
RULES = (
    "Speak: never narrate tools or steps; give the result in 1-2 sentences.",
    "Never show raw UUIDs or data keys; use names and *_label values.",
    "Current time: only `now`; other timestamps are past events.",
    "Weather: at=<time> for a time the user names; a forecast also needs focus=max|min|rain_start|HH:MM|range (range: whole span). The server moves the map.",
)
#: 교정 한 줄(④).
CORRECT_MAP_TIME = "next time pass at=<time> and focus (max|min|rain_start|HH:MM|range) in weather; the map moves itself"
CORRECT_REPEAT = "this exact call was refused the same way before; change it as must/next says, do not resend it"

#: 예보 '직후' 로 보는 시간.
FORECAST_WINDOW_S = 600
#: 세션 상태를 버리는 시간과 최대 개수.
_TTL_S = 12 * 3600
_MAX = 2048
#: 거절로 보는 상태.
_REFUSED = frozenset({'error', 'refused'})

_lock = threading.Lock()
_sessions = {}


class _State(object):
    __slots__ = ('seen', 'ruled', 'forecast_at', 'refusal', 'corrected', 'asked')

    def __init__(self, now):
        self.seen = now
        self.ruled = False
        self.forecast_at = None
        self.refusal = None
        self.corrected = set()
        self.asked = set()


def _key(user_id, session_key):
    if not session_key:
        return None
    return (str(user_id or ''), str(session_key))


def _state(key, now):
    """세션 상태(없으면 새로). _lock 안에서 부른다."""
    st = _sessions.get(key)
    if st is None:
        if len(_sessions) >= _MAX:
            for k in [k for k, v in _sessions.items() if now - v.seen > _TTL_S]:
                _sessions.pop(k, None)
            if len(_sessions) >= _MAX:
                oldest = min(_sessions, key=lambda k: _sessions[k].seen)
                _sessions.pop(oldest, None)
        st = _sessions[key] = _State(now)
    st.seen = now
    return st


def reset():
    """시험용 — 모든 세션 상태를 비운다."""
    with _lock:
        _sessions.clear()


# ── 승인 대기 기억(⑤) ──────────────────────────────────────────────────────────

def remember_asked(user_id, session_key, confirmation_id, now=None):
    key = _key(user_id, session_key)
    if key is None or not confirmation_id:
        return
    now = time.monotonic() if now is None else now
    with _lock:
        _state(key, now).asked.add(str(confirmation_id))


def was_asked(user_id, session_key, confirmation_id):
    """이 세션이 이 승인 번호를 이미 되읽어 물었는가. 세션 열쇠가 없으면 모른다 — False(다시 되읽게)."""
    key = _key(user_id, session_key)
    if key is None:
        return False
    with _lock:
        st = _sessions.get(key)
        return bool(st is not None and str(confirmation_id) in st.asked)


# ── 응답 머리(②·④) ─────────────────────────────────────────────────────────────

def _is_map_time_move(tool, arguments):
    a = arguments or {}
    return tool == 'screen' and a.get('op') == 'act' and a.get('action') == 'map_control' \
        and a.get('map_op') == 'time'


def _named_time(arguments):
    """예보 조회가 시각을 이미 알렸는가 — focus, 또는 '지금' 이 아닌 at."""
    a = arguments or {}
    from aot.tools.screen_follow import focus_valid
    if focus_valid(a):
        return True
    at = str(a.get('at') or '').strip().lower()
    return bool(at) and at not in ('now', 'current', 'today')


def _signature(tool, arguments):
    try:
        return json.dumps([tool, arguments or {}], ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return None


def annotate(content, tool, arguments, session_key, user_id, rules=True, now=None):
    """도구 응답(content 블록 목록)의 첫 JSON 사전 맨 앞에 correction·rules 를 싣는다. 바꿀 것이 없으면 그대로.

    rules: 첫 응답 규칙을 실을 수 있는 표면인가(도메인 표면 — 규칙이 weather 의 at·focus 를 가리킨다)."""
    key = _key(user_id, session_key)
    if key is None:
        return content
    try:
        body = json.loads(content[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        body = None
    if not isinstance(body, dict):
        body = None
    now = time.monotonic() if now is None else now
    status = body.get('status') if body else None
    correction = None
    add_rules = False
    with _lock:
        st = _state(key, now)
        # (a) 예보 직후 지도 시간을 직접 옮겼다.
        if _is_map_time_move(tool, arguments) and st.forecast_at is not None \
                and now - st.forecast_at <= FORECAST_WINDOW_S and 'map_time' not in st.corrected:
            st.corrected.add('map_time')
            correction = CORRECT_MAP_TIME
        if tool == 'weather' and (arguments or {}).get('op') == 'forecast' and status not in _REFUSED:
            # at·focus 로 시각을 이미 알렸으면(화면이 여럿이라 서버가 못 옮긴 경우 등) 직접 옮겨도 교정하지 않는다.
            st.forecast_at = None if _named_time(arguments) else now
        # (b) 같은 호출, 같은 거절.
        if status in _REFUSED:
            sig = (_signature(tool, arguments), body.get('reason_code'))
            if sig[0] is not None and st.refusal == sig and 'repeat' not in st.corrected and correction is None:
                st.corrected.add('repeat')
                correction = CORRECT_REPEAT
            st.refusal = sig
        elif body is not None:
            st.refusal = None
        if body is not None and rules and not st.ruled:
            st.ruled = True
            add_rules = True
    if body is None or (correction is None and not add_rules):
        return content
    head = {}
    if correction:
        head['correction'] = correction
    if 'must' in body:
        head['must'] = body.pop('must')
    if add_rules:
        head['rules'] = list(RULES)
    body = {**head, **body}
    return [dict(content[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(content[1:])
