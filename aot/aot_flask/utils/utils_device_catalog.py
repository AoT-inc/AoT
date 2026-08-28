# -*- coding: utf-8 -*-
#
# utils_device_catalog.py - "장치 추가" 드롭다운의 그룹·검색 선택지 생성
#
"""input/output/function 페이지 상단 '추가' 드롭다운의 선택지를 만든다.

목록이 200개 가까이 되면서 세 가지 문제가 있었다.

1. 평면 나열이라 훑을 기준이 없다.
2. 옵션 문구가 모듈 메타데이터 원문(영문)이라, 한국어 등 다른 언어로는
   bootstrap-select 의 live search 가 아예 걸리지 않는다. AoT 는 22개 언어로
   출시되므로 검색창이 사실상 영어 사용자 전용이었다.
3. 제조사·이름·측정항목·라이브러리·인터페이스를 한 줄에 다 이어붙여 길다.

여기서 세 가지를 한꺼번에 처리한다.

- optgroup: 입력은 측정 대상, 출력은 출력 방식, 함수는 티어로 묶는다.
- data-tokens: 번역된 측정명·제조사·인터페이스·모듈명을 검색 토큰으로 붙인다.
  bootstrap-select 는 text/subtext/tokens 셋을 모두 대문자 contains 로 훑으므로
  (vendor/bootstrap-select.min.js 의 검색 함수에서 확인) 토큰만 붙이면 어떤
  언어로도 검색이 걸린다.
- data-subtext: 라이브러리·측정항목처럼 부차적인 정보를 흐린 작은 글씨로 분리해
  주 문구가 눈에 먼저 들어오게 한다. (둘째 줄로 내리지 않는 이유: 행이 세로로
  길어지면 "메뉴가 너무 길다"는 원래 문제가 도로 커진다.)

주의 — 그룹 라벨과 측정명은 요청 언어로 번역되어야 하므로 공개 함수는 요청마다
호출해야 한다. 폼 클래스 본문(=import 시점)에서 부르면 첫 요청의 언어로 고정된다.
언어와 무관한 모듈 파싱 결과만 프로세스 수명 동안 캐시한다. 사용자가 커스텀 모듈을
설치하면 utils_settings 가 reload_frontend() 로 프론트엔드를 재기동하므로 캐시도
함께 버려진다.
"""

import logging

from flask_babel import lazy_gettext

from aot.aot_flask.utils.utils_general import generate_form_input_list
from aot.aot_flask.utils.utils_general import generate_form_output_list
from aot.config import PATH_INPUTS_GIS
from aot.config_devices_units import MEASUREMENTS
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import parse_output_information

logger = logging.getLogger("aot.utils_device_catalog")


#: 입력 그룹. 위에서부터 먼저 걸리는 그룹으로 배정한다(구체적인 것 우선).
#: 온도는 모듈 72개가 갖고 있어서 먼저 두면 절반이 한 그룹에 몰린다. CO2 센서가
#: 온도도 잰다고 해서 '온도·습도'에 있으면 사용자가 찾지 못하므로, 특징적인
#: 측정을 가진 그룹을 앞에 두고 온·습도를 뒤로 뺐다.
INPUT_GROUPS = (
    (lazy_gettext('Soil & Nutrient'), frozenset({
        'moisture',
        'volumetric_water_content',
        'electrical_conductivity',
        'electrical_conductivity_soil',
        'ion_concentration',
        'dissolved_oxygen',
        'oxidation_reduction_potential',
        'salinity',
        'total_dissolved_solids',
        'specific_gravity'})),
    (lazy_gettext('Air Quality'), frozenset({
        'co2',
        'voc',
        'o2',
        'methane',
        'particulate_matter_1_0',
        'particulate_matter_2_5',
        'particulate_matter_10_0',
        'radiation',
        'visibility'})),
    (lazy_gettext('Power & Energy'), frozenset({
        'electrical_potential',
        'electrical_current',
        'power',
        'power_apparent',
        'power_reactive',
        'power_factor',
        'energy',
        'battery',
        'resistance',
        'frequency',
        'duty_cycle',
        'pulse_width'})),
    (lazy_gettext('Weather & Light'), frozenset({
        'light',
        'uvi',
        'precipitation',
        'snowfall',
        'direction',
        'speed',
        'pressure',
        'altitude',
        'sky_condition'})),
    (lazy_gettext('Temperature & Humidity'), frozenset({
        'temperature',
        'humidity',
        'dewpoint',
        'vapor_pressure_deficit'})),
    (lazy_gettext('Motion & Position'), frozenset({
        'acceleration',
        'acceleration_x',
        'acceleration_y',
        'acceleration_z',
        'angle',
        'revolutions',
        'magnetic_flux_density',
        'length',
        'volume',
        'rate_volume',
        'duration_time'})),
)

