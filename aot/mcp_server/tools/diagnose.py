# coding=utf-8
"""
mcp_server/tools/diagnose.py — P4-1: 분석(진단) 도구 모음 (read-only).

도구 목록:
  analyze_control_performance  — 목표 추종 오차·진동 분석
  detect_sensor_anomaly        — 센서 이상치/드리프트 감지
  suggest_setpoint_adjustment  — 현 상태 기반 VPD 권장값 (제안만, 미적용)
  compare_periods              — 두 기간 비교
"""

from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)


def _safe(fn, *a, default=None, **kw):
    try:
        return fn(*a, **kw)
    except Exception as exc:
        logger.warning('diagnose: %s', exc)
        return default


# ─────────────────────────────────────────────────────────────────────────────
# analyze_control_performance
# ─────────────────────────────────────────────────────────────────────────────

def analyze_control_performance(
    function_id: str,
    window: str = '1h',
) -> dict:
    """env_coordinator 의 VPD 추종 성능을 분석한다.

    목표 추종 오차(RMSE), 진동 지수(Oscillation Index), 포화 비율을 계산한다.

    Args:
        function_id: CustomController.unique_id (env_coordinator)
        window:      분석 기간 '1h' | '6h' | '24h'

    Returns:
        Dict with vpd_rmse, oscillation_index, saturation_ratio,
        assessment (str), recommendations (list[str]).
    """
    def _query():
        # InfluxDB 에서 VPD residual 읽기 (env_control measurement)
        try:
            from aot.utils.influxdb_tags import read_last_measurements
        except ImportError:
            return {'error': 'InfluxDB not available'}

        _WINDOWS = {'1h': 3600, '6h': 21600, '24h': 86400}
        seconds = _WINDOWS.get(window, 3600)

        # env.residual.vpd 채널 조회 (log_channels 규약)
        try:
            residuals_raw = read_last_measurements(
                function_id, 'residual_vpd',
                max_age=seconds, max_count=1000)
        except Exception:
            residuals_raw = []

        if not residuals_raw:
            return {
                'function_id': function_id,
                'window': window,
                'assessment': 'insufficient_data',
                'recommendations': ['더 많은 데이터가 축적되면 재시도하세요.'],
            }

        values = [v for _, v in residuals_raw if v is not None]
        n = len(values)
        if n < 2:
            return {'assessment': 'insufficient_data'}

        rmse = math.sqrt(sum(v ** 2 for v in values) / n)

        # 진동 지수: 부호 변환 빈도
        sign_changes = sum(
            1 for i in range(1, n) if values[i] * values[i - 1] < 0)
        oscillation_index = sign_changes / n

        # 포화 비율: |residual| > 0.3 kPa 인 비율
        saturation_ratio = sum(1 for v in values if abs(v) > 0.3) / n

        # 평가
        if rmse < 0.1:
            assessment = 'excellent'
            recs = []
        elif rmse < 0.2:
            assessment = 'good'
            recs = ['목표 추종 양호. 계속 모니터링하세요.']
        elif oscillation_index > 0.3:
            assessment = 'oscillating'
            recs = [
                'VPD 가 목표 주변을 진동합니다.',
                'env_coordinator 의 tolerance_vpd 를 현재보다 0.05 kPa 높여보세요.',
                '사이클 주기(update_period)를 90초로 늘려 slew 를 완화하세요.',
            ]
        else:
            assessment = 'poor_tracking'
            recs = [
                f'VPD 편차 RMSE={rmse:.3f} kPa — 목표 추종 불량.',
                '제한인자(limiting_factor)를 확인하세요.',
                '액추에이터 효과계수(K) 캘리브레이션을 검토하세요.',
            ]

        return {
            'function_id':       function_id,
            'window':            window,
            'n_samples':         n,
            'vpd_rmse':          round(rmse, 4),
            'oscillation_index': round(oscillation_index, 4),
            'saturation_ratio':  round(saturation_ratio, 4),
            'assessment':        assessment,
            'recommendations':   recs,
        }

    return _safe(_query, default={'function_id': function_id, 'error': 'query failed'})


