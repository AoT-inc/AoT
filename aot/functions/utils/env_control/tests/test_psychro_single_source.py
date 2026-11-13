# coding=utf-8
"""습공기 식의 정본은 `psychro` 하나 — 사본을 걷어낸 뒤에도 값이 그대로인지 못 박는다.

2026-10-09: 같은 Magnus 식(0.6108·17.27·237.3)이 `situation`·`basis`·`effect_functions`·
`coordinator`·`_helpers_mixin`·`facility_sensors`·`ext_context_collector` 에 따로
적혀 있었다. 사본을 `psychro` 호출로 바꾸되 **동작은 그대로**여야 하므로, 아래
`_OLD_*` 는 바꾸기 전 식을 그대로 얼려 둔 기준이다. 이 기준과 지금 모듈 함수가
격자(T −10..60 °C, RH 0..100 %)에서 맞아야 한다 — 상대 1e-9 이내.

⚠ `_OLD_*` 에 옛 상수가 남아 있는 것은 의도다. 이 파일 밖에서는 상수를 쓰지 말 것
(맨 아래 `test_no_magnus_literals_outside_psychro` 가 지킨다).
"""
import hashlib
import math
import os

import pytest

from aot.functions.utils.env_control import basis
from aot.functions.utils.env_control import effect_functions as ef
from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control import situation
from aot.utils import psychro

REL = 1e-9

T_GRID = [-10.0 + 2.5 * i for i in range(29)]          # -10 .. 60 °C
RH_GRID = [float(r) for r in range(0, 101, 5)]         # 0 .. 100 %


def _close(a, b, rel=REL, abs_=1e-12):
    return a == b or abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


# ─────────────────────────────────────────────────────────────────────────────
# 얼려 둔 옛 식 (바꾸기 전 사본 그대로)
# ─────────────────────────────────────────────────────────────────────────────

def _OLD_svp(T):                      # situation.svp / basis._svp / effect_functions._svp_kpa
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


def _OLD_compute_vpd(T, RH):          # situation.compute_vpd
    return max(0.0, (1 - RH / 100.0) * _OLD_svp(T))


def _OLD_dsvp(T):                     # effect_functions.make_vpd_effect 의 dsvp
    svp_ = _OLD_svp(T)
    return svp_ * 17.27 * 237.3 / (T + 237.3) ** 2


def _OLD_dewpoint_from_e(e_kpa):      # _helpers_mixin._dewpoint_from_e
    if e_kpa is None or e_kpa <= 0.0:
        return None
    a = math.log(e_kpa / 0.6108)
    return 237.3 * a / (17.27 - a)


def _OLD_invert_svp_for_T(vpd_target, RH, T_ref=20.0):   # situation._invert_svp_for_T
    vpd_target = max(0.0, vpd_target)
    ea = max(0.0, min(100.0, RH) / 100.0) * _OLD_svp(T_ref)
    s_need = vpd_target + ea
    if s_need <= 0.0:
        return max(-10.0, min(50.0, T_ref))
    r = math.log(s_need / 0.6108)
    if r >= 17.27:
        return 50.0
    return max(-10.0, min(50.0, 237.3 * r / (17.27 - r)))


def _OLD_vpd_outdoor(T_e, RH_e):      # coordinator._outdoor_reachable('vpd')
    svp = 0.6108 * math.exp(17.27 * float(T_e) / (float(T_e) + 237.3))
    return svp * (1.0 - float(RH_e) / 100.0)


def _OLD_vpd_facility(T_avg, RH_avg):  # facility_sensors.compute_spatial_internal 의 VPD 폴백
    svp = 0.6108 * math.exp(17.27 * T_avg / (T_avg + 237.3))
    return round(max(0.0, (1.0 - RH_avg / 100.0) * svp), 3)


def _OLD_calc_dewpoint(T, RH):        # ext_context_collector._calc_dewpoint
    a, b = 17.27, 237.3
    alpha = (a * T) / (b + T) + math.log(max(RH, 0.1) / 100.0)
    return (b * alpha) / (a - alpha)


def _OLD_absorbable_head(t, rh):      # effect_functions._absorbable_liters 의 g/m³ 여유 (Pa 계수 610.78)
    svp = 610.78 * math.exp(17.27 * t / (t + 237.3))
    rho_sat = svp * ef._M_WATER_KG_MOL / (ef._R_GAS * (t + 273.15)) * 1000.0
    return rho_sat * (1.0 - rh / 100.0)


