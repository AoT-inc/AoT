# coding=utf-8
"""극한 고온 보호 판정·정책 (`heat_protect`) 단위 테스트 — 설계 §5.

판정은 그 모듈 한 곳이다. 여기서는 사이클 시계를 직접 굴려(60초) 래치·지연·
최소 유지·실내 끊김·환기·분무·차광 규칙과, 오버라이드의 두 모드(pi/direct)를 본다.
"""
import pytest

from aot.functions.utils.env_control import heat_protect as HP
from aot.functions.utils.env_control.heat_protect import (
    HeatProtectConfig, HeatProtectState, apply_heat_protect_overrides,
    evaluate_heat_protect, record_dispatch, wetbulb_depression,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, ManualLockState,
)

T0 = 1_767_240_000.0
CYCLE = 60.0


def _p(aid, kind, wetting=None):
    p = ActuatorProfile(actuator_id=aid, kind=kind, effect_model={},
                        cmd_constraints=CmdConstraints(), gains={})
    if wetting is not None:
        p.capacity_meta = {'nozzle': {'wetting': bool(wetting)}}
    return p


def _facility():
    # 분무기는 고압 미세포그(잎을 적시지 않음) — 보호의 증발냉각기다.
    return [_p('win', 'opening'), _p('fan', 'exhaust_fan'), _p('fog', 'fogger', wetting=False),
            _p('cool', 'cooler'), _p('heat', 'heater'), _p('shade', 'shade'),
            _p('circ', 'circulation_fan')]


def _cfg(**kw):
    base = dict(threshold=30.0, release_margin=1.5, min_hold_s=1200.0,
                cycle_sec=CYCLE)
    base.update(kw)
    return HeatProtectConfig(**base)


class _Run:
    """사이클 시계를 굴리며 같은 상태로 판정을 반복한다."""

    def __init__(self, cfg=None, profiles=None):
        self.cfg = cfg or _cfg()
        self.state = HeatProtectState()
        self.profiles = profiles if profiles is not None else _facility()
        self.now = T0
        self.tiers = []

    def step(self, T, RH=50.0, T_ext=25.0, trend=0.0, ext=None, **internal):
        inner = {'T': T, 'RH': RH, '_outdoor_solar': 600.0}
        inner.update(internal)
        external = {'T': T_ext} if ext is None else ext
        d = evaluate_heat_protect(self.cfg, self.state, inner, external,
                                  self.profiles, self.now, T_trend=trend)
        self.tiers.append(d.tier)
        self.now += self.cfg.cycle_sec
        return d


def _transitions(tiers):
    return sum(1 for a, b in zip(tiers, tiers[1:]) if a != b)


# ─────────────────────────────────────────────────────────────────────────────
# 진입·해제
# ─────────────────────────────────────────────────────────────────────────────

