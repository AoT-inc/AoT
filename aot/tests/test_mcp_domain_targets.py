# coding=utf-8
"""도메인 틀의 대상 해석 — docs/design/mcp-domain-surface.md §2.

고정하는 계약:
  1. 정확일치는 종류를 가리지 않고 모으며 부분일치보다 이긴다 — "김제" 는 지도
     '김제' 이지 같은 낱말이 든 기상 장치가 아니다(2026-10-13 실제 사건).
  2. 정확일치가 둘 이상이면 고르지 않는다(지도와 대지가 같은 이름).
  3. "지도" 를 붙이면 지도만 본다. 구획 이름은 표기만 달라도 찾는다('콩4구').
  4. id 는 어느 종류든 먼저 맞춘다.
  5. 해석 결과에는 id·종류·경로·어떤 규칙으로 풀렸는지가 실린다(§2-4).
  6. 승인 스냅샷의 대상이 지워졌거나 이름·경로가 바뀌면 `changed` 가 이유를
     낸다(§9-2 실행 시 재검증) — 같으면 None.

라이브 DB 를 쓰지 않는다(임시 sqlite).
"""
import os
import tempfile
import unittest
from datetime import date


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


class DomainTargetResolveTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import GeoMap, GeoPlot, GeoShape, Input

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'targets.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        db.session.add(GeoMap(unique_id='map-g', name='김제'))
        db.session.add(GeoMap(unique_id='map-y', name='영양'))

        def shape(uid, geo, typ, name, geom):
            db.session.add(GeoShape(
                unique_id=uid, geo_id=geo, type=typ,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}))

        shape('site-3', 'map-g', 'site', '3포장', _square(0.0, 0.0, 0.05))
        shape('zone-31', 'map-g', 'zone', '3-1', _square(0.001, 0.001, 0.02))
        # 지도 '영양' 과 같은 이름의 대지 — 정확일치 둘.
        shape('site-y', 'map-y', 'site', '영양', _square(0.5, 0.5, 0.05))
        db.session.add(GeoPlot(
            unique_id='pl-4', geo_id='map-g', subject='콩', name='콩 4구',
            started_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.002, 0.002, 0.001)}))
        # '김제' 가 이름에 든 기상 장치 둘 — 부분일치일 뿐이다.
        db.session.add(Input(unique_id='in-kma', name='기상청: 김제',
                             device='TEST_TH', is_activated=True))
        db.session.add(Input(unique_id='in-sim', name='SIM 김제 기상대',
                             device='TEST_TH', is_activated=True))
        db.session.add(Input(unique_id='in-th7', name='온습도_7',
                             device='TEST_TH', is_activated=True))
        # 시퀀스 트리거 함수 — 이름이 대지 이름으로 시작한다(2026-10-14 벤치 f27).
        from aot.databases.models.function import Trigger
        db.session.add(Trigger(unique_id='trg-1', name='3포장 밸브제어 v2',
                               trigger_type='trigger_sequence'))
        # 화면 이름 — 지도 '영양' 과 같은 이름의 대시보드·탭(2026-10-14 13:34 UTC 호출 기록).
        from aot.databases.models import Dashboard, Tab
        db.session.add(Dashboard(unique_id='dash-y', name='영양'))
        db.session.add(Tab(unique_id='tab-y', name='영양', page_type='input'))
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

    def _ok(self, ref):
        from aot.tools.domain import targets
        state, t = targets.resolve(ref)
        self.assertEqual('ok', state, (ref, t))
        return t

    def test_exact_map_name_beats_partial_device_names(self):
        t = self._ok('김제')
        self.assertEqual(('map', 'map-g'), (t['kind'], t['id']))

    def test_saying_map_looks_only_at_maps(self):
        t = self._ok('김제 지도')
        self.assertEqual(('map', 'map-g'), (t['kind'], t['id']))

    def test_two_exact_matches_are_not_picked(self):
        from aot.tools.domain import targets
        state, cands = targets.resolve('영양')
        self.assertEqual('ambiguous', state)
        self.assertEqual({'map', 'site'}, {c['kind'] for c in cands})

    def test_place_plot_device_and_ids(self):
        zone = self._ok('3-1')
        self.assertEqual(('zone', 'zone-31'), (zone['kind'], zone['id']))
        self.assertTrue(zone['path'].startswith('김제'), zone['path'])
        self.assertIn('3-1', zone['path'])
        plot = self._ok('콩 4구')
        self.assertEqual(('plot', 'pl-4', 'exact'),
                         (plot['kind'], plot['id'], plot['matched']))
        self.assertEqual(('plot', 'pl-4'), (self._ok('콩4구')['kind'],
                                            self._ok('콩4구')['id']))
        dev = self._ok('온습도_7')
        self.assertEqual(('input', 'in-th7'), (dev['kind'], dev['id']))
        for ref, kind in (('map-g', 'map'), ('site-3', 'site'), ('pl-4', 'plot'),
                          ('in-kma', 'input')):
            self.assertEqual(kind, self._ok(ref)['kind'], ref)

    def test_prefix_and_escaped_names(self):
        t = self._ok('3포')                               # 부분·앞부분 일치 — 한 곳이면 그것
        self.assertEqual(('site', 'site-3'), (t['kind'], t['id']))
        self.assertNotEqual('exact', t['matched'])
        t = self._ok('3\\ud3ec\\uc7a5')                  # 클라이언트가 이스케이프한 '3포장'
        self.assertEqual('site-3', t['id'])

    def test_trigger_functions_resolve_by_name_and_id(self):
        t = self._ok('3포장 밸브제어 v2')        # 대지 '3포장' 의 부분일치가 아니다
        self.assertEqual(('function', 'trg-1'), (t['kind'], t['id']))
        self.assertEqual(('function', 'trg-1'), (self._ok('trg-1')['kind'],
                                                 self._ok('trg-1')['id']))

    def test_candidate_paths_are_accepted_as_input(self):
        # 표시 = 입력 — 모호한 대상의 후보로 보여 준 경로(`dashboard > 영양`,
        # `input tabs > 영양`)를 그대로 target 으로 보내면 그 하나로 풀린다.
        from aot.tools.domain import targets
        accepts = ('dashboard', 'tab')
        state, cands = targets.resolve('영양', accepts=accepts)
        self.assertEqual('ambiguous', state)
        paths = {c['path'] for c in cands if c['kind'] in accepts}
        self.assertEqual({'dashboard > 영양', 'input tabs > 영양'}, paths)
        for c in (c for c in cands if c['kind'] in accepts):
            state, t = targets.resolve(c['path'], accepts=accepts)
            self.assertEqual(('ok', c['id']), (state, t['id'] if state == 'ok' else t),
                             c['path'])
        state, t = targets.resolve('Dashboard > 영양', accepts=accepts)
        self.assertEqual(('ok', 'dash-y'), (state, t['id'] if state == 'ok' else t))
        # 그 종류를 받지 않거나 없는 경로는 여전히 거절한다.
        state, _ = targets.resolve('dashboard > 없는것', accepts=accepts)
        self.assertEqual('none', state)
        state, _ = targets.resolve('dashboard > 영양')
        self.assertEqual('none', state)

    def test_unknown_name_is_not_guessed(self):
        from aot.tools.domain import targets
        state, err = targets.resolve('없는 곳')
        self.assertEqual('none', state)
        self.assertIn('Nothing named', err['error'])
        self.assertEqual(('empty', None), targets.resolve('  '))

    def test_changed_target_is_detected_before_running(self):
        from aot.aot_flask.extensions import db
        from aot.aot_flask.geo import shape_index
        from aot.databases.models import GeoShape
        from aot.tools.domain import targets
        snap = targets.snapshot(self._ok('3-1'))
        self.assertIsNone(targets.changed(snap))
        row = GeoShape.query.filter_by(unique_id='zone-31').first()
        feat = dict(row.feature)
        feat['properties'] = dict(feat['properties'], name='3-1 북쪽')
        row.feature = feat
        db.session.commit()
        shape_index.invalidate()
        try:
            self.assertIn('name', targets.changed(snap) or '')
        finally:
            feat['properties'] = dict(feat['properties'], name='3-1')
            row.feature = dict(feat)
            db.session.commit()
            shape_index.invalidate()
        self.assertIn('no longer exists',
                      targets.changed(dict(snap, id='gone-id')) or '')


