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
    """노즐의 임자는 **물길**이 정한다 (2026-08-25 재설계).

    ⚠ 이 픽스처에는 **배관(`irrigation_pipe`)이 있어야 한다.** 예전에는
      밸브의 `pipe_id` 만 맞춰 두면 그 배관 노즐을 맡는 것으로 쳤는데, 지금은
      `resolve_nozzle_owners` 가 배관 폴리라인으로 물길을 세우고 밸브 하류를
      계산한다. 배관이 없으면 물길을 세울 수 없어 **회로 전체가 레이어 몫**이
      되고(그 판단은 옳다 — 밸브가 무엇을 맡는지 모르는 채 노즐을 임의로
      나눠 주지 않는다), 밸브는 맵에 아예 나오지 않는다.
      배관 없는 옛 픽스처가 그대로 남아 `KeyError: 'valve_B'` 로 실패하고
      있었다(2026-08-26 정리).

    ⚠ **노즐 하나는 정확히 한 액추에이터에만 속한다.** 그래서 레이어와 밸브의
      합이 노즐 수를 넘지 않는다 — 예전 기대값(레이어가 전부 + 밸브가 자기
      배관)은 같은 물을 두 번 세는 것이었다.
    """

    def _pipe(self, pid, pts):
        return {'kind': 'irrigation_pipe', 'id': pid, 'layer_id': 'L1',
                'sub_type': 'branch', 'is_vertical': False,
                'segments': [{'from': list(pts[i]), 'to': list(pts[i + 1])}
                             for i in range(len(pts) - 1)]}

    def _fittings(self):
        H = 2.0
        return [
            {'kind': 'irrigation_layer', 'id': 'L1', 'height_m': H,
             'actuator_id': 'pump_A'},
            # 공급 → 갈래 둘. 밸브는 p2 갈래 입구에 선다.
            self._pipe('p0', [(0, 0, 0), (0, H, 0)]),
            self._pipe('p1', [(0, H, 0), (0, H, 6)]),
            self._pipe('p2', [(0, H, 0), (6, H, 0)]),
            {'kind': 'irrigation_valve', 'id': 'V1', 'layer_id': 'L1',
             'pipe_id': 'p2', 'actuator_id': 'valve_B',
             'valve_type': 'on_off', 'position': {'x': 0.5, 'y': H, 'z': 0}},
            make_nozzle(x=0.0, z=3.0, pipe_id='p1'),
            make_nozzle(x=3.0, z=0.0, pipe_id='p2', flow_lph=5.0, radius_m=0.5,
                        orientation='up'),
        ]

    def test_layer_takes_what_no_valve_owns(self):
        """레이어 몫은 "어떤 밸브도 맡지 않은 노즐" 이다."""
        m = nozzles_by_actuator(self._fittings())
        assert m['pump_A']['count'] == 1          # p1 갈래만
        assert m['pump_A']['wetting'] is True     # 하향 스프링클러

    def test_valve_owns_its_downstream(self):
        """밸브는 자기가 선 자리에서 하류로 뻗은 구간을 맡는다."""
        m = nozzles_by_actuator(self._fittings())
        assert m['valve_B']['count'] == 1
        assert m['valve_B']['wetting'] is False   # 상향 미세포그만 담당

    def test_no_nozzle_is_counted_twice(self):
        """같은 물이 액추에이터 두 개로 등록되면 fogger 가 두 벌이 된다."""
        m = nozzles_by_actuator(self._fittings())
        assert sum(v['count'] for v in m.values()) == 2

    def test_without_pipes_the_layer_takes_everything(self):
        """물길을 세울 수 없으면 노즐을 임의로 나눠 주지 않는다.

        밸브가 무엇을 맡는지 모르는 상태에서 배관 id 만 맞춰 나누면, 화면에
        그려진 배관망과 계산이 어긋난다.
        """
        no_pipes = [f for f in self._fittings()
                    if f.get('kind') != 'irrigation_pipe']
        m = nozzles_by_actuator(no_pipes)
        assert m['pump_A']['count'] == 2
        assert 'valve_B' not in m

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

    def test_locks_even_without_nursery_mode(self):
        """육묘 모드를 꺼도 일소 잠금은 선다 (2026-08-25 변경).

        예전에는 이 잠금이 통째로 `nursery_mode` 안에 있어서, 딸기 온실이
        육묘 모드를 끄는 순간 두상 살수의 일소 보호가 함께 사라졌다.
        물방울이 렌즈가 되는 것은 어린 모종만의 일이 아니다 — 육묘 모드는
        이제 이 게이트를 켜는 스위치가 아니라 **더 조이는 축**이다.
        고정: [[test_fog_sunburn_gate]]
        """
        gate = SafetyPreGate(PreGateConfig())
        res = gate.evaluate(gate_ctx(light_est=900.0), [make_fogger()])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN

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

    def test_evening_block_is_honoured_however_it_was_set(self):
        """저녁 차단이 선언돼 있으면 모드와 무관하게 존중한다 (2026-08-25).

        실제로 이 플래그를 심는 곳은 육묘 모드뿐이라(`_cycle_mixin`)
        비육묘 설치에서는 나타나지 않는다. 그래도 판정을 모드로 다시 나누면
        "차단해 달라고 했는데 안 됐다" 가 생기므로 플래그를 그대로 따른다.
        """
        gate = SafetyPreGate(PreGateConfig())
        ctx = gate_ctx(light_est=20.0)
        ctx['internal']['evening_block'] = True
        res = gate.evaluate(ctx, [make_fogger()])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN

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

    def test_derates_without_nursery_mode(self):
        """감쇠도 육묘 모드를 전제하지 않는다 (2026-08-25).

        하드 잠금만 일반화하고 감쇠를 육묘에 남기면, 비육묘 설치에서 분무가
        release~lockout 구간에서 완만히 줄지 않고 절벽처럼 끊긴다.
        """
        fog = make_fogger()
        cmds = {fog.actuator_id: {'value': 80.0}}
        internal = _internal(200.0)
        internal.pop('_nursery_mode')
        self._derate(internal, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] < 80.0

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
        """육묘 감쇠는 **온습도 제약 뒤**에 적용된다.

        사용자가 설정한 최저 습도 때문에 일소 위험을 무릅쓰게 두면 안 된다.
        수정 전에는 _force_humid 가 마지막이라 100% 가 그대로 나갔다.

        ⚠ 2026-08-26 재설계로 `humid_min` 은 더 이상 분무를 **구동하지 않는다**
        (제약은 막을 뿐 몰지 않는다 — `apply_temp_humid_threshold_overrides`).
        그래서 100% 는 이제 **코디네이터가** 낸 값이고, 감쇠는 그 위에 걸린다.
        지키는 것은 같다: 순서.
        """
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import apply_threshold_and_gate_overrides
        fog = make_fogger()
        internal = _internal(200.0, _force_humid=True)
        cmds = {fog.actuator_id: {'value': 100.0, 'reason': 1}}
        apply_threshold_and_gate_overrides(internal, [fog], cmds, {})
        assert cmds[fog.actuator_id]['value'] == pytest.approx(50.0)
        # 제약이 분무를 켜지 않았다는 것도 함께 고정한다.
        cmds2 = {}
        apply_threshold_and_gate_overrides(internal, [fog], cmds2, {})
        assert fog.actuator_id not in cmds2, (
            'humid_min 이 분무를 구동하고 있다 — 제약이 목표가 됐다')

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

    def test_zero_outdoor_solar_is_not_a_measurement(self):
        """실외 일사 0.0 은 측정값으로 인정하지 않고 어림값으로 넘어간다.

        일사 센서를 지정하지 않은 ext_context_collector 가 solar 를 0.0 으로
        채워 공유하기 때문이다. 이 0.0 을 측정값으로 받으면 "센서 없음"이
        "한밤중"으로 둔갑해, 폴백을 둔 목적인 바로 그 시설에서 하드 잠금이 죽는다.
        """
        gate = SafetyPreGate(_nursery_cfg())
        ctx = self._ctx(600.0)
        ctx['external']['solar'] = 0.0
        res = gate.evaluate(ctx, [make_fogger()])
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN


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


