# coding=utf-8
"""S4 — 직렬화 호출부(serialize_ts·location_iso·api_iso → iso_at·iso_utc)의 값.

농장이 America/New_York(서머타임 경계 포함)이고 장치가 다른 시간대에 있을 때
농장 시각·장치 시각·UTC 가 각각 맞는지, 그리고 옛 location_iso 와 달라진 입력
(빈 문자열·못 읽는 값)의 동작을 고정한다. 운영 DB 는 쓰지 않는다.
"""
import json
import tempfile
from datetime import datetime, timezone

import pytest
import pytz

from aot.tests.test_timekit_no_app_context import PROBE, SEED, _run
from aot.utils import timekit as tk
from aot.utils.timekit import FARM, iso_at, iso_utc

DST_BEFORE = datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)   # -05:00
DST_AFTER = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)     # -04:00


@pytest.fixture
def ny_farm(monkeypatch):
    monkeypatch.setattr(tk, '_system_tz_name', lambda: 'America/New_York')
    monkeypatch.setattr(tk, '_db_row', lambda *a, **k: None)
    monkeypatch.setattr(tk, '_db_first', lambda *a, **k: (None, None))
    monkeypatch.setattr(
        tk, '_resolve',
        (lambda orig: lambda where, cache=None:
         (pytz.timezone('Asia/Kolkata'), 'device') if where == 'dev-kolkata' else orig(where, cache)
         )(tk._resolve))


def test_farm_offset_across_dst(ny_farm):
    assert iso_at(DST_BEFORE, FARM) == '2026-03-08T01:59:00-05:00'
    assert iso_at(DST_AFTER, FARM) == '2026-03-08T03:00:00-04:00'
    assert iso_at(datetime(2026, 3, 8, 7, 0), FARM).endswith('-04:00')   # naive = UTC


def test_device_clock_differs_from_farm(ny_farm):
    assert iso_at(DST_AFTER, 'dev-kolkata') == '2026-03-08T12:30:00+05:30'
    assert iso_at(DST_AFTER, 'no-such-id') == iso_at(DST_AFTER, FARM)   # 못 풀면 농장


def test_iso_utc_is_always_utc(ny_farm):
    assert iso_utc(DST_AFTER) == '2026-03-08T07:00:00+00:00'
    assert iso_utc(datetime(2026, 3, 8, 7, 0)) == '2026-03-08T07:00:00+00:00'
    assert iso_utc(None) is None




def test_epoch_and_iso_string_inputs(ny_farm):
    want = '2026-03-08T03:00:00-04:00'
    assert iso_at(DST_AFTER.timestamp(), FARM) == want
    assert iso_at('2026-03-08T07:00:00Z', FARM) == want


def test_inputs_that_changed_from_location_iso(ny_farm):
    """옛 location_iso: '' → None, 못 읽는 비문자열 → None. iso_at: 입력 그대로.
    호출부는 실제 타임스탬프만 넘기고 결과의 None/'' 로 분기하지 않는다(S4 점검)."""
    assert iso_at(None, FARM) is None
    assert iso_at('', FARM) == ''
    assert iso_at('not a time', FARM) == 'not a time'


def test_no_app_context_process():
    with tempfile.TemporaryDirectory() as d:
        assert _run(SEED, d).returncode == 0
        r = _run(PROBE, d)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out['dev_iso'].endswith('+05:30')
    assert out['farm_iso'].endswith('-04:00')
