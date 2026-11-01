# coding=utf-8
"""시설 트윈 부품 — 그레이박스 v3 + 숨은 열질량 + UKF (`aot.functions.utils.facility_twin`) 를 노드에 끼운다 (원칙 6).

모델·필터는 그대로 import 한다(원칙 3). 여기는 배선과 출력 조립만 한다:

    설정의 계열(TargetSpec.inputs/controls) ──읽기──▶ 이력 `sync_window_h`(기본 48 h)
        ──▶ FacilityUKF 로 9상태 동기화(마지막 측정 시각까지) ──▶ 일치도(1스텝·1h 선행 RMSE)
        ──▶ 사후에서 멤버 추출 → 600 s 격자 48 h 예측(현재 설정 유지, 외기 유지) → 분위수·위험 확률 → TwinOutput(fast)

배선 (TargetSpec.inputs 의 논리 이름)

| 이름 | 뜻 | 필수 |
|---|---|---|
| `T_int` `RH_int` | 실내 기온·상대습도. 출처 표시 `measured` 여야 한다(엔진이 검사) | 예 |
| `T_ext` `RH_ext` | 외기 기온·상대습도(시설 근처 측정) | 예 |
| `CO2_int` | 실내 CO₂ | 아니오 |
| `solar` `wind` `CO2_ext` | 일사(W/m²)·풍속(m/s)·외기 CO₂ — 없으면 일사 0 · 1 m/s · 420 ppm | 아니오(일사 없으면 degraded) |

`TargetSpec.controls`: 장치가 **실제로 한 일**(개도·가동률 %) 계열. 키는 그레이박스 채널 이름
`heat` `cool` `vent` `fog` `co2_inj` `shade` `curtain`. 하나도 없으면 not_twinnable(계약 §3 전제 b).
출처가 `measured` 가 아니면(가상 출력·미러·미확인) 개발 허용(`allow_unverified`) 없이는 not_twinnable.

options (모두 선택 — 값은 가정이며 지역·제공자를 가정하지 않는다)

    greybox        `GreyboxParams` 필드(시설 capacity_meta 에서 서버가 채워 보낸 사전값)
    facility       `FacilityConfig` 필드(누기 회/h, 열질량 용량·결합 배수)
    process_sd, obs_sd, p0_sd   필터 불확실성 덮어쓰기(ukf.py 기본값 참고)
    sync_window_h  동화 이력(기본 48), filter_dt_s  필터 격자(기본 120)
    forecast_series  {"site": "<대지 uuid>"} — 그 대지에 지정된 예보 입력의 시간별 시계열(서버 `GET /api/twin/forecast_series`)을
                   전망 외기(기온·습도·풍속·일사)로 쓴다. 없는 곳(지정 없음·낡음·지평 밖·변수 없음)은 일주기 지속으로 메운다.
                   설정이 없으면 일주기 지속만 쓴다.
    T_high T_low RH_high  위험 문턱(32 · 5 · 90)
    scenario       {"overrides": {...}, "id": "<시나리오 id>"} — what-if 실행(설계서 §5.2 ④, `twin_effects.scenario`). 같은 동기화(UKF)·같은
                   시드로 돌리고 **예측 구간의 장치 명령·외기에만** 가정을 건다(과거는 그대로). 머리말 `plan_src` = 2.
    effects        {"devices": [{"id": 장치 id, "kind": 종류, "ratings": {정격}, "vent_form": null|"ridge"|"side",
                   "basis": "actual"|"duty_log"|"command"|"none"}]} — 있으면
                   `controls` 의 키는 채널 이름이 아니라 **장치 id** 이고, 장치 계열을 효과 목록표(`twin_effects.catalog`)로
                   채널에 합친다(창·팬은 풍량 비율, 난방·냉방·분무·CO₂ 는 정격 가중, 스크린은 평균). 목록표에 없거나 모델이 못 받는
                   종류는 결과 메모에 '효과 미반영'으로 남는다(상태 최대 degraded). 정격 합은 `Q_heat` 등 사전값을 채운다
                   (`options.greybox` 에 이미 있는 값이 우선). `basis` 가 `command`(명령 기록만 있음, 추정)인 장치는 동기화(UKF)에서
                   빼고 예측 입력(`last_cmd`)에만 쓴다. 서버가 위치로 읽은 장치를 자동으로 채운다(`aot.utils.twin_effects_link`). 설계서 plans/2026-10-25_twin_actuator_effects_design.md.
"""
from __future__ import annotations

