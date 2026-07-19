# coding=utf-8
"""
greybox/shadow.py — shadow 모드: 그레이박스 예측 로깅만, 제어에 미적용.

shadow 모드에서 실측 vs 예측을 InfluxDB 에 기록하면 사이트별 KPI 검증 후
greybox 모드(실제 effect_model 교체)로 전환 결정을 내릴 수 있다.

KPI: T_int 24h-ahead MAE ≤ 1.5°C, RH_int MAE ≤ 8%
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict, Optional

from .model import step
from .params import GreyboxParams
from .channels import aggregate_cmds_by_kind

logger = logging.getLogger(__name__)

# shadow 모드 InfluxDB measurement 이름
_MEASUREMENT = 'env_greybox'

# shadow 예측 지평 (사이클 수)
SHADOW_HORIZON = 1    # 현재 1-step; Stage 3 MPC 에서 확장


class GreyboxShadow:
    """매 사이클 호출되어 1-step 예측을 실행·기록.

    실제 제어에는 영향을 주지 않는다.
    """

    def __init__(self, params: Optional[GreyboxParams] = None):
        self.params    = params or GreyboxParams()
        self._prev_T:   Optional[float] = None
        self._prev_RH:  Optional[float] = None
        self._prev_CO2: Optional[float] = None
        self._prev_pred_T:   Optional[float] = None
        self._prev_pred_RH:  Optional[float] = None
        self._err_T_buf:  deque = deque(maxlen=1440)   # 24h @ 60s
        self._err_RH_buf: deque = deque(maxlen=1440)
        # 학습 입력 이력 (state, ext, cmds) — identification.fit 가 소비
        self._input_buf:  deque = deque(maxlen=1440)   # 24h @ 60s

    def step(
        self,
        unique_id: str,
        internal: dict,
        external: dict,
        cmds_pct: dict,
        dt: float = 60.0,
        kind_by_aid: Optional[Dict[str, str]] = None,
    ):
        """1-step 예측 실행. 이전 예측 오차 기록. 제어값 변경 없음.

        kind_by_aid: {actuator_id: kind} — greybox 채널 집계에 사용(없으면 id 추정).
        """
        T   = internal.get('T')
        RH  = internal.get('RH')
        CO2 = internal.get('CO2', 400.0)

        if T is None or RH is None:
            self._prev_T = T
            self._prev_RH = RH
            self._prev_CO2 = CO2
            self._prev_pred_T = None
            self._prev_pred_RH = None
            return

        # 이전 예측 오차 기록
        if self._prev_pred_T is not None and self._prev_T is not None:
            err_T  = abs(T  - self._prev_pred_T)
            err_RH = abs(RH - self._prev_pred_RH) if self._prev_pred_RH is not None else 0.0
            self._err_T_buf.append(err_T)
            self._err_RH_buf.append(err_RH)
            try:
                from aot.utils.influx import write_influxdb_value
                write_influxdb_value(unique_id, _MEASUREMENT, value=T,            channel=0)
                write_influxdb_value(unique_id, _MEASUREMENT, value=self._prev_pred_T, channel=1)
                write_influxdb_value(unique_id, _MEASUREMENT, value=err_T,        channel=2)
                write_influxdb_value(unique_id, _MEASUREMENT, value=RH,           channel=3)
                write_influxdb_value(unique_id, _MEASUREMENT,
                                     value=self._prev_pred_RH or 0.0,             channel=4)
                write_influxdb_value(unique_id, _MEASUREMENT, value=err_RH,       channel=5)
            except Exception:
                pass

        # 명령 벡터 집계 (greybox 채널별 최대값, kind 기반)
        cmds = aggregate_cmds_by_kind(cmds_pct, kind_by_aid)

        ext = {
            'T_ext':   external.get('T_ext',   20.0),
            'RH_ext':  external.get('RH_ext',  60.0),
            'CO2_ext': external.get('CO2_ext', 400.0),
            'solar':   external.get('solar',    0.0),
            'wind':    external.get('wind',     0.0),
        }

        pred_T, pred_RH, pred_CO2 = step(T, RH, CO2, ext, cmds, self.params, dt)

        # 학습용 입력 이력 버퍼 (identification.fit 가 소비)
        self._input_buf.append((
            (T, RH, CO2),
            dict(ext),
            dict(cmds),
        ))

        self._prev_T, self._prev_RH, self._prev_CO2 = T, RH, CO2
        self._prev_pred_T, self._prev_pred_RH = pred_T, pred_RH

    def mae_T(self) -> Optional[float]:
        if not self._err_T_buf:
            return None
        return sum(self._err_T_buf) / len(self._err_T_buf)

    def mae_RH(self) -> Optional[float]:
        if not self._err_RH_buf:
            return None
        return sum(self._err_RH_buf) / len(self._err_RH_buf)

    def kpi_passed(self, mae_T_limit: float = 1.5, mae_RH_limit: float = 8.0) -> bool:
        """KPI 통과 여부. shadow → greybox 전환 결정에 사용."""
        t = self.mae_T()
        r = self.mae_RH()
        if t is None or r is None:
            return False
        return t <= mae_T_limit and r <= mae_RH_limit

    def fit_window(self):
        """학습용 (states, exts, cmds) 시계열 반환.

        states 는 입력 버퍼의 연속 상태(t=0..N), exts/cmds 는 각 전이의 입력(t=0..N-1).
        identification.fit 의 입력 계약과 일치(states 길이 = exts 길이 + 1).
        샘플 부족 시 빈 시퀀스.
        """
        buf = list(self._input_buf)
        if len(buf) < 2:
            return [], [], []
        states = [b[0] for b in buf]              # N+1 states
        exts   = [b[1] for b in buf[:-1]]         # N exts (마지막 전이 입력 제외)
        cmds   = [b[2] for b in buf[:-1]]         # N cmds
        return states, exts, cmds
