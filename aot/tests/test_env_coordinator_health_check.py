# coding=utf-8
"""`check_env_coordinator_health.py` 회귀 — 조용히 틀리는 두 자리를 고정한다.

이 검사기는 **판정이 틀려도 아무 에러가 안 난다.** 숫자가 그럴듯하게 나오고,
사람은 그 숫자를 보고 릴리즈 여부를 정한다. 처음 돌렸을 때 실제로 둘 다 틀렸다:

  1. 사이클 수가 액추에이터 배로 부풀고 중앙 간격이 0초로 나왔다
     — 한 사이클의 기록들이 서로 밀리초 차이인데 타임스탬프를 그대로 셌다.
  2. 정상 동작(난방+가습)을 결함 26.8% 로 보고했다
     — 인터락이 보지 않는 종류(fogger)를 상반 쌍에 넣었다.

둘 다 "그럴듯한 오답" 이라 눈으로는 안 걸린다. 그래서 여기서 고정한다.

모듈을 import 하지 않고 소스를 읽는다 — 검사기는 `start_flask_ui` 를 끌어와
DB 를 요구하므로, import 하는 순간 이 테스트가 환경에 매인다.
"""

import ast
import os
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_ROOT, 'aot', 'scripts', 'check_env_coordinator_health.py')
_CYCLE_MIXIN = os.path.join(
    _ROOT, 'aot', 'functions', 'custom_functions', 'env_coordinator_impl',
    '_cycle_mixin.py')


def _source(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _load_helpers(*names):
    """검사기에서 순수 헬퍼만 떼어 깨끗한 네임스페이스에서 돌린다."""
    src = _source(_SCRIPT)
    tree = ast.parse(src)
    ns = {'bisect': __import__('bisect')}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module([node], []), _SCRIPT, 'exec'), ns)
    missing = [n for n in names if n not in ns]
    if missing:
        raise AssertionError(f'헬퍼를 찾지 못했습니다: {missing}')
    return ns


def _frozenset_names(assign_target):
    """`X = frozenset({'a', 'b'})` 의 원소를 읽는다."""
    src = _source(_SCRIPT)
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == assign_target
                   for t in node.targets):
            continue
        call = node.value
        if isinstance(call, ast.Call) and call.args:
            arg = call.args[0]
            if isinstance(arg, (ast.Set, ast.List, ast.Tuple)):
                return {e.value for e in arg.elts if isinstance(e, ast.Constant)}
    raise AssertionError(f'{assign_target} 을 읽지 못했습니다')


class TestCycleClustering(unittest.TestCase):
    """한 사이클의 기록은 하나로 접혀야 한다."""

    def setUp(self):
        self.ns = _load_helpers('_cluster_cycles', '_cycle_index')

    def test_same_cycle_writes_collapse_to_one(self):
        base = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        stamps = []
        for cycle in range(3):
            start = base + timedelta(seconds=600 * cycle)
            # 액추에이터 8대가 밀리초 간격으로 기록한다 — 실제 로그와 같은 모양.
            stamps += [start + timedelta(milliseconds=3 * i) for i in range(8)]

        cycles = self.ns['_cluster_cycles'](sorted(stamps))

        self.assertEqual(len(cycles), 3,
                         '한 사이클의 기록 8건이 8개 사이클로 세어졌습니다')
        gaps = [(b - a).total_seconds() for a, b in zip(cycles, cycles[1:])]
        self.assertEqual(gaps, [600.0, 600.0],
                         '중앙 간격이 0초로 무너졌습니다')

    def test_a_real_gap_still_separates(self):
        base = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        stamps = [base, base + timedelta(seconds=1), base + timedelta(seconds=60)]
        self.assertEqual(len(self.ns['_cluster_cycles'](stamps)), 2)

    def test_every_write_lands_in_its_own_cycle(self):
        base = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        starts = [base + timedelta(seconds=600 * i) for i in range(3)]
        idx = self.ns['_cycle_index']
        for i, start in enumerate(starts):
            self.assertEqual(idx(starts, start + timedelta(milliseconds=7)), i)
        # 첫 사이클보다 이른 기록도 버리지 않는다(음수 인덱스 금지).
        self.assertEqual(idx(starts, base - timedelta(seconds=5)), 0)


