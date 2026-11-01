# coding=utf-8
#
# pwm_matter_level.py - Dimmer output for Matter LevelControl endpoints
#
"""
AoT Output: Matter dimmer (LevelControl)

One Output per Matter node; one channel per dimmable endpoint (dimmable
lights and plugs). Created from the node's own description when the device
is shared to AoT (Settings > Matter); docs/design/matter-controller.md §12.

A PWM output in AoT terms, like every other light dimmer: the environment
coordinator's lighting adapter, the PWM widget, PID and the PWM triggers all
speak duty cycle 0-100 %. Here that maps onto LevelControl:

  duty 1-100 %  -> MoveToLevelWithOnOff, level 1-254 (turns the light on)
  duty 0 / off  -> OnOff Off when the endpoint has OnOff (keeps the last
                   level for the next "on"), else MoveToLevelWithOnOff 1
  on, no duty   -> OnOff On (back to the device's last level)

State comes from the device's reports of OnOff and CurrentLevel, never from
an assumption about the command. A failed command returns (1, message); the
PWM path in base_output checks it.
"""
import copy
import time

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.devices.matter_output import MatterOutputMixin
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.lazy_text import lazy_format

COMMAND_TIMEOUT_S = 5.0          # under the 8 s Pyro budget (C3)
# After a level command the device reports OnOff=true a few ms before the new
# CurrentLevel (observed). Within this window a level that does not match
# the command yet is the old one, not news.
SETTLE_S = 2.0
LEVEL_CONTROL = 8
ON_OFF = 6
MAX_LEVEL = 254

measurements_dict = {
    0: {
        'measurement': 'duty_cycle',
        'unit': 'percent'
    }
}

channels_dict = {
    0: {
        'types': ['pwm'],
        'measurements': [0]
    }
}

OUTPUT_INFORMATION = {
    'output_name_unique': 'MATTER_LEVEL',
    'output_name': lazy_format("{}: Matter", lazy_gettext('Dimmer')),
    'output_manufacturer': 'Matter',
    'output_library': 'websockets',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['pwm'],

    'message': lazy_gettext(
        'Dim the light or plug endpoints of a Matter device on the AoT Matter fabric. '
        'Created automatically when a device is shared to AoT from Settings > Matter; each '
        'channel is one endpoint. A duty cycle of 0 switches it off; any other duty cycle sets the level '
        'and switches it on. The state shown is what the device reports.'
    ),

    'dependencies_module': [
        ('pip-pypi', 'websockets', 'websockets==16.0')
    ],

    'options_enabled': [
        'button_send_duty_cycle'
    ],
    'options_disabled': ['interface'],

    'interfaces': ['IP'],

    'custom_options': [
        {
            'id': 'node_id',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Node ID'),
            'phrase': lazy_gettext(
                'Node ID on the AoT Matter fabric. Inherited from the Matter device')
        },
    ],

    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('Name'),
            'phrase': lazy_gettext('A name for this channel')
        },
        {
            'id': 'endpoint',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'name': lazy_gettext('Endpoint'),
            'phrase': lazy_gettext('Matter endpoint number of this dimmer on the device')
        },
        {
            'id': 'transition_s',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Transition (seconds)'),
            'phrase': lazy_gettext(
                'How long the device takes to reach a new level. 0 = as fast as it can')
        },
    ]
}


def execute_at_creation(error, new_output, dict_outputs=None):
    """Only Settings > Matter creates this (bound to a node); refuse elsewhere."""
    from aot.devices.matter_onboarding import refuse_outside_settings
    return refuse_outside_settings(error, new_output, dict_outputs)


OUTPUT_INFORMATION['execute_at_creation'] = execute_at_creation


def duty_to_level(duty):
    """0-100 % -> Matter level 1-254 (0 is handled as off by the caller)."""
    return max(1, min(MAX_LEVEL, int(round(float(duty) * MAX_LEVEL / 100.0))))


def level_to_duty(level):
    return round(max(0, min(MAX_LEVEL, int(level))) * 100.0 / MAX_LEVEL, 1)