# ─────────────────────────────────────────────────────────────────────────────
# 정본 자체
# ─────────────────────────────────────────────────────────────────────────────

def test_svp_matches_frozen_formula():
    for T in T_GRID:
        assert _close(psychro.svp(T), _OLD_svp(T))


def test_svp_slope_matches_frozen_formula_and_finite_difference():
    for T in T_GRID:
        assert _close(psychro.svp_slope(T), _OLD_dsvp(T))
        h = 1e-4
        fd = (psychro.svp(T + h) - psychro.svp(T - h)) / (2 * h)
        assert _close(psychro.svp_slope(T), fd, rel=1e-6)


def test_temperature_from_svp_is_inverse_of_svp():
    for T in T_GRID:
        assert abs(psychro.temperature_from_svp(psychro.svp(T)) - T) < 1e-9
    assert psychro.temperature_from_svp(0.0) is None
    assert psychro.temperature_from_svp(-1.0) is None
    assert psychro.temperature_from_svp(None) is None
    assert psychro.temperature_from_svp(1e12) == math.inf        # 점근선 밖


def test_dewpoint_is_unchanged_by_the_refactor():
    for T in T_GRID:
        for RH in RH_GRID:
            e = RH / 100.0 * _OLD_svp(T)
            old = _OLD_dewpoint_from_e(e)
            new = psychro.dewpoint(e)
            assert (old is None) == (new is None)
            if old is not None:
                assert _close(old, new)


def test_vpd_from_rh_matches_old_compute_vpd():
    for T in T_GRID:
        for RH in RH_GRID + [100.4, -1.0]:     # 범위 밖 RH 도 자르지 않는 옛 동작 그대로
            assert _close(psychro.vpd_from_rh(T, RH), _OLD_compute_vpd(T, RH))


def test_svp_pa_within_0_1_percent_of_old_pa_copy():
    """Pa 사본은 계수가 610.78 이었다(정본 610.8) — 합치며 생기는 차이를 못 박는다."""
    worst = 0.0
    for T in T_GRID:
        old = 610.78 * math.exp(17.27 * T / (T + 237.3))
        worst = max(worst, abs(psychro.svp_pa(T) - old) / old)
    assert worst < 1e-3                 # 브리프의 한도(0.1 %)
    assert worst < 4e-5                 # 실제 값은 3.3e-5


# ─────────────────────────────────────────────────────────────────────────────
# 사본이었던 모듈들 — 공개 이름은 그대로, 값도 그대로
# ─────────────────────────────────────────────────────────────────────────────

def test_situation_wrappers_unchanged():
    for T in T_GRID:
        assert _close(situation.svp(T), _OLD_svp(T))
        assert _close(situation._svp(T), _OLD_svp(T))
        for RH in RH_GRID:
            assert _close(situation.compute_vpd(T, RH), _OLD_compute_vpd(T, RH))
            assert _close(situation._compute_vpd(T, RH), _OLD_compute_vpd(T, RH))


def test_situation_invert_svp_unchanged():
    for T_ref in T_GRID:
        for RH in RH_GRID:
            for vpd_t in (0.0, 0.2, 0.8, 1.5, 3.0, 8.0, -0.5):
                assert _close(situation._invert_svp_for_T(vpd_t, RH, T_ref=T_ref),
                              _OLD_invert_svp_for_T(vpd_t, RH, T_ref=T_ref))


def test_situation_decompose_vpd_to_T_RH_unchanged():
    def old_decompose(vpd_target, T_int, RH_int, w_T=0.6):
        vpd_target = max(0.0, vpd_target)
        if abs(_OLD_compute_vpd(T_int, RH_int) - vpd_target) < 1e-4:
            return T_int, RH_int
        T_needed = _OLD_invert_svp_for_T(vpd_target, RH_int, T_ref=T_int)
        T_aux = max(-10.0, min(50.0, T_int + w_T * (T_needed - T_int)))
        svp_aux = _OLD_svp(T_aux)
        RH_aux = RH_int if svp_aux < 1e-9 else (1.0 - vpd_target / svp_aux) * 100.0
        return T_aux, max(0.0, min(100.0, RH_aux))

    for T in T_GRID[::2]:
        for RH in RH_GRID[::2]:
            for vpd_t in (0.0, 0.5, 1.0, 2.0):
                o = old_decompose(vpd_t, T, RH)
                n = situation.decompose_vpd_to_T_RH(vpd_t, T, RH)
                assert _close(o[0], n[0]) and _close(o[1], n[1])


