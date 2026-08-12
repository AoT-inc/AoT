#!/opt/Mycodo/env/bin/python
# -*- coding: utf-8 -*-
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

import os
import sys
import time

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))

import argparse
import logging
import resource
import signal
import threading
import timeit
import traceback
from logging import handlers

from Pyro5.api import Proxy, expose, serve

from aot.config import (DAEMON_LOG_FILE, DOCKER_CONTAINER, AOT_DB_PATH,
                           AOT_VERSION, STATS_CSV, STATS_INTERVAL,
                           UPGRADE_CHECK_INTERVAL, AI_SUMMARY_INTERVAL)
from aot.controllers.controller_conditional import ConditionalController
from aot.controllers.controller_function import FunctionController
from aot.controllers.controller_input import InputController
from aot.controllers.controller_output import OutputController
from aot.controllers.controller_pid import PIDController
from aot.controllers.controller_trigger import TriggerController
from aot.controllers.controller_trigger_sequence import SequenceTriggerController
from aot.controllers.controller_widget import WidgetController
from aot.databases.models import (PID, Camera, Conditional,
                                     CustomController, Input, Misc, Output,
                                     Trigger)
from aot.databases.utils import session_scope
from aot.devices.camera import camera_record
from aot.aot_flask.app import create_app
from aot.utils.actions import (get_condition_value,
                                  get_condition_value_dict,
                                  parse_action_information, trigger_action,
                                  trigger_controller_actions)
from aot.utils import output_audit
from aot.utils.command_origin import ROLE_DAEMON, set_process_role
from aot.utils.database import db_retrieve_table_daemon
from aot.utils import docker_update
from aot.utils.audit import audit_log
from aot.utils.update_availability import check_upgrade_exists, updater_status
from aot.utils.stats import (add_update_csv, recreate_stat_file,
                                return_stat_file_dict, send_anonymous_stats)
from aot.utils.system_environment import detect as detect_system_environment
from aot.utils.tools import generate_output_usage_report, next_schedule
from aot.ai.services.ai_action_service import AIActionService
from aot.utils.influx import write_influxdb_value


formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')


# Shutdown join budgets. Both were previously unbounded or silently short,
# which is why no graceful shutdown completed between 2026-07-28 and 08-07.
#
# CONTROLLER: a controller whose loop() is blocked on a device read never sees
# running=False. It is a daemon thread, so abandoning it is safe; waiting on it
# forever is not.
CONTROLLER_JOIN_TIMEOUT_S = 15
# Per controller *type*, how long stop_all_controllers() may wait for that type
# to finish before it moves on to the next one (Function -> PID -> Input -> ...).
# Was a flat sleep of the same length, paid in full every shutdown even when
# every thread had already exited.
CONTROLLER_TYPE_SETTLE_TIMEOUT_S = 2.5
# Widget: same reasoning as CONTROLLER_JOIN_TIMEOUT_S. Named rather than the
# bare 15 it used to be, because that number is now reported in the log line
# that fires when the join does cut in.
WIDGET_JOIN_TIMEOUT_S = 15
# OUTPUT: sending every output's Shutdown State is O(N) -- on LoRaWAN each one
# waits for the site-wide 4 s pacing slot (aot/utils/lorawan_pacing.py), about
# 8 s per output. The old silent join(15) therefore cut a 30-output site off
# after roughly the first two, dropping the rest with no log at all. Sized to
# stay under docker-compose's stop_grace_period (180 s) with room for the audit
# flush and Pyro teardown that follow; a site large enough to exceed it now
# says so in the log instead of failing quietly.
OUTPUT_JOIN_TIMEOUT_S = 120


_TZ_CACHE = {'tz': None, 'expires': 0.0}


def _user_tz_converter(secs):
    """Render log asctime in the user-configured timezone (Misc.timezone).
    Uses db_retrieve_table_daemon (no Flask app context required) and a
    60s TTL cache to avoid querying the DB on every log record.
    Falls back to UTC when DB is not yet available (early startup)."""
    try:
        import pytz
        from datetime import datetime as _dt
        now = time.time()
        if _TZ_CACHE['tz'] is None or now > _TZ_CACHE['expires']:
            from aot.utils.database import db_retrieve_table_daemon as _db
            misc = _db(Misc, entry='first')
            tz_name = misc.timezone if misc and getattr(misc, 'timezone', None) else 'UTC'
            _TZ_CACHE['tz'] = pytz.timezone(tz_name)
            _TZ_CACHE['expires'] = now + 60
        return _dt.fromtimestamp(secs, _TZ_CACHE['tz']).timetuple()
    except Exception:
        return time.gmtime(secs)


formatter.converter = _user_tz_converter

# File handler — RotatingFileHandler: 50 MB × 5 파일 = 최대 250 MB 유지.
# 핸들러 레벨은 INFO 기본. daemon_debug_mode=True 시 start() 에서 DEBUG로 전환.
# (핸들러 레벨은 logger 레벨보다 세밀하게 조정 가능하지만, logger 레벨이 상위 필터이므로
#  logger.setLevel(INFO) 만으로도 DEBUG 메시지는 파일에 기록되지 않는다.)
from logging.handlers import RotatingFileHandler as _RotatingFileHandler
logHandler = _RotatingFileHandler(
    DAEMON_LOG_FILE,
    maxBytes=50 * 1024 * 1024,   # 50 MB
    backupCount=5,
    encoding='utf-8',
)
logHandler.setLevel(logging.INFO)
logHandler.setFormatter(formatter)

# Stream handler (for Docker logs)
streamHandler = logging.StreamHandler(sys.stdout)
streamHandler.setLevel(logging.INFO)
streamHandler.setFormatter(formatter)

logger = logging.getLogger('aot')
logger.setLevel(logging.INFO)   # 시작 시 INFO. debug mode 시 start() 에서 DEBUG로 전환.
logger.addHandler(logHandler)
logger.addHandler(streamHandler)
logger.propagate = False


