# coding=utf-8
"""앞날 입력 — 사용자가 등록한 **AoT 예보 입력**의 채널을 읽어 앞날 비·ET0·기온으로 쓴다 (계획서 §9.8).

원칙은 같다: 노드는 외부 API 를 부르지 않고, 어떤 제공자·지역도 가정하지 않는다. 예보가 어디서
오는지는 설정이 가리키는 AoT 측정 계열이 정한다(예: `OPEN_METEO_DAILY_FORECAST` 입력, 기상청 예보
입력을 같은 모양으로 만들어도 된다).

## 계열 모양 — "리드 사다리"

예보 입력은 **받은 시각**에 `k 일 뒤의 값` 을 채널 하나(k = 0, 1, …)에 쓴다. 그래서 한 값의 대상 날짜는
`(저장 시각의 구획 현지 날짜) + k` 이고, 같은 대상 날짜에 값이 여럿이면 **가장 늦게 받은 것**이 이긴다.
설정은 묶음마다 사다리를 적는다.

    "forecast": {
      "timezone": "Asia/Seoul",          # 생략하면 구획 시간대 — 예보 입력의 날짜 기준과 같아야 한다
      "max_age_h": 36,                   # 이보다 오래된 값은 쓰지 않는다
      "rain":  {"unique_id": "<입력 id>", "unit": "mm", "channels": [0,1,2,3,4,5,6,7],
                "scale": 1.0, "log_sd": 0.35, "log_sd_per_day": 0.08},
      "et0":   {"unique_id": "<입력 id>", "unit": "mm", "channels": [8,9,10,11,12,13,14,15]},
      "t_max": {"unique_id": "<입력 id>", "unit": "C", "channels": [16,…,23]},
      "t_min": {"unique_id": "<입력 id>", "unit": "C", "channels": [24,…,31]}
    }

`channels[k]` 가 null 이면 그 리드는 없다. **`rain` 만 있어도 된다** — ET0·기온이 없으면 최근 7 일 평균을 쓴다.

## 불확실성 — 앙상블이 없으니 비 배율 오차로

예보 값은 점 하나다. 비는 멤버마다 로그정규 배율(평균 1)을 곱하고, 표준편차는 리드가 길수록 커진다:
`sd(k) = log_sd + log_sd_per_day × k`(상한 `log_sd_max`, 기본 1.0). 기본값은 가정이며(EnKF 가 쓰는 0.35 에서
출발) 아직 검증 전이다 — 예보 이력이 쌓이면 §9.8 의 검정으로 보정한다. 한계: 예보가 0 mm 인 날은 배율을
곱해도 0 이라 "예보가 놓친 비" 는 담기지 않는다.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from .types import Provenance, SeriesRef

logger = logging.getLogger(__name__)

GROUPS = ("rain", "et0", "t_max", "t_min")
DEFAULT_MAX_AGE_H = 36.0
DEFAULT_LOG_SD = 0.35
DEFAULT_LOG_SD_PER_DAY = 0.08
DEFAULT_LOG_SD_MAX = 1.0


class ForecastConfigError(ValueError):
    pass


@dataclass
class Group:
    """묶음 하나(비·ET0·…)의 사다리: 리드 k → 계열."""
    name: str
    refs: Dict[int, SeriesRef]
    scale: float = 1.0
    log_sd: float = DEFAULT_LOG_SD
    log_sd_per_day: float = DEFAULT_LOG_SD_PER_DAY
    log_sd_max: float = DEFAULT_LOG_SD_MAX


@dataclass
class Forecast:
    """읽은 결과. 값은 구획 현지 '일 번호' → 값."""
    rain_mm: Dict[int, float] = field(default_factory=dict)
    et0_mm: Dict[int, float] = field(default_factory=dict)
    t_mean: Dict[int, float] = field(default_factory=dict)
    rain_groups: Optional[Group] = None
    notes: List[str] = field(default_factory=list)
    #: 계보(데이터 관리 D3): 쓴 예보 발표본의 받은 시각 · 보정 판. 대지 예보 계열(`read_forecast`)을 쓴 때만 채운다.
    issued_at: Optional[float] = None
    cal_rev: int = 0

    def rain_log_sd(self, lead_d: int, default: float = DEFAULT_LOG_SD) -> float:
        g = self.rain_groups
        if g is None:
            return default
        return min(g.log_sd_max, g.log_sd + g.log_sd_per_day * max(0, lead_d))


def parse(options: Mapping) -> Dict[str, Group]:
    """target.options['forecast'] → 묶음 사전. 없으면 빈 사전(= 예보 미배선)."""
    cfg = options.get("forecast")
    if not cfg:
        return {}
    if not isinstance(cfg, Mapping):
        raise ForecastConfigError("options.forecast 는 객체여야 한다")
    out: Dict[str, Group] = {}
    for name in GROUPS:
        g = cfg.get(name)
        if not g:
            continue
        try:
            uid, unit, chans = str(g["unique_id"]), str(g["unit"]), list(g["channels"])
        except (KeyError, TypeError) as e:
            raise ForecastConfigError(f"forecast.{name}: unique_id·unit·channels 가 필요하다 ({e})")
        refs = {k: SeriesRef(uid, unit, int(c), Provenance.MIRROR)
                for k, c in enumerate(chans) if c is not None}
        if not refs:
            raise ForecastConfigError(f"forecast.{name}: channels 가 비었다")
        out[name] = Group(
            name, refs, scale=float(g.get("scale", 1.0)),
            log_sd=float(g.get("log_sd", DEFAULT_LOG_SD)),
            log_sd_per_day=float(g.get("log_sd_per_day", DEFAULT_LOG_SD_PER_DAY)),
            log_sd_max=float(g.get("log_sd_max", DEFAULT_LOG_SD_MAX)))
    if cfg and not out:
        raise ForecastConfigError("options.forecast 에 rain·et0·t_max·t_min 중 하나는 있어야 한다")
    return out


def _ladder(group: Group, source, now: float, tz: float, max_age_s: float) -> Dict[int, float]:
    """사다리 → {대상 일 번호: 값}. 같은 날은 가장 늦게 받은 값."""
    return {d: v for d, (_t, v) in ladder_with_times(group, source, now, tz, max_age_s).items()}


def ladder_with_times(group: Group, source, now: float, tz: float, max_age_s: float) -> Dict[int, tuple]:
    """사다리 → {대상 일 번호: (받은 시각, 값)}. 같은 날은 가장 늦게 받은 값.

    서버의 대지 예보 계열(`geo.forecast_series`)도 이 함수로 일별 값을 만든다 — 트윈과 화면·AI 가 같은 규칙을 쓴다."""
    best: Dict[int, tuple] = {}                    # day → (저장 시각, 값)
    for k, ref in group.refs.items():
        try:
            s = source.read_series(ref, max_age_s, now)
        except Exception as e:                     # 예보 읽기 실패가 실행을 막지 않는다(원칙 1)
            logger.warning("트윈 예보: %s 리드 %d 읽기 실패: %s", group.name, k, e)
            continue
        for t, v in zip(s.times, s.values):
            if v is None or not math.isfinite(v) or t > now + 60 or now - t > max_age_s:
                continue
            day = int(math.floor((t + tz) / 86400.0)) + k
            if day not in best or t > best[day][0]:
                best[day] = (t, float(v))
    return best


def load(options: Mapping, source, now: float, tz: float, today: int,
         tz_override: Optional[float] = None) -> Forecast:
    """설정의 예보 사다리를 읽는다. `today` 이전 날은 버린다(이미 지난 날은 관측이 맡는다)."""
    groups = parse(options)
    fc = Forecast()
    if not groups:
        return fc
    cfg = options["forecast"]
    max_age_s = float(cfg.get("max_age_h", DEFAULT_MAX_AGE_H)) * 3600.0
    ftz = tz if tz_override is None else tz_override

    def keep(m):
        return {d: v for d, v in m.items() if d >= today}

    if "rain" in groups:
        g = groups["rain"]
        fc.rain_groups = g
        fc.rain_mm = keep({d: max(0.0, v * g.scale) for d, v in _ladder(g, source, now, ftz, max_age_s).items()})
        if not fc.rain_mm:
            fc.notes.append("예보 비 계열이 비었거나 낡음 — 앞날 비 없음 가정")
    if "et0" in groups:
        g = groups["et0"]
        fc.et0_mm = keep({d: max(0.0, v * g.scale) for d, v in _ladder(g, source, now, ftz, max_age_s).items()})
    tx = keep(_ladder(groups["t_max"], source, now, ftz, max_age_s)) if "t_max" in groups else {}
    tn = keep(_ladder(groups["t_min"], source, now, ftz, max_age_s)) if "t_min" in groups else {}
    fc.t_mean = {d: 0.5 * (tx[d] + tn[d]) for d in tx if d in tn}
    return fc


def coverage_days(fc: Forecast, today: int, trust_d: int) -> int:
    """신뢰 구간(오늘 … 오늘 + trust_d) 가운데 예보 비가 있는 날 수 (0 … trust_d + 1)."""
    return sum(1 for d in range(today, today + trust_d + 1) if d in fc.rain_mm)


# ── 사다리 자동 생성 — 예보 입력의 채널 메타에서 (배포 제안 §2 '채널 메타로 사다리 자동') ──────────
#
# 사람이 고르는 것은 **어느 예보 입력을 쓰나**(입력 id) 하나다. 채널 번호를 손으로 적지 않는다.
# 입력 모듈이 채널마다 `forecast_lead_d`(리드, 일)와 `daily_stat`(sum·max·min)을 밝히면 그것으로
# 묶음을 만든다. 제공자·지역 이름은 보지 않는다 — 같은 메타를 단 다른 예보 입력도 그대로 된다.

# (측정, 일 통계) → 묶음, 묶음이 기대하는 단위
_GROUP_OF = {("rain", "sum"): "rain", ("precipitation", "sum"): "rain",
             ("evapotranspiration", "sum"): "et0",
             ("temperature", "max"): "t_max", ("temperature", "min"): "t_min"}
_UNIT_OF = {"rain": "mm", "et0": "mm", "t_max": "C", "t_min": "C"}


def ladder_from_channels(input_uid: str, channels, extra: Optional[Mapping] = None):
    """채널 메타 목록 → `options.forecast` 사전(위 머리말의 모양), 그리고 사람용 노트.

    channels: [{"channel", "measurement", "unit", "lead_d", "daily_stat", "enabled"}]. 리드 메타가 없는
    채널은 건너뛴다. 꺼진 채널·빠진 리드는 그 자리를 None 으로 둔다. 단위가 묶음과 다르면(사용자가
    변환을 걸었으면) 그 묶음은 쓰지 않는다 — 모델은 mm·°C 로 계산한다. 쓸 묶음이 없으면 (None, 노트)."""
    notes: List[str] = []
    by_group: Dict[str, Dict[int, int]] = {}
    units: Dict[str, str] = {}
    for c in channels or ():
        lead, stat = c.get("lead_d"), c.get("daily_stat")
        if lead is None or stat is None:
            continue
        g = _GROUP_OF.get((str(c.get("measurement", "")), str(stat)))
        if g is None:
            continue
        if not c.get("enabled", True):
            continue
        unit = str(c.get("unit", ""))
        if unit != _UNIT_OF[g]:
            units.setdefault(g, unit)
            continue
        by_group.setdefault(g, {})[int(lead)] = int(c["channel"])
    for g, u in units.items():
        if g not in by_group:
            notes.append(f"예보 {g}: 단위 {u!r} 는 {_UNIT_OF[g]} 가 아니라 쓰지 않음")
    if "rain" not in by_group:
        notes.append("예보 입력에 비(리드 메타가 있는 강수 일 합) 채널이 없다 — 앞날 비 없음 가정")
        if not by_group:
            return None, notes
    extra = dict(extra or {})
    cfg: Dict[str, object] = {k: v for k, v in extra.items() if k not in GROUPS and k != "input"}
    for g, m in by_group.items():
        n = max(m) + 1
        ov = extra.get(g) if isinstance(extra.get(g), Mapping) else {}
        cfg[g] = {**{k: v for k, v in ov.items() if k not in ("unique_id", "unit", "channels")},
                  "unique_id": str(input_uid), "unit": _UNIT_OF[g], "channels": [m.get(k) for k in range(n)]}
    return cfg, notes
