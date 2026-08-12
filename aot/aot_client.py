# coding=utf-8
#
#  Copyright (C) 2015-2022 Kyle T. Gabriel <mycodo@kylegabriel.com>
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
#  along with Mycodo. If not, see <https://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com

import argparse
import datetime
import logging
import os
import sys
import threading
import time
import traceback

import Pyro5.errors
from Pyro5.api import Proxy

sys.path.append(os.path.abspath(os.path.join(os.path.realpath(__file__), '../..')))

from aot.config import PYRO_URI
from aot.databases.models import SMTP, Misc
from aot.utils.command_origin import resolve_origin
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.send_data import send_email as send_email_notification
from aot.utils.widget_generate_html import generate_widget_html

logger = logging.getLogger(__name__)


def daemon_call_failed(ret):
    """Read a DaemonControl control-call result as (failed: bool, msg: str).

    The control methods below (output_on/output_off/output_on_off/...) do NOT
    raise on failure -- they catch Pyro5 timeouts and communication errors and
    return a ``(code, msg)`` tuple with a non-zero code (see output_off). A
    caller that only wraps the call in try/except therefore never sees the
    failure and reports success, which is how an e-stop could answer
    ``{'ok': True, 'failed': 0}`` while every channel had timed out.

    Use this at every control call site instead of relying on exceptions.
    Unknown/legacy shapes (None, plain strings) are reported as success so
    this stays safe to drop into existing call sites.
    """
    if isinstance(ret, tuple) and len(ret) == 2:
        try:
            if int(ret[0]) != 0:
                return True, str(ret[1])
        except (TypeError, ValueError):
            return False, ''
    return False, ''


