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


class TestGateOnlySilenceIsNotMistakenForStalling(unittest.TestCase):
    """게이트로만 남은 사이클도 "돌고 있다" 로 세어야 한다.

    강우·돌풍 같은 안전 게이트가 걸리면 `_cycle_mixin.py` 가 L1~L3 전에
    조기 반환해 `coord_actuator_*` 를 한 줄도 안 쓴다(`safety_gate_active`
    만 쓴다). 그런데 이 검사기는 `cmd_by_act`(= `coord_actuator_*_command`)
    만으로 `stamps`(사이클 리듬)를 계산했다 — 그래서 강우가 몇 시간 이어지면
    코디네이터가 **실제로는 매 사이클 정상 실행 중**인데도 "결정 로그가
    없다"(cycles=0, "이 창에서 한 사이클도 돌지 않았습니다")로 보였다.

    실측: 2026-09-03 쿠마모토가 강우 게이트로 5시간째였고, 이 검사기와 데몬
    로그만 보면 "코디네이터가 멈췄다"와 구분되지 않았다 — 실시간 상태
    (`get_control_state`)를 따로 찍어 보고서야 정상임을 확인했다.
    """

    def test_gate_events_feed_the_cycle_stamps(self):
        src = _source(_SCRIPT)
        self.assertIn('gate_stamps = sorted(ts for ts, _ in gate_events)', src)
        self.assertIn('_cluster_cycles(cmd_stamps + gate_stamps)', src,
                      'safety_gate_active 타임스탬프가 사이클 리듬 계산에 '
                      '안 들어가면 게이트만 걸린 시간대가 "공백"으로 보인다')

    def test_gate_only_cycles_are_reported_separately(self):
        """포함은 시키되, "게이트로만 존재했다"는 사실은 숨기지 않는다.

        합쳐서 세기만 하면 "5시간째 게이트로 쉬는 중"과 "정상적으로 5시간
        잘 돌았다"가 숫자만 봐서는 다시 구분되지 않는다."""
        src = _source(_SCRIPT)
        self.assertIn("'gate_only_cycles'", src)
        self.assertIn('게이트로만', src)

    def test_gate_only_heartbeats_stay_distinct_cycles(self):
        """게이트 사이클 3회(10분 간격, 명령 기록 없음)가 뭉개지지 않는다.

        `_cluster_cycles` 자체는 이번에 안 고쳤지만, 이 검사기가 그 함수에
        기대는 성질이 정확히 이것이다 — 뭉개지면 "5시간째 게이트" 도
        "방금 한 번 걸림"과 구분되지 않는다."""
        ns = _load_helpers('_cluster_cycles')
        base = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
        gate_stamps = [base + timedelta(minutes=10 * i) for i in range(3)]
        cycles = ns['_cluster_cycles'](gate_stamps)
        self.assertEqual(len(cycles), 3,
                         '게이트 사이클 3회가 뭉개지거나 사라졌습니다')

    def test_gate_only_cycles_after_normal_ones_extend_the_last_seen_time(self):
        """정상 사이클 2회 뒤 게이트 사이클 3회 — `last` 는 게이트 쪽으로 가야 한다.

        cmd 만 봤을 때는 정상 사이클이 끝난 시각에 멈춰, 그 뒤로 몇 시간
        게이트가 이어져도 "마지막으로 본 시각"이 과거에 고정된다."""
        ns = _load_helpers('_cluster_cycles')
        base = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
        cmd_stamps = [base, base + timedelta(minutes=10)]
        gate_stamps = [base + timedelta(minutes=20 * i) for i in range(2, 5)]
        combined = ns['_cluster_cycles'](sorted(cmd_stamps + gate_stamps))
        self.assertEqual(len(combined), 5,
                         'cmd 사이클과 게이트 사이클이 합쳐지지 않고 그대로 '
                         '다섯 개여야 합니다')
        self.assertEqual(combined[-1], gate_stamps[-1],
                         '마지막 사이클이 게이트 쪽 최신 시각을 반영해야 합니다')


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


