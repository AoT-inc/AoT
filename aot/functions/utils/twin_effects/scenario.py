# coding=utf-8
"""what-if 시나리오의 가정(`twin_scenario.overrides`) → 모델 입력 (설계서 §5.2 ④ · §5.3, E2).

저장은 데이터 관리 쪽(`twin_store`)이 불투명 JSON 으로 하고, **뜻은 이 모듈이 정한다**:

    overrides = {
      "actuators": [{"channel": "shade" | "<장치 uuid>", "t0": epoch, "t1": epoch|null, "value": 0~100, "unit": "%"}],
      "weather":   [{"var": "T_ext", "op": "add"|"scale"|"set", "value": 2.0, "t0": epoch, "t1": epoch|null}],
      "supply":    [{"name": "water_temp_c", "value": 12}]            # E4 전에는 반영하지 않는다(결과에 '미반영'으로 남는다)
    }

- 장치 가정의 키는 `channel`(또는 계약의 `channel_or_device_uid`)이다. 시설은 효과 채널 이름(`vent heat cool fog co2_inj shade
  curtain`) 이거나 장치 uuid(그 장치만 움직이고 같은 채널의 다른 장치는 그대로 — 합치기는 효과 목록표의 규칙).
  값은 시설 개도·가동률 0~100 %(`unit` 생략 또는 "%"). 노지는 `irrigation_mm` 만, `unit` 생략·`"mm"` = [t0, t1) 전체 관수 깊이,
  `"mm/h"` = 시간당. 노지는 `t1` 이 꼭 있어야 한다(끝없는 관수는 물 수지를 만들지 못한다).
- 구간은 `t0 ≤ t < t1`(UTC epoch 초), `t1` 이 null 이면 예측 끝까지. 겹치면 목록에서 뒤의 것이 이긴다. 가정은 예측 구간에만 닿는다
  (과거는 동기화에 쓴 실제 상태 그대로 — 가정으로 과거를 바꾸지 않는다).
- 기상 가정: 시설 `T_ext RH_ext CO2_ext solar wind`(별칭 `temp_c rh_pct solar_w_m2 wind_ms`), 노지 `precip_mm et0_mm temp_c`
  (일 격자라 **하루 단위**로 닿는다 — 구간이 그 날과 조금이라도 겹치면 그 날 값에 적용).
- 모르는 채널·변수·연산은 조용히 무시하지 않고 `ScenarioError` 로 거부한다.

순수 모듈이다(DB·Flask·numpy 를 모른다). env_control 은 `aggregate.merge` 가 실행할 때 가져온다(노드 import 가드).
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from . import catalog as C
from .aggregate import Device, merge

HOUR_S = 3600.0
DAY_S = 86400.0
OPS = ("add", "scale", "set")
FACILITY_CHANNELS = ("heat", "cool", "vent", "fog", "co2_inj", "shade", "curtain")
FIELD_CHANNELS = ("irrigation_mm",)
FACILITY_WEATHER = {"T_ext": "T_ext", "temp_c": "T_ext", "RH_ext": "RH_ext", "rh_pct": "RH_ext", "CO2_ext": "CO2_ext",
                    "solar": "solar", "solar_w_m2": "solar", "wind": "wind", "wind_ms": "wind"}
FIELD_WEATHER = {"precip_mm": "rain", "rain_mm": "rain", "rain": "rain", "et0_mm": "et0", "et0": "et0",
                 "temp_c": "t_mean", "t_mean": "t_mean"}
#: 이 모듈이 아직 실행할 수 있는 미래 입력 방식 — 나머지(일정·정책)는 E5.
RUNNABLE_BASE_MODES = ("hold",)
RUNNABLE_FUTURE_MODES = ("hold", "whatif")
#: 상태 출처 품질(작을수록 믿을 만하다) — 합친 채널의 출처는 가장 나쁜 구성원을 따른다.
_BASIS_RANK = {"actual": 0, "duty_log": 1, "command": 2, "assumed": 3}


class ScenarioError(ValueError):
    """가정이 모양이 틀렸거나 이 대상에 맞지 않는다 — 시나리오는 실패로 남고 이유가 `fail_reason` 에 적힌다."""


@dataclass(frozen=True)
class ActuatorOv:
    key: str
    t0: float
    t1: float                    # inf = 예측 끝까지
    value: float
    unit: str = ""


@dataclass(frozen=True)
class WeatherOv:
    var: str                     # 정규 이름(시설 T_ext … / 노지 rain·et0·t_mean)
    op: str
    value: float
    t0: float
    t1: float


@dataclass
class Plan:
    actuators: List[ActuatorOv] = field(default_factory=list)
    weather: List[WeatherOv] = field(default_factory=list)
    supply: List[Dict[str, object]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.actuators or self.weather)


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise ScenarioError("%s 는 유한한 숫자여야 한다" % what)
    return float(v)


def _span(d: Mapping, what: str, need_end: bool = False) -> Tuple[float, float]:
    t0 = _num(d.get("t0"), what + ".t0")
    if d.get("t1") in (None, ""):
        if need_end:
            raise ScenarioError("%s.t1 이 필요하다" % what)
        return t0, math.inf
    t1 = _num(d.get("t1"), what + ".t1")
    if t1 <= t0:
        raise ScenarioError("%s: t1 은 t0 보다 뒤여야 한다" % what)
    return t0, t1


def parse(overrides: Optional[Mapping], kind: str) -> Plan:
    """`overrides` → `Plan`. 모양을 검사한다(채널·변수 이름은 대상 종류 `facility|field` 에 맞춰)."""
    ov = overrides or {}
    field_target = kind == "field"
    plan = Plan()
    for i, a in enumerate(ov.get("actuators") or []):
        if not isinstance(a, Mapping):
            raise ScenarioError("actuators[%d] 는 객체여야 한다" % i)
        key = str(a.get("channel_or_device_uid") or a.get("channel") or a.get("device") or "").strip()
        if not key:
            raise ScenarioError("actuators[%d]: channel 이 없다" % i)
        unit = str(a.get("unit") or "").strip()
        val = _num(a.get("value"), "actuators[%d].value" % i)
        if field_target:
            if key not in FIELD_CHANNELS:
                raise ScenarioError("노지 장치 가정은 irrigation_mm 만 받는다: %s" % key)
            if unit not in ("", "mm", "mm/h"):
                raise ScenarioError("irrigation_mm 의 단위는 mm 또는 mm/h: %s" % unit)
            if val < 0:
                raise ScenarioError("관수량은 0 이상이어야 한다")
            t0, t1 = _span(a, "actuators[%d]" % i, need_end=True)
        else:
            if unit not in ("", "%"):
                raise ScenarioError("시설 장치 가정의 단위는 %%: %s" % unit)
            if not 0.0 <= val <= 100.0:
                raise ScenarioError("개도·가동률은 0~100 %% 여야 한다: %s" % val)
            t0, t1 = _span(a, "actuators[%d]" % i)
        plan.actuators.append(ActuatorOv(key, t0, t1, val, unit or ("mm" if field_target else "%")))
    table = FIELD_WEATHER if field_target else FACILITY_WEATHER
    for i, w in enumerate(ov.get("weather") or []):
        if not isinstance(w, Mapping):
            raise ScenarioError("weather[%d] 는 객체여야 한다" % i)
        var = str(w.get("var") or "").strip()
        if var not in table:
            raise ScenarioError("모르는 기상 변수: %s (가능: %s)" % (var, ", ".join(sorted(table))))
        op = str(w.get("op") or "").strip()
        if op not in OPS:
            raise ScenarioError("weather[%d].op 는 add, scale, set 중 하나" % i)
        val = _num(w.get("value"), "weather[%d].value" % i)
        if op == "scale" and val < 0:
            raise ScenarioError("scale 배율은 0 이상이어야 한다")
        t0, t1 = _span(w, "weather[%d]" % i)
        plan.weather.append(WeatherOv(table[var], op, val, t0, t1))
    for i, s in enumerate(ov.get("supply") or []):
        if not isinstance(s, Mapping) or not str(s.get("name") or "").strip():
            raise ScenarioError("supply[%d] 는 {name, value} 여야 한다" % i)
        plan.supply.append({"name": str(s["name"]), "value": s.get("value")})
    return plan


def validate(overrides: Optional[Mapping], kind: str) -> None:
    """생성 때의 검사 — 틀리면 `ScenarioError`."""
    parse(overrides, kind)


def check_modes(base_mode: str, future_input_mode: str) -> None:
    if base_mode not in RUNNABLE_BASE_MODES:
        raise ScenarioError("base_mode=%s 는 아직 실행할 수 없다(일정·정책 어댑터는 E5)" % base_mode)
    if future_input_mode not in RUNNABLE_FUTURE_MODES:
        raise ScenarioError("future_input_mode=%s 는 아직 실행할 수 없다(일정·정책 어댑터는 E5)" % future_input_mode)


def _apply(op: str, value: float, base: Optional[float]) -> Optional[float]:
    if op == "set":
        return value
    if base is None:
        return None
    return base + value if op == "add" else base * value


# ── 시설: 장치 가정 → 채널 명령 함수 ─────────────────────────────────────────────────

class CmdPlan:
    """예측 구간의 채널 명령 `t → {채널: %}` — 조각마다 일정해서(경계 = 가정의 t0·t1) 미리 계산해 둔다.

    모델 `predict` 가 서브스텝(60 s)마다 부르므로 한 번 계산한 조각을 `bisect` 로 찾는다."""

    def __init__(self, t_from: float, cuts: Sequence[float], segments: Sequence[Dict[str, float]]):
        self.t_from = t_from
        self._cuts = list(cuts)                    # 조각 i 는 [cuts[i], cuts[i+1]) — cuts[0] = t_from
        self._seg = [dict(s) for s in segments]

    def __call__(self, t: float) -> Dict[str, float]:
        i = bisect.bisect_right(self._cuts, t) - 1
        return self._seg[max(0, i)]

    def pieces(self) -> List[Tuple[float, Dict[str, float]]]:
        return list(zip(self._cuts, self._seg))


def facility_cmd_plan(plan: Plan, t_from: float, t_end: float, last_cmd: Mapping[str, float],
                      devices: Sequence[Device] = (), device_pct: Optional[Mapping[str, float]] = None) -> CmdPlan:
    """가정이 없으면 `last_cmd` 유지(지금 동작). 장치 가정이 있으면 그 장치의 개도만 바꿔 효과 목록표 규칙으로 다시 합친다.

    이 시설에 없는 채널·장치에 건 가정은 `ScenarioError`. 채널이 없는 장치(미반영 종류)에 건 가정은 합치기에서 효과가 없으므로
    호출자가 `unmodeled_targets` 로 알아내 결과 메모에 남긴다."""
    by_id = {d.actuator_id: d for d in devices}
    chan_ov, dev_ov = [], []
    for a in plan.actuators:
        if a.key in FACILITY_CHANNELS:
            chan_ov.append(a)
        elif a.key in by_id:
            dev_ov.append(a)
        else:
            raise ScenarioError("이 시설에 없는 채널·장치: %s" % a.key)
    cuts = {float(t_from)}
    for a in chan_ov + dev_ov:
        for t in (a.t0, a.t1):
            if math.isfinite(t) and t_from < t < t_end:
                cuts.add(float(t))
    cuts_l = sorted(cuts)
    pct0 = dict(device_pct or {})
    segs = []
    for c in cuts_l:
        cmd = dict(last_cmd)
        active_dev = [a for a in dev_ov if a.t0 <= c < a.t1]
        if active_dev:
            pct = dict(pct0)
            for a in active_dev:                       # 목록에서 뒤의 것이 이긴다
                pct[a.key] = a.value
            for ch, v in merge(list(devices), pct, C.FACILITY).values.items():
                cmd[ch] = v
        for a in chan_ov:
            if a.t0 <= c < a.t1:
                cmd[a.key] = a.value
        segs.append(cmd)
    return CmdPlan(t_from, cuts_l, segs)


def unmodeled_targets(plan: Plan, devices: Sequence[Device]) -> List[str]:
    """장치 가정을 걸었는데 그 장치의 종류가 효과 채널에 들어가지 않는 경우(미반영) — 가정이 아무 효과도 못 낸다."""
    out = []
    for a in plan.actuators:
        d = next((x for x in devices if x.actuator_id == a.key), None)
        if d is not None and C.row_for(d.kind, C.FACILITY).channel is None and a.key not in out:
            out.append(a.key)
    return out


def apply_weather_ext(plan: Plan, e: Dict[str, float], t: float) -> Dict[str, float]:
    """시설 외기 dict `e`(T_ext·RH_ext·CO2_ext·solar·wind)에 시각 `t` 의 기상 가정을 적용한다(제자리 수정)."""
    for w in plan.weather:
        if w.t0 <= t < w.t1 and w.var in e:
            v = _apply(w.op, w.value, e[w.var])
            if v is not None:
                e[w.var] = v
    if "RH_ext" in e:
        e["RH_ext"] = min(100.0, max(0.0, e["RH_ext"]))
    for k in ("solar", "wind", "CO2_ext"):
        if k in e:
            e[k] = max(0.0, e[k])
    return e


# ── 노지: 일 격자 가정 ──────────────────────────────────────────────────────────────

def irrigation_hourly(plan: Plan) -> Dict[float, float]:
    """관수 가정 → {시 시작 epoch: 그 시간 mm}. 겹치는 가정은 합친다(관수량은 더해진다)."""
    out: Dict[float, float] = {}
    for a in plan.actuators:
        span = a.t1 - a.t0
        per_s = (a.value / span) if a.unit == "mm" else a.value / HOUR_S
        h = math.floor(a.t0 / HOUR_S) * HOUR_S
        while h < a.t1:
            lo, hi = max(h, a.t0), min(h + HOUR_S, a.t1)
            if hi > lo:
                out[h] = out.get(h, 0.0) + per_s * (hi - lo)
            h += HOUR_S
    return out


def irrigation_daily(hourly: Mapping[float, float], day_starts: Sequence[float]) -> Dict[int, float]:
    """시 격자 관수 → 일 격자 인덱스(`day_starts` 의 위치)별 mm. 시 시작이 그 날 [시작, +24 h) 에 들면 그 날 몫."""
    out: Dict[int, float] = {}
    for h, mm in hourly.items():
        for i, d0 in enumerate(day_starts):
            if d0 <= h < d0 + DAY_S:
                out[i] = out.get(i, 0.0) + mm
                break
    return out


def apply_weather_day(plan: Plan, var: str, day_start: float, base: Optional[float]) -> Optional[float]:
    """일 격자 값 하나(`rain`·`et0`·`t_mean`)에 그 날 겹치는 기상 가정을 적용한다. 기본값이 없으면 `set`/(비의 `add`)만 값을 만든다."""
    v = base
    for w in plan.weather:
        if w.var != var or not (w.t0 < day_start + DAY_S and w.t1 > day_start):
            continue
        b = v
        if b is None and var == "rain" and w.op == "add":
            b = 0.0
        nv = _apply(w.op, w.value, b)
        if nv is not None:
            v = nv
    if v is not None and var in ("rain", "et0"):
        v = max(0.0, v)
    return v


# ── 작동 시계열(env_twin_act) 계열 ──────────────────────────────────────────────────

@dataclass
class ActSeries:
    """효과 채널 한 계열 — 시설 정시 평균 개도 %, 노지 `irrigation_mm` 은 시 시작 타임스탬프의 그 시간 mm."""
    effect: str
    basis: str
    times: List[float]
    values: List[float]
    dev: str = "all"


def worst_basis(bases: Sequence[Optional[str]]) -> str:
    """합친 채널의 출처 = 가장 나쁜 구성원(없음·모름은 `assumed`)."""
    ranked = [b if b in _BASIS_RANK else "assumed" for b in bases] or ["assumed"]
    return max(ranked, key=lambda b: _BASIS_RANK[b])


def hourly_mean_hold(times: Sequence[float], values: Sequence[float], t_from: float, t_to: float,
                     future: Optional[CmdPlan] = None, channel: Optional[str] = None,
                     future_from: Optional[float] = None) -> Tuple[List[float], List[float]]:
    """[t_from 의 정시 이상, t_to) 시간 칸마다 단계(마지막 값 유지) 함수의 시간 가중 평균.

    `times/values` 는 상태 계열(첫 표본 전은 정의되지 않아 칸을 건너뛴다). `future` 와 `future_from` 이 있으면 그 시각부터는
    계획 함수 `future(t)[channel]` 이 이어받는다(한 칸 안에서 섞이면 칸이 섞인 평균이 된다)."""
    out_t: List[float] = []
    out_v: List[float] = []
    if not len(times) and future is None:
        return out_t, out_v

    def edges(a: float, b: float):                       # [a, b) 안의 상태 변화 시각들(양끝 포함)
        pts = {a, b}
        pts.update(t for t in times if a < t < b)
        if future is not None and future_from is not None:
            pts.update(t for t, _ in future.pieces() if a < t < b)
            if a < future_from < b:
                pts.add(future_from)
        return sorted(pts)

    def value_at(t: float) -> Optional[float]:
        if future is not None and future_from is not None and t >= future_from:
            return float(future(t)[channel])
        i = bisect.bisect_right(times, t) - 1
        return float(values[i]) if i >= 0 else None

    h = math.ceil(t_from / HOUR_S - 1e-9) * HOUR_S
    while h + HOUR_S <= t_to + 1e-6:
        e = edges(h, h + HOUR_S)
        acc, span, ok = 0.0, 0.0, True
        for a, b in zip(e[:-1], e[1:]):
            v = value_at(a)
            if v is None:
                ok = False
                break
            acc += v * (b - a)
            span += b - a
        if ok and span > 0:
            out_t.append(h)
            out_v.append(acc / span)
        h += HOUR_S
    return out_t, out_v


# ── 효과 보고(머리말 개수 · 시나리오 effects[]) ───────────────────────────────────────

def effects_report(devices: Sequence[Mapping], domain: str, assumed: Sequence[str] = ()) -> List[Dict[str, object]]:
    """장치마다 `{id, kind, channel, status, source}` — 계약(설계서 §6.2)의 `effects[]`.

    status: 목록표의 반영 상태(modeled|partial|unmodeled). **목록표에 없는 종류·종류를 모르는 설비는 `unknown`, channel=null.**
    이 보고는 목록표 기준이고, 머리말 개수는 `header_counts` 가 센다.
    source: 정격 출처 — measured(정격을 읽음) | estimated(종류 기본값·같은 몫 가정) | unknown(모름)."""
    out = []
    for d in devices:
        kind = d.get("kind")
        row = C.row_for(kind, domain) if kind else C.UNKNOWN_KIND
        known = bool(kind) and row is not C.UNKNOWN_KIND
        ratings = d.get("ratings") or {}
        if not known or not row.ratings:
            source = "unknown" if not known else "measured"
        elif str(d.get("id")) in set(assumed):
            source = "estimated" if any(r.default is not None for r in row.ratings) else "unknown"
        else:
            source = "measured" if all(ratings.get(r.key) for r in row.ratings) else "estimated"
        out.append({"id": str(d.get("id")), "kind": kind, "channel": row.channel if known else None,
                    "status": row.status if known else "unknown", "source": source})
    return out


def header_counts(report: Sequence[Mapping], applied: bool = True) -> Tuple[int, int]:
    """머리말 `effects_modeled`(status=modeled 장치 수) · `effects_unmodeled`(partial·unmodeled·unknown 장치 수)."""
    modeled = sum(1 for r in report if r["status"] == C.MODELED and applied)
    return modeled, len(report) - modeled
