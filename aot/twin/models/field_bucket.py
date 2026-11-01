# coding=utf-8
"""노지 물 수지 모델(`aot.functions.utils.field_twin`)을 트윈 노드의 부품으로 끼운다 (원칙 6).

모델·필터 코드는 그대로 import 한다(원칙 3 — 두 벌이 되지 않게). 여기는 배선만 한다:

    설정의 계열(TargetSpec.inputs) ──읽기──▶ 일 격자 입력(비·ET0·기온) + 센서 관측(00 시 ±2 h)
        ──▶ FieldEnKF 로 심은 날(또는 options.spinup_from)부터 오늘 00 시까지 동화
        ──▶ run_ahead 로 +14 일(신뢰 7 일) 앙상블 → 분위수·사건 확률 → TwinOutput(daily)

**출처는 사용자가 고른다**(계획서 §9.5.1 · 사용자 지침 2026-10-19). 이 모듈은 외부 API 를 부르지
않는다. 비·기온·ET0 는 모두 설정이 가리키는 **AoT 측정 계열**(사용자가 등록한 입력)에서 읽는다.
기상청 관측소든 NASA POWER 입력이든 같은 길로 들어오고, 무엇인지는 `options.rain.kind` 로 적는다.

배선 (TargetSpec.inputs 의 논리 이름)

| 이름 | 뜻 | 필수 |
|---|---|---|
| `theta`  | 토양수분 센서 채널(센서 %). 출처 표시가 `measured` 여야 한다(엔진이 검사) | 예 |
| `rain`   | 비. `options.rain.agg` 로 묶는 법을 정한다 | 예 (계약 §10.5 b) |
| `t_air`  | 기온(°C). 지온·적산온도, ET0 가 없을 때 Hargreaves | ET0 계열이 없으면 예 |
| `et0`    | 기준증발산(mm/일) — 예: NASA POWER 입력의 ET0 채널 | 아니오 |
| `soil_t` | 같은 센서의 토양온도 — 센서 위치 변화 감지(계약 §10.5) | 아니오 |

options (기본값은 김제 A 들깨 1구 재현 §9.5 의 값과 같다 — 어느 것도 지역을 가정하지 않는다)

    planted_on      "YYYY-MM-DD" 정식·파종일(구획 started_on). 필수
    spinup_from     동화 시작일(기본 planted_on)
    timezone        구획 시간대(IANA, 기본 "UTC") — 일 격자 경계(계약 §10.3)
    lat, elevation_m  Hargreaves·ET0 용(구획 좌표). lat 은 ET0 계열이 없을 때 필수
    crop            "perilla" 등 params.CROPS 이름(기본 perilla)
    texture         사전 토성(기본 loam)
    sensor          {"layer": 1, "a": 1.3, "b": 0.0, "r_sd": 1.5}
    rain            {"agg": "hourly_mean_sum"|"daily_sum"|"daily_last", "scale": 1.0,
                     "kind": "station"|"gauge"|"reanalysis", "max_lag_d": 2}
                    max_lag_d = 비 계열이 이만큼 늦어도 쓴다(재분석은 며칠 늦게 채워진다 — 그 뒤 날은 0 mm)
                    hourly_mean_sum = 시간마다 평균 × scale 을 하루 합(15 분 강수를 5 분마다
                    되읽는 기상청 입력은 scale 4). daily_last = 하루 한 값(재분석 입력).
    members, rain_log_sd, shift_gate_sigma   EnKF (기본 128 · 0.35 · 3.0 — §9.5 수치를 낸 값)
    sync_window_d   sync_rmse_theta_1d·coverage_80 를 재는 최근 일수(기본 14)
    irrigated       관수 구획이면 true → 관수 모름(irrigation_known=0)이라 최대 degraded
    effects         {"devices": [{"id": 출력 id, "kind": 역할|null}]} — 이 구획 대지의 노지 출력 명단(위치로 읽고 사용자가 고른 역할).
                    기본 예측에는 아직 연결되지 않아(노지 관수 연결은 E3) 머리말 `effects_unmodeled` 로 센다.
    scenario        {"overrides": {...}, "id": "<시나리오 id>"} — what-if 실행(`twin_effects.scenario`). 같은 동기화·같은 시드로
                    돌리고 **앞날**의 관수(`irrigation_mm`)·비·ET0·기온에만 가정을 건다(하루 단위). 머리말 `plan_src` = 2.

센서 없는 구획(`theta` 미배선): 기본은 **관측 없이 모델만** 돌린다(`options.sensorless` = "predict", 기본). 심은 날부터
비·ET0·기온으로 물 수지만 굴리고(동기화 없음, 초기값은 토성의 포장용수량 근방), 앙상블 띠는 사전분포에서 시작해 넓다.
발행은 늘 `degraded` 이고 머리말 `obs_n` = 0 — 지도는 이것을 '관측 없음 — 참고용' 으로 구분한다. `"off"` 면 예전처럼
`not_twinnable`. 측정 센서가 있는 구획과 같은 부품·같은 출력 모양이다(`theta_sensor` 곡선만 없다).

앞날 입력: `options.forecast_series`(`{"site": 대지}`)가 가리키는 **대지 예보 계열**(서버 `geo.forecast_series.read` —
지도 날씨 독·AI 예보와 같은 출처)의 일 행을 앞날 비·ET0·기온으로 쓴다. 손으로 적은 `options.forecast` 사다리(forecast.py)는
개발용 덮어쓰기 JSON 에서만 쓴다.
신뢰 구간(오늘~+7 일) 전체에 예보 비가 있으면 발행은 `ok`, 하나라도 없으면 그 날을 '비 없음' 으로 메우고
`degraded`(계약 §7: 예보 대체). 예보가 점 하나라 앙상블 대신 비 배율 오차(리드가 길수록 커짐)로 불확실성을 둔다.
예보가 없으면 예전과 같다 — 앞으로 비 없음, ET0·기온은 최근 7 일 평균(`degraded`).
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from aot.functions.utils.field_twin import FieldBucketModel, FieldEnKF, FieldPrior, SensorSpec
from aot.functions.utils.field_twin import forcing as fz, validity as vz
from aot.functions.utils.field_twin.model import MODEL_REV

from .. import forecast as FC, lineage as LG, output as O
from ..expiry import valid_until_for
from ..types import Status, TargetKind, TargetSpec, TwinOutput
from . import registry

logger = logging.getLogger(__name__)

HORIZON_D = 14                 # 계약 §10.3 일 격자 k = 0…14
TRUST_D = 7
RAIN_SRC = {"forecast": 1, "station": 2, "gauge": 3, "reanalysis": 4}    # meta rain_src (계약 §10.4)
SYNC_WINDOW_D = 14             # sync_rmse_theta_1d · coverage_80 를 재는 최근 일수


def sensorless(spec: TargetSpec) -> bool:
    """토양수분 센서 없이 모델만 돌리는 구획인가 — `theta` 가 없고 `options.sensorless` 가 "off" 가 아닐 때."""
    return "theta" not in spec.inputs and str(spec.options.get("sensorless", "predict")) != "off"


def _tz_offset_s(tz: str, at: float) -> float:
    try:
        from zoneinfo import ZoneInfo
        off = _dt.datetime.fromtimestamp(at, ZoneInfo(tz)).utcoffset()
        return off.total_seconds() if off is not None else 0.0
    except Exception:
        logger.warning("트윈 노지: 시간대 %r 를 모른다 — UTC 로 본다", tz)
        return 0.0


def _day_of(datestr: str) -> int:
    y, m, d = (int(x) for x in str(datestr)[:10].split("-"))
    return fz.day_number(y, m, d)


def daily_rain(times: Sequence[float], values: Sequence[float], tz: float, agg: str,
               scale: float) -> Dict[int, float]:
    """비 계열 → 현지 날짜 → mm. 묶는 법은 설정이 정한다(입력마다 기록 방식이 다르다)."""
    if agg == "daily_last":
        out: Dict[int, float] = {}
        for t, v in zip(times, values):
            if v is not None and math.isfinite(v):
                out[int(math.floor((t + tz) / 86400.0))] = float(v) * scale
        return out
    if agg == "daily_sum":
        return {d: s for d, (s, _n) in fz.daily_sum(zip(times, values), tz, scale).items()}
    # hourly_mean_sum: 시간마다 평균 × scale → 하루 합
    hours: Dict[int, List[float]] = {}
    for t, v in zip(times, values):
        if v is not None and math.isfinite(v):
            hours.setdefault(int(math.floor((t + tz) / 3600.0)), []).append(float(v))
    out = {}
    for h, a in hours.items():
        d = h // 24
        out[d] = out.get(d, 0.0) + float(np.mean(a)) * scale
    return out


def daily_temps(times, values, tz: float, min_hours: int = 18) -> Dict[int, Tuple[float, float, float]]:
    """기온 계열 → 현지 날짜 → (최저, 최고, 평균). 시간 수가 모자란 날은 뺀다."""
    hours: Dict[int, Dict[int, List[float]]] = {}
    for t, v in zip(times, values):
        if v is None or not math.isfinite(v) or not (-60.0 < v < 60.0):
            continue
        h = int(math.floor((t + tz) / 3600.0))
        hours.setdefault(h // 24, {}).setdefault(h, []).append(float(v))
    out = {}
    for d, hs in hours.items():
        if len(hs) < min_hours:
            continue
        hm = [float(np.mean(a)) for a in hs.values()]
        out[d] = (min(hm), max(hm), float(np.mean(hm)))
    return out


class FieldBucketTwin:
    """트윈 노드용 노지 모델 부품. 엔진은 `run_target` 이 있으면 전체 실행을 맡긴다
    (EnKF 는 이력 전체를 동화해야 해서 '마지막 값으로 초기화' 하는 범용 경로가 맞지 않다)."""

    kind = "field"
    model_rev = MODEL_REV
    required_inputs = ("theta",)
    noise_sigma: Dict[str, float] = {}
    dt_nominal_s = 86400.0

    def __init__(self):
        self._m = FieldBucketModel()
        self.state_names = self._m.state_names
        self.param_names = self._m.param_names

    # ── 계약 §10.7 인터페이스(단일 상태 dict) — 엔진의 범용 경로·검사용 ─────────
    def _arr(self, x: Mapping[str, float]) -> np.ndarray:
        return np.array([float(x[n]) for n in self._m.names])

    def _dict(self, a) -> Dict[str, float]:
        return {n: float(v) for n, v in zip(self._m.names, a)}

    def required_for(self, spec: TargetSpec):
        """엔진의 전제 검사용 — 센서 없는 구획(`sensorless`)은 `theta` 를 요구하지 않는다."""
        return () if sensorless(spec) else self.required_inputs

    def init_state(self, target, t0, obs):
        return self._dict(self._m.init_state())

    def step(self, x, u, w, dt_s):
        return self._dict(self._m.step(self._arr(x), u, w, dt_s))

    def observe(self, x, name):
        return float(self._m.observe(self._arr(x), SensorSpec(name)))

    def derived(self, x):
        return {k: float(v) for k, v in self._m.derived(self._arr(x)).items()}

    def risks(self, traj, target):
        return {}

    # ── 실행 ──────────────────────────────────────────────────────────────────
    def run_target(self, spec: TargetSpec, source, cap, now: float, period: float,
                   seed: Optional[int] = None):
        from ..engine import RunResult, unusable
        o = spec.options
        if "rain" not in spec.inputs:
            return unusable(spec, now, period, Status.NOT_TWINNABLE, "비 입력 미배선(계약 §10.5 b)")
        if "planted_on" not in o:
            return unusable(spec, now, period, Status.NOT_TWINNABLE, "planted_on(정식·파종일) 설정 없음")
        if "et0" not in spec.inputs and ("t_air" not in spec.inputs or "lat" not in o):
            return unusable(spec, now, period, Status.NOT_TWINNABLE,
                            "ET0 계열도, 기온+위도(Hargreaves)도 없음")
        from aot.functions.utils.twin_effects import scenario as SC
        scn = None                                                 # what-if 가정(없으면 기본 예측)
        if isinstance(o.get("scenario"), Mapping):
            try:
                scn = SC.parse(o["scenario"].get("overrides"), "field")
            except SC.ScenarioError as e:
                return unusable(spec, now, period, Status.ERROR, "시나리오 가정 오류: %s" % e)
        tz = _tz_offset_s(str(o.get("timezone", "UTC")), now)
        plant = _day_of(o["planted_on"])
        start = _day_of(o["spinup_from"]) if o.get("spinup_from") else plant
        today = int(math.floor((now + tz) / 86400.0))
        if today - start < 3:
            return unusable(spec, now, period, Status.UNSYNCED, "동화할 날이 3 일보다 적다")
        window = now - (start * 86400.0 - tz) + 86400.0

        def read(name):
            if name not in spec.inputs:
                return [], []
            s = source.read_series(spec.inputs[name], window, now)
            return list(s.times), list(s.values)

        free = sensorless(spec)                                    # 관측 없이 모델만(동기화 없음)
        th_t, th_v = read("theta")
        rn_t, rn_v = read("rain")
        ta_t, ta_v = read("t_air")
        e_t, e_v = read("et0")
        st_t, st_v = read("soil_t")

        # 관측: 유효성 검사(계약 §10.5) → 00 시 ±2 h 평균. 키 d = 날 d 를 굴린 뒤(d+1 일 00 시)
        obs: Dict[int, float] = {}
        valid_t: List[float] = []
        moves: set = set()
        if not free:
            ok, _reason = vz.screen_series(th_t, th_v, tz_offset_s=tz)
            obs = {d - 1: v for d, (v, _n) in vz.boundary_means(th_t, th_v, ok, tz).items()}
            if not obs:
                return unusable(spec, now, period, Status.UNSYNCED, "유효한 토양수분 관측 없음")
            valid_t = [t for t, k in zip(th_t, ok) if k]
            moves = set(vz.placement_changes(st_t, st_v, tz)) if st_t else set()

        rcfg = dict(o.get("rain") or {})
        rain = daily_rain(rn_t, rn_v, tz, str(rcfg.get("agg", "hourly_mean_sum")),
                          float(rcfg.get("scale", 1.0)))
        temps = daily_temps(ta_t, ta_v, tz)
        et0: Dict[int, float] = {}
        if e_t:
            et0 = daily_rain(e_t, e_v, tz, "daily_last", 1.0)
        lat = o.get("lat")
        if lat is not None:
            for d, (tn, tx, _tm) in temps.items():
                if d not in et0:
                    doy = fz.date_of(d).timetuple().tm_yday
                    et0[d] = fz.hargreaves_et0(tn, tx, float(lat), doy)
        notes = []
        last_rain_day = max(rain) if rain else None
        max_lag = int(rcfg.get("max_lag_d", 2))
        if last_rain_day is None or last_rain_day < today - 1 - max_lag:
            return unusable(spec, now, period, Status.UNSYNCED, "비 계열이 비었거나 낡음")
        if last_rain_day < today - 1:
            notes.append(f"비 계열 마지막 {fz.date_of(last_rain_day)} — 그 뒤는 0 mm 로 봄")

        scfg = dict(o.get("sensor") or {})
        sens = SensorSpec("theta", layer=int(scfg.get("layer", 1)), a=float(scfg.get("a", 1.3)),
                          b=float(scfg.get("b", 0.0)), r_sd=float(scfg.get("r_sd", 1.5)))
        if free:                                                   # 초기값: 토성의 포장용수량(theta0=None)
            prior = FieldPrior(texture=str(o.get("texture", "loam")))
        else:
            first = obs[min(obs)]
            a0 = float(scfg.get("a", 1.3))
            prior = FieldPrior(texture=str(o.get("texture", "loam")),
                               theta0=[(first - sens.b) / (100.0 * a0)] * 3)
        model = FieldBucketModel(crop=str(o.get("crop", "perilla")))
        n = int(o.get("members", max(int(cap.ensemble_size), 128)))
        f = FieldEnKF(model, [] if free else [sens], n_members=n, prior=prior,
                      seed=int(seed if seed is not None else o.get("seed", 0)),
                      shift_gate_sigma=float(o.get("shift_gate_sigma", 3.0)),
                      rain_log_sd=float(o.get("rain_log_sd", 0.35)))

        et0_default = float(np.mean(list(et0.values()))) if et0 else 3.0
        errs, cover = [], []
        n_missing_et0 = 0
        for d in range(start, today):
            if d not in et0:
                n_missing_et0 += 1
            w = {"rain_mm": rain.get(d, 0.0), "et0_mm": et0.get(d, et0_default),
                 "t_mean": temps[d][2] if d in temps else None, "dap": d - plant}
            f.forecast({"irr_mm": float("nan")}, w)
            if d in moves:
                f.reopen_calibration("theta")
            y = obs.get(d)                                         # 센서 없으면 늘 None
            if y is None:
                continue
            q = f.obs_quantiles("theta")
            if d >= today - int(o.get("sync_window_d", SYNC_WINDOW_D)):
                errs.append(q[1] - y)
                cover.append(q[0] <= y <= q[2])
            f.update({"theta": y})
        if n_missing_et0:
            notes.append(f"ET0 없는 날 {n_missing_et0} 일은 평균 {et0_default:.1f} mm")

        # 앞날: 설정의 예보 사다리(options.forecast)가 있으면 그 값, 없는 날은 비 0 mm·ET0·기온 최근 7 일 평균
        recent = [d for d in range(today - 7, today)]
        et0_f = float(np.mean([et0[d] for d in recent if d in et0])) if any(d in et0 for d in recent) \
            else et0_default
        tm = [temps[d][2] for d in recent if d in temps]
        t_f = float(np.mean(tm)) if tm else None
        n_pts = 1 + int(HORIZON_D * cap.horizon_frac)
        fc = None
        sfc = o.get("forecast_series")
        if not o.get("forecast") and isinstance(sfc, Mapping) and sfc.get("site"):
            fc = _series_forecast(source, str(sfc["site"]), now, tz, today, notes)
        if fc is None:
            # 손으로 적은 사다리(개발용 덮어쓰기 JSON — 명시하면 이긴다)만 이 길로 온다. DB 설정은 대지 예보 계열(위)
            fcfg = o.get("forecast") or {}
            try:
                fc = FC.load(o, source, now, tz, today,
                             tz_override=_tz_offset_s(str(fcfg["timezone"]), now) if fcfg.get("timezone") else None)
            except FC.ForecastConfigError as e:
                return unusable(spec, now, period, Status.NOT_TWINNABLE, f"예보 설정 오류: {e}")
        notes.extend(fc.notes)
        base_sd = float(o.get("rain_log_sd", 0.35))
        t0 = today * 86400.0 - tz                                  # 오늘 00 시(구획 시간대)
        irr_hourly: Dict[float, float] = {}
        irr_day: Dict[int, float] = {}
        if scn is not None:                                        # 관수 가정 → 앞날 일별 mm(시 격자 합)
            irr_hourly = SC.irrigation_hourly(scn)
            irr_day = SC.irrigation_daily(irr_hourly, [t0 + k * 86400.0 for k in range(n_pts - 1)])
        ahead = []
        for k in range(n_pts - 1):
            d = today + k
            w = {"rain_mm": fc.rain_mm.get(d, 0.0), "et0_mm": fc.et0_mm.get(d, et0_f),
                 "t_mean": fc.t_mean.get(d, t_f), "dap": today - plant + k,
                 "u": {"irr_mm": float("nan")}}
            if d in fc.rain_mm:                                   # 예보 비만 리드별 배율 오차를 키운다
                w["rain_log_sd"] = fc.rain_log_sd(k, base_sd)
            if scn is not None:
                ds = t0 + k * 86400.0
                for key, var in (("rain_mm", "rain"), ("et0_mm", "et0"), ("t_mean", "t_mean")):
                    v = SC.apply_weather_day(scn, var, ds, w[key])
                    if v is not None:
                        w[key] = v
                if k in irr_day:
                    w["u"] = {"irr_mm": irr_day[k]}
            ahead.append(w)
        traj = np.concatenate([f.X[:, None, :model.n].copy(), f.run_ahead(ahead)], axis=1)  # (N, K, n)
        fc_days = FC.coverage_days(fc, today, TRUST_D)
        if fc_days >= TRUST_D + 1:
            notes.append(f"앞날 예보 비 {fc_days} 일(오늘~+{TRUST_D} 일) 반영")
        elif fc_days:
            notes.append(f"앞날 예보 비 {fc_days} 일만 반영 — 나머지 날은 비 없음 가정")
        else:
            notes.append("앞날 비 없음 가정(예보 미배선)")

        days = [t0 + k * 86400.0 for k in range(n_pts)]
        out = TwinOutput(kind=TargetKind.FIELD, target_id=spec.target_id, t0=t0, facility=spec.facility)
        out.grids["daily"] = days
        q: Dict[str, Dict[str, list]] = {}

        def put(name, arr):                                        # arr (N, K)
            p10, p50, p90 = np.percentile(arr, [10, 50, 90], axis=0)
            q[name] = {"p10": p10.tolist(), "p50": p50.tolist(), "p90": p90.tolist()}

        der = [model.derived(traj[:, k, :], dap=today - plant + k) for k in range(n_pts)]
        put("theta_root", np.stack([d["theta_root_pct"] for d in der], axis=1))
        put("Dr", np.stack([d["Dr_mm"] for d in der], axis=1))
        put("Ks", np.stack([d["Ks"] for d in der], axis=1))
        put("Ts1", traj[:, :, model.idx["Ts1"]])
        put("GDD", traj[:, :, model.idx["gdd"]])
        if not free:                                               # 센서가 없으면 '센서가 읽을 값' 도 없다
            sv = f.sensor_view(sens)
            put("theta_sensor", np.stack([model.observe(traj[:, k, :], sv) for k in range(n_pts)], axis=1))
        out.quantiles["daily"] = q
        rk = model.risks(traj, dap0=today - plant)
        out.events["daily"] = {"water_deficit": rk["p_water_short"].tolist(),
                               "water_deficit_severe": rk["p_water_short_severe"].tolist(),
                               "waterlogging": rk["p_overwet"].tolist()}

        irrigated = bool(o.get("irrigated", False))
        # 신뢰 구간 전체에 예보 비가 있으면 정상, 하나라도 비 없음으로 메웠으면 예보 대체(계약 §7)
        status = Status.OK if fc_days >= TRUST_D + 1 and not free else Status.DEGRADED
        rmse = float(np.sqrt(np.mean(np.square(errs)))) if errs else float("nan")
        out.meta = {
            "status": int(status),
            "valid_until": valid_until_for(t0, period, status, "field_daily"),
            "horizon_d": float(n_pts - 1), "ensemble_size": float(n), "stale_s": max(0.0, now - t0),
            "model_rev": float(MODEL_REV), "sync_rmse_theta_1d": rmse,
            "coverage_80": float(np.mean(cover)) if cover else float("nan"),
            "obs_n": 0.0 if free else 1.0,
            "obs_age_s": max(0.0, now - max(valid_t)) if valid_t else float("nan"),
            "irrigation_known": 0.0, "rain_src": float(RAIN_SRC.get(str(rcfg.get("kind", "station")), 0)),
            "texture_src": 0.0, "grid_rev": 0.0,
            "rain_fc_days": float(fc_days),
            "plan_src": 2.0 if scn is not None else 0.0,           # 미래 입력: 0 현재 유지(관수 모름) · 2 what-if
        }
        roster = (o.get("effects") or {}).get("devices") if isinstance(o.get("effects"), Mapping) else None
        report = SC.effects_report(roster, "field") if roster else []
        if report:                                                 # 기본 예측에는 노지 관수가 아직 연결되지 않았다(E3) — 모두 미반영으로 센다
            out.meta["effects_modeled"], out.meta["effects_unmodeled"] = 0.0, float(len(report))
        if free:
            notes.append("관측 없음 — 센서 없이 모델만(동기화·검증 없음, 참고용)")
        if irrigated:
            notes.append("관수 모름(irrigation_known=0) — 관수 제외 예측")
        m = f.mean()
        out.meta.update(LG.forecast_meta(fc.issued_at, fc.cal_rev))
        origin = LG.obs_origin([] if free else [spec.inputs.get("theta")])
        if origin is not None:
            out.meta["obs_origin"] = origin
        # 그래프 기준선(θ_root 와 같은 단위 %). 물 부족 문턱 = Ks 가 1 아래로 내려가기 시작하는 θ (고갈률 p_tab).
        fc_pct, wp_pct = 100.0 * float(m["theta_fc"]), 100.0 * float(m["theta_wp"])
        out.meta.update({"theta_fc": fc_pct, "theta_wp": wp_pct,
                         "theta_thr": fc_pct - float(model.crop.p_tab) * (fc_pct - wp_pct)})
        if not free:
            out.meta.update({"obs_a": float(m["cal_a:theta"]), "obs_b": float(m["cal_b:theta"])})
        info = {"trust_d": TRUST_D, "assimilated_days": 0 if free else today - start, "obs_days": len(obs),
                "theta_fc": float(m["theta_fc"]), "tau_drain_d": float(m["tau_drain_d"]),
                "placement_changes": [str(fz.date_of(d)) for d in sorted(moves)]}
        if not free:
            info.update({"cal_a": float(m["cal_a:theta"]), "cal_b": float(m["cal_b:theta"])})
        res = RunResult(out, status, "; ".join(notes),
                        n_points=sum(len(g) for g in out.grids.values()))
        res.info = info                                            # 사람용 요약(CLI 표·기록)
        res.effects = report
        if scn is not None:                                        # 가정한 관수를 작동 시계열로(시 격자, 앞날만)
            hs = sorted(h for h in irr_hourly if t0 <= h < t0 + (n_pts - 1) * 86400.0)
            if hs:
                res.act = [SC.ActSeries("irrigation_mm", "plan", hs, [irr_hourly[h] for h in hs])]
            if scn.supply:
                notes.append("공급 조건(supply)은 아직 반영하지 않음: " + ", ".join(str(x["name"]) for x in scn.supply))
                res.reason = "; ".join(notes)
        return res


def _series_forecast(source, site: str, now: float, tz: float, today: int, notes: List[str]):
    """대지 예보 계열(`source.read_forecast` — 지도 날씨·AI 와 같은 출처)의 일 행 → `FC.Forecast`. 못 읽으면 None.

    일 번호는 행의 `time`(대지 현지 자정)을 구획 시간대로 접는다. 비 배율 오차는 사다리와 같은 기본값."""
    reader = getattr(source, "read_forecast", None)
    if reader is None:
        return None
    fs = reader(site, now - 86400.0, now + (HORIZON_D + 1) * 86400.0)
    fc = FC.Forecast(rain_groups=FC.Group("rain", {}))
    if fs.available:
        fc.issued_at, fc.cal_rev = getattr(fs, "fetched_at", None), getattr(fs, "cal_rev", 0)
    if not fs.available or not fs.daily:
        why = fs.reason_text or fs.reason or "없음"
        fc.notes.append(f"대지 예보 계열 없음({why}) — 앞날 비 없음 가정")
        return fc
    tx, tn = {}, {}
    for r in fs.daily:
        d = int(math.floor((float(r["time"]) + tz + 3600.0) / 86400.0))     # 자정(±1 h 시간대 차)도 같은 날
        if d < today:
            continue
        if r.get("precip_mm") is not None:
            fc.rain_mm[d] = max(0.0, float(r["precip_mm"]))
        if r.get("et0_mm") is not None:
            fc.et0_mm[d] = max(0.0, float(r["et0_mm"]))
        if r.get("temp_max_c") is not None:
            tx[d] = float(r["temp_max_c"])
        if r.get("temp_min_c") is not None:
            tn[d] = float(r["temp_min_c"])
    fc.t_mean = {d: 0.5 * (tx[d] + tn[d]) for d in tx if d in tn}
    basis = {"designated": "지정", "map_layer": "지도 레이어 폴백"}.get(fs.source_basis, fs.source_basis or "?")
    kinds = "+".join(str(sg.get("kind")) for sg in fs.segments) or "daily"
    names = []
    for sg in fs.segments:
        n = str((sg.get("source") or {}).get("name") or "")
        if n and n not in names:
            names.append(n)
    notes.append(f"예보 출처: {' + '.join(names) or fs.source or '?'} ({basis}, {kinds})")
    if not fc.rain_mm:
        fc.notes.append("예보 계열에 일 강수가 없음 — 앞날 비 없음 가정")
    return fc


registry.register("field_bucket_v1", "field", FieldBucketTwin, default=True)
