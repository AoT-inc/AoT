# coding=utf-8
"""Provide abstract base template for all controller types.

Ensure that required methods and instance variables are present in every
controller, input, and output subclass.

@phase active
@stability stable
@dependency Conversion, DeviceMeasurements, Input, Output
"""
import json
import logging
import time
from collections import OrderedDict

from sqlalchemy import and_

from aot.config import AOT_DB_PATH
from aot.databases.models import Conversion
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Input
from aot.databases.models import InputChannel
from aot.databases.models import Output
from aot.databases.models import OutputChannel
from aot.databases.utils import session_scope
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import get_last_measurement
from aot.utils.influx import get_past_measurements


class ChannelNotConfigured(KeyError):
    """채널이 설정돼 있지 않은데 드라이버가 그 채널을 꺼내려 했다.

    **KeyError 를 상속한다.** 드라이버 48개가 `options_channels['x'][0]` 을
    수백 곳에서 그냥 꺼내 쓰고, 그 위쪽에 KeyError 를 잡는 코드가 있다 —
    타입을 갈면 그쪽 동작이 조용히 바뀐다. 바꾸는 것은 **메시지뿐**이다.
    """

    def __str__(self):
        # KeyError.__str__ 는 인자를 repr 로 감싸서 문장이 따옴표에 갇힌다.
        # 이 예외의 존재 이유가 읽히는 문장이므로 그대로 내보낸다.
        return self.args[0] if self.args else ''