class DaemonController:
    """AoT daemon."""
    def __init__(self):
        self.logger = logger
        time.sleep(5)  # Wait for UI to finish migrations
        self.flask_app = create_app()

        # 이 프로세스가 데몬임을 등록한다. 이게 없으면 데몬 내부의 자동화 명령
        # (PID·bang_bang·env_coordinator 등, 실행 컨텍스트를 안 심는 경로)이
        # 출처 `unknown` 으로 분류돼 감사로그를 채우고 가짜 우회 경보를 낸다.
        set_process_role(ROLE_DAEMON)
        output_audit.start_writer(self.flask_app)

        self.logger.info(f"AoT daemon v{AOT_VERSION} starting")

        # Runtime environment snapshot (platform, cores, memory, capabilities)
        # collected once at startup; exposed to the web UI via Pyro RPC.
        try:
            self.system_environment = detect_system_environment()
            self.logger.info(
                "System environment: platform={platform_type} "
                "cores={cpu_cores} mem={mem_total_gb}GB os={os_release}".format(
                    **self.system_environment))
        except Exception:
            self.logger.exception("Could not detect system environment")
            self.system_environment = {}

        if DOCKER_CONTAINER:
            self.logger.info("Detected running inside a Docker continaer")

        self.startup_timer = timeit.default_timer()
        self.startup_time = None
        self.daemon_run = True
        self.terminated = False

        # Actions
        self.actions = {}

        # Controller object that will store the thread objects for each controller
        self.controller = {
            'Conditional': {},
            'Output': None,  # May only launch a single thread for this controller
            'Widget': None,  # May only launch a single thread for this controller
            'Input': {},
            'PID': {},
            'Trigger': {},
            'Function': {}
        }

        # Controllers that may launch multiple threads
        # Order matters for starting and shutting down
        self.cont_types = [
            'Conditional',
            'Trigger',
            'Input',
            'PID',
            'Function'
        ]

        # Dashboard widgets
        self.dashboard_widget = {}

        self.thread_shutdown_timer = None
        self.start_time = time.time()
        self.timer_stats = time.time() + 120
        self.timer_upgrade = time.time() + 120
        self.timer_upgrade_message = time.time()
        self.timer_ai_summary = time.time() + 60 # Start soon after boot
        self.timer_ai_archive = time.time() + 300 # Initial archiving soon after boot

        # Update Misc settings
        self.output_usage_report_gen = None
        self.output_usage_report_span = None
        self.output_usage_report_day = None
        self.output_usage_report_hour = None
        self.output_usage_report_next_gen = None
        self.opt_out_statistics = None
        self.enable_upgrade_check = None
        # Docker auto-update (see docs/design/docker-auto-update.md). The next
        # run is an absolute epoch time rather than a "is it HH:MM right now?"
        # test: the loop's period drifts, and a minute-equality check silently
        # skips a day whenever it drifts past the minute.
        self.docker_auto_update = None
        self.docker_auto_update_time = None
        self.docker_auto_update_tz = None
        self.docker_update_next_run = None
        self.refresh_daemon_misc_settings()

        state = 'disabled' if self.opt_out_statistics else 'enabled'
        self.logger.debug(f"Anonymous statistics {state}")

        # [Fix] Ensure all tables exist (Legacy/Migration support)
        try:
            from aot.databases.utils import get_engine
            from aot.aot_flask.extensions import db
            # Ensure all models are imported (already at top)
            engine = get_engine(AOT_DB_PATH)
            db.metadata.create_all(bind=engine)
            self.logger.debug("Database tables checked/created.")
        except Exception as e:
            self.logger.error(f"Error ensuring database tables exist: {e}")

    def run(self):
        self.load_actions()

        try:
            self.start_all_controllers()
        except Exception:
            self.logger.exception("Could not start all controllers")

        self.startup_time = timeit.default_timer() - self.startup_timer
        self.logger.info(
            f"AoT daemon started in {self.startup_time:.3f} seconds")

        try:
            self.startup_stats()
        except Exception:
            self.logger.exception("Statistics initialization Error")

        # loop until daemon is instructed to shut down
        while self.daemon_run:
            now = time.time()

            try:
                # Capture time-lapse image (if enabled)
                self.check_all_timelapses(now)

                # Generate output usage report (if enabled)
                if (self.output_usage_report_gen and
                        self.output_usage_report_next_gen and
                        now > self.output_usage_report_next_gen):
                    self.generate_usage_report()
                    # Ensure timer has updated
                    if now > self.output_usage_report_next_gen:
                        while now > self.output_usage_report_next_gen:
                            self.output_usage_report_next_gen += 86400  # 1 day

                # Collect and send anonymous statistics (if enabled)
                if not self.opt_out_statistics and now > self.timer_stats:
                    while now > self.timer_stats:
                        self.timer_stats += STATS_INTERVAL
                    self.send_stats()

                # Check if running the latest version (if enabled)
                if self.enable_upgrade_check and now > self.timer_upgrade:
                    while now > self.timer_upgrade:
                        self.timer_upgrade += UPGRADE_CHECK_INTERVAL
                    self.check_aot_upgrade_exists(now)

                # Docker only: install a published update at the configured
                # hour, if the operator turned that on.
                if (self.docker_update_next_run and
                        now >= self.docker_update_next_run):
                    self.run_docker_auto_update()

                # v26.0: Periodic AI Semantic Snapshot Generation
                if now > self.timer_ai_summary:
                    while now > self.timer_ai_summary:
                        self.timer_ai_summary += AI_SUMMARY_INTERVAL
                    self.check_all_ai_summaries()

                # v26.0: Weekly AI Snapshot Archiving
                if now > self.timer_ai_archive:
                    while now > self.timer_ai_archive:
                        self.timer_ai_archive += 86400 * 7 # 1 week
                    self.archive_all_ai_summaries()

            except Exception:
                self.logger.exception("Daemon Error")
                time.sleep(30)

            time.sleep(1)

        # If the daemon errors or finishes, shut it down
        self.logger.debug("Stopping all running controllers")
        self.stop_all_controllers()

        timer = timeit.default_timer() - self.thread_shutdown_timer
        self.logger.info(f"AoT daemon terminated in {timer:.3f} seconds\n\n")
        self.terminated = True

        # Wait for the client to receive the response before it disconnects
        time.sleep(1)

    @staticmethod
    def get_condition_measurement(condition_id):
        return get_condition_value(condition_id)

    @staticmethod
    def get_condition_measurement_dict(condition_id):
        return get_condition_value_dict(condition_id)

    @staticmethod
    def determine_controller_type(unique_id):
        db_tables = {
            'Conditional': db_retrieve_table_daemon(Conditional, unique_id=unique_id),
            'Input': db_retrieve_table_daemon(Input, unique_id=unique_id),
            'PID': db_retrieve_table_daemon(PID, unique_id=unique_id),
            'Trigger': db_retrieve_table_daemon(Trigger, unique_id=unique_id),
            'Function': db_retrieve_table_daemon(CustomController, unique_id=unique_id)
        }
        for each_type in db_tables:
            if db_tables[each_type]:
                return each_type

    def resolve_controller_type(self, cont_id):
        """
        Determine a controller's type, falling back to the in-memory controller
        registry when the database row no longer exists.

        A controller whose database entry was deleted while its thread is still
        running (an orphaned controller) can no longer be identified via the
        database. Scanning the live controller registry lets the daemon still
        locate and stop it, instead of leaving it running with no way to reach it.

        :return: Controller type, or None if not found in the database nor running
        :rtype: str or None
        """
        cont_type = self.determine_controller_type(cont_id)
        if cont_type:
            return cont_type
        for each_type in self.cont_types:
            if cont_id in self.controller.get(each_type, {}):
                self.logger.warning(
                    f"Controller {cont_id} has no database row but is still "
                    f"running as a {each_type} controller (orphaned). Resolving "
                    "its type from the live controller registry so it can be stopped.")
                return each_type
        return None

    def controller_activate(self, cont_id):
        """
        Activate currently-inactive controller

        :return: 0 for success, 1 for fail, with success or error message
        :rtype: int, str

        :param cont_id: Unique ID for controller
        :type cont_id: str
        """
        cont_type = self.determine_controller_type(cont_id)

        if cont_type is None:
            message = f"Controller with ID {cont_id} not found in database; cannot activate."
            self.logger.error(message)
            return 1, message

        if cont_id in self.controller[cont_type]:
            if self.controller[cont_type][cont_id].is_running():
                message = f"Cannot activate {cont_type} controller with ID {cont_id}: " \
                          "It's already active."
                self.logger.warning(message)
                return 1, message

        controller_manage = {}
        ready = threading.Event()

        if cont_type == 'Conditional':
            controller_manage['type'] = Conditional
            controller_manage['function'] = ConditionalController
        elif cont_type == 'Input':
            controller_manage['type'] = Input
            controller_manage['function'] = InputController
        elif cont_type == 'PID':
            controller_manage['type'] = PID
            controller_manage['function'] = PIDController
        elif cont_type == 'Trigger':
            controller_manage['type'] = Trigger
            # Check for specific Trigger types requiring different controllers
            trig_check = db_retrieve_table_daemon(Trigger, unique_id=cont_id)
            if trig_check and trig_check.trigger_type == 'trigger_sequence':
                controller_manage['function'] = SequenceTriggerController
            else:
                controller_manage['function'] = TriggerController
        elif cont_type == 'Function':
            controller_manage['type'] = CustomController
            controller_manage['function'] = FunctionController
        else:
            message = f"'{cont_type}' not a valid controller type."
            self.logger.error(message)
            return 1, message

        with session_scope(AOT_DB_PATH) as new_session:
            mod_cont = new_session.query(controller_manage['type']).filter(
                controller_manage['type'].unique_id == cont_id).first()
            if not mod_cont:  # Check if the controller actually exists
                message = f"{cont_type} controller with ID {cont_id} not found."
                self.logger.error(message)
                return 1, message
            else:  # set as active in SQL database
                mod_cont.is_activated = True
                new_session.commit()

        self.controller[cont_type][cont_id] = controller_manage['function'](ready, cont_id)
        self.controller[cont_type][cont_id].daemon = True
        self.controller[cont_type][cont_id].start()
        # Bounded wait: if initialize_variables() raises before the thread calls
        # ready.set() (e.g. a broken user Python script), an unbounded wait()
        # here deadlocks start_all_controllers() forever, starving every
        # controller queued after this one (including Input -> no live data).
        if not ready.wait(timeout=30):
            self.logger.error(
                f"{cont_type} controller with ID {cont_id} did not signal ready "
                f"within 30s; continuing without waiting further (its "
                f"initialize_variables() may have failed before calling ready.set()).")

        message = f"{cont_type} controller with ID {cont_id} activated."
        self.logger.debug(message)
        return 0, message

    def controller_deactivate(self, cont_id):
        """
        Deactivate currently-active controller

        :return: 0 for success, 1 for fail, with success or error message
        :rtype: int, str

        :param cont_id: Unique ID for controller
        :type cont_id: str
        """
        cont_type = self.resolve_controller_type(cont_id)
        if cont_type is None:
            message = f"Controller with ID {cont_id} not found (no database row " \
                      "and not currently running)."
            self.logger.error(message)
            return 1, message
        if cont_id in self.controller[cont_type]:
            if self.controller[cont_type][cont_id].is_running():
                try:
                    if cont_type == 'Conditional':
                        controller_table = Conditional
                    elif cont_type == 'Input':
                        controller_table = Input
                    elif cont_type == 'PID':
                        controller_table = PID
                    elif cont_type == 'Trigger':
                        controller_table = Trigger
                    elif cont_type == 'Function':
                        controller_table = CustomController
                    else:
                        message = f"'{cont_type}' not a valid controller type."
                        self.logger.error(message)
                        return 1, message

                    if controller_table:
                        # set as inactive in SQL database
                        with session_scope(AOT_DB_PATH) as new_session:
                            mod_cont = new_session.query(controller_table).filter(
                                controller_table.unique_id == cont_id).first()
                            if not mod_cont:
                                # Row already deleted (orphaned controller). Don't
                                # bail — still stop the running thread below so the
                                # device stops acting.
                                self.logger.warning(
                                    f"{cont_type} controller with ID {cont_id} has no "
                                    "database row; stopping its orphaned thread anyway.")
                            else:  # set as inactive in SQL database
                                mod_cont.is_activated = False
                                new_session.commit()

                    if cont_type == 'PID':
                        self.controller[cont_type][cont_id].stop_controller(deactivate_pid=True)
                    else:
                        self.controller[cont_type][cont_id].stop_controller()
                    self.controller[cont_type][cont_id].join()

                    message = f"{cont_type} controller with ID {cont_id} deactivated."
                    self.logger.debug(message)
                    return 0, message
                except Exception as except_msg:
                    message = f"Could not deactivate {cont_type} controller with " \
                              f"ID {cont_id}: {except_msg}"
                    self.logger.exception(message)
                    return 1, message
                finally:
                    self.controller[cont_type].pop(cont_id, None)

            else:
                message = f"Could not deactivate {cont_type} controller with ID " \
                          f"{cont_id}, it's not active."
                self.logger.error(message)
                return 1, message
        else:
            message = f"{cont_type} controller with ID {cont_id} not found"
            self.logger.error(message)
            return 1, message

    def controller_restart(self, cont_id):
        """
        Restart a currently-active controller

        :return: 0 for success, 1 for fail, with success or error message
        :rtype: int, str

        :param cont_id: Unique ID for controller
        :type cont_id: str
        """
        status_deactivate, msg_deactivate = self.controller_deactivate(cont_id)
        status_activate, msg_activate = self.controller_activate(cont_id)
        if not status_deactivate and not status_activate:
            return 0, f"Successfully restarted controller with ID {cont_id}"
        else:
            return 1, ", ".join([msg_deactivate, msg_activate])

    def controller_is_active(self, cont_id):
        """
        Checks if a controller is active

        :return: True for active, False for inactive
        :rtype: bool

        :param cont_id: Unique ID for controller
        :type cont_id: str
        """
        cont_type = self.resolve_controller_type(cont_id)
        try:
            if cont_type is not None and cont_id in self.controller[cont_type]:
                if self.controller[cont_type][cont_id].is_running():
                    return True
                else:
                    message = f"{cont_type} controller with ID {cont_id} is not active."
                    self.logger.debug(message)
                    return False
            else:
                message = f"{cont_type} controller with ID {cont_id} not found"
                self.logger.debug(message)
                return False
        except Exception as except_msg:
            message = f"Error: {cont_type} controller with ID {cont_id}: {except_msg}"
            self.logger.exception(message)
            return False

    def check_daemon(self):
        try:
            for cond_id in self.controller['Conditional']:
                if not self.controller['Conditional'][cond_id].is_running():
                    return f"Error: Conditional ID {cond_id}"
            for input_id in self.controller['Input']:
                if not self.controller['Input'][input_id].is_running():
                    return f"Error: Input ID {input_id}"
            for pid_id in self.controller['PID']:
                if not self.controller['PID'][pid_id].is_running():
                    return f"Error: PID ID {pid_id}"
            for trigger_id in self.controller['Trigger']:
                if not self.controller['Trigger'][trigger_id].is_running():
                    return f"Error: Trigger ID {trigger_id}"
            for controller_id in self.controller['Function']:
                if not self.controller['Function'][controller_id].is_running():
                    return f"Error: Function ID {controller_id}"
            if self.controller.get('Output') and hasattr(self.controller['Output'], 'is_running'):
                if not self.controller['Output'].is_running():
                    return "Error: Output controller"
            if self.controller.get('Widget') and hasattr(self.controller['Widget'], 'is_running'):
                if not self.controller['Widget'].is_running():
                    return "Error: Widget controller"
        except Exception as except_msg:
            message = f"Could not check running threads: {except_msg}"
            self.logger.exception(message)
            return f"Exception: {except_msg}"

    def module_function(self, controller_type, unique_id, button_id, args_dict, thread=True, return_from_function=False):
        """
        Call a module function

        :return: success or error message
        :rtype: str

        :param controller_type: Which controller to call the function. Options: "Input", "Output", "Function".
        :type controller_type: str
        :param unique_id: Controller unique_id
        :type unique_id: str
        :param button_id: function name
        :type button_id: str
        :param args_dict: dict of arguments to pass to function
        :type args_dict: dict
        :param thread: execute the function as a thread or wait to get a return value
        :type thread: bool
        :param return_from_function: return the object returned from the function, rather than merely a status string
        :type return_from_function: bool
        """
        message = None
        try:
            if controller_type == "Input":
                if unique_id in self.controller["Input"]:
                    return self.controller["Input"][unique_id].call_module_function(
                        button_id, args_dict, thread=thread, return_from_function=return_from_function)
                else:
                    message = f"Attempting to call {button_id}() in inactive Input Controller with ID {unique_id}. Only active Input Controllers can have functions called."
                    self.logger.error(message)
            elif controller_type == "Output":
                return self.controller["Output"].call_module_function(
                    button_id, args_dict, unique_id=unique_id, thread=thread, return_from_function=False)
            elif controller_type in ["Function", "Function_Custom"]:
                if unique_id in self.controller["Function"]:
                    return self.controller["Function"][unique_id].call_module_function(
                        button_id, args_dict, thread=thread, return_from_function=return_from_function)
                else:
                    message = f"Attempting to call {button_id}() in inactive Function Controller with ID {unique_id}. Only active Function Controllers can have functions called."
                    self.logger.error(message)
            else:
                message = f"Unknown controller: {controller_type}"
                self.logger.error(message)
        except:
            message = "Cannot execute custom action. Is the controller activated? " \
                      "If it is and this error is still occurring, check the Daemon Log."
            self.logger.exception(message)
        return 0, message

    def input_force_measurements(self, input_id):
        """
        Force Input measurements to be acquired

        :return: success or error message
        :rtype: str

        :param input_id: Which Input controller ID is to be affected?
        :type input_id: str

        """
        try:
            return self.controller['Input'][input_id].force_measurements()
        except Exception as except_msg:
            message = f"Cannot force acquisition of Input measurements: {except_msg}"
            self.logger.exception(message)
            return 1, message

    def function_status(self, function_id):
        if function_id in self.controller["Function"]:
            try:
                return self.controller["Function"][function_id].function_status()
            except Exception:
                return {'error': [f"Error getting Function status: {traceback.format_exc()}"]}
        elif function_id in self.controller["Conditional"]:
            try:
                return self.controller["Conditional"][function_id].function_status()
            except Exception:
                return {'error': [f"Error getting Function status: {traceback.format_exc()}"]}
        elif function_id in self.controller["PID"]:
            try:
                return self.controller["PID"][function_id].function_status()
            except Exception:
                return {'error': [f"Error getting Function status: {traceback.format_exc()}"]}
        elif function_id in self.controller["Trigger"]:
            try:
                return self.controller["Trigger"][function_id].function_status()
            except Exception:
                return {'error': [f"Error getting Function status: {traceback.format_exc()}"]}
        else:
            return {'error': [f"Function ID not found. Is the Function activated?"]}

    def lcd_reset(self, lcd_id):
        """
        Resets an LCD

        :return: success or error message
        :rtype: str

        :param lcd_id: Which LCD controller ID is to be affected?
        :type lcd_id: str

        """
        try:
            if lcd_id in self.controller['Function']:
                return self.controller['Function'][lcd_id].lcd_init()
        except KeyError:
            message = "Cannot reset LCD, LCD not running"
            self.logger.exception(message)
            return 0, message
        except Exception as except_msg:
            message = f"Could not reset display: {except_msg}"
            self.logger.exception(message)

    def lcd_backlight(self, lcd_id, state):
        """
        Turn on or off the LCD backlight

        :return: success or error message
        :rtype: str

        :param lcd_id: Which LCD controller ID is to be affected?
        :type lcd_id: str
        :param state: Turn flashing on (1) or off (0)
        :type state: bool

        """
        try:
            if lcd_id in self.controller['Function']:
                if state:
                    return self.controller['Function'][lcd_id].function_action("backlight_on")
                else:
                    return self.controller['Function'][lcd_id].function_action("backlight_off")
        except KeyError:
            message = "Cannot change backlight: LCD not running"
            self.logger.exception(message)
            return 0, message
        except Exception as except_msg:
            message = f"Cannot change display backlight: {except_msg}"
            self.logger.exception(message)

    def display_backlight_color(self, lcd_id, color):
        """
        Set the LCD backlight color

        :return: success or error message
        :rtype: str

        :param lcd_id: Which LCD controller ID is to be affected?
        :type lcd_id: str
        :param color: R,G,B tuple
        :type color: tuple

        """
        try:
            if lcd_id in self.controller['Function']:
                return self.controller['Function'][lcd_id].display_backlight_color(color)
        except KeyError:
            message = "Cannot change LCD color: LCD not running"
            self.logger.exception(message)
            return 0, message
        except Exception as except_msg:
            message = f"Cannot change display color: {except_msg}"
            self.logger.exception(message)

    def lcd_flash(self, lcd_id, state):
        """
        Begin or end a repeated flashing of an LCD

        :return: success or error message
        :rtype: str

        :param lcd_id: Which LCD controller ID is to be affected?
        :type lcd_id: str
        :param state: Turn flashing on (1/True) or off (0/False)
        :type state: bool

        """
        try:
            if lcd_id in self.controller['Function']:
                return self.controller['Function'][lcd_id].lcd_flash(state)
        except KeyError:
            message = "Cannot flash display: Display not running"
            self.logger.error(message)
            return 0, message
        except Exception as except_msg:
            message = f"Cannot flash display ({state}): {except_msg}"
            self.logger.exception(message)
            return 0, message

    def pid_hold(self, pid_id):
        try:
            return self.controller['PID'][pid_id].pid_hold()
        except KeyError:
            message = "PID not running"
            self.logger.error(message)
            return message
        except Exception as except_msg:
            message = f"Could not hold PID: {except_msg}"
            self.logger.exception(message)

    def pid_mod(self, pid_id):
        try:
            return self.controller['PID'][pid_id].pid_mod()
        except KeyError:
            message = "PID not running"
            self.logger.error(message)
            return message
        except Exception as except_msg:
            message = f"Could not modify PID: {except_msg}"
            self.logger.exception(message)

    def pid_pause(self, pid_id):
        try:
            return self.controller['PID'][pid_id].pid_pause()
        except KeyError:
            message = "PID not running"
            self.logger.error(message)
            return message
        except Exception as except_msg:
            message = f"Could not pause PID: {except_msg}"
            self.logger.exception(message)

    def pid_resume(self, pid_id):
        try:
            return self.controller['PID'][pid_id].pid_resume()
        except KeyError:
            message = "PID not running"
            self.logger.error(message)
            return message
        except Exception as except_msg:
            message = f"Could not resume PID: {except_msg}"
            self.logger.exception(message)

    def pid_get(self, pid_id, setting):
        try:
            if pid_id not in self.controller['PID']:
                return None
            elif setting == 'setpoint':
                return self.controller['PID'][pid_id].get_setpoint()
            elif setting == 'setpoint_band':
                return self.controller['PID'][pid_id].get_setpoint_band()
            elif setting == 'error':
                return self.controller['PID'][pid_id].get_error()
            elif setting == 'integrator':
                return self.controller['PID'][pid_id].get_integrator()
            elif setting == 'derivator':
                return self.controller['PID'][pid_id].get_derivator()
            elif setting == 'kp':
                return self.controller['PID'][pid_id].get_kp()
            elif setting == 'ki':
                return self.controller['PID'][pid_id].get_ki()
            elif setting == 'kd':
                return self.controller['PID'][pid_id].get_kd()
        except Exception as except_msg:
            message = f"Could not get PID {setting}: {except_msg}"
            self.logger.exception(message)

    def pid_set(self, pid_id, setting, value):
        try:
            if setting == 'setpoint':
                return self.controller['PID'][pid_id].set_setpoint(value)
            elif setting == 'method':
                return self.controller['PID'][pid_id].set_method(value)
            elif setting == 'integrator':
                return self.controller['PID'][pid_id].set_integrator(value)
            elif setting == 'derivator':
                return self.controller['PID'][pid_id].set_derivator(value)
            elif setting == 'kp':
                return self.controller['PID'][pid_id].set_kp(value)
            elif setting == 'ki':
                return self.controller['PID'][pid_id].set_ki(value)
            elif setting == 'kd':
                return self.controller['PID'][pid_id].set_kd(value)
        except Exception as except_msg:
            message = f"Could not set PID {setting}: {except_msg}"
            self.logger.exception(message)

    def refresh_daemon_conditional_settings(self, unique_id):
        try:
            return self.controller['Conditional'][unique_id].refresh_settings()
        except Exception as except_msg:
            message = f"Could not refresh conditional settings: {except_msg}"
            self.logger.exception(message)

    def refresh_daemon_misc_settings(self):
        try:
            self.logger.debug("Refreshing misc settings")
            misc = db_retrieve_table_daemon(Misc, entry='first')
            self.opt_out_statistics = misc.stats_opt_out
            self.enable_upgrade_check = misc.enable_upgrade_check
            self.output_usage_report_gen = misc.output_usage_report_gen
            self.output_usage_report_span = misc.output_usage_report_span
            self.output_usage_report_day = misc.output_usage_report_day
            self.output_usage_report_hour = misc.output_usage_report_hour
            self.refresh_docker_auto_update(misc)
        except Exception:
            self.logger.exception("Could not refresh misc settings")

    def refresh_docker_auto_update(self, misc):
        """Re-arm the Docker auto-update schedule from the saved settings.

        Called on every misc refresh, which is what makes a schedule change in
        the web UI take effect without restarting the daemon.
        """
        if not DOCKER_CONTAINER:
            return

        self.docker_auto_update = bool(getattr(misc, 'docker_auto_update', False))
        self.docker_auto_update_time = (
            getattr(misc, 'docker_auto_update_time', None)
            or docker_update.DEFAULT_SCHEDULE)
        # Take the timezone from the row we already hold rather than letting
        # time_utils.get_timezone_name() look it up: that helper needs a Flask
        # app context and falls back to UTC without one. The fallback is silent,
        # and silently scheduling 03:00 UTC for someone who typed 03:00 KST
        # runs the update at noon.
        self.docker_auto_update_tz = getattr(misc, 'timezone', None) or None

        if not self.docker_auto_update:
            self.docker_update_next_run = None
            return

        self.docker_update_next_run = docker_update.next_scheduled_run(
            self.docker_auto_update_time, tz_name=self.docker_auto_update_tz)
        if self.docker_update_next_run is None:
            # An unreadable time must not mean "run now" -- leaving the schedule
            # unset is the safe reading, and saying so is how anyone finds out.
            self.logger.error(
                f"Docker auto-update is enabled but the configured time "
                f"'{self.docker_auto_update_time}' is not a valid HH:MM. "
                f"No automatic update will run until it is corrected.")
            return

        self.logger.info(
            f"Docker auto-update enabled: next check at "
            f"{docker_update.format_local(self.docker_update_next_run, self.docker_auto_update_tz)} "
            f"(local, {self.docker_auto_update_time} daily)")

    def refresh_daemon_trigger_settings(self, unique_id):
        try:
            if unique_id in self.controller['Trigger']:
                return self.controller['Trigger'][unique_id].refresh_settings()
            else:
                return "Trigger not active, settings updated in DB only"
        except Exception:
            self.logger.exception("Could not refresh trigger settings")

    def output_off(self, output_id, output_channel=None, trigger_conditionals=True,
                   origin=None):
        """
        Turn output off using default output controller

        :param output_id: Unique ID for output
        :type output_id: str
        :param output_channel: channel of output
        :type output_channel: int
        :param trigger_conditionals: Whether to trigger output conditionals or not
        :type trigger_conditionals: bool
        :param origin: 명령 출처 dict (aot/utils/command_origin.py). 호출자
            스레드에서 이미 확정돼 넘어온 값이라 스레드 경계와 무관하다.
        :type origin: dict
        """
        try:
            return self.controller['Output'].output_on_off(
                output_id,
                'off',
                output_channel=output_channel,
                trigger_conditionals=trigger_conditionals,
                origin=origin)
        except Exception as except_msg:
            message = f"Could not turn output off: {except_msg}"
            self.logger.exception(message)
            return 1, message

    def output_on(self,
                  output_id,
                  output_channel=None,
                  output_type=None,
                  amount=0.0,
                  min_off=0.0,
                  trigger_conditionals=True,
                  additional_options=None,
                  origin=None):
        """
        Turn output on using default output controller

        :param output_id: Unique ID for output
        :type output_id: str
        :param output_channel: channel of output
        :type output_channel: int
        :param output_type: The type of output ('sec', 'vol', 'pwm')
        :type output_type: str
        :param amount: How long to turn the output on or how much volume to dispense
        :type amount: float
        :param min_off: Don't turn on if not off for at least this duration (0 = disabled)
        :type min_off: float
        :param trigger_conditionals: bool
        :type trigger_conditionals: Indicate whether to trigger conditional
        """
        try:
            if self.controller['Output'] is None:
                self.logger.error("Could not find Output Controller")
                return "Error"
            else:
                return self.controller['Output'].output_on_off(
                    output_id,
                    'on',
                    output_channel=output_channel,
                    output_type=output_type,
                    amount=amount,
                    min_off=min_off,
                    trigger_conditionals=trigger_conditionals,
                    additional_options=additional_options,
                    origin=origin)
        except Exception as except_msg:
            message = f"Could not turn output on: {except_msg}"
            self.logger.exception(message)
            return 1, message

    def output_setup(self, action, output_id):
        """
        Setup output in running output controller

        :return: 0 for success, 1 for fail, with success for fail message
        :rtype: int, str

        :param action: What action to perform on a specific output ID
        :type action: str
        :param output_id: Unique ID for output
        :type output_id: str
        """
        try:
            return self.controller['Output'].output_setup(action, output_id)
        except Exception as except_msg:
            message = f"Could not set up output: {except_msg}"
            self.logger.exception(message)

    def output_state(self, output_id, output_channel):
        """
        Return the output state, whether "on" or "off"

        :param output_id: Unique ID for output
        :type output_id: str
        :param output_channel: channel of output
        :type output_channel: int
        """
        try:
            return self.controller['Output'].output_state(output_id, output_channel)
        except Exception:
            self.logger.exception("Could not query output state")

    def output_states_all(self):
        """
        Return all output states, whether "on" or "off"
        """
        try:
            return self.controller['Output'].output_states_all()
        except Exception:
            self.logger.exception(f"Could not query all output state")

    def output_comm_capable_all(self):
        """
        Return {output_id: bool} — whether each Output can actually observe its
        device's state at all (an ACK/readback/heartbeat path exists), as opposed
        to being a fire-and-forget control signal.

        Kept separate from output_states_all() on purpose: that dict's
        {output_id: {channel: state}} shape is consumed by several widgets and
        the shared classifier, and must not change. Capability is also a static
        per-output property (it follows the driver + its configured status
        topic), so callers fetch it once rather than on every state poll.
        """
        result = {}
        try:
            ctrl = self.controller.get('Output')
            if not ctrl:
                return result
            for output_id, out in ctrl.output.items():
                try:
                    result[output_id] = bool(out.comm_capable())
                except Exception:
                    # A driver that cannot answer is treated as "cannot confirm",
                    # which is the same conservative default as the base class.
                    result[output_id] = False
        except Exception:
            self.logger.exception("Could not query output comm capability")
        return result

    def input_status_all(self):
        """
        Return communication status (comm_capable/comm_is_fault/comm_last_success)
        for every active Input controller. Counterpart to output_states_all() —
        see io_link_health_infra_plan.md Phase D. Inactive Inputs are absent
        from self.controller['Input'] entirely (aot_daemon.py gates activation
        on Input.is_activated), so they are simply not present in the result;
        the Flask route (/inputstate) fills in active=False for those.
        """
        result = {}
        try:
            for input_id, ctrl in self.controller['Input'].items():
                try:
                    result[input_id] = {
                        'comm_capable': ctrl.comm_capable(),
                        'comm_is_fault': ctrl.comm_is_fault(),
                        'comm_last_success': ctrl.comm_last_success(),
                    }
                except Exception:
                    self.logger.exception(f"Could not query comm status for Input {input_id}")
        except Exception:
            self.logger.exception("Could not query all input comm status")
        return result

    def output_target_pct(self, output_id, output_channel=0):
        """Return (last_target_pct, last_target_source) for an actuator_paired output.

        last_target_pct: 마지막으로 지정된 목표값 (사용자/시스템 무관)
        last_target_source: 'manual' | 'system' | None
        """
        try:
            ctrl = self.controller.get('Output')
            if ctrl and output_id in ctrl.output:
                fn = getattr(ctrl.output[output_id], 'output_target_pct', None)
                if fn:
                    result = fn(output_channel)
                    if isinstance(result, tuple) and len(result) == 2:
                        val, src = result
                        return (float(val) if val is not None else None, src)
        except Exception:
            self.logger.exception(f"Could not query output_target_pct for {output_id}")
        return None, None

    def startup_stats(self):
        """Ensure existence of statistics file and save daemon startup time."""
        # if statistics file doesn't exist, create it
        if not os.path.isfile(STATS_CSV):
            self.logger.debug(f"Statistics file doesn't exist, creating {STATS_CSV}")
            recreate_stat_file()
        add_update_csv(STATS_CSV, 'daemon_startup_seconds', self.startup_time)

    def load_actions(self):
        self.actions = parse_action_information()

    def start_all_controllers(self):
        """
        Start all activated controllers

        See the files named controller_[name].py for details of what each
        controller does.
        """
        # Obtain database configuration options
        db_tables = {
            'Conditional': db_retrieve_table_daemon(Conditional, entry='all'),
            'Input': db_retrieve_table_daemon(Input, entry='all'),
            'PID': db_retrieve_table_daemon(PID, entry='all'),
            'Trigger': db_retrieve_table_daemon(Trigger, entry='all'),
            'Function': db_retrieve_table_daemon(CustomController, entry='all')
        }

        self.logger.debug("Starting Output Controller")
        ready = threading.Event()
        self.controller['Output'] = OutputController(ready, debug)
        self.controller['Output'].daemon = True
        self.controller['Output'].start()
        if not ready.wait(timeout=30):
            self.logger.error(
                "Output Controller did not signal ready within 30s; continuing "
                "without waiting further.")

        # Ensure Output controller has started before continuing
        time.sleep(0.5)
        output_controller_timout = time.time() + 60
        while not self.controller['Output'].is_running():
            if time.time() > output_controller_timout:
                self.logger.error("Output Controller timed out")
                break
            time.sleep(0.1)
        self.logger.debug("Output Controller fully started")

        for each_controller in self.cont_types:
            self.logger.debug(f"Starting all activated {each_controller} controllers")
            for each_entry in db_tables[each_controller]:
                # A SIGTERM during boot used to be ignored outright: _graceful_stop
                # only lowers this flag, and nothing on the startup path read it,
                # so `docker stop` did nothing until SIGKILL. Boot is exactly when
                # a stop is most likely -- it is the slowest part of the run.
                if not self.daemon_run:
                    self.logger.info(
                        "Shutdown requested during startup — stopping before "
                        f"the remaining {each_controller} controllers")
                    return 0, "Startup aborted by shutdown request"
                if each_entry.is_activated:
                    try:
                        self.controller_activate(each_entry.unique_id)
                    except Exception as except_msg:
                        message = f"Could not activate controller with ID {each_entry.unique_id}: {except_msg}"
                        self.logger.exception(message)
                        return 1, message
            self.logger.info(f"All activated {each_controller} controllers started")

        self.logger.debug("Starting Widget Controller")
        ready = threading.Event()
        self.controller['Widget'] = WidgetController(ready, debug)
        self.controller['Widget'].daemon = True
        self.controller['Widget'].start()
        if not ready.wait(timeout=30):
            self.logger.error(
                "Widget Controller did not signal ready within 30s; continuing "
                "without waiting further.")

        # Ensure Widget controller has started before continuing
        time.sleep(0.5)
        widget_controller_timout = time.time() + 60
        while not self.controller['Widget'].is_running():
            if time.time() > widget_controller_timout:
                self.logger.error("Widget Controller timed out")
                break
            time.sleep(0.1)
        self.logger.debug("Widget Controller fully started")

        time.sleep(0.5)

    def stop_all_controllers(self):
        """Stop all running controllers."""
        controller_running = {}

        # Reverse the list to shut down each controller in the
        # reverse order they were started in
        for each_controller in list(reversed(self.cont_types)):
            controller_running[each_controller] = []
            for cont_id in self.controller[each_controller]:
                try:
                    if self.controller[each_controller][cont_id].is_running():
                        self.controller[each_controller][cont_id].stop_controller()
                        controller_running[each_controller].append(cont_id)
                except Exception as err:
                    self.logger.info(f"{each_controller} controller {cont_id} thread had an issue stopping: {err}")
            # Let this type finish before stopping the next one (Function stops
            # ahead of PID, PID ahead of Input, ...). This used to be an
            # unconditional time.sleep(2.5): 12.5 s of every shutdown was spent
            # waiting on controllers that had already exited. Same upper bound,
            # but it returns as soon as they are actually gone.
            self.await_controllers_stopped(
                each_controller, controller_running[each_controller])

        for each_controller in list(reversed(self.cont_types)):
            for cont_id in controller_running[each_controller]:
                try:
                    # Bounded: a controller whose loop() is stuck in a blocking
                    # device read never sees running=False, and an unbounded
                    # join() here hangs shutdown forever behind it.
                    self.controller[each_controller][cont_id].join(
                        CONTROLLER_JOIN_TIMEOUT_S)
                    if self.controller[each_controller][cont_id].is_alive():
                        self.logger.error(
                            f"{each_controller} controller {cont_id} did not stop "
                            f"within {CONTROLLER_JOIN_TIMEOUT_S}s; abandoning it "
                            f"(it is a daemon thread and will not block exit)")
                except Exception as err:
                    self.logger.info(f"{each_controller} controller {cont_id} thread had an issue being joined: {err}")
            self.logger.info(f"All {each_controller} controllers stopped")

        try:
            self.controller['Output'].stop_controller()
            self.controller['Output'].join(OUTPUT_JOIN_TIMEOUT_S)
            if self.controller['Output'].is_alive():
                # Loud on purpose: this join cutting in is how Shutdown States
                # get dropped. Sending them is O(N) on the LoRaWAN pacing slot,
                # so a large site needs far more than the old silent 15 s.
                self.logger.error(
                    f"Output controller did not stop within "
                    f"{OUTPUT_JOIN_TIMEOUT_S}s; some Shutdown States were not "
                    f"sent")
            else:
                self.logger.info("Output controller stopped")
        except Exception as err:
            self.logger.info(f"Output controller had an issue stopping: {err}")

        # Output 정지가 각 장치에 Shutdown State 를 내보낸 직후다. 그 기록이 큐에
        # 남은 채로 프로세스가 죽으면 "종료가 장치를 껐다"는 사실이 사라지므로
        # 여기서 동기로 마저 쓴다.
        try:
            output_audit.stop_writer()
        except Exception as err:
            self.logger.info(f"감사 writer 종료 중 문제: {err}")

        try:
            self.controller['Widget'].stop_controller()
            self.controller['Widget'].join(WIDGET_JOIN_TIMEOUT_S)
            if self.controller['Widget'].is_alive():
                # This line used to be unconditional, so a Widget controller
                # that never stopped still logged "stopped" -- the 14.4 s the
                # join actually burned looked like ordinary shutdown work.
                self.logger.error(
                    f"Widget controller did not stop within "
                    f"{WIDGET_JOIN_TIMEOUT_S}s; abandoning it (daemon thread)")
            else:
                self.logger.info("Widget controller stopped")
        except Exception as err:
            self.logger.info(f"Widget controller had an issue stopping: {err}")

    def await_controllers_stopped(self, cont_type, cont_ids):
        """Wait (bounded) until this controller type's threads have exited.

        Replaces a flat sleep between types. Returns as soon as every listed
        controller is done, so a healthy site pays milliseconds instead of the
        full budget, while a stuck controller still caps the wait.
        """
        deadline = time.time() + CONTROLLER_TYPE_SETTLE_TIMEOUT_S
        while time.time() < deadline:
            try:
                if not any(self.controller[cont_type][cont_id].is_alive()
                           for cont_id in cont_ids):
                    return
            except Exception:
                return  # Controller went away mid-shutdown; nothing to wait for.
            time.sleep(0.05)

    def trigger_action(self, action_id, value={}, debug=False):
        try:
            return trigger_action(
                self.actions,
                action_id,
                value=value,
                debug=debug)
        except Exception as err:
            message = f"Could not trigger Conditional Actions: {err}"
            self.logger.exception(message)

    def trigger_all_actions(self, function_id, message='', debug=False):
        try:
            return trigger_controller_actions(
                self.actions, function_id, message=message, debug=debug)
        except Exception as err:
            message = f"Could not trigger Conditional Actions: {err}"
            self.logger.exception(message)
            return message

    def terminate_daemon(self):
        """Instruct the daemon to shut down."""
        self.thread_shutdown_timer = timeit.default_timer()
        self.logger.info("Received command to terminate daemon")
        self.daemon_run = False
        while not self.terminated:
            time.sleep(0.1)
        return 1

    #
    # Timed functions
    #

    def check_aot_upgrade_exists(self, now):
        """Check whether a newer AoT release is available.

        The source depends on how this install upgrades: git tags bare-metal,
        the container registry in Docker (a git tag exists before the image is
        pullable, so asking git tags in Docker announces upgrades that cannot
        yet be installed). See aot/utils/update_availability.py.
        """
        try:
            (upgrade_exists, _, _, _, errors) = check_upgrade_exists()

            if errors:
                for each_error in errors:
                    self.logger.debug(each_error)

            if upgrade_exists:
                upgrade_available = True
                if now > self.timer_upgrade_message:
                    # Only display message in log every 10 days
                    self.timer_upgrade_message += 864000
                    self.logger.info(
                        "A new version of AoT is available. Upgrade "
                        "through the web interface under Config -> Upgrade. "
                        "This message will repeat every 10 days unless "
                        "AoT is upgraded or upgrade checks are disabled.")
            else:
                upgrade_available = False

            with session_scope(AOT_DB_PATH) as new_session:
                mod_misc = new_session.query(Misc).first()
                if mod_misc.aot_upgrade_available != upgrade_available:
                    mod_misc.aot_upgrade_available = upgrade_available
                    new_session.commit()
        except Exception:
            self.logger.exception("AoT Upgrade Check ERROR")

    def run_docker_auto_update(self):
        """The configured hour has arrived: ask the updater to install the
        latest published release, if there is one.

        The daemon decides *whether* and *when*; the updater sidecar does the
        privileged work (docs/design/docker-auto-update.md). Keeping the
        judgement here and the privilege there is deliberate -- the component
        holding the Docker socket stays as simple as it can be.
        """
        # Re-arm first. Every path below can fail, and a schedule that only
        # advances on success would retry on every loop pass for a whole day.
        self.docker_update_next_run = docker_update.next_scheduled_run(
            self.docker_auto_update_time, tz_name=self.docker_auto_update_tz)

        try:
            if docker_update.update_in_progress():
                self.logger.info(
                    "Docker auto-update: an update is already in progress, "
                    "skipping this window")
                return

            if not updater_status()['present']:
                self.logger.warning(
                    "Docker auto-update is enabled but no updater service is "
                    "running, so nothing can install the update. Enable the "
                    "updater overlay or the host timer "
                    "(docs/design/docker-auto-update.md).")
                return

            (upgrade_exists, _releases, _tags,
             latest_release, errors) = check_upgrade_exists()

            for each_error in errors:
                self.logger.debug(f"Docker auto-update: {each_error}")

            if not upgrade_exists or not latest_release:
                # Once a day, at INFO: this line is the only evidence an
                # operator has that the automation is alive and did its check.
                # Silence here is indistinguishable from a schedule that never
                # fires, which is the failure mode worth being loud about.
                self.logger.info(
                    f"Docker auto-update: already on the latest published "
                    f"release ({AOT_VERSION}); next check "
                    f"{docker_update.format_local(self.docker_update_next_run, self.docker_auto_update_tz)}")
                return

            ok, result = docker_update.request_update(
                latest_release, requested_by='auto-update')
            if ok:
                self.logger.info(
                    f"Docker auto-update: requested {AOT_VERSION} -> "
                    f"{latest_release} (request {result})")
            else:
                self.logger.error(f"Docker auto-update: {result}")

            # Same trail a button press leaves. An unattended action that
            # restarts control is exactly the kind that has to be findable
            # afterwards, and the daemon has an app context for this.
            try:
                with self.flask_app.app_context():
                    audit_log(
                        'system.upgrade_request',
                        target_type='docker_image',
                        target_name=latest_release,
                        result='success' if ok else 'failure',
                        detail=None if ok else str(result),
                        before={'version': AOT_VERSION},
                        after={'version': latest_release},
                        username='auto-update')
            except Exception:
                self.logger.exception("Docker auto-update: audit log failed")
        except Exception:
            self.logger.exception("Docker auto-update ERROR")

    def check_all_timelapses(self, now):
        with session_scope(AOT_DB_PATH) as new_session:
            for each_camera in new_session.query(Camera).all():
                try:
                    if (each_camera.timelapse_started and
                            now > each_camera.timelapse_end_time):
                        each_camera.timelapse_started = False
                        each_camera.timelapse_paused = False
                        each_camera.timelapse_start_time = None
                        each_camera.timelapse_end_time = None
                        each_camera.timelapse_interval = None
                        each_camera.timelapse_next_capture = None
                        each_camera.timelapse_capture_number = None
                        new_session.commit()
                        self.logger.debug(f"Camera {each_camera.id}: End of time-lapse.")
                    elif ((each_camera.timelapse_started and not each_camera.timelapse_paused) and
                            now > each_camera.timelapse_next_capture):
                        # Ensure next capture is greater than now (in case of power failure/reboot)
                        capture_now = each_camera.timelapse_next_capture
                        while now > each_camera.timelapse_next_capture:
                            # Update last capture and image number to latest before capture
                            each_camera.timelapse_next_capture += each_camera.timelapse_interval
                        new_session.commit()
                        if abs(now - capture_now) < 60:
                            # Only capture if close to timelapse capture time
                            # This prevents an unscheduled timelapse capture upon resume.
                            each_camera.timelapse_capture_number += 1
                            new_session.commit()
                            self.logger.debug(f"Camera {each_camera.id}: Capturing time-lapse image")
                            capture_image = threading.Thread(
                                target=camera_record,
                                args=('timelapse', each_camera.unique_id,))
                            capture_image.start()
                        else:
                            self.logger.error(f"Camera {each_camera.id}: "
                                              f"Timelapse too far from scheduled time, not capturing.")
                except Exception:
                    self.logger.exception("Could not execute timelapse")

    def _is_ai_enabled(self):
        """[v26.0] Helper to check if AI features are enabled in global settings."""
        try:
            with self.flask_app.app_context():
                from aot.databases.models import AIGlobalSettings
                ai_settings = AIGlobalSettings.query.first()
                return ai_settings and ai_settings.ai_enabled
        except Exception:
            self.logger.exception("Error checking AI enabled status")
            return False

    def _is_ai_background_active(self):
        """Whether model-calling background AI work may run right now.

        Enabled (Settings > General) AND started (AI page) AND at least one
        activated agent. See aot/ai/services/ai_runtime_state.py — that module
        is the single place this is decided.
        """
        try:
            with self.flask_app.app_context():
                from aot.ai.services import ai_runtime_state
                return ai_runtime_state.ai_background_active()
        except Exception:
            self.logger.exception("Error checking AI background state")
            return False

    def check_all_ai_summaries(self):
        """
        v26.0: Trigger periodic AI Semantic Snapshot generation.
        """
        if not self._is_ai_background_active():
            self.logger.debug("AI background operation inactive. Skipping periodic summary generation.")
            return

        try:
            with self.flask_app.app_context():
                from aot.ai.services.ai_summary_service import AISummaryService
                self.logger.info("Triggering periodic AI System Summary generation...")
                
                # 1. System-wide summary
                AISummaryService.generate_system_summary(scope_type='system', scope_id=None)
                
                # 2. Site (Farm) level summaries
                from aot.databases.models import GeoMap
                # Use direct models inside app context
                farms = GeoMap.query.all()
                for farm in farms:
                     self.logger.debug(f"Triggering AI Summary for Farm: {farm.name}")
                     AISummaryService.generate_system_summary(scope_type='farm', scope_id=farm.unique_id)
        except Exception as e:
            self.logger.error(f"Error during periodic AI summary: {e}", exc_info=True)

    def archive_all_ai_summaries(self):
        """
        v26.0: Archive snapshots older than 30 days.
        """
        if not self._is_ai_enabled():
            return

        try:
            with self.flask_app.app_context():
                from aot.ai.services.ai_summary_service import AISummaryService
                self.logger.info("Running weekly AI summary archiving job...")
                cnt = AISummaryService.archive_old_summaries(days=30)
                if cnt > 0:
                    self.logger.info(f"Successfully archived {cnt} old AI summaries.")
        except Exception as e:
            self.logger.error(f"Error during AI summary archiving: {e}", exc_info=True)

    def generate_usage_report(self):
        """Generate an Output usage report."""
        try:
            generate_output_usage_report()
            self.refresh_daemon_misc_settings()

            # Update timer
            old_time = self.output_usage_report_next_gen
            self.output_usage_report_next_gen = next_schedule(
                self.output_usage_report_span,
                self.output_usage_report_day,
                self.output_usage_report_hour)
            if (self.output_usage_report_gen and
                    old_time != self.output_usage_report_next_gen):
                str_next_report = time.strftime(
                    '%c', time.localtime(self.output_usage_report_next_gen))
                self.logger.debug(f"Generating next output usage report {str_next_report}")
        except:
            self.logger.exception("Calculating next report time")

    def send_stats(self):
        """Collect and send statistics."""
        # Check if stats file exists, recreate if not
        try:
            return_stat_file_dict(STATS_CSV)
        except Exception:
            self.logger.exception("Reading stats file")
            try:
                os.remove(STATS_CSV)
            except OSError:
                pass
            try:
                recreate_stat_file()
            except:
                self.logger.exception("Recreating stats file")

        # Send stats
        try:
            send_anonymous_stats(self.start_time)
        except Exception:
            self.logger.exception("Sending statistics")


