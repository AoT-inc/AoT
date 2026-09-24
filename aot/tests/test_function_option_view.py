# coding=utf-8
"""get_function_detail 이 함수 옵션의 키를 싣는다 — modify_function_options 가
받는 키를 모델이 지어내지 않게(프로필 벤치마크 26-09-24, lat_24).

고정하는 계약:

  1. 모듈 옵션 정의가 있는 함수(CustomController)는 options[{key, name, value,
     …}] 를 싣는다. 원천은 모듈의 custom_options(웹 설정 화면과 같다).
  2. 값을 싣지 않는 표식(범위 밴드·접힘 앵커 등)은 키가 아니다 — 목록에도,
     modify_function_options 의 유효 키에도 없다. 표식 종류는 파서의
     DISPLAY_ONLY_TYPES 와 같다.
  3. 범위 밴드는 `ranges` 로 따로 싣고 어느 키가 양 끝인지(지금 값 포함) 말한다.
     'temperature' 는 범위이지 목표값 칸이 아니다 — 모듈 안내(ai_options_note)가
     목표가 어디서 오는지 말한다.
  4. 범위 이름이나 그것을 품은 지어낸 키(target_temperature)는 거절되고
     did_you_mean 이 범위의 양 끝 키를 가리킨다.
  5. 응답은 작게 — 긴 목록은 상한, 세부 조정 옵션은 뜻 한 줄을 뺀다.
  6. 옛 버전이 저장값에 남긴 키(target_temperature 등)는 저장돼 있어도 유효
     키가 아니다 — 지금 모듈이 읽지 않아 바꿔도 효과가 없다(거짓 성공).
     효과가 없다고 말하고 지금 키를 가리켜 거절한다. 정의 밖이어도 모듈이
     저장값에서 읽는 상태 키(_STORED_KEYS_READ)는 받는다 — 그 목록은 모듈
     소스와 맞춰 본다.

라이브 DB 를 쓰지 않는다(conftest 의 임시 DB).
"""
import json
import unittest
from unittest import mock

_NAME = 'OptView test'