def test_basis_svp_unchanged():
    for T in T_GRID:
        assert _close(basis._svp(T), _OLD_svp(T))


def test_effect_functions_svp_and_vpd_gap_unchanged():
    for T in T_GRID:
        assert _close(ef._svp_kpa(T), _OLD_svp(T))
    for T_e in T_GRID[::3]:
        for RH_e in RH_GRID[::4]:
            for T_i in T_GRID[::3]:
                for RH_i in RH_GRID[::4]:
                    env = {'T_ext': T_e, 'RH_ext': RH_e, 'T_int': T_i, 'RH_int': RH_i}
                    old = (_OLD_svp(T_e) * (1.0 - RH_e / 100.0)
                           - _OLD_svp(T_i) * (1.0 - RH_i / 100.0))
                    assert _close(ef._vpd_gap(env), old)


def test_effect_functions_absorbable_headroom_within_0_1_percent():
    """`_absorbable_liters`(Pa 사본 → psychro.svp_pa). 계수 610.78 → 610.8, 최대 3.3e-5."""
    volume = 200.0
    for T in T_GRID:
        for RH in RH_GRID[:-1]:                 # RH=100 은 여유 0 — 상대오차가 의미 없다
            env = {'T_int': T, 'RH_int': RH}
            new = ef._absorbable_liters(env, volume)
            old = max(0.0, _OLD_absorbable_head(T, RH) * volume / 1000.0)
            assert abs(new - old) <= 1e-3 * max(old, 1e-12) + 1e-15
    assert ef._absorbable_liters({'T_int': 20.0, 'RH_int': 100.0}, volume) == 0.0
    assert ef._absorbable_liters({'T_int': 20.0}, volume) == float('inf')


def test_coordinator_outdoor_reachable_vpd_unchanged():
    from aot.functions.utils.env_control import coordinator
    for T in T_GRID:
        for RH in RH_GRID + [100.4]:
            got = coordinator._outdoor_reachable('vpd', {'T_ext': T, 'RH_ext': RH})
            assert _close(got, _OLD_vpd_outdoor(T, RH))
    assert coordinator._outdoor_reachable('vpd', {'T_ext': 10.0}) is None


def test_helpers_mixin_primitives_and_margin_unchanged():
    from aot.functions.custom_functions.env_coordinator_impl import _helpers_mixin as hm
    for T in T_GRID:
        assert _close(hm._svp_kpa(T), _OLD_svp(T))
        for RH in RH_GRID:
            if RH <= 0:
                assert hm.dewpoint_margin(T, RH) is None
                continue
            old_td = _OLD_dewpoint_from_e(RH / 100.0 * _OLD_svp(T))
            assert _close(hm.dewpoint_margin(T, RH), T - old_td)
    assert hm._dewpoint_from_e(0.0) is None
    assert hm._dewpoint_from_e(None) is None
    for e in (0.01, 0.3, 1.2, 2.3, 7.0):
        assert _close(hm._dewpoint_from_e(e), _OLD_dewpoint_from_e(e))


# 바꾸기 전 코드로 만든 격자 결과의 지문 — 불리언이라 libm 차이에 흔들리지 않는다.
_CONDENSATION_GRID_SHA1 = '7fcf3c03790a6c5a0bcefed0cdb1b816fa65c877'


def test_condensation_escape_decisions_unchanged():
    from aot.functions.custom_functions.env_coordinator_impl import _helpers_mixin as hm
    out = []
    for T_in in (5.0, 10.0, 15.0, 20.0, 25.0, 30.0):
        for RH_in in (60.0, 80.0, 88.0, 92.0, 96.0, 99.0, 100.0):
            for T_out in (-5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 30.0):
                for RH_out in (30.0, 60.0, 85.0, 95.0, 100.0):
                    for was in (False, True):
                        for warm in (False, True):
                            out.append(bool(hm.condensation_escape(
                                T_in, RH_in, T_out, RH_out, was, warm)))
    digest = hashlib.sha1(''.join('1' if b else '0' for b in out).encode()).hexdigest()
    assert 0 < sum(out) < len(out)             # 격자가 두 갈래를 모두 지나는지
    assert digest == _CONDENSATION_GRID_SHA1


