# coding=utf-8
"""장치 접속정보 — 하드웨어를 갈아끼울 때 실제로 바뀌는 필드만 따로 다룬다.

고장난 센서를 같은 모델로 교체할 때의 정답은 장치를 지우고 새로 만드는 것이
아니라 **접속정보(DevEUI·I2C 주소·포트)만 갱신**하는 것이다. 도형·바인딩
이력·함수 연결·측정 채널이 전부 장치 uuid 에 매달려 있어서, 새로 만들면 그
전부를 다시 이어야 하고 시계열은 그 지점에서 끊긴다.

사람들이 그럼에도 "새로 만들고 옛것 삭제"로 가는 이유는 이 경로가 화면에
없었기 때문이다. 설정 페이지에는 접속정보가 수십 개 필드 사이에 묻혀 있고,
게다가 `input_mod` 은 활성 상태에서는 수정을 거부하므로 비활성화 → 수정 →
재활성화 3단계를 사람이 직접 밟아야 한다. 이 모듈은 그 3단계를 서버가 대신
밟고, 편집 대상을 접속정보로 좁혀서 내보낸다.

**설계 원칙 셋**

1. **필드 목록은 모듈 선언이 정본이다.** 컬럼을 훑어 "값이 있으면 보여주는"
   방식은 모델에 컬럼이 생길 때마다 조용히 늘어난다. 각 드라이버가 이미
   `options_enabled`/`options_disabled` 로 자기가 쓰는 접속 방식을 선언하고
   있으므로 그것과 `_OPTION_COLUMNS` 의 교집합만 쓴다.
2. **모르는 키는 조용히 버리지 않고 거부한다.** 화이트리스트에 없는 키를
   말없이 무시하면 사용자는 저장됐다고 믿고 화면은 새로고침에서 되돌아간다
   (`routes_geo.theme_keys` 에서 실제로 겪은 실패 모드).
3. **비밀은 접속정보가 아니다.** API 키·토큰·비밀번호는 목록에 넣지 않으며,
   허용 목록에 실수로 들어와도 `_is_secret_key()` 가 한 번 더 막는다.
   교체에 필요한 것은 "어느 장치인가"이지 "어떻게 인증하는가"가 아니다.

@phase active
@dependency Input, Output, CustomController, device_binding
"""
import json
import logging

from flask_babel import gettext

from aot.aot_flask.extensions import db
from aot.config_translations import TRANSLATIONS

logger = logging.getLogger(__name__)


def _t(text, **kwargs):
    """번역. babel 이 초기화되지 않은 자리(테스트·스크립트)에서는 원문으로
    떨어진다 — 사람에게 보일 문구 하나 때문에 저장 자체가 실패하면 안 된다."""
    try:
        return gettext(text, **kwargs)
    except Exception:
        return text % kwargs if kwargs else text


# 편집을 지원하는 장치 종류. device_binding 의 어휘를 그대로 쓴다
# ('device' = CustomController — 복합장치와 커스텀 함수가 같은 표에 산다).
# PID·Trigger·Conditional 은 물리 접점이 없어 접속정보라는 것이 없다.
SUPPORTED_KINDS = ('input', 'output', 'device')

# 모듈 선언(`options_enabled`) 의 옵션 이름 → 실제 컬럼들.
# 옵션 하나가 컬럼 둘을 뜻하는 경우가 있다(I2C = 주소 + 버스). 순서가 곧
# 화면에 뜨는 순서다.
_OPTION_COLUMNS = {
    'i2c_location':   (('i2c_location', 'text'), ('i2c_bus', 'integer')),
    'uart_location':  (('uart_location', 'text'),),
    'uart_baud_rate': (('baud_rate', 'integer'),),
    'ftdi_location':  (('ftdi_location', 'text'),),
    'gpio_location':  (('gpio_location', 'integer'),),
    # BT 는 주소를 전용 컬럼이 아니라 범용 `location` 에 담는다
    # (utils_input.input_add 가 bt_location 기본값을 location 에 넣는다).
    'bt_location':    (('location', 'text'), ('bt_adapter', 'text')),
    'location':       (('location', 'text'),),
    'pin_clock':      (('pin_clock', 'integer'),),
    'pin_cs':         (('pin_cs', 'integer'),),
    'pin_mosi':       (('pin_mosi', 'integer'),),
    'pin_miso':       (('pin_miso', 'integer'),),
    'port':           (('port', 'integer'),),
}