class TestNightDewFrostExposure(unittest.TestCase):
    """밤 이슬 분·서리 분(2026-10-12) — 시설 몫의 노출이라 결함 카운트(`problems`)에 섞지 않고 권고만 낸다."""

    @classmethod
    def setUpClass(cls):
        from aot.functions.utils.env_control import humid_regime as HR
        ns = {'HR': HR}
        tree = ast.parse(_source(_SCRIPT))
        const_names = {'NIGHT_DEW_RH_PCT', 'NIGHT_DEW_MARGIN_C', 'EXPOSURE_STEP_S', 'EXPOSURE_DEW_MIN',
                       'EXPOSURE_DEW_SHARE', 'EXPOSURE_FROST_MIN', 'EXPOSURE_FROST_PROTECT_MIN'}
        fn_names = {'_bucket_means', '_merge_sensors', '_exposure_summary', '_exposure_advice'}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id in const_names for t in node.targets):
                exec(compile(ast.Module([node], []), _SCRIPT, 'exec'), ns)
            elif isinstance(node, ast.FunctionDef) and node.name in fn_names:
                exec(compile(ast.Module([node], []), _SCRIPT, 'exec'), ns)
        cls.ns = ns
        cls.summary = staticmethod(ns['_exposure_summary'])
        cls.advice = staticmethod(ns['_exposure_advice'])
        cls.merge = staticmethod(ns['_merge_sensors'])

    @staticmethod
    def _series(values, t0=0.0, step=300.0):
        return [(t0 + i * step, float(v)) for i, v in enumerate(values)]

    def test_no_overlap_is_none_not_zero(self):
        self.assertIsNone(self.summary([], [], lambda t: True))
        self.assertIsNone(self.summary([self._series([20.0])], [], lambda t: True))
        # 온도와 습도가 서로 다른 시각에만 있으면 겹치는 격자가 없다
        self.assertIsNone(self.summary([self._series([20.0], t0=0.0)],
                                       [self._series([99.0], t0=10_000.0)], lambda t: True))

    def test_night_dew_counts_high_rh_or_small_margin(self):
        # 20 °C·RH 96 → 밤 이슬(RH ≥ 95) / 20 °C·RH 80 → 여유 3.6 °C(아님) /
        # 30 °C·RH 94 → 여유 1.07 °C(아님 — 문턱 1 °C 바로 위) / 30 °C·RH 97 → 여유 0.6 °C(밤 이슬)
        t = self._series([20.0] * 3 + [20.0] * 3 + [30.0] * 3 + [30.0] * 3)
        rh = self._series([96.0] * 3 + [80.0] * 3 + [94.0] * 3 + [97.0] * 3)
        out = self.summary([t], [rh], lambda e: True)
        self.assertEqual(out['night_min'], 12 * 5.0)
        self.assertEqual(out['night_dew_min'], 6 * 5.0)
        self.assertTrue(out['night_known'])

    def test_daytime_does_not_count_as_night_dew(self):
        t = self._series([20.0] * 6)
        rh = self._series([99.0] * 6)
        out = self.summary([t], [rh], lambda e: False)
        self.assertEqual((out['night_min'], out['night_dew_min']), (0.0, 0.0))
        self.assertTrue(out['night_known'])

    def test_unknown_night_is_not_zero_dew(self):
        """좌표를 몰라 밤을 못 가르면 0 이 아니라 '못 셈' 이다."""
        t = self._series([20.0] * 6)
        rh = self._series([99.0] * 6)
        out = self.summary([t], [rh], lambda e: None)
        self.assertFalse(out['night_known'])
        self.assertEqual(out['night_dew_min'], 0.0)

    def test_frost_minutes_ignore_day_and_night(self):
        t = self._series([3.0, 0.0, -1.0, -2.5, 0.5, 4.0])
        rh = self._series([90.0] * 6)
        out = self.summary([t], [rh], lambda e: False)
        self.assertEqual(out['frost_min'], 3 * 5.0)             # 0.0 도 서리(≤ 0)
        self.assertEqual(out['indoor_T_min'], -2.5)

    def test_sensors_are_averaged_not_summed(self):
        a = self._series([10.0, 10.0])
        b = self._series([20.0, 20.0])
        out = self.merge([a, b], 300.0)
        self.assertEqual(list(out.values()), [15.0, 15.0])

    def test_a_sensor_with_many_samples_does_not_outvote_a_sparse_one(self):
        dense = [(i * 60.0, 10.0) for i in range(5)]            # 같은 5 분 격자에 5 표본
        sparse = [(0.0, 20.0)]
        out = self.merge([dense, sparse], 300.0)
        self.assertEqual(out[0.0], 15.0)

    def test_non_numeric_samples_are_skipped(self):
        out = self.merge([[(0.0, 'x'), (60.0, None), (120.0, float('nan')), (180.0, 12.0)]], 300.0)
        self.assertEqual(out, {0.0: 12.0})

    def test_big_night_dew_recommends_dehumidifier_curtain_heating(self):
        summ = {'night_min': 600.0, 'night_dew_min': 400.0, 'frost_min': 0.0,
                'indoor_T_min': 18.0, 'night_known': True, 'covered_min': 1440.0}
        lines = self.advice(summ, {'opening', 'fogger'})
        self.assertEqual(len(lines), 1)
        self.assertIn('제습기·보온커튼·난방 검토', lines[0])
        self.assertIn('순환팬이 없습니다', lines[0])             # 순환팬이 없으면 그 말도 한다
        with_fan = self.advice(summ, {'opening', 'circulation_fan'})
        self.assertNotIn('순환팬이 없습니다', with_fan[0])

    def test_small_or_short_dew_is_quiet(self):
        base = {'night_min': 600.0, 'frost_min': 0.0, 'indoor_T_min': 18.0,
                'night_known': True, 'covered_min': 1440.0}
        self.assertEqual(self.advice({**base, 'night_dew_min': 30.0}, set()), [])        # 60 분 미만
        self.assertEqual(self.advice({**base, 'night_dew_min': 100.0}, set()), [])       # 밤의 25 % 미만
        self.assertEqual(self.advice(None, set()), [])

    def test_frost_recommendation_mentions_missing_heater(self):
        summ = {'night_min': 600.0, 'night_dew_min': 0.0, 'frost_min': 40.0,
                'indoor_T_min': -2.0, 'night_known': True, 'covered_min': 1440.0}
        lines = self.advice(summ, {'curtain'}, {'protect_min': 90.0})
        self.assertEqual(len(lines), 1)
        self.assertIn('보온커튼·난방 검토', lines[0])
        self.assertIn('서리 보호 90분', lines[0])
        self.assertIn('난방기가 없어', lines[0])
        self.assertNotIn('난방기가 없어', self.advice(summ, {'heater'})[0])

    def test_frost_protect_alone_triggers_even_if_sensors_saw_no_frost(self):
        summ = {'night_min': 600.0, 'night_dew_min': 0.0, 'frost_min': 0.0,
                'indoor_T_min': 3.0, 'night_known': True, 'covered_min': 1440.0}
        self.assertEqual(self.advice(summ, {'heater'}, {'protect_min': 30.0}), [])
        self.assertEqual(len(self.advice(summ, {'heater'}, {'protect_min': 60.0})), 1)

    def test_exposure_is_a_facility_note_not_a_defect_count(self):
        """권고는 `problems` 를 올리지 않는다 — 시설 몫이라 종료 코드를 바꾸지 않는다."""
        src = _source(_SCRIPT)
        i = src.index("ex = r.get('exposure')")
        j = src.index("sp = r.get('suspected')")
        block = src[i:j]
        self.assertNotIn('problems', block)
        self.assertIn("r.get('exposure_advice')", block)
        self.assertNotIn("r.get('exposure')", src[src.index('return 1 if any('):])

    def test_reason_59_is_labelled(self):
        from aot.functions.utils.env_control import log_channels as lc
        self.assertEqual(lc.REASON_NIGHT_DEW_FAN, 59)


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


