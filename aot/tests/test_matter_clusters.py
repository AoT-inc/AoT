# coding=utf-8
"""Matter 클러스터 → AoT 채널 매핑(aot/devices/matter_clusters.py) 검사.

순수 함수만 다루므로 I/O 없이 "endpoint/cluster/attribute" 키의 dict 로
노드를 흉내 낸다. 지키는 것:
  - convert: 센서별 원시값 환산(0.01 °C, 0.01 %, 조도 로그식, 배터리 0.5 % 단위)
    과 null·문자열·dict·list·알 수 없는 kind 는 None.
  - discover_channels: 엔드포인트별 Descriptor.ServerList 기준의 입력·출력 채널,
    이름 규칙(단일 인스턴스는 접미사 없음, 여러 개면 엔드포인트 번호, 브리지
    엔드포인트는 자기 이름), 값이 없는 센서 생략, 깨진 키 무시, 루트(0) 엔드포인트의
    OnOff 는 출력 아님.
  - device_identity / display_name: 재공유 때 기존 Device 를 맞추는 키와 표시 이름.
"""
import pytest

from aot.devices import matter_clusters as mc


SENSOR_KINDS = ['temperature', 'humidity', 'illuminance', 'boolean_state', 'battery']


# ---------------------------------------------------------------- convert

def test_convert_temperature_is_centi_celsius():
    assert mc.convert('temperature', 2150) == pytest.approx(21.5)
    assert mc.convert('temperature', -500) == pytest.approx(-5.0)


def test_convert_humidity_is_centi_percent():
    assert mc.convert('humidity', 4550) == pytest.approx(45.5)


def test_convert_illuminance_is_log_scale_lux():
    # MeasuredValue = 10000 * log10(lux) + 1
    assert mc.convert('illuminance', 1) == pytest.approx(1.0)
    assert mc.convert('illuminance', 10001) == pytest.approx(10.0)
    assert mc.convert('illuminance', 40001) == pytest.approx(10000.0)
    # 0 means "too low to measure"
    assert mc.convert('illuminance', 0) == pytest.approx(0.0)


def test_convert_illuminance_nonpositive_is_zero():
    assert mc.convert('illuminance', -5) == pytest.approx(0.0)


def test_convert_boolean_state_is_one_or_zero():
    assert mc.convert('boolean_state', True) == 1.0
    assert mc.convert('boolean_state', False) == 0.0


def test_convert_battery_is_half_percent_steps():
    assert mc.convert('battery', 200) == pytest.approx(100.0)
    assert mc.convert('battery', 101) == pytest.approx(50.5)


@pytest.mark.parametrize('kind', SENSOR_KINDS)
def test_convert_none_is_none_for_every_kind(kind):
    assert mc.convert(kind, None) is None


@pytest.mark.parametrize('kind', SENSOR_KINDS)
@pytest.mark.parametrize('raw', ['2150', {'value': 2150}, [2150]])
def test_convert_string_dict_list_is_none(kind, raw):
    assert mc.convert(kind, raw) is None


@pytest.mark.parametrize('raw', [float('nan'), float('inf')])
def test_convert_nan_and_inf_are_none(raw):
    assert mc.convert('temperature', raw) is None
    assert mc.convert('illuminance', raw) is None


def test_convert_unknown_kind_is_none():
    assert mc.convert('no_such_kind', 100) is None


def test_convert_actuator_kind_is_not_a_sensor():
    assert mc.convert('on_off', 1) is None


# ---------------------------------------------------------- attribute_path

def test_attribute_path_is_decimal_triple():
    assert mc.attribute_path(1, 6, 0) == '1/6/0'


# ------------------------------------------------------- discover_channels

