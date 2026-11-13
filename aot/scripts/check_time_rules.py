#!/usr/bin/env python3
# coding=utf-8
"""시간 규칙 가드 — 시간대·날짜를 코드에 박거나 옛 입구를 쓰는 새 코드를 막는다.

규칙 정본: `aot/utils/timekit.py`(입구 10개), 설계 `docs/design/timezone-management.md`.
저장은 UTC, 표시 날짜는 그 장소의 시간대로 바꾼 값이고, 시계는 `where` 하나로 고른다.

방식: 파이썬은 AST 로(주석·docstring 은 보지 않는다), 프런트는 정규식으로 훑는다.
기준선(`aot/tests/time_rules_baseline.json`)은 **0 으로 비어 있다** — 위반은 하나도 허용되지 않는다.
구조상 못 바꾸는 곳만 아래 `EXCEPTIONS` 표에 (파일, 규칙, 줄 안의 글자 조각, **한 줄 사유**)로 올린다.
 - 사유가 비면 가드가 실패한다.
 - 표의 항목이 어떤 위반과도 맞지 않으면(고쳐서 사라졌거나 글자 조각이 어긋남) 실패한다 —
   죽은 예외가 남아 새 위반을 가리지 않게 한다. (`--staged` 에서는 이 검사를 건너뛴다.)
 - 줄 번호가 아니라 글자 조각으로 잇기 때문에 파일이 움직여도 예외가 따라온다.
한 줄만의 정당한 예외는 그 줄 끝에 `# tz-ok: 이유` 로도 적을 수 있다(이유가 비면 인정하지 않는다).

하위 세션·에이전트는 설계서를 읽지 않는다. 그래서 실패 메시지가 **줄 번호와
'무엇으로 바꿀지'** 를 직접 말한다. 그 대안은 아래 표(`REPLACEMENTS` 등) 하나에서
나온다 — 규칙이자 메시지다.

표준 라이브러리만 쓴다(설치가 깨져도 돌아야 한다).

사용:
    python3 aot/scripts/check_time_rules.py                    # 워킹트리 전체
    python3 aot/scripts/check_time_rules.py --staged           # 인덱스 (pre-commit 훅)
    python3 aot/scripts/check_time_rules.py --update-baseline  # 기준선을 현재 값으로
    python3 aot/scripts/check_time_rules.py --json
종료 0=정상, 1=예외 표 밖의 위반·사유 없는 예외·죽은 예외, 2=검사 실패.
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter, namedtuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_ROOT = os.path.dirname(os.path.dirname(_HERE))
_BASELINE_REL = 'aot/tests/time_rules_baseline.json'

try:                                     # 표준 라이브러리. tzdata 가 없으면 pytz 로 물러난다
    import zoneinfo
    _ALL_TZ = frozenset(zoneinfo.available_timezones())
except Exception:                        # noqa: BLE001
    _ALL_TZ = frozenset()
if not _ALL_TZ:
    try:
        import pytz
        _ALL_TZ = frozenset(pytz.all_timezones)
    except Exception:                    # noqa: BLE001
        _ALL_TZ = frozenset()

# 시간대를 푸는 곳 자체 — 상수·오프셋·옛 이름을 다루는 정본 모듈
EXEMPT_FILES = {
    'aot/utils/timekit.py',
    'aot/utils/device_tz.py',
}
# timekit 의 공개 입구 — 이 이름을 몸통에서 부르는 얇은 어댑터는 '복사해 둔 헬퍼' 가 아니다
_TIMEKIT_ENTRIES = frozenset({
    'utc_now', 'naive_utc', 'parse_utc', 'resolve_tz', 'tz_of', 'to_tz',
    'iso_utc', 'iso_at', 'wall_to_utc', 'today_at',
})
# `x.localize(...)` 는 받는 쪽이 시간대 객체처럼 보일 때만 센다(번역 문장 `localize(data)` 같은 오탐 방지)
_TZ_RECEIVER = re.compile(r'tz|zone|pytz|local_tz|tzinfo|timezone', re.I)

_TZ_OK = re.compile(r'#\s*tz-ok:\s*\S')
_IANA = re.compile(r'[A-Z][A-Za-z]+/[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)?')
_OFFSET = re.compile(r'(?:UTC|GMT)?[+-]\d{2}:?\d{2}')
_ZERO_OFFSET = re.compile(r'(?:UTC|GMT)?[+-]0{2}:?0{2}')
_FIXED_ZONE_NAME = re.compile(r'(^|_)k' r'st(_|$)', re.I)   # 한국 표준시 이름
_SHIFT_HINT = re.compile(r'utc|now|today', re.I)

_IMPORT = 'from aot.utils.timekit import '

# ---------------------------------------------------------------------------
# 규칙 설명 (기준선 메시지의 '왜')
# ---------------------------------------------------------------------------
RULES = {
    'fixed_offset_shift': 'utc·now 에 timedelta(hours=상수)를 더하거나 빼 시간대를 옮김',
    'tz_literal': 'IANA 시간대 문자열을 코드에 박음',
    'offset_literal': "'+09:00' 같은 고정 오프셋 문자열",
    'kst_name': 'KST 이름의 변수·함수',
    'seconds_9h': '32400 · 9*3600 같은 +9시간 상수',
    'utc_date_display': 'utc_date 로 표시 날짜를 만듦',
    'tz_s_offset': 'now 시점 오프셋 tz_s 로 날짜 계산 — DST 경계에서 틀림',
    'old_entry': '옛 시간 입구(삭제 예정)를 import 하거나 부름',
    'naive_now': 'naive 시각·서버 OS 시계·서버 날짜를 얻음',
    'raw_tz': 'pytz/ZoneInfo/localize/mktime 로 시간대를 직접 다룸',
    'iso_by_hand': "ISO 문자열의 Z·'+00:00' 를 손으로 다룸",
    'private_helper': '파일마다 복사해 둔 시간 헬퍼',
}

# 규칙별 기본 대안 (한 줄)
RULE_HINTS = {
    'fixed_offset_shift': ("to_tz(utc_now(), 장소)  /  today_at(장소)",
                           "단순한 창 길이(hours=1 등)면 그 줄에 '# tz-ok: 창 길이'"),
    'tz_literal': ("tz_of(where)  (기본 시계는 FARM)",
                   "외부 API 가 정한 고정 시계면 '# tz-ok: 이유'"),
    'offset_literal': ("iso_at(값, where)  /  iso_utc(값)", ""),
    'kst_name': ("to_tz(값, 장소)",
                 "시뮬레이션·리플레이 데이터 자체의 시계면 '# tz-ok: 시나리오 데이터의 시계'"),
    'seconds_9h': ("tz 를 인자로 받아 점마다 to_tz(t, tz).date() 로 접는다", ""),
    'utc_date_display': ("점마다 to_tz(값, 장소).date()", ""),
    'tz_s_offset': ("점마다 to_tz(t, tz).date()  (now 시점 오프셋 금지)", ""),
    'private_helper': ("삭제하고 timekit 입구를 직접 쓴다: "
                       "utc_now · naive_utc · to_tz · iso_at · tz_of · today_at", ""),
}

# 옛 입구 → (새 입구, 덧붙임, 모듈 한정, 호출도 센다)
#   모듈 한정: import 한 모듈 이름(마지막 마디)이 여기 들어 있을 때만. None 이면 어디서든.
#   호출도 센다 False: 이름이 같아 import 만 바꾸면 되는 경우(utc_now).
REPLACEMENTS = {
    'serialize_ts': ('iso_at(값, 장소id)', '장소와 무관하면 iso_at(값, FARM)', None, True),
    'location_iso': ('iso_at(값, 장소id)', '', None, True),
    'api_iso': ('iso_utc(값)', '', None, True),
    'get_local_now': ('to_tz(utc_now(), FARM)', '장소가 있으면 FARM 대신 그 id', None, True),
    'to_local': ('to_tz(값, FARM)', '장소가 있으면 FARM 대신 그 id, 보는 사람이면 VIEWER', None, True),
    'get_user_tz': ('tz_of(FARM)', '', None, True),
    'to_user_tz': ('to_tz(값, FARM)', '', None, True),
    'get_timezone_name': ('str(tz_of(FARM))', '', None, True),
    'system_tz': ('tz_of(FARM)', '', None, True),
    'system_tz_name': ('str(tz_of(FARM))', '', None, True),
    'current_user_tz': ('tz_of(VIEWER)', '', None, True),
    'as_tz': ('tz_of(이름)', '', None, True),
    'ensure_utc': ('parse_utc(값)', 'naive 컬럼 비교용이면 naive_utc(값)', None, True),
    'get_device_tz': ('tz_of(행)', '', None, True),
    'resolve_location_tz': ('tz_of(id)', '', None, True),
    'resolve_location_tz_and_source': ('resolve_tz(id)', '(tz, source) 를 돌려준다', None, True),
    'to_device_tz': ('to_tz(값, 행)', '', None, True),
    'device_tz_name': ('str(tz_of(행))', '', None, True),
    'utc_to_wall': ('to_tz(값, where)', '', ('timekit',), True),
    'now_utc': ('utc_now()', '', None, True),
    'utc_now': ('utc_now()', 'import 를 timekit 으로: ' + _IMPORT + 'utc_now',
                ('time_utils', 'tz_utils'), False),
    'to_utc': ('parse_utc(값)', '', ('tz_utils',), True),
    'instant_or_wall_to_utc': ('wall_to_utc(값, where)', '오프셋이 붙은 값은 그 순간으로 읽는다', None, True),
    'picker_wall_to_epoch': ('wall_to_utc(문자열, where).timestamp()', '', None, True),
}
_LEGACY_MODULES = ('time_utils', 'tz_utils', 'device_tz', 'timekit')

# 파일마다 복사해 둔 헬퍼 이름 (utils_notes 의 _wall_tz·_place_tz·utc_to_wall(_str) 은
# 템플릿이 쓰는 얇은 어댑터로 남기므로 뺐다)
PRIVATE_HELPERS = frozenset({
    '_naive_utc', '_as_utc', '_utcnow', '_utc', '_now', '_now_iso', '_iso', '_iso_z', 'iso_z',
    '_to_iso', '_local_iso', '_local_now', '_device_local_now', '_facility_local_now',
    '_farm_now', '_today', '_today_in', 'local_today', '_tz_of', '_tz_for', '_tz',
    '_site_tz_name', 'site_tz', '_get_facility_tz', '_source_tz', 'local_tz', '_log_tz',
    '_schedule_display_tz', '_job_target_tz_name', '_host_timezone_name', '_resolve_tz',
    '_schedule_wall_to_utc', '_epoch_to_naive_utc', '_naive_utc_to_rfc3339',
    '_rfc3339_to_naive_utc',
})

_NAIVE_HINTS = {
    'utcnow': ('utc_now()', 'DB 의 naive 컬럼과 비교·저장하는 자리면 naive_utc(utc_now())'),
    'utcfromtimestamp': ('parse_utc(epoch)', 'naive 가 필요하면 naive_utc(parse_utc(epoch))'),
    'now': ('시각이면 to_tz(utc_now(), 장소), 간격이면 time.monotonic()',
            '인자 없는 datetime.now() 는 서버 OS 시계다'),
    'today': ('today_at(장소)', '장소가 없으면 today_at(FARM) — date.today() 는 서버 날짜다'),
}
_RAW_TZ_HINTS = {
    'timezone': ('tz_of(이름)', ''),
    'ZoneInfo': ('tz_of(이름)', ''),
    'localize': ('wall_to_utc(벽시계, where)', '벽시계 → 순간은 이것 하나로'),
    'mktime': ('wall_to_utc(벽시계, where).timestamp()', 'mktime 은 컨테이너 OS 시계로 읽는다'),
    'localtime': ('to_tz(parse_utc(epoch), where)', ''),
}
_ISO_HINT = ('parse_utc(값)', 'UTC ISO 문자열을 만들 때는 iso_utc(값)')


# ---------------------------------------------------------------------------
# 예외 표 — 구조상 못 바꾸는 곳만. (파일, 규칙, 줄 안의 글자 조각 또는 None=그 파일·규칙 전부, 사유)
# 사유는 한 줄이고 비면 가드가 실패한다. 새 항목을 올리는 것은 "이 위반은 괜찮다" 는 판단이다.
# ---------------------------------------------------------------------------
EXCEPTIONS = [
    # ── 출력 계약: 외부가 요구하는 모양이라 iso_utc(+00:00)로 바꿀 수 없다 ──
    ('aot/ai/services/calendar_sync_service.py', 'private_helper', 'def _naive_utc_to_rfc3339',
     "구글 캘린더 API 가 RFC3339 'Z' 꼴을 요구한다 — 그 문자열을 만드는 한 곳"),
    ('aot/ai/services/calendar_sync_service.py', 'iso_by_hand', "'+00:00', 'Z'",
     "구글 캘린더 API 가 RFC3339 'Z' 꼴을 요구한다(iso_utc 는 +00:00 를 낸다)"),
    ('aot/utils/ai_screen_cards.py', 'private_helper', 'def iso_z',
     "AI 카드가 클라이언트에 내는 'YYYY-MM-DDTHH:MM:SSZ' 출력 계약 — 모양을 만드는 한 곳"),
    ('aot/utils/fc_cal/sources.py', 'private_helper', 'def _iso',
     "'YYYY-MM-DDTHH:MM:SS.fffZ' 꼴 UTC 문자열(출력 계약) — 모양을 만드는 한 곳"),
    ('aot/utils/twin_gate.py', 'private_helper', 'def _iso',
     "트윈 하트비트에 싣는 'Z' 꼴 UTC 문자열(출력 계약)"),
    ('aot/inputs/chirpstack_MQTT_jmespath.py', 'iso_by_hand', None,
     "ChirpStack 가 보내는 RFC3339(나노초·Z) 페이로드를 읽는 입력 드라이버 — 출력 계약이 바뀌므로 손대지 않는다"),
    ('aot/inputs/chirpstack_jmespath.py', 'iso_by_hand', None,
     "ChirpStack 가 보내는 RFC3339(나노초·Z) 페이로드를 읽고 'Z' 로 되돌려 주는 입력 드라이버 — 출력 계약"),
    ('aot/inputs/chirpstack_rak3172_valve_hb.py', 'iso_by_hand', None,
     "ChirpStack 가 보내는 RFC3339(나노초·Z) 페이로드를 읽는 입력 드라이버 — 출력 계약"),
    # ── 시간대 해석 체인의 바닥: timekit 이 이 모델/설치 감지를 부르므로 timekit 을 되부를 수 없다 ──
    ('aot/databases/models/__init__.py', 'private_helper', 'def _host_timezone_name',
     "설치 시점에 호스트 시계(TZ·/etc/timezone)를 읽어 Misc.timezone 을 채운다 — 해석 체인의 바닥이라 timekit 을 쓸 수 없다"),
    ('aot/databases/models/__init__.py', 'raw_tz', 'pytz.timezone(candidate)',
     "위 호스트 시계 이름이 pytz 가 아는 이름인지 검증할 뿐이다(해석 체인의 바닥)"),
    ('aot/databases/models/geo.py', 'raw_tz', None,
     "GeoShape/GeoFacility.resolve_timezone — timekit.resolve_tz 가 이 메서드를 불러 쓰는 해석 체인의 바닥(되부르면 순환)"),
    ('aot/utils/logging_setup.py', 'private_helper', 'def _log_tz',
     "로그 asctime 용 시계 — DB·Flask 없이 로거가 켜질 때 도는 바닥 코드라 timekit(DB 의존)을 쓸 수 없다"),
    ('aot/utils/logging_setup.py', 'raw_tz', 'pytz.timezone(tz_name)',
     "로그 asctime 용 시계(위와 같은 이유) — 이름 하나를 tzinfo 로 바꿀 뿐이다"),
    # ── 시험이 갈아끼우는 시계 이음새 / 얇은 위임 ──
    ('aot/inputs/open_meteo_daily_forecast.py', 'private_helper', 'def local_today',
     "순수 계산 함수(now·오프셋을 인자로 받는다) — 네트워크·DB 없이 시험하려는 시그니처이고 시험이 같은 이름을 부른다"),
    ('aot/inputs/open_meteo_daily_forecast.py', 'private_helper', 'def _now',
     "epoch 초를 돌려주는 시계 이음새 — 시험이 이 이름을 패치한다(시간대와 무관)"),
    ('aot/inputs/open_meteo_hourly_forecast.py', 'private_helper', 'def _now',
     "epoch 초를 돌려주는 시계 이음새 — 시험이 이 이름을 패치한다(시간대와 무관)"),
    ('aot/utils/web_presence.py', 'private_helper', 'def _now',
     "epoch 초 기본값 주입(`now` 인자가 없을 때 time.time) — 시간대와 무관하고 시험이 now 를 주입한다"),
    ('aot/utils/fc_cal/sources.py', 'private_helper', 'def site_tz',
     "Sources 인터페이스 메서드 — 시험의 가짜 소스가 같은 이름을 구현하고, 몸통은 forecast_series 에 위임한다"),
    # ── 개발자 CLI: 서버 시계로 파일 이름·날짜를 찍는 일회성 도구 ──
    ('aot/scripts/backfill_facility_bay_crops.py', 'naive_now', None,
     "개발자 CLI(1회성 백필) — 기록 날짜를 실행한 기계의 날짜로 찍는다"),
    ('aot/scripts/manual_sync.py', 'naive_now', None,
     "개발자 CLI — 매뉴얼 장부·로그 파일 이름에 실행한 기계의 시각을 쓴다"),
    ('aot/scripts/purge_phantom_shapes.py', 'naive_now', None,
     "개발자 CLI — 백업 파일 이름에 실행한 기계의 시각을 쓴다"),
    ('aot/scripts/release_helper.py', 'naive_now', None,
     "개발자 CLI — CHANGELOG 릴리스 절 날짜를 릴리스하는 사람의 오늘로 찍는다"),
    # ── Mycodo 원본 / 트윈 ──
    ('aot/utils/tools.py', 'naive_now', None,
     "Mycodo 원본(출력 사용량 보고 일정) — 컨테이너 시계 기준 로직 전체가 한 덩어리라 부분 교체하면 일정이 어긋난다"),
    ('aot/utils/tools.py', 'raw_tz', None,
     "Mycodo 원본(출력 사용량 보고 일정) — 위와 같은 덩어리"),
    ('aot/twin/node.py', 'raw_tz', None,
     "트윈 노드의 로그 문자열 — 원격 노드는 AoT 서버 없이 돈다(패키지가 flask·DB 를 import 하지 않는다). 사용자 지정 예외"),
    ('aot/twin/schedule.py', 'raw_tz', None,
     "트윈 일정 계산 — 원격 노드는 AoT 서버 없이 돌아 timekit(DB 의존)을 못 쓴다. 사용자 지정 예외"),
    ('aot/twin/service.py', 'raw_tz', None,
     "트윈 서비스의 로그 문자열(위와 같은 이유)"),
]

Hit = namedtuple('Hit', 'line rule hint note snippet')

_JS_PATTERNS = (
    ('tz_literal', re.compile(r"""['"]Asia/Seoul['"]""")),
    ('offset_literal', re.compile(r"""['"][+-]09:?00['"]""")),
    ('seconds_9h', re.compile(r'\b9\s*\*\s*60\s*\*\s*60\b|\b32400\b')),
)
_JS_EXEMPT = {'aot/aot_flask/static/js/common/aot-tz.js'}


