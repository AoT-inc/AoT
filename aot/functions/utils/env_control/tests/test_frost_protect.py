# coding=utf-8
"""서리 보호 — 한파 비상보다 훨씬 일찍 서는 두 단계 (2026-10-10, 근거 56).

현장: 극단 날씨 폐루프 `cold_snap_frost`(맑은 낮 18 °C → 바람 없는 맑은 밤 −4 °C). 한파 비상
(실외 ≤ −5 °C **그리고** 실내 ≤ 5 °C)은 −4 °C 에 서지 않았다 — 실내가 −4.1 °C 까지 내려가
작물이 392 분 얼었는데 경보도 조치도 없었다.

지키는 것:
  · 문턱 — 보호선 min(2 °C, temp_min − 1), 주의선 + 2 °C. 복사냉각(맑고 바람 없는 찬 밤)이면 유효
    실내가 2 K 낮다. 영양(temp_min 9 °C)은 기본선 그대로.
  · 히스테리시스 — 들어갈 때 즉시, 나올 때 여유(1 °C) + 최소 유지(30 분). 실내를 잃으면 서 있던 단계만 유지.
  · 조치 — 보호: 개구부·팬 닫음 · 커튼 닫음 · 난방 100 · 유동팬 100 · 분무·CO₂·냉방 끔. 주의: 커튼 닫음 ·
    개구부 더 열지 않음. 없는 장치는 명령이 없다.
  · 근거 56 · 마스크 비트 · 재시작을 넘는 기억 · 극한 고온 보호와 배타 · 야간 결로 틈(46)을 이긴다.
"""
import json
import logging
import time
import types

import pytest

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod
from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_threshold_and_gate_overrides)
from aot.functions.utils.env_control import cycle_memory
from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.heat_protect import (
    HeatProtectConfig, HeatProtectState, evaluate_heat_protect)
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_COLD, GATE_BIT_FROST, GATE_BIT_FROST_WATCH, GATE_BIT_RAIN,
    GATE_BIT_RAIN_LIGHT, REASON_CURTAIN_GAP, REASON_FROST_PROTECT,
    REASON_RAIN_RESTRICT, reason_name)
from aot.functions.utils.env_control.safety_gates import (
    FROST_LEVEL_NONE, FROST_LEVEL_PROTECT, FROST_LEVEL_WATCH, FROST_MIN_HOLD_S,
    FROST_RADIATIVE_DROP_C, FROST_STALE_MAX_S, FrostState, PreGateConfig,
    SafetyPreGate, evaluate_frost, frost_thresholds, is_radiative_night)
from aot.functions.utils.env_control.situation import assess, compute_vpd
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, TargetVar)

from .conftest import make_opening_profile

T0 = 1_767_240_000.0          # 고정 시각
CFG = PreGateConfig(gate_ttl=0.0)


def _p(aid, kind):
    return ActuatorProfile(actuator_id=aid, kind=kind, effect_model={},
                           cmd_constraints=CmdConstraints(), gains={})


def _fleet():
    """서리가 만지는 종류 전부 + 만지지 않는 것(차광막·보광등)."""
    return [_p('win', 'opening'), _p('exh', 'exhaust_fan'), _p('int', 'intake_fan'),
            _p('cur', 'curtain'), _p('hea', 'heater'), _p('coo', 'cooler'),
            _p('cir', 'circulation_fan'), _p('fog', 'fogger'), _p('co2', 'co2_injector'),
            _p('shd', 'shade'), _p('lit', 'lighting')]


def _env(T_int, T_ext=5.0, wind=0.5, rain=0.0, solar=0.0, now=T0, temp_min=None,
         T_min=None, fallback=None):
    env = {'internal': {'T': T_int, 'T_max': T_int,
                        'T_min': T_int if T_min is None else T_min, 'RH': 70.0},
           'external': {'T': T_ext, 'rain': rain, 'wind': wind, 'solar': solar},
           'now_ts': now}
    if temp_min is not None:
        env['temp_min'] = temp_min
    if fallback is not None:
        env['internal']['_nursery_light_fallback'] = fallback
    return env


