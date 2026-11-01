# coding=utf-8
"""TwinOutput → `env_twin*` 점들 (계약 §6·§10.4). 채널 번호는 계약 문서가 정본이다.
여기서 바꾸지 말고 문서를 먼저 고친 뒤 맞춘다. 채널은 추가만 한다."""
from __future__ import annotations

import math
from typing import Dict, List, Sequence

from .expiry import is_expired  # noqa: F401  (소비자 편의 재노출)
from .types import Point, TargetKind, TwinOutput

PCTL = ("p10", "p50", "p90")

# ── 시설 (계약 §6) ──────────────────────────────────────────────
FACILITY_Q = {"T": 0, "RH": 10, "VPD": 20, "CO2": 30}           # 기준 채널 + (0,1,2)
FACILITY_EVENTS = {"condensation": 50, "heat": 51, "frost": 52, "humid": 53}
FACILITY_META = {"status": 0, "valid_until": 1, "horizon_h": 2, "ensemble_size": 3,
                 "sync_rmse_T": 4, "sync_rmse_RH": 5, "sync_rmse_T_1h": 6, "coverage_80": 7,
                 "stale_s": 8, "model_rev": 9, "policy": 10, "weather_src": 11,
                 # 계보(데이터 관리 D3): 쓴 예보의 받은 시각 · 보정 판(0 원본) · 관측 출처 코드(1 실측 2 미러 3 가상 0 미확인)
                 "fc_issue_epoch": 12, "fc_cal_rev": 13, "obs_origin": 14,
                 # 시나리오·장치 효과(D7, 소유: 장치 효과 세션): 미래 입력 방식(0 hold 1 schedule 2 what-if) ·
                 # 반영한 장치 수 · 반영 못 한 장치 수(0 보다 크면 그래프가 '효과 미반영' 배지)
                 "plan_src": 15, "effects_modeled": 16, "effects_unmodeled": 17}
FACILITY_LEAD_H = (1, 3, 6, 12, 24, 48)
FACILITY_GRID_S = 600

# ── 노지 (계약 §10.4) ───────────────────────────────────────────
FIELD_DAILY_Q = {"theta_root": 0, "Dr": 10, "Ks": 20, "Ts1": 30, "Tmin": 40, "GDD": 50,
                 "theta_sensor": 90}             # 90~92: 센서 칸 관측 예측(센서 %, 2026-10-20 추가)
FIELD_DAILY_P50_ONLY = {"fc": 60, "recommended_irrigation": 80}
FIELD_DAILY_EVENTS = {"water_deficit": 70, "water_deficit_severe": 71, "frost": 72,
                      "disease": 73, "waterlogging": 74}
FIELD_HOURLY_Q = {"T": 0}
FIELD_HOURLY_P50_ONLY = {"ground_min": 12}
FIELD_HOURLY_EVENTS = {"frost": 10, "leaf_wet": 11}
FIELD_META = {"status": 0, "valid_until": 1, "horizon_d": 2, "ensemble_size": 3,
              "sync_rmse_theta_1d": 4, "sync_rmse_Ts_1d": 5, "coverage_80": 7,
              "stale_s": 8, "model_rev": 9, "obs_n": 20, "obs_age_s": 21,
              "irrigation_known": 22, "rain_src": 23, "texture_src": 24, "grid_rev": 25,
              "rain_fc_days": 26,
              # 계보(D3) — 시설 12~14 와 같은 뜻
              "fc_issue_epoch": 27, "fc_cal_rev": 28, "obs_origin": 29,
              # 시설 15~17 과 같은 뜻(D7)
              "plan_src": 30, "effects_modeled": 31, "effects_unmodeled": 32,
              # 그래프 기준선(θ_root 와 같은 단위 %): 포장용수량 · 위조점 · 물 부족 문턱(Ks<1 시작)
              "theta_fc": 33, "theta_wp": 34, "theta_thr": 35,
              # 발행 때의 관측식 θ_sensor = a·θ_layer·100 + b 계수(센서가 있을 때) — 기준선을 센서 단위로 옮긴다
              "obs_a": 36, "obs_b": 37}