class TestReportsWhatRanNotWhatWasAsked(unittest.TestCase):
    """검사기는 **실제로 나간 값**을 보고해야 한다.

    2026-08-30 영양·쿠마모토 점검이 정확히 여기서 틀렸다. 검사기가
    `coord_actuator_*_command`(CH40, coordinate() 안에서 기록 = 게이트 이전)만
    읽어 "밸브: 영양 평균 23% · 최대 100% 작동 중"이라고 보고했는데, 실제
    출력 기록으로는 **이틀간 한 번도 나가지 않았다**. 분무 게이트가 98%
    잠겨 요청이 전부 버려지고 있었다.

    요청과 최종을 둘 다 읽고, 그 차이를 세고, 최종을 기준으로 통계를 내는
    것 — 세 가지가 함께 있어야 이 오보가 재발하지 않는다.
    """

    def test_the_analyser_reads_the_final_channel(self):
        src = _source(_SCRIPT)
        self.assertIn("endswith('_final')", src,
                      '최종값(CH100 계열)을 읽지 않으면 요청값을 작동으로 오독한다')
        self.assertIn('final_by_act', src)

    def test_final_reason_is_matched_before_plain_reason(self):
        """`_final_reason` 은 `_reason` 으로도 끝난다 — 긴 접미사를 먼저 보지
        않으면 최종 근거가 요청 근거 통계에 섞여 들어간다(무에러)."""
        src = _source(_SCRIPT)
        i_final = src.index("endswith('_final_reason')")
        i_plain = src.index("endswith('_reason')", i_final + 1)
        self.assertLess(i_final, i_plain,
                        "'_final_reason' 분기가 '_reason' 보다 뒤에 있으면 "
                        "영원히 도달하지 못한다")

    def test_statistics_prefer_final_over_requested(self):
        src = _source(_SCRIPT)
        self.assertIn('samples = final or requested', src,
                      '통계 기준이 최종값이 아니면 이 사고가 그대로 재발한다')

    def test_falling_back_to_requested_is_announced(self):
        """최종값이 없는 옛 구간은 요청값으로 보이되 **그 사실을 말해야** 한다.
        조용히 폴백하면 옛 데이터와 새 데이터가 같은 뜻으로 보인다."""
        src = _source(_SCRIPT)
        self.assertIn("'source'", src)
        self.assertIn('실제 작동이 아닙니다', src)

    def test_suppressed_cycles_are_counted_and_reported(self):
        src = _source(_SCRIPT)
        self.assertIn('def _count_suppressed', src)
        self.assertIn('게이트·감쇠·인터록을 확인하세요', src,
                      '요청이 버려진 사실을 화면이 말하지 않으면 사람은 '
                      '코디네이터를 들여다보며 시간을 쓴다')

    def test_count_suppressed_flags_a_blocked_request(self):
        """요청 23% → 최종 0% = 버려진 사이클 1건."""
        ns = _load_helpers('_count_suppressed', '_suppressed_pairs')
        t0 = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)
        requested = [(t0, 23.0)]
        final = [(t0 + timedelta(seconds=1), 0.0)]
        self.assertEqual(ns['_count_suppressed'](requested, final), 1)

    def test_count_suppressed_ignores_an_honoured_request(self):
        ns = _load_helpers('_count_suppressed', '_suppressed_pairs')
        t0 = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(
            ns['_count_suppressed']([(t0, 23.0)],
                                    [(t0 + timedelta(seconds=1), 23.0)]), 0)

    def test_count_suppressed_ignores_a_zero_request(self):
        """애초에 0 을 요청했으면 버려진 것이 아니다."""
        ns = _load_helpers('_count_suppressed', '_suppressed_pairs')
        t0 = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(
            ns['_count_suppressed']([(t0, 0.0)],
                                    [(t0 + timedelta(seconds=1), 0.0)]), 0)

    def test_count_suppressed_does_not_pair_across_cycles(self):
        """다음 사이클의 최종값을 이번 요청의 짝으로 삼으면 안 된다."""
        ns = _load_helpers('_count_suppressed', '_suppressed_pairs')
        t0 = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(
            ns['_count_suppressed']([(t0, 23.0)],
                                    [(t0 + timedelta(minutes=10), 0.0)]), 0)


