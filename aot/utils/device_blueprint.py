# coding=utf-8
"""복합장치(Device) 티어 — 청사진 기반 하위 Input/Output 자동 생성.

설계 근거: .local/plans/device_group_console_plan.md (Phase 2).

장치는 새 테이블이 아니라 is_device=True 를 선언한 Custom Function 모듈이다
(aot/utils/functions.py device_module_names 참조). 이 모듈은 자신의
FUNCTION_INFORMATION['device_blueprint']에 만들 하위 Input/Output 목록을
선언하고, execute_at_creation 에서 create_blueprint_members() 를 호출하기만
하면 된다 — 실제 생성은 이 파일이 대신한다.

이 파일이 스캔되지 않는 이유(중요): parse_function_information() 은
aot/functions/ 와 aot/functions/custom_functions/ 의 최상위 파일만 순회한다
(재귀 없음). 이 파일은 aot/utils/ 에 있으므로 그 경로 밖이라 스캐너가 아예
보지 못한다 — 헬퍼 모듈을 custom_functions/ 안에 두면(원래 계획서 2.1 초안)
스캐너가 매 부팅마다 로드를 시도하고 실패 로그를 남기는 부작용이 있어
피했다(env_coordinator_impl/ 이 이미 이 부작용을 겪고 있다).

핵심 제약 — input_add()/output_add() 재사용:
  자체 재구현 대신 aot_flask/utils 의 검증된 생성 경로(input_add/output_add)를
  그대로 호출한다. 이 함수들은 WTForms 폼 객체가 아니라 `<field>.data` 속성과
  `.validate()` 메서드만 참조하므로(코드로 확인, 실제 FlaskForm 인스턴스화는
  CSRF·request 바인딩을 끌고 들어와 오히려 더 취약하다) _FormAdapter 로 충분하다.
  두 함수 모두 Flask 요청 컨텍스트(current_app)를 참조하므로, 이 모듈의
  함수들은 반드시 Flask 라우트 핸들러 안에서 실행되는 execute_at_creation
  경로를 통해서만 호출해야 한다 — 데몬 프로세스에서 직접 호출하면 깨진다.
  (기존 Function execute_at_creation 전체가 이미 같은 제약을 갖고 있다.)

트랜잭션 순서: execute_at_creation 은 부모 장치(new_device)가 아직
db.session.commit() 되기 전에 호출된다(utils_function.py — unique_id/
custom_options 는 그 전에 채워지지만 save() 는 그 다음). 그래서 이 파일이
만드는 자식이 부모보다 먼저 커밋될 수 있다. parent_device_id 에 FK 제약을
걸지 않은 이유(Phase 1)가 여기서도 유효하다 — 커밋 순서가 뒤바뀌어도 참조
무결성 오류가 나지 않는다.

@phase active
@stability experimental
@dependency Input, Output, InputChannel, OutputChannel, DeviceMeasurements
"""
import json
import logging

from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
from aot.databases.models import (
    DeviceMeasurements, Input, InputChannel, Output, OutputChannel,
)
from aot.services.tab_service import TabService
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import parse_output_information

logger = logging.getLogger(__name__)


class _FormField:
    def __init__(self, value):
        self.data = value


class _FormAdapter:
    """input_add()/output_add() 가 기대하는 최소 인터페이스만 흉내낸다.

    실제로 참조되는 것은 <type_field>.data, .validate(), (실패 시만) .errors
    세 가지뿐임을 두 함수의 전체 본문을 읽어 확인했다.
    """

    def __init__(self, type_field, value):
        setattr(self, type_field, _FormField(value))
        self.errors = {}

    def validate(self):
        return True


def _default_tab_id(page_type):
    try:
        tab = TabService.get_default_tab(page_type)
        return tab.unique_id if tab else None
    except Exception:
        logger.exception("device_blueprint: default tab lookup failed for %s", page_type)
        return None