def _run(gate, T_int, profiles=None, **kw):
    return gate.evaluate(_env(T_int, **kw),
                         _fleet() if profiles is None else profiles)


# ─────────────────────────────────────────────────────────────────────────────
# 문턱 — 작물과 복사냉각
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholds:

    def test_기본선은_주의_4_보호_2(self):
        assert frost_thresholds(None) == (4.0, 2.0)

    def test_영양_temp_min_9_는_기본선_그대로다(self):
        """9 °C 아래는 서리가 아니라 저온이다 — 최저 온도 한계(근거 33)가 맡는다."""
        assert frost_thresholds(9.0) == (4.0, 2.0)

    @pytest.mark.parametrize('temp_min,expect', [
        (3.0, (4.0, 2.0)),       # 3 − 1 = 2 → 기본선과 같다
        (2.0, (3.0, 1.0)),
        (1.0, (2.0, 0.0)),
        (-3.0, (-2.0, -4.0)),    # 어는점을 견디는 작물 — 사용자가 정한 한계보다 먼저 몰지 않는다
    ])
    def test_보호선은_temp_min_을_넘지_않는다(self, temp_min, expect):
        assert frost_thresholds(temp_min) == pytest.approx(expect)

    @pytest.mark.parametrize('bad', ['x', float('nan'), float('inf')])
    def test_이상한_temp_min_은_기본선(self, bad):
        w, p = frost_thresholds(bad)
        assert p <= 2.0 and w == p + 2.0
        if bad == 'x' or bad != bad:
            assert (w, p) == (4.0, 2.0)


