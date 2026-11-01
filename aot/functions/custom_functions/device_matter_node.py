# coding=utf-8
"""AoT 복합장치: Matter 노드

AoT Fabric 에 커미셔닝된 Matter 노드 하나 = 이 장치 하나. 노드가 가진 센서는
Input(MATTER_NODE) 채널로, 스위치는 Output(MATTER_ON_OFF) 채널로 만들어진다.
채널은 비워 두지 않고 노드 인터뷰 결과로 채운다(docs/design/matter-controller.md
§4-1 — Modbus PLC 와 달리 Matter 는 자기 기술적이다).

이 장치는 장치 화면의 "추가"로 만들 수 없다. 노드가 AoT Fabric 에 먼저 들어와
있어야 하기 때문이다 — 설정 > Matter 에서 공유 코드를 넣으면 커미셔닝 직후
이 모듈이 만들어진다(aot/aot_flask/utils/utils_matter.py). 그 경로 밖에서
만들려 하면 execute_at_creation() 이 거절한다.

장치를 지우면 AoT Fabric 도 장치에서 지운다(utils_controller.controller_del 의
Matter 훅). 안 그러면 장치의 Fabric 자리가 남아 다른 생태계 추가를 막는다.

@phase experimental
@stability experimental
@dependency device_blueprint, matter_onboarding
"""
from flask_babel import lazy_gettext

FUNCTION_INFORMATION = {
    'function_name_unique': 'device_matter_node',
    'function_name': 'Matter',
    'function_name_short': 'Matter',

    'is_device': True,
    'device_category': 'controller',

    # 측정은 하위 Input 이 한다(device_modbus_plc_generic.py 와 같은 이유).
    'options_disabled': [
        'measurements_select',
        'measurements_configure',
    ],

    'message': lazy_gettext(
        'A Matter device shared to AoT from another ecosystem (Apple Home, Google Home, '
        'SmartThings and others). Add it from Settings > Matter with the pairing code the '
        'other app shows when you share the device. Its sensors and switches are created '
        'as the Input and Output under this device. Deleting this device also removes '
        'AoT from the device, so it frees its slot for other ecosystems.'
    ),

    'options_enabled': ['custom_options'],

    'custom_options': [
        {
            'id': 'node_id',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Node ID'),
            'phrase': lazy_gettext(
                'Node ID on the AoT Matter fabric. Set when the device is added; change it '
                'only to re-bind this device to a node that was shared again')
        },
        {
            'id': 'identity_key',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Device Identity'),
            'phrase': lazy_gettext(
                'Unique ID reported by the device. Used to find this device again when it '
                'is removed and shared again, so its history continues')
        },
        {
            'id': 'vendor_name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Vendor'),
            'phrase': lazy_gettext('Reported by the device')
        },
        {
            'id': 'product_name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Product'),
            'phrase': lazy_gettext('Reported by the device')
        },
        {
            'id': 'serial_number',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Serial Number'),
            'phrase': lazy_gettext('Reported by the device')
        },
    ],

    # 정적 청사진: 드라이버와 상속 키만. 채널은 커미셔닝 때
    # matter_onboarding.build_blueprint() 가 노드에서 채운다. 상속 동기화
    # (sync_inherited_options)는 이 정적 정의를 쓴다 — node_id 를 바꾸면 하위
    # Input/Output 도 같이 바뀐다(재공유 후 재결합, 설계 §4-3).
    'device_blueprint': {
        'inputs': [
            {
                'device': 'MATTER_NODE',
                'name': '{device_name}',
                'inherit_options': ['node_id'],
            },
        ],
        'outputs': [
            {
                'device': 'MATTER_ON_OFF',
                'name': '{device_name}',
                'inherit_options': ['node_id'],
            },
            {
                'device': 'MATTER_LEVEL',
                'name': '{device_name}',
                'inherit_options': ['node_id'],
            },
            {
                'device': 'MATTER_COVERING',
                'name': '{device_name}',
                'inherit_options': ['node_id'],
            },
        ],
    },
}


def execute_at_creation(error, new_func, dict_functions=None):
    import json

    from flask_babel import gettext

    from aot.devices import matter_onboarding
    from aot.devices.matter_clusters import display_name
    from aot.utils.device_blueprint import create_blueprint_members

    node = matter_onboarding.current_node()
    if node is None:
        error.append(gettext(
            'Matter devices are added from Settings > Matter with the pairing code '
            'shared from the other app.'))
        return error, new_func

    try:
        options = json.loads(new_func.custom_options) if new_func.custom_options else {}
    except Exception:
        options = {}
    options.update(matter_onboarding.device_options(node))
    new_func.custom_options = json.dumps(options)
    new_func.name = display_name(node)

    blueprint = matter_onboarding.build_blueprint(
        FUNCTION_INFORMATION['device_blueprint'], node)
    error, created = create_blueprint_members(error, new_func, blueprint)
    matter_onboarding.record_created(created)
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
    """node_id 를 바꾸면 하위 Input/Output 으로 내려보낸다."""
    import json

    from aot.utils.device_blueprint import sync_inherited_options

    mod_controller.custom_options = json.dumps(custom_options_dict_postsave)
    sync_inherited_options(mod_controller, FUNCTION_INFORMATION['device_blueprint'])
    return (messages, mod_controller, custom_options_dict_postsave,
            custom_options_channels_dict_postsave, False)


class CustomModule:
    """장치 자신은 로직이 없는 컨테이너다 — 연결·측정·제어는 하위 Input/Output 이
    공유 클라이언트(aot/devices/matter_client.py)로 한다."""

    def __init__(self, function, testing=False):
        self.function = function

    def stop_function(self):
        pass


FUNCTION_INFORMATION['execute_at_modification'] = execute_at_modification
