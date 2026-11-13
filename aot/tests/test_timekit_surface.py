# coding=utf-8
"""timekit 표면 고정 — 공개 입구와 보조의 합집합이 `__all__` 이다."""
from aot.utils import timekit


def test_all_is_entries_plus_helpers():
    assert set(timekit.__all__) == set(timekit.PUBLIC_ENTRIES) | set(timekit.HELPERS)


def test_no_duplicates_and_disjoint():
    assert len(timekit.__all__) == len(set(timekit.__all__))
    assert not set(timekit.PUBLIC_ENTRIES) & set(timekit.HELPERS)


def test_public_entries_are_the_designed_ten_plus_markers():
    assert set(timekit.PUBLIC_ENTRIES) == {
        'utc_now', 'naive_utc', 'parse_utc', 'resolve_tz', 'tz_of', 'to_tz',
        'iso_utc', 'iso_at', 'wall_to_utc', 'today_at', 'FARM', 'VIEWER'}


def test_every_exported_name_exists():
    for name in timekit.__all__:
        assert hasattr(timekit, name), name