@expose
class PyroServer(object):
    """
    Pyro for communicating between the client and the daemon
    """
    def __init__(self, aot):
        self.aot = aot
        self.logger = logging.getLogger('aot.pyro_server')

    def lcd_reset(self, lcd_id):
        """Resets an LCD."""
        return self.aot.lcd_reset(lcd_id)

    def lcd_backlight(self, lcd_id, state):
        """Turns an LCD backlight on or off."""
        return self.aot.lcd_backlight(lcd_id, state)

    def display_backlight_color(self, lcd_id, color):
        """Set the LCD backlight color."""
        return self.aot.display_backlight_color(lcd_id, color)

    def lcd_flash(self, lcd_id, state):
        """Starts or stops an LCD from flashing (alarm)"""
        return self.aot.lcd_flash(lcd_id, state)

    def get_condition_measurement(self, condition_id):
        return self.aot.get_condition_measurement(condition_id)

    def system_environment(self):
        """Runtime environment snapshot collected at daemon startup."""
        return self.aot.system_environment

    def get_condition_measurement_dict(self, condition_id):
        return self.aot.get_condition_measurement_dict(condition_id)

    def module_function(self, controller_type, unique_id, button_id, args_dict, thread=True, return_from_function=False):
        """execute custom button function."""
        return self.aot.module_function(
            controller_type, unique_id, button_id, args_dict, thread=thread, return_from_function=return_from_function)

    def controller_activate(self, cont_id):
        """Activates a controller."""
        try:
            return self.aot.controller_activate(cont_id)
        except Exception as except_msg:
            message = f"Could not activate controller with ID {cont_id}: {except_msg}"
            self.logger.exception(message)
            return 1, message

    def controller_deactivate(self, cont_id):
        """Deactivates a controller."""
        try:
            return self.aot.controller_deactivate(cont_id)
        except Exception as except_msg:
            message = f"Could not deactivate controller with ID {cont_id}: {except_msg}"
            self.logger.exception(message)
            return 1, message

    def controller_restart(self, cont_id):
        """Restart a controller."""
        try:
            return self.aot.controller_restart(cont_id)
        except Exception as except_msg:
            message = f"Could not restart controller with ID {cont_id}: {except_msg}"
            self.logger.exception(message)
            return 1, message

    def controller_is_active(self, cont_id):
        """Checks if a controller is active."""
        return self.aot.controller_is_active(cont_id)

    def check_daemon(self):
        """Check if all active controllers respond."""
        return self.aot.check_daemon()

    def function_status(self, function_id):
        """Get status of Function."""
        return self.aot.function_status(function_id)

    def input_force_measurements(self, input_id):
        """Updates all input information."""
        return self.aot.input_force_measurements(input_id)

    def pid_hold(self, pid_id):
        """Hold PID Controller operation."""
        return self.aot.pid_hold(pid_id)

    def pid_mod(self, pid_id):
        """Set new PID Controller settings."""
        return self.aot.pid_mod(pid_id)

    def pid_pause(self, pid_id):
        """Pause PID Controller operation."""
        return self.aot.pid_pause(pid_id)

    def pid_resume(self, pid_id):
        """Resume PID controller operation."""
        return self.aot.pid_resume(pid_id)

    def pid_get(self, pid_id, setting):
        """Get PID setting."""
        return self.aot.pid_get(pid_id, setting)

    def pid_set(self, pid_id, setting, value):
        """Set PID setting."""
        return self.aot.pid_set(pid_id, setting, value)

    def refresh_daemon_conditional_settings(self, unique_id):
        """Instruct the daemon to refresh a conditional's settings."""
        return self.aot.refresh_daemon_conditional_settings(unique_id)

    def refresh_daemon_misc_settings(self):
        """Instruct the daemon to refresh the misc settings."""
        return self.aot.refresh_daemon_misc_settings()

    def refresh_daemon_trigger_settings(self, unique_id):
        """Instruct the daemon to refresh a conditional's settings."""
        return self.aot.refresh_daemon_trigger_settings(unique_id)

    def output_state(self, output_id, output_channel):
        """Return the output state (on or off)"""
        return self.aot.output_state(output_id, output_channel)

    def output_states_all(self):
        """Return all output states."""
        return self.aot.output_states_all()

    def input_status_all(self):
        """Return comm status (comm_capable/comm_is_fault/comm_last_success) for all Inputs."""
        return self.aot.input_status_all()

    def output_comm_capable_all(self):
        """Return {output_id: bool} — can this Output observe its device's state."""
        return self.aot.output_comm_capable_all()

    def output_on(self,
                  output_id,
                  output_type=None,
                  amount=0.0,
                  min_off=0.0,
                  output_channel=None,
                  trigger_conditionals=True,
                  additional_options=None,
                  origin=None):
        """Turns output on from the client."""
        return self.aot.output_on(
            output_id,
            output_channel=output_channel,
            output_type=output_type,
            amount=amount,
            min_off=min_off,
            trigger_conditionals=trigger_conditionals,
            additional_options=additional_options,
            origin=origin)

    def output_off(self, output_id, output_channel=None, trigger_conditionals=True,
                   origin=None):
        """Turns output off from the client."""
        return self.aot.output_off(
            output_id, output_channel=output_channel,
            trigger_conditionals=trigger_conditionals, origin=origin)

    def output_sec_currently_on(self, output_id, output_channel=None):
        """Turns the amount of time a output has already been on."""
        return self.aot.controller['Output'].output_sec_currently_on(
            output_id, output_channel=output_channel)

    def output_setup(self, action, output_id):
        """Add, delete, or modify a output in the running output controller."""
        return self.aot.output_setup(action, output_id)

    def output_target_pct(self, output_id, output_channel=0):
        """Return (last_target_pct, last_target_source) for an actuator_paired output."""
        return self.aot.output_target_pct(output_id, output_channel)

    def trigger_action(self, action_id, value={}, debug=False):
        """Trigger action."""
        return self.aot.trigger_action(
            action_id,
            value=value,
            debug=debug)

    def trigger_all_actions(self, function_id, message='', debug=False):
        """Trigger all actions."""
        return self.aot.trigger_all_actions(function_id, message=message, debug=debug)

    def terminate_daemon(self):
        """Instruct the daemon to shut down."""
        return self.aot.terminate_daemon()

    def widget_add_refresh(self, unique_id):
        """Add or refresh widget object."""
        return self.aot.controller['Widget'].widget_add_refresh(unique_id)

    def widget_remove(self, unique_id):
        """Remove widget object."""
        return self.aot.controller['Widget'].widget_remove(unique_id)

    def widget_execute(self, unique_id):
        """Execute widget object."""
        return self.aot.controller['Widget'].widget_execute(unique_id)

    @staticmethod
    def daemon_status():
        """
        Merely indicates if the daemon is running or not, with successful
        response of 'alive'. This will perform checks in the future and
        return a more detailed daemon status.

        TODO: Incorporate controller checks with daemon status
        """
        return 'alive'

    @staticmethod
    def is_in_virtualenv():
        """Returns True if this script is running in a virtualenv."""
        return hasattr(sys, 'real_prefix') or sys.base_prefix != sys.prefix

    @staticmethod
    def ram_use():
        """Return the amount of ram used by the daemon."""
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / float(1000)

    @expose
    def execute_action(self, action_dict):
        """
        Execute an AI action via Pyro5 RPC.
        Receives action dictionary and delegates to AIActionService.execute_action().

        Args:
            action_dict: dict containing action_type, target_id, params, context

        Returns:
            ExecutionResult dict with status, result, error fields
        """
        try:
            action_type = action_dict.get('action_type')
            target_id = action_dict.get('target_id')
            params = action_dict.get('params')
            context = action_dict.get('context')

            result = AIActionService.execute_action(
                action_type=action_type,
                target_id=target_id,
                params=params,
                context=context
            )
            return {
                'status': 'success',
                'result': result,
                'error': None
            }
        except Exception as e:
            self.logger.exception(f"Error executing action: {e}")
            return {
                'status': 'error',
                'result': None,
                'error': str(e)
            }

    @expose
    def sync_status(self, device_id, status):
        """
        Sync hardware device status to InfluxDB.

        Args:
            device_id: Unique identifier for the device
            status: Status value to write (e.g., 'on', 'off', 'error')

        Returns:
            dict with success boolean and message
        """
        try:
            write_influxdb_value(
                unique_id=device_id,
                unit='status',
                value=1,
                measure=status
            )
            return {
                'success': True,
                'message': f"Status synced for device {device_id}"
            }
        except Exception as e:
            self.logger.exception(f"Error syncing status for {device_id}: {e}")
            return {
                'success': False,
                'message': str(e)
            }

