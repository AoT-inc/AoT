# coding=utf-8
"""
greybox/shadow.py — shadow 모드: 그레이박스 예측 로깅만, 제어에 미적용.

shadow 모드에서 실측 vs 예측을 InfluxDB 에 기록하면 사이트별 KPI 검증 후
greybox 모드(실제 effect_model 교체)로 전환 결정을 내릴 수 있다.

KPI: H스텝(SKILL_HORIZON) 예측의 기상 구간별 skill + MAE — `kpi_passed` 참조.
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

# shadow 예측 지평 (사이클 수) — Influx 에 남기는 즉시 예측
SHADOW_HORIZON = 1

# ── KPI = H스텝 skill (2026-09-22, 계획서 env-mpc-reinforcement B 단계) ─────
# 1스텝(한 사이클 뒤) 오차는 모델 품질을 가려내지 못했다 — 사이클이 짧으면 "변화
# 없음" 예측만으로도 작다(로컬 한 곳이 0.16 °C 로 통과). MPC 가 쓰는 것은 H스텝
# 예측이므로 그것을 재고, **"변화 없음"(H 사이클 전 값 그대로)보다 나은가**를 본다:
#     skill = 1 − RMSE(모델) / RMSE(변화 없음)
# 기상 구간마다 따로 잰다 — 한 구간의 좋은 점수가 다른 구간의 실패를 가리지 않게.
# ⚠ 문턱 숫자는 아직 정하지 않았다(결정 D6). 지금은 "관측된 모든 구간에서 변화 없음을
#   이긴다" 가 최소 조건이고, 수치는 그림자 기록 약 2주의 분포를 보고 정한다.
SKILL_HORIZON        = 10          # MPC 지평(MPCConfig.horizon)과 같다
SKILL_WINDOW         = 14 * 1440   # 평가 기록 보관 개수(60 초 사이클 14일)
MIN_TOTAL_SAMPLES    = 144         # 전체 평가 수 하한
MIN_REGIME_SAMPLES   = 30          # 한 구간을 판정할 최소 평가 수
MIN_REGIMES          = 2           # 판정 가능한 구간 수 하한(낮·밤 최소)
SKILL_MIN_T          = 0.0         # 구간별 온도 skill 하한(수치 미정 — D6)
SKILL_MIN_RH         = 0.0         # 구간별 습도 skill 하한(수치 미정 — D6)
MAE_LIMIT_T          = 1.5         # H스텝 절대오차 상한(전체) °C
MAE_LIMIT_RH         = 8.0         # H스텝 절대오차 상한(전체) %

REGIMES = ('hot_dry_day', 'hot_humid_day', 'mild_day', 'transition',
           'mild_night', 'cold_night')


def classify_regime(T_int: Optional[float], RH_int: Optional[float],
                    ext: dict) -> str:
    """예측을 시작한 순간의 기상 구간.

    낮·밤·전환은 일사로 가른다(해 고도를 모르는 설치도 일사는 있다).
    고온은 실내 28 °C 이상, 건조는 실내 60 % 미만, 저온 밤은 실외 10 °C 이하.
    """
    solar = float(ext.get('solar') or 0.0)
    if 5.0 < solar < 100.0:
        return 'transition'
    if solar >= 100.0:
        if T_int is not None and T_int >= 28.0:
            return 'hot_dry_day' if (RH_int is not None and RH_int < 60.0) else 'hot_humid_day'
        return 'mild_day'
    T_ext = ext.get('T_ext')
    return 'cold_night' if (T_ext is not None and T_ext <= 10.0) else 'mild_night'


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
        # H스텝 평가용 최근 이력과 평가 기록 (B 단계 KPI)
        self._hist:  deque = deque(maxlen=SKILL_HORIZON + 1)
        self._skill: deque = deque(maxlen=SKILL_WINDOW)

    def step(
        self,
        unique_id: str,
        internal: dict,
        external: dict,
        cmds_pct: dict,
        dt: float = 60.0,
        kind_by_aid: Optional[Dict[str, str]] = None,
        vent_caps: Optional[dict] = None,
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

        # 명령 벡터 집계 (kind 기반). vent 는 풍량 비율(`channels.vent_channel_value`)
        cmds = aggregate_cmds_by_kind(cmds_pct, kind_by_aid, vent_caps)

        ext = {
            'T_ext':   external.get('T_ext',   20.0),
            'RH_ext':  external.get('RH_ext',  60.0),
            'CO2_ext': external.get('CO2_ext', 400.0),
            'solar':   external.get('solar',    0.0),
            'wind':    external.get('wind',     0.0),
        }

        pred_T, pred_RH, pred_CO2 = step(T, RH, CO2, ext, cmds, self.params, dt)

        # ── H스텝 평가: H 사이클 전 상태에서 실제 입력으로 예측 → 지금과 비교 ──
        self._evaluate_horizon(T, RH)
        self._hist.append({'state': (T, RH, CO2), 'ext': dict(ext),
                           'cmds': dict(cmds), 'dt': float(dt),
                           'regime': classify_regime(T, RH, ext)})

        # 학습용 입력 이력 버퍼 (identification.fit 가 소비)
        self._input_buf.append((
            (T, RH, CO2),
            dict(ext),
            dict(cmds),
        ))

        self._prev_T, self._prev_RH, self._prev_CO2 = T, RH, CO2
        self._prev_pred_T, self._prev_pred_RH = pred_T, pred_RH

    def _evaluate_horizon(self, T: float, RH: float) -> None:
        """H 사이클 전 상태에서 그 사이의 **실제** 외기·명령으로 예측해 지금과 비교한다.

        변화 없음 예측 = H 사이클 전 값 그대로. 구간은 예측을 시작한 순간의 것이다.
        """
        if len(self._hist) < SKILL_HORIZON:
            return
        seq = list(self._hist)[-SKILL_HORIZON:]
        T0, RH0, CO20 = seq[0]['state']
        try:
            t, rh, co2 = T0, RH0, CO20
            for h in seq:
                t, rh, co2 = step(t, rh, co2, h['ext'], h['cmds'], self.params, h['dt'])
        except Exception:
            return
        self._skill.append((seq[0]['regime'], t - T, T0 - T, rh - RH, RH0 - RH))

    def skill_report(self) -> dict:
        """구간별 H스텝 skill · 표본 수 · 전체 MAE — 요약·로그·게이트가 쓴다."""
        import math
        by = {}
        for reg, eTm, eTp, eHm, eHp in self._skill:
            a = by.setdefault(reg, [0, 0.0, 0.0, 0.0, 0.0])
            a[0] += 1
            a[1] += eTm * eTm; a[2] += eTp * eTp
            a[3] += eHm * eHm; a[4] += eHp * eHp

        def skill(m, p):
            return None if p <= 1e-12 else round(1.0 - math.sqrt(m / p), 3)

        regimes = {reg: {'n': a[0], 'skill_T': skill(a[1], a[2]),
                         'skill_RH': skill(a[3], a[4])} for reg, a in by.items()}
        n = len(self._skill)
        mae_T = (sum(abs(x[1]) for x in self._skill) / n) if n else None
        mae_RH = (sum(abs(x[3]) for x in self._skill) / n) if n else None
        return {'horizon': SKILL_HORIZON, 'n': n,
                'mae_T': None if mae_T is None else round(mae_T, 3),
                'mae_RH': None if mae_RH is None else round(mae_RH, 2),
                'regimes': regimes}

    def mae_T(self) -> Optional[float]:
        """H스텝 온도 절대오차 평균(KPI 기준)."""
        return self.skill_report()['mae_T']

    def mae_RH(self) -> Optional[float]:
        """H스텝 습도 절대오차 평균(KPI 기준)."""
        return self.skill_report()['mae_RH']

    def kpi_passed(self, mae_T_limit: float = MAE_LIMIT_T,
                   mae_RH_limit: float = MAE_LIMIT_RH) -> bool:
        """KPI 통과 여부 — greybox 제어를 켜도 되는가.

        1) 전체 평가 수 ≥ MIN_TOTAL_SAMPLES
        2) 판정 가능한 구간(표본 ≥ MIN_REGIME_SAMPLES)이 MIN_REGIMES 개 이상
        3) 그 **모든** 구간에서 온도·습도 skill 이 하한을 넘는다(변화 없음을 이긴다)
        4) 전체 H스텝 MAE 가 상한 이내
        """
        rep = self.skill_report()
        if rep['n'] < MIN_TOTAL_SAMPLES or rep['mae_T'] is None:
            return False
        judged = [r for r in rep['regimes'].values() if r['n'] >= MIN_REGIME_SAMPLES]
        if len(judged) < MIN_REGIMES:
            return False
        for r in judged:
            if r['skill_T'] is None or r['skill_T'] <= SKILL_MIN_T:
                return False
            if r['skill_RH'] is None or r['skill_RH'] <= SKILL_MIN_RH:
                return False
        return rep['mae_T'] <= mae_T_limit and rep['mae_RH'] <= mae_RH_limit

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
