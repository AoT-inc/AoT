# coding=utf-8
"""`refresh_settings()`가 살아 있는 사이클을 재개(resume)하지 않는가.

## 왜 이 테스트가 있나

`initialize_variables()`는 두 자리에서 불린다 — 스레드가 갓 시작할 때(`run()`,
데몬 기동/재활성화)와, 이미 돌고 있는 스레드의 설정을 다시 읽을 때
(`refresh_settings()`, 위젯 저장·요일별 시간휠 저장이 부르는
`refresh_daemon_trigger_settings` RPC). 두 경우 다 `is_activated`가 True이면
`_load_runtime_state()`를 불러 **DB에 저장된 사이클 스냅샷**으로
`self.active_actions`/`self.cycle_start_time`를 덮어썼다.

첫 번째 경우(진짜 기동)는 맞다 — 데몬이 재시작됐으니 남은 시간을 이어가려면
저장된 스냅샷이 필요하다. 그런데 두 번째 경우(이미 살아 있는 스레드)는 스냅샷이
필요 없다 — 그 스레드 자신의 `self.active_actions`가 이미 정본이고, DB 스냅샷은
그 스레드 자신이 마지막으로 저장한 것일 뿐이다. 문제는 **그 저장이 매 ON/OFF
전환마다 일어난다는 것**이다 — `loop()` 스레드가 `stop_all_active()`로 스텝을
하나씩 끄면서 매번 `_save_runtime_state()`를 부르는 바로 그 순간, 다른 스레드
(Pyro5 RPC 핸들러)에서 같은 인스턴스의 `refresh_settings()`가 동시에 돌면
**아직 저장이 끝나지 않은, 방금 끈 스텝이 여전히 active로 남은 스냅샷**을 읽을
수 있다. `_resync_after_resume()`는 그 스냅샷을 믿고 실제 장치 상태(막 꺼짐)를
"재시작으로 꺼졌다"고 오인해 **남은 시간만큼 다시 켠다**.

실측(로컬 도커, 2026-09-04 20:20:38): 창이 막 닫혀 `stop_all_active()`가 밸브
2개(v311, v312)를 끄는 바로 그 순간 위젯의 요일별 시간휠 저장이 쏜
`refresh_daemon_trigger_settings` RPC가 겹쳐, 두 밸브 모두 "재개했으나 출력이
꺼져 있습니다 … 남은 1162초만큼 다시 켭니다"로 다시 열렸다. 사용자 보고
("종료 시간을 바꿔도/비활성화해도 작동이 멈추지 않는다")와 정확히 일치한다.

고친 형태: `initialize_variables(cold_start=False)`(refresh_settings 전용)는
`is_activated`가 True여도 `_load_runtime_state()`를 건너뛴다 — 살아 있는
스레드의 라이브 상태를 낡은 스냅샷으로 덮어쓸 이유가 없다.
"""
from unittest.mock import MagicMock

import pytest

import aot.controllers.controller_trigger_sequence as seq_mod


class _Trigger:
    def __init__(self, is_activated=True):
        self.is_activated = is_activated
        self.log_level_debug = False
        self.timer_start_time = '00:00'
        self.timer_end_time = '23:59'
        self.period = 3600.0
        self.output_duration = 0.0
        self.timer_start_offset = 0.0
        self.time_offset_minutes = 300
        self.timer_weekday = ''
        self.timer_schedule = None


def make_controller(monkeypatch, trigger):
    """`initialize_variables()`가 실제로 도는, DB 의존만 걷어낸 인스턴스."""
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'seq-refresh-race-test'
    inst.logger = MagicMock()
    inst.ready = MagicMock()
    inst.cycle_start_time = 12345.0
    inst.active_actions = {'act-live-1', 'act-live-2'}
    inst.current_schedule = []
    inst.all_actions_cache = []

    inst._load_runtime_state = MagicMock()

    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon',
                        lambda *a, **kw: trigger)
    monkeypatch.setattr(seq_mod, 'get_device_tz', lambda *a, **kw: 'UTC')
    monkeypatch.setattr(seq_mod, 'parse_action_information', lambda: {})
    monkeypatch.setattr(seq_mod, 'parse_schedule', lambda *a, **kw: None)
    monkeypatch.setattr(
        seq_mod, 'from_legacy',
        lambda *a, **kw: {'mode': 'shared', 'days': {}, 'shared': {}})
    return inst


# ---- initialize_variables(cold_start=...) ----

def test_cold_start_resumes_when_activated(monkeypatch):
    """진짜 기동(run())은 예전처럼 저장된 사이클을 재개한다."""
    inst = make_controller(monkeypatch, _Trigger(is_activated=True))
    inst.initialize_variables()  # cold_start=True 기본값
    inst._load_runtime_state.assert_called_once()