def _module_interface(dict_devices, device_name):
    """'MODBUS_TCP,IP' 형태로 input_add/output_add 에 넘길 인터페이스 접미사.

    interfaces 를 선언하지 않은 드라이버(가상 장치 등)는 빈 문자열로 둔다 —
    input_add 는 interface 가 falsy 면 그냥 건너뛴다(코드 확인).
    """
    ifaces = (dict_devices.get(device_name) or {}).get('interfaces') or []
    return ifaces[0] if ifaces else ''


def _apply_inherited_options(custom_options_json, parent_options, inherit_keys):
    """자식의 custom_options 중 inherit_keys 에 해당하는 값만 부모 값으로 덮어쓴다.

    부모→자식 단방향, 명시 호출 시에만(계획서 2.2) — 자식이 스스로 바꾼 다른
    옵션(레지스터 주소 등)은 절대 건드리지 않는다.
    """
    try:
        opts = json.loads(custom_options_json) if custom_options_json else {}
        if not isinstance(opts, dict):
            opts = {}
    except Exception:
        opts = {}
    for key in inherit_keys or []:
        if key in parent_options:
            opts[key] = parent_options[key]
    return json.dumps(opts)


# --------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------- #

def _sync_input_channels(dict_inputs, device_name, input_id, channel_specs, error):
    """청사진의 channels 스펙대로 InputChannel + DeviceMeasurements 를 채운다.

    채널 0 은 Input 생성 시 check_input_channels_exist() 가 이미 만들어 둔
    상태이므로 조회 후 갱신한다. 그 이상 채널은 직접 생성한다 — Modbus TCP
    Input 처럼 measurements_variable_amount 드라이버는 num_channels 같은
    '몇 개' 옵션이 없고, InputChannel/DeviceMeasurements 의 존재 자체가
    채널 개수를 결정하기 때문에 이 방식이 유일한 경로다.
    """
    for idx, ch_spec in enumerate(channel_specs):
        ic = InputChannel.query.filter_by(input_id=input_id, channel=idx).first()
        if ic is None:
            ic = InputChannel()
            ic.input_id = input_id
            ic.channel = idx
            error, opts_json = custom_channel_options_return_json(
                error, dict_inputs, None, input_id, idx,
                device=device_name, use_defaults=True)
            ic.custom_options = opts_json
            ic.save()

        try:
            opts = json.loads(ic.custom_options) if ic.custom_options else {}
            if not isinstance(opts, dict):
                opts = {}
        except Exception:
            opts = {}
        for key, value in ch_spec.items():
            # measurement/unit 은 InputChannel 스키마에 없는 DeviceMeasurements
            # 전용 필드라 스킵한다. name 은 다르다 — modbus_tcp.py 의
            # custom_channel_options 에도 'name' 필드가 실제로 있고 화면 표시에
            # 쓰이므로, DeviceMeasurements.name 과 별개로 여기도 채워야 한다.
            # (최초 구현에서 셋 다 스킵했다가 Output 쪽 채널 이름이 저장되지
            # 않는 버그로 드러나 수정 — 3절 참조)
            if key in ('measurement', 'unit'):
                continue
            opts[key] = value
        ic.custom_options = json.dumps(opts)
        ic.save()

        dm = DeviceMeasurements.query.filter_by(device_id=input_id, channel=idx).first()
        if dm is None:
            dm = DeviceMeasurements()
            dm.device_id = input_id
            dm.channel = idx
        if 'name' in ch_spec:
            dm.name = str(ch_spec['name'])
        if 'measurement' in ch_spec:
            dm.measurement = str(ch_spec['measurement'])
        if 'unit' in ch_spec:
            dm.unit = str(ch_spec['unit'])
        # is_enabled 기본값이 True(measurement.py) 이므로 여기서 별도로
        # 켤 필요는 없지만, 기존 행을 재사용하는 경로에서 꺼져 있었을 가능성을
        # 배제하기 위해 명시한다 — 청사진이 만든 채널은 항상 폴링 대상이어야 한다.
        dm.is_enabled = True
        dm.save()

    return error


