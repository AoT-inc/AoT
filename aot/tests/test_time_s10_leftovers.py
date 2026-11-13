# coding=utf-8
"""S10 — 가드 예외 정리 중 고친 자리: tz 없는 epoch_of_next_time 은 컨테이너 OS 시계가 아니라 농장 시계."""
from aot.utils import timekit as tk
from aot.utils.system_pi import epoch_of_next_time



def test_no_tz_reads_the_farm_clock_not_the_os_clock(monkeypatch):
    import time
    monkeypatch.setattr(tk, '_system_tz_name', lambda: 'America/New_York')
    got = epoch_of_next_time('09:30:00')
    local = tk.to_tz(tk.parse_utc(got), tk.FARM)
    assert (local.hour, local.minute) == (9, 30)
    assert str(local.tzinfo) == 'America/New_York'
    assert got > time.time() - 1                      # 이미 지났으면 하루 뒤
    assert got - time.time() <= 86400 + 3600


def test_unknown_tz_name_is_unreadable(monkeypatch):
    monkeypatch.setattr(tk, '_system_tz_name', lambda: 'America/New_York')
    assert epoch_of_next_time('09:30:00', tz='Nowhere/Land') is None
