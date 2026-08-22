# coding=utf-8
"""관리 프로그램의 쓰기 경로 — 생성·복제·수정·삭제.

식생만이 아니라 가축·시설물·도로도 같은 구조로 다룬다(`kind`).

설계 정본: docs/design/program-layer.md

불변식을 **여기 한 곳에서** 강제한다. 라우트와 AI 도구가 각자 검증하면 새 진입점이
생길 때마다 조용히 빠진다(식생 구획의 `plot_io` 와 같은 구조).

## 여기서 지키는 것

- **내장·외부는 고칠 수 없다.** 업그레이드나 외부 갱신이 그 수정을 덮어써 조용히
  되돌아간다. 고치고 싶으면 복제한다.
- **참조 중인 프로그램은 지울 수 없다.** 지우면 그 작기가 "무엇을 목표로 길렀나" 의
  근거를 잃는다. 화면은 `missing` 으로 버텨 주지만, 그것은 사고를 견디는 장치이지
  정상 경로가 아니다.
- **내용이 실제로 바뀔 때만 버전을 올린다.** 저장 버튼을 눌렀다는 이유로 올리면
  구획이 고정해 둔 버전과의 차이가 의미를 잃는다.
"""
import logging
import re

from aot.aot_flask.extensions import db
from aot.databases.models import GeoProgram

logger = logging.getLogger(__name__)

_VALID_SOURCES = ('builtin', 'external', 'user', 'ai')

# 대상 종류 — **좁게 시작한다.** `other` 가 있어 새 종류가 필요할 때 코드를 고치지
# 않고도 담긴다. 정말 자주 쓰이면 그때 이름을 준다.
VALID_KINDS = ('vegetation', 'livestock', 'facility', 'other')


def _resolve_tab_id(raw_tab_id):
    """탭 소속 문자열 → (tab_id, error).

    비어 있으면 **기본 탭으로 채운다** — 이후 생성되는 행은 항상 유효한 탭에
    속하게 해서 "어느 탭에도 안 보이는 프로그램" 이 생기지 않게 한다. 값이
    있으면 그 탭이 실제로 존재하고 `page_type='program'` 인지 검증한다 —
    검증 없이 받으면 다른 페이지(input 등)의 탭 id 를 잘못 붙이는 요청을
    조용히 받아들이게 된다.
    """
    from aot.services.tab_service import TabService

    tab_id = (raw_tab_id or '').strip() or None
    if not tab_id:
        default_tab = TabService.get_default_tab('program')
        return (default_tab.unique_id if default_tab else None), None

    tab = TabService.get_tab_by_id(tab_id)
    if not tab or tab.page_type != 'program':
        return None, '탭을 찾을 수 없습니다: %r' % tab_id
    return tab_id, None


