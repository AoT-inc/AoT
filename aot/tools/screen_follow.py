# -*- coding: utf-8 -*-
"""화면 따라가기 — AI 가 조회한 장소·구획·장치의 창을 사용자 화면에 함께 연다 (2026-10).

"3포장 상태 요약해 줘" 를 받은 AI 는 get_place_overview 로 정보를 모은다. 사용자가
그 화면에서 "AI 화면 조작 허용" 을 켜 두었다면, 같은 순간 그 화면의 지도에서
3포장 창이 열려야 한다(사용자 2026-10-10).

AI 에게 정보 도구 다음에 화면 도구를 또 부르게 하지 않는다. 모델이 자주 빠뜨리고
왕복이 는다. 대신 **실행층이 정보 도구의 대상을 보고** 화면 명령을 넣는다. 응답에는
무엇을 했는지 한 줄만 붙인다(AI 가 말로 알려 줄 수 있게).

막는 겹은 screen_action 과 같다:
- 키: screen_action 이 보이는 묶음만(운영 이상 — 2026-10-10 에 키 단위 모듈을
  없애고 운영에 넣었다). 외부 전송(MCP·REST)만 — 인앱 AI 는 제외.
- 기기: 그 화면에서 "AI 화면 조작 허용" 을 켰고, 지금 보고 있는 화면이 하나로
  정해질 때만(둘 이상이 겹치면 짐작하지 않는다).
- 위치 확인: "AI 화면 조작 허용" 을 켠 기기는 [허용] 카드 없이 바로 연다(2026-10-20 —
  `web_presence.auto_confirmed`). 오래 조용했던 화면이나 기기별 따라가기 '묻기'면 그 화면에
  [허용] 카드를 띄운다. 도구 응답은 기다리지 않는다 — 정보 답이 늦어지면 안 된다.

여는 것은 대시보드의 지도 위젯 창, 그것이 안 되면 그 장치를 보여 주는 위젯 강조다.

2026-10-11 고친 것 — "따라가기가 동작하지 않는다" 의 원인이 둘이었다:
- 따라가는 도구가 셋뿐이었다. 실제 대화에서 AI 는 list_plots·get_crop_status·
  get_control_state·get_output_state 로 답했고 따라가기는 한 번도 불리지 않았다.
- 화면이 '보는 중'(75초 안 요청)일 때만 움직였다. 폰에서 AI 앱으로 대화하면 AoT
  탭은 뒤에 있어 조용히 아무것도 안 했다. 이제 명령을 넣어 두고 링크를 돌려준다 —
  링크를 누르면 그 화면이 열리며 밀린 명령을 가져간다.

같은 날 두 번째 — "AI 가 설명할 때 화면이 안 따라간다": AI 가 '콩 2구' 를
resolve_target 으로 풀고 list_plots(구역) 로 설명했다. 이름 풀기는 따라가지 않았고,
구역 조회는 (막 연 창이라) 건너뛰었다 — 화면은 앞 대상에 머물렀다. 이제 푼 결과로
열고, 막 연 것을 감싸는 장소로는 창을 되돌리지 않는다(`_shows_inside`).

2026-10-12 혼합안(A6) — 무엇을 열지는 서버가 정하고, AI 는 호출 옵션으로 끄거나
화면을 고른다:
- 엄격 열기: 대상이 id 로 왔거나(결과에 실린 id 포함) 이름이 **정확히 하나**를
  가리킬 때만 연다. 부분 일치·무시된 말(ignored_terms)·같은 이름 여러 곳·숫자나
  띄어쓰기만 다른 이웃 이름('육묘장' 과 '육묘장3')이면 열지 않고 `not_opened` 에
  후보와 "사용자에게 물어볼 것" 을 싣는다. 짐작해 연 창은 AI 의 설명과 어긋난다.
- 화면 고르기: 숨은 탭(visibilityState)은 '보는 중' 이 아니다. 보이는 화면이 둘
  이상이면 고르지 않고 후보 screen·기기 이름을 돌려준다.
- 기기별 따라가기: 끔 / 묻기(늘 [허용] 카드) / 자동(기본) — 화면 조작 허용과 따로.
- 호출별 `_show_on_screen`: 'off'(이번 조회는 화면을 바꾸지 않는다) 또는 get_screen
  의 screen id(그 화면에). 도구 스키마에는 없다 — 실행층이 떼어 넘긴다.

2026-10-12 보완(A6 후속):
- 화면 조작 허용이 꺼진 기기를 보고 있으면 아무것도 붙이지 않는다(조회마다 이유가
  붙던 것을 없앴다). 따라가기만 "끔" 이면 `{'follow': 'off', 'note': …}` 로 알린다 —
  둘은 다르다(허용 꺼짐=조용, 따라가기 끔=알림).
- 처리기가 이름을 푼 결과에 `target_id`/`target_type` 을 싣는다(`_with_target`). 따라가기는
  그 id 로 바로 열고, 이름 재해석(`_resolve` 의 리졸버 경로)은 id 가 없을 때의 예비다.
- 처리기가 부분 일치로 푼 대상('육묘장 구획' → 시설 '육묘장')은 열지 않는다. 처리기가
  결과에 `match`('id'|'exact'|'partial')와 무시된 말(`ignored_terms`)을 싣고, partial 이면
  not_opened 에 푼 대상·이웃 이름을 후보로 담아 사용자에게 되묻게 한다(`match_of`).

2026-10-20 개선 (조사 `.local/reports/screen_follow_investigation_20261019.md`):
- 결과를 기록한다: 응답 `screen` 칸 요약(opened/asked/queued/not_opened + 이유, 조용히
  건너뛴 이유)을 읽기 호출의 `mcp_audit_log.result_summary` 에 덧붙이고(`audit_note`),
  화면이 끝낸 명령의 감사 기록(`screen.command`)에 출처 `[follow]`/`[explicit]` 를 붙인다.
- 중복 판정은 명령 이력이 아니라 **화면이 알려 온 열린 창**(`_open_now`)과 아직 끝나지 않은
  명령(`pending_open_item`)으로 한다. 화면이 이미 다른 창으로 바뀌었으면 다시 연다.
- 연달아 읽으면 마지막 대상만 남는다: 전달 전인 따라가기 명령은 새 명령이 대체한다
  (`web_presence.add_command`).
- 다른 대시보드에 있는 대상은 묻지 않고 그 대시보드로 옮겨 연다(`_plan`). 단 사용자가 입력·출력·
  설정 같은 **대시보드가 아닌 페이지**를 보고 있으면 옮기지 않는다(2026-10-30 체험: 입력 작업 중 지도로
  끌려갔다) — 응답 `screen.not_opened` 에 이유와 보여 주는 대시보드, 링크만 싣는다.
  그 대상을 보여 주는 대시보드가 하나일 때만 — 여럿이면 후보를 돌려 AI 가 묻게 한다. 이동 뒤의
  열기는 화면이 그 대시보드에 도착했다고 알릴 때까지 붙잡아 둔다(`hold_for`).
"""
import json
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

#: 따라가는 정보 도구 → (대상 인자들, 종류 힌트). 앞의 인자부터 본다. 목록 인자는
#: 대상이 하나일 때만 따라간다(여럿이면 무엇을 열지 짐작하지 않는다). 종류 힌트가
#: None 이면 이름·id 로 푼다(대지·구역·시설·구획·장치).
FOLLOW_TOOLS = {
    'get_place_overview':      (('place',), None),
    'get_plot':                (('plot_id',), 'plot'),
    'get_plot_history':        (('plot_id', 'zone_id'), None),
    'get_device_detail':       (('device_id',), 'device'),
    'get_sensor_reading':      (('device_id', 'device_ids'), 'device'),
    'get_output_state':        (('device_id', 'device_ids'), 'device'),
    'list_plots':              (('zone_id',), None),
    'get_crop_status':         (('facility_id', 'facility_name'), 'facility'),
    'get_control_state':       (('facility_id', 'facility_name'), 'facility'),
    'get_facility_capacity':   (('facility_name',), 'facility'),
    'get_map_equipment':       (('area_name',), None),
    'get_zone_sensor_summary': (('zone_ids',), None),
    # 2026-10-11 더함 — 실제 대화에서 AI 가 '콩 2구' 를 resolve_target 으로 풀고
    # 설명했는데 화면은 그대로였다. 이름을 푼다는 것은 그것을 말하려는 것이다.
    'resolve_target':          (('target_name',), None),
    'list_plot_journals':      (('target_id',), None),
    'get_energy_report':       (('zone_id',), None),
    'get_map_equipment_detail': (('area_name',), None),
    'get_device_measurements': (('device_id',), 'device'),
    'get_device_location':     (('device_id',), 'device'),
    'get_device_freshness':    (('device_id',), 'device'),
    'analyze_system_failure':  (('device_id',), 'device'),
}

#: 결과가 대상을 정확히 알려 주는 도구 — 인자(이름)보다 결과의 id 를 쓴다.
#: 이름은 겹칠 수 있지만 푼 결과는 하나다.
_RESULT_TARGET = {'resolve_target': ('target_id', 'target_type')}
_PLACE_KINDS = frozenset({'site', 'zone', 'facility', 'plot'})

_EXTERNAL = frozenset({'mcp_http', 'mcp_stdio', 'rest'})

#: 조회 도구가 화면을 바꾼 이유 — 외부 AI 가 "읽기 전용인데 화면이 바뀌었다,
#: 승인도 없었다" 로 읽었다(2026-10-11). 저장하는 것이 없고, 그 화면에서 사람이
#: 켜 두고 허락한 것이다. 따라갈 때마다 응답에 실리고 그 응답이 대화에 남아 이후
#: 요청마다 다시 실리므로 짧게 둔다(2026-10-14: 330자 → 80자).
_WHY = ("screen follow (the user allowed it; nothing saved). "
        "_show_on_screen='off' to skip.")


#: 호출별 메타 인자 — 도구 스키마에 넣지 않는다(도구 목록 토큰). 실행층이
#: 실행 전에 인자에서 떼어(`pop_show_arg`) follow 의 show 로 넘긴다.
SHOW_ARGS = ('_show_on_screen', 'show_on_screen')
_SHOW_OFF = frozenset({'off', 'no', 'none', 'false', '0', 'never', '끔', '끄기',
                       '안함', '아니오'})
_SHOW_AUTO = frozenset({'', 'auto', 'yes', 'true', '1', 'on', 'default', '자동'})

#: 조회 결과가 대상을 직접 알려 주는 키(최상위) — 인자의 이름보다 이것을 쓴다.
_RESULT_ID_KEYS = (('device_id', 'device'),)