class TestFunctionOptionView(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.aot_flask.app import create_app
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.ctx = cls.app.test_request_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def setUp(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController
        self.db = db
        self._wipe()
        # 웹 폼이 함께 저장해 둔 표식 id(범위 'temperature', 옛 접힘 앵커)가
        # 저장값에 섞여 있는 실제 모양을 흉내 낸다.
        self.env = CustomController(
            name=_NAME + ' env', device='env_coordinator', is_activated=False,
            custom_options=json.dumps({'guide_T_min': 14.0, 'temp_max': 36.0,
                                       'temperature': '', 'humidity': '',
                                       'grp_schedule_end_time_fold': ''}))
        self.bang = CustomController(name=_NAME + ' bang', device='bang_bang',
                                     custom_options='{}', is_activated=False)
        db.session.add_all([self.env, self.bang])
        db.session.commit()

    def tearDown(self):
        self._wipe()
        self.db.session.remove()

    def _wipe(self):
        from aot.databases.models import CustomController
        self.db.session.rollback()
        CustomController.query.filter(
            CustomController.name.like(_NAME + '%')).delete(
                synchronize_session=False)
        self.db.session.commit()

    @staticmethod
    def _svc():
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    def test_marker_types_match_the_parser(self):
        from aot.controllers.abstract_base_controller import DISPLAY_ONLY_TYPES
        self.assertEqual(set(DISPLAY_ONLY_TYPES),
                         set(self._svc()._NON_VALUE_OPTION_TYPES))

    def test_env_coordinator_lists_keys_values_and_ranges(self):
        d = self._svc().get_function_detail(self.env.unique_id)
        keys = {o['key']: o for o in d['options']}
        # 저장값이 있으면 그 값, 없으면 모듈 기본값.
        self.assertEqual(14.0, keys['guide_T_min']['value'])
        self.assertEqual(36.0, keys['temp_max']['value'])
        self.assertIn('guide_T_max', keys)
        self.assertIn('name', keys['guide_T_min'])
        # 선택형은 고를 수 있는 값을 싣는다.
        self.assertIn('temperature', keys['control_basis']['choices'])
        # 표식은 키가 아니다.
        for marker in ('temperature', 'humidity', 'light'):
            self.assertNotIn(marker, keys)
        self.assertFalse([k for k in keys if k.startswith('grp_')])
        rng = d['ranges']['temperature']
        self.assertEqual('guide_T_min', rng['min_key'])
        self.assertEqual('guide_T_max', rng['max_key'])
        self.assertEqual('temp_min', rng['hard_min_key'])
        self.assertEqual('temp_max', rng['hard_max_key'])
        self.assertEqual(14.0, rng['min'])
        self.assertEqual(36.0, rng['hard_max'])
        note = d['options_note']
        self.assertIn('options[].key', note)
        self.assertIn('not a target value', note)
        # 모듈 안내 — 목표는 옵션이 아니라 단계에서 온다.
        self.assertIn('No option holds a target temperature', note)
        self.assertIn('day/night temperature', note)

    def test_response_stays_compact(self):
        from aot.tools.tool_execution import _estimate_tokens
        svc = self._svc()
        d = svc.get_function_detail(self.env.unique_id)
        self.assertLessEqual(len(d['options']), svc._OPTION_VIEW_CAP)
        # 세부 조정 옵션에는 뜻 한 줄이 없다.
        self.assertNotIn('meaning',
                         {o['key']: o for o in d['options']}['guide_T_min'])
        for o in d['options']:
            self.assertLessEqual(len(o.get('meaning', '')),
                                 svc._OPTION_MEANING_CHARS)
            self.assertNotIn('%%', o.get('meaning', ''))
            self.assertLessEqual(len(o.get('choices', [])),
                                 svc._OPTION_CHOICES_CAP)
        self.assertLess(_estimate_tokens(json.dumps(d, ensure_ascii=False)),
                        6000)

    def test_cap_reports_what_was_left_out(self):
        svc = self._svc()
        with mock.patch.object(svc, '_OPTION_VIEW_CAP', 5):
            d = svc.get_function_detail(self.env.unique_id)
        self.assertEqual(5, len(d['options']))
        self.assertGreater(d['options_omitted'], 0)

    def test_simple_module_has_options_without_ranges(self):
        d = self._svc().get_function_detail(self.bang.unique_id)
        keys = {o['key'] for o in d['options']}
        self.assertIn('setpoint', keys)
        self.assertNotIn('ranges', d)
        self.assertIn('options[].key', d['options_note'])

    def test_range_names_and_made_up_targets_are_refused(self):
        svc = self._svc()
        for bad in ('temperature', 'target_temperature'):
            out = svc.validate_function_options(self.env.unique_id, {bad: 25})
            self.assertIsNotNone(out, bad)
            self.assertIn('unknown option key', out['error'], bad)
            self.assertIn('no single target-value option', out['error'], bad)
            self.assertEqual(['guide_T_min', 'guide_T_max', 'temp_min',
                              'temp_max'], out['did_you_mean'][bad], bad)
            self.assertNotIn('temperature', out['valid_keys'])
            self.assertFalse([k for k in out['valid_keys']
                              if k.startswith('grp_')])
        self.assertIsNone(svc.validate_function_options(
            self.env.unique_id, {'guide_T_max': 30.0}))

    # ── 옛 버전이 남긴 키(거짓 성공) ─────────────────────────────────
    _LEGACY = {'target_temperature': 22.0, 'tolerance_temperature': 1.5,
               'target_humidity': 70.0, 'vpd_sp_type': 'fixed',
               'actuator_1_output': 'x', 'priority_temperature': 1}

    def _legacy_env(self):
        from aot.databases.models import CustomController
        opts = dict(self._LEGACY, guide_T_min=14.0, temperature='')
        row = CustomController(name=_NAME + ' legacy', device='env_coordinator',
                               is_activated=False, custom_options=json.dumps(opts))
        self.db.session.add(row)
        self.db.session.commit()
        return row

    def test_stored_legacy_keys_are_refused_as_no_effect(self):
        row = self._legacy_env()
        svc = self._svc()
        out = svc.validate_function_options(row.unique_id, {'target_temperature': 25})
        self.assertIsNotNone(out)
        self.assertIn('older version', out['error'])
        self.assertIn('no effect', out['error'])
        self.assertIn('Nothing was changed', out['error'])
        self.assertEqual(['guide_T_min', 'guide_T_max', 'temp_min', 'temp_max'],
                         out['did_you_mean']['target_temperature'])
        for k in self._LEGACY:
            self.assertNotIn(k, out['valid_keys'], k)
            bad = svc.validate_function_options(row.unique_id, {k: 1})
            self.assertIsNotNone(bad, k)
            self.assertIn('no effect', bad['error'], k)
        # 지금 키는 그대로 통과한다.
        self.assertIsNone(svc.validate_function_options(
            row.unique_id, {'guide_T_max': 28.0}))

    def test_handler_does_not_store_a_legacy_key(self):
        row = self._legacy_env()
        out = self._svc().modify_function_options(row.unique_id,
                                                  {'target_temperature': 25})
        self.assertIn('no effect', out.get('error', ''))
        self.db.session.expire_all()
        from aot.databases.models import CustomController
        saved = json.loads(CustomController.query.filter_by(
            unique_id=row.unique_id).first().custom_options)
        self.assertEqual(22.0, saved['target_temperature'])

    def test_legacy_refusal_reaches_mcp_as_invalid_arguments(self):
        from aot.tools import tool_execution as te
        row = self._legacy_env()
        out = te._pre_gate_validation('modify_function_options',
                                      {'function_id': row.unique_id,
                                       'params': {'tolerance_temperature': 1}})
        self.assertEqual('invalid_arguments', out['reason_code'])
        self.assertIn('no effect', out['message'])
        self.assertIn('temp_max', out['did_you_mean']['tolerance_temperature'])

    def test_state_keys_the_module_still_reads_are_accepted(self):
        from aot.databases.models import CustomController
        row = CustomController(
            name=_NAME + ' lora', device='lorawan_class_scheduler',
            is_activated=False,
            custom_options=json.dumps({'device_slot_map': '{}',
                                       'input_rssi': 'x'}))
        self.db.session.add(row)
        self.db.session.commit()
        svc = self._svc()
        self.assertIsNone(svc.validate_function_options(
            row.unique_id, {'device_slot_map': '{}'}))
        out = svc.validate_function_options(row.unique_id, {'input_rssi': 'y'})
        self.assertIn('no effect', out['error'])

    def test_still_read_list_matches_module_source(self):
        """_STORED_KEYS_READ 의 키는 정의 밖이고, 모듈 소스가 실제로 읽는다."""
        import glob
        import re
        from aot.utils.functions import parse_function_information
        info = parse_function_information()
        srcs = {f: open(f, encoding='utf-8', errors='ignore').read()
                for f in glob.glob('aot/functions/**/*.py', recursive=True)}
        table = self._svc()._STORED_KEYS_READ
        self.assertNotIn('env_coordinator', table)
        for name, keys in table.items():
            self.assertIn(name, info, name)
            spec = {o.get('id') for o in info[name].get('custom_options') or []
                    if isinstance(o, dict)}
            pat = re.compile(r"['\"]function_name_unique['\"]\s*:\s*['\"]%s['\"]"
                             % re.escape(name))
            text = ''.join(s for s in srcs.values() if pat.search(s))
            self.assertTrue(text, name)
            for k in keys:
                self.assertNotIn(k, spec, (name, k))
                self.assertRegex(text, r"get_custom_option\(\s*['\"]%s['\"]"
                                 % re.escape(k), (name, k))

    def test_other_function_kinds_are_unchanged(self):
        from aot.databases.models import PID
        pid = PID(name=_NAME + ' pid')
        self.db.session.add(pid)
        self.db.session.commit()
        try:
            d = self._svc().get_function_detail(pid.unique_id)
            self.assertEqual('pid', d['function_type'])
            self.assertNotIn('options', d)
        finally:
            self.db.session.delete(pid)
            self.db.session.commit()


if __name__ == '__main__':
    unittest.main()
