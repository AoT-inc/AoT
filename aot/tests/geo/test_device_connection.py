# coding=utf-8
"""접속정보 편집 — 하드웨어 교체의 1안.

여기서 지키는 것은 넷이다.

1. **필드 목록은 드라이버 선언에서 나온다.** 컬럼을 훑어 "값이 있으면
   보여주는" 방식이면 모델에 컬럼이 늘 때마다 편집 대상이 조용히 늘어난다.
2. **모르는 키는 거부한다.** 조용히 버리면 사용자는 저장됐다고 믿고, 새로고침
   에서 값이 되돌아온 뒤에야 알게 된다(`theme_keys` 화이트리스트에서 겪은
   실패 모드다).
3. **자격증명은 접속정보가 아니다.** API 키·토큰은 스키마에 실리지도 않고
   보내도 거부된다. 한 번 응답에 실리면 로그·캐시에 남아 되돌릴 수 없다.
4. **껐다 켜기는 실패할 수 있고, 실패는 성공에 묻히면 안 된다.** 저장은 됐는데
   장치가 꺼진 채로 남는 것이 가장 위험한 결말이라 반드시 보고돼야 한다.

바인딩을 건드리지 않는다는 것도 함께 본다 — 장치 uuid 가 그대로이므로 슬롯의
연결은 변한 것이 없고, 여기서 새 이력 구간을 만들면 그것이 거짓말이 된다.
"""
import copy
import json
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_device_connection as C
from aot.databases.models import CustomController, Input, Notes, Output, PID


DEV_INPUT = 'conn-input-0001'
DEV_OUTPUT = 'conn-output-0001'
DEV_FUNC = 'conn-func-0001'
DEV_PID = 'conn-pid-0001'


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


class _Base(unittest.TestCase):

    # 드라이버 선언 대역. 실제 모듈 파싱은
    # `TestRealModuleDeclarations` 하나가 맡고, 나머지는 이 대역으로 의미론만
    # 본다 — 특정 센서 모델의 선언이 바뀌었다고 규칙 테스트가 깨지면 안 된다.
    MODULE_INFO = {
        'input': {
            'input_name': 'Test Sensor',
            'options_enabled': ['i2c_location', 'period'],
            'options_disabled': ['interface'],
            'custom_options': [
                {'id': 'dev_eui', 'type': 'text', 'name': 'DevEUI',
                 'phrase': '16-digit hexadecimal DevEUI'},
                {'id': 'cs_api_token', 'type': 'text', 'name': 'API Key'},
                {'id': 'period', 'type': 'integer', 'name': 'Period'},
                # 드라이버가 포트를 'text' 로 선언한 실제 사례
                # (chirpstack_MQTT_jmespath). 그 선언을 믿으면 안 된다.
                {'id': 'mqtt_port', 'type': 'text', 'name': 'MQTT Port'},
            ],
        },
        'output': {
            'output_name': 'Test Output',
            'options_enabled': ['uart_location', 'uart_baud_rate'],
        },
        'device': {
            'function_name': 'Test Device',
            'custom_options': [
                {'id': 'dev_eui', 'type': 'text', 'name': 'DevEUI'},
            ],
        },
    }

    def setUp(self):
        # 클래스 속성을 그대로 쓰면 한 테스트의 수정이 다음 테스트로 샌다.
        self.MODULE_INFO = copy.deepcopy(type(self).MODULE_INFO)
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        Input(unique_id=DEV_INPUT, name='센서', device='TEST_SENSOR',
              i2c_location='0x44', i2c_bus=1, interface='I2C',
              custom_options=json.dumps({'dev_eui': 'aaaa1111',
                                         'mqtt_port': '1883',
                                         'cs_api_token': 'super-secret'})).save()
        Output(unique_id=DEV_OUTPUT, name='밸브', output_type='TEST_OUTPUT',
               uart_location='/dev/ttyUSB0', baud_rate=9600).save()
        CustomController(unique_id=DEV_FUNC, name='노드', device='TEST_DEVICE',
                         custom_options=json.dumps({'dev_eui': 'bbbb2222'})).save()
        PID(unique_id=DEV_PID, name='PID').save()

        self._orig_module_info = C._module_info
        C._module_info = lambda kind, entity: self.MODULE_INFO.get(kind, {})

        # 데몬은 테스트에 없다. 토글은 기본적으로 성공한 것으로 둔다.
        self.toggles = []
        self.toggle_errors = {}
        self._patch_toggle()

    def tearDown(self):
        C._module_info = self._orig_module_info
        from aot.aot_flask.utils import utils_general
        utils_general.controller_activate_deactivate = self._orig_toggle
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _patch_toggle(self):
        """`_toggle` 자체가 아니라 그 아래를 대역으로 둔다 — 오류 수집까지
        진짜 코드가 돌아야 "재활성화 실패가 경고로 올라오는가"를 볼 수 있다."""
        from aot.aot_flask.utils import utils_general
        self._orig_toggle = utils_general.controller_activate_deactivate

        def fake(messages, action, controller_type, controller_id,
                 flash_message=True):
            self.toggles.append(action)
            err = self.toggle_errors.get(action)
            if err:
                messages['error'].append(err)
            return messages

        utils_general.controller_activate_deactivate = fake

    def _fields(self, device_id):
        return {f['key']: f for f in C.connection_schema(device_id)['fields']}