class TestEntryRelease:
    def test_a_momentary_spike_does_not_enter(self):
        r = _Run()
        for T in (29.0, 29.0, 30.6, 29.0, 29.2, 30.4, 29.1):
            assert r.step(T).tier == 0

    def test_entry_after_the_dwell(self):
        r = _Run()
        tiers = [r.step(30.2).tier for _ in range(5)]
        # 0·60·120 초는 대기, 180 초째에 진입
        assert tiers == [0, 0, 0, 1, 1]

    def test_prediction_enters_at_once(self):
        r = _Run()
        d = r.step(29.5, trend=2.0)        # 29.5 + 2.0 × 1분 = 31.5 ≥ 31
        assert d.tier == 1 and d.escalated

    def test_escalation_is_reported_only_on_the_rising_cycle(self):
        r = _Run()
        first = r.step(31.5)
        second = r.step(31.5)
        assert first.escalated and not second.escalated

    def test_oscillation_around_the_threshold_switches_at_most_once_per_hour(self):
        r = _Run()
        # 29.5 ↔ 30.5 를 5분마다 오가는 세 시간
        for i in range(180):
            r.step(30.5 if (i // 5) % 2 else 29.5)
        assert _transitions(r.tiers) <= 3
        assert _transitions(r.tiers[60:]) == 0     # 진입 뒤로는 내내 유지

    def test_release_needs_margin_dwell_and_min_hold(self):
        r = _Run()
        r.step(31.5)                                 # 즉시 진입
        assert r.state.tier == 1
        # 해제선(28.5) 바로 위 — 아무리 오래여도 풀리지 않는다
        for _ in range(30):
            assert r.step(28.6).tier == 1
        # 해제선 아래 10분: 진입 후 이미 20분이 넘었으므로 10분째 풀린다
        tiers = [r.step(28.0).tier for _ in range(12)]
        assert tiers[:10] == [1] * 10 and tiers[10] == 0

    def test_min_hold_keeps_protection_even_after_cooling(self):
        r = _Run(cfg=_cfg(min_hold_s=1800.0))
        r.step(31.5)
        tiers = [r.step(27.0).tier for _ in range(25)]
        assert all(t == 1 for t in tiers)            # 30분이 안 지났다
        assert r.step(27.0).tier == 1 and r.step(27.0).tier == 1
        later = [r.step(27.0).tier for _ in range(5)]
        assert later[-1] == 0

    def test_tier2_is_the_hard_limit_latch(self):
        r = _Run()
        d = r.step(35.5, _force_cool=True)
        assert d.tier == 2 and d.escalated
        d = r.step(34.0)                             # 하드 래치가 풀렸다
        assert d.tier == 1 and not d.escalated

    def test_tier1_to_tier2_is_an_escalation(self):
        r = _Run()
        r.step(31.5)
        assert r.step(35.5, _force_cool=True).escalated

    def test_disabled_never_enters(self):
        r = _Run(cfg=_cfg(enabled=False))
        assert all(r.step(36.0, _force_cool=True).tier == 0 for _ in range(5))


# ─────────────────────────────────────────────────────────────────────────────
# 실내 값이 끊겼을 때
# ─────────────────────────────────────────────────────────────────────────────

class TestIndoorMissing:
    def test_not_active_does_not_start_without_indoor(self):
        r = _Run()
        assert all(r.step(None).tier == 0 for _ in range(10))

    def test_active_holds_for_thirty_minutes_then_releases(self):
        r = _Run()
        r.step(31.5)
        held = [r.step(None) for _ in range(30)]
        assert all(d.tier == 1 and d.stale for d in held)
        d = held[0]
        assert d.flags & HP.HP_FLAG_INDOOR_STALE
        assert not d.fog_allowed and d.fog_block_reason == 'stale'
        assert d.vent_open_ok is None and not d.vent_open_ids and not d.vent_closed_ids
        assert d.shade_deploy                         # 차광은 그대로
        assert r.step(None).tier == 0                 # 30분 지남

    def test_indoor_returning_clears_stale(self):
        r = _Run()
        r.step(31.5)
        r.step(None)
        d = r.step(31.0)
        assert d.tier == 1 and not d.stale


# ─────────────────────────────────────────────────────────────────────────────
# 환기 — 실외 vs 실내
# ─────────────────────────────────────────────────────────────────────────────

class TestVent:
    def test_outdoor_indoor_hysteresis(self):
        r = _Run()
        r.step(31.0, T_ext=25.0)                     # 진입(즉시: 31 ≥ 31)
        assert r.step(31.0, T_ext=30.5).vent_open_ok is True    # 래치 — 31−0 이하
        assert r.step(31.0, T_ext=31.2).vent_open_ok is False   # 실외가 더 덥다
        assert r.step(31.0, T_ext=30.5).vent_open_ok is False   # 다시 열려면 ≤ 30
        d = r.step(31.0, T_ext=29.9)
        assert d.vent_open_ok is True
        assert d.vent_open_ids == {'win', 'fan'} and not d.vent_closed_ids
        assert d.flags & HP.HP_FLAG_VENT_OPEN_OK

    def test_hot_outside_closes_every_vent(self):
        r = _Run()
        d = r.step(32.0, T_ext=36.0)
        assert d.vent_closed_ids == {'win', 'fan'}
        assert d.flags & HP.HP_FLAG_HOT_OUTSIDE

    def test_made_up_outdoor_decides_nothing(self):
        r = _Run()
        d = r.step(32.0, ext={'T': 20.0, '_ext_synthetic': True})
        assert d.vent_open_ok is None and not d.vent_open_ids and not d.vent_closed_ids

    def test_floor_goes_to_fans_when_misting_ran(self):
        r = _Run()
        r.state.fog_ran = True
        d = r.step(32.0, T_ext=36.0)
        assert d.floor_pct == HP.HP_VENT_FLOOR_PCT and d.floor_ids == {'fan'}

    def test_floor_goes_to_windows_without_fans(self):
        r = _Run(profiles=[_p('win', 'opening'), _p('fog', 'fogger')])
        r.state.fog_ran = True
        d = r.step(32.0, T_ext=36.0)
        assert d.floor_ids == {'win'}

    def test_no_floor_when_misting_did_not_run(self):
        d = _Run().step(32.0, T_ext=36.0)
        assert d.floor_pct == 0.0 and not d.floor_ids


# ─────────────────────────────────────────────────────────────────────────────
# 분무 — 물 · 증발 여력 · 습도
# ─────────────────────────────────────────────────────────────────────────────

class TestFog:
    def test_dry_air_allows_misting(self):
        d = _Run().step(32.0, RH=50.0)
        assert d.fog_allowed and not d.fog_blocked_ids
        assert d.flags & HP.HP_FLAG_FOG_ALLOWED

    def test_wetbulb_hysteresis(self):
        assert wetbulb_depression(32.0, 75.0) < HP.HP_FOG_WETBULB_ENTER_C
        assert wetbulb_depression(32.0, 75.0) > HP.HP_FOG_WETBULB_EXIT_C
        r = _Run()
        d = r.step(32.0, RH=75.0)                     # 3.8 °C — 처음에는 4 가 필요
        assert not d.fog_allowed and d.fog_block_reason == 'wetbulb'
        assert r.step(32.0, RH=60.0).fog_allowed      # 여력 충분
        assert r.step(32.0, RH=75.0).fog_allowed      # 허용 중에는 2.5 까지
        d = r.step(31.0, RH=85.5)                     # 2.2 °C 이자 85 % 이상
        assert not d.fog_allowed
        assert d.flags & HP.HP_FLAG_FOG_WETBULB and d.flags & HP.HP_FLAG_FOG_HUMID

    def test_humidity_hysteresis(self):
        """습도 문턱만 본다(증발 여력은 이 습도대에서 함께 모자라므로 플래그로 가른다)."""
        r = _Run()
        r.step(36.0, RH=40.0)
        assert not r.step(36.0, RH=84.0).flags & HP.HP_FLAG_FOG_HUMID
        d = r.step(36.0, RH=86.0)
        assert not d.fog_allowed and d.flags & HP.HP_FLAG_FOG_HUMID
        assert r.step(36.0, RH=82.0).flags & HP.HP_FLAG_FOG_HUMID     # 80 아래로 와야
        assert not r.step(36.0, RH=79.0).flags & HP.HP_FLAG_FOG_HUMID

    def test_unknown_humidity_blocks(self):
        d = _Run().step(32.0, RH=None)
        assert not d.fog_allowed and d.fog_blocked_ids == {'fog'}

    def test_no_water_blocks(self):
        d = _Run().step(32.0, RH=40.0, _water_available=False)
        assert not d.fog_allowed and d.fog_block_reason == 'water'
        assert d.flags & HP.HP_FLAG_NO_WATER

    def test_record_dispatch_reads_the_final_value(self):
        st = HeatProtectState()
        prof = _facility()
        record_dispatch(st, prof, {'fog': {'value': 40.0, 'reason': 1}})
        assert st.fog_ran
        record_dispatch(st, prof, {'fog': {'value': 0.0, 'reason': 'heat_protect'}})
        assert not st.fog_ran

    def test_wetting_mist_is_not_a_protection_cooler(self):
        """습윤형(아래 향 살수)은 보호의 증발냉각기가 아니다 — 하드 온도 항이 몰지 않고
        (`cooling_fog_ids` 에 없음), 돌았다고 환기 하한을 열지 않는다(폐루프 2026-10-09:
        hot_dry 흘러내림 9 → 429 kg). 노즐 정보가 없으면 습윤형으로 본다(보수적)."""
        prof = [_p('win', 'opening'), _p('mist', 'fogger', wetting=True),
                _p('bare', 'fogger'), _p('hp', 'fogger', wetting=False)]
        assert HP.cooling_foggers(prof) == {'hp'}
        st = HeatProtectState()
        record_dispatch(st, prof, {'mist': {'value': 100.0}, 'bare': {'value': 100.0}})
        assert not st.fog_ran
        record_dispatch(st, prof, {'hp': {'value': 30.0}})
        assert st.fog_ran
        r = _Run(profiles=prof)
        d = r.step(32.0, RH=40.0)
        assert d.active and d.cooling_fog_ids == {'hp'}
        # 막을 때는 습윤형도 막는다(물·증발 여력·습도 문턱은 모든 분무기에 건다)
        d = r.step(32.0, RH=40.0, _water_available=False)
        assert d.fog_blocked_ids == {'mist', 'bare', 'hp'}


# ─────────────────────────────────────────────────────────────────────────────
# 차광
# ─────────────────────────────────────────────────────────────────────────────

class TestShade:
    def test_deploys_in_sun(self):
        d = _Run().step(31.5)
        assert d.shade_deploy and d.flags & HP.HP_FLAG_SHADE_DEPLOY

    def test_not_at_night(self):
        d = _Run().step(31.5, _outdoor_solar=0.0)
        assert not d.shade_deploy

    def test_sun_latch(self):
        r = _Run()
        r.step(31.5, _outdoor_solar=120.0)            # 150 미만 — 아직 아님
        assert not r.state.sun_on
        assert r.step(31.5, _outdoor_solar=160.0).shade_deploy
        assert r.step(31.5, _outdoor_solar=120.0).shade_deploy   # 100 까지 유지
        assert not r.step(31.5, _outdoor_solar=90.0).shade_deploy

    def test_tier1_yields_to_light_min(self):
        r = _Run(cfg=_cfg(light_min=200.0))
        d = r.step(31.5, _light_shaded_est=150.0)
        assert not d.shade_deploy and d.light_min_yield
        assert d.flags & HP.HP_FLAG_LIGHT_MIN_YIELD

    def test_severe_heat_overrides_light_min(self):
        r = _Run(cfg=_cfg(light_min=200.0))
        d = r.step(33.5, _light_shaded_est=150.0)     # 문턱 + 3
        assert d.shade_deploy and not d.light_min_yield

    def test_tier2_overrides_light_min(self):
        r = _Run(cfg=_cfg(light_min=200.0))
        d = r.step(31.5, _light_shaded_est=150.0, _force_cool=True)
        assert d.tier == 2 and d.shade_deploy

    def test_deployed_shade_stays_while_latched(self):
        r = _Run(cfg=_cfg(light_min=200.0))
        assert r.step(31.5, _light_shaded_est=300.0).shade_deploy
        # 구름이 지나 '쳤을 때' 광량이 light_min 아래로 — 이미 친 막은 고정이다
        assert r.step(31.5, _light_shaded_est=150.0).shade_deploy


# ─────────────────────────────────────────────────────────────────────────────
# 오버라이드
# ─────────────────────────────────────────────────────────────────────────────

class TestOverrides:
    def _decision(self, T=32.0, T_ext=25.0, **internal):
        return _Run().step(T, T_ext=T_ext, **internal)

    def test_inactive_touches_nothing(self):
        cmds = {}
        out = apply_heat_protect_overrides(HP.HeatProtectDecision(), _facility(), cmds)
        assert out == {} and cmds == {}

    def test_pi_mode_tier1(self):
        cmds = {'cool': {'value': 30.0, 'reason': 1}, 'win': {'value': 40.0, 'reason': 1}}
        apply_heat_protect_overrides(self._decision(), _facility(), cmds, mode='pi')
        assert cmds['heat']['value'] == 0.0
        assert cmds['shade']['value'] == 0.0
        assert cmds['cool']['value'] == 30.0            # 단계 1 냉방은 PI 가 정한다
        assert cmds['win']['value'] == 40.0             # 환기는 PI 가 다룬다
        assert 'fog' not in cmds and 'circ' not in cmds
        assert cmds['heat']['reason'] == HP.HEAT_PROTECT_REASON

    def test_pi_mode_tier2_runs_cooler_full(self):
        cmds = {}
        apply_heat_protect_overrides(self._decision(T=36.0, _force_cool=True),
                                     _facility(), cmds, mode='pi')
        assert cmds['cool']['value'] == 100.0

    def test_pi_mode_tier2_runs_ventilation_full_when_cooler_outside(self):
        """단계 2 · 바깥이 더 시원 — 창·흡배기팬 100(냉방기와 같은 판단). 습도 하한의 팬
        끄기보다 뒤에 걸려 그것도 이긴다(폐루프 extreme_tunnel/fans 50 °C 초과 230 분)."""
        cmds = {'fan': {'value': 0.0, 'reason': 'humid_min'}}
        apply_heat_protect_overrides(self._decision(T=36.0, _force_cool=True),
                                     _facility(), cmds, mode='pi')
        assert cmds['fan']['value'] == 100.0 and cmds['win']['value'] == 100.0
        # 바깥이 더 더우면 건드리지 않는다 — 코디네이터의 파킹이 닫는다
        cmds = {}
        apply_heat_protect_overrides(self._decision(T=36.0, T_ext=40.0, _force_cool=True),
                                     _facility(), cmds, mode='pi')
        assert 'fan' not in cmds and 'win' not in cmds
        # 단계 1 은 PI 가 다룬다
        cmds = {}
        apply_heat_protect_overrides(self._decision(T=32.0), _facility(), cmds, mode='pi')
        assert 'fan' not in cmds and 'win' not in cmds

    def test_direct_mode_cool_outside(self):
        cmds = {}
        apply_heat_protect_overrides(self._decision(T_ext=25.0), _facility(), cmds,
                                     mode='direct')
        assert cmds['win']['value'] == 100.0 and cmds['fan']['value'] == 100.0
        assert cmds['fog']['value'] == 0.0             # 되먹임이 없으면 분무하지 않는다
        assert cmds['cool']['value'] == 100.0
        assert cmds['circ']['value'] == 100.0
        assert cmds['heat']['value'] == 0.0

    def test_direct_mode_hot_outside_uses_the_floor(self):
        r = _Run()
        r.state.fog_ran = True
        d = r.step(32.0, T_ext=36.0)
        cmds = {}
        apply_heat_protect_overrides(d, _facility(), cmds, mode='direct')
        assert cmds['fan']['value'] == HP.HP_VENT_FLOOR_PCT
        assert cmds['win']['value'] == 0.0

    def test_direct_mode_skips_what_the_gate_commanded(self):
        """강우가 닫은 창은 보호가 다시 열지 못한다 — 차광·냉방·팬은 일한다."""
        cmds = {'win': {'value': 0.0, 'reason': 12}}
        apply_heat_protect_overrides(self._decision(T_ext=25.0), _facility(), cmds,
                                     mode='direct', skip_ids={'win'})
        assert cmds['win'] == {'value': 0.0, 'reason': 12}
        assert cmds['shade']['value'] == 0.0 and cmds['cool']['value'] == 100.0
        assert cmds['fan']['value'] == 100.0

    def test_manual_lock_is_skipped(self):
        prof = _facility()
        heater = next(p for p in prof if p.kind == 'heater')
        heater.manual_lock = ManualLockState(locked=True, manual_value=40.0)
        cmds = {}
        apply_heat_protect_overrides(self._decision(), prof, cmds, mode='direct')
        assert 'heat' not in cmds

    def test_vent_only_facility_is_flagged(self):
        r = _Run(profiles=[_p('win', 'opening'), _p('heat', 'heater')])
        assert r.step(32.0).vent_only
        assert not _Run().step(32.0).vent_only


def test_option_ranges_cover_the_user_options():
    assert set(HP.HP_OPTION_RANGES) == {
        'heat_protect_threshold', 'heat_protect_release_margin',
        'heat_protect_min_hold_min'}
    lo, hi = HP.HP_OPTION_RANGES['heat_protect_threshold']
    assert lo <= HeatProtectConfig().threshold <= hi


@pytest.mark.parametrize('T,RH', [(30.0, 60.0), (35.0, 40.0), (25.0, 90.0)])
def test_wetbulb_uses_the_psychro_definition(T, RH):
    from aot.functions.utils.env_control import psychro
    w = psychro.humidity_ratio(psychro.vapor_pressure(T, RH))
    assert wetbulb_depression(T, RH) == pytest.approx(
        T - psychro.adiabatic_saturation_temperature(T, w))
