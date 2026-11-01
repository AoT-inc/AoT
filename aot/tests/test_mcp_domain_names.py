# coding=utf-8
"""사람이 부르는 이름 → 대상(docs/design/mcp-domain-surface.md §2-2).

실제 실패의 대부분이 이 모양이었다(사용자, 2026-10-14): **같은 이름에 숫자나 지역이
붙고, 다른 지도·지역에 놓인 것**들. 예: 지도 '김제', 장치 '밸브: 김제', 시설 '온실: 김제'.
사람은 "김제 밸브", "김제 1번 밸브", "김제 온실" 처럼 순서·구두점·조사 없이 부른다.

고정하는 계약:
  - 낱말이 같으면 순서·구두점·조사('의'·'에')·'번'이 달라도 같은 이름이다.
  - 지역 낱말은 이름 안에 있거나, 그것이 놓인 지도·장소의 이름이어도 된다.
  - 낱말이 꼭 맞는 것이 하나면 그것, 여럿이면 고르지 않는다(어디 있는지를 붙여 후보로).
  - 이름에 숫자가 더 붙은 것("밸브 1: 김제")은 숫자 없는 물음("김제 밸브")의 답이 아니다 —
    숫자 없는 것("밸브: 김제")이 있으면 그것, 없으면 숫자 붙은 것들을 후보로 되묻는다.

라이브 DB 를 쓰지 않는다(임시 sqlite).
"""
import os
import tempfile
import unittest


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


def _point(x, y):
    return {'type': 'Point', 'coordinates': [x, y]}


class DomainNameResolutionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from datetime import date, timedelta
        from aot.databases.models import (Dashboard, GeoMap, GeoPlot, GeoShape, Output,
                                          Widget)

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'names.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        db.session.add(GeoMap(unique_id='map-g', name='김제'))
        db.session.add(GeoMap(unique_id='map-y', name='영양'))
        db.session.add(GeoMap(unique_id='map-j', name='金堤'))
        db.session.add(GeoMap(unique_id='map-e', name='Gimje'))
        db.session.add(Dashboard(unique_id='dash-y', name='영양'))
        for uid, subject, name, start in (
                ('pl-r', '장미', '장미원 1', date.today() - timedelta(days=30)),
                ('pl-r2', '장미', '장미원 2', date.today() + timedelta(days=150)),
                ('pl-b', '콩', None, date.today() - timedelta(days=10))):
            db.session.add(GeoPlot(unique_id=uid, geo_id='map-y', subject=subject,
                                   name=name, started_on=start,
                                   feature={'type': 'Feature', 'properties': {},
                                            'geometry': _square(1.002, 1.002, 0.001)}))
        db.session.add(Widget(unique_id='fe10a462-2cdc-4b92-8a7f-9c2c8ea8d804', name='환경',
                              graph_type='AoT_graph', tab_id='dash-y'))

        def shape(uid, geo, typ, name, geom, device_id=None):
            db.session.add(GeoShape(
                unique_id=uid, geo_id=geo, type=typ, device_id=device_id,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}))

        shape('site-g', 'map-g', 'site', '1포장', _square(0.0, 0.0, 0.05))
        shape('site-y', 'map-y', 'site', '육묘장 대지', _square(1.0, 1.0, 0.05))
        shape('fac-g', 'map-g', 'facility', '온실: 김제', _square(0.01, 0.01, 0.005))
        shape('fac-y', 'map-y', 'facility', '온실: 영양', _square(1.01, 1.01, 0.005))
        shape('site-j', 'map-j', 'site', '第1圃場', _square(2.0, 2.0, 0.05))
        shape('fac-j', 'map-j', 'facility', '温室: 金堤', _square(2.01, 2.01, 0.005))
        shape('site-e', 'map-e', 'site', 'Field A', _square(3.0, 3.0, 0.05))
        for uid, name, geo, x in (('v-g', '밸브: 김제', 'map-g', 0.02),
                                  ('v-g1', '밸브 1: 김제', 'map-g', 0.021),
                                  ('v-g2', '밸브 2: 김제', 'map-g', 0.022),
                                  ('v-y1', '밸브 1: 영양', 'map-y', 1.02),
                                  ('p-g', '펌프', 'map-g', 0.023),
                                  ('p-y', '펌프', 'map-y', 1.023),
                                  ('w-g', 'SIM 관수밸브 3', 'map-g', 0.024),
                                  ('x-g', '기상청: 김제', 'map-g', 0.025),
                                  ('j-v', 'バルブ: 金堤', 'map-j', 2.02),
                                  ('j-v1', 'バルブ 1: 金堤', 'map-j', 2.021),
                                  ('e-v', 'Valve: Gimje', 'map-e', 3.02),
                                  ('e-v1', 'Valve 1: Gimje', 'map-e', 3.021),
                                  ('e-p', 'Pump', 'map-e', 3.022),
                                  ('t-7', '온습도_7', 'map-g', 0.026),
                                  ('m-1', '환경센서:meteo', 'map-g', 0.027)):
            db.session.add(Output(unique_id=uid, name=name,
                                  output_type='virtual_on_off_single',
                                  is_ai_enabled=(uid != 'x-g')))
            shape('mk-' + uid, geo, 'aot_device', name, _point(x, x), device_id=uid)
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()

    def _resolve(self, ref):
        from aot.tools.domain import targets
        return targets.resolve(ref)

    def _is(self, ref, want_id):
        state, got = self._resolve(ref)
        self.assertEqual('ok', state, (ref, got))
        self.assertEqual(want_id, got['id'], (ref, got))

    def _ambiguous(self, ref, want_ids):
        state, got = self._resolve(ref)
        self.assertEqual('ambiguous', state, (ref, got))
        self.assertEqual(set(want_ids), {c['id'] for c in got}, (ref, got))

    def test_map_name_alone_is_the_map(self):
        self._is('김제', 'map-g')

    def test_word_order_punctuation_and_particles_do_not_matter(self):
        self._is('밸브: 김제', 'v-g')
        self._is('김제 밸브', 'v-g')
        self._is('밸브 김제', 'v-g')
        self._is('김제의 밸브', 'v-g')
        self._is('김제 온실', 'fac-g')
        self._is('영양 온실', 'fac-y')

    def test_numbers_pick_the_numbered_one(self):
        self._is('김제 1번 밸브', 'v-g1')
        self._is('밸브 1 김제', 'v-g1')
        self._is('김제 밸브 2', 'v-g2')
        self._is('영양 1번 밸브', 'v-y1')

    def test_underscore_separates_words(self):
        self._is('온습도 7', 't-7')
        self._is('김제 온습도7', 't-7')

    def test_numbered_without_region_is_not_picked(self):
        self._ambiguous('1번 밸브', ['v-g1', 'v-y1'])

    def test_region_can_come_from_where_it_is_placed(self):
        """'펌프' 는 이름에 지역이 없다 — 놓인 지도의 이름으로 가른다."""
        self._is('김제 펌프', 'p-g')
        self._is('영양 펌프', 'p-y')
        self._ambiguous('펌프', ['p-g', 'p-y'])

    def test_kind_words_read_as_inside_the_named_place(self):
        """'김제 장치' 는 지도 김제 안의 장치들이지 이름에 '김제' 가 든 장치가 아니다 —
        옛 표면은 '김제' 에 장치 둘을 내밀었다(2026-10-14 사용자 보고)."""
        for ref in ('김제 농장', '김제 지도의 농장', '김제 장치', '김제에 있는 장치',
                    '김제 요약'):
            self._is(ref, 'map-g')
        self._is('영양 시설', 'map-y')
        self._is('영양 지도의 장치', 'map-y')

    def test_unexplained_words_are_not_guessed(self):
        from aot.tools.domain import targets
        state, _err = targets.resolve('김제 오이')
        self.assertNotEqual('ok', state)

    def test_word_inside_a_compound_name(self):
        """실제 밸브 이름은 'SIM 관수밸브 3' 처럼 합성어다 — '밸브' 로도 찾는다."""
        self._is('김제 관수밸브', 'w-g')
        self._is('김제 3번 밸브', 'w-g')

    def test_device_left_out_of_ai_says_so(self):
        from aot.tools.domain import targets
        for ref in ('김제 기상청', '기상청'):         # 한 덩이 물음도(2026-10-14 웹 시험 B8)
            state, err = targets.resolve(ref)
            self.assertEqual('none', state, (ref, err))
            self.assertIn('reason_code', err, ref)
            self.assertIn('기상청: 김제', err.get('excluded') or [err['error']], ref)

    def test_measurement_word_in_the_target_is_left_to_measurement(self):
        self._is('김제 온실 온도', 'fac-g')
        self._is('영양 온실 토양수분', 'fac-y')

    # ── 언어·띄어쓰기에 기대지 않는다(2026-10-14 사용자 지적) ──────────────

    def test_no_spaces_between_words(self):
        self._is('김제의밸브', 'v-g')
        self._is('김제1번밸브', 'v-g1')
        self._is('김제온실', 'fac-g')
        self._is('김제장치', 'map-g')

    def test_japanese_without_spaces(self):
        self._is('金堤のバルブ', 'j-v')
        self._is('金堤のバルブ1', 'j-v1')
        self._is('金堤の温室', 'fac-j')
        self._is('金堤の施設', 'map-j')
        self._is('金堤にある装置', 'map-j')

    def test_english_word_order(self):
        self._is('valve in gimje', 'e-v')
        self._is('Gimje valve 1', 'e-v1')
        self._is('pump in Gimje', 'e-p')
        self._is('Gimje devices', 'map-e')

    def test_path_form_is_language_free(self):
        """'자리 > 이름' — 응답의 path 와 같은 표기. 문법을 거치지 않는다."""
        self._is('김제 > 펌프', 'p-g')
        self._is('영양 > 펌프', 'p-y')
        self._is('김제 > 밸브', 'v-g')
        self._is('김제 > 1포장', 'site-g')
        self._is('Gimje > Field A', 'site-e')
        from aot.tools.domain import targets
        state, err = targets.resolve('영양 > 관수밸브')    # 김제에만 있다
        self.assertEqual('none', state, err)
        self.assertIn("in '영양'", err['error'])

    def test_unexplained_piece_is_not_glossed_over(self):
        from aot.tools.domain import targets
        for ref in ('김제오이', '金堤のキュウリ', 'gimje cucumber'):
            state, got = targets.resolve(ref)
            self.assertNotEqual('ok', state, (ref, got))

    # ── 화면 이동의 대시보드(2026-10-14 웹 시험: '영양' 이 늘 지도로 풀려 이동 불가) ──

    def test_dashboards_are_found_only_where_they_are_accepted(self):
        from aot.tools.domain import targets
        self._is('영양', 'map-y')                                   # 읽기·장소 operation
        state, got = targets.resolve('영양', accepts={'dashboard', 'site'})
        self.assertEqual('ambiguous', state, got)
        self.assertIn('dash-y', {c['id'] for c in got})
        state, got = targets.resolve('영양', accepts={'site'}, only={'dashboard'})
        self.assertEqual(('ok', 'dash-y'), (state, got['id']))
        state, got = targets.resolve('김제', only={'dashboard'})
        self.assertEqual('none', state)                              # 지도는 대시보드가 아니다
        self.assertEqual(('ok', 'dashboard'), (targets.resolve('dash-y')[0],
                                               targets.resolve('dash-y')[1]['kind']))

    def test_widgets_by_name_and_short_id_where_accepted(self):
        """'환경' 은 위젯을 받는 곳에서는 위젯이다 — 센서 '환경센서:meteo' 가 아니다
        (2026-10-14 웹 시험: 하이라이트가 엉뚱한 센서로 풀렸다)."""
        from aot.tools.domain import targets
        wid = 'fe10a462-2cdc-4b92-8a7f-9c2c8ea8d804'
        for ref in ('환경', '#fe10a462', 'fe10a462', wid):
            state, got = targets.resolve(ref, accepts={'widget', 'site', 'input'})
            self.assertEqual(('ok', wid), (state, got['id']), ref)
            self.assertEqual('dashboard > 영양 > 환경', got['path'])
        state, got = targets.resolve('환경')
        self.assertNotEqual('widget', got.get('kind') if state == 'ok' else None)

    def test_plot_list_searches_by_crop_and_names_planned_ones(self):
        """'장미 구획' 은 장소가 아니라 작물이다(2026-10-14 사용자 시험)."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.list_plots(query='장미')
        self.assertEqual(['pl-r'], [p['unique_id'] for p in out['plots']])
        self.assertEqual('장미', out['query'])
        out = S.list_plots(query='원 2')                        # 이름의 일부, 띄어쓰기 무시
        self.assertEqual([], out['plots'])
        self.assertIn('1 planned or finished', out['note'])
        self.assertEqual(['pl-b'], [p['unique_id'] for p in S.list_plots(query='콩')['plots']])


if __name__ == '__main__':
    unittest.main()
