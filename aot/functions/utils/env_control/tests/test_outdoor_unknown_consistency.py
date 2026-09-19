# coding=utf-8
"""실외를 모를 때 개구부가 **한 가지로** 움직이는가 (2026-09-19).

## 무엇이 갈라져 있었나

두 층이 서로 다른 답을 냈다.

- 코디네이터 2.6(2026-08-22): 실외를 지어낸 값이면 개구부를 **제자리**에 둔다.
  "모른다는 이유로 장비를 움직이면 그 움직임 자체가 근거 없는 제어다."
- 안전 게이트 EXT_EXP: `last_ext_ts` 가 300초 넘으면 개구부·차광막을 **0 으로
  강제**. 디스패치 직전에 덮어써 늘 이겼다.

어느 쪽이 나오는지는 **설치 방식**이 정했다. 시설 실외 센서만 쓰면 `last_ext_ts`
가 없어 기본값 now → 영영 신선(제자리), 수집기를 쓰면 300초 뒤 폐쇄. 게다가
시설 센서 설치에서 비 오던 중 센서가 끊기면 강우 키가 사라져 0 으로 읽혀, 강우
게이트가 TTL 뒤 풀리고 창이 열릴 수 있었다. 수집기는 수집기대로 고장이라
(`[시각, 값]` 을 스칼라로 씀, 나이 판정이 늘 now) EXT_EXP 가 사실상 죽은 경로였다
— **수집기만 고쳤으면 정전 때 창 폐쇄가 조용히 살아났다.**

## 지금 규칙 (`docs/design/sensor-freshness-and-control-cadence.md` 규칙 A)

| 강우·풍속 | 온습도 | 개구부 |
|---|---|---|
| 받음 | 받음·승계 | 정상 |
| 받음 | 지어냄 | 제자리 (2.6) |
| 잃음, 마지막 값 위험 | 무관 | 닫힌 채 (게이트 래치) |
| 잃음, 마지막 값 평온 | 승계 | 제자리 또는 닫기 — **더 열지 않음** (2.7) |
| 잃음, 마지막 값 평온 | 지어냄 | 제자리 |

예외: 온도 하드 상한(`temp_max`, `_force_cool`) 위에서는 "더 열지 않음" 을 걸지
않는다 — 고온 피해는 몇 분이면 오고 빗물은 복구할 수 있다(2026-09-19 결정).
차광막은 두절로 강제하지 않는다(강우·강풍 게이트도 건드리지 않는 내부 시설).

## 적분

상한은 coordinate() **안에서** 건다. 밖에서 자르면 적분이 모른 채 감겨, 값이
돌아오는 순간 창이 튄다 — 이 도메인이 여러 번 데인 모양이다. 그래서 여기서는
명령만이 아니라 **적분이 실제 개도를 따라가는가**와 **풀린 뒤 튀지 않는가**
(bumpless)를 함께 고정한다.
"""
import time

import pytest

import aot.functions.ext_context_collector as ecc
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_threshold_and_gate_overrides)
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin)
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, limit_vent_for_unknown_outdoor,
    vent_open_ceiling_ids)
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.ext_context_fallback import (
    ExtContextCache, build_fallback_context)
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_EXT_EXP, GATE_BIT_RAIN, REASON_NO_OUTDOOR_DATA)
from aot.functions.utils.env_control.safety_gates import SafetyPreGate
from aot.functions.utils.env_control.situation import assess, compute_vpd
from aot.functions.utils.env_control.types import ActuatorProfile, TargetVar

from .conftest import make_heater_profile, make_opening_profile

START = 55.0
# 야간 습함 — 실내 VPD 0.39 < 목표 0.46 → 마른 실외면 창을 **열고** 싶어진다.
HUMID_NIGHT = {'T': 22.8, 'RH': 86.0}
DRY_OUTSIDE = {'T_ext': 30.0, 'RH_ext': 45.0}
# 실외가 더 습하면 열어 봐야 소용없다 → 무익 게이트가 창을 **닫는** 쪽으로 보낸다.
WET_OUTSIDE = {'T_ext': 21.0, 'RH_ext': 99.0}


def _profiles():
    v = make_opening_profile('v1')
    v.effect_model = build_effect_model('opening', {})
    s = ActuatorProfile(actuator_id='sh1', kind='shade', safe_default=100.0)
    s.effect_model = build_effect_model('shade', {})
    return [v, s]


