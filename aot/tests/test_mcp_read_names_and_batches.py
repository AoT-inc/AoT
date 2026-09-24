# coding=utf-8
"""조회 도구가 이름을 받고(3-A), 여러 대상을 한 번에 받는다(3-F). 같은 이름을
표시하고(P7), 쓰기 인자는 승인·조언 전용 거절보다 먼저 검사한다(P2).

고정하는 계약:

  1. id 자리에 사람이 쓰는 이름을 줘도 된다 — get_output_state·
     get_device_measurements·get_sensor_detail·get_zone_sensor_summary·
     list_plots·get_plot·get_sensor_reading. id 정확일치가 먼저다.
  2. 이름이 여럿에 걸리면 고르지 않는다 — needs_disambiguation + 사람이 가를
     단서('where')가 붙은 후보 + `_reading`.
  3. 여러 대상 인자는 {count, results[각 대상의 단수 응답 + requested]} 로 답하고,
     상한(10)을 넘으면 나눠 부르라고 답한다. `_reading` 은 위로 모은다.
  4. search_devices 는 이름이 같은 장치에 same_name_count·where 를 붙이고
     same_name_groups 와 `_reading` 한 줄을 싣는다.
  5. 쓰기 도구의 인자 오류(모르는 옵션 키·틀린 옵션 값·빠진 필수 인자·
     맞는 이름의 오타로 보이는 인자 이름)는 조언 전용 모드에서도 write_disabled
     보다 먼저 invalid_arguments 로 돌아오고, 역할·조언 전용 모드가 어차피
     막으면 같은 메시지에 적는다(also_refused). 오타가 아닌 모르는 인자
     (reason·title·confirm 같은 메타 키 포함)는 거절하지 않는다. 인자가 맞으면
     게이트가 평소대로 판정한다. 처리기가 받는 값은 스키마 선택지 밖이어도
     거절하지 않는다.
  6. (리뷰 26-09-24) 구획 이름·작물·품종 세 칸을 모두 보고, 둘 이상이면
     고르지 않는다. search_devices 결과를 통째로 줘도 여럿이면 고르지 않는다.
     여러 대상 응답은 캡에서 대상 안의 행부터 줄인다. zone_ids 도 10개 상한,
     available_targets 는 위에 한 번. 단계 확인은 날짜도 제안도 없으면 묻는다.

라이브 DB 를 쓰지 않는다(임시 sqlite · conftest 의 임시 DB).
"""
import json
import os
import tempfile
import unittest
from datetime import date
from unittest import mock


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


def _point(x, y):
    return {'type': 'Point', 'coordinates': [x, y]}


class _NoDaemon:
    """데몬 없이 get_output_state 를 돌린다(연결 시도·로그를 피한다)."""

    def output_states_all(self):
        return {}

    def output_sec_currently_on(self, *_a, **_k):
        return 0


