# coding=utf-8
"""
test_vpd_noise_filter.py — 실내 VPD 측정 잡음 필터 (2026-08-06 aot-005 야간 창호 진동).

VPD 는 센서가 직접 주는 값이 아니라 T·RH 에서 계산된다. 습도 센서가 정수 % 로
보고하면 그 최소 눈금 하나가 VPD 계단이 되고(23°C/85% 에서 0.028kPa =
tolerance_vpd 기본값의 28%), 외란이 없는 새벽에도 RH 85↔86 토글만으로 조율기
입력이 계속 흔들린다. 그 흔들림이 개구부 명령에 실려 창이 밤새 움직였다.

여기서는 필터가 (a) 눈금 디더를 눌러 주고 (b) 실제 전이는 늦추지 않으며
(c) `_collect_internal` 경로에 실제로 걸려 있는지를 고정한다.
"""

import math
from unittest.mock import MagicMock, patch

from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    _VPD_EMA_ALPHA,
    _VPD_EMA_SNAP,
    HelpersMixin,
    smooth_vpd,
)


def _svp(T):
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


def _vpd(T, RH):
    return _svp(T) * (1 - RH / 100.0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. smooth_vpd — 순수 함수
# ─────────────────────────────────────────────────────────────────────────────

class TestSmoothVpd:
    def test_first_sample_passes_through(self):
        """첫 샘플(prev=None)은 그대로 통과 — 재시작 직후 0 에서 끌려오지 않는다."""
        assert smooth_vpd(None, 0.42) == 0.42

    def test_attenuates_one_rh_tick(self):
        """습도 1% 눈금 하나가 만드는 계단을 크게 줄인다."""
        raw_step = abs(_vpd(23.0, 85.0) - _vpd(23.0, 86.0))
        assert raw_step > 0.025, '전제 확인: RH 1% = 0.028kPa 급'
        base = _vpd(23.0, 85.0)
        out = smooth_vpd(base, base + raw_step)
        assert abs(out - base) < raw_step * 0.5, \
            f'눈금 계단이 그대로 통과: {abs(out - base):.4f} / {raw_step:.4f}'

    def test_dither_ripple_stays_small(self):
        """RH 85↔86 을 계속 오갈 때 필터 출력 진폭이 원신호보다 훨씬 작다."""
        lo, hi = _vpd(23.0, 86.0), _vpd(23.0, 85.0)
        v = lo
        out = []
        for i in range(60):
            v = smooth_vpd(v, hi if i % 2 == 0 else lo)
            out.append(v)
        settled = out[-20:]
        ripple = max(settled) - min(settled)
        assert ripple < (hi - lo) * 0.35, \
            f'디더 리플 과다: {ripple:.4f} (원신호 {hi - lo:.4f})'

    def test_snaps_on_real_transition(self):
        """실제 전이(일출 직후 급상승 등)는 지연 없이 즉시 추종한다."""
        jumped = 0.40 + _VPD_EMA_SNAP * 1.5
        assert smooth_vpd(0.40, jumped) == jumped

    def test_lag_bounded_by_snap_on_ramp(self):
        """지속 램프에서도 추종 지연이 _VPD_EMA_SNAP 이하로 묶인다."""
        raw, filt = 0.40, 0.40
        worst = 0.0
        for _ in range(200):
            raw += 0.02                       # 사이클당 0.02kPa 상승
            filt = smooth_vpd(filt, raw)
            worst = max(worst, abs(raw - filt))
        assert worst <= _VPD_EMA_SNAP + 1e-9, f'추종 지연 초과: {worst:.4f}kPa'

    def test_alpha_is_a_real_average(self):
        """평활 계수가 (0,1) 범위 — 0 이면 고착, 1 이면 필터가 없는 것과 같다."""
        assert 0.0 < _VPD_EMA_ALPHA < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. _collect_internal 배선 — 필터가 실제 수집 경로에 걸려 있는가
# ─────────────────────────────────────────────────────────────────────────────

def _sensor(input_uuid, measurement_id, measurement_type):
    return {
        'fitting_id':       'fit-' + measurement_id,
        'name':             measurement_type,
        'position':         None,
        'sensor_role':      'indoor',
        'measurement_type': measurement_type,
        'input_uuid':       input_uuid,
        'measurement_id':   measurement_id,
        'input_name':       None,
        'input_device':     None,
    }


def _coordinator():
    obj = MagicMock()
    obj._collect_internal = HelpersMixin._collect_internal.__get__(obj)
    obj._sensors_resolved = [
        _sensor('dT',  'mT',  'temperature'),
        _sensor('dRH', 'mRH', 'humidity'),
    ]
    obj._sensors_resolved_outdoor = []
    obj.logger = MagicMock()
    obj.debug_logging = False
    obj._vpd_ema = None       # MagicMock 자동속성 대신 명시적 초기 상태
    return obj


def _read(obj, T, RH):
    def _glm(device_id, measurement_id, max_age=None):
        return [1000.0, {'mT': T, 'mRH': RH}.get(measurement_id)]
    with patch('aot.utils.influx.get_last_measurement', side_effect=_glm):
        return obj._collect_internal(300.0)


def test_collect_internal_applies_filter_across_cycles():
    """첫 사이클은 원값, 이후 눈금 토글은 필터가 눌러 준다."""
    obj = _coordinator()

    first = _read(obj, 23.0, 85.0)['VPD']
    # compute_spatial_internal 이 소수 3자리로 반올림해 넘긴다
    assert abs(first - _vpd(23.0, 85.0)) < 1e-3, '첫 샘플은 원값이어야 한다'

    second = _read(obj, 23.0, 86.0)['VPD']
    raw_second = _vpd(23.0, 86.0)
    raw_step = abs(raw_second - first)
    assert abs(second - first) < raw_step * 0.5, \
        f'수집 경로에 필터가 안 걸림: {abs(second - first):.4f} / {raw_step:.4f}'


def test_collect_internal_keeps_state_when_measurement_missing():
    """측정이 빠진 사이클은 필터 상태를 건드리지 않는다.

    센서 만료 뒤 복귀할 때 낡은 필터값이 새 측정값을 끌어당기면 안 된다.
    """
    obj = _coordinator()
    _read(obj, 23.0, 85.0)
    held = obj._vpd_ema

    missing = _read(obj, None, None)
    assert 'VPD' not in missing
    assert obj._vpd_ema == held, '측정 없는 사이클이 필터 상태를 바꿨다'
