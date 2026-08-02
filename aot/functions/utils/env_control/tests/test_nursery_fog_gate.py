# coding=utf-8
"""
육묘장 일소 방지 — 노즐 습윤 판정 / 안전 게이트 / 관수식 펄스 도징 테스트.

배경 (2026-07-31 aot-005 육묘장):
VPD 우선 제어에서 포그는 T↓·RH↑ 를 동시에 만들어 dVPD 이득이 압도적으로 크다.
그래서 VPD 편차가 최대인 정오 — 곧 일사가 최대인 시각 — 에 조율자가 분무를
최대로 선택했고, 상토를 막 뚫고 나온 자엽에 물방울이 맺힌 채 최대 일사를 받아
일소가 발생했다. 제어기가 "잎이 젖는다"는 사실 자체를 몰랐던 것이 근본 원인이다.
"""

import pytest

from aot.aot_flask.geo.irrigation_nozzles import (
    summarize_nozzles, nozzles_by_actuator, compute_precipitation,
)
from aot.functions.utils.env_control.dispatch_adapters import (
    PulsedDoseAdapter, TimeProportionalAdapter, VolumetricAdapter,
)
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_FOG_SUNBURN, GATE_BIT_HEAT,
)
from aot.functions.utils.env_control.safety_gates import (
    SafetyPreGate, PreGateConfig, is_wetting_fogger,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, ManualLockState,
)

from .conftest import make_ctx, make_opening_profile


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def make_nozzle(x=0.0, z=0.0, y=2.0, flow_lph=40.0, radius_m=2.0,
                sub_type='sprinkler', orientation='down', pipe_id='p1',
                layer_id='L1'):
    return {
        'kind': 'irrigation_device',
        'layer_id': layer_id,
        'pipe_id': pipe_id,
        'sub_type': sub_type,
        'orientation': orientation,
        'flow_lph': flow_lph,
        'radius_m': radius_m,
        'position': {'x': x, 'y': y, 'z': z},
    }


def make_fogger(actuator_id='fog_01', wetting=True, nozzle=None,
                constraints=None):
    cap = {}
    if nozzle is not None:
        cap['nozzle'] = nozzle
    elif wetting is not None:
        cap['nozzle'] = {'wetting': wetting, 'sprinkler_count': 1}
    return ActuatorProfile(
        actuator_id=actuator_id,
        kind='fogger',
        capabilities=['humidify'],
        manual_lock=ManualLockState(),
        cmd_constraints=constraints or CmdConstraints(),
        capacity_meta=cap,
    )


def gate_ctx(light_est=None, solar=400.0, **kw):
    ctx = make_ctx(solar=solar, **kw)
    if light_est is not None:
        ctx['internal']['light_est'] = light_est
    return ctx


class FakeControl:
    """output_on/output_off 호출을 기록하는 최소 스텁."""

    def __init__(self):
        self.calls = []

    def output_on(self, actuator_id, output_type=None, amount=None,
                  output_channel=None):
        self.calls.append(('on', actuator_id, output_type, amount))

    def output_off(self, actuator_id, output_channel=None):
        self.calls.append(('off', actuator_id, None, None))


