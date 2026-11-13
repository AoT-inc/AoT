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
#
# PID controller code was used from the source below, with modifications.
#
# <http://code.activestate.com/recipes/577231-discrete-pid-controller/>
# Copyright (c) 2010 cnr437@gmail.com
#
# Licensed under the MIT License <http://opensource.org/licenses/MIT>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
import calendar
import math
from aot.utils.timekit import iso_at, utc_now, wall_to_utc

import threading
import time
import timeit

import requests

from aot.config import AOT_DB_PATH
from aot.controllers.base_controller import AbstractController
from aot.databases.models import Conversion
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Misc
from aot.databases.models import OutputChannel
from aot.databases.models import PID
from aot.databases.utils import session_scope
from aot.aot_client import DaemonControl
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.influx import read_influxdb_single
from aot.utils.influx import write_influxdb_value
from aot.utils.method import load_method_handler, parse_db_time
from aot.utils.outputs import parse_output_information
from aot.utils.pid_controller_default import PIDControl
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info


# 주기 기본값·하한(초). 폼은 1~86400 만 받지만 위젯 경로·API·옛 DB 값은 0 이하나
# 비수(非數)가 저장돼 있을 수 있다. 0 이면 격자를 앞으로 미는 `while` 이 끝나지 않는다.
PERIOD_DEFAULT_S = 30.0
PERIOD_MIN_S = 1.0


