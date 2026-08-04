# coding=utf-8
import datetime
import logging
import time
from math import sin, radians

from aot.databases.models import Method
from aot.databases.models import MethodData
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.system_pi import get_sec

logger = logging.getLogger(__name__)


def parse_db_time(time_string, default=None):
    try:
        return datetime.datetime.fromisoformat(str(time_string))
    except ValueError:
        return default


class AbstractMethod(object):
    """
    Basic class for methods. A method is called by controller (trigger, pid) to determine an analogue
    value. A trigger can use this as condition or forward into a pwm output. Pid can use these values
    to allow setpoint tracking functionality.
    The config frontend also displays plots of the method. This class also calculates the necessary values.
    """

    def __init__(self, method, method_data, logger=None, target_id=None):
        """
        Initializes the method class
        :param method: method entry from method table
        :param method_data: data queried from method_data table
        :param logger: The logger to use
        :param target_id: 이 메서드를 돌리는 주체(PID·트리거 등)의 unique_id.
                          하루 단위 메서드의 "몇 시"와 태양 앵커를 그 위치의
                          시계로 해석하는 데 쓴다. None 이면 농장 전역 기준.
        :return: 0 (success) or 1 (error) and a setpoint value
        """
        self.logger = logger
        self.target_id = target_id

        self.unique_id = method.unique_id
        self.method_type = method.method_type
        self.method_name = method.name

        self.method_data = method_data

        self.method_data_all = self.method_data.filter(MethodData.output_id.is_(None)).all()
        self.method_data_first = self.method_data.filter(MethodData.output_id.is_(None)).first()
        self.method_data_repeat = self.method_data.filter(MethodData.duration_sec == 0).first()

    def local_tz(self):
        """이 메서드를 돌리는 주체가 있는 곳의 tz. 해석 실패 시 농장 전역."""
        try:
            from aot.utils.device_tz import resolve_location_tz
            return resolve_location_tz(self.target_id)
        except Exception:
            import pytz
            return pytz.utc

    def to_local_wallclock(self, now):
        """`now` 를 **그 위치의 벽시계** naive datetime 으로 정규화.

        하루 단위 메서드는 "06:00~18:00" 같은 벽시계 구간으로 저장되는데, 지금까지
        판정에 쓰던 `now` 는 컨트롤러가 넘긴 UTC(utc_now())였다. 도커 컨테이너
        tz=UTC 규약과 맞물려 한국에서는 곡선이 9시간 밀려 적용됐다
        (DailyMultiPoint 만 facility_tz 로 이 문제를 따로 고쳐 놓은 상태였다).

        aware datetime·epoch float 는 위치 tz 로 변환한다. naive 는 이미 벽시계로
        본다 — 플롯이 1900-01-01 기준 합성 시각을 넘기는 경로를 건드리지 않기 위해서다.
        """
        if isinstance(now, (int, float)):
            now = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)
        if getattr(now, 'tzinfo', None) is not None:
            return now.astimezone(self.local_tz()).replace(tzinfo=None)
        return now

    def _solar_clock(self, event, offset_min):
        """태양 이벤트를 오늘 그 위치의 벽시계(1900-01-01 기준)로. 실패 시 None."""
        try:
            from aot.utils.solar import SUN_EVENTS, sun_times
            if event not in SUN_EVENTS:
                return None
            tz = self.local_tz()
            times = sun_times(target_id=self.target_id)
            if times is None:
                return None
            moment = times.event(event)
            if moment is None:
                return None
            local = (moment + datetime.timedelta(minutes=int(offset_min))).astimezone(tz)
            return datetime.datetime.strptime(local.strftime('%H:%M:%S'), '%H:%M:%S')
        except Exception:
            return None

    def determine_end_time(self, method_start_time):
        """
        Called to determine desired end time of this method
        :return: None if never-ending, otherwise a date and time to end
        """
        return datetime.datetime.max

    def calculate_setpoint(self, now, method_start_time=None):
        """
        Returns the value for the setpoint for a given point in time and elapsed duration
        :param now: point in time to calculate the value for
        :param method_start_time: when this method started.
        :return: float value of the setpoint; True if method finished, otherwise False
        """
        return None, False

    def get_plot(self, max_points_x=None):
        """
        Called to calculate values to render a plot in the frontend.
        :param max_points_x:
        :return:  2d array with x and y values.
        """
        return []


