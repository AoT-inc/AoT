# coding=utf-8
"""코디네이터가 따르는 구획의 단계 목표 — **제어가 읽는 정본**.

정본 설계: `docs/design/coordinator-plot-targets.md`.

## 설정하는 곳은 한 군데다

목표(VPD·CO₂·DLI·GDD)와 기간은 프로그램에 있고, 코디네이터는 **안전
가이드라인과 장비**만 갖는다 — 한계(temp/humid min·max) · guide 범위 ·
액추에이터 · 우선순위 · 응급 · 게이트. 한때는 같은 값을 함수 옵션에도 두어
사람이 두 곳에 설정해야 했다(그 중복을 없앤 것이 이 모듈이다).

## 목표가 없는 것은 고장이 아니다

구획이 없는 시설, 시설에 연결되지 않은 코디네이터가 정상 구성이다. 그때
코디네이터는 예전부터 **guide 범위 중앙**으로 돌았다(`_cycle_mixin` 의 VPD
미설정 분기) — 즉 "안전 범위만 지킨다" 가 이미 정의된 동작이다.

## 온도·습도는 이 코디네이터의 목표가 아니다

1차 목표는 VPD 이고, 온도 목표는 VPD 를 분해해서 나온다.
`temp_max`/`temp_min`·`humid_max`/`humid_min` 은 설정 화면이 스스로
"Constraints — not a primary target" 이라 적어 둔 **한계**다(초과하면 VPD 목표를
무시하고 강제 냉·난방).

그래서 단계 목표 `temp_day: 24` 를 `temp_max` 에 넣으면 **목표가 한계로 둔갑한 채**
24도에서 냉방이 강제로 도는데 아무 에러도 나지 않는다. 그런 항목은 `unmapped`
로 따로 내고 화면이 "참고" 라고 말한다. **목표 목록에 추가하지 말 것.**
"""

from aot.aot_flask.geo import plot_context

# 이 코디네이터가 **목표로 쓰는** 항목과 단위. 여기 없는 단계 목표는 쓰이지
# 않으며(아래 `UNMAPPED_UNITS`), 한계 필드는 여기 절대 넣지 않는다.
TARGET_MAP = (
    ('vpd', 'kPa'),
    ('co2', 'ppm'),
    ('dli', 'mol/m²/d'),
)

# 단계가 아니라 대상 단위 상수에서 오는 것(프로그램의 `photosynthesis`).
PHOTO_MAP = (
    ('gdd_daily', '°C·d/d'),
)

# 단계에는 있으나 이 코디네이터가 목표로 쓰지 않는 항목 — 화면에 참고로만.
UNMAPPED_UNITS = {'temp_day': '°C', 'temp_night': '°C', 'rh': '%'}


def _options(fn):
    import json as _json
    try:
        return _json.loads(fn.custom_options) if fn.custom_options else {}
    except (TypeError, ValueError):
        return {}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


# ── Phase 3 — 제어가 구획을 **정본으로 읽는다** ────────────────────────────
#
# Phase 2 는 값을 옵션으로 **복사**했다. 그러면 같은 사실이 두 곳에 남고, 사람은
# 어느 쪽을 고쳐야 하는지 매번 판단해야 한다. 복사를 없애고 제어가 매 사이클
# 프로그램을 읽는다 — 설정하는 곳이 한 군데가 된다.
#
# 코디네이터에 남는 것은 **안전 가이드라인과 장비**다: 한계(temp/humid min·max) ·
# guide 범위 · 액추에이터 · 우선순위 · 응급 · 게이트. 목표가 없으면 코디네이터는
# 예전부터 guide 중앙값으로 돌았다(`_cycle_mixin` 의 VPD 미설정 분기) — 즉
# "구획이 없으면 안전 범위만" 이 이미 정의된 동작이다.