def pop_show_arg(arguments):
    """인자에서 `_show_on_screen` 을 떼어 (남은 인자, 값) 을 돌려준다. 원본은 두고
    새 dict 를 준다 — 처리기는 모르는 키를 `_ignored_arguments` 로 알리고, 감사
    기록·승인 큐에도 화면 옵션이 섞이지 않게."""
    if not isinstance(arguments, dict) or not any(k in arguments for k in SHOW_ARGS):
        return arguments, None
    rest = dict(arguments)
    value = None
    for k in SHOW_ARGS:
        if k in rest:
            v = rest.pop(k)
            value = v if value is None else value
    return rest, value


#: 날씨 조회에 AI 가 실어 보내는 "답하는 시각" 메타 인자 — `+6h`·`now`·ISO 8601. 도구 스키마에 없다(토큰).
#: 서버가 지도 시간 슬라이더를 그 시각으로 옮기고 화면이 적용했는지 확인한다(2026-10-26).
ANSWER_TIME_ARGS = ('_answer_time', 'answer_time')


def pop_answer_time(arguments):
    """인자에서 `_answer_time` 을 떼어 (남은 인자, 값) 을 돌려준다 — `pop_show_arg` 와 같은 이유로 새 dict."""
    if not isinstance(arguments, dict) or not any(k in arguments for k in ANSWER_TIME_ARGS):
        return arguments, None
    rest = dict(arguments)
    value = None
    for k in ANSWER_TIME_ARGS:
        if k in rest:
            v = rest.pop(k)
            value = v if value is None else value
    return rest, value


def _parse_show(value):
    """`_show_on_screen` → ('auto', None) | ('off', None) | ('screen', id)."""
    if value is None or isinstance(value, bool):
        return ('off', None) if value is False else ('auto', None)
    text = str(value).strip()
    low = text.lower()
    if low in _SHOW_OFF:
        return 'off', None
    if low in _SHOW_AUTO:
        return 'auto', None
    return 'screen', text


def follow(tool_name, arguments, result, user_id, tool_profile, transport,
           show=None, session_key=None):
    """정보 도구가 성공한 뒤 부른다. 화면에 무엇을 했는지 dict, 아무것도 안 했으면
    None. 어떤 실패도 정보 응답을 막지 않는다.

    show: 호출별 `_show_on_screen` 값 — None·'auto' 는 기기 설정대로, 'off' 는
    이번 조회로 화면을 바꾸지 않고, 그 밖의 값은 get_screen 의 screen id 다."""
    try:
        return _follow(tool_name, arguments, result, user_id, tool_profile,
                       transport, show, session_key)
    except Exception:
        logger.debug('screen follow failed', exc_info=True)
        return None


def _target_ref(arguments, names):
    """인자에서 대상 하나 — 목록이면 하나일 때만. 여럿·없음이면 None."""
    for name in names:
        value = (arguments or {}).get(name)
        if isinstance(value, (list, tuple)):
            vals = [str(v).strip() for v in value if str(v or '').strip()]
            if len(vals) == 1:
                return vals[0]
            if vals:
                return None
            continue
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


#: 대화(session_key)마다 AI 가 마지막으로 **직접 지정한** 화면 — `screen`·`_show_on_screen` 으로 고른 것(2026-10-27).
#: 화면이 둘 이상 보이면 서버는 고르지 않는다. 그러나 AI 가 이미 화면 하나를 정해 쓰고 있다면 그 정함을 따라간다(짐작이 아니다).
#: 예전에는 PC+폰이 함께 열려 있으면 예보 조회가 매번 "여러 화면" 으로 끝나 슬라이더가 한 번도 따라가지 않았다.
#: 메모리뿐이고 재시작하면 사라진다 — 다시 지정하면 된다. 값은 화면 열쇠(browser_key).
_SESSION_SCREEN = {}
_SESSION_SCREEN_TTL_S = 3600.0
_SESSION_SCREEN_MAX = 256


def remember_screen(user_id, session_key, screen, now=None):
    """AI 가 `screen`(get_screen 의 화면 번호)을 직접 지정했다 — 실제 화면으로 풀리면 이 대화의 지정 화면으로 적어 둔다."""
    try:
        if not user_id or not screen or not isinstance(screen, str):
            return
        from aot.utils import web_presence as wp
        now = time.time() if now is None else now
        row = wp.resolve_screen(user_id, screen.strip(), now=now)
        if row is None:
            return
        _SESSION_SCREEN[(user_id, session_key or '')] = (row['browser_key'], now)
        if len(_SESSION_SCREEN) > _SESSION_SCREEN_MAX:
            for k in [k for k, v in _SESSION_SCREEN.items() if now - v[1] > _SESSION_SCREEN_TTL_S]:
                _SESSION_SCREEN.pop(k, None)
    except Exception:                                       # noqa: BLE001
        logger.debug('remember_screen failed', exc_info=True)


def designated_screen(user_id, session_key, now=None):
    """이 대화에서 AI 가 직접 지정해 둔 화면의 열쇠(살아 있을 때), 없으면 None — 서버가 올리는 카드도 그 화면으로 간다."""
    saved = _SESSION_SCREEN.get((user_id, session_key or ''))
    now = time.time() if now is None else now
    if not saved or now - saved[1] > _SESSION_SCREEN_TTL_S:
        return None
    return saved[0]


def _designated(rows, user_id, session_key, now):
    """후보 화면(rows) 중 이 대화에서 AI 가 직접 지정해 둔 것, 없으면 None. 지정한 화면이 후보에서 빠졌다면(닫힘·허용 꺼짐·따라가기 꺼짐) 없다."""
    saved = _SESSION_SCREEN.get((user_id, session_key or ''))
    if not saved or now - saved[1] > _SESSION_SCREEN_TTL_S:
        return None
    return next((r for r in rows if r.get('browser_key') == saved[0]), None)


def _pick_screen(user_id, now, screen=None, session_key=None):
    """따라갈 화면 하나와 그 화면이 지금 보이는지 → ((행, 보임), None).
    고르지 못하면 (None, problem) — problem 은 AI 에게 돌려줄 dict 이거나 None(조용히).

    - 이 기기에서 "AI 화면 조작 허용" 을 켠 화면만, 따라가기를 끈 화면은 뺀다.
    - 보이는 화면(visible) 하나면 그것. 둘 이상이면 고르지 않고 후보를 준다 — 예전
      pick_likely 의 "1분 넘게 먼저 손댄 쪽" 판정은 숨은 탭을 보는 중으로 셌던 시절의
      보정이다. 이제 보임을 알므로 보이는 둘 사이에서는 짐작하지 않는다.
    - 아무것도 보이지 않으면(폰에서 AI 앱을 앞에 둔 경우) 열려 있던 화면이 하나일
      때만 그 화면에 넣어 두고 링크를 준다.
    - 보이는 화면이 둘 이상이어도 이 대화에서 AI 가 이미 `screen`·`_show_on_screen` 으로 지정해 쓴 화면이 있으면 그 화면(`_designated`).
    - screen: `_show_on_screen` 으로 지정한 화면(get_screen 의 screen id)."""
    from aot.utils import web_presence as wp
    if screen:
        row = wp.resolve_screen(user_id, screen, now=now)
        if row is None:
            return None, {'not_opened': "no screen '%s' — see get_screen for the "
                                        "user's screens" % screen[:24]}
        if not row.get('ai_allowed'):
            return None, {'not_opened': _off_reason(row)}
        if wp.follow_mode(row) == 'off':
            return None, _follow_off(row)
        if wp.state_of(row, now) == 'away':
            return None, {'not_opened': "that screen (%s) has been closed or idle "
                                        "too long" % (row.get('device') or 'browser')}
        remember_screen(user_id, session_key, screen, now=now)
        return (row, wp.state_of(row, now) == 'viewing'), None
    rows = wp.recent(user_id, now=now)
    allowed = [r for r in rows if r.get('ai_allowed')
               and wp.state_of(r, now) != 'away']
    if not allowed:
        # 화면 조작 허용이 꺼져 있다 — 조회 때마다 이유를 붙이지 않는다(사용자
        # 2026-10-12: "붙지 않게"). 아무 말 없이 지나간다.
        return None, None
    rows = [r for r in allowed if wp.follow_mode(r) != 'off']
    if not rows:
        # 허용은 켰지만 따라가기를 끈 화면 — 허용 꺼짐과 달리 AI 에게 알린다.
        shown = [r for r in allowed if wp.state_of(r, now) == 'viewing'] or allowed
        return None, _follow_off(shown[0])
    viewing = [r for r in rows if wp.state_of(r, now) == 'viewing']
    if len(viewing) == 1:
        return (viewing[0], True), None
    if len(viewing) > 1 or (not viewing and len(rows) > 1):
        chosen = _designated(rows, user_id, session_key, now)
        if chosen is not None:
            return (chosen, wp.state_of(chosen, now) == 'viewing'), None
        return None, _several_screens()
    return (rows[0], False), None


def _follow_off(row):
    """따라가기 끔 — 열지 않았다는 짧은 알림(화면 조작 허용 꺼짐과 구분된다)."""
    return {'follow': 'off',
            'note': ("screen follow is off on %s, so nothing was opened there"
                     % (row.get('device') or 'browser'))}


def _off_reason(row):
    return ("not shown on screen: AI screen control is off on %s — the user can "
            "turn it on in that screen's menu" % (row.get('device') or 'browser'))


#: 화면이 여럿이고 지정된 것이 없어 따라가지 못했다 — 응답에 실리는 한 줄이다. "어느 쪽이냐고 사용자에게 물어라" 같은 안내는 달지 않는다
#: (2026-10-27: 조회마다 붙어 AI 가 화면 지정 인자 이름이 도구마다 다르다는 식의 내부 사정을 길게 말했다). 후보 목록도 싣지 않는다 —
#: AI 가 화면 도구에 `screen` 을 지정하면 그 뒤 조회는 그 화면을 따라간다.
_SEVERAL = 'several screens are showing'


def _several_screens():
    return {'not_opened': _SEVERAL}


def _widget_showing(dashboard_id, ref):
    """그 대시보드에서 그 장치를 보여 주는 위젯 — 지도에 없는 장치를 강조로 따라간다.
    위젯 설정에 장치 id 가 들어 있는지로 본다(이름이면 같은 이름의 장치 id 로)."""
    from aot.databases.models import Input, Output, Widget
    ids = {ref}
    for model in (Input, Output):
        ids.update(r.unique_id for r in model.query.filter(model.name == ref).all())
    for w in (Widget.query.filter(Widget.tab_id == dashboard_id)
              .order_by(Widget.position_y, Widget.position_x).all()):
        opts = w.custom_options or ''
        if any(i and i in opts for i in ids):
            return w
    return None


