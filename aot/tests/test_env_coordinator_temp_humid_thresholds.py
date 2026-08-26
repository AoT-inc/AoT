# coding=utf-8
"""온습도 하드 임계(temp_max/min, humid_max/min) 오버라이드 회귀 테스트.

2026-07-29 발견: `_force_cool`/`_force_heat`/`_force_dehumid`/`_force_humid`
플래그가 _cycle_mixin.py 에서 세팅만 되고 어디서도 소비되지 않는 죽은
코드였다 — 사용자가 설정한 temp_max/min, humid_max/min 이 (debug_logging
꺼진 상태에서는) 완전히 무효였다. apply_temp_humid_threshold_overrides() 로
실제 강제 오버라이드를 wiring.
"""
import pytest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    apply_hvac_opposition_interlock,
    clamp_guide_range_to_hard_limits,
    apply_temp_humid_threshold_overrides,
    apply_threshold_and_gate_overrides,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _profiles(*kinds):
    return [ActuatorProfile(actuator_id=f'{k}-1', kind=k) for k in kinds]


def test_force_cool_prohibits_and_prevents_but_does_not_drive():
    """상한 초과는 **제약**이다 — 막을 뿐 몰지 않는다 (2026-08-26 재설계).

    예전에는 `GATE_BIT_HEAT`(폭염 **비상**)의 조합을 그대로 베껴 냉방기와
    개구부를 100% 로 켰다. 그래서 VPD 가 목표에 있는데도(제어 중심은 "할 일
    없음" 이라고 말하는데도) 참고값이 제어를 빼앗아 냉방기가 영원히 돌았다 —
    실외 35.1°C 에서 실내를 30 아래로 내릴 방법이 없으니 래치가 안 풀린다.
    """
    profiles = _profiles('opening', 'shade', 'cooler', 'heater', 'curtain')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_cool': True}, profiles, final_cmds)

    # 금지 — 더운데 가온하는 일은 없어야 한다.
    assert final_cmds.get('heater-1') == {'value': 0.0, 'reason': 'temp_max'}
    # 예방 — 차광막을 쳐서 일사 유입을 끊는다(규약: 0 = 차광막 닫음).
    assert final_cmds.get('shade-1') == {'value': 0.0, 'reason': 'temp_max'}
    # ⚠ 구동은 하지 않는다. 냉방 운전량은 **제어 중심(VPD)** 이 정한다.
    assert 'cooler-1' not in final_cmds, '참고값이 제어를 빼앗고 있다'
    assert 'opening-1' not in final_cmds, (
        '실외가 더 더울 수도 있다 — 여는 판단은 코디네이터가 한다')
    assert 'curtain-1' not in final_cmds


def test_force_heat_mirrors_gate_bit_cold_actuators():
    profiles = _profiles('opening', 'curtain', 'heater', 'shade', 'cooler')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_heat': True}, profiles, final_cmds)

    # 예방 — 찬 바깥공기 차단 · 보온커튼으로 열 손실 감소(규약: 0 = 닫음).
    assert final_cmds.get('opening-1') == {'value': 0.0, 'reason': 'temp_min'}
    assert final_cmds.get('curtain-1') == {'value': 0.0, 'reason': 'temp_min'}
    # 금지 — 추운데 냉방하는 일은 없어야 한다.
    assert final_cmds.get('cooler-1') == {'value': 0.0, 'reason': 'temp_min'}
    # ⚠ 구동은 하지 않는다(위 테스트 주석 참조).
    assert 'heater-1' not in final_cmds, '참고값이 제어를 빼앗고 있다'
    assert 'shade-1' not in final_cmds


def test_force_dehumid_uses_exhaust_fan_only():
    profiles = _profiles('exhaust_fan', 'opening', 'fogger')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_dehumid': True}, profiles, final_cmds)

    # 금지 — 습한데 가습하는 일은 없어야 한다. 배기 운전량은 VPD 가 정한다.
    assert final_cmds.get('fogger-1') == {'value': 0.0, 'reason': 'humid_max'}
    assert 'exhaust_fan-1' not in final_cmds, '참고값이 제어를 빼앗고 있다'
    assert 'opening-1' not in final_cmds


