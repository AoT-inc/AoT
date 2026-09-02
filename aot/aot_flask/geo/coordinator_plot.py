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

import logging

from aot.aot_flask.geo import plot_context

logger = logging.getLogger(__name__)

# 이 코디네이터가 **목표로 쓰는** 항목과 단위. 여기 없는 단계 목표는 쓰이지
# 않고 화면에 참고로만 나간다(`display_state` 의 `unmapped`). 한계 필드
# (temp/humid min·max)는 여기 절대 넣지 않는다.
TARGET_MAP = (
    ('vpd', 'kPa'),
    ('co2', 'ppm'),
    ('dli', 'mol/m²/d'),
)

# 단계가 아니라 대상 단위 상수에서 오는 것(프로그램의 `photosynthesis`).
PHOTO_MAP = (
    ('gdd_daily', '°C·d/d'),
)

# Big-Leaf 광합성 모델 상수 — `CropParams` 와 **같은 이름**이다(그 계약이
# 이미 있었다). 새 이름을 지으면 같은 값이 두 이름을 갖는다.
MODEL_KEYS = ('A_max', 'K_L', 'K_C', 'T_opt', 'T_sigma', 'VPD_half')

# 제어 축을 **키 이름이 아니라 `(measurement, shape)` 으로** 찾는다.
#
# 목표 항목은 이제 프로그램마다 다르고 사용자가 이름을 붙인다(`target_defs`).
# 키 이름으로 찾으면 사용자가 만든 "실내 CO₂"(key=`co2_in`)는 영영 제어에 닿지
# 않고, 그 이유가 화면 어디에도 없다. 물리량으로 찾으면 이름이 무엇이든 닿는다.
#
# `shape` 까지 보는 이유: DLI 는 `radiation` 의 **일적산**이라 순간 광량과 같은
# 축에 놓으면 안 된다. 온도(`temperature`)도 주·야 두 항목이 같은 measurement 를
# 쓰지만 이 코디네이터의 목표 축이 아니다(아래 `unmapped`).
CONTROL_AXES = {
    'vpd': ('vapor_pressure_deficit', 'instant'),
    'co2': ('co2', 'instant'),
    'dli': ('radiation', 'daily'),
}


def axis_of(target):
    """단계 목표 한 줄 → 제어 축 이름 | None.

    `measurement` 가 없는 항목(사용자가 물리량을 고르지 않은 것)은 **어느 축에도
    닿지 않는다** — 코드는 자기가 뜻을 모르는 값으로 장비를 움직일 수 없다.
    """
    m = target.get('measurement')
    if not m:
        return None
    shape = target.get('shape') or 'instant'
    for axis, (want_m, want_shape) in CONTROL_AXES.items():
        if m == want_m and shape == want_shape:
            return axis
    return None


def _pick_by_axis(targets):
    """단계 목표 목록 → `{축: 목표}`.

    같은 축에 여러 항목이 걸리면(사용자가 CO₂ 항목을 하나 더 만든 경우)
    **고정 항목이 이긴다.** 고정 항목이 없는데 후보가 둘 이상이면 **아무것도
    고르지 않는다** — 둘 중 하나를 임의로 고르면 어느 값으로 도는지 화면과
    제어가 갈리고, 그 갈라짐은 "설정한 대로 안 돈다" 로만 드러난다.
    """
    cand = {}
    for t in targets or []:
        axis = axis_of(t)
        if axis:
            cand.setdefault(axis, []).append(t)
    out = {}
    for axis, items in cand.items():
        fixed = [t for t in items if t.get('fixed')]
        if len(fixed) == 1:
            out[axis] = fixed[0]
        elif len(items) == 1:
            out[axis] = items[0]
        # else: 모호하다 — 고르지 않는다.
    return out


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
           'started_on': None, 'ended_on': None, 'expected_end_on': None,
           'stage': None,
           'vpd': {'value': None, 'method_id': None},
           'co2': {'value': None, 'method_id': None},
           'dli': None, 'gdd_daily': None, 'T_base': None, 'model': {}}

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
    # **제어 지속 여부는 이 두 값이 정본이다** (2026-09-01, 구획 프로그램
    # 아키텍처). 코디네이터 자기 옵션의 별도 종료일(`schedule_end_time`)은
    # 없앴다 — 구획을 새로 심어도 사람이 그 날짜를 다시 고치기 전까지 계속
    # 멈춰 있던 것이 실제 사고였다(2026-08-30 영양·쿠마모토). `ended_on` 은
    # 이 구획이 실제로 끝난 날(사람이 확정)이고, `expected_end_on` 은 아직
    # 진행 중인 구획의 예상치일 뿐이라 제어를 멈추는 근거로 쓰지 않는다 —
    # R2(`plot_context.plot_for_coordinator`)가 이미 종료된 구획은 애초에
    # 여기까지 올려보내지 않는다.
    out['ended_on'] = row.ended_on
    out['expected_end_on'] = row.expected_end_on

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

    picked = _pick_by_axis(st.get('targets') or [])
    for axis, t in picked.items():
        if axis == 'dli':
            out['dli'] = _num(t.get('value'))
        else:
            out[axis] = {'value': _num(t.get('value')),
                         'method_id': t.get('method_uuid')}

    photo = prow.photosynthesis if isinstance(prow.photosynthesis, dict) else {}
    # Big-Leaf 모델 상수도 프로그램이 정본이다 — 코드에 박힌 작물 5종은 이제
    # 프로그램을 만들 때 값을 채워 주는 **출발점**일 뿐이다.
    out['model'] = {k: _num(photo.get(k)) for k in MODEL_KEYS
                    if photo.get(k) is not None}
    out['gdd_daily'] = _num(photo.get('gdd_daily'))
    # T_base 도 프로그램이 정본이다 — 없으면 코디네이터의 광합성 모델 작물에서
    # 온다. 둘이 다르면 같은 구획의 GDD 가 화면과 제어에서 갈린다.
    out['T_base'] = _num(photo.get('T_base'))
    return out