# 컬럼 → 라벨 키(`config_translations.TRANSLATIONS`). 이미 번역돼 있는 것을
# 다시 쓴다 — 같은 필드가 설정 페이지와 교체 화면에서 다른 이름으로 불리면
# 사용자는 다른 필드라고 생각한다.
_COLUMN_LABEL_KEYS = {
    'i2c_location': 'i2c_location',
    'i2c_bus': 'i2c_bus',
    'uart_location': 'uart_location',
    'baud_rate': 'baud_rate',
    'ftdi_location': 'ftdi_location',
    'gpio_location': 'gpio_location',
    'location': 'bt_location',
    'bt_adapter': 'bt_adapter',
    'pin_clock': 'pin_clock',
    'pin_cs': 'pin_cs',
    'pin_mosi': 'pin_mosi',
    'pin_miso': 'pin_miso',
    'port': 'port',
}

# custom_options 중 접속정보로 인정하는 id → 값의 종류. 드라이버 저자가
# 자유롭게 짓는 이름이라 규칙으로 판별할 수 없어 명부로 둔다 — 늘릴 때는
# "이 값을 바꾸면 다른 물리 장치를 가리키게 되는가"만 묻는다. 인증 수단
# (키·토큰·비밀번호)은 그 질문에 '아니오'이므로 들어오지 않는다.
#
# **종류는 드라이버 선언이 아니라 여기가 정한다.** 드라이버의 `type` 은 폼에
# 어떤 위젯을 그릴지를 정할 뿐이라 포트를 `'text'` 로 선언한 모듈이 흔하고,
# 그것을 그대로 믿으면 포트에 "여덟팔삼" 을 넣어도 저장된다(실제로 저장됐다).
# 접속정보는 값이 틀리면 장치가 조용히 안 붙는 자리라 여기서 막는다.
_CONNECTION_OPTION_TYPES = {
    # LoRaWAN 식별자 — 현장에서 압도적으로 흔한 교체 대상.
    # device_link_status._EUI_OPTION_KEYS 와 같은 3종이다.
    'dev_eui': 'text', 'device_eui': 'text', 'device_euis': 'text',
    # 네트워크 주소
    'host': 'text', 'hostname': 'text', 'ip_address': 'text',
    'plug_address': 'text', 'mqtt_hostname': 'text',
    'mqtt_port': 'integer', 'asyncio_rpc_port': 'integer', 'port': 'integer',
    # 버스·핀. i2c_address 는 '0x44' 표기를 쓰므로 숫자가 아니다.
    'i2c_address': 'text', 'i2c_bus': 'integer',
    'spi_bus': 'integer', 'spi_device': 'integer',
    'pin': 'integer', 'pin_reset': 'integer',
}

# 이름에 이것이 들어가면 접속정보로 취급하지 않는다. 위 명부를 늘리다 실수로
# 자격증명을 넣는 것이 유일하게 되돌릴 수 없는 실수라(한 번 응답에 실리면
# 로그·캐시·브라우저 히스토리에 남는다) 마지막 그물을 하나 더 둔다.
_SECRET_MARKERS = ('password', 'passwd', 'token', 'api_key', 'apikey',
                   'secret', 'credential', 'private_key', 'username', 'user')


class ConnectionSettingError(Exception):
    """접속정보 편집이 거부된 이유. 메시지는 사용자에게 그대로 보인다."""


def _is_secret_key(key):
    low = str(key or '').lower()
    return any(marker in low for marker in _SECRET_MARKERS)


