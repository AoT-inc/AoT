# coding=utf-8
#
#  이 소프트웨어는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로
#  AoT 프로젝트 목적에 맞게 수정된 파생 버전입니다.
#  This file has been modified by AoT from the original Mycodo version.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  본 파일은 GNU GPLv3 라이선스에 따라 배포됩니다.
#  원본 저작권 및 라이선스 조건은 아래에 명시되어 있습니다.
#
#  --------------------------------------------------------------
#  원본 파일 정보:
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact:
#    - Original author: Kyle T. Gabriel (kylegabriel.com)
#    - Modified version: AoT (aot.inc.kr@gmail.com)
#  --------------------------------------------------------------
#  2025-04-21

import copy
import requests
import datetime
from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
from aot.inputs.sensorutils import calculate_dewpoint
from aot.utils.influx import add_measurements_influxdb

measurements_dict = {
    0: {'measurement': 'temperature', 'unit': 'C'},
    1: {'measurement': 'humidity', 'unit': 'percent'},
    2: {'measurement': 'pressure', 'unit': 'Pa'},
    3: {'measurement': 'dewpoint', 'unit': 'C'},
    4: {'measurement': 'speed', 'unit': 'm_s', 'name': '풍속'},
    5: {'measurement': 'direction', 'unit': 'bearing', 'name': '풍향'}
}

INPUT_INFORMATION = {
    'input_name_unique': 'AoT_weather_stn',
    'input_manufacturer': 'AoT_KMA',
    'input_name': '기상청 지점 데이터',
    'input_name_short': '기상청 지점',
    'measurements_name': 'Humidity/Temperature/Pressure/Wind',
    'measurements_dict': measurements_dict,
    'url_additional': 'https://apihub.kma.go.kr',
    'measurements_rescale': False,

    'message': '기상청 API 허브에서 무료 API 키를 발급받고 가까운 관측지점의 STN을 입력하세요.'
               '참고: 무료 API는 하루 20000회 호출이 가능하며, 1회 호출당 1개의 관측지점 데이터를 반환합니다.',

    'options_enabled': [
        'measurements_select',
        'period',
        'pre_output'
    ],

    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('API Key'),
            'phrase': "The API Key for this service's API"
        },
        {
            'id': 'stn',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('stn'),
            'phrase': "The stn to acquire the weather data"
        }
    ]
}


class InputModule(AbstractInput):
    """A sensor support class that gets weather for a stn."""

    # NEW: 마지막으로 처리한 TM(정시)를 기록할 변수
    last_tm_processed = None

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.api_url = None
        self.api_key = None
        self.stn = None

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        """
        초기화 로직 (필요한 부분 없으면 비워둬도 됨).
        여기에 last_tm_processed를 None으로 명시 초기화해도 되지만,
        클래스 변수로 이미 선언했으므로 생략 가능.
        """
        pass

    def get_measurement(self):
        # The publication timestamp will be extracted from the received data
        pub_timestamp = None

        if self.api_key and self.stn:
            self.api_url = (
                "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"
                f"?help=0&authKey={self.api_key}&stn={self.stn}"
            )
            self.logger.debug("URL: {}".format(self.api_url))
        else:
            self.logger.error("API키와 지점정보(stn)을 입력하세요.")
            return

        self.return_dict = copy.deepcopy(measurements_dict)
        try:
            response = requests.get(self.api_url, timeout=60)
            response.raise_for_status()
            data_text = response.text
            self.logger.debug("KMA raw response:\n{}".format(data_text))
        except Exception as e:
            self.logger.error(f"Error acquiring weather information: {e}")
            return

        lines = data_text.strip().split('\n')
        valid_data_found = False
        for line in lines:
            if line.startswith('#'):
                continue  # Skip comment lines
            cols = line.split()
            if len(cols) < 46:
                continue  # Skip if not enough columns

            # Extract the publication timestamp from the first column
            pub_timestamp = cols[0]

            try:
                # Parse the values (indices based on KMA data format)
                WD = float(cols[2])   # 풍향
                WS = float(cols[3])   # 풍속
                PS = float(cols[9])   # 해면기압
                TA = float(cols[11])  # 기온
                HM = float(cols[13])  # 상대습도

                temperature = TA
                humidity = HM
                pressure = PS
                wind_speed = WS
                wind_deg = WD

                valid_data_found = True
                break  # Process only one valid data line
            except (ValueError, IndexError) as e:
                self.logger.error(f"파싱 오류(숫자 변환 실패 등): {e}")
                continue

        if not valid_data_found:
            self.logger.error("No valid data found in KMA response.")
            return

        # 압력: hPa -> Pa 변환
        if pressure is not None:
            pressure *= 100.0

        self.logger.debug(
            "Parsed -> Temp: {}, Hum: {}, Press: {}, Wind Speed: {}, Wind Deg: {}"
            .format(temperature, humidity, pressure, wind_speed, wind_deg)
        )

        # Duplicate check: if the publication timestamp has already been processed, skip saving.
        if self.last_tm_processed == pub_timestamp:
            self.logger.info(f"Skipping measurement. Already processed TM={pub_timestamp}")
            return

        # Parse the publication timestamp and convert to a datetime object.
        # (시스템이 KST라면 단순 파싱 후 microsecond를 0으로 설정하여 "YYYY-MM-DD HH:MM:SS.000" 포맷을 맞춤)
        try:
            pub_dt = datetime.datetime.strptime(pub_timestamp, "%Y%m%d%H%M")
            pub_dt = pub_dt.replace(microsecond=0)
        except Exception as e:
            self.logger.error(f"Publication timestamp conversion failed: {e}")
            pub_dt = datetime.datetime.utcnow().replace(microsecond=0)

        # Duplicate check using InfluxDB within the last 1 hour (3600 seconds)
        try:
            from aot.utils.influx import read_influxdb_list
            pub_epoch = int(pub_dt.timestamp())
            duration_sec = 3600  # 1시간 내의 데이터만 조회
            existing = read_influxdb_list(self.input_dev.unique_id, 'C', 0, 'temperature', duration_sec)
            if existing:
                for point in existing:
                    if abs(int(point[0]) - pub_epoch) <= 1:
                        self.logger.info(f"Skipping measurement. Data for timestamp {pub_dt.isoformat()} already exists in InfluxDB.")
                        return
        except Exception as e:
            self.logger.error(f"Error during duplicate check in InfluxDB: {e}")

        # Save measurement values using pub_dt as the timestamp
        if self.is_enabled(0) and temperature is not None:
            self.value_set(0, temperature, pub_dt)
        if self.is_enabled(1) and humidity is not None:
            self.value_set(1, humidity, pub_dt)
        if self.is_enabled(2) and pressure is not None:
            self.value_set(2, pressure, pub_dt)
        if self.is_enabled(3) and temperature is not None and humidity is not None:
            dew_point = calculate_dewpoint(temperature, humidity)
            self.value_set(3, dew_point, pub_dt)
        if self.is_enabled(4) and wind_speed is not None:
            self.value_set(4, wind_speed, pub_dt)
        if self.is_enabled(5) and wind_deg is not None:
            self.value_set(5, wind_deg, pub_dt)

        self.last_tm_processed = pub_timestamp
        add_measurements_influxdb(self.input_dev.unique_id, self.return_dict, use_same_timestamp=False)
        return self.return_dict
    