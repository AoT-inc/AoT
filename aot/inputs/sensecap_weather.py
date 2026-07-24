# coding=utf-8
#
#  This software is a derivative version based on the open-source Mycodo
#  project (© Kyle T. Gabriel), modified to suit the goals of the AoT project.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#
#  This file is distributed under the GNU GPLv3 license.
#  The original copyright and license terms are stated below.
#
#  2026-07-24

import datetime
import logging
import requests

from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger("aot.inputs.sensecap_weather")

# Reference: https://sensecap-statics.seeed.cn/refer/def/sensor.json (Seeed's own
# sensorType -> measurementId mapping, "sm" key). Each entry here is one physical
# reading Seeed's cloud can report for a node. Channel indices are fixed (sorted by
# measurement_id) so they never shift when new device types are added below.
MEASUREMENT_CATALOG = {
    '4097': {'measurement': 'temperature',              'unit': 'C',       'name': lazy_gettext('Air Temperature')},
    '4098': {'measurement': 'humidity',                 'unit': 'percent', 'name': lazy_gettext('Air Humidity')},
    '4099': {'measurement': 'light',                    'unit': 'lux',     'name': lazy_gettext('Light Intensity')},
    '4100': {'measurement': 'co2',                       'unit': 'ppm',     'name': lazy_gettext('CO2')},
    '4101': {'measurement': 'pressure',                 'unit': 'Pa',      'name': lazy_gettext('Barometric Pressure')},
    '4102': {'measurement': 'temperature',              'unit': 'C',       'name': lazy_gettext('Soil Temperature')},
    '4103': {'measurement': 'volumetric_water_content', 'unit': 'percent', 'name': lazy_gettext('Soil Moisture')},
    '4104': {'measurement': 'direction',                'unit': 'bearing', 'name': lazy_gettext('Wind Direction')},
    '4105': {'measurement': 'speed',                    'unit': 'm_s',     'name': lazy_gettext('Wind Speed')},
    '4106': {'measurement': 'ion_concentration',        'unit': 'pH',      'name': lazy_gettext('pH')},
    '4108': {'measurement': 'electrical_conductivity_soil', 'unit': 'dS_m', 'name': lazy_gettext('Soil Electrical Conductivity')},
    '4110': {'measurement': 'volumetric_water_content', 'unit': 'percent', 'name': lazy_gettext('Soil Volumetric Water Content')},
    '4113': {'measurement': 'precipitation',            'unit': 'mm_h',    'name': lazy_gettext('Rainfall Hourly')},
    '4138': {'measurement': 'volumetric_water_content', 'unit': 'percent', 'name': lazy_gettext('Soil Moisture 10cm')},
    '4139': {'measurement': 'volumetric_water_content', 'unit': 'percent', 'name': lazy_gettext('Soil Moisture 20cm')},
    '4140': {'measurement': 'volumetric_water_content', 'unit': 'percent', 'name': lazy_gettext('Soil Moisture 30cm')},
    '4141': {'measurement': 'volumetric_water_content', 'unit': 'percent', 'name': lazy_gettext('Soil Moisture 40cm')},
    '4142': {'measurement': 'temperature',              'unit': 'C',       'name': lazy_gettext('Soil Temperature 10cm')},
    '4143': {'measurement': 'temperature',              'unit': 'C',       'name': lazy_gettext('Soil Temperature 20cm')},
    '4144': {'measurement': 'temperature',              'unit': 'C',       'name': lazy_gettext('Soil Temperature 30cm')},
    '4145': {'measurement': 'temperature',              'unit': 'C',       'name': lazy_gettext('Soil Temperature 40cm')},
    '4146': {'measurement': 'particulate_matter_2_5',   'unit': 'ug_m3',   'name': lazy_gettext('PM2.5')},
    '4147': {'measurement': 'particulate_matter_10_0',  'unit': 'ug_m3',   'name': lazy_gettext('PM10')},
    '4190': {'measurement': 'uvi',                      'unit': 'index',   'name': lazy_gettext('UV Index')},
    '4191': {'measurement': 'speed',                    'unit': 'm_s',     'name': lazy_gettext('Peak Wind Gust')},
    '4202': {'measurement': 'dewpoint',                 'unit': 'C',       'name': lazy_gettext('Dew Point Temperature')},
    '4203': {'measurement': 'temperature',              'unit': 'C',       'name': lazy_gettext('Temperature')},
    '4213': {'measurement': 'precipitation',            'unit': 'mm',      'name': lazy_gettext('Rain Accumulation')},
}

