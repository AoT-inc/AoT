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

from aot.inputs.base_input import AbstractInput
from aot.inputs.sensorutils import calculate_dewpoint
from aot.utils.constraints_pass import constraints_pass_positive_value

measurements_dict = {
    0: {'measurement': 'temperature', 'unit': 'C', 'name': '기온'},
    1: {'measurement': 'humidity', 'unit': 'percent', 'name': '습도'},
    2: {'measurement': 'pressure', 'unit': 'hPa', 'name': '기압'},
    3: {'measurement': 'direction', 'unit': 'bearing', 'name': '풍향'},
    4: {'measurement': 'speed', 'unit': 'm_s', 'name': '풍속'},
    5: {'measurement': 'precipitation', 'unit': 'none', 'name': '비'},
    6: {'measurement': 'precipitation', 'unit': 'mm', 'name': '15분강수'},
    7: {'measurement': 'visibility', 'unit': 'km', 'name': '시정'},
    8: {'measurement': 'snowfall', 'unit': 'cm', 'name': '적설'},
    9: {'measurement': 'dewpoint', 'unit': 'C', 'name': '이슬점'}
}

INPUT_INFORMATION = {
    'input_name_unique': 'AoT_weather_kma_500',
    'input_manufacturer': 'AoT_KMA',
    'input_name': '기상청 고해상도 500m 격자',
    'input_name_short': '기상청 고해상도',
    'measurements_dict': measurements_dict,
    'url_additional': 'https://apihub.kma.go.kr',
    'measurements_rescale': False,

    'message': '기상청 API 허브에서 무료 API 키를 발급받고 측정하고 싶은 장소의 위도와 경도를 입력하세요.'
               '참고: 무료 API는 하루 20000회 호출이 가능하며, 1회 호출당 1개의 관측지점 데이터를 반환합니다.',

    'options_enabled': [
        'measurements_select',
        'pre_output'
    ],

    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "API Key",
            'phrase': "기상청 API 허브에서 발급받은 API Key를 입력하세요."
        },
        {
            'id': 'period',
            'type': 'float',
            'default_value': 300,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': "측정 기간(초)",
            'phrase': "측정 주기를 초 단위로 입력하세요."
        },       
        {
            'id': 'lon',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "경도 (lon)",
            'phrase': "측정 위치의 경도를 입력하세요."
        },
        {
            'id': 'lat',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "위도 (lat)",
            'phrase': "측정위치의 위도를 입력하세요."
        }
    ]
}


