# coding=utf-8
"""자원 압박 단계와 그 신호를 측정값으로 남긴다 (R1 — 관찰만).

판정은 `aot.utils.resource_pressure` 하나가 한다. 이 입력은 그 결과를 주기적으로
Influx 에 기록할 뿐이고, 아무것도 줄이지 않는다. 기록이 있어야 "언제 바빴나" 를
실측과 맞춰 문턱을 정할 수 있고, 단계 변화에 알림을 걸고 싶으면 이 측정값에
조건·함수를 연결하면 된다(알림을 코드에 박지 않는다).

없는 신호(파이가 아니면 스로틀·온도, 커널에 PSI 가 없으면 PSI, 웹 요청이 한산하면 p95)는
그 채널만 비운다.
"""
import copy

from aot.inputs.base_input import AbstractInput

measurements_dict = {
    0: {'measurement': 'unitless', 'unit': 'none',
        'name': 'Pressure Stage (0 normal, 1 watch, 2 overload)'},
    1: {'measurement': 'unitless', 'unit': 'none', 'name': 'CPU Pressure (PSI some avg10, %)'},
    2: {'measurement': 'unitless', 'unit': 'none', 'name': 'Memory Pressure (PSI some avg10, %)'},
    3: {'measurement': 'unitless', 'unit': 'none', 'name': 'IO Pressure (PSI some avg10, %)'},
    4: {'measurement': 'unitless', 'unit': 'none', 'name': 'Load per Core (1 min)'},
    5: {'measurement': 'unitless', 'unit': 'none', 'name': 'Memory Available (%)'},
    6: {'measurement': 'duration_time', 'unit': 's', 'name': 'Web Response p95'},
    7: {'measurement': 'unitless', 'unit': 'none', 'name': 'Throttled Bits (vcgencmd)'},
    8: {'measurement': 'temperature', 'unit': 'C', 'name': 'CPU Temperature'},
    9: {'measurement': 'unitless', 'unit': 'none', 'name': 'CPU Used of Limit (%)'},
    10: {'measurement': 'unitless', 'unit': 'none', 'name': 'CPU Throttled (% of time)'},
}

INPUT_INFORMATION = {
    'input_name_unique': 'AOT_RESOURCE_PRESSURE',
    'input_manufacturer': 'AoT',
    'input_name': 'System Resource Pressure',
    'input_library': '/proc/pressure, cgroup, vcgencmd',
    'measurements_name': 'Resource Pressure',
    'measurements_dict': measurements_dict,
    'measurements_use_same_timestamp': True,

    'message': 'Records how busy this server is: a pressure stage (0 normal, 1 watch, 2 overload) '
               'and the signals behind it — CPU/memory/IO pressure (PSI), CPU use against its limit '
               'and throttled time, load per core, available memory, web response p95 of polling and '
               'API requests, and on a Raspberry Pi the throttle bits and CPU temperature. '
               'Signals the device does not provide are left empty. Observation only: nothing is '
               'slowed down or turned off by this input.',

    'options_enabled': [
        'measurements_select',
        'period'
    ],
}

# 채널 → 판정 결과의 키
_CHANNEL_KEYS = {
    0: 'stage',
    1: 'cpu_psi',
    2: 'memory_psi',
    3: 'io_psi',
    4: 'load_per_core',
    5: 'mem_available_pct',
    7: 'throttled_bits',
    8: 'temperature_c',
    9: 'cpu_used_pct',
    10: 'cpu_throttled_pct',
}


class InputModule(AbstractInput):
    """Reads the resource pressure stage and its signals.

    @phase active
    @stability experimental
    @dependency AbstractInput, aot.utils.resource_pressure"""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

    def get_measurement(self):
        from aot.utils import resource_pressure
        self.return_dict = copy.deepcopy(measurements_dict)
        snap = resource_pressure.current()
        for chan, key in _CHANNEL_KEYS.items():
            value = snap.get(key)
            if value is not None and self.is_enabled(chan):
                self.value_set(chan, value)
        p95 = snap.get('web_p95_ms')
        if p95 is not None and self.is_enabled(6):
            self.value_set(6, p95 / 1000.0)
        return self.return_dict