def test_force_humid_uses_fogger_only():
    profiles = _profiles('fogger', 'exhaust_fan')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_humid': True}, profiles, final_cmds)

    # 금지 — 건조한데 배기로 더 말리는 일은 없어야 한다.
    assert final_cmds.get('exhaust_fan-1') == {'value': 0.0, 'reason': 'humid_min'}
    assert 'fogger-1' not in final_cmds, '참고값이 제어를 빼앗고 있다'


def test_temp_and_humid_forces_never_collide_on_same_actuator():
    # 극단 케이스: 덥고 습한 상황 동시 발생 — 온도 강제(opening/shade/cooler)와
    # 습도 강제(exhaust_fan/fogger) 액추에이터 집합이 겹치지 않으므로 서로
    # 덮어쓰지 않아야 한다.
    profiles = _profiles('shade', 'heater', 'fogger', 'exhaust_fan')
    final_cmds = {}
    apply_temp_humid_threshold_overrides(
        {'_force_cool': True, '_force_dehumid': True}, profiles, final_cmds,
    )

    assert final_cmds.get('shade-1')  == {'value': 0.0, 'reason': 'temp_max'}
    assert final_cmds.get('heater-1') == {'value': 0.0, 'reason': 'temp_max'}
    assert final_cmds.get('fogger-1') == {'value': 0.0, 'reason': 'humid_max'}
    assert 'exhaust_fan-1' not in final_cmds


def test_no_breach_leaves_commands_untouched():
    profiles = _profiles('opening', 'shade', 'cooler', 'heater', 'curtain',
                         'exhaust_fan', 'fogger')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({}, profiles, final_cmds)

    assert final_cmds == {}


# ── 안전 프리게이트 우선순위 ────────────────────────────────────────────────

def test_safety_gate_wins_over_force_cool_in_high_wind():
    """강풍(풍향 차등 폐쇄) + 실내 고온 동시 발생 시 게이트가 이겨야 한다.

    한여름엔 실내 33~36°C(_force_cool 발동)와 강풍이 동시에 오는 게 흔하다.
    임계 오버라이드가 게이트보다 뒤에 적용되면 풍상측 개구부 폐쇄(0)를
    100으로 덮어써 강풍 속에 창을 활짝 열어버린다.
    """
    profiles = _profiles('opening', 'heater')
    final_cmds = {'opening-1': {'value': 100.0, 'reason': 1}}
    # 안전 프리게이트가 풍상측 개구부를 폐쇄하도록 강제한 상태.
    partial_overrides = {'opening-1': {'value': 0.0, 'reason': 'safety_pre_gate'}}

    apply_threshold_and_gate_overrides(
        {'_force_cool': True}, profiles, final_cmds, partial_overrides,
    )

    assert final_cmds['opening-1'] == {'value': 0.0, 'reason': 'safety_pre_gate'}, (
        '강풍 중 안전 게이트의 개구부 폐쇄를 다른 강제가 덮어썼다 — '
        '게이트가 마지막이 아니라는 뜻(안전 회귀).'
    )
    # 게이트가 건드리지 않은 액추에이터는 온도 제약이 그대로 살아 있어야 한다.
    assert final_cmds['heater-1'] == {'value': 0.0, 'reason': 'temp_max'}


def test_safety_gate_wins_over_light_min_shade_open():
    profiles = _profiles('shade')
    final_cmds = {}
    partial_overrides = {'shade-1': {'value': 0.0, 'reason': 'safety_pre_gate'}}

    apply_threshold_and_gate_overrides(
        {'_force_suplight': True}, profiles, final_cmds, partial_overrides,
    )

    assert final_cmds['shade-1'] == {'value': 0.0, 'reason': 'safety_pre_gate'}


def test_thresholds_still_apply_when_gate_inactive():
    profiles = _profiles('shade', 'heater')
    final_cmds = {}

    apply_threshold_and_gate_overrides({'_force_cool': True}, profiles, final_cmds, {})

    assert final_cmds['shade-1']  == {'value': 0.0, 'reason': 'temp_max'}
    assert final_cmds['heater-1'] == {'value': 0.0, 'reason': 'temp_max'}