class TestRadiativeNight:

    def test_맑고_바람_없는_찬_밤(self):
        assert is_radiative_night(0.0, 0.5, 0.0, 0.0)

    @pytest.mark.parametrize('args', [
        (3.0, 0.5, 0.0, 0.0),      # 실외가 덥다
        (0.0, 2.0, 0.0, 0.0),      # 바람(2 m/s 부터)
        (0.0, 0.5, 0.4, 0.0),      # 비 — 구름
        (0.0, 0.5, 0.0, 20.0),     # 해
        (None, 0.5, 0.0, 0.0),     # 실외를 모른다
    ])
    def test_하나라도_어기면_복사냉각이_아니다(self, args):
        assert not is_radiative_night(*args)

    def test_해를_모르면_밤으로_본다(self):
        """서리는 놓치는 쪽이 비싸다."""
        assert is_radiative_night(0.0, 0.5, 0.0, None)

    def test_풍속_센서가_없어도_복사냉각이다(self):
        assert is_radiative_night(0.0, None, 0.0, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 단계 판정 · 히스테리시스 · 최소 유지 (순수 함수)
# ─────────────────────────────────────────────────────────────────────────────

def _lv(st, T, t, radiative=False, temp_min=None):
    return evaluate_frost(st, T, radiative, temp_min, t).level


class TestLevels:

    @pytest.mark.parametrize('T,level', [
        (6.0, FROST_LEVEL_NONE), (4.1, FROST_LEVEL_NONE),
        (4.0, FROST_LEVEL_WATCH), (2.1, FROST_LEVEL_WATCH),
        (2.0, FROST_LEVEL_PROTECT), (-4.0, FROST_LEVEL_PROTECT),
    ])
    def test_실내_온도로_가른다(self, T, level):
        assert _lv(FrostState(), T, T0) == level

    def test_복사냉각이면_유효_실내가_2K_낮다(self):
        """실내 5.5 °C: 평소엔 아무 일 없고, 맑고 바람 없는 찬 밤에는 주의, 4 °C 면 보호."""
        assert _lv(FrostState(), 5.5, T0, radiative=False) == FROST_LEVEL_NONE
        assert _lv(FrostState(), 5.5, T0, radiative=True) == FROST_LEVEL_WATCH
        assert _lv(FrostState(), 4.0, T0, radiative=True) == FROST_LEVEL_PROTECT
        assert FROST_RADIATIVE_DROP_C == 2.0

    def test_올라갈_때는_기다리지_않는다(self):
        st = FrostState()
        assert _lv(st, 3.0, T0) == FROST_LEVEL_WATCH
        assert _lv(st, 1.0, T0 + 60) == FROST_LEVEL_PROTECT

    def test_나갈_때는_여유와_최소_유지가_모두_필요하다(self):
        st = FrostState()
        assert _lv(st, 1.0, T0) == FROST_LEVEL_PROTECT
        # 보호선 + 여유(1 °C) = 3 °C 안에서는 보호가 유지된다.
        assert _lv(st, 2.9, T0 + 3600) == FROST_LEVEL_PROTECT
        # 여유 밖이어도 마지막 근거(2.9 °C 가 보호를 받친 시각) 뒤 최소 유지 전이면 그대로다.
        assert _lv(st, 3.5, T0 + 3600 + FROST_MIN_HOLD_S - 1) == FROST_LEVEL_PROTECT
        assert _lv(st, 3.5, T0 + 3600 + FROST_MIN_HOLD_S) == FROST_LEVEL_WATCH
        # 주의에서도 같다: 5 °C 이하(주의선 + 여유)면 유지, 그 위로 30 분이 지나야 풀린다.
        assert _lv(st, 4.9, T0 + 7200) == FROST_LEVEL_WATCH
        assert _lv(st, 6.0, T0 + 7200 + FROST_MIN_HOLD_S - 1) == FROST_LEVEL_WATCH
        assert _lv(st, 6.0, T0 + 7200 + FROST_MIN_HOLD_S) == FROST_LEVEL_NONE

    def test_문턱_위아래_흔들림은_단계를_흔들지_않는다(self):
        st = FrostState()
        seq = [3.9, 4.2, 3.8, 4.4, 3.7, 4.6]          # 주의선(4 °C) 위아래 10 분 간격
        out = [_lv(st, T, T0 + 600 * i) for i, T in enumerate(seq)]
        assert out == [FROST_LEVEL_WATCH] * len(seq)

    def test_단계를_건너뛰어_내려갈_수_있다(self):
        """보호에서 한참 따뜻해지면 주의를 거치지 않고 풀린다 — 여유와 유지만 지키면 된다."""
        st = FrostState()
        assert _lv(st, 0.0, T0) == FROST_LEVEL_PROTECT
        assert _lv(st, 12.0, T0 + FROST_MIN_HOLD_S) == FROST_LEVEL_NONE

    def test_복사냉각이_풀려도_최소_유지가_받친다(self):
        st = FrostState()
        assert _lv(st, 5.0, T0, radiative=True) == FROST_LEVEL_WATCH
        assert _lv(st, 5.0, T0 + 60, radiative=False) == FROST_LEVEL_WATCH   # 5.0 ≤ 4 + 1

    def test_temp_min_이_낮으면_더_늦게_선다(self):
        st = FrostState()
        assert _lv(st, 3.0, T0, temp_min=1.0) == FROST_LEVEL_NONE         # 주의선 2 °C
        assert _lv(st, 1.5, T0, temp_min=1.0) == FROST_LEVEL_WATCH
        assert _lv(st, -0.1, T0, temp_min=1.0) == FROST_LEVEL_PROTECT


class TestStaleIndoor:

    def test_모르면_새로_서지_않는다(self):
        st = FrostState()
        assert _lv(st, None, T0) == FROST_LEVEL_NONE
        assert st.level == FROST_LEVEL_NONE

    def test_서_있던_단계는_30분_유지한다(self):
        st = FrostState()
        assert _lv(st, 1.0, T0) == FROST_LEVEL_PROTECT
        d = evaluate_frost(st, None, False, None, T0 + 60)
        assert d.level == FROST_LEVEL_PROTECT and d.stale
        d = evaluate_frost(st, None, False, None, T0 + 60 + FROST_STALE_MAX_S - 1)
        assert d.level == FROST_LEVEL_PROTECT and d.stale
        d = evaluate_frost(st, None, False, None, T0 + 60 + FROST_STALE_MAX_S)
        assert d.level == FROST_LEVEL_NONE and not d.stale and d.changed

    def test_값이_돌아오면_끊김_시각을_지운다(self):
        st = FrostState()
        _lv(st, 1.0, T0)
        evaluate_frost(st, None, False, None, T0 + 60)
        assert st.stale_since is not None
        _lv(st, 1.0, T0 + 120)
        assert st.stale_since is None


# ─────────────────────────────────────────────────────────────────────────────
# 게이트 — 마스크 · 근거 · 조치
# ─────────────────────────────────────────────────────────────────────────────

def _vals(res):
    return {aid: c['value'] for aid, c in res.forced_commands.items()}


class TestGateActions:

    def test_따뜻하면_아무것도_없다(self):
        res = _run(SafetyPreGate(CFG), 10.0)
        assert res.frost_level == 0 and not res.gate_mask
        assert not res.triggered and not res.forced_commands and not res.vent_caps

    def test_보호는_L1_L3_를_건너뛰고_전부_강제한다(self):
        res = _run(SafetyPreGate(CFG), 1.0)
        assert res.frost_level == FROST_LEVEL_PROTECT
        assert res.gate_mask & GATE_BIT_FROST and not res.gate_mask & GATE_BIT_FROST_WATCH
        assert res.triggered and not res.partial
        assert res.description == 'frost_protect'
        assert _vals(res) == {
            'win': 0.0, 'exh': 0.0, 'int': 0.0,          # 개구부·흡배기팬 닫음
            'cur': 0.0,                                   # 커튼 닫음
            'hea': 100.0, 'cir': 100.0,                   # 난방·유동팬
            'coo': 0.0, 'fog': 0.0, 'co2': 0.0,           # 냉방·분무·CO₂ 끔
        }
        assert {c['reason'] for c in res.forced_commands.values()} == {REASON_FROST_PROTECT}
        assert 'shd' not in res.forced_commands and 'lit' not in res.forced_commands
        assert reason_name(REASON_FROST_PROTECT) == 'frost_protect'

    def test_주의는_제약이다_커튼만_닫고_개구부는_더_열지_않는다(self):
        res = _run(SafetyPreGate(CFG), 3.5)
        assert res.frost_level == FROST_LEVEL_WATCH
        assert res.gate_mask == GATE_BIT_FROST_WATCH
        assert not res.triggered and res.partial        # L1~L3 는 그대로 돈다
        assert res.description == 'frost_watch'
        assert _vals(res) == {'cur': 0.0}
        assert res.forced_commands['cur']['reason'] == REASON_FROST_PROTECT
        assert res.vent_caps == {'win': None}           # 지금 개도 위로 열지 않음
        assert res.vent_cap_reasons == {'win': REASON_FROST_PROTECT}

    def test_주의는_TTL_전체_홀드를_잡지_않는다(self):
        g = SafetyPreGate(PreGateConfig(gate_ttl=300.0))
        assert _run(g, 3.5).partial
        res = _run(g, 20.0, now=T0 + 7200)                # 최소 유지 뒤 풀림
        assert not res.triggered and not res.partial

    @pytest.mark.parametrize('kinds,expect', [
        (['opening'], {'o0': 0.0}),
        (['heater'], {'h0': 100.0}),
        (['circulation_fan'], {'c0': 100.0}),
        (['fogger', 'co2_injector'], {'f0': 0.0, 'g0': 0.0}),
        (['shade', 'lighting'], {}),
        ([], {}),
    ])
    def test_없는_장치는_명령이_없다(self, kinds, expect):
        ids = {'opening': 'o0', 'heater': 'h0', 'circulation_fan': 'c0',
               'fogger': 'f0', 'co2_injector': 'g0', 'shade': 's0', 'lighting': 'l0'}
        res = _run(SafetyPreGate(CFG), 0.0, profiles=[_p(ids[k], k) for k in kinds])
        assert _vals(res) == expect
        assert res.frost_level == FROST_LEVEL_PROTECT        # 단계 자체는 장치와 무관하다

    def test_난방기가_없는_시설도_보호는_선다_닫기만_한다(self):
        res = _run(SafetyPreGate(CFG), 0.0,
                   profiles=[_p('win', 'opening'), _p('cur', 'curtain')])
        assert _vals(res) == {'win': 0.0, 'cur': 0.0} and res.triggered

    def test_장치가_없는_시설의_주의는_조용하다(self):
        res = _run(SafetyPreGate(CFG), 3.0, profiles=[_p('hea', 'heater')])
        assert res.frost_level == FROST_LEVEL_WATCH
        assert not res.forced_commands and not res.vent_caps

    def test_복사냉각_보정은_게이트_입력으로_들어간다(self):
        # 실내 5.5, 실외 0, 고요, 해 없음 → 주의.  같은 실내에서 바람이 있으면 아무 일 없다.
        assert _run(SafetyPreGate(CFG), 5.5, T_ext=0.0).frost_level == FROST_LEVEL_WATCH
        assert _run(SafetyPreGate(CFG), 5.5, T_ext=0.0, wind=3.0).frost_level == 0
        # 낮: 일사 센서가 양수면 복사냉각이 아니다.
        assert _run(SafetyPreGate(CFG), 5.5, T_ext=0.0, solar=300.0).frost_level == 0
        # 센서가 0.0 이어도 맑은 하늘 어림이 해를 말하면 낮이다.
        assert _run(SafetyPreGate(CFG), 5.5, T_ext=0.0, fallback=400.0).frost_level == 0
        # 실측 비는 구름 — 복사냉각이 아니다.
        assert _run(SafetyPreGate(CFG), 5.5, T_ext=0.0, rain=0.3).frost_level == 0

    def test_예보_모델_강수는_복사냉각을_막지_못한다(self):
        env = _env(5.5, T_ext=0.0, rain=0.3)
        env['external']['rain_origin'] = 'model'
        assert SafetyPreGate(CFG).evaluate(env, _fleet()).frost_level == FROST_LEVEL_WATCH

    def test_가장_찬_자리_T_min_을_본다(self):
        res = _run(SafetyPreGate(CFG), 9.0, T_min=1.0)
        assert res.frost_level == FROST_LEVEL_PROTECT

    def test_temp_min_이_낮으면_보호선도_내려간다(self):
        assert _run(SafetyPreGate(CFG), 3.0, temp_min=1.0).frost_level == 0
        assert _run(SafetyPreGate(CFG), 3.0, temp_min=9.0).frost_level == FROST_LEVEL_WATCH

    def test_보호_뒤_최소_유지_동안_게이트가_계속_선다(self):
        g = SafetyPreGate(CFG)
        assert _run(g, 0.0, now=T0).triggered
        # 영하에서 올라 8 °C — 최소 유지 전이라 보호 그대로.
        assert _run(g, 8.0, now=T0 + 600).triggered
        res = _run(g, 8.0, now=T0 + FROST_MIN_HOLD_S)
        assert res.frost_level == FROST_LEVEL_NONE and not res.gate_mask


class TestGateCompose:

    def test_한파_비상과_겹치면_비상의_값이_이기고_서리가_나머지를_더한다(self):
        profiles = _fleet()
        res = _run(SafetyPreGate(CFG), -6.0, T_ext=-8.0, profiles=profiles)
        assert res.gate_mask & GATE_BIT_COLD and res.gate_mask & GATE_BIT_FROST
        v = _vals(res)
        assert v['win'] == 0.0 and v['cur'] == 0.0 and v['hea'] == 100.0
        assert v['cir'] == 100.0 and v['fog'] == 0.0 and v['co2'] == 0.0
        # 한파 비상이 박은 명령은 그 근거(12)를 지킨다.
        from aot.functions.utils.env_control.log_channels import REASON_SAFETY_PRE_GATE
        assert res.forced_commands['win']['reason'] == REASON_SAFETY_PRE_GATE
        assert res.forced_commands['cir']['reason'] == REASON_FROST_PROTECT

    def test_비_전면_폐쇄와_겹쳐도_닫힘은_같다(self):
        res = _run(SafetyPreGate(CFG), 3.0, rain=2.0, T_ext=1.0)
        assert res.gate_mask & GATE_BIT_RAIN and res.gate_mask & GATE_BIT_FROST_WATCH
        assert res.forced_commands['win']['value'] == 0.0
        assert 'win' not in res.vent_caps

    def test_비_단계_제한의_숫자_상한이_있으면_그것을_둔다(self):
        side = make_opening_profile('side', azimuth_deg=0.0)
        side.vent_form = 'side'
        env = _env(3.5, T_ext=3.0, rain=0.6, wind=0.5)
        res = SafetyPreGate(CFG).evaluate(env, [side, _p('cur', 'curtain')])
        assert res.gate_mask & GATE_BIT_RAIN_LIGHT and res.gate_mask & GATE_BIT_FROST_WATCH
        assert res.vent_caps == {'side': 30.0}          # 숫자 상한은 그대로
        # 근거는 비(52)다 — 강풍 단계(근거 55)와 합친 뒤로는 52 도 명시한다(없으면 52 와 같다).
        assert res.vent_cap_reasons.get('side', 52) == 52

    def test_강풍은_서리_주의와_함께_전부_닫는다(self):
        res = _run(SafetyPreGate(CFG), 3.0, wind=15.0, T_ext=3.0)
        assert res.triggered and res.forced_commands['win']['value'] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 야간 결로 틈(46)·최종 오버라이드 — 서리가 이긴다
# ─────────────────────────────────────────────────────────────────────────────

class TestOverrides:

    def test_주의_커튼_닫음이_야간_결로_틈을_이긴다(self):
        profiles = _fleet()
        res = _run(SafetyPreGate(CFG), 3.5, profiles=profiles)
        final = {'cur': {'value': 6.0, 'reason': REASON_CURTAIN_GAP},
                 'win': {'value': 12.0, 'reason': 1}}
        apply_threshold_and_gate_overrides({'T': 3.5, 'RH': 92.0}, profiles, final,
                                           res.forced_commands, res.vent_caps)
        assert final['cur'] == {'value': 0.0, 'reason': REASON_FROST_PROTECT, 'ttl': 300.0}
        assert final['win'] == {'value': 12.0, 'reason': 1}   # "더 열지 않음" 은 PI 안에서 걸린다

    def test_냉난방_인터록은_서리_난방을_끄지_않는다(self):
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
            apply_hvac_opposition_interlock)
        profiles = [_p('hea', 'heater'), _p('coo', 'cooler')]
        final = {'hea': {'value': 100.0, 'reason': REASON_FROST_PROTECT},
                 'coo': {'value': 100.0, 'reason': 40}}
        assert apply_hvac_opposition_interlock(profiles, final)
        assert final['hea']['value'] == 100.0 and final['coo']['value'] == 0.0