class TestSchema(_Base):

    def test_fields_come_from_the_driver_declaration(self):
        keys = list(self._fields(DEV_INPUT))
        # i2c_location 은 컬럼 둘(주소 + 버스)을 뜻한다.
        self.assertIn('i2c_location', keys)
        self.assertIn('i2c_bus', keys)
        # period 는 선언에 있지만 접속정보가 아니다.
        self.assertNotIn('period', keys)

    def test_current_values_are_carried(self):
        fields = self._fields(DEV_INPUT)
        self.assertEqual(fields['i2c_location']['value'], '0x44')
        self.assertEqual(fields['dev_eui']['value'], 'aaaa1111')

    def test_credentials_never_appear(self):
        """API 키가 응답에 실리면 로그·캐시에 남아 되돌릴 수 없다."""
        self.assertNotIn('cs_api_token', self._fields(DEV_INPUT))

    def test_the_secret_net_bites_a_key_that_slipped_into_the_allowlist(self):
        """위 테스트만으로는 `_is_secret_key()` 를 지워도 통과한다 — 명부에
        없다는 이유만으로 이미 걸러지기 때문이다. 그물이 실제로 무는지 보려면
        명부를 통과한 자격증명을 만들어 넣어야 한다."""
        orig = C._CONNECTION_OPTION_TYPES
        C._CONNECTION_OPTION_TYPES = dict(orig, cs_api_token='text')
        try:
            self.assertNotIn('cs_api_token', self._fields(DEV_INPUT))
            with self.assertRaises(C.ConnectionSettingError):
                C.apply_connection(DEV_INPUT, {'cs_api_token': 'stolen'})
        finally:
            C._CONNECTION_OPTION_TYPES = orig

    def test_declared_but_disabled_options_are_readonly(self):
        """드라이버가 고정한 값도 보여준다 — 안 보이면 사람은 그것이 있는 줄도
        모르고, 편집 가능한 것처럼 보이면 저장이 거부되는 이유를 모른다."""
        # interface 는 컬럼 매핑이 없으므로 필드로 뜨지 않지만, 매핑이 있는
        # 옵션이 disabled 로 선언되면 readonly 로 실려야 한다.
        self.MODULE_INFO['input'] = dict(
            self.MODULE_INFO['input'],
            options_enabled=[], options_disabled=['i2c_location'])
        self.assertTrue(self._fields(DEV_INPUT)['i2c_location']['readonly'])

    def test_devices_without_connection_settings_get_an_empty_list(self):
        """빈 목록은 오류가 아니다 — 가상 출력·계산 함수가 정상적으로 그렇다."""
        self.MODULE_INFO['output'] = {'output_name': 'Virtual'}
        schema = C.connection_schema(DEV_OUTPUT)
        self.assertEqual(schema['fields'], [])

    def test_unsupported_kinds_are_refused(self):
        with self.assertRaises(C.ConnectionSettingError):
            C.connection_schema(DEV_PID)

    def test_missing_device_is_refused(self):
        with self.assertRaises(C.ConnectionSettingError):
            C.connection_schema('does-not-exist')