class TestGuardedSuppressionIsNotAlarm(unittest.TestCase):
    """보호 장치가 설계대로 막은 요청은 "게이트에 버려졌다" 가 아니다 (2026-09-30).

    로컬 3포장 분무는 육묘 일소 방지 잠금으로 107번 막혔는데 검사기는 그것을
    고장처럼 보고했다. 그런 경고가 늘 뜨면 정말 버려진 요청이 묻힌다.
    """

    def setUp(self):
        from aot.functions.utils.env_control import log_channels as lc
        self.lc = lc
        self.ns = _load_helpers('_split_suppressed')
        self.t0 = datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)

    def _split(self, pairs, final_reasons):
        guard = {self.lc.REASON_SAFETY_PRE_GATE, self.lc.REASON_LIMIT_HUMID_MAX}
        return self.ns['_split_suppressed'](pairs, final_reasons, guard)

    def test_guard_reason_marks_the_cycle_as_explained(self):
        guarded, unexplained = self._split(
            [(self.t0, 60.0)],
            [(self.t0 + timedelta(seconds=1), self.lc.REASON_SAFETY_PRE_GATE)])
        self.assertEqual(dict(guarded), {self.lc.REASON_SAFETY_PRE_GATE: 1})
        self.assertEqual(unexplained, [])

    def test_a_primary_final_reason_stays_unexplained(self):
        """최종 근거가 코디네이터 자신의 것이면 어느 보호도 막지 않았다."""
        guarded, unexplained = self._split(
            [(self.t0, 60.0)],
            [(self.t0, self.lc.REASON_PRIMARY)])
        self.assertEqual(sum(guarded.values()), 0)
        self.assertEqual(unexplained, [(self.t0, 60.0)])

    def test_missing_final_reason_is_never_folded_into_normal(self):
        """옛 구간처럼 근거 기록이 없으면 **모르는 것**이다 — 정상으로 접지 않는다."""
        guarded, unexplained = self._split([(self.t0, 60.0)], [])
        self.assertEqual(sum(guarded.values()), 0)
        self.assertEqual(len(unexplained), 1)

    def test_a_far_away_reason_is_not_paired(self):
        _g, unexplained = self._split(
            [(self.t0, 60.0)],
            [(self.t0 + timedelta(minutes=10), self.lc.REASON_SAFETY_PRE_GATE)])
        self.assertEqual(len(unexplained), 1)

    def test_screens_are_not_counted_as_suppressed(self):
        """스크린의 최종 0 은 닫힘이라는 위치다 — 요청 12% → 0% 는 정상 스냅이다."""
        src = _source(_SCRIPT)
        self.assertIn('SCREEN_KINDS', src)
        self.assertIn('if kind in SCREEN_KINDS', src)

    def test_guard_reasons_are_referenced_by_constant(self):
        """숫자를 베껴 적으면 renumber 가 조용히 오라벨을 만든다."""
        src = _source(_SCRIPT)
        self.assertIn('LC.REASON_SAFETY_PRE_GATE', src)
        self.assertIn('LC.REASON_LIMIT_HUMID_MAX', src)