def _clean_stages(stages, defs=None, rdefs=None):
    """단계 목록 검증·정규화 → (stages, error).

    `days` 는 **그 단계의 길이**다. `None`(끝까지)을 허용하되 마지막이 아닌 자리에
    두면 그 뒤 단계는 영원히 오지 않으므로 거절한다 — 저장은 되고 화면만 이상해지는
    종류의 실수다.

    `defs` 는 **이 프로그램의 목표 항목 정의**다(`_clean_target_defs` 의 결과).
    단계 값의 어휘와 범위를 그것이 정하므로 반드시 함께 넘어와야 한다 — 정의에
    없는 키가 값으로 들어오면 거절한다(고아 값을 받아 두면 화면에 그릴 라벨도
    단위도 없다). `rdefs`(`_clean_resource_defs` 의 결과)도 같은 이유로 함께
    온다 — 단계의 자원 덮어쓰기가 그 정의 안에 있어야 한다.
    """
    if not isinstance(stages, list) or not stages:
        return None, '단계를 하나 이상 넣어야 합니다'

    defs = defs or []
    out = []
    for i, st in enumerate(stages):
        if not isinstance(st, dict):
            return None, '단계 %d 의 형식이 올바르지 않습니다' % (i + 1)
        key = (st.get('key') or '').strip()
        name = (st.get('name') or '').strip()
        if not key:
            return None, '단계 %d 에 key 가 없습니다' % (i + 1)
        days = st.get('days')
        if days in ('', None):
            days = None
        else:
            try:
                days = int(days)
            except (TypeError, ValueError):
                return None, '단계 %d 의 기간이 숫자가 아닙니다' % (i + 1)
            if days <= 0:
                return None, '단계 %d 의 기간은 1일 이상이어야 합니다' % (i + 1)
        if days is None and i != len(stages) - 1:
            return None, ('기간을 비운 단계("끝까지")는 마지막에만 올 수 있습니다 '
                          '— %d번째 단계 뒤의 단계는 시작되지 않습니다' % (i + 1))
        entry = {'key': key, 'name': name or key, 'days': days}

        targets, terr = _clean_targets(st.get('targets'), defs)
        if terr:
            return None, '단계 %d: %s' % (i + 1, terr)
        if targets:
            entry['targets'] = targets

        # 적산온도 목표(P4). `days` 와 같은 규약 — **그 단계의 길이**이지
        # 누적값이 아니다. 두 뜻이 섞이면 마지막 단계만 맞고 나머지가 다
        # 어긋나는데, 화면에서는 "단계가 이상하다" 로만 보인다.
        if st.get('gdd') not in (None, ''):
            try:
                gdd = float(st['gdd'])
            except (TypeError, ValueError):
                return None, '단계 %d 의 적산온도가 숫자가 아닙니다' % (i + 1)
            if gdd <= 0:
                return None, ('단계 %d 의 적산온도는 0보다 커야 합니다'
                              % (i + 1))
            entry['gdd'] = gdd

        # 자원(관수·시비) — **역할 on/off 덮어쓰기**다(P6, 2026-08-20 재설계).
        # 함수 uuid 는 여기 오지 않는다. 무엇이 그 일을 하는지는 현장이 기하로
        # 푼다(`plot_context.stage_resources`).
        res, rerr = _clean_stage_resources(st.get('resources'), rdefs)
        if rerr:
            return None, '단계 %d: %s' % (i + 1, rerr)
        if res:
            entry['resources'] = res

        # 단계 지침 — 이 시기에 무엇을 어떻게 하는가(자유 텍스트).
        #
        # 재배 지침서·농업기술센터 자료는 원래 **산문**이라 항목으로 쪼개면 적는
        # 사람이 원문에 없던 분류를 지어내게 된다. 그래서 한 칸으로 둔다.
        #
        # **완료 체크·일정이 아니다.** 그건 Schedule·노트의 일이고, 여기에 두면
        # 사용자가 체크박스와 알림을 기대한다. 지침은 읽는 것이다.
        # **제어를 바꾸지도 않는다** — 글로 적힌 지시를 코드가 해석해 장비를
        # 움직이면 그 해석이 틀렸을 때 근거를 되짚을 수 없다.
        guidance = st.get('guidance')
        if guidance is not None:
            if not isinstance(guidance, str):
                return None, '단계 %d 의 지침 형식이 올바르지 않습니다' % (i + 1)
            guidance = guidance.strip()
            # 상한을 두는 이유는 검열이 아니라 사고 방지다 — 붙여넣기 실수로 한
            # 단계가 JSON 전체를 삼키면 프로그램을 여는 화면이 전부 느려진다.
            if len(guidance) > 4000:
                return None, ('단계 %d 의 지침이 너무 깁니다 (4000자 이내)'
                              % (i + 1))
            if guidance:
                entry['guidance'] = guidance

        # 이후 단계가 쓸 필드는 있으면 그대로 보존한다(모르는 키를 버리지 않는다).
        #
        # `functions` 는 **P6 재설계 이전의 함수 uuid 목록**이다(p6_48). 읽는
        # 쪽은 더 이상 보지 않지만 조용히 버리지 않는다 — 그 uuid 들은 "이
        # 함수가 그 자리에 배치돼야 한다" 는 정보라, 배치를 맞춘 뒤 사람이
        # 확인하고 지우는 것이 맞다(geo_binding 레거시 컬럼과 같은 태도).
        for extra in ('tasks', 'functions'):
            if st.get(extra) is not None:
                entry[extra] = st[extra]
        out.append(entry)
    return out, None


# 자원 역할. **좁게 시작한다** — 어휘는 한 번 퍼지면 되돌리기 어렵다.
# 'other' 가 있으므로 새 역할이 필요할 때 코드를 고치지 않고도 담을 수 있고,
# 정말 자주 쓰이면 그때 이름을 준다(`GeoProgram.kind` 와 같은 태도).
_RESOURCE_ROLES = ('irrigation', 'fertigation', 'other')

# 종류별 **고정 항목** — 시스템이 그 종류에 기본으로 두는 목표 어휘.
#
# ## 고정의 뜻은 "어휘가 고정" 이지 "입력이 필수" 가 아니다
#
# 실제 시설이 모든 항목을 재거나 제어하지 못하는 것은 **당연하다**(노지 상추에
# CO2 센서가 없는 것이 정상이다). 그래서 값이 비어 있는 것은 결함이 아니고,
# 화면은 빈 항목을 미완성으로 다루지 않는다. 대신 항목을 **숨길 수 있다**
# (`hidden`) — 지우지는 못한다:
#
# - 지울 수 있게 하면 어휘가 프로그램마다 달라져 제어·AI 가 `co2` 를 못 찾는다.
#   그런데 지운 것과 비운 것은 하류에서 똑같이 "값 없음" 이라 얻는 것도 없다.
# - 숨기면 화면에서는 사라지므로 "없는 것을 채우라는 압박" 이 없어지고, 나중에
#   센서를 달면 되살릴 수 있다(지웠다면 다시 만들 생각을 못 한다).
#
# `label` 은 **msgid** 다(고정 항목만) — 이미 번역이 있는 문구를 그대로 쓴다.
# 사용자가 만든 항목의 label 은 사람이 적은 그대로이므로 번역하지 않는다.
#
# `measurement` 는 `config_devices_units.MEASUREMENTS` 의 키다. 이것이 있어야
# "이 목표를 재는 센서가 이 구획에 있는가" 를 답할 수 있다(plot_context).
#
# `shape` — `instant`(순간 설정점) | `daily`(하루 적산). DLI 는 `radiation` 의
# 일적산이라 순간값과 같은 축에 놓으면 안 된다.
_FIXED_TARGET_DEFS = {
    'vegetation': [
        {'key': 'temp_day',   'label': 'Day temp',   'unit': '°C',
         'measurement': 'temperature', 'shape': 'instant', 'when': 'day',
         'min': -30.0, 'max': 60.0},
        {'key': 'temp_night', 'label': 'Night temp', 'unit': '°C',
         'measurement': 'temperature', 'shape': 'instant', 'when': 'night',
         'min': -30.0, 'max': 60.0},
        {'key': 'rh',         'label': 'Humidity',   'unit': '%',
         'measurement': 'humidity', 'shape': 'instant',
         'min': 0.0, 'max': 100.0},
        {'key': 'co2',        'label': 'CO2',        'unit': 'ppm',
         'measurement': 'co2', 'shape': 'instant',
         'min': 0.0, 'max': 5000.0},
        {'key': 'dli',        'label': 'DLI',        'unit': 'mol/m²/d',
         'measurement': 'radiation', 'shape': 'daily',
         'min': 0.0, 'max': 80.0},
        {'key': 'vpd',        'label': 'VPD',        'unit': 'kPa',
         'measurement': 'vapor_pressure_deficit', 'shape': 'instant',
         'min': 0.0, 'max': 10.0},
    ],
    # 가축·시설·기타는 **고정 항목이 없다.** AoT 에 그 종류의 측정·제어 축이 아직
    # 없고(예: 암모니아는 `MEASUREMENTS` 에도 없다), 근거 없이 지어낸 어휘는
    # 화면에 나가는 순간 되돌리기 어렵다. 사용자가 첫 항목을 직접 만든다.
    'livestock': [],
    'facility':  [],
    'other':     [],
}