# ─────────────────────────────────────────────────────────────────────────────
# detect_sensor_anomaly
# ─────────────────────────────────────────────────────────────────────────────

def detect_sensor_anomaly(
    device_id: str,
    measurement_id: str,
    window: str = '24h',
) -> dict:
    """센서 이상치/드리프트를 감지한다.

    IQR 기반 이상치 탐지 + 선형 추세(드리프트) 검사.

    Args:
        device_id:      Input device unique_id
        measurement_id: DeviceMeasurements unique_id
        window:         분석 기간

    Returns:
        Dict with anomaly_count, drift_per_hour, verdict, recommendations.
    """
    def _query():
        try:
            from aot.utils.influxdb_tags import read_last_measurements
        except ImportError:
            return {'error': 'InfluxDB not available'}

        _WINDOWS = {'1h': 3600, '6h': 21600, '24h': 86400}
        seconds = _WINDOWS.get(window, 86400)

        try:
            raw = read_last_measurements(
                device_id, measurement_id,
                max_age=seconds, max_count=2000)
        except Exception:
            raw = []

        if not raw:
            return {'verdict': 'insufficient_data', 'device_id': device_id}

        values = [v for _, v in raw if v is not None]
        n = len(values)
        if n < 4:
            return {'verdict': 'insufficient_data'}

        # IQR 이상치
        sorted_vals = sorted(values)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[3 * n // 4]
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        anomalies = [v for v in values if v < lo or v > hi]
        anomaly_rate = len(anomalies) / n

        # 선형 드리프트 (단순 시작/끝 비교)
        first_half = values[:n // 2]
        second_half = values[n // 2:]
        drift_per_window = (
            sum(second_half) / len(second_half) -
            sum(first_half) / len(first_half)
        )
        drift_per_hour = drift_per_window / (seconds / 3600.0)

        # 판정
        if anomaly_rate > 0.05:
            verdict = 'anomaly_detected'
            recs = [
                f'이상치 비율 {anomaly_rate:.1%} — 센서 연결 상태 점검 필요.',
                '센서 보정(Calibration) 또는 교체를 고려하세요.',
            ]
        elif abs(drift_per_hour) > 0.5:
            verdict = 'drift_detected'
            recs = [
                f'드리프트 {drift_per_hour:+.3f}/h — 센서 제로 포인트 이동.',
                '센서 청소 후 재보정하세요.',
            ]
        else:
            verdict = 'normal'
            recs = []

        return {
            'device_id':       device_id,
            'measurement_id':  measurement_id,
            'window':          window,
            'n_samples':       n,
            'anomaly_count':   len(anomalies),
            'anomaly_rate':    round(anomaly_rate, 4),
            'drift_per_hour':  round(drift_per_hour, 4),
            'verdict':         verdict,
            'recommendations': recs,
        }

    return _safe(_query, default={'device_id': device_id, 'error': 'query failed'})


# ─────────────────────────────────────────────────────────────────────────────
# suggest_setpoint_adjustment
# ─────────────────────────────────────────────────────────────────────────────

def suggest_setpoint_adjustment(facility_id: str) -> dict:
    """현재 환경 상태를 기반으로 VPD setpoint 권장값을 제안한다.

    제안만 반환하며, 실제 변경은 사용자 승인 후 set_vpd_target 으로 수행한다.

    Args:
        facility_id: GeoFacility.unique_id

    Returns:
        Dict with current_vpd, current_target, suggested_target, reason.
    """
    from aot.mcp_server.tools.observe import get_facility_state

    state = get_facility_state(facility_id)
    if state.get('error'):
        return state

    vpd = state.get('VPD')
    T   = state.get('T_int')
    RH  = state.get('RH_int')

    if vpd is None and T is not None and RH is not None:
        # SVP 계산
        svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
        vpd = svp * (1 - RH / 100.0)

    if vpd is None:
        return {
            'facility_id': facility_id,
            'suggestion': 'unavailable',
            'reason': '센서 데이터 없음 — 먼저 get_facility_state 로 확인하세요.',
        }

    # 간단한 룰 기반 권장
    reason = ''
    suggested = None

    if vpd < 0.4:
        suggested = round(vpd + 0.15, 2)
        reason = f'VPD={vpd:.2f} kPa 너무 낮음 — 증산 촉진을 위해 목표를 높이세요.'
    elif vpd > 1.8:
        suggested = round(vpd - 0.2, 2)
        reason = f'VPD={vpd:.2f} kPa 너무 높음 — 식물 수분 스트레스 위험.'
    else:
        reason = f'VPD={vpd:.2f} kPa 적정 범위 — 변경 불필요.'

    return {
        'facility_id':    facility_id,
        'current_vpd':    round(vpd, 3) if vpd else None,
        'T_int':          T,
        'RH_int':         RH,
        'suggested_target': suggested,
        'reason':         reason,
        'note': (
            '이 값은 제안입니다. 적용하려면 set_vpd_target 도구를 사용하고 '
            '사용자 승인을 받으세요.'
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# compare_periods
# ─────────────────────────────────────────────────────────────────────────────

def compare_periods(
    device_id: str,
    measurement_id: str,
    period_a_hours_ago: int = 48,
    period_b_hours_ago: int = 24,
    window_hours: int = 24,
) -> dict:
    """두 기간의 평균/분산을 비교한다.

    Args:
        device_id:            센서 device unique_id
        measurement_id:       측정값 unique_id
        period_a_hours_ago:   A 기간 시작점 (현재로부터 몇 시간 전)
        period_b_hours_ago:   B 기간 시작점 (현재로부터 몇 시간 전)
        window_hours:         각 기간의 길이 (시간)

    Returns:
        Dict with period_a_stats, period_b_stats, delta_mean, delta_std.
    """
    def _stats(values):
        if not values:
            return None
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        return {
            'n':    n,
            'mean': round(mean, 4),
            'std':  round(math.sqrt(variance), 4),
            'min':  round(min(values), 4),
            'max':  round(max(values), 4),
        }

    def _query():
        try:
            from aot.utils.influxdb_tags import read_last_measurements
        except ImportError:
            return {'error': 'InfluxDB not available'}

        import time
        now = time.time()
        w = window_hours * 3600

        def _fetch(hours_ago):
            try:
                return read_last_measurements(
                    device_id, measurement_id,
                    max_age=int(hours_ago * 3600 + w),
                    max_count=2000,
                    time_start=now - hours_ago * 3600 - w,
                    time_end=now - hours_ago * 3600,
                )
            except Exception:
                return []

        raw_a = _fetch(period_a_hours_ago)
        raw_b = _fetch(period_b_hours_ago)

        vals_a = [v for _, v in raw_a if v is not None]
        vals_b = [v for _, v in raw_b if v is not None]

        stats_a = _stats(vals_a)
        stats_b = _stats(vals_b)

        delta_mean = None
        if stats_a and stats_b:
            delta_mean = round(stats_b['mean'] - stats_a['mean'], 4)

        return {
            'device_id':        device_id,
            'measurement_id':   measurement_id,
            'period_a_label':   f'{period_a_hours_ago}h ago (window {window_hours}h)',
            'period_b_label':   f'{period_b_hours_ago}h ago (window {window_hours}h)',
            'period_a_stats':   stats_a,
            'period_b_stats':   stats_b,
            'delta_mean':       delta_mean,
            'interpretation':   (
                f'평균 변화: {delta_mean:+.4f}' if delta_mean is not None
                else '데이터 부족'
            ),
        }

    return _safe(_query, default={'device_id': device_id, 'error': 'query failed'})
