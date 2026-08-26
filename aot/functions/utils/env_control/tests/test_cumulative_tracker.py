# coding=utf-8
"""
cumulative_tracker (DLI/GDD) 테스트 — 광 단위 환산, 로컬 자정 경계, 프리셋 기본값.
"""

from datetime import date, datetime, timezone

import pytz

from aot.functions.utils.env_control.cumulative_tracker import (
    DailyAccumulator, accumulate_cycle, light_to_ppfd, local_today,
)
from aot.functions.utils.env_control.photosynthesis import get_crop_params, CROP_PRESETS


class TestLightConversion:
    """시스템 단위 변환표(config_devices_units.UNIT_CONVERSIONS)를 그대로 사용."""

    def test_wm2_to_ppfd(self):
        """시스템: W_m2 → umol_m2_s ×2.02 (2026-08-25 4.57 에서 정정).

        `W_m2` 는 **전천일사**다. 4.57 은 PAR 대역 W/m² 계수라, 일사계 값에
        곱하면 PPFD 가 2.26 배로 나왔다(정오 800 W/m² → 3,656 μmol, 지표면
        상한 약 2,000 을 넘는 값). 근거는 config_devices_units 주석 참조.
        """
        assert abs(light_to_ppfd(500, 'W/m²') - 500 * 2.02) < 1e-6
        assert abs(light_to_ppfd(500, 'w_m2') - 500 * 2.02) < 1e-6

    def test_맑은날_정오가_물리적_상한_안에_있다(self):
        """계수가 다시 커지면 여기서 걸린다.

        지표면 PPFD 는 맑은 날 정오에도 약 2,000 μmol/m²/s 를 넘지 않는다.
        """
        assert light_to_ppfd(1000, 'W/m²') <= 2100.0

    def test_ppfd_passthrough(self):
        assert light_to_ppfd(800, 'umol_m2_s') == 800
        assert light_to_ppfd(800, 'ppfd') == 800

    def test_lux(self):
        # 시스템 경로 lux→W_m2(×0.0079)→umol(×2.02) = ×0.015958
        assert abs(light_to_ppfd(30000, 'lux') - 30000 * 0.0079 * 2.02) < 1.0

    def test_unknown_unit_defaults_to_wm2(self):
        # 시스템 관례: internal['light'] 는 W/m²
        assert abs(light_to_ppfd(500, None) - 500 * 2.02) < 1e-6
        assert abs(light_to_ppfd(500, 'bogus') - 500 * 2.02) < 1e-6

    def test_none_value(self):
        assert light_to_ppfd(None, 'W/m²') is None


class TestLocalDateBoundary:
    def test_local_today_uses_tz(self):
        seoul = pytz.timezone('Asia/Seoul')
        # local_today 는 tz aware 날짜를 반환(예외 없이)
        assert isinstance(local_today(seoul), date)
        assert isinstance(local_today(None), date)

    def test_rollover_on_local_date_change(self):
        seoul = pytz.timezone('Asia/Seoul')
        acc = DailyAccumulator(day_local=date(2020, 1, 1))  # 과거 날짜 → 즉시 롤오버
        rolled = accumulate_cycle(acc, light_value=0, T_mean=20, VPD=1.0,
                                  CO2=400, cycle_sec=60, tz=seoul)
        assert rolled is True

    def test_no_rollover_same_day(self):
        seoul = pytz.timezone('Asia/Seoul')
        acc = DailyAccumulator(day_local=local_today(seoul))
        rolled = accumulate_cycle(acc, light_value=500, light_unit='W/m²',
                                  T_mean=25, VPD=1.0, CO2=600, cycle_sec=60,
                                  T_base=10, tz=seoul)
        assert rolled is False
        # DLI = (500 W/m² × 2.02 = 1010 PPFD) × 60s × 1e-6 = 0.06060 mol/m²
        assert abs(acc.dli - 0.06060) < 1e-4
        # GDD = (25-10) × 60/86400
        assert abs(acc.gdd - 15 * 60 / 86400.0) < 1e-6


class TestCropPresetTargets:
    def test_presets_have_dli_gdd(self):
        for key in ('tomato', 'lettuce', 'cucumber', 'strawberry', 'pepper'):
            p = get_crop_params(key)
            assert p.dli_target > 0, f'{key} dli_target missing'
            assert p.gdd_daily > 0, f'{key} gdd_daily missing'

    def test_specific_values(self):
        assert get_crop_params('tomato').dli_target == 22.0
        assert get_crop_params('lettuce').dli_target == 14.0
        assert get_crop_params('strawberry').dli_target == 17.0

    def test_gdd_daily_near_topt_minus_tbase(self):
        # gdd_daily ≈ T_opt − T_base (최적 생육 일일 적산온도)
        for key, p in CROP_PRESETS.items():
            assert abs(p.gdd_daily - (p.T_opt - p.T_base)) <= 2.0, key

    def test_presets_have_full_recipe(self):
        # 프리셋이 VPD/CO2/온도 목표까지 제공(env_coordinator 옵션 자동 반영용)
        for key in ('tomato', 'lettuce', 'cucumber', 'strawberry', 'pepper'):
            p = get_crop_params(key)
            assert p.vpd_target > 0, f'{key} vpd_target'
            assert p.co2_target > 0, f'{key} co2_target'
            assert p.temp_min > 0 and p.temp_max > p.temp_min, f'{key} temp range'
