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

import logging
import os
import json
import requests
import datetime
import math
from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
from aot.config import KMA_PATH, PATH_JSON

logger = logging.getLogger(__name__)

# 농업용 단기예보 측정 항목 구성 (원시 데이터 저장 – 향후 조회 시 문자 변환 적용)
measurements_dict = {
    'TMP': {'name': '기온', 'measurement': 'temperature', 'unit': 'C'},
    'TMN': {'name': '최저기온', 'measurement': 'temperature', 'unit': 'C'},
    'TMX': {'name': '최고기온', 'measurement': 'temperature', 'unit': 'C'},
    'REH': {'name': '습도', 'measurement': 'humidity', 'unit': 'percent'},
    'WSD': {'name': '풍속', 'measurement': 'speed', 'unit': 'm_s'},
    'VEC': {'name': '풍향', 'measurement': 'direction', 'unit': 'bearing'},
    'SKY': {'name': '하늘상태', 'measurement': 'sky_condition', 'unit': 'none'},
    'RN1': {'name': '강수량', 'measurement': 'precipitation', 'unit': 'mm'},
    'POP': {'name': '강수확률', 'measurement': 'precipitation', 'unit': 'percent'},
    'PTY': {'name': '강수형태', 'measurement': 'precipitation', 'unit': 'none'},
    'SNO': {'name': '신적설', 'measurement': 'snowfall', 'unit': 'cm'}
}

def wind_direction_to_korean(vec):
    """
    풍향(0°~360°)을 한글로 변환.
    예: 0~45 → '북풍', 45~90 → '북동풍', 90~135 → '동풍', 
       135~180 → '남동풍', 180~225 → '남풍', 225~270 → '남서풍',
       270~315 → '서풍', 315~360 → '북서풍'
    """
    vec = vec % 360
    if 0 <= vec < 45:
        return "북풍"
    elif 45 <= vec < 90:
        return "북동풍"
    elif 90 <= vec < 135:
        return "동풍"
    elif 135 <= vec < 180:
        return "남동풍"
    elif 180 <= vec < 225:
        return "남풍"
    elif 225 <= vec < 270:
        return "남서풍"
    elif 270 <= vec < 315:
        return "서풍"
    else:
        return "북서풍"

def sky_code_to_text(code):
    """
    SKY 코드 변환: 1 → '맑음', 3 → '구름많음', 4 → '흐림'
    """
    mapping = {1: "맑음", 3: "구름많음", 4: "흐림"}
    try:
        result = mapping.get(int(code), str(code))
        return fix_korean(result)
    except Exception:
        return fix_korean(str(code))

def pty_code_to_text(code):
    """
    PTY 코드 변환 (단기 기준):
      0 → '없음', 1 → '비', 2 → '비/눈', 3 → '눈', 4 → '소나기'
    """
    mapping = {0: "없음", 1: "비", 2: "비/눈", 3: "눈", 4: "소나기"}
    try:
        result = mapping.get(int(code), str(code))
        return fix_korean(result)
    except Exception:
        return fix_korean(str(code))

def fix_korean(text):
    """Attempt to fix garbled Korean text by re-encoding from latin1 to utf-8."""
    try:
        return text.encode('latin1').decode('utf-8')
    except Exception:
        return text

def sno_code_to_value(code):
    """
    SNO 코드 변환: 
      - "적설없음" (또는 인코딩 문제가 있는 경우 해당 문자열) 인 경우 0.0 반환
      - 그 외에는 숫자형 값으로 변환하여 반환합니다.
    """
    mapping = {"적설없음": 0.0}
    try:
        # fix_korean 함수를 이용해 인코딩 문제를 해결한 후 문자열로 변환
        code_str = fix_korean(str(code)).strip()
        # 매핑 사전에 있으면 매핑된 값을 반환, 없으면 숫자형 변환 시도
        return mapping.get(code_str, float(code_str))
    except Exception:
        return 0.0

