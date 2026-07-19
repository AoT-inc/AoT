# coding=utf-8
"""
DB 모델: FunctionCumulativeState — DLI·GDD 일별 누적 추적 (P5-5).

참조: docs/env_control_enhancement_design.md §3.20
"""

import json
from datetime import date as _date

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db


class FunctionCumulativeState(CRUDMixin, db.Model):
    """Function 단위 일별 누적 환경 메트릭.

    복합 기본키: (function_id, date) — 매일 하나의 행.
    누적값은 UTC 자정(00:00)에 마감되고 다음 날 새 행으로 시작한다.

    메트릭:
      dli_actual   : 실측 일적산광량 [mol/m²/day]
      dli_target   : 목표 DLI [mol/m²/day]
      gdd_actual   : 실측 누적온도 [°C·day]
      gdd_target   : 목표 GDD [°C·day]
      vpd_hours    : VPD 노출 누적 [kPa·h]
      co2_hours    : CO2 노출 누적 [ppm·h / 1000]  (1000으로 나눠 스케일 조정)
      debt_dli     : dli_target - dli_actual (양수 = 부족)
      debt_gdd     : gdd_target - gdd_actual
    """
    __tablename__ = 'function_cumulative_state'
    __table_args__ = {'extend_existing': True}

    function_id = db.Column(db.Text, primary_key=True, nullable=False)
    date        = db.Column(db.Date, primary_key=True, nullable=False,
                            default=_date.today)

    # 실측 누적
    dli_actual  = db.Column(db.Float, default=0.0)
    gdd_actual  = db.Column(db.Float, default=0.0)
    vpd_hours   = db.Column(db.Float, default=0.0)
    co2_hours   = db.Column(db.Float, default=0.0)

    # 목표 (사이클 시작 시 기록, 일 중 변경 없음)
    dli_target  = db.Column(db.Float, default=None)
    gdd_target  = db.Column(db.Float, default=None)

    # 부채 (일 마감 시 계산)
    debt_dli    = db.Column(db.Float, default=0.0)
    debt_gdd    = db.Column(db.Float, default=0.0)

    # 보상 시도 이력 (JSON 리스트)
    compensation_attempted = db.Column(db.Text, default='[]')

    # 메타
    updated_at  = db.Column(db.Float, default=0.0)

    def get_compensation(self) -> list:
        try:
            return json.loads(self.compensation_attempted or '[]')
        except Exception:
            return []

    def append_compensation(self, entry: dict) -> None:
        history = self.get_compensation()
        history.append(entry)
        self.compensation_attempted = json.dumps(history[-20:])  # 최근 20건 유지

    def __repr__(self):
        return (f'<FunctionCumulativeState function_id={self.function_id!r} '
                f'date={self.date} dli={self.dli_actual:.3f}>')


class FunctionCropPreset(CRUDMixin, db.Model):
    """작물별 광합성 모델 파라미터 프리셋 (P3-2′).

    photosynthesis.CROP_PRESETS 와 동기화된 DB 사본.
    사용자가 UI에서 커스터마이즈하거나 새 작물을 추가할 수 있도록 DB에 보관.
    """
    __tablename__ = 'function_crop_preset'
    __table_args__ = {'extend_existing': True}

    id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    crop_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(128), nullable=False, default='')

    # Big-Leaf photosynthesis parameters
    A_max    = db.Column(db.Float, nullable=False, default=20.0)   # µmol CO2/m²/s
    K_L      = db.Column(db.Float, nullable=False, default=100.0)  # µmol/m²/s (half-sat PPFD)
    K_C      = db.Column(db.Float, nullable=False, default=600.0)  # ppm (half-sat CO2)
    T_opt    = db.Column(db.Float, nullable=False, default=22.0)   # °C
    T_sigma  = db.Column(db.Float, nullable=False, default=5.0)    # °C (Gaussian width)
    VPD_half = db.Column(db.Float, nullable=False, default=1.0)    # kPa (stomatal half-sat)
    T_base   = db.Column(db.Float, nullable=False, default=10.0)   # °C (GDD base temp)

    # 작물별 권장 목표 기본값 (env_coordinator 옵션 자동 반영용)
    dli_target = db.Column(db.Float, nullable=False, default=0.0)  # mol/m²/day
    gdd_daily  = db.Column(db.Float, nullable=False, default=0.0)  # °C·day/day
    vpd_target = db.Column(db.Float, nullable=False, default=0.0)  # kPa
    co2_target = db.Column(db.Float, nullable=False, default=0.0)  # ppm
    temp_min   = db.Column(db.Float, nullable=False, default=0.0)  # °C
    temp_max   = db.Column(db.Float, nullable=False, default=0.0)  # °C

    notes    = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=None)

    def to_crop_params(self):
        """photosynthesis.CropParams 로 변환."""
        from aot.functions.utils.env_control.photosynthesis import CropParams
        return CropParams(
            A_max=self.A_max, K_L=self.K_L, K_C=self.K_C,
            T_opt=self.T_opt, T_sigma=self.T_sigma,
            VPD_half=self.VPD_half, T_base=self.T_base,
            dli_target=self.dli_target or 0.0, gdd_daily=self.gdd_daily or 0.0,
            vpd_target=self.vpd_target or 0.0, co2_target=self.co2_target or 0.0,
            temp_min=self.temp_min or 0.0, temp_max=self.temp_max or 0.0,
        )

    def __repr__(self):
        return f'<FunctionCropPreset {self.crop_key!r} A_max={self.A_max}>'