class DateMethod(AbstractMethod):
    """
    A time/date method allows a specific time/date span to dictate the setpoint.
    This is useful for long-running methods, that may take place over the period of days, weeks, or months.
    """

    def ignore_date(self):
        """
        :return: False -> date part of date-time should be considered
        """
        return False

    def resolve_daily_bound(self, method_row, which):
        """하루 단위 구간의 한쪽 끝을 1900-01-01 기준 naive datetime 으로 해석.

        태양 앵커(`time_start_event`/`time_end_event`)가 지정돼 있으면 **오늘 그
        위치의** 해당 태양 이벤트 시각(±오프셋)을 쓰고, 없으면 저장된 벽시계
        문자열을 그대로 쓴다.

        고정 시각의 문제는 계절이다. "06:00~18:00 온도 곡선"은 한여름엔 일출 뒤
        한참 지나 시작하고 한겨울엔 캄캄할 때 시작한다. 작물이 겪는 하루는 시계가
        아니라 해에 묶여 있으므로, 곡선의 양 끝을 해에 걸 수 있어야 한다.
        해석에 실패하면 None — 호출부는 그 구간을 건너뛴다.
        """
        clock = getattr(method_row, f'time_{which}', None)
        event = getattr(method_row, f'time_{which}_event', None)
        offset = getattr(method_row, f'time_{which}_offset_min', 0) or 0

        if event:
            resolved = self._solar_clock(event, offset)
            if resolved is not None:
                return resolved
            if self.logger:
                self.logger.debug(
                    "[Method] 태양 앵커 '%s' 해석 실패 — 저장된 시각으로 대체", event)
        if not clock:
            return None
        try:
            return datetime.datetime.strptime(clock, '%H:%M:%S')
        except (TypeError, ValueError):
            return None

    def calculate_setpoint(self, now, method_start_time=None):
        # Calculate where the current time/date is within the time/date method

        if self.ignore_date():
            local_now = self.to_local_wallclock(now)
            now = datetime.datetime.strptime(
                str(local_now.strftime('%H:%M:%S')), '%H:%M:%S')

        for each_method in self.method_data_all:
            if self.ignore_date():
                start_time = self.resolve_daily_bound(each_method, 'start')
                end_time = self.resolve_daily_bound(each_method, 'end')
                if start_time is None or end_time is None:
                    continue
            else:
                start_time = datetime.datetime.strptime(each_method.time_start, '%Y-%m-%d %H:%M:%S')
                end_time = datetime.datetime.strptime(each_method.time_end, '%Y-%m-%d %H:%M:%S')

            if start_time < now < end_time:
                setpoint_start = each_method.setpoint_start
                if each_method.setpoint_end is not None:
                    setpoint_end = each_method.setpoint_end
                else:
                    setpoint_end = each_method.setpoint_start

                setpoint_diff = abs(setpoint_end - setpoint_start)
                total_seconds = (end_time - start_time).total_seconds()
                part_seconds = (now - start_time).total_seconds()
                percent_total = part_seconds / total_seconds

                if setpoint_start < setpoint_end:
                    new_setpoint = setpoint_start + (setpoint_diff * percent_total)
                else:
                    new_setpoint = setpoint_start - (setpoint_diff * percent_total)

                if self.logger:
                    if self.ignore_date():
                        self.logger.debug("[Method] Start: {start} End: {end}".format(
                            start=start_time.strftime('%H:%M:%S'),
                            end=end_time.strftime('%H:%M:%S')))
                    else:
                        self.logger.debug("[Method] Start: {start} End: {end}".format(
                            start=start_time, end=end_time))
                    self.logger.debug("[Method] Start: {start} End: {end}".format(
                        start=setpoint_start, end=setpoint_end))
                    self.logger.debug("[Method] Total: {tot} Part total: {par} ({per}%)".format(
                        tot=total_seconds, par=part_seconds, per=percent_total))
                    self.logger.debug("[Method] New Setpoint: {sp}".format(
                        sp=new_setpoint))
                return new_setpoint, False

        # Setpoint not needing to be calculated, use default setpoint
        return None, False

    def get_plot(self, max_points_x=None):
        result = []
        for each_method in self.method_data_all:
            if each_method.setpoint_end is None:
                setpoint_end = each_method.setpoint_start
            else:
                setpoint_end = each_method.setpoint_end

            start_time = datetime.datetime.strptime(
                each_method.time_start, '%Y-%m-%d %H:%M:%S')
            end_time = datetime.datetime.strptime(
                each_method.time_end, '%Y-%m-%d %H:%M:%S')

            is_dst = time.daylight and time.localtime().tm_isdst > 0
            utc_offset_ms = (time.altzone if is_dst else time.timezone)
            result.append(
                [(int(start_time.strftime("%s")) - utc_offset_ms) * 1000,
                 each_method.setpoint_start])
            result.append(
                [(int(end_time.strftime("%s")) - utc_offset_ms) * 1000,
                 setpoint_end])
            result.append(
                [(int(start_time.strftime("%s")) - utc_offset_ms) * 1000,
                 None])

        return result


class DailyMethod(DateMethod):
    """
    The daily time-based method is similar to the time/date method, however it will repeat every day.
    Therefore, it is essential that only the span of one day be set in this method.
    The implementation is derived from DateMethod, as the calculation is essentially the same ignoring the date part.
    """

    def ignore_date(self):
        """
        :return: True -> date part of date-time should be ignored aka the method's data repeat on a daily basis.
        """
        return True

    def get_plot(self, max_points_x=None):
        result = []
        for each_method in self.method_data_all:
            # 태양 앵커가 걸린 구간은 오늘의 실제 태양시로 그린다 — 저장된 벽시계로
            # 그리면 그래프와 실제 동작이 어긋나 보인다.
            start = self.resolve_daily_bound(each_method, 'start')
            end = self.resolve_daily_bound(each_method, 'end')
            if start is None or end is None:
                continue
            if each_method.setpoint_end is None:
                setpoint_end = each_method.setpoint_start
            else:
                setpoint_end = each_method.setpoint_end
            start_sec = start.hour * 3600 + start.minute * 60 + start.second
            end_sec = end.hour * 3600 + end.minute * 60 + end.second
            result.append([start_sec * 1000, each_method.setpoint_start])
            result.append([end_sec * 1000, setpoint_end])
            result.append([start_sec * 1000, None])
        return result