INPUT_INFORMATION = {
    "input_name_unique": "AoT_KMA_forecast",
    "input_manufacturer": "AoT_공공데이터포털",
    "input_name": "단기예보",
    "measurements_dict": measurements_dict,
    "data_format": "json",
    "error_handling": "aot_weather",
    "url_additional": "https://www.data.go.kr/index.do",
    "message": (
        "이 모듈은 농업용 단기예보 데이터를 제공합니다. 가장 최근 발표를 기준으로 사용자가 선택한 시간 뒤의 예보 데이터를 수집합니다. "
        "API 호출 시 공공데이터포털의 서비스키를 사용하고, JSON 응답에서 기온, 최저/최고 기온, 풍속, 풍향, 하늘상태, 습도, 강수량, 강수확률, "
        "강수형태, 신적설 데이터를 추출합니다. (API 제공은 발표시간 + 10분 이후부터 이루어집니다.)"
    ),
    "options_enabled": ["period", "pre_output"],
    "custom_options": [
        {
            "id": "api_key",
            "type": "text",
            "default_value": "",
            "required": True,
            "name": lazy_gettext("API Key"),
            "phrase": "공공데이터포털에서 발급받은 KMA API 서비스키를 입력하세요."
        },
        {
            "id": "nx",
            "type": "text",
            "default_value": "",
            "required": True,
            "name": lazy_gettext("nx 좌표"),
            "phrase": lazy_gettext("nx 값을 입력하세요 (숫자).")
        },
        {
            "id": "ny",
            "type": "text",
            "default_value": "",
            "required": True,
            "name": lazy_gettext("ny 좌표"),
            "phrase": lazy_gettext("ny 값을 입력하세요 (숫자).")
        },
        {
            "id": "forecast_offset",
            "type": "select",
            "default_value": "1",
            "options_select": [
                ["1", "1"], ["2", "2"], ["3", "3"],
                ["4", "4"], ["5", "5"], ["6", "6"],
                ["7", "7"], ["8", "8"], ["9", "9"],
                ["10", "10"], ["11", "11"], ["12", "12"]
            ],
            "name": lazy_gettext("몇 시간 뒤 예보"),
            "phrase": "몇 시간 후의 예보 데이터를 사용할지 선택하세요."
        }
    ]
}

