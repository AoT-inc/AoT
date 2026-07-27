# coding=utf-8
#
# remote_output_on_off.py - Output for controlling a remote AoT On/Off Output
#
import json
import time
from threading import Thread

from flask_babel import lazy_gettext

from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon

measurements_dict = {
    0: {
        'measurement': 'duration_time',
        'unit': 's'
    }
}

channels_dict = {
    0: {
        'types': ['on_off'],
        'measurements': [0]
    }
}

# Output information
OUTPUT_INFORMATION = {
    'output_name_unique': 'remote_output',
    'output_name': "{} AoT Output: {}".format(lazy_gettext('Remote'), lazy_gettext('On/Off')),
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_library': 'requests',
    'output_types': ['on_off'],

    # The remote API POST response confirms the command was applied; the periodic
    # status poll corrects drift. Small window covers the HTTP round-trip.
    'command_timeout_default_s': 5,

    'message': 'This Output allows remote control of another AoT On/Off Output over a network using the API.',

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'requests', 'requests==2.31.0'),
    ],

    'interfaces': ['API'],

    'custom_options_message': 'Enter the API key and IP/Host address of your remote AoT and save to populate the Remote Output dropdown selection. You will need to refresh the page after saving for the Remote AoT Output dropdown to populate. Configure which Remote AoT Output you would like to control and save again. You must select an On/Off Output Channel for this to work. Selecting a PWM, Volume, or other channel will cause an error.',

    'custom_options': [
        {
            'id': 'host',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "Remote AoT Host",
            'phrase': lazy_gettext('The host or IP address of the remote AoT')
        },
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "Remote AoT API Key",
            'phrase': lazy_gettext('The API key of the remote AoT')
        },
        {
            'id': 'state_query_period',
            'type': 'integer',
            'default_value': 120,
            'name': "State Query Period (Seconds)",
            'phrase': 'How often to query the state of the output'
        },
        {
            'id': 'request_timeout',
            'type': 'integer',
            'default_value': 60,
            'name': "Request Timeout (Seconds)",
            'phrase': 'HTTP read timeout for ON/OFF commands. Must be longer than the slowest command on the remote host (e.g. if the remote command has time.sleep(15), set this to at least 20).'
        }
    ],

    'custom_channel_options': [
        {
            'id': 'remote_output',
            'type': 'select_custom_choices',
            'default_value': '',
            'name': 'Remote AoT Output',
            'phrase': 'The Remote AoT Output to control'
        },
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': -1,
            'options_select': [
                (-1, 'Do Nothing'),
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Startup State'),
            'phrase': 'Set the state when AoT starts'
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': -1,
            'options_select': [
                (-1, 'Do Nothing'),
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Shutdown State'),
            'phrase': 'Set the state when AoT shuts down'
        },
        {
            'id': 'command_force',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Force Command'),
            'phrase': 'Always send the command if instructed, regardless of the current state'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Trigger Functions at Startup'),
            'phrase': 'Whether to trigger functions when the output switches at startup'
        }
    ]
}


