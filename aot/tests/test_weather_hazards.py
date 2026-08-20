# coding=utf-8
"""곧 닥칠 기상 위험 판정 — 시설·노지 공통.

사람이 오늘 저녁에 무엇을 할지는 "지금 몇 도인가" 보다 "밤에 얼마나
떨어지는가" 가 정한다. 그 판단 재료를 화면이 주지 않으면 다른 앱을 열게 된다.

**낡은 예보로는 경고하지 않는다** — 발행시각이 수개월 지난 설치가 실제로 있다
(이 저장소의 개발 환경이 그렇다). 그런 예보로 "오늘 밤 서리" 라고 말하면 사람은
그 말을 믿고 행동한다.
"""
import os
import unittest
from unittest import mock

from aot.aot_flask.geo import weather_hazards as wh

_HERE = os.path.dirname(os.path.abspath(__file__))


def _fc(rows, pub_age_h=1.0):
    """`forecast.json` 모양의 가짜 예보. 키는 현재시각 기준 시간 오프셋."""
    from datetime import datetime, timedelta
    pub = (datetime.now() - timedelta(hours=pub_age_h)).strftime('%Y%m%d%H%M')
    return {'pub_dt': pub, 'forecasts': {str(k): v for k, v in rows.items()}}


def _upcoming(rows, pub_age_h=1.0, hours=24):
    with mock.patch(
            'aot.functions.utils.env_control.forecast_feedforward._load_forecast',
            return_value=_fc(rows, pub_age_h)):
        return wh.upcoming(hours)


class TestHazards(unittest.TestCase):

    def test_frost_is_flagged_before_it_freezes(self):
        """서리는 0℃가 아니라 2℃부터 본다 — 지면은 기온보다 낮게 떨어진다."""
        out = _upcoming({3: {'TMP': 1.5}})
        kinds = [i['kind'] for i in out['items']]
        self.assertIn('frost', kinds)
        self.assertEqual(3, out['items'][0]['in_h'])

    def test_freezing_is_severe(self):
        out = _upcoming({5: {'TMP': -1.0}})
        by = {i['kind']: i for i in out['items']}
        self.assertEqual('severe', by['freeze']['severity'])

    def test_one_row_per_kind_earliest_wins(self):
        """"3시간 뒤 서리, 4시간 뒤 서리" 는 같은 사실을 두 번 말하는 것이고
        사람이 할 일은 하나다."""
        out = _upcoming({3: {'TMP': 1.0}, 4: {'TMP': 0.5}, 5: {'TMP': 1.2}})
        frost = [i for i in out['items'] if i['kind'] in ('frost', 'freeze')]
        self.assertEqual(len(frost), len({i['kind'] for i in frost}))
        self.assertEqual(3, min(i['in_h'] for i in frost))

    def test_stale_forecast_says_nothing(self):
        out = _upcoming({3: {'TMP': -5.0}}, pub_age_h=12.0)
        self.assertTrue(out['stale'])
        self.assertEqual([], out['items'],
                         '낡은 예보로 경고하면 사람이 그 말을 믿고 행동한다')

    def test_outside_the_window_is_ignored(self):
        out = _upcoming({30: {'TMP': -5.0}}, hours=24)
        self.assertEqual([], out['items'])

    def test_past_hours_are_ignored(self):
        out = _upcoming({-3: {'TMP': -5.0}})
        self.assertEqual([], out['items'])

    def test_calm_weather_has_no_items(self):
        """평범한 날에 경고가 뜨면 다음 경고를 안 보게 된다."""
        out = _upcoming({k: {'TMP': 20.0, 'WSD': 2.0, 'RN1': 0.0}
                         for k in range(0, 24)})
        self.assertEqual([], out['items'])

    def test_missing_forecast_is_not_an_error(self):
        with mock.patch(
                'aot.functions.utils.env_control.forecast_feedforward._load_forecast',
                return_value={}):
            out = wh.upcoming()
        self.assertEqual([], out['items'])
        self.assertFalse(out['stale'])


class TestSharedByFacilityAndField(unittest.TestCase):
    """같은 사실을 계층마다 다른 문장으로 적으면 사용자는 다른 이야기로 읽는다."""

    def _read(self, path):
        with open(os.path.join(_HERE, '..', path), encoding='utf-8') as fh:
            return fh.read()

    def test_both_modals_send_the_same_payload(self):
        for path, needle in (
                ('aot_flask/routes_geo_iec.py', "'hazards':     weather_hazards"),
                ('aot_flask/routes_geo.py', "'hazards': weather_hazards")):
            self.assertIn(needle, self._read(path), path)

    def test_both_modals_use_the_same_renderer(self):
        js = self._read('aot_flask/static/js/widgets/AoT_map/'
                        'aot-map-widget-vector.js')
        self.assertEqual(2, js.count('buildHazardsHtml('),
                         '시설·노지 중 한쪽만 그리고 있다')


if __name__ == '__main__':
    unittest.main()
