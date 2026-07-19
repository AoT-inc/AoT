# coding=utf-8
"""
greybox/identification.py — 그레이박스 파라미터 배치 추정.

알고리즘: scipy.optimize.least_squares (Levenberg-Marquardt) + 물리 bound
입력:   최근 N 사이클의 (state_seq, ext_seq, cmds_seq) 시계열
출력:   업데이트된 GreyboxParams

일별 02:00 또는 N_MIN_SAMPLES 이상 누적 시 호출.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .model import step
from .params import GreyboxParams

logger = logging.getLogger(__name__)

N_MIN_SAMPLES = 120   # 최소 샘플 수 (60s 사이클 × 120 = 2시간)


def fit(
    states: List[tuple],   # [(T_int, RH_int, CO2_int)] N+1 개 (t=0..N)
    exts:   List[dict],    # [ext_dict] N 개 (t=0..N-1)
    cmds:   List[dict],    # [cmds_dict] N 개
    dt: float = 60.0,
    prev_params: Optional[GreyboxParams] = None,
    max_iter: int = 50,
    prior_weight: float = 0.05,
) -> Optional[GreyboxParams]:
    """배치 least-squares 파라미터 추정.

    온도식은 dT ∝ 1/(tau_T·UA_eff) 형태의 스케일 비식별성을 가져, 데이터만으로는
    여러 계수 조합이 같은 예측을 낸다(예측·민감도는 보존되나 개별 계수가 표류).
    이를 막기 위해 prior(prev_params 또는 물리 기본값) 대비 상대 편차에 작은 릿지
    패널티를 더해 영공간 표류를 제거하고 RH 결합 계수가 물리적으로 유지되게 한다.
    prior_weight=0 이면 순수 데이터 적합.

    Returns updated GreyboxParams, or None if insufficient data / fit failed.
    """
    N = len(exts)
    if N < N_MIN_SAMPLES or len(states) < N + 1:
        logger.debug('greybox.fit: 샘플 부족 (%d < %d)', N, N_MIN_SAMPLES)
        return None

    try:
        from scipy.optimize import least_squares
    except ImportError:
        logger.warning('greybox.fit: scipy 없음 — 설치 필요')
        return None

    p0 = prev_params or GreyboxParams()

    # 파라미터 이름과 초기값 벡터
    param_keys = ['UA_eff', 'alpha_sol', 'Q_heat', 'Q_cool', 'm_vent_coef',
                  'Q_plant_base', 'tau_T', 'K_RH_vent', 'K_CO2_inj']
    x0 = [getattr(p0, k) for k in param_keys]
    bounds_lo = [p0.BOUNDS[k][0] for k in param_keys]
    bounds_hi = [p0.BOUNDS[k][1] for k in param_keys]

    # 릿지 prior: 각 계수의 prior 값(0 보호)과 가중치
    prior_vec   = [max(abs(getattr(p0, k)), 1e-6) for k in param_keys]
    ridge_scale = (prior_weight * N) ** 0.5 if prior_weight > 0 else 0.0

    def residuals(x):
        p = _vec_to_params(x, param_keys, p0)
        res = []
        for i in range(N):
            T, RH, CO2 = states[i]
            T_pred, RH_pred, CO2_pred = step(T, RH, CO2, exts[i], cmds[i], p, dt)
            T_true, RH_true, CO2_true = states[i + 1]
            # 온도 오차 가중 ×1, RH ÷5 (단위 스케일 보정), CO2 ÷100
            res.extend([
                (T_pred - T_true),
                (RH_pred - RH_true) / 5.0,
                (CO2_pred - CO2_true) / 100.0,
            ])
        # 릿지 패널티: prior 대비 상대 편차 (영공간 표류 억제). 데이터 항(3N개)에
        # 비해 작도록 sqrt(prior_weight·N) 로 스케일.
        if ridge_scale > 0.0:
            for xi, pri in zip(x, prior_vec):
                res.append(ridge_scale * (xi - pri) / pri)
        return res

    try:
        result = least_squares(
            residuals, x0,
            bounds=(bounds_lo, bounds_hi),
            method='trf',
            max_nfev=max_iter * len(x0),
            ftol=1e-4, xtol=1e-4,
        )
    except Exception as exc:
        logger.warning('greybox.fit 실패: %s', exc)
        return None

    if not result.success and result.cost > 1e6:
        logger.warning('greybox.fit 수렴 실패 (cost=%.1f)', result.cost)
        return None

    new_p = _vec_to_params(result.x, param_keys, p0)
    new_p.n_updates = getattr(p0, 'n_updates', 0) + 1

    # RMSE 계산 — 데이터 잔차(앞 3N개)만 사용(끝의 릿지 패널티 제외)
    final_res = residuals(result.x)[:3 * N]
    if N > 0:
        import math
        new_p.rmse_T  = math.sqrt(sum(r**2 for r in final_res[0::3]) / N)
        new_p.rmse_RH = math.sqrt(sum(r**2 for r in final_res[1::3]) / N) * 5.0

    logger.info(
        'greybox.fit 완료: n=%d rmse_T=%.3f rmse_RH=%.3f',
        N, new_p.rmse_T, new_p.rmse_RH)
    return new_p


def _vec_to_params(x, keys, base: GreyboxParams) -> GreyboxParams:
    import copy
    p = copy.copy(base)
    for k, v in zip(keys, x):
        setattr(p, k, float(v))
    p.clamp()
    return p
