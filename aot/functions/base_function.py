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

    def register_upcoming_action(self, action_type, params, schedule_time, reasoning=None):
        """
        Opt-in API for Functions to register their upcoming actions to the AIScheduler.
        This allows the AI to see what the function plans to do.
        """
        try:
            from aot.ai.services.ai_scheduler_service import AISchedulerService
            AISchedulerService.propose_job(
                action_type=action_type,
                target_id=self.unique_id,
                params=params,
                reasoning=reasoning or f"Function {self.function.name} scheduled action",
                schedule_time=schedule_time,
                proposed_by='FUNCTION',
                source_type='function',
                approval_required=False  # Functions usually run autonomously
            )
            self.logger.info(f"Registered upcoming action: {action_type} at {schedule_time}")
        except Exception as e:
            self.logger.error(f"Failed to register upcoming action: {e}")