class TestReadTargetsByName(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import (DeviceMeasurements, GeoMap, GeoPlot,
                                          GeoShape, Input, Output)

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'names.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls.flask_app = app
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        db.session.add(GeoMap(unique_id='map-a', name='김제'))

        def shape(uid, typ, name, geom, device_id=None):
            db.session.add(GeoShape(
                unique_id=uid, geo_id='map-a', type=typ, device_id=device_id,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}))

        # 대지 > 구역 > 구역(3포장 > 1구역 > 3-1) — 이름 3-1 은 하나뿐.
        shape('site-3', 'site', '3포장', _square(0.0, 0.0, 0.05))
        shape('zone-31', 'zone', '1구역', _square(0.001, 0.001, 0.02))
        shape('zone-311', 'zone', '3-1', _square(0.002, 0.002, 0.01))
        # 서로 다른 대지의 같은 이름 구역 '1'.
        shape('site-g', 'site', '구례', _square(0.3, 0.3, 0.01))
        shape('site-j', 'site', '진안', _square(0.4, 0.4, 0.01))
        shape('z1-g', 'zone', '1', _square(0.302, 0.302, 0.002))
        shape('z1-j', 'zone', '1', _square(0.402, 0.402, 0.002))
        # 출력: 이름이 하나뿐인 v121, 이름이 같은 v111 둘.
        db.session.add(Output(unique_id='out-v121', name='v121',
                              output_type='virtual_on_off_single'))
        db.session.add(Output(unique_id='out-a', name='v111',
                              output_type='virtual_on_off_single'))
        db.session.add(Output(unique_id='out-b', name='v111',
                              output_type='virtual_on_off_single'))
        # 센서 하나 — 지도에는 같은 이름의 장치 표식 도형도 있다.
        db.session.add(Input(unique_id='in-temp', name='온습도_1',
                             device='TEST_TH', is_activated=True))
        db.session.add(DeviceMeasurements(device_id='in-temp', channel=0,
                                          measurement='temperature', unit='C'))
        shape('mk-temp', 'aot_device', '온습도_1', _point(0.003, 0.003),
              device_id='in-temp')
        # 재배 중인 구획: '콩' 하나, '상추' 둘.
        for uid, subject, x in (('pl-kong', '콩', 0.004), ('pl-s1', '상추', 0.006),
                                ('pl-s2', '상추', 0.008)):
            db.session.add(GeoPlot(
                unique_id=uid, geo_id='map-a', subject=subject,
                started_on=date.today(),
                feature={'type': 'Feature', 'properties': {},
                         'geometry': _square(x, x, 0.001)}))
        # 리뷰 재현: 구획 **이름**이 다른 구획에서 기르는 작물 이름과 같다.
        db.session.add(GeoPlot(
            unique_id='pl-named', geo_id='map-a', name='고추', subject='옥수수',
            started_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.010, 0.010, 0.001)}))
        db.session.add(GeoPlot(
            unique_id='pl-gochu', geo_id='map-a', subject='고추',
            started_on=date.today(),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.012, 0.012, 0.001)}))
        # 프로그램을 따르는 구획(단계 확인 날짜 검사용 — 제안은 모의한다).
        db.session.add(GeoPlot(
            unique_id='pl-prog', geo_id='map-a', subject='오이',
            program_uuid='prog-x', started_on=date(2026, 3, 1),
            feature={'type': 'Feature', 'properties': {},
                     'geometry': _square(0.014, 0.014, 0.001)}))
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
        self._daemon = mock.patch('aot.aot_client.DaemonControl', _NoDaemon)
        self._daemon.start()

    def tearDown(self):
        self._daemon.stop()

    @property
    def S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    # ── 1·2. 이름을 받고, 모호하면 고르지 않는다 ───────────────────────────
    def test_output_state_takes_a_name(self):
        out = self.S.get_output_state(device_id='v121')
        self.assertEqual('out-v121', out.get('device_id'), out)
        self.assertEqual('v121', out.get('name'))

    def test_output_state_id_still_works(self):
        self.assertEqual('out-v121',
                         self.S.get_output_state(device_id='out-v121')['device_id'])

    def test_shared_name_returns_candidates_with_where(self):
        out = self.S.get_output_state(device_id='v111')
        self.assertEqual('needs_disambiguation', out.get('status'), out)
        self.assertEqual(2, len(out['candidates']))
        self.assertTrue(all('where' in c for c in out['candidates']))
        self.assertTrue(any('never by id' in r for r in out['_reading']))

    def test_output_state_refuses_a_sensor(self):
        out = self.S.get_output_state(device_id='온습도_1')
        self.assertIn('is an input, not an output', out.get('error', ''), out)

    def test_device_measurements_take_a_name(self):
        out = self.S.get_device_measurements(device_id='온습도_1')
        self.assertEqual('in-temp', out.get('device_id'), out)
        self.assertEqual('temperature', out['measurements'][0]['measurement'])

    def test_sensor_name_goes_to_the_sensor_not_its_map_marker(self):
        """장치 표식 도형도 같은 이름이다 — 곳 리졸버를 먼저 쓰면 "센서 없는
        구역" 으로 풀렸다."""
        self.assertEqual('in-temp', self.S._sensor_loc_by_name('온습도_1'))

    def test_sensor_detail_zone_name_and_ambiguity(self):
        self.assertEqual('zone-311', self.S._sensor_loc_by_name('3-1'))
        amb = self.S._sensor_loc_by_name('1')
        self.assertEqual('needs_disambiguation', amb.get('status'), amb)
        self.assertEqual(2, len(amb['candidates']))
        out = self.S._sensor_loc_by_name('v121')
        self.assertIn('get_output_state', out.get('error', ''))

    def test_zone_summary_takes_names_and_reports_the_unresolved(self):
        out = self.S.get_zone_sensor_summary(zone_ids=['3-1', '1'],
                                             measurement_type='co2')
        self.assertEqual(['1'], [u['requested'] for u in out['unresolved']], out)
        self.assertEqual('needs_disambiguation', out['unresolved'][0]['status'])
        # 하나뿐인 이름이 모호하면 그 후보를 그대로 돌려준다.
        only = self.S.get_zone_sensor_summary(zone_ids=['1'])
        self.assertEqual('needs_disambiguation', only.get('status'), only)

    def test_list_plots_zone_name(self):
        amb = self.S.list_plots(zone_id='1')
        self.assertEqual('needs_disambiguation', amb.get('status'), amb)
        missing = self.S.list_plots(zone_id='없는곳')
        self.assertIn('No zone or site', missing.get('error', ''))
        ok = self.S.list_plots(zone_id='3-1')
        self.assertNotIn('error', ok)

    def test_plot_by_crop_name(self):
        row, err = self.S._read_plot('콩')
        self.assertIsNone(err)
        self.assertEqual('pl-kong', row.unique_id)
        row, err = self.S._read_plot('상추')
        self.assertIsNone(row)
        self.assertEqual('needs_disambiguation', err['status'])
        self.assertEqual({'pl-s1', 'pl-s2'},
                         {c['plot_id'] for c in err['candidates']})
        row, err = self.S._read_plot('없는작물')
        self.assertIn('콩', err['growing_plots'])

    def test_plot_named_like_a_crop_grown_elsewhere_is_ambiguous(self):
        """리뷰 재현(26-09-24): '고추' 는 한 구획의 **이름**이고 다른 구획의
        **작물**이다. 이름 칸에서 멈추면 앞 구획을 조용히 골랐다."""
        row, err = self.S._read_plot('고추')
        self.assertIsNone(row, '고르지 말아야 한다')
        self.assertEqual('needs_disambiguation', err['status'])
        by_id = {c['plot_id']: c for c in err['candidates']}
        self.assertEqual({'pl-named', 'pl-gochu'}, set(by_id))
        self.assertEqual('plot name', by_id['pl-named']['matched_by'])
        self.assertEqual('crop', by_id['pl-gochu']['matched_by'])
        self.assertTrue(all(c.get('where') for c in err['candidates']))
        self.assertTrue(any('never by id' in r for r in err['_reading']))
        # 같은 구획이 두 칸에 걸리면 한 후보다(이름=작물인 구획 하나).
        row, err = self.S._read_plot('옥수수')
        self.assertIsNone(err)
        self.assertEqual('pl-named', row.unique_id)

    def test_search_result_with_several_devices_is_not_guessed(self):
        row, _k, err = self.S._read_device(
            {'results': [{'id': 'out-a'}, {'id': 'out-v121'}]}, kinds=('output',))
        self.assertIsNone(row)
        self.assertEqual('needs_disambiguation', err['status'], err)
        self.assertEqual({'out-a', 'out-v121'}, {c['id'] for c in err['candidates']})
        self.assertTrue(all('where' in c for c in err['candidates']))
        row, kind, err = self.S._read_device({'results': [{'id': 'out-v121'}]})
        self.assertIsNone(err)
        self.assertEqual('out-v121', row.unique_id)
        # 센서가 섞여 있어도 출력 자리에는 출력 하나뿐이면 그것이다.
        row, _k, err = self.S._read_device(
            {'results': [{'id': 'in-temp'}, {'id': 'out-v121'}]}, kinds=('output',))
        self.assertIsNone(err)
        self.assertEqual('out-v121', row.unique_id)

    def test_zone_ids_are_capped_and_targets_listed_once(self):
        many = ['z%d' % i for i in range(11)]
        self.assertIn('At most 10',
                      self.S.get_zone_sensor_summary(zone_ids=many).get('error', ''))
        out = self.S.get_zone_sensor_summary(zone_ids=['없는1', '없는2'])
        self.assertEqual(2, len(out['unresolved']), out)
        self.assertTrue(all('available_targets' not in u for u in out['unresolved']))
        self.assertIn('available_targets', out)
        out = self.S.get_zone_sensor_summary(zone_ids=['3-1', '없는1'],
                                             measurement_type='co2')
        self.assertEqual(['없는1'], [u['requested'] for u in out['unresolved']], out)
        self.assertNotIn('available_targets', out['unresolved'][0])
        self.assertIn('available_targets', out)

    # ── 3. 여러 대상 ──────────────────────────────────────────────────────
    def test_output_state_batch(self):
        out = self.S.get_output_state(device_ids=['v121', 'v111', 'v121'])
        self.assertEqual(2, out['count'], '겹친 대상을 빼지 않았다')
        self.assertEqual(['v121', 'v111'], [r['requested'] for r in out['results']])
        self.assertEqual('needs_disambiguation', out['results'][1]['status'])
        self.assertNotIn('_reading', out['results'][1], '_reading 은 위로 모은다')
        self.assertTrue(out['_reading'])

    def test_batches_are_capped(self):
        many = ['x%d' % i for i in range(11)]
        for call in (lambda: self.S.get_output_state(device_ids=many),
                     lambda: self.S.get_sensor_detail(loc_ids=many),
                     lambda: self.S.get_plot(plot_ids=many),
                     lambda: self.S.search_notes_tool(target_names=many)):
            self.assertIn('At most 10', call().get('error', ''))

    def test_sensor_detail_and_plot_batches_answer_per_target(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        with mock.patch.object(S, '_sensor_detail_one',
                               classmethod(lambda cls, t, **k: {'got': t})):
            out = S.get_sensor_detail(loc_ids=['a', 'b'])
        self.assertEqual([{'requested': 'a', 'got': 'a'},
                          {'requested': 'b', 'got': 'b'}], out['results'])
        with mock.patch.object(S, '_plot_one',
                               classmethod(lambda cls, t, **k: {'plot': t})):
            out = S.get_plot(plot_ids=['콩', '상추'])
            self.assertEqual(2, out['count'])
            # 단수 인자는 예전 모양 그대로다.
            self.assertEqual({'plot': '콩'}, S.get_plot(plot_id='콩'))

    def test_search_notes_batch(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        with mock.patch.object(S, '_scope_for_target',
                               classmethod(lambda cls, name: ([], {'requested': name}))):
            out = S.search_notes_tool(target_names=['3-1', '콩'])
        self.assertEqual(['3-1', '콩'], [r['requested'] for r in out['results']])

    def test_native_sensor_reading_takes_names_and_lists(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        reading = [{'readings': [{'t': '2026-09-24T00:00:00+09:00', 'v': 21.5,
                                  'u': 'C'}]}]
        seen = []

        def fake(cls, loc_id=None, **k):
            seen.append(loc_id)
            return reading
        with mock.patch.object(S, 'get_sensor_detail', classmethod(fake)):
            one = N.execute('get_sensor_reading', {'device_id': '온습도_1'})
            both = N.execute('get_sensor_reading',
                             {'device_ids': ['온습도_1', 'v111']})
        self.assertEqual('in-temp', one['device_id'], one)
        self.assertEqual(21.5, one['value'])
        self.assertEqual('in-temp', seen[0])
        self.assertEqual(2, both['count'])
        self.assertEqual('needs_disambiguation', both['results'][1]['status'])

    def test_set_output_state_takes_a_name_but_never_guesses(self):
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        amb = N.execute('set_output_state', {'device_id': 'v111', 'state': 'on'})
        self.assertIs(False, amb.get('dispatched'), amb)
        self.assertEqual(2, len(amb.get('candidates') or []))
        sent = mock.MagicMock()
        sent.execute_action.return_value = {'status': 'success'}
        with mock.patch('aot.tools.providers.get', return_value=sent), \
                mock.patch('aot.aot_flask.access.write_scope.enforce'):
            ok = N.execute('set_output_state', {'device_id': 'v121', 'state': 'on'})
        self.assertEqual('success', ok.get('status'), ok)
        self.assertEqual('out-v121', sent.execute_action.call_args[0][1])

    # ── 4. 같은 이름 표시 (P7) ────────────────────────────────────────────
    def test_search_devices_marks_same_names(self):
        out = self.S.search_devices(query='v111')
        rows = [r for r in out['results'] if r.get('type') == 'output']
        self.assertEqual(2, len(rows), out)
        self.assertTrue(all(r.get('same_name_count') == 2 for r in rows))
        self.assertTrue(all(r.get('where') for r in rows))
        self.assertEqual([{'name': 'v111', 'count': 2}], out['same_name_groups'])
        self.assertTrue(any('same_name_groups' in r for r in out['_reading']))

    def test_unique_names_are_not_marked(self):
        out = self.S.search_devices(query='v121')
        self.assertNotIn('same_name_groups', out)
        self.assertTrue(all('same_name_count' not in r for r in out['results']))


    # ── 단계 확인 날짜 — 제안이 없으면 오늘로 채우지 않는다 ─────────────
    def test_confirm_stage_without_date_or_proposal_asks(self):
        from aot.aot_flask.geo import plot_context, plot_io
        with mock.patch.object(plot_context, 'stage_proposal', return_value=None), \
                mock.patch.object(plot_io, 'accept_stage') as accept:
            out = self.S.confirm_plot_stage(plot_id='pl-prog', stage_key='s2')
            pre = self.S.validate_confirm_plot_stage(plot_id='pl-prog',
                                                     stage_key='s2')
        self.assertEqual('error', out.get('status'), out)
        self.assertIn('started_on is required', out['message'])
        self.assertIn('started_on is required', pre['error'])
        accept.assert_not_called()

    def test_confirm_stage_uses_the_proposal_date_or_the_given_one(self):
        from aot.aot_flask.geo import plot_context, plot_io
        prop = {'stage_key': 's2', 'started_on': '2026-09-01'}
        with mock.patch.object(plot_context, 'stage_proposal', return_value=prop), \
                mock.patch.object(plot_io, 'accept_stage',
                                  return_value=({'ok': 1}, None)) as accept:
            self.assertEqual('success', self.S.confirm_plot_stage(
                plot_id='pl-prog', stage_key='s2')['status'])
            self.assertEqual('2026-09-01', accept.call_args.kwargs['started_on'])
            # 다른 단계를 확인하려면 날짜가 있어야 한다.
            self.assertIn('started_on is required', self.S.confirm_plot_stage(
                plot_id='pl-prog', stage_key='s3')['message'])
            self.assertEqual('success', self.S.confirm_plot_stage(
                plot_id='pl-prog', stage_key='s3',
                started_on='2026-08-20')['status'])
            self.assertEqual('2026-08-20', accept.call_args.kwargs['started_on'])
            self.assertIsNone(self.S.validate_confirm_plot_stage(
                plot_id='pl-prog', stage_key='s2'))


    def test_confirm_stage_passes_a_program_summary_not_a_row(self):
        """stage_proposal 은 program_brief 요약(dict|None)을 받는다.

        모델 행을 넘기면 .get 에서 터지고 그 예외가 삼켜져, 제안이 있어도 늘 날짜를
        되물었다(26-09-24 재검증에서 실데이터 20곳 중 12곳 재현)."""
        from aot.aot_flask.geo import plot_context, plot_io
        seen = {}

        def fake_proposal(row, program=None, **kw):
            seen['program'] = program
            assert program is None or isinstance(program, dict), type(program)
            return {'stage_key': 's2', 'started_on': '2026-09-01'}

        with mock.patch.object(plot_context, 'stage_proposal', side_effect=fake_proposal), \
                mock.patch.object(plot_io, 'accept_stage',
                                  return_value=({'ok': 1}, None)) as accept:
            out = self.S.confirm_plot_stage(plot_id='pl-prog', stage_key='s2')
        self.assertEqual('success', out['status'], out)
        self.assertIn('program', seen)
        self.assertEqual('2026-09-01', accept.call_args.kwargs['started_on'])

class TestMultiTargetCap(unittest.TestCase):
    """여러 대상 응답이 상한을 넘으면 대상 안의 행부터 줄인다(대상은 남긴다)."""

    def _reply(self, sizes):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        rows = {t: [{'t': '2026-09-24T00:%02d:00+09:00' % (i % 60),
                     'v': 20.0 + i / 7.0, 'id': 'row-%05d-%s' % (i, t)}
                    for i in range(n)] for t, n in sizes.items()}
        return S._for_each_target(list(sizes), lambda t: {'readings': rows[t]})

    def test_targets_survive_and_rows_are_thinned_per_target(self):
        from aot.tools import tool_execution as te
        out = te._cap_result(self._reply({'a': 400, 'b': 400, 'c': 20}),
                             'get_sensor_detail', max_tokens=6000)
        self.assertEqual(['a', 'b', 'c'], [r['requested'] for r in out['results']])
        self.assertEqual(3, out['count'])
        a, b, c = out['results']
        self.assertIn('readings_truncated', a)
        self.assertIn('readings_truncated', b)
        self.assertEqual(20, len(c['readings']), '작은 대상은 건드리지 않는다')
        self.assertNotIn('readings_truncated', c)
        # 큰 두 대상은 비슷한 몫을 받는다.
        self.assertLess(abs(len(a['readings']) - len(b['readings'])), 5)
        self.assertIn('INCOMPLETE', out['_truncated']['advice'])
        paths = {d['path'] for d in out['_truncated']['lists_trimmed']}
        self.assertEqual({'results[0].readings', 'results[1].readings'}, paths)
        self.assertLessEqual(te._estimate_tokens(json.dumps(out, ensure_ascii=False)),
                             6000)
        self.assertNotIn('_cap_priority', json.dumps(out))

    def test_small_reply_drops_the_hint(self):
        from aot.tools import tool_execution as te
        reply = self._reply({'a': 2, 'b': 2})
        reply['results'][0]['_cap_priority'] = {'drop_first': []}
        out = te._cap_result(reply, 'get_sensor_detail', max_tokens=6000)
        self.assertNotIn('_cap_priority', json.dumps(out))
        self.assertNotIn('_truncated', out)


class TestStageRuleInThePlotReply(unittest.TestCase):
    """P3: get_plot 응답이 두 단계 도구의 기준을 싣는다."""

    def test_rule_rides_the_reply(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        notes = S._plot_reading_notes({'stage_schedule': [], 'stage_proposal': None})
        text = ' '.join(notes)
        self.assertIn('confirm_plot_stage', text)
        self.assertIn('reschedule_plot_stage', text)
        self.assertIn("'stage_proposal' is null", text)
        notes = S._plot_reading_notes({'stage_schedule': [],
                                       'stage_proposal': {'stage_key': 's2'}})
        self.assertNotIn('is null', ' '.join(notes))


# ---------------------------------------------------------------------------
# 5. 인자 검증이 게이트보다 먼저 (P2) — 전체 앱(conftest 의 임시 DB)
# ---------------------------------------------------------------------------

from aot.tests.test_mcp_tool_profiles import OPS, _AppFixture  # noqa: E402


class TestArgumentsCheckedBeforeTheGate(_AppFixture):

    def setUp(self):
        super().setUp()
        from aot.databases.models import CustomController
        self.fn = CustomController(name='ProfTest bang', device='bang_bang',
                                   custom_options='{}', is_activated=False)
        self.db.session.add(self.fn)
        self.db.session.commit()
        self.fn_id = self.fn.unique_id
        self.role = self._auth(self._issue('Editor', 'full', OPS))

    def tearDown(self):
        from aot.databases.models import CustomController
        self.db.session.rollback()
        CustomController.query.filter_by(name='ProfTest bang').delete()
        self.db.session.commit()
        super().tearDown()

    def _call(self, tool, args, write_enabled='0'):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': write_enabled}):
            out = te._execute_tool(
                self.app, tool, dict(args), agent_id='user:proftest',
                role=self.role, scope_user_uuid=None, transport='mcp_http',
                tool_profile=mcp_auth.tool_profile_of(self.role))
        return json.loads(out[0]['text'])

    def test_unknown_option_key_is_named_even_in_advice_only_mode(self):
        out = self._call('modify_function_options',
                         {'function_id': self.fn_id,
                          'params': {'target_temp_day': 25}})
        self.assertEqual('invalid_arguments', out.get('reason_code'), out)
        self.assertIn('target_temp_day', out['message'])
        self.assertIn('setpoint', out['valid_keys'])
        self.assertIs(False, out.get('performed'))

    def test_invalid_option_value_is_named(self):
        out = self._call('modify_function_options',
                         {'function_id': self.fn_id,
                          'params': {'direction': 'sideways'}})
        self.assertEqual('invalid_arguments', out.get('reason_code'), out)
        self.assertIn('raise', out['message'])

    def test_valid_options_reach_the_gate(self):
        out = self._call('modify_function_options',
                         {'function_id': self.fn_id,
                          'params': {'setpoint': 24.5, 'direction': 'lower'}})
        self.assertEqual('write_disabled', out.get('reason_code'), out)
        # 조언 전용 거절은 묶음 전환을 권하지 않는다(벤치마크 lat_24).
        self.assertNotIn('Settings > Users > API keys', out['message'])
        self.assertIn('would not change it', out['message'])

    def test_combined_refusal_does_not_suggest_a_profile_switch(self):
        """인자 오류 + 조언 전용(also_refused) — lat_24 에서 모델이 받은 모양."""
        out = self._call('modify_function_options',
                         {'function_id': self.fn_id,
                          'params': {'target_temp_day': 25}})
        self.assertEqual('write_disabled', out.get('also_refused'), out)
        self.assertNotIn('Settings > Users > API keys', out['message'])
        self.assertIn('not this key', out['message'])

    def test_the_handler_itself_refuses_unknown_keys(self):
        """게이트를 지나는 경로(쓰기 허용)에서도 틀린 키가 저장되지 않는다."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.modify_function_options(self.fn_id, {'made_up': 1})
        self.assertIn('unknown option key', out.get('error', ''))
        self.db.session.expire_all()
        from aot.databases.models import CustomController
        row = CustomController.query.filter_by(unique_id=self.fn_id).first()
        self.assertNotIn('made_up', row.custom_options or '')

    def test_schema_checks_come_first_too(self):
        missing = self._call('operate_device', {'state': 'on'})
        self.assertEqual('invalid_arguments', missing.get('reason_code'), missing)
        self.assertIn('missing required argument(s): device_id', missing['message'])
        # 조언 전용 모드라 인자를 고쳐도 거절된다 — 같은 메시지에 적는다.
        self.assertEqual('write_disabled', missing.get('also_refused'), missing)
        self.assertIn('advice-only', missing['message'])
        typo = self._call('activate_function', {'function_id': 'x',
                                                'functon_idd': 1})
        self.assertEqual('invalid_arguments', typo.get('reason_code'), typo)
        self.assertIn("'functon_idd' (did you mean 'function_id'?)", typo['message'])
        self.assertIn('function_id', typo['valid_arguments'])
        plural = self._call('activate_function', {'function_ids': ['x']})
        self.assertIn("did you mean 'function_id'", plural['message'])

    def test_unrelated_unknown_keys_are_ignored_not_refused(self):
        """오타가 아닌 모르는 키는 거절하지 않는다 — 게이트가 평소대로 판정한다."""
        out = self._call('activate_function', {'function_id': self.fn_id,
                                               'bogus': 1})
        self.assertEqual('write_disabled', out.get('reason_code'), out)

    def test_client_meta_keys_run_as_before(self):
        """reason·title·confirm 을 싣는 클라이언트가 있다 — 조언 전용이면
        write_disabled, 쓰기 허용이면 승인 대기, 승인 면제 도구는 실행된다."""
        meta = {'reason': 'user asked', 'title': 'Pump', 'confirm': True}
        off = self._call('operate_device', dict(meta, device_id='v1', state='on'))
        self.assertEqual('write_disabled', off.get('reason_code'), off)
        pend = self._call('activate_function', dict(meta, function_id=self.fn_id),
                          write_enabled='1')
        self.assertEqual('awaiting_user', pend.get('reason_code'), pend)
        ran = self._call('modify_function_options',
                         dict(meta, function_id=self.fn_id,
                              params={'setpoint': 24.5}), write_enabled='1')
        self.assertNotEqual('invalid_arguments', ran.get('reason_code'), ran)
        self.assertNotEqual('refused', ran.get('status'), ran)
        self.assertEqual(['confirm', 'reason', 'title'],
                         ran.get('_ignored_arguments'), ran)

    def test_says_when_the_role_would_refuse_anyway(self):
        role = self._auth(self._issue('Monitor', 'full', OPS))
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '1'}):
            out = json.loads(te._execute_tool(
                self.app, 'operate_device', {'state': 'on'},
                agent_id='user:proftest', role=role, scope_user_uuid=None,
                transport='mcp_http',
                tool_profile=mcp_auth.tool_profile_of(role))[0]['text'])
        self.assertEqual('invalid_arguments', out.get('reason_code'), out)
        self.assertEqual('insufficient_role', out.get('also_refused'), out)
        self.assertIn('would be refused', out['message'])
        self.assertIn('write access', out['message'])
        # 쓰기가 허용되고 역할도 되면 덧붙이지 않는다.
        ok = self._call('operate_device', {'state': 'on'}, write_enabled='1')
        self.assertEqual('invalid_arguments', ok.get('reason_code'), ok)
        self.assertNotIn('also_refused', ok)

    def test_handlers_that_take_any_key_are_not_second_guessed(self):
        """옛 별칭(location)을 처리기가 읽는 도구는 이름 검사를 하지 않는다."""
        out = self._call('create_note', {'note': 'n', 'location': '3-1'})
        self.assertNotEqual('invalid_arguments', out.get('reason_code'), out)

    def test_values_the_handler_accepts_are_not_refused(self):
        """스키마 선택지는 on/off/set_value 지만 처리기는 open/close 도 받는다 —
        선택지로 거절하면 맞는 호출이 막힌다. 게이트까지 간다."""
        out = self._call('operate_device', {'device_id': 'v1', 'state': 'open'})
        self.assertEqual('write_disabled', out.get('reason_code'), out)

    def test_reads_are_not_checked_here(self):
        out = self._call('get_function_list', {'bogus': 1})
        self.assertNotEqual('invalid_arguments', out.get('reason_code'))


if __name__ == '__main__':
    unittest.main()