class _Coordinator:
    """`_run_cycle` 가 들고 다니는 사이클 간 상태만 가진 얇은 대역.

    실제 코드를 부르는 곳: `_collect_external_context`(실물) · `_build_gate_env`
    (실물) · `SafetyPreGate.evaluate`(실물) · `assess`/`coordinate`(실물) ·
    `apply_threshold_and_gate_overrides`(실물). 옮겨 적은 것은 `_run_cycle` 의
    실외 신선도 분기와 context 주입 몇 줄뿐이다 — 거기가 바뀌면 이 대역도 고칠 것.
    """

    def __init__(self, outdoor_sensors=False, start=START):
        import logging
        self.logger = logging.getLogger('test.outdoor_unknown')
        self._sensors_resolved_outdoor = (
            [{'input_uuid': 'wx', 'sensor_role': 'outdoor'}] if outdoor_sensors else [])
        self._ext_cache = ExtContextCache()
        self._pre_gate = SafetyPreGate()
        self.state = CoordinatorState()
        for aid in ('v1', 'sh1'):
            self.state.integral[aid] = start
            self.state.prev_commands[aid] = start

    def cycle(self, internal_extra=None):
        """한 사이클 — (최종 명령 dict, 게이트 결과, L3 명령)."""
        now_ts = time.time()
        external, _ = CycleMixin._collect_external_context(self, None)
        # ── `_run_cycle` P2-2 (옮겨 적음) ──
        ext_max_age = self._pre_gate.config.ext_context_max_age
        last_ext_ts = external.get('last_ext_ts', 0.0)
        ext_stale = (now_ts - last_ext_ts) > ext_max_age
        if not ext_stale:
            self._ext_cache.update(external, now=now_ts)
        internal = dict(HUMID_NIGHT,
                        VPD=compute_vpd(HUMID_NIGHT['T'], HUMID_NIGHT['RH']))
        internal.update(internal_extra or {})
        external_for_control = (build_fallback_context(self._ext_cache, internal, now_ts)
                                if ext_stale else external)

        gate_env = HelpersMixin._build_gate_env(self, internal, external)
        gr = self._pre_gate.evaluate(gate_env, _profiles(), '')
        profiles = _profiles()
        if gr.triggered:                    # 전체 게이트 — L1~L3 건너뜀
            return ({aid: dict(c) for aid, c in gr.forced_commands.items()},
                    gr, None)
        partial = gr.forced_commands if gr.partial else {}

        target = {'vpd': TargetVar(value=0.46, tolerance=0.1, priority=1.2, unit='kPa')}
        report, _ = assess(target, internal, external_for_control, cycle_sec=600.0,
                           now_ts=now_ts, last_ext_ts=external.get('last_ext_ts'))
        # ── context 주입 (옮겨 적음) ──
        report.context['vent_futility_gate'] = True
        report.context['vent_open_ceiling'] = gr.vent_open_ceiling
        l3, self.state = coordinate(report, profiles, self.state)

        final = {aid: {'value': c.control_value(), 'reason': c.reason}
                 for aid, c in l3.items()}
        apply_threshold_and_gate_overrides(internal, profiles, final, partial)
        return final, gr, l3


# ─────────────────────────────────────────────────────────────────────────────
# 실외 입력원 두 가지 — 같은 물리 상황을 각자의 모양으로 만든다
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def outdoor(monkeypatch):
    """`outdoor.set(source, **values)` — 값이 None 이면 그 센서가 끊긴 것."""
    import aot.aot_flask.geo.facility_sensors as fs

    monkeypatch.setattr(ecc, 'write_influxdb_value', lambda *a, **k: None)
    monkeypatch.setattr(ecc._freshness, 'freshness_by_device', lambda ids: {})
    monkeypatch.setattr(ecc, '_shared_context', {})
    monkeypatch.setattr(ecc, '_shared_context_ts', 0.0)

    class _Outdoor:
        facility = {}

        def set(self, source, **values):
            if source == 'facility':
                self.facility = {
                    'T_ext': values.get('T_ext'), 'RH_ext': values.get('RH_ext'),
                    'rain_mm': values.get('rain'), 'wind_ms': values.get('wind'),
                }
            else:                           # 수집기 — **실제** 수집 코드를 돌린다
                f = ecc.CustomFunction.__new__(ecc.CustomFunction)
                f.logger, f.unique_id = self_logger(), 'collector'
                f.update_period, f.sensor_max_age = 60.0, 0.0
                f.sensor_temperature, f.sensor_humidity = 'wx,t', 'wx,rh'
                f.sensor_rain, f.sensor_wind = 'wx,rain', 'wx,wind'
                f.sensor_solar = f.sensor_dewpoint = f.sensor_co2 = None
                by_meas = {'t': values.get('T_ext'), 'rh': values.get('RH_ext'),
                           'rain': values.get('rain'), 'wind': values.get('wind')}
                now = time.time()
                f.get_last_measurement = lambda d, m, max_age=None: (
                    [now - 30, by_meas[m]] if by_meas[m] is not None
                    else [None, None])
                f._collect_and_publish()

    o = _Outdoor()
    monkeypatch.setattr(fs, 'read_outdoor_sensors',
                        lambda sensors, max_age=None: dict(o.facility))
    return o


