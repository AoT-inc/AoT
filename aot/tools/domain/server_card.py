# -*- coding: utf-8 -*-
"""날씨·장소 요약 카드를 서버가 직접 올린다 — 설계 plans/mcp_act_say_split_design.md §4 #1·§8(카드 결정 A, 2026-10-29).

글로 시킨 카드("한 장 올려라", `card_hint`)는 절반 남짓 빠졌다(10-18~10-29 claude.ai 실측: 위치를 앞·뒤로 옮겨도 40~45%).
반드시 일어나야 할 일은 서버가 한다 — 지도 슬라이더를 서버가 옮긴 뒤 문제가 사라진 선례와 같다. 도메인 틀 출구에서
장소 요약(overview.place)·날씨(weather.now·weather.forecast) 조회가 성공하면 그 데이터로 카드를 만들어 AI 가 쓰는 길과
**같은 길**(`screen_action` action=post — 감사·한도·화면 허용·수신함이 같다)로 올리고, 응답에는 올렸다는 사실(`card`)만 싣는다.
AI 는 말만 한다. 결론 한 줄을 덧붙이는 것은 AI 의 선택 호출(`next.optional`)이다.

카드 글은 사용자 언어다(AI 가 올리던 카드가 그랬다) — 웹 화면과 같은 번역 체계(flask_babel, translations/*/messages.po)를
쓰고, 언어는 그 사용자의 언어 설정(`User.language`), 없으면 앱의 언어 선택(`.language` 시스템 언어 …)을 따른다. MCP 컨테이너에는
요청 문맥이 없어 가짜 요청 문맥을 연다(`screen_follow._slow_message` 와 같은 방식). 새 설정 칸은 없다. 값·단위는 그대로 둔다.

올리지 않는 때: 설정 '자동 카드'(card_auto_enabled) 꺼짐 · 이 묶음에 화면 도구가 없음 · `_show_on_screen='off'` ·
카드로 접을 값이 없음. 외부 연결이 아니거나 사용자가 없으면 이 출구의 일이 아니다(인앱 AI 는 `card_hint` 를 그대로 받는다).
실패한 조회는 카드도 `card_hint` 도 싣지 않는다.

응답(2026-10-30 점검): 성공한 조회에는 **언제나** `card` 한 칸이 있다 — `{state: posted|already_shown|skipped, reason?, title?}`.
`skipped` 는 까닭(`reason`)을 적고, 서버가 일부러 올리지 않은 경우(`screen_off`·`card_auto_off`·`no_screen_tool`·
`nothing_to_show`·`auto_card_budget`)에는 AI 에게 카드를 만들라고 하지 않는다. 올리려다 못 했을 때(`post_failed: …`, 여러 화면 중 고르지 못함 등)만
`next.call` 로 AI 가 올릴 길을 남긴다. 같은 카드는 두 번 오르지 않는다 — 올리는 길이 같아
`ai_screen_cards.DUPLICATE_WINDOW` 안의 같은 제목·본문은 건너뛴다(`already_shown`).
"""
import json
import logging
import threading
import time

from flask_babel import lazy_gettext as lg

from aot.tools.domain import display_names

logger = logging.getLogger(__name__)

#: 서버가 카드를 올리는 조회 — 안쪽 도구가 `ai_screen_cards.card_hint_always_tools()` 인 operation 과 같다.
OPS = {('overview', 'place'): 'place', ('weather', 'now'): 'now', ('weather', 'forecast'): 'forecast'}
MAX_LINES = 5
_EXTERNAL = frozenset({'mcp_http', 'mcp_stdio', 'rest'})
#: 결론 한 줄 — AI 의 선택 호출(사용자 결정 2026-10-29).
OPTIONAL_CALL = "only to add a one-line conclusion: screen(op='card', title='%s', text='<conclusion>')"
#: 서버가 올리려다 못 했을 때만 — AI 가 같은 제목으로 올릴 길(여러 화면 중 고르기 등은 그 호출의 오류가 말한다).
CALL_IF_FAILED = "screen(op='card', title='%s', text='<one-line conclusion, max 5 lines>')"
#: 서버 자동 카드(장소·날씨·값)의 사용자별 분당 상한 — 수신함 한도(`ai_screen_cards.RATE_PER_MIN`=6)의 나머지는 AI 몫이다.
#: 26-11-08 실사용: 하루씩 나눈 이력 조회 7번이 자동 카드 7장을 올려 한도를 다 쓰고, AI 가 올리려던 요약 카드가 막혔다.
AUTO_PER_MIN = 3
_AUTO_LOCK = threading.Lock()
_AUTO_SENT = {}