import logging
import math
import zlib
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np

from .. import engine as EN, lineage as LG, output as O
from ..expiry import valid_until_for
from ..ext_forecast import REQUEST_VARIABLES, SeriesExt
from ..types import Status, TargetKind, TargetSpec, TwinOutput
from . import registry

logger = logging.getLogger(__name__)

# `aot.functions.utils.env_control` 의 `__init__` 이 DB·Influx 모듈을 끌어오므로(노드 import 가드, 시험이 지킨다)
# 시설 모델은 **실행할 때** 가져온다. 아래 상수는 `facility_twin` 과 같아야 하고 시험이 맞춰 본다.
MODEL_REV = 1
PARAM_NAMES = ("theta_UA", "theta_leak", "theta_sol", "theta_vent", "theta_tr")
CONTROL_NAMES = ("heat", "cool", "vent", "fog", "co2_inj", "shade", "curtain")
SYNC_WINDOW_H = 48.0
FILTER_DT_S = 120.0
LEAD_S = 3600.0
MIN_LEAD_SAMPLES = 6
# 일치도 신호등 (계획서 P1: 1h 선행 T < 1.0 °C · RH < 7 %p 가 합격선)
GREEN = {"T": 1.0, "RH": 7.0}
YELLOW = {"T": 1.5, "RH": 10.5}          # 계약 §7: 초록 문턱의 1.5 배 이내가 노랑
PROC_FORECAST = {"T": 0.30, "AH": 0.15, "CO2": 15.0, "Tm": 0.15}      # 예측 중 모델 오차(√h 당)
EXT_SIGMA = {"T_ext": 1.5, "RH_ext": 8.0}                              # engine.EXT_SIGMA 와 같다(자리표시자)


def apply_scale(ref, values: Sequence[float]) -> List[float]:
    """장치 상태 계열의 `scale=(from_min, from_max)` 가 있으면 그 범위를 0~100 % 로 옮긴다(범위 밖은 자른다).
    없으면 값을 그대로 둔다 — 임의 변환 금지."""
    if ref.scale is None:
        return list(values)
    lo, hi = ref.scale
    return [min(100.0, max(0.0, (v - lo) / (hi - lo) * 100.0)) for v in values]


def facility_risks(traj: Sequence[Mapping[str, float]], target: TargetSpec) -> Dict[str, List[float]]:
    """궤적 하나의 격자 지점별 사건(0/1). 확률은 뼈대가 멤버 평균으로 낸다."""
    o = target.options
    hi, lo, rh_hi = float(o.get("T_high", 32.0)), float(o.get("T_low", 5.0)), float(o.get("RH_high", 90.0))

    def dew(t, rh):
        g = math.log(max(rh, 1e-3) / 100.0) + 17.27 * t / (t + 237.3)
        return 237.3 * g / (17.27 - g)

    return {"heat": [float(s["T"] > hi) for s in traj],
            "frost": [float(s["T"] < lo) for s in traj],
            "humid": [float(s["RH"] > rh_hi) for s in traj],
            "condensation": [float(s["T"] - dew(s["T"], s["RH"]) < 1.0) for s in traj]}


def _effect_devices(eff):
    """`options.effects.devices` → `twin_effects.aggregate.Device` 목록(없으면 빈 목록)."""
    if not isinstance(eff, Mapping) or not eff.get("devices"):
        return []
    from aot.functions.utils.twin_effects.aggregate import Device
    return [Device(str(d["id"]), str(d["kind"]), dict(d.get("ratings") or {}), d.get("vent_form"))
            for d in eff["devices"] if isinstance(d, Mapping) and d.get("id") and d.get("kind")]