# 사용자 항목의 키에 허용하는 모양. 화면·AI·JSON 을 오가므로 좁게 잡는다.
_KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,31}$')

_TARGET_SHAPES = ('instant', 'daily')


def fixed_target_defs(kind):
    """그 종류의 고정 항목 **사본** → list.

    사본을 주는 이유: 호출부가 `hidden` 을 얹거나 정렬하는데, 원본을 주면 그
    변형이 프로세스 전역에 남는다.
    """
    return [dict(d) for d in _FIXED_TARGET_DEFS.get(kind or 'vegetation', [])]


def _clean_target_defs(defs, kind):
    """목표 항목 정의 검증·정규화 → (list, error).

    **고정 항목은 언제나 먼저, 정의된 순서로 들어간다.** 클라이언트가 빠뜨리고
    보내도 서버가 되돌려 놓는다 — 그래서 "지울 수 없다" 가 구조적으로 지켜진다.
    클라이언트가 보낸 고정 항목에서는 `hidden` 만 받는다(라벨·단위·범위는
    시스템 소유다 — 사람이 바꾸면 같은 키가 시설마다 다른 뜻이 된다).

    사용자 항목은 뒤에 붙는다. `measurement` 는 있으면 `MEASUREMENTS` 의 키여야
    한다 — 오타를 받아 두면 "센서가 있는데 안 잡힌다" 를 나중에 만나고, 그때는
    원인이 정의인지 센서인지 알 수 없다.
    """
    from aot.config_devices_units import MEASUREMENTS

    incoming = defs if isinstance(defs, list) else []
    by_key = {}
    for item in incoming:
        if isinstance(item, dict) and (item.get('key') or '').strip():
            by_key[(item['key'] or '').strip()] = item

    out = []
    fixed_keys = set()
    for base in fixed_target_defs(kind):
        fixed_keys.add(base['key'])
        sent = by_key.get(base['key']) or {}
        base['fixed'] = True
        base['hidden'] = bool(sent.get('hidden'))
        # 라벨·단위·범위는 시스템 소유지만 **기본 목표값은 사람의 것**이다.
        derr = _apply_default(base, sent, base.get('min'), base.get('max'))
        if derr:
            return None, derr
        out.append(base)

    seen = set(fixed_keys)
    for item in incoming:
        if not isinstance(item, dict):
            return None, '목표 항목 형식이 올바르지 않습니다'
        key = (item.get('key') or '').strip()
        if not key or key in fixed_keys:
            continue                       # 고정 항목은 위에서 이미 넣었다
        # **다른 종류의 고정 항목은 옮겨오지 않는다.** 종류를 식생→가축으로 바꿀 때
        # 이것을 걸러내지 않으면 DLI·VPD 가 "사용자가 만든 항목" 으로 둔갑해 축사
        # 화면에 그대로 남고, 라벨은 msgid 라 번역도 되지 않는다('Day temp').
        # 가축·시설은 고정 항목 없이 **빈 상태에서 시작**하는 것이 합의된 동작이다.
        # 그 항목에 값이 남아 있으면 아래 `_clean_stages` 가 고아로 잡아 거절한다 —
        # 조용히 지우지 않는다.
        if item.get('fixed'):
            continue
        if not _KEY_RE.match(key):
            return None, ('목표 항목 키는 영문 소문자로 시작하는 32자 이내의 '
                          '영문·숫자·밑줄이어야 합니다: %s' % key)
        if key in seen:
            return None, '목표 항목 키가 중복됩니다: %s' % key
        seen.add(key)

        label = (item.get('label') or '').strip()
        if not label:
            return None, '목표 항목 %s 의 이름이 필요합니다' % key

        measurement = (item.get('measurement') or '').strip() or None
        if measurement is not None and measurement not in MEASUREMENTS:
            return None, ('알 수 없는 측정 종류: %s (센서가 쓰는 이름이어야 '
                          '합니다)' % measurement)

        shape = (item.get('shape') or 'instant').strip()
        if shape not in _TARGET_SHAPES:
            return None, '알 수 없는 목표 모양: %s' % shape

        lo, hi = item.get('min'), item.get('max')
        try:
            lo = None if lo in (None, '') else float(lo)
            hi = None if hi in (None, '') else float(hi)
        except (TypeError, ValueError):
            return None, '목표 항목 %s 의 범위가 숫자가 아닙니다' % key
        if lo is not None and hi is not None and lo >= hi:
            return None, '목표 항목 %s 의 범위가 뒤집혀 있습니다' % key

        entry = {
            'key': key, 'label': label,
            'unit': (item.get('unit') or '').strip() or None,
            'measurement': measurement, 'shape': shape,
            'min': lo, 'max': hi,
            'fixed': False, 'hidden': bool(item.get('hidden')),
        }
        derr = _apply_default(entry, item, lo, hi)
        if derr:
            return None, derr
        out.append(entry)
    return out, None