def _shows_inside(last, args):
    """화면에 방금 연 것(last)이 새로 열 장소(args) 안에 있는가."""
    if not last or last.get('id') == args.get('id'):
        return False
    place, kind = args.get('id'), args.get('kind')
    if kind not in ('site', 'zone', 'facility'):
        return False
    from aot.aot_flask.geo import device_membership as dm
    lkind, lid = last.get('kind'), str(last.get('id') or '')
    if lkind in ('site', 'zone', 'facility'):
        return dm.PlaceIndex().within(lid, place)
    if lkind == 'plot':
        from aot.databases.models import GeoFacility, GeoPlot
        plot = GeoPlot.query.filter(GeoPlot.unique_id == lid).first()
        if plot is None:
            return False
        fac = getattr(plot, 'facility_uuid', None)
        if fac and kind == 'facility':
            row = GeoFacility.query.filter(GeoFacility.unique_id == fac).first()
            if row is not None and row.shape_uuid == place:
                return True
        return dm.PlaceIndex().plot_within(plot, place)
    if lkind == 'device':
        ids = dm.device_ids_in_area(place, include_references=False) or ()
        return lid.split('::')[0] in {str(i).split('::')[0] for i in ids}
    return False


# ── 무엇을 열까 — 엄격 열기 ──────────────────────────────────────────────────

def _norm(text):
    """비교용 — 소문자, 띄어쓰기·밑줄·전각 차이 없앰(`name_key`)."""
    from aot.tools.name_key import name_key
    return name_key(text)


def _digits(text):
    return re.findall(r'\d+', str(text or ''))


def _by_id(ref):
    """id → (kind, id, 이름들) 또는 None. 지도 도형·구획·장치·시설 행 id 를 받는다.
    종류는 site/zone/facility/plot/device 로 — 열 창이 없는 것(설비 등)은 원래
    종류를 둔다(열기에서 걸러진다)."""
    from aot.databases.models import GeoPlot, GeoShape, Input, Output
    ref = str(ref or '').strip().split('::')[0]
    if not ref:
        return None
    sh = GeoShape.query.filter(GeoShape.unique_id == ref).first()
    if sh is not None:
        name = ((sh.feature or {}).get('properties') or {}).get('name') \
            if isinstance(sh.feature, dict) else None
        return (sh.type or 'zone'), sh.unique_id, [name] if name else []
    p = GeoPlot.query.filter(GeoPlot.unique_id == ref).first()
    if p is not None:
        return 'plot', p.unique_id, [n for n in (p.name, p.subject, p.variety) if n]
    for model in (Input, Output):
        row = model.query.filter(model.unique_id == ref).first()
        if row is not None:
            return 'device', row.unique_id, [row.name] if row.name else []
    try:
        from aot.databases.models import GeoFacility
        fac = GeoFacility.query.filter(GeoFacility.unique_id == ref).first()
    except Exception:                                       # noqa: BLE001
        fac = None
    if fac is not None and fac.shape_uuid:
        return 'facility', fac.shape_uuid, [fac.name] if fac.name else []
    return None


def _given_target(tool_name, result):
    """조회 결과가 실어 준 대상 id(정보 도구가 이미 푼 것) — 없으면 None.

    처리기가 이름을 풀었으면 `target_id`(+`target_type`)를 싣는다(resolve_target 과
    같은 이름 — `_with_target`). 구획은 `plot`, 장치는 최상위 `device_id` 가 같은
    역할을 한다."""
    tid = result.get('target_id')
    if tid:
        return str(tid)
    if tool_name in _RESULT_TARGET:
        id_key, _kind_key = _RESULT_TARGET[tool_name]
        return str(result.get(id_key) or '') or None
    plot = result.get('plot')
    if isinstance(plot, dict) and plot.get('unique_id'):
        return str(plot['unique_id'])
    for key, _kind in _RESULT_ID_KEYS:
        if result.get(key):
            return str(result[key])
    return None


def _all_names():
    """이웃 이름 판정용 — 지도 도형·자라는 구획·장치의 이름 [(이름, 종류)]."""
    from aot.aot_flask.geo import shape_index
    from aot.databases.models import GeoPlot, Input, Output
    out = [(r.name, r.type) for r in shape_index.all_shapes()
           if r.name and r.type != 'equipment']
    for p in GeoPlot.query.filter(GeoPlot.ended_on.is_(None)).all():
        out.extend((n, 'plot') for n in (p.name, p.subject) if n)
    for model in (Input, Output):
        out.extend((r.name, 'device') for r in model.query.all() if r.name)
    return out


def _qualifiers():
    """이름 앞에 붙는 장소·지도 이름(정규화) — '김제 1포장', '3포장 3-1' 의 앞부분."""
    from aot.aot_flask.geo import shape_index
    from aot.databases.models import GeoMap
    names = {_norm(r.name) for r in shape_index.all_shapes()
             if r.name and r.type in ('site', 'zone', 'facility')}
    try:
        names.update(_norm(m.name) for m in GeoMap.query.all() if m.name)
    except Exception:                                       # noqa: BLE001
        pass
    return names


def _names_exactly(ref, names):
    """사람이 말한 ref 가 그 대상의 이름(들) 그대로인가 — 띄어쓰기·대소문자만
    무시한다. 앞에 장소·지도 이름을 붙인 것('3포장 3-1')도 그대로로 친다."""
    want = {_norm(n) for n in names if n}
    if _norm(ref) in want:
        return True
    words = str(ref or '').split()
    quals = None
    for cut in range(1, len(words)):
        if _norm(' '.join(words[cut:])) in want:
            quals = _qualifiers() if quals is None else quals
            if all(_norm(w) in quals for w in words[:cut]):
                return True
    return False


def _neighbours(ref, own_names):
    """숫자·띄어쓰기만 다른 다른 이름 — 사람이 숫자를 빠뜨렸거나 잘못 들은 것일 수
    있다('육묘장' 이라 했는데 '육묘장3' 도 있다). 말한 숫자를 그 이름이 다 품지
    않으면 다른 것을 분명히 가리킨 것이라 이웃이 아니다('콩 2구' 와 '콩 3구')."""
    key = re.sub(r'\d+', '', _norm(ref))
    if not key:
        return []
    mine = {_norm(n) for n in own_names if n}
    said = _digits(ref)
    seen, out = set(), []
    for name, kind in _all_names():
        n = _norm(name)
        if n in mine or n in seen or re.sub(r'\d+', '', n) != key:
            continue
        if not _subsequence(said, _digits(name)):
            continue
        seen.add(n)
        out.append('%s (%s)' % (name, kind))
    return out


def _subsequence(short, long_):
    """short 의 숫자들이 순서대로 long_ 안에 있는가 — 말한 숫자를 다 품은 이름만
    이웃이다('육묘장' ⊂ '육묘장3'). 다른 숫자를 말했으면('콩 2구' 와 '콩 3구') 아니다."""
    it = iter(long_)
    return all(any(x == y for y in it) for x in short)


def _ask(ref, why, candidates):
    out = {'not_opened': "'%s' %s — ask the user which one they mean; nothing was "
                         "opened on the screen" % (ref, why)}
    if candidates:
        out['candidates'] = candidates[:6]
    return out


def _partial(ref, hit, ignored=()):
    """처리기가 부분 일치로 푼 대상 — 열지 않고, 푼 대상과 이웃 이름을 후보로 준다."""
    label = '%s (%s)' % ((hit[2] or [ref])[0], hit[0])
    why = ("was only partly matched (not used: %s)" % ' '.join(ignored)
           if ignored else 'was only partly matched')
    return _ask(ref, why, [label] + [n for n in _neighbours(ref, hit[2])
                                     if n != label])


def match_of(ref, ident, exact=False):
    """처리기가 이름 `ref` 로 푼 대상 `ident` 의 해석 방식 → (match, ignored_terms).

    match: 'id'(id 로 지정) | 'exact'(이름이 그대로) | 'normalized'(공백·밑줄·전각·대소문자만 다른 같은 이름 — `name_key`,
    exact 처럼 안전하게 연다) | 'partial'(일부만 맞음·무시된 말).
    exact=True 는 처리기의 리졸버가 이름·id 정확일치만 받는 경우(시설 등) — 다시 풀지 않는다.
    처리기가 결과에 싣는다(`_with_target`). 실패하면 (None, [])."""
    ref = str(ref or '').strip()
    if not ref:
        return None, []
    try:
        if ref.split('::')[0] == str(ident) or _by_id(ref) is not None:
            return 'id', []
        if exact:
            return 'exact', []
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        d = S._resolve_explain(ref)
        ignored = list(d.get('ignored_terms') or [])
        rule = (d.get('matched') or {}).get('rule')
        hit = _by_id(ident)
        if ignored or rule not in (None, 'exact', 'normalized') or (
                hit is not None and not _names_exactly(ref, hit[2])):
            return 'partial', ignored
        if rule == 'normalized':
            return 'normalized', []
        return 'exact', []
    except Exception:                                       # noqa: BLE001
        logger.debug('screen follow: match_of failed', exc_info=True)
        return None, []


def _candidates(ref):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    out = []
    for c in (S._ambiguous_places(ref) or []):
        label = c.get('use_name') or c.get('name') or ref
        where = c.get('where')
        out.append('%s (%s%s)' % (label, c.get('type') or '?',
                                  ', %s' % where if where else ''))
    return out