def resolve_entity(device_id):
    """장치 uuid → (kind, 엔티티). 지원하지 않는 종류면 ConnectionSettingError.

    종류 판별은 `device_binding.resolve_device_kind` 하나만 쓴다 — 호출자가
    들고 있는 종류 문자열을 믿으면 UI 어휘와 DB 어휘가 갈리는 자리다.
    """
    from aot.aot_flask.geo import device_binding
    from aot.databases.models import CustomController, Input, Output

    uid = str(device_id or '').split('::')[0]
    if not uid:
        raise ConnectionSettingError(_t("No device was given."))

    kind = device_binding.resolve_device_kind(uid)
    if kind is None:
        raise ConnectionSettingError(_t("That device no longer exists."))
    if kind not in SUPPORTED_KINDS:
        raise ConnectionSettingError(_t(
            "%(kind)s entries have no connection settings to change.",
            kind=kind))

    model = {'input': Input, 'output': Output, 'device': CustomController}[kind]
    entity = model.query.filter(model.unique_id == uid).first()
    if entity is None:
        raise ConnectionSettingError(_t("That device no longer exists."))
    return kind, entity


def _module_info(kind, entity):
    """이 장치가 쓰는 드라이버 모듈의 선언 dict. 못 찾으면 빈 dict."""
    try:
        if kind == 'input':
            from aot.utils.inputs import parse_input_information
            return parse_input_information().get(entity.device, {}) or {}
        if kind == 'output':
            from aot.utils.outputs import parse_output_information
            return parse_output_information().get(entity.output_type, {}) or {}
        from aot.utils.functions import parse_function_information
        return parse_function_information().get(entity.device, {}) or {}
    except Exception:
        logger.exception("[device_connection] 모듈 선언을 읽지 못했다")
        return {}


def _declared_options(info):
    """모듈이 선언한 옵션 이름 집합(enabled + disabled).

    disabled 를 포함하는 이유: 드라이버가 주소를 고정해 두고
    `options_disabled` 로 선언하는 경우가 있고(SHT3x 의 interface 가 그렇다),
    그때도 값 자체는 보여줘야 사람이 "여기는 못 바꾸는구나"를 안다.
    """
    out = []
    for key in ('options_enabled', 'options_disabled'):
        for name in (info.get(key) or []):
            if name not in out:
                out.append(name)
    return out


def _label(column):
    key = _COLUMN_LABEL_KEYS.get(column)
    if key and key in TRANSLATIONS:
        try:
            # lazy_gettext 의 LazyString 은 jsonify 가 직렬화하지 못하고,
            # 요청 밖(스크립트·데몬)에서 풀면 locale 선택기가 터진다.
            # 라벨 하나 때문에 스키마 전체가 죽을 이유는 없다.
            return str(TRANSLATIONS[key]['title'])
        except Exception:
            return column
    return column


def _current_custom_options(entity):
    try:
        return json.loads(entity.custom_options or '{}') or {}
    except Exception:
        return {}


def connection_schema(device_id):
    """이 장치에서 교체 시 갈아끼우는 필드들 — 스키마 + 현재값.

    반환:
        {
          'device_id':.., 'kind':.., 'name':.., 'module':.., 'interface':..,
          'is_activated': bool,
          'fields': [{'key','label','value','type','source','readonly','help'}],
        }
    `fields` 가 비면 이 장치는 접속정보를 갖지 않는다(예: 계산만 하는 함수).
    빈 목록은 오류가 아니므로 호출자가 그렇게 다뤄야 한다.
    """
    kind, entity = resolve_entity(device_id)
    return _schema_for(kind, entity)


