# coding=utf-8
"""AoT 복합장치: AoT-C (태양광 12V 전원 제어용 ChirpStack 릴레이 노드).

기존에는 "AoT-C-001" ~ "AoT-C-260012" 같은 실물 개체마다 `chirpstack_downlink`
Output 하나만 등록돼 있고 짝이 되는 텔레메트리 Input이 없거나 따로 관리됐다.
이 모듈은 두 개를 접속정보 하나로 함께 만든다 — ChirpStack MQTT 텔레메트리
Input(`chirpstack_mqtt_jmespath`) + ChirpStack gRPC/REST 다운링크 Output
(`chirpstack_downlink`).

"구 lorawan manager 승계" — 개별 `lorawan_mode_manager`(디바이스당 1개)는
사이트당 1개인 `lorawan_class_scheduler`로 대체됐다(그 파일 자체의 헤더 주석
"Replaces the per-device lorawan_mode_manager" 참조). 이 장치는 새 스케줄러를
만들지 않는다 — 사용자 지시(2026-07-28): "여러 대의 장치가 하나의 스케줄러로
작동하도록 하는 게 이득"이므로, `scheduler_id` 로 **기존** 스케줄러 중 하나를
선택하게 하고(`select_device` 타입, Function 목록을 device=='lorawan_class_
scheduler' 로 필터 — 새 옵션 타입을 만들지 않고 기존 `Custom_Options.html`의
`select_device` 필터 메커니즘을 그대로 재사용) 저장 시 `_lorawan_common.
assign_device_to_scheduler()` 로 DevEUI를 그 슬롯맵에 등록한다.

접속정보 공유 범위: MQTT 브로커(mqtt_host 등)는 Input에만, ChirpStack 서버/
토큰(cs_server/cs_api_token)은 Output에만 필요하다 — 서로 다른 프로토콜(MQTT
구독 vs gRPC/REST 다운링크)이라 하나로 합쳐지지 않는다. 유일하게 겹치는 값은
DevEUI인데, 이름마저 다르다(Output 필드는 `dev_eui`, Input 필드는 콤마구분
리스트인 `device_euis`) — `device_blueprint.py`의 `inherit_options`는 동일
이름 키만 복사하므로(Phase 2 설계), 이 한 쌍만 아래 `_sync_device_euis()`가
별도로 맞춘다.

@phase active
@stability experimental
@dependency device_blueprint, _lorawan_common
"""
import logging

from flask_babel import lazy_gettext

logger = logging.getLogger(__name__)