class PyroDaemon(threading.Thread):
    """
    Class to run the Pyro5 server thread

    ComServer will handle execution of commands from the web UI or other
    controllers. It allows the client (aot_client.py to be executed as non-root
    user) to communicate with the daemon (aot_daemon.py running with root privileges).

    """
    def __init__(self, aot):
        threading.Thread.__init__(self)

        self.logger = logging.getLogger('aot.pyro_daemon')
        self.aot = aot

    def run(self):
        try:
            self.logger.info("Starting Pyro5 daemon")
            serve({
                PyroServer(self.aot): 'aot.pyro_server',
            }, host="0.0.0.0", port=9081, use_ns=False)
        except Exception:
            self.logger.exception("PyroDaemon")


class PyroMonitor(threading.Thread):
    """
    Monitor whether the Pyro5 server (and daemon) is active or not

    """
    def __init__(self):
        threading.Thread.__init__(self)

        self.logger = logging.getLogger('aot.pyro_monitor')
        self.timer_sec = 1800

    def run(self):
        try:
            self.logger.info(f"Starting Pyro5 daemon monitor ({self.timer_sec / 60.0:.0f} min timer)")
            log_timer = time.time() + 1
            while True:
                now = time.time()
                if now > log_timer:
                    while now > log_timer:
                        log_timer += self.timer_sec
                    try:
                        proxy = Proxy("PYRO:aot.pyro_server@127.0.0.1:9081")
                        proxy.check_daemon()
                        self.logger.debug(f"Pyro5 daemon monitor: daemon_status() response: '{proxy.daemon_status()}'")
                    except Exception:
                        self.logger.exception("Pyro5 daemon monitor")
                time.sleep(1)
        except Exception:
            self.logger.exception("ERROR: PyroMonitor")


