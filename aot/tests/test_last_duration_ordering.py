# coding=utf-8
"""get_last_duration() 회귀 가드 — InfluxDB 목록은 시간순이 아니다.

`read_influxdb_list()` 는 여러 시리즈/테이블의 결과가 이어 붙어 오므로 **정렬을
보장하지 않는다.** 그런데 `get_last_duration()` 은 `data[-1]` 을 "가장 최근" 으로
가정하고 있었다("가장 최근 값 선택 (timestamp 기준)" 이라는 주석까지 달려 있었지만
실제로는 마지막 원소를 집었다).

실측(2026-08-13, 출력 v332): 30일 조회가 아래 순서로 왔다.

    60.0   @ 08-13 09:18:44   ← 진짜 최신
    114.2  @ 08-10 18:55:16
    123.59 @ 08-13 02:26:51   ← data[-1]

그래서 60초를 작동시킨 직후에도 지도 위젯의 '마지막 작동 시간' 이 00:02:03(=123초)
으로 표시됐고, 새로 작동시켜도 값이 바뀌지 않는 것처럼 보였다. 장치마다 증상이
달랐던 이유도 같다 — 우연히 마지막 원소가 최신인 장치는 정상으로 보였다(v322/v331은
맞았고 v332/v312는 틀렸다).

이 테스트는 정렬 가정이 되살아나는 것을 막는다. Influx 도, 앱 컨텍스트도 필요 없다 —
`read_influxdb_list` 를 대신 세워 순서만 흔든다.
"""
import pytest


def _call_with(points, monkeypatch):
    """read_influxdb_list 가 `points` 를 돌려주도록 세우고 get_last_duration 호출."""
    from aot.utils import runtime as rt

    monkeypatch.setattr(rt, 'read_influxdb_list',
                        lambda **kw: list(points), raising=True)
    # 채널/측정 해석은 DB 를 보므로 우회 — 이 테스트의 관심사는 선택 로직뿐이다.
    monkeypatch.setattr(rt, '_resolve_channel_index', lambda *a, **k: 0, raising=False)
    monkeypatch.setattr(rt, 'db_retrieve_table_daemon',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('no db')),
                        raising=False)
    return rt.get_last_duration('dev-1', 0)


def test_picks_max_timestamp_not_last_element(monkeypatch):
    """실측에서 나온 순서 그대로 — 최신(60)을 골라야 한다."""
    points = [
        (1786000724, 60.0),        # 최신
        (1785740116, 114.2002),
        (1785974811, 123.593046),  # data[-1] 이지만 최신이 아니다
    ]
    assert _call_with(points, monkeypatch) == 60


def test_already_sorted_still_works(monkeypatch):
    """정렬돼 온 경우에도 같은 답이어야 한다(수정이 정상 케이스를 깨지 않았는지)."""
    points = [(1785740116, 114.2), (1785974811, 123.5), (1786000724, 60.0)]
    assert _call_with(points, monkeypatch) == 60


def test_single_point(monkeypatch):
    assert _call_with([(1786000724, 42.7)], monkeypatch) == 42


def test_no_data_returns_none(monkeypatch):
    assert _call_with([], monkeypatch) is None


def test_source_does_not_index_last_element():
    """소스에서 data[-1] 가정이 되살아나면 잡는다.

    선택 로직이 다시 '마지막 원소' 로 돌아가는 것은 위 테스트로도 잡히지만, 다른
    측정 후보를 도는 루프에서 슬쩍 재도입되는 경우까지 막기 위해 소스도 본다.
    """
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / 'aot' / 'utils' / 'runtime.py'
    body = src.read_text()
    fn = body[body.index('def get_last_duration'):]
    fn = fn[:fn.index('\ndef ')] if '\ndef ' in fn else fn
    assert not re.search(r'=\s*data\[-1\]', fn), (
        "get_last_duration 이 다시 data[-1] 을 최신으로 가정한다 — "
        "read_influxdb_list 는 시간순을 보장하지 않는다. max(timestamp) 로 고를 것."
    )
    assert 'max(data' in fn, "timestamp 최대값 선택이 사라졌다."


