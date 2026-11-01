# coding=utf-8
"""트윈 노드가 주고받는 값 모양. 계약(docs/design/digital-twin.md) §6·§7·§10.7 을 코드로 옮긴 것."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


class TargetKind(str, enum.Enum):
    FACILITY = "facility"   # 시설(공기 한 덩어리) — 계약 §3~§8
    FIELD = "field"         # 노지 구획 — 계약 §10


class Status(enum.IntEnum):
    """`env_twin*_meta` 채널 0 (계약 §7). 숫자는 바꾸지 않고 추가만 한다."""
    OK = 0
    DEGRADED = 1
    UNSYNCED = 2
    NOT_TWINNABLE = 3
    ERROR = 9


class Provenance(str, enum.Enum):
    """입력의 출처 표시 — 계보(lineage)에 남기는 기록용이다. **동기화·검증 판정에는 쓰지 않는다**(2026-10-26: 위치로 정해진
    센서는 그대로 동기화한다 — 미러 센서는 현장 실측의 사본이다). 모르면 UNKNOWN."""
    MEASURED = "measured"   # 실측
    MIRROR = "mirror"       # 다른 시스템 값의 거울
    VIRTUAL = "virtual"     # 가상·시험 출력
    UNKNOWN = "unknown"     # 미확인


@dataclass(frozen=True)
class SeriesRef:
    """AoT 측정 계열 하나를 가리킨다 (device unique_id · 단위/측정 이름 · 채널).

    `scale` 은 장치 상태(개도·가동) 계열의 선택 값 `(from_min, from_max)` — 있으면 읽은 값을 이 범위에서
    0~100 % 로 옮겨 쓴다. 없으면 값을 건드리지 않는다(임의 변환 금지)."""
    unique_id: str
    unit: str
    channel: int
    provenance: Provenance = Provenance.UNKNOWN
    scale: Optional[Tuple[float, float]] = None


@dataclass
class TargetSpec:
    """트윈 대상 하나(시설 또는 노지 구획)와 그 입력 배선.

    `inputs`/`controls` 의 키는 모델이 정한 논리 이름이다 (예: 시설 `T_int`, `RH_int`, `CO2_int`,
    `T_ext`, `RH_ext`, `solar`, `wind` / 제어 `vent`, `fog` …). 배선은 서버마다 다르므로 설정에서 온다.
    """
    server_id: str
    kind: TargetKind
    target_id: str                       # 출력 device_id 태그 (시설: 코디네이터 unique_id, 노지: 구획 uuid)
    facility: str = ""                   # 출력 facility 태그 (uuid 앞 8자)
    inputs: Mapping[str, SeriesRef] = field(default_factory=dict)
    controls: Mapping[str, SeriesRef] = field(default_factory=dict)
    options: Mapping[str, object] = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.server_id, self.kind.value, self.target_id)


@dataclass
class Series:
    """시간순 (epoch 초, 값). 결측은 건너뛴다."""
    times: List[float] = field(default_factory=list)
    values: List[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.times)

    def last(self) -> Optional[tuple]:
        return (self.times[-1], self.values[-1]) if self.times else None


@dataclass(frozen=True)
class Point:
    """Influx 에 쓸 점 하나. `measurement` 가 `write_influxdb_value` 의 `unit` 인자다 (계약 §6)."""
    measurement: str
    device_id: str
    channel: Optional[int]               # None = 채널 태그를 쓰지 않는 측정(`env_twin_act` — 효과 이름이 태그다)
    timestamp: float
    value: float
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass
class WriteResult:
    written: int = 0
    rejected: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.rejected == 0


@dataclass
class TwinOutput:
    """대상 종류와 무관한 하나의 결과 레코드 (계약 §10.7). 쓰기 층(`output.flatten`)이 측정으로 푼다.

    grids      격자 이름 → 대상 시각(epoch 초) 목록. 시설 `fast`(600 s), 노지 `daily`·`hourly`.
    quantiles  격자 이름 → 변수 → {"p10","p50","p90"} → 값 목록(격자와 같은 길이). 앙상블이 없으면 "p50" 만.
    events     격자 이름 → 사건 이름 → 확률 목록(0~1).
    meta       status, valid_until, horizon_h, ensemble_size, sync_rmse_*, stale_s, model_rev, …
    """
    kind: TargetKind
    target_id: str
    t0: float
    facility: str = ""
    grids: Dict[str, Sequence[float]] = field(default_factory=dict)
    quantiles: Dict[str, Dict[str, Dict[str, Sequence[float]]]] = field(default_factory=dict)
    events: Dict[str, Dict[str, Sequence[float]]] = field(default_factory=dict)
    meta: Dict[str, float] = field(default_factory=dict)


@dataclass
class ForecastSeries:
    """대지의 예보 계열 (`GET /api/twin/forecast_series`, 서버 `geo.forecast_series.read`) — 지도 날씨·AI 와 같은 출처.

    행은 한 시간 칸 `{time, end, <변수>}` (epoch 초, `end = time + 3600`). 변수:
      순간 값(time 정시 값)  temp_c · rh_pct · wind_ms · wind_dir_deg
      칸 값([time, end) 칸)  precip_mm_h · solar_w_m2 · cloud_pct · pop_pct
    결측은 키가 없다(0 이 아니다). `available=False` 이면 지정된 예보 입력이 없거나 낡았다(`reason`).
    """
    available: bool = False
    rows: List[Dict[str, float]] = field(default_factory=list)
    source: str = ""
    input_id: str = ""
    model: str = ""
    fetched_at: Optional[float] = None
    horizon: Optional[float] = None          # 마지막 칸의 끝
    step_s: float = 3600.0
    covers_request: bool = False
    reason: str = ""
    reason_text: str = ""
    #: 대지 현지 하루 행 `{date, time, end, precip_mm?, temp_max_c?, temp_min_c?, et0_mm?, pop_pct?}` — 시간 칸과 같은 계열
    daily: List[Dict[str, object]] = field(default_factory=list)
    source_basis: str = ""                   # designated | map_layer | none
    segments: List[Dict[str, object]] = field(default_factory=list)
    #: 계보(데이터 관리 D3): 쓴 발표본의 정시 기준(시간별), 보정 여부·판(보정 D5 전에는 False·0)
    issued_epoch: Optional[float] = None
    calibrated: bool = False
    cal_rev: int = 0

    @classmethod
    def from_response(cls, d: Mapping) -> "ForecastSeries":
        """서버 응답(dict) → 값. 모양이 이상하면 쓸 수 없는 것으로 본다(트윈은 예보 없이도 돈다)."""
        if not isinstance(d, Mapping):
            return cls(reason="bad_response")
        src = d.get("source") if isinstance(d.get("source"), Mapping) else {}
        res = d.get("resolution") if isinstance(d.get("resolution"), Mapping) else {}
        rows = []
        for r in d.get("rows") or []:
            if isinstance(r, Mapping) and isinstance(r.get("time"), (int, float)) and isinstance(r.get("end"), (int, float)):
                rows.append({k: float(v) for k, v in r.items()
                             if isinstance(v, (int, float)) and not isinstance(v, bool)})
        rows.sort(key=lambda r: r["time"])
        daily = []
        for r in d.get("daily") or []:
            if isinstance(r, Mapping) and isinstance(r.get("time"), (int, float)) and isinstance(r.get("date"), str):
                row: Dict[str, object] = {k: float(v) for k, v in r.items()
                                          if isinstance(v, (int, float)) and not isinstance(v, bool)}
                row["date"] = r["date"]
                daily.append(row)
        daily.sort(key=lambda r: r["time"])
        ok = bool(d.get("available")) and bool(rows or daily)

        def num(v):
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        return cls(available=ok, rows=rows if ok else [], source=str(src.get("name") or ""),
                   input_id=str(src.get("input_id") or ""), model=str(src.get("model") or ""),
                   fetched_at=num(d.get("fetched_at")), horizon=num(d.get("horizon")),
                   step_s=num(res.get("step_s")) or 3600.0, covers_request=bool(d.get("covers_request")),
                   reason=str(d.get("reason") or ("" if ok else "no_rows")), reason_text=str(d.get("reason_text") or ""),
                   daily=daily if ok else [], source_basis=str(d.get("source_basis") or ""),
                   segments=[dict(sg) for sg in (d.get("segments") or []) if isinstance(sg, Mapping)],
                   issued_epoch=num(d.get("issued_epoch")), calibrated=bool(d.get("calibrated")),
                   cal_rev=int(num(d.get("cal_rev")) or 0))
