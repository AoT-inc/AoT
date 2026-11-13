# coding=utf-8
"""도메인 틀의 기간 변환과 응답 모양 — 2026-10-14 claude.ai 웹 시험에서 나온 것.

고정하는 계약:
  1. 공통 낱말 `period` 는 안쪽 도구 인자로 **그대로 넘어가지 않는다** — 명부의
     `period_form` 모양으로 바뀐다(시험 A4: 예보에 hours='tomorrow' 가 그대로 가서
     "내일" 이 지금부터 24시간이 됐다). 모양이 없으면 명부 검사가 막는다.
  2. 응답에 틀이 어떤 대상·기간으로 읽었는지(`read_as`)가 실린다 — 대상 경로의
     맨 앞은 지도 이름이다(시험 A3: '육묘장' 이 어느 지도의 것인지 답에 없었다).
     안쪽 도구에는 그 칸이 가지 않는다.
  3. 장소 안의 장치를 목록 인자로 읽을 때 안쪽 상한(10)씩 나눠 전부 부른다
     (시험 B4: 19개 중 5개에서 멈췄다).
  4. 안쪽 응답의 다음 단계 안내가 이 표면에 없는 이름(use_tool: get_plot)이면
     도메인 operation 이름으로 바꾼다(시험 A2).
  5. 개요의 구획 목록은 잘라도 나머지 이름을 말한다(시험 A2: 13개 중 10개만).

결정론적 서버 테스트다(DB·모델 없이).
"""
import json
import unittest
from datetime import date, datetime
from unittest import mock

from aot.tools.domain.registry import Op


class PeriodToTest(unittest.TestCase):

    TODAY = date(2026, 10, 14)            # 수요일
    NOW = datetime(2026, 10, 14, 8, 30)

    def _to(self, form, text):
        from aot.tools.domain import vocab
        return vocab.period_to(form, text, today=self.TODAY, now=self.NOW)

    def test_forecast_words_become_start_and_hours(self):
        self.assertEqual({'start': '2026-10-15', 'hours': 24}, self._to('forecast', 'tomorrow')[0])
        self.assertEqual({'start': 'today', 'hours': 24}, self._to('forecast', 'today')[0])
        self.assertEqual({'hours': 168}, self._to('forecast', '7d')[0])
        self.assertEqual({'start': 'today', 'hours': 120},       # 수~일
                         self._to('forecast', 'this_week')[0])
        self.assertEqual({}, self._to('forecast', 'now')[0])
        self.assertEqual(336, self._to('forecast', '30d')[0]['hours'])
        with self.assertRaises(ValueError):
            self._to('forecast', 'yesterday')                     # 예보는 지난날이 아니다

    def test_past_forms(self):
        self.assertEqual({'value': '9h'}, self._to('lookback', 'today')[0])
        self.assertEqual({'value': '7d'}, self._to('lookback', '7d')[0])
        self.assertEqual({'value': '2d'}, self._to('lookback', 'yesterday')[0])
        self.assertEqual({'value': 3}, self._to('days', '2026-10-12')[0])
        self.assertEqual({'value': 'daily'}, self._to('span', 'today')[0])
        self.assertEqual({'value': 'weekly'}, self._to('span', 'this_week')[0])
        self.assertEqual({'value': 'monthly'}, self._to('span', '30d')[0])
        self.assertEqual({}, self._to('lookback', 'now')[0])
        with self.assertRaises(ValueError):
            self._to('lookback', 'tomorrow')
        with self.assertRaises(ValueError):
            self._to('days', 'gibberish')


