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

# ── 재초기화를 견디는 상태 저장 (2026-09-28) ─────────────────────────────────
# 학습 창(`_input_buf`)과 KPI 평가 기록(`_skill`)은 여기 메모리에만 있었다. 컨트롤러
# 객체는 옵션 저장·데몬 리로드마다 다시 만들어지므로(로컬 실측 7일간 155회) 그때마다
# 창이 0 으로 돌아갔고, 600 초 주기에서 학습에 필요한 120 샘플 = **20시간 연속**이라
# 사실상 학습이 성립하지 않았다. 그래서 압축해서 영속화한다(호출부가 주기적으로 저장).
#
# ⚠ 저장하는 것은 **측정과 명령**(데이터)이지 모델 출력이 아니다. 그래서 물리식이
#   바뀌어(model_version) 계수를 버릴 때도 이 창은 그대로 쓸 수 있다 — 오히려 새 식의
#   재학습이 빨라진다.
STATE_SCHEMA        = 2
_ACCEPTED_SCHEMAS   = (1, 2)   # v1 = 시각·H스텝 이력이 없던 판
PERSIST_INPUT_MAX   = 600     # 저장할 학습 샘플 수(600 초 주기면 100시간, 60 초면 10시간)
PERSIST_SKILL_MAX   = 1500    # 저장할 KPI 평가 기록 수(하한 144 보다 넉넉히)
PERSIST_MAX_AGE_S   = 7 * 86400   # 이보다 오래된 저장분은 버린다(시설 구성이 달라진다)
_EXT_KEYS = ('T_ext', 'RH_ext', 'CO2_ext', 'solar', 'wind')
_CMD_KEYS = ('heat', 'cool', 'vent', 'fog', 'co2_inj', 'shade', 'curtain')

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


