# coding=utf-8
"""
This module contains the AbstractOutput Class which acts as a template
for all outputs. It is not to be used directly. The AbstractOutput Class
ensures that certain methods and instance variables are included in each
Output.

All Outputs should inherit from this class and overwrite methods that raise
NotImplementedErrors
"""
from datetime import datetime, timezone, timedelta
from aot.utils.time_utils import utc_now

import logging
import threading
import time
import timeit

from sqlalchemy import and_
from sqlalchemy import or_

from aot.controllers.abstract_base_controller import AbstractBaseController
from aot.outputs.confirmable_output import ConfirmableOutputMixin
from aot.databases.models import Output
from aot.databases.models import OutputChannel
from aot.databases.models import Trigger
from aot.aot_client import DaemonControl
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import write_influxdb_value
from aot.utils.execution_context import get_extra_tags
from aot.utils.outputs import output_types


class AbstractOutput(AbstractBaseController, ConfirmableOutputMixin):
    """Abstract base class for all output device drivers.

    @phase active
    @stability stable
    @dependency AbstractBaseController, DaemonControl, ConfirmableOutputMixin
    """
    def __init__(self, output, testing=False, name=__name__):
        if not testing:
            super().__init__(output.unique_id, testing=testing, name=__name__)
        else:
            super().__init__(None, testing=testing, name=__name__)

        # Command-confirmation / latency state machine (dormant for synchronous
        # outputs: no timers arm unless a module calls begin_command()).
        self._confirm_init()

        self.output_setup = False
        self.startup_timer = timeit.default_timer()
        self.control = DaemonControl()

        self.logger = None
        self.setup_logger(testing=testing, name=name, output_dev=output)

        self.OUTPUT_INFORMATION = None
        self.output_time_turned_on = {}
        self.output_on_duration = {}
        self.output_last_duration = {}
        self.output_on_until = {}
        self.output_off_until = {}
        self.output_off_triggered = {}
        self.output_states = {}
        self._started_at_written = {}
        self.output_session_start = {}
        self.output_session_max = {}

        self.output = output
        self.running = True

        # Geo location info for mapping
        self.latitude = getattr(output, 'latitude', None)
        self.longitude = getattr(output, 'longitude', None)
        self.location_source = getattr(output, 'location_source', 'manual')

        if not testing:
            self.output_types = output_types()
            self.unique_id = output.unique_id
            self.output_name = self.output.name
            self.output_type = self.output.output_type

    def __iter__(self):
        """Support the iterator protocol."""
        return self

    def __repr__(self):
        """Representation of object."""
        return_str = f'<{type(self).__name__}'
        return_str += '>'
        return return_str

    def __str__(self):
        """Return measurement information."""
        return_str = ''
        return return_str

    def output_switch(self, state, output_type=None, amount=None, duty_cycle=None, output_channel=None):
        self.logger.error(
            f"{type(self).__name__} did not overwrite the output_switch() method. All "
            "subclasses of the AbstractOutput class are required to overwrite "
            "this method")
        raise NotImplementedError

    def is_on(self, output_channel=None):
        self.logger.error(
            f"{type(self).__name__} did not overwrite the is_on() method. All "
            "subclasses of the AbstractOutput class are required to overwrite "
            "this method")
        raise NotImplementedError

    # is_pending() / is_fault() / resolve_is_on() are provided by
    # ConfirmableOutputMixin. Synchronous outputs never arm the state machine,
    # so is_pending() stays False and is_fault() stays False for them.

    # comm_capable()/comm_is_pending()/comm_is_fault() are also implemented by
    # ConfirmableOutputMixin, but AbstractBaseController (listed BEFORE
    # ConfirmableOutputMixin in this class's bases, see the class line above)
    # already defines those same names with a safe-default stub. Left alone,
    # Python's MRO would resolve self.comm_is_fault() to that stub and never
    # reach the mixin's real implementation — silently defeating the whole
    # link-health feature. These three explicit shims bypass MRO ambiguity by
    # calling the mixin's method directly, unconditionally.
    def comm_capable(self):
        return ConfirmableOutputMixin.comm_capable(self)

    def comm_is_pending(self, output_channel=0):
        return ConfirmableOutputMixin.comm_is_pending(self, output_channel)

    def comm_is_fault(self, output_channel=0):
        return ConfirmableOutputMixin.comm_is_fault(self, output_channel)

    def is_setup(self):
        self.logger.error(
            f"{type(self).__name__} did not overwrite the is_setup() method. All "
            "subclasses of the AbstractOutput class are required to overwrite "
            "this method")
        raise NotImplementedError

    def initialize(self):
        self.logger.error(
            f"{type(self).__name__} did not overwrite the initialize() method. All "
            "subclasses of the AbstractOutput class are required to overwrite "
            "this method")
        raise NotImplementedError

    def stop_output(self):
        """Called when Output is stopped."""
        self.running = False

    def startup_state_is_deferrable(self):
        """True if this driver's Startup State may be sent after boot finishes.

        Opt-in, default False. A driver that says True must apply its Startup
        State through the plain output_switch('on'/'off') contract, because
        OutputController replays it via apply_startup_state() below instead of
        the driver's own initialize().

        Why this exists: OutputController builds outputs one at a time, and a
        driver whose dispatch is globally rate limited (LoRaWAN downlinks share
        one site-wide 4 s slot, aot/utils/lorawan_pacing.py) turns boot into an
        O(N) wait -- measured at ~254 s for 30 outputs, during which no Input
        controller runs and OutputController.loop() has not started, so timed
        outputs get no auto-off supervision either.

        It is opt-in rather than blanket because Startup State is not uniform:
        on_off_gpio writes the pin directly from the option value, so blanking
        it there would drive the pin instead of skipping it.
        """
        return False

    def apply_startup_state(self):
        """Send this output's Startup State. Used for deferred drivers only.

        Mirrors the shape every rate-limited driver uses in initialize():
        1 = on, 0 = off, anything else = do nothing.
        """
        try:
            channels = self.options_channels.get('state_startup') or {}
        except Exception:
            return

        for channel, startup in list(channels.items()):
            if startup == 1:
                state = 'on'
            elif startup == 0:
                state = 'off'
            else:
                continue  # 'Do Nothing' (-1) or suppressed (None)

            try:
                ret = self.output_switch(state, output_channel=channel)
                failed, fail_msg = self._switch_failed(ret)
                if failed:
                    self.logger.error(
                        f"Startup State '{state}' for channel {channel} was not "
                        f"delivered: {fail_msg}")
                    continue
                self.output_states[channel] = (state == 'on')
            except Exception:
                self.logger.exception(
                    f"Applying Startup State for channel {channel}")
                continue

            try:
                if (self.options_channels.get('trigger_functions_startup') or {}).get(channel):
                    self.check_triggers(self.unique_id, output_channel=channel)
            except Exception:
                self.logger.exception(
                    f"Could not check Trigger for channel {channel} of output "
                    f"{self.unique_id}")

    #
    # Do not overwrite the function below
    #

    def init_post(self):
        self.logger.info(f"Initialized in {(timeit.default_timer() - self.startup_timer) * 1000:.1f} ms")

    def setup_logger(self, testing=None, name=None, output_dev=None):
        name = name if name else __name__
        if not testing and output_dev:
            log_name = f"{name}_{output_dev.unique_id.split('-')[0]}"
        else:
            log_name = name
        self.logger = logging.getLogger(log_name)
        if not testing and output_dev:
            if output_dev.log_level_debug:
                self.logger.setLevel(logging.DEBUG)
            else:
                # 시스템 전역 로그 규칙: 장치 단위 INFO/WARNING 은 사용자가
                # log_level_debug 옵션을 켠 경우에만 기록. 기본은 ERROR 이상만 저장.
                self.logger.setLevel(logging.ERROR)

    def setup_on_off_output(self, output_information):
        """Deprecated TODO: Remove."""
        self.setup_output_variables(output_information)

    def setup_output_variables(self, output_information):
        self.OUTPUT_INFORMATION = output_information
        self.output_states = {}
        self.output_off_triggered = {}
        self.output_time_turned_on = {}
        self.output_on_duration = {}
        self.output_last_duration = {}
        self.output_off_until = {}
        self.output_session_start = {}
        self.output_session_max = {}

        if "on_off" in output_information['output_types']:
            self.output_on_until = {}

        for each_output_channel in output_information['channels_dict']:
            self.output_states[each_output_channel] = None
            self.output_off_triggered[each_output_channel] = False
            self.output_time_turned_on[each_output_channel] = None
            self.output_on_duration[each_output_channel] = False
            self.output_last_duration[each_output_channel] = 0
            self.output_off_until[each_output_channel] = 0
            self._started_at_written[each_output_channel] = False
            self.output_session_start[each_output_channel] = None
            self.output_session_max[each_output_channel] = 0

            if "on_off" in output_information['output_types']:
                self.output_on_until[each_output_channel] = utc_now()


    def _write_output_started_at_async(self, output_channel):
        """
        Write an 'output_started_at' point to Influx asynchronously (epoch seconds in value).
        Write to the measurement channel whose unit == 's' to stay consistent with duration_time.
        """
        try:
            measurement_channel = output_channel
            try:
                if ('channels_dict' in self.OUTPUT_INFORMATION and
                        'measurements_dict' in self.OUTPUT_INFORMATION):
                    measurement_channels = self.OUTPUT_INFORMATION['channels_dict'][output_channel]['measurements']
                    for each_measure_channel in measurement_channels:
                        if self.OUTPUT_INFORMATION['measurements_dict'][each_measure_channel]['unit'] == 's':
                            measurement_channel = each_measure_channel
                            break
            except Exception:
                pass

            started_at_utc = utc_now()

            started_epoch = float(int(started_at_utc.timestamp()))
            ctx_tags = get_extra_tags()

            def _writer():
                try:
                    write_influxdb_value(
                        self.unique_id,
                        's',
                        started_epoch,
                        measure='output_started_at',
                        channel=measurement_channel,
                        timestamp=started_at_utc,
                        extra_tags=ctx_tags
                    )
                    if self.logger:
                        self.logger.debug(
                            f"[START_MARK] wrote output_started_at uid={self.unique_id} ch={measurement_channel} epoch={started_epoch}")
                except Exception as e:
                    if self.logger:
                        self.logger.warning(
                            f"Failed to write output_started_at for Output {self.unique_id} CH{measurement_channel}: {e}")

            threading.Thread(target=_writer, daemon=True).start()
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Failed to write output_started_at for Output {self.unique_id} CH{output_channel}: {e}")

    def _ensure_started_marked(self, output_channel):
        """Mark start-time once per ON sequence per channel.

        For confirmation-capable outputs (e.g. LoRaWAN), defer the start marker
        until the device actually confirms the ON — the runtime clock must count
        from the response, not the dispatch. confirm_command() re-invokes this
        once confirmed, at which point confirmation_deferred_start() is False.
        """
        try:
            if self.confirmation_deferred_start(output_channel):
                return
            if not self._started_at_written.get(output_channel):
                self._write_output_started_at_async(output_channel)
                self._started_at_written[output_channel] = True
        except Exception:
            # Don't interrupt main flow if metrics fail
            pass

    def _record_on_duration(self, output_channel, current_time):
        """켜져 있던 시간을 기록하고 세션 장부를 닫는다.

        OFF 경로와 종료(`shutdown`) 경로가 함께 쓴다. 장부를 지우므로 한 세션에
        두 번 부르면 두 번째는 아무것도 하지 않는다 — 중복 기록은 나지 않는다.
        """
        if not (self.output_time_turned_on.get(output_channel) is not None or
                self.output_on_duration.get(output_channel)):
            return False

        duration_sec = None
        timestamp = None

        if self.output_on_duration[output_channel]:
            remaining_time = 0
            if self.output_on_until[output_channel] > current_time:
                remaining_time = (
                    self.output_on_until[output_channel] - current_time).total_seconds()
            duration_sec = (abs(self.output_last_duration[output_channel]) - remaining_time)
            timestamp = (utc_now() - timedelta(seconds=duration_sec))

            # Store negative amount if a negative amount is received
            if self.output_last_duration[output_channel] < 0:
                duration_sec = -duration_sec

            self.output_on_duration[output_channel] = False
            self.output_on_until[output_channel] = current_time
            self.output_session_start[output_channel] = None
            self.output_session_max[output_channel] = 0

        if self.output_time_turned_on[output_channel] is not None:
            # Write the amount the output was ON to the database
            # at the timestamp it turned ON
            duration_sec = (
                current_time - self.output_time_turned_on[output_channel]).total_seconds()
            timestamp = utc_now() - timedelta(seconds=duration_sec)

            self.output_time_turned_on[output_channel] = None

        # determine which measurement of the output_channel is a duration.
        # Some multi-channel MQTT outputs declare channels_dict[0]
        # as a template and register runtime channels 1..N dynamically — a
        # bare channels_dict[output_channel] lookup raises KeyError for any
        # ch>=1 and silently kills the DB-write path. Mirror the ON-side
        # fallback (line 179): default to output_channel so each runtime
        # channel writes a distinct series tag; only override when
        # channels_dict has an explicit per-channel definition.
        measurement_channel = output_channel
        try:
            if ('channels_dict' in self.OUTPUT_INFORMATION and
                    'measurements_dict' in self.OUTPUT_INFORMATION):
                ch_def = self.OUTPUT_INFORMATION['channels_dict'].get(output_channel)
                if ch_def:
                    for each_measure_channel in ch_def.get('measurements', []):
                        if self.OUTPUT_INFORMATION['measurements_dict'][each_measure_channel]['unit'] == 's':
                            measurement_channel = each_measure_channel
                            break
                # else: template-only channels_dict → keep output_channel
                # so per-channel series stays separate.
        except Exception as e:
            self.logger.warning(
                f"measurement_channel resolve failed for ch={output_channel}: {e}")

        write_db = threading.Thread(
            target=write_influxdb_value,
            args=(self.unique_id,
                  's',
                  duration_sec,),
            kwargs={'measure': 'duration_time',
                    'channel': measurement_channel,
                    'timestamp': timestamp,
                    'extra_tags': get_extra_tags()})
        write_db.start()
        return True

    def _shutdown_turns_channel_off(self, output_channel):
        """종료할 때 이 채널이 실제로 꺼지는가(Startup/Shutdown State = Off)."""
        try:
            return self.options_channels['state_shutdown'][output_channel] == 0
        except (AttributeError, KeyError, TypeError):
            return False

    def _record_open_time_before_shutdown(self):
        """데몬이 내려가며 끄는 출력의 개방 시간을 남긴다.

        종료 경로는 드라이버의 `stop_output()` 이 하드웨어를 **직접** 끈다 —
        `output_on_off()` 를 지나지 않으므로 개방 시간을 적는 코드가 돌지 않는다.
        그 결과 재시작을 낀 세션은 조각조각 사라진다.

        실측(2026-08-30 로컬): 12:30~13:00 로 예정된 30분 관수가 12:51 과 12:54
        두 번의 재시작을 거치며 마지막 조각 301초만 기록됐다. 앞의 21분과 3분은
        어디에도 남지 않아, 조회하면 **5분만 물을 준 것으로 보인다.**

        여기서 적는 것은 "직전 명령 이후 실제로 열려 있던 시간"이다. 재시작 뒤
        시퀀스가 남은 시간만큼만 다시 켜므로(`_resync_after_resume`), 조각의
        합이 실제 개방 시간이 된다.

        꺼지지 않는 채널(Shutdown State = On/무변경)은 적지 않는다 — 아직 열려
        있는데 닫혔다고 적으면 그거야말로 틀린 기록이다.
        """
        try:
            channels = list(self.output_time_turned_on.keys())
        except AttributeError:
            return
        current_time = utc_now()
        for output_channel in channels:
            if not self._shutdown_turns_channel_off(output_channel):
                continue
            try:
                if self._record_on_duration(output_channel, current_time):
                    self.logger.info(
                        f"Output {self.unique_id} CH{output_channel} "
                        f"({self.output_name}): 종료로 꺼지기 전까지의 개방 시간을 기록했습니다.")
            except Exception:
                # 기록 실패가 종료를 막아서는 안 된다.
                self.logger.exception(
                    f"Could not record on-time for CH{output_channel} before shutdown")

    def shutdown(self, shutdown_timer):
        self._record_open_time_before_shutdown()
        self.stop_output()
        self.logger.info(f"Stopped in {(timeit.default_timer() - shutdown_timer) * 1000:.1f} ms")

    @staticmethod
    def _switch_failed(out_ret):
        """Opt-in failure signalling from output_switch().

        Modules may return a (code, msg) tuple from output_switch() where a
        non-zero code means the physical command failed (e.g. a remote host was
        unreachable). Legacy modules return a plain string or None and are
        unaffected. Returns (failed: bool, msg: str).
        """
        if (isinstance(out_ret, tuple) and len(out_ret) == 2 and
                isinstance(out_ret[0], int) and out_ret[0] != 0):
            return True, str(out_ret[1])
        return False, ''

    def output_on_off(self,
                      state,
                      output_channel=0,
                      output_type=None,
                      amount=0.0,
                      min_off=0.0,
                      trigger_conditionals=True,
                      additional_options=None):
        """
        Manipulate an output by passing on/off, a volume, or a PWM duty cycle
        to the output module.

        :param state: What state is desired? 'on', 1, True or 'off', 0, False
        :type state: str or int or bool
        :param output_channel: Channel of output
        :type output_channel: int
        :param output_type: The type of output ('sec', 'vol', 'value', 'pwm')
        :type output_type: str
        :param amount: If state is 'on', an amount can be set (e.g. duration to stay on, volume to output, etc.)
        :type amount: float
        :param min_off: Don't allow on again for at least this amount (0 = disabled)
        :type min_off: float
        :param trigger_conditionals: Whether to allow trigger conditionals to act or not
        :type trigger_conditionals: bool
        :param additional_options: dict
        :type additional_options: Additional options passed to the output controller
        """
        msg = ''

        self.logger.debug(
            f"output_on_off({state}, {output_channel}, {output_type}, "
            f"{amount}, {min_off}, {trigger_conditionals})")

        if state not in ['on', 1, True, 'off', 0, False]:
            return 1, 'state not "on", 1, True, "off", 0, or False'
        elif state in ['on', 1, True]:
            state = 'on'
        elif state in ['off', 0, False]:
            state = 'off'

        current_time = utc_now()


        if amount is None:
            amount = 0

        output_is_on = self.is_on(output_channel)

        # Check if output channel exists
        if output_channel not in self.output_states:
            msg = f"Cannot manipulate Output {self.unique_id}: output channel doesn't exist: {output_channel}"
            self.logger.error(msg)
            return 1, msg

        # Check if output is set up
        if not self.is_setup():
            self.logger.debug(f"Output {self.unique_id} not set up. Attempting initialization...")
            self.try_initialize()
            if not self.is_setup():
                msg = f"Cannot manipulate Output {self.unique_id}: Output not set up."
                self.logger.error(msg)
                return 1, msg

        # Do not disturb a command already in flight to a confirmation-capable
        # output: a re-issued *same-direction* command during the pending window
        # (e.g. a PID or bang-bang function firing every period before the slow
        # device has confirmed) would re-anchor timing and stack retransmissions.
        # Ignore it so the in-flight command and its confirm-anchored duration
        # stand. An opposite-direction command (a cancel) is allowed through.
        try:
            if (self.confirmation_capable() and self.is_pending(output_channel) and
                    self.pending_intent(output_channel) == state):
                msg = (f"Output {self.unique_id} CH{output_channel} command "
                       f"'{state}' ignored: identical command already in flight "
                       f"(awaiting device confirmation).")
                self.logger.debug(msg)
                return 0, msg
        except Exception:
            pass

        #
        # Signaled to turn output on
        #
        if state == 'on':

            # Checks if device is not on and is instructed to turn on
            if (output_type in ['sec', None] and
                    self.output_type in self.output_types['on_off'] and
                    not output_is_on):

                # Check if time is greater than off_until to allow an output on.
                # If the output is supposed to be off for a minimum duration and that amount
                # of time has not passed, do not allow the output to be turned on.
                off_until_datetime = self.output_off_until[output_channel]
                if off_until_datetime and off_until_datetime > current_time:
                    off_seconds = (off_until_datetime - current_time).total_seconds()
                    msg = f"Output {self.unique_id} CH{output_channel} ({self.output_name}) " \
                          "instructed to turn on, however the output has been instructed to stay " \
                          f"off for {off_seconds:.2f} more seconds."
                    self.logger.debug(msg)
                    return 1, msg

            # Output type: volt, set amount
            if output_type == 'value' and self.output_type in self.output_types['value']:
                self.output_switch(
                    'on',
                    output_type='value',
                    amount=amount,
                    output_channel=output_channel,
                    additional_options=additional_options)
                self._ensure_started_marked(output_channel)

                msg = f"Command sent: Output {self.unique_id} CH{output_channel} " \
                      f"({self.output_name}) value: {amount:.1f} "

            # Output type: Volume, set amount
            if output_type == 'vol' and self.output_type in self.output_types['volume']:
                self.output_switch(
                    'on',
                    output_type='vol',
                    amount=amount,
                    output_channel=output_channel)

                msg = f"Command sent: Output {self.unique_id} CH{output_channel} " \
                      f"({self.output_name}) volume: {amount:.1f} "

            # Output type: PWM, set duty cycle
            elif output_type == 'pwm' and self.output_type in self.output_types['pwm']:
                out_ret = self.output_switch(
                    'on',
                    output_type='pwm',
                    amount=amount,
                    output_channel=output_channel)

                # Same opt-in (code, msg) contract the on_off path above uses.
                # Without this the PWM path captured out_ret and then reported
                # success regardless, so a module that knew its command had
                # failed (e.g. remote_output_pwm when the host is unreachable)
                # had no way to say so. Legacy modules return a string or None
                # and are unaffected — _switch_failed() only fires on the tuple.
                failed, fail_msg = self._switch_failed(out_ret)
                if failed:
                    self.logger.error(
                        f"Output {self.unique_id} CH{output_channel} ({self.output_name}) "
                        f"failed to set duty cycle: {fail_msg}")
                    return 1, fail_msg

                self._ensure_started_marked(output_channel)

                msg = f"Command sent: Output {self.unique_id} CH{output_channel} ({self.output_name}) " \
                      f"duty cycle: {amount:.2f} %. Output returned: {out_ret}"

            # Output type: On/Off, set duration for on state
            elif (output_type in ['sec', None] and
                    self.output_type in self.output_types['on_off'] and
                    amount != 0):
                # If a minimum off duration is set, determine the time the output is allowed to turn on again
                if min_off:
                    self.output_off_until[output_channel] = (
                        current_time + timedelta(seconds=abs(amount) + min_off))

                # Output is already on for an amount, update duration on with new end time
                if output_is_on and self.output_on_duration[output_channel]:
                    if self.output_on_until[output_channel] > current_time:
                        remaining_time = (
                            self.output_on_until[output_channel] - current_time).total_seconds()
                    else:
                        remaining_time = 0

                    time_on = abs(self.output_last_duration[output_channel]) - remaining_time

                    # Cap the new end time to session_start + session_max to enforce max on duration.
                    # Without this, repeated output_on calls (e.g. from PID each period) extend the
                    # timer indefinitely beyond the configured maximum on duration.
                    session_start = self.output_session_start.get(output_channel)
                    session_max = self.output_session_max.get(output_channel, 0)
                    proposed_until = current_time + timedelta(seconds=abs(amount))
                    if session_start and session_max:
                        hard_limit = session_start + timedelta(seconds=session_max)
                        if proposed_until > hard_limit:
                            proposed_until = hard_limit

                    msg = f"Output {self.unique_id} CH{output_channel} ({self.output_name}) is already on for an " \
                          f"amount of {abs(self.output_last_duration[output_channel]):.2f} seconds " \
                          f"(with {remaining_time:.2f} seconds remaining). Recording the amount of time " \
                          f"the output has been on ({time_on:.2f} sec) and updating the amount " \
                          f"to {abs(amount):.2f} seconds."
                    self.logger.debug(msg)
                    self.output_on_until[output_channel] = proposed_until
                    self.output_last_duration[output_channel] = amount

                    # Write the amount the output was ON to the
                    # database at the timestamp it turned ON
                    if time_on > 0:
                        # Make sure the recorded value is recorded negative
                        # if instructed to do so
                        if self.output_last_duration[output_channel] < 0:
                            duration_on = float(-time_on)
                        else:
                            duration_on = float(time_on)
                        timestamp = utc_now() - timedelta(seconds=abs(duration_on))


                        write_db = threading.Thread(
                            target=write_influxdb_value,
                            args=(self.unique_id,
                                  's',
                                  duration_on,),
                            kwargs={'measure': 'duration_time',
                                    'channel': output_channel,
                                    'timestamp': timestamp,
                                    'extra_tags': get_extra_tags()})
                        write_db.start()

                    return 0, msg

                # Output is on, but not for an amount
                elif output_is_on and not self.output_on_duration[output_channel]:

                    self.output_on_duration[output_channel] = True
                    self.output_on_until[output_channel] = (
                        current_time + timedelta(seconds=abs(amount)))
                    self.output_last_duration[output_channel] = amount
                    msg = f"Output {self.unique_id} CH{output_channel} ({self.output_name}) is " \
                          f"currently on without an amount. Turning into an amount of {abs(amount):.1f} seconds."
                    self.logger.debug(msg)
                    return 0, msg

                # Output is not already on
                else:
                    out_ret = self.output_switch(
                        'on', output_type='sec', amount=amount, output_channel=output_channel)
                    failed, fail_msg = self._switch_failed(out_ret)
                    if failed:
                        self.logger.error(
                            f"Output {self.unique_id} CH{output_channel} ({self.output_name}) "
                            f"failed to turn on: {fail_msg}")
                        return 1, fail_msg
                    self._ensure_started_marked(output_channel)

                    msg = f"Output {self.unique_id} CH{output_channel} ({self.output_name}) " \
                          f"on for {abs(amount):.1f} seconds. Output returned: {out_ret}"
                    self.logger.debug(msg)

                    # Timed-ON auto-off scheduling — three tiers by latency model:
                    #   1) device-timed: the device runs its own N-sec timer (the
                    #      duration was carried in the command); arm NO server off.
                    #   2) confirmation-capable: defer the off to confirm_time + N
                    #      so the device gets >= N sec of *confirmed* on-time (the
                    #      dispatch->ACK latency never truncates the run).
                    #   3) otherwise: dispatch-anchored (legacy behavior).
                    if self.supports_device_duration():
                        self.output_last_duration[output_channel] = amount
                        self.output_on_duration[output_channel] = False
                        self.output_session_start[output_channel] = current_time
                        self.output_session_max[output_channel] = abs(amount)
                    elif self.confirmation_capable():
                        self.defer_duration_to_confirm(output_channel, amount)
                        self.output_last_duration[output_channel] = amount
                        self.output_on_duration[output_channel] = True
                        self.output_session_start[output_channel] = current_time
                        self.output_session_max[output_channel] = abs(amount)
                    else:
                        self.output_on_until[output_channel] = (
                            current_time + timedelta(seconds=abs(amount)))
                        self.output_last_duration[output_channel] = amount
                        self.output_on_duration[output_channel] = True
                        self.output_session_start[output_channel] = current_time
                        self.output_session_max[output_channel] = abs(amount)

            # No duration specific, so just turn output on
            elif ('output_types' in self.OUTPUT_INFORMATION and
                    'on_off' in self.OUTPUT_INFORMATION['output_types'] and
                    amount in [None, 0] and
                    output_type in ['sec', None]):

                try:
                    force_output_channel = self.options_channels["command_force"][output_channel]
                except:
                    force_output_channel = False

                # Don't turn on if already on, except if it can be forced on
                if output_is_on and not force_output_channel:
                    msg = f"Output {self.unique_id} CH{output_channel} ({self.output_name}) is already on."
                    self.logger.debug(msg)
                    return 1, msg
                else:
                    # Record the time the output was turned on in order to
                    # calculate and log the total amount was on, when
                    # it eventually turns off.
                    prev_time_turned_on = self.output_time_turned_on[output_channel]
                    if not self.output_time_turned_on[output_channel]:
                        self.output_time_turned_on[output_channel] = current_time

                    ret_value = self.output_switch(
                        'on', output_channel=output_channel, output_type='sec')

                    failed, fail_msg = self._switch_failed(ret_value)
                    if failed:
                        # Physical command failed: restore the prior on-time
                        # marker so a later successful ON records the correct
                        # duration (and a forced re-send keeps its original time).
                        self.output_time_turned_on[output_channel] = prev_time_turned_on
                        self.logger.error(
                            f"Output {self.unique_id} CH{output_channel} ({self.output_name}) "
                            f"failed to turn on: {fail_msg}")
                        return 1, fail_msg

                    msg = f"Output {self.unique_id} CH{output_channel} ({self.output_name}) " \
                          f"ON at {self.output_time_turned_on[output_channel]}. Output returned: {ret_value}"
                    self.logger.debug(msg)
                    self._ensure_started_marked(output_channel)

        #
        # Signaled to turn output off
        #
        elif state == 'off':

            ret_value = self.output_switch('off', output_type=output_type, output_channel=output_channel)

            failed, fail_msg = self._switch_failed(ret_value)
            if failed:
                # Physical command failed: leave on-time/duration bookkeeping
                # intact (the output is still considered on) and report failure.
                self.logger.error(
                    f"Output {self.unique_id} CH{output_channel} ({self.output_name}) "
                    f"failed to turn off: {fail_msg}")
                return 1, fail_msg

            timestamp = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
            msg = f"Output {self.unique_id} CH{output_channel} ({self.output_name}) " \
                  f"OFF at {timestamp}. Output returned: {ret_value}"
            self.logger.debug(msg)

            # Write output amount to database
            #
            # 확인 가능한 출력에서는 여기가 **아직 꺼진 시점이 아니다.** 큐를
            # 쓰는 전송(LoRaWAN 등)에서 `output_switch` 가 돌려주는 0 은 "사이트
            # 전송 큐가 받아들였다" 는 뜻이고, 실제 전파와 장치 동작은 그 뒤에
            # 온다. 여기서 장부를 닫으면 개방 시간이 실제보다 짧게 남고, 명령이
            # 끝내 전달되지 않은 경우에는 **밸브가 열려 있는데 "껐다" 고
            # 기록된다** — 이 도메인에서 가장 나쁜 기록이다.
            #
            # 그래서 확인이 오는 출력은 `confirm_command()` 가 닫는다(ON 쪽
            # 시계는 이미 그렇게 ACK 에 앵커돼 있다). 확인이 영영 안 오면 장부는
            # 열린 채 남고, 데몬 종료 시 `_record_open_time_before_shutdown()`
            # 이 마지막으로 거둔다. 단방향 출력은 확인해 줄 것이 없으므로
            # 예전처럼 여기서 닫는다.
            if not self.confirmation_capable():
                self._record_on_duration(output_channel, current_time)

            self.output_off_triggered[output_channel] = False
            # Allow next ON to record a fresh start marker
            self._started_at_written[output_channel] = False

        if trigger_conditionals:
            try:
                self.check_triggers(self.unique_id, amount=amount, output_channel=output_channel)
            except Exception as err:
                self.logger.error(
                    f"Could not check Trigger for channel {output_channel} of output {self.unique_id}: {err}")

        return 0, msg

    def check_triggers(self, output_id, amount=None, output_channel=0):
        """
        This function is executed whenever an output is turned on or off
        It is responsible for executing Output Triggers
        """
        output_channel_dev = db_retrieve_table_daemon(OutputChannel).filter(
            and_(OutputChannel.output_id == output_id, OutputChannel.channel == output_channel)).first()
        if output_channel_dev is None:
            self.logger.error("Could not find channel in database")
            return

        #
        # Check On/Off Outputs
        #
        trigger_output = db_retrieve_table_daemon(Trigger)
        trigger_output = trigger_output.filter(Trigger.trigger_type == 'trigger_output')
        trigger_output = trigger_output.filter(Trigger.unique_id_1 == output_id)
        trigger_output = trigger_output.filter(Trigger.unique_id_2 == output_channel_dev.unique_id)
        trigger_output = trigger_output.filter(Trigger.is_activated.is_(True))

        # Find any Output Triggers with the output_id of the output that
        # just changed its state
        if self.is_on(output_channel):
            trigger_output = trigger_output.filter(
                or_(Trigger.output_state == 'on_duration_none',
                    Trigger.output_state == 'on_duration_any',
                    Trigger.output_state == 'on_duration_none_any',
                    Trigger.output_state == 'on_duration_equal',
                    Trigger.output_state == 'on_duration_greater_than',
                    Trigger.output_state == 'on_duration_equal_greater_than',
                    Trigger.output_state == 'on_duration_less_than',
                    Trigger.output_state == 'on_duration_equal_less_than'))

            on_duration_none = and_(
                Trigger.output_state == 'on_duration_none',
                amount == 0.0)

            on_duration_any = and_(
                Trigger.output_state == 'on_duration_any',
                bool(amount))

            on_duration_none_any = Trigger.output_state == 'on_duration_none_any'

            on_duration_equal = and_(
                Trigger.output_state == 'on_duration_equal',
                Trigger.output_duration == amount)

            on_duration_greater_than = and_(
                Trigger.output_state == 'on_duration_greater_than',
                amount > Trigger.output_duration)

            on_duration_equal_greater_than = and_(
                Trigger.output_state == 'on_duration_equal_greater_than',
                amount >= Trigger.output_duration)

            on_duration_less_than = and_(
                Trigger.output_state == 'on_duration_less_than',
                amount < Trigger.output_duration)

            on_duration_equal_less_than = and_(
                Trigger.output_state == 'on_duration_equal_less_than',
                amount <= Trigger.output_duration)

            trigger_output = trigger_output.filter(
                or_(on_duration_none,
                    on_duration_any,
                    on_duration_none_any,
                    on_duration_equal,
                    on_duration_greater_than,
                    on_duration_equal_greater_than,
                    on_duration_less_than,
                    on_duration_equal_less_than))
        else:
            trigger_output = trigger_output.filter(
                Trigger.output_state == 'off')

        # Execute the Trigger Actions for each Output Trigger
        # for this particular Output device
        for each_trigger in trigger_output.all():
            timestamp = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
            message = f"{timestamp}\n[Trigger {each_trigger.unique_id.split('-')[0]} ({each_trigger.name})] " \
                      f"Output {output_id} CH{output_channel} {each_trigger.output_state}"

            self.control.trigger_all_actions(
                each_trigger.unique_id, message=message)

        #
        # Check PWM Outputs
        #
        trigger_output_pwm = db_retrieve_table_daemon(Trigger)
        trigger_output_pwm = trigger_output_pwm.filter(Trigger.trigger_type == 'trigger_output_pwm')
        trigger_output_pwm = trigger_output_pwm.filter(Trigger.unique_id_1 == output_id)
        trigger_output_pwm = trigger_output_pwm.filter(Trigger.unique_id_2 == output_channel_dev.unique_id)
        trigger_output_pwm = trigger_output_pwm.filter(Trigger.is_activated.is_(True))

        # Execute the Trigger Actions for each Output Trigger
        # for this particular Output device
        for each_trigger in trigger_output_pwm.all():
            trigger_trigger = False
            duty_cycle = self.output_state(output_channel)

            if duty_cycle == 'off':
                if (
                        (each_trigger.output_state == 'equal' and
                         each_trigger.output_duty_cycle == 0) or
                        (each_trigger.output_state == 'below' and
                         each_trigger.output_duty_cycle != 0)
                        ):
                    trigger_trigger = True
            elif (
                    (each_trigger.output_state == 'above' and
                     duty_cycle > each_trigger.output_duty_cycle) or
                    (each_trigger.output_state == 'below' and
                     duty_cycle < each_trigger.output_duty_cycle) or
                    (each_trigger.output_state == 'equal' and
                     duty_cycle == each_trigger.output_duty_cycle)
                    ):
                trigger_trigger = True

            if not trigger_trigger:
                continue

            timestamp = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
            message = f"{timestamp}\n[Trigger {each_trigger.unique_id.split('-')[0]} ({each_trigger.name})] " \
                      f"Output {output_id} CH{output_channel} Duty Cycle {duty_cycle} " \
                      f"{each_trigger.output_state} {each_trigger.output_duty_cycle}"

            # Check triggers whenever an output is manipulated
            self.control.trigger_all_actions(each_trigger.unique_id, message=message)

    def output_sec_currently_on(self, output_channel):
        """Return how many seconds an output has been currently on for."""
        if not self.is_on(output_channel):
            return 0
        else:
            now = utc_now()

            sec_currently_on = 0
            if self.output_on_duration[output_channel]:
                left = 0
                if self.output_on_until[output_channel] > now:
                    left = (self.output_on_until[output_channel] - now).total_seconds()
                sec_currently_on = abs(self.output_last_duration[output_channel]) - left
            elif self.output_time_turned_on[output_channel]:
                sec_currently_on = (now - self.output_time_turned_on[output_channel]).total_seconds()
            return sec_currently_on

    def output_state(self, output_channel):
        """
        Return the state of an output

        :param output_channel: Channel of the output
        :type output_channel: int

        :return: "on", "off", "pending", "fault", or duty cycle (for PWM output)
        :rtype: str
        """
        try:
            # comm_is_pending/comm_is_fault (not the bare is_pending/is_fault)
            # so a shared-link fault (io_link_health_infra_plan.md 2.2 — the
            # device is unreachable even with no command currently in flight)
            # reaches this UI-facing state, not just per-command confirmation
            # timeouts. See aot/outputs/confirmable_output.py comm_is_fault().
            #
            # Fault is checked BEFORE pending: a device already known offline
            # stays reported as offline while a new command is in flight to it,
            # instead of briefly looking like a healthy device awaiting its ACK.
            # For a device that is NOT offline, comm_is_fault() is False here, so
            # an ordinary command still shows the usual 'pending'.
            if self.comm_is_fault(output_channel):
                return 'fault'
            if self.comm_is_pending(output_channel):
                return 'pending'
        except Exception:
            pass
        state = self.is_on(output_channel)
        if state is not None:
            if self.output_type in self.output_types['pwm'] + self.output_types['value']:
                if state:
                    return state
                elif state == 0 or state is False:
                    return 'off'
            elif state:
                return 'on'
            else:
                return 'off'

    def set_custom_option(self, option, value):
        return self._set_custom_option(Output, self.unique_id, option, value)

    def get_custom_option(self, option, default_return=None):
        return self._get_custom_option(Output, self.unique_id, option, default_return=default_return)

    def delete_custom_option(self, option):
        return self._delete_custom_option(Output, self.unique_id, option)

    def set_custom_channel_option(self, channel, option, value):
        return self._set_custom_channel_option(Output, self.unique_id, channel, option, value)

    def get_custom_channel_option(self, channel, option):
        return self._get_custom_channel_option(Output, self.unique_id, channel, option)

    def delete_custom_channel_option(self, channel, option):
        return self._delete_custom_channel_option(Output, self.unique_id, channel, option)