# ─────────────────────────────────────────────────────────────────────────────
# 노즐 배치 → 습윤형 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestNozzleWettingClassification:
    def test_default_designer_sprinkler_is_wetting(self):
        """디자이너 기본값(40 L/h, 반경 2 m, 하향) = 습윤형.

        고압 미세포그는 노즐당 3~7 L/h, 확산 반경 1 m 미만이다. 그 6배 유량에
        반경 2 m 면 액적이 100µm 이상이라 잎에 닿는 즉시 맺힌다.
        """
        s = summarize_nozzles([make_nozzle()])
        assert s['wetting'] is True
        assert set(s['wetting_reasons']) == {'flow', 'radius', 'downward'}

    def test_high_pressure_fog_is_not_wetting(self):
        """고압 미세포그(5 L/h, 반경 0.6 m, 상향) = 비습윤 → 잠금 대상 아님."""
        s = summarize_nozzles([
            make_nozzle(flow_lph=5.0, radius_m=0.6, orientation='up')])
        assert s['wetting'] is False
        assert s['wetting_reasons'] == []

    def test_drip_only_is_not_wetting(self):
        """드립 전용은 잎에 닿지 않으므로 습윤형이 아니다."""
        s = summarize_nozzles([
            make_nozzle(sub_type='drip', flow_lph=2.0, radius_m=0.0)])
        assert s['wetting'] is False
        assert s['sprinkler_count'] == 0
        assert s['drip_count'] == 1

    def test_downward_alone_flags_wetting(self):
        """유량·반경이 미세포그급이어도 하향 직분사면 습윤형."""
        s = summarize_nozzles([
            make_nozzle(flow_lph=5.0, radius_m=0.5, orientation='down')])
        assert s['wetting'] is True
        assert s['wetting_reasons'] == ['downward']

    def test_empty_layout(self):
        s = summarize_nozzles([])
        assert s['count'] == 0
        assert s['wetting'] is False


# ─────────────────────────────────────────────────────────────────────────────
# 강수강도·중첩도
# ─────────────────────────────────────────────────────────────────────────────

class TestPrecipitation:
    def test_single_nozzle_intensity(self):
        """단일 노즐 강수강도 = flow / (π r²) [mm/h]."""
        p = compute_precipitation([make_nozzle(flow_lph=40.0, radius_m=2.0)])
        expected = 40.0 / (3.14159265 * 4.0)     # ≈ 3.18 mm/h
        assert p['precip_mm_h_max'] == pytest.approx(expected, rel=0.02)
        assert p['overlap_max'] == 1

    def test_overlap_accumulates(self):
        """살수 원이 겹치면 강수강도가 합산되고 중첩도가 올라간다.

        노즐 간격 1.5 m 에 반경 2 m 이면 인접 노즐이 반드시 겹친다 —
        디자이너 기본값이 바로 이 조합이라, 실제 배치에서 국소 과습윤이 생긴다.
        """
        devs = [make_nozzle(x=i * 1.5) for i in range(3)]
        p = compute_precipitation(devs)
        assert p['overlap_max'] >= 2
        single = 40.0 / (3.14159265 * 4.0)
        assert p['precip_mm_h_max'] > single * 1.9

    def test_grid_row_matches_hand_calculation(self):
        """1.5 m 간격 한 줄 배치의 최대 강수강도가 손계산과 맞는다."""
        devs = [make_nozzle(x=i * 1.5) for i in range(9)]
        p = compute_precipitation(devs)
        # 중앙부는 반경 2m 안에 좌우 각 1개씩 + 자기 자신 = 3개가 겹친다.
        single = 40.0 / (3.14159265 * 4.0)
        assert p['overlap_max'] == 3
        assert p['precip_mm_h_max'] == pytest.approx(single * 3, rel=0.02)

    def test_no_usable_nozzle_returns_zero(self):
        p = compute_precipitation([make_nozzle(radius_m=0.0)])
        assert p['precip_mm_h_max'] == 0.0
        assert p['overlap_max'] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 액추에이터별 노즐 귀속
# ─────────────────────────────────────────────────────────────────────────────

class TestNozzlesByActuator:
    def _fittings(self):
        return [
            {'kind': 'irrigation_layer', 'id': 'L1', 'height_m': 2.0,
             'actuator_id': 'pump_A'},
            {'kind': 'irrigation_valve', 'id': 'V1', 'layer_id': 'L1',
             'pipe_id': 'p2', 'actuator_id': 'valve_B'},
            make_nozzle(pipe_id='p1'),
            make_nozzle(x=1.5, pipe_id='p2', flow_lph=5.0, radius_m=0.5,
                        orientation='up'),
        ]

    def test_layer_actuator_sees_all_nozzles(self):
        m = nozzles_by_actuator(self._fittings())
        assert m['pump_A']['count'] == 2
        assert m['pump_A']['wetting'] is True     # 습윤형 노즐이 섞여 있음

    def test_valve_scopes_to_its_pipe(self):
        """밸브가 특정 배관에 붙어 있으면 그 배관 노즐만 본다."""
        m = nozzles_by_actuator(self._fittings())
        assert m['valve_B']['count'] == 1
        assert m['valve_B']['wetting'] is False   # 상향 미세포그만 담당

    def test_no_devices_returns_empty(self):
        assert nozzles_by_actuator([
            {'kind': 'irrigation_layer', 'id': 'L1', 'actuator_id': 'a'}]) == {}