class InputModule(AbstractInput):
    """한국 내 농업용 단기예보 데이터를 처리하는 KMA 단기예보조회 input 모듈.
    
    - 발표시간은 정각(예: 0200, 0500 등) 기준이며, API는 발표시간 + 10분부터 제공됩니다.
    - forecast_offset에 따라 target(예보) 시간이 결정되고, forecast_offset이 1~3이면 실제 저장 시점은 현재 시각(now)으로 처리합니다.
    - 측정값은 원시 숫자 데이터로 저장하며, 조회 시 문자 변환(예: 풍향, 하늘상태, 강수형태)은 별도 변환 로직을 사용합니다.
    - unique_id는 self.input_dev.unique_id를 그대로 사용하며, 안내문구는 'announce_' + unique_id 형식의 고유 ID로 외부 호출할 수 있습니다.
    """
    last_tm_processed = None

    def __init__(self, input_dev, testing=False):
        self.logger = logger
        self.api_key = None
        self.nx = None
        self.ny = None
        self.announcement = None
        super().__init__(input_dev, testing=testing, name=__name__)
 
        if not testing:
            self.setup_custom_options(INPUT_INFORMATION["custom_options"], input_dev)
            self.initialize()

    def initialize(self):
        # API key 및 forecast_offset 설정
        self.api_key = self.get_custom_option("api_key")
        self.forecast_offset = self.get_custom_option("forecast_offset")
        try:
            self.forecast_offset = int(self.forecast_offset)
        except Exception as e:
            self.logger.error(f"Forecast offset conversion error: {e}")
            self.forecast_offset = 1

        # nx, ny 좌표 설정
        nx_input = self.get_custom_option("nx")
        ny_input = self.get_custom_option("ny")
        if nx_input and ny_input:
            try:
                self.nx = int(nx_input)
                self.ny = int(ny_input)
                self.logger.info(f"User provided nx, ny: nx={self.nx}, ny={self.ny}")
            except Exception as e:
                self.logger.error(f"nx, ny conversion error: {e}")
        else:
            self.logger.error("nx, ny values are not set.")

    def value_set(self, category, value, store_dt):
        # Ensure self.return_dict is a dict
        if not isinstance(self.return_dict, dict):
            self.logger.error("return_dict is not a dict; resetting to empty dict.")
            self.return_dict = {}
        # Merge measurement metadata from measurements_dict and set the value
        meta = measurements_dict.get(category, {}).copy()
        meta["value"] = value
        self.return_dict[category] = meta

    def get_valid_base_time(self, now):
        """
        현재 시각(now)에서 10분을 뺀 시각을 기준으로, KMA의 정각 발표시간(base_time)을 결정합니다.
        KMA API와 서버 모두 한국 표준시(KST)를 사용하므로, 별도의 시간대 보정은 필요하지 않습니다.
        """
        adjusted = now - datetime.timedelta(minutes=10)
        valid_times = [200, 500, 800, 1100, 1400, 1700, 2000, 2300]
        current = adjusted.hour * 100 + adjusted.minute
        candidate = None
        for t in valid_times:
            if t <= current:
                candidate = t
        if candidate is None:
            candidate = valid_times[0]
        return f"{candidate:04d}"
    
    def get_previous_base_time(self, now):
        """
        Computes the previous valid base time and corresponding base_date based on KMA valid times.
        Valid times: [200, 500, 800, 1100, 1400, 1700, 2000, 2300].
        If the current base time is the first in the list, returns the last valid time of the previous day.
        Returns a tuple (base_date, base_time) as strings.
        """
        valid_times = [200, 500, 800, 1100, 1400, 1700, 2000, 2300]
        current_base = int(self.get_valid_base_time(now))
        previous = None
        for t in valid_times:
            if t < current_base:
                previous = t
        if previous is None:
            previous = valid_times[-1]
            base_date = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")
        else:
            base_date = now.strftime("%Y%m%d")
        return base_date, f"{previous:04d}"

    # ------------- 파일 관리 모듈 (API 응답 저장/로드/정리) -------------
    def save_api_response(self, data, base_time, page_no):
        try:
            os.makedirs(KMA_PATH, exist_ok=True)
            file_name = f"{self.input_dev.unique_id}_{base_time}.json"
            file_path = os.path.join(KMA_PATH, file_name)
            # 파일이 존재하지 않으면 빈 파일을 생성
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("")
                self.logger.info(f"Empty file created: {file_path}")
            # 빈 파일(또는 기존 파일)을 데이터로 덮어쓰기
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"API response saved to {file_path} (size: {os.path.getsize(file_path)} bytes)")
            return file_path
        except Exception as e:
            self.logger.error(f"Error saving API response to file: {e}")
            return None

    def load_api_response(self, base_time, page_no):
        """
        KMA_PATH 디렉터리에서 "{self.input_dev.unique_id}_{base_time}.json" 파일을 로드합니다.
        """
        aggregated_file_name = f"{self.input_dev.unique_id}_{base_time}.json"
        file_path = os.path.join(KMA_PATH, aggregated_file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.logger.info(f"Aggregated API response loaded from {file_path}")
            return data
        except Exception as e:
            self.logger.error(f"Error loading aggregated API response from file: {e}")
            return None

    def cleanup_old_files(self, days=7):
        """
        KMA_PATH 디렉터리 내에서 마지막 수정 시각이 현재로부터 days일 이상 지난 파일들 중,
        "announce_"로 시작하지 않는 파일들을 삭제합니다.
        """
        now = datetime.datetime.now()
        try:
            for filename in os.listdir(KMA_PATH):
                # Skip announcement files
                if filename.startswith("announce_"):
                    continue
                file_path = os.path.join(KMA_PATH, filename)
                if os.path.isfile(file_path):
                    file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                    if (now - file_mtime).days >= days:
                        os.remove(file_path)
                        self.logger.info(f"Removed old file: {file_path}")
        except Exception as e:
            self.logger.error(f"Error during cleanup of old files: {e}")

    def _fetch_api_data(self, base_date, base_time):
        numOfRows = 50
        pageNo = 1
        all_items = []
        aggregated_data = []
        totalCount = None

        aggregated_file_name = f"{self.input_dev.unique_id}_{base_time}.json"
        aggregated_file_path = os.path.join(KMA_PATH, aggregated_file_name)

        # 파일이 존재하면 로드
        if os.path.exists(aggregated_file_path):
            try:
                with open(aggregated_file_path, "r", encoding="utf-8") as f:
                    aggregated_data = json.load(f)
                self.logger.info(f"Aggregated API response loaded from {aggregated_file_path}")
                for page in aggregated_data:
                    page_items = page["response"]["body"]["items"]["item"]
                    if isinstance(page_items, dict):
                        page_items = [page_items]
                    all_items.extend(page_items)
            except Exception as e:
                self.logger.error(f"Error loading aggregated API response: {e}")
                aggregated_data = []

        # 데이터가 없는 경우 API 호출
        if not aggregated_data:
            while True:
                api_url = (
                    f"http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
                    f"?serviceKey={self.api_key}"
                    f"&numOfRows={numOfRows}&pageNo={pageNo}"
                    f"&dataType=json"
                    f"&base_date={base_date}&base_time={base_time}"
                    f"&nx={self.nx}&ny={self.ny}"
                )
                self.logger.debug(f"Fetching API data (Page {pageNo}): {api_url}")
                try:
                    response = requests.get(api_url, timeout=60)
                    response.raise_for_status()
                    # XML 오류 응답 처리
                    if response.text.strip().startswith("<"):
                        try:
                            import xml.etree.ElementTree as ET
                            root = ET.fromstring(response.text)
                            errMsg = root.find(".//errMsg").text if root.find(".//errMsg") is not None else "No errMsg"
                            self.logger.error(f"API XML error: {errMsg}")
                        except Exception as ex:
                            self.logger.error(f"XML parsing error: {ex}")
                        # XML 오류 발생 시 빈 목록 반환하여 이후 처리를 건너뜁니다.
                        return []
                    data = response.json()
                    self.logger.debug(f"KMA response JSON (Page {pageNo}): {data}")
                    aggregated_data.append(data)
                except Exception as e:
                    self.logger.error(f"API request error (Page {pageNo}): {e}")
                    break

                try:
                    page_items = data["response"]["body"]["items"]["item"]
                    if isinstance(page_items, dict):
                        page_items = [page_items]
                    all_items.extend(page_items)
                    if totalCount is None:
                        totalCount = int(data["response"]["body"]["totalCount"])
                    if pageNo * numOfRows >= totalCount:
                        break
                    pageNo += 1
                except Exception as e:
                    self.logger.error(f"API request parsing error (Page {pageNo}): {e}")
                    break

            try:
                with open(aggregated_file_path, "w", encoding="utf-8") as f:
                    json.dump(aggregated_data, f, ensure_ascii=False, indent=2)
                self.logger.info(f"Aggregated API response saved to {aggregated_file_path} (size: {os.path.getsize(aggregated_file_path)} bytes)")
            except Exception as e:
                self.logger.error(f"Error saving aggregated API response: {e}")

        self.cleanup_old_files(days=1)
        return all_items

    def _calculate_publication_time(self, all_items):
        """첫 항목의 baseDate, baseTime으로 발표시간(pub_dt)을 계산합니다."""
        pub_timestamp = all_items[0]["baseDate"] + all_items[0]["baseTime"]
        try:
            pub_dt = datetime.datetime.strptime(pub_timestamp, "%Y%m%d%H%M")
        except Exception as e:
            self.logger.error(f"Timestamp conversion error: {e}")
            pub_dt = datetime.datetime.utcnow()
        return pub_dt

    def _calculate_target_and_store_times(self, pub_dt, now):
        """
        target_dt: 발표시간 + forecast_offset (정각 기준)
        store_dt: forecast_offset이 1,2,3이면 현재 시간(now), 그렇지 않으면 target_dt
        """
        target_dt = pub_dt + datetime.timedelta(hours=self.forecast_offset)
        if self.forecast_offset in [1, 2, 3]:
            store_dt = now
        else:
            store_dt = target_dt
        return target_dt, store_dt

    def _extract_and_set_measurements(self, all_items, target_dt, store_dt):
        """
        target_dt에 해당하는 예보 데이터를 추출하여 value_set()을 호출합니다.
        필수 측정값 누락에 대비하여, measurements_dict에 정의된 모든 키를
        기본값 0.0으로 초기화합니다.
        """
        # 필수 항목에 대해 기본값 0.0으로 초기화
        self.return_dict = {key: measurements_dict[key].copy() for key in measurements_dict}
        for key in self.return_dict:
            self.return_dict[key]["value"] = 0.0
        target_timestamp = target_dt.strftime("%Y%m%d%H%M")
        found = False
        for item in all_items:
            forecast_timestamp = item.get("fcstDate", "") + item.get("fcstTime", "")
            try:
                forecast_dt = datetime.datetime.strptime(forecast_timestamp, "%Y%m%d%H%M")
            except Exception as e:
                self.logger.error(f"Forecast timestamp conversion error for item {item}: {e}")
                continue
            if forecast_dt != target_dt:
                continue
            found = True
            category = item.get("category")
            if category not in measurements_dict:
                continue
            fcst_value = item.get("fcstValue")
            if fcst_value is None:
                self.logger.warning(f"Missing forecast value for category {category} at time {forecast_timestamp}")
                continue
            try:
                if category == "SKY":
                    value = sky_code_to_text(fcst_value)
                elif category == "PTY":
                    value = pty_code_to_text(fcst_value)
                elif category == "SNO":
                    value = sno_code_to_value(fcst_value)
                else:
                    value = float(fcst_value)
            except ValueError:
                if category == "SNO":
                    self.logger.info(f"Non-numeric value for {category} interpreted as 0: {fcst_value}")
                    value = 0.0
                else:
                    self.logger.error(f"Numeric conversion failed for category {category} with value {fcst_value}. Defaulting to 0.0")
                    value = 0.0
            # value_set() 내에서 딕셔너리 업데이트 처리 (필수 키가 항상 존재함)
            self.value_set(category, value, store_dt)

        if not found:
            self.logger.error(f"No forecast data found for target time {target_dt.strftime('%Y%m%d%H%M')}")
            return False

        # 누락된 필수 카테고리에 대해 경고 로그 기록
        all_cats = set(measurements_dict.keys())
        extracted_cats = set(item.get("category") for item in all_items if (item.get("fcstDate", "") + item.get("fcstTime", "")) == target_dt.strftime("%Y%m%d%H%M"))
        missing_categories = list(all_cats - extracted_cats)
        publish_key = all_items[0].get("baseDate", "") + all_items[0].get("baseTime", "")
        if missing_categories and (not hasattr(self, "logged_missing") or publish_key not in self.logged_missing):
            self.logger.warning(f"[Publish {publish_key}] Missing forecast data for categories: {missing_categories}. 기본값 0이 적용됩니다.")
            if not hasattr(self, "logged_missing"):
                self.logged_missing = {}
            self.logged_missing[publish_key] = True
        # After processing items for target_dt, check for missing TMX, TMN, and RN1
        # --- TMN and TMX fallback logic improved ---
        # Determine publication date from the first item in all_items
        try:
            pub_date = datetime.datetime.strptime(all_items[0].get('baseDate', ''), '%Y%m%d')
        except Exception as e:
            self.logger.error(f"Error parsing publication date: {e}")
            pub_date = target_dt  # Fallback to target_dt if parsing fails
        
        # Expected forecast date for TMN and TMX is publication date + 1 day
        expected_TMN_date = target_dt.strftime('%Y%m%d')
        expected_TMX_date = target_dt.strftime('%Y%m%d')
        
        # Process TMN (desired fcstTime "0600")
        if self.return_dict.get('TMN', {}).get('value', 0.0) == 0.0:
            # Check for expected TMN data with fcstTime "0600" on expected_TMN_date
            tmn_expected = [item for item in all_items if item.get('category') == 'TMN'
                           and item.get('fcstDate') == expected_TMN_date and item.get('fcstTime') == '0600']
            if tmn_expected:
                chosen = max(tmn_expected, key=lambda x: x.get('baseTime', '0'))
                target_for_TMN = expected_TMN_date + '0600'
                try:
                    value = float(chosen.get('fcstValue'))
                    self.value_set('TMN', value, store_dt)
                    self.logger.info(f"Loaded TMN value from expected forecast time {target_for_TMN}: {value}")
                except Exception as e:
                    self.logger.error(f"Error loading TMN value from expected forecast time {target_for_TMN}: {e}")
            else:
                # Fallback: use previous day's TMN data (pub_date - 1 day)
                prev_date = (pub_date - datetime.timedelta(days=1)).strftime('%Y%m%d')
                target_for_TMN = prev_date + '0600'
                tmn_prev = [item for item in all_items if item.get('category') == 'TMN'
                            and item.get('fcstDate') == prev_date and item.get('fcstTime') == '0600']
                if tmn_prev:
                    chosen = max(tmn_prev, key=lambda x: x.get('baseTime', '0'))
                    try:
                        value = float(chosen.get('fcstValue'))
                        self.value_set('TMN', value, store_dt)
                        self.logger.info(f"Loaded TMN value from fallback forecast time {target_for_TMN}: {value}")
                    except Exception as e:
                        self.logger.error(f"Error loading TMN value from fallback forecast time {target_for_TMN}: {e}")
                else:
                    self.logger.warning(f"No TMN data available for expected fcstTime 0600 on {expected_TMN_date} or fallback.")
        
        # Process TMX (desired fcstTime "1500")
        if self.return_dict.get('TMX', {}).get('value', 0.0) == 0.0:
            # Check for expected TMX data with fcstTime "1500" on expected_TMX_date
            tmx_expected = [item for item in all_items if item.get('category') == 'TMX'
                           and item.get('fcstDate') == expected_TMX_date and item.get('fcstTime') == '1500']
            if tmx_expected:
                chosen = max(tmx_expected, key=lambda x: x.get('baseTime', '0'))
                target_for_TMX = expected_TMX_date + '1500'
                try:
                    value = float(chosen.get('fcstValue'))
                    self.value_set('TMX', value, store_dt)
                    self.logger.info(f"Loaded TMX value from expected forecast time {target_for_TMX}: {value}")
                except Exception as e:
                    self.logger.error(f"Error loading TMX value from expected forecast time {target_for_TMX}: {e}")
            else:
                # Fallback: use previous day's TMX data (pub_date - 1 day)
                prev_date = (pub_date - datetime.timedelta(days=1)).strftime('%Y%m%d')
                target_for_TMX = prev_date + '1500'
                tmx_prev = [item for item in all_items if item.get('category') == 'TMX'
                            and item.get('fcstDate') == prev_date and item.get('fcstTime') == '1500']
                if tmx_prev:
                    chosen = max(tmx_prev, key=lambda x: x.get('baseTime', '0'))
                    try:
                        value = float(chosen.get('fcstValue'))
                        self.value_set('TMX', value, store_dt)
                        self.logger.info(f"Loaded TMX value from fallback forecast time {target_for_TMX}: {value}")
                    except Exception as e:
                        self.logger.error(f"Error loading TMX value from fallback forecast time {target_for_TMX}: {e}")
                else:
                    self.logger.warning(f"No TMX data available for expected fcstTime 1500 on {expected_TMX_date} or fallback.")
        # --- TMN and TMX fallback logic end ---
        return True
    
    def generate_forecast_json(self, forecast_hours=None):
        # 1. 현재 시각을 기준으로 now 값을 구합니다.
        now = datetime.datetime.now()
        now_rounded = now.replace(minute=0, second=0, microsecond=0)
        
        # 2. 파일 목록 로드: KMA_PATH 디렉터리에서 해당 unique_id로 시작하는 모든 JSON 파일을 수정 시간 기준 오름차순(가장 오래된 파일부터) 정렬
        file_list = [f for f in os.listdir(KMA_PATH) if f.startswith(self.input_dev.unique_id + "_") and f.endswith(".json")]
        if not file_list:
            self.logger.error("No API response files found in KMA_PATH.")
            return {}
        file_list_sorted = sorted(file_list, key=lambda f: os.path.getmtime(os.path.join(KMA_PATH, f)))
        self.logger.info(f"Forecast API response files found: {file_list_sorted}")
        
        # 3. 각 파일의 데이터를 로드하여 사전에 저장
        file_data_dict = {}
        for filename in file_list_sorted:
            filepath = os.path.join(KMA_PATH, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = []
                for page in data:
                    page_items = page["response"]["body"]["items"]["item"]
                    if isinstance(page_items, dict):
                        page_items = [page_items]
                    items.extend(page_items)
                file_data_dict[filename] = items
            except Exception as e:
                self.logger.error(f"Error loading file {filename}: {e}")
        
        # 4. 최신 파일에서 발표시간(pub_dt) 계산
        latest_file = file_list_sorted[-1]
        latest_items = file_data_dict.get(latest_file, [])
        if latest_items:
            pub_dt = self._calculate_publication_time(latest_items)
        else:
            all_items_tmp = []
            for items in file_data_dict.values():
                all_items_tmp.extend(items)
            pub_dt = self._calculate_publication_time(all_items_tmp)
        
        # --- 일별 TMX/TMN 최신값 추출 (TMX는 fcstTime "1500", TMN은 "0600"만 대상) ---
        daily_extremes = {}
        for filename in file_list_sorted:
            items = file_data_dict.get(filename, [])
            for item in items:
                fcstDate = item.get("fcstDate", "").strip()
                category = item.get("category")
                fcstTime = item.get("fcstTime", "").strip()
                if category == "TMX" and fcstTime != "1500":
                    continue
                if category == "TMN" and fcstTime != "0600":
                    continue
                if fcstDate not in daily_extremes:
                    daily_extremes[fcstDate] = {}
                current_entry = daily_extremes[fcstDate]
                # 각각의 카테고리에 대해 해당 fcstTime 조건에 맞는 값만 업데이트 (기존 값과 baseTime 비교)
                existing_baseTime = current_entry.get(category + "_baseTime", "0000")
                current_baseTime = item.get("baseTime", "0000")
                if current_baseTime > existing_baseTime:
                    try:
                        current_entry[category] = float(item.get("fcstValue"))
                    except Exception:
                        current_entry[category] = 0.0
                    current_entry[category + "_baseTime"] = current_baseTime
                daily_extremes[fcstDate] = current_entry
        self.logger.info(f"Daily extremes for TMX/TMN: {daily_extremes}")
        # --- 끝 ---
        
        # 5. forecast_offsets 설정 (예: -25 ~ 49)
        forecast_offsets = list(range(-25, 50))
        forecasts = {}
        now = datetime.datetime.now()
        now_rounded = now.replace(minute=0, second=0, microsecond=0)
        
        for offset in forecast_offsets:
            target_dt = now_rounded + datetime.timedelta(hours=offset)
            target_timestamp = target_dt.strftime("%Y%m%d%H%M")
            forecast_data = {}
            for cat in measurements_dict.keys():
                candidate = None
                candidate_diff = None
                for filename in file_list_sorted:
                    items = file_data_dict.get(filename, [])
                    for item in items:
                        if item.get("category") != cat:
                            continue
                        fcst_date = item.get("fcstDate", "").strip()
                        fcst_time = item.get("fcstTime", "").strip()
                        key = fcst_date + fcst_time
                        if len(key) != 12:
                            continue
                        try:
                            fcst_dt = datetime.datetime.strptime(key, "%Y%m%d%H%M")
                        except Exception as e:
                            self.logger.error(f"Datetime parsing error for key {key}: {e}")
                            continue
                        diff = abs((fcst_dt - target_dt).total_seconds())
                        threshold = 3600  # 1시간 이내
                        if diff <= threshold:
                            if candidate is None or diff < candidate_diff:
                                candidate = item
                                candidate_diff = diff
                if candidate is not None:
                    try:
                        raw_val = candidate.get("fcstValue")
                        if cat == "SNO":
                            val_str = str(raw_val).strip()
                            if "적설없음" in val_str:
                                forecast_data[cat] = 0.0
                            else:
                                import re
                                cleaned = re.sub(r"[^\d\.]", "", val_str)
                                forecast_data[cat] = float(cleaned) if cleaned else 0.0
                        elif cat == "PCP":
                            val_str = str(raw_val).strip()
                            if "강수없음" in val_str:
                                forecast_data[cat] = 0.0
                            else:
                                import re
                                cleaned = re.sub(r"[^\d\.]", "", val_str)
                                forecast_data[cat] = float(cleaned) if cleaned else 0.0
                        elif cat == "SKY":
                            forecast_data[cat] = sky_code_to_text(raw_val)
                        elif cat == "PTY":
                            forecast_data[cat] = pty_code_to_text(raw_val)
                        else:
                            forecast_data[cat] = float(raw_val)
                    except Exception as e:
                        self.logger.error(f"Error processing {cat} at {target_timestamp}: {e}")
            # --- TMX/TMN 오버라이드: 같은 날짜이면 일별 최신 TMX, TMN 값 사용 ---
            target_date = target_dt.strftime("%Y%m%d")
            if target_date in daily_extremes:
                daily = daily_extremes[target_date]
                if "TMX" in daily:
                    forecast_data["TMX"] = daily["TMX"]
                if "TMN" in daily:
                    forecast_data["TMN"] = daily["TMN"]
            forecasts[str(offset)] = forecast_data
        
        json_obj = {
            "now": now_rounded.strftime("%Y%m%d%H%M"),
            "pub_dt": pub_dt.strftime("%Y%m%d%H%M"),
            "forecasts": forecasts,
            "units": {key: measurements_dict[key]["unit"] for key in measurements_dict}
        }
        
        try:
            os.makedirs(PATH_JSON, exist_ok=True)
            file_name = "forecast.json"
            file_path = os.path.join(PATH_JSON, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(json_obj, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Forecast JSON successfully saved to {file_path} (size: {os.path.getsize(file_path)} bytes)")
        except Exception as e:
            self.logger.error(f"Error saving forecast JSON: {e}")
        
        return json_obj

    def get_forecast(self):
        """
        /forecast/<unique_id> 엔드포인트 호출 시, 이 함수가 호출되어 JSON 객체를 반환합니다.
        """
        return self.generate_forecast_json()

    def get_measurement(self):
        """
        전체 프로세스:
          1. 현재 시각 기반으로 base_date, base_time 결정 (현재 시각에서 10분 전 기준)
          2. KMA API를 다중 페이지 호출하여 모든 예보 데이터를 수집 (파일 저장/로드 활용)
          3. 첫 항목의 발표시간(pub_dt) 계산 후, forecast_offset을 더해 target_dt(예보시간) 계산
             - forecast_offset이 1,2,3인 경우 실제 저장 시점(store_dt)은 현재 시각(now)으로 설정
          4. target_dt에 해당하는 예보 데이터를 추출하여 value_set() 호출 (SKY, PTY 포함)
          5. 동일 발표 데이터의 중복 저장을 방지한 후, InfluxDB에 측정값 저장 (unique_id: self.input_dev.unique_id)
        """
        if not (self.api_key and self.nx and self.ny):
            self.logger.error("API key and region settings (nx, ny) must be completed.")
            return

        now = datetime.datetime.now() - datetime.timedelta(hours=24)
        base_date = now.strftime("%Y%m%d")
        base_time = self.get_valid_base_time(now)
        self.logger.info(f"Using base_date {base_date} and base_time {base_time}")

        all_items = self._fetch_api_data(base_date, base_time)
        if not all_items:
            self.logger.error("No valid data in API response.")
            return

        pub_dt = self._calculate_publication_time(all_items)
        target_dt, store_dt = self._calculate_target_and_store_times(pub_dt, now)
        target_timestamp = target_dt.strftime("%Y%m%d%H%M")

        if not self._extract_and_set_measurements(all_items, target_dt, store_dt):
            return

        # Check if both target_timestamp and publication time (pub_dt) are unchanged.
        # If self.last_pub_dt does not exist yet, treat it as different.
        if (self.last_tm_processed == target_timestamp and 
            hasattr(self, "last_pub_dt") and self.last_pub_dt == pub_dt):
            self.logger.info(f"TM={target_timestamp} with pub_dt {pub_dt.strftime('%Y%m%d%H%M')} already processed. Skipping measurement update, but updating announcement JSON.")
            self.generate_forecast_json()  # JSON 파일 갱신 강제 호출
            return self.return_dict

        # Otherwise, update the stored last processed target and publication time.
        self.last_tm_processed = target_timestamp
        self.last_pub_dt = pub_dt

        self.last_tm_processed = target_timestamp

        # Add pub_time and forecast_time tags to each measurement using the calculated publication and target times
        for key, measurement in self.return_dict.items():
            measurement["pub_time"] = pub_dt.strftime("%Y%m%d%H%M")
            measurement["forecast_time"] = target_dt.strftime("%Y%m%d%H%M")

        return self.return_dict