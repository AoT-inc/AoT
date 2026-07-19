# coding=utf-8
#
# on_off_virtual_single.py - Virtual output for testing with no hardware dependencies (Single Channel)
#
from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon

# Measurements (Single channel)
measurements_dict = {
    0: {'measurement': 'duration_time', 'unit': 's'}
}

# 1 Virtual Channel
channels_dict = {
    0: {'types': ['on_off'], 'measurements': [0]}
}

# Output information
OUTPUT_INFORMATION = {
    'output_name_unique': 'virtual_on_off_single',
    'output_name': "{} (Virtual Single-Channel)".format(lazy_gettext('On/Off')),
    'output_library': 'Internal',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    'message': 'A single-channel virtual output device for testing. State is stored in memory and has no effect on hardware.',

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],

    'custom_channel_options': [
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Startup State'),
            'phrase': 'Set the state when AoT starts'
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Shutdown State'),
            'phrase': 'Set the state when AoT shuts down'
        },
        {
            'id': 'amps',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Current'), lazy_gettext('Amps')),
            'phrase': 'The current draw of the virtual device'
        }
    ]
}


class OutputModule(AbstractOutput):
    """Simulate a single-channel on/off output in memory for testing.

    @phase active
    @stability stable
    @dependency AbstractOutput
    """
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)
        
        # Consistent with on_off_gpio.py
        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)
        
        # Initialize single channel state based on startup options
        startup_opt = self.options_channels['state_startup'][0]
        self.output_states[0] = True if startup_opt == 1 else False
        
        self.output_setup = True
        
        status_str = "ON" if self.output_states[0] else "OFF"
        self.logger.info(f"Virtual Single Channel Output Initialized ({status_str})")

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        if not self.is_setup():
            self.logger.error('Output not set up')
            return

        # Ensure channel is treated as int 0
        try:
            chan = int(output_channel)
        except (ValueError, TypeError):
            chan = 0
            
        if chan != 0:
            self.logger.debug(f"Virtual Single Channel received command for invalid channel {chan}, ignoring or mapping to 0")
            # For single channel, might optionally enforce channel 0
            # chan = 0 

        if state == 'on':
            self.output_states[chan] = True
            self.logger.debug(f"Virtual Single Channel turned ON")
        elif state == 'off':
            self.output_states[chan] = False
            self.logger.debug(f"Virtual Single Channel turned OFF")

    def is_on(self, output_channel=0):
        if self.is_setup():
            try:
                chan = int(output_channel)
            except (ValueError, TypeError):
                chan = 0
            return self.output_states.get(chan, False)
        return False

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        if self.is_setup():
            shutdown_opt = self.options_channels['state_shutdown'][0]
            if shutdown_opt == 1:
                self.output_switch('on')
            elif shutdown_opt == 0:
                self.output_switch('off')
        self.running = False
