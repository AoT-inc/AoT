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
    4: {'measurement': 'speed', 'unit': 'm_s', 'name': lazy_gettext('Wind Speed')},
    5: {'measurement': 'direction', 'unit': 'bearing', 'name': lazy_gettext('Wind Direction')}
}

INPUT_INFORMATION = {
    'input_name_unique': 'KMA_weather_stn',
    'input_manufacturer': 'KMA',
    'input_name': lazy_gettext('KMA Station Data'),
    'input_name_short': lazy_gettext('KMA Station'),
    'measurements_name': lazy_gettext('Humidity/Temperature/Pressure/Wind Speed/Wind Direction'),
    'measurements_dict': measurements_dict,
    'url_additional': 'https://apihub.kma.go.kr',
    'measurements_rescale': False,

    'message': lazy_gettext('Issue a free API key from the KMA API Hub and enter the STN of the nearest observation station.'
               ' Note: the free API allows 20000 calls per day, and each call returns data for a single observation station.'),

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
    """KMA API driver for surface weather station observation data.

    Produces temperature (C), humidity (percent), pressure (Pa), wind speed (m/s),
    wind direction (bearing), and calculated dew point (C).

    @phase active
    @dependency AbstractInput
    """

    # NEW: variable to record the last processed TM (on the hour)
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
        Initialization logic (may be left empty if nothing is needed).
        last_tm_processed could be explicitly initialized to None here, but
        it is already declared as a class variable, so this can be omitted.
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
            self.logger.error("Please enter the API key and station info (stn).")
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
                WD = float(cols[2])   # wind direction
                WS = float(cols[3])   # wind speed
                PS = float(cols[9])   # sea-level pressure
                TA = float(cols[11])  # temperature
                HM = float(cols[13])  # relative humidity

                temperature = TA
                humidity = HM
                pressure = PS
                wind_speed = WS
                wind_deg = WD

                valid_data_found = True
                break  # Process only one valid data line
            except (ValueError, IndexError) as e:
                self.logger.error(f"Parsing error (numeric conversion failure, etc.): {e}")
                continue

        if not valid_data_found:
            self.logger.error("No valid data found in KMA response.")
            return

        # Pressure: convert hPa -> Pa
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
        # (If the system is in KST, simply parse and set microsecond to 0 to match the "YYYY-MM-DD HH:MM:SS.000" format)
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
            duration_sec = 3600  # only query data within the last 1 hour
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
    