# ─────────────────────────────────────────────────────────────────────────────
# 실운영 경로 회귀 — _build_gate_env() 산출물을 그대로 게이트에 먹인다
# ─────────────────────────────────────────────────────────────────────────────

class TestGateEnvEndToEnd:
    """코디네이터가 실제로 만드는 env 로 게이트를 돌리는 회귀 묶음.

    위쪽 게이트 테스트들은 ctx 를 손으로 조립해 `solar` 키를 직접 빼거나 넣었고,
    `_build_gate_env` 를 쓰는 테스트는 폴백 키가 전달되는지만 보고 게이트 평가까지
    가지 않았다. 그 틈으로 다음 버그가 살아남았다 — `_build_gate_env` 가 solar
    기본값 0.0 을 채워 넣는 바람에, 게이트의 3단 폴백(light_est → 실외 일사 →
    태양고도 어림값)에서 중간 단이 늘 0.0 으로 채워져 어림값에 영원히 도달하지
    못했다. 결과적으로 **일사 센서가 없는 육묘장은 감쇠만 받고 하드 잠금은 통째로
    죽은 채** 정오를 맞았다. 폴백을 넣은 목적이 바로 그 시설이었다.

    ext_context_collector 도 같은 팬텀을 만든다 — 일사 센서를 지정하지 않아도
    공유 컨텍스트에 `solar: 0.0` 을 넣는다. 그래서 게이트는 실외 일사를 **양수일
    때만** 측정값으로 인정한다.
    """

    @staticmethod
    def _gate_env(internal, external):
        from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin \
            import HelpersMixin

        class C(HelpersMixin):
            pass
        return C()._build_gate_env(internal, external)

    def _evaluate(self, internal, external, cfg=None):
        gate = SafetyPreGate(cfg or _nursery_cfg())
        fog = make_fogger()
        res = gate.evaluate(self._gate_env(internal, external), [fog])
        return res, fog

    @staticmethod
    def _internal(**kw):
        d = {'T': 25.0, 'RH': 60.0}
        d.update(kw)
        return d

    @staticmethod
    def _external(**kw):
        """ext_context_collector 공유 컨텍스트 형태."""
        d = {'T_ext': 25.0, 'RH_ext': 60.0, 'wind': 2.0, 'rain': 0.0}
        d.update(kw)
        return d

    def test_locks_on_fallback_when_no_solar_key_at_all(self):
        """실외 컨텍스트 자체가 없는 시설 — 어림값으로 잠겨야 한다."""
        res, fog = self._evaluate(
            self._internal(_nursery_light_fallback=640.0), self._external())
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
        assert res.forced_commands[fog.actuator_id]['value'] == 0.0

    def test_locks_despite_phantom_zero_from_ext_collector(self):
        """일사 센서 미지정 collector 가 넣는 0.0 이 어림값을 가로막지 않는다."""
        res, fog = self._evaluate(
            self._internal(_nursery_light_fallback=640.0),
            self._external(solar=0.0))
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
        assert res.forced_commands[fog.actuator_id]['value'] == 0.0

    def test_real_outdoor_measurement_is_used(self):
        """실제 일사 센서값(양수)은 그대로 판정에 쓰인다."""
        res, _ = self._evaluate(self._internal(), self._external(solar=700.0))
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN

    def test_indoor_estimate_beats_outdoor_solar(self):
        """차광막을 닫아 그늘이 지면 실외가 강해도 잠그지 않는다."""
        res, _ = self._evaluate(
            self._internal(light_est=50.0, _nursery_light_fallback=900.0),
            self._external(solar=900.0))
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_night_does_not_lock(self):
        """야간 — 실측 0.0 이든 어림값 0.0 이든 잠기지 않는다."""
        res, _ = self._evaluate(
            self._internal(_nursery_light_fallback=0.0),
            self._external(solar=0.0))
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_no_coordinates_and_no_sensor_does_not_lock(self):
        """좌표도 센서도 없으면 예전 동작 그대로 — 잠그지 않는다."""
        res, _ = self._evaluate(
            self._internal(_nursery_light_fallback=None), self._external())
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_lock_stays_partial_on_the_real_path(self):
        """실운영 env 에서도 분무만 끄고 시설 제어는 계속 돈다."""
        gate = SafetyPreGate(_nursery_cfg())
        env = self._gate_env(
            self._internal(_nursery_light_fallback=640.0), self._external())
        res = gate.evaluate(env, [make_fogger(), make_opening_profile()])
        assert res.partial is True
        assert res.triggered is False
        assert 'vent_01' not in res.forced_commands

    def test_fallback_is_used_without_nursery_mode(self):
        """어림값 폴백도 모드와 무관하다 (2026-08-25).

        일사 센서가 없는 설치가 정확히 폴백에 의존하는데, 그것을 육묘로
        묶어 두면 그런 설치의 일소 보호가 통째로 꺼진 채 돈다.
        """
        res, _ = self._evaluate(
            self._internal(_nursery_light_fallback=900.0),
            self._external(), cfg=PreGateConfig())
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN


