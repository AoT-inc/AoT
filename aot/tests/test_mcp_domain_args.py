# coding=utf-8
"""도메인 호출의 인자 모양 — 2026-10-28 claude.ai 점검(세션 A 항목 2·4·8).

- 객체·목록 인자가 JSON 글자로 와도 푼다(control.function_options 의 params 가
  'non-empty object' 로 세 번 거절됐다. tool_profile_set 의 modules 는 글자로 오면
  한 글자씩 쪼개져 운영으로 내려갔다).
- 명부의 필수 인자가 비면 게이트 앞에서 거절한다(빈 input_create 가 승인 대기로 갔다).
- 거절 문구가 받지 않는 것을 받는다고 하지 않는다('takes , not a zone',
  find.functions 의 'It takes: op, target').
- 입출력 수정은 객체가 아닌 params 를 버리고 성공하지 않는다.
"""
import json
import unittest
from unittest import mock


def _plan(tool, args, kind=None):
    from aot.tools.domain import dispatch

    def resolve(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref),
                      'path': 'map > %s' % ref, 'matched': 'exact'}
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
        return dispatch.plan(tool, args)


def _text(verdict):
    return json.loads(verdict[1][0]['text'])


class TextValueTest(unittest.TestCase):

    def test_json_text_params_reach_the_inner_tool_as_an_object(self):
        v = _plan('control', {'op': 'function_options', 'target': 'f',
                              'params': '{"setpoint": 25}'}, kind='function')
        self.assertEqual('call', v[0], v)
        self.assertEqual({'setpoint': 25}, v[2]['params'])

    def test_object_params_are_left_alone(self):
        v = _plan('control', {'op': 'function_options', 'target': 'f',
                              'params': {'setpoint': 25}}, kind='function')
        self.assertEqual({'setpoint': 25}, v[2]['params'])

    def test_text_that_is_not_json_is_left_for_the_inner_tool(self):
        v = _plan('control', {'op': 'function_options', 'target': 'f',
                              'params': 'setpoint=25'}, kind='function')
        self.assertEqual('setpoint=25', v[2]['params'])

    def test_input_edit_params_text_is_decoded(self):
        v = _plan('configure', {'op': 'input_edit', 'target': 'i',
                                'params': ' {"period": 60} '}, kind='input')
        self.assertEqual({'period': 60}, v[2]['params'])

    def test_modules_as_comma_text_or_json_text_become_a_list(self):
        for given in ('plots, map', '["plots", "map"]'):
            with self.subTest(given=given):
                v = _plan('configure', {'op': 'tool_profile_set',
                                        'profile': 'operations', 'modules': given})
                self.assertEqual('call', v[0], v)
                self.assertEqual(['plots', 'map'], v[2]['modules'])


class RequiredArgumentTest(unittest.TestCase):

    def test_empty_create_is_refused_before_the_gate(self):
        v = _plan('configure', {'op': 'input_create'})
        self.assertEqual('refuse', v[0])
        body = _text(v)
        self.assertEqual('missing_argument', body['reason_code'])
        self.assertIn('input_type', body['message'])
        self.assertIn('name', body['message'])

    def test_complete_create_is_planned(self):
        v = _plan('configure', {'op': 'input_create', 'input_type': 'OPEN_METEO_FORECAST',
                                'name': 'x'})
        self.assertEqual('call', v[0], v)
        self.assertEqual('create_input', v[1])

    def test_target_is_not_counted_here(self):
        # 대상은 해석 단계가 따로 거절한다(target_required) — 여기서 두 번 말하지 않는다.
        v = _plan('control', {'op': 'function_on'})
        self.assertEqual('target_required', _text(v)['reason_code'])


class RefusalWordingTest(unittest.TestCase):

    def test_op_without_target_says_so_instead_of_a_blank(self):
        v = _plan('configure', {'op': 'input_create', 'input_type': 'X', 'name': 'x',
                                'target': '3포장'}, kind='zone')
        self.assertEqual('refuse', v[0])
        msg = _text(v)['message']
        self.assertNotIn('takes ,', msg)
        self.assertIn('takes no target', msg)

    def test_unknown_argument_lists_target_only_when_taken(self):
        v = _plan('find', {'op': 'functions', 'name': '일일타이머'})
        msg = _text(v)['message']
        self.assertNotIn('target', msg)
        self.assertIn('function_type', msg)
        v = _plan('detail', {'op': 'function', 'target': 'f', 'bogus': 1}, kind='function')
        self.assertIn('op, target', _text(v)['message'])


class EditParamsTest(unittest.TestCase):

    def _run(self, method, id_arg, model):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        row = mock.MagicMock(custom_options='{}')
        fake = mock.MagicMock()
        fake.query.filter_by.return_value.first.return_value = row
        commit = mock.MagicMock()
        with mock.patch('aot.databases.models.%s' % model, fake), \
                mock.patch('aot.aot_flask.access.write_scope.enforce', lambda *a: None), \
                mock.patch('aot.tools.data_tools.definition.db.session.commit', commit):
            out = getattr(S, method)(**{id_arg: 'id-1', 'name': 'new',
                                        'params': 'period=60'})
        return out, commit, row

    def test_text_params_are_refused_not_dropped(self):
        for method, id_arg, model in (('modify_input', 'input_id', 'Input'),
                                      ('modify_output', 'output_id', 'Output'),
                                      ('modify_gis_input', 'layer_id', 'GeoLayer')):
            with self.subTest(method=method):
                out, commit, row = self._run(method, id_arg, model)
                self.assertIn('error', out)
                self.assertIn('Nothing was changed', out['error'])
                commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
