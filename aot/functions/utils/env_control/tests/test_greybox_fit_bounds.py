# coding=utf-8
"""
학습이 "초기값이 범위 밖" 으로 매번 실패하지 않는가 — 2026-09-28.

`least_squares` 는 초기값이 범위 밖이면 **손도 대지 않고** 실패한다. 물리 기반
초기값(`from_capacity_meta`)은 시설 크기에 비례하는데 범위는 작은 온실 기준이라,
개구부가 넓은 시설은 학습이 100 % 실패했다 — 로컬 실측에서 `m_vent_coef` 가 417
인데 상한이 10 이었다(개구부 833 m²).

그 전까지는 그림자 자체가 죽어 있어(`cycle_sec` 결함) 이 실패가 드러나지도 않았다.
그래서 두 축으로 막는다: **범위를 시설 크기에 맞게 넓히고**, 그래도 밖이면 접어
넣되 **말한다**(조용히 접으면 범위 산정이 틀린 것을 영영 모른다).
"""

import logging
import math

import pytest

from aot.functions.utils.env_control.greybox.identification import fit, N_MIN_SAMPLES
from aot.functions.utils.env_control.greybox.model import step
from aot.functions.utils.env_control.greybox.params import GreyboxParams


def _series(params, n):
    """그 모델이 만든 시계열 — 학습이 실제로 풀 수 있는 입력."""
    T, RH, CO2 = 22.0, 65.0, 480.0
    states, exts, cmds = [(T, RH, CO2)], [], []
    for i in range(n):
        ext = {'T_ext': 14.0 + 6.0 * math.sin(i / 20.0), 'RH_ext': 60.0,
               'CO2_ext': 410.0,
               'solar': max(0.0, 600.0 * math.sin(math.pi * (i % 144) / 144.0)),
               'wind': 1.5}
        cmd = {'heat': 0.0, 'cool': 0.0, 'vent': 30.0 if i % 7 else 0.0,
               'fog': 20.0 if i % 11 == 0 else 0.0, 'co2_inj': 0.0}
        T, RH, CO2 = step(T, RH, CO2, ext, cmd, params, 600.0)
        states.append((T, RH, CO2))
        exts.append(ext)
        cmds.append(cmd)
    return states, exts, cmds


class TestLargeFacility:
    def test_개구부가_넓은_시설의_초기값이_범위_안이다(self):
        """833 m² 개구부 — 로컬 실측값. 예전 상한(10)이면 학습이 통째로 막힌다."""
        p = GreyboxParams.from_capacity_meta({
            'volume_m3': 6000.0, 'u_effective': 4.0, 'envelope_m2': 2450.0,
            'roof_m2': 980.0, 'transmittance': 0.78, 'vent_open_m2': 833.0,
        })
        for key in ('UA_eff', 'alpha_sol', 'm_vent_coef', 'tau_T'):
            lo, hi = p.BOUNDS[key]
            v = getattr(p, key)
            assert lo <= v <= hi, '%s=%g 가 범위(%g~%g) 밖 — 학습이 매번 실패한다' % (
                key, v, lo, hi)

    def test_그_시설의_데이터로_학습이_된다(self):
        p = GreyboxParams.from_capacity_meta({
            'volume_m3': 6000.0, 'u_effective': 4.0, 'envelope_m2': 2450.0,
            'vent_open_m2': 833.0,
        })
        states, exts, cmds = _series(p, N_MIN_SAMPLES + 10)
        out = fit(states, exts, cmds, dt=600.0, prev_params=p)
        assert out is not None, '초기값이 범위 안인데도 학습이 실패했다'
        assert out.n_updates == p.n_updates + 1


class TestClampIsLoud:
    def test_범위_밖_초기값은_접어_넣되_말한다(self, caplog):
        p = GreyboxParams()
        p.m_vent_coef = p.BOUNDS['m_vent_coef'][1] * 10.0     # 상한의 10배
        states, exts, cmds = _series(GreyboxParams(), N_MIN_SAMPLES + 5)
        with caplog.at_level(logging.WARNING):
            out = fit(states, exts, cmds, dt=600.0, prev_params=p)
        assert out is not None, '접어 넣었는데도 학습이 실패했다'
        assert any('범위' in r.message or 'm_vent_coef' in str(r.args)
                   for r in caplog.records), '조용히 접으면 범위가 틀린 것을 모른다'

    def test_접은_값은_범위_안이다(self):
        p = GreyboxParams()
        p.UA_eff = p.BOUNDS['UA_eff'][1] * 3.0
        states, exts, cmds = _series(GreyboxParams(), N_MIN_SAMPLES + 5)
        out = fit(states, exts, cmds, dt=600.0, prev_params=p)
        assert out is not None
        lo, hi = out.BOUNDS['UA_eff']
        assert lo <= out.UA_eff <= hi


class TestBoundsStillGuard:
    def test_물리적으로_말이_안_되는_값은_여전히_막는다(self):
        """범위를 넓힌 것이지 없앤 것이 아니다 — 음수·0 은 계속 막혀야 한다."""
        p = GreyboxParams()
        p.m_vent_coef = -5.0
        p.tau_T = 0.0
        p.clamp()
        assert p.m_vent_coef >= p.BOUNDS['m_vent_coef'][0] > 0
        assert p.tau_T >= p.BOUNDS['tau_T'][0] > 0


if __name__ == '__main__':
    pytest.main([__file__])