def control_targets(fn, on=None):
    """이 코디네이터가 지금 따라야 할 목표 → dict.

    ## 값과 곡선을 함께 낸다

    항목마다 `{'value': 숫자|None, 'method_id': uuid|None}` 이다. 곡선이 걸려
    있으면 그 항목은 시간에 따라 변하므로 숫자를 미리 정할 수 없다 — 제어가
    Method 를 직접 돌린다(예전에 `vpd_sp_type='method'` 가 하던 일이고, 이제
    그 선택은 프로그램의 `targets_methods` 에 있다).

    ## 검토 안 된 AI 프로그램은 제어에 쓰지 않는다

    `GeoProgram.usable_for_control` — AI 가 지어낸 단계 기간과 목표가 곧바로
    온실 설정이 되지 않게 하는 장치다. 여기서 우회하면 그 장치가 무의미해진다.

    ## 아무것도 없으면 빈 목표를 낸다 (**에러가 아니다**)

    구획이 없는 시설, 시설에 연결되지 않은 코디네이터가 정상 구성이다. 그때는
    목표 없이 guide 범위 안에서 돈다.
    """
    out = {'plot_uuid': None, 'plot_name': None, 'reason': 'none',
           'started_on': None, 'stage': None,
           'vpd': {'value': None, 'method_id': None},
           'co2': {'value': None, 'method_id': None},
           'dli': None, 'gdd_daily': None, 'T_base': None}

    scope = plot_context.plot_for_coordinator(fn, on=on)
    out['reason'] = scope.get('reason')
    if not scope.get('plot'):
        return out

    from aot.databases.models import GeoPlot, GeoProgram
    row = GeoPlot.query.filter_by(
        unique_id=scope['plot']['unique_id']).first()
    if row is None:
        return out

    out['plot_uuid'] = row.unique_id
    out['plot_name'] = row.subject or row.name
    out['started_on'] = row.started_on

    if not row.program_uuid:
        out['reason'] = 'no-program'
        return out
    prow = GeoProgram.query.filter_by(unique_id=row.program_uuid).first()
    if prow is None:
        out['reason'] = 'program-missing'
        return out
    if not prow.usable_for_control():
        # 사람이 확인하지 않은 AI 프로그램이다. 구획은 화면에 그대로 보이되
        # 목표는 내지 않는다 — 왜 안 잡히는지 `reason` 이 말한다.
        out['reason'] = 'program-unreviewed'
        return out

    prog = plot_context.program_brief(row)
    st = plot_context.stage_of(row, program=prog, on=on)
    if not st or st.get('state') != 'running':
        out['reason'] = 'no-stage'
        return out
    out['stage'] = {'name': st.get('name'), 'index': st.get('index'),
                    'total': st.get('total'), 'key': st.get('key')}
    out['reason'] = 'ok'

    for t in (st.get('targets') or []):
        key = t.get('key')
        if key in ('vpd', 'co2'):
            out[key] = {'value': _num(t.get('value')),
                        'method_id': t.get('method_uuid')}
        elif key == 'dli':
            out['dli'] = _num(t.get('value'))

    photo = prow.photosynthesis if isinstance(prow.photosynthesis, dict) else {}
    out['gdd_daily'] = _num(photo.get('gdd_daily'))
    # T_base 도 프로그램이 정본이다 — 없으면 코디네이터의 광합성 모델 작물에서
    # 온다. 둘이 다르면 같은 구획의 GDD 가 화면과 제어에서 갈린다.
    out['T_base'] = _num(photo.get('T_base'))
    return out


def display_state(fn, on=None):
    """설정 화면·시설 모달이 그리는 상태 → dict.

    `control_targets` 와 **같은 값**을 낸다(다른 경로로 다시 계산하지 않는다).
    예전에는 코디네이터가 목표를 따로 갖고 있어 "설정 대 목표" 를 견줘야 했지만,
    이제 견줄 것이 없다 — 화면이 하는 일은 "지금 무엇을 따르고 있는가" 를
    말하는 것뿐이다.

    `unmapped` 는 단계에는 있으나 **이 코디네이터가 목표로 쓰지 않는** 항목이다
    (주간·야간 온도·습도). 1차 목표가 VPD 이고 온도·습도 칸은 한계라, 숨기면
    "왜 안 잡히지" 가 되고 넣으면 한계가 목표로 둔갑한다.
    """
    scope = plot_context.plot_for_coordinator(fn, on=on)
    tgt = control_targets(fn, on=on)

    out = dict(scope)
    out['reason'] = tgt['reason']
    out['stage'] = tgt['stage']
    out['targets'] = []
    out['unmapped'] = []
    for key, unit in TARGET_MAP:
        item = tgt.get(key)
        if key == 'dli':
            val, method = tgt.get('dli'), None
        else:
            val, method = (item or {}).get('value'), (item or {}).get('method_id')
        if val is None and not method:
            continue
        out['targets'].append({'key': key, 'unit': unit, 'value': val,
                               'method_id': method})
    if tgt.get('gdd_daily') is not None:
        out['targets'].append({'key': 'gdd_daily', 'unit': '°C·d/d',
                               'value': tgt['gdd_daily'], 'method_id': None})

    if not tgt.get('plot_uuid'):
        return out

    # 단계 목표 중 이 코디네이터가 쓰지 않는 항목
    from aot.databases.models import GeoPlot
    row = GeoPlot.query.filter_by(unique_id=tgt['plot_uuid']).first()
    if row is None:
        return out
    st = plot_context.stage_of(row, on=on)
    for t in ((st or {}).get('targets') or []):
        if t.get('key') in UNMAPPED_UNITS and t.get('value') is not None:
            out['unmapped'].append({'key': t['key'],
                                    'unit': t.get('unit') or UNMAPPED_UNITS[t['key']],
                                    'value': t['value']})
    return out