class InputModule(AbstractInput):
    """A sensor support class that gets high-resolution weather observation data from KMA API."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)
        if not hasattr(self.input_dev, 'options'):
            self.input_dev.options = {}
            self.api_url = None
            self.api_key = None
            self.lon = None
            self.lat = None
            self.period = 600  # 기본값 600초

        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        # 필요한 경우 초기화 로직 구현
        pass

    def pre_fetch_data(self):
        """API 호출 및 응답 파싱을 수행하여, 최신 데이터를 담은 딕셔너리를 반환합니다."""
        try:
            response = requests.get(self.api_url, timeout=120)
            response.raise_for_status()
            data_text = response.text
            self.logger.debug("KMA raw response:\n{}".format(data_text))
        except Exception as e:
            self.logger.error(f"Error acquiring weather information: {e}")
            return None

        lines = data_text.strip().split('\n')
        
        best_ts = None
        data = {}
        for line in lines:
            line = line.strip()
            # Skip comment lines (including block markers)
            if line.startswith('#'):
                continue

            cols = [col.strip() for col in line.split(',')]
            if len(cols) != 10:
                continue
            pub_timestamp = cols[0]
            if len(pub_timestamp) != 12:
                continue
            if not pub_timestamp:
                self.logger.error("No data available for this time. The response data is empty.")
                continue
            
            # If the three consecutive values following the timestamp are all 0.0, skip this row
            try:
                if float(cols[1]) == 0.0 and float(cols[2]) == 0.0 and float(cols[3]) == 0.0:
                    self.logger.info(f"Ignoring invalid data row with 3 consecutive 0.0 values at {pub_timestamp}")
                    continue
            except Exception:
                pass
            
            try:
                curr_ta = float(cols[1].replace(',', ''))
                curr_hm = float(cols[2].replace(',', ''))
                curr_wd_10m = float(cols[3].replace(',', ''))
                curr_ws_10m = float(cols[4].replace(',', ''))
                curr_pa = float(cols[5].replace(',', ''))
                curr_rn_ox = float(cols[6].replace(',', ''))
                curr_rn_15m = float(cols[7].replace(',', ''))
                curr_vs = float(cols[8].replace(',', ''))
                curr_sd_tot = float(cols[9].replace(',', ''))
            except (ValueError, IndexError) as e:
                self.logger.error(f"Parsing error: {e}")
                continue
            # YYYYMMDDHHMM 포맷이므로 문자열 비교로 최신 pub_timestamp 선택
            if best_ts is None or pub_timestamp > best_ts:
                best_ts = pub_timestamp
                data = {
                    "ta": curr_ta,
                    "hm": curr_hm,
                    "wd_10m": curr_wd_10m,
                    "ws_10m": curr_ws_10m,
                    "pa": curr_pa,
                    "rn_ox": curr_rn_ox,
                    "rn_15m": curr_rn_15m,
                    "vs": curr_vs,
                    "sd_tot": curr_sd_tot,
                    "pub_timestamp": pub_timestamp
                }
        if best_ts is None:
            self.logger.error("No valid data found in the response.")
            return None
        return data

    def get_measurement(self):
        # Custom 옵션에서 값을 읽어옴
        self.api_key = self.get_custom_option('api_key')
        self.lon = self.get_custom_option('lon')
        self.lat = self.get_custom_option('lat')
        self.period = int(self.get_custom_option('period') or 300)

        if self.api_key and self.lon and self.lat:
            # 요청 시간: 지금 시간에서 5분 전부터 지금 시간까지의 데이터를 요청
            now = datetime.datetime.now()
            tm1_dt = now - datetime.timedelta(minutes=5)
            tm1 = tm1_dt.strftime("%Y%m%d%H%M")
            tm2 = now.strftime("%Y%m%d%H%M")
            # itv는 tm1과 tm2 사이의 시간(분)로, 여기서는 5분입니다.
            itv = 5

            self.api_url = (
                "https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php"
                f"?tm1={tm1}&tm2={tm2}&lon={self.lon}&lat={self.lat}"
                f"&obs=ta,hm,wd_10m,ws_10m,pa,rn_ox,rn_15m,vs,sd_tot"
                f"&itv={itv}&help=0&authKey={self.api_key}"
            )
            self.logger.debug("URL: {}".format(self.api_url))
        else:
            self.logger.error("Please provide API key and coordinates (lon, lat).")
            return

        self.return_dict = copy.deepcopy(measurements_dict)
        data = self.pre_fetch_data()
        if data is None:
            return

        ta = data["ta"]
        hm = data["hm"]
        wd_10m = data["wd_10m"]
        ws_10m = data["ws_10m"]
        pa = data["pa"]
        rn_ox = data["rn_ox"]
        rn_15m = data["rn_15m"]
        vs = data["vs"]
        sd_tot = data["sd_tot"]

        pressure = pa
        dew_point = calculate_dewpoint(ta, hm)

        self.logger.debug(
            "Parsed -> Temp: {}, Hum: {}, Pressure: {}, Wind Dir: {}, Wind Speed: {}, "
            "Precipitation Indicator: {}, 15min Precip: {}, Visibility: {}, Snowfall: {}"
            .format(ta, hm, pressure, wd_10m, ws_10m, rn_ox, rn_15m, vs, sd_tot)
        )

        # 데이터를 분류하여 self.return_dict에 저장
        if self.is_enabled(0) and ta is not None:
            self.value_set(0, ta)
        if self.is_enabled(1) and hm is not None:
            self.value_set(1, hm)
        if self.is_enabled(2) and pressure is not None:
            self.value_set(2, pressure)
        if self.is_enabled(3) and wd_10m is not None:
            self.value_set(3, wd_10m)
        if self.is_enabled(4) and ws_10m is not None:
            self.value_set(4, ws_10m)
        if self.is_enabled(5) and rn_ox is not None:
            self.value_set(5, rn_ox)
        if self.is_enabled(6) and rn_15m is not None:
            self.value_set(6, rn_15m)
        if self.is_enabled(7) and vs is not None:
            self.value_set(7, vs)
        if self.is_enabled(8) and sd_tot is not None:
            self.value_set(8, sd_tot)
        if self.is_enabled(9) and dew_point is not None:
            self.value_set(9, dew_point)

        return self.return_dict