# Fixed channel index for every measurement_id, sorted numerically for stability.
CHANNEL_MEASUREMENT_ID = {i + 1: mid for i, mid in enumerate(sorted(MEASUREMENT_CATALOG, key=int))}
MEASUREMENT_ID_CHANNEL = {mid: idx for idx, mid in CHANNEL_MEASUREMENT_ID.items()}

measurements_dict = {
    idx: dict(MEASUREMENT_CATALOG[mid]) for idx, mid in CHANNEL_MEASUREMENT_ID.items()
}

# sensorType code (Seeed's own device-type catalog) -> device name and the
# measurement_ids it reports. Curated to the types relevant to AoT (weather
# stations, temperature/humidity, soil, CO2, pH). Source: sensor.json 'sm' key.
DEVICE_TYPES = {
    '1001': {'name': lazy_gettext('Air Temperature and Humidity Sensor'), 'measurement_ids': ['4097', '4098']},
    '1003': {'name': lazy_gettext('Light Intensity Sensor'), 'measurement_ids': ['4099']},
    '1004': {'name': lazy_gettext('CO2 Sensor'), 'measurement_ids': ['4100']},
    '1005': {'name': lazy_gettext('Barometric Pressure Sensor'), 'measurement_ids': ['4101']},
    '1006': {'name': lazy_gettext('Soil Moisture and Temperature Sensor'), 'measurement_ids': ['4102', '4103']},
    '1008': {'name': lazy_gettext('Wind Direction Sensor'), 'measurement_ids': ['4104']},
    '1009': {'name': lazy_gettext('Wind Speed Sensor'), 'measurement_ids': ['4105']},
    '1011': {'name': lazy_gettext('Rain Gauge'), 'measurement_ids': ['4113']},
    '2001': {'name': lazy_gettext('Compact Weather Station 5-in-1 (S500)'), 'measurement_ids': ['4097', '4098', '4101', '4104', '4105']},
    '2002': {'name': lazy_gettext('Compact Weather Station 3-in-1 (S300)'), 'measurement_ids': ['4097', '4098', '4101']},
    '2003': {'name': lazy_gettext('Compact Weather Station 4-in-1 (S400)'), 'measurement_ids': ['4097', '4098', '4101', '4099']},
    '2007': {'name': lazy_gettext('Soil Temperature and VWC Sensor'), 'measurement_ids': ['4110', '4102']},
    '2019': {'name': lazy_gettext('Multilayer Soil Moisture and Temperature Sensor'), 'measurement_ids': ['4138', '4139', '4140', '4141', '4142', '4143', '4144', '4145']},
    '2035': {'name': lazy_gettext('Soil Moisture, Temperature and EC Sensor'), 'measurement_ids': ['4102', '4103', '4108']},
    '2040': {'name': lazy_gettext('LoRaWAN 8-in-1 Compact Weather Station (S2120)'), 'measurement_ids': ['4097', '4098', '4099', '4101', '4104', '4105', '4113', '4190', '4191', '4213']},
    '2041': {'name': lazy_gettext('Compact Weather Station 10-in-1 (S1000)'), 'measurement_ids': ['4097', '4098', '4099', '4100', '4101', '4104', '4105', '4113', '4146', '4147']},
    '2043': {'name': lazy_gettext('pH Sensor (S2106)'), 'measurement_ids': ['4097', '4106']},
    '2048': {'name': lazy_gettext('Air Temperature, Humidity and Dew Point Sensor'), 'measurement_ids': ['4097', '4098', '4202']},
    '2049': {'name': lazy_gettext('Temperature Sensor'), 'measurement_ids': ['4203']},
}

DEVICE_TYPE_OPTIONS = [(code, info['name']) for code, info in DEVICE_TYPES.items()]