#: 어느 그룹에도 걸리지 않는 입력(시스템 상태, 색상, 신호세기 등)
INPUT_GROUP_OTHER = lazy_gettext('System & Other')

#: AoT 가 직접 만든 모듈. 기존 폼도 이들을 목록 맨 앞에 두었는데 경계가 보이지
#: 않아 구분이 되지 않았다. 별도 그룹으로 올려 둔다.
GROUP_AOT = lazy_gettext('AoT Devices')

#: 출력 그룹. 한 모듈이 여러 output_types 를 가지면 먼저 걸리는 쪽으로 간다
#: (펌프는 volume 과 on_off 를 함께 갖지만 사용자는 펌프로 찾는다).
OUTPUT_GROUPS = (
    (lazy_gettext('Pump & Dosing'), 'volume'),
    (lazy_gettext('Proportional (PWM)'), 'pwm'),
    (lazy_gettext('Value Setting'), 'value'),
    (lazy_gettext('On/Off Switching'), 'on_off'),
)

OUTPUT_GROUP_OTHER = lazy_gettext('System & Other')

#: 함수 그룹. trigger_sequence 는 값만 trigger_ 로 시작할 뿐 트리거가 아니라
#: 시퀀스이므로 제어·자동화 쪽에 둔다.
FUNCTION_GROUP_CONTROL = lazy_gettext('Control & Automation')
FUNCTION_GROUP_TRIGGER = lazy_gettext('Triggers')
FUNCTION_GROUP_CUSTOM = lazy_gettext('Custom Functions')

FUNCTION_CONTROL_VALUES = frozenset({
    'function_actions',
    'conditional_conditional',
    'pid_pid',
    'trigger_sequence'})