def _vents():
    roof = make_opening_profile('roof')
    roof.effect_model = build_effect_model('opening', {})
    return [roof]


class TestPiHold:
    """주의의 "더 열지 않음" 은 적분과 함께 PI 안에서 걸리고 근거는 56 이다."""

    def _cycle(self, caps, reasons, start=40.0):
        profiles = _vents()
        state = CoordinatorState()
        state.integral['roof'] = start
        state.prev_commands['roof'] = start
        internal = {'T': 22.8, 'RH': 86.0, 'VPD': compute_vpd(22.8, 86.0)}
        ext = {'T': 30.0, 'RH': 45.0, 'T_ext': 30.0, 'RH_ext': 45.0, 'wind': 1.0, 'rain': 0.0}
        target = {'vpd': TargetVar(value=0.46, tolerance=0.1, priority=1.2, unit='kPa')}
        report, _ = assess(target, internal, ext, cycle_sec=600.0, now_ts=time.time(),
                           last_ext_ts=time.time())
        report.context['vent_open_caps'] = dict(caps)
        report.context['vent_open_cap_reasons'] = dict(reasons)
        return coordinate(report, profiles, state)

    def test_서리_주의는_창을_더_열지_않고_근거는_56(self):
        l3, st = self._cycle({'roof': None}, {'roof': REASON_FROST_PROTECT})
        assert l3['roof'].reason == REASON_FROST_PROTECT
        assert l3['roof'].control_value() == pytest.approx(40.0)
        assert st.integral['roof'] <= 40.0 + 1e-9

    def test_근거를_안_주면_예전처럼_비_52(self):
        l3, _ = self._cycle({'roof': None}, {})
        assert l3['roof'].reason == REASON_RAIN_RESTRICT