INPUT_INFORMATION = {
    'input_name_unique': 'sensecap_weather',
    'input_manufacturer': 'Seeed',
    'input_name': 'SenseCAP OpenAPI Sensor',
    'input_name_short': 'SenseCAP',
    # Left empty on purpose: channels are not a static superset for this Input.
    # execute_at_creation/execute_at_modification below create exactly the channels
    # for the selected Device Type and delete the rest, so channels that don't apply
    # to the chosen device never exist as DeviceMeasurements rows - and therefore
    # never show up as selectable options in Functions, dashboard widgets, etc.
    'measurements_dict': {},
    'message': lazy_gettext('Polls the SenseCAP OpenAPI directly for a SenseCAP LoRaWAN sensor node, bypassing the LoRaWAN network server. Requires an API ID/Access API Key created in the SenseCAP portal, and the device Node EUI. Select the Device Type matching the physical sensor so only its relevant channels are created.'),

    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
            'default_value': 300,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("Measurement Period (sec)"),
            'phrase': lazy_gettext("Enter the measurement interval in seconds.")
        },
        {
            'id': 'device_type',
            'type': 'select',
            'default_value': '2040',
            'options_select': DEVICE_TYPE_OPTIONS,
            'required': True,
            'name': lazy_gettext("Device Type"),
            'phrase': lazy_gettext("Select the type of SenseCAP sensor this node is, so the correct measurement channels are used.")
        },
        {
            'id': 'node_eui',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext("Node EUI"),
            'phrase': lazy_gettext("Enter the SenseCAP device Node EUI.")
        },
        {
            'id': 'api_id',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext("API ID"),
            'phrase': lazy_gettext("Enter the API ID issued by the SenseCAP portal (Organization/Security Credentials).")
        },
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext("Access API Key"),
            'phrase': lazy_gettext("Enter the Access API Key issued by the SenseCAP portal.")
        },
    ],

    'custom_commands': [
        {
            'id': 'backfill_now',
            'type': 'button',
            'wait_for_return': False,
            'name': lazy_gettext('Fetch Historical Data'),
            'phrase': lazy_gettext('Backfill past readings from the SenseCAP cloud. Only fetches data older than what is already stored, so pressing this again is safe once history is caught up.')
        }
    ]
}

# SenseCAP's /raw endpoint documents a ~1 month span per request and ~3 months of
# retained history. Walk backward in weekly chunks (safe well under any point-count
# limit) until either that retention floor or an empty response is reached.
BACKFILL_CHUNK_MS = 7 * 24 * 60 * 60 * 1000
BACKFILL_MAX_LOOKBACK_MS = 90 * 24 * 60 * 60 * 1000
BACKFILL_REQUEST_LIMIT = 5000


def _channels_for_device_type(device_type):
    allowed_ids = DEVICE_TYPES.get(device_type, {}).get('measurement_ids', [])
    return {MEASUREMENT_ID_CHANNEL[mid] for mid in allowed_ids if mid in MEASUREMENT_ID_CHANNEL}