def _apply_default(entry, item, lo, hi):
    """항목의 **기본 목표값**을 얹는다 → error|None.

    ## 왜 기본값이 필요한가

    목표는 대개 작기 내내 같고, 단계마다 달라지는 것은 그중 일부다. 그런데 값을
    단계에만 둘 수 있으면 **바뀌지 않는 값도 단계 수만큼 다시 적어야 한다** —
    4단계 × 6항목이면 빈 칸 24개를 마주하고, 그중 20개는 같은 값을 옮겨 적는
    일이 된다. 실제로 만들어 보면 여기서 그만두게 된다.

    그래서 값을 **프로그램에 한 번** 적고, 달라지는 단계에서만 덮어쓴다.
    단계 값이 없으면 이 기본값이 그 단계의 목표다(`_stage_targets`).
    """
    raw = item.get('default')
    if raw in (None, ''):
        return None
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return '목표 항목 %s 의 기본값이 숫자가 아닙니다' % entry['key']
    if lo is not None and num < lo:
        return '%s 기본값이 범위를 벗어납니다 (%g 이상)' % (entry['label'], lo)
    if hi is not None and num > hi:
        return '%s 기본값이 범위를 벗어납니다 (%g 이하)' % (entry['label'], hi)
    entry['default'] = num
    return None


def _clean_targets(targets, defs):
    """단계 목표 검증 → (dict|None, error).

    빈 값은 **넣지 않는다**(`None` 으로 채우지 않는다) — 키가 있는데 값이 없으면
    읽는 쪽이 "0" 인지 "미지정" 인지 구분할 수 없다. 비어 있는 것은 정상이다:
    그 시설이 그 항목을 재지 못하는 것이 흔하고, 그때 빈칸이 옳은 답이다.

    범위는 **항목 정의**가 정한다(`min`/`max`). 틀린 값을 막기 위한 것이지 정답을
    정하는 것이 아니므로, 정의에 범위가 없으면 검사하지 않는다.
    """
    if targets in (None, '', {}):
        return None, None
    if not isinstance(targets, dict):
        return None, '목표 형식이 올바르지 않습니다'

    by_key = {d['key']: d for d in (defs or [])}
    out = {}
    for key, value in targets.items():
        spec = by_key.get(key)
        if spec is None:
            return None, ('알 수 없는 목표 항목: %s (프로그램의 목표 항목에 '
                          '먼저 추가하세요)' % key)
        if value in (None, ''):
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None, ('%s 값이 숫자가 아닙니다'
                          % (_public_target_def(spec).get('label') or key))
        lo, hi = spec.get('min'), spec.get('max')
        label = _public_target_def(spec).get('label') or key
        if lo is not None and num < lo:
            return None, ('%s 값이 범위를 벗어납니다 (%g 이상)' % (label, lo))
        if hi is not None and num > hi:
            return None, ('%s 값이 범위를 벗어납니다 (%g 이하)' % (label, hi))
        out[key] = num
    return (out or None), None




def _clean_resource_defs(defs):
    """자원 역할 정의 검증 → (list, error). `[{role, default}]`.

    **함수 uuid 를 받지 않는다**(P6 재설계, 2026-08-20). 프로그램은 "이 작물은
    관수를 쓴다" 까지만 말하고 무엇이 그 일을 하는지는 현장이 기하로 푼다 —
    계획이 현장을 미리 지정하면 충돌을 풀 방법이 없고, 같은 프로그램을 두 번째
    자리에서 쓰려면 복제해야 해서 작물 지식이 두 벌이 된다.

    `default` 는 **단계 기본값**이다(목표 항목의 `default` 와 같은 패턴). 관수는
    대개 작기 내내 필요하고 달라지는 것은 예외 쪽이라, 단계마다 적게 하면 안
    바뀌는 것을 단계 수만큼 다시 적어야 한다.
    """
    if defs in (None, ''):
        return [], None
    if not isinstance(defs, list):
        return None, '자원 정의 형식이 올바르지 않습니다'

    out = []
    seen = set()
    for item in defs:
        if isinstance(item, str):
            item = {'role': item}
        if not isinstance(item, dict):
            return None, '자원 항목 형식이 올바르지 않습니다'
        role = (item.get('role') or '').strip()
        if not role:
            continue
        if role not in _RESOURCE_ROLES:
            return None, '알 수 없는 자원 역할: %s' % role
        if role in seen:
            continue                       # 같은 역할을 두 번 적어도 한 번만
        seen.add(role)
        out.append({'role': role, 'default': bool(item.get('default', True))})
    return out, None


