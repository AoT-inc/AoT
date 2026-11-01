# coding=utf-8
"""밤 보온 — 열 수요가 있으면 보온커튼을 닫는다 (2026-10-10, 근거 49).

실측(영양 육묘장 2026-10-09 18:00 → 10-10 05:47): 실내 9~12 °C(목표 하한 21 °C 대), 실외 7~11 °C 인데
커튼이 밤새 100 %(걷힘)·근거 15(구동력 없음). 효과 모델이 커튼의 값을 **지금의 안팎 공기 온도차**로
쟀고, 걷힌 커튼 아래 실내는 바깥을 따라가 그 차이가 1~2 °C 라 "닫아도 소용없다" 가 되었다 — 걷혀
있다는 사실이 걷어 둘 이유가 되는 고리. 05:57 최저 온도 한계(33)가 닫을 때까지 그랬다.

판단은 `screen_policy._curtain_night_close` 한 곳 — 목표와 실외로 열 수요를 본다.
"""
import types

from aot.functions.utils.env_control import screen_policy as SP
from aot.functions.utils.env_control.log_channels import (
    REASON_CURTAIN_GAP, REASON_CURTAIN_NIGHT_CLOSE, REASON_NO_GRADIENT, REASON_PRIMARY,
)


def _cur(aid='c', positional=True):
    return types.SimpleNamespace(actuator_id=aid, kind='curtain',
                                 capacity_meta={'screen_positional': positional})


def _close(state, T, T_ext, lo=21.4, hi=23.4, day=False, profiles=None):
    return SP._curtain_night_close(state, {'T': T}, {'T': T_ext},
                                   profiles or [_cur()], day, lo, hi)


# ── 판단 ─────────────────────────────────────────────────────────────────────

def test_yeongyang_night_closes_although_the_air_gap_is_small():
    """실내 11.7 · 실외 11.2(차 0.5 °C) · 목표 22.4 ± 1 — 닫는다."""
    assert _close(SP.ScreenState(), 11.7, 11.2) == frozenset({'c'})


def test_binary_curtain_is_closed_too():
    """부분 개도와 무관하다 — 틈·램프와 달리 0/100 커튼에도 건다."""
    got = _close(SP.ScreenState(), 12.0, 10.0, profiles=[_cur('a'), _cur('b', False)])
    assert got == frozenset({'a', 'b'})


def test_cold_outside_alone_is_heat_demand():
    """실내가 아직 범위 안이어도 실외가 목표 하한 아래면 걷어 둘수록 범위 밖으로 끌린다."""
    assert _close(SP.ScreenState(), 17.5, 12.0, lo=14.0, hi=20.0) == frozenset({'c'})
    assert _close(SP.ScreenState(), 17.5, 14.5, lo=14.0, hi=20.0) == frozenset()


def test_day_never_closes_and_forgets():
    st = SP.ScreenState()
    _close(st, 12.0, 10.0)
    assert _close(st, 12.0, 10.0, day=True) == frozenset() and not st.night_close_on


def test_warm_summer_night_stays_open():
    """실내가 목표 상한 근처·위면 보온할 일이 없다 — 종전대로(PI·제자리)."""
    assert _close(SP.ScreenState(), 25.0, 22.0) == frozenset()
    assert _close(SP.ScreenState(), 22.5, 20.0) == frozenset()     # 상한 − 1 이상


def test_mild_night_without_demand_stays_open():
    """실내가 하한 + 2 위이고 실외도 하한 위면 닫지 않는다."""
    assert _close(SP.ScreenState(), 18.0, 16.5, lo=14.0, hi=20.0) == frozenset()


def test_warmer_outside_air_is_left_to_the_pi():
    assert _close(SP.ScreenState(), 15.0, 16.0, lo=14.0, hi=20.0) == frozenset()


def test_unknown_target_or_indoor_keeps_old_behaviour():
    assert _close(SP.ScreenState(), 12.0, 10.0, lo=None) == frozenset()
    st = SP.ScreenState()
    assert SP._curtain_night_close(st, {}, {'T': 5.0}, [_cur()], False, 21.0, 23.0) == frozenset()


