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
from datetime import datetime
from aot.utils.time_utils import utc_now

import threading
import time
import timeit

from aot.controllers.base_controller import AbstractController
from aot.databases.models import Misc
from aot.databases.models import Output
from aot.databases.models import SMTP
from aot.aot_client import DaemonControl
from aot.utils import output_audit
from aot.utils.command_origin import (TYPE_LIFECYCLE, normalize_origin,
                                      should_audit)
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.execution_context import clear_execution_context
from aot.utils.execution_context import set_execution_context
from aot.utils.modules import load_module_from_file
from aot.utils.outputs import output_types
from aot.utils.outputs import parse_output_information


class OutputController(AbstractController, threading.Thread):
    """Manage all output devices with on/off control and timed duration.

    @phase active
    @stability stable
    @dependency AbstractController, DaemonControl, Output, OutputChannel
    """
    def __init__(self, ready, debug):
        threading.Thread.__init__(self)
        super().__init__(ready, unique_id=None, name=__name__)

        self.set_log_level_debug(debug)
        self.control = DaemonControl()

        # SMTP options
        self.smtp_max_count = None
        self.smtp_wait_time = None
        self.smtp_timer = None
        self.email_count = None
        self.allowed_to_send_notice = None

        self.sample_rate = None
        self.output = {}
        self.dict_outputs = {}
        self.output_unique_id = {}
        self.output_type = {}
        self.output_types = {}

        # One lock per output ID, serializing the background reloads started by
        # output_setup(). Two saves of the same output in quick succession would
        # otherwise race on self.output[output_id] and leave a half-torn-down
        # driver behind.
        self._setup_locks = {}
        self._setup_locks_guard = threading.Lock()

        # (output_id, channel) -> 그 채널을 켠 명령의 출처.
        # 자동 OFF 는 그 명령의 꼬리이므로 같은 출처로 귀속한다 (loop() 참조).
        self._on_origin = {}
        # (output_id, channel) -> 자동 OFF 재시도를 허용할 최소 시각(monotonic).
        self._auto_off_retry_at = {}

        # 짝 액추에이터 다리 인터락용 캐시. `paired_leg_relations` 조회는
        # OutputChannel 을 전부 훑으므로 명령마다 새로 하지 않는다 — 짧은
        # TTL 만 준다(_interlock_paired_legs 참조).
        self._paired_leg_relations = {}
        self._paired_leg_relations_at = 0.0
        self._PAIRED_LEG_RELATIONS_TTL_S = 3.0

    def initialize_variables(self):
        """Begin initializing output parameters."""
        self.sample_rate = db_retrieve_table_daemon(Misc, entry='first').sample_rate_controller_output

        self.logger.debug("Initializing Outputs")
        try:
            smtp = db_retrieve_table_daemon(SMTP, entry='first')
            self.smtp_max_count = smtp.hourly_max
            self.smtp_wait_time = time.time() + 3600
            self.smtp_timer = time.time()
            self.email_count = 0
            self.allowed_to_send_notice = True

            outputs = db_retrieve_table_daemon(Output, entry='all')
            self.all_outputs_initialize(outputs)
            self.logger.debug("Outputs Initialized")

            self.ready.set()
            self.running = True
        except Exception:
            self.logger.exception("Problem initializing outputs")

    # 자동 OFF 가 실패했을 때 다시 시도하기까지 기다리는 시간(초).
    # 0.25초 루프에서 곧바로 재시도하면 죽은 원격 호스트를 초당 네 번 두들긴다.
    AUTO_OFF_RETRY_INTERVAL_S = 30.0

    def loop(self):
        """Main loop of the output controller."""
        for output_id in self.output:
            for each_channel in self.output_unique_id[output_id]:

                # Execute if past the time the output was supposed to turn off
                if (self.output[output_id].output_setup and
                        each_channel in self.output[output_id].output_on_until and
                        self.output[output_id].output_on_until[each_channel] is not None and
                        self.output[output_id].output_on_until[each_channel] < utc_now() and
                        self.output[output_id].output_on_duration[each_channel] and
                        not self.output[output_id].output_off_triggered[each_channel]):

                    # 직전 자동 OFF 가 실패해 빗장을 다시 푼 경우, 백오프가 끝날
                    # 때까지는 재시도하지 않는다 — 이 루프는 0.25초마다 돈다.
                    if time.monotonic() < self._auto_off_retry_at.get(
                            (output_id, each_channel), 0):
                        continue

                    # Use a thread to prevent blocking the loop
                    self.output[output_id].output_off_triggered[each_channel] = True
                    turn_output_off = threading.Thread(
                        target=self._auto_off,
                        args=(output_id, each_channel))
                    turn_output_off.start()

    def _auto_off(self, output_id, output_channel):
        """시간이 다 된 출력을 끈다 — **제어 게이트를 통해서.**

        예전에는 `loop()` 이 드라이버의 `output_on_off('off')` 를 직접 불렀다.
        게이트(`OutputController.output_on_off`)를 건너뛰므로 세 가지가 동시에
        빠졌고, 셋 다 "기록과 실물이 어긋난다" 는 같은 증상으로 나타난다:

        1. **감사 기록이 없다.** 타이머 ON 은 감사로그에 남는데 그것을 끝낸
           자동 OFF 는 아무 데도 안 남는다. 로그만 보면 밸브가 아직 열려 있는
           것으로 읽힌다 — 원격 밸브 조사(2026-09-21)에서 실제로 그렇게 보였다.
        2. **실행 컨텍스트가 없다.** `set_execution_context` 를 지나지 않으니
           InfluxDB 의 `source_type` 태그가 비고, 게이트 주석이 "그래서 30일간
           한 건도 안 찍혔다" 고 적어 둔 그 사고가 이 경로에서만 그대로 남는다.
        3. **실패가 아무 데도 안 드러난다.** `output_off_triggered` 를 미리
           True 로 올려 두므로 OFF 가 실패해도(원격 호스트 불통 등) 재시도도
           기록도 없다. 밸브는 열린 채, 화면은 조용한 채로 굳는다.

        출처는 **그 채널을 켠 명령의 출처를 물려받는다.** 자동 OFF 는 독립된
        명령이 아니라 그 명령의 꼬리이기 때문이다. 덕분에 감사 정책도 그대로
        유지된다 — 사람/시퀀스가 켠 것의 OFF 는 남고(그래야 로그가 말이 된다),
        PID 처럼 주기마다 켜는 자동화의 OFF 는 ON 과 마찬가지로 안 남아
        관계형 테이블을 잠그지 않는다(`command_origin.AUDITED_TYPES` 참조).
        """
        key = (output_id, output_channel)
        origin = self._on_origin.get(key)
        try:
            ret = self.output_on_off(
                output_id, 'off', output_channel=output_channel, origin=origin)
        except Exception:
            self.logger.exception(
                f"자동 OFF 실패: output={output_id} CH{output_channel}")
            ret = (1, 'exception')

        failed = bool(ret[0]) if isinstance(ret, (tuple, list)) and ret else False
        if not failed:
            self._auto_off_retry_at.pop(key, None)
            return

        # 실패했으면 다시 시도할 수 있게 빗장을 푼다. 그대로 두면 이 채널은
        # 영영 감시 대상에서 빠져(`output_off_triggered` 가 True 로 굳는다)
        # 물리적으로 열린 밸브를 아무도 닫지 않는다. 다음 시도까지의 간격은
        # `loop()` 이 `_auto_off_retry_at` 으로 지킨다.
        self._auto_off_retry_at[key] = (
            time.monotonic() + self.AUTO_OFF_RETRY_INTERVAL_S)
        self.logger.error(
            f"Output {output_id} CH{output_channel}: 자동 OFF 가 실패했습니다 "
            f"({ret[1] if isinstance(ret, (tuple, list)) and len(ret) > 1 else ret}). "
            f"{self.AUTO_OFF_RETRY_INTERVAL_S:.0f}초 뒤 다시 시도합니다.")
        try:
            self.output[output_id].output_off_triggered[output_channel] = False
        except Exception:
            pass

    def run_finally(self):
        """Run when the controller is shutting down.

        Every output is shut down independently. self.output_unique_id holds an
        entry for outputs that never got a driver -- 'no_run' modules such as
        output_spacer, and anything whose module failed to load -- because it is
        filled in before those checks in all_outputs_initialize(). Indexing
        self.output for one of those raises KeyError, and with no guard here
        that escaped run_finally() (called from base_controller's finally),
        killing the thread and silently dropping the Shutdown State of every
        output after it. Nothing was logged; shutdown just looked fast.
        """
        # Turn all outputs to their shutdown state
        for each_output_id in self.output_unique_id:
            output_obj = self.output.get(each_output_id)
            if output_obj is None:
                continue  # No driver was ever built (no_run / load failure).
            try:
                shutdown_timer = timeit.default_timer()
                # 종료 상태 전송도 게이트를 안 지난다. shutdown() 이 드라이버를 정리해
                # 옵션을 못 읽게 되므로 반드시 **먼저** 기록한다.
                self._audit_lifecycle(
                    each_output_id, 'state_shutdown', 'daemon_shutdown')
                # instruct each output to shut down
                output_obj.shutdown(shutdown_timer)
            except Exception:
                # One driver must not take the rest of the site down with it.
                self.logger.exception(
                    f"Could not shut down output {each_output_id}; continuing "
                    f"with the remaining outputs")

    def all_outputs_initialize(self, outputs):
        """Initialize all output variables and classes.

        Drivers that opt into startup_state_is_deferrable() have their Startup
        State held back and replayed from a background thread once every output
        exists (see _apply_deferred_startup_states). Sending it inline made boot
        O(N) on the site-wide LoRaWAN pacing slot -- ~254 s for 30 outputs --
        and nothing else runs during that window: initialize_variables() has not
        returned, so ready.set() has not fired, no Input controller has started,
        and OutputController.loop() has not begun supervising timed outputs.
        """
        self.dict_outputs = parse_output_information()
        self.output_types = output_types()
        deferred_startup = []

        for each_output in outputs:
            if each_output.output_type not in self.dict_outputs:
                self.logger.error(f"'{each_output.output_type}' not found in Output dictionary. Not starting Output.")
                continue

            try:
                self.output_type[each_output.unique_id] = each_output.output_type
                self.output_unique_id[each_output.unique_id] = {}

                if 'channels_dict' in self.dict_outputs[each_output.output_type]:
                    for each_channel in self.dict_outputs[each_output.output_type]['channels_dict']:
                        self.output_unique_id[each_output.unique_id][each_channel] = None
                else:
                    self.output_unique_id[each_output.unique_id][0] = None

                # Also register channels from DB (for dynamic multi-channel outputs)
                from aot.databases.models import OutputChannel
                for db_ch in db_retrieve_table_daemon(OutputChannel).filter(
                        OutputChannel.output_id == each_output.unique_id).all():
                    if db_ch.channel not in self.output_unique_id[each_output.unique_id]:
                        self.output_unique_id[each_output.unique_id][db_ch.channel] = None

                if each_output.output_type in self.dict_outputs:
                    if ('no_run' in self.dict_outputs[each_output.output_type] and
                            self.dict_outputs[each_output.output_type]['no_run']):
                        continue

                    output_loaded, status = load_module_from_file(
                        self.dict_outputs[each_output.output_type]['file_path'],
                        'outputs')

                    if output_loaded:
                        output_obj = output_loaded.OutputModule(each_output)
                        self.output[each_output.unique_id] = output_obj

                        # Hold back the Startup State for rate-limited drivers
                        # so try_initialize() below does not sit on the pacing
                        # slot. The saved values are replayed after the loop.
                        saved_startup = self._defer_startup_state(
                            each_output.unique_id, output_obj)
                        if saved_startup is not None:
                            deferred_startup.append(
                                (each_output.unique_id, saved_startup))

                        output_obj.try_initialize()
                        # 기동 상태 전송은 게이트를 안 지난다 — 여기서만 남는다.
                        self._audit_lifecycle(
                            each_output.unique_id, 'state_startup', 'daemon_startup')
                        output_obj.init_post()

                self.logger.debug(f"{each_output.unique_id.split('-')[0]} ({each_output.name}) Initialized")
            except:
                self.logger.exception(f"Could not initialize output {each_output.unique_id}")

        if deferred_startup:
            self.logger.info(
                f"Startup State deferred for {len(deferred_startup)} rate-limited "
                f"output(s); sending in the background so boot is not blocked")
            thread = threading.Thread(
                target=self._apply_deferred_startup_states,
                args=(deferred_startup,))
            thread.daemon = True
            thread.start()

    def _defer_startup_state(self, output_id, output_obj):
        """Blank a deferrable driver's Startup State, returning the saved values.

        Returns None when the driver did not opt in (nothing was changed), so
        the caller only queues the ones it actually suppressed.
        """
        try:
            if not output_obj.startup_state_is_deferrable():
                return None
        except Exception:
            return None
        try:
            saved = dict(output_obj.options_channels.get('state_startup') or {})
        except Exception:
            return None
        if not saved:
            return None
        # Same mechanism the settings-reload path uses: every driver reads
        # anything other than 0/1 as "do nothing" (see suppress_state_transition).
        self.suppress_state_transition(output_obj, 'state_startup')
        return saved

    def _apply_deferred_startup_states(self, deferred_startup):
        """Restore and send the Startup States held back during boot.

        Runs on its own thread. Each send still waits on the site-wide pacing
        slot, but off the boot path -- the daemon is already serving RPCs and
        supervising timed outputs while these go out.
        """
        for output_id, saved_startup in deferred_startup:
            try:
                output_obj = self.output.get(output_id)
                if output_obj is None:
                    continue  # Removed while we were booting.
                output_obj.options_channels['state_startup'].update(saved_startup)
                output_obj.apply_startup_state()
                # Audit here, not at construction. _audit_lifecycle() skips a
                # channel whose value is None, and while we were booting these
                # were blanked -- so the physical state change would otherwise
                # go unrecorded, which is the exact gap that method exists to
                # close. Recorded after the send, matching the inline path.
                self._audit_lifecycle(
                    output_id, 'state_startup', 'daemon_startup')
            except Exception:
                self.logger.exception(
                    f"Could not apply deferred Startup State for {output_id}")
        self.logger.info("Deferred Startup States sent")

    def suppress_state_transition(self, output_instance, option_id):
        """Neutralize a startup/shutdown state option before a settings reload.

        Saving an Output's settings tears the driver down and builds it back up,
        which makes every module run its Shutdown State and then its Startup
        State transmission. Those are *daemon lifecycle* actions: replaying them
        on a settings save physically actuates the device, so renaming a valve
        drives that valve. On LoRaWAN sites it also costs two downlinks per save
        against a single site-wide 4 s pacing slot (aot/utils/lorawan_pacing.py),
        which is what pushed output_setup past the web UI's RPC deadline.

        Every module reads these as options_channels[option_id][channel] and
        treats any value other than 0/1 as "do nothing", so blanking them here
        covers all drivers without touching a single module. options_channels is
        built in each module's __init__, so this works on a freshly constructed
        instance too — before try_initialize() applies the Startup State.
        """
        try:
            channel_options = output_instance.options_channels[option_id]
        except Exception:
            return  # Module has no such option; nothing to suppress.
        try:
            for channel in channel_options:
                channel_options[channel] = None
        except Exception:
            self.logger.exception(f"Suppressing {option_id}")

    def add_mod_output(self, output_id):
        """
        Add or modify local dictionary of output settings form SQL database

        When a output is added or modified while the output controller is
        running, these local variables need to also be modified to
        maintain consistency between the SQL database and running controller.

        :param output_id: Unique ID for each output
        :type output_id: str

        :return: 0 for success, 1 for fail, with success for fail message
        :rtype: int, str
        """
        try:
            self.dict_outputs = parse_output_information()

            output = db_retrieve_table_daemon(Output, unique_id=output_id)

            self.output_type[output_id] = output.output_type
            self.output_unique_id[output_id] = {}

            if 'channels_dict' in self.dict_outputs[output.output_type]:
                for each_channel in self.dict_outputs[output.output_type]['channels_dict']:
                    self.output_unique_id[output_id][each_channel] = None
            else:
                self.output_unique_id[output_id][0] = None

            # Also register channels from DB (for dynamic multi-channel outputs)
            from aot.databases.models import OutputChannel
            for db_ch in db_retrieve_table_daemon(OutputChannel).filter(
                    OutputChannel.output_id == output_id).all():
                if db_ch.channel not in self.output_unique_id[output_id]:
                    self.output_unique_id[output_id][db_ch.channel] = None

            if self.output_type[output_id] in self.dict_outputs:
                if ('no_run' in self.dict_outputs[output.output_type] and
                        self.dict_outputs[output.output_type]['no_run']):
                    pass
                else:
                    # Try to stop the output
                    if output_id in self.output:
                        try:
                            self.suppress_state_transition(
                                self.output[output_id], 'state_shutdown')
                            self.output[output_id].stop_output()
                        except Exception:
                            self.logger.exception("Stopping output")

                    output_loaded, status = load_module_from_file(
                        self.dict_outputs[self.output_type[output_id]]['file_path'],
                        'outputs')
                    if output_loaded:
                        self.output[output_id] = output_loaded.OutputModule(output)
                        self.suppress_state_transition(
                            self.output[output_id], 'state_startup')
                        self.output[output_id].try_initialize()
                        self.output[output_id].init_post()

            return 0, "add_mod_output() Success"
        except Exception as e:
            return 1, f"add_mod_output() Error: {output_id}: {e}"

    def del_output(self, output_id):
        """
        Delete output from being managed by Output controller

        :param output_id: Unique ID for output
        :type output_id: str

        :return: 0 for success, 1 for fail (with error message)
        :rtype: int, str
        """
        try:
            self.dict_outputs = parse_output_information()

            if output_id not in self.output_type:
                msg = f"Output {output_id} Deleted (was not tracked by the running daemon)."
                self.logger.debug(msg)
                return 0, msg

            if ('no_run' in self.dict_outputs[self.output_type[output_id]] and
                    self.dict_outputs[self.output_type[output_id]]['no_run']):
                pass

            # instruct output to shutdown
            shutdown_timer = timeit.default_timer()

            if ('no_run' in self.dict_outputs[self.output_type[output_id]] and
                    self.dict_outputs[self.output_type[output_id]]['no_run']):
                pass
            else:
                try:
                    # 삭제 경로의 종료 상태 전송은 일부러 억제하지 않는다(장치를
                    # 지우기 전에 shutdown 상태로 보내는 건 의미 있는 동작이다).
                    # 그러니 실제로 나가는 만큼 기록도 남겨야 한다.
                    self._audit_lifecycle(
                        output_id, 'state_shutdown', 'output_delete')
                    self.output[output_id].shutdown(shutdown_timer)
                except Exception as err:
                    self.logger.error(f"Could not shut down output gracefully: {err}")

            self.output_unique_id.pop(output_id, None)
            self.output_type.pop(output_id, None)
            self.output.pop(output_id, None)
            msg = f"Output {output_id} Deleted."
            self.logger.debug(msg)
            return 0, msg
        except Exception as e:
            self.logger.exception(1)
            return 1, f"Error deleting Output {output_id}: {e}"

    def output_on_off(self,
                      output_id,
                      state,
                      output_channel=0,
                      output_type=None,
                      amount=0.0,
                      min_off=0.0,
                      trigger_conditionals=True,
                      additional_options=None,
                      origin=None):
        """
        Manipulate an output by passing on/off, a volume, or a PWM duty cycle
        to the output module.

        **이 메서드가 모든 Output 명령의 단일 게이트다.** on 이든 off 든, 웹 UI 든
        Function 이든 AI 든 드라이버든, 전부 여기로 수렴한다 (`aot_daemon.py` 의
        `output_on`/`output_off` 둘 다 이걸 부른다). 그래서 "누가 이 장치를 켰나" 에
        답할 기록도 여기 한 곳에서만 남긴다 — 라우트마다 감사로그를 심으면 새 경로가
        생길 때마다 조용히 빠진다.

        :param output_id: ID for output
        :type output_id: str
        :param state: What state is desired? 'on', 1, True or 'off', 0, False
        :type state: str or int or bool
        :param output_channel: The output channel
        :type output_channel: int
        :param output_type: The type of output ('sec', 'vol', 'value', 'pwm')
        :type output_type: str
        :param amount: If state is 'on', an amount can be set (e.g. duration to stay on, volume to output, etc.)
        :type amount: float
        :param min_off: Don't allow on again for at least this amount (0 = disabled)
        :type min_off: float
        :param trigger_conditionals: Whether to allow trigger conditionals to act or not
        :type trigger_conditionals: bool
        """
        if output_id not in self.output:
            msg = f"Output {output_id} not found"
            self.logger.error(msg)
            self._audit_command(output_id, state, output_channel, output_type,
                                amount, origin, result='failure')
            return 1, msg

        # 짝 액추에이터의 열기/닫기(또는 버스의 selector) 다리로 쓰이는 채널을
        # 직접 켜는 경로 — 출력 페이지, Conditional 액션, MCP `operate_device`
        # 전부 결국 여기로 수렴하므로(파일 docstring 참조) 한 곳에서만 지키면
        # 된다. **이 함수 자신을 다시 부르기 전에** 실행 컨텍스트가 아직
        # 심어지지 않은 지금 자리에서 처리한다 — 아래에서 컨텍스트를 심은
        # 뒤에 재귀 호출하면, 재귀 호출 쪽 `finally` 가 그 컨텍스트를 지워
        # 버려서 이 명령 자신의 드라이버 호출이 컨텍스트 없이 나간다.
        if state in ('on', 1, True):
            self._interlock_paired_legs(output_id, output_channel, origin)

        # # TODO: Unimplemented until speed of current_amp_load() execution can be tested
        # # Checks if device is not on and instructed to turn on and will exceed max amp load
        # if (state == 'on' and
        #         self.output_type[output_id] in ['sec', 'vol'] and
        #         not self.is_on(output_id, output_channel=output_channel)):
        #     # Check if max amperage will be exceeded
        #     current_amps = self.current_amp_load()
        #     max_amps = db_retrieve_table_daemon(
        #         Misc, entry='first').max_amps
        #     if current_amps + self.output_amps[output_id] > max_amps:
        #         msg = "Cannot turn output {} On. If this output " \
        #               "turns on, there will be {} amps being drawn, " \
        #               "which exceeds the maximum set draw of {} " \
        #               "amps.".format(
        #             output_id,
        #             current_amps,
        #             max_amps)
        #         self.logger.warning(msg)
        #         return 1, msg

        # 실행 컨텍스트는 **이 스레드에서** 심어야 한다. 예전에는 호출자(Trigger 등)가
        # 자기 스레드에 심었는데, 명령이 Pyro5 RPC 를 타고 워커 스레드로 넘어오면서
        # thread-local 이 통째로 유실됐다 — 그래서 InfluxDB 의 source_type 태그가
        # 30일 내내 한 건도 안 찍혔다. origin 은 이제 인자로 넘어오므로 여기서 다시
        # 심으면 base_output 의 get_extra_tags() 가 제 값을 본다.
        origin = origin or {}
        # 이 채널을 켠 명령의 출처를 기억해 둔다. 시간이 다 돼 자동으로 끌 때
        # 그 출처를 물려받아야 감사로그가 "누가 켜고 언제 닫혔다" 로 읽힌다
        # (`_auto_off` 참조). OFF 에서는 갱신하지 않는다 — OFF 의 출처는
        # 그 자체로 기록되고, 다음 ON 이 오기 전까지 물려줄 것도 없다.
        if state in ('on', 1, True):
            self._on_origin[(output_id, output_channel)] = origin
        set_execution_context(
            source_type=origin.get('type'), source_id=origin.get('id'))
        try:
            ret = self.output[output_id].output_on_off(
                state,
                output_channel=output_channel,
                output_type=output_type,
                amount=amount,
                min_off=min_off,
                trigger_conditionals=trigger_conditionals,
                additional_options=additional_options)
        finally:
            # 워커 스레드는 재사용된다. 안 지우면 다음 명령이 엉뚱한 행위자를
            # 뒤집어쓴다 — 틀린 귀속은 기록이 없는 것보다 나쁘다.
            clear_execution_context()

        failed = bool(ret[0]) if isinstance(ret, (tuple, list)) and ret else False
        self._audit_command(output_id, state, output_channel, output_type, amount,
                            origin, result='failure' if failed else 'success')
        return ret

    def _paired_leg_relations_cached(self):
        """`paired_actuator_common.fetch_paired_leg_relations()` 를 짧은 TTL 로 캐시."""
        now = time.time()
        if now - self._paired_leg_relations_at > self._PAIRED_LEG_RELATIONS_TTL_S:
            try:
                from aot.outputs.paired_actuator_common import (
                    fetch_paired_leg_relations)
                self._paired_leg_relations = fetch_paired_leg_relations()
            except Exception as err:
                self.logger.warning("짝 액추에이터 다리 관계 조회 실패: %s", err)
                self._paired_leg_relations = {}
            self._paired_leg_relations_at = now
        return self._paired_leg_relations

    def _interlock_paired_legs(self, output_id, output_channel, origin):
        """이 채널이 짝 액추에이터의 열기/닫기/selector 다리라면, 반대쪽(또는
        같은 버스의 다른 selector)이 켜져 있을 때 먼저 끈다.

        짝 액추에이터 드라이버 자신의 인터락(반대 릴레이를 먼저 끄고 방향
        전환 사이에 정지 시간을 둠, `actuator_paired.py` 의 `_drive` 참조)을
        **드라이버를 거치지 않고 밑단 채널을 직접 켜는 경로에도** 적용한다.
        하나라도 실패해도 본 명령(ON)은 계속 진행한다 — 인터락 조회·해제
        실패로 원래 하려던 제어까지 막으면 더 나쁘다. 대신 로그를 남긴다.
        """
        try:
            relations = self._paired_leg_relations_cached()
            entries = relations.get((output_id, output_channel)) or []
        except Exception as err:
            self.logger.warning("짝 액추에이터 인터락 조회 실패: %s", err)
            return

        seen = set()
        for entry in entries:
            for other_id, other_channel in entry.get('partners') or []:
                key = (other_id, other_channel)
                if key == (output_id, output_channel) or key in seen:
                    continue
                seen.add(key)
                driver = self.output.get(other_id)
                if driver is None:
                    continue
                try:
                    if not driver.is_on(output_channel=other_channel):
                        continue
                except Exception as err:
                    self.logger.warning(
                        "짝 액추에이터 인터락: %s(CH%s) 상태 확인 실패: %s",
                        other_id, other_channel, err)
                    continue
                self.logger.info(
                    "짝 액추에이터 인터락: %s(CH%s) 를 켜기 전에 %s 다리인 "
                    "%s(CH%s) 를 먼저 끕니다 (owner=%s)",
                    output_id, output_channel, entry.get('leg'),
                    other_id, other_channel, entry.get('owner_name'))
                try:
                    self.output_on_off(
                        other_id, 'off', output_channel=other_channel,
                        trigger_conditionals=False, origin=origin)
                except Exception as err:
                    self.logger.warning(
                        "짝 액추에이터 인터락: %s(CH%s) 를 끄지 못했습니다: %s",
                        other_id, other_channel, err)

    def _audit_command(self, output_id, state, output_channel, output_type,
                       amount, origin, result):
        """감사 큐에 한 건 적재. 논블로킹이고 절대 예외를 올리지 않는다.

        자동화(PID·env_coordinator 등)는 주기마다 명령하므로 관계형 감사로그에
        넣지 않는다 — 사람/API/AI/불명만 남기고 나머지는 InfluxDB 태그로 추적한다.
        """
        try:
            if not should_audit(origin):
                return
            driver = self.output.get(output_id)
            # 명령을 실제로 내보냈는지까지 남긴다. 드라이버가 "이미 그 상태" 라서
            # 아무것도 안 보내고 성공을 돌려준 경우가 정상 제어와 똑같이 기록되면,
            # 로컬 상태 캐시가 실제 장치와 어긋났을 때 "로그에는 ON 인데 장치는
            # 그대로" 가 되고 로그만으로는 원인을 가릴 수 없다
            # (base_output.last_command_dispatched 참조).
            try:
                dispatched = driver.last_command_dispatched(output_channel)
            except Exception:
                dispatched = True
            output_audit.record({
                'output_id': output_id,
                'output_name': getattr(driver, 'output_name', None),
                'channel': output_channel,
                'state': state,
                'output_type': output_type,
                'amount': amount,
                'origin': normalize_origin(origin),
                'ip_address': normalize_origin(origin).get('ip'),
                'result': result,
                'dispatched': dispatched,
            })
        except Exception:
            self.logger.debug("Output 감사 적재 실패", exc_info=True)

    def _audit_lifecycle(self, output_id, option_id, phase):
        """드라이버 생명주기 상태 전송을 감사에 남긴다.

        **이 경로는 제어 게이트를 지나지 않는다.** 기동·종료·삭제 때 드라이버의
        `initialize()`/`stop_output()` 이 하드웨어를 직접 건드리기 때문이다 — 예를
        들어 `on_off_gpio` 는 `initialize()` 안에서 `GPIO.output()` 을 그냥 호출한다.
        그래서 여기서 따로 남기지 않으면 물리 상태가 바뀐 기록이 아무 데도 없고,
        "아무도 안 켰는데 켜져 있다" 가 그대로 재현된다.

        `suppress_state_transition()` 이 None 으로 만든 채널과 '-1'(아무것도 안 함)은
        실제 전송이 없으므로 건너뛴다 — 모든 드라이버가 0/1 이외 값을 무시한다는
        공통 규약을 그대로 따른다.
        """
        try:
            instance = self.output.get(output_id)
            channel_options = dict(instance.options_channels[option_id])
        except Exception:
            return  # 해당 옵션이 없는 모듈 — 내보낼 상태가 없다
        for channel, value in channel_options.items():
            if value is None or value not in (0, 1, True, False, '0', '1'):
                continue
            try:
                output_audit.record({
                    'output_id': output_id,
                    'output_name': getattr(instance, 'output_name', None),
                    'channel': channel,
                    'state': 'on' if value in (1, True, '1') else 'off',
                    'output_type': option_id,
                    'amount': None,
                    'origin': {'type': TYPE_LIFECYCLE, 'id': phase, 'name': phase},
                    'ip_address': None,
                    'result': 'success',
                })
            except Exception:
                self.logger.debug("생명주기 감사 적재 실패", exc_info=True)

    def output_setup(self, action, output_id):
        """Add, delete, or modify a specific output.

        Hands the reload to a worker thread and returns immediately. Rebuilding
        a driver can block for tens of seconds — a LoRaWAN send waits up to
        MAX_PACE_WAIT_S (30 s) for a site-wide downlink slot, and an MQTT
        listener teardown joins for up to 5 s — while the caller in aot_client.py
        gives the RPC 10 s (_MAX_RPC_TIMEOUT). Answering synchronously made the
        web UI report "Could not connect to Daemon: receiving: timeout" on saves
        that were in fact succeeding in the background.

        The trade-off is that per-output failures no longer reach the flash
        message; they are logged instead, which is why the worker logs errors at
        ERROR rather than swallowing them.
        """
        if action not in ['Add', 'Modify', 'Delete']:
            return 1, 'Invalid output_setup action'

        with self._setup_locks_guard:
            lock = self._setup_locks.setdefault(output_id, threading.Lock())

        def _reload():
            with lock:
                try:
                    if action == 'Delete':
                        error, msg = self.del_output(output_id)
                    else:
                        error, msg = self.add_mod_output(output_id)
                except Exception:
                    self.logger.exception(f"output_setup({action}, {output_id})")
                    return
                if error:
                    self.logger.error(f"output_setup({action}, {output_id}): {msg}")
                else:
                    self.logger.debug(f"output_setup({action}, {output_id}): {msg}")

        threading.Thread(
            target=_reload,
            name=f"output_setup_{output_id[:8]}",
            daemon=True).start()

        return 0, f"{action} accepted; the output is reloading in the background"

    def current_amp_load(self):  # TODO: Unimplemented until speed of current_amp_load() execution can be tested
        """
        Calculate the sum of amps drawn from all outputs currently on

        :return: total Amperage draw
        :rtype: float
        """
        from aot.databases.models import OutputChannel
        amp_load = 0.0

        for each_output_id in self.output:
            output_channels = db_retrieve_table_daemon(
                OutputChannel).filter(OutputChannel.output_id == each_output_id).all()
            self.setup_custom_channel_options_json(
                self.output[each_output_id].OUTPUT_INFORMATION['custom_channel_options'], output_channels)
            channels_amps = self.output[each_output_id].options_channels['amps']
            for each_channel in channels_amps:
                if self.is_on(each_output_id, output_channel=each_channel) and channels_amps[each_channel]:
                    amp_load += channels_amps[each_channel]

        return amp_load

    def output_sec_currently_on(self, output_id, output_channel):
        return self.output[output_id].output_sec_currently_on(output_channel)

    def output_state(self, output_id, output_channel):
        """
        Return an output state
        :rtype: dict
        """
        if output_id and output_channel is not None and output_id in self.output:
            return self.output[output_id].output_state(output_channel)

    def output_states_all(self):
        """
        Return a dictionary of all output states
        :rtype: dict
        """
        states = {}
        for output_id in self.output:
            states[output_id] = {}
            for each_channel in self.output_unique_id[output_id]:
                try:
                    states[output_id][each_channel] = self.output[output_id].output_state(each_channel)
                except Exception as err:
                    self.logger.error(
                        f"Error getting state for channel {each_channel} of output with ID {output_id}: {err}")
        return states

    def is_on(self, output_id, output_channel=0):
        """
        CHeck if the output is on or off

        :param output_id: Unique ID for each output
        :type output_id: str
        :param output_channel: Channel each output
        :type output_id: int

        :return: Whether the output is currently On (True) or Off (False)
        :rtype: bool
        """
        try:
            return self.output[output_id].is_on(output_channel=output_channel)
        except KeyError:
            self.logger.error("Output not found. This indicates the output controller either didn't properly "
                              "start or it experienced a fatal error.")
        except Exception:
            self.logger.exception("is_on() exception")

    def is_setup(self, output_id):
        """
        This function checks to see if the output is set up

        :param output_id: Unique ID for each output
        :type output_id: str

        :return: Is it safe to manipulate this output?
        :rtype: bool
        """
        try:
            return self.output[output_id].is_setup()
        except Exception:
            self.logger.exception("is_setup() exception")

    def call_module_function(self, button_id, args_dict, unique_id=None, thread=True, return_from_function=False):
        """Execute function from custom action button press."""
        try:
            run_command = getattr(self.output[unique_id], button_id)
            if not thread or return_from_function:
                return_val = run_command(args_dict)
                if return_from_function:
                    return 0, return_val
                else:
                    return 0, f"Command sent to Output Controller. Returned: {return_val}"
            else:
                thread_run_command = threading.Thread(
                    target=run_command,
                    args=(args_dict,))
                thread_run_command.start()
                return 0, "Command sent to Output Controller and is running in the background."
        except Exception as err:
            msg = f"Error executing function '{button_id}': {err}"
            self.logger.exception(msg)
            return 1, msg