def _clean_stage_resources(value, rdefs):
    """단계의 자원 덮어쓰기 검증 → (dict|None, error). `{role: bool}`.

    **"이 단계는 쓰지 않는다" 와 "기본값을 따른다" 는 다른 사실이다.** 수확 전
    단수(斷水)처럼 일부러 끊는 단계가 있고, 그것을 빈 칸으로 표현하면 실수와
    구분되지 않는다. 그래서 덮어쓴 역할만 키로 담고, 없는 키는 기본값을 따른다.

    정의(`rdefs`)에 없는 역할은 거절한다 — 고아 값을 받아 두면 화면에 그릴
    근거가 없다(목표 값과 같은 규율).
    """
    if value in (None, '', {}, []):
        return None, None
    if not isinstance(value, dict):
        return None, '단계 자원 형식이 올바르지 않습니다'

    known = {d.get('role') for d in (rdefs or [])}
    out = {}
    for role, use in value.items():
        role = (role or '').strip()
        if not role:
            continue
        if role not in _RESOURCE_ROLES:
            return None, '알 수 없는 자원 역할: %s' % role
        if role not in known:
            return None, ('프로그램이 쓰지 않는 자원 역할입니다: %s '
                          '— 먼저 프로그램에 추가하세요' % role)
        out[role] = bool(use)
    return (out or None), None


# 광합성(Big-Leaf) 모델 상수와 허용 범위. 이름은 `CropParams` 와 **같다** —
# 그 계약이 이미 있었고, 새 이름을 지으면 같은 값이 두 이름을 갖는다.
#
# 범위는 **틀린 값을 막기 위한 것이지 정답을 정하는 것이 아니다**(작물마다
# 다르다). 좁게 잡으면 실제 작물을 거부하게 된다.
_PHOTO_FIELDS = {
    'T_base':     (-20.0, 40.0,   '기준온도(T_base)'),
    'A_max':      (0.1,   100.0,  '최대 광합성률(A_max)'),
    'K_L':        (1.0,   2000.0, '광 반포화 상수(K_L)'),
    'K_C':        (1.0,   3000.0, 'CO₂ 반포화 상수(K_C)'),
    'T_opt':      (-10.0, 50.0,   '최적 온도(T_opt)'),
    'T_sigma':    (0.5,   30.0,   '온도 응답 폭(T_sigma)'),
    'VPD_half':   (0.1,   10.0,   'VPD 반포화(VPD_half)'),
    'dli_target': (0.0,   80.0,   '권장 DLI'),
    'gdd_daily':  (0.0,   60.0,   '권장 일 적산온도'),
}


def _check_photosynthesis(photo):
    """`photosynthesis` 값 검증 → error|None.

    틀린 값이 들어가도 **에러가 나지 않는다** — 단계가 너무 빨리 넘어가거나
    영영 안 넘어가고, 광합성 모드가 엉뚱한 제한 요인을 고를 뿐이다. 그래서
    저장할 때 한 번 본다.

    모르는 키는 **거부하지 않는다** — 이 JSON 은 `CropParams` 와 같은 어휘라
    그쪽이 늘면 여기도 함께 늘어야 하는데, 거부하면 그때까지 저장이 막힌다.
    """
    if not isinstance(photo, dict):
        return None if photo in (None, '', {}) else '광합성 값 형식이 올바르지 않습니다'
    for key, (lo, hi, label) in _PHOTO_FIELDS.items():
        raw = photo.get(key)
        if raw in (None, ''):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return '%s 가 숫자가 아닙니다' % label
        if not (lo <= val <= hi):
            return '%s 가 범위를 벗어납니다 (%g~%g)' % (label, lo, hi)
        # **숫자로 되돌려 담는다.** 화면은 입력칸의 문자열을 보내므로 그대로
        # 두면 `"19.5"` 가 저장되고, 다음 저장 때 `"19.5" != 19.5` 라 바뀌지
        # 않았는데도 바뀐 것으로 잡힌다(버전이 헛돈다).
        photo[key] = val
    return None



def _clean_target_methods(methods, defs=None):
    """목표 곡선 참조 검증 → (dict|None, error).

    `{목표항목: Method.unique_id}`. 항목 어휘는 단계 목표와 **같아야 한다** —
    화면·해석이 두 어휘를 각자 기억하게 되면 한쪽만 고쳐진다. 그래서 프로그램의
    목표 항목 정의(`defs`)를 그대로 어휘로 쓴다.

    **실존하지 않는 Method 는 거절한다.** 죽은 참조를 두면 나중에 목표를 읽는
    쪽이 "곡선이 있는데 값이 안 나온다" 를 만나고, 그때는 원인이 프로그램인지
    함수인지 알 수 없다.
    """
    if methods in (None, '', {}):
        return None, None
    if not isinstance(methods, dict):
        return None, '목표 곡선 형식이 올바르지 않습니다'

    from aot.databases.models import Method

    known = {d['key'] for d in (defs or [])}
    out = {}
    for key, value in methods.items():
        if key not in known:
            return None, ('알 수 없는 목표 항목: %s (프로그램의 목표 항목에 '
                          '먼저 추가하세요)' % key)
        uuid = (value or '').strip() if isinstance(value, str) else value
        if not uuid:
            continue
        if Method.query.filter_by(unique_id=uuid).first() is None:
            return None, '메서드를 찾을 수 없습니다: %s' % uuid
        out[key] = uuid
    return (out or None), None