# ─────────────────────────────────────────────────────────────────────────────
# 재시작을 넘는 기억
# ─────────────────────────────────────────────────────────────────────────────

class TestRestartMemory:

    def test_코디네이터_속성은_게이트의_상태를_이어_준다(self):
        c = CustomModule.__new__(CustomModule)
        assert c._frost_state is None                      # 게이트 전
        c._pre_gate = SafetyPreGate(CFG)
        c._frost_state = FrostState(level=2, held_since=T0)
        assert c._pre_gate.frost_state.level == 2
        assert c._frost_state is c._pre_gate.frost_state

    def test_저장하고_복원하면_보호가_이어진다(self):
        a = CustomModule.__new__(CustomModule)
        a._pre_gate = SafetyPreGate(CFG)
        _run(a._pre_gate, 0.0, now=T0)                     # 보호 진입
        blob = json.loads(json.dumps(cycle_memory.export_memory(a, T0 + 60)))
        assert blob['_frost_state']['level'] == FROST_LEVEL_PROTECT

        b = CustomModule.__new__(CustomModule)             # 재시작한 새 프로세스
        b._pre_gate = SafetyPreGate(CFG)
        assert '_frost_state' in cycle_memory.restore_memory(b, blob, T0 + 120)
        assert b._frost_state.level == FROST_LEVEL_PROTECT
        # 첫 사이클: 보호선 + 여유(3 °C) 위인 3.4 °C 여도 최소 유지가 받친다 — 기억이 없었으면 주의다.
        res = _run(b._pre_gate, 3.4, now=T0 + 180)
        assert res.frost_level == FROST_LEVEL_PROTECT
        fresh = _run(SafetyPreGate(CFG), 3.4, now=T0 + 180)
        assert fresh.frost_level == FROST_LEVEL_WATCH

    def test_낡은_기억은_버린다(self):
        a = types.SimpleNamespace(_frost_state=FrostState(level=2, held_since=T0))
        blob = cycle_memory.export_memory(a, T0)
        b = types.SimpleNamespace(_frost_state=FrostState())
        assert cycle_memory.restore_memory(
            b, blob, T0 + cycle_memory.MEMORY_MAX_AGE_S + 1) == []
        assert b._frost_state.level == 0

    def test_모르는_필드와_빠진_필드에_견딘다(self):
        b = types.SimpleNamespace(_frost_state=FrostState())
        blob = {'ts': T0, '_frost_state': {'level': 1, 'future_field': 7}}
        assert '_frost_state' in cycle_memory.restore_memory(b, blob, T0 + 10)
        assert b._frost_state.level == 1 and b._frost_state.held_since is None