def test_outdoor_unknown_uses_indoor_only():
    st = SP.ScreenState()
    assert SP._curtain_night_close(st, {'T': 12.0}, {}, [_cur()], False, 21.4, 23.4) == {'c'}


def test_hysteresis_on_the_way_out():
    """하한 14 · 상한 20: 15.5 에서 닫고(< 16), 16.5 에서는 그대로, 17.2(> 17)·실외 15.5(> 15)에서 푼다."""
    st = SP.ScreenState()
    assert _close(st, 15.5, 15.0, lo=14.0, hi=20.0) == {'c'}
    assert _close(st, 16.5, 15.0, lo=14.0, hi=20.0) == {'c'}
    assert _close(st, 17.2, 14.8, lo=14.0, hi=20.0) == {'c'}       # 실외가 아직 하한 + 1 아래
    assert _close(st, 17.2, 15.5, lo=14.0, hi=20.0) == frozenset()


def test_releases_when_there_is_cooling_to_do():
    st = SP.ScreenState()
    assert _close(st, 22.0, 15.0) == {'c'}
    assert _close(st, 23.0, 15.0) == {'c'}                         # 상한 23.4 아래
    assert _close(st, 23.6, 15.0) == frozenset()                   # 식힐 일 → PI


def test_releases_when_outside_gets_clearly_warmer():
    st = SP.ScreenState()
    assert _close(st, 12.0, 11.0) == {'c'}
    assert _close(st, 12.0, 12.8) == {'c'}                         # + 1 안
    assert _close(st, 12.0, 13.5) == frozenset()


def test_evaluate_screens_carries_the_decision():
    st = SP.ScreenState()
    dec = SP.evaluate_screens(SP.ScreenConfig(cycle_sec=600.0), st, {'T': 11.7, 'RH': 70.0},
                              {'T': 11.2}, [_cur()], None, 0.0,
                              curtain_day_open=False, T_low=21.4, T_high=23.4)
    assert dec.curtain_night_close == frozenset({'c'})
    day = SP.evaluate_screens(SP.ScreenConfig(cycle_sec=600.0), st, {'T': 11.7, 'RH': 70.0},
                              {'T': 11.2}, [_cur()], None, 600.0,
                              curtain_day_open=True, T_low=21.4, T_high=23.4)
    assert day.curtain_night_close == frozenset()


# ── PI 에 얹기 ───────────────────────────────────────────────────────────────

def test_pi_hold_open_becomes_close():
    """무구배 제자리(100 · 근거 15) → 0 · 적분 0 · 근거 49."""
    dec = SP.ScreenDecision(curtain_night_close=frozenset({'c'}))
    assert SP.adjust_pi_command(dec, _cur(), 100.0, 100.0, REASON_NO_GRADIENT, None) == (
        0.0, 0.0, REASON_CURTAIN_NIGHT_CLOSE)
    assert SP.adjust_pi_command(dec, _cur(), 0.0, 3.0, REASON_PRIMARY, 'temperature') == (
        0.0, 0.0, REASON_CURTAIN_NIGHT_CLOSE)


def test_the_humidity_gap_still_cracks_a_closed_curtain():
    dec = SP.ScreenDecision(curtain_night_close=frozenset({'c'}), curtain_gap={'c': 6.0})
    assert SP.adjust_pi_command(dec, _cur(), 100.0, 100.0, REASON_NO_GRADIENT, None) == (
        6.0, 6.0, REASON_CURTAIN_GAP)