class TestApply(_Base):

    def test_column_and_custom_option_are_both_saved(self):
        result = C.apply_connection(DEV_INPUT, {
            'i2c_location': '0x45', 'dev_eui': 'cccc3333'})
        self.assertEqual(len(result['changed']), 2)
        row = Input.query.filter(Input.unique_id == DEV_INPUT).first()
        self.assertEqual(row.i2c_location, '0x45')
        self.assertEqual(json.loads(row.custom_options)['dev_eui'], 'cccc3333')

    def test_other_custom_options_survive(self):
        """custom_options 는 통째로 덮어쓰지 않고 병합한다 — 덮어쓰면 접속정보를
        한 번 고칠 때마다 나머지 설정이 전부 지워진다."""
        C.apply_connection(DEV_INPUT, {'dev_eui': 'cccc3333'})
        row = Input.query.filter(Input.unique_id == DEV_INPUT).first()
        self.assertEqual(json.loads(row.custom_options)['cs_api_token'],
                         'super-secret')

    def test_unknown_key_is_refused_not_dropped(self):
        with self.assertRaises(C.ConnectionSettingError):
            C.apply_connection(DEV_INPUT, {'period': 30})

    def test_credential_key_is_refused(self):
        with self.assertRaises(C.ConnectionSettingError):
            C.apply_connection(DEV_INPUT, {'cs_api_token': 'stolen'})

    def test_readonly_field_is_refused(self):
        self.MODULE_INFO['input'] = dict(
            self.MODULE_INFO['input'],
            options_enabled=[], options_disabled=['i2c_location'])
        with self.assertRaises(C.ConnectionSettingError):
            C.apply_connection(DEV_INPUT, {'i2c_location': '0x45'})

    def test_non_numeric_value_for_a_numeric_field_is_refused(self):
        with self.assertRaises(C.ConnectionSettingError):
            C.apply_connection(DEV_INPUT, {'i2c_bus': 'left one'})

    def test_numeric_check_ignores_what_the_driver_declared(self):
        """드라이버의 `type` 은 폼 위젯을 정할 뿐이라 포트를 'text' 로 선언한
        모듈이 흔하다. 그것을 믿었더니 포트에 "여덟팔삼" 이 저장됐다 —
        브라우저 실증에서 실제로 저장됐고, 그래서 종류는 우리 명부가 정한다."""
        self.assertEqual(self._fields(DEV_INPUT)['mqtt_port']['type'], 'integer')
        with self.assertRaises(C.ConnectionSettingError):
            C.apply_connection(DEV_INPUT, {'mqtt_port': '여덟팔삼'})
        row = Input.query.filter(Input.unique_id == DEV_INPUT).first()
        self.assertEqual(json.loads(row.custom_options)['mqtt_port'], '1883')

    def test_numeric_custom_option_keeps_its_stored_representation(self):
        """검증 때문에 int 로 바꾼 값을 그대로 써 넣으면 문자열로 저장돼 있던
        자리가 숫자가 되고, 그 값을 문자열로 다루던 드라이버가 조용히 깨진다."""
        C.apply_connection(DEV_INPUT, {'mqtt_port': '8883'})
        row = Input.query.filter(Input.unique_id == DEV_INPUT).first()
        stored = json.loads(row.custom_options)['mqtt_port']
        self.assertEqual(stored, '8883')
        self.assertIsInstance(stored, str)

    def test_no_change_does_nothing(self):
        result = C.apply_connection(DEV_INPUT, {'i2c_location': '0x44'})
        self.assertEqual(result['changed'], [])
        self.assertEqual(self.toggles, [])
        self.assertEqual(Notes.query.count(), 0)

    def test_binding_history_is_not_touched(self):
        """장치가 그대로이므로 슬롯의 연결도 그대로다. 여기서 이력 구간을
        만들면 "다른 장치가 붙었다"는 거짓말이 기록된다."""
        from aot.databases.models import GeoBinding
        C.apply_connection(DEV_INPUT, {'dev_eui': 'cccc3333'})
        self.assertEqual(GeoBinding.query.count(), 0)