# ─────────────────────────────────────────────────────────────────────────────
# 극한 고온 보호와 배타
# ─────────────────────────────────────────────────────────────────────────────

class TestHeatProtectExclusive:

    CFG_HP = HeatProtectConfig(enabled=True, threshold=30.0, release_margin=1.5,
                               min_hold_s=0.0, cycle_sec=60.0)

    def test_서리가_서_있으면_고온_보호는_풀리고_새로_서지_않는다(self):
        st = HeatProtectState(latched=True, tier=1, entered_at=T0 - 3600)
        dec = evaluate_heat_protect(
            self.CFG_HP, st, {'T': None, '_frost_level': 1}, {'T': 2.0}, [], T0)
        assert dec.tier == 0 and dec.released and not st.latched
        st2 = HeatProtectState()
        for i in range(10):         # 서리 단계가 서 있는 동안은 30 °C 를 넘어도 새로 서지 않는다
            dec = evaluate_heat_protect(
                self.CFG_HP, st2, {'T': 33.0, '_frost_level': 2}, {'T': 2.0}, [], T0 + 60 * i)
            assert dec.tier == 0
        assert not st2.latched

    def test_서리가_없으면_종전대로다(self):
        st = HeatProtectState()
        for i in range(5):
            dec = evaluate_heat_protect(
                self.CFG_HP, st, {'T': 33.0, '_frost_level': 0}, {'T': 26.0}, [], T0 + 60 * i)
        assert dec.tier == 1

    def test_서리_게이트는_한낮_고온에서_서지_않는다(self):
        res = _run(SafetyPreGate(CFG), 33.0, T_ext=2.0)
        assert res.frost_level == 0