# ─────────────────────────────────────────────────────────────────────────────
# is_wetting_fogger
# ─────────────────────────────────────────────────────────────────────────────

class TestIsWettingFogger:
    def test_non_fogger_is_never_wetting(self):
        assert is_wetting_fogger(make_opening_profile()) is False

    def test_nozzle_metadata_decides(self):
        assert is_wetting_fogger(make_fogger(wetting=True)) is True
        assert is_wetting_fogger(make_fogger(wetting=False)) is False

    def test_missing_nozzle_info_is_conservative(self):
        """노즐 정보가 없는 수동 등록 분무기는 습윤형으로 간주한다."""
        p = make_fogger(nozzle=None, wetting=None)
        assert is_wetting_fogger(p) is True


# ─────────────────────────────────────────────────────────────────────────────
# 안전 게이트 — 육묘 분무 잠금
# ─────────────────────────────────────────────────────────────────────────────

def _nursery_cfg(**kw):
    base = dict(nursery_mode=True, nursery_solar_lockout=250.0,
                nursery_solar_release=150.0)
    base.update(kw)
    return PreGateConfig(**base)


class TestNurseryFogGate:
    def test_locks_wetting_fogger_under_strong_light(self):
        gate = SafetyPreGate(_nursery_cfg())
        fog = make_fogger()
        res = gate.evaluate(gate_ctx(light_est=600.0), [fog])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
        assert res.forced_commands[fog.actuator_id]['value'] == 0.0

    def test_lock_is_partial_so_other_control_continues(self):
        """분무만 끄고 나머지 제어는 정상 진행해야 한다 (시설 비상 정지 아님)."""
        gate = SafetyPreGate(_nursery_cfg())
        res = gate.evaluate(gate_ctx(light_est=600.0),
                            [make_fogger(), make_opening_profile()])
        assert res.partial is True
        assert res.triggered is False
        assert 'vent_01' not in res.forced_commands

    def test_no_lock_below_threshold(self):
        gate = SafetyPreGate(_nursery_cfg())
        res = gate.evaluate(gate_ctx(light_est=100.0), [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_hysteresis_holds_lock_between_release_and_lockout(self):
        """한 번 잠기면 release 아래로 내려가야 풀린다 — 구름 지나갈 때 채터 방지."""
        gate = SafetyPreGate(_nursery_cfg())
        fog = [make_fogger()]
        gate.evaluate(gate_ctx(light_est=600.0), fog)          # 잠금
        res = gate.evaluate(gate_ctx(light_est=200.0), fog)    # 중간 구간
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
        res = gate.evaluate(gate_ctx(light_est=140.0), fog)    # release 아래
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_non_wetting_fogger_is_not_locked(self):
        """고압 미세포그는 고일사에 쓰는 것이 정석이므로 잠그지 않는다."""
        gate = SafetyPreGate(_nursery_cfg())
        res = gate.evaluate(gate_ctx(light_est=800.0),
                            [make_fogger(wetting=False)])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_disabled_when_nursery_mode_off(self):
        gate = SafetyPreGate(PreGateConfig())
        res = gate.evaluate(gate_ctx(light_est=900.0), [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_falls_back_to_outdoor_solar(self):
        """실내 추정 광량이 없으면 실외 일사로 판정한다."""
        gate = SafetyPreGate(_nursery_cfg())
        res = gate.evaluate(gate_ctx(solar=700.0), [make_fogger()])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN

    def test_no_light_data_does_not_lock(self):
        """광량을 전혀 모르면 잠그지 않는다 — 야간까지 잠기면 정상 가습이 막힌다."""
        gate = SafetyPreGate(_nursery_cfg())
        ctx = make_ctx()
        ctx['external'].pop('solar')
        res = gate.evaluate(ctx, [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_uses_clear_sky_fallback_when_no_light_measured(self):
        """광 측정이 하나도 없으면 태양고도 어림값으로 잠근다.

        일사 센서가 없는 시설이 흔한데, 폴백이 없으면 그런 시설은 일소 보호가
        통째로 꺼진 채 정오를 맞는다.
        """
        gate = SafetyPreGate(_nursery_cfg())
        ctx = make_ctx()
        ctx['external'].pop('solar')
        ctx['internal']['_nursery_light_fallback'] = 700.0
        res = gate.evaluate(ctx, [make_fogger()])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN

    def test_measured_light_wins_over_fallback(self):
        """실측이 있으면 어림값을 쓰지 않는다 — 차광 상태를 무시하면 안 된다."""
        gate = SafetyPreGate(_nursery_cfg())
        ctx = gate_ctx(light_est=50.0)
        ctx['internal']['_nursery_light_fallback'] = 900.0
        res = gate.evaluate(ctx, [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_gate_env_carries_the_fallback(self):
        """_build_gate_env 가 폴백 키를 게이트로 전달하는지.

        게이트용 internal 은 새 dict 로 재구성되므로, 키를 빠뜨리면 폴백이
        조용히 죽는다(감쇠만 되고 하드 잠금은 안 걸림).
        """
        from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin \
            import HelpersMixin

        class C(HelpersMixin):
            pass
        env = C()._build_gate_env(
            {'T': 25.0, 'RH': 60.0, '_nursery_light_fallback': 640.0},
            {'T_ext': 25.0, 'RH_ext': 60.0})
        assert env['internal']['_nursery_light_fallback'] == 640.0

    def test_evening_block_locks_regardless_of_light(self):
        """일몰 차단 구간에서는 광량이 낮아도 분무를 막는다.

        해가 진 뒤엔 일소 게이트가 풀리지만, 밤새 잎이 젖어 있으면 병해
        위험이 커진다. 육묘장은 밀식이라 확산이 빠르다.
        """
        gate = SafetyPreGate(_nursery_cfg(nursery_evening_fog=False))
        fog = make_fogger()
        ctx = gate_ctx(light_est=20.0)          # 해질녘 — 일소 기준으로는 안전
        ctx['internal']['evening_block'] = True
        res = gate.evaluate(ctx, [fog])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
        assert res.forced_commands[fog.actuator_id]['value'] == 0.0

    def test_evening_block_does_not_latch(self):
        """저녁 차단은 시간 기반이라 조건이 사라지면 즉시 풀린다.

        일사 래치처럼 붙잡아 두면 다음 날 아침까지 분무가 막힌다.
        """
        gate = SafetyPreGate(_nursery_cfg(nursery_evening_fog=False))
        fog = [make_fogger()]
        ctx = gate_ctx(light_est=20.0)
        ctx['internal']['evening_block'] = True
        assert gate.evaluate(ctx, fog).gate_mask & GATE_BIT_FOG_SUNBURN
        res = gate.evaluate(gate_ctx(light_est=20.0), fog)   # evening_block 해제
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_evening_block_ignored_when_mode_off(self):
        gate = SafetyPreGate(PreGateConfig())
        ctx = gate_ctx(light_est=20.0)
        ctx['internal']['evening_block'] = True
        res = gate.evaluate(ctx, [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_beats_heat_emergency(self):
        """폭염 게이트와 겹쳐도 분무 잠금이 이긴다.

        한여름 정오는 폭염 발동 조건이자 일소 위험이 최대인 시각이다.
        """
        gate = SafetyPreGate(_nursery_cfg(heat_ext_threshold=38.0,
                                          heat_int_threshold=35.0))
        fog = make_fogger()
        res = gate.evaluate(
            gate_ctx(light_est=800.0, T_int=36.0, T_ext=39.0),
            [fog, make_opening_profile()])
        assert res.gate_mask & GATE_BIT_HEAT
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
        assert res.forced_commands[fog.actuator_id]['value'] == 0.0
        # 폭염 대응(개구부 최대 개방)은 그대로 살아 있어야 한다.
        assert res.forced_commands['vent_01']['value'] == 100.0

    def test_wind_differential_closure_still_works(self):
        """분무 잠금이 켜져도 풍향 차등 폐쇄가 일괄 폐쇄로 퇴화하지 않는다."""
        cfg = _nursery_cfg(wind_threshold=10.0)
        gate = SafetyPreGate(cfg)
        windward = make_opening_profile(actuator_id='vent_S')
        windward.azimuth_deg = 180.0
        leeward = make_opening_profile(actuator_id='vent_N')
        leeward.azimuth_deg = 0.0
        ctx = gate_ctx(light_est=800.0, wind=15.0)
        ctx['external']['wind_dir'] = 180.0
        res = gate.evaluate(ctx, [windward, leeward, make_fogger()])
        assert res.partial is True
        assert res.forced_commands['vent_S']['value'] == 0.0
        assert 'vent_N' not in res.forced_commands   # 풍하측은 정상 운용


# ─────────────────────────────────────────────────────────────────────────────
# 관수식 펄스 도징
# ─────────────────────────────────────────────────────────────────────────────

class TestPulsedDoseAdapter:
    def test_relay_sends_bounded_pulse(self):
        """on/off 릴레이: 사이클 비례가 아니라 max_on_sec 기준 정량 펄스."""
        ctrl = FakeControl()
        a = PulsedDoseAdapter(TimeProportionalAdapter(),
                              max_on_sec=20.0, min_off_sec=600.0)
        a.send(ctrl, 'fog_01', 100.0, 0, cycle_sec=60.0)
        assert ctrl.calls == [('on', 'fog_01', 'sec', 20.0)]

    def test_pct_scales_pulse_length(self):
        ctrl = FakeControl()
        a = PulsedDoseAdapter(TimeProportionalAdapter(),
                              max_on_sec=20.0, min_off_sec=600.0)
        a.send(ctrl, 'fog_01', 50.0, 0, cycle_sec=60.0)
        assert ctrl.calls[0] == ('on', 'fog_01', 'sec', 10.0)

    def test_drying_interval_blocks_repeat(self):
        """분무 직후 min_off_sec 동안은 어떤 명령이 와도 뿌리지 않는다."""
        ctrl = FakeControl()
        a = PulsedDoseAdapter(TimeProportionalAdapter(),
                              max_on_sec=20.0, min_off_sec=600.0)
        a.send(ctrl, 'fog_01', 100.0, 0, cycle_sec=60.0)
        ctrl.calls.clear()
        for _ in range(5):
            a.send(ctrl, 'fog_01', 100.0, 0, cycle_sec=60.0)
        assert all(c[0] == 'off' for c in ctrl.calls)

    def test_resumes_after_drying_interval(self, monkeypatch):
        ctrl = FakeControl()
        a = PulsedDoseAdapter(TimeProportionalAdapter(),
                              max_on_sec=20.0, min_off_sec=600.0)
        a.send(ctrl, 'fog_01', 100.0, 0, cycle_sec=60.0)
        # 건조 시간이 지난 것처럼 시계를 되돌린다.
        a._blocked_until = 0.0
        ctrl.calls.clear()
        a.send(ctrl, 'fog_01', 100.0, 0, cycle_sec=60.0)
        assert ctrl.calls[0][0] == 'on'

    def test_zero_request_turns_off(self):
        ctrl = FakeControl()
        a = PulsedDoseAdapter(TimeProportionalAdapter(),
                              max_on_sec=20.0, min_off_sec=600.0)
        a.send(ctrl, 'fog_01', 0.0, 0, cycle_sec=60.0)
        assert ctrl.calls == [('off', 'fog_01', None, None)]

    def test_volumetric_pump_doses_millilitres(self):
        ctrl = FakeControl()
        a = PulsedDoseAdapter(VolumetricAdapter(flow_lpm=2.0),
                              max_on_sec=30.0, min_off_sec=600.0,
                              flow_lpm=2.0)
        a.send(ctrl, 'pump_01', 100.0, 0, cycle_sec=60.0)
        kind, _, otype, amount = ctrl.calls[0]
        assert (kind, otype) == ('on', 'vol')
        assert amount == pytest.approx(2.0 * 30.0 / 60.0 * 1000.0)   # 1000 mL

    def test_long_cycle_does_not_drop_pulse(self):
        """긴 사이클에서도 펄스가 최소 작동 임계(5%)에 걸려 사라지지 않는다.

        연속 변조 경로였다면 cycle 600s / on 20s = 3.3% 라 OFF 로 스냅된다.
        """
        ctrl = FakeControl()
        a = PulsedDoseAdapter(TimeProportionalAdapter(),
                              max_on_sec=20.0, min_off_sec=600.0)
        a.send(ctrl, 'fog_01', 100.0, 0, cycle_sec=600.0)
        assert ctrl.calls[0] == ('on', 'fog_01', 'sec', 20.0)


class TestPulseDosingFlag:
    def test_requires_both_parameters(self):
        assert CmdConstraints(max_on_sec=20.0, min_off_sec=600.0).pulse_dosing
        assert not CmdConstraints(max_on_sec=20.0).pulse_dosing
        assert not CmdConstraints(min_off_sec=600.0).pulse_dosing
        assert not CmdConstraints().pulse_dosing


# ─────────────────────────────────────────────────────────────────────────────
# 프로필 로더 — 펄스 도징 파라미터 결정
# ─────────────────────────────────────────────────────────────────────────────

class _FakeCoordinator:
    def __init__(self, **kw):
        self.nursery_mode = kw.get('nursery_mode', False)
        self.nursery_max_on_sec = kw.get('nursery_max_on_sec', 20.0)
        self.nursery_min_off_sec = kw.get('nursery_min_off_sec', 600.0)


class TestFogPulseConstraints:
    def _call(self, coord, kind='fogger', wetting=True):
        from aot.functions.custom_functions.env_coordinator_impl \
            ._profile_loader_mixin import _fog_pulse_constraints
        meta = {} if wetting is None else {'nozzle': {'wetting': wetting}}
        return _fog_pulse_constraints(coord, kind, meta)

    def test_wetting_fogger_pulses_even_without_nursery_mode(self):
        """습윤형 분무는 육묘가 아니어도 건조 간격이 필요하다 (병해 예방)."""
        c = self._call(_FakeCoordinator())
        assert c['max_on_sec'] == 30.0
        assert c['min_off_sec'] == 180.0

    def test_nursery_mode_tightens_the_pulse(self):
        c = self._call(_FakeCoordinator(nursery_mode=True))
        assert c['max_on_sec'] == 20.0
        assert c['min_off_sec'] == 600.0

    def test_non_wetting_fogger_keeps_continuous_modulation(self):
        """고압 미세포그는 연속 변조가 정상 — 펄스로 바꾸지 않는다."""
        assert self._call(_FakeCoordinator(nursery_mode=True),
                          wetting=False) == {}

    def test_other_kinds_untouched(self):
        assert self._call(_FakeCoordinator(nursery_mode=True),
                          kind='opening') == {}

    def test_missing_nozzle_info_is_conservative(self):
        """노즐 정보가 없으면 습윤형으로 보고 펄스를 건다."""
        c = self._call(_FakeCoordinator(), wetting=None)
        assert c['max_on_sec'] == 30.0


# ─────────────────────────────────────────────────────────────────────────────
# 감쇠 구간 + 오버라이드 우선순위
# ─────────────────────────────────────────────────────────────────────────────

def _internal(light_est, lockout=250.0, release=150.0, **kw):
    d = {
        '_nursery_mode': True,
        'light_est': light_est,
        '_nursery_solar_lockout': lockout,
        '_nursery_solar_release': release,
    }
    d.update(kw)
    return d


class TestNurseryFogDerate:
    def _derate(self, internal, profiles, cmds):
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import apply_nursery_fog_derate
        apply_nursery_fog_derate(internal, profiles, cmds)
        return cmds

    def test_midpoint_halves_the_command(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        self._derate(_internal(200.0), [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == pytest.approx(40.0)

    def test_below_release_untouched(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        self._derate(_internal(120.0), [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 80.0

    def test_at_lockout_reaches_zero(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        self._derate(_internal(250.0), [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == pytest.approx(0.0)

    def test_non_wetting_fogger_untouched(self):
        fog = make_fogger(wetting=False)
        cmds = {fog.actuator_id: {'value': 80.0}}
        self._derate(_internal(200.0), [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 80.0

    def test_disabled_without_nursery_mode(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        internal = _internal(200.0)
        internal.pop('_nursery_mode')
        self._derate(internal, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 80.0

    def test_no_light_data_untouched(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        self._derate(_internal(None), [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 80.0

    def test_evening_block_leaves_derate_to_the_gate(self):
        """저녁 차단 중에는 감쇠하지 않는다 — 게이트가 0 으로 강제한다.

        여기서 깎아 두면 게이트 강제값과 두 곳에서 같은 값을 만지게 된다.
        """
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        self._derate(_internal(200.0, evening_block=True), [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 80.0


class TestEveningWindow:
    """`_evening_fog_blocked()` — 일몰 전 차단 구간 판정."""

    def _coord(self, now_h, sunset_h=19, sunrise_h=6, allow=False, cutoff=120.0,
               st=object()):
        """가짜 코디네이터. 시각은 UTC 기준 시(hour)로 준다."""
        import datetime as _dt
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import CycleMixin

        day = _dt.datetime(2026, 7, 31, tzinfo=_dt.timezone.utc)
        sun = type('S', (), {
            'sunset':  None if sunset_h is None else day.replace(hour=sunset_h),
            'sunrise': None if sunrise_h is None else day.replace(hour=sunrise_h),
        })()

        class C(CycleMixin):
            unique_id = 'x'
            debug_logging = False
            nursery_evening_fog = allow
            nursery_evening_cutoff_min = cutoff
        c = C()
        return c, sun, day.replace(hour=now_h)

    def _run(self, monkeypatch, **kw):
        c, sun, now = self._coord(**kw)
        monkeypatch.setattr('aot.utils.solar.sun_times', lambda **k: sun)
        monkeypatch.setattr('aot.utils.timekit.utc_now', lambda: now)
        return c._evening_fog_blocked()

    def test_allowed_never_blocks(self, monkeypatch):
        assert self._run(monkeypatch, now_h=18, allow=True) is False

    def test_blocks_from_cutoff_before_sunset(self, monkeypatch):
        # 일몰 19:00, cutoff 120분 → 17:00부터 차단
        assert self._run(monkeypatch, now_h=17) is True
        assert self._run(monkeypatch, now_h=18) is True

    def test_open_before_cutoff(self, monkeypatch):
        assert self._run(monkeypatch, now_h=16) is False

    def test_still_blocked_before_next_sunrise(self, monkeypatch):
        """자정을 넘긴 새벽도 일출 전이면 계속 차단."""
        assert self._run(monkeypatch, now_h=3) is True

    def test_open_after_sunrise(self, monkeypatch):
        assert self._run(monkeypatch, now_h=8) is False

    def test_no_sun_times_does_not_block(self, monkeypatch):
        """좌표 미설정 등으로 태양시를 못 구하면 차단하지 않는다."""
        c, _, now = self._coord(now_h=18)
        monkeypatch.setattr('aot.utils.solar.sun_times', lambda **k: None)
        monkeypatch.setattr('aot.utils.timekit.utc_now', lambda: now)
        assert c._evening_fog_blocked() is False

    def test_polar_day_without_sunset_does_not_block(self, monkeypatch):
        assert self._run(monkeypatch, now_h=18, sunset_h=None) is False


class TestOverrideOrdering:
    def test_derate_beats_humid_min_force(self):
        """`humid_min` 이 분무를 100%로 강제해도 육묘 감쇠가 그 뒤에 적용된다.

        사용자가 설정한 최저 습도 때문에 일소 위험을 무릅쓰게 두면 안 된다.
        수정 전에는 _force_humid 가 마지막이라 100% 가 그대로 나갔다.
        """
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import apply_threshold_and_gate_overrides
        fog = make_fogger()
        internal = _internal(200.0, _force_humid=True)
        cmds = {}
        apply_threshold_and_gate_overrides(internal, [fog], cmds, {})
        assert cmds[fog.actuator_id]['value'] == pytest.approx(50.0)

    def test_safety_partial_override_still_wins(self):
        """안전 프리게이트(하드 잠금)는 감쇠보다 뒤 = 최우선."""
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import apply_threshold_and_gate_overrides
        fog = make_fogger()
        internal = _internal(200.0, _force_humid=True)
        cmds = {}
        apply_threshold_and_gate_overrides(
            internal, [fog], cmds,
            {fog.actuator_id: {'value': 0.0, 'reason': 12}})
        assert cmds[fog.actuator_id]['value'] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 태양고도 폴백 — 일사 센서가 없는 시설
# ─────────────────────────────────────────────────────────────────────────────

class TestClearSkyFallbackGate:
    """측정 광량이 하나도 없을 때 태양고도 어림값으로 일소를 잠그는지."""

    def _ctx(self, fallback):
        ctx = make_ctx(solar=None)
        ctx['internal'].pop('light_est', None)
        ctx['external']['solar'] = None
        if fallback is not None:
            ctx['internal']['_nursery_light_fallback'] = fallback
        return ctx

    def test_locks_from_fallback_when_no_sensor(self):
        gate = SafetyPreGate(_nursery_cfg())
        fog = make_fogger()
        res = gate.evaluate(self._ctx(600.0), [fog])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
        assert res.forced_commands[fog.actuator_id]['value'] == 0.0

    def test_fallback_below_threshold_does_not_lock(self):
        gate = SafetyPreGate(_nursery_cfg())
        res = gate.evaluate(self._ctx(100.0), [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_night_fallback_is_zero_so_no_lock(self):
        """해가 지면 어림값이 0 — 야간에 계속 잠기지 않는다."""
        gate = SafetyPreGate(_nursery_cfg())
        res = gate.evaluate(self._ctx(0.0), [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_measurement_wins_over_fallback(self):
        """측정값이 있으면 어림값은 쓰지 않는다 — 차광 닫힌 그늘까지 잠그면 안 된다."""
        gate = SafetyPreGate(_nursery_cfg())
        ctx = self._ctx(900.0)
        ctx['internal']['light_est'] = 100.0
        res = gate.evaluate(ctx, [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_without_coordinates_behaviour_is_unchanged(self):
        """좌표조차 없어 어림도 못 하면 예전처럼 잠그지 않는다."""
        gate = SafetyPreGate(_nursery_cfg())
        res = gate.evaluate(self._ctx(None), [make_fogger()])
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)


class TestClearSkyFallbackDerate:
    """감쇠 구간도 같은 폴백을 써야 분무가 절벽처럼 끊기지 않는다."""

    @staticmethod
    def _derate(internal, profiles, cmds):
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import apply_nursery_fog_derate
        apply_nursery_fog_derate(internal, profiles, cmds)

    def test_derate_uses_fallback(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        internal = _internal(None, _nursery_light_fallback=200.0)
        self._derate(internal, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == pytest.approx(40.0)

    def test_measurement_still_wins(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        internal = _internal(120.0, _nursery_light_fallback=250.0)
        self._derate(internal, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 80.0

    def test_no_fallback_leaves_command_untouched(self):
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        self._derate(_internal(None), [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == 80.0
