# coding=utf-8
"""2026-11-03 MCP 점검 S1 — 옛 카탈로그(구 도구 이름) 쪽 오류(A11·A12).

  A11 get_weather_forecast 의 focus 는 무시된 인자가 아니다 · 카드 안내가 옛 목록에 없는 동작(screen op=card)을 시키지
      않는다 · get_place_overview 의 _more 가 없는 use_tool 을 가리키지 않는다 · create_note 설명이 없는 add_schedule 을
      안내하지 않는다.
  A12 resolve_target 후보의 target_id(장치 표식 도형 id)로 장치를 읽을 수 있다 · get_plot_history 가 구역 이름도 받는다.
"""
import json
import unittest
from unittest import mock

import pytest

from aot.config import ProdConfig
from aot.tools import tool_execution as te


class FocusTest(unittest.TestCase):

    def _run(self, tool, **args):
        def handler(place=None, **extra):
            return {'status': 'success'}
        with mock.patch('aot.tools.tool_registry.build_tool_map', return_value={tool: handler}), \
                mock.patch.object(te, '_discarded_kwarg_sink', return_value=True):
            return te._dispatch_virtual_tool(tool, args)

    def test_focus_is_not_reported_as_ignored_for_the_forecast(self):
        out = self._run('get_weather_forecast', place='x', focus='max')
        self.assertNotIn('_ignored_arguments', out)

    def test_other_unknown_arguments_are_still_reported(self):
        out = self._run('get_weather_forecast', place='x', focus='max', bogus=1)
        self.assertEqual(['bogus'], out['_ignored_arguments'])


class OldNamesTest(unittest.TestCase):

    def test_card_words_follow_the_surface(self):
        hint = "Summary or weather answer: show one card now (screen op=card) unless already shown."
        with mock.patch.object(te, 'domain_surface_enabled', return_value=True):
            self.assertEqual(hint, te._legacy_card_words(hint))
        with mock.patch.object(te, 'domain_surface_enabled', return_value=False):
            self.assertIn('screen_action action=post', te._legacy_card_words(hint))
            self.assertNotIn('op=card', te._legacy_card_words(hint))

    def test_place_overview_more_does_not_point_at_use_tool(self):
        import os
        import aot.tools
        path = os.path.join(os.path.dirname(aot.tools.__file__), 'data_tools', 'space.py')
        with open(path, encoding='utf-8') as f:
            tail = f.read().split('out["_more"] = (', 1)[1][:120]
        self.assertNotIn('use_tool', tail)

    def test_create_note_points_at_a_tool_that_exists(self):
        from aot.tools import tool_registry as R
        text = json.dumps([t for t in R.virtual_tools() if t['tool_name'] == 'create_note'])
        self.assertNotIn('add_schedule', text)
        self.assertIn('schedule_add', text)


@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'legacy.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def test_a_marker_shape_id_reads_the_device_it_stands_for(app):
    from aot.aot_flask.extensions import db
    from aot.databases import set_uuid
    from aot.databases.models import GeoShape, Input
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    with app.test_request_context():
        inp = Input(unique_id=set_uuid())
        inp.name = '온습도: 가곡리'
        inp.device = 'X'
        shape = GeoShape(unique_id=set_uuid(), geo_id='m1', type='aot_device', feature={})
        db.session.add_all([inp, shape])
        db.session.commit()
        with mock.patch('aot.space.device_binding.device_for_shape',
                        return_value=inp.unique_id):
            row, kind, err = S._resolve_device_target(shape.unique_id)
        assert err is None and row.unique_id == inp.unique_id and kind == 'input'
        # 장치가 아닌 도형 id 는 예전처럼 못 찾는다.
        with mock.patch('aot.space.device_binding.device_for_shape', return_value=None):
            row, _kind, err = S._resolve_device_target(shape.unique_id)
        assert row is None and 'Device not found' in err['error']


def test_plot_history_accepts_a_zone_name(app):
    from aot.tools.aot_data_tool_service import AoTDataToolService as S
    with app.test_request_context():
        with mock.patch.object(S, '_read_place', return_value=(None, {"error": "no such place"})) as read:
            out = S.get_plot_history(zone_id='가곡리 농장')
        read.assert_called_once_with('가곡리 농장')
        assert out == {"error": "no such place"}
