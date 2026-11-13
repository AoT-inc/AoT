# coding=utf-8
"""2026-11-04 MCP 수정 S6 A — 측정 이름·단위의 표시용 이름표.

`vapor_pressure_deficit 0.2 kPa` · `volumetric_water_content 16 percent` 가 카드에 그대로 나오던 것.
서버가 `measurement_label` / `unit_label` 을 함께 내린다(일지가 쓰던 어휘·정본 `MEASUREMENTS`/`UNITS` 재사용).
기존 키(`measurement`, `unit`)는 그대로다.
"""
import json
import unittest

from flask_babel import force_locale

from aot.tools.domain import display_names, server_card


def _out(body):
    return [{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}]


class dispatch:                         # 안쪽 도구 응답에 이름표를 더하는 한 걸음(실행층이 부르는 `add`)을 같은 모양으로 부른다
    @staticmethod
    def _display_names(out):
        try:
            body = json.loads(out[0]['text'])
        except (TypeError, ValueError, KeyError, IndexError):
            return out
        return _out(body) if display_names.add(body) else out


class _App(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()
        from aot.aot_flask.app import create_app
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.ctx = cls.app.test_request_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()


class Names(_App):

    def test_korean_names_and_symbols(self):
        with force_locale('ko'):
            self.assertEqual(('VPD', None), display_names.names('vapor_pressure_deficit', 'kPa'))
            self.assertEqual(('토양 수분', '%'), display_names.names('volumetric_water_content', 'percent'))
            self.assertEqual(('온도', '°C'), display_names.names('temperature', 'C'))
            self.assertEqual(('토양 온도', '°C'), display_names.names('temperature', 'C', soil=True))
            self.assertEqual(('습도', '%'), display_names.names('humidity', 'percent'))

    def test_unknown_names_add_nothing(self):
        self.assertEqual((None, None), display_names.names('no_such_measure', 'weird'))


class PlaceOverview(_App):

    PLACE = {"status": "success", "place": {"name": "1포장"},
             "sensors": {
                 "temperature": {"avg": 9.4, "unit": "C", "n": 2},
                 "humidity": {"avg": 79.5, "unit": "percent", "n": 2},
                 "vapor_pressure_deficit": {"avg": 0.1, "unit": "kPa", "n": 2},
                 "soil": {"temperature": {"avg": 11.8, "unit": "C", "n": 1},
                          "volumetric_water_content": {"avg": 17.0, "unit": "percent", "n": 1}}}}

    def test_sensors_rows_get_labels_and_keep_the_old_keys(self):
        with force_locale('ko'):
            got = json.loads(dispatch._display_names(_out(json.loads(json.dumps(self.PLACE))))[0]['text'])
        s = got['sensors']
        self.assertEqual({"avg": 9.4, "unit": "C", "n": 2, "measurement_label": "온도", "unit_label": "°C"},
                         s['temperature'])
        self.assertEqual(('습도', '%'), (s['humidity']['measurement_label'], s['humidity']['unit_label']))
        self.assertEqual('VPD', s['vapor_pressure_deficit']['measurement_label'])
        self.assertNotIn('unit_label', s['vapor_pressure_deficit'])          # kPa 는 이미 기호다
        soil = s['soil']
        self.assertEqual(('토양 온도', '°C'), (soil['temperature']['measurement_label'], soil['temperature']['unit_label']))
        self.assertEqual(('토양 수분', '%'), (soil['volumetric_water_content']['measurement_label'],
                                          soil['volumetric_water_content']['unit_label']))
        self.assertEqual('percent', soil['volumetric_water_content']['unit'])    # 옛 키 유지

    def test_idempotent(self):
        with force_locale('ko'):
            once = dispatch._display_names(_out(json.loads(json.dumps(self.PLACE))))
            twice = dispatch._display_names(once)
        self.assertEqual(once, twice)


class MeasureLatest(_App):

    def test_group_rows_use_the_medium_for_soil_names(self):
        body = {"zones": [{"zone_name": "1포장", "groups": [
            {"medium": "air", "avg": [{"measurement": "temperature", "unit": "C", "avg_last": 9.2},
                                      {"measurement": "vapor_pressure_deficit", "unit": "kPa", "avg_last": 0.2}]},
            {"medium": "soil", "avg": [{"measurement": "temperature", "unit": "C", "avg_last": 11.8},
                                       {"measurement": "volumetric_water_content", "unit": "percent",
                                        "avg_last": 17.0}]}]}]}
        with force_locale('ko'):
            got = json.loads(dispatch._display_names(_out(body))[0]['text'])
        air, soil = got['zones'][0]['groups']
        self.assertEqual('온도', air['avg'][0]['measurement_label'])
        self.assertEqual('토양 온도', soil['avg'][0]['measurement_label'])
        self.assertEqual('토양 수분', soil['avg'][1]['measurement_label'])
        self.assertEqual('%', soil['avg'][1]['unit_label'])

    def test_one_line_per_site_mode_gets_label_maps(self):
        body = {"units": {"humidity": "percent", "temperature": "C", "vapor_pressure_deficit": "kPa"},
                "sites": [{"site": "1포장", "groups": [{"medium": "air", "avg": {"humidity": 79.5}}]}]}
        with force_locale('ko'):
            got = json.loads(dispatch._display_names(_out(body))[0]['text'])
        self.assertEqual({"humidity": "습도", "temperature": "온도", "vapor_pressure_deficit": "VPD"},
                         got['measurement_labels'])
        self.assertEqual({"humidity": "%", "temperature": "°C"}, got['unit_labels'])
        self.assertEqual("percent", got['units']['humidity'])

    def test_device_level_row_and_request_echo(self):
        body = {"measurement": "volumetric_water_content", "unit": "percent", "value": 16,
                "read_as": {"measurement": "soil moisture"}}
        with force_locale('ko'):
            got = json.loads(dispatch._display_names(_out(body))[0]['text'])
        self.assertEqual(('토양 수분', '%'), (got['measurement_label'], got['unit_label']))
        self.assertEqual({"measurement": "soil moisture"}, got['read_as'])      # 물은 말은 그대로

    def test_errors_and_non_json_are_untouched(self):
        err = _out({"status": "error", "measurement": "temperature", "unit": "C"})
        self.assertEqual(err, dispatch._display_names(err))
        raw = [{'type': 'text', 'text': 'plain'}]
        self.assertEqual(raw, dispatch._display_names(raw))


class Wiring(unittest.TestCase):

    def test_execution_layer_adds_labels_for_exactly_the_reading_tools(self):
        import inspect
        from aot.tools import tool_execution
        src = inspect.getsource(tool_execution._execute_tool)
        self.assertIn('tool_name in _display_names.TOOLS', src)
        # 도메인 표면의 안쪽 도구(measure.* / overview.place)와 인앱 AI 가 같은 도구를 지난다
        from aot.tools.domain import registry_data
        inner = set()
        for o in registry_data.OPS:
            if (o.tool, o.op) in {('overview', 'place'), ('measure', 'latest'), ('measure', 'history'),
                                  ('measure', 'channels'), ('measure', 'freshness')}:
                inner |= set(v for v in (o.inner.values() if isinstance(o.inner, dict) else [o.inner]) if v)
        self.assertTrue(inner <= display_names.TOOLS, inner - display_names.TOOLS)


class ThroughTheExecutionLayer(_App):
    """인앱 AI 는 안쪽 도구를 직접 부른다 — 같은 실행층을 지나면 이름표가 붙는다."""

    def test_inner_tool_result_gets_labels(self):
        from unittest import mock
        from aot.tools import tool_execution
        res = json.loads(json.dumps(PlaceOverview.PLACE))
        with mock.patch.object(tool_execution, '_run_gated_tool', return_value=(res, None)):
            out = tool_execution._execute_tool(self.app, 'get_place_overview', {'place': '1포장'},
                                               agent_id='t', role=None, transport='in_app')
        body = json.loads(out[0]['text'])
        row = body['sensors']['soil']['volumetric_water_content']
        self.assertEqual('percent', row['unit'])
        self.assertIn('unit_label', row)
        self.assertIn('measurement_label', row)
        self.assertIn('unit_label', body['sensors']['temperature'])


class UserLanguage(_App):
    """MCP 컨테이너에는 요청 로케일이 없다 — 이름표는 사용자 언어로 계산한다."""

    def test_add_localised_runs_add_inside_the_user_locale(self):
        from unittest import mock
        seen = {}

        def fake(app, user_id, fn):
            seen['user'] = user_id
            with force_locale('ko'):
                return fn()
        body = json.loads(json.dumps(PlaceOverview.PLACE))
        with mock.patch.object(server_card, 'in_user_locale', fake):
            display_names.add_localised(self.app, 'u-1', body)
        self.assertEqual('u-1', seen['user'])
        self.assertEqual('토양 수분', body['sensors']['soil']['volumetric_water_content']['measurement_label'])
        self.assertEqual('온도', body['sensors']['temperature']['measurement_label'])

    def test_execution_layer_uses_the_localised_entry(self):
        import inspect
        from aot.tools import tool_execution
        self.assertIn('_display_names.add_localised(app, scope_user_uuid', inspect.getsource(tool_execution._execute_tool))


class Card(_App):

    def test_place_card_uses_symbols_and_names_for_vpd_and_soil_moisture(self):
        place = {"place": {"name": "1포장"},
                 "sensors": {"temperature": {"avg": 10.6, "unit": "C", "n": 2},
                             "humidity": {"avg": 75.8, "unit": "percent", "n": 2},
                             "vapor_pressure_deficit": {"avg": 0.2, "unit": "kPa", "n": 2},
                             "soil": {"temperature": {"avg": 13.1, "unit": "C", "n": 1},
                                      "volumetric_water_content": {"avg": 16, "unit": "percent", "n": 1}}}}
        with force_locale('ko'):
            title, msg = server_card.compose('place', place)
        self.assertEqual(['공기: 온도 10.6 °C, 습도 75.8 %, VPD 0.2 kPa', '흙: 온도 13.1 °C, 토양 수분 16 %'],
                         msg.splitlines())
        self.assertNotIn('percent', msg)
        self.assertNotIn('volumetric', msg)


if __name__ == '__main__':
    unittest.main()