# ── 화면이 쓰는 프로그램 값 (목표 · 한계 · 곡선) ───────────────────────────
#
# 어휘가 여기 있는 이유: 무엇을 목표로 보고 무엇을 한계로 볼지는 이미 이 파일이
# 정하고 있다(TARGET_MAP · UNMAPPED_UNITS). 라우트마다 다시 고르면 시설 모달과
# 구획 모달이 같은 단계를 두고 다른 말을 하게 된다 — 실제로 그렇게 갈렸다.

def facility_env_coordinator(facility_uuid):
    """시설에 연결된 env_coordinator → CustomController (없으면 None). 활성 우선.

    링크 판정은 `custom_options` 의 `geo_facility_id_device_id`(구: `geo_facility_id`)
    다 — status·env_summary 가 쓰는 것과 **같은 기준**이어야 한다. 기준이 갈리면
    같은 시설을 두고 한 화면은 코디네이터가 있다 하고 다른 화면은 없다고 한다.

    라우트가 아니라 여기 있는 이유: "이 시설의 제어는 무엇인가" 는 도메인 질문이고,
    구획 화면(곡선 값 빌려오기)도 같은 답이 필요하다.
    """
    import json as _json
    from aot.databases.models.controller import CustomController

    def _belongs(fn):
        try:
            opts = _json.loads(fn.custom_options or '{}') or {}
        except (TypeError, ValueError):
            return False
        return (opts.get('geo_facility_id_device_id')
                or opts.get('geo_facility_id') or '') == facility_uuid

    try:
        matched = [f for f in CustomController.query
                   .filter_by(device='env_coordinator').all() if _belongs(f)]
    except Exception as exc:                                # noqa: BLE001
        logger.warning('[env_coordinator lookup] %s', exc)
        return None
    for f in matched:
        if f.is_activated:
            return f
    return matched[0] if matched else None


def _stage_values(plot_row, on=None):
    """진행 중인 단계의 목표 목록 → `(값dict, 곡선이름dict)`."""
    from aot.aot_flask.geo import plot_context
    st = plot_context.stage_of(plot_row, on=on)
    if not st or st.get('state') != 'running':
        return {}, {}
    vals, methods = {}, {}
    for t in (st.get('targets') or []):
        key = t.get('key')
        if t.get('value') is not None:
            vals[key] = t.get('value')
        elif t.get('source') == 'method':
            methods[key] = t.get('method_name') or ''
    return vals, methods