class TestMostlyGuardedIsNotPuzzling(TestActivityFlags):
    def test_guard_dominated_window_is_not_puzzling(self):
        """습도 상한 46 · 안전 강제 43 · 주작용 11 % — 89 % 는 이미 설명됐다."""
        from collections import Counter
        out = self.flags([0.0] * 100, Counter({
            self.lc.REASON_LIMIT_HUMID_MAX: 46,
            self.lc.REASON_SAFETY_PRE_GATE: 43,
            self.lc.REASON_PRIMARY: 11}))
        self.assertTrue(out['never_ran'])
        self.assertFalse(out['idle_while_claiming_work'])

    def test_majority_primary_is_still_puzzling(self):
        from collections import Counter
        out = self.flags([0.0] * 100, Counter({
            self.lc.REASON_PRIMARY: 68, self.lc.REASON_IDLE: 32}))
        self.assertTrue(out['idle_while_claiming_work'])


class TestFinalCommandsAreActuallyLogged(unittest.TestCase):
    """기록이 없으면 위 검사는 영원히 요청값 폴백으로 돈다."""

    @staticmethod
    def _run_cycle_src():
        """`_run_cycle` 본문만 — 게이트 사이클의 기록(`_write_gate_final_commands`,
        2026-10-10)도 같은 함수를 부르므로 파일 전체에서 첫 출현을 찾으면 그쪽을 본다."""
        src = _source(_CYCLE_MIXIN)
        i = src.index('    def _run_cycle(')
        j = src.index('\n    def ', i + 1)
        return src[i:j]

    def test_the_cycle_logs_final_commands_after_the_overrides(self):
        src = self._run_cycle_src()
        i_override = src.index('apply_threshold_and_gate_overrides(\n')
        i_write = src.index('write_final_commands(')
        self.assertLess(
            i_override, i_write,
            '오버라이드보다 먼저 기록하면 그 값은 최종값이 아니다 — '
            'CH40 과 똑같아져 이 채널의 존재 이유가 사라진다')

    def test_final_logging_is_not_behind_the_debug_flag(self):
        """`write_cycle_metrics` 와 달리 이 기록은 디버그 로깅과 무관해야 한다.
        장치가 왜 안 돌았는지는 기본 설치에서도 답할 수 있어야 한다."""
        src = self._run_cycle_src()
        i_write = src.index('write_final_commands(')
        # 디버그 분기(`if getattr(self, 'log_level_debug', False):`) 안이면
        # 한 단계 더 들여써져 12칸이 된다. 메서드 본문 직속은 8칸이다.
        line_start = src.rindex('\n', 0, i_write) + 1
        line = src[line_start:i_write]
        self.assertEqual(len(line) - len(line.lstrip()), 8,
                         '디버그 분기 안으로 들어가 있습니다 — 기본 설치에서 '
                         '최종 명령 기록이 통째로 사라집니다')


    def test_gate_cycles_log_final_commands_too(self):
        """게이트가 선 사이클도 최종 명령을 남긴다(2026-10-10 구마모토 — 강우 게이트
        5시간 동안 CH100+ 가 통째로 비어 그 시각의 창을 로그로 설명할 수 없었다)."""
        src = _source(_CYCLE_MIXIN)
        i = src.index('    def _act_on_triggered_gate(')
        j = src.index('\n    def ', i + 1)
        self.assertIn('self._write_gate_final_commands(', src[i:j])
        k = src.index('    def _write_gate_final_commands(')
        body = src[k:src.index('\n    def ', k + 1)]
        self.assertIn('write_final_commands(', body)
        self.assertNotIn('log_level_debug', body)