# ─────────────────────────────────────────────────────────────────────────────
# 맞서는 짝 인터록 — 냉방과 난방이 동시에 돌지 않는다 (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────
# 인터록은 원래 Post-Gate 안에 있었는데, 그것은 임계 오버라이드보다 **앞**에서
# 돈다. 그 시점에는 아직 충돌이 없고(코디네이터가 난방 100 · 냉방 0), 충돌은
# 그 뒤 `_force_cool` 이 냉방을 100 으로 올리면서 **새로 생겼다** — 검사는
# 통과했는데 나가는 명령은 둘 다 100 이었다(실측: 温室環境制御, temp_max=30 ·
# 실내 32.7°C · 난방 근거는 온도가 아니라 VPD).

def _cost(v):
    return lambda env, pct: v


def test_interlock_catches_a_conflict_created_after_the_coordinator():
    """검사가 **모든 강제 뒤**에 있어야 한다는 것이 이 테스트의 전부다.

    인터록은 원래 Post-Gate 안(=코디네이터 직후)에 있었다. 그 시점에는 아직
    충돌이 없고, 충돌은 **그 뒤에 오는 강제**가 만든다 — 지금 그 자리는 안전
    프리게이트다(한파 게이트가 난방기를 100% 로 강제하는데 코디네이터는
    VPD 때문에 냉방기를 돌리고 있는 조합).
    """
    profiles = _profiles('cooler', 'heater')
    # 코디네이터가 남긴 상태 — 냉방기가 VPD 때문에 돌고 있다. 충돌 없음.
    final_cmds = {'cooler-1': {'value': 100.0, 'reason': 1},
                  'heater-1': {'value': 0.0, 'reason': 1}}
    apply_threshold_and_gate_overrides(
        {}, profiles, final_cmds,
        {'heater-1': {'value': 100.0, 'reason': 12}})   # 한파 게이트

    assert final_cmds['heater-1']['value'] == 100.0
    assert final_cmds['cooler-1']['value'] == 0.0, (
        '게이트가 만든 모순을 아무도 검사하지 않았다')


def test_safety_gate_beats_cost():
    """안전 게이트로 강제된 쪽이 **비용보다 앞이다.**

    예전 규칙은 "비용이 싼 쪽이 이긴다" 뿐이라, 게이트가 켠 난방기가 냉방이
    더 싸다는 이유로 꺼질 수 있었다 — 그러면 게이트의 뜻이 뒤집힌다.
    """
    profiles = _profiles('cooler', 'heater')
    profiles[0].cost_fn = _cost(1.0)   # 냉방이 훨씬 싸다
    profiles[1].cost_fn = _cost(9.0)
    final_cmds = {'cooler-1': {'value': 100.0, 'reason': 1}}
    apply_threshold_and_gate_overrides(
        {}, profiles, final_cmds,
        {'heater-1': {'value': 100.0, 'reason': 12}})

    assert final_cmds['heater-1']['value'] == 100.0
    assert final_cmds['cooler-1']['value'] == 0.0


def test_equal_rank_falls_back_to_cost():
    """강제된 쪽이 없으면 예전 규칙 그대로 — 싼 쪽이 이긴다."""
    profiles = _profiles('cooler', 'heater')
    profiles[0].cost_fn = _cost(9.0)
    profiles[1].cost_fn = _cost(1.0)
    final_cmds = {'heater-1': {'value': 100.0, 'reason': 1},
                  'cooler-1': {'value': 100.0, 'reason': 1}}
    apply_hvac_opposition_interlock(profiles, final_cmds)

    assert final_cmds['heater-1']['value'] == 100.0, '싼 쪽이 이겨야 한다'
    assert final_cmds['cooler-1']['value'] == 0.0