def _create_input_member(spec, parent_device, parent_options, error):
    from aot.aot_flask.utils.utils_input import input_add

    device_name = spec.get('device')
    dict_inputs = parse_input_information()
    if device_name not in dict_inputs:
        error.append(f"장치 청사진: 알 수 없는 Input 드라이버 '{device_name}'")
        return None

    # input_add()는 콤마가 정확히 1개인 문자열만 받아들이고(그 외엔 input_name=''
    # 로 처리해 KeyError를 낸다 — 실제로 chirpstack_mqtt_jmespath처럼 'interfaces'
    # 를 선언하지 않는 드라이버에서 재현됨, AoT-C 장치 실증 중 발견) 콤마는
    # iface가 비어 있어도 항상 붙여야 한다.
    iface = _module_interface(dict_inputs, device_name)
    form = _FormAdapter('input_type', f"{device_name},{iface}")
    tab_id = _default_tab_id('input')

    messages, dep_name, dep_list, dep_message, new_input_id = input_add(form, tab_id)
    if messages.get('error') or not new_input_id:
        error.extend(messages.get('error') or [])
        if dep_list:
            error.append(f"장치 청사진: '{device_name}' 의존성 미충족 — {dep_message}")
        return None

    new_row = Input.query.filter_by(unique_id=new_input_id).first()
    if new_row is None:
        error.append(f"장치 청사진: Input '{device_name}' 생성 직후 조회 실패")
        return None

    if spec.get('name'):
        try:
            new_row.name = spec['name'].format(device_name=parent_device.name)
        except Exception:
            new_row.name = spec['name']
    new_row.parent_device_id = parent_device.unique_id
    new_row.custom_options = _apply_inherited_options(
        new_row.custom_options, parent_options, spec.get('inherit_options'))
    new_row.save()

    channels = spec.get('channels') or []
    if channels:
        error = _sync_input_channels(dict_inputs, device_name, new_input_id, channels, error)

    return new_input_id


# --------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------- #

def _sync_output_channels(dict_outputs, device_name, output_id, channel_specs, error):
    """Input과 대칭이나 두 가지가 다르다.

    (1) DeviceMeasurements 는 채널 0 용 항목(measurements_dict, 보통
        duration_time)이 output_add() 시점에 이미 만들어져 있고 채널마다
        새로 필요하지 않은 드라이버가 많다 — 그래서 spec 에 measurement/unit
        이 명시된 경우에만 만든다(Input처럼 항상 만들지 않는다).
    (2) 채널 개수를 num_channels 류 옵션으로 노출하는 드라이버(Modbus 코일,
        MQTT Multi 등)가 있다 — 실제 채널 행 개수와 그 표시값이 어긋나면
        사용자가 설정 화면을 열었을 때 혼란스러우므로 맞춰 둔다.
    """
    for idx, ch_spec in enumerate(channel_specs):
        oc = OutputChannel.query.filter_by(output_id=output_id, channel=idx).first()
        if oc is None:
            oc = OutputChannel()
            oc.output_id = output_id
            oc.channel = idx
            error, opts_json = custom_channel_options_return_json(
                error, dict_outputs, None, output_id, idx,
                device=device_name, use_defaults=True)
            oc.custom_options = opts_json
            oc.save()

        try:
            opts = json.loads(oc.custom_options) if oc.custom_options else {}
            if not isinstance(opts, dict):
                opts = {}
        except Exception:
            opts = {}
        for key, value in ch_spec.items():
            # measurement/unit 은 OutputChannel 스키마에 없는 DeviceMeasurements
            # 전용 필드라 스킵한다. name 은 스킵하지 않는다 — on_off_modbus.py
            # 의 custom_channel_options 에 'name'(Channel Name) 필드가 있고
            # 이게 화면에 쓰이는 채널 이름이다. Input과 달리 Output 채널에는
            # DeviceMeasurements가 채널마다 있지 않으므로(coil 자체는 보통
            # duration_time 하나만 채널0에 있음, 아래 참조), name을 여기서도
            # 스킵하면 청사진의 채널 이름(예: '관수밸브')이 어디에도 저장되지
            # 않고 사라진다 — Phase 3 device.html 작업 중 실제로 발견한 버그.
            if key in ('measurement', 'unit'):
                continue
            opts[key] = value
        oc.custom_options = json.dumps(opts)
        oc.save()

        if 'measurement' in ch_spec or 'unit' in ch_spec or 'name' in ch_spec:
            dm = DeviceMeasurements.query.filter_by(
                device_id=output_id, channel=idx).first()
            if dm is None:
                dm = DeviceMeasurements()
                dm.device_id = output_id
                dm.channel = idx
            if 'name' in ch_spec:
                dm.name = str(ch_spec['name'])
            if 'measurement' in ch_spec:
                dm.measurement = str(ch_spec['measurement'])
            if 'unit' in ch_spec:
                dm.unit = str(ch_spec['unit'])
            dm.is_enabled = True
            dm.save()

    row = Output.query.filter_by(unique_id=output_id).first()
    if row is not None:
        try:
            opts = json.loads(row.custom_options) if row.custom_options else {}
        except Exception:
            opts = {}
        if isinstance(opts, dict) and 'num_channels' in opts:
            opts['num_channels'] = len(channel_specs)
            row.custom_options = json.dumps(opts)
            row.save()

    return error