FUNCTION_INFORMATION = {
    'function_name_unique': 'device_aot_c',
    # "장치: " 접두어를 여기 넣지 않는 이유는 device_modbus_plc_generic.py의
    # 동일 주석 참조 — 접두어는 routes_device.py의 choices_devices에서만 붙인다.
    'function_name': 'AoT-C (Solar 12V Relay Node)',
    'function_name_short': 'AoT-C',

    'is_device': True,
    'device_category': 'controller',

    # device_modbus_plc_generic.py와 동일한 이유(측정 채널을 직접 갖지 않음)
    # 로 "측정값 설정" 그룹을 끈다.
    'options_disabled': [
        'measurements_select',
        'measurements_configure',
    ],

    'message': lazy_gettext(
        'A ChirpStack-connected 12V solar power relay/valve node as a single manageable '
        'unit. Enter the connection info once here and it is copied to the telemetry '
        'Input and downlink Output created alongside this device. Pick an existing LoRaWAN '
        'class scheduler below to have this DevEUI join/class-managed alongside other '
        'devices on the same scheduler — this does not create a new scheduler.'
    ),

    'options_enabled': ['custom_options'],

    'custom_options': [
        {
            'id': 'dev_eui',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('DevEUI'),
            'phrase': lazy_gettext('16-digit hexadecimal DevEUI (separators allowed)')
        },
        {
            'id': 'mqtt_host',
            'type': 'text',
            'default_value': 'localhost',
            'required': True,
            'name': lazy_gettext('MQTT Host'),
            'phrase': lazy_gettext('MQTT broker hostname or IP address for telemetry (uplink)')
        },
        {
            'id': 'mqtt_port',
            'type': 'text',
            'default_value': 1883,
            'required': True,
            'name': lazy_gettext('MQTT Port'),
            'phrase': lazy_gettext('MQTT broker port (default 1883, 8883 recommended for TLS)')
        },
        {
            'id': 'mqtt_username',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('MQTT Username'),
            'phrase': lazy_gettext('Optional: broker authentication username')
        },
        {
            'id': 'mqtt_password',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('MQTT Password'),
            'phrase': lazy_gettext('Optional: broker authentication password')
        },
        {
            'id': 'mqtt_tls_enable',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable MQTT TLS'),
            'phrase': lazy_gettext('Whether to use a TLS (SSL) connection to the MQTT broker')
        },
        {
            'id': 'mqtt_clientid',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('MQTT Client ID'),
            'phrase': lazy_gettext('Leave blank to let the telemetry Input generate one')
        },
        {
            'id': 'cs_server',
            'type': 'text',
            'default_value': '127.0.0.1:8080',
            'required': False,
            'name': lazy_gettext('ChirpStack gRPC Server'),
            'phrase': lazy_gettext('Host:port for downlink control (e.g., 127.0.0.1:8080)')
        },
        {
            'id': 'cs_api_token',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('ChirpStack API Key'),
            'phrase': lazy_gettext('JWT token for downlink control (without Bearer prefix)')
        },
        {
            'id': 'scheduler_id',
            'type': 'select_device',
            'options_select': ['Function'],
            'filter': {'key': 'device', 'value': 'lorawan_class_scheduler'},
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Class Scheduler'),
            'phrase': lazy_gettext(
                'Existing LoRaWAN class scheduler that manages this DevEUI\'s join/class '
                'state alongside other devices. Leave unset to manage class manually.')
        },
    ],

    # 채널은 빈 채로 둔다(device_modbus_plc_generic.py와 동일한 이유) — Input은
    # measurements_variable_amount라 check_input_channels_exist()가, Output은
    # channels_dict 고정 채널0(duration_time)이 각각 빈 채널 하나를 자동으로
    # 만들어 준다.
    'device_blueprint': {
        'inputs': [
            {
                'device': 'chirpstack_mqtt_jmespath',
                'name': '{device_name} 측정',
                'inherit_options': [
                    'mqtt_host', 'mqtt_port', 'mqtt_username', 'mqtt_password',
                    'mqtt_tls_enable', 'mqtt_clientid',
                ],
            },
        ],
        'outputs': [
            {
                'device': 'chirpstack_downlink',
                'name': '{device_name} 제어',
                'inherit_options': ['cs_server', 'cs_api_token', 'dev_eui'],
            },
        ],
    },
}


def _sync_device_euis(parent_device):
    """dev_eui(장치 자신의 필드)를 하위 텔레메트리 Input의 device_euis(콤마구분
    리스트 필드)로 복사한다. inherit_options는 동일 이름 키만 복사하므로
    (device_blueprint.py, Phase 2) 이름이 다른 이 한 쌍만 여기서 맞춘다."""
    import json

    from aot.databases.models import Input

    try:
        parent_options = json.loads(parent_device.custom_options) if parent_device.custom_options else {}
        if not isinstance(parent_options, dict):
            parent_options = {}
    except Exception:
        parent_options = {}
    dev_eui = parent_options.get('dev_eui', '')

    for inp in Input.query.filter_by(
            parent_device_id=parent_device.unique_id, device='chirpstack_mqtt_jmespath').all():
        try:
            opts = json.loads(inp.custom_options) if inp.custom_options else {}
            if not isinstance(opts, dict):
                opts = {}
        except Exception:
            opts = {}
        opts['device_euis'] = dev_eui
        inp.custom_options = json.dumps(opts)
        inp.save()