def test_facility_sensors_vpd_fallback_unchanged(monkeypatch):
    """센서가 VPD 를 안 줄 때 T/RH 평균으로 계산하는 값(`compute_spatial_internal`)."""
    from aot.space import facility_sensors as fs
    state = {}
    monkeypatch.setattr(fs, '_freshness_by_device', lambda ids: {})
    monkeypatch.setattr(fs, '_read_one_sensor',
                        lambda uuid, mtype, max_age, measurement_id=None:
                        {'T': state['T'], 'RH': state['RH']})
    for T in T_GRID[::2]:
        for RH in RH_GRID[::2]:
            state.update(T=T, RH=RH)
            res = fs.compute_spatial_internal([{'input_uuid': 'dev-1'}])
            assert res['vpd_measured'] is False
            assert res['VPD'] == round(_OLD_vpd_facility(T, RH), 3)


def test_ext_context_dewpoint_unchanged():
    pytest.importorskip('flask_babel')
    try:
        from aot.functions import ext_context_collector as ecc
    except Exception as exc:                  # pragma: no cover - 환경 의존
        pytest.skip('ext_context_collector 를 불러올 수 없다: %r' % (exc,))
    for T in T_GRID:
        for RH in RH_GRID + [0.05]:
            assert _close(ecc._calc_dewpoint(T, RH), _OLD_calc_dewpoint(T, RH),
                          rel=REL, abs_=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Task B — 결로 문턱은 `humid_regime` 한 곳
# ─────────────────────────────────────────────────────────────────────────────

def test_condensation_margins_defined_once_in_humid_regime(monkeypatch):
    """결로 탈출구(`condensation_escape`)와 과습 구간 판정이 같은 이슬점 여유 문턱을 쓴다."""
    from aot.functions.custom_functions.env_coordinator_impl import _helpers_mixin as hm
    assert (HR.ENTER_MARGIN_C, HR.EXIT_MARGIN_C) == (2.0, 3.0)
    # 사본이 남아 있지 않다 — 별칭도 두지 않는다.
    assert not hasattr(hm, '_CONDENSATION_ENTER_C')
    assert not hasattr(hm, '_CONDENSATION_EXIT_C')

    # 문턱을 바꾸면 두 판정이 함께 움직인다: 22 °C·RH 84 % 는 여유 ≈ 2.8 °C 라 ENTER(2.0)
    # 위 — 둘 다 '안전'. ENTER 를 3.5 로 올리면 둘 다 '위험'으로 바뀐다(건조한 외기가 있을 때).
    T, RH = 22.0, 84.0
    margin = hm.dewpoint_margin(T, RH)
    assert HR.ENTER_MARGIN_C < margin < 3.5
    T_out, RH_out = 18.0, 30.0
    assert not HR.in_overhumid_zone(T, RH) and not hm.condensation_escape(T, RH, T_out, RH_out)
    monkeypatch.setattr(HR, 'ENTER_MARGIN_C', 3.5)
    assert HR.in_overhumid_zone(T, RH)
    assert hm.condensation_escape(T, RH, T_out, RH_out)


# ─────────────────────────────────────────────────────────────────────────────
# 사본 재발 방지
# ─────────────────────────────────────────────────────────────────────────────

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *(['..'] * 4)))
_SKIP_DIRS = ('/tests/', '/greybox/', '/aot/inputs/', '/__pycache__/')
_SKIP_FILES = ('/aot/utils/psychro.py', '/env_control/psychro.py', '/aot/utils/auto_vpd.py')


def test_no_magnus_literals_outside_psychro():
    """Magnus 상수(0.6108·237.3)를 psychro 밖에서 다시 쓰지 말 것.

    범위 밖: `greybox/`(동결), `inputs/`(센서 드라이버), `utils/auto_vpd.py`, 테스트.
    """
    offenders = []
    for dirpath, _dirs, files in os.walk(_ROOT):
        for fn in files:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            norm = path.replace(os.sep, '/')
            if any(s in norm for s in _SKIP_DIRS + _SKIP_FILES):
                continue
            with open(path, encoding='utf-8') as fh:
                for no, line in enumerate(fh, 1):
                    code = line.split('#', 1)[0]
                    if '0.6108' in code or '237.3' in code or '610.78' in code:
                        offenders.append('%s:%d' % (norm.split('/aot/', 1)[-1], no))
    assert not offenders, 'psychro 밖의 Magnus 상수: %s' % offenders