FIELD_LEAD_D = (1, 3, 7)
FIELD_LEAD_Q_BASES = {0, 10, 20, 30, 40, 90}  # 계약 §10.4: 0~2,10~12,20~22,30~32,40~42,90~92 + 70~74

M_FAC, M_FAC_LEAD, M_FAC_META = "env_twin", "env_twin_lead", "env_twin_meta"
M_FLD, M_FLD_H, M_FLD_LEAD, M_FLD_META = (
    "env_twin_field", "env_twin_field_h", "env_twin_field_lead", "env_twin_field_meta")
# ── 시나리오·분석 이력·작동 시계열 (D7, 설계 §6.3~§6.5) ──────────────────────────
#: 시나리오 곡선 — 기본 예측과 채널 배치·격자·분위수가 같고 태그 `scenario` 만 더한다.
M_FAC_SCN, M_FLD_SCN, M_FLD_SCN_H = "env_twin_scn", "env_twin_scn_field", "env_twin_scn_field_h"
#: 분석 이력(동기화로 맞춘 과거의 최선 추정) — 발행 시각 `t0` 앞의 시각만, 새 발행이 같은 시각을 덮는다.
M_FAC_POST, M_FLD_POST, M_FLD_POST_H = "env_twin_post", "env_twin_field_post", "env_twin_field_post_h"
#: 작동 시계열 — 효과 채널 값(L3 파생). 원천(장치 기록)을 복사하지 않는다.
M_ACT = "env_twin_act"

BASELINE = "baseline"                         # 예약어: 시나리오 태그가 없는 기본 예측
SCENARIO_OF = {M_FAC: M_FAC_SCN, M_FLD: M_FLD_SCN, M_FLD_H: M_FLD_SCN_H}
POST_OF = {M_FAC: M_FAC_POST, M_FLD: M_FLD_POST, M_FLD_H: M_FLD_POST_H}

#: 분석 이력 채널 — 시설은 `env_twin` 의 T·RH·VPD·CO2 와 같고, 노지 일 격자는 θ_root·Dr·Ks·Ts1·Tmin·센서 칸 관측
#: (GDD 는 누적이라 뺀다), 시 격자는 구획 기온. 모두 사후 p10/p50/p90.
FACILITY_POST_Q = dict(FACILITY_Q)
FIELD_POST_DAILY_Q = {k: v for k, v in FIELD_DAILY_Q.items() if k != "GDD"}
FIELD_POST_HOURLY_Q = dict(FIELD_HOURLY_Q)

#: 작동 시계열 태그 `basis`(과거는 위로 갈수록 믿을 만하다, 미래는 plan) · 효과 채널 이름(시설 %, 노지 mm)
ACT_BASES = ("actual", "duty_log", "command", "assumed", "plan")
ACT_EFFECTS_FACILITY = ("vent", "heat", "cool", "fog", "co2_inj", "shade", "curtain", "light")
ACT_EFFECTS_FIELD = ("irrigation_mm",)
ACT_ALL_DEVICES = "all"                        # 태그 `dev`: 합친 값. 장치별 펼침은 장치 uuid

#: 트윈이 쓰는 측정 전부 — 읽기 API(`/api/twin/series`)가 이 밖의 측정은 422 로 막는다.
MEASUREMENTS = frozenset((M_FAC, M_FAC_LEAD, M_FAC_META, M_FLD, M_FLD_H, M_FLD_LEAD, M_FLD_META,
                          M_FAC_SCN, M_FLD_SCN, M_FLD_SCN_H, M_FAC_POST, M_FLD_POST, M_FLD_POST_H))
#: 채널 번호로 읽는 계열(`/api/twin/series`)에서 시나리오·분석 이력 이름을 허용하는 짝.
SCENARIO_MEASUREMENTS = frozenset(SCENARIO_OF.values())
POST_MEASUREMENTS = frozenset(POST_OF.values())


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _monotone(trio: Dict[str, Sequence[float]], i: int):
    """p10 ≤ p50 ≤ p90 를 강제한다(계약 §5, 교차 금지). 없는 분위수는 건너뛴다."""
    vals = [(k, trio[k][i]) for k in PCTL if k in trio and _ok(trio[k][i])]
    srt = sorted(v for _, v in vals)
    return {k: s for (k, _), s in zip(vals, srt)}