class TestOscillationCounting(unittest.TestCase):

    def setUp(self):
        self.ns = _load_helpers('_count_reversals')

    def _series(self, values):
        base = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        return [(base + timedelta(seconds=60 * i), v) for i, v in enumerate(values)]

    def test_ripple_below_threshold_is_not_oscillation(self):
        # PWM·반올림 수준의 흔들림까지 세면 정상 제어가 떠는 것으로 보인다.
        series = self._series([50, 51, 50, 51, 50, 51])
        self.assertEqual(self.ns['_count_reversals'](series, 5.0), 0)

    def test_visible_swings_are_counted(self):
        series = self._series([0, 60, 0, 60, 0])
        self.assertEqual(self.ns['_count_reversals'](series, 5.0), 3)

    def test_a_monotonic_ramp_is_not_oscillation(self):
        self.assertEqual(
            self.ns['_count_reversals'](self._series([0, 20, 40, 60, 80]), 5.0), 0)


class TestOpposingPairMatchesTheInterlock(unittest.TestCase):
    """검사기의 상반 쌍은 **인터락이 실제로 보는 종류**와 같아야 한다.

    갈라지면 두 방향 모두 나쁘다 — 넓으면 정상 동작을 결함으로 보고하고(실제로
    겪었다), 좁으면 인터락이 놓친 조합을 검사기도 못 본다.
    """

    def _interlock_kinds(self):
        tree = ast.parse(_source(_CYCLE_MIXIN))
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == 'apply_hvac_opposition_interlock'):
                return {
                    cmp.comparators[0].value
                    for cmp in ast.walk(node)
                    if isinstance(cmp, ast.Compare)
                    and isinstance(cmp.ops[0], ast.Eq)
                    and isinstance(cmp.comparators[0], ast.Constant)
                    and isinstance(cmp.comparators[0].value, str)
                }
        raise AssertionError('apply_hvac_opposition_interlock 를 찾지 못했습니다')

    def test_same_two_kinds(self):
        checker = _frozenset_names('WARMING_KINDS') | _frozenset_names('COOLING_KINDS')
        self.assertEqual(
            checker, self._interlock_kinds(),
            '상반 쌍이 인터락과 갈라졌습니다 — 한쪽만 고치면 보고가 조용히 틀립니다')

    def test_fogger_is_not_an_opposing_kind(self):
        # VPD 를 목표로 하면 난방과 가습이 함께 도는 것이 정상이다.
        self.assertNotIn('fogger',
                         _frozenset_names('WARMING_KINDS') | _frozenset_names('COOLING_KINDS'))


class TestReasonLabelsCoverEveryCode(unittest.TestCase):
    """근거 코드를 새로 만들면 이름도 함께 붙어야 한다.

    빠뜨려도 `코드 18` 로 찍히며 돌기 때문에 화면만 보고는 모른다 — 그런데
    근거 분포는 "이 장치가 왜 안 움직였나" 에 답하는 유일한 열이다.
    """

    def test_every_reason_constant_has_a_label(self):
        from aot.functions.utils.env_control import log_channels as lc

        codes = {getattr(lc, n) for n in dir(lc) if n.startswith('REASON_')}
        labelled = set()
        for node in ast.parse(_source(_SCRIPT)).body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'REASON_LABEL'
                    for t in node.targets):
                for key in node.value.keys:
                    # 상수를 **참조**해야 한다. 숫자를 베끼면 renumber 가
                    # 조용히 오라벨을 만든다.
                    self.assertIsInstance(
                        key, ast.Attribute,
                        'REASON_LABEL 의 키는 log_channels 상수여야 합니다')
                    labelled.add(getattr(lc, key.attr))
        self.assertEqual(codes - labelled, set(),
                         '이름 없는 근거 코드가 있습니다')


if __name__ == '__main__':
    unittest.main()


class TestActivityFlags(unittest.TestCase):
    """"안 움직였다" 와 "왜 안 움직였다" 는 따로 나와야 한다.

    쿠마모토 냉방기가 24시간 전부 0% 인데 근거의 68% 가 `주작용` 이었다. 둘 다
    맞는 값이다(냉방 모드가 한 번도 없었다) — 그런데 한 줄에 나란히 찍히면
    "일하고 있다는데 0%" 라는 모순으로 읽힌다.
    """

    def setUp(self):
        from aot.functions.utils.env_control import log_channels as lc
        self.lc = lc
        src = _source(_SCRIPT)
        tree = ast.parse(src)
        ns = {'LC': lc}
        # IDLE_REASONS 선언과 헬퍼를 함께 싣는다.
        for node in tree.body:
            keep = (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'IDLE_REASONS'
                            for t in node.targets))
            if keep or (isinstance(node, ast.FunctionDef)
                        and node.name == '_activity_flags'):
                exec(compile(ast.Module([node], []), _SCRIPT, 'exec'), ns)
        self.flags = ns['_activity_flags']

    def test_zero_all_window_while_labelled_primary_is_surfaced(self):
        from collections import Counter
        out = self.flags([0.0] * 135, Counter({self.lc.REASON_PRIMARY: 92,
                                               self.lc.REASON_OPPOSING_PARKED: 20}))
        self.assertTrue(out['never_ran'])
        self.assertTrue(out['idle_while_claiming_work'],
                        '0% 인데 주작용으로 표시된 장치가 조용히 지나갔습니다')
        self.assertFalse(out['always_idle'],
                         '주작용이 섞였는데 "설명 끝" 으로 접혔습니다')

    def test_parked_all_window_is_explained_not_puzzling(self):
        from collections import Counter
        out = self.flags([0.0] * 50, Counter({self.lc.REASON_NO_GRADIENT: 50}))
        self.assertTrue(out['always_idle'])
        self.assertFalse(out['idle_while_claiming_work'],
                         '정상 사유로 쉰 장치를 볼 것으로 올렸습니다')

    def test_a_working_actuator_is_flagged_neither_way(self):
        from collections import Counter
        out = self.flags([0.0, 40.0, 0.0], Counter({self.lc.REASON_PRIMARY: 3}))
        self.assertFalse(out['never_ran'])
        self.assertFalse(out['always_idle'])
        self.assertFalse(out['idle_while_claiming_work'])


