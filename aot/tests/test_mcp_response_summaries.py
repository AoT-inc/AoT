# coding=utf-8
"""MCP 응답 요약(2026-09-29) — 컨텍스트 초과의 주원인이 응답 크기라는 벤치
실측(list_plots/get_plot/get_control_state 등, `.local/bench/runs/*_prof_*`)에
따라 기본 응답을 줄인 도구들의 계약을 고정한다.

  1. list_plots/get_crop_status: 목록마다 기본 상한(10)을 두고, 넘으면
     `truncated`+참값 카운트를 남긴다 — 잘라도 몇 건이 더 있는지는 안다.
  2. get_control_state: `detail=False`(기본)면 코디네이터의 `tolerance`/
     `priority`(설정값)와 `latest_cycle_summary`의 화면 전용 진단값
     (greybox_skill 등), 구획의 `timeline.stages`(전체 단계 일정)를 뺀다.
     `_omitted` 로 무엇을 뺐는지 말하고, `detail=True` 면 원본 그대로 낸다.
  3. get_function_list: 같은 `function_type` 을 항목마다 반복하지 않고
     타입별로 묶는다. null 필드는 아예 싣지 않는다.
  4. search_schedule: 상한을 넘으면 `truncated`, 항목이 전부 같은 tz 면
     위로 올린다, `target_id`(raw uuid)는 안 싣는다.
  5. get_sensor_detail: 채널이 여럿이면(sensor_type 을 안 좁힌 경우) 채널당
     기본 보관 건수를 20 → 5 로 낮춘다(명시적 `limit` 은 그대로 존중).
  6. get_plot: 전 단계 일정(`stage_schedule`의 guidance·targets·날짜,
     `timeline.stages`)을 개수/현재 위치만 남기고 접는다 — 현재 단계는
     이미 `stage`/`timeline` 스칼라가 답하고, 전체는 get_program 이 낸다.
     target_check 의 `other_sensors`/`recent.drift[].sensors`(다른 센서
     값 전체)도 개수만 남긴다.

라이브 DB 를 쓰지 않는다(임시 sqlite).
"""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