def _grey_params(o: Mapping[str, object]):
    from aot.functions.utils.env_control.greybox.params import GreyboxParams
    d = o.get("greybox")
    if isinstance(d, Mapping) and d:
        p = GreyboxParams.from_dict(dict(d))
        if "volume_m3" in d:
            p.volume_m3 = d["volume_m3"]
        return p
    return GreyboxParams()


def _act_series(cmds, eff, eff_info, cmd_fn, last_cmd, t0: float, horizon_s: float, SC):
    """작동 시계열(`env_twin_act`) 계열 — 효과 채널마다 정시 평균 개도 %. 과거(동기화에 쓴 상태, 출처 = 구성원 중 가장 나쁜
    것)는 t0 의 정시 앞까지, 그 뒤는 `plan`(현재 유지 또는 what-if 명령). 채널에 상태 계열이 없으면 쓰지 않는다(지어내지 않는다)."""
    basis_of = {str(d["id"]): d.get("basis") for d in (eff or {}).get("devices", []) if isinstance(d, Mapping)}
    members = eff_info.members if eff_info is not None else {}
    plan_fn = cmd_fn if isinstance(cmd_fn, SC.CmdPlan) else SC.CmdPlan(t0, [t0], [last_cmd])
    h0 = math.floor(t0 / 3600.0) * 3600.0
    out = []
    for ch, (ts, vs) in cmds.items():
        if ch not in last_cmd or not len(ts):
            continue
        b = SC.worst_basis([basis_of.get(a) for a in members.get(ch, [])]) if members else "actual"
        pt, pv = SC.hourly_mean_hold(ts, vs, ts[0], h0)
        if pt:
            out.append(SC.ActSeries(ch, b, pt, pv))
        ft, fv = SC.hourly_mean_hold(ts, vs, h0, t0 + horizon_s, future=plan_fn, channel=ch, future_from=t0)
        if ft:
            out.append(SC.ActSeries(ch, "plan", ft, fv))
    return out


