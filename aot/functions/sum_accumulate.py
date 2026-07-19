# coding=utf-8
#
#  sum_accumulate.py - Single-source accumulating / point sum function
#
#  Unlike the cross-device Sum functions (sum_last_multiple / sum_past_single),
#  this function sums one device's measurement *over time*:
#
#    - Interval mode ("period"): every period, sum every value that arrived in
#      the window [previous run, now]. Use for per-cycle usage totals.
#    - Point mode ("point"): take a single snapshot value at a recurring clock
#      instant (anchored to a time-of-day in the device's timezone, repeating
#      every N hours) and sum the most recent N snapshots. Use for "value at
#      24:00 over the last N days".
#
#  Both modes store the result with the user-selected measurement and unit.
#
#  Downtime handling (daemon/app restart):
#    Runtime cursors (last_sum_time / last_processed_instant) are persisted to
#    the function's custom_options, so a restart resumes where it left off.
#    - Interval: the first post-restart sum covers [last_sum_time, now], which
#      spans the outage. No usage is lost because InfluxDB retains the raw data.
#    - Point: snapshot instants missed during the outage are back-filled, each
#      recomputed from InfluxDB history and written at its own timestamp
#      (bounded by MAX_BACKFILL to avoid a runaway catch-up).
#
import math
import time
from datetime import datetime
from datetime import timezone

from flask_babel import lazy_gettext

from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.databases.models import Input
from aot.databases.models import Output
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.device_tz import get_device_tz
from aot.utils.influx import add_measurements_influxdb
from aot.utils.influx import read_influxdb_list
from aot.utils.influx import read_influxdb_single
from aot.utils.influx import write_influxdb_value
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info

measurements_dict = {
    0: {
        'measurement': '',
        'unit': '',
        'name': 'Sum'
    }
}

FUNCTION_INFORMATION = {
    'function_name_unique': 'SUM_ACCUMULATE',
    'function_name': lazy_gettext('Sum (Accumulate / Point)'),
    'measurements_dict': measurements_dict,
    'enable_channel_unit_select': True,

    'message': lazy_gettext(
        'Sums a single measurement source over time. '
        'Interval mode sums every value between cycles (per-cycle usage). '
        'Point mode samples one value at a recurring time-of-day (every N hours, '
        'in the device timezone) and sums the most recent N snapshots. '
        'The result is stored with the selected measurement and unit.'),

    'options_enabled': [
        'measurements_select_measurement_unit',
        'custom_options'
    ],

    'custom_options': [
        {
            'id': 'sum_mode',
            'type': 'select',
            'default_value': 'period',
            'required': True,
            'options_select': [
                ('period', lazy_gettext('Interval sum (between cycles)')),
                ('point', lazy_gettext('Point sum (value at a recurring time)'))
            ],
            'name': lazy_gettext('Sum Mode'),
            'phrase': lazy_gettext(
                'Interval: sum all values in the [previous run, now] window. '
                'Point: sum the most recent N snapshot values.')
        },
        {
            'id': 'select_measurement',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function',
                'Output'
            ],
            'name': lazy_gettext('Measurement'),
            'phrase': lazy_gettext('The single measurement source to sum')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Start Offset'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The duration to wait before the first operation')
        },
        {
            'id': 'period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 3600,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('[Interval mode] The duration between sums')
        },
        {
            'id': 'snapshot_time',
            'type': 'text',
            'default_value': '00:00',
            'required': True,
            'name': lazy_gettext('Snapshot Time (HH:MM)'),
            'phrase': lazy_gettext(
                '[Point mode] Time-of-day anchor for snapshots in the device '
                'timezone (e.g. 00:00). Use 24:00 for midnight.')
        },
        {
            'id': 'snapshot_interval_hours',
            'type': 'text',
            'default_value': 24,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Snapshot Interval'), lazy_gettext('Hours')),
            'phrase': lazy_gettext(
                '[Point mode] Hours between snapshots, starting from the anchor '
                '(e.g. 24 = once daily, 6 = four times daily)')
        },
        {
            'id': 'point_count',
            'type': 'integer',
            'default_value': 1,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Point Count (N)'),
            'phrase': lazy_gettext(
                '[Point mode] Number of most-recent snapshot values to sum')
        },
        {
            'id': 'execute_now',
            'type': 'button',
            'wait_for_return': True,
            'name': lazy_gettext('Measure Now'),
            'phrase': lazy_gettext('Force the sum logic to run immediately, regardless of the period timer')
        }
    ]
}


