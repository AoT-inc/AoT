# coding=utf-8
"""VPD 직접 모드의 유도 온도 목표를 '온도 기준선' 으로 쓰던 남은 두 곳 점검 (2026-10-14).

PR #217·#218 이 과습 열림(2.65)과 야간 결로 탈출의 '보온 쪽' 판정에서 고친 것과 같은 함정이다. VPD 직접 모드의
`_temperature_constraint` 는 유도 온도 목표다 — `decompose_vpd_to_T_RH` 가 (실내 + 0.6 × 필요한 만큼)을 유도 범위 안으로 자른
값 ± 1 °C. 습한 밤에는 실내보다 위에, 건조한 밤에는 아래에 서므로 '실내 대 (그 목표 ± 허용오차)' 로 춥다·덥다를 가르면
VPD 오차의 부호가 판정을 한쪽으로 고정한다.

## 결론

1. `_evaluate_screens` 의 `T_low`/`T_high` — **고쳤다.** 보온커튼 밤 닫기(근거 49)와 커튼 틈의 열 손실 판정이 이 두 선을 읽는다.
   습한 밤에는 '늘 춥다'(범위 한가운데서도 커튼을 닫고, 난방기 없는 시설은 결로 틈을 0 으로 만든다), 건조한 밤에는 '늘 덥다'
   (유도 범위 아래로 식는 밤에도 커튼을 안 닫는다). 이제 `humid_regime.temp_band_c` 한 곳 — 온도 제어 모드는 목표 ∓ 허용오차,
   VPD 직접 모드는 유도 범위의 양 끝.
2. `coordinator.decide_parking` 2.55 의 `_demand` — **의도된 폴백이라 바꾸지 않았다.** 거기서 유도 목표는 '기준선' 이 아니라
   '가야 할 방향' 이다: 그 방향의 반대편 장치(습해서 위로 가야 하면 냉각기, 건조해서 아래로 가야 하면 난방기)를 쉬게 할 뿐,
   무엇을 열거나 닫는 판정이 아니다. 유도 목표가 유도 범위 안으로 잘려 있어 범위 밖으로 끌지 못하고, 부호는 VPD 오차에 따라
   양쪽 다 선다(아래 `TestDemandIsADirectionNotABaseline`).
"""
import inspect
import types

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin
from aot.functions.utils.env_control import coordinator as C
from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control import screen_policy as SP
from aot.functions.utils.env_control.situation import decompose_vpd_to_T_RH
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

# 김제 육묘장3 밤 유도 범위(낮은 22–32). VPD 목표는 0.8 kPa 로 둔다.
GUIDE_NIGHT = (12.0, 22.0, 60.0, 90.0)
VPD_SET = 0.8


def _derived(T_in, RH_in, guide=GUIDE_NIGHT, vpd=VPD_SET):
    """`_run_cycle` 이 만드는 유도 온도 목표 — 분해 뒤 유도 범위로 자른다, 허용오차 1 °C."""
    T_aux, _ = decompose_vpd_to_T_RH(vpd, T_in, RH_in, 0.6)
    return TargetVar(value=max(guide[0], min(guide[1], T_aux)), tolerance=1.0, priority=0.5, unit='°C')


def _vpd_sit(T_in, RH_in, guide=GUIDE_NIGHT):
    """VPD 직접 모드의 상황 — 온도는 `_temperature_constraint` 로 강등돼 있다."""
    return types.SimpleNamespace(
        target={'vpd': TargetVar(value=VPD_SET, tolerance=0.1, priority=1.2, unit='kPa'),
                '_temperature_constraint': _derived(T_in, RH_in, guide)},
        context={})


def _temp_sit(value=22.0, tol=1.0):
    return types.SimpleNamespace(
        target={'temperature': TargetVar(value=value, tolerance=tol, priority=0.5, unit='°C')},
        context={})


def _old_lines(situation, guide=GUIDE_NIGHT):
    """수정 전 `_evaluate_screens` 의 인라인 — 유도 목표로 폴백. 수정 전 값을 보이려고 시험에만 둔다."""
    tv = ((situation.target or {}).get('temperature')
          or (situation.target or {}).get('_temperature_constraint'))
    tol = float(getattr(tv, 'tolerance', 0.0) or 0.0) if tv is not None else 0.0
    if tv is None:
        return guide[0], guide[1]
    return float(tv.value) - tol, float(tv.value) + tol


def _lines(situation, guide=GUIDE_NIGHT):
    return CustomModule._screen_temp_band(situation, guide[:2])