def _resolve(tool_name, arguments, result, ref):
    """열 대상 → ((kind, id), None) | (None, not_opened dict) | (None, None).

    id 로 왔거나(인자·결과) 이름이 정확히 하나를 가리킬 때만 연다."""
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    given = _given_target(tool_name, result)
    if given and tool_name not in _RESULT_TARGET:
        # 처리기가 이미 푼 대상 — 이름을 다시 풀지 않고 그 id 로 연다. 정보 응답이
        # 말하는 대상과 화면에 여는 대상이 어긋나지 않는다. 다만 처리기는 '육묘장 구획'
        # 을 시설 '육묘장'으로 부분 일치해 풀기도 한다 — 결과의 `match` 가 그것을 말한다:
        # id·지정(구획·장치 도구) 이면 열고, partial 이면 열지 않고 묻는다. exact 거나 표시가
        # 없으면 아래 이름 검사(이웃·같은 이름)를 거친다.
        hit = _by_id(given)
        if hit is not None:
            match = result.get('match')
            if (match == 'id' or ref is None or _by_id(ref) is not None
                    or not result.get('target_id')):
                return (hit[0], hit[1]), None
            ignored = result.get('ignored_terms') or []
            if match == 'partial' or ignored:
                return None, _partial(ref, hit, ignored)
    if ref is None or _by_id(ref) is not None:
        hit = _by_id(given or ref)
        return ((hit[0], hit[1]), None) if hit else (None, None)
    # id 가 없을 때의 예비 — 정보 도구가 쓰는 리졸버로 이름을 다시 보되, 짐작한
    # 단계는 받지 않는다.
    try:
        d = S._resolve_explain(ref)
    except Exception:                                       # noqa: BLE001
        logger.debug('screen follow: resolve failed', exc_info=True)
        return None, None
    tid, ttype = d['result'][0], d['result'][1]
    if ttype == 'ambiguous':
        return None, _ask(ref, 'names several places', _candidates(ref)
                          or [str(getattr(r, 'name', '') or '') for r, _k
                              in (d.get('devices') or [])][:6])
    if d.get('ignored_terms'):
        return None, _ask(ref, "was only partly matched (not used: %s)"
                          % ' '.join(d['ignored_terms']), [d['result'][2]]
                          if tid else [])
    matched = d.get('matched') or {}
    if matched and matched.get('rule') not in (None, 'exact', 'normalized'):
        return None, _ask(ref, 'was only partly matched', [d['result'][2]])
    if not tid and given:
        tid = given                       # 리졸버가 못 푼 이름(시설 표 이름 등)
    if not tid:
        fac = S._resolve_facility(ref)
        tid = getattr(fac, 'shape_uuid', None)
    hit = _by_id(tid) if tid else None
    if hit is None:
        return None, None
    if given and given != hit[1]:
        other = _by_id(given)
        if other is not None and other[1] != hit[1]:
            return None, _ask(ref, 'could mean more than one thing', [
                '%s (%s)' % ((h[2] or ['?'])[0], h[0]) for h in (hit, other)])
    if not _names_exactly(ref, hit[2]):
        return None, _ask(ref, 'was only partly matched', [
            '%s (%s)' % ((hit[2] or ['?'])[0], hit[0])])
    near = _neighbours(ref, hit[2])
    if near:
        return None, _ask(ref, 'has similar names', [
            '%s (%s)' % ((hit[2] or [ref])[0], hit[0])] + near)
    return (hit[0], hit[1]), None


def _follow(tool_name, arguments, result, user_id, tool_profile, transport,
            show=None, session_key=None):
    spec = FOLLOW_TOOLS.get(tool_name)
    if spec is None or transport not in _EXTERNAL or not user_id:
        return None
    if not isinstance(result, dict) or result.get('status') == 'error' \
            or result.get('error'):
        return None
    from aot.tools import tool_registry as R
    if tool_profile is None or not R.tool_in_profile('screen_action', tool_profile):
        return None
    how, screen = _parse_show(show)
    if how == 'off':
        return None        # AI 가 이번 조회는 화면을 바꾸지 말라고 했다
    names, _kind = spec
    ref = _target_ref(arguments, names)
    if tool_name in _RESULT_TARGET and (result.get('status') != 'success'
                                        or not _given_target(tool_name, result)):
        return None        # 모호함·못 찾음 — 결과가 이미 후보를 말했다
    if not ref and not _given_target(tool_name, result):
        return None        # 농장 전체 요약·여러 대상 — 열 창이 없다

    from aot.utils import web_presence as wp
    now = time.time()
    picked, problem = _pick_screen(user_id, now, screen=screen, session_key=session_key)
    if picked is None:
        return problem
    target, visible = picked

    found, problem = _resolve(tool_name, arguments, result, ref)
    if found is None and problem is None and _kind == 'device' and ref:
        # 장치 표에 없는 id(다른 노드의 장치 등)는 지도 창이 없다 — 그 id 를 그대로
        # 실은 위젯이 있으면 강조로 따라간다(정확히 같은 id 만).
        found = ('device', ref)
    if found is None:
        return problem
    return _open(found[0], found[1], _kind, user_id, target, visible, now)


#: 예보를 읽는 순간 슬라이더를 서버가 옮긴다(2026-10-24 시작, 2026-10-27 AI 안내 제거). AI 에게 "예보 뒤 슬라이더도 옮겨라" 를
#: 시키는 방식은 안내 문구를 바꿀 때마다 반대쪽으로 실패했고(옮기고 값을 말하지 않음 ↔ 값만 말하고 안 옮김), 그 안내가 AI 의
#: 혼잣말에 되풀이되어 음성 모드에서 소리로 나갔다("Preferences say: … move the map time slider …"). 그래서 서버가 혼자 정한다:
#: 질문의 시작 시각(없거나 now·today 면 지금)이 슬라이더의 대표 시각이다. AI 는 슬라이더를 몰라도 되고, 응답에도 싣지 않는다.
TIME_FOLLOW_TOOLS = frozenset({'get_weather_forecast'})
#: 슬라이더가 닿는 범위(지금 기준 시간) — screen_action 의 op=time 한도와 같은 말이다(-2시간 ~ +7일).
_TIME_RANGE_H = (-2.0, 7 * 24.0)
#: 한 질문에 여러 장소를 읽으면 AI 는 병렬로 부른다 — 다른 시각을 가리키는 호출이 10초 안에 또 오면 둘 중 어느
#: 시각이 맞는지 서버는 모른다. 먼저 옮긴 것이 있으면 뒤의 것은 옮기지 않고 AI 에게 맡긴다.
_TIME_CONFLICT_S = 10.0
_LAST_TIME_FOLLOW = {}


#: 서버가 슬라이더를 옮긴 예보 응답에 싣는 힌트(2026-10-27). 현재 슬라이더 시각을 알려 주므로 AI 는 따로 확인 호출 없이 비교만 하면 된다. 서버는 질문의 시작 시각으로 먼저 옮겨 둔다 — 도구를 막 불러온 AI 가
#: 실수하기 쉬운 첫 조회의 안전망이다. 그러나 답이 가리키는 시각(최고·최저·비 시작 …)은 **결과를 읽은 뒤에야** 정해지므로
#: 그 판단과 이동은 AI 가 한다. 약한 문구("직접 판단하라")는 AI 가 따르지 않았고, "직접 옮겨라" 안내는 따랐다(10-27 기록) —
#: 그래서 특정 시각을 말하는 답에는 옮기라고 분명히 쓴다. 안내는 서버 지침이 아니라 이 응답에만 실어, 대화 시작 때부터
#: AI 의 혼잣말에 규칙이 남지 않게 한다. 말하지 말라는 꼬리표(SILENT_NOTE)가 붙는다.


#: 서버가 못 옮겨 현재 슬라이더 시각을 모르는 경우 — 여러 화면, 같은 순간 다른 시각의 예보가 먼저 옮겼음(병렬 호출). 어느 쪽이든 답이 가리키는
#: 시각으로 AI 가 옮겨야 한다(2026-10-27: 병렬 두 호출이 충돌로 끝나 힌트가 없었고 AI 는 옮기지 않았다).
_UNKNOWN_TIME = frozenset({'not moved: ' + _SEVERAL, 'not moved: another forecast just set a different time'})


#: 같은 조회가 화면을 다른 대시보드로 옮겼다 — 이동이 페이지를 다시 읽어 막 넣은 명령이 사라진다. AI 가 이동 뒤에 직접 옮길 수 있다.
_CHANGING = 'the screen was changing dashboards in this call, so the time was not set'


#: 힌트 끝의 말하지 말라는 꼬리표 — 공통 SILENT_NOTE("Internal note: …")는 AI 가 힌트를 '지킬 규칙'이 아니라 '읽고 넘길 참고 문구'로
#: 취급하게 했다(2026-10-27 AI 자기 설명). 이 힌트는 해야 할 일을 시키므로 명령형으로 쓰고, 말하지 말라는 것은 행동에만 건다.
_HINT_TAIL = " Do not tell the user about this or the call; reply only in the user's language."


def time_hint_for(user_id, moved, domain=False):
    """이번 예보 조회 응답에 붙일 힌트(글) 또는 None. 응답의 **맨 앞**에 싣는다 — 끝에 두면 AI 가 앞쪽 숫자만 읽고 답했다.

    서버가 이번에 슬라이더를 옮겼을 때(`sent to …`)는 현재 시각을 알려 주는 힌트를, 화면이 여럿이라 고르지 못했거나 다른 예보가 먼저 다른 시각으로
    옮겼을 때(`_UNKNOWN_TIME`)는 AI 가 직접 옮기라는 짧은 힌트를 낸다 — 이때 현재 슬라이더 시각은 서버도 모른다. 그 밖의 못 옮김(화면 없음·백그라운드)은
    AI 가 옮길 곳도 없으므로 내지 않는다."""
    slider = str((moved or {}).get('slider') or '')
    if not user_id:
        return None
    # 도메인 표면의 AI 는 `screen_action` 이 아니라 `screen(op=act …)` 를 부른다 — 부를 호출을 그 이름으로 정확히 적는다.
    call = ("screen(op=act, action=map_control, map_op=time, value=full ISO time)" if domain
            else "action=map_control, time op, value=full ISO time")
    if slider in _UNKNOWN_TIME:
        return ('Do this before you answer: the server did not set the map time for this lookup. If your answer is about a '
                'specific time, first make one screen call (%s, screen=<id> if several screens are open), then answer once. '
                'The current map time is unknown.' % call) + _HINT_TAIL
    if not slider.startswith('sent to '):
        return None
    return ('Do this before you answer: the map shows %s (set by the server). If your answer is about a different time '
            '(the peak or low you name, when rain starts …), first make one screen call (%s), then answer once - never '
            'before and again after the call. If it already matches, or you speak about the whole range, skip the call.'
            % (slider[len('sent to '):].strip(), call)) + _HINT_TAIL


#: 계약 op(`domain.act_say`)의 지도 시간 — 글(`time_hint`) 대신 기계용 next 한 칸. 할 호출과 그 조건만 담고 "말하지 마라" 꼬리는
#: 없다(규약 1: next 는 하되 말하지 않는다).
_TIME_CALL = "screen(op='act', action='map_control', map_op='time', value='<full ISO time>')"