class CustomModule(AbstractFunction):
    """Sum a single measurement source over time (interval or point mode).

    @phase co-growth
    @stability experimental
    @dependency AbstractFunction, DaemonControl, InfluxDB, device_tz
    """

    # Cap on how many missed snapshot instants to back-fill after an outage.
    MAX_BACKFILL = 500

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = time.time()

        self.control = DaemonControl()

        # Custom options
        self.sum_mode = None
        self.select_measurement_device_id = None
        self.select_measurement_measurement_id = None
        self.start_offset = None
        self.period = None
        self.snapshot_time = None
        self.snapshot_interval_hours = None
        self.point_count = None

        # Persisted runtime cursors (restored in initialize())
        self.last_sum_time = None          # interval mode: end of last window
        self.last_processed_instant = None  # point mode: last snapshot epoch

        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        if not testing:
            self.try_initialize()

    def initialize(self):
        """Set the loop timer and restore persisted cursors from the DB."""
        self.timer_loop = time.time() + self.start_offset
        # Survive daemon/app restarts: resume from where we left off.
        self.last_sum_time = self.get_custom_option('last_sum_time')
        self.last_processed_instant = self.get_custom_option(
            'last_processed_instant')

    def loop(self):
        """Dispatch to the configured sum mode."""
        if self.sum_mode == 'point':
            self._loop_point()
        else:
            self._loop_period()

    #
    # Helpers
    #

    def _source_tz(self):
        """소스 디바이스(Input/Function/Output)의 타임존 반환. 없으면 function 타임존."""
        device_id = self.select_measurement_device_id
        for model in (Input, CustomController, Output):
            try:
                device = db_retrieve_table_daemon(model, unique_id=device_id)
                if device:
                    return get_device_tz(device)
            except Exception:
                pass
        return get_device_tz(self.function)

    @staticmethod
    def _rfc3339(epoch):
        """Format an epoch (seconds) as a UTC RFC3339 string for Flux range()."""
        return datetime.fromtimestamp(
            epoch, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _source_info(self):
        """Return (device_id, channel, unit, measurement) for the source, or None."""
        device_measurement = get_measurement(
            self.select_measurement_measurement_id)
        if not device_measurement:
            self.logger.error("Could not find source Device Measurement")
            return None

        conversion = db_retrieve_table_daemon(
            Conversion, unique_id=device_measurement.conversion_id)
        channel, unit, measurement = return_measurement_info(
            device_measurement, conversion)
        return self.select_measurement_device_id, channel, unit, measurement

    def _store(self, value):
        """Store a summed value at the current time (interval mode)."""
        measurement_dict = {
            0: {
                'measurement': self.channels_measurement[0].measurement,
                'unit': self.channels_measurement[0].unit,
                'value': float(value)
            }
        }
        self.logger.debug(
            "Adding measurement to InfluxDB with ID {}: {}".format(
                self.unique_id, measurement_dict))
        add_measurements_influxdb(self.unique_id, measurement_dict)

    def _store_at(self, value, epoch):
        """Store a summed value stamped at a specific instant (point mode)."""
        write_influxdb_value(
            self.unique_id,
            self.channels_measurement[0].unit,
            float(value),
            measure=self.channels_measurement[0].measurement,
            channel=0,
            timestamp=datetime.fromtimestamp(epoch, tz=timezone.utc))

    #
    # Interval mode: sum every value between cycles
    #

    def _loop_period(self):
        now = time.time()
        if self.timer_loop > now:
            return

        # Window to sum: from the end of the last window (or one period back on
        # the first run) up to now. Using `now` as the end keeps consecutive
        # windows contiguous (no gap/overlap); after a restart the persisted
        # last_sum_time makes this window span the outage automatically.
        window_start = self.last_sum_time if self.last_sum_time is not None \
            else now - self.period
        window_end = now

        while self.timer_loop < now:
            self.timer_loop += self.period

        source = self._source_info()
        if not source:
            return
        device_id, channel, unit, measurement = source

        data = read_influxdb_list(
            device_id, unit, channel,
            measure=measurement,
            start_str=self._rfc3339(window_start),
            end_str=self._rfc3339(window_end))

        total = float(sum(v for _, v in data)) if data else 0.0
        self._store(total)
        self.last_sum_time = window_end
        self.set_custom_option('last_sum_time', window_end)

    #
    # Point mode: sum the most recent N snapshot values
    #

    def _snapshot_geometry(self, now):
        """Return (current_instant_epoch, interval_sec) or None.

        Snapshots are anchored to `snapshot_time` (time-of-day in the device's
        timezone) and repeat every `snapshot_interval_hours`. The returned
        instant is the latest snapshot at or before `now`.
        """
        try:
            hh, mm = (int(p) for p in str(self.snapshot_time).split(':'))
        except (ValueError, AttributeError):
            self.logger.error(
                "Invalid Snapshot Time '{}'; expected HH:MM".format(
                    self.snapshot_time))
            return None
        if hh == 24:  # 24:00 == midnight
            hh = 0

        interval_sec = float(self.snapshot_interval_hours) * 3600.0
        if interval_sec <= 0:
            self.logger.error("Snapshot Interval must be positive")
            return None

        # Anchor in the device's timezone (from device.timezone or its coords),
        # localized DST-correctly, then converted back to an epoch.
        tz = self._source_tz()
        local_naive = datetime.fromtimestamp(now, tz=tz).replace(
            tzinfo=None, hour=hh, minute=mm, second=0, microsecond=0)
        anchor_epoch = tz.localize(local_naive).timestamp()

        k = math.floor((now - anchor_epoch) / interval_sec)
        return anchor_epoch + k * interval_sec, interval_sec

    def _read_point_value(self, device_id, unit, channel, measurement,
                          instant, interval_sec):
        """Last value at or just before `instant` (within one interval back)."""
        res = read_influxdb_single(
            device_id, unit, channel,
            measure=measurement,
            start_str=self._rfc3339(instant - interval_sec),
            end_str=self._rfc3339(instant),
            value='LAST')
        return res[1] if res and res[1] is not None else None

    def _process_instant(self, source, instant, interval_sec):
        """Sum the N snapshots ending at `instant` and store at that instant."""
        device_id, channel, unit, measurement = source

        total = 0.0
        found = 0
        for i in range(int(self.point_count)):
            value = self._read_point_value(
                device_id, unit, channel, measurement,
                instant - i * interval_sec, interval_sec)
            if value is not None:
                total += value
                found += 1

        if found == 0:
            self.logger.error(
                "No snapshot values found for instant {} (last {} points)".format(
                    self._rfc3339(instant), self.point_count))
            return
        if found < int(self.point_count):
            self.logger.debug(
                "Only {} of {} snapshot points had data at {}".format(
                    found, self.point_count, self._rfc3339(instant)))

        self._store_at(total, instant)

    def _loop_point(self):
        now = time.time()
        if self.timer_loop > now:  # honor start offset
            return

        geometry = self._snapshot_geometry(now)
        if not geometry:
            return
        current_instant, interval_sec = geometry

        # Determine which snapshot instants still need processing.
        if self.last_processed_instant is None:
            instants = [current_instant]
        else:
            n_missed = int(round(
                (current_instant - self.last_processed_instant) / interval_sec))
            if n_missed <= 0:
                return  # already processed this instant
            first_k = 1
            if n_missed > self.MAX_BACKFILL:
                self.logger.warning(
                    "Outage back-fill capped: {} snapshots missed, processing "
                    "the most recent {}".format(n_missed, self.MAX_BACKFILL))
                first_k = n_missed - self.MAX_BACKFILL + 1
            instants = [
                self.last_processed_instant + k * interval_sec
                for k in range(first_k, n_missed + 1)
            ]

        source = self._source_info()
        if not source:
            return

        for instant in instants:
            self._process_instant(source, instant, interval_sec)

        self.last_processed_instant = current_instant
        self.set_custom_option('last_processed_instant', current_instant)

    def execute_now(self, args_dict):
        """Button: force the sum logic to run immediately."""
        self.timer_loop = 0
        self.last_sum_time = None
        self.last_processed_instant = None
        self.loop()
        return "Sum executed."