def _cur(aid='c'):
    return types.SimpleNamespace(actuator_id=aid, kind='curtain',
                                 capacity_meta={'screen_positional': True})


# ─────────────────────────────────────────────────────────────────────────────
# 1. 기준 띠 — 정의는 한 곳(`humid_regime`)
# ─────────────────────────────────────────────────────────────────────────────

class TestTempBand:

    def _tv(self, v=22.0, tol=1.0):
        return TargetVar(value=v, tolerance=tol, priority=0.5, unit='°C')

    def test_temperature_control_mode_is_target_minus_and_plus_tolerance(self):
        assert HR.temp_band_c(self._tv(), 12.0, 22.0) == (pytest.approx(21.0), pytest.approx(23.0))

    def test_the_two_lines_are_the_edges_of_the_one_definition(self):
        tv = self._tv(21.4, 1.5)
        assert HR.temp_band_c(tv, 12.0, 22.0) == (HR.temp_edge_c(tv, 12.0), HR.temp_edge_c(tv, 12.0, upper=True))

    def test_vpd_direct_mode_is_the_guide_range_ends(self):
        assert HR.temp_band_c(None, 12.0, 22.0) == (12.0, 22.0)

    def test_the_low_line_is_the_one_the_vent_paths_use(self):
        """과습 열림·아침 습기 빼기가 읽는 VPD 모드의 선(`temp_edge_c`)과 스크린의 아래 선이 같은 값이다."""
        assert HR.temp_band_c(None, 12.0, 22.0)[0] == HR.temp_edge_c(None, 12.0)

    def test_unknown_is_not_invented(self):
        assert HR.temp_band_c(None, None, None) == (None, None)
        assert HR.temp_band_c(None, 12.0, None) == (12.0, None)


class TestScreenTempBand:

    def test_temperature_control_mode_is_unchanged(self):
        sit = _temp_sit(22.0, 1.0)
        assert _lines(sit) == (pytest.approx(21.0), pytest.approx(23.0))
        assert _lines(sit) == _old_lines(sit)

    @pytest.mark.parametrize('T_in,RH_in', [(19.0, 82.0), (20.8, 95.0), (16.0, 45.0), (14.0, 40.0)])
    def test_vpd_mode_is_the_guide_range_whatever_the_derived_target_does(self, T_in, RH_in):
        assert _lines(_vpd_sit(T_in, RH_in)) == (12.0, 22.0)

    def test_the_derived_target_follows_the_vpd_error_but_the_band_does_not(self):
        humid, dry = _vpd_sit(19.0, 82.0), _vpd_sit(16.0, 45.0)
        t_h = humid.target['_temperature_constraint'].value
        t_d = dry.target['_temperature_constraint'].value
        assert t_h > 19.0 + 1.0 and t_d < 16.0          # 습하면 실내 위, 건조하면 실내 아래
        assert _lines(humid) == _lines(dry) == (12.0, 22.0)

    def test_no_target_at_all_falls_back_to_the_guide_as_before(self):
        sit = types.SimpleNamespace(target={}, context={})
        assert _lines(sit) == (12.0, 22.0) == _old_lines(sit)

    def test_evaluate_screens_uses_the_one_helper(self):
        src = inspect.getsource(_cycle_mixin.CycleMixin._evaluate_screens)
        assert '_screen_temp_band(' in src
        assert '_temperature_constraint' not in src      # 유도 목표를 기준선으로 읽는 옛 폴백이 남아 있지 않다
        helper = inspect.getsource(CustomModule._screen_temp_band)
        assert 'HR.temp_band_c(' in helper and "'_temperature_constraint'" not in helper.split('"""')[2]


# ─────────────────────────────────────────────────────────────────────────────
# 2. 현실적인 밤 — 판정이 VPD 오차의 부호에 갇히지 않는다
# ─────────────────────────────────────────────────────────────────────────────

def _night_close(T, RH, T_ext, lines):
    lo, hi = lines
    return SP._curtain_night_close(SP.ScreenState(), {'T': T, 'RH': RH}, {'T': T_ext, 'RH': 60.0},
                                   [_cur()], False, lo, hi)