class AbstractDailyFormulaMethod(AbstractMethod):
    """
    Abstract base for mathematical function based methods. It offers shared functionality to generate the frontend
    plot by iterating through the x axis and calling the calculate_setpoint function to get the corresponding y values.
    """

    def day_seconds(self, now):
        """곡선의 x축으로 쓸 "하루 중 초". 위상 고정이 켜져 있으면 태양시로 보정.

        sine/bezier 는 자정~자정을 한 주기로 잡는다. 그 결과 곡선의 마루가 늘 같은
        **시계 시각**에 오는데, 정작 해가 가장 높은 시각(남중)은 계절과 경도에 따라
        움직인다(같은 표준시대 안에서도 30분 넘게 차이 난다). 곡선을 온도·광량에
        맞춰 그렸다면 그 마루는 시계가 아니라 해를 따라가야 한다.

        `time_start_event` 가 지정되면 그 이벤트가 12:00 위치에 오도록 하루를
        통째로 민다(오프셋은 추가 미세조정). 해석 실패 시 보정 없이 벽시계 그대로.
        """
        local = self.to_local_wallclock(now)
        secs = local.hour * 3600 + local.minute * 60 + local.second

        row = self.method_data_first
        event = getattr(row, 'time_start_event', None) if row is not None else None
        if not event:
            return secs

        anchor = self._solar_clock(
            event, getattr(row, 'time_start_offset_min', 0) or 0)
        if anchor is None:
            return secs
        anchor_secs = anchor.hour * 3600 + anchor.minute * 60 + anchor.second
        return (secs - (anchor_secs - 12 * 3600)) % (24 * 3600)

    def get_plot(self, max_points_x=700):
        result = []

        seconds_in_day = 60 * 60 * 24
        today = datetime.datetime(1900, 1, 1)
        for n in range(max_points_x):
            percent = n / float(max_points_x)
            now = today + datetime.timedelta(seconds=percent * seconds_in_day)
            y, ended = self.calculate_setpoint(now)
            if not ended:
                result.append([percent * seconds_in_day * 1000, y])

        return result


class DailySineMethod(AbstractDailyFormulaMethod):
    """
    The daily sine wave method defines the setpoint over the day based on a sinusoidal wave.
    The sine wave is defined by y = [A * sin(B * x + C)] + D, where A is amplitude, B is frequency,
    C is the angle shift, and D is the y-axis shift. This method will repeat daily.
    """

    def calculate_setpoint(self, now, method_start_time=None):
        # Calculate sine y-axis value from the x-axis (seconds of the day)
        total_seconds = self.day_seconds(now)
        secs_per_day = 24 * 60 * 60
        angle = total_seconds / secs_per_day * 360
        new_setpoint = sine_wave_y_out(self.method_data_first.amplitude,
                                       self.method_data_first.frequency,
                                       self.method_data_first.shift_angle,
                                       self.method_data_first.shift_y,
                                       angle)
        return new_setpoint, False


class DailyBezierMethod(AbstractDailyFormulaMethod):
    def calculate_setpoint(self, now, method_start_time=None):
        # Calculate Bezier curve y-axis value from the x-axis (seconds of the day)

        total_seconds = self.day_seconds(now)

        new_setpoint = bezier_curve_y_out(
            self.method_data_first.shift_angle,
            (self.method_data_first.x0, self.method_data_first.y0),
            (self.method_data_first.x1, self.method_data_first.y1),
            (self.method_data_first.x2, self.method_data_first.y2),
            (self.method_data_first.x3, self.method_data_first.y3),
            total_seconds)

        return new_setpoint, False