class OutputModule(MatterOutputMixin, AbstractOutput):
    """Matter LevelControl as an AoT PWM output.

    @phase experimental
    @stability experimental
    @dependency AbstractOutput, matter_client, matter_output
    """

    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)
        self._matter_init()
        self._last_recorded = {}
        self._commanded = {}          # channel -> last duty sent (> 0)
        self._commanded_at = {}       # channel -> monotonic time it was sent

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)
        self.setup_custom_options(OUTPUT_INFORMATION['custom_options'], self.output)
        if not self.node_id:
            # Normal for a moment while Settings > Matter creates the device.
            self.logger.info("Node ID not set yet; waiting for it to be configured")
            return
        self._matter_setup(OUTPUT_INFORMATION)

    # -- state -------------------------------------------------------------

    def state_paths(self, endpoint):
        from aot.devices.matter_clusters import attribute_path
        return [attribute_path(endpoint, LEVEL_CONTROL, 0), attribute_path(endpoint, ON_OFF, 0)]

    def _has_on_off(self, endpoint):
        """From the endpoint's cluster list, not from whether an OnOff value
        happens to be cached (it can be null or not yet reported)."""
        from aot.devices.matter_clusters import endpoint_clusters
        node = self.client.get_node(self.node_id) or {}
        return ON_OFF in endpoint_clusters(node.get('attributes') or {}).get(endpoint, set())

    def _state_from_cache(self, channel, endpoint):
        """Duty cycle the device is at: 0 when off, else its level in %."""
        on = self._attr(endpoint, ON_OFF, 0)
        level = self._attr(endpoint, LEVEL_CONTROL, 0)
        if on is False:
            return 0.0
        if level is None:
            return None if on is None else (100.0 if on else 0.0)
        # Levels are coarser than duty (254 steps): 40 % goes out as level 102
        # and comes back as 40.2 %. While the device sits at the level we sent,
        # show what was asked for.
        commanded = self._commanded.get(channel)
        if commanded is not None:
            if duty_to_level(commanded) == int(level):
                return commanded
            sent_at = self._commanded_at.get(channel, 0.0)
            if time.monotonic() - sent_at < SETTLE_S:
                # OnOff=true arrived ahead of the new level: still the old
                # level. Hold the commanded value instead of recording a spike.
                return commanded
            # The device moved elsewhere (another controller, a wall dimmer):
            # forget the old command so it cannot reappear on a later match.
            self._commanded.pop(channel, None)
        return level_to_duty(level)

    def _set_state(self, channel, value, source):
        super()._set_state(channel, value, source)
        # Against the last *recorded* value, so a slow drift is still recorded.
        last = self._last_recorded.get(channel)
        if last is None or abs(float(last) - float(value)) >= 0.5:
            self._last_recorded[channel] = value
            self._record(channel, value)

    def _record(self, channel, duty):
        try:
            measure = {channel: copy.deepcopy(measurements_dict[0])}
            measure[channel]['value'] = float(duty)
            add_measurements_influxdb(self.unique_id, measure)
        except Exception:
            self.logger.exception("Recording duty cycle failed")

    # -- commands ----------------------------------------------------------

    def output_switch(self, state, output_type=None, amount=None, output_channel=0,
                      **kwargs):
        from aot.devices.matter_client import MatterError

        if self.client is None:
            return 1, "Output not set up"
        endpoint = self._endpoint(output_channel)
        if endpoint is None:
            return 1, f"Channel {output_channel} has no Matter endpoint"

        try:
            duty = None if amount is None else float(amount)
        except (TypeError, ValueError):
            return 1, f"Invalid duty cycle: {amount}"

        # A new command replaces the last one's memory, whatever it is: an off,
        # an on-without-level or a command that fails must not leave an older
        # level behind for a late report to "match" (E2E: a stray old-level
        # point after a timed-out command).
        self._commanded.pop(output_channel, None)
        self._commanded_at.pop(output_channel, None)
        try:
            if state == 'on' and duty is None:
                self._send(endpoint, ON_OFF, 'On', {}, COMMAND_TIMEOUT_S)
            elif state == 'off' or (duty is not None and duty <= 0):
                if self._has_on_off(endpoint):
                    self._send(endpoint, ON_OFF, 'Off', {}, COMMAND_TIMEOUT_S)
                else:
                    self._send(endpoint, LEVEL_CONTROL, 'MoveToLevelWithOnOff',
                               self._level_payload(output_channel, 1), COMMAND_TIMEOUT_S)
            else:
                self._send(endpoint, LEVEL_CONTROL, 'MoveToLevelWithOnOff',
                           self._level_payload(output_channel, duty_to_level(duty)),
                           COMMAND_TIMEOUT_S)
                self._commanded[output_channel] = round(duty, 1)
                self._commanded_at[output_channel] = time.monotonic()
        except MatterError as err:
            msg = f"Matter command failed on channel {output_channel}: {err}"
            self.logger.error(msg)
            return 1, msg
        except Exception as err:
            msg = f"Error setting channel {output_channel}: {err}"
            self.logger.exception(msg)
            return 1, msg
        return 0, ""

    def _level_payload(self, channel, level):
        try:
            transition = float(self.options_channels.get('transition_s', {}).get(channel) or 0)
        except (TypeError, ValueError):
            transition = 0.0
        return {
            'level': int(level),
            # null = as fast as the device can (spec), not 0 s.
            'transitionTime': int(round(transition * 10)) if transition > 0 else None,
            'optionsMask': 0,
            'optionsOverride': 0,
        }

    def is_on(self, output_channel=0):
        if not self.is_setup():
            return None
        duty = self.output_states.get(output_channel)
        if duty is None:
            return None
        return duty if duty > 0 else False

    def stop_output(self):
        self._matter_teardown()
        self.running = False
