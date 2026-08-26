# coding=utf-8
"""입력했는데 **안 쓰이는 값**을 사용자가 알 수 있어야 한다 (2026-08-27).

## 실측

    쿠마모토 イチゴ
      저장된 actuation_profile      'gentle'
      저장된 actuation_period_sec   1200      ← 화면에 이 값이 보인다
      실제로 쓰이는 주기            600       ← gentle 의 값

`profile != 'custom'` 이면 `_resolve_actuation()` 이 숫자 칸을 **아예 보지
않는다.** 20분마다 움직이라고 적어 뒀는데 10분마다 움직이고, 그 사실이 화면에도
로그에도 안 나왔다.

## 왜 해석 규칙을 안 고쳤나

"값이 있으면 프로파일보다 우선" 으로 바꾸면 더 나쁘다 — 프로파일을 바꾼
사용자가 옛 custom 값에 묶인다. 규칙 자체는 일관되고 문서화돼 있다
(옵션 설명에 "직접 지정일 때만" 이라고 적혀 있다).

**고칠 것은 규칙이 아니라 침묵이다.**

## 한 건이 아니라 부류다

`night_vent_basis` 도 같은 모양이라(일몰 기준이면 시각 칸이, 시각 기준이면
오프셋이 안 쓰인다) 명부(`_INERT_UNLESS`)로 둔다. 조건부 옵션을 새로 만들면
거기 등록해야 한다.

## 두 곳이 말한다 — 나누는 근거가 다르다

    저장 화면   지금 만든 상태를 그 자리에서 (`execute_at_modification`)
    데몬 로그   **이미 그런 설치**를 기동 때 한 번 (아무도 안 알려 준다)
"""
import sys
import types

import pytest


def _fi():
    if 'flask_babel' not in sys.modules:
        b = types.ModuleType('flask_babel')
        b.lazy_gettext = lambda s: s
        b.gettext = lambda s, **k: (s % k) if k else s
        sys.modules['flask_babel'] = b
    from aot.functions.custom_functions.env_coordinator_impl import (
        _function_info as fi)
    return fi


def _inert(values):
    return _fi().inert_options(values)


class TestTheMeasuredCase:
    """쿠마모토가 실제로 있던 상태."""

    def test_gentle_profile_makes_the_custom_seconds_inert(self):
        got = _inert({'actuation_profile': 'gentle',
                      'actuation_period_sec': 1200.0})
        assert got == [('actuation_period_sec', 'actuation_profile', 'custom')]

    def test_custom_profile_uses_it(self):
        """영양은 profile='custom' 이라 1200 이 실제로 쓰인다 — 알릴 일이 없다."""
        assert _inert({'actuation_profile': 'custom',
                       'actuation_period_sec': 1200.0}) == []


class TestItDoesNotNag:
    """알림이 잦으면 아무도 안 읽는다."""

    def test_an_untouched_default_is_not_reported(self):
        """사용자가 정한 적 없는 값이 안 쓰이는 것은 알릴 일이 아니다."""
        assert _inert({'actuation_profile': 'gentle',
                       'actuation_period_sec': 0.0}) == []

    def test_a_missing_key_is_not_reported(self):
        assert _inert({'actuation_profile': 'gentle'}) == []

    def test_a_switched_off_feature_is_not_reported(self):
        """야간 파킹을 안 쓰는 사람에게 그 하위 설정 얘기를 하지 않는다 —
        토글이 꺼져 있는 것은 눈에 보이는 사실이다."""
        assert _inert({'night_vent_park': False,
                       'night_vent_basis': 'sun',
                       'night_vent_start': '19:00'}) == []


class TestTheWholeFamily:
    """`night_vent_basis` 도 같은 모양이다 — 한 건만 고치면 나머지가 남는다."""

    def test_sun_basis_makes_the_clock_times_inert(self):
        got = dict((o, c) for o, c, _n in _inert({
            'night_vent_park': True, 'night_vent_basis': 'sun',
            'night_vent_start': '19:00', 'night_vent_end': '05:00'}))
        assert 'night_vent_start' in got and 'night_vent_end' in got

    def test_clock_basis_makes_the_sunset_offset_inert(self):
        got = [o for o, _c, _n in _inert({
            'night_vent_park': True, 'night_vent_basis': 'clock',
            'night_vent_sunset_offset_min': 30.0})]
        assert got == ['night_vent_sunset_offset_min']

    def test_none_valued_attributes_do_not_crash(self):
        """데몬은 저장된 dict 가 아니라 **파싱된 속성**을 넘긴다 — 설정 안 된
        옵션은 None 이다."""
        assert _inert({'actuation_profile': 'gentle',
                       'actuation_period_sec': 1200.0,
                       'night_vent_park': None, 'night_vent_basis': None,
                       'night_vent_start': None}) == [
            ('actuation_period_sec', 'actuation_profile', 'custom')]