def time_next_for(user_id, moved):
    """도메인 계약 op 의 `next.map_time` 또는 None. 옮겼으면 보이는 시각, 못 옮겼거나 가리킨 시각을 못 골랐으면 `{moved: False, why}`."""
    slider = str((moved or {}).get('slider') or '')
    if not user_id:
        return None
    if slider in _UNKNOWN_TIME:
        return {"shows": "unknown", "if_answer_names_one_time": _TIME_CALL,
                "why": "the server could not set it; add screen='<id>' if several screens are open"}
    if slider.startswith('not moved: '):
        # 서버가 옮기려 했으나 못 옮겼다(또는 가리킨 시각을 못 골랐다) — 조용히 두지 않고 까닭을 한 줄 싣는다(2026-10-30 점검).
        why = slider[len('not moved: '):].strip()
        out = {"moved": False, "why": why[:140]}
        if why == _CHANGING:
            out["if_answer_names_one_time"] = _TIME_CALL
        return out
    if not slider.startswith('sent to '):
        return None
    return {"shows": slider[len('sent to '):].strip(), "if_answer_names_another_time": _TIME_CALL}


def follow_time(tool_name, arguments, result, user_id, tool_profile, transport,
                show=None, answer_time=None, session_key=None):
    """예보 조회가 성공한 뒤 부른다 — 사용자 지도의 시간 슬라이더를 그 시각으로 옮긴다.

    ``{'slider': '<한 줄>'}`` 또는 None(조용히 건너뜀). 한 줄(`sent to …` | `not moved: …`)은 **감사 기록용**이다 — 실행층이
    기록한 뒤 응답에서 뗀다. AI 에게 보이지 않고, AI 가 할 일을 말하지도 않는다. 어떤 실패도 예보 응답을 막지 않는다.

    answer_time: AI 가 `_answer_time` 으로 알려 준 답하는 시각(선택). 주면 서버가 정한 시각 대신 그 시각으로 옮긴다.
    화면이 적용했는지 기다리지 않는다 — 기다림은 예보 응답을 늦추고, 알려 줄 사람도 없다.
    막는 겹은 화면 따라가기와 같다: 외부 AI · 화면 조작이 이 묶음에 있음 · `_show_on_screen` 끄지
    않음 · "AI 화면 조작 허용" 을 켠 화면이 **하나로 정해짐** · 지금 보이는 화면."""
    try:
        return _follow_time(tool_name, arguments, result, user_id, tool_profile,
                            transport, show, answer_time, session_key)
    except Exception:
        logger.debug('screen follow (time) failed', exc_info=True)
        return None


#: 질문이 '지금부터' 를 가리키는 말 — 슬라이더는 지금이다. 평면 도구는 `start`, 도메인 날씨는 `at`(시각)·`period`(기간)로 말한다.
_NOW_WORDS = frozenset({'', 'now', 'current', 'today', '24h', '7d', 'this_week'})


def _result_period(result):
    """(period, 시간대) — 평면 응답은 최상위, 도메인 날씨는 `results[0].result` 안에 있다."""
    inner = result
    # 도메인 응답의 최상위 `period` 는 {'asked','read'} 라 구간 시작이 없다 — 시작이 있는 쪽을 찾는다.
    if not (result.get('period') or {}).get('start'):
        rows = result.get('results')
        first = (rows[0] or {}).get('result') if isinstance(rows, list) and rows else None
        if isinstance(first, dict):
            inner = first
    tz_name = inner.get('timezone') or ((inner.get('answered_for') or {}).get('tz'))
    return inner.get('period') or {}, tz_name


def _time_target(arguments, result):
    """(옮길 시각, 사람이 읽는 글) 또는 None.

    질문이 지금부터를 가리키면(시작이 없거나 now·today·24h·7d …) 슬라이더는 '지금'(`'now'`)이다. 내일·날짜·구간처럼
    다른 시각을 가리키면 응답이 알려 준 구간 시작을 그 장소의 현지 시각으로 옮긴다 — 구간 길이는 보지 않는다. 응답에서
    구간 시작을 못 읽거나 지난 날(yesterday)이면 건드리지 않는다.
    """
    import datetime as _dt
    if not isinstance(arguments, dict) or not isinstance(result, dict):
        return None
    # 도메인 날씨는 시작 시각을 `at` 으로 준다(안쪽 `start`). 이름을 몰라 'now' 로 읽으면 "점심(12:00)" 을 물어도 슬라이더가 지금에 머문다
    # (2026-10-30 점검: at=15:00 인데 `sent to now`).
    kind = str(arguments.get('start') or arguments.get('at') or arguments.get('period') or '').strip().lower()
    if kind in _NOW_WORDS:
        return 'now', 'now'
    period, tz_name = _result_period(result)
    if not period.get('start') or not tz_name:
        return None
    from zoneinfo import ZoneInfo
    at = _dt.datetime.fromisoformat(str(period['start'])).replace(tzinfo=ZoneInfo(str(tz_name)))
    delta_h = (at - _dt.datetime.now(_dt.timezone.utc)).total_seconds() / 3600.0
    # 지금이 속한 시간 칸(시작 ≤ 지금 < 시작+1h)은 '지금' 이다 — 칸 시작(몇십 분 전)으로 되돌리지 않는다.
    if -1.0 < delta_h <= 0:
        return 'now', 'now'
    if not _TIME_RANGE_H[0] <= delta_h <= _TIME_RANGE_H[1]:
        return None
    return at.isoformat(), '%s (%s)' % (at.strftime('%Y-%m-%d %H:%M'), tz_name)


#: 답이 가리키는 순간 — AI 가 조회 때 `focus` 로 알려 주면 서버가 응답에서 그 시각을 골라 슬라이더를 옮긴다(2026-10-27).
#: 결과를 읽고 난 뒤 화면 호출을 하나 더 하라는 안내(지침·도구 설명·힌트)는 AI 가 따르지 않았다 — 조회 인자를 채우는 일은 한다.
FOCUS_VALUES = frozenset({'max', 'min', 'rain_start'})


def _focus_inner(result):
    """focus 를 고를 응답 본문 — 도메인 날씨는 `results[0].result` 안에 있다."""
    if not isinstance(result.get('forecasts'), list) and not isinstance(result.get('summary'), dict):
        rows = result.get('results')
        first = (rows[0] or {}).get('result') if isinstance(rows, list) and rows else None
        if isinstance(first, dict):
            return first
    return result


def _first_wet_day(rows):
    """일 행에서 비가 처음 오는 날짜(없으면 None)."""
    for r in rows if isinstance(rows, list) else ():
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            if str(k).startswith('precipitation') and 'prob' not in str(k) \
                    and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return r.get('date')
    return None


def _focus_pick(arguments, result):
    """`focus`(max·min·rain_start) 가 가리키는 시각 → ((ISO, 글) 또는 None, 못 골랐을 때의 까닭 한 줄 또는 None).

    까닭은 AI 가 읽으므로 짧고 사실만 적는다. focus 를 주지 않았거나 모르는 값이면 (None, None)."""
    import datetime as _dt
    focus = str((arguments or {}).get('focus') or '').strip().lower()
    if focus not in FOCUS_VALUES or not isinstance(result, dict):
        return None, None
    period, tz_name = _result_period(result)
    inner = _focus_inner(result)
    if not tz_name:
        return None, '%s: the answer has no time zone' % focus
    if period.get('daily'):
        return None, '%s: the answer is daily rows (no hours); ask 72 h or less for an hour' % focus
    local = None
    forecasts = inner.get('forecasts')
    summary = inner.get('summary')
    rain = lambda k: k.startswith('precipitation (')
    if isinstance(forecasts, list) and forecasts:
        keys = [k for k in forecasts[0] if k not in ('hour_offset', 'time', 'date')]
        if focus == 'rain_start':
            key = next((k for k in keys if rain(k)), None)
            hit = next((r for r in forecasts if isinstance(r.get(key), (int, float)) and r[key] > 0), None) if key else None
            local = (hit or {}).get('time')
        else:
            key = next((k for k in keys if k.startswith('temperature')), None)
            pts = [(r.get('time'), r.get(key)) for r in forecasts if key and isinstance(r.get(key), (int, float))]
            if pts:
                pick = (max if focus == 'max' else min)(pts, key=lambda p: p[1])
                local = pick[0]
    elif isinstance(summary, dict):
        if focus == 'rain_start':
            key = next((k for k in summary if rain(k)), None)
            short = (summary.get(key) or {}).get('first_at') if key else None
        else:
            key = next((k for k in summary if k.startswith('temperature')), None)
            short = ((summary.get(key) or {}).get('max_at' if focus == 'max' else 'min_at')) if key else None
        start = str(period.get('start') or '')
        if short and len(short) == 11 and len(start) >= 4:       # 'MM-DD HH:MM' — 연도는 구간 시작에서
            local = '%s-%s' % (start[:4], short.replace(' ', 'T'))
    if not local:
        if focus != 'rain_start':
            return None, '%s: no temperature in the hourly rows' % focus
        end = str(period.get('end') or '')[:16].replace('T', ' ')
        day = _first_wet_day(inner.get('daily_forecasts'))
        if day:
            return None, ('rain_start: none in the hourly rows (to %s); the first rain is on %s in daily rows, '
                          'hour unknown' % (end[5:] if end else '?', day))
        return None, 'rain_start: no rain in the hours read (to %s)' % (end[5:] if end else '?')
    from zoneinfo import ZoneInfo
    try:
        at = _dt.datetime.fromisoformat(str(local)).replace(tzinfo=ZoneInfo(str(tz_name)))
    except ValueError:
        return None, '%s: the hour could not be read' % focus
    delta_h = (at - _dt.datetime.now(_dt.timezone.utc)).total_seconds() / 3600.0
    if not _TIME_RANGE_H[0] <= delta_h <= _TIME_RANGE_H[1]:
        return None, '%s: %s is outside the map time range (-2 h to +7 days)' % (focus, at.strftime('%m-%d %H:%M'))
    return (at.isoformat(), '%s (%s)' % (at.strftime('%Y-%m-%d %H:%M'), tz_name)), None


def _focus_target(arguments, result):
    """`focus`(max·min·rain_start) 가 가리키는 시각 → (ISO, 글) 또는 None. 범위 밖이거나 못 읽으면 None."""
    return _focus_pick(arguments, result)[0]