class DateRangeTest(unittest.TestCase):
    """이력의 날짜 구간 — 지난주와 이번 주를 나란히 본다(2026-10-14 사용자 시험)."""

    TODAY = date(2026, 10, 14)

    def test_range_form(self):
        from aot.tools.domain import vocab
        to = lambda t: vocab.period_to('range', t, today=self.TODAY)[0]
        self.assertEqual({'value': '2026-10-01/2026-10-07'}, to('2026-10-01/2026-10-07'))
        self.assertEqual({'value': '2026-10-13/2026-10-13'}, to('yesterday'))
        self.assertEqual({'value': '2026-10-12/'}, to('this_week'))     # 오늘까지는 끝 없이
        self.assertEqual({'value': '2026-10-14/'}, to('today'))
        self.assertEqual({'value': '7d'}, to('7d'))
        self.assertEqual({}, to('now'))
        with self.assertRaises(ValueError):
            to('tomorrow')

    def test_time_range_takes_dates(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        self.assertEqual(('2026-10-01', '2026-10-07'), S._date_span('2026-10-01/2026-10-07'))
        self.assertEqual(('2026-10-01', '2026-10-01'), S._date_span('2026-10-01'))
        self.assertEqual(('2026-10-01', None), S._date_span('2026-10-01/'))
        self.assertEqual((None, None), S._date_span('7d'))

    def test_window_is_local_and_includes_the_end_day(self):
        import pytz
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        with mock.patch('aot.utils.timekit.tz_of',
                        lambda _id: pytz.timezone('Asia/Seoul')):
            w, err = S._detail_window('2026-10-01', '2026-10-07', 'x')
            self.assertIsNone(err)
            self.assertEqual('2026-09-30T15:00:00.000000Z', w['start_utc'])
            self.assertEqual('2026-10-07T15:00:00.000000Z', w['end_utc'])
            self.assertEqual('2026-10-08T00:00+09:00', w['period']['to'])
            for bad in (('2026-10-07', '2026-10-01'), (None, '2026-10-01'),
                        ('2026-01-01', '2026-12-31'), ('10/01', None)):
                self.assertEqual('bad_period', S._detail_window(*bad, 'x')[1]['reason_code'], bad)

    def test_history_passes_dates_to_the_inner_range_arguments(self):
        from aot.tools.domain import dispatch
        from aot.tools.domain.dispatch import META_KEY
        op = Op('measure', 'history', 'History', {'zone': 'get_sensor_detail'}, 'read',
                args={'period': 'time_range'}, target_arg={'zone': 'loc_id'},
                period_form='range')
        cat = lambda: {'get_sensor_detail': {'inputSchema': {'type': 'object', 'properties': {
            'loc_id': {'type': 'string'},
            'time_range': {'type': 'string', 'description': "'7d' or 'FROM/TO'"}}}}}
        with mock.patch.object(dispatch.targets, 'resolve', lambda ref, **kw: (
                'ok', {'kind': 'zone', 'id': 'Z', 'name': ref, 'path': ref})), \
                mock.patch('aot.tools.domain.contract.catalog', cat), \
                mock.patch.object(dispatch, 'today_at', lambda *_a: date(2026, 10, 14)):
            v = dispatch.plan('measure', {'op': 'history', 'target': '3-1',
                                          'period': '2026-10-01/2026-10-07'}, ops=[op])
        self.assertEqual('2026-10-01/2026-10-07', v[2]['time_range'])
        self.assertIn('both days', v[2][META_KEY]['period']['read'])


class PeriodContractTest(unittest.TestCase):

    def _cat(self):
        return {'get_weather_forecast': {'inputSchema': {'type': 'object', 'properties': {
            'place': {'type': 'string'}, 'start': {'type': 'string'},
            'hours': {'type': 'integer'}}}}}

    def _problems(self, op):
        from aot.tools.domain import contract
        return [p for p in contract.problems(ops=[op], cat=self._cat())
                if 'unmapped' not in p]

    def test_period_without_a_form_is_a_registry_problem(self):
        op = Op('weather', 'forecast', 'Forecast', {'none': 'get_weather_forecast'}, 'read',
                args={'at': 'start', 'period': 'hours'})
        self.assertTrue(any('period_form' in p for p in self._problems(op)))

    def test_form_must_fit_the_inner_argument(self):
        bad = Op('weather', 'forecast', 'Forecast', {'none': 'get_weather_forecast'}, 'read',
                 args={'at': 'start', 'period': 'hours'}, period_form='lookback')
        self.assertTrue(any('does not fit' in p for p in self._problems(bad)))
        good = Op('weather', 'forecast', 'Forecast', {'none': 'get_weather_forecast'}, 'read',
                  args={'at': 'start', 'period': 'hours'}, period_form='forecast')
        self.assertEqual([], self._problems(good))

    def test_the_real_registry_has_no_raw_period(self):
        from aot.tools.domain.registry_data import OPS
        for o in OPS:
            if 'period' in o.args:
                self.assertTrue(o.period_form, '%s.%s' % (o.tool, o.op))


def _cat():
    return {
        'get_weather_forecast': {'inputSchema': {'type': 'object', 'properties': {
            'place': {'type': 'string'}, 'start': {'type': 'string'},
            'hours': {'type': 'integer'}}}},
        'get_output_state': {'inputSchema': {'type': 'object', 'properties': {
            'device_ids': {'type': 'array', 'items': {'type': 'string'}}}}},
        'screen_action': {'inputSchema': {'type': 'object', 'properties': {
            'action': {'type': 'string'}, 'page': {'type': 'string'},
            'item': {'type': 'string'}, 'dashboard': {'type': 'string'}}}},
    }


_FORECAST = Op('weather', 'forecast', 'Forecast', {'site': 'get_weather_forecast'}, 'read',
               args={'at': 'start', 'period': 'hours'}, target_arg={'site': 'place'},
               period_form='forecast')
_STATE = Op('measure', 'output_state', 'State', {'output': 'get_output_state'}, 'read',
            target_arg={'output': 'device_ids'})
_SCREEN = Op('screen', 'act', 'Change the page', {'none': 'screen_action',
             'site': 'screen_action', 'dashboard': 'screen_action'}, 'screen',
             target_arg={'site': 'item', 'dashboard': 'dashboard'},
             extra_args={'action': 'what to do', 'page': 'page to open'})


class DispatchShapeTest(unittest.TestCase):

    def setUp(self):
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)
        p = mock.patch('aot.tools.domain.contract.catalog', _cat)
        p.start()
        self.addCleanup(p.stop)

    def _plan(self, tool, args, kind, **patches):
        from aot.tools.domain import dispatch
        res = lambda ref, **kw: ('ok', {'kind': kind, 'id': 'T', 'name': ref,
                                  'path': '영양 > ' + ref})
        with mock.patch.object(dispatch.targets, 'resolve', res), \
                mock.patch.object(dispatch, 'today_at', lambda *_a: date(2026, 10, 14)), \
                mock.patch.multiple(dispatch, **(patches or {'_LIST_CHUNK': 10})):
            return dispatch.plan(tool, args, ops=[_FORECAST, _STATE, _SCREEN])

    def test_forecast_period_reaches_the_inner_tool_translated(self):
        from aot.tools.domain.dispatch import META_KEY
        v = self._plan('weather', {'op': 'forecast', 'target': '3포장', 'period': 'tomorrow'},
                       'site')
        self.assertEqual(('call', 'get_weather_forecast'), v[:2])
        self.assertEqual('2026-10-15', v[2]['start'])
        self.assertEqual(24, v[2]['hours'])
        self.assertEqual('영양 > 3포장', v[2][META_KEY]['target']['path'])
        self.assertEqual('tomorrow', v[2][META_KEY]['period']['asked'])

    def test_bad_period_is_refused_before_calling(self):
        v = self._plan('weather', {'op': 'forecast', 'target': '3포장', 'period': 'yesterday'},
                       'site')
        self.assertEqual('refuse', v[0])
        self.assertIn('bad_period', v[1][0]['text'])

    def test_many_devices_are_read_in_chunks_not_cut(self):
        devs = [{'kind': 'output', 'id': 'o%d' % i, 'name': 'v%d' % i, 'path': 'v'}
                for i in range(19)]
        v = self._plan('measure', {'op': 'output_state', 'target': '김제'}, 'map',
                       _device_ids_in=lambda t: [d['id'] for d in devs],
                       _device_targets=lambda ids, kinds: devs)
        self.assertEqual(('fanout', 'get_output_state'), v[:2])
        sent = [i for _c, a in v[2] for i in a['device_ids']]
        self.assertEqual([d['id'] for d in devs], sent)
        self.assertTrue(all(len(a['device_ids']) <= 10 for _c, a in v[2]))
        self.assertNotIn('not_shown', v[3])

    def _screen_plan(self, args, resolve):
        from aot.tools.domain import dispatch
        seen = []

        def res(ref, accepts=(), only=None):
            seen.append(only)
            return resolve(ref, only)
        with mock.patch.object(dispatch.targets, 'resolve', res):
            return dispatch.plan('screen', args, ops=[_SCREEN]), seen

    def test_inner_slot_name_is_taken_as_the_target_of_that_kind(self):
        dash = {'kind': 'dashboard', 'id': 'D', 'name': '영양', 'path': 'dashboard > 영양'}
        v, seen = self._screen_plan(
            {'op': 'act', 'action': 'navigate', 'page': 'dashboard', 'dashboard': '영양'},
            lambda ref, only: ('ok', dash))
        self.assertEqual(('call', 'screen_action'), v[:2])
        self.assertEqual('D', v[2]['dashboard'])
        self.assertEqual([{'dashboard'}], seen)
        v, _ = self._screen_plan({'op': 'act', 'target': '영양', 'dashboard': '영양'},
                                 lambda ref, only: ('ok', dash))
        self.assertIn('target_given_twice', v[1][0]['text'])

    def test_action_decides_which_kinds_the_target_can_be(self):
        """modal_tab 의 `tab` 은 열린 지도 창의 탭 이름이다 — 틀이 푸는 대상이 아니다
        (2026-10-14 사용자 시험: '영양' 이 입력 탭으로 풀려 그 id 가 창 탭 칸에 들어갔다)."""
        from aot.tools.domain import dispatch
        op = Op('screen', 'act', 'Change the page', {'none': 'screen_action',
                'dashboard': 'screen_action', 'tab': 'screen_action'}, 'screen',
                target_arg={'dashboard': 'dashboard', 'tab': 'tab'},
                extra_args={'action': 'what to do', 'page': 'page to open'},
                kinds_by_arg={'action': {'navigate': ('dashboard', 'tab'), 'modal_tab': ()}})
        cands = [{'kind': 'dashboard', 'id': 'D', 'name': '영양', 'path': 'dashboard > 영양'},
                 {'kind': 'tab', 'id': 'T', 'name': '영양', 'path': 'input tabs > 영양'}]
        seen = []

        def res(ref, accepts=(), only=None):
            seen.append(only)
            return 'ambiguous', cands
        with mock.patch.object(dispatch.targets, 'resolve', res):
            v = dispatch.plan('screen', {'op': 'act', 'action': 'modal_tab',
                                         'target': '영양'}, ops=[op])
            self.assertIn('target_not_taken', v[1][0]['text'])
            self.assertIn('navigate', v[1][0]['text'])           # 어디로 가야 하는지
            v = dispatch.plan('screen', {'op': 'act', 'action': 'modal_tab',
                                         'tab': '환경'}, ops=[op])
            self.assertEqual(('call', 'screen_action'), v[:2])
            self.assertEqual('환경', v[2]['tab'])                  # 글자 그대로
            self.assertEqual([], seen)                             # 풀지 않았다
            v = dispatch.plan('screen', {'op': 'act', 'action': 'navigate',
                                         'target': '영양'}, ops=[op])
            self.assertEqual([{'dashboard', 'tab'}], seen)
            # 2026-10-26: 이동은 같은 이름이 대시보드와 탭에 있으면 되묻지 않고 대시보드로 간다 — 탭 후보는 why 로 남는다.
            self.assertEqual(('call', 'screen_action'), v[:2])
            self.assertEqual('D', v[2]['dashboard'])
            self.assertIn('input tabs > 영양', v[2]['_domain_meta']['why'])

    def test_screen_act_help_card_carries_the_action_target_pairs(self):
        """2026-10-28 점검: 필지=open_map_item·대시보드=navigate·위젯=highlight 짝과 modal_tab 의 tab 이
        help 에 없었다. 목록 설명이 아니라 help 카드에만 싣는다."""
        from aot.tools.domain import dispatch
        card = dispatch.help_card('screen.act')
        pairs = card['action_target_pairs']
        self.assertIn('action=navigate (dashboard, tab)', pairs)
        self.assertIn('action=open_map_item (site, zone, facility, plot', pairs)
        self.assertIn('action=highlight (widget', pairs)
        self.assertIn('`tab`', pairs)
        self.assertIn('target_slots', card['same_name_many_kinds'])
        self.assertNotIn('action_target_pairs', dispatch.help_card('find.resolve'))

    def test_navigate_with_a_map_item_says_what_to_send_next(self):
        """navigate + 지도 위 대상(2026-10-14 '김제 > 3포장') → 거절 + 다시 보낼 호출.
        대시보드는 그대로 실행, 자동으로 고쳐 실행하지는 않는다."""
        site = {'kind': 'site', 'id': 'S', 'name': '3포장', 'path': '김제 > 3포장'}
        dash = {'kind': 'dashboard', 'id': 'D', 'name': '영양', 'path': 'dashboard > 영양'}

        def res(ref, only):
            if only and 'site' not in only:
                return 'none', {"error": "'3포장' is a site, not a dashboard or tab."}
            return 'ok', site
        def plan(args, resolve):
            op = Op('screen', 'act', 'Change the page', {'none': 'screen_action',
                    'site': 'screen_action', 'dashboard': 'screen_action'}, 'screen',
                    target_arg={'site': 'item', 'dashboard': 'dashboard'},
                    extra_args={'action': 'what to do', 'page': 'page to open',
                                'screen': 'From get_screen'},
                    kinds_by_arg={'action': {'navigate': ('dashboard', 'tab'),
                                             'open_map_item': ('site', 'zone')}})
            from aot.tools.domain import dispatch
            with mock.patch.object(dispatch.targets, 'resolve',
                                   lambda ref, accepts=(), only=None: resolve(ref, only)):
                return dispatch.plan('screen', args, ops=[op]), None
        v, _ = plan({'op': 'act', 'action': 'navigate', 'page': 'map',
                     'target': '김제 > 3포장'}, res)
        self.assertEqual('refuse', v[0])
        body = json.loads(v[1][0]['text'])
        self.assertIn("is a site, not a dashboard or tab.", body['message'])
        self.assertIn('open_map_item', body['next']['resend'])
        self.assertIn('김제 > 3포장', body['next']['resend'])
        # 화면이 둘 이상이면 안쪽이 고르지 못한다 — 찾는 법을 한 줄 덧붙인다(값은 못 넣는다).
        self.assertIn("add screen='<id>'", body['next']['why'])
        self.assertIn('screen_view op=current', body['next']['why'])
        self.assertEqual({'why', 'resend'}, set(body['next']))
        v, _ = plan({'op': 'act', 'action': 'navigate', 'page': 'dashboard',
                     'target': '영양'}, lambda ref, only: ('ok', dash))
        self.assertEqual(('call', 'screen_action'), v[:2])
        v, _ = plan({'op': 'act', 'action': 'navigate', 'target': 'x'},
                    lambda ref, only: ('none', {"error": "No dashboard or tab named 'x'."}))
        # 없는 대상에는 찾는 길 한 줄을 싣는다(2026-11-07 오류 안내) — 고쳐서 다시 보낼 호출(`resend`)은 아니다.
        self.assertEqual({'call'}, set(json.loads(v[1][0]['text'])['next']))

    def test_write_drops_candidates_of_kinds_it_cannot_take(self):
        cands = [{'kind': 'map', 'id': 'M', 'name': '영양', 'path': '영양'},
                 {'kind': 'dashboard', 'id': 'D', 'name': '영양', 'path': 'dashboard > 영양'}]
        v, _ = self._screen_plan({'op': 'act', 'action': 'navigate', 'page': 'dashboard',
                                  'target': '영양'}, lambda ref, only: ('ambiguous', cands))
        self.assertEqual('call', v[0], v)
        self.assertEqual('D', v[2]['dashboard'])

    def test_kind_said_in_the_call_narrows_the_candidates(self):
        cands = [{'kind': 'dashboard', 'id': 'D', 'name': '영양', 'path': 'dashboard > 영양'},
                 {'kind': 'site', 'id': 'S', 'name': '영양', 'path': '영양 > 영양'}]
        v, _ = self._screen_plan({'op': 'act', 'action': 'navigate', 'page': 'dashboard',
                                  'target': '영양'}, lambda ref, only: ('ambiguous', cands))
        self.assertEqual('D', v[2]['dashboard'])
        dash = {'kind': 'dashboard', 'id': 'D', 'name': 'x', 'path': 'p'}
        v, seen = self._screen_plan({'op': 'act', 'target': 'x', 'kind': 'dashboard'},
                                    lambda ref, only: ('ok', dash))
        self.assertEqual([{'dashboard'}], seen)
        self.assertNotIn('kind', v[2])                    # 안쪽 kind 는 지도 대상용이다

    def test_read_keeps_only_directly_accepted_candidates(self):
        from aot.tools.domain import dispatch
        cands = [{'kind': 'zone', 'id': 'Z', 'name': '장미원', 'path': '임실군 > 장미원'},
                 {'kind': 'output', 'id': 'O1', 'name': '장미원 밸브 1', 'path': 'p'},
                 {'kind': 'output', 'id': 'O2', 'name': '장미원 밸브 2', 'path': 'p'}]
        op = Op('find', 'plots', 'Plots', {'none': 'list_plots', 'zone': 'list_plots'},
                'read', target_arg={'zone': 'zone_id'})
        with mock.patch.object(dispatch.targets, 'resolve',
                               lambda ref, **kw: ('ambiguous', cands)), \
                mock.patch('aot.tools.domain.contract.catalog', lambda: {
                    'list_plots': {'inputSchema': {'type': 'object', 'properties': {
                        'zone_id': {'type': 'string'}}}}}):
            v = dispatch.plan('find', {'op': 'plots', 'target': '장미'}, ops=[op])
        self.assertEqual(('call', 'list_plots'), v[:2])
        self.assertEqual('Z', v[2]['zone_id'])

    def test_read_of_matches_all_in_one_place_reads_that_place(self):
        from aot.tools.domain import dispatch
        site = {'kind': 'site', 'id': 'S', 'name': '붕어섬생태공원', 'path': '임실군 > 붕어섬생태공원'}
        cands = [{'kind': 'device', 'id': 'v%d' % i, 'name': 'v장미0%d' % i, 'path': 'p'}
                 for i in range(3)]
        op = Op('find', 'plots', 'Plots', {'none': 'list_plots', 'site': 'list_plots'},
                'read', target_arg={'site': 'zone_id'})
        cat = lambda: {'list_plots': {'inputSchema': {'type': 'object', 'properties': {
            'zone_id': {'type': 'string'}}}}}
        got = {}
        # 셋 다 같은 대지 안 → 그 대지를 읽는다. 하나라도 놓인 곳을 모르면 되묻는다.
        for name, anc in (('all', lambda c: [site]),
                          ('one_unknown', lambda c: [] if c['id'] == 'v2' else [site])):
            with mock.patch.object(dispatch.targets, 'resolve',
                                   lambda ref, **kw: ('ambiguous', cands)), \
                    mock.patch.object(dispatch, '_ancestors', anc), \
                    mock.patch('aot.tools.domain.contract.catalog', cat):
                got[name] = dispatch.plan('find', {'op': 'plots', 'target': '장미'}, ops=[op])
        self.assertEqual(('call', 'list_plots'), got['all'][:2])
        self.assertEqual('S', got['all'][2]['zone_id'])
        self.assertIn('all 3 matches', got['all'][2][dispatch.META_KEY]['why'])
        self.assertEqual('refuse', got['one_unknown'][0])

    def test_read_as_is_not_attached_to_a_refusal_from_inside(self):
        from aot.tools.domain import dispatch
        out = [{'type': 'text', 'text': json.dumps({'status': 'error', 'error': 'widget is required'})}]
        body = json.loads(dispatch._annotate(out, {'target': {'name': '온습도_1'}})[0]['text'])
        self.assertNotIn('read_as', body)
        out = [{'type': 'text', 'text': json.dumps({'status': 'success'})}]
        body = json.loads(dispatch._annotate(out, {'target': {'name': '온습도_1'}})[0]['text'])
        self.assertIn('read_as', body)

    def test_help_period_matches_the_list_and_says_how_this_op_reads_it(self):
        from aot.tools.domain import dispatch
        from aot.tools.domain.surface import VOCAB_SCHEMA
        with mock.patch('aot.tools.tool_registry.approval_required_tools', lambda: ()):
            card = dispatch.help_card('weather.forecast', ops=[_FORECAST])
        doc = card['shared_args']['period']
        self.assertEqual(VOCAB_SCHEMA['period']['description'], doc['description'])
        self.assertIn('today or later', doc['here'])

    def test_help_names_the_target_slots(self):
        from aot.tools.domain import dispatch
        with mock.patch('aot.tools.tool_registry.approval_required_tools', lambda: ()):
            card = dispatch.help_card('screen.act', ops=[_SCREEN])
        self.assertEqual({'item': ['site'], 'dashboard': ['dashboard']}, card['target_slots'])

    def test_refusals_are_recorded(self):
        from aot.tools.domain import dispatch
        rec = []
        with mock.patch('aot.mcp_server.audit.record_call',
                        lambda **kw: rec.append(kw)), \
                mock.patch.object(dispatch, '_ops', lambda: [_SCREEN]):
            dispatch._run(None, 'screen', {'op': 'act', 'speed': 3}, {'agent_id': 'a'})
        self.assertEqual('screen.act', rec[0]['tool_name'])
        self.assertEqual('unknown_argument', rec[0]['result_summary'])

    def test_place_taking_reads_expand_a_map_to_places_not_devices(self):
        """예보·개요처럼 장소를 받는 읽기에 지도가 오면 안의 장소로 펼친다 — 장치마다
        또는 '대상 없음(농장 전체)' 으로 빠지지 않는다(2026-10-14: '영양' 개요가 농장 전체)."""
        op = Op('weather', 'forecast', 'Forecast', {'none': 'get_weather_forecast',
                'site': 'get_weather_forecast', 'device': 'get_weather_forecast'}, 'read',
                target_arg={'site': 'place', 'device': 'place'})
        site = {'kind': 'site', 'id': 'S1', 'name': '육묘장 대지', 'path': '영양 > 육묘장 대지'}
        dev = {'kind': 'device', 'id': 'D1', 'name': 'x', 'path': 'p'}
        from aot.tools.domain import dispatch
        res = lambda ref, **kw: ('ok', {'kind': 'map', 'id': 'M', 'name': ref, 'path': ref})
        with mock.patch.object(dispatch.targets, 'resolve', res), \
                mock.patch.multiple(dispatch, _descendants=lambda t: [site],
                                    _device_ids_in=lambda t: ['D1'],
                                    _device_targets=lambda ids, kinds: [dev]):
            v = dispatch.plan('weather', {'op': 'forecast', 'target': '영양'}, ops=[op])
        self.assertEqual(('fanout', 'get_weather_forecast'), v[:2])
        self.assertEqual('S1', v[2][0][1]['place'])

    def test_meta_never_reaches_the_inner_tool(self):
        from aot.tools.domain import dispatch
        seen = []

        def fake_execute(app, name, args, **ctx):
            seen.append(dict(args))
            return [{'type': 'text', 'text': json.dumps(
                {'status': 'success', '_more': 'Detail via use_tool: get_plot (one plot)'})}]
        res = lambda ref, **kw: ('ok', {'kind': 'site', 'id': 'T', 'name': ref,
                                  'path': '영양 > ' + ref})
        with mock.patch('aot.tools.tool_execution._execute_tool', fake_execute), \
                mock.patch.object(dispatch.targets, 'resolve', res), \
                mock.patch.object(dispatch, '_ops', lambda: [_FORECAST, _STATE]), \
                mock.patch.object(dispatch, 'today_at', lambda *_a: date(2026, 10, 14)):
            dispatch._INNER_TO_OP.clear()
            dispatch._INNER_TO_OP['get_plot'] = 'detail.plot'
            try:
                out = dispatch._run(None, 'weather', {'op': 'forecast', 'target': '육묘장',
                                                      'period': 'tomorrow'}, {})
            finally:
                dispatch._INNER_TO_OP.clear()
        self.assertNotIn(dispatch.META_KEY, seen[0])
        body = json.loads(out[0]['text'])
        self.assertEqual('영양 > 육묘장', body['read_as']['target']['path'])
        self.assertIn('detail.plot', body['_more'])
        self.assertNotIn('use_tool', body['_more'])