def test_plug_has_one_output_and_no_inputs():
    node = {
        'node_id': 5,
        'attributes': {
            '0/40/1': 'Acme',
            '0/40/2': 65521,
            '0/40/3': 'Plug',
            '0/40/4': 32768,
            '0/40/5': '',
            '0/40/15': 'SN1',
            '0/40/18': 'U1',
            '0/29/1': [29, 40, 62],
            '1/29/1': [3, 4, 6, 29],
            '1/6/0': False,
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert inputs == []
    assert outputs == [{
        'matter_kind': 'on_off',
        'endpoint': 1,
        'cluster_id': 6,
        'output_type': 'on_off',
        'driver': 'MATTER_ON_OFF',
        'name': 'Switch',
    }]


def test_temperature_humidity_battery_inputs_ordered_by_endpoint():
    node = {
        'node_id': 9,
        'attributes': {
            '0/29/1': [29, 40, 47],
            '0/47/12': 180,
            '1/29/1': [1026, 29],
            '1/1026/0': 2150,
            '2/29/1': [1029, 29],
            '2/1029/0': 4550,
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert outputs == []
    assert [(i['matter_kind'], i['endpoint']) for i in inputs] == [
        ('battery', 0),
        ('temperature', 1),
        ('humidity', 2),
    ]
    battery, temperature, humidity = inputs
    assert battery == {
        'matter_kind': 'battery',
        'endpoint': 0,
        'cluster_id': 47,
        'attribute_id': 12,
        'measurement': 'battery',
        'unit': 'percent',
        'name': 'Battery',
    }
    assert temperature['measurement'] == 'temperature'
    assert temperature['unit'] == 'C'
    assert temperature['name'] == 'Temperature'
    assert temperature['attribute_id'] == 0
    assert humidity['measurement'] == 'humidity'
    assert humidity['unit'] == 'percent'
    assert humidity['name'] == 'Humidity'


def test_two_onoff_endpoints_get_numbered_names():
    node = {
        'node_id': 3,
        'attributes': {
            '1/29/1': [6, 29],
            '1/6/0': True,
            '2/29/1': [6, 29],
            '2/6/0': False,
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert inputs == []
    assert [(o['endpoint'], o['name']) for o in outputs] == [
        (1, 'Switch 1'),
        (2, 'Switch 2'),
    ]


def test_bridged_endpoint_uses_its_own_label():
    node = {
        'node_id': 4,
        'attributes': {
            '3/29/1': [6, 57, 29],
            '3/57/5': 'Greenhouse fan',
            '3/6/0': False,
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert inputs == []
    assert len(outputs) == 1
    assert outputs[0]['endpoint'] == 3
    assert outputs[0]['name'] == 'Greenhouse fan Switch'


def test_bridged_label_is_stripped_and_product_name_is_used_when_label_blank():
    node = {
        'node_id': 4,
        'attributes': {
            '3/29/1': [6, 57, 29],
            '3/57/5': '   ',
            '3/57/3': '  Heater  ',
            '3/6/0': False,
        },
    }
    _, outputs = mc.discover_channels(node)
    assert [o['name'] for o in outputs] == ['Heater Switch']


def test_sensor_listed_in_server_list_without_value_is_skipped():
    node = {
        'node_id': 6,
        'attributes': {
            '0/29/1': [29, 40],
            '1/29/1': [29, 1026],   # ServerList says temperature, no 1/1026/0
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert inputs == []
    assert outputs == []


def test_missing_server_list_falls_back_to_observed_clusters():
    node = {
        'node_id': 7,
        'attributes': {
            '1/1026/0': 2150,
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert outputs == []
    assert len(inputs) == 1
    assert inputs[0]['matter_kind'] == 'temperature'
    assert inputs[0]['endpoint'] == 1
    assert inputs[0]['name'] == 'Temperature'


def test_empty_server_list_also_falls_back_to_observed_clusters():
    node = {
        'node_id': 7,
        'attributes': {
            '1/29/1': [],
            '1/6/0': True,
        },
    }
    _, outputs = mc.discover_channels(node)
    assert [(o['endpoint'], o['name']) for o in outputs] == [(1, 'Switch')]


def test_onoff_on_root_endpoint_is_never_an_output():
    node = {
        'node_id': 8,
        'attributes': {
            '0/29/1': [6, 29, 40],
            '0/6/0': True,
            '0/40/3': 'Plug',
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert inputs == []
    assert outputs == []


@pytest.mark.parametrize('node', [None, {}, {'node_id': 1}, {'node_id': 1, 'attributes': {}}])
def test_empty_or_none_node_has_no_channels(node):
    assert mc.discover_channels(node) == ([], [])


def test_malformed_attribute_keys_are_ignored():
    node = {
        'node_id': 2,
        'attributes': {
            'x/y': 1,
            '1/6': True,        # two parts
            '1/2/3/4': 9,       # four parts
            'a/b/c': 1,
            '1/6/0': True,
            '1/29/1': [6, 29],
        },
    }
    inputs, outputs = mc.discover_channels(node)
    assert inputs == []
    assert [(o['endpoint'], o['name']) for o in outputs] == [(1, 'Switch')]


# -------------------------------------------------------- device_identity

def test_identity_prefers_unique_id():
    node = {
        'attributes': {
            '0/40/18': 'U1',
            '0/40/2': 65521,
            '0/40/4': 32768,
            '0/40/15': 'SN1',
        },
    }
    info = mc.device_identity(node)
    assert info['identity_key'] == 'uid:U1'
    assert info['unique_id'] == 'U1'
    assert info['vendor_id'] == 65521
    assert info['product_id'] == 32768
    assert info['serial_number'] == 'SN1'


def test_unique_id_is_trimmed_in_key():
    node = {'attributes': {'0/40/18': '  U1  '}}
    assert mc.device_identity(node)['identity_key'] == 'uid:U1'


def test_identity_falls_back_to_vendor_product_serial():
    node = {
        'attributes': {
            '0/40/2': 65521,
            '0/40/4': 32768,
            '0/40/15': 'SN1',
        },
    }
    assert mc.device_identity(node)['identity_key'] == 'vps:65521:32768:SN1'


def test_whitespace_only_unique_id_falls_back_to_vps():
    node = {
        'attributes': {
            '0/40/18': '   ',
            '0/40/2': 65521,
            '0/40/4': 32768,
            '0/40/15': 'SN1',
        },
    }
    assert mc.device_identity(node)['identity_key'] == 'vps:65521:32768:SN1'


def test_identity_is_none_without_unique_id_or_full_triplet():
    neither = {'attributes': {'0/40/1': 'Acme', '0/40/3': 'Plug'}}
    assert mc.device_identity(neither)['identity_key'] is None

    no_serial = {'attributes': {'0/40/2': 65521, '0/40/4': 32768}}
    assert mc.device_identity(no_serial)['identity_key'] is None

    blank_serial = {'attributes': {'0/40/2': 65521, '0/40/4': 32768, '0/40/15': '  '}}
    assert mc.device_identity(blank_serial)['identity_key'] is None


def test_identity_of_none_node_is_empty():
    info = mc.device_identity(None)
    assert info['identity_key'] is None
    assert info['unique_id'] is None


# ---------------------------------------------------------- display_name

def test_display_name_prefers_node_label():
    node = {
        'node_id': 7,
        'attributes': {'0/40/5': 'Garage plug', '0/40/3': 'Plug', '0/40/1': 'Acme'},
    }
    assert mc.display_name(node) == 'Garage plug'


def test_display_name_strips_label_whitespace():
    node = {'node_id': 7, 'attributes': {'0/40/5': '  Garage  '}}
    assert mc.display_name(node) == 'Garage'


def test_display_name_falls_back_to_product_name_when_label_blank():
    node = {
        'node_id': 7,
        'attributes': {'0/40/5': '', '0/40/3': 'Plug', '0/40/1': 'Acme'},
    }
    assert mc.display_name(node) == 'Plug'


def test_display_name_falls_back_to_vendor_name():
    node = {
        'node_id': 7,
        'attributes': {'0/40/5': '  ', '0/40/3': '  ', '0/40/1': 'Acme'},
    }
    assert mc.display_name(node) == 'Acme'


def test_display_name_falls_back_to_node_id():
    assert mc.display_name({'node_id': 7, 'attributes': {}}) == 'Matter node 7'
    assert mc.display_name({'attributes': {}}) == 'Matter node ?'
    assert mc.display_name(None) == 'Matter node ?'


def test_name_counts_only_emitted_channels():
    """값이 없어 빠지는 센서는 번호 매기기에 세지 않는다."""
    node = {'attributes': {
        '1/29/1': [1026, 29], '1/1026/0': 2150,
        '2/29/1': [1026, 29],
    }}
    inputs, _ = mc.discover_channels(node)
    assert [i['name'] for i in inputs] == ['Temperature']


# --- P2 센서 ------------------------------------------------------------------

@pytest.mark.parametrize('kind, raw, expected', [
    ('pressure', 1013, 101.3),
    ('flow', 600, 1000.0),                 # 60.0 m³/h -> 1000 L/min
    ('occupancy', 1, 1.0),
    ('occupancy', 0, 0.0),
    ('occupancy', 2, 0.0),                 # other bits are not "occupied"
    ('co2', 612.5, 612.5),
    ('pm25', 12.0, 12.0),
    ('soil_moisture', 37, 37.0),
    ('power', 1234567, 1234.567),          # mW -> W
    ('voltage', 230100, 230.1),            # mV -> V
    ('current', 1500, 1.5),                # mA -> A
    ('energy', {'0': 2500000, '1': 1700000000}, 2.5),   # mWh -> kWh
])
def test_p2_conversions(kind, raw, expected):
    assert mc.convert(kind, raw) == pytest.approx(expected)


def test_struct_only_for_struct_kinds():
    assert mc.convert('energy', {'1': 5}) is None          # no energy tag
    assert mc.convert('temperature', {'0': 2150}) is None  # not a struct kind


def test_concentration_mapped_only_in_stored_unit():
    node = {'attributes': {
        '1/29/1': [1037, 1066, 29],
        '1/1037/0': 600.0, '1/1037/8': 0,      # CO2 in ppm -> mapped
        '1/1066/0': 0.012, '1/1066/8': 3,      # PM2.5 in mg/m³ -> skipped
    }}
    inputs, _ = mc.discover_channels(node)
    assert [(i['matter_kind'], i['unit']) for i in inputs] == [('co2', 'ppm')]


def test_electrical_sensor_channels():
    node = {'attributes': {
        '2/29/1': [144, 145, 156, 29],
        '2/144/8': 1200000, '2/144/4': 230000, '2/144/5': 5200,
        '2/145/1': {'0': 1000000},
    }}
    inputs, _ = mc.discover_channels(node)
    assert [(i['matter_kind'], i['measurement'], i['unit']) for i in inputs] == [
        ('power', 'power', 'W'), ('voltage', 'electrical_potential', 'V'),
        ('current', 'electrical_current', 'A'), ('energy', 'energy', 'kWh')]


# --- P2 출력·버튼 ----------------------------------------------------------------

def test_dimmable_light_is_one_dimmer_not_switch_plus_dimmer():
    node = {'attributes': {'1/29/1': [3, 4, 6, 8, 29], '1/29/0': [{'0': 257, '1': 3}],
                           '1/6/0': True, '1/8/0': 200}}
    _, outputs = mc.discover_channels(node)
    assert [(o['matter_kind'], o['driver'], o['output_type']) for o in outputs] == [
        ('level', 'MATTER_LEVEL', 'pwm')]


@pytest.mark.parametrize('device_type', [0x0101, 0x010B, 0x010C, 0x010D])
def test_every_dimmable_device_type_becomes_a_dimmer(device_type):
    node = {'attributes': {'1/29/1': [6, 8, 29], '1/29/0': [{'0': device_type, '1': 1}],
                           '1/6/0': True, '1/8/0': 100}}
    _, outputs = mc.discover_channels(node)
    assert [o['matter_kind'] for o in outputs] == ['level']


def test_dimmable_type_may_be_one_of_several_device_types():
    node = {'attributes': {'1/29/1': [6, 8, 29],
                           '1/29/0': [{'0': 0x010A, '1': 3}, {'0': 0x0101, '1': 3}],
                           '1/6/0': True, '1/8/0': 100}}
    assert [o['matter_kind'] for o in mc.discover_channels(node)[1]] == ['level']


def test_relay_plug_with_level_control_stays_an_on_off_switch():
    """On/Off Plug-in Unit (0x010A) 이 LevelControl 을 갖고 있어도 디머가 아니다."""
    node = {'attributes': {'1/29/1': [3, 4, 6, 8, 29], '1/29/0': [{'0': 0x010A, '1': 3}],
                           '1/6/0': True, '1/8/0': 100}}
    _, outputs = mc.discover_channels(node)
    assert [(o['matter_kind'], o['driver'], o['output_type']) for o in outputs] == [
        ('on_off', 'MATTER_ON_OFF', 'on_off')]


def test_level_control_without_a_device_type_list_stays_on_off():
    node = {'attributes': {'1/29/1': [3, 4, 6, 8, 29], '1/6/0': True, '1/8/0': 100}}
    _, outputs = mc.discover_channels(node)
    assert [o['matter_kind'] for o in outputs] == ['on_off']


def test_malformed_device_type_list_stays_on_off():
    node = {'attributes': {'1/29/1': [6, 8, 29], '1/29/0': 'oops', '1/6/0': True, '1/8/0': 1}}
    assert [o['matter_kind'] for o in mc.discover_channels(node)[1]] == ['on_off']
    node['attributes']['1/29/0'] = [None, {'0': 'x'}]
    assert [o['matter_kind'] for o in mc.discover_channels(node)[1]] == ['on_off']


def test_covering_needs_lift_and_is_per_endpoint():
    node = {'attributes': {
        '1/29/1': [258, 29], '1/258/65532': 0b101, '1/258/14': 0,      # lift + PA lift
        '2/29/1': [258, 29], '2/258/65532': 0b010, '2/258/15': 0,      # tilt only
    }}
    _, outputs = mc.discover_channels(node)
    assert [(o['matter_kind'], o['endpoint']) for o in outputs] == [('covering', 1)]
    assert mc.ACTUATOR_SPECS[2]['per_endpoint'] is True
    assert mc.covering_position_aware(node['attributes'], 1) is True
    assert mc.covering_position_aware({'1/258/65532': 0b001}, 1) is False


def test_button_channel_only_for_momentary_switch():
    node = {'attributes': {
        '1/29/1': [59, 29], '1/59/65532': 0b10110, '1/59/1': 0,        # momentary
        '2/29/1': [59, 29], '2/59/65532': 0b00001, '2/59/1': 0,        # latching
    }}
    inputs, _ = mc.discover_channels(node)
    assert [(i['matter_kind'], i['endpoint']) for i in inputs] == [('button', 1)]


@pytest.mark.parametrize('event_id, data, multi, expected', [
    (mc.SWITCH_EV_SHORT_RELEASE, {'previousPosition': 1}, False, 1.0),
    (mc.SWITCH_EV_INITIAL_PRESS, {'newPosition': 1}, False, None),
    (mc.SWITCH_EV_LONG_PRESS, {'newPosition': 1}, False, -1.0),
    (mc.SWITCH_EV_LONG_RELEASE, {'previousPosition': 1}, False, None),
    (mc.SWITCH_EV_SHORT_RELEASE, {'previousPosition': 1}, True, None),   # device counts
    (mc.SWITCH_EV_MULTI_PRESS_COMPLETE, {'totalNumberOfPressesCounted': 2}, True, 2.0),
    (mc.SWITCH_EV_MULTI_PRESS_COMPLETE, {'totalNumberOfPressesCounted': 0}, True, None),
    (mc.SWITCH_EV_LONG_PRESS, {}, True, -1.0),
])
def test_button_value(event_id, data, multi, expected):
    assert mc.button_value(event_id, data, multi) == expected