def _resolve_submitted_scheduler_id(request_form, custom_options_dict_postsave):
    """scheduler_id의 실제 제출값을 postsave 딕셔너리가 아니라 request_form에서
    직접 읽는다.

    custom_options_return_json()(utils_general.py)은 select/text류 필드가 빈
    문자열로 제출되면 "값 없음"으로 취급해 postsave에 이전 값을 그대로
    남긴다 — 모든 옵션 필드가 공유하는 보호 로직으로, 실수로 빈 제출이 기존
    값을 지우는 사고를 막기 위한 것이다. 다른 필드에서는 대개 바람직하지만
    scheduler_id는 "선택 해제"가 정상적인 조작이라 이 보호가 방해가 된다 —
    빈 값으로 저장해도 DB의 scheduler_id가 안 바뀌어 슬롯맵 등록이 풀리지
    않던 버그로 실제 재현됐다(2026-07-28). request_form의 원본 제출값을
    직접 읽어야 "비움"이 실제로 반영된다.
    """
    if request_form is None:
        return (custom_options_dict_postsave or {}).get('scheduler_id') or ''
    raw = request_form.get('scheduler_id')
    return raw if raw is not None else ((custom_options_dict_postsave or {}).get('scheduler_id') or '')


def _sync_scheduler_assignment(old_scheduler, old_dev_eui, new_scheduler, new_dev_eui):
    """scheduler_id/dev_eui 변경을 lorawan_class_scheduler의 슬롯맵에 반영한다.
    실패해도 장치 저장 자체를 막지 않는다 — 스케줄러 자체가 아직 없거나
    비활성 상태여도 접속정보 저장은 항상 성공해야 한다."""
    from aot.functions._lorawan_common import assign_device_to_scheduler

    try:
        if old_scheduler and old_dev_eui and (
                old_scheduler != new_scheduler or old_dev_eui != new_dev_eui):
            assign_device_to_scheduler(old_scheduler, old_dev_eui, assign=False)
        if new_scheduler and new_dev_eui:
            assign_device_to_scheduler(new_scheduler, new_dev_eui, assign=True)
    except Exception:
        logger.exception("AoT-C: 스케줄러 배정 갱신 실패 (scheduler_id=%s, dev_eui=%s)",
                          new_scheduler, new_dev_eui)


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
    """접속정보·DevEUI·스케줄러 배정을 저장할 때마다 하위/외부로 재전파한다.

    device_modbus_plc_generic.py와 동일한 이유로 생성 시점이 아니라 저장
    시점에야 실제 값이 있다(execute_at_creation은 아직 드라이버 기본값인
    시점에 호출됨, device_blueprint.py 상단 docstring 참조).
    """
    import json

    from aot.utils.device_blueprint import sync_inherited_options

    # scheduler_id는 postsave 딕셔너리를 신뢰하지 않고 실제 제출값으로
    # 덮어쓴다(_resolve_submitted_scheduler_id 참조) — 그래야 "선택 해제"로
    # 저장했을 때 DB에도 실제로 비워지고, 다음에 모달을 열었을 때 드롭다운이
    # 다시 이전 값으로 보이는 불일치가 생기지 않는다.
    old_scheduler = (custom_options_dict_presave or {}).get('scheduler_id') or ''
    old_dev_eui = (custom_options_dict_presave or {}).get('dev_eui') or ''
    new_scheduler = _resolve_submitted_scheduler_id(request_form, custom_options_dict_postsave)
    custom_options_dict_postsave['scheduler_id'] = new_scheduler
    new_dev_eui = (custom_options_dict_postsave or {}).get('dev_eui') or ''

    mod_controller.custom_options = json.dumps(custom_options_dict_postsave)
    sync_inherited_options(mod_controller, FUNCTION_INFORMATION['device_blueprint'])
    _sync_device_euis(mod_controller)
    _sync_scheduler_assignment(old_scheduler, old_dev_eui, new_scheduler, new_dev_eui)

    return (
        messages,
        mod_controller,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave,
        False,
    )


FUNCTION_INFORMATION['execute_at_modification'] = execute_at_modification


class CustomModule:
    """장치 자신은 아무 로직도 없는 컨테이너다(device_modbus_plc_generic.py와
    동일한 근거) — 실제 폴링·다운링크는 하위 Input/Output이, class 관리는
    사용자가 고른 lorawan_class_scheduler가 수행한다."""

    def __init__(self, function, testing=False):
        pass