class FacilityGreyboxTwin:
    kind = "facility"
    model_rev = MODEL_REV
    state_names = ("T", "RH", "CO2")
    param_names = PARAM_NAMES
    dt_nominal_s = 60.0
    required_inputs = ("T_int", "RH_int", "T_ext", "RH_ext")

    # TwinModel 프로토콜의 자리 — 실행 전체는 run_target 이 맡는다(엔진이 먼저 hasattr 로 본다)
    def init_state(self, target, t0, obs):
        return {"T": obs.get("T_int", 20.0), "RH": obs.get("RH_int", 60.0), "CO2": obs.get("CO2_int", 420.0)}

    def step(self, x, u, w, dt_s):
        raise NotImplementedError("run_target 이 전체를 맡는다")

    def observe(self, x, name):
        return {"T_int": x["T"], "RH_int": x["RH"], "CO2_int": x["CO2"]}.get(name, float("nan"))

    def derived(self, x):
        return dict(x)

    def risks(self, traj, target):
        return facility_risks(traj, target)

    # ── 실행 ──────────────────────────────────────────────────────────────────
    def run_target(self, spec: TargetSpec, source, cap, now: float, period: float,
                   seed: Optional[int] = None):
        from aot.functions.utils.facility_twin import FacilityConfig, FacilityTwinModel, FacilityUKF
        from aot.functions.utils.facility_twin.sync import DEFAULT_CMDS, assimilate
        o = spec.options
        eff = o.get("effects")
        eff_devs = _effect_devices(eff)
        if eff_devs:
            ctl = {d.actuator_id: spec.controls[d.actuator_id] for d in eff_devs if d.actuator_id in spec.controls}
        else:
            ctl = {k: r for k, r in spec.controls.items() if k in CONTROL_NAMES}
        if not ctl:
            return EN.unusable(spec, now, period, Status.NOT_TWINNABLE,
                               "장치 실제 상태(개도·가동) 계열 미배선(계약 §3 전제 b)")
        notes: List[str] = []
        from aot.functions.utils.twin_effects import scenario as SC
        scn = None                                                    # what-if 가정(없으면 기본 예측)
        if isinstance(o.get("scenario"), Mapping):
            try:
                scn = SC.parse(o["scenario"].get("overrides"), "facility")
            except SC.ScenarioError as e:
                return EN.unusable(spec, now, period, Status.ERROR, "시나리오 가정 오류: %s" % e)
            if scn.supply:
                notes.append("공급 조건(supply)은 아직 반영하지 않음: " + ", ".join(str(x["name"]) for x in scn.supply))

        window_s = float(o.get("sync_window_h", SYNC_WINDOW_H)) * 3600.0
        dt = float(o.get("filter_dt_s", FILTER_DT_S))

        def read(ref):
            try:
                s = source.read_series(ref, window_s, now)
            except Exception as e:                                  # 읽기 실패는 그 입력의 결측
                logger.warning("트윈 읽기 실패 %s: %s", spec.server_id, e)
                return [], []
            return list(s.times), apply_scale(ref, s.values)

        obs = {"T": read(spec.inputs["T_int"]), "RH": read(spec.inputs["RH_int"])}
        obs["CO2"] = read(spec.inputs["CO2_int"]) if "CO2_int" in spec.inputs else ([], [])
        ext = {k: read(spec.inputs[k]) for k in ("T_ext", "RH_ext", "solar", "wind", "CO2_ext") if k in spec.inputs}
        cmds = {k: read(r) for k, r in ctl.items()}
        eff_info = None
        est_note = ""
        raw_cmds = {}
        sync_cmds = cmds                                              # 동기화(UKF)에 넣는 상태 — 아래에서 효과 채널로 바뀐다
        if eff_devs:
            from aot.functions.utils.twin_effects.series import channelize
            from aot.functions.utils.twin_effects.state import COMMAND, SYNC_BASES
            basis = {str(d["id"]): d.get("basis") for d in eff.get("devices", []) if isinstance(d, Mapping)}
            cs = channelize(eff_devs, cmds)                           # 예측 입력: 쓸 수 있는 상태를 모두
            # 동기화: 명령만 있는 장치(`command`, 명령≠실제일 수 있다)는 뺀다(설계서 결정 4). 같은 채널의 다른 장치와의
            # 합치기 몫은 그대로라 뺀 장치는 가동 0 으로 합쳐진다 — 검증 가능한 부분만 필터에 들어간다.
            est = [a for a in cmds if basis.get(a) == COMMAND]
            if est:
                synced = {a: v for a, v in cmds.items() if basis.get(a) in (None, *SYNC_BASES)}
                sync_cmds = channelize(eff_devs, synced).channels
                est_note = "명령 기록만 있는 장치(추정, 동기화 제외·예측 입력에만 사용): " + ", ".join(est)
                notes.append(est_note)
            else:
                sync_cmds = cs.channels
            raw_cmds = cmds                                           # 장치별 원 상태(what-if 의 장치 가정이 쓴다)
            cmds, eff_info = cs.channels, cs
            if not cmds:
                return EN.unusable(spec, now, period, Status.NOT_TWINNABLE,
                                   "효과 채널로 합칠 장치 상태 계열이 없다(모두 미배선·미반영)")
            if cs.unmodeled:
                notes.append("효과 미반영 장치: " + ", ".join(f"{u['kind']}({u['actuator_id']})" for u in cs.unmodeled))
            if cs.unwired:
                notes.append(f"상태 계열 없는 장치(가동 0 으로 합치지 않음, 제외): {cs.unwired}")
            if cs.assumed:
                notes.append(f"정격을 모르는 장치(가정): {cs.assumed}")
        if not obs["T"][0] or not obs["RH"][0]:
            return EN.unusable(spec, now, period, Status.UNSYNCED, "실내 T·RH 관측 없음")
        newest = min(obs["T"][0][-1], obs["RH"][0][-1])
        max_age = float(o.get("max_obs_age_s", EN.DEFAULT_MAX_AGE_S[TargetKind.FACILITY]))
        if now - newest > max_age:
            return EN.unusable(spec, now, period, Status.UNSYNCED,
                               f"관측이 낡음: {now - newest:.0f}s > {max_age:.0f}s")
        if not ext.get("T_ext", ([], []))[0] or not ext.get("RH_ext", ([], []))[0]:
            return EN.unusable(spec, now, period, Status.UNSYNCED, "외기 T·RH 관측 없음")
        for k in ("solar", "wind"):
            if k not in ext or not ext[k][0]:
                notes.append(f"{k} 입력 없음 — 기본값 사용")
        if not obs["CO2"][0]:
            notes.append("CO₂ 관측 없음 — 실내 CO₂ 는 모델 추정")

        t0 = math.floor(newest / 60.0) * 60.0
        n_steps = int(window_s // dt)
        t_start = t0 - n_steps * dt

        gp = _grey_params(o)
        if eff_devs:
            from aot.functions.utils.twin_effects.priors import grey_priors
            given = o.get("greybox") if isinstance(o.get("greybox"), Mapping) else {}
            for name, pr in grey_priors(eff_devs, gp.volume_m3).items():
                if name in given or pr["basis"] != "physical":       # 상한(분무)은 사전값으로 쓰지 않는다
                    continue
                setattr(gp, name, pr["value"])
        model = FacilityTwinModel(gp, FacilityConfig.from_options(o.get("facility", {}) or {}))
        ukf = FacilityUKF(model, process_sd=o.get("process_sd"), obs_sd=o.get("obs_sd"), p0_sd=o.get("p0_sd"))
        res = assimilate(model, ukf, t_start, t0, obs, ext, sync_cmds, dt_s=dt, lead_s=(LEAD_S,))
        if res is None:
            return EN.unusable(spec, now, period, Status.UNSYNCED, "동화할 관측이 부족하다")

        rmse_T1, rmse_RH1 = res.rmse_1step("T"), res.rmse_1step("RH")
        lead_T = res.rmse_lead(LEAD_S, "T", "actual")
        lead_RH = res.rmse_lead(LEAD_S, "RH", "actual")
        n_lead = res.n_lead(LEAD_S, "T", "actual")
        if n_lead < MIN_LEAD_SAMPLES or math.isnan(lead_T):
            return EN.unusable(spec, now, period, Status.UNSYNCED,
                               f"일치도를 잴 이력이 짧다(선행 표본 {n_lead} < {MIN_LEAD_SAMPLES})")
        if lead_T <= GREEN["T"] and lead_RH <= GREEN["RH"]:
            sync = Status.OK
        elif lead_T <= YELLOW["T"] and lead_RH <= YELLOW["RH"]:
            sync = Status.DEGRADED
            notes.append(f"일치도 노랑: 1h 선행 T {lead_T:.2f} °C · RH {lead_RH:.1f} %p")
        else:
            why = f"일치도 빨강: 1h 선행 T {lead_T:.2f} °C · RH {lead_RH:.1f} %p"
            if est_note:                                   # 필터가 못 본 입력이 있다는 단서를 이유에 남긴다
                why += " — " + est_note
            return EN.unusable(spec, now, period, Status.UNSYNCED, why)

        # 예측 — 사후에서 멤버를 뽑아 현재 설정·외기를 유지한 채 48 h
        plan = EN.GRID_PLANS[TargetKind.FACILITY][0]
        n_pts = plan.n_points(cap.horizon_frac)
        n_members = cap.ensemble_size
        rng = np.random.default_rng(seed if seed is not None else zlib.crc32(f"{spec.key}:{t0}".encode()))
        last_cmd = {k: (cmds[k][1][-1] if k in cmds and cmds[k][1] else DEFAULT_CMDS[k]) for k in CONTROL_NAMES}
        cmd_fn = last_cmd                                             # 정책 0: 마지막 명령 유지. what-if 면 조각 함수
        if scn is not None:
            horizon_end = t0 + (n_pts - 1) * plan.step_s
            dev_pct = {a: float(v[1][-1]) for a, v in raw_cmds.items() if v and v[1]}
            try:
                cmd_fn = SC.facility_cmd_plan(scn, t0, horizon_end, last_cmd, eff_devs, dev_pct)
            except SC.ScenarioError as e:
                return EN.unusable(spec, now, period, Status.ERROR, "시나리오 가정 오류: %s" % e)
            for uid in SC.unmodeled_targets(scn, eff_devs):
                notes.append(f"효과 미반영 장치에 건 가정은 효과가 없다: {uid}")
        # 외기 전망 = 일주기 지속: 예측 시각 t 의 외기를 "t 에서 하루의 정수 배를 뺀, 마지막 24 h 안의 같은 시각" 측정으로 쓴다.
        # 낮 일사·밤 저온이 반복되므로 마지막 값을 붙드는 것보다 낫다(예보 입력이 붙기 전의 최소 전망, 계약 weather_src 4).
        # 그 24 h 에 측정이 비면 그 항은 기본값(일사 0 · 풍속 1 m/s · 외기 CO₂ 420 ppm).
        from aot.functions.utils.facility_twin.sync import DEFAULT_EXT, _Hold
        holds = {k: _Hold(ext.get(k), 3 * 3600.0) for k in DEFAULT_EXT}
        if holds["solar"].t and holds["solar"].first_time() > t0 - 20 * 3600.0:
            notes.append("일사 이력 20 h 미만 — 일주기 반복이 불완전")

        def ext_persist(t: float) -> Dict[str, float]:
            n = max(1, math.ceil((t - t0) / 86400.0 - 1e-9))
            tb = t - n * 86400.0
            out_ = {}
            for k, d in DEFAULT_EXT.items():
                v = holds[k].at(tb)
                out_[k] = d if v is None else v
            return out_

        # 지정 예보 입력이 설정돼 있으면(options.forecast_series.site) 그 시계열로 전망 외기를 만들고, 없는 곳만 일주기 지속으로
        # 메운다. 설정이 없으면 예전과 같다. 읽기가 실패하거나 지정이 없어도 트윈은 돈다(원칙 1) — 그때는 '예보 대체'(degraded).
        ext_fwd = ext_persist
        fs_used = False
        fcfg = o.get("forecast_series")
        if isinstance(fcfg, Mapping) and fcfg.get("site"):
            reader = getattr(source, "read_forecast", None)
            fs = None
            if reader is None:
                notes.append("예보 시계열 읽기를 이 통로가 지원하지 않음 — 일주기 지속")
            else:
                try:
                    fs = reader(str(fcfg["site"]), t0, t0 + (n_pts - 1) * plan.step_s, REQUEST_VARIABLES)
                except Exception as e:                                  # noqa: BLE001
                    logger.warning("트윈 예보 시계열 읽기 실패 %s: %s", spec.server_id, e)
                    fs = None
                if fs is None or not fs.available:
                    why = (getattr(fs, "reason_text", "") or getattr(fs, "reason", "") or "읽지 못함") if fs else "읽지 못함"
                    notes.append(f"예보 입력 없음({why}) — 일주기 지속")
                    fs = None
            if fs is not None:
                ext_fwd = SeriesExt(fs, ext_persist)
                fs_used = True
                if fs.horizon is not None and fs.horizon < t0 + (n_pts - 1) * plan.step_s - 1.0:
                    notes.append(f"예보가 {(fs.horizon - t0) / 3600.0:.0f} h 까지 — 이후는 일주기 지속")
                rows_have = set().union(*(set(r) for r in fs.rows)) if fs.rows else set()
                if "solar_w_m2" not in rows_have:
                    notes.append("예보에 일사 없음 — 일사는 일주기 지속")

        sd = [PROC_FORECAST[k] for k in ("T", "AH", "CO2", "Tm")]
        members = []
        z_samples = ukf.sample(n_members, rng)
        for m in range(n_members):
            if m == 0:
                off, r_m = {}, None
            else:
                off = {k: s_ * rng.standard_normal() for k, s_ in EXT_SIGMA.items()}
                r_m = rng

            def e_fn(t, off=off):
                e = ext_fwd(t)
                if scn is not None and scn.weather:                    # 가정은 예보 위에, 멤버 잡음은 그 위에 더한다
                    SC.apply_weather_ext(scn, e, t)
                for k, d in off.items():
                    e[k] += d
                e["RH_ext"] = min(100.0, max(0.0, e["RH_ext"]))
                return e

            tr = model.predict(z_samples[m], e_fn, cmd_fn, t0, plan.step_s, n_pts,
                               rng=r_m, noise_sd_per_sqrt_h=sd if r_m is not None else None)
            traj = [model.derived(z) for z in tr]
            members.append((traj, facility_risks(traj, spec)))
        out = TwinOutput(kind=TargetKind.FACILITY, target_id=spec.target_id, t0=t0, facility=spec.facility)
        EN._collect(out, plan, members, t0, n_pts, n_members)

        status = Status.DEGRADED if (notes or sync == Status.DEGRADED) else Status.OK
        out.meta = {
            "status": int(status),
            "valid_until": valid_until_for(t0, period, status, "facility"),
            "horizon_h": (n_pts - 1) * plan.step_s / 3600.0,
            "ensemble_size": float(n_members),
            "sync_rmse_T": rmse_T1, "sync_rmse_RH": rmse_RH1, "sync_rmse_T_1h": lead_T,
            "stale_s": max(0.0, now - t0),
            "model_rev": float(MODEL_REV),
            "policy": 0.0, "weather_src": 5.0 if fs_used else 4.0,
            "plan_src": 2.0 if scn is not None else 0.0,             # 미래 입력: 0 현재 유지 · 2 what-if
        }
        report = []
        if eff_devs:                                                 # 장치 효과 보고 → 머리말 개수(손배선만 있으면 장치를 몰라 쓰지 않는다)
            report = SC.effects_report(eff["devices"], "facility", eff_info.assumed if eff_info else ())
            out.meta["effects_modeled"], out.meta["effects_unmodeled"] = (float(n) for n in SC.header_counts(report))
        if fs_used:
            out.meta.update(LG.forecast_meta(getattr(ext_fwd.fs, "fetched_at", None), getattr(ext_fwd.fs, "cal_rev", 0)))
        origin = LG.obs_origin(spec.inputs.get(k) for k in ("T_int", "RH_int", "CO2_int"))
        if origin is not None:
            out.meta["obs_origin"] = origin
        z = ukf.z
        info = {"sync_rmse_T": rmse_T1, "sync_rmse_RH": rmse_RH1, "lead1h_T": lead_T, "lead1h_RH": lead_RH,
                "lead_n": n_lead, "nis": ukf.nis_mean, "gated": ukf.stats["n_gated"],
                "theta": {n: float(math.exp(z[4 + i])) for i, n in enumerate(PARAM_NAMES)},
                "Tm": float(z[3]), "T": float(z[0])}
        if eff_info is not None:
            info["effects"] = {"members": eff_info.members, "unmodeled": eff_info.unmodeled,
                               "assumed": eff_info.assumed, "unwired": eff_info.unwired}
        if fs_used:
            info["forecast"] = {"source": ext_fwd.fs.source, "model": ext_fwd.fs.model,
                                "horizon_h": (ext_fwd.horizon - t0) / 3600.0 if ext_fwd.horizon else None,
                                "coverage": {k: round(v, 3) for k, v in ext_fwd.coverage().items()}}
        rr = EN.RunResult(out, status, "; ".join(notes), n_points=sum(len(g) for g in out.grids.values()))
        rr.info = info
        rr.effects = report
        rr.act = _act_series(cmds, eff, eff_info, cmd_fn, last_cmd, t0, (n_pts - 1) * plan.step_s, SC)
        return rr


registry.register("facility_greybox_v1", "facility", FacilityGreyboxTwin, default=True)