class DurationMethod(AbstractMethod):
    """
    A daily Bezier curve method define the setpoint over the day based on a cubic Bezier curve.
    The x-axis start (x3) and end (x0) will be automatically stretched or skewed to fit within a
    24-hour period and this method will repeat daily.
    """

    def calculate_setpoint(self, now, method_start_time=None):
        # Calculate the duration in the method based on self.method_start_time

        start_time = parse_db_time(method_start_time, datetime.datetime.min)

        duration_in_seconds = self.cycle_duration()
        seconds_from_start = (now - start_time).total_seconds()

        if seconds_from_start >= duration_in_seconds:
            repeat_duration = self.repeat_duration()
            if repeat_duration is None:
                # ended after one cycle
                return None, True
            if 0 < repeat_duration <= seconds_from_start:
                # ended after configured repeat time
                return None, True
            else:
                # still repeated
                seconds_from_start = seconds_from_start % duration_in_seconds

        total_sec = 0
        previous_total_sec = 0
        for each_method in self.method_data_all:
            total_sec += each_method.duration_sec
            if previous_total_sec <= seconds_from_start < total_sec:
                row_since_start_sec = seconds_from_start - previous_total_sec
                percent_row = row_since_start_sec / each_method.duration_sec

                setpoint_start = each_method.setpoint_start
                if each_method.setpoint_end is not None:
                    setpoint_end = each_method.setpoint_end
                else:
                    setpoint_end = each_method.setpoint_start
                setpoint_diff = abs(setpoint_end - setpoint_start)
                if setpoint_start < setpoint_end:
                    new_setpoint = setpoint_start + (setpoint_diff * percent_row)
                else:
                    new_setpoint = setpoint_start - (setpoint_diff * percent_row)

                if self.logger:
                    self.logger.debug(
                        "[Method] {sec_method:.1f}s/{sec_cycle:.1f}s/{sec_row:.1f}s "
                        "since start of method/cycle/row".format(
                            sec_method=(now - start_time).total_seconds(),
                            sec_cycle=seconds_from_start,
                            sec_row=row_since_start_sec))
                    self.logger.debug(
                        "[Method] Percent of row: {per:.2f}, new Setpoint {sp:.2f}".format(
                            per=percent_row, sp=new_setpoint))
                return new_setpoint, False

            previous_total_sec = total_sec

        return previous_total_sec, False

    def cycle_duration(self):
        total_sec = 0
        for each_method in self.method_data_all:
            total_sec += each_method.duration_sec

        return total_sec

    def repeat_duration(self):
        for each_method in self.method_data_all:
            if each_method.duration_sec == 0:
                return each_method.duration_end or 0

        return None

    def determine_end_time(self, method_start_time):
        method_start_time = parse_db_time(method_start_time, datetime.datetime.min)
        repeat_duration = self.repeat_duration()

        if repeat_duration is None:
            # if not repeated, the end time is always based on the total configured duration
            return method_start_time + datetime.timedelta(seconds=self.cycle_duration())
        elif repeat_duration > 0:
            # specific total duration in seconds is given
            return method_start_time + datetime.timedelta(seconds=repeat_duration)
        else:
            # if no specific end time is given but the method shall be repeated, return max date
            return datetime.datetime.max

    def get_plot(self, max_points_x=None):
        result = []
        first_entry = True
        start_duration = 0
        for each_method in self.method_data_all:
            if each_method.setpoint_end is None:
                setpoint_end = each_method.setpoint_start
            else:
                setpoint_end = each_method.setpoint_end

            if each_method.duration_sec == 0:
                pass  # Method line is repeat command, don't add to method_list
            elif first_entry:
                result.append([0, each_method.setpoint_start])
                result.append([each_method.duration_sec, setpoint_end])
                start_duration += each_method.duration_sec
                first_entry = False
            else:
                end_duration = start_duration + each_method.duration_sec

                result.append(
                    [start_duration, each_method.setpoint_start])
                result.append(
                    [end_duration, setpoint_end])

                start_duration += each_method.duration_sec

        return result


class CascadeMethod(AbstractMethod):

    def calculate_setpoint(self, now, method_start_time=None, blacklist=None):
        setpoint = 1.
        # blacklist is passed into cascaded cascade methods to avoid endless loops
        if blacklist is None:
            blacklist = set()

        if self.unique_id in blacklist:
            if self.logger:
                self.logger.error("Recursive method invocation. Stopping here.")
                return None, False

        blacklist.add(self.unique_id)

        for each_method in self.method_data_all:
            if not each_method.linked_method_id:
                if self.logger:
                    self.logger.warning("Method data does not contain linked_method_id")
                continue

            linked_method = load_method_handler(each_method.linked_method_id, self.logger,
                                               target_id=self.target_id)

            if not linked_method:
                if self.logger:
                    self.logger.warning("Linked method {} not found".format(each_method.linked_method_id))
                continue

            if isinstance(linked_method, CascadeMethod):
                linked_method_setpoint, linked_method_ended = linked_method.calculate_setpoint(
                    now, method_start_time, blacklist)
            else:
                linked_method_setpoint, linked_method_ended = linked_method.calculate_setpoint(
                    now, method_start_time)

            if linked_method_setpoint is not None:
                setpoint *= linked_method_setpoint / 100.
            if linked_method_ended:
                return None, True

            if self.logger:
                self.logger.debug("Linked method: {} {} returned {}, {}; current product is {}".format(
                    each_method.linked_method_id, linked_method.method_name,
                    linked_method_setpoint, linked_method_ended,
                    setpoint * 100.))

        setpoint *= 100.
        return setpoint, False


