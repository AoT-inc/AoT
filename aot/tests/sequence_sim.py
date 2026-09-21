# coding=utf-8
"""시퀀스 컨트롤러 시뮬레이터 — **출력에 실제로 나간 명령열**을 기록한다.

`test_sequence_scenarios.py` 가 이것으로 시나리오별 명령열을 고정한다.

## 무엇이 진짜이고 무엇이 가짜인가

진짜(흉내 내지 않는다):
  - `SequenceTriggerController` 의 `loop()` · `initialize_variables()` ·
    `refresh_settings()` · `run_finally()` · 계획 계산 · 재개 저장/복원
  - 출력층 `AbstractOutput.output_on_off()` — 켜기/끄기/연장/세션 상한/이어받기
  - `output_on_off` 액션 모듈의 `run_action()` — 스텝 길이를 어디서 읽는가

가짜:
  - 시계. 루프의 `time.sleep()` 이 가짜 시계를 밀고, 그 사이에 예약된 사건
    (설정 변경·비활성화·재시작)과 출력층의 자동 OFF 를 처리한다.
  - DB. Trigger·Actions 는 메모리 객체, 재개 상태(FunctionRuntimeState)는 임시
    SQLite 로 진짜 코드를 지난다.
  - 장치. `output_switch()` 가 명령을 기록하고 상태만 뒤집는다.
  - 출력 컨트롤러의 자동 OFF — `controller_output.loop()` 의 조건을 그대로 옮겼다.

출력층과 액션을 진짜로 쓰는 이유: 이 컨트롤러의 결함 절반은 **다른 계층과의
약속**이 어긋난 것이었다(스텝 길이를 액션이 못 읽음, 출력층이 연장을 첫 세션
끝에서 자름). 그 계층을 흉내 내면 흉내가 틀린 만큼 조용히 통과한다.

## 기록 형식

`sim.events` — `(경과초, 출력, 종류)`.
  ON / OFF   장치로 나간 명령(시퀀스가 보낸 것)
  AUTO_OFF   출력층 타이머가 끝나 스스로 끈 것
  RENEW      이어받기 — 장치 명령 없이 타이머만 새 세션으로
  EXTEND     이미 켜진 출력에 일반 ON — 장치 명령 없음(세션 상한 적용)
"""
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import aot.actions.output_on_off as action_mod
import aot.controllers.controller_trigger_sequence as seq_mod
import aot.outputs.base_output as base_output_mod
import aot.utils.weekly_schedule as weekly_mod
from aot.databases.models import Actions, Trigger
from aot.outputs.base_output import AbstractOutput

# 2026-09-07 00:00 UTC — 월요일(weekday 0). 창은 UTC 로 적는다.
EPOCH0 = datetime(2026, 9, 7, tzinfo=timezone.utc).timestamp()
SEQ_ID = 'sim-seq'


class _Clock:
    def __init__(self, t):
        self.t = t


class _FakeTime:
    """시퀀스 모듈의 `time` 을 대신한다. sleep 이 곧 시뮬레이션의 한 걸음이다."""

    def __init__(self, sim):
        self._sim = sim

    def time(self):
        return self._sim.clock.t

    def monotonic(self):
        return self._sim.clock.t

    def sleep(self, dt):
        self._sim._advance(dt)


def _fake_datetime(clock):
    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock.t, tz or timezone.utc)

        @classmethod
        def utcnow(cls):
            return datetime.fromtimestamp(clock.t, timezone.utc).replace(tzinfo=None)
    return FakeDatetime


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *a, **kw):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeControl:
    """DaemonControl 대역 — 호출을 진짜 출력층(`AbstractOutput`)으로 돌린다."""

    def __init__(self, sim):
        self._sim = sim

    def output_on(self, output_id, output_type=None, amount=0.0, min_off=0.0,
                  output_channel=None, trigger_conditionals=True,
                  additional_options=None):
        return self._sim._command(output_id, 'on', amount, additional_options)

    def output_off(self, output_id, output_channel=None, trigger_conditionals=True):
        return self._sim._command(output_id, 'off', 0, None)

    def output_on_off(self, output_id, state, output_type=None, amount=0.0,
                      output_channel=None, additional_options=None):
        return self._sim._command(output_id, state, amount, additional_options)

    def output_state(self, output_id, output_channel=None, *a, **kw):
        out = self._sim.outputs.get(output_id)
        return None if out is None else ('on' if out.output_states[0] else 'off')

    def output_states_all(self):
        return {oid: {0: 'on' if o.output_states[0] else 'off'}
                for oid, o in self._sim.outputs.items()}


