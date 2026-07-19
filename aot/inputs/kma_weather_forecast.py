# coding=utf-8
#
#  This software is a derivative version based on the open-source Mycodo
#  project (© Kyle T. Gabriel), modified to suit the goals of the AoT project.
#  This file has been modified by AoT from the original Mycodo version.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is distributed under the GNU GPLv3 license.
#  The original copyright and license terms are stated below.
#
#  --------------------------------------------------------------
#  Original file information:
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
#  2025-11-03

import datetime
import json
import logging
import math
import os
import time
from typing import List, Optional, Tuple
from urllib.parse import unquote

import requests
from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
from aot.config import KMA_PATH, PATH_JSON
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.device_tz import get_device_tz

logger = logging.getLogger(__name__)

# Short-term agricultural forecast measurement configuration
# (stores raw data; text conversion is applied later on lookup)
measurements_dict = {
    'TMP': {'name': lazy_gettext('Temperature'), 'measurement': 'temperature', 'unit': 'C'},
    'TMN': {'name': lazy_gettext('Min Temperature'), 'measurement': 'temperature', 'unit': 'C'},
    'TMX': {'name': lazy_gettext('Max Temperature'), 'measurement': 'temperature', 'unit': 'C'},
    'REH': {'name': lazy_gettext('Humidity'), 'measurement': 'humidity', 'unit': 'percent'},
    'WSD': {'name': lazy_gettext('Wind Speed'), 'measurement': 'speed', 'unit': 'm_s'},
    'VEC': {'name': lazy_gettext('Wind Direction'), 'measurement': 'direction', 'unit': 'bearing'},
    'SKY': {'name': lazy_gettext('Sky Condition'), 'measurement': 'sky_condition', 'unit': 'none'},
    'RN1': {'name': lazy_gettext('Precipitation'), 'measurement': 'precipitation', 'unit': 'mm'},
    'POP': {'name': lazy_gettext('Precipitation Probability'), 'measurement': 'precipitation', 'unit': 'percent'},
    'PTY': {'name': lazy_gettext('Precipitation Type'), 'measurement': 'precipitation', 'unit': 'none'},
    'SNO': {'name': lazy_gettext('Fresh Snowfall'), 'measurement': 'snowfall', 'unit': 'cm'}
}

def wind_direction_to_korean(vec):
    """
    Convert wind direction (0deg to 360deg) into Korean text.
    e.g. 0-45 -> North, 45-90 -> Northeast, 90-135 -> East,
       135-180 -> Southeast, 180-225 -> South, 225-270 -> Southwest,
       270-315 -> West, 315-360 -> Northwest.
    The returned strings stay Korean because they are stored measurement values.
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
    SKY code conversion: 1 -> Clear, 3 -> Mostly Cloudy, 4 -> Overcast.
    Returned strings stay Korean because they are stored measurement values.
    """
    mapping = {1: "맑음", 3: "구름많음", 4: "흐림"}
    try:
        result = mapping.get(int(code), str(code))
        return fix_korean(result)
    except Exception:
        return fix_korean(str(code))

def pty_code_to_text(code):
    """
    PTY code conversion (short-term basis):
      0 -> None, 1 -> Rain, 2 -> Rain/Snow, 3 -> Snow, 4 -> Shower.
    Returned strings stay Korean because they are stored measurement values.
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
    SNO code conversion:
      - Returns 0.0 for "적설없음" (or the equivalent string when encoding is broken).
      - Otherwise converts to a numeric value and returns it.
    """
    mapping = {"적설없음": 0.0}
    try:
        # Use fix_korean to repair encoding issues, then convert to string
        code_str = fix_korean(str(code)).strip()
        # Return the mapped value if present, otherwise try numeric conversion
        return mapping.get(code_str, float(code_str))
    except Exception:
        return 0.0

