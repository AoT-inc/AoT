# coding=utf-8
"""시퀀스 시나리오 표 — 상황마다 **출력에 나가야 할 명령열**을 고정한다.

## 왜 이 파일이 있나

시퀀스 결함은 지금까지 하나가 나올 때마다 그 경우만 테스트로 막아 왔다. 그런데
결함의 절반은 **고친 것이 다른 경우를 깨뜨린 것**이었다(재개 기능 → 비활성 시퀀스가
밸브를 엶, 격자 앵커링 → 활성화 직후 몇 시간 건너뜀). 경우마다 따로 막으면 서로를
보지 못한다.

그래서 **한 표에** 모든 상황을 두고, 각 상황에서 장치로 나간 명령을 통째로 비교한다.
컨트롤러 구조를 바꿀 때(정본 하나로 · 상태를 루프 스레드 하나만 바꾸게) 이 표가
그대로면 동작이 같다는 뜻이다.

하네스는 `sequence_sim.py` — 진짜 루프·진짜 출력층·진짜 액션 모듈을 가짜 시계로
돌린다(무엇이 진짜이고 가짜인지는 그 파일 머리말).

## 표 읽는 법

`(경과초, 출력, 종류)` — ON/OFF 는 장치로 나간 명령, AUTO_OFF 는 출력층 타이머가
스스로 끈 것, RENEW 는 장치 명령 없이 타이머만 갱신한 이어받기다. 기본 설정은
창 06:00~07:00(UTC), 주기 600초, 스텝 a(V1)·b(V2) 각 300초.

**기대값은 현재 동작을 받아 적은 것이 아니다.** 하나씩 따져 맞다고 판정한 것이고,
그 과정에서 결함 둘이 나왔다(스텝 끝마다 중복 OFF, 재개 재동기화 뒤 중복 OFF).
기대값을 바꿔야 한다면 그것은 **동작 변경**이다 — 왜 바뀌는지 여기에 적을 것.
"""
import os
import tempfile

import pytest
from sqlalchemy import create_engine

from aot.databases.models import FunctionRuntimeState
from aot.tests.sequence_sim import SequenceSim

H6 = 6 * 3600          # 06:00
BASE = dict(start=H6, window=('06:00', '07:00'), period=600)


def _new_runtime_db(paths):
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    engine = create_engine(f'sqlite:///{path}')
    FunctionRuntimeState.__table__.create(bind=engine)
    engine.dispose()
    paths.append(path)
    return f'sqlite:///{path}'


@pytest.fixture
def sim(monkeypatch):
    """시뮬레이터마다 **재개 상태 DB 를 새로** 만든다. 한 테스트에서 둘을 돌리며
    DB 를 공유하면 앞 시나리오가 저장한 사이클을 뒤 시나리오가 "재개" 해 버린다
    (하네스를 만들 때 실제로 그렇게 헷갈렸다)."""
    paths = []

    def make(**overrides):
        return SequenceSim(monkeypatch, _new_runtime_db(paths), **{**BASE, **overrides})
    yield make
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def two_steps(s):
    s.step('a', 'V1', 300)
    s.step('b', 'V2', 300)
    return s


# 두 스텝이 정상으로 한 사이클을 도는 모양. 여러 시나리오의 앞부분이다.
FIRST_HALF = [(0, 'V1', 'ON'), (300, 'V2', 'ON'), (300, 'V1', 'OFF')]
NEXT_CYCLE = [(600, 'V2', 'OFF'), (600, 'V1', 'ON'),
              (900, 'V2', 'ON'), (900, 'V1', 'OFF'),
              (1200, 'V2', 'OFF'), (1200, 'V1', 'ON')]


# ---------------------------------------------------------------------------
# 기본 운전
# ---------------------------------------------------------------------------

def test_s01_two_steps_run_in_turn(sim):
    """스텝 안에서는 다음 밸브를 먼저 열고 앞 밸브를 닫는다(make-before-break).
    사이클 경계에서는 서로 다른 밸브라 끄고 켠다."""
    s = two_steps(sim()).run(1300)
    assert s.timeline() == FIRST_HALF + NEXT_CYCLE


def test_s12_fresh_activation_mid_window_starts_now(sim):
    """창 중간(06:07:30)에 처음 켜면 지금부터 시작한다 — 격자(06:00)에 맞추면
    이번 슬롯의 절반이 이미 지난 것으로 계산된다(2026-09-05 수정)."""
    s = two_steps(sim(start=H6 + 450)).run(700)
    assert s.timeline() == FIRST_HALF + [(600, 'V2', 'OFF'), (600, 'V1', 'ON')]


# ---------------------------------------------------------------------------
# 멈추는 경우 — 전부 즉시 꺼져야 한다
# ---------------------------------------------------------------------------