def _apply_fields(row, data):
    """수정 가능한 필드만 반영 → 내용이 바뀌었으면 True.

    **목표 항목 정의를 먼저 확정한다.** 단계 값·목표 곡선의 어휘를 그것이 정하므로
    순서가 뒤집히면 옛 어휘로 새 값을 검사하게 된다. `kind` 가 바뀌면 고정 항목도
    바뀌므로 정의는 **바뀐 뒤의 kind** 로 만든다.
    """
    changed = False
    kind_changed = False
    if 'kind' in data:
        kind = (data.get('kind') or '').strip()
        if kind not in VALID_KINDS:
            return None, '대상 종류 허용값 아님: %r' % kind
        if row.kind != kind:
            row.kind = kind
            changed = True
            kind_changed = True

    # 정의는 보내오지 않았으면 지금 것을 쓴다(부분 저장 규칙 — 키가 없으면 기존
    # 값을 지킨다). 단, `kind` 가 바뀌었으면 그 종류의 고정 항목이 섞여 들어와야
    # 하므로 어느 쪽이든 한 번은 정규화를 거친다.
    defs, derr = _clean_target_defs(
        data['target_defs'] if 'target_defs' in data else row.target_def_list(),
        row.kind)
    if derr:
        return None, derr
    # **지금 값도 정규화해서 견준다.** 컬럼이 비어 있어도 `target_def_list()` 는
    # 고정 항목으로 답하므로, 비교를 raw 컬럼으로 하면 아무것도 안 바꾼 저장이
    # `None != [...]` 로 잡혀 버전이 헛돈다(그러면 구획이 고정해 둔 버전과의
    # 차이가 의미를 잃는다).
    current, _cerr = _clean_target_defs(row.target_def_list(), row.kind)
    if current != defs:
        changed = True
    row.target_defs = defs

    # 자원 역할 정의 — 같은 부분 저장 규칙(키가 없으면 기존 값을 지킨다).
    rdefs, rderr = _clean_resource_defs(
        data['resource_defs'] if 'resource_defs' in data
        else row.resource_def_list())
    if rderr:
        return None, rderr
    if row.resource_def_list() != rdefs:
        row.resource_defs = rdefs
        changed = True

    for field in ('name', 'variety', 'notes', 'source_note'):
        if field not in data:
            continue
        value = data.get(field)
        if isinstance(value, str):
            value = value.strip()
        value = value or None
        if field == 'name' and not value:
            return None, '이름은 비울 수 없습니다'
        if getattr(row, field) != value:
            setattr(row, field, value)
            changed = True

    # 단계는 정의가 바뀌지 않았어도 다시 본다 — 항목을 숨기거나 지운 뒤 그 값이
    # 남아 있으면 화면에 그릴 라벨이 없는 고아가 된다. `stages` 를 보내지 않은
    # 부분 저장에서도 검사해야 그 고아를 저장 시점에 잡는다.
    stages_in = data['stages'] if 'stages' in data else row.stage_list()
    stages, err = _clean_stages(stages_in, defs, rdefs)
    if err:
        # 종류를 바꾼 것이 원인이면 그렇게 말한다 — "알 수 없는 목표 항목" 만
        # 보면 사람은 자기가 방금 종류를 바꾼 것과 연결짓지 못한다.
        if kind_changed:
            return None, ('%s — 대상 종류를 바꾸면 그 종류에 없는 목표 항목은 '
                          '사라집니다. 그 값을 먼저 지우고 다시 시도하세요.' % err)
        return None, err
    if row.stage_list() != stages:
        row.stages = stages
        changed = True

    if 'targets_methods' in data:
        tm, terr = _clean_target_methods(data.get('targets_methods'), defs)
        if terr:
            return None, terr
        if (row.targets_methods or None) != tm:
            row.targets_methods = tm
            changed = True

    if 'auto_advance' in data:
        row.auto_advance = bool(data.get('auto_advance'))

    if 'photosynthesis' in data:
        photo = data.get('photosynthesis') or None
        perr = _check_photosynthesis(photo)
        if perr:
            return None, perr
        if (row.photosynthesis or None) != photo:
            row.photosynthesis = photo
            changed = True
    return changed, None