class DaemonControl:
    """Communicate with the daemon to execute commands or retrieve information."""
    _rpc_timeout_cache = {}

    # output_states_all TTL cache: (result, expires_at)
    _states_all_cache = (None, 0.0)
    _states_all_lock = threading.Lock()
    _STATES_CACHE_TTL = 3.0  # seconds

    # input_status_all TTL cache: (result, expires_at) — separate slot from the
    # output cache above (io_link_health_infra_plan.md Phase D), same 3s TTL
    # rationale (the polling UI period on the Input page, aot-flask input.html).
    _input_status_all_cache = (None, 0.0)
    _input_status_all_lock = threading.Lock()

    _MAX_RPC_TIMEOUT = 10        # hard cap for most callers
    _MAX_RPC_TIMEOUT_EXTENDED = 120  # cap for callers that explicitly need longer (e.g. remote output with long-running commands)

    def __init__(self, pyro_uri=PYRO_URI, pyro_timeout=None, extended_timeout=False):
        self.pyro_timeout = 8
        cap = self._MAX_RPC_TIMEOUT_EXTENDED if extended_timeout else self._MAX_RPC_TIMEOUT
        try:
            if pyro_timeout:
                self.pyro_timeout = min(pyro_timeout, cap)
            elif cap in DaemonControl._rpc_timeout_cache:
                self.pyro_timeout = DaemonControl._rpc_timeout_cache[cap]
            else:
                misc = db_retrieve_table_daemon(Misc, entry='first')
                if misc:
                    self.pyro_timeout = min(misc.rpyc_timeout, cap)
                    DaemonControl._rpc_timeout_cache[cap] = self.pyro_timeout
        except Exception:
            logger.exception("Could not access SQL table to determine Pyro Timeout. Using 8 seconds.")

        self.uri = pyro_uri

    def proxy(self, timeout=None):
        try:
            proxy = Proxy(self.uri)
            if timeout:
                proxy._pyroTimeout = timeout
            else:
                proxy._pyroTimeout = self.pyro_timeout
            return proxy
        except Exception as e:
            logger.error(f"Pyro5 proxy error: {e}")

    #
    # Status functions
    #

    def check_daemon(self):
        proxy = self.proxy()
        old_timeout = proxy._pyroTimeout
        try:
            proxy._pyroTimeout = 10
            result = proxy.check_daemon()
            if result:
                return result
            else:
                return "GOOD"
        except Pyro5.errors.TimeoutError as err:
            msg = f"Pyro5 TimeoutError: {err}"
            logger.error(msg)
            return msg
        except Pyro5.errors.CommunicationError as err:
            msg = f"Pyro5 Communication error: {err}"
            logger.error(msg)
            return msg
        except Pyro5.errors.NamingError as err:
            msg = f"Failed to locate Pyro5 Nameserver: {err}"
            logger.error(msg)
            return msg
        except Exception as err:
            msg = f"Pyro Exception: {err}"
            logger.error(msg)
            return msg
        finally:
            proxy._pyroTimeout = old_timeout

    def controller_is_active(self, controller_id):
        return self.proxy().controller_is_active(controller_id)

    def daemon_status(self):
        return self.proxy().daemon_status()

    def is_in_virtualenv(self):
        return self.proxy().is_in_virtualenv()

    def ram_use(self):
        return self.proxy().ram_use()

    def system_environment(self):
        """Runtime environment snapshot collected at daemon startup."""
        return self.proxy().system_environment()

    #
    # Daemon
    #

    def controller_activate(self, controller_id):
        return self.proxy().controller_activate(controller_id)

    def controller_deactivate(self, controller_id):
        return self.proxy().controller_deactivate(controller_id)

    def controller_restart(self, controller_id):
        return self.proxy().controller_restart(controller_id)

    def refresh_daemon_conditional_settings(self, unique_id):
        return self.proxy().refresh_daemon_conditional_settings(unique_id)

    def refresh_daemon_misc_settings(self):
        return self.proxy().refresh_daemon_misc_settings()

    def refresh_daemon_trigger_settings(self, unique_id):
        return self.proxy().refresh_daemon_trigger_settings(unique_id)

    def terminate_daemon(self):
        return self.proxy().terminate_daemon()

    #
    # Function Actions
    #

    def trigger_action(
            self, action_id, value={}, debug=False):
        return self.proxy().trigger_action(
            action_id, value=value, debug=debug)

    def trigger_all_actions(self, function_id, message='', debug=False):
        return self.proxy().trigger_all_actions(
            function_id, message=message, debug=debug)

    #
    # Input Controller
    #

    def input_force_measurements(self, input_id):
        try:
            return self.proxy().input_force_measurements(input_id)
        except Exception:
            return 0, traceback.format_exc()

    #
    # Display
    #

    def lcd_backlight(self, lcd_id, state):
        return self.proxy().lcd_backlight(lcd_id, state)

    def display_backlight_color(self, lcd_id, color):
        return self.proxy().display_backlight_color(lcd_id, color)

    def lcd_flash(self, lcd_id, state):
        return self.proxy().lcd_flash(lcd_id, state)

    def lcd_reset(self, lcd_id):
        return self.proxy().lcd_reset(lcd_id)

    #
    # Measurements
    #

    def get_condition_measurement(self, condition_id, function_id=None):
        return self.proxy().get_condition_measurement(condition_id)

    def get_condition_measurement_dict(self, condition_id):
        return self.proxy().get_condition_measurement_dict(condition_id)

    #
    # Output Controller
    #

    @classmethod
    def invalidate_states_cache(cls):
        """Drop the cached output-state snapshot after a command changes an output.

        output_states_all() caches for _STATES_CACHE_TTL seconds so the polling
        dashboard does not hammer the daemon, but nothing used to clear it when a
        command actually changed a state. For up to 3s afterwards a read-back
        returned the PRE-command snapshot, while `seconds_on` — a separate,
        uncached call — already counted from the new one. get_output_state, the
        very tool an AI uses to confirm what it just toggled, would answer
        "state: off, seconds_on: 1.08" and tell the operator the command had not
        worked. Measured locally: wrong for ~2s after ON, and after OFF it kept
        reporting 'on'.
        """
        with cls._states_all_lock:
            cls._states_all_cache = (None, 0.0)

    def output_off(self, output_id, output_channel=None, trigger_conditionals=True):
        try:
            origin = resolve_origin()
            try:
                return self.proxy().output_off(
                    output_id, output_channel=output_channel,
                    trigger_conditionals=trigger_conditionals, origin=origin)
            except TypeError:
                # 구버전 데몬은 origin 인자를 모른다. 업그레이드 중 aotflask 가
                # 먼저 올라온 창에서 제어가 막히면 안 되므로 인자 없이 재시도한다.
                logger.warning("데몬이 origin 인자를 지원하지 않습니다 — 출처 없이 전송합니다")
                return self.proxy().output_off(
                    output_id, output_channel=output_channel,
                    trigger_conditionals=trigger_conditionals)
        except Pyro5.errors.TimeoutError as err:
            msg = f"Output OFF timed out: {err}"
            logger.error(msg)
            return 1, msg
        except Pyro5.errors.CommunicationError as err:
            msg = f"Output OFF communication error: {err}"
            logger.error(msg)
            return 1, msg
        except Exception as err:
            msg = f"Output OFF error: {err}"
            logger.error(msg)
            return 1, msg
        finally:
            # In `finally`, not on the success path: a timed-out or errored
            # command may still have reached the daemon, so a snapshot taken
            # before it must not keep being served either way.
            DaemonControl.invalidate_states_cache()

    def output_on(self,
                  output_id,
                  output_type=None,
                  amount=0.0,
                  min_off=0.0,
                  output_channel=None,
                  trigger_conditionals=True,
                  additional_options=None):
        try:
            origin = resolve_origin()
            try:
                return self.proxy().output_on(
                    output_id, output_type=output_type, amount=amount, min_off=min_off,
                    output_channel=output_channel, trigger_conditionals=trigger_conditionals,
                    additional_options=additional_options, origin=origin)
            except TypeError:
                logger.warning("데몬이 origin 인자를 지원하지 않습니다 — 출처 없이 전송합니다")
                return self.proxy().output_on(
                    output_id, output_type=output_type, amount=amount, min_off=min_off,
                    output_channel=output_channel, trigger_conditionals=trigger_conditionals,
                    additional_options=additional_options)
        except Pyro5.errors.TimeoutError as err:
            msg = f"Output ON timed out: {err}"
            logger.error(msg)
            return 1, msg
        except Pyro5.errors.CommunicationError as err:
            msg = f"Output ON communication error: {err}"
            logger.error(msg)
            return 1, msg
        except Exception as err:
            msg = f"Output ON error: {err}"
            logger.error(msg)
            return 1, msg
        finally:
            # See output_off — invalidate regardless of outcome.
            DaemonControl.invalidate_states_cache()

    def output_on_off(self, output_id, state, output_type=None, amount=0.0, output_channel=None):
        """Turn an output on or off."""
        if state in ['on', 1, True]:
            return self.output_on(
                output_id, amount=amount, output_type=output_type, output_channel=output_channel)
        elif state in ['off', 0, False]:
            return self.output_off(output_id, output_channel=output_channel)
        else:
            return 1, f'state not "on", 1, True, "off", 0, or False. Found: "{state}"'

    def output_sec_currently_on(self, output_id, output_channel=None):
        """Return the amount of seconds an on/off output channel has been on."""
        return self.proxy().output_sec_currently_on(output_id, output_channel)

    def output_setup(self, action, output_id):
        return self.proxy().output_setup(action, output_id)

    def output_state(self, output_id, output_channel):
        try:
            return self.proxy().output_state(output_id, output_channel)
        except Pyro5.errors.TimeoutError as err:
            msg = f"Output state timed out: {err}"
            logger.error(msg)
            return None
        except Pyro5.errors.CommunicationError as err:
            msg = f"Output state communication error: {err}"
            logger.error(msg)
            return None
        except Exception as err:
            msg = f"Output state error: {err}"
            logger.error(msg)
            return None

    def output_states_all(self):
        now = time.monotonic()
        with DaemonControl._states_all_lock:
            cached, expires = DaemonControl._states_all_cache
            if cached is not None and now < expires:
                return cached
        result = None
        try:
            result = self.proxy().output_states_all()
        except Pyro5.errors.TimeoutError as err:
            logger.error(f"output_states_all timed out: {err}")
        except Pyro5.errors.CommunicationError as err:
            logger.error(f"output_states_all communication error: {err}")
        except Exception as err:
            logger.error(f"output_states_all error: {err}")
        # Cache the failure as well. With this write inside the try, a daemon
        # that is down or slow was never cached, so every caller paid the full
        # RPC timeout again -- the cache stopped working at exactly the moment
        # it was needed, and the polling UI multiplied that cost per request.
        with DaemonControl._states_all_lock:
            DaemonControl._states_all_cache = (
                result or {}, now + DaemonControl._STATES_CACHE_TTL)
        return result if result is not None else {}

    def input_status_all(self):
        """Comm status (comm_capable/comm_is_fault/comm_last_success) for all Inputs.

        Same failure convention as output_states_all(): any RPC problem (daemon
        down, timeout) returns {} rather than raising, so callers (the
        /inputstate route) degrade gracefully instead of 500ing.
        """
        now = time.monotonic()
        with DaemonControl._input_status_all_lock:
            cached, expires = DaemonControl._input_status_all_cache
            if cached is not None and now < expires:
                return cached
        result = None
        try:
            result = self.proxy().input_status_all()
        except Pyro5.errors.TimeoutError as err:
            logger.error(f"input_status_all timed out: {err}")
        except Pyro5.errors.CommunicationError as err:
            logger.error(f"input_status_all communication error: {err}")
        except Exception as err:
            logger.error(f"input_status_all error: {err}")
        # Failures are cached too -- see output_states_all() for why.
        with DaemonControl._input_status_all_lock:
            DaemonControl._input_status_all_cache = (
                result or {}, now + DaemonControl._STATES_CACHE_TTL)
        return result if result is not None else {}

    def output_comm_capable_all(self):
        """{output_id: bool} — can this Output observe its device's state at all.

        Static per output (driver + configured status path), so callers fetch it
        once per page rather than on every state poll; no TTL cache needed here.
        Same degrade-to-empty convention as output_states_all().
        """
        try:
            return self.proxy().output_comm_capable_all()
        except Pyro5.errors.TimeoutError as err:
            logger.error(f"output_comm_capable_all timed out: {err}")
            return {}
        except Pyro5.errors.CommunicationError as err:
            logger.error(f"output_comm_capable_all communication error: {err}")
            return {}
        except Exception as err:
            logger.error(f"output_comm_capable_all error: {err}")
            return {}

    def output_target_pct(self, output_id, output_channel=0):
        try:
            return self.proxy().output_target_pct(output_id, output_channel)
        except Exception as err:
            logger.error(f"output_target_pct error: {err}")
            return None, None

    #
    # PID Controller
    #

    def pid_hold(self, pid_id):
        return self.proxy().pid_hold(pid_id)

    def pid_mod(self, pid_id):
        return self.proxy().pid_mod(pid_id)

    def pid_pause(self, pid_id):
        return self.proxy().pid_pause(pid_id)

    def pid_resume(self, pid_id):
        return self.proxy().pid_resume(pid_id)

    def pid_get(self, pid_id, setting):
        return self.proxy().pid_get(pid_id, setting)

    def pid_set(self, pid_id, setting, value):
        return self.proxy().pid_set(pid_id, setting, value)

    #
    # Functions
    #

    def function_status(self, function_id):
        return self.proxy().function_status(function_id)

    #
    # Miscellaneous
    #

    @staticmethod
    def send_email(recipients, message, subject=''):
        smtp = db_retrieve_table_daemon(SMTP, entry='first')
        if smtp is None:
            logger.error("SMTP 설정을 읽지 못해 이메일 발송을 건너뛴다")
            return
        send_email_notification(
            smtp.host, smtp.protocol, smtp.port,
            smtp.user, smtp.passw, smtp.email_from,
            recipients, message, subject=subject)

    def module_function(self, controller_type, unique_id, button_id, args_dict, thread=True, return_from_function=False, timeout=None):
        try:
            return self.proxy(timeout=timeout).module_function(
                controller_type, unique_id, button_id, args_dict, thread=thread, return_from_function=return_from_function)
        except Exception:
            return 1, traceback.format_exc()

    def widget_add_refresh(self, unique_id):
        try:
            return self.proxy().widget_add_refresh(unique_id)
        except Pyro5.errors.CommunicationError as err:
            logger.error("widget_add_refresh: daemon not reachable: %s", err)
        except Exception:
            logger.exception("widget_add_refresh error")

    def widget_remove(self, unique_id):
        try:
            return self.proxy().widget_remove(unique_id)
        except Pyro5.errors.CommunicationError as err:
            logger.error("widget_remove: daemon not reachable: %s", err)
        except Exception:
            logger.exception("widget_remove error")

    def widget_execute(self, unique_id):
        try:
            return self.proxy().widget_execute(unique_id)
        except Pyro5.errors.CommunicationError as err:
            logger.error("widget_execute: daemon not reachable: %s", err)
        except Exception:
            logger.exception("widget_execute error")