class DailyMultiPointMethod(AbstractMethod):
    """Daily method with up to 12 control points, monotonic cubic Hermite interpolation,
    and multi-week (keyframe) evolution.

    v2 points_json schema:
    {
      "version": 2,
      "weeks": [0, 2, 6],          # week numbers, ascending
      "points": [
        {"point_id": 0, "t_sec": 0,     "values": [0.6, 0.7, 0.9],
         "smooth": false, "is_endpoint": true},
        {"point_id": 1, "t_sec": 43200, "values": [1.2, 1.3, 1.5],
         "smooth": true,  "is_endpoint": false},
        {"point_id": 2, "t_sec": 86400, "values": [0.6, 0.7, 0.9],
         "smooth": false, "is_endpoint": true}
      ]
    }

    24h repeating — calculate_setpoint() never returns ended=True.
    """

    MAX_POINTS = 12

    def __init__(self, method, method_data, logger=None, target_id=None):
        # target_id 는 이 클래스가 직접 쓰지는 않는다 — 하루 구간을 facility_tz
        # 인자로 직접 받아 해석하므로 AbstractMethod.local_tz() 경로가 필요 없다.
        # 그래도 받아서 상위로 넘긴다: create_method_handler() 가 **모든** 핸들러에
        # target_id 를 넘기므로, 안 받으면 이 타입만 TypeError 로 로드 자체가 실패한다
        # (2026-07-31 d48b2b7 에서 실제로 그렇게 깨져 VPD 목표가 정적 기본값으로
        # 떨어졌다 — aot-005 '고추육묘 VPD').
        super().__init__(method, method_data, logger, target_id)
        first = self.method_data_first
        if first and getattr(first, 'points_json', None):
            try:
                import json as _json
                raw = _json.loads(first.points_json)
                self._data = _migrate_multipoint(raw)
            except Exception:
                self._data = self._default_data()
        else:
            self._data = self._default_data()

        self._resolved_cache = None
        self._resolved_week_floor = None

    @staticmethod
    def _default_data():
        return {
            'version': 3,
            'weeks': [0],
            'points': [
                {'point_id': 0, 't_sec': 0,     'values': [0.8], 'smooth': False,
                 'curve': 'linear', 'handle_dt': None, 'handle_dv': None, 'is_endpoint': True},
                {'point_id': 1, 't_sec': 86400, 'values': [0.8], 'smooth': False,
                 'curve': 'linear', 'handle_dt': None, 'handle_dv': None, 'is_endpoint': True},
            ],
        }

    # ── public API ────────────────────────────────────────────────────────────

    def calculate_setpoint(self, now, method_start_time=None,
                           weeks_elapsed=None, facility_tz=None):
        """Calculate setpoint for the given timestamp.

        Args:
            now:             Unix timestamp (float) or datetime.
            method_start_time: start datetime for internal weeks_elapsed computation
                               (ignored when weeks_elapsed is supplied explicitly).
            weeks_elapsed:   Pre-computed fractional weeks (from Function/Growth Schedule).
                             When supplied, method_start_time is ignored for week selection.
            facility_tz:     pytz timezone object for the facility.
                             When supplied, t_sec is derived from local facility time
                             instead of UTC — fixes the 9-hour offset for e.g. Korea.
        """
        if isinstance(now, (int, float)):
            now_ts = now
            now_dt_utc = datetime.datetime.utcfromtimestamp(now)
        elif hasattr(now, 'tzinfo') and now.tzinfo is not None:
            now_ts = now.timestamp()
            now_dt_utc = now.replace(tzinfo=None) - now.utcoffset()
        else:
            now_dt_utc = now
            now_ts = None

        # ── weeks_elapsed ────────────────────────────────────────────────────
        if weeks_elapsed is None:
            if method_start_time is None:
                start_dt = datetime.datetime(1900, 1, 1)
            elif hasattr(method_start_time, 'tzinfo') and method_start_time.tzinfo is not None:
                start_dt = method_start_time.replace(tzinfo=None) - method_start_time.utcoffset()
            elif isinstance(method_start_time, str):
                _parsed = parse_db_time(method_start_time, datetime.datetime(1900, 1, 1))
                if hasattr(_parsed, 'tzinfo') and _parsed.tzinfo is not None:
                    start_dt = _parsed.replace(tzinfo=None) - _parsed.utcoffset()
                else:
                    start_dt = _parsed
            else:
                start_dt = method_start_time
            weeks_elapsed = max(0.0, (now_dt_utc - start_dt).total_seconds() / (7 * 86400))

        # ── t_sec: use facility local time when available ────────────────────
        if facility_tz is not None and now_ts is not None:
            try:
                import pytz as _pytz
                now_local = datetime.datetime.fromtimestamp(now_ts, tz=facility_tz)
                t_sec = now_local.hour * 3600 + now_local.minute * 60 + now_local.second
            except Exception:
                t_sec = now_dt_utc.hour * 3600 + now_dt_utc.minute * 60 + now_dt_utc.second
        else:
            t_sec = now_dt_utc.hour * 3600 + now_dt_utc.minute * 60 + now_dt_utc.second

        week_floor = int(weeks_elapsed)
        if self._resolved_cache is None or self._resolved_week_floor != week_floor:
            self._resolved_cache = _resolve_v2_at(self._data, weeks_elapsed)
            self._resolved_week_floor = week_floor

        return _eval_curve(self._resolved_cache, t_sec), False

    def get_plot(self, max_points_x=700):
        """Returns list of series dicts for DailyMultiPoint.

        [{"week": 0, "data": [[t_ms, value], ...]},
         {"week": 2, "data": [[t_ms, value], ...]}, ...]
        """
        weeks = self._data.get('weeks', [0])
        step = max(1, 86400 // max_points_x)
        series = []
        for i, w in enumerate(weeks):
            pts = _resolve_v2_at(self._data, float(w))
            data = [[t * 1000, _eval_curve(pts, t)] for t in range(0, 86401, step)]
            series.append({'week': w, 'week_index': i, 'data': data})
        return series

    def ignore_date(self):
        return True


# ─────────────────────────────────────────────────────────────────────────────
# DailyMultiPointMethod 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _migrate_multipoint(data: dict) -> dict:
    """v1/v2 → v3 자동 변환. v3는 그대로 반환."""
    v = data.get('version', 1)

    if v < 2:
        # v1 → v2: 'value' 단일 필드 + keyframes → values[] 배열
        points_v1 = data.get('points', [])
        all_weeks = {0}
        for p in points_v1:
            for kf in p.get('keyframes') or []:
                all_weeks.add(int(kf['week']))
        weeks = sorted(all_weeks)

        points_v2 = []
        for p in points_v1:
            kfs = {int(kf['week']): kf['value'] for kf in (p.get('keyframes') or [])}
            base = float(p.get('value', 0))
            values = [float(kfs.get(w, base)) for w in weeks]
            points_v2.append({
                'point_id':    p.get('point_id', 0),
                't_sec':       p.get('t_sec', 0),
                'values':      values,
                'smooth':      p.get('smooth', False),
                'is_endpoint': p.get('is_endpoint', False),
            })

        data = {'version': 2, 'weeks': weeks, 'points': points_v2}

    if data.get('version', 1) < 3:
        # v2 → v3: smooth bool → curve str, handle_dt/handle_dv 필드 추가
        for p in data.get('points', []):
            if 'curve' not in p:
                p['curve'] = 'smooth' if p.get('smooth', False) else 'linear'
            if 'handle_dt' not in p:
                # 구 tangent 필드(slope) → handle_dt/handle_dv(오프셋) 변환
                old_tan = p.get('tangent')
                if old_tan is not None:
                    p['handle_dt'] = 5400.0   # 기본 암 길이 90분
                    p['handle_dv'] = float(old_tan) * 5400.0
                else:
                    p['handle_dt'] = None
                    p['handle_dv'] = None
        data['version'] = 3

    return data


def _resolve_v2_at(data: dict, weeks_elapsed: float) -> list:
    """weeks_elapsed 시점의 단일 곡선 포인트 목록 반환.

    각 포인트의 values[] 를 weeks[] 기준으로 선형 보간하여 단일 value 생성.
    반환: [{'t_sec': int, 'value': float, 'curve': str, 'tangent': float|None,
             'smooth': bool, 'is_endpoint': bool}, ...]
    """
    weeks = data.get('weeks', [0])
    points = data.get('points', [])
    resolved = []

    for p in points:
        vals = p.get('values', [p.get('value', 0)])
        value = _interp_weeks(weeks, vals, weeks_elapsed)
        curve = p.get('curve', 'smooth' if p.get('smooth') else 'linear')
        resolved.append({
            't_sec':       int(p.get('t_sec', 0)),
            'value':       value,
            'smooth':      p.get('smooth', False),
            'curve':       curve,
            'handle_dt':   p.get('handle_dt'),
            'handle_dv':   p.get('handle_dv', 0.0) if p.get('handle_dt') is not None else None,
            'tangent':     p.get('tangent'),  # backward compat
            'is_endpoint': p.get('is_endpoint', False),
        })

    return sorted(resolved, key=lambda x: x['t_sec'])


def _interp_weeks(weeks: list, values: list, w: float) -> float:
    """weeks/values 배열에서 w 주차 선형 보간."""
    if not weeks or not values:
        return 0.0
    n = min(len(weeks), len(values))
    if n == 1 or w <= weeks[0]:
        return float(values[0])
    if w >= weeks[n - 1]:
        return float(values[n - 1])
    for i in range(n - 1):
        if weeks[i] <= w <= weeks[i + 1]:
            span = weeks[i + 1] - weeks[i]
            frac = (w - weeks[i]) / span if span else 0.0
            return values[i] + frac * (values[i + 1] - values[i])
    return float(values[-1])


def _resolve_points_at(raw_points, weeks_elapsed):
    """주차(weeks_elapsed)에 따라 각 포인트의 t_sec/value를 키프레임 선형 보간으로 결정."""
    resolved = []
    for p in raw_points:
        kfs = p.get('keyframes') or []
        if not kfs:
            resolved.append(dict(p))
            continue

        kfs_sorted = sorted(kfs, key=lambda k: k['week'])
        # week=0 기준점이 없으면 포인트 자체 값으로 삽입
        if not kfs_sorted or kfs_sorted[0]['week'] != 0:
            kfs_sorted = [{'week': 0, 't_sec': p['t_sec'], 'value': p['value']}] + kfs_sorted

        t_val = float(p['t_sec'])
        v_val = float(p['value'])

        for i in range(len(kfs_sorted) - 1):
            k0, k1 = kfs_sorted[i], kfs_sorted[i + 1]
            if k0['week'] <= weeks_elapsed <= k1['week']:
                w_span = k1['week'] - k0['week']
                frac = (weeks_elapsed - k0['week']) / w_span if w_span else 0.0
                if not p.get('is_endpoint'):
                    t_val = k0['t_sec'] + frac * (k1['t_sec'] - k0['t_sec'])
                v_val = k0['value'] + frac * (k1['value'] - k0['value'])
                break
        else:
            # 마지막 키프레임 이후 — 최종값 유지
            last = kfs_sorted[-1]
            if not p.get('is_endpoint'):
                t_val = float(last['t_sec'])
            v_val = float(last['value'])

        resolved.append({**p, 't_sec': int(round(t_val)), 'value': v_val})

    return sorted(resolved, key=lambda pp: pp['t_sec'])


def _get_curve_type(p: dict) -> str:
    """포인트의 곡선 유형 반환. v3 'curve' 필드 우선, 하위호환."""
    if 'curve' in p:
        return p['curve']
    return 'smooth' if p.get('smooth') else 'linear'


def _eval_curve(points, t_sec):
    """t_sec(0~86400)에서 곡선 값 반환. curve 타입에 따라 선형 또는 Hermite 보간."""
    if not points:
        return 0.0
    pts = sorted(points, key=lambda p: p['t_sec'])
    t_sec = max(0, min(86400, t_sec))

    if t_sec <= pts[0]['t_sec']:
        return float(pts[0]['value'])
    if t_sec >= pts[-1]['t_sec']:
        return float(pts[-1]['value'])

    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        if p0['t_sec'] <= t_sec <= p1['t_sec']:
            dt = p1['t_sec'] - p0['t_sec']
            if dt == 0:
                return float(p0['value'])
            frac = (t_sec - p0['t_sec']) / dt
            if _get_curve_type(p0) == 'linear' and _get_curve_type(p1) == 'linear':
                # 선형 보간
                return p0['value'] + frac * (p1['value'] - p0['value'])
            else:
                # Monotonic Cubic Hermite (Bezier 탄젠트 오버라이드 포함)
                return _hermite_interp(pts, i, frac)
    return float(pts[-1]['value'])


def _hermite_interp(pts, seg_idx, frac):
    """Cubic Hermite interpolation with optional Bezier tangent override.

    Smooth 포인트는 Fritsch-Carlson 자동 접선, Bezier 포인트는 사용자 tangent 사용.
    """
    n = len(pts)

    # 1. 인접 기울기 δ
    deltas = []
    for i in range(n - 1):
        dt = pts[i + 1]['t_sec'] - pts[i]['t_sec']
        if dt == 0:
            deltas.append(0.0)
        else:
            deltas.append((pts[i + 1]['value'] - pts[i]['value']) / dt)

    # 2. 접선 초기화 (Fritsch-Carlson)
    m = [0.0] * n

    # smooth 또는 bezier 끝점이 하나라도 있으면 주기적 접선 사용
    is_periodic = (
        abs(pts[0]['value'] - pts[-1]['value']) < 1e-10
        and (_get_curve_type(pts[0]) != 'linear' or _get_curve_type(pts[-1]) != 'linear')
    )
    if is_periodic:
        m[0] = m[n - 1] = (deltas[0] + deltas[-1]) / 2.0
    else:
        m[0] = deltas[0]
        m[n - 1] = deltas[-1] if len(deltas) > 0 else 0.0

    for i in range(1, n - 1):
        m[i] = (deltas[i - 1] + deltas[i]) / 2.0

    # 3. Fritsch-Carlson 단조성 조건 적용
    for i in range(n - 1):
        if abs(deltas[i]) < 1e-12:
            m[i] = 0.0
            m[i + 1] = 0.0
        else:
            a = m[i]   / deltas[i]
            b = m[i + 1] / deltas[i]
            if a < 0 or b < 0:
                m[i] = 0.0
                m[i + 1] = 0.0
            elif a ** 2 + b ** 2 > 9:
                tau = 3.0 / (a ** 2 + b ** 2) ** 0.5
                m[i]     = tau * a * deltas[i]
                m[i + 1] = tau * b * deltas[i]

    # 4. Bezier(manual) 탄젠트 오버라이드 — F-C 결과를 사용자 지정값으로 교체
    def _bz_slope(p):
        """handle_dt/handle_dv → slope. backward compat: tangent 필드."""
        hdt = p.get('handle_dt')
        if hdt is not None and float(hdt) != 0:
            return float(p.get('handle_dv', 0)) / float(hdt)
        old_tan = p.get('tangent')
        return float(old_tan) if old_tan is not None else None

    has_bezier_start = (
        _get_curve_type(pts[0]) == 'bezier' and _bz_slope(pts[0]) is not None)
    has_bezier_end = (
        _get_curve_type(pts[-1]) == 'bezier' and _bz_slope(pts[-1]) is not None)
    for i, p in enumerate(pts):
        if _get_curve_type(p) == 'bezier':
            s = _bz_slope(p)
            if s is not None:
                m[i] = s

    # 5. 주기적 끝점 접선 재동기화
    if is_periodic:
        if has_bezier_start:
            m[n - 1] = m[0]
        elif has_bezier_end:
            m[0] = m[n - 1]
        else:
            m[0] = m[n - 1] = (m[0] + m[n - 1]) / 2.0

    # 6. Hermite 기저 함수로 보간
    i = seg_idx
    h = pts[i + 1]['t_sec'] - pts[i]['t_sec']
    y0 = float(pts[i]['value'])
    y1 = float(pts[i + 1]['value'])
    m0 = m[i] * h
    m1 = m[i + 1] * h
    t = frac

    return (y0 * (2*t**3 - 3*t**2 + 1)
            + m0 * (t**3 - 2*t**2 + t)
            + y1 * (-2*t**3 + 3*t**2)
            + m1 * (t**3 - t**2))


def create_method_handler(method, method_data, logger=None, target_id=None):
    """Factory function to create a method handler instance from database method_type.

    @phase active
    @stability stable
    @dependency Method, MethodData
    """

    method_class = globals().get(method.method_type+"Method")
    if not method_class or not issubclass(method_class, AbstractMethod):
        logger.error("Method {} is unknown.".format(method.method_type))
        method_class = AbstractMethod

    return method_class(method, method_data, logger, target_id=target_id)


def load_method_handler(method_id, logger=None, target_id=None):
    """Load a method handler from the database by method_id.

    @phase active
    @stability stable
    @dependency db_retrieve_table_daemon, Method, MethodData
    """

    method = db_retrieve_table_daemon(Method).filter(Method.unique_id == method_id).first()
    if not method:
        return None

    method_data = db_retrieve_table_daemon(MethodData).filter(MethodData.method_id == method_id)

    return create_method_handler(method, method_data, logger, target_id=target_id)


def sine_wave_y_out(amplitude, frequency, shift_angle,
                    shift_y, angle_in):
    if angle_in is None:
        raise Exception("angle_in must be specified")
    else:
        angle = angle_in

    y = (amplitude * sin(radians(frequency * (angle - shift_angle)))) + shift_y
    return y


def bezier_curve_y_out(shift_angle, P0, P1, P2, P3, second_of_day):
    """
    For a cubic Bezier segment described by the 2-tuples P0, ..., P3, return
    the y-value associated with the given x-value.

    Ex: getYfromXforBezSegment((10,0), (5,-5), (5,5), (0,0), 3.2)
    """

    try:
        import numpy as np
    except ImportError:
        np = None

    if not np:
        return 0

    seconds_per_day = 24*60*60

    # Check if the second of the day is provided.
    # If provided, calculate y of the Bezier curve with that x
    # Otherwise, use the current second of the day
    if second_of_day is None:
        raise Exception("second_of_day must be specified")
    else:
        seconds = second_of_day

    # Shift the entire graph using 0 - 360 to determine the degree
    if shift_angle:
        percent_angle = shift_angle/360
        angle_seconds = percent_angle*seconds_per_day
        if seconds+angle_seconds > seconds_per_day:
            seconds_shifted = seconds+angle_seconds-seconds_per_day
        else:
            seconds_shifted = seconds+angle_seconds
        percent_of_day = seconds_shifted/seconds_per_day
    else:
        percent_of_day = seconds/seconds_per_day

    x = percent_of_day*(P0[0]-P3[0])

    # First, get the t-value associated with x-value, where t is the
    # parameterization of the Bezier curve and ranges from 0 to 1.
    # We need the coefficients of the polynomial describing cubic Bezier
    # (cubic polynomial in t)
    coefficients = [-P0[0] + 3*P1[0] - 3*P2[0] + P3[0],
                    3*P0[0] - 6*P1[0] + 3*P2[0],
                    -3*P0[0] + 3*P1[0],
                    P0[0] - x]
    # Find roots of the polynomial to determine the parameter t
    roots = np.roots(coefficients)
    # Find the root which is between 0 and 1, and is also real
    correct_root = None
    for root in roots:
        if np.isreal(root) and 0 <= root <= 1:
            correct_root = root
    # Check a valid root was found
    if correct_root is None:
        print('Error, no valid root found. Are you sure your Bezier curve '
              'represents a valid function when projected into the xy-plane?')
        return 0
    param_t = correct_root
    # From the value for the t parameter, find the corresponding y-value
    # using the formula for cubic Bezier curves
    y = (1-param_t)**3*P0[1] + 3*(1-param_t)**2*param_t*P1[1] + 3*(1-param_t)*param_t**2*P2[1] + param_t**3*P3[1]
    if not np.isreal(y):
        raise AssertionError
    # Typecast y from np.complex128 to float64
    y = y.real
    return y
