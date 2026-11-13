# coding=utf-8
"""S5 — 시간대 해석 호출부(get_device_tz·resolve_location_tz·system_tz·get_timezone_name → tz_of).

이전 전후로 값이 같은지, 장치가 농장과 다른 시간대(America/New_York 서머타임 경계,
Asia/Kolkata)일 때 장치 위치 기준인지, 그리고 의도된 한 가지 변화
(`_facility_local_now` 가 시설 시간대를 못 풀 때 서버 시계 대신 폴백 사슬로 물러난다)를 고정한다.
운영 DB 는 쓰지 않는다.
"""
import ast
import json
import os
import tempfile
import time
from datetime import datetime, timezone

import pytest
import pytz

from aot.tests.test_timekit_no_app_context import SEED, _run
from aot.utils import timekit as tk
from aot.utils.timekit import FARM, tz_of

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

DST_BEFORE = datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc)   # 뉴욕 -05:00
DST_AFTER = datetime(2026, 3, 8, 7, 0, tzinfo=timezone.utc)     # 뉴욕 -04:00


@pytest.fixture
def ny_farm(monkeypatch):
    """농장 = America/New_York, 장치 'dev-kolkata' = Asia/Kolkata, 그 밖의 id 는 못 찾음."""
    monkeypatch.setattr(tk, '_system_tz_name', lambda: 'America/New_York')
    monkeypatch.setattr(tk, '_db_row', lambda *a, **k: None)
    monkeypatch.setattr(tk, '_db_first', lambda *a, **k: (None, None))
    monkeypatch.setattr(
        tk, '_resolve',
        (lambda orig: lambda where, cache=None:
         (pytz.timezone('Asia/Kolkata'), 'device') if where == 'dev-kolkata' else orig(where, cache)
         )(tk._resolve))


# ── 해석 입구 ─────────────────────────────────────────────────────────────────
def test_none_and_unknown_resolve_to_farm(ny_farm):
    for target in ('no-such-id', None, 'none'):
        assert tz_of(target) == tz_of(FARM)
    assert str(tz_of(FARM)) == 'America/New_York'


def test_device_clock_follows_device_not_farm(ny_farm):
    assert DST_AFTER.astimezone(tz_of('dev-kolkata')).isoformat() == '2026-03-08T12:30:00+05:30'
    assert DST_BEFORE.astimezone(tz_of(FARM)).isoformat() == '2026-03-08T01:59:00-05:00'
    assert DST_AFTER.astimezone(tz_of(FARM)).isoformat() == '2026-03-08T03:00:00-04:00'
    assert tz_of('no-such-id') == tz_of(FARM)          # 못 찾으면 농장


def test_anchor_source_vocabulary_is_unchanged(ny_farm):
    """예약 앵커의 출처 어휘는 'device'|'system' 둘뿐이다(저장 값) — 옛 래퍼와 같은 말."""
    from aot.tools.data_tools.schedule import ScheduleToolsMixin
    for target in ('dev-kolkata', 'no-such-id', None):
        tz, name, src = ScheduleToolsMixin._resolve_schedule_anchor(target)
        assert tz == tz_of(target) and src in ('device', 'system')
        assert name == str(tz)
    assert ScheduleToolsMixin._resolve_schedule_anchor('dev-kolkata')[2] == 'device'
    assert ScheduleToolsMixin._resolve_schedule_anchor('no-such-id')[2] == 'system'


# ── 장치 쪽 소비처: 장치 위치 기준 ────────────────────────────────────────────
def test_lorawan_scheduler_uses_device_clock(ny_farm, monkeypatch):
    import aot.functions.lorawan_class_scheduler as mod
    sched = object.__new__(mod.CustomModule)
    sched.unique_id = 'dev-kolkata'
    monkeypatch.setattr(tk, 'utc_now', lambda: DST_AFTER)
    monkeypatch.setattr(mod, 'utc_now', lambda: DST_AFTER)
    assert sched._local_tz() == pytz.timezone('Asia/Kolkata')
    assert sched._local_now().isoformat() == '2026-03-08T12:30:00+05:30'


def test_method_wallclock_uses_target_location(ny_farm):
    from aot.utils.method import AbstractMethod
    m = object.__new__(AbstractMethod)
    m.target_id = 'dev-kolkata'
    assert m.to_local_wallclock(DST_AFTER) == datetime(2026, 3, 8, 12, 30)


# ── 의도된 변화: _facility_local_now 의 폴백 ─────────────────────────────────
def _coordinator(fac_tz):
    from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import HelpersMixin

    class Fake(HelpersMixin):
        def __init__(self):
            pass

        def _get_facility_tz(self):
            return fac_tz
    return Fake()


def test_facility_clock_when_tz_resolves_is_unchanged(ny_farm, monkeypatch):
    monkeypatch.setattr(tk, 'utc_now', lambda: DST_BEFORE)
    assert _coordinator(pytz.timezone('Asia/Kolkata'))._facility_local_now().isoformat() \
        == '2026-03-08T12:29:00+05:30'
    monkeypatch.setattr(tk, 'utc_now', lambda: DST_AFTER)
    assert _coordinator(pytz.timezone('America/New_York'))._facility_local_now().isoformat() \
        == '2026-03-08T03:00:00-04:00'