def daemon_active():
    """Used to determine if the daemon is reachable to communicate."""
    try:
        daemon = DaemonControl()
        if daemon.check_daemon() != 'GOOD':
            return False
        return True
    except Exception:
        return False


def parseargs(parser):
    # Daemon
    parser.add_argument('-c', '--checkdaemon', action='store_true',
                        help="Check if all active daemon controllers are running")
    parser.add_argument('--activatecontroller', nargs=2,
                        metavar=('CONTROLLER', 'ID'), type=str,
                        help='Activate controller. Options: Conditional, PID, Input',
                        required=False)
    parser.add_argument('--deactivatecontroller', nargs=2,
                        metavar=('CONTROLLER', 'ID'), type=str,
                        help='Deactivate controller. Options: Conditional, PID, Input',
                        required=False)
    parser.add_argument('--ramuse', action='store_true',
                        help="Return the amount of ram used by the AoT daemon")
    parser.add_argument('-t', '--terminate', action='store_true',
                        help="Terminate the daemon")

    # Function Actions
    parser.add_argument('--trigger_action', metavar='ACTIONID', type=str,
                        help='Trigger action with Action ID',
                        required=False)
    parser.add_argument('--trigger_all_actions', metavar='FUNCTIONID', type=str,
                        help='Trigger all actions belonging to Function with ID',
                        required=False)

    # Input Controller
    parser.add_argument('--input_force_measurements', metavar='INPUTID', type=str,
                        help='Force acquiring measurements for Input ID',
                        required=False)

    # LCD Controller
    parser.add_argument('--backlight_on', metavar='LCDID', type=str,
                        help='Turn on LCD backlight with LCD ID',
                        required=False)
    parser.add_argument('--backlight_off', metavar='LCDID', type=str,
                        help='Turn off LCD backlight with LCD ID',
                        required=False)
    parser.add_argument('--lcd_reset', metavar='LCDID', type=str,
                        help='Reset LCD with LCD ID',
                        required=False)

    # Output Controller
    parser.add_argument('--output_state', metavar='OUTPUTID', type=str,
                        help='State of output with output ID',
                        required=False)
    parser.add_argument('--output_currently_on', metavar='OUTPUTID', type=str,
                        help='How many seconds an output has currently been active for',
                        required=False)
    parser.add_argument('--outputoff', metavar='OUTPUTID', type=str,
                        help='Turn off output with output ID',
                        required=False)
    parser.add_argument('--outputon', metavar='OUTPUTID', type=str,
                        help='Turn on output with output ID',
                        required=False)
    parser.add_argument('--duration', metavar='SECONDS', type=float,
                        help='Turn on output for a duration of time (seconds)',
                        required=False)
    parser.add_argument('--dutycycle', metavar='DUTYCYCLE', type=float,
                        help='Turn on PWM output for a duty cycle (%%)',
                        required=False)
    parser.add_argument('--output_channel', metavar='OUTPUTCHANNEL', type=int,
                        help='The output channel to modulate',
                        required=False)

    # PID Controller
    parser.add_argument('--pid_pause', nargs=1,
                        metavar='ID', type=str,
                        help='Pause PID controller.',
                        required=False)
    parser.add_argument('--pid_hold', nargs=1,
                        metavar='ID', type=str,
                        help='Hold PID controller.',
                        required=False)
    parser.add_argument('--pid_resume', nargs=1,
                        metavar='ID', type=str,
                        help='Resume PID controller.',
                        required=False)
    parser.add_argument('--pid_get_setpoint', nargs=1,
                        metavar='ID', type=str,
                        help='Get the setpoint value of the PID controller.',
                        required=False)
    parser.add_argument('--pid_get_error', nargs=1,
                        metavar='ID', type=str,
                        help='Get the error value of the PID controller.',
                        required=False)
    parser.add_argument('--pid_get_integrator', nargs=1,
                        metavar='ID', type=str,
                        help='Get the integrator value of the PID controller.',
                        required=False)
    parser.add_argument('--pid_get_derivator', nargs=1,
                        metavar='ID', type=str,
                        help='Get the derivator value of the PID controller.',
                        required=False)
    parser.add_argument('--pid_get_kp', nargs=1,
                        metavar='ID', type=str,
                        help='Get the Kp gain of the PID controller.',
                        required=False)
    parser.add_argument('--pid_get_ki', nargs=1,
                        metavar='ID', type=str,
                        help='Get the Ki gain of the PID controller.',
                        required=False)
    parser.add_argument('--pid_get_kd', nargs=1,
                        metavar='ID', type=str,
                        help='Get the Kd gain of the PID controller.',
                        required=False)
    parser.add_argument('--pid_set_setpoint', nargs=2,
                        metavar=('ID', 'SETPOINT'), type=str,
                        help='Set the setpoint value of the PID controller.',
                        required=False)
    parser.add_argument('--pid_set_integrator', nargs=2,
                        metavar=('ID', 'INTEGRATOR'), type=str,
                        help='Set the integrator value of the PID controller.',
                        required=False)
    parser.add_argument('--pid_set_derivator', nargs=2,
                        metavar=('ID', 'DERIVATOR'), type=str,
                        help='Set the derivator value of the PID controller.',
                        required=False)
    parser.add_argument('--pid_set_kp', nargs=2,
                        metavar=('ID', 'KP'), type=str,
                        help='Set the Kp gain of the PID controller.',
                        required=False)
    parser.add_argument('--pid_set_ki', nargs=2,
                        metavar=('ID', 'KI'), type=str,
                        help='Set the Ki gain of the PID controller.',
                        required=False)
    parser.add_argument('--pid_set_kd', nargs=2,
                        metavar=('ID', 'KD'), type=str,
                        help='Set the Kd gain of the PID controller.',
                        required=False)

    # Widgets
    parser.add_argument('--gen_widget_html', action='store_true',
                        help="Generate all widget HTML files")

    return parser.parse_args()


