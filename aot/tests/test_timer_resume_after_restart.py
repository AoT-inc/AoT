# -*- coding: utf-8 -*-
"""타이머가 웹 앱 재시작 뒤 **있어야 할 자리**를 옳게 구하는지.

배경 — 2026-09-18 E2E(L3 C4). 타이머의 반복은 웹 프로세스 안의 작업 스레드가
돌리는데, 재시작 뒤 복구는 시작 전 예약만 다시 걸었다. 돌던 실행은 스레드와 함께
사라져 상태가 "진행 중" 으로 굳고, 반복 모드의 남은 주기는 조용히 사라졌다.

이제 복구가 상태 파일과 지금 시각으로 자리를 구해 그곳부터 잇는다
(`_cyc_resume_point`). 재시작하는 동안 지나간 구간은 건너뛴다.
"""
import os
import sys

sys.path.append(
    os.path.abspath(os.path.join(os.path.realpath(__file__), '../../..')))

from aot.widgets.AoT_timer import _cyc_resume_point  # noqa: E402

S = 1000   # ms


def _state(phase, cycle, end_ms, run=20, rest=10, cycles=3):
    return {'phase': phase, 'current_cycle': cycle, 'next_transition_ms': end_ms,
            'run_sec': run, 'rest_sec': rest, 'target_cycles': cycles}


def test_in_the_middle_of_a_run_it_keeps_the_same_end():
    point = _cyc_resume_point(_state('running', 1, 100 * S), now_ms=88 * S)
    assert point == {'cycle': 1, 'kind': 'run', 'remaining_sec': 12.0}


def test_a_run_that_ended_during_the_restart_moves_into_its_rest():
    # 켜짐은 100s 에 끝났고 쉼(10s)은 110s 까지 — 지금 104s
    point = _cyc_resume_point(_state('running', 1, 100 * S), now_ms=104 * S)
    assert point == {'cycle': 1, 'kind': 'rest', 'remaining_sec': 6.0}


def test_skipping_whole_phases_lands_on_the_right_cycle():
    # 1주기 켜짐 끝 100 → 쉼 끝 110 → 2주기 켜짐 끝 130 → 쉼 끝 140 → 3주기 켜짐 ~160
    point = _cyc_resume_point(_state('running', 1, 100 * S), now_ms=145 * S)
    assert point == {'cycle': 3, 'kind': 'run', 'remaining_sec': 15.0}


def test_resting_continues_the_rest():
    point = _cyc_resume_point(_state('resting', 2, 50 * S), now_ms=47 * S)
    assert point == {'cycle': 2, 'kind': 'rest', 'remaining_sec': 3.0}


def test_everything_finished_during_the_restart_means_nothing_to_resume():
    # 3주기 켜짐 끝이 160s — 그 뒤는 쉼 없이 끝
    assert _cyc_resume_point(_state('running', 1, 100 * S), now_ms=200 * S) is None


def test_the_rest_after_the_last_cycle_is_not_resumed():
    assert _cyc_resume_point(_state('resting', 3, 200 * S), now_ms=195 * S) is None


def test_a_single_timed_run_that_ended_is_finished():
    st = _state('running', 1, 40 * S, run=40, rest=0, cycles=1)
    assert _cyc_resume_point(st, now_ms=55 * S) is None
    assert _cyc_resume_point(st, now_ms=30 * S) == {
        'cycle': 1, 'kind': 'run', 'remaining_sec': 10.0}


def test_hold_mode_is_held_again():
    st = _state('running', 1, None, run=0, rest=0, cycles=1)
    assert _cyc_resume_point(st, now_ms=10 * S)['kind'] == 'hold'


def test_died_before_switching_on_starts_that_cycle_now():
    point = _cyc_resume_point(_state('initializing', 1, None), now_ms=10 * S)
    assert point == {'cycle': 1, 'kind': 'run', 'remaining_sec': 20.0}
