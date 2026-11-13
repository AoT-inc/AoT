# coding=utf-8
"""모듈 파일 안의 웹 훅(`execute_at_creation`·`execute_at_modification`)이 쓰는 공통 처리.

입력·출력·함수 모듈 파일(`aot/functions`·`aot/inputs`·`aot/outputs`·
`aot/actions`)은 데몬도 import 한다. 그런데 그 파일 안의 훅은 웹 프로세스에서
돈다(설정 저장 때 `utils_controller`·`utils_input`·`utils_output` 이 부른다).
훅이 필요하다고 `aot.aot_flask.utils.utils_general` 이나 `flask` 를 직접
가져오면 데몬이 모듈을 읽을 때 웹 계층까지 끌려 들어온다(`check_import_layers.py`
의 `daemon-no-flask`).

그래서 훅이 쓰는 것은 여기 모은다. 규칙은 하나다:

- **여기서는 `flask` 를 import 하지 않는다.** 사용자에게 보일 메시지는
  문자열로 돌려주고, `flash` 는 훅을 부른 웹 쪽이 한다.
  훅이 지금 바로 띄우던 메시지는 `queue_flash()` 로 `messages` 에 담고,
  웹 쪽이 `drain_flash()` 로 꺼내 `flash` 한다 — 보이는 결과는 전과 같다.
- 웹 앱의 TESTING 여부는 `web_app_testing()` 으로 본다. 웹 앱 문맥이 없으면
  (데몬·스크립트) False 다.
"""
import copy
import json
import logging
import sys

from flask_babel import lazy_gettext

from aot.config_translations import TRANSLATIONS
from aot.databases.models import APIKey
from aot.utils.system_pi import is_int, str_is_float

logger = logging.getLogger(__name__)

_NULLISH_STRINGS = {'', 'none', 'null'}  # 'false' removed - it's a valid boolean value

#: `messages` 안에서 웹 쪽이 `flash` 할 (분류, 문장) 을 담아 두는 열쇠
FLASH_QUEUE_KEY = '_flash_queue'


def normalize_nullish_value(value, empty_value=''):
    """Normalize placeholder/nullish values to a consistent empty representation."""
    if value is None:
        return empty_value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in _NULLISH_STRINGS:
            return empty_value
        return stripped
    return value


def normalize_option_value(val, empty_value=None):
    """Normalize custom option payloads by stripping nullish placeholders."""
    if isinstance(val, list):
        return [v for v in (normalize_option_value(v, empty_value) for v in val) if v not in [None, '']]
    if isinstance(val, dict):
        cleaned = {}
        for k, v in val.items():
            norm_key = normalize_nullish_value(k, '')
            norm_val = normalize_option_value(v, empty_value)
            cleaned[norm_key] = norm_val
        return cleaned
    normalized = normalize_nullish_value(val, '')
    if normalized == '':
        return empty_value
    return normalized


