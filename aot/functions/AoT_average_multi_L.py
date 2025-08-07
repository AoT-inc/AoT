# coding=utf-8
#

import time

from flask_babel import lazy_gettext

from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.influx import read_influxdb_single
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info

# 측정값(Measurement) 설정 딕셔너리
measurements_dict = {
    0: {
        'measurement': '',
        'unit': '',
    }
}

FUNCTION_INFORMATION = {
    'function_name_unique': 'AoT_AVG_MULTI',
    'function_name': 'AoT 평균 (최종, 다중)',
    'measurements_dict': measurements_dict,
    'enable_channel_unit_select': True,

    'message': '이 기능은 선택된 측정값들을 읽어와, 유효한 데이터만 평균을 구한 후, 결과를 지정한 Measurement와 단위로 저장합니다.'
               '유효하지 않거나 오래된 측정값(최대 유효 시간 초과)은 평균에서 제외합니다.',

    'options_enabled': [
        'measurements_select_measurement_unit',
        'custom_options'
    ],

    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('주기'), lazy_gettext('초')),
            'phrase': lazy_gettext('측정 및 계산 주기, 시간(초 단위)')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('시작 지연'), lazy_gettext('초')),
            'phrase': lazy_gettext('첫 측정 전에 대기할 시간(초)')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('최대 유효 시간'), lazy_gettext('초')),
            'phrase': lazy_gettext(' 사용할 측정값의 최대 유효 시간')
        },
        {
            'id': 'select_measurement',
            'type': 'select_multi_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'name': lazy_gettext('Measurement'),
            'phrase': lazy_gettext('평균을 계산할 측정 값을 선택하세요')
        }
    ]
}


class CustomModule(AbstractFunction):
    """
    여러 채널의 마지막 측정값들을 취합하여 평균을 구하는 예시 기능입니다.
    유효하지 않거나 오래된 측정값(최대 유효 시간 초과)은 평균에서 제외합니다.
    """

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = time.time()

        self.control = DaemonControl()

        # 사용자 정의 옵션 초기화
        self.period = None
        self.start_offset = None
        self.select_measurement = None
        self.max_measure_age = None

        # DB에서 해당 CustomController(기능) 정보 조회
        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)

        # UI에서 설정된 custom_options를 가져와서 self에 적용
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function
        )

        if not testing:
            self.try_initialize()

    def initialize(self):
        """
        초기 구동 시점에 호출됩니다.
        """
        # 첫 동작 시점을 start_offset 후로 설정
        self.timer_loop = time.time() + self.start_offset

    def loop(self):
        """
        주기(period)마다 실행되는 메인 루프 함수입니다.
        """
        # 아직 주기가 안 되었으면 그냥 반환
        if self.timer_loop > time.time():
            return

        # 주기 시간만큼 timer_loop를 갱신하여 다음 실행 시점 계산
        while self.timer_loop < time.time():
            self.timer_loop += self.period

        # ------------------------------------------------
        # 1) 선택된 Measurement(채널들)로부터 마지막 측정값 수집
        # ------------------------------------------------
        measurements = []
        for each_id_set in self.select_measurement:
            device_device_id = each_id_set.split(",")[0]  # 장치(unique_id)
            device_measure_id = each_id_set.split(",")[1]  # 측정 채널 ID

            device_measurement = get_measurement(device_measure_id)

            # 채널 정보가 유효한지 확인
            if not device_measurement:
                self.logger.error(
                    "채널(측정 ID: {}) 정보를 찾을 수 없습니다. 이 채널을 스킵합니다.".format(device_measure_id))
                continue

            # Conversion(변환 설정) 조회
            conversion = db_retrieve_table_daemon(
                Conversion, unique_id=device_measurement.conversion_id
            )
            channel, unit, measurement = return_measurement_info(
                device_measurement, conversion
            )

            self.logger.debug(
                "장치ID: {}, 측정단위: {}, 채널: {}, 측정명: {}, max_age: {} 초".format(
                    device_device_id, unit, channel, measurement, self.max_measure_age
                )
            )

            # InfluxDB에서 마지막(최근) 측정값 조회 (최대 유효 시간 내)
            last_measurement = read_influxdb_single(
                device_device_id,
                unit,
                channel,
                measure=measurement,
                duration_sec=self.max_measure_age,
                value='LAST'
            )

            self.logger.debug("채널 측정 결과: {}".format(last_measurement))

            if not last_measurement:
                # 유효한 측정값을 얻지 못한 경우(시간 초과, 데이터 없음 등)는 평균에서 제외
                self.logger.warning(
                    "유효 데이터 없음(또는 {}초 이내 측정값 없음) → 채널(장치ID: {}, 채널: {}) 제외".format(
                        self.max_measure_age, device_device_id, channel
                    )
                )
            else:
                # last_measurement 구조: (timestamp, value)
                measurements.append(last_measurement[1])

        # ------------------------------------------------
        # 2) 유효한 데이터가 하나도 없으면 평균 계산 안 함
        # ------------------------------------------------
        if not measurements:
            self.logger.warning("유효한 측정값이 없어 평균을 계산하지 않습니다.")
            return

        # 평균 계산
        average = float(sum(measurements) / float(len(measurements)))
        self.logger.info("획득된 {}개 채널 측정값 평균: {}".format(len(measurements), average))

        # ------------------------------------------------
        # 3) 계산된 평균값을 InfluxDB에 저장
        # ------------------------------------------------
        measurement_dict = {
            0: {
                'measurement': self.channels_measurement[0].measurement,
                'unit': self.channels_measurement[0].unit,
                'value': average
            }
        }

        if measurement_dict:
            self.logger.debug(
                "ID {}에 대한 평균값 InfluxDB 기록: {}".format(
                    self.unique_id, measurement_dict
                )
            )
            add_measurements_influxdb(self.unique_id, measurement_dict)
        else:
            self.logger.debug(
                "ID {}에 기록할 측정값이 없습니다.".format(self.unique_id)
            )