# @manual ai/env-control#settings-calibration
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
        # ⚠ **시각을 함께 싣는다.** 이 버퍼의 이웃 두 항목은 "한 사이클 전이" 로
        #   쓰이는데, 재시작·센서 끊김으로 사이에 구멍이 나면 두 시점이 이웃이
        #   아니다. 시각이 없으면 그 구멍을 건너뛴 쌍이 정상 전이처럼 학습에
        #   들어간다(2026-09-28 확인 — 로컬은 재초기화 간격 중앙값 18분이라
        #   이런 쌍이 드물지 않다).
        self._input_buf.append((
            (T, RH, CO2),
            dict(ext),
            dict(cmds),
            time.time(),
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

    # @manual ai/env-control#settings-calibration
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

    # ── 재초기화를 견디게 저장·복원 ──────────────────────────────────────
    def export_state(self, dt: float) -> dict:
        """다음 객체가 이어받을 상태. 숫자 배열로 눕혀 크기를 줄인다.

        `dt` 를 함께 적는다 — 학습은 "한 사이클 뒤" 전이를 맞추는 것이라, 주기가
        바뀐 샘플을 섞으면 전이의 뜻이 달라진다(복원할 때 버린다).
        """
        def _ent(entry):
            state, ext, cmds = entry[0], entry[1], entry[2]
            ts = entry[3] if len(entry) > 3 else None
            return [
                [round(float(x), 3) if x is not None else None for x in state],
                [None if ext.get(k) is None else round(float(ext.get(k)), 3)
                 for k in _EXT_KEYS],
                [round(float(cmds.get(k, 0.0) or 0.0), 1) for k in _CMD_KEYS],
                None if ts is None else round(float(ts), 1),
            ]

        skill = []
        for reg, eTm, eTp, eHm, eHp in list(self._skill)[-PERSIST_SKILL_MAX:]:
            try:
                idx = REGIMES.index(reg)
            except ValueError:
                continue
            skill.append([idx] + [round(float(v), 3) for v in (eTm, eTp, eHm, eHp)])

        return {
            'v': STATE_SCHEMA,
            'dt': round(float(dt), 3),
            'saved_at': time.time(),
            'input': [_ent(e) for e in list(self._input_buf)[-PERSIST_INPUT_MAX:]],
            'skill': skill,
            # H스텝 평가는 직전 10사이클 이력이 있어야 한 건이 나온다. 이것을
            # 이어받지 않으면 재초기화마다 10사이클을 버리고 다시 센다 — 로컬
            # 실측에서 재초기화 간격 중앙값이 18분(≈2사이클)이라, 그대로 두면
            # KPI 가 **영영 쌓이지 않는다**(실제로 0건이었다).
            'hist': [[[round(float(x), 3) for x in h['state']],
                      [None if h['ext'].get(k) is None else round(float(h['ext'][k]), 3)
                       for k in _EXT_KEYS],
                      [round(float(h['cmds'].get(k, 0.0) or 0.0), 1) for k in _CMD_KEYS],
                      round(float(h['dt']), 1),
                      REGIMES.index(h['regime']) if h['regime'] in REGIMES else -1]
                     for h in list(self._hist)],
            # 직전 예측 — 재시작 직후 첫 사이클의 오차 기록을 잃지 않는다.
            'prev': ([round(float(v), 3) if v is not None else None
                      for v in (self._prev_T, self._prev_RH, self._prev_CO2,
                                self._prev_pred_T, self._prev_pred_RH)]),
        }

    def load_state(self, blob: Optional[dict], dt: float) -> dict:
        """저장분을 이어받는다. 반환값은 무엇을 이어받았는지(호출부가 로그로 남긴다).

        이어받지 않는 경우를 **말한다** — 조용히 버리면 "왜 학습이 또 처음부터인가"
        에 답할 수 없다.
        """
        out = {'input': 0, 'skill': 0, 'hist': 0, 'prev': False, 'skipped': None}
        if not isinstance(blob, dict) or not blob:
            out['skipped'] = 'none'
            return out
        # 옛 판(v1: 항목에 시각·H스텝 이력이 없다)도 받는다 — 버리면 이미 쌓인 창을
        # 업데이트 한 번에 잃는다. 시각이 없는 항목은 연속 여부를 판단하지 않는다.
        if int(blob.get('v') or 0) not in _ACCEPTED_SCHEMAS:
            out['skipped'] = 'schema'
            return out
        saved_dt = blob.get('dt')
        if saved_dt is None or abs(float(saved_dt) - float(dt)) > max(1e-6, 0.01 * float(dt)):
            out['skipped'] = 'cycle_changed'
            return out
        age = time.time() - float(blob.get('saved_at') or 0.0)
        if age > PERSIST_MAX_AGE_S:
            out['skipped'] = 'too_old'
            return out

        for ent in (blob.get('input') or []):
            try:
                state, ext, cmds = ent[0], ent[1], ent[2]
                ts = ent[3] if len(ent) > 3 else None
                st = tuple(float(x) for x in state)
                ex = {k: (None if v is None else float(v))
                      for k, v in zip(_EXT_KEYS, ext)}
                cm = {k: float(v) for k, v in zip(_CMD_KEYS, cmds)}
            except Exception:
                continue          # 한 줄이 깨졌다고 창을 통째로 버리지 않는다
            self._input_buf.append((st, ex, cm, None if ts is None else float(ts)))
            out['input'] += 1
        # 사이클 하나를 넘게 쉬었으면 "이어지는 것"(H스텝 이력·직전 예측)은 버린다.
        #   그 둘은 **연속**을 전제로 하기 때문이다. 학습 창은 전이마다 시각으로
        #   따로 가리므로 그대로 이어받는다.
        continuous = age <= max(2.0, 1.5 * float(dt))
        if continuous:
            for row in (blob.get('hist') or []):
                try:
                    state, ext, cmds, h_dt, reg = row
                    self._hist.append({
                        'state': tuple(float(x) for x in state),
                        'ext': {k: (None if v is None else float(v))
                                for k, v in zip(_EXT_KEYS, ext)},
                        'cmds': {k: float(v) for k, v in zip(_CMD_KEYS, cmds)},
                        'dt': float(h_dt),
                        'regime': REGIMES[int(reg)] if 0 <= int(reg) < len(REGIMES)
                        else 'mild_day',
                    })
                    out['hist'] += 1
                except Exception:
                    continue
            prev = blob.get('prev') or []
            if len(prev) == 5:
                (self._prev_T, self._prev_RH, self._prev_CO2,
                 self._prev_pred_T, self._prev_pred_RH) = [
                    None if v is None else float(v) for v in prev]
                out['prev'] = True
        for row in (blob.get('skill') or []):
            try:
                idx, eTm, eTp, eHm, eHp = row
                reg = REGIMES[int(idx)]
            except Exception:
                continue
            self._skill.append((reg, float(eTm), float(eTp), float(eHm), float(eHp)))
            out['skill'] += 1
        return out

    def fit_window(self, dt: Optional[float] = None):
        """학습용 (states, exts, cmds, valid) 반환.

        states 는 입력 버퍼의 상태(t=0..N), exts/cmds 는 각 전이의 입력(t=0..N-1),
        `valid[i]` 는 **i 번째 이웃 쌍이 진짜 한 사이클 전이인가**다. 재시작이나
        센서 끊김으로 사이에 구멍이 나면 False 이고, 학습은 그 쌍을 건너뛴다 —
        건너뛰지 않으면 "두 시간이 한 사이클 만에 흘렀다" 는 전이가 섞여 계수를
        끌어당긴다. 시각이 없는 옛 저장분은 판단하지 않고 유효로 본다(예전 동작).
        샘플 부족 시 빈 시퀀스.
        """
        buf = list(self._input_buf)
        if len(buf) < 2:
            return [], [], [], []
        states = [b[0] for b in buf]              # N+1 states
        exts   = [b[1] for b in buf[:-1]]         # N exts (마지막 전이 입력 제외)
        cmds   = [b[2] for b in buf[:-1]]         # N cmds
        valid  = []
        for a, b in zip(buf, buf[1:]):
            ta = a[3] if len(a) > 3 else None
            tb = b[3] if len(b) > 3 else None
            if dt is None or ta is None or tb is None:
                valid.append(True)
                continue
            valid.append(abs((tb - ta) - dt) <= max(2.0, 0.25 * dt))
        return states, exts, cmds, valid