class AoTDaemon:
    """
    Handle starting the components of the AoT Daemon
    """
    def __init__(self, aot):
        self.logger = logging.getLogger('aot.daemon')
        self.aot = aot

    def start_daemon(self):
        """Start communication and daemon threads."""
        try:
            pd = PyroDaemon(self.aot)
            pd.daemon = True
            pd.start()

            # pm = PyroMonitor()
            # pm.daemon = True
            # pm.start()

            self.aot.run()  # Start daemon thread that manages controllers
        except Exception:
            self.logger.exception("ERROR Starting AoT Daemon")


def parse_args():
    parser = argparse.ArgumentParser(description='AoT daemon.')

    parser.add_argument('-d', '--debug', action='store_true',
                        help='Set Log Level to Debug.')

    return parser.parse_args()


if __name__ == '__main__':
    # Check for root privileges
    # if not os.geteuid() == 0:
    #     sys.exit("Script must be executed as root")

    # Parse commandline arguments
    args = parse_args()

    debug = False
    misc = db_retrieve_table_daemon(Misc, entry='first')
    if misc:
        debug = misc.daemon_debug_mode
    if args.debug:
        debug = args.debug

    if debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logger.setLevel(log_level)
    # 핸들러 레벨도 동기화 — logger 레벨이 상위 필터지만 핸들러에도 명시적으로 적용
    for _h in logger.handlers:
        _h.setLevel(log_level)

    daemon_controller = DaemonController()

    # SIGTERM/SIGINT 을 systemd 의 ExecStop 과 같은 경로로 보낸다.
    #
    # 네이티브 설치는 `install/aot.service` 의
    # `ExecStop=... aot_client.py -t`(terminate_daemon RPC)로 정상 종료 절차를
    # 타지만, Docker 배포에는 ExecStop 개념이 없어 `docker stop` 이 곧바로
    # SIGTERM 이었다. 핸들러가 없으니 프로세스가 그냥 죽어 각 Output 의
    # Shutdown State 가 **전송되지 않았다** — 사용자가 "종료 시 끄기" 로 설정해도
    # 컨테이너 재시작에서는 안 꺼졌다는 뜻이다. 설정과 실제 동작을 맞춘다.
    #
    # 여기서는 플래그만 내린다. run() 이 메인 스레드에서 돌고 있으므로 루프가
    # 다음 회차에 빠져나가 stop_all_controllers() → 각 Output 의 Shutdown State
    # → 감사 flush 까지 정상 순서로 진행한다. 신호 핸들러 안에서 블로킹하면
    # 그 절차를 오히려 방해한다.
    def _graceful_stop(signum, _frame):
        if not daemon_controller.daemon_run:
            logger.info(f"신호 {signum} 재수신 — 이미 종료 중입니다")
            return
        logger.info(f"신호 {signum} 수신 — 정상 종료 절차를 시작합니다")
        daemon_controller.thread_shutdown_timer = timeit.default_timer()
        daemon_controller.daemon_run = False

    signal.signal(signal.SIGTERM, _graceful_stop)
    signal.signal(signal.SIGINT, _graceful_stop)

    aot_daemon = AoTDaemon(daemon_controller)
    aot_daemon.start_daemon()