class ScreenOutcomeTest(unittest.TestCase):
    """화면 조작의 응답이 실제로 한 일을 말한다(2026-10-14 사용자 시험)."""

    def _S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    def test_highlight_fallback_is_partial_not_success(self):
        row = {'status': 'done', 'action': 'highlight',
               'args': json.dumps({'pin': True, 'describe': "highlight '육묘장'"}),
               'result': json.dumps({'message': '@@{"highlighted": "widget", '
                                                '"highlight_note": "no pin"}@@'})}
        out = self._S()._screen_action_outcome(row)
        self.assertEqual('partial', out['status'])
        self.assertIn('whole map widget', out['done'])
        row['result'] = json.dumps({'message': '@@{"highlighted": "pin"}@@'})
        self.assertEqual('success', self._S()._screen_action_outcome(row)['status'])

    def test_navigate_says_what_it_did_not_use(self):
        got = self._S()._screen_unused('navigate', item='장미원', kind=None, widget=None,
                                       value=None)
        self.assertEqual(['item'], got['args'])
        self.assertIn('open_map_item', got['note'])
        self.assertIsNone(self._S()._screen_unused('highlight', item='x'))


class SchemaCarriesNeededArgsTest(unittest.TestCase):
    """모델은 스키마에 없는 인자를 넣지 않는다 — 동작에 꼭 필요한 고유 인자는 스키마에
    있어야 한다(2026-10-14 사용자 시험: action 을 넣을 자리가 없어 화면 이동이 안 됐다)."""

    def _entry(self, tool, op):
        from aot.tools.domain import surface
        ent = surface.entries([op], lambda n: True, set())
        return next(e for e in ent if e['name'] == tool)

    def test_shown_args_are_in_the_schema_without_being_required(self):
        op = Op('screen', 'act', 'Change the page', {'none': 'screen_action'}, 'screen',
                extra_args={'action': 'navigate|highlight', 'page': 'dashboard|map',
                            'layer': 'map layer'}, shown=('action', 'page'))
        e = self._entry('screen', op)
        props = e['inputSchema']['properties']
        self.assertIn('action', props)
        self.assertIn('page', props)
        self.assertNotIn('layer', props)                 # 나머지는 help 로
        self.assertEqual(['op'], e['inputSchema']['required'])
        self.assertIn("help(target='screen.<op>')", e['description'])

    def test_real_screen_and_edit_ops_list_what_they_need(self):
        from aot.tools.domain.registry_data import OPS
        ops = {(o.tool, o.op): o for o in OPS}
        self.assertTrue({'action', 'page', 'confirm_token'} <= set(ops[('screen', 'act')].shown))
        for arg in ('kind', 'params', 'options'):
            self.assertIn(arg, ops[('configure', 'edit')].shown, arg)
        # 노트 고치기의 바꿀 본문은 공통 어휘 `text` 라 스키마에 늘 실린다(2026-11-03 재설계 PR 2).
        self.assertEqual('note', ops[('record', 'note')].args['text'])

    def test_shown_must_name_an_extra_arg(self):
        from aot.tools.domain import contract
        bad = Op('screen', 'act', 'x', {'none': 'screen_action'}, 'screen', shown=('nope',))
        self.assertTrue(any('shown arg' in p for p in contract.problems(
            ops=[bad], cat={'screen_action': {'inputSchema': {'properties': {}}}})))