# ─────────────────────────────────────────────────────────────────────────────
# 사이클 이음매 — 한 번만 말하고, 보호 진입에 메일 한 통
# ─────────────────────────────────────────────────────────────────────────────

def _host(profiles=None):
    c = CycleMixin.__new__(CycleMixin)
    c._profiles = profiles if profiles is not None else _fleet()
    c.logger = logging.getLogger('test_frost_protect')
    c.emails = []
    c._send_critical_email = lambda key, msg: c.emails.append((key, msg))
    c.said = []
    c._status_log = lambda level, msg, *a: c.said.append((level, msg % a))
    c._pre_gate = SafetyPreGate(CFG)
    return c


class TestCycleSeam:

    def _step(self, c, T, now, **kw):
        env = _env(T, now=now, **kw)
        res = c._pre_gate.evaluate(env, c._profiles)
        internal = {'T': T}
        c._note_frost(res, env, internal)
        return res, internal

    def test_단계를_internal_에_싣는다(self):
        c = _host()
        _, internal = self._step(c, 3.0, T0)
        assert internal['_frost_level'] == FROST_LEVEL_WATCH
        _, internal = self._step(c, 15.0, T0 + 7200)
        assert internal['_frost_level'] == 0

    def test_바뀔_때만_말한다(self):
        c = _host()
        for i, T in enumerate([8.0, 3.0, 3.0, 3.0, 1.0, 1.0]):
            self._step(c, T, T0 + 60 * i)
        assert len(c.said) == 2
        assert '서리 주의 진입' in c.said[0][1] and '서리 보호 진입' in c.said[1][1]
        assert c.said[1][0] == logging.WARNING

    def test_해제도_한_번_말한다(self):
        c = _host()
        self._step(c, 1.0, T0)
        self._step(c, 15.0, T0 + FROST_MIN_HOLD_S)
        assert c.said[-1][0] == logging.INFO and '해제' in c.said[-1][1]

    def test_보호_진입에_경보_메일_한_통(self):
        c = _host()
        for i, T in enumerate([8.0, 3.0, 1.0, 0.5, 0.0]):
            self._step(c, T, T0 + 60 * i)
        assert [k for k, _ in c.emails] == ['frost_protect']
        assert '난방·유동팬' in c.emails[0][1]

    def test_주의만으로는_메일이_없다(self):
        c = _host()
        self._step(c, 3.0, T0)
        assert c.emails == []

    def test_난방기가_없으면_메일이_그것을_말한다(self):
        c = _host([_p('win', 'opening')])
        self._step(c, 0.0, T0)
        assert len(c.emails) == 1 and '난방 장치가 없어' in c.emails[0][1]

    def test_보호에서_주의로_내려가면_메일은_다시_가지_않는다_말만_한다(self):
        c = _host()
        self._step(c, 0.0, T0)
        self._step(c, 3.5, T0 + FROST_MIN_HOLD_S)
        assert len(c.emails) == 1 and '보호에서 주의로' in c.said[-1][1]

    def test_평가가_깨져도_사이클을_죽이지_않는다(self):
        c = _host()
        c._status_log = None                       # 호출하면 TypeError
        res = c._pre_gate.evaluate(_env(0.0), c._profiles)
        c._note_frost(res, _env(0.0), {})          # 예외가 밖으로 나오지 않는다

    def test_게이트_요약은_강제한_근거를_그대로_싣는다(self):
        c = _host()
        res = c._pre_gate.evaluate(_env(0.0), c._profiles)
        c._SUMMARY_MAX_TEXT = 200
        c._SUMMARY_MAX_COMMANDS = 50
        c._build_photo_snapshot = lambda internal: {}
        c._save_runtime_state = lambda: None
        c._last_capability = None
        c._write_gate_only_summary(res, _env(0.0), T0, internal={})
        by_kind = {r['kind']: r for r in c._last_cycle_summary['commands']}
        assert by_kind['heater']['reason'] == REASON_FROST_PROTECT
        assert by_kind['heater']['pct'] == 100.0
        assert by_kind['shade']['reason'] is None and by_kind['shade']['pct'] is None
        assert c._last_cycle_summary['gate']['reasons'] == ['frost_protect']
