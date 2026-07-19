# coding=utf-8
#
# Copyright 2014 Matt Heitzenroder
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Python wrapper exposes the capabilities of the AOSONG AM2315 humidity
# and temperature sensor.
# The datasheet for the device can be found here:
# http://www.adafruit.com/datasheets/AM2315.pdf
#
# Portions of this code were inspired by Joehrg Ehrsam's am2315-python-api
# code. http://code.google.com/p/am2315-python-api/
#
# This library was originally authored by Sopwith:
#     http://sopwith.ismellsmoke.net/?p=104
import math
import time

import copy

from aot.inputs.base_input import AbstractInput
from aot.inputs.sensorutils import calculate_dewpoint
from aot.inputs.sensorutils import calculate_vapor_pressure_deficit

# Measurements
measurements_dict = {
    0: {
        'measurement': 'temperature',
        'unit': 'C'
    },
    1: {
        'measurement': 'humidity',
        'unit': 'percent'
    },
    2: {
        'measurement': 'dewpoint',
        'unit': 'C'
    },
    3: {
        'measurement': 'vapor_pressure_deficit',
        'unit': 'Pa'
    }
}

# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'AM2315C',
    'input_manufacturer': 'AOSONG',
    'input_name': 'AM2315C',
    'input_library': 'quick2wire-api',
    'measurements_name': 'Humidity/Temperature',
    'measurements_dict': measurements_dict,
    'url_datasheet': 'https://cdn-shop.adafruit.com/product-files/5182/5182_AM2315C.pdf',
    'url_product_purchase': 'https://vctec.co.kr/product/am2315c-i2c-%EC%98%A8%EB%8F%84%EC%8A%B5%EB%8F%84-%EC%84%BC%EC%84%9C-am2315c-encased-i2c-temperaturehumidity-sensor/20000',

    'measurements_rescale': False,

    'options_enabled': [
        'measurements_select',
        'period',
        'pre_output',
        'i2c_location'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'quick2wire', 'quick2wire-api==0.0.0.2')
    ],
    'interfaces': ['I2C'],
    'i2c_location': ['0x38'],
    'i2c_address_editable': False
}


class InputModule(AbstractInput):
    """Interfaces with the AOSONG AM2315C (AHT20-compatible) sensor to measure humidity, temperature, and dew point.

    @phase active
    @stability stable
    @dependency AbstractInput
    """
    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.sensor = None
        self.powered = False
        self.control = None

        if not testing:
            self.try_initialize()

    def initialize(self):
        from aot.aot_client import DaemonControl

        self.control = DaemonControl()
        self.sensor = AM2315(self.input_dev.i2c_bus)

    def get_measurement(self):
        """Gets the humidity and temperature."""
        if not self.sensor:
            self.logger.error("Error 101: Device not set up. See https://aot-inc.github.io/AoT/Error-Codes#error-101 for more info.")
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        temperature = None
        humidity = None
        dew_point = None
        measurements_success = False

        # Try twice to get measurement. This prevents an anomaly where
        # the first measurement fails if the sensor has just been powered
        # for the first time.
        for _ in range(2):
            dew_point, humidity, temperature = self.return_measurements()
            if dew_point is not None:
                measurements_success = True
                break
            time.sleep(2)

        if measurements_success:
            self.value_set(0, temperature)
            self.value_set(1, humidity)

            if self.is_enabled(0) and self.is_enabled(1):
                self.value_set(2, dew_point)
                self.value_set(3, calculate_vapor_pressure_deficit(self.value_get(0), self.value_get(1)))

            return self.return_dict
        else:
            self.logger.debug("Could not acquire a measurement")

    def return_measurements(self):
        # Retry measurement if CRC fails
        for num_measure in range(3):
            humidity, temperature = self.sensor.data()
            if humidity is None:
                self.logger.debug("Measurement {num} returned failed CRC".format(num=num_measure))
            else:
                dew_pt = calculate_dewpoint(temperature, humidity)
                return dew_pt, humidity, temperature
            time.sleep(2)

        self.logger.error("All measurements returned failed CRC")
        return None, None, None