def test_gap_enters_on_the_cycle_after_the_close():
    """틈은 나간 개도(`screen_pos`)가 닫힘일 때 들어간다 — 닫은 다음 사이클부터 설 수 있다."""
    st = SP.ScreenState()
    wet = {'T': 15.0, 'RH': 92.0}
    kw = dict(curtain_day_open=False, T_low=21.4, T_high=23.4,
              prev_commands={'c': 100.0})
    d1 = SP.evaluate_screens(SP.ScreenConfig(cycle_sec=600.0), st, wet, {'T': 10.0},
                             [_cur(), types.SimpleNamespace(actuator_id='h', kind='heater',
                                                            capacity_meta={})],
                             None, 0.0, **kw)
    assert d1.curtain_night_close == {'c'} and d1.curtain_gap == {}
    SP.record_screen_positions(st, {'c': {'value': 0.0}}, [_cur()], 0.0)
    d2 = SP.evaluate_screens(SP.ScreenConfig(cycle_sec=600.0), st, wet, {'T': 10.0},
                             [_cur(), types.SimpleNamespace(actuator_id='h', kind='heater',
                                                            capacity_meta={})],
                             None, 600.0, **kw)
    assert d2.curtain_night_close == {'c'} and d2.curtain_gap == {'c': 3.0}


def test_other_kinds_are_untouched():
    dec = SP.ScreenDecision(curtain_night_close=frozenset({'c'}))
    shade = types.SimpleNamespace(actuator_id='c', kind='shade', capacity_meta={})
    assert SP.adjust_pi_command(dec, shade, 100.0, 100.0, REASON_NO_GRADIENT, None)[2] != (
        REASON_CURTAIN_NIGHT_CLOSE)


# ── coordinate() 까지 ────────────────────────────────────────────────────────