def take_auto_slot(user, now=None):
    """자동 카드 한 장을 올려도 되면 자리를 잡고 True. 동시 호출(병렬 조회)도 잠금 안에서 센다 — DB 로 세면 같은 순간의
    호출들이 모두 빈자리를 본다."""
    if not user:
        return True
    now = time.monotonic() if now is None else now
    with _AUTO_LOCK:
        sent = [t for t in _AUTO_SENT.get(user, ()) if now - t < 60.0]
        ok = len(sent) < AUTO_PER_MIN
        if ok:
            sent.append(now)
        _AUTO_SENT[user] = sent
        return ok


def post_for(app, tool, op, out, ctx, show=None):
    """조회 응답 `out` 을 보고 카드를 올린다. 성공한 응답에는 `card`(올렸음·이미 있음·건너뜀+까닭)를 싣고 옛 안내(`card_hint`)를 뗀다."""
    kind = OPS.get((tool, op))
    if kind is None:
        return out
    try:
        body = json.loads(out[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return out
    if not isinstance(body, dict):
        return out
    why = skip_reason(ctx, show)
    if why == 'not_external':
        return out                                          # 인앱 AI 의 길 — 안내를 그대로 둔다
    if not _ran_ok(body):
        return _reply(out, body, None) if _has_hint(body) else out    # 실패한 조회에 "카드를 만들라" 를 남기지 않는다
    if why:
        return _reply(out, body, {'state': 'skipped', 'reason': why})
    try:
        card = in_user_locale(app, ctx.get('scope_user_uuid'), lambda: compose(kind, body))
    except Exception:                                       # noqa: BLE001
        logger.exception('[server_card] compose failed')
        card = None
    if not card:
        return _reply(out, body, {'state': 'skipped', 'reason': 'nothing_to_show'})
    title, message = card
    if not take_auto_slot(ctx.get('scope_user_uuid')):
        # 일부러 올리지 않은 경우다 — AI 에게 대신 올리라고 하지 않는다(그 카드가 다시 한도를 쓴다).
        return _reply(out, body, {'state': 'skipped', 'reason': 'auto_card_budget'})
    got = _post(app, title, message, ctx)
    state = got.get('status') if isinstance(got, dict) else None
    if state in ('posted', 'skipped'):
        return _reply(out, body, {'state': 'posted' if state == 'posted' else 'already_shown', 'title': title},
                      optional=OPTIONAL_CALL % title.replace("'", ''))
    err = str((got or {}).get('error') or state or 'no answer') if isinstance(got, dict) else 'no answer'
    logger.info('[server_card] not posted (%s)', err)
    return _reply(out, body, {'state': 'skipped', 'reason': 'post_failed: ' + err[:70], 'title': title},
                  call=CALL_IF_FAILED % title.replace("'", ''))


def _reply(out, body, card, optional=None, call=None):
    """`card` 를 응답 앞쪽(상태 다음)에 싣고 옛 안내를 뗀다. `optional`·`call` 은 `next` 에 한 줄."""
    drop_hints(body)
    if card is not None:
        head = {'status': body['status']} if 'status' in body else {}
        body = {**head, 'card': card, **{k: v for k, v in body.items() if k not in ('card', 'status')}}
    extra = {k: v for k, v in (('optional', optional), ('call', call)) if v}
    if extra:
        nxt = body.get('next') if isinstance(body.get('next'), dict) else {}
        body['next'] = dict(nxt, **extra)
    return [dict(out[0], text=json.dumps(body, ensure_ascii=False, default=str))] + list(out[1:])


def skip_reason(ctx, show=None):
    """서버가 카드를 올리지 않는 까닭, 올릴 수 있으면 None. `not_external` 은 이 출구의 일이 아님(인앱·사용자 없음)."""
    ctx = ctx or {}
    if ctx.get('transport') not in _EXTERNAL or not ctx.get('scope_user_uuid'):
        return 'not_external'
    try:
        from aot.tools import screen_follow
        if screen_follow._parse_show(show)[0] == 'off':
            return 'screen_off'
        profile = ctx.get('tool_profile')
        if profile is not None:
            from aot.tools import tool_registry as R
            if not R.tool_in_profile('screen_action', profile):
                return 'no_screen_tool'
        from aot.utils import ai_screen_cards as cards
        return None if cards.card_auto_enabled() else 'card_auto_off'
    except Exception:                                       # noqa: BLE001
        logger.debug('[server_card] eligibility check failed', exc_info=True)
        return 'check_failed'


def eligible(ctx, show=None):
    return skip_reason(ctx, show) is None


def _has_hint(body):
    return 'card_hint' in body or any(isinstance(r, dict) and isinstance(r.get('result'), dict)
                                       and 'card_hint' in r['result'] for r in body.get('results') or ())


def drop_hints(body):
    body.pop('card_hint', None)
    for row in body.get('results') or ():
        inner = row.get('result') if isinstance(row, dict) else None
        if isinstance(inner, dict):
            inner.pop('card_hint', None)


def _ran_ok(body):
    return not (body.get('status') in ('error', 'refused', 'rejected', 'expired', 'needs_disambiguation',
                                       'not_found', 'pending_approval')
                or body.get('error') or body.get('call_state') in ('failed', 'refused'))


def _post(app, title, message, ctx):
    """AI 의 카드와 같은 길 — 이 대화가 지정해 둔 화면이 있으면 그 화면으로."""
    from aot.tools import screen_follow
    from aot.tools.tool_execution import _execute_tool
    args = {'action': 'post', 'title': title, 'message': message}
    key = screen_follow.designated_screen(ctx.get('scope_user_uuid'), ctx.get('session_key'))
    if key:
        args['screen'] = key[:12]
    res = _execute_tool(app, 'screen_action', args, **ctx)
    try:
        return json.loads(res[0]['text'])
    except (TypeError, ValueError, KeyError, IndexError):
        return None


# ── 카드 글(사용자 언어) ──────────────────────────────────────────────────

def _t(text, **kw):
    """번역(flask_babel) — 문맥이 없거나 실패하면 원문. 이름이 `_t` 라 `pybabel extract -k _t` 가 문구를 모은다."""
    try:
        from flask_babel import gettext
        return gettext(text, **kw)
    except Exception:                                       # noqa: BLE001
        return text % kw if kw else text


def _text(lazy):
    try:
        return str(lazy)
    except Exception:                                       # noqa: BLE001
        args = getattr(lazy, '_args', None)
        return str(args[0]) if args else ''


#: 측정 이름(예보 열 'temperature_2m (°C)', 관측·요약 'temperature' …) → 화면과 같은 이름표. 앞부분이 맞는 첫 줄을 쓴다
#: (precipitation_probability 가 precipitation 보다 먼저). 모르는 이름은 그대로 둔다.
_LABELS = (
    ('temperature', lg('Temperature')),
    ('relative_humidity', lg('Humidity')),
    ('humidity', lg('Humidity')),
    ('dew_point', lg('Dew Point')),
    ('vapour_pressure_deficit', lg('VPD')),
    ('vapor_pressure_deficit', lg('VPD')),
    ('vpd', lg('VPD')),
    ('wind_speed', lg('Wind Speed')),
    ('speed', lg('Wind Speed')),
    ('wind_direction', lg('Wind Direction')),
    ('precipitation_probability', lg('Chance of rain')),
    ('precipitation', lg('Precipitation')),
    ('rain', lg('Rain')),
    ('shortwave_radiation', lg('Solar Radiation')),
    ('solar', lg('Solar Radiation')),
    ('light', lg('Solar Radiation')),
    ('cloud_cover', lg('Cloud cover')),
    ('sky_condition', lg('Cloud cover')),
    ('soil_moisture', lg('Soil Moisture')),
    ('volumetric_water_content', lg('Soil Moisture')),
    ('moisture', lg('Moisture')),
    ('pressure', lg('Pressure')),
)


def in_user_locale(app, user_id, fn):
    """fn() 을 그 사용자의 언어로 돌린다. 언어를 못 정하면 앱의 기본 선택, 문맥을 못 열면 원문(영어)."""
    try:
        if app is None:
            from flask import current_app
            app = current_app._get_current_object()
    except Exception:                                       # noqa: BLE001
        return fn()
    try:
        from flask_babel import force_locale
        with app.test_request_context():
            lang = ''
            try:
                from aot.databases.models import User
                user = User.query.filter(User.unique_id == user_id).first()
                lang = (getattr(user, 'language', None) or '').strip()
            except Exception:                               # noqa: BLE001
                pass
            if lang:
                with force_locale(lang):
                    return fn()
            return fn()
    except Exception:                                       # noqa: BLE001
        logger.debug('[server_card] localisation failed', exc_info=True)
        return fn()


def compose(kind, body):
    """(제목, 본문) 또는 None. 본문은 MAX_LINES 줄 안의 값뿐이다(해석·권고는 AI 몫)."""
    if kind == 'forecast':
        return _forecast_card(body)
    if kind == 'now':
        return _now_card(body)
    if kind == 'place':
        return _place_card(body)
    return None


def _name_of(body):
    for path in (('read_as', 'target', 'name'), ('answered_for', 'name'), ('place', 'name'), ('target', 'name')):
        cur = body
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur:
            return str(cur)
    return None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    return ('%.1f' % v).rstrip('0').rstrip('.') if v != int(v) else str(int(v))


def _measure(name):
    """측정 이름 → 사용자 언어 이름표."""
    k = str(name).strip().lower().replace(' ', '_')
    for prefix, label in _LABELS:
        if k.startswith(prefix):
            return _text(label) or str(name)
    return str(name)


def _label(key):
    """'temperature_2m (°C)' → ('온도', ' °C')."""
    key = str(key)
    if key.endswith(')') and ' (' in key:
        name, unit = key[:-1].split(' (', 1)
        return _measure(name), ' ' + unit
    return _measure(key), ''


#: 예보 줄 순서 — 사람이 먼저 보는 것부터.
_FIRST = ('temperature', 'precipitation (', 'precipitation', 'relative_humidity', 'humidity', 'wind')


def _rank(key):
    k = str(key).lower()
    return next((i for i, w in enumerate(_FIRST) if k.startswith(w)), len(_FIRST))


def _summary_lines(summary, limit):
    lines = []
    for key in sorted(summary, key=_rank):
        blk = summary[key]
        if not isinstance(blk, dict):
            continue
        name, unit = _label(key)
        if 'sum' in blk:
            line = _t("%(name)s total %(value)s%(unit)s", name=name, value=_num(blk['sum']), unit=unit)
            if blk.get('first_at'):
                line += _t(", from %(at)s", at=blk['first_at'])
        elif blk.get('min') is not None and blk.get('max') is not None:
            line = _t("%(name)s %(low)s–%(high)s%(unit)s (max %(at)s)", name=name, low=_num(blk['min']),
                      high=_num(blk['max']), unit=unit, at=blk.get('max_at') or '?')
        else:
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _forecast_summary(result):
    if not isinstance(result, dict):
        return None
    if isinstance(result.get('summary'), dict) and result['summary']:
        return result['summary']
    rows = result.get('forecasts')
    if isinstance(rows, list) and rows and not (result.get('period') or {}).get('daily'):
        from aot.tools.data_tools import weather_summary as ws
        folded = ws.summarize_forecast(dict(result, status='success'))
        return folded.get('summary') if isinstance(folded, dict) else None
    return None


def _daily_lines(rows, limit):
    lines = []
    for r in rows[:limit]:
        if not isinstance(r, dict):
            continue
        vals = ["%s %s" % (_label(k)[0], _num(v)) for k, v in r.items()
                if k not in ('date', 'day_offset') and isinstance(v, (int, float)) and not isinstance(v, bool)][:3]
        if vals:
            lines.append("%s: %s" % (r.get('date') or '?', ", ".join(vals)))
    return lines


def _period_line(body):
    p = body.get('period') if isinstance(body.get('period'), dict) else {}
    start, end = str(p.get('start') or ''), str(p.get('end') or '')
    if not start:
        return None
    short = lambda t: t[5:16].replace('T', ' ') if len(t) >= 16 else t
    if end:
        return _t("%(start)s → %(end)s, model forecast", start=short(start), end=short(end))
    return _t("from %(start)s, model forecast", start=short(start))


def _fan_title(body, rows, singular, plural):
    """여러 장소를 펼친 읽기의 제목 — 같은 질문은 같은 제목이어야 중복이 걸러진다.
    사용자가 말한 그릇(`target`, 예: 김제)이 있으면 그 이름, 없고 한 곳뿐이면 그 장소 이름, 그 밖에는 이름 없는 제목."""
    name = _name_of(body)
    if not name and len(rows) == 1:
        name = (rows[0].get('target') or {}).get('name')
    return (singular % {'place': name}) if name else plural


def _forecast_card(body):
    results = body.get('results')
    if isinstance(results, list) and results:
        lines = []
        for row in results[:MAX_LINES]:
            inner = row.get('result') if isinstance(row, dict) else None
            summ = _forecast_summary(inner)
            if not summ:
                continue
            name = ((row.get('target') or {}).get('name')) or '?'
            lines.append("%s: %s" % (name, "; ".join(_summary_lines(summ, 2))))
        if not lines:
            return None
        return _fan_title(body, results, _t("%(place)s forecast"), _t("Forecast")), "\n".join(lines)
    name = _name_of(body)
    summ = _forecast_summary(body)
    head = _period_line(body)
    lines = [head] if head else []
    room = MAX_LINES - len(lines)
    if summ:
        lines += _summary_lines(summ, room)
    elif isinstance(body.get('forecasts'), list):
        lines += _daily_lines(body['forecasts'], room)
    if len(lines) <= (1 if head else 0):
        return None
    return (_t("%(place)s forecast", place=name) if name else _t("Forecast")), "\n".join(lines)


def _now_lines(rows):
    lines = []
    for r in rows[:MAX_LINES]:
        if not isinstance(r, dict):
            continue
        ended = r.get('last') is not None               # 끝난 구간 — 마지막 값이 아니라 범위가 그 기간의 날씨다
        value = r.get('last') if ended else r.get('latest')
        if value is None:
            continue
        u = (' ' + str(r['unit'])) if r.get('unit') else ''
        chance = r.get('measurement') == 'precipitation' and r.get('unit') == 'percent'    # 강수 확률 채널
        name = _measure('precipitation_probability' if chance else r.get('measurement') or '?')
        if r.get('sum') is not None:
            lines.append(_t("%(name)s total %(value)s", name=name, value=_num(r['sum']) + u))
            continue
        spread = r.get('min') is not None and r.get('max') is not None
        if ended and spread:
            lines.append("%s %s–%s%s" % (name, _num(r['min']), _num(r['max']), u))
            continue
        line = "%s %s%s" % (name, _num(value), u)
        if spread:
            line += " (%s–%s)" % (_num(r['min']), _num(r['max']))
        lines.append(line)
    return lines


def _observed_rows(body):
    rows = body.get('summary')
    if not isinstance(rows, list):
        data = body.get('data')
        if isinstance(data, list) and data:
            from aot.tools.data_tools import weather_summary as ws
            rows = (ws.summarize_observed(dict(body)) or {}).get('summary')
    return rows if isinstance(rows, list) else None


def _period_word(body):
    """이 조회가 읽은 기간의 이름표 — 지금이면 None. 사람이 물은 말(`asked`)에서 만든다(읽은 범위 글은 영어 설명이다)."""
    block = (body.get('read_as') or {}).get('period') if isinstance(body.get('read_as'), dict) else None
    block = block or body.get('period')
    asked = str((block or {}).get('asked') or '').strip() if isinstance(block, dict) else ''
    low = asked.lower()
    if low in ('', 'now', '지금'):
        return None
    if low in ('today', '오늘'):
        return _t("today")
    if low in ('yesterday', '어제'):
        return _t("yesterday")
    if low in ('this_week', 'week', '이번주', '이번 주'):
        return _t("this week")
    if low[:-1].isdigit() and low[-1:] in ('h', 'd'):
        return _t("last %(span)s", span=low)
    short = lambda t: t[5:16].replace('T', ' ').replace('t', ' ') if len(t) > 10 else t[5:10]
    a, sep, b = asked.partition('/')
    a, b = a.strip(), b.strip()
    if not sep or not b:
        return short(a)
    if a[:10] == b[:10] and len(a) > 10 and len(b) > 10:    # 같은 날의 시간대
        return "%s–%s" % (short(a), short(b)[6:])
    return "%s–%s" % (short(a), short(b))


def _now_title(body, name):
    word = _period_word(body)
    if word:
        return (_t("%(place)s weather, %(period)s", place=name, period=word) if name
                else _t("Weather, %(period)s", period=word))
    return _t("%(place)s weather now", place=name) if name else _t("Weather now")


def _now_card(body):
    results = body.get('results')
    if isinstance(results, list) and results:                # 그릇(예: 김제)을 안의 장소로 펼친 읽기 — 장소마다 한 줄
        lines = []
        for row in results[:MAX_LINES]:
            inner = row.get('result') if isinstance(row, dict) else None
            vals = _now_lines(_observed_rows(inner) or []) if isinstance(inner, dict) else []
            if vals:
                lines.append("%s: %s" % (((row.get('target') or {}).get('name')) or '?', "; ".join(vals[:2])))
        if not lines:
            return None
        name = _name_of(body) or ((results[0].get('target') or {}).get('name') if len(results) == 1 else None)
        return _now_title(body, name), "\n".join(lines)
    lines = _now_lines(_observed_rows(body) or [])
    if not lines:
        return None
    return _now_title(body, _name_of(body)), "\n".join(lines)


def _avg_line(label, group, limit=3):
    vals = []
    for m, v in (group or {}).items():
        if isinstance(v, dict) and v.get('avg') is not None:
            unit = v.get('unit_label') or display_names.names(m, v.get('unit'))[1] or v.get('unit')    # °C·% (원문 'C'·'percent' 아님)
            vals.append("%s %s%s" % (_measure(m), _num(v['avg']), (' ' + str(unit)) if unit else ''))
        if len(vals) >= limit:
            break
    return "%s: %s" % (label, ", ".join(vals)) if vals else None


def _place_card(body):
    sensors = body.get('sensors') if isinstance(body.get('sensors'), dict) else {}
    inside = {k: v for k, v in sensors.items() if k not in ('outdoor', 'soil')}
    lines = [l for l in (_avg_line(_t("Air"), inside), _avg_line(_t("Outdoor"), sensors.get('outdoor')),
                         _avg_line(_t("Soil"), sensors.get('soil'))) if l]
    alert = body.get('alert')
    if isinstance(alert, dict) and alert.get('count'):
        lines.append(_t("Alerts: %(n)s", n=alert['count']))
    stale = body.get('stale_sensors')
    if isinstance(stale, dict) and stale.get('count'):
        lines.append(_t("Silent sensors: %(n)s", n=stale['count']))
    plots = body.get('plots')
    if isinstance(plots, list) and plots:
        lines.append(_t("Plots: %(n)s", n=len(plots)))
    elif isinstance(plots, dict) and plots.get('count'):
        lines.append(_t("Plots: %(n)s", n=plots['count']))
    if not lines:
        return None
    name = _name_of(body)
    return (_t("%(place)s summary", place=name) if name else _t("Summary")), "\n".join(lines[:MAX_LINES])