# ─────────────────────────────────────────────────────────────────────────────
# 차광막 투과율 — 실외 일사 유입구 두 곳이 같은 결과를 내야 한다
# ─────────────────────────────────────────────────────────────────────────────

def make_shade(actuator_id='shade_01', tau=None):
    cap = {} if tau is None else {'shade_transmittance': tau}
    return ActuatorProfile(
        actuator_id=actuator_id,
        kind='shade',
        capabilities=['shade'],
        manual_lock=ManualLockState(),
        cmd_constraints=CmdConstraints(),
        capacity_meta=cap,
    )


class TestOutdoorSolarShadeConsistency:
    """실외 일사는 유입구가 둘인데, 차광막 개도는 한쪽에만 반영되고 있었다.

    - 시설 도면의 실외 센서 → `_collect_internal` 이 internal['light'] +
      `_light_is_outdoor` 로 넣는다 → 차광 반영 ✓
    - ext_context_collector → external['solar'] 로만 온다 → `_compute_light_est`
      가 보지 못해 게이트가 **원본 그대로** 판정했다 ✗

    그래서 실외 700 W/m² · 차광막 완전폐쇄(τ=0.3) · 잠금임계 250 인 같은 상황에서
    센서를 어느 수집기에 물렸느냐로 판정이 갈렸다 — 전자는 실내 210 으로 보고
    잠그지 않고, 후자는 700 으로 보고 잠갔다. 차광포 투과율을 도입한 목적
    (차광막이 만든 광부족을 광량 판정이 못 보는 맹점 제거)이 그 경로에서만
    무효가 되는 셈이다.
    """

    OUTDOOR = 700.0
    TAU     = 0.3
    SHADED  = 210.0     # 700 × (1 - 1.0 × (1 - 0.3))

    def _coord(self, aperture=0.0):
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import CycleMixin

        profiles = [make_fogger(), make_shade()]

        class _State:
            prev_commands = {'shade_01': aperture}

        class C(CycleMixin):
            unique_id           = 'x'
            debug_logging       = False
            nursery_mode        = True
            nursery_solar_lockout = 250.0
            nursery_solar_release = 150.0
            shade_transmittance = TestOutdoorSolarShadeConsistency.TAU
            _profiles           = profiles
            _coord_state        = _State()

            def _evening_fog_blocked(self):
                return False

            def _clear_sky_light_fallback(self):
                # 테스트에서 DB·좌표 조회를 타지 않게 고정한다.
                return None

        return C(), profiles

    def test_facility_outdoor_sensor_applies_shade(self):
        """기존 경로 — 회귀 감시용."""
        c, _ = self._coord()
        internal = {'T': 25.0, 'light': self.OUTDOOR, '_light_is_outdoor': True}
        c._compute_light_est(internal, {})
        assert internal['light_est'] == pytest.approx(self.SHADED)

    def test_ext_collector_solar_applies_shade(self):
        """새로 배선한 경로 — 같은 값이 나와야 한다."""
        c, _ = self._coord()
        internal = {'T': 25.0}
        c._compute_light_est(internal, {'solar': self.OUTDOOR})
        assert internal['light_est'] == pytest.approx(self.SHADED)

    def test_both_inlets_agree(self):
        """어느 수집기에 물렸든 판정 광량이 같아야 한다."""
        c1, _ = self._coord()
        a = {'T': 25.0, 'light': self.OUTDOOR, '_light_is_outdoor': True}
        c1._compute_light_est(a, {})

        c2, _ = self._coord()
        b = {'T': 25.0}
        c2._compute_light_est(b, {'solar': self.OUTDOOR})

        assert a['light_est'] == pytest.approx(b['light_est'])

    def test_facility_sensor_takes_priority(self):
        """더 가까운 실측인 시설 실외 센서가 collector 값을 이긴다."""
        c, _ = self._coord()
        internal = {'T': 25.0, 'light': 400.0, '_light_is_outdoor': True}
        c._compute_light_est(internal, {'solar': 900.0})
        assert internal['light_est'] == pytest.approx(400.0 * self.TAU)

    def test_indoor_sensor_is_never_shade_adjusted(self):
        """실내 광센서 값에는 차광이 이미 반영돼 있으므로 손대지 않는다."""
        c, _ = self._coord()
        internal = {'T': 25.0, 'light': 180.0}      # _light_is_outdoor 없음
        c._compute_light_est(internal, {'solar': 900.0})
        assert internal['light_est'] == pytest.approx(180.0)

    def test_phantom_zero_is_not_taken_as_measurement(self):
        """collector 의 팬텀 0.0 을 측정값으로 굳히면 어림값 폴백까지 막힌다."""
        c, _ = self._coord()
        internal = {'T': 25.0}
        c._compute_light_est(internal, {'solar': 0.0})
        assert 'light_est' not in internal
        assert internal['_nursery_light_fallback'] is None

    def test_open_shade_leaves_value_intact(self):
        """차광막이 걷혀 있으면(개도 100%) 감쇠 없이 원본 그대로."""
        c, _ = self._coord(aperture=100.0)
        internal = {'T': 25.0}
        c._compute_light_est(internal, {'solar': self.OUTDOOR})
        assert internal['light_est'] == pytest.approx(self.OUTDOOR)

    def test_gate_does_not_lock_under_closed_shade(self):
        """끝단 확인 — 차광막을 닫아 그늘이 지면 collector 경로도 잠그지 않는다."""
        from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin \
            import HelpersMixin

        c, profiles = self._coord()
        internal = {'T': 25.0, 'RH': 60.0}
        external = {'T_ext': 25.0, 'RH_ext': 60.0, 'solar': self.OUTDOOR}
        c._compute_light_est(internal, external)

        class H(HelpersMixin):
            pass
        res = SafetyPreGate(_nursery_cfg()).evaluate(
            H()._build_gate_env(internal, external), profiles)
        assert not (res.gate_mask & GATE_BIT_FOG_SUNBURN)

    def test_gate_still_locks_when_shade_is_open(self):
        """차광막이 걷혀 있으면 그대로 잠긴다 — 보호가 약해지지 않았다."""
        from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin \
            import HelpersMixin

        c, profiles = self._coord(aperture=100.0)
        internal = {'T': 25.0, 'RH': 60.0}
        external = {'T_ext': 25.0, 'RH_ext': 60.0, 'solar': self.OUTDOOR}
        c._compute_light_est(internal, external)

        class H(HelpersMixin):
            pass
        res = SafetyPreGate(_nursery_cfg()).evaluate(
            H()._build_gate_env(internal, external), profiles)
        assert res.gate_mask & GATE_BIT_FOG_SUNBURN
