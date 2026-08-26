# coding=utf-8
"""야간에는 창을 닫고 **장치로** 관리한다 (`night_vent_park`, 2026-08-26).

밤에는 습도가 오르고 이슬이 맺힌다. 해질 무렵 "쓸모 있어 보이던" 개구도 아침까지
작물을 젖은 채로 둘 수 있다 — 엽면 습윤 지속 시간이 길수록 잿빛곰팡이·노균병
위험이 커진다.

## ⚠ 시간창(`time_enable`)의 확장이 아니다

    time_enable   창밖 시간 → `_apply_end_behaviors()` 후 return  = 제어 **중단**
    night_vent_park  개구부만 park_ids 로                          = 수단의 **제한**

기존 옵션을 확장하면 밤에 난방까지 멈춘다. 공유하는 것은 동작이 아니라 기준축
(시간 vs 일출·일몰)뿐이라, 별개 옵션으로 둔다.

## 왜 파킹(park_ids)이지 잠금이 아닌가

파킹은 코디네이터 안의 판정이라 **안전 게이트가 그 위에 있다.** 게이트는 이
함수 앞에서 명령을 강제하거나(triggered) 뒤에서 덮어쓴다(partial) — 여름밤
고온에 창이 잠긴 채 방치되면 작물 손실인데, 파킹이면 그 성질이 공짜로 따라온다.

## 탈출구

밤새 닫아 두면 결로·고온이 쌓인다. 하드 임계를 넘으면 파킹을 **푼다**
(`_force_cool`·`_force_dehumid`). 이것이 없으면 "여력만 묻고 결과는 안 묻는"
실패가 세 번째로 재현된다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.log_channels import (
    REASON_NIGHT_PARKED, REASON_NO_GRADIENT, REASON_PRIMARY,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context):
        self.target = {'vpd': TargetVar(value=1.0, tolerance=0.1,
                                        priority=1.2, unit='kPa')}
        self.deviation_native = deviation
        self.context = context


def _p(aid, kind, magnitude=0.4, safe_default=0.0):
    return ActuatorProfile(
        actuator_id=aid, kind=kind,
        effect_model={'vpd': _effect('↑', magnitude)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=safe_default)


def _run(night, cycles=1):
    """실외가 더 건조(0.897) → 창을 열면 VPD 가 오른다. 밤이면 열지 않는다."""
    import math
    T = 30.0
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    ctx = {'cycle_sec': 600.0, 'T_ext': T,
           'RH_ext': (1.0 - 0.897 / svp) * 100.0,
           'vent_futility_gate': False, 'night_vent_park': night}
    vent, heater = _p('vent', 'opening'), _p('heater', 'heater')
    st = CoordinatorState()
    st.prev_commands = {'vent': 40.0, 'heater': 20.0}
    st.integral      = {'vent': 40.0, 'heater': 20.0}
    for _ in range(cycles):
        cmds, st = coordinate(_Situation({'vpd': -0.33}, ctx),
                              [vent, heater], st, unique_id='t')
    return cmds


class TestParking:

    def test_the_vent_closes_at_night(self):
        cmds = _run(night=True)
        assert cmds['vent'].reason == REASON_NIGHT_PARKED
        assert cmds['vent'].control_value() < 40.0

    def test_it_keeps_closing_toward_the_safe_default(self):
        cmds = _run(night=True, cycles=10)
        assert cmds['vent'].control_value() < 1.0

    def test_the_heater_still_works(self):
        """제어의 중단이 아니라 수단의 제한이다 — 냉난방까지 멈추면 밤새
        아무도 일하지 않는다."""
        cmds = _run(night=True)
        assert cmds['heater'].reason == REASON_PRIMARY
        assert cmds['heater'].control_value() > 20.0

    def test_by_day_the_vent_opens_as_before(self):
        cmds = _run(night=False)
        assert cmds['vent'].reason == REASON_PRIMARY
        assert cmds['vent'].control_value() > 40.0


class TestTheReasonIsItsOwn:
    """15(무구배)와 뭉치면 "왜 밤에 창이 안 열리나" 에 화면이 답할 수 없다.

    15 는 "밀어도 안 움직인다" 이고 19 는 "지금은 열지 않기로 했다" 다 —
    뒤는 사용자가 켠 옵션의 결과이므로 그렇게 말해야 한다.
    """

    def test_night_parking_is_not_reported_as_no_gradient(self):
        assert _run(night=True)['vent'].reason != REASON_NO_GRADIENT

    def test_the_code_is_in_the_shared_table(self):
        from aot.functions.utils.env_control import log_channels as LC
        assert LC.REASON_NIGHT_PARKED == 19
        codes = [v for k, v in vars(LC).items()
                 if k.startswith('REASON_') and isinstance(v, int)]
        assert len(codes) == len(set(codes)), '근거코드가 겹친다'


class TestScreensAreNotVents:
    """개구부만 닫는다 — 보온커튼·차광막은 이 옵션의 대상이 아니다."""

    def test_a_curtain_is_untouched(self):
        import math
        T = 30.0
        svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
        ctx = {'cycle_sec': 600.0, 'T_ext': T,
               'RH_ext': (1.0 - 0.897 / svp) * 100.0,
               'vent_futility_gate': False, 'night_vent_park': True}
        curtain = _p('curtain', 'curtain', safe_default=100.0)
        st = CoordinatorState()
        st.prev_commands = {'curtain': 50.0}
        st.integral      = {'curtain': 50.0}
        cmds, _ = coordinate(_Situation({'vpd': -0.33}, ctx), [curtain], st,
                             unique_id='t')
        assert cmds['curtain'].reason != REASON_NIGHT_PARKED


# ─────────────────────────────────────────────────────────────────────────────
# 판정(언제가 밤인가)은 코디네이터가 아니라 호출자에 있다 — 소스로 고정한다.
# ─────────────────────────────────────────────────────────────────────────────

def _helpers_src():
    import inspect
    from aot.functions.custom_functions.env_coordinator_impl \
        import _helpers_mixin as m
    return inspect.getsource(m)


class TestTheDecisionLivesWithTheCaller:

    def test_the_hard_limit_escape_exists(self):
        """탈출구가 없으면 닫힌 온실이 익거나 잠긴다."""
        src = _helpers_src()
        block = src.split('def _night_vent_parked', 1)[1].split(
            '\n    def ', 1)[0]
        assert "_force_cool" in block and "_force_dehumid" in block, (
            '하드 임계를 넘어도 파킹이 안 풀린다')

    def test_missing_coordinates_do_not_park(self):
        """위치를 모른다는 이유로 밤새 창을 잠그면, 사용자가 켠 적 없는
        위험을 시스템이 만든다(`_evening_fog_blocked` 과 같은 판단)."""
        src = _helpers_src()
        block = src.split('def _night_vent_parked', 1)[1].split(
            '\n    def ', 1)[0]
        i_none = block.index('st is None')
        assert 'return False' in block[i_none:i_none + 120]

    def test_a_negative_offset_cannot_delay_the_close(self):
        """음수 오프셋은 일몰 **뒤에** 닫히게 하는데, 그 지연이야말로 이
        옵션이 없애려는 것이다."""
        src = _helpers_src()
        block = src.split('def _night_vent_parked', 1)[1].split(
            '\n    def ', 1)[0]
        assert 'max(0.0, float(' in block

    def test_the_clock_basis_crosses_midnight(self):
        """18:00~06:00 이 하룻밤이다 — 뒤집힌 구간을 안 다루면 밤에 한 번도
        파킹되지 않는다."""
        src = _helpers_src()
        block = src.split('def _night_vent_parked', 1)[1].split(
            '\n    def ', 1)[0]
        assert 'now >= start or now <= end' in block

    def test_it_uses_facility_local_time_not_server_time(self):
        """같은 서버가 여러 지역의 시설을 돌린다 — 서버 시각을 쓰면 쿠마모토
        온실이 서울 시각으로 밤을 맞는다."""
        src = _helpers_src()
        block = src.split('def _night_vent_parked', 1)[1].split(
            '\n    def ', 1)[0]
        assert '_facility_local_now' in block


class TestOptionSchema:

    def _opts(self):
        from aot.functions.custom_functions.env_coordinator_impl import (
            _function_info as fi)
        return {o.get('id'): o for o in fi.FUNCTION_INFORMATION['custom_options']
                if o.get('id')}

    def test_it_is_off_by_default(self):
        """업그레이드로 조용히 달라지는 설치가 없어야 한다 — 밤에 제습 환기가
        필요한 온실이 있다."""
        o = self._opts()['night_vent_park']
        assert o['default_value'] is False
        assert o['type'] == 'bool', '슬라이드 토글은 bool 이 렌더한다'

    def test_both_bases_are_offered(self):
        sel = dict(self._opts()['night_vent_basis']['options_select'])
        assert set(sel) == {'sun', 'clock'}

    def test_ctx_carries_the_decision(self):
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl \
            import _cycle_mixin as m
        src = inspect.getsource(m.CycleMixin._run_cycle)
        assert "situation.context['night_vent_park']" in src
        assert '_night_vent_parked(internal)' in src, (
            '내부 상태를 안 넘기면 하드 임계 탈출구가 판정할 근거가 없다')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


# ─────────────────────────────────────────────────────────────────────────────
# 저장 시 경고 — 문구가 **번역 가능**해야 한다 (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────

class TestGuideRangeWarningIsTranslatable:
    """경고에 끼워 넣는 조각까지 번역돼야 한다.

    처음 만들 때 `clamp_guide_range_to_hard_limits()` 가 돌려주는 `changed`
    (`'T상한→30.0'`)를 화면에 그대로 실었다. 그것은 **로그용 한국어 조각**이라,
    일본어 화면에서 일본어 문장 안에 한국어가 섞여 나온다.

    지금은 클램프의 **결과**와 입력을 비교해 축을 가려내고, 문장은 번역 가능한
    msgid 하나로 만든다 — 판정을 다시 하는 것이 아니라 이미 나온 답을 읽는
    것이므로 정본은 여전히 클램프 하나다.
    """

    def _src(self):
        import inspect
        from aot.functions.custom_functions import env_coordinator as m
        return inspect.getsource(m.execute_at_modification)

    def test_the_log_fragments_are_not_shown_to_the_user(self):
        src = self._src()
        code = '\n'.join(ln.split('#', 1)[0] for ln in src.splitlines())
        assert 'join(changed)' not in code and "'.join(_changed)" not in code, (
            '로그용 한국어 조각을 화면에 그대로 싣고 있다')

    def test_the_axis_words_go_through_gettext(self):
        code = '\n'.join(ln.split('#', 1)[0] for ln in self._src().splitlines())
        assert "gettext('temperature')" in code
        assert "gettext('humidity')" in code

    def test_the_msgid_carries_no_literal_percent(self):
        """⚠ 리터럴 `%` 는 python-format 판정을 깨서 `pybabel compile` 이
        그 언어 **전체**를 거부한다. 단위(`%`)는 값 쪽에 붙인다."""
        code = self._src()
        msg = code.split("messages['warning'].append(str(gettext(", 1)[1]
        msgid = msg.split('what=', 1)[0]
        import re
        # `%(name)s` 는 정상 자리표시자 — 그 밖의 `%` 만 본다.
        assert not re.search(r'%(?!\(\w+\)s)', msgid), (
            'msgid 에 리터럴 %% 가 있다: %r' % msgid)

    def test_both_catalogs_have_it(self):
        import gettext as g
        MSG = ('The guide range for %(what)s (%(guide)s) lies outside your '
               'hard limits (%(hard)s), so targets are only built inside '
               '%(effective)s. Widen the hard limits or narrow the guide '
               'range so the two agree.')
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(here, '..', '..', '..', '..', 'aot_flask', 'translations')
        for lang in ('ko', 'ja'):
            t = g.translation('messages', d, languages=[lang])
            for src in (MSG, 'temperature', 'humidity'):
                assert t.gettext(src) != src, '%s: %r 이 번역되지 않았다' % (lang, src[:40])


class TestTheWarningOnlyFiresOnRelevantEdits:
    """조건이 아니라 **이번 저장에서 손댄 것**을 기준으로 말한다.

    조건(유도가 임계 밖)은 한 번 만들어지면 계속 참이라, 그것만 보면 **저장할
    때마다** 뜬다. 야간 파킹 토글 하나를 켰는데 온도 경고가 같이 나오고,
    사용자는 "이것 때문에 안 켜지나" 로 읽는다(2026-08-26 실제로 그랬다).
    기존 경고들(`nursery_evening_fog` 계열)은 자기 설정을 건드릴 때만 뜬다.
    """

    def _src(self):
        import inspect
        from aot.functions.custom_functions import env_coordinator as m
        return inspect.getsource(m.execute_at_modification)

    def _code(self):
        return '\n'.join(ln.split('#', 1)[0] for ln in self._src().splitlines())

    def test_it_reads_the_presave_values(self):
        assert 'custom_options_dict_presave' in self._code(), (
            '직전 값을 안 읽는다 — 무엇이 바뀌었는지 알 수 없다')

    def test_each_axis_checks_its_own_four_values(self):
        code = self._code()
        assert "_touched(lo_key, hi_key, g_lo, g_hi)" in code, (
            '축마다 자기 값이 바뀌었는지 보지 않는다')

    def test_the_comparison_is_numeric(self):
        """폼에서 온 값은 문자열일 수 있다 — `'30.0' != 30.0` 이면 언제나
        "바뀜" 이라 검사가 통째로 무력해진다."""
        block = self._code().split('def _touched', 1)[1].split('\n    _fresh', 1)[0]
        assert 'float(a) != float(b)' in block

    def test_the_first_save_still_warns(self):
        """presave 가 비어 있는 것은 "안 바뀌었다" 가 아니라 "비교할 것이
        없다" 다. 새로 만든 설정이 이미 어긋나 있으면 그때 말해야 한다."""
        code = self._code()
        assert '_fresh = not was' in code
        assert '_fresh or _touched' in code
