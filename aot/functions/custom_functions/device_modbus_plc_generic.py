# coding=utf-8
"""AoT 복합장치: Modbus PLC (범용)

첫 실물 장치 모듈(.local/plans/device_group_console_plan.md Phase 4). 특정
레지스터 맵을 가정하지 않는다 — 벤더/모델마다 주소·데이터타입이 다르므로
(plc_modbus_integration_plan.md 4절), 이 모듈은 접속정보 하나로 Modbus TCP
Input 1개 + Modbus TCP Coil Output 1개를 만들어 줄 뿐, 채널은 빈 채로 둔다.
사용자가 실제 PLC의 레지스터 맵을 보고 각 페이지("설정 →" 딥링크)에서
채널을 추가한다.

이 모듈 자체는 아무 로직도 갖지 않는다(CustomModule 이 loop()/listener() 를
선언하지 않으므로 controller_function.py 가 has_loop=False 로 판정 — 코드로
확인). 장치의 역할은 컨트롤러(설계 1.3)이고, 실제 폴링·제어는 하위
Input/Output 이 한다.

@phase active
@stability experimental
@dependency device_blueprint
"""
from flask_babel import lazy_gettext

FUNCTION_INFORMATION = {
    'function_name_unique': 'device_modbus_plc_generic',
    # "장치: " 접두어는 여기 넣지 않는다 — 이 값은 이 파일 전용이 아니라
    # custom_function_options.html(모든 Function 공용 메타 스트립, L62-63)의
    # "이름: {function_name}"에도 그대로 쓰인다. 접두어를 여기 박아두면 그
    # 화면에 "이름: 장치: Modbus PLC (Generic)"처럼 라벨이 겹친다(실제 확인된
    # 버그) — 접두어는 이 값을 소비하는 쪽(routes_device.py choices_devices)
    # 에서만 붙인다.
    'function_name': 'Modbus PLC (Generic)',
    'function_name_short': 'Modbus PLC',

    'is_device': True,
    'device_category': 'controller',

    # 장치 자신은 측정 채널을 직접 갖지 않는다(측정은 전부 하위 Input이 한다)
    # — 꺼두지 않으면 custom_function_options.html의 "측정값 설정" 그룹
    # 제목만 뜨고 내용은 비어 있는 채로 나온다(실제 확인된 버그, 사용자 지적:
    # "거긴 측정값이 아니잖아"). backup_rsync.py 등 기존 비측정형 모듈과
    # 동일한 방식으로 끈다.
    'options_disabled': [
        'measurements_select',
        'measurements_configure',
    ],

    'message': lazy_gettext(
        'A Modbus TCP PLC as a single manageable unit. Enter the connection info once here '
        'and it is copied to the measurement Input and coil Output created alongside this '
        'device. Add the actual channels (registers/coils) on those pages once you have the '
        "PLC's register map — this module does not assume one."
    ),

    'options_enabled': ['custom_options'],

    'custom_options': [
        {
            'id': 'plc_host',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Host'),
            'phrase': lazy_gettext('IP address or hostname of the Modbus TCP device')
        },
        {
            'id': 'plc_port',
            'type': 'integer',
            'default_value': 502,
            'required': True,
            'name': lazy_gettext('Port'),
            'phrase': lazy_gettext('TCP port of the Modbus TCP device (standard: 502)')
        },
        {
            'id': 'unit_id',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Unit ID'),
            'phrase': lazy_gettext(
                'Modbus unit/slave ID of the device. Usually 1 for a device addressed '
                'directly, or the slave address behind a serial gateway')
        },
        {
            'id': 'timeout_s',
            'type': 'float',
            'default_value': 1.0,
            'required': True,
            'name': lazy_gettext('Timeout (seconds)'),
            'phrase': lazy_gettext(
                'How long to wait for a response. One request takes at most '
                'timeout x (retries + 1)')
        },
        {
            'id': 'retries',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Retries'),
            'phrase': lazy_gettext(
                'Retries per request before it is treated as failed. Keep this low: a high '
                'value multiplies how long an unreachable device blocks a command')
        }
    ],

    # 접속정보만 공유하고 채널은 사용자가 직접 정의한다(위 docstring 참조) —
    # 그래서 'channels' 키를 아예 생략한다. Input 은 measurements_variable_amount
    # 라 check_input_channels_exist() 가, Output 은 channels_dict 고정 채널0이
    # 각각 빈 채널 하나를 자동으로 만들어 준다(둘 다 Phase 2에서 확인).
    'device_blueprint': {
        'inputs': [
            {
                'device': 'MODBUS_TCP',
                'name': '{device_name} 측정',
                'inherit_options': ['plc_host', 'plc_port', 'unit_id', 'timeout_s', 'retries'],
            },
        ],
        'outputs': [
            {
                'device': 'MODBUS_TCP_COIL',
                'name': '{device_name} 제어',
                'inherit_options': ['plc_host', 'plc_port', 'unit_id', 'timeout_s', 'retries'],
            },
        ],
    },
}


def execute_at_creation(error, new_func, dict_functions=None):
    from aot.utils.device_blueprint import create_blueprint_members
    error, created = create_blueprint_members(
        error, new_func, FUNCTION_INFORMATION['device_blueprint'])
    return error, new_func


FUNCTION_INFORMATION['execute_at_creation'] = execute_at_creation


def execute_at_modification(
        messages,
        mod_controller,
        request_form,
        custom_options_dict_presave,
        custom_options_channels_dict_presave,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave):
    """장치 설정을 저장할 때마다 접속정보를 하위 Input/Output 에 재전파한다.

    "접속정보 1회 입력"이 실제로 성립하는 지점 — 생성 직후엔 이 값들이 아직
    드라이버 기본값(빈 문자열)이라(device_blueprint.py 상단 docstring 참조),
    사용자가 실제 host/port 를 입력해 저장하는 이 시점에야 하위로 퍼진다.
    """
    import json

    from aot.utils.device_blueprint import sync_inherited_options

    # mod_controller 는 아직 DB에 커밋되지 않았다(controller_mod() 가 이 함수의
    # 반환값으로 custom_options 를 다시 덮어써 최종 저장한다) — sync 는 이번에
    # 저장될 postsave 값을 기준으로 해야 하므로 여기서 임시로 반영해 둔다.
    mod_controller.custom_options = json.dumps(custom_options_dict_postsave)
    sync_inherited_options(mod_controller, FUNCTION_INFORMATION['device_blueprint'])

    return (
        messages,
        mod_controller,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave,
        False,
    )


FUNCTION_INFORMATION['execute_at_modification'] = execute_at_modification


class CustomModule:
    """장치 자신은 아무 로직도 없는 컨테이너다 — loop()/listener() 를 선언하지
    않으므로 controller_function.py 가 has_loop=False 로 판정한다(코드 확인).
    실제 폴링·제어는 하위 Input/Output 이 각자의 컨트롤러에서 수행한다.
    """

    def __init__(self, function, testing=False):
        pass