def test_s02_window_close_stops_the_running_step(sim):
    s = two_steps(sim(window=('06:00', '06:08'))).run(700)
    assert s.timeline() == FIRST_HALF + [(480, 'V2', 'OFF')]


def test_s03_deactivation_stops_the_running_step(sim):
    s = two_steps(sim())
    s.at(450, lambda x: x.deactivate())
    s.run(1300)
    assert s.timeline() == FIRST_HALF + [(450, 'V2', 'OFF')]


def test_s06_moving_the_end_into_the_past_stops_it(sim):
    """최초 신고("종료시간을 바꿔도 멈추지 않는다")."""
    s = two_steps(sim())
    s.at(450, lambda x: (x.set_window(end_hm='06:05'), x.refresh()))
    s.run(1300)
    assert s.timeline() == FIRST_HALF + [(450, 'V2', 'OFF')]


def test_s07_disabling_a_running_step_for_today_closes_its_valve(sim):
    """계획에서 빠진 스텝은 OFF 없이 목록에서만 빠져 밸브가 열린 채 잊혔다
    (최초 코드부터, 2026-09-05 수정). 다음 사이클은 남은 스텝만 돈다."""
    s = two_steps(sim())
    s.at(450, lambda x: (x.set_window(day_actions={'b': False}), x.refresh()))
    s.run(1300)
    assert s.timeline() == FIRST_HALF + [
        (450, 'V2', 'OFF'),
        (600, 'V1', 'ON'), (900, 'V1', 'OFF'), (1200, 'V1', 'ON')]


def test_s13_a_stalled_sequence_is_closed_by_the_output_timer(sim):
    """시퀀스가 멈추면 출력층이 스텝 길이(+여유) 뒤에 스스로 닫는다. 예전에는 스텝
    길이가 출력에 닿지 않아 무기한이었다(최초 코드부터, 2026-09-21 수정)."""
    s = two_steps(sim()).run(100)
    s.hang(400)
    assert s.timeline() == [(0, 'V1', 'ON'), (310, 'V1', 'AUTO_OFF')]


# ---------------------------------------------------------------------------
# 설정 변경 — 바꾼 것만 반영되고, 이미 끝난 것은 다시 켜지지 않는다
# ---------------------------------------------------------------------------

def test_s14_saving_without_changes_sends_nothing(sim):
    """설정 재로드가 저장된 스냅샷으로 방금 끈 밸브를 다시 켜던 경합(2026-09-04)."""
    s = two_steps(sim())
    s.at(450, lambda x: x.refresh())
    s.run(700)
    assert s.timeline() == FIRST_HALF + [(600, 'V2', 'OFF'), (600, 'V1', 'ON')]


def test_s17_shortening_a_finished_step_does_not_rerun_it(sim):
    """a 를 100초로 줄이면 b 가 [100, 400] 으로 앞당겨져 이미 끝났다 — 끈다.
    a 는 이번 사이클에 이미 물을 줬으므로 다시 켜지 않는다."""
    s = two_steps(sim())
    s.at(450, lambda x: (x.set_step('a', action_duration=100.0), x.refresh()))
    s.run(1100)
    assert s.timeline() == FIRST_HALF + [
        (450, 'V2', 'OFF'),
        (600, 'V1', 'ON'), (700, 'V2', 'ON'), (700, 'V1', 'OFF'), (1000, 'V2', 'OFF')]


# ---------------------------------------------------------------------------
# 재시작 · 다시 켜기
# ---------------------------------------------------------------------------

def test_s04_daemon_restart_keeps_the_cycle_without_commands(sim):
    """재시작은 사이클을 이어간다 — 끄고 켜지 않는다."""
    s = two_steps(sim())
    s.at(450, lambda x: x.restart_daemon())
    s.run(1300)
    assert s.timeline() == FIRST_HALF + NEXT_CYCLE


def test_s05_restart_with_outputs_down_reopens_only_the_remainder(sim):
    """종료 정책으로 꺼진 채 올라오면 남은 시간만큼만 다시 켠다. 타이머 끝이 스텝
    끝과 같으면 600초에 AUTO_OFF 와 OFF 가 겹쳤다(이 표를 만들며 발견)."""
    s = two_steps(sim())
    s.at(450, lambda x: x.restart_daemon(outputs_off=True))
    s.run(1300)
    assert s.timeline() == FIRST_HALF + [(450, 'V2', 'ON')] + NEXT_CYCLE


def test_s15_reactivate_with_resume_continues_the_step(sim):
    """"이어서" — 450초에 끄고 500초에 켜면 b 가 남은 100초를 마저 돈다."""
    s = two_steps(sim(resume_on_activate=True))
    s.at(450, lambda x: x.deactivate())
    s.at(500, lambda x: x.reactivate())
    s.run(1300)
    assert s.timeline() == FIRST_HALF + [(450, 'V2', 'OFF'), (500, 'V2', 'ON')] + NEXT_CYCLE


