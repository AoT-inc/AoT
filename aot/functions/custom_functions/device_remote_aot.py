# coding=utf-8
"""AoT 복합장치: 원격 AoT 서버.

다른 AoT 인스턴스 하나를 장치 한 대로 다룬다. 접속정보(호스트·API 키·프로토콜)
를 여기 한 번만 넣으면 청사진이 수집용 Input(`REMOTE_AOT`)과 제어용
Output(`remote_output`)을 함께 만들고, 저장할 때마다 그 값을 하위로 다시
전파한다.

**이 모듈이 없으면 같은 접속정보를 두 번 이상 입력해야 한다.** 원격 수집과
원격 제어는 서로 다른 드라이버이고 각자 host/api_key 옵션을 갖고 있어서,
서버 한 대를 붙일 때마다 같은 키를 여러 화면에 복사해 넣게 된다. 키가 바뀌면
바뀐 곳을 사람이 기억해서 전부 고쳐야 한다.

**PWM 출력은 청사진에 넣지 않는다.** 원격 PWM(`remote_output_pwm`)은 필요한
현장이 드물어 기본 구성에 넣으면 대부분의 장치에 안 쓰는 Output 이 하나씩
붙는다. 필요하면 장치 설정의 "연결된 Input/Output" 에서 붙이면 되고, 그때도
접속정보는 그 Output 에 직접 입력해야 한다(청사진 밖의 항목은
`sync_inherited_options` 가 건드리지 않는다 — 하위가 스스로 바꾼 설정을 부모가
덮어쓰지 않는다는 규칙 때문이다).

@phase active
@stability experimental
@dependency device_blueprint, RemoteAoTClient
"""
import logging
import re

from flask_babel import lazy_gettext

logger = logging.getLogger(__name__)

#: 하위 Input/Output 에 그대로 복사되는 접속정보 키. 세 드라이버
#: (`remote_aot_input`, `remote_output_on_off`, `remote_output_pwm`)와
#: `RemoteAoTClient.from_options()` 가 같은 이름을 쓰기로 한 계약이다 —
#: 한쪽만 바꾸면 전파가 조용히 끊긴다(inherit_options 는 이름이 같은 키만
#: 복사한다).
_CONNECTION_KEYS = ['host', 'api_key', 'scheme', 'verify_tls', 'request_timeout']

FUNCTION_INFORMATION = {
    'function_name_unique': 'device_remote_aot',
    # "장치: " 접두어를 여기 넣지 않는 이유는 device_modbus_plc_generic.py 의
    # 동일 주석 참조 — 접두어는 routes_device.py 의 choices_devices 에서만 붙인다.
    'function_name': lazy_gettext('Remote AoT Server'),
    'function_name_short': lazy_gettext('Remote AoT'),

    'is_device': True,
    'device_category': 'controller',

    # 장치 자신은 측정 채널을 갖지 않는다(측정은 하위 Input 이 한다) —
    # device_modbus_plc_generic.py 와 같은 이유로 끈다.
    'options_disabled': [
        'measurements_select',
        'measurements_configure',
    ],

    'message': lazy_gettext(
        'Another AoT server as a single manageable unit. Enter the connection details '
        'once here and they are copied to the collection Input and the control Output '
        'created alongside this device. After saving, the Input\'s Remote Measurement '
        'dropdowns are filled with the channels found on that server — set the number of '
        'measurements on the Input and pick one for each. '
        'SECURITY: an AoT API key carries every permission of the user it belongs to. If '
        'you only want to collect data, use a key belonging to a remote user whose role '
        'has just "View Settings"; an admin key would also grant control of that server.'),

    'options_enabled': ['custom_options'],

    'custom_options': [
        {
            'id': 'host',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Remote AoT Host'),
            'phrase': lazy_gettext('The host or IP address of the remote AoT (a port may be included, e.g. 192.168.0.9:8084)')
        },
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Remote AoT API Key'),
            'phrase': lazy_gettext('The API key of the remote AoT, exactly as shown on that server')
        },
        {
            'id': 'scheme',
            'type': 'select',
            'default_value': 'https',
            'options_select': [
                ('https', 'HTTPS'),
                ('http', 'HTTP')
            ],
            'name': lazy_gettext('Protocol'),
            'phrase': lazy_gettext('Use HTTPS unless the remote AoT is only reachable over plain HTTP on a trusted network')
        },
        {
            'id': 'verify_tls',
            'type': 'bool',
            'default_value': True,
            'name': lazy_gettext('Verify TLS Certificate'),
            'phrase': lazy_gettext('Verify the remote server certificate. Turn this off only for a self-signed certificate on a trusted network — while off, the API key can be read by a man in the middle')
        },
        {
            'id': 'request_timeout',
            'type': 'integer',
            'default_value': 30,
            'name': lazy_gettext('Request Timeout (Seconds)'),
            'phrase': lazy_gettext('HTTP read timeout for requests to the remote server')
        }
    ],

    # 채널 스펙('channels')은 생략한다. 원격이 몇 개의 측정을 갖고 있는지는
    # 접속하기 전에 알 수 없고, 장치를 만드는 시점에는 접속정보가 아직 드라이버
    # 기본값(빈 문자열)이기 때문이다(device_blueprint.py 상단 docstring).
    # Input 은 measurements_variable_amount 라 빈 채널 하나가 자동 생성되고,
    # 실제 채널 수는 사용자가 Input 페이지에서 정한다.
    'device_blueprint': {
        'inputs': [
            {
                'device': 'REMOTE_AOT',
                'name': '{device_name} 수집',
                'inherit_options': _CONNECTION_KEYS,
            },
        ],
        'outputs': [
            {
                'device': 'remote_output',
                'name': '{device_name} 제어',
                'inherit_options': _CONNECTION_KEYS,
            },
        ],
    },
}


