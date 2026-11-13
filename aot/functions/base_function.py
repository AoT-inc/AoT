# coding=utf-8
"""
This module contains the AbstractFunction Class which acts as a template
for all functions.  It is not to be used directly. The AbstractFunction Class
ensures that certain methods and instance variables are included in each
Function.

All Functions should inherit from this class and overwrite methods that raise
NotImplementedErrors
"""
import logging
import math
import time

from aot.controllers.abstract_base_controller import AbstractBaseController
from aot.databases.models import CustomController
from aot.utils.database import disabled_measurement_channels


class AbstractFunction(AbstractBaseController):
    """Provide the base template for all AoT function controllers.

    Subclasses must override initialize() at minimum.
    Handles logger setup, measurement initialization, and custom-option
    persistence via the daemon database.

    @phase core
    @stability stable
    @dependency AbstractBaseController, CustomController
    """
    def __init__(self, function, testing=False, name=__name__):
        if not testing:
            super().__init__(function.unique_id, testing=testing, name=__name__)
        else:
            super().__init__(None, testing=testing, name=__name__)

        self.logger = None
        self.setup_logger(testing=testing, name=name, function=function)
        self.function = function
        self.running = True

        if not testing:
            self.unique_id = function.unique_id
            self.initialize_measurements()

    # 루프가 `while timer_loop < now: timer_loop += 주기` 로 다음 시각을 미는 모듈이
    # 많다(≈35개). 주기가 0·음수·숫자 아님이면 이 while 이 끝나지 않아 Function
    # 스레드가 영영 돌고(0), 문자열이면 매 틱 TypeError(숫자 아님)다. 저장 화면의
    # 제약(양수)은 API·옛 값·시간 입력 해석 실패를 막지 못하므로 옵션을 읽은 직후
    # 한 곳에서 고친다.
    LOOP_PERIOD_OPTION_IDS = ('period', 'update_period')

    def seconds_until_due(self):
        """다음 `loop()` 할 일까지 남은 초. 모르면 None.

        Function 컨트롤러는 이것을 보고 점검 주기(sample_rate) 대신 그 시각에
        깨어나 `loop()` 를 부른다. 예전에는 점검 주기마다만 불러, 점검 주기를
        15초로 둔 설치에서 60초 주기 모듈도 최대 15초씩 늦게 돌았다.

        기본은 모듈들이 공통으로 쓰는 `self.timer_loop`(다음 실행 epoch)다
        (`aot/functions/*` 의 loop 모듈 39개 전부). 다른 규칙으로 도는 모듈은 덮어쓴다.
        """
        due = getattr(self, 'timer_loop', None)
        if isinstance(due, bool) or not isinstance(due, (int, float)):
            return None
        if not math.isfinite(due):
            return None
        return due - time.time()

    def setup_custom_options(self, custom_options, custom_controller):
        """옵션을 읽은 뒤 루프 주기가 쓸 수 있는 값인지 확인한다."""
        result = super().setup_custom_options(custom_options, custom_controller)
        try:
            self._ensure_positive_loop_periods(custom_options)
        except Exception:
            self.logger.exception("루프 주기 점검 실패")
        return result

    def _ensure_positive_loop_periods(self, custom_options):
        for each_option in custom_options or []:
            option_id = each_option.get('id')
            if option_id not in self.LOOP_PERIOD_OPTION_IDS:
                continue
            if not hasattr(self, option_id):
                continue
            value = getattr(self, option_id)
            try:
                period = float(value)
            except (TypeError, ValueError):
                period = None
            if period is not None and math.isfinite(period) and period > 0:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    setattr(self, option_id, period)
                continue
            try:
                fallback = float(each_option.get('default_value'))
            except (TypeError, ValueError):
                fallback = 0.0
            if not (math.isfinite(fallback) and fallback > 0):
                fallback = 60.0
            self.logger.error(
                "'%s' 값 %r 은(는) 양의 초가 아니다 — 주기를 %s초로 대신 쓴다. "
                "설정에서 주기를 다시 저장하라.", option_id, value, fallback)
            setattr(self, option_id, fallback)

    def initialize_measurements(self):
        """Load device measurement channels from the database."""
        try:
            if self.device_measurements:
                return
        except:
            pass
        self.setup_device_measurement(self.unique_id)

    def is_enabled(self, channel):
        """Return whether a measurement channel is enabled.

        channels_measurement 는 컨트롤러 기동 때 뜬 스냅샷이라 설정 변경이
        재시작 전까지 반영되지 않는다. 정본인 DB 를 짧은 TTL 로 다시 읽는다.
        """
        return channel not in disabled_measurement_channels(self.unique_id)

    def setup_logger(self, testing=None, name=None, function=None):
        """Configure the logger with the function's unique ID and log level."""
        name = name if name else __name__
        if not testing and function:
            log_name = "{}_{}".format(name, function.unique_id.split('-')[0])
        else:
            log_name = name
        self.logger = logging.getLogger(log_name)
        if not testing and function:
            if function.log_level_debug:
                self.logger.setLevel(logging.DEBUG)
            else:
                # 시스템 전역 로그 규칙: 장치 단위 INFO/WARNING 은 사용자가
                # log_level_debug 옵션을 켠 경우에만 기록. 기본은 ERROR 이상만 저장.
                self.logger.setLevel(logging.ERROR)

    def initialize(self):
        """Override in subclasses to perform controller-specific setup."""
        self.logger.error(
            "{cls} did not overwrite the initialize() method. All "
            "subclasses of the AbstractFunction class are required to overwrite "
            "this method".format(cls=type(self).__name__))
        raise NotImplementedError

    def start_function(self):
        """Not used yet."""
        self.running = True

    def stop_function(self):
        """Called when Function is deactivated."""
        self.running = False

    #
    # Accessory functions
    #

    def set_custom_option(self, option, value):
        """Persist a custom option value to the database."""
        return self._set_custom_option(CustomController, self.unique_id, option, value)

    def get_custom_option(self, option, default_return=None):
        """Retrieve a custom option value from the database."""
        return self._get_custom_option(CustomController, self.unique_id, option, default_return=default_return)

    def delete_custom_option(self, option):
        """Remove a custom option entry from the database."""
        return self._delete_custom_option(CustomController, self.unique_id, option)

    def create_note(
        self,
        note_text,
        name=None,
        tags=None,
        target_id=None,
        target_type=None,
        category='general',
        priority=0,
        gps_lat=None,
        gps_lng=None,
    ):
        """Create a Notes record originating from the current Function.

        When target_id/target_type are not specified, this Function itself is linked automatically.
        tags is a list of tag name strings; missing tags are created automatically.

        :param note_text:   note body
        :param name:        title (if None, auto-extracted from the first body line)
        :param tags:        list of tag names, e.g. ['alarm', 'sensor']
        :param target_id:   unique_id of the linked target (default: this Function's unique_id)
        :param target_type: target type (default: 'function')
        :param category:    'general' | 'observation' | 'alarm' | 'maintenance'
        :param priority:    0=normal, 1=high, 2=critical
        :param gps_lat:     latitude (float, optional)
        :param gps_lng:     longitude (float, optional)
        :return:            the created Notes.unique_id, or None
        """
        from aot.utils.note_factory import create_note_record
        return create_note_record(
            note_text,
            name=name,
            tag_names=tags or [],
            target_id=target_id if target_id is not None else self.unique_id,
            target_type=target_type if target_type is not None else 'function',
            category=category,
            priority=priority,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
        )