class SequenceSim:
    """시나리오 하나. `step()` 으로 스텝을 넣고 `run()` 으로 돌린다.

    :param start: 시뮬레이션 시작 시각(월요일 00:00 기준 초)
    :param window: (시작 'HH:MM', 끝 'HH:MM') UTC — 모든 요일 같은 창
    :param period: 사이클 주기(초)
    :param overlap: 교차 시간(초) — `Trigger.output_duration`
    """

    def __init__(self, monkeypatch, runtime_db, start, window, period,
                 overlap=0.0, resume_on_activate=True):
        self.mp = monkeypatch
        self.clock = _Clock(EPOCH0 + start)
        self.t_origin = self.clock.t
        self.events = []
        self.outputs = {}
        self.actions = []
        self._scheduled = []          # (시각, 콜백)
        self._auto_flag = False
        self._stop_at = None
        self._pending_stop = None     # 'deactivate' | 'restart' | None
        self._pending_start = False   # 비활성 중 다시 켜기 요청
        self.inst = None

        start_hm, end_hm = window
        days = {str(i): {'enabled': True, 'start': start_hm, 'end': end_hm,
                         'period': int(period)} for i in range(7)}
        self.trigger = SimpleNamespace(
            unique_id=SEQ_ID, name='sim', is_activated=True, log_level_debug=False,
            timer_start_time=start_hm, timer_end_time=end_hm, period=float(period),
            output_duration=float(overlap), timer_start_offset=0,
            time_offset_minutes=300, timer_weekday='0,1,2,3,4,5,6',
            resume_on_activate=resume_on_activate,
            timer_schedule=json.dumps({
                'version': 1, 'mode': 'shared',
                'shared': {'enabled': True, 'start': start_hm, 'end': end_hm,
                           'period': int(period)},
                'days': days}),
        )
        self._patch(runtime_db)

    # ---------------------------------------------------------------- 구성

    def output(self, oid):
        if oid in self.outputs:
            return self.outputs[oid]
        o = object.__new__(AbstractOutput)
        o.unique_id = oid
        o.output_name = oid
        o.logger = MagicMock()
        # 실제 on/off 드라이버와 같게 — 출력층은 "지속시간 없는 ON" 을 이 선언으로
        # 가른다. 비워 두면 무기한 ON 이 아무 명령도 내보내지 못하는데, 하네스는 그걸
        # 알려 주지 않는다(옛 코드를 돌려 보다 실제로 그렇게 걸렸다).
        o.OUTPUT_INFORMATION = {'output_types': ['on_off']}
        o.output_type = 'sim_on_off'
        o.output_types = {'on_off': ['sim_on_off']}
        o.output_setup = True
        o.options_channels = {'state_shutdown': {0: 0}, 'command_force': {0: False}}
        now = self._utc_now()
        o.output_states = {0: False}
        o.output_on_until = {0: now}
        o.output_on_duration = {0: False}
        o.output_last_duration = {0: 0}
        o.output_off_until = {0: None}
        o.output_off_triggered = {0: False}
        o.output_time_turned_on = {0: None}
        o.output_session_start = {0: None}
        o.output_session_max = {0: 0}
        o._command_dispatched = {}
        o._started_at_written = {}
        o.is_setup = lambda: True
        o.is_on = lambda output_channel=0, _o=o: bool(_o.output_states.get(output_channel))
        o.output_switch = (lambda state, output_type=None, amount=None, output_channel=0,
                           _o=o: self._switch(_o, state))
        self.outputs[oid] = o
        return o

    def step(self, uid, out, duration, group='', mode='single', enabled=True,
             configured_duration=0.0, lead=0.0, lag=0.0, action_type='output_on_off'):
        """스텝 하나. `duration` 은 스텝 길이(action_duration)."""
        self.output(out)
        opts = {'output': f'{out},0', 'state': 'on', 'duration': configured_duration,
                'sequence_mode': mode, 'action_duration': float(duration),
                'group_name': group, 'enabled': enabled,
                'total_lead': lead, 'total_lag': lag}
        a = SimpleNamespace(unique_id=uid, action_type=action_type,
                            custom_options=json.dumps(opts), do_unique_id=None,
                            position=len(self.actions), function_id=SEQ_ID, name=uid)
        self.actions.append(a)
        return a

    def set_step(self, uid, **changes):
        a = next(x for x in self.actions if x.unique_id == uid)
        opts = json.loads(a.custom_options)
        opts.update(changes)
        a.custom_options = json.dumps(opts)

    def set_window(self, start_hm=None, end_hm=None, day_actions=None):
        sched = json.loads(self.trigger.timer_schedule)
        for i in range(7):
            e = sched['days'][str(i)]
            if start_hm:
                e['start'] = start_hm
            if end_hm:
                e['end'] = end_hm
            if day_actions is not None:
                e['actions'] = dict(day_actions)
        if start_hm:
            sched['shared']['start'] = start_hm
            self.trigger.timer_start_time = start_hm
        if end_hm:
            sched['shared']['end'] = end_hm
            self.trigger.timer_end_time = end_hm
        self.trigger.timer_schedule = json.dumps(sched)

    # ---------------------------------------------------------------- 사건

    def at(self, t_rel, fn):
        """시작 후 `t_rel` 초에 `fn(sim)` 을 부른다(루프 반복 사이에서)."""
        self._scheduled.append((self.t_origin + t_rel, fn))
        self._scheduled.sort(key=lambda x: x[0])

    def refresh(self):
        """설정 저장 → `refresh_daemon_trigger_settings` 가 하는 일."""
        self.inst.refresh_settings()

    def deactivate(self):
        """`controller_deactivate` — DB 를 먼저 끄고 스레드를 멈춘다."""
        self.trigger.is_activated = False
        self._pending_stop = 'deactivate'
        self.inst.running = False

    def reactivate(self):
        """비활성화한 시퀀스를 다시 켠다(`controller_activate` — 새 스레드)."""
        self.trigger.is_activated = True
        self._pending_start = True

    def restart_daemon(self, outputs_off=False):
        """데몬 재시작 — 활성 상태는 그대로 두고 스레드만 멈췄다 다시 띄운다.

        `outputs_off`: 출력의 종료 정책(state_shutdown=off)으로 장치가 꺼진 채
        올라오는 경우.
        """
        self._pending_stop = ('restart', outputs_off)
        self.inst.running = False

    # ---------------------------------------------------------------- 실행

    def run(self, seconds):
        self._stop_at = self.t_origin + seconds
        self.inst = self._new_controller()
        self.inst.initialize_variables()
        while True:
            self.inst.running = True
            self.inst.loop()
            stop, self._pending_stop = self._pending_stop, None
            if stop == 'deactivate':
                self.inst.run_finally()
                if self._idle_until_end():          # 도중에 다시 켜졌다
                    self.inst = self._new_controller()
                    self.inst.initialize_variables()
                    continue
                break
            if isinstance(stop, tuple) and stop[0] == 'restart':
                self.inst.run_finally()
                if stop[1]:
                    for o in self.outputs.values():
                        o.output_states[0] = False
                        o.output_on_duration[0] = False
                self.inst = self._new_controller()
                self.inst.initialize_variables()
                continue
            break
        return self

    def hang(self, seconds):
        """시퀀스가 멈춘 채(루프가 안 돈다) 시간만 흐른다 — 안전 타이머 확인용."""
        end = self.clock.t + seconds
        while self.clock.t < end:
            self._advance(0.25, drive_loop=False)
        return self

    # ---------------------------------------------------------------- 조회

    def device_commands(self):
        """장치로 나간 명령과 출력층 자동 OFF 만(ON/OFF/AUTO_OFF)."""
        return [(round(t), o, k) for t, o, k in self.events
                if k in ('ON', 'OFF', 'AUTO_OFF')]

    def timeline(self):
        return [(round(t), o, k) for t, o, k in self.events]

    def is_on(self, oid):
        return bool(self.outputs[oid].output_states[0])

    # ---------------------------------------------------------------- 내부

    def _utc_now(self):
        return datetime.fromtimestamp(self.clock.t, timezone.utc)

    def _rel(self):
        return self.clock.t - self.t_origin

    def _switch(self, out, state):
        out.output_states[0] = (state == 'on')
        kind = 'AUTO_OFF' if (self._auto_flag and state == 'off') else state.upper()
        self.events.append((self._rel(), out.unique_id, kind))
        return 0, 'ok'

    def _command(self, oid, state, amount, additional_options):
        out = self.output(oid)
        n_before = len(self.events)
        ret = out.output_on_off(state, output_channel=0, output_type='sec',
                                amount=amount or 0.0,
                                additional_options=additional_options)
        if state == 'on' and len(self.events) == n_before:
            renew = bool((additional_options or {}).get('renew_session'))
            self.events.append((self._rel(), oid, 'RENEW' if renew else 'EXTEND'))
        return ret

    def _auto_off_tick(self):
        """`controller_output.loop()` 의 자동 OFF 조건 그대로."""
        now = self._utc_now()
        for oid, o in self.outputs.items():
            until = o.output_on_until.get(0)
            if (until is not None and until < now and o.output_on_duration[0]
                    and not o.output_off_triggered[0]):
                o.output_off_triggered[0] = True
                self._auto_flag = True
                try:
                    o.output_on_off('off', output_channel=0)
                finally:
                    self._auto_flag = False

    def _advance(self, dt, drive_loop=True):
        self.clock.t += dt
        self._auto_off_tick()
        while self._scheduled and self._scheduled[0][0] <= self.clock.t:
            _, fn = self._scheduled.pop(0)
            fn(self)
        if drive_loop and self.inst is not None and self.clock.t >= self._stop_at:
            self.inst.running = False

    def _idle_until_end(self):
        """비활성 동안 시간만 흐른다. 도중에 다시 켜지면 True."""
        while self.clock.t < self._stop_at:
            self._advance(0.25, drive_loop=False)
            if self._pending_start:
                self._pending_start = False
                return True
        return False

    def _new_controller(self):
        inst = object.__new__(seq_mod.SequenceTriggerController)
        inst.unique_id = SEQ_ID
        inst.ready = threading.Event()
        inst.control = _FakeControl(self)
        inst.cycle_start_time = None
        inst._fresh_activation = False
        inst._had_persisted_cycle = False
        inst._handover = {}
        inst._out_key_cache = {}
        inst.activation_timestamp = 0
        inst.current_schedule = []
        inst.active_actions = set()
        inst._close_grace_started = None
        inst._runt_logged_start = None
        inst._skip_logged_start = None
        inst.all_actions_cache = []
        inst._chan_idx_cache = {}
        inst.logger = MagicMock()
        inst.running = False
        return inst

    def _fake_db(self, table, unique_id=None, entry=None, **kw):
        if table is Trigger:
            return self.trigger
        if table is Actions:
            if unique_id is not None:
                return next((a for a in self.actions if a.unique_id == unique_id), None)
            return _Query(self.actions)
        return _Query([])

    def _trigger_action(self, dict_actions, action_id, value=None, **kw):
        """`utils.actions.trigger_action` 대역 — 진짜 액션 모듈의 run_action 을 부른다."""
        a = next(x for x in self.actions if x.unique_id == action_id)
        opts = json.loads(a.custom_options)
        mod = object.__new__(action_mod.ActionModule)
        mod.logger = MagicMock()
        mod.control = _FakeControl(self)
        mod.output_device_id, mod.output_channel_id = opts['output'].split(',')
        mod.state = opts.get('state', 'on')
        mod.duration = opts.get('duration', 0.0)
        mod.get_output_channel_from_channel_id = lambda cid: 0
        return mod.run_action(dict(value or {}))

    def _patch(self, runtime_db):
        mp = self.mp
        mp.setattr(seq_mod, 'time', _FakeTime(self))
        mp.setattr(weekly_mod, 'datetime', _fake_datetime(self.clock))
        mp.setattr(base_output_mod, 'utc_now', self._utc_now)
        # influx 기록 스레드만 막는다. `threading` 모듈 자체를 고치면 테스트
        # 러너까지 영향을 받으므로 base_output 의 이름만 갈아 끼운다.
        mp.setattr(base_output_mod, 'threading', SimpleNamespace(Thread=MagicMock()))
        mp.setattr(seq_mod, 'db_retrieve_table_daemon', self._fake_db)
        mp.setattr(seq_mod, 'get_device_tz', lambda *a, **kw: 'UTC')
        mp.setattr(seq_mod, 'parse_action_information', lambda: {})
        mp.setattr(seq_mod, 'trigger_action', self._trigger_action)
        mp.setattr(seq_mod, 'AOT_DB_PATH', runtime_db)
        mp.setattr(action_mod, 'db_retrieve_table_daemon',
                   lambda *a, **kw: SimpleNamespace(name='sim-output'))
        mp.setattr(action_mod, 'run_in_thread',
                   lambda fn, args=(), kwargs=None: fn(*args, **(kwargs or {})))