if __name__ == "__main__":
    # 로깅 설정은 **진입점에서만** 한다. 예전에는 이 줄이 모듈 최상단에 있어,
    # 이 모듈을 import 하는 것만으로 프로세스 전역 로깅이 stdout 으로 바뀌었다
    # — flask 라우트·유틸 등 12곳 이상이 이 모듈을 import 한다.
    #
    # 두 번 물렸다. (1) `docker_backup_cli` 는 stdout 이 caller 가 파싱하는
    # 값(백업 경로)인데 로그 한 줄이 섞여 상태 파일이 오염됐다(v26.08.4 에서
    # 발견, 그쪽은 force=True 로 되돌려 막아 뒀다). (2) 테스트에서 이 모듈이
    # import 되는 순간 root 핸들러가 갈려 그 뒤에 도는 테스트의 caplog 이
    # 로그를 못 받았다 — `test_safety_service` 가 전체 스위트에서만 실패하고
    # 단독 실행에서는 통과해 원인을 찾기 어려웠다.
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='%(asctime)s %(message)s'
    )

    now = datetime.datetime.now
    parser = argparse.ArgumentParser(description="Client for AoT daemon.")
    args = parseargs(parser)
    daemon = DaemonControl()

    if args.checkdaemon:
        return_msg = daemon.check_daemon()
        logger.info(f"[Remote command] Check Daemon: {return_msg}")

    elif args.ramuse:
        return_msg = daemon.ram_use()
        logger.info(f"[Remote command] Daemon Ram in Use: {return_msg} MB")

    elif args.input_force_measurements:
        return_msg = daemon.input_force_measurements(args.input_force_measurements)
        logger.info(
            "[Remote command] Force acquiring measurements for Input with "
            f"ID '{args.input_force_measurements}': Server returned: {return_msg[1]}")

    elif args.lcd_reset:
        return_msg = daemon.lcd_reset(args.lcd_reset)
        logger.info(f"[Remote command] Reset LCD with ID '{args.lcd_reset}': Server returned: {return_msg}")

    elif args.backlight_off:
        return_msg = daemon.lcd_backlight(args.backlight_off, 0)
        logger.info("[Remote command] Turn off LCD backlight with "
                    f"ID '{args.backlight_off}': Server returned: {return_msg}")

    elif args.backlight_on:
        return_msg = daemon.lcd_backlight(args.backlight_on, 1)
        logger.info("[Remote command] Turn on LCD backlight with "
                    f"ID '{args.backlight_on}': Server returned: {return_msg}")

    elif args.output_currently_on and args.output_channel is None:
        parser.error("--output_currently_on requires --output_channel")

    elif args.output_currently_on:
        return_msg = daemon.output_sec_currently_on(
            args.output_currently_on, output_channel=args.output_channel)
        logger.info("[Remote command] How many seconds output has been on. "
                    f"ID '{args.output_currently_on}' CH{args.output_channel}: "
                    f"Server returned: {return_msg}")

    elif args.output_state and args.output_channel is None:
        parser.error("--output_state requires --output_channel")

    elif args.output_state:
        return_msg = daemon.output_state(args.output_state, args.output_channel)
        logger.info("[Remote command] State of output with "
                    f"ID '{args.output_state}' CH{args.output_channel}: "
                    f"Server returned: {return_msg}")

    elif args.outputoff and args.output_channel is None:
        parser.error("--outputoff requires --output_channel")

    elif args.outputoff:
        return_msg = daemon.output_off(args.outputoff, args.output_channel)
        logger.info("[Remote command] Turn off output with "
                    f"ID '{args.outputoff}': Server returned: {return_msg}")

    elif args.duration and args.outputon is None:
        parser.error("--duration requires --outputon")

    elif args.outputon and args.output_channel is None:
        parser.error("--outputon requires --output_channel")

    elif args.outputon:
        if args.duration:
            return_msg = daemon.output_on(
                args.outputon,
                output_type='sec',
                amount=args.duration,
                output_channel=args.output_channel)
        elif args.dutycycle:
            return_msg = daemon.output_on(
                args.outputon,
                output_type='pwm',
                amount=args.dutycycle,
                output_channel=args.output_channel)
        else:
            return_msg = daemon.output_on(
                args.outputon,
                output_channel=args.output_channel)
        logger.info(f"[Remote command] Turn on output with ID '{args.outputon}': Server returned: {return_msg}")

    elif args.activatecontroller:
        return_msg = daemon.controller_activate(
            args.activatecontroller[0])
        logger.info("[Remote command] Activate controller with "
                    f"ID '{args.activatecontroller[0]}': Server returned: {return_msg}")

    elif args.deactivatecontroller:
        return_msg = daemon.controller_deactivate(
            args.deactivatecontroller[0])
        logger.info("[Remote command] Deactivate controller with "
                    f"ID '{args.deactivatecontroller[0]}': Server returned: {return_msg}")

    elif args.pid_pause:
        daemon.pid_pause(args.pid_pause[0])

    elif args.pid_hold:
        daemon.pid_pause(args.pid_hold[0])

    elif args.pid_resume:
        daemon.pid_pause(args.pid_resume[0])

    elif args.pid_get_setpoint:
        print(daemon.pid_get(args.pid_get_setpoint[0], 'setpoint'))
    elif args.pid_get_error:
        print(daemon.pid_get(args.pid_get_error[0], 'error'))
    elif args.pid_get_integrator:
        print(daemon.pid_get(args.pid_get_integrator[0], 'integrator'))
    elif args.pid_get_derivator:
        print(daemon.pid_get(args.pid_get_derivator[0], 'derivator'))
    elif args.pid_get_kp:
        print(daemon.pid_get(args.pid_get_kp[0], 'kp'))
    elif args.pid_get_ki:
        print(daemon.pid_get(args.pid_get_ki[0], 'ki'))
    elif args.pid_get_kd:
        print(daemon.pid_get(args.pid_get_kd[0], 'kd'))

    elif args.pid_set_setpoint:
        print(daemon.pid_set(args.pid_set_setpoint[0], 'setpoint', args.pid_set_setpoint[1]))
    elif args.pid_set_integrator:
        print(daemon.pid_set(args.pid_set_integrator[0], 'integrator', args.pid_set_integrator[1]))
    elif args.pid_set_derivator:
        print(daemon.pid_set(args.pid_set_derivator[0], 'derivator', args.pid_set_derivator[1]))
    elif args.pid_set_kp:
        print(daemon.pid_set(args.pid_set_kp[0], 'kp', args.pid_set_kp[1]))
    elif args.pid_set_ki:
        print(daemon.pid_set(args.pid_set_ki[0], 'ki', args.pid_set_ki[1]))
    elif args.pid_set_kd:
        print(daemon.pid_set(args.pid_set_kd[0], 'kd', args.pid_set_kd[1]))

    elif args.trigger_action:
        print(daemon.trigger_action(args.trigger_action))
    elif args.trigger_all_actions:
        print(daemon.trigger_all_actions(args.trigger_all_actions))

    elif args.gen_widget_html:
        generate_widget_html()

    elif args.terminate:
        logger.info("[Remote command] Terminate daemon...")
        if daemon.terminate_daemon():
            logger.info("Daemon response: Terminated.")
        else:
            logger.info("Unknown daemon response.")

    sys.exit(0)