class TestShadowAliveCheck(unittest.TestCase):
    """그림자가 켜져 있는데 **기록이 없으면** 말하는가 (2026-09-28).

    2026-08-04 리팩터가 사이클 길이를 넘기지 않아 그림자 단계가 매 사이클
    NameError 로 죽었는데, 예외가 debug 로 삼켜져 8주 동안 아무도 몰랐다. 그동안
    예측·학습·검증 기록이 통째로 비어 물리 제어로 전환할 근거가 쌓일 수 없었다.
    화면도 로그도 조용했다 — **기록이 없다는 사실**만이 유일한 신호였다.
    """

    def _check(self, engine, records, cycles=100):
        from aot.scripts.check_env_coordinator_health import _check_shadow_alive
        return _check_shadow_alive({'effect_engine': engine}, records, cycles)

    def test_예측_기록이_없으면_말한다(self):
        got = self._check('shadow', {6: 50, 8: 50})      # MPC 그림자만 있다
        self.assertEqual(1, len(got))
        self.assertEqual('error', got[0][0])
        self.assertIn('1스텝 예측 기록', got[0][1])

    def test_아무_기록도_없으면_말한다(self):
        got = self._check('greybox', {})
        self.assertEqual(1, len(got))
        self.assertIn('한 건도 없습니다', got[0][1])

    def test_기록이_있으면_조용하다(self):
        self.assertEqual([], self._check('shadow', {0: 30, 2: 30, 6: 30}))

    def test_legacy_는_대상이_아니다(self):
        """그림자를 안 켰으면 기록이 없는 것이 정상이다 — 잡음을 만들지 않는다."""
        self.assertEqual([], self._check('legacy', {}))

    def test_사이클이_없으면_판정하지_않는다(self):
        """멈춰 있던 코디네이터는 다른 항목(사이클 리듬)이 이미 말한다."""
        self.assertEqual([], self._check('shadow', {}, cycles=0))

    def test_분석_결과에_그림자_기록_수가_실린다(self):
        """사람이 숫자를 직접 볼 수 있어야 한다 — 판정만 주면 확인할 방법이 없다."""
        src = _source(_SCRIPT)
        self.assertIn("'greybox_records'", src)
        self.assertIn("_check_shadow_alive(", src)


class TestHeatProtectSummary(unittest.TestCase):
    """극한 고온 보호(CH75·76) 요약 — 활성 분·단계 전환·플래그."""

    def setUp(self):
        self.fn = _load_helpers('_heat_protect_summary')['_heat_protect_summary']
        self.t0 = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)
        self.labels = [(1, '환기 가능'), (2, '바깥이 더 더움'), (64, '차광 전개')]

    def _series(self, values, step=60):
        return [(self.t0 + timedelta(seconds=i * step), float(v))
                for i, v in enumerate(values)]

    def test_no_records_is_not_zero(self):
        """기록이 없는 것과 보호가 0 분이었던 것은 다르다."""
        self.assertIsNone(self.fn([], [], self.labels, 24))

    def test_active_minutes_and_transitions(self):
        tiers = self._series([0] * 10 + [1] * 30 + [2] * 5 + [1] * 5 + [0] * 10)
        out = self.fn(tiers, [], self.labels, 1)
        self.assertAlmostEqual(out['active_min'], 40.0)
        self.assertAlmostEqual(out['tier2_min'], 5.0)
        self.assertEqual(out['transitions'], 4)          # 0→1, 1→2, 2→1, 1→0
        self.assertEqual([(a, b) for _t, a, b in out['transition_times']],
                         [(0, 1), (1, 2), (2, 1), (1, 0)])

    def test_a_missing_stretch_is_not_counted_as_protection(self):
        """사이클이 빠진 공백(재시작)은 보호 중으로 부풀리지 않는다."""
        tiers = self._series([1] * 5)
        tiers.append((tiers[-1][0] + timedelta(hours=3), 1.0))
        out = self.fn(tiers, [], self.labels, 4)
        self.assertLess(out['active_min'], 10.0)

    def test_flags_are_counted_by_label(self):
        flags = self._series([1 | 64, 2 | 64, 2])
        out = self.fn(self._series([1, 1, 1]), flags, self.labels, 1)
        self.assertEqual(out['flags'], {'환기 가능': 1, '바깥이 더 더움': 2,
                                        '차광 전개': 2})

    def test_flag_labels_reference_the_module_constants(self):
        src = _source(_SCRIPT)
        self.assertIn('HP.HP_FLAG_HOT_OUTSIDE', src)
        self.assertIn("measurement == 'heat_protect_tier'", src)