def custom_channel_options_return_json(
        error,
        dict_options,
        request_form,
        device_id,
        channel,
        mod_dev=None,
        device=None,
        use_defaults=False,
        custom_options=None):
    # Custom channel_options — seed with presave values so null form fields don't erase DB data
    if isinstance(custom_options, dict):
        dict_options_return = copy.deepcopy(custom_options)
    else:
        dict_options_return = {}

    # TODO: name same name in next major release
    if mod_dev is None:
        pass
    elif hasattr(mod_dev, 'graph_type'):
        device = mod_dev.graph_type
    elif hasattr(mod_dev, 'device'):
        device = mod_dev.device
    elif hasattr(mod_dev, 'output_type'):
        device = mod_dev.output_type
    else:
        logger.error("custom_channel_options_return_json: Unknown device; returning empty {}")
        return error, json.dumps({})

    if device not in dict_options:
        logger.error("custom_channel_options_return_json: device %s not found in dict_options; returning empty {}", device)
        return error, json.dumps({})

    if 'custom_channel_options' in dict_options[device]:
        for each_option in dict_options[device]['custom_channel_options']:
            if 'id' not in each_option:
                continue

            null_value = True

            if request_form:
                for key in request_form.keys():
                    key_str = "{}_{}_{}".format(device_id, channel, each_option['id'])
                    if key_str == key:
                        # logger.error("key_str: {}".format(key_str))
                        # logger.error("val: {}".format(request_form.get(key)))
                        constraints_pass = True
                        constraints_errors = []
                        value = None

                        if each_option['type'] in ('float', 'select_scale'):
                            raw_val = request_form.get(key)
                            if str_is_float(raw_val):
                                if 'constraints_pass' in each_option:
                                    (constraints_pass,
                                     constraints_errors,
                                     mod_dev) = each_option['constraints_pass'](
                                        mod_dev, float(raw_val))
                                if constraints_pass:
                                    value = float(raw_val)
                            elif raw_val in (None, '', 'None', 'null'):
                                value = each_option.get('default_value', None)
                            else:
                                error.append(
                                    "{name} must represent a float/decimal value "
                                    "(submitted '{value}')".format(
                                        name=each_option['name'],
                                        value=raw_val))

                        elif each_option['type'] == 'integer':
                            raw_val = request_form.get(key)
                            if is_int(raw_val):
                                if 'constraints_pass' in each_option:
                                    (constraints_pass,
                                     constraints_errors,
                                     mod_dev) = each_option['constraints_pass'](
                                        mod_dev, int(raw_val))
                                if constraints_pass:
                                    value = int(raw_val)
                            elif 'required' in each_option and not each_option['required']:
                                value = None
                            else:
                                error.append(
                                    "{name} must represent an integer value "
                                    "(submitted '{value}')".format(
                                        name=each_option['name'],
                                        value=raw_val))

                        elif each_option['type'] in ['select', 'select_custom_choices']:
                            raw_val = request_form.get(key)
                            if 'constraints_pass' in each_option:
                                (constraints_pass,
                                 constraints_errors,
                                 mod_dev) = each_option['constraints_pass'](
                                    mod_dev, normalize_option_value(raw_val))
                            if constraints_pass:
                                value = normalize_option_value(raw_val)
                                if is_int(raw_val):
                                    value = int(raw_val)
                                elif str_is_float(raw_val):
                                    value = float(raw_val)

                        elif each_option['type'] in [
                                'multiline_text',
                                'text',
                                'select_measurement',
                                'select_channel',
                                'select_measurement_channel',
                                'select_type_measurement',
                                'select_type_unit',
                                'select_device']:
                            raw_val = request_form.get(key)
                            if 'constraints_pass' in each_option:
                                (constraints_pass,
                                 constraints_errors,
                                 mod_dev) = each_option['constraints_pass'](
                                    mod_dev, normalize_option_value(raw_val))
                            if constraints_pass:
                                value = normalize_option_value(raw_val)

                        elif each_option['type'] in ['select_multi_measurement', 'channel_selector']:
                            raw_val = request_form.get(key)
                            if 'constraints_pass' in each_option:
                                (constraints_pass,
                                 constraints_errors,
                                 mod_dev) = each_option['constraints_pass'](
                                    mod_dev, normalize_option_value(raw_val))
                            if constraints_pass:
                                value = normalize_option_value(request_form.getlist(key), empty_value=[])

                        elif each_option['type'] == 'bool':
                            value = bool(normalize_option_value(request_form.get(key), False))

                        for each_error in constraints_errors:
                            error.append(
                                "Error: {name}: {error}".format(
                                    name=each_option['name'],
                                    error=each_error))

                        if value is not None:
                            null_value = False
                            dict_options_return[each_option['id']] = value

                            # [Auto-Save API Key/Token]
                            auth_keywords = ['api_key', 'token', 'secret', 'access_key', 'auth_key', 'client_id', 'client_secret']
                            is_auth_field = any(kw in each_option['id'].lower() for kw in auth_keywords)

                            if is_auth_field and isinstance(value, str) and len(value) > 5:
                                try:
                                    device_info = dict_options.get(device, {})
                                    
                                    # [Metadata Extraction]
                                    provider = (device_info.get('input_manufacturer') or 
                                                device_info.get('output_manufacturer') or 
                                                device_info.get('function_manufacturer') or 
                                                device)
                                    
                                    display_name = (device_info.get('input_name') or 
                                                   device_info.get('output_name') or 
                                                   device_info.get('function_name') or 
                                                   device)
                                    
                                    url_list = []
                                    for url_key in ['url_additional', 'url_manufacturer', 'url_datasheet', 'url_product_purchase']:
                                        urls = device_info.get(url_key, [])
                                        if isinstance(urls, list):
                                            url_list.extend([u for u in urls if u])
                                        elif urls:
                                            url_list.append(urls)
                                    
                                    url_list = list(dict.fromkeys(url_list))
                                    primary_url = url_list[0] if url_list else None
                                    
                                    existing = APIKey.query.filter(APIKey.key == value).first()
                                    if not existing:
                                        new_api_key = APIKey()
                                        new_api_key.name = f"{display_name} {each_option['name']} (Auto-saved)"
                                        new_api_key.provider = provider
                                        new_api_key.key = value
                                        new_api_key.tag = each_option['id']
                                        new_api_key.url = primary_url
                                        
                                        desc = f"Automatically saved from {display_name} ({device}) channel {channel} configuration."
                                        if len(url_list) > 1:
                                            desc += "\nRelated URLs:\n" + "\n".join(url_list)
                                        new_api_key.description = desc
                                        
                                        new_api_key.save()
                                        logger.info(f"Auth field '{each_option['id']}' for {provider} auto-saved from channel {channel} with metadata.")
                                except Exception as e:
                                    logger.error(f"Failed to auto-save auth field from channel with metadata: {e}")

            if (request_form and
                    each_option['type'] == 'bool' and
                    "{}_{}_{}".format(device_id, channel, each_option['id']) not in request_form.keys() and
                    not use_defaults):
                dict_options_return[each_option['id']] = False

            elif null_value:
                if each_option['id'] in dict_options_return:
                    pass  # presave value already in dict — do not overwrite with module default
                elif use_defaults and 'default_value' in each_option:
                    # If a select type has cast_value set, cast the value as that type
                    if (each_option['type'] in ['select', 'select_custom_choices'] and
                            'cast_value' in each_option and
                            each_option['default_value'] is not None):
                        if each_option['cast_value'] == 'integer':
                            dict_options_return[each_option['id']] = int(each_option['default_value'])
                        elif each_option['cast_value'] == 'float':
                            dict_options_return[each_option['id']] = float(each_option['default_value'])
                        elif each_option['cast_value'] == 'bool':
                            dict_options_return[each_option['id']] = bool(each_option['default_value'])
                    else:
                        dict_options_return[each_option['id']] = each_option['default_value']
                elif each_option['type'] == "select_multi_measurement":
                    dict_options_return[each_option['id']] = ""
                else:
                    dict_options_return[each_option['id']] = None

    return error, json.dumps(dict_options_return)