def _create_output_member(spec, parent_device, parent_options, error):
    from aot.aot_flask.utils.utils_output import output_add

    device_name = spec.get('device')
    dict_outputs = parse_output_information()
    if device_name not in dict_outputs:
        error.append(f"장치 청사진: 알 수 없는 Output 드라이버 '{device_name}'")
        return None

    # output_add()도 input_add()와 동일하게 콤마 1개를 요구한다 — 위 Input 쪽과
    # 같은 이유로 iface가 비어 있어도 콤마를 항상 붙인다.
    iface = _module_interface(dict_outputs, device_name)
    form = _FormAdapter('output_type', f"{device_name},{iface}")
    tab_id = _default_tab_id('output')

    # output_add 는 request_form 을 채널 custom_options 기본값 생성에 그대로
    # 넘기지만 None 이면 use_defaults 경로로만 도니 안전하다(코드 확인).
    messages, dep_name, dep_list, dep_message, new_output_id, size_y = output_add(
        form, None, tab_id)
    if messages.get('error') or not new_output_id:
        error.extend(messages.get('error') or [])
        if dep_list:
            error.append(f"장치 청사진: '{device_name}' 의존성 미충족 — {dep_message}")
        return None

    new_row = Output.query.filter_by(unique_id=new_output_id).first()
    if new_row is None:
        error.append(f"장치 청사진: Output '{device_name}' 생성 직후 조회 실패")
        return None

    if spec.get('name'):
        try:
            new_row.name = spec['name'].format(device_name=parent_device.name)
        except Exception:
            new_row.name = spec['name']
    new_row.parent_device_id = parent_device.unique_id
    new_row.custom_options = _apply_inherited_options(
        new_row.custom_options, parent_options, spec.get('inherit_options'))
    new_row.save()

    channels = spec.get('channels') or []
    if channels:
        error = _sync_output_channels(dict_outputs, device_name, new_output_id, channels, error)

    return new_output_id


# --------------------------------------------------------------------- #
# 공개 API
# --------------------------------------------------------------------- #