class TestRestart(_Base):

    def test_inactive_device_is_not_toggled(self):
        C.apply_connection(DEV_INPUT, {'dev_eui': 'cccc3333'})
        self.assertEqual(self.toggles, [])

    def test_active_device_is_stopped_and_started_again(self):
        row = Input.query.filter(Input.unique_id == DEV_INPUT).first()
        row.is_activated = True
        db.session.commit()

        result = C.apply_connection(DEV_INPUT, {'dev_eui': 'cccc3333'})
        self.assertEqual(self.toggles, ['deactivate', 'activate'])
        self.assertTrue(result['restarted'])
        self.assertEqual(result['warnings'], [])

    def test_failure_to_restart_is_reported_loudly(self):
        """여기서 조용하면 사용자는 저장 성공만 보고 떠나고 장치는 꺼진 채 남는다."""
        row = Input.query.filter(Input.unique_id == DEV_INPUT).first()
        row.is_activated = True
        db.session.commit()
        self.toggle_errors['activate'] = '데몬 응답 없음'

        result = C.apply_connection(DEV_INPUT, {'dev_eui': 'cccc3333'})
        self.assertFalse(result['restarted'])
        self.assertIn('데몬 응답 없음', result['warnings'])
        self.assertTrue(len(result['warnings']) > 1)

    def test_output_is_refreshed_through_the_daemon(self):
        from aot.aot_flask.utils import utils_output
        calls = []
        orig = utils_output.manipulate_output
        utils_output.manipulate_output = lambda action, oid: (
            calls.append((action, oid)) or {'error': [], 'success': []})
        try:
            result = C.apply_connection(DEV_OUTPUT, {'baud_rate': '19200'})
        finally:
            utils_output.manipulate_output = orig
        self.assertEqual(calls, [('Modify', DEV_OUTPUT)])
        self.assertTrue(result['restarted'])
        self.assertEqual(self.toggles, [])   # Output 은 활성 개념이 없다


class TestNote(_Base):

    def test_a_maintenance_note_records_the_swap(self):
        """바인딩은 이 교체를 기록하지 못한다(장치 uuid 가 그대로다). 나중에
        "이 시점부터 값이 왜 달라졌나"에 답할 수 있는 것은 이 노트뿐이다."""
        C.apply_connection(DEV_INPUT, {'dev_eui': 'cccc3333'})
        note = Notes.query.first()
        self.assertIsNotNone(note)
        self.assertEqual(note.target_id, DEV_INPUT)
        self.assertEqual(note.target_type, 'input')
        self.assertEqual(note.category, 'maintenance')
        self.assertIn('aaaa1111', note.note)
        self.assertIn('cccc3333', note.note)


class TestRealModuleDeclarations(unittest.TestCase):
    """대역이 아니라 실제 드라이버 선언과 맞는지 한 번은 확인한다.

    `_OPTION_COLUMNS` 의 키는 드라이버가 `options_enabled` 에 쓰는 이름이어야
    한다. 오타 하나면 그 접속 방식 전체가 화면에서 조용히 사라진다.
    """

    def test_option_names_exist_in_real_drivers(self):
        from aot.utils.inputs import parse_input_information
        from aot.utils.outputs import parse_output_information

        declared = set()
        for parse in (parse_input_information, parse_output_information):
            for info in parse().values():
                for key in ('options_enabled', 'options_disabled'):
                    declared.update(info.get(key) or [])

        known = set(C._OPTION_COLUMNS) & declared
        # 최소한 I2C·UART 는 실제로 쓰이고 있어야 한다. 교집합이 비면
        # 이름 규칙이 어긋난 것이다.
        self.assertIn('i2c_location', known)
        self.assertIn('uart_location', known)

        unknown = set(C._OPTION_COLUMNS) - declared
        self.assertEqual(unknown, set(),
                         '어떤 드라이버도 선언하지 않는 옵션 이름: %s' % unknown)


if __name__ == '__main__':
    unittest.main()
