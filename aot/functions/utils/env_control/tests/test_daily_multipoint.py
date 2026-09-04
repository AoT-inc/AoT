# coding=utf-8
"""
P3-5: DailyMultiPointMethod 단위 테스트.

대상:
  - _resolve_points_at: 키프레임 보간, is_endpoint 시간 고정
  - _eval_curve: 선형(corner), Hermite(smooth), 끝점 클램프
  - _hermite_interp: 단조성 (오버슈트 없음)
  - DailyMultiPointMethod.calculate_setpoint: 24h 반복 / 주차 진행
"""

import datetime
import json
import math
import pytest

from aot.utils.method import (
    _resolve_points_at,
    _eval_curve,
    _hermite_interp,
    _migrate_multipoint,
    _resolve_v2_at,
    _interp_weeks,
    DailyMultiPointMethod,
)


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처
# ─────────────────────────────────────────────────────────────────────────────

def _pt(point_id, t_sec, value, smooth=False, is_endpoint=False, keyframes=None):
    return {
        'point_id': point_id,
        't_sec': t_sec,
        'value': value,
        'smooth': smooth,
        'is_endpoint': is_endpoint,
        'keyframes': keyframes or [],
    }


def two_point_linear():
    """0h=0.5, 24h=0.5 (정적 곡선)."""
    return [
        _pt(0, 0,     0.5, is_endpoint=True),
        _pt(1, 86400, 0.5, is_endpoint=True),
    ]


def three_point_linear():
    """0h=0.5, 12h=1.0, 24h=0.5 — corner 선형."""
    return [
        _pt(0, 0,     0.5, is_endpoint=True),
        _pt(1, 43200, 1.0),
        _pt(2, 86400, 0.5, is_endpoint=True),
    ]