def create_blueprint_members(error, new_device, blueprint):
    """장치 모듈의 execute_at_creation 이 위임하는 진입점.

    :param error: execute_at_creation 이 받은 error 리스트(그대로 이어받아 반환)
    :param new_device: 아직 저장(commit)되지 않은 CustomController 인스턴스.
        unique_id/custom_options 는 이미 채워져 있다(호출 시점 보장, 이 파일
        상단 docstring 참조).
    :param blueprint: FUNCTION_INFORMATION['device_blueprint']
    :return: (error, created) — created = {'inputs': [...], 'outputs': [...]}
        (functions 는 이번 범위에서 다루지 않는다 — 6절 참조)
    """
    try:
        parent_options = json.loads(new_device.custom_options) if new_device.custom_options else {}
        if not isinstance(parent_options, dict):
            parent_options = {}
    except Exception:
        parent_options = {}

    created = {'inputs': [], 'outputs': []}

    for spec in (blueprint or {}).get('inputs') or []:
        new_id = _create_input_member(spec, new_device, parent_options, error)
        if new_id:
            created['inputs'].append(new_id)

    for spec in (blueprint or {}).get('outputs') or []:
        new_id = _create_output_member(spec, new_device, parent_options, error)
        if new_id:
            created['outputs'].append(new_id)

    return error, created


def sync_inherited_options(parent_device, blueprint):
    """장치의 접속정보 저장(수정) 시 하위에 inherit_options 만 다시 전파.

    청사진은 '생성 시' 한 번만 적용되면 끝이 아니다 — 사용자가 장치를 처음
    추가한 시점의 custom_options 는 드라이버 기본값(대개 빈 문자열)이고,
    실제 접속정보는 그 다음 장치 설정을 저장할 때 채워진다. 그래서 각 장치
    모듈은 자신의 execute_at_modification 안에서 이 함수를 호출해야
    "접속정보 1회 입력"이라는 청사진의 핵심 가치가 실제로 성립한다.

    inherit_options 가 없는 스펙은 건드리지 않는다. 하위 항목이 채널 정의 등
    다른 설정을 스스로 바꿔 놨을 수 있으므로 그 부분은 절대 만지지 않는다.
    """
    try:
        parent_options = json.loads(parent_device.custom_options) if parent_device.custom_options else {}
        if not isinstance(parent_options, dict):
            parent_options = {}
    except Exception:
        parent_options = {}

    # Input.device / Output.output_type — 이름이 다른 두 컬럼을 같은 루프에서
    # 다루려고 row.device 로 통일해 버렸다가 AttributeError 로 실제로 걸렸다.
    # (device_blueprint.py 검증 중 발견) 모델별 device 값 접근자를 분리한다.
    device_field = {Input: lambda r: r.device, Output: lambda r: r.output_type}

    for model, blueprint_key in ((Input, 'inputs'), (Output, 'outputs')):
        specs_by_device = {}
        for spec in (blueprint or {}).get(blueprint_key) or []:
            if spec.get('inherit_options'):
                specs_by_device[spec.get('device')] = spec

        if not specs_by_device:
            continue

        get_device = device_field[model]
        rows = model.query.filter_by(parent_device_id=parent_device.unique_id).all()
        for row in rows:
            spec = specs_by_device.get(get_device(row))
            if not spec:
                continue
            row.custom_options = _apply_inherited_options(
                row.custom_options, parent_options, spec['inherit_options'])
            row.save()


# --------------------------------------------------------------------- #
# 활성화 연동 (Phase 4)
# --------------------------------------------------------------------- #

