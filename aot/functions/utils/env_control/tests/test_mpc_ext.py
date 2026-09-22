# coding=utf-8
"""MPC 외기 시퀀스(F 단계, 2026-09-22) — 예보 변화량·맑은 날 일사 × 맑음 정도."""

from datetime import datetime

import pytest
import pytz

from aot.functions.utils.env_control.mpc_ext import (
    K_MIN_CLEAR, STALE_H, build_ext_seq, kma_curve,
)

KST = pytz.timezone('Asia/Seoul')
BASE = {'T_ext': 20.0, 'RH_ext': 60.0, 'CO2_ext': 400.0, 'solar': 300.0, 'wind': 2.0}


def _epoch(y, mo, d, h, mi=0):
    return KST.localize(datetime(y, mo, d, h, mi)).timestamp()


def _file(now='202609221200', pub='202609221100', tmp=(18.0, 20.0, 22.0, 24.0),
          reh=(70.0, 65.0, 60.0, 55.0)):
    return {'tz': 'Asia/Seoul', 'now': now, 'pub_dt': pub,
            'forecasts': {str(i): {'TMP': t, 'REH': r}
                          for i, (t, r) in enumerate(zip(tmp, reh))}}


class TestKmaCurve:
    def test_오프셋은_파일을_쓴_시각_기준(self):
        c = kma_curve(_file(), _epoch(2026, 9, 22, 12, 30))
        assert c[0][0] == _epoch(2026, 9, 22, 12)
        assert c[1][0] == _epoch(2026, 9, 22, 13)

    def test_낡은_예보는_쓰지_않는다(self):
        now = _epoch(2026, 9, 22, 11) + (STALE_H + 0.5) * 3600
        assert kma_curve(_file(), now) is None

    def test_빈_파일(self):
        assert kma_curve({}, 0.0) is None
        assert kma_curve({'now': '202609221200', 'forecasts': {}}, 0.0) is None

    def test_숫자_아닌_값은_버린다(self):
        f = _file()
        f['forecasts']['1'] = {'TMP': '비', 'REH': None}
        c = kma_curve(f, _epoch(2026, 9, 22, 12))
        assert len(c) == 3


class TestTemperature:
    def test_변화량만_쓴다_편향은_지운다(self):
        """예보는 12시 18°C → 13시 20°C. 실측은 지금 20°C — 한 시간 뒤는 22°C 여야 한다
        (예보 값 20°C 를 그대로 쓰면 편향 2°C 만큼 틀린다)."""
        now = _epoch(2026, 9, 22, 12)
        seq, info = build_ext_seq(BASE, 6, 600.0, now, curve=kma_curve(_file(), now))
        assert info['temp'] == 'forecast'
        # 6번째 칸 가운데 = 12:55 → 예보 +1.83 °C
        assert seq[5]['T_ext'] == pytest.approx(20.0 + 2.0 * 55 / 60, abs=1e-6)
        assert seq[0]['T_ext'] == pytest.approx(20.0 + 2.0 * 5 / 60, abs=1e-6)
        assert seq[5]['RH_ext'] == pytest.approx(60.0 - 5.0 * 55 / 60, abs=1e-6)

    def test_지평을_못_덮으면_지금_값(self):
        now = _epoch(2026, 9, 22, 14, 30)       # 곡선 끝은 15:00
        seq, info = build_ext_seq(BASE, 6, 600.0, now, curve=kma_curve(_file(), now))
        assert info['temp'] == 'persistence'
        assert all(s['T_ext'] == 20.0 for s in seq)

    def test_예보가_없으면_예전과_같다(self):
        seq, info = build_ext_seq(BASE, 4, 600.0, 0.0)
        assert seq == [BASE] * 4
        assert info == {'temp': 'persistence', 'solar': 'persistence', 'k': None}

    def test_습도는_0_100(self):
        now = _epoch(2026, 9, 22, 12)
        f = _file(reh=(5.0, 90.0, 90.0, 90.0))
        seq, _ = build_ext_seq(dict(BASE, RH_ext=95.0), 6, 600.0, now,
                               curve=kma_curve(f, now))
        assert max(s['RH_ext'] for s in seq) == 100.0


class TestSolar:
    @staticmethod
    def _sky(peak_at, width=6 * 3600.0, peak=800.0):
        """가짜 맑은 날 곡선 — peak_at 에서 최대인 반원."""
        import math

        def cs(t):
            x = (t - peak_at) / width
            return peak * math.cos(x * math.pi / 2) if abs(x) < 1 else 0.0
        return cs

    def test_맑음_정도를_유지한다(self):
        now = 0.0
        cs = self._sky(peak_at=3 * 3600.0)       # 오후로 갈수록 오른다
        seq, info = build_ext_seq(dict(BASE, solar=0.5 * cs(now)), 10, 600.0, now,
                                  clear_sky=cs)
        assert info['solar'] == 'clear_sky' and info['k'] == pytest.approx(0.5)
        assert seq[-1]['solar'] == pytest.approx(0.5 * cs(9.5 * 600.0))
        assert seq[-1]['solar'] > seq[0]['solar']

    def test_해가_지면_0_으로(self):
        cs = self._sky(peak_at=-5 * 3600.0)      # 지금은 해 질 무렵
        now = 0.0
        seq, _ = build_ext_seq(dict(BASE, solar=cs(now)), 10, 600.0, now, clear_sky=cs)
        assert cs(now) >= K_MIN_CLEAR
        assert seq[-1]['solar'] == 0.0

    def test_해가_낮으면_기억한_맑음_정도(self):
        cs = self._sky(peak_at=6 * 3600.0)       # 새벽 — 지금은 0
        seq, info = build_ext_seq(dict(BASE, solar=0.0), 10, 600.0, 0.0,
                                  clear_sky=cs, k_memory=0.7)
        assert info['k'] == pytest.approx(0.7)
        assert seq[-1]['solar'] == pytest.approx(0.7 * cs(9.5 * 600.0))

    def test_기억도_없으면_지금_값(self):
        cs = self._sky(peak_at=6 * 3600.0)
        seq, info = build_ext_seq(dict(BASE, solar=0.0), 10, 600.0, 0.0, clear_sky=cs)
        assert info['solar'] == 'persistence'
        assert all(s['solar'] == 0.0 for s in seq)

    def test_좌표를_모르면_지금_값(self):
        seq, info = build_ext_seq(BASE, 3, 600.0, 0.0, clear_sky=lambda t: None)
        assert info['solar'] == 'persistence'
        assert all(s['solar'] == 300.0 for s in seq)


class TestCoordinatorWiring:
    def _coord(self, fac_tz):
        import logging
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
        c = CycleMixin.__new__(CycleMixin)
        c.unique_id = 'x'
        c.logger = logging.getLogger('test_mpc_ext')
        c._get_facility_tz = lambda: fac_tz
        return c

    def test_시간대가_다른_시설에는_서울_예보를_쓰지_않는다(self, monkeypatch):
        import aot.functions.utils.env_control.forecast_feedforward as ff
        monkeypatch.setattr(ff, '_load_forecast', lambda *a, **k: _file())
        now = _epoch(2026, 9, 22, 12)
        assert self._coord(pytz.timezone('Asia/Tokyo'))._mpc_forecast_curve(
            now, kma_curve) is None
        assert self._coord(None)._mpc_forecast_curve(now, kma_curve) is None
        assert self._coord(KST)._mpc_forecast_curve(now, kma_curve) is not None