INPUT_INFORMATION = {
    "input_name_unique": "KMA_forecast",
    "input_manufacturer": "KMA",
    "input_name": lazy_gettext("KMA Short-term Forecast"),
    "measurements_dict": measurements_dict,
    "data_format": "json",
    "error_handling": "kma_forecast",
    "url_additional": "https://www.data.go.kr/index.do",
    "message": lazy_gettext(
        "This module provides short-term agricultural forecast data. Based on the most recent announcement, "
        "it collects forecast data for the time offset selected by the user. The API call uses a service key "
        "from the Public Data Portal, and extracts temperature, min/max temperature, wind speed, wind direction, "
        "sky condition, humidity, precipitation, precipitation probability, precipitation type, and fresh snowfall "
        "from the JSON response. (Data is available from 10 minutes after the announcement time.)"
    ),
    "options_enabled": ["period", "pre_output"],
    "custom_options": [
        {
            "id": "api_key",
            "type": "text",
            "default_value": "",
            "required": True,
            "name": lazy_gettext("API Key"),
            "phrase": lazy_gettext("Enter the KMA API service key issued by the Public Data Portal.")
        },
        {
            "id": "nx",
            "type": "text",
            "default_value": "",
            "required": True,
            "name": lazy_gettext("nx Coordinate"),
            "phrase": lazy_gettext("Enter the nx value (number).")
        },
        {
            "id": "ny",
            "type": "text",
            "default_value": "",
            "required": True,
            "name": lazy_gettext("ny Coordinate"),
            "phrase": lazy_gettext("Enter the ny value (number).")
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
            "name": lazy_gettext("Forecast Hours Ahead"),
            "phrase": lazy_gettext("Select how many hours ahead of forecast data to use.")
        },
        {
            "id": "api_timeout",
            "type": "integer",
            "default_value": 60,
            "required": False,
            "constraints_pass": constraints_pass_positive_value,
            "name": lazy_gettext("API Timeout (sec)"),
            "phrase": lazy_gettext("Set the API response timeout (default 60 sec).")
        },
        {
            "id": "api_retry_count",
            "type": "integer",
            "default_value": 3,
            "required": False,
            "constraints_pass": constraints_pass_positive_value,
            "name": lazy_gettext("API Retry Count"),
            "phrase": lazy_gettext("Set how many times to retry the same announcement time on an HTTP error.")
        },
        {
            "id": "api_retry_delay",
            "type": "float",
            "default_value": 3.0,
            "required": False,
            "constraints_pass": constraints_pass_positive_value,
            "name": lazy_gettext("API Retry Interval (sec)"),
            "phrase": lazy_gettext("Time to wait between retries (default 3 sec).")
        }
    ]
}