class TestNightCloseIsNotPinnedByTheVpdError:

    def test_humid_mild_night_does_not_read_as_cold(self):
        """실내 19 °C·RH 82 %(VPD ≈ 0.4, 목표 0.8) · 실외 14 °C — 범위(12–22)의 한가운데이고 결로 여유도 3 °C.
        유도 목표는 20.7 °C 로 실내보다 위에 서서 '목표 하한 + 2 = 21.7 > 19' → 늘 '춥다' 였다."""
        sit = _vpd_sit(19.0, 82.0)
        assert _night_close(19.0, 82.0, 14.0, _old_lines(sit)) == frozenset({'c'})     # 수정 전: 닫음
        assert _night_close(19.0, 82.0, 14.0, _lines(sit)) == frozenset()              # 수정 후: 열려 있음

    def test_dry_cold_night_below_the_guide_low_closes(self):
        """실내 16 °C·RH 45 %(건조) · 실외 10 °C — 실외가 범위 아래 끝(12) 아래라 보온이 필요하다.
        유도 목표는 14.9 °C 로 실내 아래에 서서 '실내 ≥ 위 선 − 1' → 늘 '덥다' 라 닫히지 않았다."""
        sit = _vpd_sit(16.0, 45.0)
        assert _night_close(16.0, 45.0, 10.0, _old_lines(sit)) == frozenset()          # 수정 전: 안 닫음
        assert _night_close(16.0, 45.0, 10.0, _lines(sit)) == frozenset({'c'})         # 수정 후: 닫음

    def test_below_the_guide_low_closes_in_both_directions_of_error(self):
        for T, RH in ((11.5, 85.0), (11.5, 45.0)):
            assert _night_close(T, RH, 9.0, _lines(_vpd_sit(T, RH))) == frozenset({'c'})

    def test_temperature_control_mode_is_decided_as_before(self):
        sit = _temp_sit(22.0, 1.0)
        for T, T_ext in ((11.7, 11.2), (22.5, 20.0), (25.0, 22.0), (17.5, 12.0)):
            assert _night_close(T, 70.0, T_ext, _lines(sit)) == _night_close(T, 70.0, T_ext, _old_lines(sit))


class TestCurtainGapHeatLoss:

    def _gap(self, T, RH, lines, heaters=()):
        profiles = [_cur()] + [types.SimpleNamespace(actuator_id=h, kind='heater', capacity_meta={})
                               for h in heaters]
        return SP._curtain_gap(SP.ScreenConfig(cycle_sec=600.0), SP.ScreenState(), {'T': T, 'RH': RH},
                               {'T': 14.0, 'RH': 70.0}, profiles, {'c': 0.0}, False, lines[0], 0.0)

    def test_humid_night_without_heaters_still_cracks_the_curtain(self):
        """난방기 없는 시설의 습한 밤(19 °C·RH 93 %, 이슬점 여유 1.1 °C). 유도 목표 22 → 하한 21 > 19 라 '난방기도 없는데 추운
        쪽' 으로 읽혀 틈이 0 이 되고 결로가 창으로 넘어갔다 — 결로가 가장 심한 때에 틈이 막혔다."""
        sit = _vpd_sit(19.0, 93.0)
        old, _, _ = self._gap(19.0, 93.0, _old_lines(sit))
        new, _, _ = self._gap(19.0, 93.0, _lines(sit))
        assert old == {}                      # 수정 전: 틈 없음
        assert new == {'c': SP.GAP_STEPS[0]}  # 수정 후: 첫 단계 3 %

    def test_below_the_guide_low_without_heaters_still_holds_the_gap(self):
        sit = _vpd_sit(11.0, 93.0)
        got, escape, _ = self._gap(11.0, 93.0, _lines(sit))
        assert got == {} and escape            # 범위 아래 끝 이하 — 열 손실이라 틈 0(종전과 같다)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 2.55 `_demand` — 의도된 폴백(바꾸지 않는다)
# ─────────────────────────────────────────────────────────────────────────────

def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