# ── 같은 실수가 '작동 시작 시각' 쪽에도 있었다 ────────────────────────────────
#
# `get_started_at` 도 `data[-1]` 을 최신 ON 시각으로 가정했다. 그래서 방금 켠
# 장치의 '작동 시간' 이 00:00 이 아니라 **1:48:xx 부터** 세기 시작했다 —
# 몇 시간 전 ON 시각에서 경과를 계산했기 때문이다(2026-08-13 사용자 신고).
#
# 실측으로 순서가 뒤섞여 오는 것을 확인했다(v332, output_started_at 13점):
#
#     10:32:06 · 10:56:16 · 11:14:41 ← 즉시 실행 계열
#     09:15:00 · 09:42:00 · 09:58:00 · 11:09:00 · 11:13:00 ← 예약 계열(뒤에 붙는다)
#
# 즉 `data[-1]` = 11:13:00 인데 최신은 11:14:41 이다. 시리즈가 둘 이상이면
# 이어 붙는 순서가 곧 시간순이 아니다.
#
# 고친 자리는 넷이다(같은 코드가 복사돼 있었다):
#   runtime.get_started_at · runtime.read_latest_started_at ·
#   AoT_timer._read_latest_started_at · AoT_timer._read_last_duration


def _started_at_with(points, monkeypatch):
    from aot.utils import runtime as rt
    monkeypatch.setattr(rt, 'read_influxdb_list', lambda **kw: list(points), raising=True)
    monkeypatch.setattr(rt, '_resolve_channel_index', lambda *a, **k: 0, raising=False)
    return rt.get_started_at('dev-1', 0)


def test_started_at_picks_max_timestamp_not_last_element(monkeypatch):
    """실측 순서 그대로 — 11:14:41 을 골라야 한다."""
    points = [
        (1786587281, 1786587281.0),   # 11:14:41 ← 최신
        (1786580100, 1786580100.0),   # 09:15:00
        (1786587180, 1786587180.0),   # 11:13:00 ← data[-1] 이지만 최신이 아니다
    ]
    assert _started_at_with(points, monkeypatch) == 1786587281


def test_started_at_single_point(monkeypatch):
    assert _started_at_with([(1786587281, 1786587281.0)], monkeypatch) == 1786587281


def test_no_data_returns_none_without_daemon(monkeypatch):
    """데이터가 없으면 데몬 폴백을 시도하고, 그것도 실패하면 None."""
    from aot.utils import runtime as rt
    monkeypatch.setattr(rt, 'read_influxdb_list', lambda **kw: [], raising=True)
    monkeypatch.setattr(rt, '_resolve_channel_index', lambda *a, **k: 0, raising=False)
    assert rt.get_started_at('dev-1', 0) is None


def test_no_started_at_reader_indexes_last_element():
    """네 자리 전부 — `data[-1]` 가정이 되살아나면 잡는다.

    복사된 사본이 넷이라 한 곳만 고치면 나머지에서 같은 증상이 다시 난다.
    실행 경로가 달라(위젯 렌더 · 타이머 위젯 · AI 도구) 단위 테스트로 전부
    덮기 어렵기 때문에 소스를 본다.
    """
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / 'aot'
    targets = [
        (root / 'utils' / 'runtime.py', ['get_started_at', 'read_latest_started_at']),
        (root / 'widgets' / 'AoT_timer.py',
         ['_read_latest_started_at', '_read_last_duration']),
    ]
    for path, funcs in targets:
        body = path.read_text()
        for fn in funcs:
            marker = 'def %s' % fn
            assert marker in body, '%s 에 %s 가 없다 — 이름이 바뀌면 이 가드가 조용히 통과한다' % (path.name, fn)
            src = body[body.index(marker):]
            nxt = re.search(r'\ndef ', src)
            src = src[:nxt.start()] if nxt else src
            code = '\n'.join(l for l in src.splitlines() if not l.strip().startswith('#'))
            assert not re.search(r'=\s*data\[-1\]', code), (
                '%s.%s 가 다시 data[-1] 을 최신으로 가정한다 — '
                'read_influxdb_list 는 시간순을 보장하지 않는다.' % (path.name, fn))