class AM2315:
    """Wrapping for an AOSONG AM2315 humidity and temperature sensor.

    Provides simple access to a AM2315 chip using the quickwire i2c module
    Attributes:
        bus:       Int containing the smbus channel.
        address:   AM2315 bus address
        bus:       quickwire i2c object instance.
        lastError: String containing the last error string.Formatter
        debug:     bool containing debug state
    """
    def __init__(self, bus, address=0x38, debug=False):
        import quick2wire.i2c as i2c
        self.i2c = i2c
        self.channel = bus
        self.address = address   				  # Default address 0x38 (AM2315C)
        self.bus = self.i2c.I2CMaster(int(bus))        # quick2wire master
        self.lastError = None   				  # Contains last error string
        self.debug = debug       				  # Debug flag

    def data(self):
        """
        Reads the humidity and temperature from the AM2315C (AHT20-compatible).

        Sequence (per AM2315C / AHT20 datasheet):
        1) Send measurement trigger command 0xAC with parameters 0x33, 0x00.
        2) Wait for the conversion time (>80 ms).
        3) Read 7 bytes:
           [0] status
           [1:3] 20‑bit humidity data (MSB first, high 4 bits of byte 3)
           [3:6] 20‑bit temperature data (lower 4 bits of byte 3 + bytes 4,5)
           [6] CRC8 over bytes 0..5
        4) Convert to physical units:
           RH(%) = Srh / 2^20 * 100
           T(°C) = St / 2^20 * 200 - 50
        """
        # 1) Trigger a measurement
        try:
            # Command 0xAC, DATA0=0x33, DATA1=0x00
            self.bus.transaction(self.i2c.writing(self.address,
                                                  bytes([0xAC, 0x33, 0x00])))
        except Exception as e:
            self.lastError = 'I/O Error while starting measurement: {0}'.format(e)
            return None, None

        # 2) Wait for the sensor to perform the measurement
        time.sleep(0.1)  # 100 ms (>80 ms required)

        # 3) Read measurement data: 7 bytes
        try:
            result = self.bus.transaction(self.i2c.reading(self.address, 7))
            data = bytearray(result[0])
        except IOError as e:
            self.lastError = 'I/O Error({0}): {1}'.format(e.errno, e.strerror)
            return None, None
        except Exception as e:
            self.lastError = 'Error reading data from AM2315C: {0}'.format(e)
            return None, None

        if len(data) != 7:
            self.lastError = 'Unexpected data length from AM2315C: {0}'.format(len(data))
            return None, None

        status = data[0]

        # Bit7 = busy flag (1 = busy, 0 = idle) according to datasheet
        if status & 0x80:
            self.lastError = 'Sensor busy bit set in status byte: 0x{0:02X}'.format(status)
            return None, None

        # 4) CRC8 check over bytes 0..5
        crc_received = data[6]
        crc_calculated = self.verify_crc(data[0:6])
        if crc_received != crc_calculated:
            self.lastError = 'CRC8 error in sensor data (got 0x{0:02X}, expected 0x{1:02X})'.format(
                crc_received, crc_calculated
            )
            return None, None

        # 5) Parse 20‑bit humidity and temperature raw values
        # Humidity: bits [19:0] in data[1], data[2], data[3] (high nibble)
        raw_humidity = ((data[1] << 12) | (data[2] << 4) | (data[3] >> 4))

        # Temperature: bits [19:0] in data[3] (low nibble), data[4], data[5]
        raw_temperature = (((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5])

        # 6) Convert to engineering units using formulas from AM2315C datasheet
        humidity = (raw_humidity / float(1 << 20)) * 100.0
        tempC = (raw_temperature / float(1 << 20)) * 200.0 - 50.0

        return humidity, tempC

    def humidity(self):
        """Read humidity data from the sensor.

        Returns:
            float = humidity reading, None if error
        """
        time.sleep(.25)
        data = self.data()
        if data is not None:
            return self.data()[0]
        return None

    def temperature(self, fahrenheit=False):
        """Read temperature data from the sensor. (Celsius is default)

        Args:
            bool - if True returns temp in Fahrenheit. Default=False
        Returns:
            float = humidity reading, None if error
        """
        time.sleep(.25)
        data = self.data()
        if data is None:
            return None
        if fahrenheit:
            return self.data()[2]
        return self.data()[1]

    def fahrenheit(self):
        return self.temperature(True)

    def celsius(self):
        return self.temperature()

    @staticmethod
    def verify_crc(data):
        """Returns the 8‑bit CRC of sensor data (AM2315C / AHT20 style)."""
        crc = 0xFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) & 0xFF) ^ 0x31
                else:
                    crc = (crc << 1) & 0xFF
        return crc

    def c_to_f(self, celsius):
        """Convert Celsius to Fahrenheit.

        Params:
            celsius: int containing C temperature

        Returns:
            String with Fahrenheit conversion. None if error.
        """
        if celsius is None:
           return

        if celsius == 0:
            return 32

        try:
            temp_f = float((celsius * 9 / 5) + 32)
            return (math.trunc(temp_f * 10)) / 10
        except Exception:
            self.lastError = 'Error converting %s celsius to fahrenheit' % celsius
            return None

    def last_error(self):
        return self.lastError