def test_refresh_does_not_resume_even_when_activated(monkeypatch):
    """살아 있는 스레드의 설정 재로드는 활성 상태여도 재개하지 않는다.

    이것이 이 파일의 핵심 회귀다 — 여기가 깨지면 위 실측 사고가 재발한다.
    """
    inst = make_controller(monkeypatch, _Trigger(is_activated=True))
    live_actions_before = set(inst.active_actions)

    inst.initialize_variables(cold_start=False)

    inst._load_runtime_state.assert_not_called()
    # 라이브 상태가 그대로 보존됐는가 — _load_runtime_state 를 건너뛰는 것만으론
    # 부족하다. 아무도 self.active_actions 를 건드리지 않았어야 한다.
    assert inst.active_actions == live_actions_before


def test_refresh_still_skips_when_deactivated(monkeypatch):
    """비활성 + refresh 조합도 여전히 안전하다(기존 가드와 새 가드가 겹쳐도 무해)."""
    inst = make_controller(monkeypatch, _Trigger(is_activated=False))
    inst.initialize_variables(cold_start=False)
    inst._load_runtime_state.assert_not_called()


# ---- _fresh_activation: 방금 켠 것인가 (controller_trigger_sequence._next_cycle_start 의 신호) ----
#
# 별개의 사고: "처음부터 시작" 을 골라 재활성화해도 elapsed 가 0 이 아니라
# 몇 시간으로 시작했다(실측 2026-09-05). 원인은 이 파일 위쪽의 재개-스냅샷
# 경합과 무관한 `_next_cycle_start()`의 격자 앵커링이었다 — 그것을 막는
# 신호가 `_fresh_activation` 이고, 여기서는 `initialize_variables()` 가 그
# 신호를 올바른 조건에서만 세우는지를 본다(`_next_cycle_start` 자체의 동작은
# test_trigger_sequence_cycle_grid.py 가 검증한다).

def test_cold_start_without_restored_cycle_marks_fresh_activation(monkeypatch):
    """복원할 사이클이 없는 진짜 콜드 스타트 — 다음 사이클은 지금부터."""
    inst = make_controller(monkeypatch, _Trigger(is_activated=True))
    inst.cycle_start_time = None  # _load_runtime_state 가 목이라 아무것도 복원 안 함

    inst.initialize_variables()  # cold_start=True 기본값

    assert inst._fresh_activation is True


def test_cold_start_with_restored_cycle_is_not_fresh_activation(monkeypatch):
    """데몬 재시작으로 진짜 재개했다면 그 사이클을 이어간다 — 지금부터가 아니다."""
    inst = make_controller(monkeypatch, _Trigger(is_activated=True))
    inst.cycle_start_time = None

    def fake_resume():
        inst.cycle_start_time = 999.0  # _load_runtime_state 가 실제로 복원했다고 가정

    inst._load_runtime_state.side_effect = fake_resume
    inst.initialize_variables()

    assert inst._fresh_activation is False


def test_stale_persisted_cycle_is_not_a_fresh_activation(monkeypatch):
    """데몬이 한 주기 넘게 내려가 있다 올라온 경우 — 복원은 못 해도 '방금 켠 것'이
    아니다. 여기서 지금을 기준으로 잡으면 그날 남은 사이클이 전부 재기동 시각으로
    밀려 격자 앵커링(표류 방지)이 깨진다."""
    inst = make_controller(monkeypatch, _Trigger(is_activated=True))
    inst.cycle_start_time = None

    def stale_row_seen():
        # 낡아서 복원은 포기하지만, 돌던 시퀀스였다는 사실은 남긴다.
        inst._had_persisted_cycle = True

    inst._load_runtime_state.side_effect = stale_row_seen
    inst.initialize_variables()

    assert inst._fresh_activation is False


def test_refresh_never_marks_fresh_activation(monkeypatch):
    """설정 재로드는 창 사이 유휴 상태(cycle_start_time=None)라도 '방금 켠 것'이
    아니다 — 격자 앵커링(표류 방지)이 계속 적용돼야 한다."""
    inst = make_controller(monkeypatch, _Trigger(is_activated=True))
    inst.cycle_start_time = None  # 예: 창과 창 사이라 원래도 None

    inst.initialize_variables(cold_start=False)

    assert inst._fresh_activation is False


# ---- refresh_settings() actually calls cold_start=False ----

def test_refresh_settings_passes_cold_start_false(monkeypatch):
    """`refresh_settings()`가 실제로 `cold_start=False`를 넘기는지 — 이름이나
    기본값이 바뀌어도 이 배선이 깨지면 조용히 되돌아간다."""
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'seq-refresh-race-test'
    inst.logger = MagicMock()
    inst.cycle_start_time = None
    inst.active_weekday = 'stale'
    inst.all_actions_cache = []
    inst.initialize_variables = MagicMock()

    fake_query = MagicMock()
    fake_query.filter.return_value.all.return_value = []
    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon',
                        lambda *a, **kw: fake_query)

    inst.refresh_settings()

    inst.initialize_variables.assert_called_once_with(cold_start=False)
    assert inst.active_weekday is None