def self_logger():
    import logging
    return logging.getLogger('test.collector')


SOURCES = ['facility', 'collector']


def _coord(source):
    return _Coordinator(outdoor_sensors=(source == 'facility'))


# ─────────────────────────────────────────────────────────────────────────────
# 핵심 불변식 — 입력원이 달라도 답은 같다
# ─────────────────────────────────────────────────────────────────────────────

class TestSameAnswerWhateverTheSource:

    @pytest.mark.parametrize('source', SOURCES)
    def test_평온하다_끊기면_더_열지_않는다(self, outdoor, source):
        c = _coord(source)
        outdoor.set(source, rain=0.0, wind=1.0, **DRY_OUTSIDE)
        c.cycle()
        start = c.state.prev_commands['v1']
        outdoor.set(source, rain=None, wind=None, **DRY_OUTSIDE)
        final, gr, l3 = c.cycle()
        assert gr.gate_mask & GATE_BIT_EXT_EXP and gr.vent_open_ceiling
        assert not gr.triggered
        assert final['v1']['value'] <= start + 1e-9, '모르는 채로 더 열면 안 된다'
        assert l3['v1'].reason == REASON_NO_OUTDOOR_DATA

    @pytest.mark.parametrize('source', SOURCES)
    def test_비_오다_끊기면_닫힌_채다(self, outdoor, source):
        """수정 전 시설 센서 설치는 여기서 강우 게이트가 TTL 뒤 풀렸다."""
        c = _coord(source)
        outdoor.set(source, rain=3.0, wind=1.0, **DRY_OUTSIDE)
        final, gr, _ = c.cycle()
        assert gr.triggered and final['v1']['value'] == 0.0
        outdoor.set(source, rain=None, wind=None, **DRY_OUTSIDE)
        for _ in range(3):
            c._pre_gate._triggered_until = 0.0          # gate_ttl 경과 가정
            final, gr, _ = c.cycle()
            assert gr.gate_mask & GATE_BIT_RAIN, '마지막 "비 옴" 은 닫는 근거다'
            assert final['v1']['value'] == 0.0

    @pytest.mark.parametrize('source', SOURCES)
    def test_새_값이_비_그침이면_풀린다(self, outdoor, source):
        c = _coord(source)
        outdoor.set(source, rain=3.0, wind=1.0, **DRY_OUTSIDE)
        c.cycle()
        outdoor.set(source, rain=None, wind=None, **DRY_OUTSIDE)
        c.cycle()
        outdoor.set(source, rain=0.0, wind=1.0, **DRY_OUTSIDE)
        c._pre_gate._triggered_until = 0.0
        _, gr, _ = c.cycle()
        assert gr.gate_mask == 0 and not gr.vent_open_ceiling

    @pytest.mark.parametrize('source', SOURCES)
    def test_원래_강우계가_없으면_제약하지_않는다(self, outdoor, source):
        """한 번도 못 본 값은 "잃은" 것이 아니다 — 강우계 없는 설치는 예전대로."""
        c = _coord(source)
        outdoor.set(source, rain=None, wind=None, **DRY_OUTSIDE)
        for _ in range(2):
            _, gr, l3 = c.cycle()
            assert gr.gate_mask == 0
            assert l3['v1'].reason != REASON_NO_OUTDOOR_DATA

    def test_두_입력원의_최종_명령이_같다(self, outdoor):
        runs = {}
        for source in SOURCES:
            c = _coord(source)
            seq = []
            for rain, wind in ((0.0, 1.0), (None, None), (None, None), (0.0, 1.0)):
                outdoor.set(source, rain=rain, wind=wind, **DRY_OUTSIDE)
                final, gr, _ = c.cycle()
                seq.append((round(final['v1']['value'], 6),
                            round(final['sh1']['value'], 6), gr.gate_mask))
            runs[source] = seq
        assert runs['facility'] == runs['collector']


