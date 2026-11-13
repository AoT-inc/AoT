# coding=utf-8
"""자정을 잇는 창(24:00 → 다음 날 00:00)에서 자정 직전 사이클이 잘리지 않는가.

## 왜 이 테스트가 있나

루프는 연속 경계(`is_continuity_boundary`)에서 사이클을 끊지 않고 이어 가는데,
"남은 창이 한 pass 를 못 담으면 시작하지 않는다"(`_reject_runt`)는 판정은 자정을
창 끝으로 봤다. 그래서 자정 직전 사이클을 거부해 놓고, 자정에 연속 판정으로 같은
격자점의 사이클을 **늦은 자리에서** 이어 켰다 — 2026-11-11 재현: 00:00~24:00 매일,
1시간 주기·50분 스텝, 14:20 에 켬 → 매일 밤 23:20 사이클(50분)이 00:00~00:10
(10분)으로 줄었다. 밤샘 창은 22:00~24:00 + 00:00~02:00 으로만 적을 수 있으므로
그 설정도 같은 길을 지난다.
"""
from datetime import datetime, timezone

from aot.tests.test_sequence_scenarios import sim  # noqa: F401  (fixture)
from aot.utils.weekly_schedule import continuous_window_end_epoch

H = 3600


def _commands_between(s, base, lo, hi):
    """시작 후 `base` 초 기준 하루 안 시각 [lo, hi) 의 명령. (하루 안 초, 출력, 종류)."""
    out = []
    for t, o, k in s.device_commands():
        day_s = (base + t) % 86400
        if lo <= day_s < hi:
            out.append((day_s, o, k))
    return out


def test_last_cycle_before_midnight_runs_whole_when_window_continues(sim):
    base = 14 * H + 20 * 60          # 월 14:20 에 켠다 → 격자 :20
    s = sim(start=base, window=('00:00', '24:00'), period=3600)
    s.step('a', 'V1', 3000)          # 50분
    s.run(12 * H)                    # 화 02:20 까지

    late = _commands_between(s, base, 23 * H, 24 * H)
    early = _commands_between(s, base, 0, 1 * H)
    assert (23 * H + 20 * 60, 'V1', 'ON') in late, late
    assert (10 * 60, 'V1', 'OFF') in early, (
        '자정 직전 사이클이 50분을 다 채우지 못했다', early)
    assert (0, 'V1', 'ON') not in early, (
        '자정에 잘린 사이클을 다시 켰다 — 23:20 사이클이 거부된 것이다', early)


def test_last_cycle_is_still_rejected_when_window_really_closes(sim):
    """다음 날이 00:00 에 열리지 않으면 자정은 진짜 창 끝이다 — 예전 판정 그대로."""
    base = 14 * H + 20 * 60
    s = sim(start=base, window=('06:00', '24:00'), period=3600)
    s.step('a', 'V1', 3000)
    s.run(12 * H)

    late = _commands_between(s, base, 23 * H, 24 * H)
    assert (23 * H + 20 * 60, 'V1', 'ON') not in late, (
        '창이 자정에 닫히는데 한 pass 를 못 담는 사이클을 시작했다', late)


def _sched(days):
    return {'version': 1, 'mode': 'per_day', 'shared': {},
            'days': {str(i): days.get(i, {'enabled': False, 'start': '06:00',
                                           'end': '07:00', 'period': 3600})
                     for i in range(7)}}


def test_overnight_split_window_end_is_next_morning():
    sched = _sched({0: {'enabled': True, 'start': '22:00', 'end': '24:00', 'period': 3600},
                    1: {'enabled': True, 'start': '00:00', 'end': '02:00', 'period': 3600}})
    mon_23 = datetime(2026, 9, 7, 23, 0, tzinfo=timezone.utc).timestamp()
    end = continuous_window_end_epoch(sched, 0, 'UTC', mon_23)
    assert end == datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc).timestamp()


def test_non_continuous_day_keeps_its_own_end():
    sched = _sched({0: {'enabled': True, 'start': '22:00', 'end': '24:00', 'period': 3600},
                    1: {'enabled': True, 'start': '00:30', 'end': '02:00', 'period': 3600}})
    mon_23 = datetime(2026, 9, 7, 23, 0, tzinfo=timezone.utc).timestamp()
    end = continuous_window_end_epoch(sched, 0, 'UTC', mon_23)
    assert end == datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc).timestamp()


def test_continuous_end_across_dst_fall_back():
    """뉴욕 2026-11-01(일) 02:00 EDT→01:00 EST. 토 00:00~24:00 + 일 00:00~03:00 이면
    끝은 일요일 벽시계 03:00 EST = 08:00 UTC 다(25시간짜리 날을 지난다)."""
    sched = _sched({5: {'enabled': True, 'start': '00:00', 'end': '24:00', 'period': 3600},
                    6: {'enabled': True, 'start': '00:00', 'end': '03:00', 'period': 3600}})
    sat_22_local = datetime(2026, 11, 1, 2, 0, tzinfo=timezone.utc).timestamp()  # 토 22:00 EDT
    end = continuous_window_end_epoch(sched, 5, 'America/New_York', sat_22_local)
    assert end == datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc).timestamp()


def test_seoul_overnight_window():
    sched = _sched({2: {'enabled': True, 'start': '21:00', 'end': '24:00', 'period': 3600},
                    3: {'enabled': True, 'start': '00:00', 'end': '05:00', 'period': 3600}})
    wed_22_kst = datetime(2026, 9, 9, 13, 0, tzinfo=timezone.utc).timestamp()  # 수 22:00 KST
    end = continuous_window_end_epoch(sched, 2, 'Asia/Seoul', wed_22_kst)
    assert end == datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc).timestamp()  # 목 05:00 KST
