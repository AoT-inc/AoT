# coding=utf-8
"""실내를 모르는 동안의 환기 — '제자리' 가 맑은 낮을 닫아 두지 않고, 제자리가 서서히 닫히지 않는다 (2026-10-14).

실측(개발서버 2026-10-14): 07:29 KST 부터 실내 미러 센서가 모두 끊겼다(원천 네트워크 장애).

  · 김제 육묘장3 09:03~12:55 — 맑음, 외기 19 °C · RH 25 %, 측창 0 %, 근거 21(실내 측정 없음 → 제자리).
    구마모토 08:23 이후 일사 656 W/m², 창 0 %. 밤에 닫힌 0 % 를 제자리가 낮까지 끌고 갔다. 일사 하한(51)도
    실내 온도가 있어야 서서 함께 빠졌다. 실제 온실이면 닫힌 채 30~40 °C 다.
  · 김제 측창이 근거 21 인데 08:13~09:03 20 → 16 → 13 → 12 → 7 → 0 % 로 줄었다. 제자리가 직전 개도를 그대로
    내서 `finalize_command` 의 전달 비율(풍향 가중치, `cmd_scale`)이 사이클마다 곱해졌다.

고친 뒤의 규칙(`solar_vent` 머리말 마지막 절 · `coordinator` 2.8b · 근거 60):
  1. 제자리는 실제 개도다 — 전달 비율로 나눠 낸다(`hold_command`).
  2. 실내 온도를 모르고 실외 실측이 있는 맑은 낮(일사 ≥ 200 W/m² · 외기 ≥ 12 °C · 외기 + 0.02 × 일사 > 선)이면
     환기창을 10~20 % 하한까지 사이클당 5 %p 씩 연다. 흐림·밤·찬 바깥은 제자리. 해가 진 뒤에는 그 크기
     이하로 열린 창을 같은 폭으로 닫는다. 비 단계 제한이 이긴다. 실내가 돌아오면 보통의 판정이다.
"""
import pytest

from aot.functions.utils.env_control import coordinator as C
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import situation as S
from aot.functions.utils.env_control import solar_vent as SV
from aot.functions.utils.env_control.authority import derive_authority
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.goal import build_env_target
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.types import ActuatorProfile

CYCLE = 600.0
# 김제 10/14 정오 꼴 — 외기 19 °C · RH 25 %, 맑은 하늘 650 W/m²
_EXT = {'T': 19.0, 'RH': 25.0, 'wind': 1.0}


def _vent(aid='v', scale=1.0):
    p = ActuatorProfile(actuator_id=aid, kind='opening',
                        effect_model=build_effect_model('opening', {}), safe_default=0.0)
    p.cmd_scale = scale
    return p


def _report(internal, profiles, external=None, **ctx):
    target = build_env_target(T_target=25.0, T_tol=1.0, T_pri=0.5,
                              RH_target=70.0, RH_tol=5.0, RH_pri=0.5)
    target.pop('co2', None)
    report, _ = S.assess(target, dict(internal), dict(external or _EXT), cycle_sec=CYCLE,
                         authority=derive_authority(profiles))
    report.context['cycle_sec'] = CYCLE
    report.context['heat_protect'] = HeatProtectDecision(tier=0, threshold=30.0)
    report.context['temp_max'] = 36.0
    report.context.update(ctx)
    return report


def _blind(profiles, solar=650.0, clear_sky=650.0, external=None, sv_state=None, **ctx):
    """실내 온도·습도 없음. 일사는 실외 실측(`solar=None` 이면 맑은 하늘 × `BLIND_UNMEASURED_CLOUD`)."""
    internal = {'wind': 1.0}
    if solar is not None:
        internal['_outdoor_solar'] = solar
    rep = _report(internal, profiles, external, clear_sky_now=clear_sky, **ctx)
    st = sv_state if sv_state is not None else SV.SolarVentState()
    rep.context['solar_vent'] = SV.evaluate_solar_vent(
        st, rep.context, rep.target or {}, clear_sky_now=clear_sky)
    return rep


