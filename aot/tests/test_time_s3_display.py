# coding=utf-8
"""S3 — 표시·내보내기 호출부를 새 입구로 옮긴 뒤에도 값이 같다.

농장 시계(FARM)와 보는 사람 시계(VIEWER)가 구분되고, 농장이 뉴욕일 때(서머타임
경계 포함)에도 옛 계산(pytz 직접)과 같은 결과인지 고정한다. DB 는 쓰지 않는다.
"""
import ast
import pathlib
import sys
from datetime import datetime, timezone
from unittest import mock

import pytest
import pytz

from aot.utils import timekit as tk
from aot.utils.timekit import FARM, VIEWER, to_tz, tz_of, utc_now

NY = pytz.timezone('America/New_York')
TOKYO = pytz.timezone('Asia/Tokyo')
# 2026 미국 서머타임: 3/8 02:00 EST(=07:00Z) 시작, 11/1 02:00 EDT(=06:00Z) 종료
BOUNDARY = [
    datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc),
    datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc),
    datetime(2026, 11, 1, 5, 59, tzinfo=timezone.utc),
    datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc),
    datetime(2026, 7, 1, 0, 0),          # naive = UTC
]


@pytest.fixture
def ny_farm_tokyo_viewer(monkeypatch):
    monkeypatch.setattr(tk, '_system_tz_name', lambda: 'America/New_York')
    monkeypatch.setattr(tk, '_db_row', lambda *a, **k: None)
    monkeypatch.setattr(tk, '_db_first', lambda *a, **k: (None, None))
    user = mock.Mock(is_authenticated=True, timezone='Asia/Tokyo')
    with mock.patch('flask_login.current_user', user):
        yield


def _old_farm(dt):          # 옛 to_local 의 뜻: 농장 시계
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(NY)


@pytest.mark.parametrize('dt', BOUNDARY)
def test_farm_clock_matches_old_to_local(ny_farm_tokyo_viewer, dt):
    new = to_tz(dt, FARM)
    old = _old_farm(dt)
    assert new == old and new.utcoffset() == old.utcoffset()
    assert new.strftime('%Y-%m-%d %H:%M:%S %Z') == old.strftime('%Y-%m-%d %H:%M:%S %Z')


def test_farm_and_viewer_are_different_clocks(ny_farm_tokyo_viewer):
    x = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert to_tz(x, FARM).hour == 20 and to_tz(x, VIEWER).hour == 9
    assert tz_of(VIEWER).zone == 'Asia/Tokyo' and tz_of(FARM).zone == 'America/New_York'


def test_notes_report_uses_viewer_clock(ny_farm_tokyo_viewer):
    x = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert to_tz(x, VIEWER).hour == 9
    assert to_tz(utc_now(), VIEWER).tzinfo.zone == 'Asia/Tokyo'




def test_notes_wall_clock_viewer_and_place(ny_farm_tokyo_viewer):
    from aot.aot_flask.utils import utils_notes as n
    x = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert n.utc_to_wall(x) == datetime(2026, 7, 1, 9, 0)           # 보는 사람
    assert n.utc_to_wall(x, 'Asia/Seoul') == datetime(2026, 7, 1, 9, 0)   # 장소(이름도 시계)
    assert n._wall_tz(None).zone == 'Asia/Tokyo'
    assert n.utc_to_wall(None) is None


def test_utc_to_local_time_label_is_unchanged(ny_farm_tokyo_viewer):
    from aot.aot_flask.utils.utils_general import utc_to_local_time
    assert utc_to_local_time(datetime(2026, 7, 1, tzinfo=timezone.utc)) == '2026-07-01 09:00:00 (UTC+09:00)'
    assert utc_to_local_time(None) == ''


_MIGRATED = ('aot/aot_flask/routes_admin.py', 'aot/aot_flask/utils/utils_export.py',
             'aot/aot_flask/routes_page.py', 'aot/ai/services/ai_agent_service.py',
             'aot/ai/services/ai_summary_service.py', 'aot/aot_flask/routes_password_reset.py',
             'aot/aot_flask/routes_authentication.py', 'aot/aot_flask/routes_general.py')


@pytest.mark.parametrize('rel', _MIGRATED)
def test_migrated_files_no_longer_import_old_display_entries(rel):
    root = pathlib.Path(__file__).resolve().parents[2]
    tree = ast.parse((root / rel).read_text(encoding='utf-8'))
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == 'aot.utils.time_utils':
            assert not {a.name for a in n.names} & {'to_local', 'get_local_now'}, rel
