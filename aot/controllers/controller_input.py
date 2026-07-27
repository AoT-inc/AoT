# coding=utf-8
#
#
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
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
#  Contact at kylegabriel.com
#
import threading
import time

from aot.controllers.base_controller import AbstractController
from aot.databases.models import (SMTP, Conversion,
                                     DeviceMeasurements, Input, Misc, Output,
                                     OutputChannel)
from aot.inputs.base_input import AbstractInput
from aot.aot_client import DaemonControl
from aot.utils.actions import run_input_actions
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.inputs import parse_input_information, parse_measurement
from aot.utils.lockfile import LockFile
from aot.utils.modules import load_module_from_file


class Measurement:
    """Hold measurement values as a channel-keyed dictionary.

    @phase active
    @stability stable
    @dependency None
    """

    def __init__(self, raw_data):
        self.rawData = raw_data

    @property
    def values(self):
        return self.rawData


class InputController(AbstractController, threading.Thread):
    """Operate input controller with measurement acquisition and pre-output.

    @phase active
    @stability stable
    @dependency AbstractController, AbstractInput, DaemonControl
    """
    def __init__(self, ready, unique_id):
        threading.Thread.__init__(self)
        super().__init__(ready, unique_id=unique_id, name=__name__)

        self.unique_id = unique_id
        self.sample_rate = None
        self.lf = LockFile()

        self.control = DaemonControl()

        self.stop_iteration_counter = 0
        self.measurement = None
        self.measurement_success = False
        self.pause_loop = False
        self.verify_pause_loop = True
        self.dict_inputs = None
        self.device_measurements = None
        self.conversions = None
        self.input_dev = None
        self.input_name = None
        self.log_level_debug = None
        self.gpio_location = None
        self.device = None
        self.interface = None
        self.period = None
        self.start_offset = None

        # Pre-Output: Activates prior to input measurement
        self.pre_output_id = None
        self.pre_output_channel_id = None
        self.pre_output_channel = None
        self.pre_output_duration = None
        self.pre_output_during_measure = None
        self.pre_output_lock_file = None
        self.pre_output_setup = None
        self.last_measurement = None
        self.next_measurement = None
        self.get_new_measurement = None
        self.trigger_cond = None
        self.measurement_acquired = None
        self.pre_output_activated = None
        self.pre_output_timer = None

        # SMTP options
        self.smtp_max_count = None
        self.email_count = None
        self.allowed_to_send_notice = None

        self.i2c_address = None
        self.switch_edge_gpio = None
        self.measure_input = None
        self.device_recognized = None

        self.input_timer = time.time()
        self.lastUpdate = None

        self.has_loop = False
        self.has_listener = False

    def __str__(self):
        return str(self.__class__)

    def loop(self):
        """Acquire measurements at each period with optional pre-output activation."""
        # Pause loop to modify conditional.
        # Prevents execution of conditional while variables are
        # being modified.
        if self.pause_loop:
            self.verify_pause_loop = True
            while self.pause_loop:
                time.sleep(0.1)

        if self.has_loop:
            now = time.time()
            # Signal that a measurement needs to be obtained
            if (now > self.next_measurement and
                    not self.get_new_measurement):

                # Prevent double measurement if previous acquisition of a measurement was delayed
                if self.last_measurement < self.next_measurement:
                    self.get_new_measurement = True
                    self.trigger_cond = True

                # Ensure the next measure event will occur in the future
                while self.next_measurement < now:
                    self.next_measurement += self.period

            # if signaled and a pre output is set up correctly, turn the
            # output on or on for the set duration
            if (self.get_new_measurement and
                    self.pre_output_setup and
                    not self.pre_output_activated):

                if self.lf.lock_acquire(self.pre_output_lock_file, timeout=30):
                    self.pre_output_timer = time.time() + self.pre_output_duration
                    self.pre_output_activated = True

                    # Only run the pre-output before measurement
                    # Turn on for a duration, measure after it turns off
                    if not self.pre_output_during_measure:
                        output_on = threading.Thread(
                            target=self.control.output_on,
                            args=(self.pre_output_id,),
                            kwargs={'output_channel': self.pre_output_channel,
                                    'amount': self.pre_output_duration})
                        output_on.start()

                    # Run the pre-output during the measurement
                    # Just turn on, then off after the measurement
                    else:
                        output_on = threading.Thread(
                            target=self.control.output_on,
                            args=(self.pre_output_id,),
                            kwargs={'output_channel': self.pre_output_channel})
                        output_on.start()
                else:
                    self.logger.error(f"Could not acquire pre-output lock at {self.pre_output_lock_file}")

            # If using a pre output, wait for it to complete before
            # querying the input for a measurement
            if self.get_new_measurement:

                if (self.pre_output_setup and
                        self.pre_output_activated and
                        now > self.pre_output_timer):

                    if self.lf.lock_locked(self.pre_output_lock_file):
                        try:
                            if self.pre_output_during_measure:
                                # Measure then turn off pre-output
                                self.update_measure()
                                output_off = threading.Thread(
                                    target=self.control.output_off,
                                    args=(self.pre_output_id,),
                                    kwargs={'output_channel': self.pre_output_channel})
                                output_off.start()
                            else:
                                # Pre-output has turned off, now measure
                                self.update_measure()
                        finally:
                            self.lf.lock_release(self.pre_output_lock_file)
                    else:
                        self.logger.error(f"Pre-output lock not found at {self.pre_output_lock_file}")

                    self.pre_output_activated = False
                    self.get_new_measurement = False

                elif not self.pre_output_setup:
                    # Pre-output not enabled, just measure
                    self.update_measure()
                    self.get_new_measurement = False

                # Acquiring measurements was successful
                if self.measurement_success:
                    measurements_dict = self.create_measurements_dict()

                    # Run actions
                    message = "Executing actions of Input."
                    message, measurements_dict = run_input_actions(self.unique_id, message, measurements_dict, self.log_level_debug)

                    # Add measurement(s) to influxdb
                    use_same_timestamp = True
                    if ('measurements_use_same_timestamp' in self.dict_inputs[self.device] and
                            not self.dict_inputs[self.device]['measurements_use_same_timestamp']):
                        use_same_timestamp = False

                    add_measurements_influxdb(
                        self.unique_id,
                        measurements_dict,
                        use_same_timestamp=use_same_timestamp)
                    self.measurement_success = False

        self.trigger_cond = False

    def run_finally(self):
        """Stop the input module on controller shutdown."""
        try:
            self.measure_input.stop_input()
        except:
            pass

    def initialize_variables(self):
        """Load input module, configure pre-output, and start listener if available."""
        input_dev = db_retrieve_table_daemon(
            Input, unique_id=self.unique_id)

        self.log_level_debug = input_dev.log_level_debug
        self.set_log_level_debug(self.log_level_debug)

        self.dict_inputs = parse_input_information()

        self.sample_rate = db_retrieve_table_daemon(
            Misc, entry='first').sample_rate_controller_input

        self.device_measurements = db_retrieve_table_daemon(
            DeviceMeasurements).filter(
            DeviceMeasurements.device_id == self.unique_id)

        self.conversions = db_retrieve_table_daemon(Conversion)

        self.input_dev = input_dev
        self.input_name = input_dev.name
        self.unique_id = input_dev.unique_id
        self.gpio_location = input_dev.gpio_location
        self.device = input_dev.device
        self.interface = input_dev.interface
        self.period = input_dev.period
        self.start_offset = input_dev.start_offset

        # Pre-Output (activates output prior to and/or during input measurement)
        self.pre_output_setup = False

        if self.input_dev.pre_output_id and "," in self.input_dev.pre_output_id:
            try:
                self.pre_output_id = input_dev.pre_output_id.split(",")[0]
                self.pre_output_channel_id = input_dev.pre_output_id.split(",")[1]

                self.pre_output_duration = input_dev.pre_output_duration
                self.pre_output_during_measure = input_dev.pre_output_during_measure
                self.pre_output_activated = False
                self.pre_output_timer = time.time()
                self.pre_output_lock_file = f'/var/lock/input_pre_output_{self.pre_output_id}_{self.pre_output_channel_id}'

                # Check if Pre Output and channel IDs exists
                output = db_retrieve_table_daemon(Output, unique_id=self.pre_output_id)
                output_channel = db_retrieve_table_daemon(OutputChannel, unique_id=self.pre_output_channel_id)
                if output and output_channel and self.pre_output_duration:
                    self.pre_output_channel = output_channel.channel
                    self.logger.debug("Pre output successfully set up")
                    self.pre_output_setup = True
            except:
                self.logger.exception("Could not set up pre-output")

        self.last_measurement = 0
        # Reference point for the startup grace period in comm_is_fault() below.
        # last_measurement is 0/falsy until the first successful measurement, so
        # without this a freshly (re)started controller would read as "fault"
        # for every polling Input until it succeeds once — see
        # io_link_health_infra_plan.md 부록3 for the bug this fixes.
        self._comm_ref_ts = time.time()
        self.next_measurement = time.time() + self.start_offset
        self.get_new_measurement = False
        self.trigger_cond = False
        self.measurement_acquired = False

        smtp = db_retrieve_table_daemon(SMTP, entry='first')
        self.smtp_max_count = smtp.hourly_max
        self.email_count = 0
        self.allowed_to_send_notice = True

        # Convert string I2C address to base-16 int
        if self.interface == 'I2C' and self.input_dev.i2c_location:
            self.i2c_address = int(str(self.input_dev.i2c_location), 16)

        self.device_recognized = True

        if self.device in self.dict_inputs:
            input_loaded, status = load_module_from_file(
                self.dict_inputs[self.device]['file_path'], 'inputs')

            if input_loaded:
                self.measure_input = input_loaded.InputModule(self.input_dev)
            self.ready.set()
            self.running = True
        else:
            self.device_recognized = False
            self.ready.set()
            self.running = False
            self.logger.error(f"'{self.device}' is not a valid device type. Deactivating controller.")
            return

        self.input_timer = time.time()
        self.lastUpdate = None

        # Check if get_measurement() has been overwritten
        if type(self.measure_input).get_measurement != AbstractInput.get_measurement:
            self.logger.debug("get_measurement() found")
            self.has_loop = True
        else:
            self.logger.debug("get_measurement() not found")

        # Check if listener() exists
        if hasattr(self.measure_input, 'listener'):
            self.logger.debug("listener() found")
            self.has_listener = True
            self.logger.debug("Starting listener() thread.")
            input_listener = threading.Thread(
                target=self.measure_input.listener)
            input_listener.daemon = True
            input_listener.start()
        else:
            self.logger.debug("listener() not found")

    def update_measure(self):
        """Retrieve measurement from the input module and update state."""
        measurements = None

        if not self.device_recognized:
            self.logger.debug(f"Device not recognized: {self.device}")
            self.measurement_success = False
            return 1

        try:
            # Get measurement from input
            measurements = self.measure_input.next()
            # Reset StopIteration counter on successful read
            if self.stop_iteration_counter:
                self.stop_iteration_counter = 0
        except StopIteration:
            self.stop_iteration_counter += 1
            # Notify after 3 consecutive errors. Prevents filling log
            # with many one-off errors over long periods of time
            if self.stop_iteration_counter > 2:
                self.stop_iteration_counter = 0
                self.logger.error(
                    "StopIteration raised 3 times. Possibly could not read "
                    "input. Ensure it's connected properly and "
                    "detected.")
        except AttributeError:
            self.logger.error(
                "AoT is attempting to acquire measurement(s) from an Input that has already critically errored. "
                "Review the log lines following Input Activation to investigate why this happened.")
        except Exception as except_msg:
            if except_msg == "'NoneType' object has no attribute 'next'":
                self.logger.exception("This Input has already crashed. Look before this message "
                                      "for the relevant error that indicates what the issue was.")
            else:
                self.logger.exception("Error while attempting to read input")

        if self.device_recognized and measurements is not None:
            self.measurement = Measurement(measurements)
            self.last_measurement = time.time()
            self.measurement_success = True
        else:
            self.measurement_success = False

        self.lastUpdate = time.time()

    # ------------------------------------------------------------------ #
    # AbstractBaseController.comm_* interface (protocol-agnostic status)
    # ------------------------------------------------------------------ #
    STALE_FACTOR = 3

    def comm_capable(self):
        if self.has_loop:
            return True
        if self.has_listener and hasattr(self.measure_input, 'comm_capable'):
            try:
                return bool(self.measure_input.comm_capable())
            except Exception:
                return False
        # Listener-type driver not yet retrofitted (io_link_health_infra_plan.md
        # 2.4) — report honestly that we don't know, rather than defaulting to
        # a value that would make every un-retrofitted listener Input look
        # permanently offline.
        return False

    def comm_last_success(self):
        if self.has_loop:
            return self.last_measurement or None
        if self.has_listener and hasattr(self.measure_input, 'comm_last_success'):
            try:
                return self.measure_input.comm_last_success()
            except Exception:
                return None
        return None

    def comm_is_fault(self, channel=None):
        if not self.comm_capable():
            return False
        if not self.has_loop:
            try:
                return bool(self.measure_input.comm_is_fault(channel))
            except Exception:
                return False
        deadline = self.period * self.STALE_FACTOR
        last = self.comm_last_success()
        if last is None:
            # Never succeeded yet — measure the grace period from controller
            # startup, not from a last-success timestamp that doesn't exist.
            return (time.time() - self._comm_ref_ts) > deadline
        return (time.time() - last) > deadline

    def comm_is_pending(self, channel=None):
        # Polling Inputs are synchronous (no in-flight/unconfirmed concept).
        # A retrofitted listener driver may define its own notion of pending.
        if self.has_listener and hasattr(self.measure_input, 'comm_is_pending'):
            try:
                return bool(self.measure_input.comm_is_pending(channel))
            except Exception:
                return False
        return False

    def create_measurements_dict(self):
        """Build a measurements dict with conversions applied for InfluxDB storage."""
        measurements_record = {}
        for each_channel, each_measurement in self.measurement.values.items():
            measurement = self.device_measurements.filter(
                DeviceMeasurements.channel == each_channel).first()

            if measurement and 'value' in each_measurement:
                conversion = self.conversions.filter(
                    Conversion.unique_id == measurement.conversion_id).first()

                # If a timestamp is passed from the module, use it
                if 'timestamp_utc' in each_measurement:
                    timestamp = each_measurement['timestamp_utc']
                else:
                    timestamp = None

                measurements_record = parse_measurement(
                    conversion,
                    measurement,
                    measurements_record,
                    each_channel,
                    each_measurement,
                    timestamp=timestamp)
        return measurements_record

    def force_measurements(self):
        """Signal that a measurement needs to be obtained."""
        self.next_measurement = time.time()
        return 0, "Input instructed to begin acquiring measurements"

    def call_module_function(self, button_id, args_dict, thread=True, return_from_function=False):
        """Execute function from custom action button press."""
        try:
            run_command = getattr(self.measure_input, button_id)
            if not thread or return_from_function:
                return_val = run_command(args_dict)
                if return_from_function:
                    return 0, return_val
                else:
                    return 0, f"Command sent to Input Controller. Returned: {return_val}"
            else:
                thread_run_command = threading.Thread(
                    target=run_command,
                    args=(args_dict,))
                thread_run_command.start()
                return 0, "Command sent to Input Controller and is running in the background."

        except Exception as err:
            msg = f"Error executing function '{button_id}': {err}"
            self.logger.exception(msg)
            return 1, msg

    def pre_stop(self):
        """Executed when the controller is instructed to stop."""
        self.measure_input.pre_stop()
        if self.pre_output_setup:
            output_off = threading.Thread(
                target=self.control.output_off,
                args=(self.pre_output_id,),
                kwargs={'output_channel': self.pre_output_channel})
            output_off.start()