def test_s16_reactivate_from_the_start_begins_a_new_cycle(sim):
    """"처음부터" — 다시 켠 순간부터 새 사이클이다."""
    s = two_steps(sim(resume_on_activate=False))
    s.at(450, lambda x: x.deactivate())
    s.at(500, lambda x: x.reactivate())
    s.run(1300)
    assert s.timeline() == FIRST_HALF + [
        (450, 'V2', 'OFF'),
        (500, 'V1', 'ON'), (800, 'V2', 'ON'), (800, 'V1', 'OFF'),
        (1100, 'V2', 'OFF'), (1100, 'V1', 'ON')]


# ---------------------------------------------------------------------------
# 같은 출력을 이어 쓰는 경우 — 끊지 않는다(2026-09-21)
# ---------------------------------------------------------------------------

def test_s08_single_step_filling_the_period_never_drops(sim):
    """스텝이 주기를 꽉 채우는 설정. 경계마다 끄고 켜던 것이 이어받기만 남는다."""
    s = sim()
    s.step('a', 'V1', 600)
    s.run(1900)
    assert s.device_commands() == [(0, 'V1', 'ON')]
    assert s.timeline() == [(0, 'V1', 'ON'), (600, 'V1', 'RENEW'),
                            (1200, 'V1', 'RENEW'), (1800, 'V1', 'RENEW')]


def test_s09_pump_spanning_the_period_keeps_running(sim):
    s = two_steps(sim())
    s.step('p', 'PUMP', 0, mode='total')
    s.run(1300)
    assert [c for c in s.timeline() if c[1] == 'PUMP'] == [
        (0, 'PUMP', 'ON'), (600, 'PUMP', 'RENEW'), (1200, 'PUMP', 'RENEW')]
    assert [c for c in s.timeline() if c[1] != 'PUMP'] == FIRST_HALF + NEXT_CYCLE


def test_s10_adjacent_groups_sharing_an_output_keep_it_open(sim):
    """그룹 g1·g2 가 액비(LIQ)를 함께 쓴다. 예전에는 경계에서 ON→OFF 순서라
    최종이 꺼졌고 컨트롤러는 켜져 있다고 믿었다."""
    s = sim()
    s.step('g1a', 'V11', 300, group='g1')
    s.step('g1b', 'LIQ', 300, group='g1')
    s.step('g2a', 'V12', 300, group='g2')
    s.step('g2b', 'LIQ', 300, group='g2')
    s.run(1300)
    assert [c for c in s.timeline() if c[1] == 'LIQ'] == [
        (0, 'LIQ', 'ON'), (300, 'LIQ', 'RENEW'), (600, 'LIQ', 'RENEW'),
        (900, 'LIQ', 'RENEW'), (1200, 'LIQ', 'RENEW')]
    assert s.is_on('LIQ')


def test_s11_overlapping_steps_on_one_output(sim):
    """교차 30초로 x[0,330]·y[300,630]. 겹치는 동안 이어받고, 이어 쓸 스텝이
    없을 때만 한 번 끈다."""
    s = sim(period=700, overlap=30)
    s.step('x', 'LIQ', 300)
    s.step('y', 'LIQ', 300)
    s.run(1500)
    assert s.timeline() == [
        (0, 'LIQ', 'ON'), (300, 'LIQ', 'RENEW'), (630, 'LIQ', 'OFF'),
        (700, 'LIQ', 'ON'), (1000, 'LIQ', 'RENEW'), (1330, 'LIQ', 'OFF'),
        (1400, 'LIQ', 'ON')]


# ---------------------------------------------------------------------------
# 표 전체에 걸린 불변식
# ---------------------------------------------------------------------------

def test_no_scenario_sends_off_and_on_to_one_output_at_the_same_moment(sim):
    """같은 출력에 같은 순간 OFF 와 ON(또는 AUTO_OFF 와 OFF)이 함께 나가면 안 된다.
    펄스 밸브는 닫는 중에 여는 명령을 받고, 중복 OFF 는 링크를 낭비한다."""
    cases = []
    s = two_steps(sim()); s.step('p', 'PUMP', 0, mode='total'); cases.append(s.run(1300))
    s = sim(); s.step('a', 'V1', 600); cases.append(s.run(1900))
    s = two_steps(sim()); s.at(450, lambda x: x.restart_daemon(outputs_off=True))
    cases.append(s.run(1300))
    for s in cases:
        seen = {}
        for t, out, kind in s.device_commands():
            seen.setdefault((t, out), []).append(kind)
        clashes = {k: v for k, v in seen.items() if len(v) > 1}
        assert not clashes, f'같은 순간 같은 출력에 명령이 겹쳤다: {clashes}'