def _follow_time(tool_name, arguments, result, user_id, tool_profile, transport, show,
                 answer_time=None, session_key=None):
    if tool_name not in TIME_FOLLOW_TOOLS or transport not in _EXTERNAL or not user_id:
        return None
    if not isinstance(result, dict) or result.get('status') != 'success':
        return None
    from aot.tools import tool_registry as R
    if tool_profile is None or not R.tool_in_profile('screen_action', tool_profile):
        return None
    how, screen = _parse_show(show)
    if how == 'off':
        return None
    if answer_time not in (None, ''):
        iso = text = str(answer_time).strip()[:40]
    else:
        asked = str((arguments or {}).get('focus') or '').strip().lower() in FOCUS_VALUES
        # AI 가 가리킨 순간(focus)을 응답에서 못 찾았으면(비가 안 옴·일 단위 …) 시작 시각으로 대신 옮기지 않는다 — 엉뚱한 시각을 보이느니 그대로 둔다.
        if asked:
            when, why = _focus_pick(arguments, result)
            if when is None:
                return {'slider': 'not moved: ' + why} if why else None      # 까닭은 응답에도 한 줄(`time_next_for`)
        else:
            when = _time_target(arguments, result)
        if when is None:
            return None
        iso, text = when
    shown = result.get('screen')
    if isinstance(shown, dict) and 'after moving the screen' in json.dumps(shown, ensure_ascii=False):
        # 같은 조회가 화면을 다른 대시보드로 옮겼다 — 이동이 페이지를 다시 읽어 지금 넣는 명령은 사라진다.
        return {'slider': 'not moved: ' + _CHANGING}

    from aot.utils import web_presence as wp
    now = time.time()
    picked, problem = _pick_screen(user_id, now, screen=screen, session_key=session_key)
    if picked is None:
        if (problem or {}).get('not_opened') == _SEVERAL:
            return {'slider': 'not moved: ' + _SEVERAL}     # 힌트(`time_hint_for`)가 AI 에게 직접 옮기라고 알린다
        return None                 # 화면 조작 허용이 꺼짐 등 — 따라가기 칸이 이미 이유를 말한다
    target, visible = picked
    if not visible:
        return {'slider': 'not moved: that screen is in the background'}
    ask_mode = wp.follow_mode(target) == 'ask'
    if ask_mode or not (wp.auto_confirmed(target, now) or wp.has_grant(target, now)):
        return None                 # 슬라이더 때문에 [허용] 카드를 띄우지 않는다
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    args, problem = S._screen_map_control_args(target, None, 'time', iso, None, None)
    if args is None:
        # 이 화면에 지도가 없다 / 시각을 읽지 못했다 — 기록에만 남긴다.
        return {'slider': 'not moved: %s' % str(problem)[:100]}
    prev = _LAST_TIME_FOLLOW.get(user_id)
    if prev and now - prev[0] < _TIME_CONFLICT_S and prev[1] != iso:
        return {'slider': 'not moved: another forecast just set a different time'}
    if wp.recent_command_count(user_id, now=now) + 1 > wp.RATE_PER_MIN:
        return None
    cid, _tok = wp.add_command(user_id, target['browser_key'], 'map_control', args, confirmed=True,
                               now=now, source=wp.FOLLOW_SOURCE, ttl_s=wp.QUEUE_TTL_S)
    _LAST_TIME_FOLLOW[user_id] = (now, iso, cid)
    wp.extend_grant(target['browser_key'], now=now)
    return {'slider': 'sent to %s' % text}


# ── 느린 조회 중 안내 자막 (2026-10-26) ─────────────────────────────────────────────────────────────────
# 사용자는 AI 가 말없이 일하는 동안 고장인지 알 수 없다. 개발서버 기록으로 가장 긴 침묵은 서버의 첫 예보 조회(20~34초)였다.
# AI 가 "작업 중" 카드를 띄우게 하지 않고 — 카드는 수신함에 쌓이고 AI 가 따라야 하며 정작 느린 서버 조회 동안은 그대로 조용하다 —
# 서버가 느린 읽기 도중에 화면 자막(수신함·미읽음에 남지 않는 일회성 안내)을 직접 띄운다. 화면 쪽은 옛 `toast` 명령이 그
# 자막(`AoTAICards.notice`)으로 이어져 있어 JS 를 바꾸지 않는다. AI 의 협조도 서버 지침 토큰도 필요 없다.
#: 조회가 이만큼 걸리면 첫 안내를 띄운다. 그 전에 끝나는 조회(중앙값 0.3초)는 아무것도 보이지 않는다.
SLOW_NOTICE_FIRST_S = 2.5
#: 자막은 4초면 사라진다(`NOTICE_MS`) — 아직 기다리는 중이면 이 간격으로 다시 띄운다. 분당 명령 한도(12)를 다 쓰지 않게 6초.
SLOW_NOTICE_EVERY_S = 6.0
SLOW_NOTICE_MAX = 4
#: 최근 1분에 이만큼 넘게 명령이 나갔다면 안내를 아낀다 — 안내가 진짜 화면 명령의 한도를 먹지 않게.
SLOW_NOTICE_ROOM = 8
#: 안내가 소용없는 도구 — 화면을 직접 다루거나(그 응답을 기다리는 화면 조작) 승인·스키마 조회.
_SLOW_NOTICE_SKIP = frozenset({'screen_action', 'get_screen', 'respond_to_confirmation', 'open_drawer',
                               'get_tool_detail', 'screen', 'screen_view'})
#: 이 사용자에게 마지막으로 안내를 보낸 때(monotonic) — 한 질문이 읽기를 여럿 병렬로 불러도 안내가 겹쳐 쌓이지 않는다.
_SLOW_NOTICE_LAST = {}
_SLOW_NOTICE_LOCK = threading.Lock()


def _slow_message(app, user_id):
    """안내 한 줄을 사용자 화면 언어로. 못 만들면 영어 원문."""
    text = 'AI is looking this up…'   # 영어 원문(번역 실패 시)
    try:
        from flask_babel import force_locale, gettext
        from aot.databases.models import User
        with app.test_request_context():
            user = User.query.filter(User.unique_id == user_id).first()
            lang = (getattr(user, 'language', None) or '').strip()
            if lang:
                with force_locale(lang):
                    return gettext('AI is looking this up…')
            return gettext('AI is looking this up…')
    except Exception:                                       # noqa: BLE001
        logger.debug('slow notice: localisation failed', exc_info=True)
        return text


def _send_slow_notice(app, user_id, tool_profile, transport, show):
    """보이는 화면 하나에 안내 자막 명령을 넣는다 → 넣었으면 True. 어떤 이유로든 못 넣으면 조용히 False."""
    if not eligible(user_id, tool_profile, transport, show):
        return False
    from aot.utils import web_presence as wp
    now = time.time()
    picked, _problem = _pick_screen(user_id, now)
    if picked is None:
        return False
    target, visible = picked
    if not visible:
        return False                # 가려진 탭의 자막은 보이지 않고, 나중에 켜지면 낡은 안내가 된다
    if wp.follow_mode(target) == 'ask' or not (wp.auto_confirmed(target, now) or wp.has_grant(target, now)):
        return False                # 안내 때문에 [허용] 카드를 띄우지 않는다
    if wp.recent_command_count(user_id, now=now) >= SLOW_NOTICE_ROOM:
        return False
    mono = time.monotonic()
    with _SLOW_NOTICE_LOCK:
        last = _SLOW_NOTICE_LAST.get(user_id)
        if last is not None and mono - last < SLOW_NOTICE_EVERY_S - 0.5:
            return False
        _SLOW_NOTICE_LAST[user_id] = mono
        if len(_SLOW_NOTICE_LAST) > 256:
            for k in [k for k, v in _SLOW_NOTICE_LAST.items() if mono - v > 120]:
                _SLOW_NOTICE_LAST.pop(k, None)
    wp.add_command(user_id, target['browser_key'], 'toast',
                   {'message': _slow_message(app, user_id), 'describe': 'show a status line'},
                   confirmed=True, now=now, source=wp.FOLLOW_SOURCE, ttl_s=20.0)
    return True


class slow_read_notice:
    """`with` 로 감싼 읽기가 SLOW_NOTICE_FIRST_S 넘게 걸리면 사용자 화면에 안내 자막을 띄운다(끝나면 멈춘다).

    외부 AI 의 읽기에만 걸린다 — 쓰기는 승인 흐름이 따로 말하고, 화면 조작 도구는 그 응답을 기다리는 화면이다.
    빨리 끝나는 조회는 타이머만 걸었다 푼다(DB·화면 조회 없음)."""

    def __init__(self, app, tool_name, permission, user_id, tool_profile, transport, show=None):
        self._args = (app, user_id, tool_profile, transport, show)
        self._timer = None
        self._done = False
        self._sent = 0
        self._on = (permission == 'read' and tool_name not in _SLOW_NOTICE_SKIP
                    and transport in _EXTERNAL and bool(user_id) and _parse_show(show)[0] != 'off')

    def __enter__(self):
        if self._on:
            self._arm(SLOW_NOTICE_FIRST_S)
        return self

    def __exit__(self, *exc):
        self._done = True
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        return False

    def _arm(self, delay):
        timer = threading.Timer(delay, self._fire)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _fire(self):
        if self._done:
            return
        try:
            if _send_slow_notice(*self._args):
                self._sent += 1
        except Exception:                                   # noqa: BLE001
            logger.debug('slow notice failed', exc_info=True)
        if not self._done and self._sent < SLOW_NOTICE_MAX:
            self._arm(SLOW_NOTICE_EVERY_S)


def eligible(user_id, tool_profile, transport, show=None):
    """이 호출이 화면을 따라갈 자리인가 — 외부 AI 이고, 키 주인이 있고, 화면 조작이 이
    묶음에 있고, 이번 조회에서 끄지 않았다. 대상이 없어 열지 못한 경우를 기록에 남길지
    가르는 데만 쓴다(인앱 AI 의 모든 읽기에 '열지 않음' 을 붙이지 않으려고)."""
    try:
        if transport not in _EXTERNAL or not user_id:
            return False
        from aot.tools import tool_registry as R
        if tool_profile is None or not R.tool_in_profile('screen_action', tool_profile):
            return False
        if _parse_show(show)[0] == 'off':
            return False
        # 화면 조작을 켠 화면이 있을 때만 — 없으면 기록할 만한 놓침이 아니다.
        from aot.utils import web_presence as wp
        now = time.time()
        return any(r.get('ai_allowed') and wp.state_of(r, now) != 'away'
                   for r in wp.recent(user_id, now=now))
    except Exception:                                       # noqa: BLE001
        return False