def safe_period(value):
    """저장된 주기를 격자에 쓸 수 있는 값으로 바꾼다.

    0 이하·비수·None 은 기본값(30초), 0 < 값 < 1 은 하한(1초)으로 올린다.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return PERIOD_DEFAULT_S
    if not math.isfinite(number) or number <= 0:
        return PERIOD_DEFAULT_S
    return max(number, PERIOD_MIN_S)


class PIDController(AbstractController, threading.Thread):
    """Operate discrete PID controller for process automation.

    Implements a discrete PID controller that reads measurements from an input
    sensor and adjusts output devices to maintain a setpoint. Supports both
    raise and lower output directions with configurable output types.

    @phase active
    @stability stable
    @dependency AbstractController, PID, DeviceMeasurements, DaemonControl
    """
    def __init__(self, ready, unique_id):
        threading.Thread.__init__(self)
        super().__init__(ready, unique_id=unique_id, name=__name__)

        self.unique_id = unique_id
        self.sample_rate = None
        self.dict_outputs = None

        self.control = DaemonControl()

        self.PID_Controller = None
        self.setpoint = None

        self.device_measurements = None
        self.device_id = None
        self.measurement_id = None
        self.log_level_debug = None
        self.last_time = None
        self.last_measurement = None
        self.last_measurement_success = False
        self.is_activated = None
        self.is_held = None
        self.is_paused = None
        self.measurement = None
        self.setpoint_tracking_type = None
        self.setpoint_tracking_id = None
        self.setpoint_tracking_max_age = None
        self.raise_output_id = None
        self.raise_output_channel_id = None
        self.raise_output_channel = None
        self.raise_output_type = None
        self.raise_min_duration = None
        self.raise_max_duration = None
        self.raise_min_off_duration = None
        self.raise_always_min_pwm = None
        self.lower_output_id = None
        self.lower_output_channel_id = None
        self.lower_output_channel = None
        self.lower_output_type = None
        self.lower_min_duration = None
        self.lower_max_duration = None
        self.lower_min_off_duration = None
        self.lower_always_min_pwm = None
        self.period = 0
        self.start_offset = 0
        self.max_measure_age = None
        self.send_lower_as_negative = None
        self.store_lower_as_negative = None
        self.timer = 0     # time.monotonic() 기준 — 벽시계가 움직여도 격자는 그대로
        self._last_run_mono = None
        self._integrated_sample = None   # 마지막으로 적분에 더한 (시각, 값)
        self._cycle_abort = False
        self._cycle_setpoint = None
        self._bad_period_logged = None

        # Check if a method is set for this PID
        self.method_type = None
        self.method_start_time = None
        self.method_end_time = None
        self._facility_tz = None

    def _period_s(self):
        """격자에 쓰는 주기(초) — 항상 1초 이상의 유한한 값."""
        return safe_period(self.period)

    def _start_offset_s(self):
        """첫 실행까지 미루는 초 — 음수·비수·무한은 0(곧바로).

        비수(NaN)를 단조 시계에 더하면 `now > self.timer` 가 영영 거짓이라 PID 가
        조용히 한 번도 돌지 않는다.
        """
        try:
            offset = float(self.start_offset or 0)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(offset) or offset < 0:
            return 0.0
        return offset

    def seconds_until_due(self):
        """다음 주기까지 남은 초(단조 시계) — 기반 루프가 이때 깨어난다."""
        if not self.timer:
            return None
        return self.timer - time.monotonic()

    def loop(self):
        now = time.monotonic()
        if now > self.timer:
            period = self._period_s()
            if self._bad_period_logged != self.period and period != self.period:
                self._bad_period_logged = self.period
                self.logger.error(
                    f"PID 주기 {self.period!r} 는 쓸 수 없다 — {period}초로 돈다. "
                    f"설정에서 1~86400 초 사이로 고쳐야 한다")
            # 밀린 주기는 몰아서 실행하지 않고 격자만 따라잡는다.
            while now > self.timer:
                self.timer = self.timer + period
            self.run_cycle()

    def run_cycle(self):
        """한 주기: 읽기 단계만 재시도하고, 계산·출력 단계는 한 번만 한다.

        재시도(`attempt_execute`)가 계산 단계까지 감싸면 출력 단계 예외 한 번에
        적분이 두 번 이상 쌓인다.
        """
        self.attempt_execute(self.read_phase)
        try:
            self.control_phase()
        except Exception:
            self.logger.exception(
                "PID 계산·출력 단계 실패 — 같은 주기 안에서 다시 하지 않는다")
        self._last_run_mono = time.monotonic()

    def run_finally(self):
        # Turn off output used in PID when the controller is deactivated
        if self.raise_output_id and self.PID_Controller.direction in ['raise', 'both']:
            self.control.output_off(
                self.raise_output_id, output_channel=self.raise_output_channel, trigger_conditionals=True)
        if self.lower_output_id and self.PID_Controller.direction in ['lower', 'both']:
            self.control.output_off(
                self.lower_output_id, output_channel=self.lower_output_channel, trigger_conditionals=True)

    def initialize_variables(self):
        """Set PID parameters."""
        self.dict_outputs = parse_output_information()

        self.sample_rate = db_retrieve_table_daemon(Misc, entry='first').sample_rate_controller_pid

        self.device_measurements = db_retrieve_table_daemon(DeviceMeasurements)

        pid = db_retrieve_table_daemon(PID, unique_id=self.unique_id)

        self.log_level_debug = pid.log_level_debug
        self.set_log_level_debug(self.log_level_debug)

        self.device_id = pid.measurement.split(',')[0]
        self.measurement_id = pid.measurement.split(',')[1]
        self.is_activated = pid.is_activated
        self.is_held = pid.is_held
        self.is_paused = pid.is_paused
        if self.is_held and self.is_paused:
            # 옛 DB 에서 두 플래그가 같이 켜진 경우 — 둘은 배타다. 출력을 멈추는
            # 쪽(일시정지)이 안전하다.
            self.is_held = False
        self.setpoint_tracking_type = pid.setpoint_tracking_type
        self.setpoint_tracking_id = pid.setpoint_tracking_id
        self.setpoint_tracking_max_age = pid.setpoint_tracking_max_age
        if pid.raise_output_id and "," in pid.raise_output_id:
            self.raise_output_id = pid.raise_output_id.split(",")[0]
            self.raise_output_channel_id = pid.raise_output_id.split(",")[1]
            output_channel = db_retrieve_table_daemon(
                OutputChannel, unique_id=self.raise_output_channel_id)
            if output_channel is not None:
                self.raise_output_channel = output_channel.channel
            else:
                self.logger.error(
                    f"Raise output channel '{self.raise_output_channel_id}' not found. "
                    f"The referenced output may have been deleted. Check the PID's Raise Output setting.")
        self.raise_output_type = pid.raise_output_type
        self.raise_min_duration = pid.raise_min_duration
        self.raise_max_duration = pid.raise_max_duration
        self.raise_min_off_duration = pid.raise_min_off_duration
        self.raise_always_min_pwm = pid.raise_always_min_pwm
        if pid.lower_output_id and "," in pid.lower_output_id:
            self.lower_output_id = pid.lower_output_id.split(",")[0]
            self.lower_output_channel_id = pid.lower_output_id.split(",")[1]
            output_channel = db_retrieve_table_daemon(
                OutputChannel, unique_id=self.lower_output_channel_id)
            if output_channel is not None:
                self.lower_output_channel = output_channel.channel
            else:
                self.logger.error(
                    f"Lower output channel '{self.lower_output_channel_id}' not found. "
                    f"The referenced output may have been deleted. Check the PID's Lower Output setting.")
        self.lower_output_type = pid.lower_output_type
        self.lower_min_duration = pid.lower_min_duration
        self.lower_max_duration = pid.lower_max_duration
        self.lower_min_off_duration = pid.lower_min_off_duration
        self.lower_always_min_pwm = pid.lower_always_min_pwm
        self.period = pid.period
        self.start_offset = pid.start_offset
        self.max_measure_age = pid.max_measure_age
        self.send_lower_as_negative = pid.send_lower_as_negative
        self.store_lower_as_negative = pid.store_lower_as_negative
        self.timer = time.monotonic() + self._start_offset_s()
        self.setpoint = pid.setpoint

        # Initialize PID Controller
        if self.PID_Controller is None:
            self.PID_Controller = PIDControl(
                self.logger, pid.setpoint, pid.p, pid.i, pid.d, pid.direction,
                pid.band, pid.integrator_min, pid.integrator_max)
        else:
            # Set PID options
            self.PID_Controller.setpoint = pid.setpoint
            self.PID_Controller.Kp = pid.p
            self.PID_Controller.Ki = pid.i
            self.PID_Controller.Kd = pid.d
            self.PID_Controller.direction = pid.direction
            self.PID_Controller.band = pid.band
            self.PID_Controller.integrator_min = pid.integrator_min
            self.PID_Controller.integrator_max = pid.integrator_max
            self.PID_Controller.first_start = True

        self.PID_Controller.output_min, self.PID_Controller.output_max = \
            self._output_limits()

        # Cache facility timezone for DailyMultiPoint method time-of-day calculation
        self._facility_tz = self._resolve_facility_tz(pid)

        if self.setpoint_tracking_type == 'method' and self.setpoint_tracking_id != '':
            self.setup_method(self.setpoint_tracking_id)

        if self.is_paused:
            self.logger.info("Starting Paused")
        elif self.is_held:
            self.logger.info("Starting Held")

        self.logger.info(f"PID Settings: {self.pid_parameters_str()}")

        self.ready.set()
        self.running = True

        return "success"

    def check_pid(self):
        """한 주기를 재시도 없이 실행한다(시험·수동 호출용)."""
        self.read_phase()
        self.control_phase()

    def read_phase(self):
        """읽기 단계 — 측정값과 설정점 입력만 읽는다. 재시도해도 부작용이 없다.

        일시정지면 아무것도 읽지 않는다. 유지(hold)는 측정값만 읽는다 —
        계산은 멈추되 센서가 죽었는데 옛 제어 변수를 계속 내보내지 않으려는 것이다.
        """
        self._cycle_abort = False
        self._cycle_setpoint = None
        if not self.is_activated or self.is_paused:
            return

        self.get_last_measurement_pid()
        if self.is_held or not self.last_measurement_success:
            return

        if self.setpoint_tracking_type == 'method' and self.setpoint_tracking_id != '':
            this_pid = db_retrieve_table_daemon(PID, unique_id=self.unique_id)
            if this_pid is None:
                # 설정을 못 읽은 사이클은 건너뛴다 — 옛 설정으로 계속
                # 제어하는 편이 엉뚱한 값으로 움직이는 것보다 낫다.
                self.logger.error(
                    "PID 설정을 읽지 못해 이번 설정점 추종을 건너뛴다")
                self._cycle_abort = True
                return

            now = utc_now()
            method = load_method_handler(self.setpoint_tracking_id, self.logger,
                                         target_id=self.unique_id)
            if method.method_type == 'DailyMultiPoint':
                weeks_elapsed = self._get_weeks_elapsed(this_pid.method_start_time)
                new_setpoint, ended = method.calculate_setpoint(
                    now, this_pid.method_start_time,
                    weeks_elapsed=weeks_elapsed,
                    facility_tz=self._facility_tz)
            else:
                new_setpoint, ended = method.calculate_setpoint(now, this_pid.method_start_time)
            self.logger.debug(f"Method {self.setpoint_tracking_id} {method} {now} {this_pid.method_start_time}")
            self._cycle_setpoint = ('method', new_setpoint, ended)

        elif self.setpoint_tracking_type == 'input-math' and self.setpoint_tracking_id != '':
            # Update setpoint using an Input
            device_id = self.setpoint_tracking_id.split(',')[0]
            measurement_id = self.setpoint_tracking_id.split(',')[1]

            measurement = get_measurement(measurement_id)
            if not measurement:
                self._cycle_abort = True
                return

            conversion = db_retrieve_table_daemon(
                Conversion, unique_id=measurement.conversion_id)
            channel, unit, measurement = return_measurement_info(
                measurement, conversion)

            last_measurement = read_influxdb_single(
                device_id,
                unit,
                channel,
                measure=measurement,
                duration_sec=self.setpoint_tracking_max_age,
                value='LAST')

            if last_measurement[1] is not None:
                self._cycle_setpoint = ('input', last_measurement[1], False)
            else:
                self.logger.debug(
                    "Could not find measurement for Setpoint "
                    f"Tracking. Max Age of {self.setpoint_tracking_max_age} exceeded for measuring "
                    f"device ID {device_id} (measurement {measurement_id})")
                self._cycle_setpoint = ('input', None, False)

    def control_phase(self):
        """계산·출력 단계 — 주기당 한 번만 실행한다(재시도 없음).

        - 일시정지: 측정·적분·출력 모두 하지 않는다(출력은 pid_pause 가 한 번 끈다).
        - 유지: 적분과 제어 변수를 얼리고, 측정값이 신선할 때만 마지막 출력을 반복한다.
        - 같은 측정 표본은 적분에 한 번만 더한다.
        """
        if self._cycle_abort or not self.is_activated or self.is_paused:
            return

        if not self.is_held and self.last_measurement_success:
            self._apply_cycle_setpoint()

            sample = (self.last_time, self.last_measurement)
            new_sample = sample != self._integrated_sample
            # Calculate new control variable (output) from PID Controller
            self.PID_Controller.update_pid_output(
                self.last_measurement, new_sample=new_sample)
            self._integrated_sample = sample

            self.write_pid_values()  # Write variables to database

        # Is PID in a state that allows manipulation of outputs
        if self.PID_Controller.setpoint is not None:
            if not self.raise_output_id and not self.lower_output_id:
                # Calculation-only mode: no output device configured.
                # Write the raw control variable to channel 9 (unitless/none)
                # so other functions/conditionals can consume it.
                if self.last_measurement_success and self.PID_Controller.control_variable is not None:
                    self.write_pid_output_influxdb(
                        'none', 'unitless', 9, self.PID_Controller.control_variable)
            else:
                self.manipulate_output()

    def _apply_cycle_setpoint(self):
        """읽기 단계에서 구한 설정점을 적용한다(방법 종료 처리는 부작용이라 여기서)."""
        if self._cycle_setpoint is None:
            return
        kind, value, ended = self._cycle_setpoint
        if kind == 'method':
            if ended:
                # point in time is out of method range
                with session_scope(AOT_DB_PATH) as db_session:
                    # Overwrite this_controller with committable connection
                    this_pid = db_session.query(PID).filter(
                        PID.unique_id == self.unique_id).first()

                    self.logger.debug("Ended")
                    # Duration method has ended, reset method_start_time locally and in DB
                    this_pid.method_start_time = None
                    this_pid.method_end_time = None
                    this_pid.is_activated = False
                    db_session.commit()

                    self.is_activated = False
                    self.stop_controller()

                    db_session.commit()

            if value is not None:
                self.logger.debug(f"New setpoint = {value} {ended}")
                self.PID_Controller.setpoint = value
            else:
                self.logger.debug(f"New setpoint = default {self.setpoint} {ended}")
                self.PID_Controller.setpoint = self.setpoint
        else:
            self.PID_Controller.setpoint = value

    def _output_limits(self):
        """제어 변수의 (하한, 상한) — 조건부 적분의 근거. None 은 한계 없음.

        출력 설정에서 구한다: 한쪽 방향 출력이 없으면 그쪽 제어 변수는 아무 일도
        안 하므로 0 이 한계다. 출력이 하나도 없는 계산 전용 모드는 한계가 없다.
        """
        direction = self.PID_Controller.direction
        has_raise = direction in ('raise', 'both') and bool(self.raise_output_id)
        has_lower = direction in ('lower', 'both') and bool(self.lower_output_id)
        if not has_raise and not has_lower:
            return None, None
        period = self._period_s()

        def cap(output_type, max_duration):
            if output_type == 'pwm':
                duty = 100.0
                if max_duration:
                    duty = min(duty, float(max_duration))
                return duty / 100.0 * period
            return float(max_duration) if max_duration else None

        high = cap(self.raise_output_type, self.raise_max_duration) if has_raise else 0.0
        low = 0.0
        if has_lower:
            lower_cap = cap(self.lower_output_type, self.lower_max_duration)
            low = -lower_cap if lower_cap is not None else None
        return low, high

    def setup_method(self, method_id):
        """Initialize method variables to start running a method."""
        self.setpoint_tracking_id = ''

        method = load_method_handler(method_id, self.logger, target_id=self.unique_id)

        this_controller = db_retrieve_table_daemon(PID, unique_id=self.unique_id)
        self.method_type = method.method_type

        if parse_db_time(this_controller.method_start_time) is None:
            self.method_start_time = utc_now()

            self.method_end_time = method.determine_end_time(self.method_start_time)

            self.logger.info(f"Starting method {self.method_start_time} {self.method_end_time}")

            with session_scope(AOT_DB_PATH) as db_session:
                this_controller = db_session.query(PID)
                this_controller = this_controller.filter(PID.unique_id == self.unique_id).first()
                this_controller.method_start_time = self.method_start_time
                this_controller.method_end_time = self.method_end_time
                db_session.commit()
        else:
            # already running, potentially the daemon has been restarted
            self.method_start_time = this_controller.method_start_time
            self.method_end_time = this_controller.method_end_time

        self.setpoint_tracking_id = method_id
        self.logger.debug(f"Method enabled: {self.setpoint_tracking_id}")

    def stop_method(self):
        self.method_start_time = None
        self.method_end_time = None
        with session_scope(AOT_DB_PATH) as db_session:
            this_controller = db_session.query(PID)
            this_controller = this_controller.filter(PID.unique_id == self.unique_id).first()
            this_controller.is_activated = False
            this_controller.method_start_time = None
            this_controller.method_end_time = None
            db_session.commit()
        self.stop_controller()
        self.is_activated = False
        self.logger.warning(
            "Method has ended. "
            "Activate the Trigger controller to start it again.")

    def _resolve_facility_tz(self, pid_row=None):
        """Return pytz timezone from PID's timezone/latitude/longitude fields.

        Falls back to system timezone if PID has no location data.
        Returns None only when no timezone can be resolved anywhere.
        """
        try:
            from aot.utils.timekit import tz_of
            row = pid_row
            if row is None:
                row = db_retrieve_table_daemon(PID, unique_id=self.unique_id)
            tz = tz_of(row)
            return tz if tz else None
        except Exception as exc:
            self.logger.warning(f'PID _resolve_facility_tz: {exc}')
            return None

    def _get_weeks_elapsed(self, method_start_raw) -> float:
        """Return fractional weeks elapsed for DailyMultiPoint keyframe progression.

        우선순위:
          1. PID.schedule_start_time — 사용자가 설정한 재배 시작일(env_coordinator와 동일 로직).
             날짜만 입력(YYYY-MM-DD)이면 장치 위치 시간대 자정으로 해석.
          2. method_start_time — schedule_start_time 미설정 시 method 최초 활성화 시각 사용.
        """
        import re as _re
        from datetime import timezone as _tz

        # ── 1. schedule_start_time 우선 (env_coordinator 동일 로직) ──────────
        pid_row = db_retrieve_table_daemon(PID, unique_id=self.unique_id)
        start_raw = (getattr(pid_row, 'schedule_start_time', None) or '').strip()
        week_offset = float(getattr(pid_row, 'schedule_week_offset', 0.0) or 0.0)

        if start_raw:
            try:
                from dateutil.parser import isoparse
                date_only = bool(_re.fullmatch(r'\d{4}-\d{2}-\d{2}', start_raw))
                fac_tz = self._facility_tz

                if date_only:
                    if fac_tz is None:
                        self.logger.warning(
                            'PID _get_weeks_elapsed: 장치 위치 좌표 없음 — '
                            'schedule_start_time 시간대 결정 불가.')
                        return 0.0
                    import datetime as _datetime
                    year, month, day = map(int, start_raw.split('-'))
                    local_midnight = _datetime.datetime(year, month, day, 0, 0, 0)
                    start_dt = wall_to_utc(local_midnight, fac_tz)
                else:
                    start_dt = isoparse(start_raw)
                    if start_dt.tzinfo is None:
                        if fac_tz is not None:
                            start_dt = wall_to_utc(start_dt, fac_tz)
                        else:
                            start_dt = start_dt.replace(tzinfo=_tz.utc)

                elapsed_sec = (utc_now() - start_dt).total_seconds()
                return max(0.0, elapsed_sec / (7 * 86400) + week_offset)
            except Exception as exc:
                self.logger.warning(f'PID _get_weeks_elapsed (schedule): {exc}')
                return 0.0

        # ── 2. fallback: method_start_time (method 최초 활성화 시각 = week 0) ─
        if not method_start_raw:
            return 0.0
        try:
            start_dt = parse_db_time(str(method_start_raw))
            if start_dt is None:
                return 0.0
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=_tz.utc)
            elapsed_sec = (utc_now() - start_dt).total_seconds()
            return max(0.0, elapsed_sec / (7 * 86400) + week_offset)
        except Exception as exc:
            self.logger.warning(f'PID _get_weeks_elapsed (method_start): {exc}')
            return 0.0

    def write_pid_values(self):
        """Write PID values to the measurement database"""
        if self.PID_Controller.band:
            setpoint_band_lower = self.PID_Controller.setpoint - self.PID_Controller.band
            setpoint_band_upper = self.PID_Controller.setpoint + self.PID_Controller.band
        else:
            setpoint_band_lower = None
            setpoint_band_upper = None

        list_measurements = [
            self.PID_Controller.setpoint,
            setpoint_band_lower,
            setpoint_band_upper,
            self.PID_Controller.P_value,
            self.PID_Controller.I_value,
            self.PID_Controller.D_value
        ]

        measurement_dict = {}
        measurements = self.device_measurements.filter(
            DeviceMeasurements.device_id == self.unique_id).all()
        for each_channel, each_measurement in enumerate(measurements):
            if (each_measurement.channel not in measurement_dict and
                    each_measurement.channel < len(list_measurements)):

                # If setpoint, get unit from PID measurement
                if each_measurement.measurement_type == 'setpoint':
                    setpoint_pid = db_retrieve_table_daemon(
                        PID, unique_id=each_measurement.device_id)
                    if setpoint_pid and ',' in setpoint_pid.measurement:
                        pid_measurement = setpoint_pid.measurement.split(',')[1]
                        setpoint_measurement = db_retrieve_table_daemon(DeviceMeasurements, unique_id=pid_measurement)
                        if setpoint_measurement:
                            conversion = db_retrieve_table_daemon(
                                Conversion, unique_id=setpoint_measurement.conversion_id)
                            _, unit, _ = return_measurement_info(
                                setpoint_measurement, conversion)
                            measurement_dict[each_channel] = {
                                'measurement': each_measurement.measurement,
                                'unit': unit,
                                'value': list_measurements[each_channel]
                            }
                else:
                    measurement_dict[each_channel] = {
                        'measurement': each_measurement.measurement,
                        'unit': each_measurement.unit,
                        'value': list_measurements[each_channel]
                    }

        add_measurements_influxdb(self.unique_id, measurement_dict)

    def get_last_measurement_pid(self):
        """
        Retrieve the latest input measurement from InfluxDB

        :rtype: None
        """
        self.last_measurement_success = False

        # Get latest measurement from influxdb
        try:
            device_measurement = get_measurement(self.measurement_id)

            if device_measurement:
                conversion = db_retrieve_table_daemon(
                    Conversion, unique_id=device_measurement.conversion_id)
            else:
                conversion = None
            channel, unit, measurement = return_measurement_info(
                device_measurement, conversion)

            last_measurement = read_influxdb_single(
                self.device_id,
                unit,
                channel,
                measure=measurement,
                duration_sec=int(self.max_measure_age),
                value='LAST')

            if last_measurement and last_measurement[0] is not None and last_measurement[1] is not None:
                # read_influxdb_single 은 초 단위 epoch 를 돌려준다(예전 `/ 1000` 은
                # 1970년 1월로 만들었다). 같은 표본인지 가르는 열쇠이기도 하다.
                self.last_time = float(last_measurement[0])
                self.last_measurement = last_measurement[1]

                local_timestamp = iso_at(self.last_time, self._facility_tz)
                self.logger.debug(f"Latest (CH{channel}, Unit: {unit}): {self.last_measurement} @ {local_timestamp}")
                self.last_measurement_success = True
            else:
                self.logger.debug("No data from the specified time period returned from influxdb")
        except requests.ConnectionError:
            self.logger.error("Failed to read measurement from the influxdb database: Could not connect.")
        except Exception:
            self.logger.exception(
                "Exception while reading measurement from the influxdb database")

    def manipulate_output(self):
        """
        Activate output based on PID control variable and whether
        the manipulation directive is to raise, lower, or both.

        :rtype: None
        """
        # If the last measurement was able to be retrieved and was entered within the past minute
        if self.last_measurement_success:
            #
            # PID control variable is positive, indicating a desire to raise
            # the environmental condition
            #
            if self.PID_Controller.direction in ['raise', 'both'] and self.raise_output_id:

                if self.PID_Controller.control_variable > 0:

                    if self.raise_output_type == 'pwm':
                        raise_duty_cycle = self.control_var_to_duty_cycle(
                            self.PID_Controller.control_variable)

                        # Ensure the duty cycle doesn't exceed the min/max
                        if (self.raise_max_duration and
                                raise_duty_cycle > self.raise_max_duration):
                            raise_duty_cycle = self.raise_max_duration
                        elif (self.raise_min_duration and
                                raise_duty_cycle < self.raise_min_duration):
                            raise_duty_cycle = self.raise_min_duration

                        self.logger.debug(
                            f"Setpoint: {self.PID_Controller.setpoint}, "
                            f"Control Variable: {self.PID_Controller.control_variable}, "
                            f"Output: PWM output {self.raise_output_id} "
                            f"CH{self.raise_output_channel} to {raise_duty_cycle:.1f}%")

                        # Activate pwm with calculated duty cycle
                        self.control.output_on(
                            self.raise_output_id,
                            output_type='pwm',
                            amount=raise_duty_cycle,
                            output_channel=self.raise_output_channel)

                        self.write_pid_output_influxdb(
                            'percent', 'duty_cycle', 7,
                            self.control_var_to_duty_cycle(self.PID_Controller.control_variable))

                    elif self.raise_output_type == 'on_off':
                        raise_seconds_on = self.PID_Controller.control_variable

                        # Ensure the output on duration doesn't exceed the set maximum
                        if (self.raise_max_duration and
                                raise_seconds_on > self.raise_max_duration):
                            raise_seconds_on = self.raise_max_duration

                        if raise_seconds_on >= self.raise_min_duration:
                            # Activate raise_output for a duration
                            self.logger.debug(
                                f"Setpoint: {self.PID_Controller.setpoint} "
                                f"Output: {self.PID_Controller.control_variable} sec to "
                                f"output {self.raise_output_id} CH{self.raise_output_channel}")

                            self.control.output_on(
                                self.raise_output_id,
                                output_type='sec',
                                amount=raise_seconds_on,
                                min_off=self.raise_min_off_duration,
                                output_channel=self.raise_output_channel)

                        self.write_pid_output_influxdb(
                            's', 'duration_time', 6, self.PID_Controller.control_variable)

                    elif self.raise_output_type == 'value':
                        raise_value = self.PID_Controller.control_variable

                        # Ensure the duty cycle doesn't exceed the min/max
                        if (self.raise_max_duration and
                                raise_value > self.raise_max_duration):
                            raise_value = self.raise_max_duration

                        if raise_value >= self.raise_min_duration:
                            # Activate raise_output for a value
                            self.logger.debug(
                                f"Setpoint: {self.PID_Controller.setpoint} "
                                f"Output: {self.PID_Controller.control_variable} to "
                                f"output {self.raise_output_id} CH{self.raise_output_channel}")

                            self.control.output_on(
                                self.raise_output_id,
                                output_type='value',
                                amount=raise_value,
                                min_off=self.raise_min_off_duration,
                                output_channel=self.raise_output_channel)

                        self.write_pid_output_influxdb(
                            'none', 'unitless', 9, raise_value)

                    elif self.raise_output_type == 'volume':
                        raise_volume = self.PID_Controller.control_variable

                        # Ensure the duty cycle doesn't exceed the min/max
                        if (self.raise_max_duration and
                                raise_volume > self.raise_max_duration):
                            raise_volume = self.raise_max_duration

                        if raise_volume >= self.raise_min_duration:
                            # Activate raise_output for a volume (ml)
                            self.logger.debug(
                                f"Setpoint: {self.PID_Controller.setpoint} "
                                f"Output: {self.PID_Controller.control_variable} ml to "
                                f"output {self.raise_output_id} CH{self.raise_output_channel}")

                            self.control.output_on(
                                self.raise_output_id,
                                output_type='vol',
                                amount=raise_volume,
                                min_off=self.raise_min_off_duration,
                                output_channel=self.raise_output_channel)

                        self.write_pid_output_influxdb(
                            'ml', 'volume', 8, self.PID_Controller.control_variable)

                elif self.raise_output_type == 'pwm' and not self.raise_always_min_pwm:
                    # Turn PWM Off if PWM Output and not instructed to always be at least min
                    self.control.output_on(
                        self.raise_output_id,
                        output_type='pwm',
                        amount=0,
                        output_channel=self.raise_output_channel)

            #
            # PID control variable is negative, indicating a desire to lower
            # the environmental condition
            #
            if self.PID_Controller.direction in ['lower', 'both'] and self.lower_output_id:

                if self.PID_Controller.control_variable < 0:

                    if self.lower_output_type == 'pwm':
                        lower_duty_cycle = self.control_var_to_duty_cycle(
                            abs(self.PID_Controller.control_variable))

                        # Ensure the duty cycle doesn't exceed the min/max
                        if (self.lower_max_duration and
                                lower_duty_cycle > self.lower_max_duration):
                            lower_duty_cycle = self.lower_max_duration
                        elif (self.lower_min_duration and
                                lower_duty_cycle < self.lower_min_duration):
                            lower_duty_cycle = self.lower_min_duration

                        self.logger.debug(
                            f"Setpoint: {self.PID_Controller.setpoint}, "
                            f"Control Variable: {self.PID_Controller.control_variable}, "
                            f"Output: PWM output {self.lower_output_id} "
                            f"CH{self.lower_output_channel} to {lower_duty_cycle:.1f}%")

                        if self.store_lower_as_negative:
                            store_duty_cycle = -self.control_var_to_duty_cycle(
                                abs(self.PID_Controller.control_variable))
                        else:
                            store_duty_cycle = self.control_var_to_duty_cycle(
                                abs(self.PID_Controller.control_variable))

                        if self.send_lower_as_negative:
                            send_duty_cycle = -abs(lower_duty_cycle)
                        else:
                            send_duty_cycle = abs(lower_duty_cycle)

                        # Activate pwm with calculated duty cycle
                        self.control.output_on(
                            self.lower_output_id,
                            output_type='pwm',
                            amount=send_duty_cycle,
                            output_channel=self.lower_output_channel)

                        self.write_pid_output_influxdb(
                            'percent', 'duty_cycle', 7, store_duty_cycle)

                    elif self.lower_output_type == 'on_off':
                        lower_seconds_on = abs(self.PID_Controller.control_variable)

                        # Ensure the output on duration doesn't exceed the set maximum
                        if (self.lower_max_duration and
                                lower_seconds_on > self.lower_max_duration):
                            lower_seconds_on = self.lower_max_duration

                        if self.store_lower_as_negative:
                            store_amount_on = -abs(self.PID_Controller.control_variable)
                        else:
                            store_amount_on = abs(self.PID_Controller.control_variable)

                        if self.send_lower_as_negative:
                            send_amount_on = -lower_seconds_on
                        else:
                            send_amount_on = lower_seconds_on

                        if lower_seconds_on >= self.lower_min_duration:
                            # Activate lower_output for a duration
                            self.logger.debug(
                                f"Setpoint: {self.PID_Controller.setpoint} "
                                f"Output: {self.PID_Controller.control_variable} sec to "
                                f"output {self.lower_output_id} CH{self.lower_output_channel}")

                            self.control.output_on(
                                self.lower_output_id,
                                output_type='sec',
                                amount=send_amount_on,
                                min_off=self.lower_min_off_duration,
                                output_channel=self.lower_output_channel)

                        self.write_pid_output_influxdb(
                            's', 'duration_time', 6, store_amount_on)

                    elif self.lower_output_type == 'value':
                        lower_value = abs(self.PID_Controller.control_variable)

                        # Ensure the output value doesn't exceed the set maximum
                        if (self.lower_max_duration and
                                lower_value > self.lower_max_duration):
                            lower_value = self.lower_max_duration

                        if self.store_lower_as_negative:
                            store_value = -abs(self.PID_Controller.control_variable)
                        else:
                            store_value = abs(self.PID_Controller.control_variable)

                        if self.send_lower_as_negative:
                            send_value = -lower_value
                        else:
                            send_value = lower_value

                        if lower_value >= self.lower_min_duration:
                            # Activate lower_output for a value
                            self.logger.debug(
                                f"Setpoint: {self.PID_Controller.setpoint} "
                                f"Output: {self.PID_Controller.control_variable} to "
                                f"output {self.lower_output_id} CH{self.lower_output_channel}")

                            self.control.output_on(
                                self.lower_output_id,
                                output_type='value',
                                amount=send_value,
                                min_off=self.lower_min_off_duration,
                                output_channel=self.lower_output_channel)

                        self.write_pid_output_influxdb(
                            'none', 'unitless', 9, store_value)

                    elif self.lower_output_type == 'volume':
                        lower_volume = abs(self.PID_Controller.control_variable)

                        # Ensure the output volume doesn't exceed the set maximum
                        if (self.lower_max_duration and
                                lower_volume > self.lower_max_duration):
                            lower_volume = self.lower_max_duration

                        if self.store_lower_as_negative:
                            store_volume = -abs(self.PID_Controller.control_variable)
                        else:
                            store_volume = abs(self.PID_Controller.control_variable)

                        if self.send_lower_as_negative:
                            send_volume = -lower_volume
                        else:
                            send_volume = lower_volume

                        if lower_volume >= self.lower_min_duration:
                            # Activate lower_output for a volume (ml)
                            self.logger.debug(
                                f"Setpoint: {self.PID_Controller.setpoint} "
                                f"Output: {self.PID_Controller.control_variable} ml to "
                                f"output {self.lower_output_id} CH{self.lower_output_channel}")

                            self.control.output_on(
                                self.lower_output_id,
                                output_type='vol',
                                amount=send_volume,
                                min_off=self.lower_min_off_duration,
                                output_channel=self.lower_output_channel)

                        self.write_pid_output_influxdb(
                            'ml', 'volume', 8, store_volume)

                elif self.lower_output_type == 'pwm' and not self.lower_always_min_pwm:
                    # Turn PWM Off if PWM Output and not instructed to always be at least min
                    self.control.output_on(
                        self.lower_output_id,
                        output_type='pwm',
                        amount=0,
                        output_channel=self.lower_output_channel)

        else:
            self.logger.debug("Last measurement unsuccessful. Turning outputs off.")
            self._turn_outputs_off()

    def _turn_outputs_off(self):
        if self.PID_Controller.direction in ['raise', 'both'] and self.raise_output_id:
            self.control.output_off(
                self.raise_output_id, output_channel=self.raise_output_channel)
        if self.PID_Controller.direction in ['lower', 'both'] and self.lower_output_id:
            self.control.output_off(
                self.lower_output_id, output_channel=self.lower_output_channel)

    def pid_parameters_str(self):
        return f"Device ID: {self.device_id}, " \
               f"Measurement ID: {self.measurement_id}, " \
               f"Direction: {self.PID_Controller.direction}, " \
               f"Period: {self.period}, " \
               f"Setpoint: {self.PID_Controller.setpoint}, " \
               f"Band: {self.PID_Controller.band}, " \
               f"Kp: {self.PID_Controller.Kp}, " \
               f"Ki: {self.PID_Controller.Ki}, " \
               f"Kd: {self.PID_Controller.Kd}, " \
               f"Integrator Min: {self.PID_Controller.integrator_min}, " \
               f"Integrator Max {self.PID_Controller.integrator_max}, " \
               f"Output Raise: {self.raise_output_id}, " \
               f"Output Raise Channel: {self.raise_output_channel}, " \
               f"Output Raise Type: {self.raise_output_type}, " \
               f"Output Raise Min On: {self.raise_min_duration}, " \
               f"Output Raise Max On: {self.raise_max_duration}, " \
               f"Output Raise Min Off: {self.raise_min_off_duration}, " \
               f"Output Raise Always Min: {self.raise_always_min_pwm}, " \
               f"Output Lower: {self.lower_output_id}, " \
               f"Output Lower Channel: {self.lower_output_channel}, " \
               f"Output Lower Type: {self.lower_output_type}, " \
               f"Output Lower Min On: {self.lower_min_duration}, " \
               f"Output Lower Max On: {self.lower_max_duration}, " \
               f"Output Lower Min Off: {self.lower_min_off_duration}, " \
               f"Output Lower Always Min: {self.lower_always_min_pwm}, " \
               f"Setpoint Tracking Type: {self.setpoint_tracking_type}, " \
               f"Setpoint Tracking ID: {self.setpoint_tracking_id}"

    def control_var_to_duty_cycle(self, control_variable):
        # Convert control variable to duty cycle
        period = self._period_s()
        if control_variable > period:
            return 100.0
        else:
            return float((control_variable / period) * 100)

    @staticmethod
    def return_output_channel(output_channel_id):
        output_channel = db_retrieve_table_daemon(
            OutputChannel, unique_id=output_channel_id)
        if output_channel and output_channel.channel is not None:
            return output_channel.channel

    def write_pid_output_influxdb(self, unit, measurement, channel, value):
        write_pid_out_db = threading.Thread(
            target=write_influxdb_value,
            args=(self.unique_id,
                  unit,
                  value,),
            kwargs={'measure': measurement,
                    'channel': channel})
        write_pid_out_db.start()

    def pid_mod(self):
        if self.initialize_variables():
            return "success"
        else:
            return "error"

    def _save_run_state(self):
        """일시정지·유지 플래그를 DB 에 맞춘다(둘은 배타다)."""
        with session_scope(AOT_DB_PATH) as db_session:
            mod_pid = db_session.query(PID).filter(
                PID.unique_id == self.unique_id).first()
            mod_pid.is_held = self.is_held
            mod_pid.is_paused = self.is_paused
            db_session.commit()

    def pid_hold(self):
        """유지: 적분과 제어 변수를 얼리고 마지막 출력을 (측정값이 신선한 동안) 반복한다."""
        self.is_held = True
        self.is_paused = False
        self._save_run_state()
        self.logger.info("PID Held")
        return "success"

    def pid_pause(self):
        """일시정지: 측정·적분·출력을 모두 멈추고 출력을 끈다."""
        self.is_paused = True
        self.is_held = False
        self._save_run_state()
        try:
            self._turn_outputs_off()
        except Exception:
            self.logger.exception("Could not turn outputs off while pausing")
        self.logger.info("PID Paused")
        return "success"

    def pid_resume(self):
        """재개: 적분은 그대로 이어 쓰고(bumpless) 미분 기준점만 다시 잡는다."""
        self.is_activated = True
        self.is_held = False
        self.is_paused = False
        self.PID_Controller.first_start = True
        with session_scope(AOT_DB_PATH) as db_session:
            mod_pid = db_session.query(PID).filter(
                PID.unique_id == self.unique_id).first()
            mod_pid.is_activated = True
            mod_pid.is_held = False
            mod_pid.is_paused = False
            db_session.commit()
        self.logger.info("PID Resumed")
        return "success"

    def set_setpoint(self, setpoint):
        """Set the setpoint of PID."""
        self.PID_Controller.setpoint = float(setpoint)
        with session_scope(AOT_DB_PATH) as db_session:
            mod_pid = db_session.query(PID).filter(PID.unique_id == self.unique_id).first()
            mod_pid.setpoint = setpoint
            db_session.commit()
        return f"Setpoint set to {setpoint}"

    def set_method(self, method_id):
        """Set the method of PID."""
        with session_scope(AOT_DB_PATH) as db_session:
            mod_pid = db_session.query(PID).filter(PID.unique_id == self.unique_id).first()
            mod_pid.setpoint_tracking_id = method_id

            if method_id == '':
                self.setpoint_tracking_id = ''
                db_session.commit()
            else:
                mod_pid.method_start_time = None
                mod_pid.method_end_time = None
                db_session.commit()
                self.setup_method(method_id)

        return f"Method set to {method_id}"

    def set_integrator(self, integrator):
        """Set the integrator of the controller."""
        self.PID_Controller.integrator = float(integrator)
        return f"Integrator set to {self.PID_Controller.integrator}"

    def set_derivator(self, derivator):
        """Set the derivator of the controller."""
        self.PID_Controller.derivator = float(derivator)
        return f"Derivator set to {self.PID_Controller.derivator}"

    def set_kp(self, p):
        """Set Kp gain of the controller."""
        self.PID_Controller.Kp = float(p)
        with session_scope(AOT_DB_PATH) as db_session:
            mod_pid = db_session.query(PID).filter(PID.unique_id == self.unique_id).first()
            mod_pid.p = p
            db_session.commit()
        return f"Kp set to {self.PID_Controller.Kp}"

    def set_ki(self, i):
        """Set Ki gain of the controller."""
        self.PID_Controller.Ki = float(i)
        with session_scope(AOT_DB_PATH) as db_session:
            mod_pid = db_session.query(PID).filter(PID.unique_id == self.unique_id).first()
            mod_pid.i = i
            db_session.commit()
        return f"Ki set to {self.PID_Controller.Ki}"

    def set_kd(self, d):
        """Set Kd gain of the controller."""
        self.PID_Controller.Kd = float(d)
        with session_scope(AOT_DB_PATH) as db_session:
            mod_pid = db_session.query(PID).filter(PID.unique_id == self.unique_id).first()
            mod_pid.d = d
            db_session.commit()
        return f"Kd set to {self.PID_Controller.Kd}"

    def get_setpoint(self):
        return self.PID_Controller.setpoint

    def get_setpoint_band(self):
        return self.PID_Controller.setpoint_band

    def get_error(self):
        return self.PID_Controller.error

    def get_integrator(self):
        return self.PID_Controller.integrator

    def get_derivator(self):
        return self.PID_Controller.derivator

    def get_kp(self):
        return self.PID_Controller.Kp

    def get_ki(self):
        return self.PID_Controller.Ki

    def get_kd(self):
        return self.PID_Controller.Kd

    def function_status(self):
        """상태 사실만 낸다 — 문장은 Flask 쪽(`utils_function_status`)이 뷰어의 언어로 만든다.

        조회 순간의 시각이 아니라 **마지막 실행이 언제였는지**와 다음 실행까지
        남은 시간을 내보낸다 — 멈춘 PID 가 정상처럼 보이지 않게.
        """
        controller = self.PID_Controller
        p_value = (controller.P_value or 0) if controller else 0
        i_value = (controller.I_value or 0) if controller else 0
        d_value = (controller.D_value or 0) if controller else 0

        if not self.is_activated:
            state = 'deactivated'
        elif self.is_paused:
            state = 'paused'
        elif self.is_held:
            state = 'held'
        else:
            state = 'running'

        now = time.monotonic()
        last_run = self._last_run_mono
        return {
            'status_facts': {
                'kind': 'pid',
                'state': state,
                'period_s': self._period_s(),
                'last_run_age_s': (now - last_run) if last_run is not None else None,
                'next_run_s': (max(0.0, self.timer - now)
                               if self.is_activated else None),
                'control_variable': {
                    'total': p_value + i_value + d_value,
                    'p': p_value, 'i': i_value, 'd': d_value,
                },
            },
            'error': [],
        }

    def stop_controller(self, ended_normally=True, deactivate_pid=False):
        self.thread_shutdown_timer = timeit.default_timer()
        self.running = False

        # Unset method start time
        if (self.setpoint_tracking_type == 'method' and
                self.setpoint_tracking_id != '' and
                ended_normally):
            with session_scope(AOT_DB_PATH) as db_session:
                mod_pid = db_session.query(PID).filter(
                    PID.unique_id == self.unique_id).first()
                mod_pid.method_start_time = None
                mod_pid.method_end_time = None
                db_session.commit()

        # Deactivate PID and Autotune
        if deactivate_pid:
            with session_scope(AOT_DB_PATH) as db_session:
                mod_pid = db_session.query(PID).filter(
                    PID.unique_id == self.unique_id).first()
                mod_pid.is_activated = False
                mod_pid.autotune_activated = False
                db_session.commit()
