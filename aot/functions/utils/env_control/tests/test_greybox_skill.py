# coding=utf-8
"""greybox KPI = H스텝 skill(계획서 env-mpc-reinforcement B 단계).

1스텝 오차는 "변화 없음" 예측만으로도 작아 모델 품질을 가려내지 못했다. 이제
H 사이클 앞 예측이 변화 없음보다 나은지를 기상 구간마다 따로 잰다.
"""
import copy
import math

import pytest

import aot.utils.influx as influx
from aot.functions.utils.env_control.greybox import shadow as sh
from aot.functions.utils.env_control.greybox.model import step
from aot.functions.utils.env_control.greybox.params import GreyboxParams


@pytest.fixture(autouse=True)
def _no_influx(monkeypatch):
    monkeypatch.setattr(influx, 'write_influxdb_value', lambda *a, **k: None)


TRUTH = GreyboxParams(volume_m3=1000.0, UA_eff=400.0, tau_T=3000.0, m_vent_coef=1.5,
                      alpha_sol=60.0, k_transp=3e-4, k_photo=0.0, Q_plant_base=0.0)


def _series(n=600, dt=300.0):
    """하루 두 번의 낮·밤이 지나가는 합성 기록 — 창을 여닫고 일사가 오르내린다."""
    out, s = [], (22.0, 70.0, 400.0)
    for i in range(n):
        solar = max(0.0, 700.0 * math.sin(2 * math.pi * i / 288.0))
        ext = {'T_ext': 18.0 + 6.0 * math.sin(2 * math.pi * i / 288.0), 'RH_ext': 65.0,
               'CO2_ext': 400.0, 'solar': solar, 'wind': 1.0}
        vent = 60.0 if (i // 12) % 2 else 0.0
        out.append((s, ext, vent))
        s = step(*s, ext, {'vent': vent}, TRUTH, dt)
    return out


def _run(params, series, dt=300.0):
    g = sh.GreyboxShadow(params=params)
    for (T, RH, CO2), ext, vent in series:
        g.step('fn', {'T': T, 'RH': RH, 'CO2': CO2},
               {'T_ext': ext['T_ext'], 'RH_ext': ext['RH_ext'], 'CO2_ext': 400.0,
                'solar': ext['solar'], 'wind': ext['wind']},
               {'v1': vent}, dt=dt, kind_by_aid={'v1': 'opening'})
    return g


def test_regimes():
    assert sh.classify_regime(30.0, 50.0, {'solar': 600.0}) == 'hot_dry_day'
    assert sh.classify_regime(30.0, 70.0, {'solar': 600.0}) == 'hot_humid_day'
    assert sh.classify_regime(24.0, 70.0, {'solar': 600.0}) == 'mild_day'
    assert sh.classify_regime(24.0, 70.0, {'solar': 50.0}) == 'transition'
    assert sh.classify_regime(15.0, 80.0, {'solar': 0.0, 'T_ext': 5.0}) == 'cold_night'
    assert sh.classify_regime(15.0, 80.0, {'solar': 0.0, 'T_ext': 15.0}) == 'mild_night'


def test_a_correct_model_beats_persistence_and_passes():
    g = _run(copy.deepcopy(TRUTH), _series())
    rep = g.skill_report()
    assert rep['horizon'] == sh.SKILL_HORIZON and rep['n'] >= sh.MIN_TOTAL_SAMPLES
    judged = {k: v for k, v in rep['regimes'].items() if v['n'] >= sh.MIN_REGIME_SAMPLES}
    assert len(judged) >= 2
    assert all(v['skill_T'] > 0.5 and v['skill_RH'] > 0.5 for v in judged.values())
    assert g.kpi_passed()


def test_a_wrong_model_fails_even_with_a_small_one_step_error():
    """환기량을 10배 틀린 모델 — 1스텝으로는 가려지던 것을 H스텝이 잡는다."""
    bad = copy.deepcopy(TRUTH)
    bad.m_vent_coef = 15.0
    bad.UA_eff = 4000.0
    g = _run(bad, _series())
    assert not g.kpi_passed()


def test_a_no_change_model_does_not_pass():
    """"변화 없음" 과 같은 수준이면 통과하지 못한다(skill 이 하한을 넘어야 한다)."""
    frozen = copy.deepcopy(TRUTH)
    frozen.UA_eff, frozen.tau_T = 10.0, 7200.0          # 열용량이 커서 거의 안 움직인다
    frozen.m_vent_coef, frozen.alpha_sol, frozen.k_transp = 0.001, 0.0, 0.0
    g = _run(frozen, _series())
    rep = g.skill_report()
    assert any(v['skill_T'] is not None and v['skill_T'] <= 0.05
               for v in rep['regimes'].values())
    assert not g.kpi_passed()


def test_not_enough_samples_does_not_pass():
    g = _run(copy.deepcopy(TRUTH), _series(n=60))
    assert not g.kpi_passed()


def test_one_failing_regime_blocks_the_pass(monkeypatch):
    """한 구간의 좋은 점수가 다른 구간의 실패를 가리지 않는다."""
    g = _run(copy.deepcopy(TRUTH), _series())
    assert g.kpi_passed()
    # 밤 구간만 모델 오차를 "변화 없음" 의 두 배로(참 모델이라 원래 오차는 0 이다)
    g._skill = type(g._skill)(
        [(r, (2.0 * eTp if 'night' in r else eTm), eTp, eHm, eHp)
         for r, eTm, eTp, eHm, eHp in g._skill], maxlen=g._skill.maxlen)
    assert not g.kpi_passed()


def test_mae_now_means_the_horizon_error():
    g = _run(copy.deepcopy(TRUTH), _series())
    assert g.mae_T() == g.skill_report()['mae_T']