def follow_resolved(kind, ident, user_id, tool_profile, transport, show=None,
                    trace=None, center_only=False, session_key=None):
    """이미 풀린 대상 하나(종류·id)를 화면에 연다 — 도메인 틀이 부른다.

    틀은 대상을 한 번 풀어 두므로(`targets.resolve`) 어떤 읽기 operation 이든 그 대상을
    따라갈 수 있다. 안쪽 도구 이름 목록(`FOLLOW_TOOLS`)에 기대면 그 목록에 없는 읽기
    (이력·날씨·장치 위치 …)는 따라가지 않는다(2026-10-14 사용자: "지도 위젯에서라고
    해도 텍스트로만 설명한다"). 막는 겹은 `follow` 와 같다.

    trace: 주면 **열지 않은 이유**(조용히 건너뛴 경우)를 한 줄씩 덧붙인다 — 감사 기록에
    남겨 "왜 안 열렸나" 를 사후에 재구성하지 않게 한다(`audit_note`).

    center_only: 창을 열지 않고 지도만 그 대상 가운데로 옮긴다(날씨 설명 — 창이 측정값 패널을
    가린다. 2026-10-25). 지도에 없는 장치의 위젯 강조는 그대로다.
    """
    try:
        if transport not in _EXTERNAL or not user_id or not ident:
            return _note(trace, 'not an external AI call')
        from aot.tools import tool_registry as R
        if tool_profile is None or not R.tool_in_profile('screen_action', tool_profile):
            return _note(trace, 'screen control is not in this tool profile')
        how, screen = _parse_show(show)
        if how == 'off':
            return _note(trace, '_show_on_screen off')
        now = time.time()
        picked, problem = _pick_screen(user_id, now, screen=screen, session_key=session_key)
        if picked is None:
            if problem is None:
                _note(trace, 'no screen with AI control on')
            return problem
        target, visible = picked
        hint = kind if kind in ('site', 'zone', 'facility') else None
        return _open(kind, ident, hint, user_id, target, visible, now, trace=trace,
                     center_only=center_only)
    except Exception:
        logger.debug('screen follow (resolved) failed', exc_info=True)
        return _note(trace, 'follow failed (see debug log)')


def follow_focus(ref, user_id, tool_profile, transport, show=None, trace=None, session_key=None):
    """screen_view 의 focus=<위젯·카드 이름> — AI 가 그것을 설명하려는 순간이므로 사용자 화면을 그 자리로
    가져간다(위젯·카드 강조 + 화면 밖이면 스크롤). 막는 겹은 `follow_resolved` 와 같다: 외부 AI, 화면 조작
    허용, 기기별 따라가기, 호출별 `_show_on_screen`. 화면이 이미 충분히 보여 주면 스크롤하지 않는다(화면 쪽)."""
    try:
        if transport not in _EXTERNAL or not user_id or not ref:
            return _note(trace, 'not an external AI call')
        from aot.tools import tool_registry as R
        if tool_profile is None or not R.tool_in_profile('screen_action', tool_profile):
            return _note(trace, 'screen control is not in this tool profile')
        how, screen = _parse_show(show)
        if how == 'off':
            return _note(trace, '_show_on_screen off')
        now = time.time()
        picked, problem = _pick_screen(user_id, now, screen=screen, session_key=session_key)
        if picked is None:
            if problem is None:
                _note(trace, 'no screen with AI control on')
            return problem
        target, visible = picked
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        args = S._screen_focus_pick(target, ref)
        if not args:
            return _note(trace, 'the focus is not a widget or card on the screen')
        return _issue({'mode': 'open', 'action': 'highlight', 'args': args, 'hold_for': None},
                      user_id, target, visible, now, trace)
    except Exception:
        logger.debug('screen follow (focus) failed', exc_info=True)
        return _note(trace, 'follow failed (see debug log)')


def _note(trace, reason):
    """열지 않은 이유를 trace 에 남기고 None 을 돌려준다."""
    if trace is not None:
        trace.append(reason)
    return None


#: 감사 기록에 남기는 따라가기 결과의 종류 — 응답 `screen` 칸의 키.
_OUTCOME_KEYS = ('opened', 'highlighted', 'queued', 'asked', 'not_opened')


def audit_note(shown, trace=None, limit=160):
    """따라가기 결과 한 줄 — `mcp_audit_log.result_summary` 에 덧붙인다.

    `opened`(바로 열었음) · `queued`(화면이 뒤에 있어 넣어 둠) · `asked`([허용] 카드) ·
    `not_opened`(이유와 후보) 는 AI 에게 돌려준 `screen` 칸의 요약이고, 아무것도 돌려주지
    않은 경우(조용히 건너뜀)는 `skipped` 와 이유다. 따라가기를 시도할 자리가 아니었으면
    None — 기록에 아무것도 붙이지 않는다."""
    if isinstance(shown, dict):
        for key in _OUTCOME_KEYS:
            if key in shown:
                text = re.sub(r'\s+', ' ', str(shown[key])).strip()
                return 'screen:%s %s' % (key, text[:limit])
        if shown.get('follow') == 'off':
            return 'screen:follow_off'
    if trace:
        return 'screen:skipped %s' % str(trace[-1])[:limit]
    return None


# ── 어디에 어떻게 여는가 ─────────────────────────────────────────────────────

def _denied_dashboards(user_id):
    """이 사용자가 조작할 수 없어 목록에서 감춰진 대시보드(그룹 스코프) — 거기로는
    옮기지 않는다. 요청 밖(MCP)이라 사용자를 직접 넘긴다. 판정이 깨져도 따라가기가
    멈추면 안 되므로 화면 쪽 필터(`visible_dashboards`)와 같이 빈 집합으로 둔다."""
    try:
        from aot.aot_flask.access import scope
        from aot.databases.models import User
        user = User.query.filter(User.unique_id == user_id).first()
        if user is None:
            return frozenset()
        return scope.denied_resource_uuids('dashboard', user=user)
    except Exception:                                       # noqa: BLE001
        logger.debug('screen follow: dashboard scope check failed', exc_info=True)
        return frozenset()


def _dashboard_names(ids):
    from aot.databases.models import Dashboard
    rows = Dashboard.query.filter(Dashboard.unique_id.in_(list(ids))).all() if ids else []
    return {d.unique_id: (d.name or '').strip() for d in rows}


def _dashboards_with_widget(ref, dashboard_ids):
    """그 장치를 보여 주는 위젯이 있는 대시보드 — 지도에 없는 장치를 강조로 따라간다."""
    return [d for d in dashboard_ids if _widget_showing(d, ref) is not None]


def _open_now(target, now):
    """화면이 동기화로 알려 온 **지금 열린 지도 창**의 대상({kind,name,id}), 없으면 None.

    창 제목(`dialog`, '이름 (map)')을 그 대시보드 지도의 항목으로 푼다. 보고가 오래됐으면
    (뒤에 숨은 탭은 5초 간격) 믿지 않는다."""
    if not target.get('client_state') or now - (target.get('client_at') or 0) > 45:
        return None
    try:
        st = json.loads(target['client_state'])
    except ValueError:
        return None
    dialog = st.get('dialog') if isinstance(st, dict) else None
    if not dialog:
        return None
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    try:
        return S._screen_open_item(target, dialog)
    except Exception:                                       # noqa: BLE001
        logger.debug('screen follow: open dialog lookup failed', exc_info=True)
        return None


def _already_there(target, args, now):
    """열려는 창이 이미 화면에 있거나 곧 있을 것인가 → 이유 문장 또는 None.

    비교 대상은 명령 이력이 아니라 **화면에 실제로 열린 것**(`_open_now`)과 아직 끝나지
    않은 명령(`pending_open_item`)이다. 예전에는 90초 안에 보낸 명령을 "화면에 열려
    있다" 고 가정해, 그 사이 화면이 다른 창으로 바뀌었어도 건너뛰었다(2026-10-18)."""
    from aot.utils import web_presence as wp
    shown = wp.pending_open_item(target['browser_key'], now=now) or _open_now(target, now)
    if not shown:
        return None
    if shown.get('id') == args.get('id') and shown.get('kind') == args.get('kind'):
        return 'already open'
    if _shows_inside(shown, args):
        # 방금 그 안의 것(구획·장치)을 열었다 — 감싸는 구역으로 되돌리면 AI 가
        # 설명하는 대상이 화면에서 사라진다(list_plots(구역) 가 구획 뒤에 온다).
        return 'the open window is inside it'
    return None


def _item_args(S, target, widget, ident, hint):
    args, problem = S._screen_map_item_args(target, widget, ident, hint)
    if problem and hint:
        args, problem = S._screen_map_item_args(target, widget, ident, None)
    return args, problem


def _highlight_args(w):
    return {'widget_id': w.unique_id, 'id': w.unique_id, 'name': w.name,
            'describe': "highlight widget '%s'" % w.name}


def _wildcard_maps_on(S, dash_id):
    """그 대시보드에서 지도를 하나로 정해 두지 않은 지도 위젯(`map_uuid` 가 비었다) —
    어느 지도를 보여 주는지 서버가 모르고 화면이 판정한다."""
    from aot.databases.models import Widget
    return [w for w in (Widget.query.filter(Widget.tab_id == dash_id,
                                            Widget.graph_type == 'AoT_map')
                        .order_by(Widget.position_y, Widget.position_x).all())
            if not S._screen_widget_map_uuid(w)]