def _quantile_points(meas, dev, tags, times, qmap, bases, indices=None, extra=None) -> List[Point]:
    pts: List[Point] = []
    tg = dict(tags, **(extra or {}))
    for var, trio in qmap.items():
        base = bases.get(var)
        if base is None:
            continue
        for i in (range(len(times)) if indices is None else indices):
            for pk, v in _monotone(trio, i).items():
                pts.append(Point(meas, dev, base + PCTL.index(pk), times[i], float(v), tg))
    return pts


def _p50_points(meas, dev, tags, times, qmap, bases, indices=None, extra=None) -> List[Point]:
    pts: List[Point] = []
    tg = dict(tags, **(extra or {}))
    for var, base in bases.items():
        trio = qmap.get(var)
        if not trio or "p50" not in trio:
            continue
        for i in (range(len(times)) if indices is None else indices):
            v = trio["p50"][i]
            if _ok(v):
                pts.append(Point(meas, dev, base, times[i], float(v), tg))
    return pts


def _event_points(meas, dev, tags, times, ev, bases, indices=None, extra=None) -> List[Point]:
    pts: List[Point] = []
    tg = dict(tags, **(extra or {}))
    for name, base in bases.items():
        seq = ev.get(name)
        if seq is None:
            continue
        for i in (range(len(times)) if indices is None else indices):
            if _ok(seq[i]):
                pts.append(Point(meas, dev, base, times[i], float(min(1.0, max(0.0, seq[i]))), tg))
    return pts


def _meta_points(meas, dev, tags, t0, meta, table) -> List[Point]:
    return [Point(meas, dev, ch, t0, float(meta[k]), tags)
            for k, ch in table.items() if k in meta and _ok(meta[k])]