def test_coordinate_closes_an_open_curtain_on_a_cold_still_night():
    """영양 밤의 모양: 실내 11.7 · 실외 11.2 · 걷힘(100)에서 출발 — 예전엔 100·근거 15 로 머물렀다."""
    from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
    from aot.functions.utils.env_control.effect_functions import build_effect_model
    from aot.functions.utils.env_control.situation import assess
    from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints, TargetVar

    cur = ActuatorProfile(
        actuator_id='c', kind='curtain', effect_model=build_effect_model('curtain', {}),
        cmd_constraints=CmdConstraints(effective_start_pct=0.0, effective_end_pct=100.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=100.0)
    target = {'temperature': TargetVar(22.4, 1.0, 1.0)}
    internal = {'T': 11.7, 'RH': 84.0, 'CO2': 420.0}
    external = {'T': 11.2, 'RH': 90.0, 'wind': 0.5, 'solar': 0.0}

    def run(decision):
        st = CoordinatorState(integral={'c': 100.0}, prev_commands={'c': 100.0})
        report, _ = assess(target, internal, external, cycle_sec=600.0, now_ts=1767240000.0)
        report.context['curtain_day_open'] = False
        if decision is not None:
            report.context['screen'] = decision
        cmds, new = coordinate(report, [cur], st)
        return cmds['c'], new.integral['c']

    before, _ = run(None)
    assert before.aperture == 100.0 and before.reason == REASON_NO_GRADIENT   # 종전(재현)
    dec = SP.evaluate_screens(SP.ScreenConfig(cycle_sec=600.0), SP.ScreenState(), internal,
                              external, [cur], None, 0.0, curtain_day_open=False,
                              T_low=21.4, T_high=23.4)
    after, I = run(dec)
    assert after.aperture == 0.0 and after.reason == REASON_CURTAIN_NIGHT_CLOSE and I == 0.0


# ── 이슬 수요 (2026-10-12 최종 폐루프 회귀 R2) ────────────────────────────────
# squall_heat/screens: 같은 저녁이 19:30 에 PI(근거 1)로 닫히면 밤 젖음 173 분, 무구배(근거 15)로 걷힌 채 남으면 433 분.
# 열 수요(실내 26 °C, 하한 22)는 없지만 실내 RH 85 % — 이슬점 여유 2.7 °C.

def _close_rh(state, T, RH, T_ext, lo=22.0, hi=32.0):
    return SP._curtain_night_close(state, {'T': T, 'RH': RH}, {'T': T_ext}, [_cur()], False, lo, hi)


def test_small_dew_margin_closes_without_heat_demand():
    assert _close_rh(SP.ScreenState(), 26.0, 85.0, 25.2) == {'c'}


def test_dry_mild_night_stays_open():
    assert _close_rh(SP.ScreenState(), 26.0, 60.0, 25.2) == frozenset()


def test_dew_close_respects_warm_and_warmer_outside():
    assert _close_rh(SP.ScreenState(), 32.5, 90.0, 25.0) == frozenset()     # 식힐 일(상한 위, 바깥이 찬다)
    # VPD 를 좇는 목표 온도는 습한 밤에 실내 바로 위에 선다 — 상한 − 1 안이어도 이슬 수요로는 닫는다.
    assert _close_rh(SP.ScreenState(), 26.0, 85.0, 25.2, lo=24.0, hi=26.5) == {'c'}
    assert _close_rh(SP.ScreenState(), 26.0, 90.0, 26.5) == frozenset()     # 바깥이 더 따뜻하다


def test_dew_close_releases_with_hysteresis():
    st = SP.ScreenState()
    assert _close_rh(st, 26.0, 85.0, 25.0) == {'c'}                          # 여유 2.7
    assert _close_rh(st, 26.0, 80.0, 25.0) == {'c'}                          # 여유 3.7 — 아직(풀림 4.0)
    assert _close_rh(st, 26.0, 75.0, 25.0) == frozenset()                    # 여유 4.8 — 풀림


def test_daytime_dew_does_not_close():
    st = SP.ScreenState()
    assert SP._curtain_night_close(st, {'T': 26.0, 'RH': 90.0}, {'T': 25.0}, [_cur()], True,
                                   22.0, 32.0) == frozenset()


def test_no_gradient_hold_does_not_block_the_night_close():
    """무구배(근거 15)로 걷힌 채 제자리인 커튼도 밤 보온이 서면 닫힌다 — 해 진 뒤 무구배는 닫기를 막지 못한다."""
    dec = SP.ScreenDecision(curtain_night_close=_close_rh(SP.ScreenState(), 26.0, 85.0, 25.2))
    assert SP.adjust_pi_command(dec, _cur(), 100.0, 100.0, REASON_NO_GRADIENT, None) == (
        0.0, 0.0, REASON_CURTAIN_NIGHT_CLOSE)


def test_squall_evening_closes_although_above_the_night_guide():
    """squall_heat/screens 19:30: 실내 26.0 °C · RH 85 % · 바깥 25.2 °C, 밤 유도 범위 12~22 °C. 상한 위지만 바깥이 1 °C 넘게
    차지 않아 걷어도 공기는 안 식는다 — 이슬 수요로 닫는다. 닫힌 뒤에도 같은 이유로 풀리지 않는다."""
    st = SP.ScreenState()
    assert _close_rh(st, 26.0, 85.0, 25.2, lo=12.0, hi=22.0) == {'c'}
    assert _close_rh(st, 25.8, 86.0, 25.1, lo=12.0, hi=22.0) == {'c'}
    # 바깥이 확실히 차면(식힐 수 있으면) 상한 위의 집은 PI 에 맡긴다.
    assert _close_rh(st, 26.0, 86.0, 23.0, lo=12.0, hi=22.0) == frozenset()


def test_rainy_night_has_no_dew_demand():
    """비 오는 밤(typhoon/screens)은 구름이 덮어 복사 냉각이 작다 — 이슬 수요로 닫지 않는다(열 수요는 그대로)."""
    st = SP.ScreenState()
    assert SP._curtain_night_close(st, {'T': 26.0, 'RH': 92.0}, {'T': 25.2, 'rain': 3.0}, [_cur()], False,
                                   12.0, 22.0) == frozenset()
    assert SP._curtain_night_close(st, {'T': 26.0, 'RH': 92.0}, {'T': 25.2, 'rain': 0.0}, [_cur()], False,
                                   12.0, 22.0) == {'c'}
    assert SP._curtain_night_close(SP.ScreenState(), {'T': 12.0, 'RH': 92.0}, {'T': 10.0, 'rain': 3.0},
                                   [_cur()], False, 21.4, 23.4) == {'c'}       # 열 수요
    # 비 띠 사이(강우 0)라도 바깥이 포화(RH ≥ 95 %)면 하늘이 덮여 있다 — 이슬 수요 없음(typhoon 21:30).
    assert SP._curtain_night_close(SP.ScreenState(), {'T': 26.0, 'RH': 95.0}, {'T': 26.0, 'RH': 96.0, 'rain': 0.0},
                                   [_cur()], False, 12.0, 22.0) == frozenset()


def test_a_short_break_between_rain_bands_is_still_rain():
    """typhoon/screens 21:30: 비 띠 사이 30 분 강우 0 — 그친 뒤 한 시간은 이슬 수요로 닫지 않는다."""
    st = SP.ScreenState()
    ins, cur = {'T': 26.0, 'RH': 95.0}, [_cur()]
    assert SP._curtain_night_close(st, ins, {'T': 26.0, 'RH': 91.0, 'rain': 2.0}, cur, False, 12.0, 22.0,
                                   now=0.0) == frozenset()
    assert SP._curtain_night_close(st, ins, {'T': 26.0, 'RH': 91.0, 'rain': 0.0}, cur, False, 12.0, 22.0,
                                   now=1800.0) == frozenset()
    assert SP._curtain_night_close(st, ins, {'T': 26.0, 'RH': 91.0, 'rain': 0.0}, cur, False, 12.0, 22.0,
                                   now=SP.NIGHT_CLOSE_DEW_RAIN_S + 60.0) == {'c'}


# ── 난방 중이면 열 수요가 있다 (2026-10-14) ──────────────────────────────────
# VPD 직접 모드: 난방기는 유도 온도 목표를 좇아 데우는데 커튼의 열 수요 선은 유도 범위(아래 끝 + 2 °C)라, 범위 한가운데
# (19 °C, 범위 12–22)에서 난방기는 돌고 커튼은 걷혀 열을 버렸다(폐루프 normal/screens_heated 난방 kWh +7.7 %).

def _heat(state, T, T_ext, heating, now, lo=12.0, hi=22.0, **kw):
    return SP._curtain_night_close(state, {'T': T, 'RH': 70.0}, {'T': T_ext, 'RH': 60.0},
                                   [_cur()], False, lo, hi, now=now, heating=heating, **kw)


def test_heating_with_colder_outside_closes_in_the_middle_of_the_range():
    assert _heat(SP.ScreenState(), 19.0, 14.0, False, 0.0) == frozenset()          # 난방 없음: 열 수요 없음(이번 수정 동작)
    assert _heat(SP.ScreenState(), 19.0, 14.0, True, 0.0) == frozenset({'c'})      # 난방 중: 닫음


def test_heating_with_warmer_outside_does_not_close():
    assert _heat(SP.ScreenState(), 19.0, 20.0, True, 0.0) == frozenset()
    assert _heat(SP.ScreenState(), 19.0, None, True, 0.0) == frozenset()           # 실외를 모르면 열 수요로 보지 않는다


def test_heating_does_not_beat_the_existing_exceptions():
    assert _heat(SP.ScreenState(), 21.5, 14.0, True, 0.0) == frozenset()           # 실내가 상한 − 1 이상 → 식힐 일
    assert _heat(SP.ScreenState(), 23.0, 14.0, True, 0.0) == frozenset()


def test_day_never_closes_even_while_heating():
    assert SP._curtain_night_close(SP.ScreenState(), {'T': 19.0}, {'T': 14.0}, [_cur()], True,
                                   12.0, 22.0, now=0.0, heating=True) == frozenset()


def test_stays_closed_while_heating_runs_even_when_far_above_the_entry_line():
    st = SP.ScreenState()
    assert _heat(st, 15.0, 13.0, True, 0.0) == {'c'}                               # 12 + 2 = 14 위에서도 난방 때문에 들어감
    assert _heat(st, 18.0, 13.0, True, 600.0) == {'c'}                             # 예전 '풀림' 선(15 + )을 넘어도 유지
    assert _heat(st, 18.0, 13.0, True, 1200.0) == {'c'}


def test_release_after_heating_stops_follows_the_old_rule_after_the_hold():
    st = SP.ScreenState()
    _heat(st, 18.0, 14.0, True, 0.0)
    # 난방이 멎어도 NIGHT_CLOSE_HEAT_HOLD_S 안에서는 난방 중으로 친다 — 펄스마다 커튼이 왕복하지 않는다
    assert _heat(st, 18.0, 14.0, False, 600.0) == {'c'}
    assert _heat(st, 18.0, 14.0, False, SP.NIGHT_CLOSE_HEAT_HOLD_S - 1.0) == {'c'}
    # 그 뒤에는 기존 해제 규칙(실내·실외 모두 들어간 선 + 1 위) — 바로 걷힌다
    assert _heat(st, 18.0, 14.0, False, SP.NIGHT_CLOSE_HEAT_HOLD_S + 1.0) == frozenset()


def test_release_conditions_still_win_while_heating():
    st = SP.ScreenState()
    _heat(st, 18.0, 13.0, True, 0.0)
    assert _heat(st, 22.6, 13.0, True, 600.0) == frozenset()                       # 식힐 일(상한 22 초과)
    st = SP.ScreenState()
    _heat(st, 18.0, 13.0, True, 0.0)
    assert _heat(st, 18.0, 19.5, True, 600.0) == frozenset()                       # 실외가 clearly 더 따뜻함


def test_without_heating_the_old_decisions_are_unchanged():
    st = SP.ScreenState()
    assert _close(st, 15.5, 15.0, lo=14.0, hi=20.0) == {'c'}
    assert _close(st, 17.2, 15.5, lo=14.0, hi=20.0) == frozenset()


def test_dew_demand_and_the_gap_are_not_touched_by_heating():
    wet = {'T': 19.0, 'RH': 93.0}
    st = SP.ScreenState()
    # 이슬 수요로 닫는 건 난방과 무관하다(난방 없음에서도 닫는다)
    assert SP._curtain_night_close(st, wet, {'T': 14.0, 'RH': 60.0}, [_cur()], False, 12.0, 22.0,
                                   now=0.0, heating=False) == {'c'}
    heater = types.SimpleNamespace(actuator_id='h', kind='heater', capacity_meta={})
    gap_cold = SP._curtain_gap(SP.ScreenConfig(cycle_sec=600.0), SP.ScreenState(), wet, {'T': 14.0},
                               [_cur(), heater], {'c': 0.0}, False, 12.0, 0.0)
    gap_hot = SP._curtain_gap(SP.ScreenConfig(cycle_sec=600.0), SP.ScreenState(), wet, {'T': 14.0},
                              [_cur(), heater], {'c': 0.0, 'h': 0.0}, False, 12.0, 0.0)
    assert gap_hot[0] == {'c': SP.GAP_STEPS[0]} and gap_cold[0] == {'c': SP.GAP_STEPS[0]}


def test_evaluate_screens_reads_the_heater_command_from_prev_commands():
    heater = types.SimpleNamespace(actuator_id='h', kind='heater', capacity_meta={})
    cooler = types.SimpleNamespace(actuator_id='k', kind='cooler', capacity_meta={})

    def go(prev, profs):
        return SP.evaluate_screens(SP.ScreenConfig(cycle_sec=600.0), SP.ScreenState(), {'T': 19.0, 'RH': 70.0},
                                   {'T': 14.0, 'RH': 60.0}, profs, None, 0.0, curtain_day_open=False,
                                   T_low=12.0, T_floor=12.0, T_high=22.0, prev_commands=prev)
    assert go({'h': 40.0}, [_cur(), heater]).curtain_night_close == frozenset({'c'})
    assert go({'h': 0.0}, [_cur(), heater]).curtain_night_close == frozenset()
    assert go({}, [_cur(), heater]).curtain_night_close == frozenset()
    assert go({'k': 80.0}, [_cur(), cooler]).curtain_night_close == frozenset()    # 냉방은 열 수요가 아니다


def test_heat_seen_at_survives_a_restart():
    """사이클 기억(`cycle_memory`)은 ScreenState 의 필드를 그대로 싣는다 — 새 필드도 dataclass 필드여야 한다."""
    import dataclasses
    assert 'heat_seen_at' in {f.name for f in dataclasses.fields(SP.ScreenState)}