def _plan(kind, ident, hint, user_id, target, now):
    """대상을 어디서 어떻게 열지 → 계획 dict.

    {'mode': 'open', 'action', 'args', 'hold_for'}   지금 화면의 대시보드에서 연다
                                                     (hold_for: 이동이 아직 끝나지 않았다)
    {'mode': 'move', 'dest', 'dest_name', 'nav', 'action', 'args'}
                                                     그 대시보드로 옮긴 뒤 연다
    {'mode': 'blocked', 'out': {...}}                열지 않고 AI 에게 이유·후보를 준다
    {'mode': 'skip', 'why': str}                     조용히 건너뜀(이유는 감사 기록에)

    사용자 결정 2026-10-20: 다른 대시보드(입력·출력 페이지 포함)에 있는 대상은 묻지 않고 그
    대시보드로 옮겨 연다. 단 그 대상을 보여 주는 대시보드가 **하나로 정해질 때만** — 여럿이면
    옮기지 않고 후보를 돌려 AI 가 사용자에게 묻게 한다.

    순서(확실한 것부터): ① 지금 대시보드에 그 지도가 있다 ② 다른 대시보드에 있다(옮긴다)
    ③ 지도를 하나로 정해 두지 않은 위젯이 지금 대시보드에 있다(화면이 판정) ④ 지도에 없는
    장치는 그 장치를 보여 주는 위젯 강조.
    """
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    from aot.utils import web_presence as wp
    key = target['browser_key']
    here = target.get('page_ref') if target.get('page_kind') == 'dashboard' else None
    pending = wp.pending_dashboard(key, now=now)     # 방금 옮기라고 보냈고 아직 도착 전
    cur = pending or here
    # 이동이 끝나기 전이면 열기는 도착을 기다린다.
    wait = pending if pending and pending != here else None

    # 사용자가 입력·출력·함수 페이지에서 그 장치의 카드가 있는 탭을 보고 있으면, 페이지를 떠나지 않고 그 카드로
    # 스크롤·강조한다(2026-10-30 결정: 읽기 조회가 페이지를 떠나게 하지 않는다 — 그 안에서 설명하는 자리를 맞춘다).
    # 카드가 다른 탭에 있으면 아래처럼 옮기지 않고 알려 준다.
    if kind == 'device' and not here and not pending \
            and target.get('page_kind') in ('inputs', 'outputs', 'functions'):
        card, _problem = S._screen_card_args(target, ident)
        if card:
            return {'mode': 'open', 'action': 'highlight', 'args': S._screen_card_highlight(card),
                    'hold_for': None}

    by_dash = {}
    for w in S._screen_map_widgets_for(kind, ident):
        by_dash.setdefault(w.tab_id, []).append(w)

    def at(dash_id):
        """그 대시보드에 있는 것처럼 본 화면 행 — 지도 고르기는 이 행의 대시보드를 본다."""
        return dict(target, page_kind='dashboard', page_ref=dash_id)

    def open_on(dash_id, widgets):
        problem = None
        for w in widgets:
            args, problem = _item_args(S, at(dash_id), w.unique_id, ident, hint)
            if args:
                return args, None
        return None, problem

    # ① 지금(곧) 있는 대시보드의 지도에 있다 — 그 위젯으로 연다.
    if cur and cur in by_dash:
        args, problem = open_on(cur, by_dash[cur])
        if args:
            return {'mode': 'open', 'action': 'open_map_item', 'args': args,
                    'hold_for': wait}
        return {'mode': 'skip', 'why': str(problem or 'not on the map')[:100]}

    # ② 다른 대시보드의 지도에 있다.
    denied = _denied_dashboards(user_id)
    cands = [d for d in by_dash if d not in denied]
    use_widget = False
    if not cands:
        # ③ 지금 대시보드에 지도를 정해 두지 않은 위젯이 있으면 화면이 판정한다.
        if cur:
            args, problem = open_on(cur, _wildcard_maps_on(S, cur))
            if args:
                return {'mode': 'open', 'action': 'open_map_item', 'args': args,
                        'hold_for': wait}
        # ④ 지도에 없는 장치 — 그 장치를 보여 주는 위젯을 강조한다.
        if kind == 'device':
            if cur:
                w = _widget_showing(cur, ident)
                if w is not None:
                    return {'mode': 'open', 'action': 'highlight',
                            'args': _highlight_args(w), 'hold_for': wait}
            from aot.databases.models import Dashboard
            every = [d.unique_id for d in Dashboard.query.all()
                     if d.unique_id not in denied and d.unique_id != cur]
            cands = _dashboards_with_widget(ident, every)
            use_widget = bool(cands)
    if not cands:
        if kind in _PLACE_KINDS or not here:
            on = ("on the %s page" % target.get('page_kind')) if not here else \
                "on a dashboard that does not show it"
            return {'mode': 'blocked', 'out': {'not_opened': (
                "the user's screen is %s, and no dashboard map the user can open "
                "shows this %s" % (on, kind))}}
        return {'mode': 'skip', 'why': 'not on any dashboard'}

    names = _dashboard_names(cands)
    page = target.get('page_kind')
    if not here and not pending and page and page not in ('dashboard', 'home'):
        # 사용자가 입력·출력·설정 같은 페이지에서 작업 중이다 — 읽기 조회가 그 페이지를 떠나게
        # 하지 않는다(2026-10-30 체험: 입력 페이지 작업 중 지도 대시보드로 끌려갔다). 어느
        # 대시보드가 보여 주는지와 링크만 돌려준다. 명시한 화면 이동(screen navigate)은 이 길이 아니다.
        label = [names.get(d) or d for d in cands]
        out = {'not_opened': (
            "the user is working on the %s page, so the screen was not moved; this %s "
            "is shown on dashboard %s — tell the user, or navigate there if they ask"
            % (page, kind, ', '.join("'%s'" % n for n in label[:6])))}
        if len(cands) == 1:
            nav, _problem = S._screen_action_args(target, 'navigate', 'dashboard',
                                                  cands[0], None, None)
            link = wp.link_to(target, (nav or {}).get('url'))
            if link:
                out['link'] = link
        else:
            out['candidates'] = label[:6]
        return {'mode': 'blocked', 'out': out}
    if len(cands) > 1:
        label = [names.get(d) or d for d in cands]
        return {'mode': 'blocked', 'out': {
            'not_opened': ("it is shown on several dashboards (%s) — ask the user which "
                           "one to go to; the screen was not moved" % ', '.join(label[:6])),
            'candidates': label[:6]}}
    dest = cands[0]
    nav, problem = S._screen_action_args(target, 'navigate', 'dashboard', dest, None, None)
    if problem or not nav:
        return {'mode': 'skip', 'why': str(problem or 'cannot navigate')[:100]}
    if use_widget:
        action, args = 'highlight', _highlight_args(_widget_showing(dest, ident))
    else:
        action = 'open_map_item'
        args, problem = open_on(dest, by_dash[dest])
        if not args:
            return {'mode': 'skip', 'why': str(problem or 'not on the map')[:100]}
    return {'mode': 'move', 'dest': dest, 'dest_name': names.get(dest) or dest,
            'nav': nav, 'action': action, 'args': args}


def _open(kind, ident, _kind, user_id, target, visible, now, trace=None,
          center_only=False):
    """대상 하나를 사용자 화면에 연다 — 지금 대시보드의 지도 창, 안 되면 그 장치의 위젯
    강조, 다른 대시보드에 있으면 그리로 옮긴 뒤. center_only 면 창 대신 지도만 가운데로."""
    from aot.utils import web_presence as wp
    kind = {'input': 'device', 'output': 'device'}.get(kind, kind)
    if kind not in _PLACE_KINDS and kind != 'device':
        return _note(trace, 'no window for this kind')    # 설비 등 — 열 창이 없다

    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    # 같은 이름의 대지와 시설('영양 육묘장')은 도구가 묻는 쪽(시설)으로 연다.
    hint = _kind if (_kind in ('site', 'zone', 'facility')
                     and kind in ('site', 'zone', 'facility')) else None
    plan = _plan(kind, ident, hint, user_id, target, now)
    if plan['mode'] == 'skip':
        return _note(trace, plan['why'])
    if plan['mode'] == 'blocked':
        return plan['out']

    return _issue(plan, user_id, target, visible, now, trace, center_only)


def _issue(plan, user_id, target, visible, now, trace=None, center_only=False):
    """계획(`_plan`)을 화면 명령으로 넣고 AI 에게 줄 한 줄 결과를 만든다 — 대상을 푸는 일은 끝났다."""
    from aot.utils import web_presence as wp
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    key = target['browser_key']
    action, args = plan['action'], plan['args']
    centering = center_only and action == 'open_map_item'
    if centering:
        # 화면은 modal=False 면 창을 열지 않고 지도 카메라만 옮긴다(aot-screen-link.js).
        args = dict(args, modal=False, center=True,
                    describe="center the map on %s '%s'" % (args['kind'], args['name']))
    moving = plan['mode'] == 'move'
    hold_for = plan.get('hold_for')
    if not moving and not hold_for:
        if action == 'highlight' and wp.recently_sent(key, action, args['id'],
                                                      within_s=8.0, now=now):
            return _note(trace, 'already highlighted')
        if action == 'open_map_item' and not centering:
            why = _already_there(target, args, now)
            if why:
                return _note(trace, why)
    elif action == 'open_map_item' and not centering:
        pend = wp.pending_open_item(key, now=now)
        if pend and pend.get('id') == args['id']:
            return _note(trace, 'already queued')
    if wp.recent_command_count(user_id, now=now) + (2 if moving else 1) > wp.RATE_PER_MIN:
        return _note(trace, 'rate limited')

    where = '%s — %s' % (target.get('device') or 'browser',
                         S._screen_page_label(target))
    what = (("%s '%s'" % (args['kind'], args['name'])) if action == 'open_map_item'
            else "%s '%s'" % ('card' if args.get('card_id') else 'widget', args['name']))
    ask_mode = wp.follow_mode(target) == 'ask'
    # 그 기기에서 "AI 화면 조작 허용" 을 켰으면 [허용] 카드 없이 바로 한다(사용자 결정
    # 2026-10-20 — 근거는 `wp.auto_confirmed`). 기기별 따라가기 '묻기'는 사용자가 고른
    # 것이니 그대로 묻는다.
    confirmed = (wp.auto_confirmed(target, now) or wp.has_grant(target, now)) \
        and not ask_mode

    if moving:
        # 이동 명령을 먼저 넣고, 열기는 그 대시보드에 **도착했다고 화면이 알려 올 때까지**
        # 붙잡아 둔다 — 이동이 페이지를 다시 읽으므로 같이 내보내면 열기가 사라진다.
        wp.add_command(user_id, key, 'navigate', plan['nav'], confirmed=confirmed,
                       now=now, source=wp.FOLLOW_SOURCE)
        wp.add_command(user_id, key, action, args, confirmed=confirmed, now=now,
                       source=wp.FOLLOW_SOURCE, hold_for=plan['dest'],
                       ttl_s=wp.QUEUE_TTL_S if confirmed else wp.PROPOSE_TTL_S,
                       supersede=False)
        what = "%s, after moving the screen to dashboard '%s'" % (what, plan['dest_name'])
        link = None if visible else wp.link_to(target, plan['nav']['url'])
    else:
        wp.add_command(user_id, key, action, args, confirmed=confirmed, now=now,
                       source=wp.FOLLOW_SOURCE, hold_for=hold_for,
                       ttl_s=(wp.QUEUE_TTL_S if confirmed else wp.PROPOSE_TTL_S)
                       if hold_for else None)
        link = None if visible else wp.page_link(target)
    if confirmed:
        wp.extend_grant(key, now=now)
        if visible:
            verb = ('centered' if centering else 'opened') if action == 'open_map_item' \
                else 'highlighted'
            return {verb: "%s on %s" % (what, where), 'why': _WHY}
        out = {'queued': ("%s on %s — that screen is in the background; it "
                          "shows when the user returns to it" % (what, where))}
    else:
        out = {'asked': ("an [Allow] card on %s will show %s when the user "
                         "taps it" % (where, what)),
               # 왜 바로 열지 않았는가 — 한 줄(2026-10-12 A6).
               'reason': ("that device is set to ask before following"
                          if ask_mode else
                          "that screen has been quiet for a while, so the user is "
                          "asked first")}
    if link:
        out['link'] = link
    out['why'] = _WHY
    return out