#: 하위 항목 이름의 기본형. 접속정보가 채워지면 뒤에 " (host)" 가 붙는다.
#: 청사진의 name 템플릿과 같은 문자열이어야 한다(위 device_blueprint 참조).
_INPUT_NAME_BASE = '{device_name} 수집'
_OUTPUT_NAME_BASE = '{device_name} 제어'

#: 이름 규칙: **앞부분은 사용자 것, 괄호 안 호스트는 우리 것.**
#:
#: "사용자가 고쳤는지" 를 이름 전체로 판정하려 했더니 장치 이름을 바꾸는 저장에서
#: 곧바로 깨졌다 — 그 한 번의 저장에서 장치는 새 이름이 되는데 하위 Input 은 아직
#: 옛 이름을 갖고 있어, 어느 쪽과 비교해도 "사용자가 고친 것" 으로 보였다.
#: 그래서 이름 전체를 관리하지 않고 **끝의 괄호 부분만** 관리한다. 사용자가 지은
#: 이름은 그대로 두고 출처만 덧붙이므로 무엇을 덮어쓸 걱정이 없다.
#:
#: 괄호를 떼어낼 때는 호스트처럼 생긴 것만 뗀다(영숫자·점·하이픈·콜론·대괄호).
#: "센서 (외부)" 처럼 사람이 쓴 괄호는 남는다 — 지우는 것보다 덧붙이는 쪽이 안전하다.
_HOSTLIKE_SUFFIX = re.compile(r'\s*\(([A-Za-z0-9._\-:\[\]]+)\)\s*$')


def _strip_host_suffix(name):
    return _HOSTLIKE_SUFFIX.sub('', name or '').strip()


def _auto_child_name(base_template, device_name, host, current_name=None):
    base = _strip_host_suffix(current_name) if current_name else ''
    if not base:
        base = base_template.format(device_name=device_name or 'Remote AoT')
    return '{b} ({h})'.format(b=base, h=host) if host else base


def execute_at_creation(error, new_func, dict_functions=None):
    from aot.utils.device_blueprint import create_blueprint_members
    error, _created = create_blueprint_members(
        error, new_func, FUNCTION_INFORMATION['device_blueprint'])
    return error, new_func


FUNCTION_INFORMATION['execute_at_creation'] = execute_at_creation


def _refresh_child_input_choices(parent_device, options):
    """하위 REMOTE_AOT Input 의 원격 측정 목록을 미리 채워 둔다.

    이 단계가 없으면 사용자는 장치에 접속정보를 넣어 저장한 뒤, 다시 Input
    페이지로 가서 한 번 더 저장해야 드롭다운이 채워진다(디스커버리가 Input 의
    execute_at_modification 에서만 돌기 때문). 접속정보를 한 번만 넣게 하려고
    만든 장치에서 그 왕복이 남으면 의미가 없다.

    조회 실패는 저장을 막지 않는다 — 원격이 잠깐 닿지 않아도 접속정보 저장
    자체는 성립해야 하고, Input 쪽에서 다시 시도할 수 있다.

    :return: 사용자에게 보여줄 알림 문자열, 또는 None
    """
    import json

    from aot.databases.models import Input, InputChannel
    from aot.utils.remote_aot_client import (
        RemoteAoTClient, RemoteAoTError, discover_measurements)

    client = RemoteAoTClient.from_options(options, logger_=logger)
    if not client.configured:
        return None

    children = Input.query.filter_by(
        parent_device_id=parent_device.unique_id, device='REMOTE_AOT').all()
    if not children:
        return None

    try:
        choices = discover_measurements(client)
    except RemoteAoTError as err:
        return "Remote AoT: saved, but could not read the measurement list from {host} ({err})".format(
            host=client.host, err=err)

    if not choices:
        return ("Remote AoT: connected to {host} but it reported no measurements. "
                "If that server does have Inputs, the API key's user may lack "
                "'View Settings'.".format(host=client.host))

    for child in children:
        for channel in InputChannel.query.filter_by(input_id=child.unique_id).all():
            try:
                opts = json.loads(channel.custom_options) if channel.custom_options else {}
                if not isinstance(opts, dict):
                    opts = {}
            except Exception:
                opts = {}
            opts['remote_measurement_choices'] = choices
            channel.custom_options = json.dumps(opts)
            channel.save()

    return "Remote AoT: {n} measurement(s) available on {host}.".format(
        n=len(choices), host=client.host)


