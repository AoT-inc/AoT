# coding=utf-8
"""check_mcp_contract 의 판정이 맞는 쪽으로 서는지 — 가짜 응답으로 본다(DB 없음).

검사기는 판정이 틀려도 아무 에러가 안 난다. 'OK' 가 그럴듯하게 찍히고 사람은 그것을
믿고 릴리스한다. 그래서 각 검사가 **깨진 응답을 실제로 실패로 잡는지** 를 고정한다.
"""
import unittest

from aot.scripts import check_mcp_contract as C


class _FakeService:
    def __init__(self, summary=None, tree=None, resolve=None):
        self._summary = summary or {'zones': []}
        self._tree = tree or {'hierarchy': []}
        self._resolve = resolve or {'status': 'needs_disambiguation'}
        self.calls = {}

    def _count(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def get_zone_sensor_summary(self):
        self._count('summary')
        return self._summary

    def get_control_state(self, **_):
        return {'coordinators': []}

    def get_device_freshness(self):
        return {'devices': []}

    def get_anomalies(self):
        return {'anomalies': []}

    def get_spatial_tree(self, depth=None):
        self._count('tree')
        return self._tree

    def resolve_target_tool(self, **_):
        return self._resolve

    def search_devices(self, **_):
        return self._resolve

    def get_weather_tool(self, **_):
        return self._resolve


def _summary(last_time):
    return {'zones': [{'name': '1포장', 'sensors': [
        {'device_id': 'd1', 'device_name': '센서', 'last_time': last_time}]}]}


class UtcTimeCheckTest(unittest.TestCase):
    def _run(self, last_time, farm_is_utc=False):
        S = _FakeService(summary=_summary(last_time))
        rep = C.Report()
        C.check_utc_time(S, rep, C.Memo(S), farm_is_utc=farm_is_utc)
        return rep

    def test_local_offset_passes(self):
        self.assertFalse(self._run('2026-10-10T09:00:00+09:00').failed)

    def test_utc_offset_fails(self):
        self.assertTrue(self._run('2026-10-10T00:00:00+00:00').failed)

    def test_z_suffix_fails(self):
        self.assertTrue(self._run('2026-10-10T00:00:00Z').failed)

    def test_utc_plus_zero_farm_accepts_plus_zero(self):
        # 영국 겨울처럼 농장 현지가 UTC+0 이면 '+00:00' 은 정상 현지 표기다.
        self.assertFalse(self._run('2026-10-10T00:00:00+00:00', farm_is_utc=True).failed)
        self.assertTrue(self._run('2026-10-10T00:00:00Z', farm_is_utc=True).failed)

    def test_epoch_ts_fails(self):
        S = _FakeService(summary={'zones': [{'sensors': [{'ts': 1760054400}]}]})
        rep = C.Report()
        C.check_utc_time(S, rep, C.Memo(S), farm_is_utc=False)
        self.assertTrue(rep.failed)


class AmbiguityCheckTest(unittest.TestCase):
    _tree = {'hierarchy': [{'name': '1포장', 'use_name': '김제 1포장', 'children': []}]}

    def test_asks_back(self):
        S = _FakeService(tree=self._tree)
        rep = C.Report()
        C.check_ambiguity(S, rep, C.Memo(S))
        self.assertFalse(rep.failed)
        self.assertEqual(3, len(rep.items))

    def test_silent_pick_fails(self):
        S = _FakeService(tree=self._tree, resolve={'status': 'success'})
        rep = C.Report()
        C.check_ambiguity(S, rep, C.Memo(S))
        self.assertEqual(3, len(rep.failed))

    def test_no_shared_names_is_skipped_not_failed(self):
        S = _FakeService(tree={'hierarchy': [{'name': '1포장', 'children': []}]})
        rep = C.Report()
        C.check_ambiguity(S, rep, C.Memo(S))
        self.assertFalse(rep.failed)


class MemoTest(unittest.TestCase):
    def test_expensive_calls_run_once(self):
        # 구역 요약은 장치 수만큼 시계열을 읽는다 — 검사마다 다시 부르면 실행이 세 배가 된다.
        S = _FakeService(summary=_summary('2026-10-10T09:00:00+09:00'))
        M = C.Memo(S)
        for _ in range(3):
            M.zone_summary()
            M.tree()
        self.assertEqual(1, S.calls['summary'])
        self.assertEqual(1, S.calls['tree'])

    def test_every_check_takes_the_memo(self):
        import inspect
        for fn in C.CHECKS:
            self.assertEqual(['S', 'rep', 'M'],
                             list(inspect.signature(fn).parameters)[:3], fn.__name__)


class RunIsolatesFailuresTest(unittest.TestCase):
    def test_one_broken_check_does_not_stop_the_rest(self):
        class Broken(_FakeService):
            def get_spatial_tree(self, depth=None):
                raise RuntimeError('boom')
        orig = C.CHECKS
        try:
            C.CHECKS = (C.check_ambiguity, C.check_utc_time)
            rep = C.run(Broken())
        finally:
            C.CHECKS = orig
        checks = {i['check'] for i in rep.items}
        self.assertIn('ambiguity', checks)
        self.assertIn('utc-time', checks)
        self.assertTrue(any('검사 자체가 실패' in i['detail'] for i in rep.failed))


class ModelDriversCacheTest(unittest.TestCase):
    """실패한 파싱을 기억하면 그 프로세스 내내 예보가 실측처럼 나간다."""

    def setUp(self):
        from aot.utils import inputs as I
        self.I, self._saved = I, I._MODEL_DRIVERS
        I._MODEL_DRIVERS = None

    def tearDown(self):
        self.I._MODEL_DRIVERS = self._saved

    def test_failure_is_not_remembered(self):
        from unittest import mock
        info = {'OPEN_METEO_FORECAST': {'data_origin': 'model'}, 'X': {}}
        with mock.patch.object(self.I, 'parse_input_information',
                               side_effect=RuntimeError('outside request')):
            self.assertEqual(frozenset(), self.I.model_input_drivers())
        with mock.patch.object(self.I, 'parse_input_information', return_value=info):
            self.assertEqual({'OPEN_METEO_FORECAST'}, self.I.model_input_drivers())
        with mock.patch.object(self.I, 'parse_input_information',
                               side_effect=AssertionError('should be cached')):
            self.assertEqual({'OPEN_METEO_FORECAST'}, self.I.model_input_drivers())


if __name__ == '__main__':
    unittest.main()