def _cascade_inputs(device, action, messages):
    """장치 활성화/비활성화 시 하위 Input 을 함께 전환한다.

    Output 은 대상이 아니다 — Output 모델에는 is_activated 개념 자체가 없다
    (Input/Function 과 다름, 코드로 확인). output_add() 가 저장 직후
    manipulate_output('Add', ...) 로 데몬에 즉시 등록하므로, Output 은 청사진
    생성 시점에 이미 데몬이 알고 있다. 그래서 cascade가 필요한 건 Input 뿐이다.

    input_activate()/input_deactivate() 를 자체 재구현하지 않고 그대로
    재사용한다 — period 설정 여부, 필수 옵션 채움 여부, 측정 채널 활성화 여부
    같은 검증을 다시 만들면 두 경로가 갈릴 위험이 있다. 두 함수 모두
    form_mod.input_id.data 만 참조하므로(코드 확인) 이 파일 상단의 _FormAdapter
    로 충분하다.

    실패는 장치 자신의 활성화/비활성화를 막지 않는다 — 접속정보를 아직
    입력하지 않은 채로 장치를 막 추가한 직후에는 하위 Input 활성화가
    거의 항상 실패하는데(필수 옵션 미충족), 그때마다 장치 자체가 활성화되지
    않으면 사용자가 설정을 입력할 방법이 없어진다. 실패는 messages['warning']
    에만 쌓는다.
    """
    from aot.aot_flask.utils.utils_input import input_activate, input_deactivate

    fn = input_activate if action == 'activate' else input_deactivate
    warnings = messages.setdefault('warning', [])

    for inp in Input.query.filter_by(parent_device_id=device.unique_id).all():
        form = _FormAdapter('input_id', inp.unique_id)
        result = fn(form)
        for err in (result or {}).get('error') or []:
            warnings.append(f"{inp.name}: {err}")

    return messages


def cascade_activate_inputs(device, messages):
    return _cascade_inputs(device, 'activate', messages)


def cascade_deactivate_inputs(device, messages):
    return _cascade_inputs(device, 'deactivate', messages)


# --------------------------------------------------------------------- #
# 기존 항목 연결/해제 (Phase 6) + 다대다 소속 & 장치 간 계층 (Phase 8/9) —
# 청사진이 만들지 않은, 사용자가 이미 갖고 있던 Input/Output/Device를 나중에
# 장치 구성에 편입한다. 6절이 "미답"으로 남겨 뒀던 세 경로 중 "기존 항목 편입
# UI"는 Phase 6, "장치 간 계층"과 "다대다 소속"은 이 절에서 함께 해소한다.
#
# 소유(primary, parent_device_id)와 참조(secondary, DeviceMember)는 뜻이
# 다르다. primary는 청사진 자동 생성물이 다니는 단일 소유 관계이고 활성화
# cascade(Phase 4)가 여기만 본다. secondary는 "이미 다른 곳에 속한 항목을
# 추가로 이 장치 구성에도 보여준다"는 참조 전용 관계로, cascade에 관여하지
# 않는다 — 두 장치가 같은 Input을 참조할 때 한쪽이 꺼진다고 다른 쪽이 의존하는
# 항목까지 꺼지면 안 되기 때문이다. link_member()는 항목이 아직 미소속이면
# primary로, 이미 다른 곳 소속이면 secondary로 자동 판단해 연결한다(다대다).
# 장치가 장치를 참조하면(member_type='device') 그것이 곧 장치 간 계층이다 —
# 항상 secondary로만 연결하고(장치 자동 생성이 스스로 하위 장치를 만드는
# 경로는 이번 범위 밖), 순환 참조는 조상 체인 검사로 거부한다.
# --------------------------------------------------------------------- #

_MEMBER_MODELS_CACHE = None


def _member_models():
    global _MEMBER_MODELS_CACHE
    if _MEMBER_MODELS_CACHE is None:
        from aot.databases.models.controller import CustomController
        _MEMBER_MODELS_CACHE = {'input': Input, 'output': Output, 'device': CustomController}
    return _MEMBER_MODELS_CACHE


def _member_row(member_type, member_id):
    model = _member_models().get(member_type)
    if model is None:
        return None
    return model.query.filter_by(unique_id=member_id).first()


def _linked_ids(device_id, member_type):
    """device_id 에 이미(primary 또는 secondary로) 연결된 member_type 의 id 집합."""
    from aot.databases.models.device_member import DeviceMember

    model = _member_models()[member_type]
    ids = {row.unique_id for row in model.query.filter_by(parent_device_id=device_id).all()}
    ids.update(dm.member_id for dm in DeviceMember.query.filter_by(
        device_id=device_id, member_type=member_type).all())
    return ids