def delete_channel_row(table, entry_id):
    """훅이 채널 행 하나를 지운다. (지웠는지, flash 분류, 문장) 을 돌려준다.

    `utils_general.delete_entry_with_id()` 와 같은 일을 하되 `flash` 하지 않는다.
    그쪽의 그룹 스코프 검사는 여기 없다 — 훅이 지우는 것은 채널 같은 자식 행이고
    `scope.can_operate_record()` 는 스코프 대상이 아닌 모델에 늘 True 를 낸다.
    부모(함수·입력·출력)를 고칠 권한은 훅을 부르기 전에 웹 쪽이 이미 물었다.
    **스코프 대상 모델(Input·Output·Function·Tab 등)을 지울 때는 쓰지 말 것.**
    """
    entry = table.query.filter(table.unique_id == entry_id).first()
    if entry is None:
        msg = '{action} {id}: {err}'.format(
            action=TRANSLATIONS['delete']['title'],
            id=entry_id,
            err=lazy_gettext("Could not find ID %(id)s.", id=entry_id))
        return False, 'error', msg
    entry.delete()
    msg = '{action} {table} with ID: {id}'.format(
        action=TRANSLATIONS['delete']['title'],
        table=table.__tablename__,
        id=entry_id)
    return True, 'success', msg


def queue_flash(messages, category, msg):
    """훅이 '지금 바로 띄우던' 메시지를 `messages` 에 담는다(웹 쪽이 `drain_flash`)."""
    messages.setdefault(FLASH_QUEUE_KEY, []).append((category, msg))


def drain_flash(messages):
    """`queue_flash` 로 담긴 (분류, 문장) 목록을 꺼내고 `messages` 에서 지운다."""
    if not isinstance(messages, dict):
        return []
    return messages.pop(FLASH_QUEUE_KEY, None) or []


def web_app_testing():
    """웹 앱이 TESTING 설정으로 돌고 있는가. 웹 앱 문맥이 없으면 False.

    `flask` 를 import 하지 않는다 — 웹 프로세스라면 이미 올라와 있다.
    """
    flask_mod = sys.modules.get('flask')
    if flask_mod is None or not flask_mod.has_app_context():
        return False
    return bool(flask_mod.current_app.config.get('TESTING'))
