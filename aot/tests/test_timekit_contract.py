# coding=utf-8
"""timekit 계약 시험 — DB 없음 (설계: time_unification_design §6).

로컬 장치는 전부 +09:00 이라 8084 값으로는 준수를 가릴 수 없다. 여기서는 시간대
행렬과 DST 경계에서 입구 10개의 약속을 고정한다. 장소 조회(`_db_row`)와 농장
시계(`_system_tz_name`)는 가짜로 바꾼다.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
import pytz

from aot.utils import timekit as tk

MATRIX = [
    ('America/New_York', None),
    ('Asia/Kolkata', '+05:30'),
    ('Pacific/Auckland', None),
    ('Asia/Seoul', '+09:00'),
    ('UTC', '+00:00'),
]


@pytest.fixture
def farm(monkeypatch):
    """농장 시계를 바꾸고 모든 장소 조회를 빈 손으로 만든다."""
    state = {'name': 'Asia/Seoul'}
    monkeypatch.setattr(tk, '_system_tz_name', lambda: state['name'])
    monkeypatch.setattr(tk, '_db_row', lambda *a, **k: None)
    monkeypatch.setattr(tk, '_db_first', lambda *a, **k: (None, None))
    return state


class _Dev:
    def __init__(self, uid, tzname, source='explicit'):
        self.unique_id = uid
        self.timezone = tzname
        self.tz_source = source
        self.latitude = self.longitude = None


# --- 시간대 행렬 ---------------------------------------------------------
@pytest.mark.parametrize('name,offset', MATRIX)
def test_instant_roundtrip_in_every_zone(name, offset):
    t = datetime(2026, 7, 1, 3, 0, tzinfo=timezone.utc)
    local = tk.to_tz(t, name)
    assert local.utcoffset() is not None
    assert local.astimezone(timezone.utc) == t
    assert tk.iso_at(t, name) == local.isoformat()
    if offset:
        assert tk.iso_at(t, name).endswith(offset)
    # 벽시계로 되돌리면 같은 순간
    assert tk.wall_to_utc(local.replace(tzinfo=None), name) == t


def test_offsets_differ_by_season_for_dst_zones():
    ny = pytz.timezone('America/New_York')
    assert tk.iso_at('2026-01-15T12:00:00Z', ny).endswith('-05:00')
    assert tk.iso_at('2026-07-15T12:00:00Z', ny).endswith('-04:00')
    # 남반구는 반대
    assert tk.iso_at('2026-01-15T12:00:00Z', 'Pacific/Auckland').endswith('+13:00')
    assert tk.iso_at('2026-07-15T12:00:00Z', 'Pacific/Auckland').endswith('+12:00')


# --- DST 경계 ------------------------------------------------------------
def test_dst_gap_nonexistent_wall_time_is_standard_time():
    # 2026-03-08 02:30 NY 는 존재하지 않는다 — 표준시(-05:00)로 읽어 07:30Z.
    assert tk.wall_to_utc('2026-03-08 02:30', 'America/New_York') == \
        datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)


def test_dst_overlap_ambiguous_wall_time_is_second_occurrence():
    # 2026-11-01 01:30 NY 는 두 번 있다 — pytz 기본(is_dst=False)은 두 번째(-05:00).
    assert tk.wall_to_utc('2026-11-01 01:30', 'America/New_York') == \
        datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)


def test_day_length_23_and_25_hours():
    ny = 'America/New_York'
    d = lambda y, m, dd: tk.wall_to_utc(datetime(y, m, dd), ny)  # noqa: E731
    assert d(2026, 3, 9) - d(2026, 3, 8) == timedelta(hours=23)
    assert d(2026, 11, 2) - d(2026, 11, 1) == timedelta(hours=25)
    assert d(2026, 7, 2) - d(2026, 7, 1) == timedelta(hours=24)


def test_midnight_crossing_today_at(farm, monkeypatch):
    # 같은 순간, 다른 날짜: 서울은 이미 다음 날, 뉴욕은 아직 전날.
    monkeypatch.setattr(tk, 'utc_now',
                        lambda: datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc))
    assert tk.today_at('Asia/Seoul') == date(2026, 11, 2)
    assert tk.today_at('America/New_York') == date(2026, 11, 1)
    assert tk.today_at('Pacific/Auckland') == date(2026, 11, 2)
    assert tk.today_at('UTC') == date(2026, 11, 1)


# --- where 전 종류 -------------------------------------------------------
def test_where_tzinfo_and_iana_name(farm):
    assert tk.resolve_tz(pytz.timezone('Asia/Kolkata')) == (pytz.timezone('Asia/Kolkata'), 'explicit')
    assert tk.resolve_tz('Pacific/Auckland')[0].zone == 'Pacific/Auckland'
    assert tk.tz_of(timezone.utc) is timezone.utc


def _placed(monkeypatch, tzname, point=(28.1, 77.1)):
    """장치를 tzname 대지에 놓인 것으로 — 리졸버(`_locate_row`) 결과를 흉내낸다."""
    from types import SimpleNamespace
    monkeypatch.setattr(tk, '_locate_row', lambda row: SimpleNamespace(
        tz=tzname, point=point, basis='device', source='marker'))


@pytest.mark.parametrize('source', ['explicit', 'coords', 'system', 'inherited'])
def test_where_row_non_explicit_cache_is_ignored(farm, source):
    """결정 ①(L4 S3b-tz): 장치 행의 tz 값은 출처가 무엇이든 읽지 않는다 — 자리가 없으면 농장.
    (explicit 핀은 p7_07 이 자리 도형 timezone 으로 승격했다.)"""
    tz, src = tk.resolve_tz(_Dev('d1', 'Asia/Kolkata', source))
    assert tz.zone == 'Asia/Seoul' and src == 'system'


def test_where_row_inherits_tz_from_placement(farm, monkeypatch):
    _placed(monkeypatch, 'Asia/Kolkata')
    tz, src = tk.resolve_tz(_Dev('d2', 'America/New_York', 'system'))
    assert tz.zone == 'Asia/Kolkata' and src == 'inherited'


def test_where_id_found(farm, monkeypatch):
    dev = _Dev('abc-id', 'Asia/Seoul', 'inherited')
    from aot.databases.models import Input
    monkeypatch.setattr(tk, '_db_first',
                        lambda models, uid: (Input, dev) if uid == 'abc-id' else (None, None))
    _placed(monkeypatch, 'America/New_York')
    tz, src = tk.resolve_tz('abc-id')
    assert tz.zone == 'America/New_York' and src == 'inherited'


def test_unknown_id_falls_back_to_farm(farm):
    tz, src = tk.resolve_tz('no-such-id')
    assert tz.zone == 'Asia/Seoul' and src == 'system'


def test_none_bad_iana_and_none_word_are_farm(farm):
    for w in (None, 'none', '', 'Mars/Olympus'):
        tz, src = tk.resolve_tz(w)
        assert (tz.zone, src) == ('Asia/Seoul', 'system'), w


def test_farm_unset_falls_to_utc(farm):
    farm['name'] = None
    assert tk.resolve_tz(None) == (pytz.utc, 'utc')
    assert tk.resolve_tz('no-such-id') == (pytz.utc, 'utc')
    assert tk.iso_at('2026-07-01T00:00:00Z', tk.FARM).endswith('+00:00')


def test_farm_and_viewer(farm, monkeypatch):
    farm['name'] = 'America/New_York'
    assert tk.tz_of(tk.FARM).zone == 'America/New_York'
    # 로그인 사용자가 없으면 VIEWER 는 농장
    assert tk.resolve_tz(tk.VIEWER) == (pytz.timezone('America/New_York'), 'system')

    class U:
        is_authenticated = True
        timezone = 'Asia/Kolkata'

    import flask_login
    monkeypatch.setattr(flask_login, 'current_user', U())
    tz, src = tk.resolve_tz(tk.VIEWER)
    assert tz.zone == 'Asia/Kolkata' and src == 'user'
    U.timezone = None
    assert tk.resolve_tz(tk.VIEWER)[1] == 'system'


def test_user_kwarg_compat(farm):
    class U:
        timezone = 'Pacific/Auckland'
    assert tk.resolve_tz(None, user=U()) [0].zone == 'Pacific/Auckland'


def test_cache_resolves_each_place_once_including_misses(farm, monkeypatch):
    calls = []
    from aot.databases.models import Input
    dev = _Dev('x', 'Asia/Kolkata')

    def fake(models, uid):
        calls.append(uid)
        return (Input, dev) if uid == 'x' else (None, None)

    monkeypatch.setattr(tk, '_db_first', fake)
    cache = {}
    for _ in range(3):
        tk.tz_of('x', cache)
        tk.iso_at('2026-01-01T00:00:00Z', 'x', cache)
        tk.tz_of('missing', cache)          # 못 찾은 것도 다시 묻지 않는다
        tk.iso_at('2026-01-01T00:00:00Z', 'missing', cache)
    assert sorted(calls) == ['missing', 'x']


# --- 개별 입구 -------------------------------------------------------------
def test_naive_utc_and_parse_utc():
    aware = datetime(2026, 7, 1, 9, 0, tzinfo=timezone(timedelta(hours=9)))
    assert tk.naive_utc(aware) == datetime(2026, 7, 1, 0, 0)
    assert tk.naive_utc(None) is None
    assert tk.parse_utc('2026-07-01T09:00:00+09:00') == datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert tk.parse_utc('2026-07-01T09:00:00Z').hour == 9
    assert tk.parse_utc('2026-07-01 09:00').tzinfo == timezone.utc
    assert tk.parse_utc(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        tk.parse_utc('내일')


def test_iso_utc_and_none_passthrough(farm):
    assert tk.iso_utc(None) is None and tk.to_tz(None, 'UTC') is None
    assert tk.iso_at(None, tk.FARM) is None
    assert tk.iso_at('쓰레기', tk.FARM) == '쓰레기'     # 못 읽으면 입력 그대로
    assert tk.iso_utc(datetime(2026, 7, 1, 1, 2, 3)) == '2026-07-01T01:02:03+00:00'


def test_wall_to_utc_offset_means_that_instant():
    assert tk.wall_to_utc('2026-07-01T09:00:00+09:00', 'America/New_York') == \
        datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert tk.wall_to_utc('2026-07-01T00:00:00Z', 'Asia/Seoul').hour == 0
    with pytest.raises(ValueError):
        tk.wall_to_utc('not a time', 'UTC')


def test_utc_now_is_module_global_for_simulation_clock(monkeypatch, farm):
    fixed = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(tk, 'utc_now', lambda: fixed)
    assert tk.today_at('UTC') == date(2030, 1, 1)