if __name__ == '__main__':
    unittest.main()


class NavigateNameTieTest(unittest.TestCase):
    """화면 이동은 같은 이름이 대시보드와 탭에 있으면 되묻지 않고 대시보드로 간다(2026-10-26).
    대지·시설·장치와의 이름 겹침은 이 규칙이 아니다 — 이동은 대시보드·탭만 후보로 받는다."""

    DASH = {'kind': 'dashboard', 'id': 'D1', 'name': '영양', 'path': 'dashboard > 영양'}
    TAB = {'kind': 'tab', 'id': 'T1', 'name': '영양', 'path': 'input tabs > 영양'}
    TAB2 = {'kind': 'tab', 'id': 'T2', 'name': '영양', 'path': 'output tabs > 영양'}
    SITE = {'kind': 'site', 'id': 'S1', 'name': '영양', 'path': '영양'}

    def _plan(self, cands, **extra):
        from unittest import mock
        from aot.tools.domain import contract, dispatch
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)

        def resolve(ref, accepts=(), only=None):
            fit = [c for c in cands if only is None or c['kind'] in only]
            return ('ambiguous', fit) if len(fit) > 1 else (('ok', fit[0]) if fit else ('none', {'error': 'none'}))
        with mock.patch.object(dispatch.targets, 'resolve', resolve):
            return dispatch.plan('screen', dict({'op': 'act', 'action': 'navigate', 'target': '영양'}, **extra))

    def test_a_dashboard_and_tabs_with_one_name_go_to_the_dashboard_and_say_so(self):
        for cands in ([self.DASH, self.TAB], [self.TAB, self.DASH, self.TAB2]):
            verdict = self._plan(cands)
            self.assertNotEqual('refuse', verdict[0], verdict)
            inner_args = verdict[2]
            self.assertEqual('D1', inner_args.get('dashboard'), inner_args)
            self.assertIn('went to the dashboard', inner_args['_domain_meta']['why'])

    def test_only_tabs_with_one_name_still_ask(self):
        verdict = self._plan([self.TAB, self.TAB2])
        self.assertEqual('refuse', verdict[0])
        self.assertIn('needs_disambiguation', str(verdict[1]))

    def test_a_site_of_the_same_name_is_not_a_navigate_candidate_so_it_never_hijacks_the_tie(self):
        verdict = self._plan([self.SITE, self.DASH, self.TAB])
        self.assertNotEqual('refuse', verdict[0], verdict)
        self.assertEqual('D1', verdict[2].get('dashboard'))
