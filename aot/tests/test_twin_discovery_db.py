# coding=utf-8
"""디지털트윈 배포형 서비스(S2): DB 에서 대지·노지 구획·예보 채널 메타를 읽는 `DbCatalog`.

순수 조립(`build_plan`)은 aot/twin/tests/test_service.py 가 맡는다. 여기는 진짜 모델(sqlite)로
'열린 노지 구획만, 대지로 묶어서, 시간대·위도·심은 날을 채워서' 와 예보 입력의 채널 메타를 고정한다.
"""
import datetime
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements, GeoMap, GeoPlot, GeoShape, Input, Misc
from aot.inputs.open_meteo_daily_forecast import INPUT_INFORMATION as OM_DAILY
from aot.twin.discovery import DbCatalog, build_plan
from aot.twin.gate import LazyApp


def _poly(ring):
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [ring]}, 'properties': {}}


def _sq(x0, y0, d):
    return [[x0, y0], [x0, y0 + d], [x0 + d, y0 + d], [x0 + d, y0], [x0, y0]]


SITE = _sq(126.88, 35.86, 0.01)                 # 김제 인근 경위도(시간대 판정용) — 지역을 가정하는 코드는 없다


class DbCatalogTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        try:
            from flask_babel import Babel
            Babel(self.app)
        except Exception:
            pass
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add(Misc())
        GeoMap(unique_id='m1', name='김제', category='design').save()
        site = _poly(SITE)
        site['properties']['name'] = 'A 포장'
        GeoShape(unique_id='site-1', geo_id='m1', type='site', feature=site).save()
        d = datetime.date

        def plot(uid, ring, **kw):
            kw.setdefault('kind', 'vegetation')
            kw.setdefault('subject', '들깨')
            kw.setdefault('started_on', d(2026, 6, 20))
            db.session.add(GeoPlot(unique_id=uid, geo_id='m1', name=uid, feature=_poly(ring) if ring else None, **kw))

        plot('open-in', _sq(126.882, 35.862, 0.001))
        plot('ended-in', _sq(126.884, 35.862, 0.001), ended_on=d(2026, 9, 1))
        plot('facility', None, facility_uuid='fac-1', bay_id='bay_1')
        plot('livestock', _sq(126.886, 35.862, 0.001), kind='livestock', subject='한우')
        plot('outside', _sq(126.95, 35.95, 0.001), started_on=d(2026, 7, 1))
        plot('planned', _sq(126.887, 35.862, 0.001), started_on=d(2099, 1, 1))
        plot('ends-later', _sq(126.888, 35.862, 0.001), ended_on=d(2099, 1, 1))
        db.session.add(Input(unique_id='om-1', device='OPEN_METEO_DAILY_FORECAST', name='예보'))
        for ch in range(40):
            meta = OM_DAILY['measurements_dict'][ch]
            db.session.add(DeviceMeasurements(device_id='om-1', channel=ch, measurement=meta['measurement'],
                                              unit=meta['unit'], is_enabled=(ch != 2), name=meta['name']))
        db.session.commit()
        self.cat = DbCatalog(LazyApp(lambda: self.app))

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_open_field_plots_grouped_by_site_with_auto_options(self):
        sites = {s.site_id: s for s in self.cat.sites()}
        self.assertEqual(set(sites), {'site-1', 'map:m1'})
        a = sites['site-1']
        self.assertEqual(a.name, 'A 포장')
        self.assertEqual([p.unique_id for p in a.plots], ['open-in', 'ends-later'])   # 끝난·안 심은 작기·시설·가축 제외
        self.assertEqual(a.plots[0].started_on, '2026-06-20')
        self.assertAlmostEqual(a.plots[0].lat, 35.8625, places=3)
        self.assertEqual(a.timezone, 'Asia/Seoul')
        self.assertEqual([p.unique_id for p in sites['map:m1'].plots], ['outside'])   # 대지 밖 → 지도 하나

    def test_forecast_channel_meta_from_db_and_input_module(self):
        with mock.patch('aot.utils.inputs.parse_input_information',
                        return_value={'OPEN_METEO_DAILY_FORECAST': OM_DAILY}):
            chans = self.cat.forecast_channels('om-1')
        by_ch = {c['channel']: c for c in chans}
        self.assertEqual(by_ch[3]['lead_d'], 3)
        self.assertEqual(by_ch[3]['daily_stat'], 'sum')
        self.assertEqual(by_ch[17]['daily_stat'], 'max')
        self.assertFalse(by_ch[2]['enabled'])
        with self.assertRaises(LookupError):
            self.cat.forecast_channels('nope')

    def test_forecast_channel_meta_runs_inside_a_request_context(self):
        """입력 모듈 정보의 지연 번역 문구가 요청(로케일 선택)을 요구한다 — 서비스는 요청 밖이라 직접 열어 줘야 한다
        (개발서버에서 'Working outside of request context' 로 예보 사다리가 빠진 회귀)."""
        from flask import has_request_context

        def needs_request():
            self.assertTrue(has_request_context())
            return {'OPEN_METEO_DAILY_FORECAST': OM_DAILY}

        with mock.patch('aot.utils.inputs.parse_input_information', side_effect=needs_request):
            self.assertTrue(self.cat.forecast_channels('om-1'))

    def test_end_to_end_plan_from_db(self):
        ov = {'sites': {'site-1': {'enabled': True, 'forecast': {'input': 'om-1'},
                                   'inputs': {'rain': {'unique_id': 'r', 'unit': 'mm', 'channel': 0}}}}}
        with mock.patch('aot.utils.inputs.parse_input_information',
                        return_value={'OPEN_METEO_DAILY_FORECAST': OM_DAILY}):
            plans = build_plan(self.cat.sites(), ov, self.cat.forecast_channels)
        self.assertEqual([p.site_id for p in plans], ['site-1'])
        t = plans[0].targets[0]
        self.assertEqual(t.target_id, 'open-in')
        self.assertEqual(t.options['planted_on'], '2026-06-20')
        self.assertEqual(t.options['timezone'], 'Asia/Seoul')
        # 앞날 예보는 대지 예보 계열 — 입력은 대지 예보 출처 지정이 정한다(옛 forecast.input 은 쓰지 않는다고 알림)
        self.assertEqual(t.options['forecast_series'], {'site': 'site-1'})
        self.assertNotIn('forecast', t.options)
        self.assertTrue(any('forecast.input' in n for n in plans[0].notes))


if __name__ == '__main__':
    unittest.main()