def _hvac(aid, kind):
    p = ActuatorProfile(
        actuator_id=aid, kind=kind, effect_model={'vpd': _effect('↑' if kind == 'heater' else '↓', 0.4)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)
    p.cmd_scale = 1.0
    return p


def _park(T_in, RH_in):
    sit = _vpd_sit(T_in, RH_in)
    sit.deviation_native = {'vpd': -0.3}
    ctx = {'cycle_sec': 600.0, 'T_int': T_in, 'RH_int': RH_in, 'T_ext': 12.0, 'RH_ext': 70.0,
           'vent_futility_gate': False, 'internal': {}, 'external': {}, 'T_guide_low': 12.0}
    sit.context = ctx
    return C.decide_parking([_hvac('h', 'heater'), _hvac('k', 'cooler')], sit, ctx, 600.0,
                            {'h': 0.0, 'k': 0.0}, log=False)


class TestDemandIsADirectionNotABaseline:
    """`_demand` 는 유도 목표 방향의 반대편 냉·난방을 쉬게 할 뿐 — 열고 닫는 기준선이 아니다."""

    def test_the_sign_follows_the_vpd_error_in_both_directions(self):
        humid = _park(18.0, 80.0)          # VPD 낮음 → 유도 목표 위(범위 안) → 난방 쪽 요구 → 냉각기 쉼
        dry = _park(21.0, 40.0)            # VPD 높음 → 유도 목표 아래 → 냉각 쪽 요구 → 난방기 쉼
        assert humid.opposing_ids == {'k'}
        assert dry.opposing_ids == {'h'}

    def test_near_the_derived_target_there_is_no_demand_either_way(self):
        pk = _park(20.5, 70.0)
        assert not pk.opposing_ids         # 유도 목표가 허용오차(1 °C) 안이면 어느 장치도 막지 않는다

    def test_the_derived_target_is_clamped_into_the_guide_so_it_never_pulls_outside_it(self):
        """매우 습해도 유도 목표는 범위 위 끝(22)을 넘지 못한다 — 22 °C 에서는 난방 요구가 서지 않는다."""
        assert _derived(21.5, 97.0).value <= GUIDE_NIGHT[1]
        assert not _park(21.5, 97.0).opposing_ids
        assert _derived(10.0, 40.0).value >= GUIDE_NIGHT[0]

    def test_the_humid_zone_vent_baseline_does_not_read_the_derived_target(self):
        """열고 닫는 판정(과습 열림 2.65)은 `warm_side` 로 유도 목표를 쓰지 않는다 — `_demand` 의 폴백과 섞이지 않는다."""
        src = inspect.getsource(C.decide_parking)
        assert 'HR.warm_side(' in src
        section = src.split('# ── 2.65.')[1].split('# ── 2.7')[0]
        code = '\n'.join(ln for ln in section.splitlines() if not ln.lstrip().startswith('#'))
        assert 'heat_demand=_warm_side' in code           # 인자 이름만 같을 뿐, 값은 `warm_side` 다
        assert '_demand =' not in code and '_demand ==' not in code and "_demand)" not in code


# ─────────────────────────────────────────────────────────────────────────────
# 4. VPD 직접 모드의 난방 출력 상한 — 유도 범위 상한에서 0 (2026-10-14, 폐루프 recorded/screens_heated)
# ─────────────────────────────────────────────────────────────────────────────
# 해가 지면 온도 범위는 22–32 → 12–22 로 한 번에 내려가는데 VPD 목표는 천천히 내려온다(18시 1.25 → 21시 0.9 kPa).
# 난방기는 VPD 항 하나만 받아(온도가 제어 목표가 아니다) 실내가 범위 상한을 넘은 22.5~24.5 °C 에서도 80~100 % 로 돌았다 —
# 맞서는 짝 파킹은 '유도 목표(= 상한으로 잘림) + 허용오차' 를 넘어야 서서 실제 문턱이 23 °C 였고, 선 위에서도 파킹은 20 %p/사이클로 내렸다.

class TestHeatCap:

    def test_vpd_mode_cap_falls_linearly_to_zero_at_the_guide_top(self):
        assert HR.heat_cap_pct(20.5, None, 12.0, 22.0) == pytest.approx(100.0)
        assert HR.heat_cap_pct(21.5, None, 12.0, 22.0) == pytest.approx(50.0)
        assert HR.heat_cap_pct(22.0, None, 12.0, 22.0) == 0.0
        assert HR.heat_cap_pct(24.0, None, 12.0, 22.0) == 0.0

    def test_the_top_is_the_one_definition_of_temp_band_c(self):
        top = HR.temp_band_c(None, 12.0, 22.0)[1]
        assert HR.heat_cap_pct(top, None, 12.0, 22.0) == 0.0
        assert HR.heat_cap_pct(top - HR.HEAT_CAP_BAND_C, None, 12.0, 22.0) == pytest.approx(100.0)

    def test_temperature_control_mode_has_no_cap(self):
        tv = TargetVar(value=22.0, tolerance=1.0, priority=0.5, unit='°C')
        assert HR.heat_cap_pct(24.0, tv, 12.0, 32.0) is None

    def test_the_hard_minimum_limit_wins(self):
        assert HR.heat_cap_pct(24.0, None, 12.0, 22.0, force_heat=True) is None

    def test_unknown_is_not_invented(self):
        assert HR.heat_cap_pct(None, None, 12.0, 22.0) is None
        assert HR.heat_cap_pct(21.0, None, 12.0, None) is None


def _heater(slew=20.0):
    p = _hvac('h', 'heater')
    p.cmd_constraints = CmdConstraints(slew_per_cycle=slew, min_on_pct=0.0)
    return p


def _heat_run(T_in, mode='vpd', prev=100.0, cycles=1, internal=None, top=22.0, deviation=-0.6):
    """VPD 가 목표보다 낮은(습한) 밤. 난방기 하나. 반환: 마지막 사이클의 명령."""
    from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
    st = CoordinatorState()
    st.prev_commands = {'h': prev}
    st.integral = {'h': prev}
    cmds = None
    for _ in range(cycles):
        sit = _vpd_sit(T_in, 82.0) if mode == 'vpd' else _temp_sit(24.0, 1.0)
        sit.target['vpd'] = TargetVar(value=VPD_SET, tolerance=0.1, priority=1.2, unit='kPa')
        sit.deviation_native = {'vpd': deviation}
        sit.context = {'cycle_sec': 600.0, 'T_int': T_in, 'RH_int': 82.0, 'T_ext': 14.0, 'RH_ext': 70.0,
                       'vent_futility_gate': False, 'internal': dict(internal or {}), 'external': {},
                       'T_guide_low': 12.0, 'T_ceiling': top}
        cmds, st = coordinate(sit, [_heater()], st, unique_id='')
    return cmds['h']


class TestHeaterAtTheGuideTop:

    def test_above_the_top_the_heater_is_cut_at_once_not_slewed_down(self):
        """수정 전: 22.6 °C(상한 22 + 0.6, 파킹 문턱 23 아래)에서 100 % 로 계속 돌았다. 선 위 파킹도 100 → 80 → 64 로 내렸다."""
        for T in (22.0, 22.6, 24.4):
            cmd = _heat_run(T)
            assert cmd.control_value() == 0.0, T

    def test_below_the_top_it_is_throttled_linearly(self):
        cmd = _heat_run(21.5)
        assert cmd.control_value() == pytest.approx(50.0)

    def test_well_inside_the_range_nothing_changes(self):
        cmd = _heat_run(18.0)
        assert cmd.control_value() > 50.0              # 습한 밤의 정상 가온

    def test_the_integral_does_not_wind_up_above_the_cap(self):
        from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
        st = CoordinatorState()
        st.prev_commands = {'h': 100.0}
        st.integral = {'h': 100.0}
        for _ in range(5):
            sit = _vpd_sit(22.6, 82.0)
            sit.deviation_native = {'vpd': -0.6}
            sit.context = {'cycle_sec': 600.0, 'T_int': 22.6, 'RH_int': 82.0, 'T_ext': 14.0, 'RH_ext': 70.0,
                           'vent_futility_gate': False, 'internal': {}, 'external': {},
                           'T_guide_low': 12.0, 'T_ceiling': 22.0}
            _, st = coordinate(sit, [_heater()], st, unique_id='')
        assert st.integral['h'] == 0.0

    def test_force_heat_is_an_exception(self):
        cmd = _heat_run(22.6, internal={'_force_heat': True})
        assert cmd.control_value() > 0.0

    def test_temperature_control_mode_is_unchanged(self):
        """온도가 제어 목표면 상한 캡이 없다 — 목표 24 ± 1 에서 22.6 °C 는 한참 아래라 계속 데운다."""
        cmd = _heat_run(22.6, mode='temp')
        assert cmd.control_value() > 0.0

    def test_the_reason_says_the_other_direction_is_needed(self):
        from aot.functions.utils.env_control.log_channels import REASON_OPPOSING_PARKED
        assert _heat_run(23.5).reason == REASON_OPPOSING_PARKED

    def test_the_cap_is_set_by_decide_parking(self):
        sit = _vpd_sit(22.6, 82.0)
        sit.deviation_native = {'vpd': -0.6}
        sit.context = {'cycle_sec': 600.0, 'T_int': 22.6, 'RH_int': 82.0, 'T_ext': 14.0, 'RH_ext': 70.0,
                       'vent_futility_gate': False, 'internal': {}, 'external': {},
                       'T_guide_low': 12.0, 'T_ceiling': 22.0}
        pk = C.decide_parking([_heater(), _hvac('k', 'cooler')], sit, sit.context, 600.0,
                              {'h': 100.0, 'k': 0.0}, log=False)
        assert pk.heat_cap_ids == {'h'} and pk.heat_cap_pct == 0.0