# 모듈 전체가 Flask 앱 하나·sqlite 하나를 공유한다(클래스마다 새 앱을 만들면
# 이 파일 하나가 db.create_all() 을 7번 반복해 — 전체 스위트(300여 파일)와
# 함께 돌 때만 드러나는 무거움이었다: 처음엔 클래스마다 따로 만들었더니
# 이 파일이 껴 있을 때만 전혀 무관한 다른 파일 몇 개가 sporadic 하게
# 실패했다(2026-09-29, `inspect.getsource` 가 엉뚱한 함수 본문을 냄 —
# 원인은 못 밝혔지만 앱을 하나로 합치니 재현이 없어졌다). 클래스별 시드는
# 서로 다른 unique_id 접두사를 쓰므로 충돌하지 않는다.
def setUpModule():
    from flask import Flask
    from flask_babel import Babel
    from aot.aot_flask.extensions import db
    import aot.databases.models  # noqa: F401

    global _tmp, _flask_app, _ctx
    _tmp = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = \
        'sqlite:///' + os.path.join(_tmp.name, 'summaries.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Babel(app)
    _flask_app = app
    _ctx = app.app_context()
    _ctx.push()
    db.create_all()


def tearDownModule():
    from aot.aot_flask.extensions import db
    db.session.remove()
    _ctx.pop()
    _tmp.cleanup()


class _DBTestCase(unittest.TestCase):
    """공유 앱 컨텍스트 위에서 서브클래스가 자기 몫만 심는다."""

    @classmethod
    def setUpClass(cls):
        from aot.aot_flask.extensions import db
        cls.seed()
        db.session.commit()

    @classmethod
    def seed(cls):
        """서브클래스가 채운다."""

    @property
    def S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService


class TestListPlotsDefaultLimit(_DBTestCase):
    N_PLOTS = 40

    @classmethod
    def seed(cls):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoMap, GeoPlot

        db.session.add(GeoMap(unique_id='map-many', name='큰농장'))
        for i in range(cls.N_PLOTS):
            db.session.add(GeoPlot(
                unique_id='plot-%03d' % i, geo_id='map-many',
                subject='작물%03d' % i, started_on=date.today(),
                feature={'type': 'Feature', 'properties': {},
                         'geometry': _square(i * 0.001, 0.0, 0.0005)}))

    def test_default_limit_truncates_and_says_the_true_total(self):
        out = self.S.list_plots(map_id='map-many')
        self.assertEqual(10, len(out['plots']))
        self.assertTrue(out.get('truncated'))
        self.assertEqual(self.N_PLOTS, out.get('total_matched'))
        self.assertIn('10', out['truncated_note'])
        self.assertIn(str(self.N_PLOTS), out['truncated_note'])

    def test_limit_argument_raises_or_lowers_the_cap(self):
        out = self.S.list_plots(map_id='map-many', limit=5)
        self.assertEqual(5, len(out['plots']))
        self.assertTrue(out['truncated'])

        out_all = self.S.list_plots(map_id='map-many', limit=100)
        self.assertEqual(self.N_PLOTS, len(out_all['plots']))
        self.assertNotIn('truncated', out_all)


class TestCropStatusDefaultLimit(_DBTestCase):
    N_PLOTS = 35

    @classmethod
    def seed(cls):
        from aot.aot_flask.extensions import db
        from aot.databases.models import GeoMap, GeoPlot

        db.session.add(GeoMap(unique_id='map-crop', name='큰농장'))
        for i in range(cls.N_PLOTS):
            db.session.add(GeoPlot(
                unique_id='cplot-%03d' % i, geo_id='map-crop',
                subject='작물%03d' % i, started_on=date.today(),
                feature={'type': 'Feature', 'properties': {},
                         'geometry': _square(i * 0.001, 0.5, 0.0005)}))

    def test_open_field_plots_are_capped_but_plot_count_is_the_true_total(self):
        # 이 모듈은 sqlite 하나를 공유한다(다른 클래스가 자기 지도에 심은
        # 구획도 여기 잡힌다 — get_crop_status 는 지도를 안 가린다) — 그래서
        # 참값을 정확히 self.N_PLOTS 로 못 박지 않고, **적어도 그만큼**이고
        # 잘린 목록 길이(10)와는 다르다는 것으로 "len() 이 아니다" 를 확인한다.
        out = self.S.get_crop_status()
        self.assertEqual(10, len(out['open_field_plots']))
        self.assertGreaterEqual(out['plot_count'], self.N_PLOTS)
        self.assertGreater(out['plot_count'], len(out['open_field_plots']))
        self.assertTrue(out.get('truncated'))
        self.assertIn('10', out['truncated_note'])

    def test_system_brief_crops_summary_uses_the_true_total_not_len(self):
        """get_system_brief 는 get_crop_status 가 자른 목록의 len() 이 아니라
        참값(plot_count)을 더해야 한다 — 아니면 큰 농장에서 개수가 작게
        보인다."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        brief = S.get_system_brief()
        self.assertGreaterEqual(brief['crops']['plot_count'], self.N_PLOTS)
        self.assertGreaterEqual(brief['crops']['open_field'], self.N_PLOTS)


class TestControlStateSummary(_DBTestCase):

    @classmethod
    def seed(cls):
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController, FunctionRuntimeState

        options = {
            'geo_facility_id': None,
            'tolerance_vpd': 0.1, 'tolerance_temperature': 1.0,
            'tolerance_humidity': 5.0, 'tolerance_co2': 50,
            'priority_vpd': 1, 'priority_temperature': 2,
            'priority_humidity': 3, 'priority_co2': 4,
            'temp_min': 10.0, 'temp_max': 35.0,
            'humid_min': 40.0, 'humid_max': 90.0,
            'guide_T_min': 18.0, 'guide_T_max': 28.0,
            'guide_RH_min': 60.0, 'guide_RH_max': 80.0,
            'time_enable': False, 'time_start': None, 'time_end': None,
            'effect_engine': 'legacy',
        }
        ctrl = CustomController(
            unique_id='ctl-env-1', name='Env Coordinator 1',
            device='env_coordinator', is_activated=True,
            custom_options=json.dumps(options))
        db.session.add(ctrl)

        summary = {
            'ts': 1234567890.0,
            'limiting_factor': 'temperature',
            'strain': None,
            'unmeasured': [],
            'deviation': {'temperature': 1.2},
            'trend': {'T_per_min': 0.01, 'RH_per_min': -0.02, 'CO2_per_min': 0.0},
            'targets': {'temperature': 24.0},
            'stage_guide': None,
            'greybox_skill': {'mae_t': 0.4, 'mae_rh': 3.1, 'n': 500},
            'mpc_shadow': {'method': 'noop'},
            'solar_lead': {'reason': 'clear', 'bias': 0.1},
            'capability': {'cooler': 1.0, 'heater': 0.0},
            'basis': {'mode': 'legacy', 'temperature': 24.0},
            'vent': {'effective_area_m2': 1.2, 'total_area_m2': 5.0,
                     'open_ratio_pct': 24.0},
            'outputs_by_kind': {'cooler': 10.0},
            'gate': {'triggered': False, 'description': ''},
            'feedforward': {'active': False},
            'schedule': {'start': '2026-08-01', 'end': None,
                         'end_confirmed': False, 'week': 4.0,
                         'plot': 'tomato', 'stage': 'veg'},
            'photo': {'enabled': True, 'crop': 'tomato'},
            'commands': [{'slot_key': 'a1', 'kind': 'cooler', 'pct': 40.0,
                          'reason': 1, 'var': 'temperature'}],
            'actuation': {'profile': 'standard', 'normal_period_sec': 180,
                          'emergency_period_sec': 60, 'emergency': False,
                          'reason': None, 'vents': []},
        }
        db.session.add(FunctionRuntimeState(
            function_id='ctl-env-1', summary_json=json.dumps(summary)))

    def test_default_drops_tolerance_priority_and_display_only_diagnostics(self):
        out = self.S.get_control_state()
        coord = out['coordinators'][0]
        self.assertNotIn('tolerance', coord)
        self.assertNotIn('priority', coord)
        # safety_range 는 안전 상·하한이라 남는다.
        self.assertIn('safety_range', coord)

        lcs = coord['latest_cycle_summary']
        for kept in ('limiting_factor', 'gate', 'commands', 'targets',
                     'deviation', 'schedule'):
            self.assertIn(kept, lcs, kept)
        for dropped in ('greybox_skill', 'mpc_shadow', 'solar_lead',
                        'capability', 'basis', 'vent', 'outputs_by_kind',
                        'trend', 'photo', 'actuation'):
            self.assertNotIn(dropped, lcs, dropped)

        self.assertIn('_omitted', out)
        self.assertIn('detail=true', out['_omitted'])

    def test_detail_true_restores_everything(self):
        out = self.S.get_control_state(detail=True)
        coord = out['coordinators'][0]
        self.assertIn('tolerance', coord)
        self.assertIn('priority', coord)
        lcs = coord['latest_cycle_summary']
        for k in ('greybox_skill', 'mpc_shadow', 'solar_lead', 'capability',
                  'basis', 'vent', 'outputs_by_kind', 'trend', 'photo',
                  'actuation'):
            self.assertIn(k, lcs, k)
        self.assertNotIn('_omitted', out)

    def test_response_is_much_smaller_by_default(self):
        before = json.dumps(self.S.get_control_state(detail=True),
                            ensure_ascii=False)
        after = json.dumps(self.S.get_control_state(), ensure_ascii=False)
        self.assertLess(len(after), len(before))


class TestFunctionListGrouping(_DBTestCase):

    @classmethod
    def seed(cls):
        from aot.aot_flask.extensions import db
        from aot.databases.models.function import Conditional, Trigger
        from aot.databases.models.pid import PID
        from aot.databases.models.controller import CustomController

        db.session.add(Conditional(unique_id='c1', name='Cond A',
                                   is_activated=True, period=None))
        db.session.add(Trigger(unique_id='t1', name='Trig A',
                               trigger_type='timer', is_activated=False,
                               period=60))
        db.session.add(PID(unique_id='p1', name='PID A', is_activated=True))
        db.session.add(CustomController(unique_id='cc1', name='Custom A',
                                        device='bang_bang', is_activated=True))

    def test_grouped_by_type_not_repeated_per_row(self):
        # 이 파일은 모듈 전체가 sqlite 하나를 공유한다(다른 클래스의 시드도
        # 같은 테이블에 있다) — 그래서 정확한 개수/집합은 종류별로 좁혀
        # 물은 뒤에 확인한다(각 종류에는 이 클래스가 심은 것만 있다).
        out = self.S.get_function_list()
        self.assertIn('functions', out)
        self.assertNotIn('results', out)
        groups = out['functions']
        self.assertEqual({'c1'}, {f['function_id'] for f in groups['conditional']})
        self.assertEqual({'t1'}, {f['function_id'] for f in groups['trigger']})
        self.assertEqual({'p1'}, {f['function_id'] for f in groups['pid']})
        self.assertIn('cc1', {f['function_id'] for f in groups['custom']})
        # 항목 자체에는 그룹의 타입 이름을 반복해서 싣지 않는다.
        for group in groups.values():
            for row in group:
                self.assertNotIn('function_type', row)

    def test_null_fields_are_not_serialized(self):
        # CustomController 에는 period 칼럼 자체가 없다(getattr 기본값 None) —
        # Conditional/Trigger/PID 는 period 에 모델 기본값(60.0)이 있어 null 을
        # 자연스럽게 재현할 수 없다.
        out = self.S.get_function_list(function_type='custom')
        row = out['functions']['custom'][0]
        self.assertNotIn('period', row, 'period=None 은 아예 안 싣는다')

    def test_filter_still_works(self):
        out = self.S.get_function_list(function_type='trigger')
        self.assertEqual({'trigger'}, set(out['functions'].keys()))
        self.assertEqual(60, out['functions']['trigger'][0]['period'])


class TestSearchScheduleSummary(_DBTestCase):
    N_ROWS = 25

    @classmethod
    def seed(cls):
        from aot.aot_flask.extensions import db
        from aot.databases.models.scheduler import SchedulerJobMeta

        base = datetime.utcnow() + timedelta(days=1)
        for i in range(cls.N_ROWS):
            db.session.add(SchedulerJobMeta(
                unique_id='job-%03d' % i, action_type='human',
                state='PENDING', schedule_time=base + timedelta(hours=i),
                anchor_tz='Asia/Seoul', target_id='none',
                params_json=json.dumps({'content': '작업 %03d' % i}),
                is_editable=True, is_deletable=True))

    def test_default_limit_flags_truncation(self):
        out = self.S.search_schedule_tool()
        self.assertEqual(20, len(out['results']))
        self.assertTrue(out.get('truncated'))
        self.assertIn('note', out)

    def test_common_tz_is_hoisted_not_repeated(self):
        out = self.S.search_schedule_tool(limit=5)
        self.assertEqual('Asia/Seoul', out.get('when_tz'))
        for row in out['results']:
            self.assertNotIn('when_tz', row)

    def test_target_id_is_not_exposed(self):
        out = self.S.search_schedule_tool(limit=5)
        for row in out['results']:
            self.assertNotIn('target_id', row)


class TestSensorDetailMultiChannelDefault(_DBTestCase):

    @classmethod
    def seed(cls):
        from aot.aot_flask.extensions import db
        from aot.databases.models import DeviceMeasurements, Input, Misc

        db.session.add(Misc(measurement_db_name='influxdb',
                            measurement_db_version='2',
                            measurement_db_host='localhost',
                            measurement_db_port='8086'))
        db.session.add(Input(unique_id='multi-1', name='기상대',
                             device='TEST_WEATHER', is_activated=True))
        for meas in ('temperature', 'humidity', 'wind_speed', 'wind_direction',
                    'rainfall'):
            db.session.add(DeviceMeasurements(
                device_id='multi-1', channel=hash(meas) % 1000,
                measurement=meas, unit='u'))
        db.session.add(Input(unique_id='single-1', name='단일센서',
                             device='TEST_TH', is_activated=True))
        db.session.add(DeviceMeasurements(device_id='single-1', channel=0,
                                          measurement='temperature', unit='C'))

    def _fake_rows(self, n=30):
        from datetime import timezone
        now = datetime.now(timezone.utc)
        return [(now - timedelta(minutes=i), 20.0 + i * 0.1)
                for i in range(n)][::-1]

    def test_multi_channel_device_keeps_fewer_readings_by_default(self):
        with mock.patch('aot.tools.data_tools.measurement.read_influxdb_list',
                        return_value=self._fake_rows()):
            out = self.S.get_sensor_detail(loc_id='multi-1')
        self.assertIsInstance(out, list)
        self.assertEqual(5, len(out[0]['readings']))
        self.assertEqual(30, out[0]['total_readings'])

    def test_single_channel_device_keeps_the_full_default(self):
        with mock.patch('aot.tools.data_tools.measurement.read_influxdb_list',
                        return_value=self._fake_rows()):
            out = self.S.get_sensor_detail(loc_id='single-1')
        self.assertEqual(20, len(out[0]['readings']))

    def test_explicit_limit_overrides_the_default(self):
        with mock.patch('aot.tools.data_tools.measurement.read_influxdb_list',
                        return_value=self._fake_rows()):
            out = self.S.get_sensor_detail(loc_id='multi-1', limit=12)
        self.assertEqual(12, len(out[0]['readings']))


if __name__ == '__main__':
    unittest.main()