class TestFreshnessCheckSeesOutdoorSensors(unittest.TestCase):
    """실외 센서를 빠뜨리면 정작 망가진 쪽을 통째로 못 본다.

    `sensors_resolved` 에는 **실내만** 들어간다. 실외 바인딩은 `sensors_outdoor`
    라는 별도 목록이라, 앞의 것만 읽으면 실외는 검사 밖이다 — 그리고 실외는
    개구부와 안전 게이트의 **유일한** 근거다.

    실제로 그렇게 놓쳤다: 육묘장3 은 기상청(주기 300초)에 상한 120초라 실외값이
    늘 만료였고, 측창 둘이 24시간 내내 '실외 값 없음' 으로 멈춰 있었다. 바인딩은
    6채널 모두 정상이었으므로 로그만 보면 배선 문제로 읽힌다.
    """

    def _freshness_source(self):
        for node in ast.parse(_source(_SCRIPT)).body:
            if (isinstance(node, ast.FunctionDef)
                    and node.name == '_check_sensor_freshness'):
                return ast.get_source_segment(_source(_SCRIPT), node) or ''
        raise AssertionError('_check_sensor_freshness 를 찾지 못했습니다')

    def test_both_sensor_lists_are_read(self):
        src = self._freshness_source()
        for key in ('sensors_resolved', 'sensors_outdoor'):
            self.assertIn(
                f"'{key}'", src,
                f'{key} 를 읽지 않습니다 — 그 목록의 센서는 검사 밖입니다')


class TestDecisionMetricsAreNotSilentlyDisabled(unittest.TestCase):
    """`log_level_debug` 는 옵션이 아니라 **Function 행의 컬럼**이다.

    `setup_custom_options_json` 은 옵션 스키마를 순회하므로 스키마에 없는
    이름은 아무것도 채우지 않는다. `self.log_level_debug = None` 으로 두면
    영원히 None 이고, 그것을 보는 `write_cycle_metrics` 가 한 번도 안 돌아
    `env_control`(모드·편차·목표·제한인자)이 통째로 사라진다.

    실제로 그랬다 — 2026-08-27 09:54 UTC 이후 두 코디네이터가 24시간 넘게 한
    줄도 안 남겼다. 액추에이터 명령·근거는 계속 기록되므로 **화면상 아무 이상이
    없고**, 없어진 것은 "왜 그렇게 했는가" 뿐이라 그 로그를 읽으려 할 때에야
    드러난다.
    """

    def test_it_is_read_from_the_row_not_left_none(self):
        src = _source(os.path.join(
            _ROOT, 'aot', 'functions', 'custom_functions', 'env_coordinator.py'))
        code = '\n'.join(ln.split('#', 1)[0] for ln in src.splitlines())
        self.assertNotIn(
            'self.log_level_debug                = None', code,
            'log_level_debug 가 다시 None 으로 남았습니다 — 진단 기록이 죽습니다')
        self.assertIn(
            "getattr(function, 'log_level_debug'", code,
            'Function 행의 컬럼에서 읽어야 합니다 — 옵션 스키마에는 없습니다')

    def test_it_is_not_declared_as_a_custom_option(self):
        """옵션으로 되살리면 컬럼과 **같은 스위치가 둘**이 되어 갈라진다."""
        src = _source(os.path.join(
            _ROOT, 'aot', 'functions', 'custom_functions',
            'env_coordinator_impl', '_function_info.py'))
        code = '\n'.join(ln.split('#', 1)[0] for ln in src.splitlines())
        self.assertNotIn("'id': 'log_level_debug'", code)