def _sync_channels(device_id, device_type):
    """Make DeviceMeasurements for device_id exactly match the selected Device Type's
    channels: create missing ones, delete ones that no longer apply. Channels not
    part of the current Device Type are not merely disabled - they don't exist as
    rows at all, so they can't appear in Function/dashboard measurement pickers
    (those list every DeviceMeasurements row for a device with no is_enabled filter)."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import DeviceMeasurements

    wanted_channels = _channels_for_device_type(device_type)
    existing = {m.channel: m for m in DeviceMeasurements.query.filter_by(device_id=device_id).all()}

    for idx in wanted_channels:
        meas_info = measurements_dict[idx]
        if idx in existing:
            continue
        new_measurement = DeviceMeasurements()
        new_measurement.device_id = device_id
        new_measurement.name = str(meas_info['name'])
        new_measurement.measurement = meas_info['measurement']
        new_measurement.unit = meas_info['unit']
        new_measurement.channel = idx
        new_measurement.is_enabled = True
        db.session.add(new_measurement)

    for channel, meas in existing.items():
        if channel not in wanted_channels:
            db.session.delete(meas)

    db.session.commit()
    return len(wanted_channels)


def execute_at_modification(
        messages,
        mod_input,
        request_form,
        custom_options_dict_presave,
        custom_options_channels_dict_presave,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave):
    """Sync channels to exactly match the (possibly changed) selected Device Type."""
    device_type = custom_options_dict_postsave.get('device_type')
    num_channels = _sync_channels(mod_input.unique_id, device_type)

    device_name = str(DEVICE_TYPES.get(device_type, {}).get('name', device_type))
    messages["info"].append(
        f"SenseCAP: {num_channels} channel(s) active for device type '{device_name}'.")

    return (messages,
            mod_input,
            custom_options_dict_postsave,
            custom_options_channels_dict_postsave)


INPUT_INFORMATION['execute_at_modification'] = execute_at_modification


def execute_at_creation(error, new_input, dict_inputs=None):
    """Create exactly the channels for the submitted Device Type, so the correct
    channels exist immediately (no extra edit/save round-trip). Runs before
    new_input.save() and before the generic channel-creation step - which is a
    no-op here since INPUT_INFORMATION['measurements_dict'] is deliberately empty."""
    import json

    try:
        custom_options = json.loads(new_input.custom_options or '{}')
    except (TypeError, ValueError):
        custom_options = {}
    _sync_channels(new_input.unique_id, custom_options.get('device_type'))

    return error, new_input


INPUT_INFORMATION['execute_at_creation'] = execute_at_creation


class InputModule(AbstractInput):
    """Sensor driver for a SenseCAP LoRaWAN sensor node via the SenseCAP OpenAPI.

    Reads the device's latest reported measurements directly from Seeed's cloud
    (GET /1.0/devices/data/{node_eui}/latest) instead of joining the local LoRaWAN
    network server, since SenseCAP does not expose OTAA join keys for this device.
    The Device Type option determines which channels are enabled/recorded.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)
        if not hasattr(self.input_dev, 'options'):
            self.input_dev.options = {}
        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        """Override initialize to satisfy AbstractInput requirements."""
        # No additional initialization required for this input module
        pass

    def pre_fetch_data(self):
        try:
            response = requests.get(
                self.api_url,
                auth=(self.api_id, self.api_key),
                timeout=60)
            response.raise_for_status()
            result = response.json()
            if str(result.get('code')) != '0':
                self.logger.error(f"SenseCAP OpenAPI returned error: {result}")
                return None
            data = result.get('data')
            if not data:
                return None
            self.raw_data_cache = data
            return data
        except Exception as e:
            self.logger.error(f"Error fetching data from SenseCAP OpenAPI: {e}")
            return None

    def _extract_measurements(self, data, active_channels):
        results = {}
        points = {}
        for channel_group in data:
            for point in channel_group.get('points', []):
                points[point.get('measurement_id')] = point.get('value')
        for idx in active_channels:
            raw_val = points.get(CHANNEL_MEASUREMENT_ID[idx])
            if raw_val is None:
                continue
            try:
                results[idx] = float(raw_val)
            except (TypeError, ValueError):
                continue
        return results

    def get_measurement(self):
        self.node_eui = self.get_custom_option('node_eui')
        self.api_id = self.get_custom_option('api_id')
        self.api_key = self.get_custom_option('api_key')
        if not (self.node_eui and self.api_id and self.api_key):
            return
        active_channels = _channels_for_device_type(self.get_custom_option('device_type'))
        self.api_url = f"https://sensecap-openapi.seeed.cc/1.0/devices/data/{self.node_eui}/latest"
        self.return_dict = {idx: dict(measurements_dict[idx]) for idx in active_channels}
        data = self.pre_fetch_data()
        if data is None:
            return
        measurements = self._extract_measurements(data, active_channels)
        for idx, val in measurements.items():
            if self.is_enabled(idx):
                self.value_set(idx, val)
        return self.return_dict

    def _fetch_raw_chunk(self, node_eui, api_id, api_key, time_start_ms, time_end_ms):
        url = f"https://sensecap-openapi.seeed.cc/1.0/devices/data/{node_eui}/raw"
        params = {
            'time_start': int(time_start_ms),
            'time_end': int(time_end_ms),
            'limit': BACKFILL_REQUEST_LIMIT,
        }
        response = requests.get(url, params=params, auth=(api_id, api_key), timeout=60)
        response.raise_for_status()
        result = response.json()
        if str(result.get('code')) != '0':
            self.logger.error(f"SenseCAP backfill: API returned error: {result}")
            return []
        points = []
        for channel_group in result.get('data') or []:
            points.extend(channel_group.get('points', []))
        return points

    def _existing_timestamps(self, channel, meas_info, start_ms, end_ms):
        """All timestamps (ms) already stored for this channel within [start_ms, end_ms].
        Used to skip re-writing points, including ones inside gaps left by an earlier
        partial/buggy backfill run - not just points older than the earliest one seen."""
        from aot.utils.influx import query_flux

        start = datetime.datetime.fromtimestamp(start_ms / 1000, tz=datetime.timezone.utc)
        end = datetime.datetime.fromtimestamp(end_ms / 1000, tz=datetime.timezone.utc)
        try:
            tables = query_flux(
                meas_info['unit'], self.unique_id,
                channel=channel, measure=meas_info['measurement'],
                start_str=start.isoformat(), end_str=end.isoformat())
        except Exception as e:
            self.logger.error(f"SenseCAP backfill: existing-data lookup failed for channel {channel}: {e}")
            return set()
        existing = set()
        for table in tables or []:
            for record in table.records:
                try:
                    existing.add(int(record.get_time().timestamp() * 1000))
                except Exception:
                    continue
        return existing

    def backfill_now(self, args_dict):
        """Custom command (button): fetch SenseCAP history older than what is already
        stored locally, per channel, so re-running this never re-fetches data that's
        already covered."""
        from aot.utils.influx import write_influxdb_value

        node_eui = self.get_custom_option('node_eui')
        api_id = self.get_custom_option('api_id')
        api_key = self.get_custom_option('api_key')
        if not (node_eui and api_id and api_key):
            self.logger.error("SenseCAP backfill: missing Node EUI/API credentials")
            return

        active_channels = _channels_for_device_type(self.get_custom_option('device_type'))
        if not active_channels:
            self.logger.error("SenseCAP backfill: no channels active for the selected Device Type")
            return

        now_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        floor_ms = now_ms - BACKFILL_MAX_LOOKBACK_MS

        self.logger.info("SenseCAP backfill: checking existing coverage")
        existing_ts = {}
        for idx in active_channels:
            existing_ts[idx] = self._existing_timestamps(idx, measurements_dict[idx], floor_ms, now_ms)

        window_end = now_ms
        written = 0

        self.logger.info("SenseCAP backfill: starting")
        while window_end > floor_ms:
            window_start = max(window_end - BACKFILL_CHUNK_MS, floor_ms)
            try:
                points = self._fetch_raw_chunk(node_eui, api_id, api_key, window_start, window_end)
            except Exception as e:
                self.logger.error(f"SenseCAP backfill: request failed for window {window_start}-{window_end}: {e}")
                break

            if not points:
                self.logger.info(
                    f"SenseCAP backfill: no more data before {window_start}, stopping")
                break

            for point in points:
                meas_id = point.get('measurement_id')
                channel = MEASUREMENT_ID_CHANNEL.get(meas_id)
                if channel is None or channel not in active_channels:
                    continue
                try:
                    point_ms = int(point.get('created'))
                    value = float(point.get('value'))
                except (TypeError, ValueError):
                    continue
                if point_ms in existing_ts[channel]:
                    continue  # already stored - covers both "older than earliest" and gaps

                meas_info = measurements_dict[channel]
                point_time = datetime.datetime.fromtimestamp(point_ms / 1000, tz=datetime.timezone.utc)
                write_influxdb_value(
                    self.unique_id, meas_info['unit'], value,
                    measure=meas_info['measurement'], channel=channel, timestamp=point_time)
                written += 1
                existing_ts[channel].add(point_ms)

            window_end = window_start

        self.logger.info(f"SenseCAP backfill: finished, {written} historical point(s) written")