# ---------------------------------------------------------------------------
# 파이썬 스캐너
# ---------------------------------------------------------------------------
def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, 'body', [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _is_const_hours(call):
    """timedelta(hours=<0 이 아닌 상수>)."""
    for kw in call.keywords:
        if (kw.arg == 'hours' and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, (int, float))
                and not isinstance(kw.value.value, bool)
                and 0 < abs(kw.value.value) <= 14):
            return True
        if (kw.arg == 'hours' and isinstance(kw.value, ast.UnaryOp)
                and isinstance(kw.value.operand, ast.Constant)
                and 0 < abs(kw.value.operand.value) <= 14):
            return True
    return False


def _callee(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')


def _last(node):
    """a.b.c → 'c', Name → id."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return getattr(node, 'id', '')


def _mod_base(module):
    return (module or '').split('.')[-1]


def _delegates_to_timekit(func):
    """몸통이 timekit 입구를 부르면 시간대를 직접 푸는 복사본이 아니라 얇은 어댑터다."""
    for n in ast.walk(func):
        if isinstance(n, ast.Name) and n.id in _TIMEKIT_ENTRIES:
            return True
        if isinstance(n, ast.Attribute) and n.attr in _TIMEKIT_ENTRIES:
            return True
    return False


def scan_python_detail(source, rel=None):
    """[Hit] — tz-ok 표시한 줄은 뺀다. `rel` 이 옛 정의 파일이면 새 규칙을 건너뛴다."""
    tree = ast.parse(source)
    lines = source.splitlines()
    docs = _docstring_nodes(tree)
    hits = []

    def add(node, rule, hint=None, note=''):
        text = lines[node.lineno - 1] if node.lineno <= len(lines) else ''
        if _TZ_OK.search(text):
            return
        if hint is None:
            hint, note = RULE_HINTS.get(rule, ('', ''))
        hits.append(Hit(node.lineno, rule, hint, note, text.strip()[:110]))

    # 이 파일이 옛 입구를 어떤 이름으로 들여왔는가
    bound = {}            # 지역 이름 → REPLACEMENTS 키
    module_aliases = {}   # 지역 이름 → 모듈 마지막 마디
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = _mod_base(node.module)
            for a in node.names:
                local = a.asname or a.name
                if a.name in _LEGACY_MODULES and (node.module or '').endswith('aot.utils'):
                    module_aliases[local] = a.name
                ent = REPLACEMENTS.get(a.name)
                if ent and (ent[2] is None or base in ent[2]):
                    bound[local] = a.name
                    add(node, 'old_entry', ent[0], ent[1])
        elif isinstance(node, ast.Import):
            for a in node.names:
                base = _mod_base(a.name)
                if base in _LEGACY_MODULES:
                    module_aliases[a.asname or base] = base
    # 이 파일 최상위에 같은 이름을 다시 정의한 것(중복 입구)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ent = REPLACEMENTS.get(node.name)
            if ent and ent[2] is None:
                bound[node.name] = node.name
                add(node, 'old_entry', ent[0], '이 파일의 중복 정의 — 삭제하고 새 입구를 쓴다')

    docs_ok = docs
    for node in ast.walk(tree):
        # ── 옛 입구 호출 ──
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in bound:
                ent = REPLACEMENTS[bound[f.id]]
                if ent[3]:
                    add(node, 'old_entry', ent[0], ent[1])
            elif (isinstance(f, ast.Attribute) and f.attr in REPLACEMENTS
                  and isinstance(f.value, ast.Name) and f.value.id in module_aliases):
                ent = REPLACEMENTS[f.attr]
                if ent[3] and (ent[2] is None or module_aliases[f.value.id] in ent[2]):
                    add(node, 'old_entry', ent[0], ent[1])
            # ── naive_now ──
            if isinstance(f, ast.Attribute):
                base = _last(f.value)
                if f.attr in ('utcnow', 'utcfromtimestamp'):
                    add(node, 'naive_now', *_NAIVE_HINTS[f.attr])
                elif f.attr == 'now' and not node.args and not node.keywords and base in (
                        'datetime', '_dt', 'dt'):
                    add(node, 'naive_now', *_NAIVE_HINTS['now'])
                elif f.attr == 'today' and base in ('date', 'datetime'):
                    add(node, 'naive_now', *_NAIVE_HINTS['today'])
                # ── raw_tz ──
                elif f.attr == 'timezone' and base == 'pytz':
                    utc_only = (len(node.args) == 1 and isinstance(node.args[0], ast.Constant)
                                and str(node.args[0].value).lower() == 'utc')
                    if not utc_only:
                        add(node, 'raw_tz', *_RAW_TZ_HINTS['timezone'])
                elif f.attr == 'localize' and _TZ_RECEIVER.search(ast.unparse(f.value)):
                    add(node, 'raw_tz', *_RAW_TZ_HINTS['localize'])
                elif f.attr in ('mktime', 'localtime') and base == 'time':
                    add(node, 'raw_tz', *_RAW_TZ_HINTS[f.attr])
                # ── iso_by_hand ──
                elif (f.attr == 'replace' and node.args
                      and isinstance(node.args[0], ast.Constant)
                      and node.args[0].value in ('Z', 'z', '+00:00')):
                    add(node, 'iso_by_hand', *_ISO_HINT)
            elif isinstance(f, ast.Name) and f.id == 'ZoneInfo':
                add(node, 'raw_tz', *_RAW_TZ_HINTS['ZoneInfo'])
        # ── 정의 이름 ──
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in PRIVATE_HELPERS and not _delegates_to_timekit(node)):
            add(node, 'private_helper')
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            if any(isinstance(s, ast.Constant) and s.value == '+00:00'
                   for s in (node.left, node.right)):
                add(node, 'iso_by_hand', *_ISO_HINT)
        elif isinstance(node, ast.JoinedStr):
            if any(isinstance(v, ast.Constant) and isinstance(v.value, str)
                   and v.value.endswith('+00:00') for v in node.values):
                add(node, 'iso_by_hand', *_ISO_HINT)

        # ── 기존 6종 ──
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            for a, b in ((node.left, node.right), (node.right, node.left)):
                if (isinstance(a, ast.Call) and _callee(a) == 'timedelta'
                        and _is_const_hours(a)
                        and _SHIFT_HINT.search(ast.unparse(b))):
                    add(a, 'fixed_offset_shift')
                    break
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, str) and id(node) not in docs_ok:
                s = node.value.strip()
                if _IANA.fullmatch(s) and s in _ALL_TZ:
                    add(node, 'tz_literal')
                elif _OFFSET.fullmatch(s) and not _ZERO_OFFSET.fullmatch(s):
                    add(node, 'offset_literal')
            elif node.value == 9 * 3600 and not isinstance(node.value, bool):  # tz-ok: 가드 자신의 탐지 상수
                add(node, 'seconds_9h')
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            vals = [c.value for c in (node.left, node.right)
                    if isinstance(c, ast.Constant)]
            if sorted(v for v in vals if isinstance(v, int)) == [9, 3600]:
                add(node, 'seconds_9h')
        names = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [node.name] + [a.arg for a in node.args.args]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        for n in names:
            if _FIXED_ZONE_NAME.search(n):
                add(node, 'kst_name')
            elif n == 'utc_date':
                add(node, 'utc_date_display')
            elif n == 'tz_s':
                add(node, 'tz_s_offset')
    hits.sort(key=lambda h: (h.line, h.rule))
    return hits


def scan_python(source, rel=None):
    """[(줄, 규칙)] — 간단한 형태."""
    return [(h.line, h.rule) for h in scan_python_detail(source, rel)]


def scan_js_detail(source):
    hits = []
    for i, line in enumerate(source.splitlines(), 1):
        if _TZ_OK.search(line) or line.lstrip().startswith(('//', '*')):
            continue
        for rule, pat in _JS_PATTERNS:
            if pat.search(line):
                hint, note = RULE_HINTS.get(rule, ('', ''))
                hits.append(Hit(i, rule, hint, note, line.strip()[:110]))
    return hits


def scan_js(source):
    return [(h.line, h.rule) for h in scan_js_detail(source)]


# ---------------------------------------------------------------------------
# 파일 선택
# ---------------------------------------------------------------------------
def is_scanned_py(rel):
    parts = rel.split('/')
    return (rel.endswith('.py') and parts[0] == 'aot'
            and not any(p in ('tests', '__pycache__', 'node_modules') for p in parts)
            and rel not in EXEMPT_FILES)


def is_scanned_js(rel):
    parts = rel.split('/')
    return (rel.endswith('.js') and not rel.endswith('.min.js')
            and rel.startswith('aot/aot_flask/static/js/')
            and not any(p in ('vendor', 'lib', 'node_modules') for p in parts)
            and rel not in _JS_EXEMPT)


def _walk(root):
    base = os.path.join(root, 'aot')
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in ('tests', '__pycache__', 'node_modules')]
        for f in files:
            path = os.path.join(d, f)
            rel = os.path.relpath(path, root).replace(os.sep, '/')
            yield path, rel


def _scan_source(rel, source):
    if rel.endswith('.py'):
        return scan_python_detail(source, rel)
    return scan_js_detail(source)


def scan_worktree(root):
    """{rel: [Hit]}"""
    out = {}
    for path, rel in _walk(root):
        if not (is_scanned_py(rel) or is_scanned_js(rel)):
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                hits = _scan_source(rel, fh.read())
        except SyntaxError:
            continue
        if hits:
            out[rel] = hits
    return out


def _git(root, *args):
    return subprocess.run(['git'] + list(args), cwd=root, capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


def scan_staged(root):
    """인덱스(스테이지된 내용) 기준 {rel: [Hit]}."""
    res = _git(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMR')
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or 'git diff --cached 실패')
    out = {}
    for rel in res.stdout.splitlines():
        rel = rel.strip()
        if not (is_scanned_py(rel) or is_scanned_js(rel)):
            continue
        blob = _git(root, 'show', ':' + rel)
        if blob.returncode != 0:
            continue
        try:
            hits = _scan_source(rel, blob.stdout)
        except SyntaxError:
            continue
        if hits:
            out[rel] = hits
    return out


def counts_of(found):
    counts = Counter()
    for rel, hits in found.items():
        for h in hits:
            counts['%s::%s' % (rel, h.rule)] += 1
    return counts


# ---------------------------------------------------------------------------
# 기준선 비교와 메시지
# ---------------------------------------------------------------------------
def load_baseline(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def write_baseline(path, counts):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(counts.items())), fh, ensure_ascii=False, indent=1)
        fh.write('\n')


def worse_than(counts, base, only_files=None):
    return sorted((k, counts[k], base.get(k, 0)) for k in counts
                  if counts[k] > base.get(k, 0)
                  and (only_files is None or k.split('::')[0] in only_files))


def format_report(worse, found, max_lines=12):
    """줄 번호와 '→ 무엇으로 바꿀지' 를 담은 실패 메시지."""
    out = ['시간 규칙 위반이 늘었습니다. 아래대로 바꾸면 됩니다. 설계서를 찾을 필요는 없습니다.', '']
    for key, now, was in worse:
        rel, rule = key.split('::')
        hits = [h for h in found.get(rel, []) if h.rule == rule]
        out.append('  %s  [%s] %d개 (기준 %d) — %s' % (rel, rule, now, was, RULES.get(rule, '')))
        shown = hits[:max_lines]
        for h in shown:
            out.append('    %s:%d  %s' % (rel, h.line, h.snippet))
            if h.hint:
                extra = '  (%s)' % h.note if h.note else ''
                out.append('        → %s%s' % (h.hint, extra))
        if len(hits) > len(shown):
            out.append('    … 외 %d줄' % (len(hits) - len(shown)))
        if was:
            out.append('    (이 파일의 기준 %d개는 예전부터 있던 것이라, 위 목록에는 그것도 섞여 있습니다)' % was)
    out.append('')
    out.append('import: %sutc_now, naive_utc, parse_utc, tz_of, to_tz, iso_utc, iso_at, '
               'wall_to_utc, today_at, FARM, VIEWER' % _IMPORT)
    out.append('시간대와 무관한 정당한 예외면 그 줄에 "# tz-ok: 이유" 를 적습니다(이유가 비면 인정하지 않습니다).')
    out.append('구조상 못 바꾸는 파일 단위 예외는 check_time_rules.py 의 EXCEPTIONS 표에 한 줄 사유와 함께 올립니다.')
    return '\n'.join(out)


def _exception_errors(found_all, exceptions):
    """사유 없는 항목 · 어떤 위반과도 안 맞는 항목(죽은 예외)을 찾는다. [(항목, 문제)]"""
    errs = []
    for ex in exceptions:
        rel, rule, anchor, reason = ex
        if not str(reason or '').strip():
            errs.append((ex, '사유(한 줄)가 비어 있습니다'))
            continue
        matched = any(h.rule == rule and (anchor is None or anchor in h.snippet)
                      for h in found_all.get(rel, []))
        if not matched:
            errs.append((ex, '맞는 위반이 없습니다 — 고쳐졌거나 글자 조각이 어긋났습니다. 표에서 지우거나 고치세요'))
    return errs


def apply_exceptions(found, exceptions):
    """예외 표에 걸리는 위반을 뺀 {rel: [Hit]}. 사유가 빈 항목은 아무것도 가려 주지 않는다."""
    out = {}
    for rel, hits in found.items():
        keep = []
        for h in hits:
            covered = any(r == rel and rule == h.rule
                          and (anchor is None or anchor in h.snippet)
                          and str(reason or '').strip()
                          for r, rule, anchor, reason in exceptions)
            if not covered:
                keep.append(h)
        if keep:
            out[rel] = keep
    return out


def format_exception_errors(errs):
    out = ['시간 규칙 예외 표(check_time_rules.py 의 EXCEPTIONS)에 문제가 있습니다.', '']
    for (rel, rule, anchor, reason), why in errs:
        out.append('  %s  [%s] %r — %s' % (rel, rule, anchor, why))
    return '\n'.join(out)


def check(root, staged=False, baseline_path=None, exceptions=None):
    """(종료코드, 메시지, 개수). 예외 표 밖의 위반이 기준선(0)보다 늘었거나 예외 표가 어긋나면 1."""
    baseline_path = baseline_path or os.path.join(root, _BASELINE_REL)
    exceptions = EXCEPTIONS if exceptions is None else exceptions
    found_all = scan_staged(root) if staged else scan_worktree(root)
    found = apply_exceptions(found_all, exceptions)
    counts = counts_of(found)
    base = load_baseline(baseline_path)
    worse = worse_than(counts, base, only_files=set(found) if staged else None)
    msgs = []
    if worse:
        msgs.append(format_report(worse, found))
    if not staged:
        errs = _exception_errors(found_all, exceptions)
    else:
        errs = [e for e in _exception_errors(found_all, exceptions)
                if '사유' in e[1] and '비어' in e[1]]
    if errs:
        msgs.append(format_exception_errors(errs))
    if msgs:
        return 1, '\n\n'.join(msgs), counts
    return 0, '', counts


def main(argv=None):
    ap = argparse.ArgumentParser(description='시간 규칙 가드')
    ap.add_argument('--staged', action='store_true', help='인덱스(스테이지된 내용)만 본다')
    ap.add_argument('--update-baseline', action='store_true', help='기준선을 현재 값으로 쓴다')
    ap.add_argument('--json', action='store_true', help='규칙별 합계를 JSON 으로')
    ap.add_argument('--root', default=_DEFAULT_ROOT, help='저장소 루트(시험용)')
    ap.add_argument('--baseline', default=None, help='기준선 파일(시험용)')
    ap.add_argument('--exceptions', default=None,
                    help='예외 표 JSON [[파일,규칙,글자조각|null,사유],…] (시험용; 없으면 EXCEPTIONS)')
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    baseline = args.baseline or os.path.join(root, _BASELINE_REL)
    try:
        exceptions = None
        if args.exceptions:
            with open(args.exceptions, encoding='utf-8') as fh:
                exceptions = [tuple(e) for e in json.load(fh)]
        if args.update_baseline:
            counts = counts_of(apply_exceptions(scan_worktree(root), EXCEPTIONS if exceptions is None else exceptions))
            write_baseline(baseline, counts)
            print('기준선 갱신: %d 항목 · %d 회' % (len(counts), sum(counts.values())))
            return 0
        code, msg, counts = check(root, staged=args.staged, baseline_path=baseline,
                                  exceptions=exceptions)
    except Exception as exc:                                 # noqa: BLE001
        print('시간 규칙 검사 실패: %s' % exc, file=sys.stderr)
        return 2
    if args.json:
        by_rule = Counter()
        for k, v in counts.items():
            by_rule[k.split('::')[1]] += v
        print(json.dumps({'exit': code, 'by_rule': dict(by_rule)}, ensure_ascii=False))
    if msg:
        print(msg, file=sys.stderr)
    return code


if __name__ == '__main__':
    sys.exit(main())