# ─────────────────────────────────────────────────────────────────────────────
# 두 층의 모순이 풀렸는가
# ─────────────────────────────────────────────────────────────────────────────

class TestLayersAgree:

    def test_온습도까지_지어냈으면_제자리_그대로_나간다(self, outdoor):
        """수정 전: L3 는 제자리 55, 게이트가 뒤에서 0 으로 덮어 창이 닫혔다."""
        c = _coord('collector')
        outdoor.set('collector', rain=0.0, wind=1.0, T_ext=None, RH_ext=None)
        c.cycle()
        outdoor.set('collector', rain=None, wind=None, T_ext=None, RH_ext=None)
        final, gr, l3 = c.cycle()
        assert gr.vent_open_ceiling
        assert l3['v1'].reason == REASON_NO_OUTDOOR_DATA
        assert final['v1']['value'] == pytest.approx(START)

    def test_닫는_쪽은_허용한다(self, outdoor):
        """습한 실외면 PI 가 닫는다 — 그건 막지 않는다(닫기는 비바람에 안전)."""
        c = _coord('facility')
        outdoor.set('facility', rain=0.0, wind=1.0, **WET_OUTSIDE)
        c.cycle()
        outdoor.set('facility', rain=None, wind=None, **WET_OUTSIDE)
        before = c.state.prev_commands['v1']
        final, _, _ = c.cycle()
        assert final['v1']['value'] < before

    def test_차광막은_두절로_강제하지_않는다(self, outdoor):
        c = _coord('facility')
        outdoor.set('facility', rain=0.0, wind=1.0, **DRY_OUTSIDE)
        c.cycle()
        outdoor.set('facility', rain=None, wind=None, **DRY_OUTSIDE)
        final, gr, l3 = c.cycle()
        assert 'sh1' not in gr.forced_commands
        assert final['sh1']['value'] == pytest.approx(l3['sh1'].control_value())


# ─────────────────────────────────────────────────────────────────────────────
# 적분 — 상한에 걸린 동안 감기지 않고, 풀리면 튀지 않는다
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegralUnderCeiling:

    def _into_ceiling(self, outdoor, cycles):
        c = _coord('facility')
        outdoor.set('facility', rain=0.0, wind=1.0, **DRY_OUTSIDE)
        c.cycle()
        outdoor.set('facility', rain=None, wind=None, **DRY_OUTSIDE)
        for _ in range(cycles):
            c.cycle()
        return c

    def test_걸린_동안_적분은_한_톨도_쌓이지_않는다(self, outdoor):
        """`min(I, 개도)` 만 걸면 개도 아래에서 사이클마다 조금씩 쌓였다(실측
        55.002 → 55.007) — 긴 두절이면 개도까지 차올라 풀리는 순간 창을 민다."""
        c = self._into_ceiling(outdoor, 0)
        frozen = c.state.integral['v1']
        for _ in range(50):
            c.cycle()
            assert c.state.integral['v1'] == pytest.approx(frozen, abs=1e-12)
            assert c.state.integral['v1'] <= c.state.prev_commands['v1'] + 1e-9

    def test_풀린_첫_사이클은_두절이_없던_것처럼_이어진다(self, outdoor):
        """bumpless — 50 사이클 막혀 있다 풀린 명령이, 막히기 직전 다음 사이클과 같다."""
        c = self._into_ceiling(outdoor, 50)
        outdoor.set('facility', rain=0.0, wind=1.0, **DRY_OUTSIDE)
        after, _, _ = c.cycle()

        ref = _coord('facility')
        outdoor.set('facility', rain=0.0, wind=1.0, **DRY_OUTSIDE)
        ref.cycle()
        expected, _, _ = ref.cycle()
        assert after['v1']['value'] == pytest.approx(expected['v1']['value'], abs=1e-6)

    def test_막힌_사이에_닫는_쪽으로_바뀌면_실제_개도에서_내려간다(self, outdoor):
        """적분이 막힌 동안 개도 위로 가 있지 않으므로, 방향이 바뀌어도 튀지 않는다."""
        c = self._into_ceiling(outdoor, 10)
        held = c.state.prev_commands['v1']
        outdoor.set('facility', rain=None, wind=None, **WET_OUTSIDE)
        final, _, _ = c.cycle()
        assert final['v1']['value'] <= held
        assert c.state.integral['v1'] <= held + 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# temp_max 예외 · 환기 우선 · MPC 경로
# ─────────────────────────────────────────────────────────────────────────────

