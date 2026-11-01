# coding=utf-8
"""계단 시험 — 장치 하나를 0 → 100 % 로 켰을 때 변화의 **방향과 크기**를 독립 참값(`sim/plant.py`)과 비교한다.

트윈 쪽은 정격에서 `priors.grey_priors` 로 채운 사전값(동기화 없음)을 쓴다. 참값과 모델은 같은 저자의 물리 가정을 공유하므로
"독립"은 구조 독립이지 현실 독립이 아니다(설계서 §8-6). 기준 크기비는 측정으로 정한 느슨한 범위이고, 알려진 어긋남은
**일부러 고정 시험으로 남긴다** — 누가 고치면 이 시험이 깨져 목록표(`catalog`)를 같이 고치게 된다.
"""
import pytest

from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.env_control.sim import plant as P
from aot.functions.utils.facility_twin import FacilityConfig, FacilityTwinModel
from aot.functions.utils.twin_effects import catalog as C
from aot.functions.utils.twin_effects.aggregate import Device, merge
from aot.functions.utils.twin_effects.priors import grey_priors

PP = P.PlantParams()
ACTS = [P.ActuatorSpec('wr', 'opening', '측창', area_m2=56.46), P.ActuatorSpec('wl', 'opening', '측창2', area_m2=56.46),
        P.ActuatorSpec('ht', 'heater', '난방', rated_kw=40.0), P.ActuatorSpec('cl', 'cooler', '냉방', rated_kw=20.0),
        P.ActuatorSpec('fg', 'fogger', '분무', flow_kg_s=0.2, nozzles=40, eta=0.9),
        P.ActuatorSpec('co', 'co2_injector', 'CO2', co2_kg_h=3.0),
        P.ActuatorSpec('sh', 'shade', '차광'), P.ActuatorSpec('ct', 'curtain', '커튼')]
DEVS = [Device('wr', 'opening', {'area_m2': 56.46}), Device('wl', 'opening', {'area_m2': 56.46}),
        Device('ht', 'heater', {'rated_kW_thermal': 40.0}), Device('cl', 'cooler', {'rated_kW_thermal': 20.0}),
        Device('fg', 'fogger', {'fog_flow_lpm': 12.0}), Device('co', 'co2_injector', {'co2_kg_h': 3.0}),
        Device('sh', 'shade', {}), Device('ct', 'curtain', {})]
SCREENS = ('shade', 'curtain')


def _closed(kind):
    return 100.0 if kind in SCREENS else 0.0       # 스크린은 100 = 걷힘


def _plant(cmds, w, T0, RH0):
    pl = P.Plant(PP, ACTS, 0.0, T=T0, RH=RH0, CO2=420.0)
    for a in ACTS:
        v = cmds.get(a.actuator_id, _closed(a.kind))
        if a.kind in ('opening', 'shade', 'curtain'):
            pl.set_position(a.actuator_id, v)
        else:
            pl.set_command(a.actuator_id, 'value', v, 0.0)
    wx = lambda t: {'T': w['T'], 'RH': w['RH'], 'solar': w['solar'], 'wind': 1.0, 'rain': 0.0, 'co2': 420.0, 'cloud': 0.0}
    pl.advance(3600.0, wx, dt=20.0)
    return pl.observe()


def _twin(cmds, w, T0, RH0, fog_evap=None):
    gp = GreyboxParams(UA_eff=PP.U_cover * PP.cover_m2, volume_m3=PP.volume_m3, alpha_sol=PP.tau_cover * 0.5 * 0.4 * PP.cover_m2,
                       tau_T=900.0, m_vent_coef=113.0 * 0.5, tau_shade=PP.shade_tau, tau_curtain=PP.curtain_tau,
                       curtain_ua_saving=PP.curtain_ua_saving)
    for k, v in grey_priors(DEVS, PP.volume_m3).items():
        if k != 'm_fog_evap':                       # 상한이라 쓰지 않는다
            setattr(gp, k, v['value'])
    if fog_evap is not None:
        gp.m_fog_evap = fog_evap
    ch = merge(DEVS, {a.actuator_id: cmds.get(a.actuator_id, _closed(a.kind)) for a in ACTS}).values
    cm = {'heat': 0, 'cool': 0, 'vent': 0, 'fog': 0, 'co2_inj': 0, 'shade': 100, 'curtain': 100}
    cm.update(ch)
    m = FacilityTwinModel(gp, FacilityConfig())
    e = {'T_ext': w['T'], 'RH_ext': w['RH'], 'solar': w['solar'], 'wind': 1.0, 'CO2_ext': 420.0}
    return m.derived(m.predict(m.init_state(T0, RH0, 420.0), lambda t: e, cm, 0.0, 600.0, 7)[-1])