class OutputModule(AbstractOutput):
    """Control another AoT On/Off output over a network via the AoT REST API.

    @phase active
    @stability stable
    @dependency AbstractOutput, requests
    """
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.api_key = None
        self.host = None
        self.state_query_period = None
        self.request_timeout = 60

        self.api_output = None
        self.query_timer = 0

        # Communication status. Two independent levels, because "I can reach the
        # remote AoT" and "the remote AoT can reach its device" are different
        # questions and either one failing means we do not know our own state:
        #
        #   _remote_reachable    — did the last /api/outputs poll succeed
        #                          (None = not polled yet, so a fresh start is
        #                          not reported as a failure)
        #   _remote_device_fault — channels the REMOTE AoT itself reports as
        #                          'fault'. It runs the same status stack we do,
        #                          so its verdict about its own device is more
        #                          authoritative than anything we could infer,
        #                          and is passed straight through rather than
        #                          being flattened into on/off.
        self._remote_reachable = None
        self._remote_device_fault = set()

        self.setup_custom_options(
            OUTPUT_INFORMATION['custom_options'], output)

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == self.output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)

        if self.api_key and self.host:
            self.get_remote_output_information()
            if self.api_output:
                self.parse_remote_output_info()
            else:
                self.output_setup = False

        try:
            if self.output_setup:
                # Set up thread to query output states
                query_states = Thread(target=self.remote_state_query)
                query_states.daemon = True
                query_states.start()

                for channel in channels_dict:
                    if self.options_channels['state_startup'][channel] == 1:
                        self.output_switch("on", output_channel=channel)
                    elif self.options_channels['state_startup'][channel] == 0:
                        self.output_switch("off", output_channel=channel)
                    else:
                        continue

                    startup = 'ON' if self.options_channels['state_startup'][channel] else 'OFF'
                    self.logger.info(f"Output setup and turned {startup}")

                    if self.options_channels['trigger_functions_startup'][channel]:
                        try:
                            self.check_triggers(self.unique_id, output_channel=channel)
                        except Exception as err:
                            self.logger.error(
                                f"Could not check Trigger for channel {channel} of output {self.unique_id}: {err}")
        except Exception as except_msg:
            self.logger.exception(
                "Output was unable to be setup: {err}".format(err=except_msg))

    def remote_state_query(self):
        """Periodically query output states"""
        while self.running:
            now = time.time()

            if self.state_query_period and self.query_timer < now:
                # allow_clear=False: keep last good api_output on transient failure
                # so send_remote_output can still resolve channel ids.
                self.get_remote_output_information(allow_clear=False)
                self.parse_output_state_info()
                self.query_timer = now + self.state_query_period

            time.sleep(1)

    def get_remote_output_information(self, allow_clear=True):
        """Fetch output list from the remote host.

        allow_clear=False: on transient failure keep the last good api_output so
        send_remote_output can still resolve channels during a temporary outage.
        """
        import requests

        endpoint = 'outputs'
        url = 'https://{ip}/api/{ep}'.format(ip=self.host, ep=endpoint)
        headers = {
            'Accept': 'application/vnd.aot.v1+json',
            'X-API-KEY': self.api_key
        }

        try:
            response = requests.get(
                url, headers=headers, verify=False, timeout=5)
        except requests.exceptions.RequestException as err:
            self.logger.error(f"Remote output information request failed: {err}")
            # Cannot reach the remote AoT at all — our view of every channel on
            # it is stale from this moment, regardless of what was last seen.
            self._remote_reachable = False
            if allow_clear:
                self.api_output = None
            return

        self.logger.debug(f"Response Status: {response.status_code}")
        self.logger.debug(f"Response Headers: {response.headers}")

        try:
            response_dict = json.loads(response.text)
        except:
            response_dict = {}
        self.logger.debug(f"Response Dictionary: {response_dict}")

        if response.status_code != 200:
            self.logger.error("Response Status was not 200")
            # Reachable but refusing to answer (auth, error): still no usable
            # state, so treat it the same as unreachable.
            self._remote_reachable = False
            if allow_clear:
                self.api_output = None
            return

        self._remote_reachable = True
        self.api_output = response_dict

    def parse_remote_output_info(self):
        remote_output_choices = []

        if 'output devices' in self.api_output and self.api_output['output devices']:
            self.output_setup = True
            for each_out in self.api_output['output devices']:
                if ('unique_id' in each_out and
                        'output channels' in self.api_output and
                        self.api_output['output channels']):
                    for each_chan in self.api_output['output channels']:
                        if each_out["unique_id"] == each_chan["output_id"]:
                            name = f'{each_out["name"]}: [{each_out["interface"]}] CH{each_chan["channel"]}'
                            if each_chan['name']:
                                name += f': {each_chan["name"]}'
                            remote_output_choices.append(
                                (f'{each_out["unique_id"]},{each_chan["unique_id"]}', name))

        self.logger.debug(f"Remote Outputs: {remote_output_choices}")

        if self.output_setup:
            for each_chan in channels_dict:
                self.set_custom_channel_option(each_chan, "remote_output_choices", remote_output_choices)

    def parse_output_state_info(self):
        if not self.output_setup:
            self.logger.error("Output not set up, can't parse API info")
            return

        if not self.api_output:
            return

        for each_chan in channels_dict:
            if ('output states' in self.api_output and
                    self.options_channels['remote_output'][each_chan] and
                    ',' in self.options_channels['remote_output'][each_chan]):
                output_unique_id = self.options_channels['remote_output'][each_chan].split(",")[0]
                channel_unique_id = self.options_channels['remote_output'][each_chan].split(",")[1]

                device_channel = self.get_channel_entry_from_id(channel_unique_id)
                if device_channel is None:
                    continue

                if (output_unique_id in self.api_output['output states'] and
                        str(device_channel) in self.api_output['output states'][output_unique_id]):
                    # The remote's reported state is the authoritative report:
                    # route through confirm_command to resolve pending, correct
                    # optimistic state and clear faults (drift correction).
                    remote_state = self.api_output['output states'][output_unique_id][str(device_channel)]
                    if remote_state == "on":
                        self._remote_device_fault.discard(each_chan)
                        self.confirm_command(each_chan, True, 'remote-status')
                    elif remote_state == "off":
                        self._remote_device_fault.discard(each_chan)
                        self.confirm_command(each_chan, False, 'remote-status')
                    elif remote_state == "fault":
                        # The remote AoT reaches us fine but cannot confirm its
                        # OWN device. Passed through as our fault instead of
                        # being dropped: without this the channel would keep
                        # showing its last known on/off, i.e. we would report a
                        # state that the machine actually holding the device has
                        # already declared unknown.
                        self._remote_device_fault.add(each_chan)
                    # 'pending' is transient (a command in flight on the remote)
                    # and resolves to on/off/fault on a later poll — left alone
                    # so a normal command round-trip does not flap the display.

    def send_remote_output(self, channel, state):
        import requests

        if (not self.options_channels['remote_output'][channel] or
                ',' not in self.options_channels['remote_output'][channel]):
            raise RuntimeError("No remote output configured for this channel")

        output_unique_id = self.options_channels['remote_output'][channel].split(",")[0]
        channel_unique_id = self.options_channels['remote_output'][channel].split(",")[1]

        device_channel = self.get_channel_entry_from_id(channel_unique_id)
        if device_channel is None:
            raise RuntimeError("Could not resolve remote output channel")

        endpoint = f'outputs/{output_unique_id}'
        url = 'https://{ip}/api/{ep}'.format(ip=self.host, ep=endpoint)
        headers = {
            'Accept': 'application/vnd.aot.v1+json',
            'X-API-KEY': self.api_key
        }

        data = {
            "channel": device_channel,
            "state": state
        }

        # connect timeout 3 s (fast-fail if host is down),
        # read timeout = self.request_timeout (configurable, default 15 s).
        read_timeout = max(5, int(self.request_timeout or 15))
        try:
            response = requests.post(
                url, json=data, headers=headers, verify=False, timeout=(3, read_timeout))
        except requests.exceptions.RequestException as err:
            self.logger.error(f"Remote output request failed: {err}")
            raise RuntimeError(f"Remote host unreachable: {err}")

        self.logger.debug(f"Response Status: {response.status_code}")
        self.logger.debug(f"Response Headers: {response.headers}")

        try:
            response_dict = json.loads(response.text)
        except:
            response_dict = {}
        self.logger.debug(f"Response Dictionary: {response_dict}")

        if response.status_code != 200:
            detail = response_dict.get('message', response.text[:200])
            self.logger.error(f"Response Status was not 200: {response.status_code} — {detail}")
            raise RuntimeError(f"Remote host returned status {response.status_code}: {detail}")

        if not ('message' in response_dict and 'Success' in response_dict['message']):
            self.logger.error("Did not receive success message from API")
            raise RuntimeError("Remote host did not return a success message")
        # Success: the remote applied the command. State confirmation is handled
        # by the caller (output_switch -> confirm_command).

    def get_channel_entry_from_id(self, channel_id):
        if not self.api_output or 'output channels' not in self.api_output:
            return

        for channel in self.api_output['output channels']:
            if channel_id == channel['unique_id']:
                return channel['channel']

        self.logger.error("Could not determine channel table.")

    def confirmation_capable(self):
        """The remote AoT reports each output's actual state (POST response +
        periodic status poll), so commands are confirmed, not fire-and-forget."""
        return True

    def comm_is_fault(self, output_channel=0):
        """Fault if we cannot reach the remote AoT, or if the remote AoT says it
        cannot reach the device — plus the usual per-command timeout.

        Reaching the remote host successfully is what makes this output "online"
        at the transport level; but a healthy API connection to a machine whose
        own device is offline is still not a working output, so the remote's
        verdict is honoured rather than masked by our successful connection.
        """
        # None = no poll has completed yet. Not a fault: at startup the state
        # thread has simply not run, and reporting every remote output as failed
        # for the first poll interval would be a false alarm.
        if self._remote_reachable is False:
            return True
        if output_channel in self._remote_device_fault:
            return True
        return super().comm_is_fault(output_channel)

    def _resend_command(self, output_channel, intent_state):
        try:
            self.send_remote_output(output_channel, intent_state == 'on')
            return True
        except Exception:
            return False

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        # Returns an opt-in (code, msg) tuple: code 0 = success, 1 = failure.
        # base_output.output_on_off() detects this tuple and propagates a
        # failure return code to the caller (e.g. the timer widget) instead of
        # always reporting success.
        prev_state = bool(self.output_states.get(output_channel) or False)
        try:
            if state == 'on':
                self.send_remote_output(output_channel, True)
            elif state == 'off':
                self.send_remote_output(output_channel, False)
            # POST succeeded -> the remote applied it. Arm the state machine and
            # confirm synchronously (the status poll later corrects any drift).
            self.begin_command(output_channel, state, prev_state, dispatched_ok=True)
            self.confirm_command(output_channel, state == 'on', 'remote-post')
            return 0, "success"
        except Exception as e:
            msg = "State change error: {}".format(e)
            self.logger.exception(msg)
            # Dispatch failed -> no phantom on; leave prior state untouched.
            self.begin_command(output_channel, state, prev_state, dispatched_ok=False)
            return 1, msg

    def is_on(self, output_channel=0):
        if self.is_setup():
            try:
                return self.resolve_is_on(
                    output_channel, bool(self.output_states.get(output_channel) or False))
            except Exception as e:
                self.logger.error("Status check error: {}".format(e))

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        """Called when Output is stopped."""
        if self.is_setup():
            for channel in channels_dict:
                if self.options_channels['state_shutdown'][channel] == 1:
                    self.output_switch('on', output_channel=channel)
                elif self.options_channels['state_shutdown'][channel] == 0:
                    self.output_switch('off', output_channel=channel)
        self.running = False