class TestExceptionsAndOtherPaths:

    def test_온도_하드_상한_위에서는_더_열_수_있다(self, outdoor):
        c = _coord('facility')
        outdoor.set('facility', rain=0.0, wind=1.0, **DRY_OUTSIDE)
        c.cycle()
        outdoor.set('facility', rain=None, wind=None, **DRY_OUTSIDE)
        before = c.state.prev_commands['v1']
        _, gr, l3 = c.cycle(internal_extra={'_force_cool': True})
        assert gr.vent_open_ceiling
        assert l3['v1'].reason != REASON_NO_OUTDOOR_DATA
        assert l3['v1'].control_value() > before

    def test_상한_대상은_개구부뿐이고_temp_max_면_비운다(self):
        vents = [make_opening_profile('v1'),
                 ActuatorProfile(actuator_id='fan', kind='exhaust_fan')]
        ctx = {'vent_open_ceiling': True, 'internal': {}}
        assert vent_open_ceiling_ids(ctx, vents) == {'v1'}
        ctx['internal']['_force_cool'] = True
        assert vent_open_ceiling_ids(ctx, vents) == set()
        assert vent_open_ceiling_ids({'internal': {}}, vents) == set()

    def test_더_못_여는_창의_도움을_믿고_냉난방이_쉬지_않는다(self):
        """환기 우선은 상한이 걸리면 꺼진다 — 인내 시간도 쌓이지 않는다."""
        from aot.functions.utils.env_control.situation import assess as _assess
        heater = make_heater_profile('h1')
        vent = make_opening_profile('v1')
        vent.effect_model = build_effect_model('opening', {})
        internal = {'T': 14.0, 'RH': 70.0, 'VPD': compute_vpd(14.0, 70.0)}
        target = {'temperature': TargetVar(value=20.0, tolerance=1.0,
                                           priority=1.0, unit='C')}
        runs = {}
        for ceiling in (False, True):
            report, _ = _assess(target, internal,
                                {'T': 26.0, 'RH': 50.0, 'T_ext': 26.0, 'RH_ext': 50.0},
                                cycle_sec=600.0, now_ts=time.time())
            report.context['vent_first'] = True
            report.context['vent_open_ceiling'] = ceiling
            st = CoordinatorState()
            st.prev_commands = {'v1': 0.0, 'h1': 0.0}
            cmds, new = coordinate(report, [vent, heater], st)
            runs[ceiling] = (cmds['h1'].value, new.vent_first_held_s)
        # 실외가 따뜻하다 — 상한이 없으면 창에 맡기고 난방기는 쉰다(전제 확인).
        assert runs[False][0] == 0.0, '전제가 깨졌다 — 이 테스트가 아무것도 안 본다'
        # 상한이 걸리면 창이 더 못 연다 → 난방기가 직접 일해야 한다.
        assert runs[True][0] > 0.0, '못 여는 창을 믿고 난방기가 쉬고 있다'
        assert runs[True][1] == 0.0

    def test_잃음_단독은_긴급이_아니다(self):
        """긴급이면 모터 최소 이동 간격이 풀린다 — 센서가 며칠 끊기면 그 내내."""
        from types import SimpleNamespace
        from aot.functions.utils.env_control.safety_gates import GateResult
        calm = SimpleNamespace(deviation_native={}, target={}, context={})
        stub = SimpleNamespace(_force_immediate=False)
        lost = GateResult(partial=True, gate_mask=GATE_BIT_EXT_EXP,
                          vent_open_ceiling=True)
        assert CycleMixin._classify_emergency(stub, lost, calm) == (False, '')
        windward = GateResult(partial=True, forced_commands={'v1': {'value': 0.0}})
        assert CycleMixin._classify_emergency(stub, windward, calm)[0] is True

    def test_MPC_경로도_같은_규칙(self):
        v = make_opening_profile('v1')
        ctx = {'vent_open_ceiling': True, 'internal': {}, 'external': {}}
        assert limit_vent_for_unknown_outdoor(ctx, v, 80.0, 40.0) == (
            40.0, REASON_NO_OUTDOOR_DATA)
        assert limit_vent_for_unknown_outdoor(ctx, v, 10.0, 40.0) == (10.0, None)
        ctx = {'internal': {}, 'external': {'_ext_synthetic': True}}
        assert limit_vent_for_unknown_outdoor(ctx, v, 10.0, 40.0) == (
            40.0, REASON_NO_OUTDOOR_DATA)
        heater = make_heater_profile('h1')
        assert limit_vent_for_unknown_outdoor(ctx, heater, 10.0, 40.0) == (10.0, None)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