def program_targets(plot_row, on=None):
    """프로그램이 정한 **목표** → `{env_key: value}`.

    `TARGET_MAP` 과 같은 목록(vpd · co2 · dli)만 낸다. 주간·야간 온도와 습도는
    단계가 정한 **한계**이지 목표가 아니다 — 목표 칸에 넣으면 한계가 목표로
    둔갑한다(`display_state` 가 같은 이유로 `unmapped` 로 뺀다).
    """
    if plot_row is None:
        return {}
    vals, methods = _stage_values(plot_row, on=on)
    usable = {k for k, _u in TARGET_MAP}
    out = {k: v for k, v in vals.items() if k in usable}

    # 곡선으로 정해진 항목은 단계에 숫자가 없다. 그런데 이 구획이 시설에 있고
    # 그 시설에 코디네이터가 있으면 **그 곡선의 지금 값**이 이미 풀려 있다 —
    # 제어가 매 주기 계산해 쓰는 값이다. 빌려 오면 구획 화면과 시설 화면이
    # 같은 숫자를 말한다(따로 계산하면 두 화면이 갈린다).
    #
    # 코디네이터가 없으면(노지 등) 못 푼다 — 그때는 `program_target_methods` 가
    # 곡선 이름만 낸다.
    missing = [k for k in methods if k in usable and k not in out]
    fac = getattr(plot_row, 'facility_uuid', None)
    if missing and fac:
        for k, v in _coordinator_live_targets(fac).items():
            if k in missing and v is not None:
                out[k] = v
        missing = [k for k in missing if k not in out]

    # 코디네이터가 못 풀어 준 곡선은 **여기서 직접 푼다**.
    #
    # 노지 구획에는 코디네이터가 아예 없고(`facility_uuid` 가 None), 시설이어도
    # 코디네이터가 한 번도 안 돌았으면 스냅샷이 비어 있다. 그때 화면은 곡선
    # 이름만 받아 "곡선을 따름: vpd" 로만 적었다 — **목표가 정해져 있는데도
    # 숫자를 못 보여 주는 상태**다(2026-08-28 지적).
    #
    # 계산은 코디네이터가 하는 것과 **같은 호출**이다(`_helpers_mixin` 의 VPD·
    # CO₂ 경로): 같은 핸들러에 경과 주차와 시간대를 넘긴다. 그래야 시설 화면과
    # 구획 화면이 같은 숫자를 말한다 — 여기서 다르게 계산하면 두 화면이 갈린다.
    if missing:
        for k, v in _resolve_curve_targets(plot_row, missing, on=on).items():
            if v is not None:
                out[k] = v
    return out