class InputModule(AbstractInput):
    """KMA short-term weather forecast driver for agricultural data.

    Produces temperature (C), humidity (percent), wind speed (m/s), wind direction (bearing),
    sky condition, precipitation (mm), precipitation probability, precipitation type,
    and snowfall (cm) forecasts.

    @phase active
    @dependency AbstractInput
    """
    last_tm_processed = None

    def __init__(self, input_dev, testing=False):
        self.logger = logger
        self.api_key = None
        self.nx = None
        self.ny = None
        self.announcement = None
        self.api_timeout = 60
        self.api_retry_count = 3
        self.api_retry_delay = 3.0
        # KMA interprets base_date/base_time in KST; use the device's
        # location-derived timezone so requests are correct on any host.
        self.current_base_date = datetime.datetime.now(
            get_device_tz(input_dev)).strftime("%Y%m%d")
        super().__init__(input_dev, testing=testing, name=__name__)
 
        if not testing:
            self.setup_custom_options(INPUT_INFORMATION["custom_options"], input_dev)
            self.initialize()

    def initialize(self):
        # Configure API key and forecast_offset
        self.api_key = self.get_custom_option("api_key")
        self.forecast_offset = self.get_custom_option("forecast_offset")
        try:
            self.forecast_offset = int(self.forecast_offset)
        except Exception as e:
            self.logger.error(f"Forecast offset conversion error: {e}")
            self.forecast_offset = 1

        # Configure nx, ny coordinates
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

        # Ensure KMA_PATH exists
        if not os.path.exists(KMA_PATH):
            try:
                os.makedirs(KMA_PATH, exist_ok=True)
                self.logger.info(f"Created KMA_PATH directory: {KMA_PATH}")
            except Exception as e:
                self.logger.error(f"Error creating KMA_PATH directory {KMA_PATH}: {e}")

        try:
            timeout_opt = self.get_custom_option("api_timeout")
            if timeout_opt is not None and timeout_opt != "":
                self.api_timeout = max(1, int(timeout_opt))
        except Exception as e:
            self.logger.warning(f"API timeout conversion error: {e}")
            self.api_timeout = 60

        try:
            retry_opt = self.get_custom_option("api_retry_count")
            if retry_opt not in [None, ""]:
                self.api_retry_count = max(1, int(retry_opt))
        except Exception as e:
            self.logger.warning(f"API retry count conversion error: {e}")
            self.api_retry_count = 3

        try:
            delay_opt = self.get_custom_option("api_retry_delay")
            if delay_opt not in [None, ""]:
                self.api_retry_delay = max(0.0, float(delay_opt))
        except Exception as e:
            self.logger.warning(f"API retry delay conversion error: {e}")
            self.api_retry_delay = 3.0

    def value_set(self, category, value, store_dt):
        # Ensure self.return_dict is a dict
        if not isinstance(self.return_dict, dict):
            self.logger.error("return_dict is not a dict; resetting to empty dict.")
            self.return_dict = {}
        # Merge measurement metadata from measurements_dict and set the value
        meta = measurements_dict.get(category, {}).copy()
        meta["value"] = value
        meta["timestamp_utc"] = store_dt
        meta["timestamp"] = store_dt
        self.return_dict[category] = meta

    def get_valid_base_time(self, now: datetime.datetime) -> Tuple[str, str]:
        """
        Return the most recent announcement time (base_date, base_time) relative to now.
        Announcements occur on the hour (0200, 0500, ...) and data is published 10 minutes after.
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
            base_date = (adjusted - datetime.timedelta(days=1)).strftime("%Y%m%d")
        else:
            base_date = adjusted.strftime("%Y%m%d")
        return base_date, f"{candidate:04d}"

    def get_previous_base_time(self, base_date: str, base_time: str) -> Tuple[str, str]:
        """
        Return the announcement time immediately before the given one.
        """
        valid_times = [200, 500, 800, 1100, 1400, 1700, 2000, 2300]
        current_base = int(base_time)
        previous = None
        for t in valid_times:
            if t < current_base:
                previous = t
        if previous is None:
            previous = valid_times[-1]
            base_date_dt = datetime.datetime.strptime(base_date, "%Y%m%d") - datetime.timedelta(days=1)
        else:
            base_date_dt = datetime.datetime.strptime(base_date, "%Y%m%d")
        return base_date_dt.strftime("%Y%m%d"), f"{previous:04d}"

    # ------------- File management module (API response save/load/cleanup) -------------
    # (Removed unused save_api_response and load_api_response methods)

    def cleanup_old_files(self, days=7):
        """
        Delete old files in the KMA_PATH directory.
        Keep the most recent `days` days of data, but skip announce_ files.
        """
        if not os.path.isdir(KMA_PATH):
            return
        # Host-local time on purpose: compared against file mtimes from
        # os.path.getmtime via fromtimestamp (both host-local, consistent).
        now = datetime.datetime.now()
        try:
            for filename in os.listdir(KMA_PATH):
                # Skip announcement files
                if filename.startswith("announce_"):
                    continue
                file_path = os.path.join(KMA_PATH, filename)
                if os.path.isfile(file_path):
                    file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                    if (now - file_mtime).days > days:
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

        aggregated_file_name = f"{self.input_dev.unique_id}_{self.current_base_date}_{base_time}.json"
        aggregated_file_path = os.path.join(KMA_PATH, aggregated_file_name)

        # Load if the file exists
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

        # Call the API if there is no data
        if not aggregated_data:
            retry_attempt = 0
            while True:
                params = {
                    "serviceKey": unquote(self.api_key),
                    "numOfRows": numOfRows,
                    "pageNo": pageNo,
                    "dataType": "JSON",
                    "base_date": base_date,
                    "base_time": base_time,
                    "nx": self.nx,
                    "ny": self.ny,
                }
                api_root = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
                self.logger.debug(
                    f"Fetching API data (Page {pageNo}) with timeout {self.api_timeout}s: {api_root} params={params}"
                )
                try:
                    response = requests.get(api_root, params=params, timeout=self.api_timeout)
                    response.raise_for_status()
                    # Handle XML error responses
                    if response.text.strip().startswith("<"):
                        try:
                            import xml.etree.ElementTree as ET
                            root = ET.fromstring(response.text)
                            errMsg = root.find(".//errMsg").text if root.find(".//errMsg") is not None else "No errMsg"
                            self.logger.error(f"API XML error: {errMsg}")
                        except Exception as ex:
                            self.logger.error(f"XML parsing error: {ex}")
                        # On XML error, return an empty list to skip further processing.
                        return []
                    data = response.json()
                    self.logger.debug(f"KMA response JSON (Page {pageNo}): {data}")
                    aggregated_data.append(data)
                    retry_attempt = 0  # reset retry counter on success
                except Exception as e:
                    self.logger.error(f"API request error (Page {pageNo}): {e}")
                    retry_attempt += 1
                    if retry_attempt >= self.api_retry_count:
                        break
                    if self.api_retry_delay > 0:
                        time.sleep(self.api_retry_delay)
                    continue

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

            if aggregated_data:
                try:
                    with open(aggregated_file_path, "w", encoding="utf-8") as f:
                        json.dump(aggregated_data, f, ensure_ascii=False, indent=2)
                    self.logger.info(f"Aggregated API response saved to {aggregated_file_path} (size: {os.path.getsize(aggregated_file_path)} bytes)")
                except Exception as e:
                    self.logger.error(f"Error saving aggregated API response: {e}")
            else:
                self.logger.warning(f"No data fetched for {base_date} {base_time}; existing cache retained.")

        # [Improved] Increase retention from 1 day to 7 days for better history
        self.cleanup_old_files(days=7)
        return all_items

    def _calculate_publication_time(self, all_items):
        """Calculate the announcement time (pub_dt) from the first item's baseDate and baseTime."""
        pub_timestamp = all_items[0]["baseDate"] + all_items[0]["baseTime"]
        try:
            pub_dt = datetime.datetime.strptime(pub_timestamp, "%Y%m%d%H%M")
        except Exception as e:
            self.logger.error(f"Timestamp conversion error: {e}")
            # pub_dt is compared against KST forecast timestamps, so the
            # fallback must also be device-local (KST), not host time.
            pub_dt = datetime.datetime.now(
                get_device_tz(self.input_dev)).replace(tzinfo=None)
        return pub_dt

    def _calculate_target_and_store_times(self, pub_dt, now):
        """
        target_dt: announcement time + forecast_offset (on the hour)
        store_dt: now if forecast_offset is 1, 2, or 3; otherwise target_dt
        """
        target_dt = pub_dt + datetime.timedelta(hours=self.forecast_offset)
        if self.forecast_offset in [1, 2, 3]:
            store_dt = now
        else:
            store_dt = target_dt
        return target_dt, store_dt

    def _extract_and_set_measurements(self, all_items, target_dt, store_dt):
        """
        Extract forecast data for target_dt and call value_set().
        To guard against missing required measurements, initialize every key
        defined in measurements_dict to a default of 0.0.
        """
        # Initialize required items to a default of 0.0
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
            # value_set() handles the dict update (required keys always exist)
            self.value_set(category, value, store_dt)

        if not found:
            self.logger.error(f"No forecast data found for target time {target_dt.strftime('%Y%m%d%H%M')}")
            return False

        # Log a warning for any missing required categories
        all_cats = set(measurements_dict.keys())
        extracted_cats = set(item.get("category") for item in all_items if (item.get("fcstDate", "") + item.get("fcstTime", "")) == target_dt.strftime("%Y%m%d%H%M"))
        missing_categories = list(all_cats - extracted_cats)
        publish_key = all_items[0].get("baseDate", "") + all_items[0].get("baseTime", "")
        if missing_categories and (not hasattr(self, "logged_missing") or publish_key not in self.logged_missing):
            self.logger.warning(f"[Publish {publish_key}] Missing forecast data for categories: {missing_categories}. A default of 0 is applied.")
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
        # 1. Determine `now` in the device's local timezone (KST), since all
        # forecast timestamps (fcstDate/fcstTime) from KMA are in KST.
        device_tz = get_device_tz(self.input_dev)
        now = datetime.datetime.now(device_tz).replace(tzinfo=None)
        now_rounded = now.replace(minute=0, second=0, microsecond=0)

        # 2. Load the file list: all JSON files in KMA_PATH starting with this unique_id, sorted ascending by mtime (oldest first)
        file_list = [f for f in os.listdir(KMA_PATH)
                     if f.startswith(self.input_dev.unique_id + "_") and f.endswith(".json")]
        if not file_list:
            self.logger.error(f"No API response files found in KMA_PATH: {KMA_PATH}")
            return {}
        # [Improved] Sort by filename to ensure consistency across base dates/times
        file_list_sorted = sorted(file_list)
        self.logger.info(f"Forecast API response files found: {file_list_sorted}")
        
        # 3. Load each file's data and store it in a dict
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
        
        # 4. Calculate the announcement time (pub_dt) from the latest file
        latest_file = file_list_sorted[-1]
        latest_items = file_data_dict.get(latest_file, [])
        if latest_items:
            pub_dt = self._calculate_publication_time(latest_items)
        else:
            all_items_tmp = []
            for items in file_data_dict.values():
                all_items_tmp.extend(items)
            pub_dt = self._calculate_publication_time(all_items_tmp)
        
        # --- Extract latest daily TMX/TMN values ---
        daily_extremes = {}
        for filename in file_list_sorted:
            items = file_data_dict.get(filename, [])
            for item in items:
                fcstDate = item.get("fcstDate", "").strip()
                category = item.get("category")
                if category not in ("TMX", "TMN"):
                    continue
                if fcstDate not in daily_extremes:
                    daily_extremes[fcstDate] = {}
                current_entry = daily_extremes[fcstDate]
                # For each category, only update the value matching the fcstTime condition (compare baseTime with the existing value)
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
        # --- end ---

        # 5. Configure forecast_offsets (-24 to 48 hours)
        forecast_offsets = list(range(-24, 49))
        forecasts = {}
        now = datetime.datetime.now(device_tz).replace(tzinfo=None)
        now_rounded = now.replace(minute=0, second=0, microsecond=0)
        
        last_known = {}
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
                        threshold = 5400  # allow up to 90 minutes
                        if diff <= threshold:
                            # [Improved] Use <= to Prefer NEWER files (since files are sorted by mtime)
                            # If diff matches (e.g. 0), we want the latest file's data.
                            if candidate is None or diff <= candidate_diff:
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
                        last_known[cat] = forecast_data[cat]
                    except Exception as e:
                        self.logger.error(f"Error processing {cat} at {target_timestamp}: {e}")
                elif cat in last_known:
                    forecast_data[cat] = last_known[cat]
            # --- TMX/TMN override: for the same date, use the latest daily TMX, TMN values ---
            target_date = target_dt.strftime("%Y%m%d")
            if target_date in daily_extremes:
                daily = daily_extremes[target_date]
                if "TMX" in daily:
                    forecast_data["TMX"] = daily["TMX"]
                    last_known["TMX"] = daily["TMX"]
                if "TMN" in daily:
                    forecast_data["TMN"] = daily["TMN"]
                    last_known["TMN"] = daily["TMN"]
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
        Called when the /forecast/<unique_id> endpoint is hit; returns a JSON object.
        """
        return self.generate_forecast_json()

    def get_measurement(self):
        """
        Full process:
          1. Determine base_date, base_time from the current time (10 minutes before now).
          2. Call the KMA API across multiple pages to collect all forecast data (using file save/load).
          3. Calculate the announcement time (pub_dt) from the first item, then add forecast_offset to get target_dt (forecast time).
             - For forecast_offset of 1, 2, or 3, set the actual store time (store_dt) to now.
          4. Extract forecast data for target_dt and call value_set() (including SKY, PTY).
          5. Prevent duplicate storage of the same announcement data, then store measurements in InfluxDB (unique_id: self.input_dev.unique_id).
        """
        if not (self.api_key and self.nx and self.ny):
            self.logger.error("API key and region settings (nx, ny) must be completed.")
            return

        # KMA interprets base_date/base_time in KST; compute `now` in the
        # device's location-derived timezone so requests are correct on any host.
        device_tz = get_device_tz(self.input_dev)
        now = datetime.datetime.now(device_tz).replace(tzinfo=None)
        base_date, base_time = self.get_valid_base_time(now)
        self.logger.info(f"Trying base_date {base_date} and base_time {base_time}")

        attempts = 0
        all_items: List[dict] = []
        self.current_base_date = base_date
        while attempts < 3:
            all_items = self._fetch_api_data(base_date, base_time)
            if all_items:
                break
            attempts += 1
            base_date, base_time = self.get_previous_base_time(base_date, base_time)
            self.current_base_date = base_date
            self.logger.warning(f"Retrying with previous base time: {base_date} {base_time} (attempt {attempts})")

        if not all_items:
            self.logger.error("No valid data in API response after retries. Attempting to refresh JSON with existing cache.")
            self.generate_forecast_json()  # Try to update JSON even if fetch fails
            return

        pub_dt = self._calculate_publication_time(all_items)
        target_dt, store_dt = self._calculate_target_and_store_times(pub_dt, now)
        target_timestamp = target_dt.strftime("%Y%m%d%H%M")

        # store_dt is naive device-local (KST); convert to tz-aware UTC for storage.
        store_dt = device_tz.localize(store_dt).astimezone(datetime.timezone.utc)

        if not self._extract_and_set_measurements(all_items, target_dt, store_dt):
            return

        # Check if both target_timestamp and publication time (pub_dt) are unchanged.
        # If self.last_pub_dt does not exist yet, treat it as different.
        if (self.last_tm_processed == target_timestamp and 
            hasattr(self, "last_pub_dt") and self.last_pub_dt == pub_dt):
            self.logger.info(f"TM={target_timestamp} with pub_dt {pub_dt.strftime('%Y%m%d%H%M')} already processed. Skipping measurement update, but updating announcement JSON.")
            self.generate_forecast_json()  # Force a JSON file refresh
            return self.return_dict

        # Otherwise, update the stored last processed target and publication time.
        self.last_tm_processed = target_timestamp
        self.last_pub_dt = pub_dt

        self.last_tm_processed = target_timestamp

        # Add pub_time and forecast_time tags to each measurement using the calculated publication and target times
        for key, measurement in self.return_dict.items():
            measurement["pub_time"] = pub_dt.strftime("%Y%m%d%H%M")
            measurement["forecast_time"] = target_dt.strftime("%Y%m%d%H%M")
            if measurement.get("timestamp_utc") is None:
                measurement["timestamp_utc"] = store_dt

        # Generate/update forecast JSON so widgets can render newest forecasts.
        try:
            self.generate_forecast_json()
        except Exception as e:
            self.logger.warning(f"Forecast JSON generation failed: {e}")

        return self.return_dict