def _as_list(value):
    """interfaces 처럼 리스트일 수도, 단일 문자열일 수도 있는 필드를 리스트로."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _measurement_keys(info):
    """모듈의 measurements_dict 에서 측정 키를 순서대로 뽑는다."""
    keys = []
    for each_measure in (info.get('measurements_dict') or {}).values():
        if not isinstance(each_measure, dict):
            continue
        measurement = each_measure.get('measurement')
        if measurement and measurement not in keys:
            keys.append(measurement)
    return keys


def _measurement_labels(measure_keys):
    """측정 키를 요청 언어의 측정명으로 (MEASUREMENTS 의 이름이 이미 번역 대상)."""
    labels = []
    for each_key in measure_keys:
        if each_key not in MEASUREMENTS:
            continue
        label = str(MEASUREMENTS[each_key]['name'])
        if label not in labels:
            labels.append(label)
    return labels


def _tokens(*parts):
    """검색 토큰 문자열을 만든다.

    bootstrap-select 는 data-tokens 전체를 대문자 contains 로 훑기 때문에 단어를
    쪼갤 필요는 없지만, 중복을 걷어내면 문자열이 짧아져 옵션 200개분의 DOM 이
    가벼워진다.
    """
    tokens = []
    for each_part in parts:
        if not each_part:
            continue
        for token in str(each_part).replace('/', ' ').replace(',', ' ').split():
            token = token.strip('()[]:')
            if token and token not in tokens:
                tokens.append(token)
    return ' '.join(tokens)


def _add(groups, label, choice):
    """그룹 라벨(문자열)에 선택지 하나를 넣는다."""
    groups.setdefault(str(label), []).append(choice)


def _prune(groups):
    """비어 있는 그룹은 optgroup 을 만들지 않는다."""
    return {label: choices for label, choices in groups.items() if choices}


_input_catalog_cache = None


def _input_catalog():
    """언어와 무관한 입력 모듈 카탈로그. 프로세스 수명 동안 한 번만 만든다."""
    global _input_catalog_cache

    if _input_catalog_cache is not None:
        return _input_catalog_cache

    entries = []
    dict_inputs = parse_input_information()

    for each_input in generate_form_input_list(dict_inputs):
        info = dict_inputs[each_input]

        # GIS 입력은 이 드롭다운이 아니라 geo 페이지에서 추가한다
        if info.get('file_path', '').startswith(PATH_INPUTS_GIS):
            continue

        manufacturer = info.get('input_manufacturer') or ''
        entries.append({
            'module': each_input,
            'manufacturer': manufacturer,
            'is_aot': manufacturer == 'AoT',
            'name': info.get('input_name') or each_input,
            'measurements_name': info.get('measurements_name') or '',
            'library': info.get('input_library') or '',
            'interfaces': _as_list(info.get('interfaces')),
            'measure_keys': _measurement_keys(info)})

    _input_catalog_cache = entries
    return _input_catalog_cache


_output_catalog_cache = None


def _output_catalog():
    """언어와 무관한 출력 모듈 카탈로그. 프로세스 수명 동안 한 번만 만든다."""
    global _output_catalog_cache

    if _output_catalog_cache is not None:
        return _output_catalog_cache

    entries = []
    dict_outputs = parse_output_information()

    for each_output in generate_form_output_list(dict_outputs):
        info = dict_outputs[each_output]

        manufacturer = info.get('output_manufacturer') or ''
        entries.append({
            'module': each_output,
            'manufacturer': manufacturer,
            'is_aot': manufacturer == 'AoT',
            'name': info.get('output_name') or each_output,
            'library': info.get('output_library') or '',
            'interfaces': _as_list(info.get('interfaces')),
            'output_types': _as_list(info.get('output_types')),
            'measure_keys': _measurement_keys(info)})

    _output_catalog_cache = entries
    return _output_catalog_cache


def _input_group_label(entry):
    if entry['is_aot']:
        return GROUP_AOT
    measure_keys = set(entry['measure_keys'])
    for label, group_keys in INPUT_GROUPS:
        if measure_keys & group_keys:
            return label
    return INPUT_GROUP_OTHER


def _output_group_label(entry):
    if entry['is_aot']:
        return GROUP_AOT
    output_types = set(entry['output_types'])
    for label, group_type in OUTPUT_GROUPS:
        if group_type in output_types:
            return label
    return OUTPUT_GROUP_OTHER


def _ordered_groups(labels):
    """optgroup 출력 순서를 미리 잡아 둔 빈 dict."""
    return {str(label): [] for label in labels}


def input_add_choices():
    """input 페이지 '추가' 드롭다운의 그룹 choices.

    WTForms 3.1 의 그룹 choices 형식({그룹라벨: [(값, 라벨, render_kw)]})으로
    돌려주면 Select 위젯이 optgroup 과 옵션 속성까지 그려 준다.

    값 형식('<모듈>,<인터페이스>')은 기존과 완전히 같다. 서버 처리와 저장 형식은
    건드리지 않고 보이는 방식만 바꾼다.
    """
    groups = _ordered_groups(
        [GROUP_AOT] + [label for label, _ in INPUT_GROUPS] + [INPUT_GROUP_OTHER])

    for entry in _input_catalog():
        group_label = _input_group_label(entry)

        if entry['manufacturer']:
            name = '{manuf}: {name}'.format(
                manuf=entry['manufacturer'], name=entry['name'])
        else:
            name = entry['name']

        measurement_labels = _measurement_labels(entry['measure_keys'])
        subtext = entry['measurements_name']
        if entry['library']:
            subtext = '{sub} ({lib})'.format(
                sub=subtext, lib=entry['library']) if subtext else entry['library']

        base_tokens = _tokens(
            entry['module'],
            entry['manufacturer'],
            entry['name'],
            entry['measurements_name'],
            entry['library'],
            ' '.join(measurement_labels),
            ' '.join(entry['measure_keys']))

        if entry['interfaces']:
            for each_interface in entry['interfaces']:
                _add(groups, group_label, (
                    '{mod},{int}'.format(mod=entry['module'], int=each_interface),
                    '{name} [{int}]'.format(name=name, int=each_interface),
                    {'data-subtext': subtext,
                     'data-tokens': _tokens(base_tokens, each_interface)}))
        else:
            _add(groups, group_label, (
                '{mod},'.format(mod=entry['module']),
                name,
                {'data-subtext': subtext,
                 'data-tokens': base_tokens}))

    return _prune(groups)


def output_add_choices():
    """output 페이지 '추가' 드롭다운의 그룹 choices. 값 형식은 기존과 동일하다."""
    groups = _ordered_groups(
        [GROUP_AOT] + [label for label, _ in OUTPUT_GROUPS] + [OUTPUT_GROUP_OTHER])

    for entry in _output_catalog():
        group_label = _output_group_label(entry)
        name = entry['name']
        subtext = entry['library']

        base_tokens = _tokens(
            entry['module'],
            entry['manufacturer'],
            entry['name'],
            entry['library'],
            ' '.join(_measurement_labels(entry['measure_keys'])),
            ' '.join(entry['measure_keys']),
            ' '.join(entry['output_types']))

        if entry['interfaces']:
            for each_interface in entry['interfaces']:
                _add(groups, group_label, (
                    '{mod},{int}'.format(mod=entry['module'], int=each_interface),
                    '{name} [{int}]'.format(name=name, int=each_interface),
                    {'data-subtext': subtext,
                     'data-tokens': _tokens(base_tokens, each_interface)}))
        else:
            _add(groups, group_label, (
                '{mod},'.format(mod=entry['module']),
                name,
                {'data-subtext': subtext,
                 'data-tokens': base_tokens}))

    # 그룹 안에서는 기존처럼 표시 이름 순
    for choices in groups.values():
        choices.sort(key=lambda choice: choice[1])

    return _prune(groups)


def function_add_groups(choices_functions_add, builtin_values):
    """function 페이지 '추가' 드롭다운을 그룹으로 묶어 템플릿에 넘길 구조.

    이 드롭다운만 WTForms 폼이 아니라 템플릿에서 직접 <select> 를 그리므로
    (function.html), dict 대신 렌더링하기 쉬운 리스트로 돌려준다.

    :param choices_functions_add: [{'value': ..., 'item': ...}] 기존 평면 목록
    :param builtin_values: 내장 함수 value 집합. 나머지는 사용자 함수로 본다.
    """
    grouped = _ordered_groups(
        [FUNCTION_GROUP_CONTROL, FUNCTION_GROUP_TRIGGER, FUNCTION_GROUP_CUSTOM])

    for each_choice in choices_functions_add:
        value = each_choice['value']

        if value in FUNCTION_CONTROL_VALUES:
            group_label = FUNCTION_GROUP_CONTROL
        elif value in builtin_values:
            group_label = FUNCTION_GROUP_TRIGGER
        else:
            group_label = FUNCTION_GROUP_CUSTOM

        _add(grouped, group_label, {
            'value': value,
            'item': each_choice['item'],
            'tokens': _tokens(value, each_choice['item'])})

    return [{'label': label, 'options': options}
            for label, options in grouped.items() if options]