def _rename_children(parent_device, options):
    """수집 Input·제어 Output 이름에 원격 호스트를 드러낸다.

    이름만 보고는 어느 서버를 가리키는지 알 수 없었다. 원격 서버를 여러 대
    붙이면 "Remote AoT 수집"·"Remote AoT 제어" 가 여러 개 생기고, 그래프·리포트
    ·출력 목록에서 서로 구별되지 않는다. 특히 제어 Output 은 잘못 고르면 남의
    농장 밸브를 여닫는 것이라 출처가 이름에 보이는 편이 안전하다.

    사용자가 지은 이름은 유지하고 **끝의 "(호스트)" 만** 우리가 관리한다
    (`_HOSTLIKE_SUFFIX` 주석 참조). 그래서 "온실 A 외부기상" 은
    "온실 A 외부기상 (10.0.0.5:9000)" 이 되고, 호스트를 바꾸면 괄호 안만 바뀐다.

    호스트만 넣고 API 키는 넣지 않는다 — 이름은 목록·그래프·로그에 그대로
    노출되는 문자열이다.

    청사진이 만든 항목만 대상으로 한다(`sync_inherited_options` 와 같은 범위) —
    사용자가 나중에 손수 연결한 Input/Output 은 이 장치 소유가 아니므로 이름을
    건드리지 않는다.

    :return: 바꾼 이름 목록
    """
    from aot.databases.models import Input, Output

    host = (options.get('host') or '').strip()
    if not host:
        return []

    # (모델, 드라이버컬럼, 드라이버값, 이름템플릿)
    # Input 은 `device`, Output 은 `output_type` 으로 드라이버를 갖는다 — 컬럼
    # 이름이 다르다(device_blueprint.sync_inherited_options 의 동일 주석 참조).
    targets = (
        (Input, 'device', 'REMOTE_AOT', _INPUT_NAME_BASE),
        (Output, 'output_type', 'remote_output', _OUTPUT_NAME_BASE),
    )

    renamed = []
    for model, column, driver, template in targets:
        rows = model.query.filter_by(**{
            'parent_device_id': parent_device.unique_id, column: driver}).all()
        for child in rows:
            current = (child.name or '').strip()
            new_name = _auto_child_name(
                template, parent_device.name, host, current_name=current)
            if current == new_name:
                continue
            child.name = new_name
            child.save()
            renamed.append(new_name)
    return renamed


def execute_at_modification(
        messages,
        mod_controller,
        request_form,
        custom_options_dict_presave,
        custom_options_channels_dict_presave,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave):
    """접속정보를 하위 Input/Output 에 재전파하고 원격 측정 목록을 새로 읽는다."""
    import json

    from aot.utils.device_blueprint import sync_inherited_options

    # mod_controller 는 아직 커밋되지 않았다(controller_mod() 가 이 함수의
    # 반환값으로 custom_options 를 다시 덮어써 최종 저장한다) — sync 는 이번에
    # 저장될 postsave 값을 기준으로 해야 하므로 여기서 임시로 반영해 둔다.
    mod_controller.custom_options = json.dumps(custom_options_dict_postsave)
    sync_inherited_options(mod_controller, FUNCTION_INFORMATION['device_blueprint'])

    # 이름에 원격 호스트를 드러낸다. 실패해도 저장 자체는 통과시킨다 — 이름은
    # 표시용이고, 여기서 예외가 올라가면 접속정보 저장이 통째로 실패한다.
    try:
        _rename_children(mod_controller, custom_options_dict_postsave)
    except Exception:
        logger.exception("device_remote_aot: renaming child Input/Output failed")

    try:
        note = _refresh_child_input_choices(mod_controller, custom_options_dict_postsave)
    except Exception:
        # 디스커버리는 편의 기능이다. 여기서 예외가 올라가면 접속정보 저장
        # 자체가 실패하므로, 실패해도 저장은 통과시킨다.
        logger.exception("device_remote_aot: refreshing remote measurements failed")
        note = "Remote AoT: saved, but refreshing the remote measurement list failed."

    if note:
        messages["info"].append(note)

    return (
        messages,
        mod_controller,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave,
        False,
    )


FUNCTION_INFORMATION['execute_at_modification'] = execute_at_modification


class CustomModule:
    """장치 자신은 로직이 없는 컨테이너다 — loop()/listener() 를 선언하지 않아
    controller_function.py 가 has_loop=False 로 판정한다. 실제 수집·제어는
    하위 Input/Output 이 각자의 컨트롤러에서 수행한다.
    """

    def __init__(self, function, testing=False):
        pass