def test_facility_clock_unresolved_falls_back_to_farm_not_server_clock(ny_farm, monkeypatch):
    """시설 tz 를 못 풀면 예전엔 서버 시계(naive). 이제 농장 시각(aware) — 서버 TZ 와 무관."""
    monkeypatch.setenv('TZ', 'Asia/Seoul')
    time.tzset()
    try:
        monkeypatch.setattr(tk, 'utc_now', lambda: DST_AFTER)
        now = _coordinator(None)._facility_local_now()
        assert now.isoformat() == '2026-03-08T03:00:00-04:00'     # 농장(뉴욕)
        assert now.tzinfo is not None
    finally:
        monkeypatch.undo()
        time.tzset()


def test_facility_clock_same_as_old_when_container_tz_equals_farm(monkeypatch):
    """평범한 설치(컨테이너 TZ = 농장): 새 값과 옛 값(datetime.now())의 벽시계가 같다."""
    monkeypatch.setenv('TZ', 'Asia/Seoul')
    time.tzset()
    try:
        monkeypatch.setattr(tk, '_system_tz_name', lambda: 'Asia/Seoul')
        new = _coordinator(None)._facility_local_now()
        old = datetime.now()
        assert abs((new.replace(tzinfo=None) - old).total_seconds()) < 5
    finally:
        monkeypatch.undo()
        time.tzset()


def test_facility_clock_unresolved_and_no_farm_is_utc(monkeypatch):
    monkeypatch.setattr(tk, '_system_tz_name', lambda: None)
    monkeypatch.setattr(tk, 'utc_now', lambda: DST_AFTER)
    now = _coordinator(None)._facility_local_now()
    assert now.utcoffset().total_seconds() == 0
    assert (now.hour, now.minute) == (7, 0)


def test_night_window_decisions_use_the_resolved_clock(ny_farm, monkeypatch):
    """운전 시간대 판정이 시설 시각(뉴욕 03:00)을 본다 — 06:00~20:00 창 밖."""
    c = _coordinator(None)
    c.time_start, c.time_end = '06:00', '20:00'
    c._get_time_window = lambda: ('06:00', '20:00')
    monkeypatch.setattr(tk, 'utc_now', lambda: DST_AFTER)
    assert c._in_time_window() is False


# ── 옛 입구가 소스에 남지 않았다 ──────────────────────────────────────────────
_OLD = {'get_device_tz', 'resolve_location_tz', 'resolve_location_tz_and_source',
        'system_tz', 'get_timezone_name', 'location_iso', 'to_device_tz', 'device_tz_name'}
_DEFINERS = {'aot/utils/device_tz.py', 'aot/utils/timekit.py', 'aot/utils/time_utils.py',
             'aot/scripts/check_time_rules.py'}


def test_no_source_file_calls_or_imports_the_old_resolvers():
    offenders = []
    for root, _dirs, files in os.walk(os.path.join(REPO, 'aot')):
        if os.sep + 'tests' in root or 'node_modules' in root:
            continue
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, REPO).replace(os.sep, '/')
            if rel in _DEFINERS:
                continue
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and any(a.name in _OLD for a in n.names):
                    offenders.append(f'{rel}:{n.lineno}')
                elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _OLD:
                    offenders.append(f'{rel}:{n.lineno}')
    assert not offenders, offenders


# ── 앱 컨텍스트 없는 프로세스(데몬) ───────────────────────────────────────────
PROBE = r'''
import json
from flask import has_app_context
from aot.utils import timekit as tk
assert not has_app_context()
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import HelpersMixin
import aot.functions.lorawan_class_scheduler as lw

class Fake(HelpersMixin):
    def __init__(self): pass
    def _get_facility_tz(self): return None
sched = object.__new__(lw.CustomModule)
sched.unique_id = 'dev-kolkata'
print(json.dumps({
    'tz': str(tk.tz_of('dev-kolkata')),
    'lorawan_off': sched._local_now().isoformat()[-6:],
    'facility_off': Fake()._facility_local_now().isoformat()[-6:],
    'farm': str(tk.tz_of(tk.FARM)),
}))
'''


def test_daemon_like_process_resolves_device_and_falls_back_to_farm():
    with tempfile.TemporaryDirectory(prefix='aot-s5-') as d:
        assert _run(SEED, d).returncode == 0
        r = _run(PROBE, d)
        assert r.returncode == 0, r.stderr[-2000:]
        out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out['tz'] == 'Asia/Kolkata'
    assert out['lorawan_off'] == '+05:30'               # 농장(뉴욕)으로 뭉개지지 않는다
    assert out['farm'] == 'America/New_York'
    assert out['facility_off'] in ('-04:00', '-05:00')  # 시설 tz 불명 → 농장(뉴욕)