def _delta(on, w, T0, RH0, **kw):
    p0, p1 = _plant({}, w, T0, RH0), _plant(on, w, T0, RH0)
    t0, t1 = _twin({}, w, T0, RH0, **kw), _twin(on, w, T0, RH0, **kw)
    return ({k: p1[k] - p0[k] for k in ('T', 'RH', 'CO2')}, {k: t1[k] - t0[k] for k in ('T', 'RH', 'CO2')})


# (이름, 켜는 장치, 날씨, 초기 T·RH, ΔT 크기비 범위)  — 크기비 = 트윈 / 참값. 범위는 측정(2026-10-25)으로 정한 느슨한 값.
CASES = [
    ('heater', {'ht': 100.0}, dict(T=10, RH=60, solar=0), (22, 70), (0.5, 2.0)),
    ('cooler', {'cl': 100.0}, dict(T=33, RH=50, solar=0), (30, 55), (0.5, 2.0)),
    ('vent', {'wr': 100.0, 'wl': 100.0}, dict(T=15, RH=60, solar=0), (22, 70), (0.3, 3.0)),   # 환기 능력은 알려진 ×2~3 편차(§9.16.1)
    ('shade_closed', {'sh': 0.0}, dict(T=28, RH=50, solar=800), (22, 70), (0.5, 2.0)),
    ('curtain_closed', {'ct': 0.0}, dict(T=0, RH=60, solar=0), (22, 70), (0.5, 2.0)),
]


@pytest.mark.parametrize("name,on,w,init,band", CASES, ids=[c[0] for c in CASES])
def test_temperature_response_sign_and_size(name, on, w, init, band):
    dp, dt = _delta(on, w, *init)
    assert dp['T'] != 0 and dt['T'] * dp['T'] > 0, (name, dp, dt)          # 부호 일치(필수)
    ratio = dt['T'] / dp['T']
    assert band[0] <= ratio <= band[1], (name, ratio, dp, dt)


def test_co2_injection_size():
    dp, dt = _delta({'co': 100.0}, dict(T=20, RH=60, solar=0), 20, 60)
    assert dp['CO2'] > 500 and dt['CO2'] > 500
    assert 0.7 <= dt['CO2'] / dp['CO2'] <= 1.5, (dp, dt)


def test_humidity_sign_for_modeled_effects():
    for name, on, w, init, _ in CASES:
        if name == 'cooler':
            continue                                                       # 아래 알려진 어긋남
        dp, dt = _delta(on, w, *init)
        if abs(dp['RH']) > 2.0:
            assert dp['RH'] * dt['RH'] > 0, (name, dp, dt)


def test_known_divergence_cooler_dehumidification_is_unmodeled():
    """참값의 냉방기는 제습한다(RH↓), 그레이박스는 못 한다(온도만 내려 RH↑). 목록표가 이를 '미반영'으로 적고 있어야 한다."""
    dp, dt = _delta({'cl': 100.0}, dict(T=33, RH=50, solar=0), 30, 55)
    assert dp['RH'] < 0 < dt['RH']
    assert 'dehumidification' in C.row_for('cooler').unmodeled_effects
    assert C.row_for('cooler').status == C.PARTIAL


def test_known_divergence_fog_magnitude_and_prior_is_upper_bound_only():
    """분무: ΔT 방향은 맞지만 ΔRH 크기는 참값의 수 배~10배(참값은 잎 젖음·단락으로 덜 증발). 정격 기반 값은 상한이라
    사전값으로 쓰지 않는다 — 기본 `m_fog_evap`(500 W)은 효과가 거의 없어(ΔT ≈ −0.1) 동기화·식별이 맡아야 한다."""
    pri = grey_priors(DEVS, PP.volume_m3)
    assert pri['m_fog_evap']['basis'] == 'upper_bound'
    w, init = dict(T=33, RH=40, solar=600), (30, 55)
    dp, dt = _delta({'fg': 100.0}, w, *init, fog_evap=1.0e5)
    assert dp['T'] < 0 and dt['T'] < 0 and dp['RH'] > 0 and dt['RH'] > 0
    assert dt['RH'] > 3 * dp['RH']                                          # 알려진 크기 어긋남(고쳐지면 이 줄을 갱신)
    _, dt0 = _delta({'fg': 100.0}, w, *init)
    assert abs(dt0['T']) < 0.5                                              # 기본 사전값은 사실상 무효과
    assert C.row_for('fogger').status == C.PARTIAL