class TestTheRosterMatchesTheCode:
    """명부에 적힌 조건이 실제 해석 규칙과 같아야 한다.

    갈라지면 화면은 "쓰인다" 고 하는데 코드는 안 쓰거나, 그 반대가 된다.
    """

    def _read(self, *parts):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, '..', *parts), encoding='utf-8') as fh:
            return fh.read()

    def test_every_roster_entry_names_real_options(self):
        fi = _fi()
        ids = {o['id'] for o in fi.FUNCTION_INFORMATION['custom_options']
               if o.get('id')}
        for opt, cond, _need, gate in fi._INERT_UNLESS:
            for name in (opt, cond, gate):
                if name is not None:
                    assert name in ids, '%r 은 옵션 명부에 없다' % name

    def test_the_actuation_condition_matches_the_resolver(self):
        src = self._read('functions', 'custom_functions',
                         'env_coordinator_impl', '_helpers_mixin.py')
        assert "profile == 'custom'" in src, (
            "해석 규칙이 바뀌었다 — `_INERT_UNLESS` 의 'custom' 도 함께 볼 것")

    def test_the_night_basis_condition_matches_the_resolver(self):
        src = self._read('functions', 'custom_functions',
                         'env_coordinator_impl', '_helpers_mixin.py')
        block = src.split('def _night_vent_parked', 1)[1].split('\n    def ', 1)[0]
        assert "basis == 'clock'" in block, (
            "해석 규칙이 바뀌었다 — `_INERT_UNLESS` 의 'clock'/'sun' 도 함께 볼 것")


class TestBothSurfacesReport:
    """저장 화면과 데몬 로그가 **둘 다** 있어야 한다.

    저장 화면만 있으면 이미 그런 상태인 설치는 영영 모르고,
    데몬 로그만 있으면 사용자가 로그를 볼 때까지 모른다.
    """

    def _read(self, *parts):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, '..', *parts), encoding='utf-8') as fh:
            return fh.read()

    def test_the_save_hook_reports_it(self):
        src = self._read('functions', 'custom_functions', 'env_coordinator.py')
        assert 'inert_options' in src

    def _impl_sources(self):
        """구현이 어느 mixin 에 있든 찾는다 — 파일을 옮겼다는 이유로 이 검사가
        깨지면, 진짜 회귀와 구분이 안 된다."""
        import glob
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        pat = os.path.join(here, '..', 'functions', 'custom_functions',
                           'env_coordinator_impl', '*.py')
        out = {}
        for path in glob.glob(pat):
            with open(path, encoding='utf-8') as fh:
                out[os.path.basename(path)] = fh.read()
        return out

    def test_the_daemon_reports_it_once(self):
        """매 사이클 찍으면 정작 읽어야 할 로그를 밀어낸다."""
        srcs = self._impl_sources()
        assert any('inert_options' in s for s in srcs.values())
        assert any('_inert_logged' in s for s in srcs.values()), (
            '한 번만 찍는 장치가 없다')

    def test_the_daemon_uses_error_level(self):
        """컨트롤러 로거는 `log_level_debug` 가 꺼져 있으면 ERROR 다 —
        warning 으로 찍으면 기본 설치에서 아무 데도 안 남는다."""
        blocks = [s.split('_inert_logged', 1)[1][:1200]
                  for s in self._impl_sources().values() if '_inert_logged' in s]
        assert blocks and any('self.logger.error(' in b for b in blocks)

    def test_the_cycle_only_calls_it(self):
        """`_run_cycle` 에 인라인으로 붙이면 그 함수가 다시 길어진다 —
        `test_run_cycle_stays_readable` 이 실제로 그것을 잡았다(491줄)."""
        cyc = self._impl_sources()['_cycle_mixin.py']
        assert '_warn_inert_options_once()' in cyc
        assert 'inert_options(saved)' not in cyc, '구현이 사이클에 인라인돼 있다'


def test_the_message_has_no_double_quote():
    """⚠ msgid 의 큰따옴표는 `.po` 의 문자열 구분자다 — 이스케이프 없이 넣으면
    그 카탈로그가 통째로 깨진다(2026-08-27 실제로 두 언어를 깨뜨렸다)."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, '..', 'functions', 'custom_functions',
                           'env_coordinator.py'), encoding='utf-8') as fh:
        src = fh.read()
    body = src.split('def execute_at_modification', 1)[1].split('\nFUNCTION_', 1)[0]
    for line in body.splitlines():
        code = line.split('#', 1)[0]
        if 'gettext(' in code or (code.strip().startswith("'")
                                  and '%(' in code):
            assert '\\"' not in code and '"' not in code.strip("'"), (
                'msgid 에 큰따옴표가 있다: %s' % line.strip())


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