def _run(rep_fn, profiles, prev, cycles):
    """`rep_fn()` 이 매 사이클의 상황을 만든다. 실제 나간 개도 목록을 돌려준다."""
    state = C.CoordinatorState(prev_commands={p.actuator_id: prev for p in profiles})
    seq = []
    for _ in range(cycles):
        cmds, state = C.coordinate(rep_fn(), profiles, state)
        seq.append((round(cmds['v'].control_value(), 3), cmds['v'].reason))
    return seq, state


# ─────────────────────────────────────────────────────────────────────────────
# 1. 제자리는 실제 개도다 (할 일 B)
# ─────────────────────────────────────────────────────────────────────────────

class TestHoldKeepsTheActualOpening:

    def test_실내_모름_제자리가_풍향_가중치에_감쇠하지_않는다(self):
        """사고 재현 — 고치기 전에는 20 → 16 → 12.8 → 10.2 …(가중치 0.8)."""
        p = _vent(scale=0.8)
        # 흐린 아침(해 부하 없음 · 해는 떠 있음) — 열지도 닫지도 않는 순수한 제자리
        seq, _ = _run(lambda: _blind([p], solar=120.0, clear_sky=500.0), [p], 20.0, 6)
        assert all(r == LC.REASON_NO_MEASUREMENT for _, r in seq)
        assert [v for v, _ in seq] == [pytest.approx(20.0)] * 6

    def test_실외_모름_제자리도_같다(self):
        p = _vent(scale=0.6)
        rep = lambda: _report({'T': 26.0, 'RH': 60.0}, [p], external={'_ext_synthetic': True})
        seq, _ = _run(rep, [p], 15.0, 5)
        assert all(r == LC.REASON_NO_OUTDOOR_DATA for _, r in seq)
        assert [v for v, _ in seq] == [pytest.approx(15.0)] * 5

    def test_비율_1_이면_종전과_같다(self):
        p = _vent(scale=1.0)
        assert C.hold_command(p, 20.0) == pytest.approx(20.0)
        p.cmd_scale = 0.0   # 게이트 차단 — 무엇을 내도 0
        assert C.hold_command(p, 20.0) == pytest.approx(20.0)
        p.cmd_scale = 0.5
        assert C.hold_command(p, 20.0) == pytest.approx(40.0)
        assert C.hold_command(p, 80.0) == pytest.approx(100.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 판정 — `solar_vent`
# ─────────────────────────────────────────────────────────────────────────────

class TestBlindDecision:

    def test_맑은_낮이면_하한이_선다(self):
        dec = _blind([_vent()]).context['solar_vent']
        assert dec.blind and not dec.active
        # 닫힌 집 어림 19 + 0.02 × 650 = 32 > 선(25 + 1) — 보호 문턱(30)까지의 폭 4 °C 를 넘어 상한 20 %
        assert dec.t_est == pytest.approx(32.0)
        assert dec.blind_floor_pct == pytest.approx(SV.BLIND_FLOOR_MAX_PCT)

    def test_일사_센서가_없어도_맑은_하늘로_어림한다(self):
        """김제 — 기상청 실외에 일사 채널이 없다. 맑은 하늘 650 × 0.75 = 487.5 → 19 + 9.75 = 28.75 > 26."""
        dec = _blind([_vent()], solar=None, clear_sky=650.0).context['solar_vent']
        assert dec.t_est == pytest.approx(28.75)
        assert SV.BLIND_FLOOR_MIN_PCT < dec.blind_floor_pct < SV.BLIND_FLOOR_MAX_PCT

    def test_흐리면_서지_않는다(self):
        dec = _blind([_vent()], solar=120.0, clear_sky=650.0).context['solar_vent']
        assert dec.blind_floor_pct == 0.0 and dec.blind_why_off == 'no_sun'

    def test_바깥이_차면_서지_않는다(self):
        dec = _blind([_vent()], external=dict(_EXT, T=8.0)).context['solar_vent']
        assert dec.blind_floor_pct == 0.0 and dec.blind_why_off == 'cold_outside'

    def test_닫힌_집_어림이_선_아래면_서지_않는다(self):
        dec = _blind([_vent()], solar=220.0, external=dict(_EXT, T=13.0)).context['solar_vent']
        # 13 + 4.4 = 17.4 < 26
        assert dec.blind_floor_pct == 0.0 and dec.blind_why_off == 'cool'

    def test_바깥이_극한_고온이면_최소_하한만(self):
        dec = _blind([_vent()], external=dict(_EXT, T=33.0)).context['solar_vent']
        assert dec.blind_floor_pct == pytest.approx(SV.BLIND_FLOOR_MIN_PCT)

    def test_실외를_지어냈으면_실내_모름_판정도_없다(self):
        dec = _blind([_vent()], external={'_ext_synthetic': True}).context['solar_vent']
        assert not dec.blind and dec.blind_floor_pct == 0.0

    def test_실내를_재면_이_판정이_아니다(self):
        rep = _report({'T': 27.5, 'RH': 50.0, '_outdoor_solar': 650.0}, [_vent()])
        dec = SV.evaluate_solar_vent(SV.SolarVentState(), rep.context, rep.target)
        assert not dec.blind and dec.active      # 보통의 일사 하한(근거 51)

    def test_선_쪽은_이력을_갖는다(self):
        st = SV.SolarVentState()
        # 17 + 0.02 × 460 = 26.2 > 26 → 선다
        assert _blind([_vent()], solar=460.0, external=dict(_EXT, T=17.0),
                      sv_state=st).context['solar_vent'].blind_floor_pct > 0.0
        # 25.8 — 선 아래지만 0.5 °C 안이라 유지
        assert _blind([_vent()], solar=440.0, external=dict(_EXT, T=17.0),
                      sv_state=st).context['solar_vent'].blind_floor_pct > 0.0
        # 25.4 — 풀린다
        assert _blind([_vent()], solar=420.0, external=dict(_EXT, T=17.0),
                      sv_state=st).context['solar_vent'].blind_floor_pct == 0.0

    def test_해_쪽도_이력을_갖는다(self):
        st = SV.SolarVentState()
        assert _blind([_vent()], solar=650.0, sv_state=st).context['solar_vent'].blind_floor_pct > 0.0
        # 해 문턱(200) 아래 · 풀림(150) 위 — 유지
        assert _blind([_vent()], solar=180.0, external=dict(_EXT, T=24.0),
                      sv_state=st).context['solar_vent'].blind_floor_pct > 0.0
        dec = _blind([_vent()], solar=140.0, external=dict(_EXT, T=24.0), sv_state=st).context['solar_vent']
        assert dec.blind_floor_pct == 0.0 and dec.blind_why_off == 'no_sun'
        # 새로 서려면 200 이 필요하다
        assert _blind([_vent()], solar=180.0, external=dict(_EXT, T=24.0),
                      sv_state=st).context['solar_vent'].blind_floor_pct == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. 명령 — `coordinate`
# ─────────────────────────────────────────────────────────────────────────────

class TestBlindCommand:

    def test_맑은_낮_닫힌_창을_천천히_하한까지_연다(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p]), [p], 0.0, 6)
        vals = [v for v, _ in seq]
        assert vals[:4] == [pytest.approx(5.0), pytest.approx(10.0),
                            pytest.approx(15.0), pytest.approx(20.0)]
        assert vals[4:] == [pytest.approx(20.0)] * 2
        assert {r for _, r in seq[:4]} == {LC.REASON_BLIND_SUN_VENT}
        assert seq[-1][1] == LC.REASON_NO_MEASUREMENT      # 하한에 닿은 뒤는 제자리

    def test_짧은_주기에서도_min_on_에_막히지_않는다(self):
        p = _vent()

        def rep():
            r = _blind([p])
            r.context['cycle_sec'] = 60.0
            return r
        seq, _ = _run(rep, [p], 0.0, 3)
        assert seq[0][0] >= p.cmd_constraints.min_on_pct
        assert seq[2][0] > seq[0][0]

    def test_풍향_가중치가_있어도_실제_개도가_오른다(self):
        p = _vent(scale=0.8)
        seq, _ = _run(lambda: _blind([p]), [p], 0.0, 6)
        vals = [v for v, _ in seq]
        assert vals[0] >= p.cmd_constraints.min_on_pct
        assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))
        assert vals[-1] == pytest.approx(SV.BLIND_FLOOR_MAX_PCT * 0.8)

    def test_이미_더_열려_있으면_닫지_않는다(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p]), [p], 45.0, 4)
        assert [v for v, _ in seq] == [pytest.approx(45.0)] * 4
        assert {r for _, r in seq} == {LC.REASON_NO_MEASUREMENT}

    def test_흐리면_제자리(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p], solar=120.0), [p], 0.0, 4)
        assert seq == [(0.0, LC.REASON_NO_MEASUREMENT)] * 4

    def test_해_질_녘_어스름은_제자리(self):
        """해 있음(150) 아래 · 해 짐(맑은 하늘 50) 위 — 열지도 닫지도 않는다."""
        p = _vent()
        seq, _ = _run(lambda: _blind([p], solar=None, clear_sky=120.0), [p], 15.0, 3)
        assert seq == [(pytest.approx(15.0), LC.REASON_NO_MEASUREMENT)] * 3

    def test_해가_지면_작은_열림을_천천히_닫는다(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p], solar=None, clear_sky=10.0), [p], 15.0, 4)
        assert [v for v, _ in seq] == [pytest.approx(10.0), pytest.approx(5.0), 0.0, 0.0]
        assert seq[0][1] == LC.REASON_BLIND_SUN_VENT

    def test_밤에도_크게_열린_창은_제자리(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p], solar=None, clear_sky=10.0), [p], 45.0, 3)
        assert seq == [(pytest.approx(45.0), LC.REASON_NO_MEASUREMENT)] * 3

    def test_비_단계_제한이_이긴다(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p], vent_open_caps={'v': None},
                                     vent_open_cap_reasons={'v': LC.REASON_RAIN_RESTRICT}),
                      [p], 0.0, 3)
        assert seq == [(0.0, LC.REASON_RAIN_RESTRICT)] * 3
        seq, _ = _run(lambda: _blind([p], vent_open_caps={'v': 8.0},
                                     vent_open_cap_reasons={'v': LC.REASON_RAIN_RESTRICT}),
                      [p], 0.0, 4)
        assert max(v for v, _ in seq) <= 8.0 + 1e-9

    def test_강우_풍속_모름이면_열지_않는다(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p], vent_open_ceiling=True), [p], 0.0, 3)
        assert max(v for v, _ in seq) == 0.0

    def test_야간_파킹이_이긴다(self):
        p = _vent()
        rep = _blind([p], night_vent_park=True)
        assert not C.decide_parking([p], rep, rep.context, CYCLE, {'v': 0.0}).blind_floor_ids
        rep = _blind([p])
        assert C.decide_parking([p], rep, rep.context, CYCLE, {'v': 0.0}).blind_floor_ids == {'v'}

    def test_밤_야간_파킹_대상이면_크게_열린_창도_근거_19_로_닫는다(self):
        """김제 10/14 17:04~ 실내 두절로 55 % 에 묶인 측창 — 해가 지면(야간 파킹 시작) 근거 21 이 아니라 19 로 감쇠한다.

        우선순위: 야간 파킹(19) > 해 진 뒤 닫기(60, ≤ 20 %) > 제자리(21). `blind_ids` 가 `park_ids` 를 빼 두어서
        파킹된 창은 실내 모름 분기를 지나 파킹 분기로 간다 — 그 `- park_ids` 가 빠지면 이 시험이 깨진다.
        """
        p = _vent()
        seq, _ = _run(lambda: _blind([p], solar=None, clear_sky=10.0, night_vent_park=True), [p], 55.0, 4)
        assert [v for v, _ in seq] == [pytest.approx(35.0), pytest.approx(21.0),
                                       pytest.approx(12.6), pytest.approx(7.56)]
        assert {r for _, r in seq} == {LC.REASON_NIGHT_PARKED}

    def test_야간_파킹이_작은_열림의_해_진_뒤_닫기_근거_60_보다_앞선다(self):
        p = _vent()
        seq, _ = _run(lambda: _blind([p], solar=None, clear_sky=10.0, night_vent_park=True), [p], 15.0, 2)
        assert seq[0] == (pytest.approx(9.0), LC.REASON_NIGHT_PARKED)

    def test_야간_파킹이_꺼져_있으면_밤에도_크게_열린_창은_제자리(self):
        """옵션을 켜지 않은 시설은 종전 그대로 — 파킹을 안 쓰기로 한 것이다(실외 모름 쪽도 같다)."""
        p = _vent()
        seq, _ = _run(lambda: _blind([p], solar=None, clear_sky=10.0, night_vent_park=False), [p], 55.0, 3)
        assert seq == [(pytest.approx(55.0), LC.REASON_NO_MEASUREMENT)] * 3

    def test_낮에는_파킹이_없어_제자리_또는_하한(self):
        """옵션은 켜져 있어도 아직 밤이 아니면(`night_vent_park` 판정이 거짓) 낮의 동작 그대로."""
        p = _vent()
        seq, _ = _run(lambda: _blind([p], night_vent_park=False), [p], 55.0, 3)
        assert seq == [(pytest.approx(55.0), LC.REASON_NO_MEASUREMENT)] * 3
        seq, _ = _run(lambda: _blind([p], night_vent_park=False), [p], 0.0, 2)
        assert [r for _, r in seq] == [LC.REASON_BLIND_SUN_VENT] * 2

    def test_실외_모름_쪽은_그대로_야간_파킹이_닫는다(self):
        p = _vent()
        rep = lambda: _report({'T': 26.0, 'RH': 60.0}, [p], external={'_ext_synthetic': True},
                              night_vent_park=True, clear_sky_now=10.0)
        seq, _ = _run(rep, [p], 55.0, 3)
        assert [v for v, _ in seq] == [pytest.approx(35.0), pytest.approx(21.0), pytest.approx(12.6)]
        assert {r for _, r in seq} == {LC.REASON_NIGHT_PARKED}

    def test_실내가_돌아오면_보통의_판정(self):
        p = _vent()
        state = C.CoordinatorState(prev_commands={'v': 0.0})
        for _ in range(3):
            cmds, state = C.coordinate(_blind([p]), [p], state)
        assert cmds['v'].reason == LC.REASON_BLIND_SUN_VENT
        opened = cmds['v'].control_value()
        # 실내 22 °C · RH 70 % — 시원하다. 근거 60·21 이 아니고, 적분이 그 자리에서 이어 가 계단 없이 내려간다.
        back = _report({'T': 22.0, 'RH': 70.0, '_outdoor_solar': 650.0}, [p], clear_sky_now=650.0)
        back.context['solar_vent'] = SV.evaluate_solar_vent(
            SV.SolarVentState(), back.context, back.target, clear_sky_now=650.0)
        assert not back.context['solar_vent'].blind
        cmds, state = C.coordinate(back, [p], state)
        assert cmds['v'].reason not in (LC.REASON_BLIND_SUN_VENT, LC.REASON_NO_MEASUREMENT)
        assert cmds['v'].control_value() <= opened + 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# 4. 근거 60 의 이름·화면
# ─────────────────────────────────────────────────────────────────────────────

class TestReason:

    def test_번호와_이름(self):
        assert LC.REASON_BLIND_SUN_VENT == 60
        assert LC.reason_name(60) == 'blind_sun_vent'

    def test_건강_점검이_이름을_안다(self):
        from aot.scripts import check_env_coordinator_health as H
        assert H.REASON_LABEL[LC.REASON_BLIND_SUN_VENT]