class FrameFollowTest(unittest.TestCase):
    """읽기가 대상 하나를 풀면 그것을 화면(지도 위젯)에 연다 — 안쪽 도구 이름과 무관하게
    (2026-10-14 사용자: 지도 위젯에서라고 해도 텍스트로만 설명했다)."""

    def setUp(self):
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)

    def _run(self, tool, args, ops, resolve, inner_body):
        from aot.tools.domain import dispatch
        inner_calls, follows = [], []

        def fake_execute(app, name, a, **ctx):
            inner_calls.append(dict(a))
            return [{'type': 'text', 'text': json.dumps(inner_body)}]

        def fake_follow(kind, ident, user, profile, transport, show=None, trace=None, session_key=None):
            follows.append((kind, ident, show))
            return {'opened': '%s %s' % (kind, ident)}
        cat = lambda: {'get_sensor_detail': {'inputSchema': {'type': 'object', 'properties': {
            'loc_id': {'type': 'string'}}}},
            'list_plots': {'inputSchema': {'type': 'object', 'properties': {
                'zone_id': {'type': 'string'}, 'query': {'type': 'string'}}}},
            'create_note': {'inputSchema': {'type': 'object', 'properties': {
                'target_id': {'type': 'string'}, 'note': {'type': 'string'}}}}}
        with mock.patch('aot.tools.tool_execution._execute_tool', fake_execute), \
                mock.patch('aot.tools.screen_follow.follow_resolved', fake_follow), \
                mock.patch('aot.tools.domain.contract.catalog', cat), \
                mock.patch.object(dispatch.targets, 'resolve', resolve), \
                mock.patch.object(dispatch, '_ops', lambda: ops):
            out = dispatch._run(None, tool, args, {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        return json.loads(out[0]['text']), inner_calls, follows

    _HIST = Op('measure', 'history', 'History', {'zone': 'get_sensor_detail'}, 'read',
               target_arg={'zone': 'loc_id'})
    _ZONE = staticmethod(lambda ref, **kw: ('ok', {'kind': 'zone', 'id': 'Z', 'name': ref,
                                                    'path': '김제 > ' + ref}))

    def test_any_read_follows_its_resolved_target_once(self):
        body, inner, follows = self._run('measure', {'op': 'history', 'target': '3-1'},
                                         [self._HIST], self._ZONE, {'status': 'success'})
        self.assertEqual([('zone', 'Z', None)], follows)
        self.assertEqual('off', inner[0]['_show_on_screen'])     # 안쪽은 따라가지 않는다
        self.assertEqual({'opened': 'zone Z'}, body['screen'])

    def test_show_off_and_failures_do_not_follow(self):
        _b, _i, follows = self._run('measure', {'op': 'history', 'target': '3-1',
                                                '_show_on_screen': 'off'},
                                    [self._HIST], self._ZONE, {'status': 'success'})
        self.assertEqual([('zone', 'Z', 'off')], follows)       # 끔은 따라가기가 판정
        _b, _i, follows = self._run('measure', {'op': 'history', 'target': '3-1'},
                                    [self._HIST], self._ZONE, {'status': 'error', 'error': 'x'})
        self.assertEqual([], follows)

    def test_writes_do_not_follow(self):
        op = Op('record', 'note_add', 'Note', {'zone': 'create_note'}, 'record',
                args={'value': 'note'}, target_arg={'zone': 'target_id'})
        with mock.patch('aot.tools.mcp_safety_gate.classify_permission', lambda n: 'write'):
            _b, inner, follows = self._run('record', {'op': 'note_add', 'target': '3-1',
                                                      'value': 'x'}, [op], self._ZONE,
                                           {'status': 'success'})
        self.assertEqual([], follows)
        self.assertNotIn('_show_on_screen', inner[0])

    def test_single_result_without_a_target_is_followed(self):
        op = Op('find', 'plots', 'Plots', {'none': 'list_plots'}, 'read', args={'query': 'query'})
        body, _i, follows = self._run('find', {'op': 'plots', 'query': '검정콩'}, [op],
                                      self._ZONE, {'plots': [{'unique_id': 'P1'}], 'count': 1})
        self.assertEqual([('plot', 'P1', None)], follows)

    def test_crops_of_a_facility_with_one_plot_open_the_plot(self):
        """2026-10-28 점검: 육묘장3 의 작물을 묻자 화면에는 시설이 떴다 — 작물을 본 사람은 그 구획을 보려는 것이다.
        구획이 여럿이면 하나를 고르지 않고 시설 그대로."""
        op = Op('overview', 'crops', 'Crops', {'facility': 'list_plots'}, 'read',
                target_arg={'facility': 'zone_id'})
        fac = staticmethod(lambda ref, **kw: ('ok', {'kind': 'facility', 'id': 'F', 'name': ref,
                                                     'path': ref}))
        one = {'facility_bay_plots': [{'unique_id': 'P1'}]}
        _b, _i, follows = self._run('overview', {'op': 'crops', 'target': '육묘장3'}, [op], fac, one)
        self.assertEqual([('plot', 'P1', None)], follows)
        many = {'facility_bay_plots': [{'unique_id': 'P1'}, {'unique_id': 'P2'}]}
        _b, _i, follows = self._run('overview', {'op': 'crops', 'target': '육묘장3'}, [op], fac, many)
        self.assertEqual([('facility', 'F', None)], follows)

    def test_screen_target_alone_picks_the_action_by_kind(self):
        from aot.tools.domain import dispatch
        op = Op('screen', 'act', 'Show', {'plot': 'screen_action', 'widget': 'screen_action',
                'dashboard': 'screen_action'}, 'screen',
                target_arg={'plot': 'item', 'widget': 'widget', 'dashboard': 'dashboard'},
                extra_args={'action': 'a', 'page': 'p'},
                defaults_by_kind={'plot': {'action': 'open_map_item'},
                                  'widget': {'action': 'highlight'},
                                  'dashboard': {'action': 'navigate', 'page': 'dashboard'}})
        cat = lambda: {'screen_action': {'inputSchema': {'type': 'object', 'properties': {
            'action': {'type': 'string'}, 'page': {'type': 'string'}, 'item': {'type': 'string'},
            'widget': {'type': 'string'}, 'dashboard': {'type': 'string'}}}}}
        got = {}
        for kind in ('plot', 'widget', 'dashboard'):
            with mock.patch.object(dispatch.targets, 'resolve', lambda ref, kind=kind, **kw: (
                    'ok', {'kind': kind, 'id': 'X', 'name': ref, 'path': ref})), \
                    mock.patch('aot.tools.domain.contract.catalog', cat):
                got[kind] = dispatch.plan('screen', {'op': 'act', 'target': 'x'}, ops=[op])[2]
                explicit = dispatch.plan('screen', {'op': 'act', 'target': 'x',
                                                    'action': 'open_notes'}, ops=[op])[2]
            self.assertEqual('open_notes', explicit['action'])        # 준 것이 이긴다
        self.assertEqual('open_map_item', got['plot']['action'])
        self.assertEqual('highlight', got['widget']['action'])
        self.assertEqual(('navigate', 'dashboard'), (got['dashboard']['action'],
                                                     got['dashboard']['page']))


class FollowResolvedGateTest(unittest.TestCase):

    def test_gates_are_the_same_as_follow(self):
        from aot.tools import screen_follow
        self.assertIsNone(screen_follow.follow_resolved('zone', 'Z', 'u', 'operations',
                                                        'in_app'))       # 인앱 AI 는 제외
        self.assertIsNone(screen_follow.follow_resolved('zone', 'Z', None, 'operations',
                                                        'mcp_http'))     # 사람 없음
        with mock.patch('aot.tools.tool_registry.tool_in_profile', lambda n, p: True):
            self.assertIsNone(screen_follow.follow_resolved(
                'zone', 'Z', 'u', 'operations', 'mcp_http', show='off'))
        self.assertLess(len(screen_follow._WHY), 120)   # 따라갈 때마다 대화에 남는다


class OverviewPlotsTest(unittest.TestCase):

    def test_rest_of_the_list_is_named_not_dropped(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        plots = [{'subject': '콩 %d구' % i, 'zone_name': '3-%d' % (1 + i % 2)}
                 for i in range(13)]
        with mock.patch.object(S, 'list_plots', classmethod(
                lambda cls, **kw: {'plots': plots[:kw.get('limit') or 13],
                                   'total_matched': 13})):
            out = S._overview_plots(mock.Mock(unique_id='s'), brief=False)
        self.assertEqual(13, out['count'])
        self.assertEqual(10, len(out['items']))
        self.assertEqual(3, len(out['others']))
        self.assertIn('콩 12구', out['others'][-1])
        self.assertNotIn('not_listed', out)


if __name__ == '__main__':
    unittest.main()


class ApprovalFlowTest(unittest.TestCase):
    """승인 대기 → 사용자 승인 → 같은 operation 다시(2026-10-14 사용자 시험: 공지 작성이
    승인 대기만 두 번 쌓였다 — 안내는 옛 이름이었고, 다시 부른 호출의 `_confirmation_id`
    를 틀이 버렸다)."""

    _NOTICE = Op('record', 'notice_add', 'Post a notice', {'none': 'create_notice'},
                 'record', extra_args={'title': 'title', 'body': 'body'})

    def setUp(self):
        from aot.tools.domain import contract
        contract._STATE.update(ok=True, problems=[])
        self.addCleanup(contract._STATE.clear)

    def test_confirmation_id_reaches_the_inner_tool(self):
        from aot.tools.domain import dispatch
        v = dispatch.plan('record', {'op': 'notice_add', 'title': 't', 'body': 'b',
                                     '_confirmation_id': 'C1', '_agent_id': 'spoof'},
                          ops=[self._NOTICE])
        self.assertEqual(('call', 'create_notice'), v[:2])
        self.assertEqual('C1', v[2]['_confirmation_id'])
        self.assertNotIn('_agent_id', v[2])                 # 그것은 서버가 정한다

    def test_pending_reply_names_this_surfaces_next_steps(self):
        from aot.tools.domain import dispatch
        pending = [{"type": "text", "text": json.dumps({
            "status": "pending_approval", "confirmation_id": "C1",
            "message": "... call respond_to_confirmation ..."})}]
        out = dispatch._approval_next(pending, 'record',
                                      {'op': 'notice_add', 'title': 't', 'body': 'b'})
        body = json.loads(out[0]['text'])
        self.assertIn("control(op='confirm', target='C1'", body['next']['2_answer'])
        self.assertIn("record(op='notice_add'", body['next']['3_run'])
        self.assertIn("_confirmation_id='C1'", body['next']['3_run'])
        self.assertEqual({'title': 't', 'body': 'b'}, body['next']['same_arguments'])
        self.assertNotIn('respond_to_confirmation', body['message'])
        done = [{"type": "text", "text": json.dumps({"status": "success"})}]
        self.assertIs(done, dispatch._approval_next(done, 'record', {'op': 'notice_add'}))
