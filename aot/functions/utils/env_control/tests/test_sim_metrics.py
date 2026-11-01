# coding=utf-8
"""폐루프 시뮬레이터 지표(sim/metrics.py) — 손으로 셀 수 있는 추적으로 확인."""
import pytest

from aot.functions.utils.env_control.sim.metrics import summarize

T0 = 1_800_000_000.0


def _trace(T, rain=None, open_=None, dispatched=None, finals=None):
    n = len(T)
    fine = {'t': [T0 + 60.0 * i for i in range(n)], 'T': T, 'RH': [60.0] * n,
            'VPD': [1.0] * n, 'rain': rain or [0.0] * n, 'open': open_ or [0.0] * n,
            'fan': [0.0] * n}
    cycles = [{'t': T0 + 600.0 * k, 'target': {'VPD': 1.0, 'VPD_tol': 0.1, 'T': 25.0,
                                                 'T_tol': 1.0},
               'guide': {'T_min': 20.0, 'T_max': 30.0, 'RH_min': 50.0, 'RH_max': 80.0},
               'finals': (finals or {}).get(k, {}), 'acc': {'fog_water_kg': 10.0 * k},
               'sensor': {'T': 25.0}, 'truth': {'T': 25.5}, 'emergency': [False, '']}
              for k in range(n // 10 + 1)]
    return {'meta': {'t0': T0, 'warmup_s': 0.0, 'fine_step_s': 60.0,
                     'actuators': [{'actuator_id': 'w', 'kind': 'opening', 'name': '창'}]},
            'cycles': cycles, 'fine': fine, 'fine_pos': {'w': [0.0] * n},
            'dispatched': dispatched or [], 'acc': {'fog_water_kg': 10.0 * (n // 10)}}


def test_degree_minutes_and_bands():
    T = [25.0] * 30 + [41.0] * 30 + [51.0] * 60          # 2 h
    s = summarize(_trace(T))
    assert s['hours'] == pytest.approx(2.0)
    assert s['degmin_gt40'] == pytest.approx(30 * 1.0 + 60 * 11.0)
    assert s['degmin_gt50'] == pytest.approx(60 * 1.0)
    assert s['min_gt50'] == pytest.approx(60.0)
    assert s['T_in_guide_pct'] == pytest.approx(25.0)
    assert s['VPD_in_tol_pct'] == pytest.approx(100.0)
    assert s['sensor_T_abs_err_mean'] == pytest.approx(0.5)


def test_rain_open_minutes():
    n = 60
    rain = [0.0] * 20 + [5.0] * 40
    open_ = [0.5] * 30 + [0.0] * 30
    s = summarize(_trace([25.0] * n, rain=rain, open_=open_))
    assert s['rain_open_min'] == pytest.approx(10.0)
    assert s['rain_min'] == pytest.approx(40.0)


def test_actuator_moves_and_reversals():
    disp = [{'t': T0 + 600 * i, 'aid': 'w', 'type': 'value', 'amount': v}
            for i, v in enumerate([0, 50, 20, 60, 60, 10])]
    s = summarize(_trace([25.0] * 60, dispatched=disp))
    a = s['actuators']['w']
    # 0→50, 50→20, 20→60, 60→10 = 4 이동(60→60 은 이동 아님), 방향 반전 3
    assert a['moves_per_h'] == pytest.approx(4.0)
    assert a['reversals_per_h'] == pytest.approx(3.0)


def test_accumulators_exclude_warmup():
    tr = _trace([25.0] * 60)
    tr['meta']['warmup_s'] = 1200.0
    s = summarize(tr)
    assert s['fog_water_kg'] == pytest.approx(60.0 - 20.0)


def test_leaf_vpd_kpi_uses_the_set_target_and_the_mass_temperature():
    """잎 VPD 지표 — 엽온은 시설 열질량 Tm, 목표는 사람이 정한 숫자(`vpd_set`, 옮기기 전)."""
    from aot.functions.utils.env_control import psychro
    n = 60
    tr = _trace([25.0] * n)
    tr['fine']['RH'] = [70.0] * n
    tr['fine']['Tm'] = [23.5] * n                    # 잎 VPD ≈ 0.68
    for c in tr['cycles']:
        c['vpd_set'] = 0.7
        c['vpd_basis'] = 'leaf'
    s = summarize(tr)
    assert s['leafVPD_mean'] == pytest.approx(psychro.leaf_vpd(23.5, 25.0, 70.0), abs=1e-3)
    assert s['leafVPD_in_tol_pct'] == pytest.approx(100.0)
    assert s['leaf_minus_air_C'] == pytest.approx(-1.5)
    assert s['vpd_basis_fallback_cycles'] == 0
    for c in tr['cycles']:
        c['vpd_set'] = 1.0                           # 0.68 은 1.0 ± 0.1 밖, ± 0.2 밖
    assert summarize(tr)['leafVPD_in_2tol_pct'] == pytest.approx(0.0)


def test_leaf_vpd_kpi_is_absent_without_mass_temperature():
    s = summarize(_trace([25.0] * 30))
    assert s['leafVPD_mean'] is None and s['leafVPD_in_tol_pct'] is None