def test_interlock_has_exactly_one_implementation():
    """같은 규칙을 두 곳에 두면 갈라지고, 갈라지면 **늦게 도는 쪽**이 실질
    규칙이 된다. Post-Gate 의 옛 구현이 되살아나지 않는지 소스로 고정한다."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, '..', 'functions', 'utils', 'env_control',
                            'safety_gates.py'), encoding='utf-8').read()
    assert 'cooler_on and heater_on' not in src, (
        'Post-Gate 에 인터록이 되살아났다 — 임계 오버라이드보다 앞이라 '
        '그 뒤에 생기는 모순을 못 본다')


# ─────────────────────────────────────────────────────────────────────────────
# 하드 임계는 **목표의 한계**다 (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────
# 유도 범위와 하드 임계는 서로를 모르는 두 설정이라, 유도 상한이 더 높으면
# 파생 목표가 하드 상한 **밖**에 떨어진다. 그러면 코디네이터는 매 사이클
# "거기까지 데워라" 를 계산하고 하드 임계는 매 사이클 그것을 끈다 — 설정만으로
# 영구 교착이고, 나가는 명령은 서로 맞선다.

def test_guide_ceiling_is_capped_by_the_hard_ceiling():
    """실측 재현: 유도 상한 32(기본값) · temp_max 30 → 목표 31.97°C."""
    (t_min, t_max, _, _), changed = clamp_guide_range_to_hard_limits(
        (12.0, 32.0, 40.0, 85.0), temp_min=15.0, temp_max=30.0)

    assert t_max == 30.0, '목표가 하드 상한 밖에 설 수 있다'
    assert t_min == 15.0
    assert changed, '조용히 좁히면 사용자는 자기 설정이 안 쓰인 줄 모른다'


def test_a_guide_inside_the_hard_limits_is_left_alone():
    guide = (18.0, 28.0, 45.0, 80.0)
    out, changed = clamp_guide_range_to_hard_limits(
        guide, temp_min=15.0, temp_max=30.0, humid_min=30.0, humid_max=90.0)

    assert out == guide
    assert changed == []


def test_unset_limits_are_not_treated_as_zero():
    """0/None 은 "안 정했다" 다 — 유효한 한계로 받으면 목표가 0°C 로 눌린다."""
    guide = (12.0, 32.0, 40.0, 85.0)
    assert clamp_guide_range_to_hard_limits(guide)[0] == guide
    assert clamp_guide_range_to_hard_limits(
        guide, temp_min=0, temp_max=0, humid_min=0, humid_max=0)[0] == guide


def test_contradictory_settings_let_the_hard_limit_win():
    """좁힌 결과가 뒤집히면 하드 임계가 이긴다 — 유도 범위를 살리면
    "넘지 마라" 가 무의미해진다."""
    (t_min, t_max, _, _), _ = clamp_guide_range_to_hard_limits(
        (31.0, 33.0, 40.0, 85.0), temp_max=30.0)

    assert t_max == 30.0
    assert t_min <= t_max, '하한이 상한을 넘었다'


def test_humidity_uses_the_same_rule():
    (_, _, rh_min, rh_max), changed = clamp_guide_range_to_hard_limits(
        (12.0, 32.0, 20.0, 95.0), humid_min=30.0, humid_max=90.0)

    assert (rh_min, rh_max) == (30.0, 90.0)
    assert len(changed) == 2


def test_the_cycle_uses_the_shared_clamp():
    """유도 범위를 만드는 자리에서 이 함수를 **실제로** 부르는지 고정한다.

    판정이 두 벌이 되면 갈라지고, 갈라지면 느슨한 쪽이 실질 규칙이 된다.
    """
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, '..', 'functions', 'custom_functions',
                            'env_coordinator_impl', '_cycle_mixin.py'),
               encoding='utf-8').read()
    body = src.split('# Guide 범위', 1)[1].split('T_int  = internal.get', 1)[0]
    assert 'clamp_guide_range_to_hard_limits(' in body, (
        '유도 범위가 하드 임계를 안 지나간다')


# ─────────────────────────────────────────────────────────────────────────────
# 못 따라감 보고는 **강등된 변수에도** 서야 한다 (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────
# VPD 직접 제어 모드에서는 `_decompose_vpd` 가 온도·습도를 제어목표에서 빼므로
# `deviation_native` 에 없다. 그래서 이 판정이 온도로는 **한 번도 서지 않았다** —
# 냉방기가 몇 시간째 돌고 실내가 상한을 2°C 넘긴 채여도 화면은 조용했다.
#
# ⚠ 이것은 온도를 목표로 되살리는 것이 아니다. 제어는 여전히 VPD 하나가 하고,
#   여기서 하는 일은 **보고**뿐이다.

class _Strain:
    """`_assess_strain` 만 쓰는 최소 껍데기 — 데몬·DB 없이 판정을 부른다."""
    temp_max = 30.0
    temp_min = 15.0
    humid_max = 90.0
    humid_min = 30.0
    _STRAIN_KINDS = None
    _STRAIN_SATURATED_PCT = None
    _STRAIN_MIN_SEC = None


def _strain_host():
    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
        import CycleMixin as _M
    h = _Strain()
    h._STRAIN_KINDS = _M._STRAIN_KINDS
    h._STRAIN_SATURATED_PCT = _M._STRAIN_SATURATED_PCT
    h._STRAIN_MIN_SEC = _M._STRAIN_MIN_SEC
    h._assess_strain = _M._assess_strain.__get__(h)
    h._deviation_from_hard_limit = _M._deviation_from_hard_limit.__get__(h)
    return h


class _Sit:
    def __init__(self, dev, ctx):
        self.deviation_native = dev
        self.context = ctx


def _tv(value, tol):
    from aot.functions.utils.env_control.types import TargetVar
    return TargetVar(value=value, tolerance=tol, priority=1.0)


def test_strain_fires_on_temperature_even_when_it_is_demoted():
    h = _strain_host()
    # VPD 모드: deviation 에 온도가 없다. 실내 32.6 · 상한 30 · 래치 활성.
    sit = _Sit({'vpd': 0.01}, {'T_trend': 0.0})
    internal = {'T': 32.6, 'RH': 60.0, '_force_cool': True}
    target = {'temperature': _tv(30.0, 1.0), 'vpd': _tv(1.6, 0.1)}

    first = h._assess_strain(sit, target, {'cooler': 0.0}, sit.context, 1000.0,
                             internal_for_strain=internal)
    assert first is None, '15분 지속 조건이 사라졌다'

    later = h._assess_strain(sit, target, {'cooler': 0.0}, sit.context, 2000.0,
                             internal_for_strain=internal)
    assert later is not None, '온도로 못 따라감이 서지 않는다'
    assert later['var'] == 'temperature'
    assert later['reason'] == 'limit_breached'
    assert later['dev'] == pytest.approx(2.6)


def test_constraint_breach_does_not_require_saturation():
    """제어 중심(VPD)이 냉방을 요구하지 않으면 냉방기는 0% 다.

    포화를 요구하면 **바로 그 경우에** 화면이 조용해진다 — 고치려던 증상이다.
    """
    h = _strain_host()
    sit = _Sit({}, {'T_trend': 0.0})
    internal = {'T': 32.6, '_force_cool': True}
    target = {'temperature': _tv(30.0, 1.0)}

    h._assess_strain(sit, target, {'cooler': 0.0}, sit.context, 1000.0,
                     internal_for_strain=internal)
    out = h._assess_strain(sit, target, {'cooler': 0.0}, sit.context, 2000.0,
                           internal_for_strain=internal)
    assert out and out['reason'] == 'limit_breached'


def test_saturated_still_reads_as_equipment_limit():
    """최대로 밀고 있으면 '설비 한계' 다 — 사람이 할 일이 다르다."""
    h = _strain_host()
    sit = _Sit({}, {'T_trend': 0.0})
    internal = {'T': 32.6, '_force_cool': True}
    target = {'temperature': _tv(30.0, 1.0)}

    h._assess_strain(sit, target, {'cooler': 100.0}, sit.context, 1000.0,
                     internal_for_strain=internal)
    out = h._assess_strain(sit, target, {'cooler': 100.0}, sit.context, 2000.0,
                           internal_for_strain=internal)
    assert out and out['reason'] == 'saturated'


def test_no_latch_means_no_report():
    """선을 안 넘었으면 아무 말도 하지 않는다.

    래치를 근거로 삼는다 — 값을 여기서 다시 비교하면 진입/해제 문턱이 다른
    히스테리시스 **밖**에서 판정하게 되어 경계에서 떤다.
    """
    h = _strain_host()
    sit = _Sit({}, {'T_trend': 0.0})
    target = {'temperature': _tv(30.0, 1.0)}
    for ts in (1000.0, 2000.0):
        out = h._assess_strain(sit, target, {'cooler': 0.0}, sit.context, ts,
                               internal_for_strain={'T': 32.6})
        assert out is None


def test_improving_trend_is_not_a_limit():
    """목표 쪽으로 오고 있으면 기다리면 된다."""
    h = _strain_host()
    sit = _Sit({}, {'T_trend': -0.2})     # 내려가는 중
    internal = {'T': 32.6, '_force_cool': True}
    target = {'temperature': _tv(30.0, 1.0)}

    h._assess_strain(sit, target, {'cooler': 100.0}, sit.context, 1000.0,
                     internal_for_strain=internal)
    out = h._assess_strain(sit, target, {'cooler': 100.0}, sit.context, 2000.0,
                           internal_for_strain=internal)
    assert out is None


def test_strain_call_site_passes_internal():
    """`internal` 을 안 넘기면 강등된 변수의 판정이 **통째로 죽는다.**

    `_deviation_from_hard_limit` 이 None 을 받아 늘 None 을 돌려주므로 strain
    이 계속 null 이 된다 — 그런데 그것은 "선을 안 넘었다" 와 화면에서 구분되지
    않는다. 즉 고장이 조용하다. 그래서 배선을 소스로 고정한다.
    """
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, '..', 'functions', 'custom_functions',
                            'env_coordinator_impl', '_cycle_mixin.py'),
               encoding='utf-8').read()
    call = src.split("'strain':", 1)[1].split('\n', 4)
    assert any('internal_for_strain=internal' in ln for ln in call), (
        'strain 호출부가 internal 을 안 넘긴다')


def test_vent_form_reaches_the_profile():
    """개구부 형태가 **프로필까지** 실려야 효과 모델이 본다.

    fitting 에는 이미 `window`/`side_window` 구분이 있는데(2026-08-26 실측
    데이터), 그것을 액추에이터 레코드→프로필로 나르지 않으면 제어기는 끝까지
    구분을 모른다. 배선이 끊기면 조용하다 — 효과 모델은 `None` 을 받아
    예전처럼 동작하고, 화면은 아무 말도 하지 않는다.
    """
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    integ = open(os.path.join(here, '..', 'aot_flask', 'geo',
                              'facility_integration.py'), encoding='utf-8').read()
    loader = open(os.path.join(here, '..', 'functions', 'custom_functions',
                               'env_coordinator_impl', '_profile_loader_mixin.py'),
                  encoding='utf-8').read()
    types_ = open(os.path.join(here, '..', 'functions', 'utils', 'env_control',
                               'types.py'), encoding='utf-8').read()

    assert "'window':      'ridge'" in integ, 'fitting 종류 → 형태 표가 없다'
    assert "'vent_form':             _vent_form(f)" in integ, (
        '액추에이터 레코드가 형태를 안 싣는다')
    assert "vent_form=ar.get('vent_form')" in loader, (
        '로더가 형태를 프로필로 안 나른다')
    assert 'vent_form: Optional[str] = None' in types_, (
        'ActuatorProfile 에 형태 칸이 없다')


def test_gate_summary_lists_every_device_not_just_the_forced_ones():
    """강우 게이트는 개구부·분무만 건드린다 — 냉난방기도 **여전히 거기 있다.**

    강제된 것만 실으면 그 장치가 목록에서 통째로 사라져 사용자는 "어디 갔나"
    를 묻게 된다(2026-08-26 지적).

    건드리지 않은 장치의 `pct` 는 **None** 이다. 0 을 쓰면 "이번에 0 을
    명령했다" 가 되어, 켜져 있는 난방기에 "명령 0%" 가 붙는다.
    """
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, '..', 'functions', 'custom_functions',
                            'env_coordinator_impl', '_cycle_mixin.py'),
               encoding='utf-8').read()
    block = src.split('def _write_gate_only_summary', 1)[1].split(
        '\n    def ', 1)[0]
    assert 'for p in self._profiles\n' in block, '프로필 전수를 안 돈다'
    assert 'if p.actuator_id in (gate_result.forced_commands' not in block, (
        '강제된 장치만 싣고 있다')
    assert "if p.actuator_id in _fc else None)" in block, (
        '건드리지 않은 장치의 명령을 0 으로 지어내고 있다')

    popup = open(os.path.join(here, '..', 'aot_flask', 'static', 'js',
                              'widgets', 'AoT_map', 'aot-map-popup.js'),
                 encoding='utf-8').read()
    assert 'var commanded = (c.pct != null);' in popup, (
        '화면이 null 명령을 0 으로 읽는다')
    assert 'if (commanded && actual != null' in popup, (
        '명령하지 않은 장치에 명령 대조를 붙이고 있다')
