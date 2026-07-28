# coding=utf-8
# Copyright (c) 2026, AoT Project Authors. All rights reserved.
"""
AoT Input: Modbus TCP (PLC)

Polls registers/coils on a Modbus TCP device (PLC, gateway, meter) and stores
one measurement per channel.

Design notes (.local/plans/plc_modbus_integration_plan.md):
  - The TCP connection is NOT owned here. It comes from the process-wide
    registry in aot/devices/modbus_client.py, keyed by (host, port), so several
    Inputs and Outputs pointing at the same PLC share one connection and one
    lock. Opening one connection per driver would hit the connection cap that
    most PLCs impose, and pymodbus is not thread safe.
  - Nothing connects during __init__/initialize(). The daemon activates Inputs
    sequentially at boot and waits on an untimed Event, so a blocking connect
    here would stall the whole daemon startup. The first poll connects.
  - Communication status needs no code here: this is a polling ('has_loop')
    Input, so controller_input.py derives comm_capable/comm_is_fault from
    measurement staleness automatically. A failed poll must therefore store
    nothing at all — that silence is the signal.
"""
import copy

from flask_babel import lazy_gettext

from aot.config_translations import TRANSLATIONS
from aot.databases.models import DeviceMeasurements, InputChannel
from aot.devices.modbus_client import (DATA_TYPES, ModbusLinkError,
                                       decode_registers, get_link,
                                       register_count)
from aot.inputs.base_input import AbstractInput
from aot.utils.database import db_retrieve_table_daemon

measurements_dict = {}
channels_dict = {0: {}}

INPUT_INFORMATION = {
    'input_name_unique': 'MODBUS_TCP',
    'input_manufacturer': 'Modbus',
    'input_name': 'Modbus TCP (PLC)',
    'input_name_short': 'Modbus TCP',
    'input_library': 'pymodbus',
    'measurements_name': 'Variable measurements',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': lazy_gettext(
        'Reads coils and registers from a Modbus TCP device (PLC, gateway, meter). '
        'Define one channel per register to read. Several Inputs and Outputs pointing at '
        'the same host and port share a single connection automatically. '
        'Note that Modbus has no authentication or encryption — keep the device on an '
        'isolated network and never expose it to the internet.'),

    'measurements_variable_amount': True,
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': False,

    'options_enabled': [
        'measurements_select',
        'period',
        'start_offset',
        'pre_output'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'pymodbus', 'pymodbus==3.14.0')
    ],

    # 'IP' is what every other network device uses (kasa_energy_meter.py on the
    # Input side, the 9 network Outputs on the other), and the link-health work
    # classified network devices by exactly this field.
    'interfaces': ['IP'],

    'custom_options': [
        {
            'id': 'plc_host',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext('Host'),
            'phrase': lazy_gettext('IP address or hostname of the Modbus TCP device')
        },
        {
            'id': 'plc_port',
            'type': 'integer',
            'default_value': 502,
            'required': True,
            'name': lazy_gettext('Port'),
            'phrase': lazy_gettext('TCP port of the Modbus TCP device (standard: 502)')
        },
        {
            'id': 'unit_id',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Unit ID'),
            'phrase': lazy_gettext(
                'Modbus unit/slave ID of the device. Usually 1 for a device addressed '
                'directly, or the slave address behind a serial gateway')
        },
        {
            'id': 'timeout_s',
            'type': 'float',
            'default_value': 1.0,
            'required': True,
            'name': lazy_gettext('Timeout (seconds)'),
            'phrase': lazy_gettext(
                'How long to wait for a response. One request takes at most '
                'timeout x (retries + 1)')
        },
        {
            'id': 'retries',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Retries'),
            'phrase': lazy_gettext(
                'Retries per request before it is treated as failed. Keep this low: a high '
                'value multiplies how long an unreachable device blocks a command')
        }
    ],

    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': TRANSLATIONS['name']['title'],
            'phrase': TRANSLATIONS['name']['phrase']
        },
        {
            'id': 'register_type',
            'type': 'select',
            'default_value': 'holding_register',
            'options_select': [
                ('coil', lazy_gettext('Coil (read/write bit)')),
                ('discrete_input', lazy_gettext('Discrete Input (read-only bit)')),
                ('holding_register', lazy_gettext('Holding Register (read/write word)')),
                ('input_register', lazy_gettext('Input Register (read-only word)'))
            ],
            'required': True,
            'name': lazy_gettext('Register Type'),
            'phrase': lazy_gettext('Which Modbus table this channel reads from')
        },
        {
            'id': 'register_address',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Register Address'),
            'phrase': lazy_gettext(
                'Zero-based address within the selected table. Vendor documentation often '
                'lists one-based addresses (e.g. 40001 for holding register 0), so verify '
                'against the register map')
        },
        {
            'id': 'data_type',
            'type': 'select',
            'default_value': 'uint16',
            'options_select': [
                ('bool', lazy_gettext('Bit (coil / discrete input)')),
                ('int16', 'int16'),
                ('uint16', 'uint16'),
                ('int32', 'int32 (2 registers)'),
                ('uint32', 'uint32 (2 registers)'),
                ('float32', 'float32 (2 registers)')
            ],
            'required': True,
            'name': lazy_gettext('Data Type'),
            'phrase': lazy_gettext(
                'How to interpret the value. Bit types apply to coils and discrete inputs; '
                'the rest apply to registers')
        },
        {
            'id': 'word_order',
            'type': 'select',
            'default_value': 'big',
            'options_select': [
                ('big', lazy_gettext('Big endian (high word first)')),
                ('little', lazy_gettext('Little endian (low word first)'))
            ],
            'required': False,
            'name': lazy_gettext('Word Order'),
            'phrase': lazy_gettext(
                'Register order for 32-bit types. Vendors differ, so if a value reads as '
                'nonsense while the register address is correct, try the other order')
        },
        {
            'id': 'scale_factor',
            'type': 'float',
            'default_value': 1.0,
            'required': False,
            'name': lazy_gettext('Scale Factor'),
            'phrase': lazy_gettext(
                'The raw value is multiplied by this. Use it when a device reports e.g. '
                'tenths of a degree (0.1)')
        }
    ]
}