class TestSensorStatusSummary(unittest.TestCase):
    """센서 상태(CH80~91)를 접는 헬퍼 — 기록 없음을 0 으로 말하지 않는다."""

    @classmethod
    def setUpClass(cls):
        from collections import Counter
        from aot.functions.utils.env_control import log_channels as LC
        from aot.utils import sensor_status as SS
        src = _source(_SCRIPT)
        env = {'LC': LC, 'SS': SS, 'Counter': Counter,
               'STATUS_NAME': {c: n for n, c in SS.STATUS_CODES.items()},
               'VPD_SOURCE_NAME': {c: n for n, c in SS.VPD_SOURCE_CODES.items()}}
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name == '_summarize_sensor_status':
                exec(compile(ast.Module([node], []), _SCRIPT, 'exec'), env)
        cls.fn = staticmethod(env['_summarize_sensor_status'])
        cls.LC, cls.SS = LC, SS

    def _series(self, values):
        t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
        return [(t0 + timedelta(minutes=i), float(v)) for i, v in enumerate(values)]

    def test_기록이_없으면_None_이다(self):
        self.assertIsNone(self.fn({}))

    def test_valid_만_있는_축은_조용하다(self):
        by = {self.LC.ch_sensor_status('T'): self._series([0, 0, 0])}
        out = self.fn(by)
        self.assertEqual(out['axes'], {})
        self.assertEqual(out['records'], 3)

    def test_범위밖은_따로_센다(self):
        by = {self.LC.ch_sensor_status('RH'): self._series([0, 4, 4, 1]),
              self.LC.CH_VPD_SOURCE: self._series([1, 1, 2, 1]),
              self.LC.CH_VPD_DEVICE_DIFF: self._series([-0.2, -0.1])}
        out = self.fn(by)
        self.assertEqual(out['axes']['RH'], {'valid': 1, 'out_of_range': 2, 'stale': 1})
        self.assertEqual(out['out_of_range'], {'RH': 2})
        self.assertEqual(out['vpd_source'], {'computed': 3, 'device': 1})
        self.assertAlmostEqual(out['vpd_device_diff_mean'], -0.15)
        self.assertAlmostEqual(out['vpd_device_diff_max_abs'], 0.2)

    def test_멈춘_센서는_코드_5_이고_라벨은_frozen_이다(self):
        """CH80~89 의 5 는 `frozen` 으로 읽히고 out_of_range 와 따로 센다."""
        self.assertEqual(self.SS.STATUS_CODES[self.SS.FROZEN], 5)
        by = {self.LC.ch_sensor_status('T'): self._series([0, 5, 5, 5, 0]),
              self.LC.ch_sensor_status('RH'): self._series([0, 4, 5])}
        out = self.fn(by)
        self.assertEqual(out['axes']['T'], {'valid': 2, 'frozen': 3})
        self.assertEqual(out['frozen'], {'T': 3, 'RH': 1})
        self.assertEqual(out['out_of_range'], {'RH': 1})
        self.assertNotIn('코드 5', str(out['axes']))

    def test_멈춘_센서는_볼_것으로_올라간다(self):
        src = _source(_SCRIPT)
        self.assertIn("if sst['frozen']:", src)
        self.assertIn("SS.FROZEN", src)