def create_program(data, source='user'):
    """새 프로그램 → (dict, error).

    `source='ai'` 는 `reviewed_at` 이 비어 있으므로 **제어에 쓰이지 않는다**
    (모델 `usable_for_control`). AI 가 지어낸 단계 기간과 목표가 곧바로 온실
    설정이 되지 않게 하는 유일한 장치라, 여기서 자동으로 채우지 않는다.
    """
    if source not in _VALID_SOURCES:
        return None, 'source 허용값 아님: %r' % source

    name = (data.get('name') or '').strip()
    # `crop` 도 받는다 — AI 도구·옛 호출부가 그 이름을 쓴다. 저장은 `subject` 다.
    subject = (data.get('subject') or data.get('crop') or '').strip()
    kind = (data.get('kind') or 'vegetation').strip()
    if not name:
        return None, '이름이 필요합니다'
    if not subject:
        return None, '대상이 필요합니다'
    if kind not in VALID_KINDS:
        return None, '대상 종류 허용값 아님: %r' % kind

    # 목표 항목 정의가 먼저다 — 단계 값의 어휘와 범위를 그것이 정한다. 보내지
    # 않았으면 그 종류의 고정 항목만으로 시작한다(가축·시설은 빈 목록이라 사용자가
    # 첫 항목을 직접 만든다).
    defs, err = _clean_target_defs(data.get('target_defs'), kind)
    if err:
        return None, err

    # 자원 역할 정의 — 단계의 자원 덮어쓰기가 이 안에 있어야 한다.
    rdefs, err = _clean_resource_defs(data.get('resource_defs'))
    if err:
        return None, err

    stages, err = _clean_stages(data.get('stages'), defs, rdefs)
    if err:
        return None, err

    tmethods, err = _clean_target_methods(data.get('targets_methods'), defs)
    if err:
        return None, err

    tab_id, err = _resolve_tab_id(data.get('tab_id'))
    if err:
        return None, err

    row = GeoProgram(
        name=name, subject=subject, kind=kind,
        target_defs=defs,
        resource_defs=rdefs,
        variety=(data.get('variety') or '').strip() or None,
        source=source,
        source_ref=(data.get('source_ref') or None),
        source_note=(data.get('source_note') or None),
        derived_from=(data.get('derived_from') or None),
        stages=stages,
        targets_methods=tmethods,
        photosynthesis=data.get('photosynthesis') or None,
        auto_advance=bool(data.get('auto_advance')),
        notes=(data.get('notes') or None),
        tab_id=tab_id,
        version=1)
    try:
        db.session.add(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('[CropProgram] 생성 실패: %s', exc)
        return None, str(exc)
    return to_dict(row), None


def clone_program(program_uuid, data=None):
    """기존 프로그램을 **복제**해 내 것으로 만든다 → (dict, error).

    내장·외부를 고치는 유일한 방법이다. `derived_from` 은 **출처 기록**이지
    링크가 아니다 — 원본이 바뀌어도 복제본은 따라가지 않는다(따라가면 "내 것" 이
    아니게 된다).
    """
    data = data or {}
    src = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if src is None:
        return None, '프로그램을 찾을 수 없습니다: %s' % program_uuid

    payload = {
        'name': data.get('name') or ('%s (사본)' % src.name),
        'subject': data.get('subject') or data.get('crop') or src.subject,
        'kind': data.get('kind') or src.kind,
        'variety': data.get('variety', src.variety),
        'stages': data.get('stages') or src.stage_list(),
        # 정의를 함께 옮기지 않으면 사용자 항목이 사라지고, 그 값들이 고아가 되어
        # 복제 자체가 거절된다.
        'target_defs': data.get('target_defs') or src.target_def_list(),
        'photosynthesis': data.get('photosynthesis') or src.photosynthesis,
        'targets_methods': data.get('targets_methods') or src.targets_methods,
        'notes': data.get('notes', src.notes),
        'derived_from': src.unique_id,
        # 복제본은 **호출한 쪽이 보고 있던 탭**에 놓인다(안 넘기면 기본 탭).
        # 원본의 탭을 그대로 따라가지 않는다 — 내장/외부 프로그램은 탭이
        # 없을 수 있고, 사용자가 지금 보는 화면 맥락이 더 유의미하다.
        'tab_id': data.get('tab_id'),
    }
    return create_program(payload, source='user')


def update_program(program_uuid, data):
    """수정 → (dict, error). 내장·외부는 거절한다.

    **탭 소속(`tab_id`)은 예외다.** "무엇을, 어떤 단계로, 어떤 목표로 기르는가"
    라는 내용이 아니라 화면에서 어디 보이는지일 뿐이라, 내장·외부 프로그램도
    사용자가 원하는 탭으로 옮길 수 있어야 한다(안 그러면 내장 프로그램은 영원히
    첫 탭에 갇힌다). payload 가 `tab_id` 하나만 담고 있으면(geo/program 화면의
    탭 이동 드롭다운이 보내는 요청) `is_editable()` 게이트를 건너뛰고 탭만
    바꾼다 — 다른 필드가 하나라도 같이 오면 평소대로 내장·외부를 거절한다.
    """
    row = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if row is None:
        return None, '프로그램을 찾을 수 없습니다: %s' % program_uuid

    tab_only = set(data.keys()) <= {'tab_id'}
    changed = False

    if 'tab_id' in data:
        tab_id, err = _resolve_tab_id(data.get('tab_id'))
        if err:
            return None, err
        if tab_id != row.tab_id:
            row.tab_id = tab_id
            # 버전은 올리지 않는다 — 탭 이동은 내용이 아니라 조직 정보다.

    if not tab_only:
        if not row.is_editable():
            return None, ('내장·외부 프로그램은 직접 고칠 수 없습니다. '
                          '복제한 뒤 고치세요.')

        changed, err = _apply_fields(row, data)
        if err:
            db.session.rollback()
            return None, err

        # 사람이 AI 프로그램을 확인했다는 표시. 이게 있어야 제어에 쓸 수 있다.
        if data.get('reviewed') is True and row.reviewed_at is None:
            from aot.utils.time_utils import utc_now
            row.reviewed_at = utc_now()
            changed = True

    if changed:
        # 내용이 실제로 바뀔 때만 올린다 — 저장 버튼을 눌렀다는 이유로 올리면
        # 구획이 고정해 둔 버전과의 차이가 의미를 잃는다.
        row.version = (row.version or 1) + 1
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('[CropProgram] 수정 실패: %s', exc)
        return None, str(exc)
    return to_dict(row), None


def delete_program(program_uuid):
    """삭제 → (dict, error). **쓰는 구획이 있으면 거절한다.**

    지우면 그 작기가 "무엇을 목표로 길렀나" 의 근거를 잃는다. 화면은 `missing`
    으로 버티지만 그것은 사고를 견디는 장치이지 정상 경로가 아니다. 정말 지우려면
    구획에서 프로그램을 먼저 해제한다.
    """
    from aot.databases.models import GeoPlot

    row = GeoProgram.query.filter_by(unique_id=program_uuid).first()
    if row is None:
        return None, '프로그램을 찾을 수 없습니다: %s' % program_uuid

    used = GeoPlot.query.filter_by(program_uuid=program_uuid).count()
    if used:
        return None, ('이 프로그램을 쓰는 구획이 %d 건 있습니다. '
                      '먼저 그 구획에서 프로그램을 해제하세요.' % used)
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return None, str(exc)
    return {'ok': True, 'deleted': program_uuid}, None


def _public_target_def(item):
    """목표 항목 정의를 화면·AI 가 쓸 형태로 → dict.

    **고정 항목의 `label` 만 번역한다.** 그쪽은 msgid 이고 이미 번역이 있다.
    사용자가 만든 항목의 label 은 사람이 적은 문자열이라 번역하면 안 된다 —
    우연히 msgid 와 같은 글자를 적었을 때 엉뚱한 말로 바뀐다.

    번역은 요청 맥락 밖(데몬·AI 도구)에서도 불리므로 실패해도 원문으로 떨어진다.
    """
    out = dict(item)
    if item.get('fixed'):
        try:
            from flask_babel import gettext
            out['label'] = gettext(item.get('label') or '')
        except Exception:
            pass
    return out


def to_dict(row, with_stages=True):
    """API 응답 형태. 목록에서는 `with_stages=False` 로 단계를 뺀다."""
    out = {
        'unique_id': row.unique_id,
        'name': row.name,
        'kind': row.kind,
        'subject': row.subject,
        'variety': row.variety,
        'source': row.source,
        'source_ref': row.source_ref,
        'source_note': row.source_note,
        'derived_from': row.derived_from,
        'reviewed_at': row.reviewed_at.isoformat() if row.reviewed_at else None,
        'version': row.version,
        'tab_id': row.tab_id,
        'stage_count': len(row.stage_list()),
        'total_days': row.total_days(),
        'editable': row.is_editable(),
        'usable_for_control': row.usable_for_control(),
        'notes': row.notes,
    }
    # 검색용 지침 텍스트 — 단계 안의 `guidance`(자유 텍스트 지침)는 `with_stages`
    # 가 꺼진 목록 응답에는 원래 안 나간다(전체 stages 구조를 실으면 응답이
    # 커진다는 이유는 위 with_stages 분기 주석과 같다). 하지만 검색은 "제목
    # 말고 지침 속 단어로도 찾고 싶다"는 요구가 있어, 무거운 구조 전체 대신
    # 지침 문장만 뽑아 붙인다 — 목록·상세 어느 쪽이든 가볍게 함께 낸다.
    guidance_bits = [st.get('guidance') for st in row.stage_list()
                     if st.get('guidance')]
    out['guidance_text'] = ' '.join(guidance_bits) if guidance_bits else None
    # 곡선 유무는 목록에서도 보여야 한다 — "이 프로그램은 값이 변한다" 는 사실이
    # 단계 수만큼이나 중요하다.
    out['target_methods'] = row.targets_methods or {}
    # 목표 항목 정의는 **상세에서만** 낸다(목록에는 프로그램마다 여섯 줄 이상이
    # 붙어 응답만 커진다). 라벨은 여기서 번역해 내보낸다 — 화면이 각자 번역하면
    # 사용자 항목(번역하면 안 되는 것)까지 msgid 로 취급하게 된다.
    if with_stages:
        out['target_defs'] = [_public_target_def(d)
                              for d in row.target_def_list()]
        out['stages'] = row.stage_list()
        # 자원 역할 정의(P6). 단계는 `resources` 로 on/off 만 덮어쓴다 —
        # 함수 uuid 는 프로그램 어디에도 없다.
        out['resource_defs'] = row.resource_def_list()
        out['photosynthesis'] = row.photosynthesis
    out['auto_advance'] = bool(getattr(row, 'auto_advance', False))
    return out