def three_point_smooth():
    """0h=0.5, 12h=1.0, 24h=0.5 — smooth Hermite."""
    return [
        _pt(0, 0,     0.5, smooth=True, is_endpoint=True),
        _pt(1, 43200, 1.0, smooth=True),
        _pt(2, 86400, 0.5, smooth=True, is_endpoint=True),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_points_at
# ─────────────────────────────────────────────────────────────────────────────

class TestResolvePointsAt:
    def test_static_point_unchanged(self):
        pts = [_pt(0, 0, 0.8, is_endpoint=True)]
        resolved = _resolve_points_at(pts, weeks_elapsed=5.0)
        assert resolved[0]['value'] == pytest.approx(0.8)

    def test_keyframe_at_week0(self):
        """week=0 기준 그대로."""
        pts = [_pt(0, 21600, 0.6, keyframes=[
            {'week': 0, 't_sec': 21600, 'value': 0.6},
            {'week': 4, 't_sec': 21600, 'value': 1.0},
        ])]
        resolved = _resolve_points_at(pts, 0.0)
        assert resolved[0]['value'] == pytest.approx(0.6)

    def test_keyframe_at_week4(self):
        pts = [_pt(0, 21600, 0.6, keyframes=[
            {'week': 0, 't_sec': 21600, 'value': 0.6},
            {'week': 4, 't_sec': 21600, 'value': 1.0},
        ])]
        resolved = _resolve_points_at(pts, 4.0)
        assert resolved[0]['value'] == pytest.approx(1.0)

    def test_keyframe_midpoint_linear(self):
        """W=2 → (0.6 + 1.0) / 2 = 0.8."""
        pts = [_pt(0, 21600, 0.6, keyframes=[
            {'week': 0, 't_sec': 21600, 'value': 0.6},
            {'week': 4, 't_sec': 21600, 'value': 1.0},
        ])]
        resolved = _resolve_points_at(pts, 2.0)
        assert resolved[0]['value'] == pytest.approx(0.8)

    def test_endpoint_t_sec_fixed(self):
        """is_endpoint=True → 키프레임이 있어도 t_sec 변경 불가."""
        pts = [_pt(0, 0, 0.6, is_endpoint=True, keyframes=[
            {'week': 0, 't_sec': 0,    'value': 0.6},
            {'week': 4, 't_sec': 3600, 'value': 1.0},  # t_sec 변경 시도
        ])]
        resolved = _resolve_points_at(pts, 4.0)
        assert resolved[0]['t_sec'] == 0  # 고정

    def test_beyond_last_keyframe(self):
        """마지막 키프레임 이후 주차 → 최종값 유지."""
        pts = [_pt(0, 21600, 0.6, keyframes=[
            {'week': 0, 't_sec': 21600, 'value': 0.6},
            {'week': 4, 't_sec': 21600, 'value': 1.0},
        ])]
        resolved = _resolve_points_at(pts, 10.0)
        assert resolved[0]['value'] == pytest.approx(1.0)

    def test_sorted_output(self):
        """반환 목록이 t_sec 오름차순으로 정렬된다."""
        pts = [
            _pt(0, 86400, 0.5, is_endpoint=True),
            _pt(1, 0,     0.5, is_endpoint=True),
        ]
        resolved = _resolve_points_at(pts, 0.0)
        assert resolved[0]['t_sec'] <= resolved[1]['t_sec']


# ─────────────────────────────────────────────────────────────────────────────
# _eval_curve — 선형 보간
# ─────────────────────────────────────────────────────────────────────────────

class TestEvalCurveLinear:
    def test_at_start_point(self):
        pts = three_point_linear()
        assert _eval_curve(pts, 0) == pytest.approx(0.5)

    def test_at_end_point(self):
        pts = three_point_linear()
        assert _eval_curve(pts, 86400) == pytest.approx(0.5)

    def test_midpoint(self):
        pts = three_point_linear()
        assert _eval_curve(pts, 43200) == pytest.approx(1.0)

    def test_quarter_point(self):
        """0→12h 중간 = 0.75."""
        pts = three_point_linear()
        assert _eval_curve(pts, 21600) == pytest.approx(0.75)

    def test_clamp_below_zero(self):
        pts = two_point_linear()
        assert _eval_curve(pts, -1000) == pytest.approx(0.5)

    def test_clamp_above_86400(self):
        pts = two_point_linear()
        assert _eval_curve(pts, 90000) == pytest.approx(0.5)

    def test_single_point(self):
        assert _eval_curve([_pt(0, 0, 1.2)], 43200) == pytest.approx(1.2)

    def test_empty_returns_zero(self):
        assert _eval_curve([], 43200) == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# _eval_curve — smooth (Hermite) 단조성 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestEvalCurveHermite:
    def test_no_overshoot_ascending(self):
        """단조 증가 구간에서 오버슈트 없음."""
        pts = [
            _pt(0, 0,     0.5, smooth=True, is_endpoint=True),
            _pt(1, 43200, 1.2, smooth=True),
            _pt(2, 86400, 1.2, smooth=True, is_endpoint=True),
        ]
        values = [_eval_curve(pts, t) for t in range(0, 86401, 1800)]
        assert all(v >= 0.5 - 1e-9 for v in values)
        assert all(v <= 1.2 + 1e-9 for v in values)

    def test_no_overshoot_descending(self):
        """단조 감소 구간에서 오버슈트 없음."""
        pts = [
            _pt(0, 0,     1.2, smooth=True, is_endpoint=True),
            _pt(1, 43200, 0.5, smooth=True),
            _pt(2, 86400, 0.5, smooth=True, is_endpoint=True),
        ]
        values = [_eval_curve(pts, t) for t in range(0, 86401, 1800)]
        assert all(v <= 1.2 + 1e-9 for v in values)
        assert all(v >= 0.5 - 1e-9 for v in values)

    def test_endpoints_exact(self):
        pts = three_point_smooth()
        assert _eval_curve(pts, 0)     == pytest.approx(0.5)
        assert _eval_curve(pts, 86400) == pytest.approx(0.5)

    def test_peak_near_midpoint(self):
        """정점이 12h 근처에 있어야 한다."""
        pts = three_point_smooth()
        values = [(t, _eval_curve(pts, t)) for t in range(0, 86401, 3600)]
        peak_t = max(values, key=lambda x: x[1])[0]
        # 8h~16h 사이에 정점
        assert 8 * 3600 <= peak_t <= 16 * 3600

    def test_non_negative_vpd(self):
        """모든 값이 0 이상 (VPD 물리 하한)."""
        pts = three_point_smooth()
        values = [_eval_curve(pts, t) for t in range(0, 86401, 600)]
        assert all(v >= -1e-9 for v in values)


# ─────────────────────────────────────────────────────────────────────────────
# DailyMultiPointMethod.calculate_setpoint (mock 없이 직접 로직 검증)
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyMultiPointCalculation:
    """_resolve_points_at + _eval_curve 파이프라인 통합 검증."""

    def test_static_curve_noon(self):
        """정오(12h) 값 = 피크 1.0 (linear)."""
        pts = three_point_linear()
        resolved = _resolve_points_at(pts, 0.0)
        val = _eval_curve(resolved, 43200)
        assert val == pytest.approx(1.0)

    def test_weekly_evolution_value(self):
        """W=2에서 값이 W=0과 W=4 사이."""
        pts = [
            _pt(0, 0,     0.5, is_endpoint=True),
            _pt(1, 43200, 0.8, keyframes=[
                {'week': 0, 't_sec': 43200, 'value': 0.8},
                {'week': 4, 't_sec': 43200, 'value': 1.4},
            ]),
            _pt(2, 86400, 0.5, is_endpoint=True),
        ]
        res0 = _resolve_points_at(pts, 0.0)
        res4 = _resolve_points_at(pts, 4.0)
        res2 = _resolve_points_at(pts, 2.0)
        v0 = _eval_curve(res0, 43200)
        v4 = _eval_curve(res4, 43200)
        v2 = _eval_curve(res2, 43200)
        assert v0 < v2 < v4
        assert v2 == pytest.approx(1.1)   # 선형 중간값

    def test_24h_wrap(self):
        """t=0 과 t=86400 에서 같은 값 (닫힌 루프)."""
        pts = three_point_linear()
        resolved = _resolve_points_at(pts, 0.0)
        assert _eval_curve(resolved, 0) == pytest.approx(_eval_curve(resolved, 86400))

    def test_max_12_points_constraint(self):
        """12개 포인트 이상은 시스템 제약 — 값 검증 (제한 자체는 UI 에서 강제)."""
        pts = [_pt(i, i * 7200, float(i) / 11.0) for i in range(12)]
        resolved = _resolve_points_at(pts, 0.0)
        assert len(resolved) == 12


# ─────────────────────────────────────────────────────────────────────────────
# v2 스키마: _migrate_multipoint / _interp_weeks / _resolve_v2_at
# ─────────────────────────────────────────────────────────────────────────────

def _v2_data():
    return {
        'version': 2,
        'weeks': [0, 4],
        'points': [
            {'point_id': 0, 't_sec': 0,     'values': [0.6, 0.9], 'smooth': False, 'is_endpoint': True},
            {'point_id': 1, 't_sec': 43200, 'values': [1.2, 1.5], 'smooth': True,  'is_endpoint': False},
            {'point_id': 2, 't_sec': 86400, 'values': [0.6, 0.9], 'smooth': False, 'is_endpoint': True},
        ],
    }


class TestMigrateMultipoint:
    def test_v3_passthrough(self):
        """이미 v3 인 데이터는 그대로(동일 객체) 반환된다."""
        d = {
            'version': 3,
            'weeks': [0],
            'points': [
                {'point_id': 0, 't_sec': 0, 'values': [0.8], 'smooth': False,
                 'curve': 'linear', 'handle_dt': None, 'handle_dv': None, 'is_endpoint': True},
            ],
        }
        result = _migrate_multipoint(d)
        assert result is d
        assert result['version'] == 3

    def test_v2_upgraded_to_v3(self):
        """v2 데이터는 최신 v3 로 업그레이드된다 (curve/handle 필드 추가).

        _migrate_multipoint 는 v1/v2/v3 어떤 입력이든 항상 v3 로 정규화한다.
        """
        d = _v2_data()
        result = _migrate_multipoint(d)
        assert result['version'] == 3
        # smooth=False → curve='linear', smooth=True → curve='smooth'
        assert result['points'][0]['curve'] == 'linear'   # smooth=False
        assert result['points'][1]['curve'] == 'smooth'   # smooth=True
        # v2 의 values/weeks 는 보존
        assert result['weeks'] == [0, 4]
        assert result['points'][0]['values'] == [0.6, 0.9]
        # 신규 핸들 필드 추가됨
        assert 'handle_dt' in result['points'][0]
        assert 'handle_dv' in result['points'][0]

    def test_v1_no_keyframes(self):
        """v1(keyframes 없음) → v3 로 변환. values[] 배열화 + curve 필드."""
        v1 = {
            'version': 1,
            'points': [
                {'point_id': 0, 't_sec': 0,     'value': 0.5, 'smooth': False, 'is_endpoint': True,  'keyframes': []},
                {'point_id': 1, 't_sec': 86400, 'value': 0.5, 'smooth': False, 'is_endpoint': True,  'keyframes': []},
            ],
        }
        v3 = _migrate_multipoint(v1)
        assert v3['version'] == 3                       # v1 → v2 → v3 일괄 변환
        assert v3['weeks'] == [0]
        assert v3['points'][0]['values'] == [0.5]
        assert v3['points'][1]['values'] == [0.5]
        assert 'keyframes' not in v3['points'][0]        # v1 keyframes 필드 제거
        # v3 신규 필드
        assert v3['points'][0]['curve'] == 'linear'      # smooth=False
        assert v3['points'][0]['handle_dt'] is None

    def test_v1_with_keyframes(self):
        """v1(keyframes 있음) → v3. 주차별 values 배열 구성 + curve 필드."""
        v1 = {
            'version': 1,
            'points': [
                {'point_id': 0, 't_sec': 0, 'value': 0.6, 'smooth': False,
                 'is_endpoint': True, 'keyframes': [{'week': 4, 't_sec': 0, 'value': 0.9}]},
                {'point_id': 1, 't_sec': 86400, 'value': 0.6, 'smooth': True,
                 'is_endpoint': True, 'keyframes': [{'week': 4, 't_sec': 86400, 'value': 0.9}]},
            ],
        }
        v3 = _migrate_multipoint(v1)
        assert v3['version'] == 3
        assert v3['weeks'] == [0, 4]
        assert v3['points'][0]['values'] == [0.6, 0.9]
        assert v3['points'][1]['values'] == [0.6, 0.9]
        # smooth 플래그 → curve 문자열로 변환
        assert v3['points'][0]['curve'] == 'linear'      # smooth=False
        assert v3['points'][1]['curve'] == 'smooth'      # smooth=True


class TestInterpWeeks:
    def test_single_week(self):
        assert _interp_weeks([0], [1.0], 5.0) == pytest.approx(1.0)

    def test_at_first(self):
        assert _interp_weeks([0, 4], [0.6, 0.9], 0.0) == pytest.approx(0.6)

    def test_at_last(self):
        assert _interp_weeks([0, 4], [0.6, 0.9], 4.0) == pytest.approx(0.9)

    def test_midpoint(self):
        assert _interp_weeks([0, 4], [0.6, 0.9], 2.0) == pytest.approx(0.75)

    def test_beyond_last(self):
        assert _interp_weeks([0, 4], [0.6, 0.9], 10.0) == pytest.approx(0.9)

    def test_three_columns(self):
        # 0→0.6, 2→0.9, 6→1.2  — w=4 는 [2,6] 구간 중간
        result = _interp_weeks([0, 2, 6], [0.6, 0.9, 1.2], 4.0)
        expected = 0.9 + (4 - 2) / (6 - 2) * (1.2 - 0.9)
        assert result == pytest.approx(expected)


class TestResolveV2At:
    def test_week0_values(self):
        pts = _resolve_v2_at(_v2_data(), 0.0)
        assert pts[0]['value'] == pytest.approx(0.6)
        assert pts[1]['value'] == pytest.approx(1.2)

    def test_week4_values(self):
        pts = _resolve_v2_at(_v2_data(), 4.0)
        assert pts[0]['value'] == pytest.approx(0.9)
        assert pts[1]['value'] == pytest.approx(1.5)

    def test_week2_interpolated(self):
        pts = _resolve_v2_at(_v2_data(), 2.0)
        assert pts[0]['value'] == pytest.approx(0.75)
        assert pts[1]['value'] == pytest.approx(1.35)

    def test_output_sorted_by_t_sec(self):
        pts = _resolve_v2_at(_v2_data(), 0.0)
        t_secs = [p['t_sec'] for p in pts]
        assert t_secs == sorted(t_secs)

    def test_smooth_flag_preserved(self):
        pts = _resolve_v2_at(_v2_data(), 0.0)
        assert pts[1]['smooth'] is True

    def test_curves_differ_between_weeks(self):
        d = _v2_data()
        pts0 = _resolve_v2_at(d, 0.0)
        pts4 = _resolve_v2_at(d, 4.0)
        v0 = _eval_curve(pts0, 43200)
        v4 = _eval_curve(pts4, 43200)
        assert v0 < v4

    def test_multi_week_plot_series_count(self):
        """get_plot 이 weeks 수만큼 시리즈를 반환한다."""
        import json

        class FakeMethod:
            unique_id = 'x'
            method_type = 'DailyMultiPoint'
            name = 'T'
            method_order = ''

        class FakeMD:
            method_id = 'x'
            unique_id = 'md'
            points_json = json.dumps(_v2_data())

        from aot.utils.method import DailyMultiPointMethod

        class FakeMDQuery:
            def __init__(self, rows): self._rows = rows
            def filter(self, *a, **k): return self
            def all(self): return self._rows
            def first(self): return self._rows[0] if self._rows else None

        m = DailyMultiPointMethod.__new__(DailyMultiPointMethod)
        m.method = FakeMethod()
        m.method_data = FakeMDQuery([FakeMD()])
        m.method_data_first = FakeMD()
        m._data = _migrate_multipoint(json.loads(FakeMD().points_json))
        m._resolved_cache = None
        m._resolved_week = None

        plot = m.get_plot(100)
        assert len(plot) == 2          # weeks [0, 4]
        assert plot[0]['week'] == 0
        assert plot[1]['week'] == 4
        assert len(plot[0]['data']) > 0
        # 두 시리즈의 피크값이 다름
        mid = len(plot[0]['data']) // 2
        assert plot[0]['data'][mid][1] != plot[1]['data'][mid][1]


# ─────────────────────────────────────────────────────────────────────────────
# DailyMultiPointMethod.calculate_setpoint — timezone / weeks_elapsed
# ─────────────────────────────────────────────────────────────────────────────

def _make_method(data=None):
    m = DailyMultiPointMethod.__new__(DailyMultiPointMethod)
    m._data = _migrate_multipoint(data or _v2_data())
    m._resolved_cache = None
    m._resolved_week = None
    return m


def _midnight_ts(aware_dt):
    """Return Unix timestamp for UTC midnight of the given date."""
    d = aware_dt.astimezone(datetime.timezone.utc)
    return datetime.datetime(d.year, d.month, d.day, 0, 0, 0,
                             tzinfo=datetime.timezone.utc).timestamp()


class TestCalculateSetpointTimezone:
    def test_week0_at_midnight_endpoint_value(self):
        """weeks_elapsed=0, t=0 → endpoint value 0.6."""
        m = _make_method()
        start = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        val, ended = m.calculate_setpoint(_midnight_ts(start), method_start_time=start)
        assert val == pytest.approx(0.6, abs=0.02)
        assert ended is False

    def test_week4_at_midnight_endpoint_value(self):
        """weeks_elapsed=4, t=0 → endpoint value 0.9."""
        m = _make_method()
        start = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        now   = start + datetime.timedelta(weeks=4)
        val, ended = m.calculate_setpoint(_midnight_ts(now), method_start_time=start)
        assert val == pytest.approx(0.9, abs=0.02)

    def test_week2_interpolated_endpoint(self):
        """weeks_elapsed=2, t=0 → 0.75 (midpoint of 0.6 and 0.9)."""
        m = _make_method()
        start = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
        now   = start + datetime.timedelta(weeks=2)
        val, ended = m.calculate_setpoint(_midnight_ts(now), method_start_time=start)
        assert val == pytest.approx(0.75, abs=0.02)

    def test_aware_start_equals_float_now_gives_week0(self):
        """start=utc_now(), now_ts=start.timestamp() → weeks_elapsed≈0."""
        m = _make_method()
        start = datetime.datetime(2025, 6, 15, 8, 30, 0, tzinfo=datetime.timezone.utc)
        now_ts = start.timestamp()
        val, _ = m.calculate_setpoint(now_ts, method_start_time=start)
        # weeks_elapsed≈0 → uses week-0 curve; at 8:30 AM value is between 0.6 and 1.2
        # Just confirm no exception and weeks_elapsed was really 0 by checking cache
        assert m._resolved_week == 0

    def test_none_start_uses_epoch_fallback(self):
        """method_start_time=None → start=1900-01-01, weeks_elapsed is huge, clamped to last week."""
        m = _make_method()
        val, ended = m.calculate_setpoint(
            datetime.datetime(2024, 1, 1, 0, 0, 0,
                              tzinfo=datetime.timezone.utc).timestamp(),
            method_start_time=None)
        assert ended is False
        assert 0.0 <= val <= 2.0