def _schema_for(kind, entity):
    info = _module_info(kind, entity)
    declared = _declared_options(info)
    disabled = set(info.get('options_disabled') or [])

    fields = []
    seen = set()

    for option in declared:
        for column, ftype in _OPTION_COLUMNS.get(option, ()):
            if column in seen or not hasattr(entity, column):
                continue
            seen.add(column)
            value = getattr(entity, column)
            fields.append({
                'key': column,
                'label': _label(column),
                'value': '' if value is None else value,
                'type': ftype,
                'source': 'column',
                'readonly': option in disabled,
                'help': '',
            })

    opt_values = _current_custom_options(entity)
    for option in (info.get('custom_options') or []):
        oid = option.get('id')
        if (not oid or oid in seen
                or oid not in _CONNECTION_OPTION_TYPES
                or _is_secret_key(oid)):
            continue
        seen.add(oid)
        value = opt_values.get(oid, option.get('default_value', ''))
        fields.append({
            'key': oid,
            'label': option.get('name') or oid,
            'value': '' if value is None else value,
            'type': _CONNECTION_OPTION_TYPES[oid],
            'source': 'custom_option',
            'readonly': False,
            'help': option.get('phrase') or '',
        })

    return {
        'device_id': entity.unique_id,
        'kind': kind,
        'name': entity.name or '',
        'module': (info.get('input_name') or info.get('output_name')
                   or info.get('function_name') or ''),
        'interface': getattr(entity, 'interface', '') or '',
        'is_activated': bool(getattr(entity, 'is_activated', False)),
        'fields': fields,
    }


def _coerce(field, raw):
    if field['type'] == 'integer':
        text = str(raw).strip()
        if text == '':
            return None
        try:
            return int(text)
        except ValueError:
            raise ConnectionSettingError(_t(
                "%(field)s must be a number.", field=field['label']))
    return '' if raw is None else str(raw).strip()


def _keep_repr(old_value, new_value):
    """custom_options 안에서 값의 **표기 형태**를 기존과 맞춘다.

    같은 포트가 어떤 모듈에서는 `'1883'`(문자열), 어떤 모듈에서는 `1883`(정수)로
    저장돼 있다. 검증 때문에 int 로 바꾼 값을 그대로 써 넣으면 문자열로 저장돼
    있던 자리가 숫자로 바뀌고, 그 값을 문자열로 다루던 드라이버가 조용히
    깨진다. 검증은 하되 저장 형태는 건드리지 않는다.
    """
    if isinstance(new_value, int) and isinstance(old_value, str):
        return str(new_value)
    return new_value


def apply_connection(device_id, values):
    """접속정보 필드만 갱신한다. 바뀐 항목이 없으면 아무것도 하지 않는다.

    활성 상태인 Input/Function 은 비활성화 → 수정 → 재활성화 순으로 처리한다
    (`input_mod` 과 같은 제약이다 — 도는 컨트롤러의 설정을 바꾸면 데몬이 옛
    설정으로 계속 돈다). Output 은 활성 개념이 없어 저장 후 데몬에
    'Modify' 를 알린다.

    반환: {'changed': [{key,label,before,after}], 'restarted': bool,
           'warnings': [str], 'note_id': str|None}
    """
    kind, entity = resolve_entity(device_id)
    schema = _schema_for(kind, entity)
    by_key = {f['key']: f for f in schema['fields']}

    if not isinstance(values, dict):
        raise ConnectionSettingError(_t("No changes were submitted."))

    changed = []
    col_updates = {}
    opt_updates = {}

    for key, raw in values.items():
        field = by_key.get(key)
        # 화이트리스트 밖의 키는 거부한다. 조용히 버리면 사용자는 저장됐다고
        # 믿고, 새로고침에서 값이 되돌아온 뒤에야 알게 된다.
        if field is None:
            raise ConnectionSettingError(_t(
                "'%(field)s' is not a connection setting of this device.",
                field=key))
        if field['readonly']:
            raise ConnectionSettingError(_t(
                "%(field)s is fixed by this device's driver and cannot be "
                "changed.", field=field['label']))
        if _is_secret_key(key):
            raise ConnectionSettingError(_t(
                "%(field)s is not a connection setting.", field=key))

        new_value = _coerce(field, raw)
        old_value = field['value']
        if str(old_value) == str('' if new_value is None else new_value):
            continue

        changed.append({
            'key': key,
            'label': field['label'],
            'before': old_value,
            'after': '' if new_value is None else new_value,
        })
        if field['source'] == 'column':
            col_updates[key] = new_value
        else:
            opt_updates[key] = _keep_repr(old_value, new_value)

    if not changed:
        return {'changed': [], 'restarted': False, 'warnings': [],
                'note_id': None}

    warnings = []
    was_activated = bool(getattr(entity, 'is_activated', False))
    controller_type = {'input': 'Input', 'device': 'Function'}.get(kind)

    if was_activated and controller_type:
        warnings.extend(_toggle(controller_type, entity.unique_id,
                                'deactivate'))

    try:
        for column, value in col_updates.items():
            setattr(entity, column, value)
        if opt_updates:
            merged = _current_custom_options(entity)
            merged.update(opt_updates)
            entity.custom_options = json.dumps(merged)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("[device_connection] 저장 실패")
        # 저장에 실패했는데 꺼진 채로 두면 사고다. 되살리기를 시도한다.
        if was_activated and controller_type:
            warnings.extend(_toggle(controller_type, entity.unique_id,
                                    'activate'))
        raise ConnectionSettingError(_t("Failed to save"))

    restarted = False
    if was_activated and controller_type:
        errs = _toggle(controller_type, entity.unique_id, 'activate')
        warnings.extend(errs)
        restarted = not errs
        if errs:
            # 여기서 조용하면 사용자는 저장 성공만 보고 떠나고, 장치는 꺼진
            # 채로 남는다. 켜지지 않았다는 사실이 성공 메시지보다 중요하다.
            warnings.append(_t(
                "The device is saved but stayed off. Turn it back on from its "
                "settings page."))
    elif kind == 'output':
        restarted = _refresh_output(entity.unique_id, warnings)

    note_id = _write_note(kind, entity, changed)

    return {'changed': changed, 'restarted': restarted,
            'warnings': warnings, 'note_id': note_id}


