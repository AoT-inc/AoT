# coding=utf-8
"""워치독은 **고장**만 울려야 한다 — 의도된 정지는 아니다.

2026-08-30 영양·쿠마모토가 재배 종료일에 도달해 정상적으로 제어를 멈췄는데,
워치독이 10분마다 이렇게 찍었다:

    EnvCoordinator watchdog: no cycle for 107560s (expected 600s)
    EnvCoordinator: 29.9h outage detected — plants continued growing.
    Correct growth week via schedule_week_offset.

30시간 연속이었다. 로그만 보면 30시간째 고장 난 것으로 읽히고, 조치랍시고
생육 주차 보정을 권하는데 그것은 이 상황과 아무 상관이 없다. 정지 사유가
셋(종료일·운전 시간대 밖·액추에이터 미설정)인데 워치독이 그것을 몰랐다.

⚠ 판정자를 둘로 만들지 않는다 — `_run_cycle` 이 멈출 때 사유를 남기고
워치독은 그것을 읽기만 한다. 각자 판정하면 갈라지고, 갈라지면 느슨한 쪽이
실질 동작이 된다.
"""
import ast
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_COORD = os.path.join(_ROOT, 'aot', 'functions', 'custom_functions',
                      'env_coordinator.py')
_CYCLE = os.path.join(_ROOT, 'aot', 'functions', 'custom_functions',
                      'env_coordinator_impl', '_cycle_mixin.py')


def _src(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class TestTheWatchdogRunsAfterTheCycle(unittest.TestCase):
    """순서가 곧 정확성이다."""

    def test_watchdog_is_checked_after_run_cycle(self):
        """앞에 두면 플래그가 **직전** 사이클 것이라, 재시작 직후 한 번은
        반드시 헛울린다 — 플래그는 메모리에만 있고 `_last_cycle_ts` 는
        DB 에서 복원되기 때문이다."""
        s = _src(_COORD)
        i_run = s.index('self._run_cycle(period)')
        i_dog = s.index("'EnvCoordinator watchdog: no cycle")
        self.assertLess(i_run, i_dog,
                        '워치독이 _run_cycle 앞에 있습니다 — 재시작마다 헛울립니다')

    def test_watchdog_returns_early_when_paused(self):
        s = _src(_COORD)
        i_dog = s.index("'EnvCoordinator watchdog: no cycle")
        head = s[:i_dog]
        self.assertIn("getattr(self, '_control_paused', None)", head,
                      '의도된 정지를 확인하지 않고 경고합니다')

    def test_the_flag_is_initialised(self):
        """초기화가 없으면 첫 loop 에서 AttributeError 가 난다."""
        self.assertIn('self._control_paused', _src(_COORD))


class TestEveryIntentionalStopRecordsItsReason(unittest.TestCase):
    """`_run_cycle` 의 의도적 조기 return 은 **전부** 사유를 남겨야 한다.

    하나라도 빠뜨리면 그 정지만 고장으로 보고된다 — 조용히 어긋나는 종류다.
    """

    def _run_cycle_node(self):
        for node in ast.walk(ast.parse(_src(_CYCLE))):
            if isinstance(node, ast.FunctionDef) and node.name == '_run_cycle':
                return node
        raise AssertionError('_run_cycle 을 찾지 못했습니다')

    def test_both_gates_return_a_reason(self):
        """`schedule_ended` 는 2026-09-01 에 없앴다 — 구획이 없으면 이미
        R2(guide 범위로 계속 돈다)가 그 역할을 한다, 별도 사유가 필요 없다."""
        s = _src(_CYCLE)
        i = s.index('def _intentional_stop')
        body = s[i:s.index('\n    def ', i + 10)]
        for reason in ('no_actuators', 'outside_time_window'):
            self.assertIn("return '%s'" % reason, body,
                          '정지 사유 %r 를 남기지 않습니다' % reason)
        self.assertNotIn("return 'schedule_ended'", body,
                         '제어 종료일 사유가 되살아났다 — 구획이 정본이다')

    def test_the_normal_path_returns_none(self):
        """지우지 않으면 한 번 멈춘 코디네이터는 이후 진짜 고장에도 조용하다."""
        s = _src(_CYCLE)
        i = s.index('def _intentional_stop')
        body = s[i:s.index('\n    def ', i + 10)]
        self.assertIn('return None', body)

    def test_the_flag_is_assigned_before_the_control_body(self):
        """대입이라 정상 경로에서는 None 이 들어가 사유가 저절로 지워진다 —
        따로 지우는 줄을 두면 한쪽만 고쳤을 때 조용히 갈라진다."""
        s = _src(_CYCLE)
        i_assign = s.index('self._control_paused = self._intentional_stop()')
        i_coord = s.index('situation, self._trend_state = assess(')
        self.assertLess(i_assign, i_coord, '제어 본문 뒤에서 판정합니다')


class TestTheOtherEarlyReturnsAreClassified(unittest.TestCase):
    """제어 본문 앞의 조기 return 은 다섯이고, **셋만** 의도된 정지다.
    나머지 둘을 사유로 덮으면 진짜 고장이 조용해진다.

        no_actuators / schedule_ended / outside_time_window  → 의도된 정지(사유 남김)
        내부 센서 없음                                        → **고장**, 워치독이 울려야 한다
        안전게이트 발동                                       → 완료된 사이클, 스스로 도장을 찍는다
    """

    def test_missing_sensor_data_is_a_fault_not_a_pause(self):
        """센서가 죽어 사이클을 못 도는 것은 정확히 워치독이 잡아야 할 일이다.
        여기에 사유를 달면 그 고장이 영영 조용해진다."""
        s = _src(_CYCLE)
        i = s.index('if not internal:')
        window = s[i:i + 400]
        self.assertNotIn('_control_paused', window,
                         '센서 없음을 의도된 정지로 표시했습니다 — '
                         '진짜 고장이 조용해집니다')

    def test_the_safety_gate_path_stamps_the_cycle_itself(self):
        """안전게이트로 끝난 사이클도 **완료된 사이클**이다 — 코디네이터가
        돌았고 판단했고 명령을 내보냈다. 그래서 사유가 아니라 도장이 필요하다.
        도장이 없으면 비 오는 날 내내 워치독이 헛울린다."""
        s = _src(_CYCLE)
        i = s.index('def _write_gate_only_summary')
        body = s[i:s.index('\n    def ', i + 10)]
        self.assertIn('self._last_cycle_ts = now_ts', body,
                      '게이트 전용 요약이 사이클 도장을 안 찍습니다')
        self.assertNotIn('_control_paused', body)

    def test_exactly_two_gates_carry_a_reason(self):
        """관문을 새로 만들면 사유도 함께 남겨야 한다 — 개수로 고정한다."""
        s = _src(_CYCLE)
        i = s.index('def _intentional_stop')
        body = s[i:s.index('\n    def ', i + 10)]
        self.assertEqual(len([1 for ln in body.split('\n')
                              if ln.strip().startswith("return '")]), 2,
                         '의도된 정지의 수가 바뀌었습니다 — 새 관문이라면 '
                         '사유를 남기고 이 수를 갱신하세요')

    def test_only_one_place_decides(self):
        """판정자가 둘이면 갈라지고, 갈라지면 느슨한 쪽이 실질 동작이 된다."""
        s = _src(_CYCLE)
        self.assertEqual(s.count('def _intentional_stop'), 1)
        self.assertEqual(
            s.count('self._control_paused = self._intentional_stop()'), 1)


if __name__ == '__main__':
    unittest.main()