def _resolve_curve_targets(plot_row, keys, on=None):
    """곡선이 걸린 항목의 **지금 값** → `{env_key: value}`.

    작기가 기준점이다 — 곡선의 몇 주차인지는 심은 날부터 센다(코디네이터는
    자기 시작 시각을 쓰지만, 구획에는 그것이 곧 작기다). 못 풀면 그 항목을
    빼고 돌려준다: 지어낸 숫자를 목표라고 적는 것보다 이름만 적는 편이 낫다.
    """
    import time as _time
    from datetime import date as _date, datetime as _dt, time as _t
    from aot.databases.models import GeoProgram

    puuid = getattr(plot_row, 'program_uuid', None)
    if not puuid:
        return {}
    prog = GeoProgram.query.filter_by(unique_id=puuid).first()
    curves = (getattr(prog, 'targets_methods', None) or {}) if prog else {}
    if not isinstance(curves, dict) or not curves:
        return {}

    started = getattr(plot_row, 'started_on', None)
    ref = on or _date.today()
    weeks = None
    start_dt = None
    if started is not None:
        weeks = max(0, (ref - started).days // 7)
        start_dt = _dt.combine(started, _t.min)

    out = {}
    for key in keys:
        uuid = curves.get(key)
        if not uuid:
            continue
        try:
            from aot.utils.method import load_method_handler
            handler = load_method_handler(uuid)
            if handler is None:
                continue
            value, ended = handler.calculate_setpoint(
                _time.time(), method_start_time=start_dt,
                weeks_elapsed=weeks, facility_tz=None)
            # 끝난 곡선은 값을 내지 않는다 — 마지막 값을 붙들고 있는 것은
            # 제어의 일이지(코디네이터가 `_vpd_last_sp` 로 한다) 표시의 일이
            # 아니다. 화면은 "곡선을 따름" 으로 돌아간다.
            if not ended and value is not None:
                out[key] = round(float(value), 2)
        except TypeError:
            # 인자를 그만큼 안 받는 곡선 종류(주차·시간대가 없는 것들).
            try:
                value, ended = handler.calculate_setpoint(
                    _time.time(), method_start_time=start_dt)
                if not ended and value is not None:
                    out[key] = round(float(value), 2)
            except Exception as exc:                        # noqa: BLE001
                logger.debug('곡선 목표 계산 실패(%s/%s): %s', key, uuid, exc)
        except Exception as exc:                            # noqa: BLE001
            logger.debug('곡선 목표 계산 실패(%s/%s): %s', key, uuid, exc)
    return out


def _coordinator_live_targets(facility_uuid):
    """코디네이터가 **마지막 사이클에 실제로 쓴** 목표 → `{key: value}`.

    곡선(메서드)이 걸린 항목의 지금 값은 여기에만 있다. `control_targets` 는
    곡선을 풀지 않는다 — `method_id` 만 넘긴다(메서드 종류마다 계산 인자가 달라
    조회 시점에 일반적으로 풀 수 없다는 것이 `_stage_targets` 의 판단이다).
    실제로 푸는 것은 데몬의 사이클이고, 그 결과가 `FunctionRuntimeState.
    summary_json` 에 남는다. 시설 모달이 읽는 것과 **같은 값**이다.

    ⚠ 스냅샷이다. 코디네이터가 멈춰 있으면 마지막 값이 남아 있고, 한 번도 돈 적이
    없으면 아무것도 없다. 그래서 "없으면 곡선 이름만" 으로 되돌아간다 — 지어낸
    숫자를 목표라고 적는 것보다 낫다.
    """
    import json as _json
    from aot.databases.models.function import FunctionRuntimeState

    try:
        fn = facility_env_coordinator(facility_uuid)
        if fn is None:
            return {}
        rs = FunctionRuntimeState.query.filter_by(
            function_id=fn.unique_id).first()
        if rs is None or not getattr(rs, 'summary_json', None):
            return {}
        summary = _json.loads(rs.summary_json) or {}
        tgt = summary.get('targets')
        return tgt if isinstance(tgt, dict) else {}
    except Exception as exc:                                # noqa: BLE001
        logger.debug('코디네이터 목표 스냅샷 읽기 실패(%s): %s',
                     facility_uuid, exc)
        return {}


def program_target_methods(plot_row, on=None):
    """목표가 **곡선**으로 정해진 항목 → `{env_key: 곡선 이름}`.

    곡선의 "지금 값" 은 여기서 구할 수 없다(`_stage_targets` 주석: 메서드 종류마다
    계산 인자가 다르다). 그래서 숫자 대신 **곡선을 따른다는 사실**만 낸다 —
    화면은 그 항목에 앱 기본 구간을 그리지 않는다. 곡선이 다스리는 값에 기본
    적정 범위를 겹쳐 그리면 두 기준을 동시에 말하게 된다.

    ⚠ 코디네이터가 붙어 있으면 그 **런타임 요약**에 곡선이 풀린 현재 값이
    들어 있다(`summary.targets`) — 시설 모달은 그것을 쓰므로 이 목록이 필요
    없다. 구획 모달은 코디네이터가 없을 수 있어 여기까지가 한계다.
    """
    if plot_row is None:
        return {}
    _v, methods = _stage_values(plot_row, on=on)
    usable = {k for k, _u in TARGET_MAP}
    out = {k: v for k, v in methods.items() if k in usable}

    # 곡선이 이미 **숫자로 풀렸으면 여기서 뺀다** — `program_targets` 가 그
    # 숫자를 내므로, 두 목록에 같은 키가 남으면 화면이 "목표 0.99" 와 "곡선을
    # 따름: vpd" 를 동시에 말하게 되고 사용자는 어느 것이 목표인지 다시 골라야
    # 한다. 판정은 한 곳에서 끝낸다.
    #
    # 푸는 길이 둘이라(코디네이터 스냅샷 · 여기서 직접 계산) 그 둘을 각각
    # 물어보지 않고 **결과 하나**를 본다 — 어느 길로 풀렸든 숫자가 있으면
    # 곡선 이름은 낼 일이 없다.
    if out:
        resolved = program_targets(plot_row, on=on)
        out = {k: v for k, v in out.items() if resolved.get(k) is None}
    return out


def program_limits(plot_row, on=None):
    """프로그램이 정한 **한계** → `{env_key: [값, …]}`.

    온도는 `temp_night` · `temp_day` 가 두 경계다. 어느 쪽이 큰지는 값이 정하게
    두고 여기서 "야간이 하한" 이라고 못 박지 않는다.

    습도는 값이 하나뿐이라 **한 줄만** 낸다. 그것이 상한인지 하한인지 아무도
    선언한 적이 없으므로 정하지 않는다 — 한쪽으로 단정하면 "습도가 낮아서
    문제" 를 "정상" 으로 읽게 만들 수 있다.

    키는 화면 어휘(측정 키 → env 이름)로 맞춘다.
    """
    if plot_row is None:
        return {}
    vals, _m = _stage_values(plot_row, on=on)
    out = {}
    temps = [vals[k] for k in ('temp_night', 'temp_day') if k in vals]
    if temps:
        out['temperature'] = sorted(temps)
    if 'rh' in vals:
        out['humidity'] = [vals['rh']]
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
    # 이 코디네이터가 목표로 쓰지 **않는** 항목 전부 — 주·야 온도와 습도(한계
    # 필드라 목표로 쓸 수 없다)와, 사용자가 만든 항목(물리량이 없거나 이 축에
    # 없는 것)이 여기로 온다. 숨기면 "왜 안 잡히지" 가 되고 목표 목록에 넣으면
    # 한계가 목표로 둔갑한다 — 그래서 따로 내고 화면이 "참고" 라고 말한다.
    used = {id(t) for t in _pick_by_axis((st or {}).get('targets') or []).values()}
    for t in ((st or {}).get('targets') or []):
        if id(t) in used or t.get('value') is None:
            continue
        out['unmapped'].append({'key': t.get('key'),
                                'label': t.get('label'),
                                'unit': t.get('unit'),
                                'value': t['value']})
    return out