def _toggle(controller_type, controller_id, action):
    """활성/비활성 토글. 반환은 오류 메시지 목록(비면 성공)."""
    from aot.aot_flask.utils import utils_general
    messages = {'success': [], 'info': [], 'warning': [], 'error': []}
    try:
        messages = utils_general.controller_activate_deactivate(
            messages, action, controller_type, controller_id,
            flash_message=False)
    except Exception as err:
        logger.exception("[device_connection] %s 실패", action)
        return [str(err)]
    return list(messages.get('error') or [])


def _refresh_output(output_id, warnings):
    """Output 은 켜고 끄는 대신 데몬에 'Modify' 를 알려 다시 설정하게 한다.

    데몬 RPC 는 10초 하드캡이 있고 이 호출이 실제 장치 명령을 유발할 수 있어
    (LoRaWAN 다운링크 등) 타임아웃이 정상 범위 안의 사건이다. 실패해도 저장은
    이미 끝났으므로 경고로만 남긴다.
    """
    from aot.aot_flask.utils.utils_output import manipulate_output
    try:
        result = manipulate_output('Modify', output_id)
    except Exception as err:
        warnings.append(str(err))
        return False
    errs = list(result.get('error') or [])
    warnings.extend(errs)
    return not errs


def _write_note(kind, entity, changed):
    """교체를 이력에 남긴다.

    바인딩은 이 교체를 기록하지 못한다 — 장치 uuid 가 그대로라 슬롯의 연결은
    바뀐 것이 없기 때문이다. 그런데 물리적으로는 다른 기계가 달렸고, 그래서
    "이 시점부터 값이 달라진" 이유를 나중에 설명할 수 있는 것은 이 노트뿐이다.
    실패해도 저장을 되돌리지 않는다(기록은 갱신에 종속된 부수 작업이다).
    """
    from aot.databases.models import Notes
    try:
        lines = [_t("Connection settings changed (hardware swap).")]
        for item in changed:
            lines.append("- %s: %s → %s" % (
                item['label'],
                item['before'] if item['before'] != '' else '(empty)',
                item['after'] if item['after'] != '' else '(empty)'))
        note = Notes()
        note.name = _t("Replaced: %(name)s", name=entity.name or '')[:255]
        note.note = '\n'.join(lines)
        note.target_id = entity.unique_id
        note.target_type = kind
        note.category = 'maintenance'
        db.session.add(note)
        db.session.commit()
        return note.unique_id
    except Exception:
        db.session.rollback()
        logger.exception("[device_connection] 교체 노트 기록 실패")
        return None