def flatten(out: TwinOutput) -> List[Point]:
    """한 발행을 점 목록으로 푼다. 머리말은 마지막에 둔다 — 곡선이 다 쓰이기 전에 머리말이 먼저
    보이면 소비자가 반쯤 쓰인 곡선을 읽는다(계약 §7-4: 머리말을 먼저 읽고 곡선을 읽는다)."""
    dev = out.target_id
    if out.kind == TargetKind.FACILITY:
        tags = {"facility": out.facility} if out.facility else {}
        g = out.grids.get("fast", [])
        q = out.quantiles.get("fast", {})
        ev = out.events.get("fast", {})
        pts = _quantile_points(M_FAC, dev, tags, g, q, FACILITY_Q)
        pts += _event_points(M_FAC, dev, tags, g, ev, FACILITY_EVENTS)
        step = FACILITY_GRID_S
        for lead in FACILITY_LEAD_H:
            k = int(lead * 3600 // step)
            if k < len(g):
                x = {"lead_h": str(lead)}
                pts += _quantile_points(M_FAC_LEAD, dev, tags, g, q, FACILITY_Q, [k], x)
                pts += _event_points(M_FAC_LEAD, dev, tags, g, ev, FACILITY_EVENTS, [k], x)
        pts += _meta_points(M_FAC_META, dev, tags, out.t0, out.meta, FACILITY_META)
        return pts

    tags = {"target": "field"}
    pts = []
    d = out.grids.get("daily", [])
    if len(d):
        q, ev = out.quantiles.get("daily", {}), out.events.get("daily", {})
        pts += _quantile_points(M_FLD, dev, tags, d, q, FIELD_DAILY_Q)
        pts += _p50_points(M_FLD, dev, tags, d, q, FIELD_DAILY_P50_ONLY)
        pts += _event_points(M_FLD, dev, tags, d, ev, FIELD_DAILY_EVENTS)
        lead_q = {v: t for v, t in q.items() if FIELD_DAILY_Q.get(v) in FIELD_LEAD_Q_BASES}
        for lead in FIELD_LEAD_D:
            if lead < len(d):
                x = {"lead_d": str(lead)}
                pts += _quantile_points(M_FLD_LEAD, dev, tags, d, lead_q, FIELD_DAILY_Q, [lead], x)
                pts += _event_points(M_FLD_LEAD, dev, tags, d, ev, FIELD_DAILY_EVENTS, [lead], x)
    h = out.grids.get("hourly", [])
    if len(h):
        q, ev = out.quantiles.get("hourly", {}), out.events.get("hourly", {})
        pts += _quantile_points(M_FLD_H, dev, tags, h, q, FIELD_HOURLY_Q)
        pts += _p50_points(M_FLD_H, dev, tags, h, q, FIELD_HOURLY_P50_ONLY)
        pts += _event_points(M_FLD_H, dev, tags, h, ev, FIELD_HOURLY_EVENTS)
    pts += _meta_points(M_FLD_META, dev, tags, out.t0, out.meta, FIELD_META)
    return pts


def flatten_scenario(out: TwinOutput, scenario_id: str) -> List[Point]:
    """시나리오 한 건의 곡선을 점 목록으로 푼다 — 기본 예측(`flatten`)과 채널·격자·분위수가 같고 측정 이름만
    `env_twin_scn*` 이며 태그 `scenario` 가 붙는다(설계 §6.3). 검증 보관본(`*_lead`)과 머리말은 없다 — 계보는
    시나리오 레코드(SQLite)가 가진다. `device_id` 는 기본 예측과 같은 대상 id 라 구획 삭제 때 같이 치워진다."""
    sid = str(scenario_id)
    if not sid or sid == BASELINE:
        raise ValueError("scenario id is reserved or empty")
    dev = out.target_id
    extra = {"scenario": sid}
    if out.kind == TargetKind.FACILITY:
        tags = {"facility": out.facility} if out.facility else {}
        g = out.grids.get("fast", [])
        q = out.quantiles.get("fast", {})
        ev = out.events.get("fast", {})
        pts = _quantile_points(M_FAC_SCN, dev, tags, g, q, FACILITY_Q, extra=extra)
        return pts + _event_points(M_FAC_SCN, dev, tags, g, ev, FACILITY_EVENTS, extra=extra)
    tags = {"target": "field"}
    pts = []
    d = out.grids.get("daily", [])
    if len(d):
        q, ev = out.quantiles.get("daily", {}), out.events.get("daily", {})
        pts += _quantile_points(M_FLD_SCN, dev, tags, d, q, FIELD_DAILY_Q, extra=extra)
        pts += _p50_points(M_FLD_SCN, dev, tags, d, q, FIELD_DAILY_P50_ONLY, extra=extra)
        pts += _event_points(M_FLD_SCN, dev, tags, d, ev, FIELD_DAILY_EVENTS, extra=extra)
    h = out.grids.get("hourly", [])
    if len(h):
        q, ev = out.quantiles.get("hourly", {}), out.events.get("hourly", {})
        pts += _quantile_points(M_FLD_SCN_H, dev, tags, h, q, FIELD_HOURLY_Q, extra=extra)
        pts += _p50_points(M_FLD_SCN_H, dev, tags, h, q, FIELD_HOURLY_P50_ONLY, extra=extra)
        pts += _event_points(M_FLD_SCN_H, dev, tags, h, ev, FIELD_HOURLY_EVENTS, extra=extra)
    return pts


def _before(times: Sequence[float], t0: float) -> List[int]:
    return [i for i, t in enumerate(times) if float(t) < float(t0)]


def flatten_post(out: TwinOutput) -> List[Point]:
    """분석 이력 — 발행 시각 `t0` **앞** 시각의 최선 추정(필터·평활 뒤)만 점으로 푼다(설계 §6.4).
    `out.grids`·`quantiles` 는 기본 예측과 같은 모양이고 미래 구간(`t ≥ t0`)은 버린다 — 미래는 예측(`env_twin*`)의 몫이다.
    사건 확률·머리말은 없다. 새 발행이 같은 대상 시각을 다시 추정하면 같은 키라 덮어쓴다(최신 추정이 이긴다)."""
    dev = out.target_id
    if out.kind == TargetKind.FACILITY:
        tags = {"facility": out.facility} if out.facility else {}
        g = out.grids.get("fast", [])
        return _quantile_points(M_FAC_POST, dev, tags, g, out.quantiles.get("fast", {}), FACILITY_POST_Q,
                                _before(g, out.t0))
    tags = {"target": "field"}
    pts: List[Point] = []
    d = out.grids.get("daily", [])
    if len(d):
        pts += _quantile_points(M_FLD_POST, dev, tags, d, out.quantiles.get("daily", {}), FIELD_POST_DAILY_Q,
                                _before(d, out.t0))
    h = out.grids.get("hourly", [])
    if len(h):
        pts += _quantile_points(M_FLD_POST_H, dev, tags, h, out.quantiles.get("hourly", {}), FIELD_POST_HOURLY_Q,
                                _before(h, out.t0))
    return pts


def act_points(kind: TargetKind, target_id: str, effect: str, basis: str, times: Sequence[float],
               values: Sequence[float], scenario: str = BASELINE, dev: str = ACT_ALL_DEVICES) -> List[Point]:
    """작동 시계열 한 계열을 점으로 푼다(설계 §6.5). 값은 효과 채널 값 — 시설 정시 평균 개도 %, 노지 `irrigation_mm`
    은 시 격자의 그 한 시간 mm. `device_id` 는 대상 id(구획 삭제 때 같이 치워진다), `channel` 태그는 쓰지 않는다."""
    effects = ACT_EFFECTS_FIELD if kind == TargetKind.FIELD else ACT_EFFECTS_FACILITY
    if effect not in effects:
        raise ValueError("unknown effect channel: %s" % effect)
    if basis not in ACT_BASES:
        raise ValueError("unknown basis: %s" % basis)
    tags = {"target": str(target_id), "effect": effect, "basis": basis,
            "scenario": str(scenario or BASELINE), "dev": str(dev or ACT_ALL_DEVICES)}
    return [Point(M_ACT, str(target_id), None, float(t), float(v), tags)
            for t, v in zip(times, values) if _ok(v)]


def run_act_points(out: TwinOutput, act: Sequence, scenario: str = BASELINE, plan_only: bool = False) -> List[Point]:
    """실행 결과의 작동 시계열 계열(`RunResult.act`, `twin_effects.scenario.ActSeries`) → `env_twin_act` 점.
    시나리오는 앞날(`plan`)만 쓴다(`plan_only`) — 과거는 기본 예측의 계열을 그래프가 이어 읽는다. 쓸 수 없는 효과 이름은 건너뛴다."""
    pts: List[Point] = []
    for a in act or ():
        if plan_only and a.basis != "plan":
            continue
        try:
            pts += act_points(out.kind, out.target_id, a.effect, a.basis, a.times, a.values, scenario,
                              getattr(a, "dev", ACT_ALL_DEVICES))
        except ValueError:
            continue
    return pts


META_MEASUREMENT = {TargetKind.FACILITY: (M_FAC_META, FACILITY_META),
                    TargetKind.FIELD: (M_FLD_META, FIELD_META)}


def publications(points: Sequence[Point]) -> List[Dict[str, float]]:
    """점 목록(머리말 포함)에서 발행 요약 `[{family, id, t0, status, valid_until}]`.

    원격 쓰기는 조각(2,000 점)으로 나뉘어 머리말이 마지막 조각에만 실린다(머리말은 곡선 뒤).
    받는 쪽은 조각마다 이 요약으로 유효기한을 검사한다(참조 구현 aot/twin/contract_check.py) —
    Influx 에는 쓰지 않는다.
    """
    fam_of = {M_FAC_META: ("facility", FACILITY_META), M_FLD_META: ("field", FIELD_META)}
    acc: Dict[tuple, Dict[str, float]] = {}
    for p in points:
        if p.measurement not in fam_of:
            continue
        fam, table = fam_of[p.measurement]
        rec = acc.setdefault((fam, p.device_id), {"family": fam, "id": p.device_id,
                                                  "t0": float(p.timestamp)})
        if p.channel == table["status"]:
            rec["status"] = float(p.value)
        elif p.channel == table["valid_until"]:
            rec["valid_until"] = float(p.value)
    return list(acc.values())