class _ChannelValues(OrderedDict):
    """옵션 하나의 채널별 값. 없는 채널을 꺼내면 원인을 말한다.

    2026-08-25: 출력 v121 이 `output` 행은 있는데 `output_channel` 행이 없어
    데몬이 기동할 때마다 죽었다. 그때 나온 것은 `KeyError: 0` 한 줄뿐이라,
    "채널이 없다" 는 사실에 닿기까지 DB 를 뒤져야 했다. 가상 출력이라 피해가
    없었지만 같은 코드가 GPIO·펌프·PWM 드라이버 전부를 지난다 — 거기서 나면
    **실제 릴레이가 안 뜨는데 원인은 `KeyError: 0`** 으로만 보인다.

    호출부를 고치지 않는 이유: 이 패턴은 드라이버 48개 수백 곳에 있다. 값을
    만드는 여기 한 곳이 말하면 전부가 함께 말한다.
    """

    __slots__ = ('_option_id', '_owner_id')

    def __init__(self, *args, option_id=None, owner_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._option_id = option_id
        self._owner_id = owner_id

    def __missing__(self, key):
        configured = list(self.keys())
        if configured:
            detail = f"configured channels: {configured}"
        else:
            detail = ("this device has NO channels configured at all — its row "
                      "exists but its channel rows do not, which is what a "
                      "half-finished create or delete leaves behind")
        raise ChannelNotConfigured(
            f"channel {key!r} is not configured for device "
            f"{self._owner_id or '(unknown)'} (option {self._option_id!r}); "
            f"{detail}. Add the channel, or delete the device.")


class AbstractBaseController(object):
    """Provide base template for all controller, input, and output classes.

    @phase active
    @stability stable
    @dependency Conversion, DeviceMeasurements, Input, Output
    """
    def __init__(self, unique_id=None, testing=False, name=__name__):
        logger_name = name
        if not testing and unique_id:
            logger_name += f"_{unique_id.split('-')[0]}"
        self.logger = logging.getLogger(logger_name)

        self.channels_conversion = {}
        self.channels_measurement = {}
        self.device_measurements = None

    def initialize(self):
        pass

    def comm_capable(self):
        """Does this controller have a communication-status concept at all.

        False means "no feedback path exists" (e.g. a local GPIO relay with no
        readback), not "unknown/broken". Subclasses that can actually detect
        reachability (network/bus devices, polling loops) override this.
        """
        return False

    def comm_last_success(self):
        """Epoch timestamp of the last successful communication, or None."""
        return None

    def comm_is_fault(self, channel=None):
        """Is communication currently down. Meaningless (always False) unless comm_capable()."""
        return False

    def comm_is_pending(self, channel=None):
        """Is there an unconfirmed communication in flight (optional concept, default False)."""
        return False

    def try_initialize(self, tries=3, wait_sec=5):
        """Retry initialize() up to a given number of attempts with delay between tries."""
        for i in range(tries):
            try:
                self.initialize()
                break
            except Exception as err:
                if i + 1 < tries:
                    self.logger.exception(f"Error initializing, trying again in {wait_sec} seconds: {err}")
                    time.sleep(wait_sec)
                else:  # Last try
                    self.logger.exception(
                        f"Initialization errored {tries} times; giving up. Maybe the following traceback "
                        f"can help diagnose the issue.")

    def setup_custom_options(self, custom_options, custom_controller):
        """Route custom option parsing to CSV or JSON handler based on format."""
        if not hasattr(custom_controller, 'custom_options'):
            self.logger.error("custom_controller missing attribute custom_options")
            return
        elif custom_controller.custom_options.startswith("{"):
            return self.setup_custom_options_json(custom_options, custom_controller)
        else:
            return self.setup_custom_options_csv(custom_options, custom_controller)

    def setup_device_measurement(self, unique_id):
        """Load device measurement channels and conversions from the database."""
        for _ in range(5):  # Make 5 attempts to access database
            try:
                self.device_measurements = db_retrieve_table_daemon(
                    DeviceMeasurements).filter(
                    DeviceMeasurements.device_id == unique_id)

                for each_measure in self.device_measurements.all():
                    # 전역 자동 VPD 채널(예약 900)은 센서가 읽는 소스 채널이 아니라
                    # run_input_actions 에서 계산·주입되는 출력 전용 채널이다. push/MQTT
                    # 입력이 channels_measurement 를 순회하며 json_name 등 채널 옵션을
                    # 참조할 때 이 채널을 만나 KeyError 나지 않도록 읽기용 맵에서 제외한다.
                    if each_measure.measurement_type == 'auto_vpd':
                        continue
                    self.channels_measurement[each_measure.channel] = each_measure
                    self.channels_conversion[each_measure.channel] = db_retrieve_table_daemon(
                        Conversion, unique_id=each_measure.conversion_id)
                return
            except Exception as msg:
                self.logger.debug(f"Error: {msg}")
            time.sleep(0.1)

    # TODO: Remove in place of JSON function, below, in next major version
    def setup_custom_options_csv(self, custom_options, custom_controller):
        """Parse legacy CSV-formatted custom options and set instance attributes."""
        for each_option_default in custom_options:
            try:
                required = False
                custom_option_set = False
                error = []

                if 'type' not in each_option_default:
                    error.append("'type' not found in custom_options")
                if ('id' not in each_option_default and
                        ('type' in each_option_default and
                         each_option_default['type'] not in ['new_line', 'message', 'header'])):
                    error.append("'id' not found in custom_options")
                if ('default_value' not in each_option_default and
                        ('type' in each_option_default and
                         each_option_default['type'] not in ['new_line', 'header', 'button'])):
                    error.append("'default_value' not found in custom_options")

                for each_error in error:
                    self.logger.error(each_error)
                if error:
                    return

                if each_option_default['type'] in ['new_line', 'message', 'header', 'button']:
                    continue

                if 'required' in each_option_default and each_option_default['required']:
                    required = True

                option_value = each_option_default['default_value']
                device_id = None
                measurement_id = None
                channel_id = None

                if not hasattr(custom_controller, 'custom_options'):
                    self.logger.error("custom_controller missing attribute custom_options")
                    return

                if custom_controller.custom_options:
                    for each_option in custom_controller.custom_options.split(';'):
                        option = each_option.split(',')[0]

                        if option == each_option_default['id']:
                            custom_option_set = True

                            if (each_option_default['type'] in ['select_measurement',
                                                                'select_measurement_from_this_input'] and
                                    len(each_option.split(',')) > 2):
                                device_id = each_option.split(',')[1]
                                measurement_id = each_option.split(',')[2]
                            elif (each_option_default['type'] == 'select_channel' and
                                    len(each_option.split(',')) > 2):
                                device_id = each_option.split(',')[1]
                                channel_id = each_option.split(',')[2]
                            elif (each_option_default['type'] == 'select_measurement_channel' and
                                    len(each_option.split(',')) > 3):
                                device_id = each_option.split(',')[1]
                                measurement_id = each_option.split(',')[2]
                                channel_id = each_option.split(',')[3]
                            else:
                                option_value = each_option.split(',')[1]

                if required and not custom_option_set:
                    self.logger.error(
                        f"Option '{each_option_default['id']}' required but was not found to be set by the user. "
                        f"Setting to default ({option_value}).")

                if each_option_default['type'] == 'integer':
                    setattr(self, each_option_default['id'], int(option_value))

                elif each_option_default['type'] == 'float':
                    setattr(self, each_option_default['id'], float(option_value))

                elif each_option_default['type'] == 'bool':
                    setattr(self, each_option_default['id'], bool(option_value))

                elif each_option_default['type'] in ['multiline_text',
                                                     'text']:
                    # If this is a time input field, parse it to seconds
                    if (each_option_default['type'] == 'text' and
                            'class' in each_option_default and
                            'aot-time-input' in each_option_default['class']):
                        try:
                            from aot.utils.time_utils import parse_flexible_time
                            parsed_time = parse_flexible_time(option_value)
                            if parsed_time:
                                option_value = parsed_time['total_seconds']
                        except Exception as err:
                            self.logger.error(f"Error parsing time option '{each_option_default['id']}': {err}")

                    setattr(self, each_option_default['id'], str(option_value))

                elif each_option_default['type'] == 'select_multi_measurement':
                    setattr(self, each_option_default['id'], str(option_value))

                elif each_option_default['type'] in ['select', 'select_custom_choices']:
                    option_value = str(option_value)
                    if 'cast_value' in each_option_default and each_option_default['cast_value']:
                        if each_option_default['cast_value'] == 'integer':
                            option_value = int(option_value)
                        elif each_option_default['cast_value'] == 'float':
                            option_value = float(option_value)
                    setattr(self, each_option_default['id'], option_value)

                elif each_option_default['type'] in ['select_measurement',
                                                     'select_measurement_from_this_input']:
                    setattr(self, f"{each_option_default['id']}_device_id", device_id)
                    setattr(self, f"{each_option_default['id']}_measurement_id", measurement_id)

                elif each_option_default['type'] == 'select_measurement_channel':
                    setattr(self, f"{each_option_default['id']}_device_id", device_id)
                    setattr(self, f"{each_option_default['id']}_measurement_id", measurement_id)
                    setattr(self, f"{each_option_default['id']}_channel_id", channel_id)

                elif each_option_default['type'] in ['select_type_measurement',
                                                     'select_type_unit']:
                    setattr(self, each_option_default['id'], str(option_value))

                elif each_option_default['type'] == 'select_device':
                    setattr(self, f"{each_option_default['id']}_id", str(option_value))

                elif each_option_default['type'] in ['message', 'new_line']:
                    pass

                else:
                    self.logger.error(
                        f"setup_custom_options_csv() Unknown custom_option type '{each_option_default['type']}'")
            except Exception:
                self.logger.exception("Error parsing custom_options")

    def setup_custom_options_json(self, custom_options, custom_controller):
        """Parse JSON-formatted custom options and set instance attributes."""
        except_option = None

        for each_option_default in custom_options:
            try:
                except_option = each_option_default
                required = False
                custom_option_set = False
                error = []

                if 'type' not in each_option_default:
                    error.append(f"'type' not found in custom_options: {each_option_default}")
                if ('id' not in each_option_default and
                        ('type' in each_option_default and
                         each_option_default['type'] not in ['new_line', 'message', 'header'])):
                    error.append(f"'id' not found in custom_options: {each_option_default}")
                if ('default_value' not in each_option_default and
                        ('type' in each_option_default and
                         each_option_default['type'] not in ['new_line', 'header', 'button'])):
                    error.append(f"'default_value' not found in custom_options: {each_option_default}")

                for each_error in error:
                    self.logger.error(each_error)
                if error:
                    return

                if each_option_default['type'] in ['new_line', 'message', 'header', 'button']:
                    continue

                if 'required' in each_option_default and each_option_default['required']:
                    required = True

                # set default value
                option_value = each_option_default['default_value']
                device_id = None
                measurement_id = None
                channel_id = None

                if not hasattr(custom_controller, 'custom_options'):
                    self.logger.error("custom_controller missing attribute custom_options")
                    return

                if getattr(custom_controller, 'custom_options'):
                    for each_option, each_value in json.loads(getattr(custom_controller, 'custom_options')).items():
                        if each_option == each_option_default['id']:
                            custom_option_set = True

                            if (each_option_default['type'] in ['select_measurement',
                                                                'select_measurement_from_this_input'] and
                                    len(each_value.split(',')) > 1):
                                device_id = each_value.split(',')[0]
                                measurement_id = each_value.split(',')[1]
                            elif (each_option_default['type'] == 'select_channel' and
                                    len(each_value.split(',')) > 1):
                                device_id = each_value.split(',')[0]
                                channel_id = each_value.split(',')[1]
                            elif (each_option_default['type'] == 'select_measurement_channel' and
                                    len(each_value.split(',')) > 2):
                                device_id = each_value.split(',')[0]
                                measurement_id = each_value.split(',')[1]
                                channel_id = each_value.split(',')[2]
                            else:
                                option_value = each_value

                if required and not custom_option_set:
                    self.logger.error(
                        f"Option '{each_option_default['id']}' required but was not found to be set by the user. "
                        f"Setting to default ({option_value}).")

                if each_option_default['type'] in ['integer',
                                                   'float',
                                                   'bool',
                                                   'multiline_text',
                                                   'select_multi_measurement',
                                                   'text',
                                                   'select',
                                                   'select_custom_choices']:
                    # If this is a time input field, parse it to seconds
                    if (each_option_default['type'] == 'text' and
                            'class' in each_option_default and
                            'aot-time-input' in each_option_default['class']):
                        try:
                            from aot.utils.time_utils import parse_flexible_time
                            parsed_time = parse_flexible_time(option_value)
                            if parsed_time:
                                option_value = parsed_time['total_seconds']
                        except Exception as err:
                            self.logger.error(f"Error parsing time option '{each_option_default['id']}': {err}")

                    setattr(self, each_option_default['id'], option_value)

                elif each_option_default['type'] in ['select_measurement',
                                                     'select_measurement_from_this_input']:
                    setattr(self, f"{each_option_default['id']}_device_id", device_id)
                    setattr(self, f"{each_option_default['id']}_measurement_id", measurement_id)

                elif each_option_default['type'] == 'select_channel':
                    setattr(self, f"{each_option_default['id']}_device_id", device_id)
                    setattr(self, f"{each_option_default['id']}_channel_id", channel_id)

                elif each_option_default['type'] == 'select_measurement_channel':
                    setattr(self, f"{each_option_default['id']}_device_id", device_id)
                    setattr(self, f"{each_option_default['id']}_measurement_id", measurement_id)
                    setattr(self, f"{each_option_default['id']}_channel_id", channel_id)

                elif each_option_default['type'] == 'select_type_measurement':
                    setattr(self, each_option_default['id'], str(option_value))

                elif each_option_default['type'] == 'select_type_unit':
                    setattr(self, each_option_default['id'], str(option_value))

                elif each_option_default['type'] == 'select_device':
                    setattr(self, f"{each_option_default['id']}_id", str(option_value))

                else:
                    self.logger.error(
                        f"setup_custom_options_json() Unknown option type '{each_option_default['type']}'")
            except Exception:
                self.logger.exception(f"Error parsing option: {except_option}")

    def setup_custom_channel_options_json(self, custom_options, custom_controller_channels):
        """Parse JSON-formatted per-channel custom options into a nested dict."""
        dict_values = {}
        except_option = None

        # 채널이 하나도 없으면 아래 루프가 통째로 안 돌아 모든 옵션이 빈 칸이
        # 된다. 그 사실은 드라이버가 값을 꺼낼 때에야 예외로 드러나는데, 그때는
        # 이미 어느 옵션에서 터졌는지가 이야기의 전부가 되어 원인이 가려진다.
        # **여기서 한 번 말해 두면 로그의 첫 줄이 진짜 원인이 된다.**
        if not custom_controller_channels:
            self.logger.error(
                "No channels are configured for this device (%s). Its row "
                "exists but its channel rows do not — a half-finished create "
                "or delete leaves exactly this. Every per-channel option below "
                "will be empty and initialization will fail.",
                getattr(self, 'unique_id', '(unknown)'))
        for each_option_default in custom_options:
            try:
                except_option = each_option_default
                required = False
                custom_option_set = False
                error = []

                if 'type' not in each_option_default:
                    error.append(f"'type' not found in custom_options: {each_option_default}")
                if ('id' not in each_option_default and
                        ('type' in each_option_default and
                         each_option_default['type'] not in ['new_line', 'message', 'header'])):
                    error.append(f"'id' not found in custom_options: {each_option_default}")
                if ('default_value' not in each_option_default and
                        ('type' in each_option_default and
                         each_option_default['type'] not in ['new_line', 'header', 'button'])):
                    error.append(f"'default_value' not found in custom_options: {each_option_default}")

                for each_error in error:
                    self.logger.error(each_error)
                if error:
                    return

                if each_option_default['type'] in ['new_line', 'message', 'header', 'button']:
                    continue

                dict_values[each_option_default['id']] = _ChannelValues(
                    option_id=each_option_default['id'],
                    owner_id=getattr(self, 'unique_id', None))

                if 'required' in each_option_default and each_option_default['required']:
                    required = True

                for each_channel in custom_controller_channels:
                    channel = each_channel.channel

                    # set default value
                    dict_values[each_option_default['id']][channel] = each_option_default['default_value']

                    if each_option_default['type'] == 'select_measurement':
                        dict_values[each_option_default['id']][channel] = {}
                        dict_values[each_option_default['id']][channel]['device_id'] = None
                        dict_values[each_option_default['id']][channel]['measurement_id'] = None
                        dict_values[each_option_default['id']][channel]['channel_id'] = None

                    elif each_option_default['type'] == 'select_channel':
                        dict_values[each_option_default['id']][channel] = {}
                        dict_values[each_option_default['id']][channel]['device_id'] = None
                        dict_values[each_option_default['id']][channel]['channel_id'] = None

                    elif each_option_default['type'] == 'select_measurement_channel':
                        dict_values[each_option_default['id']][channel] = {}
                        dict_values[each_option_default['id']][channel]['device_id'] = None
                        dict_values[each_option_default['id']][channel]['measurement_id'] = None
                        dict_values[each_option_default['id']][channel]['channel_id'] = None

                    if not hasattr(each_channel, 'custom_options'):
                        self.logger.error("custom_controller missing attribute custom_options")
                        return

                    if getattr(each_channel, 'custom_options'):
                        for each_option, each_value in json.loads(getattr(each_channel, 'custom_options')).items():
                            if each_option == each_option_default['id']:
                                custom_option_set = True

                                if each_option_default['type'] == 'select_measurement':
                                    if len(each_value.split(',')) > 1:
                                        dict_values[each_option_default['id']][channel]['device_id'] = each_value.split(',')[0]
                                        dict_values[each_option_default['id']][channel]['measurement_id'] = each_value.split(',')[1]
                                    if len(each_value.split(',')) > 2:
                                        dict_values[each_option_default['id']][channel]['channel_id'] = each_value.split(',')[2]
                                elif each_option_default['type'] == 'select_channel':
                                    if len(each_value.split(',')) > 1:
                                        dict_values[each_option_default['id']][channel]['device_id'] = each_value.split(',')[0]
                                        dict_values[each_option_default['id']][channel]['channel_id'] = each_value.split(',')[1]
                                elif each_option_default['type'] == 'select_measurement_channel':
                                    if len(each_value.split(',')) > 1:
                                        dict_values[each_option_default['id']][channel]['device_id'] = each_value.split(',')[0]
                                        dict_values[each_option_default['id']][channel]['measurement_id'] = each_value.split(',')[1]
                                        dict_values[each_option_default['id']][channel]['channel_id'] = each_value.split(',')[2]
                                else:
                                    dict_values[each_option_default['id']][channel] = each_value

                    if required and not custom_option_set:
                        self.logger.error(
                            f"Option '{each_option_default['id']}' required but was not found to be set by the user")
            except Exception:
                self.logger.exception(f"Error parsing option: {except_option}")

        return dict_values

    def _delete_custom_option(self, controller, unique_id, option):
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                mod_function = new_session.query(controller).filter(
                    controller.unique_id == unique_id).first()
                try:
                    dict_custom_options = json.loads(mod_function.custom_options)
                except:
                    dict_custom_options = {}
                if option in dict_custom_options:
                    dict_custom_options.pop(option)
                    mod_function.custom_options = json.dumps(dict_custom_options)
                    new_session.commit()
        except Exception:
            self.logger.exception("delete_custom_option")

    def _set_custom_option(self, controller, unique_id, option, value):
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                mod_function = new_session.query(controller).filter(
                    controller.unique_id == unique_id).first()
                try:
                    dict_custom_options = json.loads(mod_function.custom_options)
                except:
                    dict_custom_options = {}
                dict_custom_options[option] = value
                mod_function.custom_options = json.dumps(dict_custom_options)
                new_session.commit()
            return value
        except Exception:
            self.logger.exception("set_custom_option")

    def _get_custom_option(self, controller, unique_id, option, default_return=None):
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                read_function = new_session.query(controller).filter(
                    controller.unique_id == unique_id).first()
                new_session.expunge_all()
                try:
                    dict_custom_options = json.loads(read_function.custom_options)
                except:
                    dict_custom_options = {}
                if option in dict_custom_options:
                    return dict_custom_options[option]
        except Exception:
            self.logger.exception("get_custom_option")
        return default_return

    def _delete_custom_channel_option(self, controller, unique_id, channel, option):
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                if controller == Output:
                    channel = new_session.query(OutputChannel).filter(and_(
                        OutputChannel.output_id == unique_id,
                        OutputChannel.channel == channel)).first()
                elif controller == Input:
                    channel = new_session.query(InputChannel).filter(and_(
                        InputChannel.input_id == unique_id,
                        InputChannel.channel == channel)).first()
                else:
                    return "controller doesn't represent Output or Input"
                try:
                    dict_custom_options = json.loads(channel.custom_options)
                except:
                    dict_custom_options = {}
                if option in dict_custom_options:
                    dict_custom_options.pop(option)
                    channel.custom_options = json.dumps(dict_custom_options)
                    new_session.commit()
        except Exception:
            self.logger.exception("delete_custom_option")

    def _set_custom_channel_option(self, controller, unique_id, channel, option, value):
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                if controller == Output:
                    channel = new_session.query(OutputChannel).filter(and_(
                        OutputChannel.output_id == unique_id,
                        OutputChannel.channel == channel)).first()
                elif controller == Input:
                    channel = new_session.query(InputChannel).filter(and_(
                        InputChannel.input_id == unique_id,
                        InputChannel.channel == channel)).first()
                else:
                    return "controller doesn't represent Output or Input"
                try:
                    dict_custom_options = json.loads(channel.custom_options)
                except:
                    dict_custom_options = {}
                dict_custom_options[option] = value
                channel.custom_options = json.dumps(dict_custom_options)
                new_session.commit()
            return value
        except Exception:
            self.logger.exception("set_custom_option")

    def _get_custom_channel_option(self, controller, unique_id, channel, option):
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                if controller == Output:
                    channel = new_session.query(OutputChannel).filter(and_(
                        OutputChannel.output_id == unique_id,
                        OutputChannel.channel == channel)).first()
                elif controller == Input:
                    channel = new_session.query(InputChannel).filter(and_(
                        InputChannel.input_id == unique_id,
                        InputChannel.channel == channel)).first()
                else:
                    return "controller doesn't represent Output or Input"
                new_session.expunge_all()
                try:
                    dict_custom_options = json.loads(channel.custom_options)
                except:
                    dict_custom_options = {}
                if option in dict_custom_options:
                    return dict_custom_options[option]
        except Exception:
            self.logger.exception("get_custom_option")

    @staticmethod
    def get_last_measurement(device_id, measurement_id, max_age=None):
        """Retrieve the most recent measurement from InfluxDB."""
        return get_last_measurement(device_id, measurement_id, max_age=max_age)

    @staticmethod
    def get_past_measurements(device_id, measurement_id, max_age=None):
        """Retrieve past measurements from InfluxDB within a time window."""
        return get_past_measurements(device_id, measurement_id, max_age=max_age)

    @staticmethod
    def get_output_channel_from_channel_id(channel_id):
        """Return channel number from channel ID."""
        output_channel = db_retrieve_table_daemon(
            OutputChannel).filter(
            OutputChannel.unique_id == channel_id).first()
        if output_channel:
            return output_channel.channel