class InputModule(AbstractInput):
    """Poll coils/registers from a Modbus TCP device.

    @phase active
    @stability experimental
    @dependency AbstractInput, ModbusTCPLink
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.plc_host = ''
        self.plc_port = 502
        self.unit_id = 1
        self.timeout_s = 1.0
        self.retries = 1

        self.link = None
        self.options_channels = {}
        self.measure_info = {}

        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        """Resolve channel options and claim the shared link (no I/O here)."""
        if not self.plc_host:
            self.logger.error("Host must be set")
            return

        input_channels = db_retrieve_table_daemon(InputChannel).filter(
            InputChannel.input_id == self.input_dev.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            INPUT_INFORMATION['custom_channel_options'], input_channels)

        # Measurement count is user-defined here, so the per-poll return_dict
        # template has to be built from the database rather than from the
        # module-level measurements_dict (which is empty for variable Inputs).
        self.measure_info = {}
        for each_measure in db_retrieve_table_daemon(DeviceMeasurements).filter(
                DeviceMeasurements.device_id == self.input_dev.unique_id).all():
            self.measure_info[each_measure.channel] = {
                'measurement': each_measure.measurement,
                'unit': each_measure.unit
            }

        # get_link() only registers the connection — it does not open a socket,
        # so this stays safe inside the daemon's sequential Input activation.
        self.link = get_link(
            self.plc_host,
            port=int(self.plc_port),
            timeout_s=float(self.timeout_s),
            retries=int(self.retries))
        self.logger.debug(
            f"Using shared Modbus link {self.plc_host}:{self.plc_port} (unit {self.unit_id})")

    def _channel_option(self, option_id, channel, default=None):
        try:
            value = self.options_channels[option_id][channel]
        except (KeyError, IndexError, TypeError):
            return default
        return default if value in (None, '') else value

    def _read_channel(self, channel):
        """Read and scale one channel. Raises ModbusLinkError on link failure."""
        register_type = self._channel_option('register_type', channel, 'holding_register')
        data_type = self._channel_option('data_type', channel, 'uint16')
        word_order = self._channel_option('word_order', channel, 'big')
        address = int(self._channel_option('register_address', channel, 0))
        scale = float(self._channel_option('scale_factor', channel, 1.0))
        device_id = int(self.unit_id)

        if data_type not in DATA_TYPES:
            self.logger.error(f"Channel {channel}: unknown data type '{data_type}'")
            return None

        if register_type in ('coil', 'discrete_input'):
            if register_type == 'coil':
                bits = self.link.read_coils(address, count=1, device_id=device_id)
            else:
                bits = self.link.read_discrete_inputs(address, count=1, device_id=device_id)
            raw = 1.0 if bits[0] else 0.0
        else:
            if data_type == 'bool':
                self.logger.error(
                    f"Channel {channel}: data type 'bool' cannot be read from "
                    f"'{register_type}' — choose an integer or float type")
                return None
            count = register_count(data_type)
            if register_type == 'holding_register':
                registers = self.link.read_holding_registers(
                    address, count=count, device_id=device_id)
            else:
                registers = self.link.read_input_registers(
                    address, count=count, device_id=device_id)
            raw = decode_registers(registers, data_type, word_order=word_order)

        return float(raw) * scale

    def get_measurement(self):
        """Poll every enabled channel once."""
        if self.link is None:
            self.logger.error("Input not set up")
            return

        self.return_dict = copy.deepcopy(self.measure_info)

        for channel in self.channels_measurement:
            if not self.is_enabled(channel):
                continue
            try:
                value = self._read_channel(channel)
            except ModbusLinkError as err:
                # Store nothing. Staleness is what marks this Input as offline
                # (controller_input.py comm_is_fault), so a placeholder value
                # here would actively hide the outage.
                self.logger.error(f"Channel {channel}: {err}")
                continue
            except Exception:
                self.logger.exception(f"Channel {channel}: reading register")
                continue
            if value is not None:
                self.value_set(channel, value)

        return self.return_dict