def _device_descendants(root_id, _seen=None):
    """root_id 가 (직접·간접적으로) 포함하는 모든 장치 id 집합(root_id 포함).

    순환 참조 방지에 쓴다 — "D를 A의 멤버로 연결하면 순환이 생기는가"는
    "A가 이미 D의 descendants 안에 있는가"로 판정한다(그렇다면 D가 이미
    A를 포함하고 있어, A가 D를 포함하면 고리가 닫힌다).
    """
    from aot.databases.models.controller import CustomController
    from aot.databases.models.device_member import DeviceMember

    if _seen is None:
        _seen = set()
    if root_id in _seen:
        return _seen
    _seen.add(root_id)
    for child in CustomController.query.filter_by(parent_device_id=root_id).all():
        _device_descendants(child.unique_id, _seen)
    for dm in DeviceMember.query.filter_by(device_id=root_id, member_type='device').all():
        _device_descendants(dm.member_id, _seen)
    return _seen


def linkable_members(device_id):
    """device_id 에 아직 연결되지 않은 Input/Output/Device — 연결 후보.

    Phase 6은 "미소속 항목만" 후보로 삼았으나, 다대다 지원으로 그 제약을
    풀었다(설계 6.5 재검토) — 이미 다른 장치 소속인 항목도 후보에 포함하고,
    "이 장치에는 아직 없다"는 기준만 유지한다. 스페이서는 여전히 제외.
    장치 후보에서는 자기 자신과, 연결 시 순환이 생기는 장치(이미 device_id를
    포함하고 있는 장치)를 제외한다.
    """
    from aot.databases.models.controller import CustomController
    from aot.utils.functions import device_module_names

    linked_inputs = _linked_ids(device_id, 'input')
    linked_outputs = _linked_ids(device_id, 'output')
    linked_devices = _linked_ids(device_id, 'device') | {device_id}

    inputs = [i for i in Input.query.filter(Input.device != 'input_spacer')
              .order_by(Input.name).all() if i.unique_id not in linked_inputs]
    outputs = [o for o in Output.query.filter(Output.output_type != 'output_spacer')
               .order_by(Output.name).all() if o.unique_id not in linked_outputs]

    devices = []
    device_names = device_module_names()
    if device_names:
        for d in (CustomController.query
                  .filter(CustomController.device.in_(device_names))
                  .order_by(CustomController.name).all()):
            if d.unique_id in linked_devices:
                continue
            if device_id in _device_descendants(d.unique_id):
                continue  # d가 이미 device_id를 포함 — 연결하면 순환
            devices.append(d)

    return inputs, outputs, devices


def link_member(device_id, member_type, member_id):
    """항목을 device_id 의 구성에 연결한다.

    Input/Output이 아직 어디에도 속하지 않았으면 device_id의 primary 소유가
    된다(Phase 6과 동일 — 활성화 cascade 대상). 이미 다른 곳(다른 장치의
    primary이거나 어떤 장치의 secondary)에 속해 있으면 device_id에는
    secondary(참조)로만 추가한다(다대다). member_type == 'device'는 항상
    secondary로만 연결하고, 자기 자신 연결과 순환 참조는 거부한다.

    :return: 에러 메시지(문자열) 또는 성공 시 None.
    """
    from aot.databases.models.device_member import DeviceMember

    row = _member_row(member_type, member_id)
    if row is None:
        return f"{member_type} not found: {member_id}"

    if member_type == 'device':
        if member_id == device_id:
            return "a device cannot be linked to itself"
        if device_id in _device_descendants(member_id):
            return f"linking {row.name} here would create a device loop"
        if DeviceMember.query.filter_by(
                device_id=device_id, member_type='device', member_id=member_id).first():
            return f"{row.name} is already linked to this device"
        dm = DeviceMember()
        dm.device_id = device_id
        dm.member_type = 'device'
        dm.member_id = member_id
        dm.save()
        return None

    if not row.parent_device_id:
        row.parent_device_id = device_id
        row.save()
        return None

    if row.parent_device_id == device_id:
        return f"{row.name} is already linked to this device"
    if DeviceMember.query.filter_by(
            device_id=device_id, member_type=member_type, member_id=member_id).first():
        return f"{row.name} is already linked to this device"
    dm = DeviceMember()
    dm.device_id = device_id
    dm.member_type = member_type
    dm.member_id = member_id
    dm.save()
    return None