class TestWaterAndSuspectSummaries(unittest.TestCase):
    """분무용 물 공급(CH92)·의심 액추에이터(CH93) 요약 — 분 단위, 기록 없음 ≠ 0."""

    def setUp(self):
        from aot.functions.utils.env_control import water_supply as WS
        self.ns = _load_helpers('_state_minutes', '_water_summary', '_suspect_summary')
        self.ns['WS'] = WS
        self.WS = WS
        self.t0 = datetime(2026, 7, 20, 3, 0, tzinfo=timezone.utc)

    def _series(self, values, step=60):
        return [(self.t0 + timedelta(seconds=i * step), float(v))
                for i, v in enumerate(values)]

    def test_water_without_records_is_none_not_zero(self):
        """옵션을 켜지 않은 코디네이터는 CH92 를 남기지 않는다."""
        self.assertIsNone(self.ns['_water_summary']([]))

    def test_water_minutes_by_state(self):
        ws = self.WS
        out = self.ns['_water_summary'](self._series(
            [ws.WATER_OK] * 10 + [ws.WATER_LOW] * 5 + [ws.WATER_STALE] * 3
            + [ws.WATER_OK] * 2))
        self.assertAlmostEqual(out['ok_min'], 12.0)
        self.assertAlmostEqual(out['low_min'], 5.0)
        self.assertAlmostEqual(out['stale_min'], 3.0)

    def test_a_restart_gap_is_not_counted_as_a_state(self):
        series = self._series([self.WS.WATER_LOW] * 4)
        series.append((series[-1][0] + timedelta(hours=5), float(self.WS.WATER_LOW)))
        out = self.ns['_water_summary'](series)
        self.assertLess(out['low_min'], 10.0)

    def test_no_suspect_records_means_none(self):
        """CH93 은 의심이 있을 때만 남는다 — 기록이 없다는 것이 곧 의심이 없었다는 뜻이다."""
        self.assertIsNone(self.ns['_suspect_summary']([]))

    def test_suspect_minutes_and_peak(self):
        out = self.ns['_suspect_summary'](self._series([1, 1, 2, 2, 1, 0]))
        self.assertAlmostEqual(out['held_min'], 5.0)      # 마지막 0 은 종료 표식
        self.assertEqual(out['max_count'], 2)

    def test_summaries_are_wired_into_analyse_and_the_exit_code(self):
        src = _source(_SCRIPT)
        self.assertIn("measurement == 'water_supply_state'", src)
        self.assertIn("measurement == 'actuator_suspect_count'", src)
        self.assertIn("'suspected': _suspect_summary(suspect_state)", src)
        self.assertIn("(r.get('suspected') or {}).get('max_count')", src)

    def test_vpd_basis_minutes_and_wiring(self):
        """CH94 — 잎 기준인데 엽온 없이 공기로 돈 시간은 볼 것이다(`leaf_vpd`)."""
        from aot.functions.utils.env_control import leaf_vpd as LV
        ns = _load_helpers('_state_minutes', '_vpd_basis_summary')
        ns['LV'] = LV
        self.assertIsNone(ns['_vpd_basis_summary']([]))
        out = ns['_vpd_basis_summary'](self._series(
            [LV.TARGET_LEAF] * 6 + [LV.TARGET_LEAF_FALLBACK] * 3 + [LV.TARGET_LEAF]))
        self.assertAlmostEqual(out['leaf_min'], 7.0)
        self.assertAlmostEqual(out['leaf_fallback_min'], 3.0)
        src = _source(_SCRIPT)
        self.assertIn("measurement == 'vpd_target_basis'", src)
        self.assertIn("(r.get('vpd_basis') or {}).get('leaf_fallback_min')", src)

    def test_the_two_new_reason_codes_are_labelled_from_the_constants(self):
        src = _source(_SCRIPT)
        self.assertIn("LC.REASON_NO_WATER:", src)
        self.assertIn("LC.REASON_ACTUATOR_SUSPECT:", src)


class TestVentAzimuthCheck(unittest.TestCase):
    """풍향 센서는 있는데 개구부 방위각이 없으면 강풍 1단계가 풍향별로 못 가른다(2026-10-10).

    김제 측창 둘이 그 상태였고 화면도 로그도 조용했다 — 설정 점검이 말해야 한다.
    """

    def _run(self, outdoor, shapes):
        from unittest import mock
        import aot.space.facility_integration as fi
        import aot.space.device_binding as db
        ns = _load_helpers('_check_vent_azimuth')
        integ = {'sensors_outdoor': [{'input_uuid': 'wx', 'measurement_type': m}
                                     for m in outdoor],
                 'actuators_resolved': [
                     {'output_uuid': 'o-right', 'output_name': '측창 우', 'kind': 'opening'},
                     {'output_uuid': 'o-left', 'output_name': '측창 좌', 'kind': 'opening'},
                     {'output_uuid': 'o-fog', 'output_name': '분무', 'kind': 'fogger'}]}
        with mock.patch.object(fi, 'get_facility_integration', lambda uid: (integ, None)), \
                mock.patch.object(db, 'shapes_for_devices', lambda ids: shapes):
            return ns['_check_vent_azimuth']('fac')

    def test_방위각_없는_개구부를_말한다(self):
        out = self._run(['wind_speed', 'wind_direction'], {})
        self.assertEqual(len(out), 1)
        level, msg = out[0]
        self.assertEqual(level, 'warn')
        self.assertTrue(msg.startswith('측창 방위각 미설정 — 풍향별 닫기를 못 함'))
        self.assertIn('측창 우', msg)
        self.assertIn('측창 좌', msg)
        self.assertNotIn('분무', msg)

    def test_풍향_센서가_없으면_말하지_않는다(self):
        self.assertEqual(self._run(['wind_speed'], {}), [])

    def test_도형에서_방위각이_나오면_말하지_않는다(self):
        import types
        line = {'type': 'Feature', 'geometry': {
            'type': 'LineString', 'coordinates': [[127.0, 36.0], [127.0005, 36.0]]},
            'properties': {}}
        shp = types.SimpleNamespace(feature=line)
        out = self._run(['wind_direction'], {'o-right': [shp], 'o-left': [shp]})
        self.assertEqual(out, [])