def unlink_member(device_id, member_type, member_id):
    """device_id에 연결된 항목 하나를 해제한다(primary·secondary 어느 쪽이든).

    항목 자체는 삭제하지 않는다 — 소속 표시만 사라진다. 확인을 device_id로
    제한해, 다른 장치 소속 항목의 unique_id를 잘못 넘겨도 그 장치 구성이
    실수로 깨지지 않게 한다.

    :return: 에러 메시지(문자열) 또는 성공 시 None.
    """
    from aot.databases.models.device_member import DeviceMember

    row = _member_row(member_type, member_id)
    if row is None:
        return f"{member_type} not found: {member_id}"

    if row.parent_device_id == device_id:
        row.parent_device_id = None
        row.save()
        return None

    dm = DeviceMember.query.filter_by(
        device_id=device_id, member_type=member_type, member_id=member_id).first()
    if dm is None:
        return f"{row.name} is not linked to this device"
    dm.delete()
    return None


def member_devices(member_type, member_id):
    """이 항목이 소속된 모든 장치 id 목록 — primary(있으면 1개, 맨 앞) +
    secondary(N개). 장치 자신의 카드가 "다른 장치의 하위로도 연결돼 있는가"를
    보여줄 때도, Input/Output 카드 배지에도 이 함수를 쓸 수 있다(단건 조회용
    — 다건은 아래 member_device_map()으로 N+1을 피한다)."""
    from aot.databases.models.device_member import DeviceMember

    row = _member_row(member_type, member_id)
    ids = []
    if row is not None and row.parent_device_id:
        ids.append(row.parent_device_id)
    ids.extend(dm.device_id for dm in DeviceMember.query.filter_by(
        member_type=member_type, member_id=member_id).all())
    return ids


def member_device_map(member_type):
    """{member_id: [device_id, ...]} — member_type('input'|'output') 전체에
    대해 소속된 모든 장치를 한 번에 계산한다. Input/Output 목록 페이지가
    항목마다 따로 조회하지 않고 페이지당 쿼리 2개로 배지를 그리게 한다."""
    from aot.databases.models.device_member import DeviceMember

    model = _member_models()[member_type]
    mapping = {}
    for row in model.query.filter(model.parent_device_id.isnot(None)).all():
        mapping.setdefault(row.unique_id, []).append(row.parent_device_id)
    for dm in DeviceMember.query.filter_by(member_type=member_type).all():
        mapping.setdefault(dm.member_id, []).append(dm.device_id)
    return mapping


def parent_device_names(device_names=None):
    """{CustomController.unique_id: name} — is_device=True 장치 전체.

    Input/Output 카드가 소속 장치 id를 이 맵으로 이름으로 바꿔 배지를
    표시하는 데 쓴다(설계 6.3/9). 장치 개수가 많지 않아(Input 151종/Output
    54종과 달리 장치는 실물 단위) 전체를 한 번에 읽어도 비용이 작다.
    """
    from aot.databases.models.controller import CustomController
    from aot.utils.functions import device_module_names

    names = device_names if device_names is not None else device_module_names()
    if not names:
        return {}
    return {c.unique_id: c.name for c in
            CustomController.query.filter(CustomController.device.in_(names)).all()}
