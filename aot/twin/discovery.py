# coding=utf-8
"""대상 자동 발견 — 켜진 대지의 노지 구획을 대상으로, 앞날 예보는 대지 예보 계열로 (배포 제안 §2, S2·S3).

손으로 적던 JSON 배선(`targets[]` 의 구획 id·심은 날·시간대·위도·예보 채널 번호)을 DB 에서 채운다.
**사람이 고르는 것**은 대지·구획 트윈 설정(`twin_config` 표, 지도 모달 '트윈' 탭 — S3·S4)에 있다.
`aot.utils.twin_config.overrides()` 가 그 표를 아래 모양으로 돌려준다:

    {
      "sites": {
        "<대지 id>":   {"enabled": true,                          # 이 대지를 트윈 대상으로
                        "inputs":   {"rain": {"unique_id": …, "unit": "mm", "channel": 0, "provenance": "measured"},
                                     "t_air": {…}, "et0": {…}},
                        "options":  {"rain": {"agg": "hourly_mean_sum", "scale": 4}}}
      },
      "plots": {
        "<구획 id>":   {"enabled": false}                          # 이 구획만 빼기
        "<구획 id>":   {"inputs": {"theta": {…}, "soil_t": {…}, "rain": null}, "options": {"sensor": {"layer": 1}}}
      }
    }

- 값은 (`"*"` →) 대지 → 구획 순으로 덮어쓴다(대지 → 구획 상속). 입력 값이 null 이면 "이 구획에서는 없음".
- 개발용으로 같은 모양의 JSON 을 `--overrides`·`$AOT_TWIN_OVERRIDES` 로 **명시했을 때만** DB 설정 위에 겹친다
  (기본 경로는 없다 — 화면에서 고른 것이 정본).
- **자동으로 채우는 것**: 관수 입력 `irrigation`(구획 자신의 `water_day`), 구획 목록(대지 안의 지금 재배 중인 노지 식생 구획 — 지도와 같은 `active_plots`, 시설 구획·끝난·아직 안 심은 작기 제외), `planted_on`(구획
  시작일), `timezone`(대지 시간대), `lat`(구획 대표점), `forecast_series`(`{"site": 대지}` — 앞날 예보는 대지에 지정한
  예보 출처의 계열, 지도 날씨·AI 와 같은 출처. 출처 지정은 기상원 지정·트윈 탭이 같은 행에 쓴다). 자동 값도 사람이 고른 값이 이긴다.
- **도형 상속으로 채우는 것**(2026-10-26): 비·기온·ET0 = 대지 기상대, 토양수분·지온 = 구획 안/가까운/구역 센서 — 지도·환경제어와
  같은 도형 상속 결과(`twin_config.resolved_overrides`). 저장된 선택(위 `inputs`)이 있으면 덮어쓰기라 상속하지 않는다(null 도 포함).
  저장하지 않으니 상속이 바뀌면 따라간다. 지역·제공자를 코드에 적지 않는다.
- 대지 밖 구획은 지도 하나를 대지 하나로 본다(`map:<지도 id>`).

DB 를 읽는 쪽(`DbCatalog`)은 flask 앱 문맥을 받아 호출 시점에만 import 한다. 조립(`build_plan`)은 순수 함수라
시험이 가짜 목록으로 돈다.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from aot.functions.utils.water_net.result import DAY_FIELDS, M_DAY

from . import forecast as FC
from . import obs_basis as OB
from .settings import SettingsError, _series
from .types import SeriesRef, TargetKind, TargetSpec

logger = logging.getLogger(__name__)

SERVER_ID = "local"


@dataclass
class PlotInfo:
    unique_id: str
    name: str = ""
    started_on: str = ""                 # YYYY-MM-DD
    lat: Optional[float] = None
    lon: Optional[float] = None
    subject: str = ""


@dataclass
class FacilityInfo:
    facility_uuid: str                   # GeoFacility.unique_id — 트윈 설정(scope 'facility')의 대상 id
    name: str = ""
    coordinator_uid: str = ""            # 환경제어 함수(코디네이터) uuid — 출력 태그 `device_id`(계약 §6). 없으면 ""
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class SiteInfo:
    site_id: str                         # GeoShape(site).unique_id, 대지 밖이면 "map:<GeoMap id>"
    name: str = ""
    timezone: str = "UTC"
    plots: List[PlotInfo] = field(default_factory=list)
    facilities: List[FacilityInfo] = field(default_factory=list)


@dataclass
class SitePlan:
    site_id: str
    name: str
    timezone: str
    targets: List[TargetSpec] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _merge(a: Mapping, b: Mapping) -> Dict:
    """얕지 않은 덮어쓰기: 사전끼리는 안으로 들어가 합치고, 그 밖은 b 가 이긴다."""
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_overrides(path: Optional[str] = None) -> Dict:
    """개발용 덮어쓰기 JSON — 명시한 경로(인자·`$AOT_TWIN_OVERRIDES`)만 읽는다. 없으면 빈 사전."""
    path = path or os.environ.get("AOT_TWIN_OVERRIDES", "")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, Mapping):
        raise SettingsError(f"덮어쓰기 {path}: 객체여야 한다")
    for k in ("sites", "plots"):
        if k in d and not isinstance(d[k], Mapping):
            raise SettingsError(f"덮어쓰기 {path}: '{k}' 는 객체여야 한다")
    return dict(d)


def combine(db: Mapping, dev_json: Mapping) -> Dict:
    """DB 설정 위에 개발용 JSON 을 겹친다(JSON 이 이긴다)."""
    return _merge(db or {}, dev_json or {})


def site_config(overrides: Mapping, site_id: str) -> Dict:
    sites = overrides.get("sites") or {}
    return _merge(sites.get("*") or {}, sites.get(site_id) or {})


def build_plan(sites: Sequence[SiteInfo], overrides: Mapping,
               forecast_channels: Callable[[str], Sequence[Mapping]]) -> List[SitePlan]:
    """대상 목록을 대지마다 만든다. 잘못된 배선은 그 대상만 빼고 노트를 남긴다(원칙 1).

    노지 구획은 대지가 켜졌을 때만. **시설은 시설 행의 `enabled` 가 True 일 때만**(대지 켜짐과 무관, 기본 끔) —
    한 대지에 시설·구역·구획이 여럿일 수 있어 각자 켠다. 시설만 켜진 대지도 계획에 들어간다.
    """
    plots_ov = overrides.get("plots") or {}
    facs_ov = overrides.get("facilities") or {}
    ladders: Dict[str, tuple] = {}            # 예보 입력 id → (채널 메타, 오류)
    out: List[SitePlan] = []
    for site in sites:
        scfg = site_config(overrides, site.site_id)
        site_on = bool(scfg.get("enabled", False))
        facs = [f for f in site.facilities if (facs_ov.get(f.facility_uuid) or {}).get("enabled") is True]
        if not site_on and not facs:
            continue
        plan = SitePlan(site.site_id, site.name, str(scfg.get("timezone") or site.timezone or "UTC"))
        for p in (site.plots if site_on else []):
            pcfg = _merge(scfg, plots_ov.get(p.unique_id) or {})
            if pcfg.get("enabled") is False:
                continue
            try:
                plan.targets.append(_target(p, plan.timezone, pcfg, ladders, forecast_channels, plan.notes,
                                            site.site_id))
            except (SettingsError, KeyError, TypeError, ValueError) as e:
                plan.notes.append(f"구획 {p.name or p.unique_id}: 설정 오류 — 뺐다 ({e})")
        for f in facs:
            try:
                plan.targets.append(_facility_target(f, plan.timezone, facs_ov[f.facility_uuid], plan.notes))
            except (SettingsError, KeyError, TypeError, ValueError) as e:
                plan.notes.append(f"시설 {f.name or f.facility_uuid}: 설정 오류 — 뺐다 ({e})")
        out.append(plan)
    return out


#: 결과 한 줄에 쓰는 입력 이름.
_INPUT_KO = {"rain": "비", "t_air": "기온", "et0": "ET0", "theta": "토양수분", "soil_t": "지온"}


def _excluded(cfg: Mapping, inputs: Mapping, who: str, notes: List[str]) -> Dict[str, Dict]:
    """설정의 `excluded`(관측이 아니라 빠진 입력 — `twin_config.drop_non_observations`) 중 지금도 비어 있는 칸만 모아
    '관측이 아님 — 동기화에서 제외' 줄로 `notes` 에 남기고, 모델이 결과 이유에 같은 줄을 쓰도록 돌려준다."""
    out: Dict[str, Dict] = {}
    for k, e in (cfg.get("excluded") or {}).items():
        if k in inputs or not isinstance(e, Mapping):          # 다른 입력으로 바꿨으면 지난 일이다
            continue
        reason = str(e.get("reason") or "")
        out[k] = {"reason": reason, "name": str(e.get("name") or ""),
                  "line": OB.excluded_line(_INPUT_KO.get(k, k), reason, str(e.get("name") or ""))}
        notes.append(f"{who}: {out[k]['line']}")
    return out


def _facility_target(f: FacilityInfo, tz: str, cfg: Mapping, notes: List[str]) -> TargetSpec:
    """시설 대상 하나. 입력·장치 상태·옵션은 전부 사용자가 고른 설정에서 온다(자동으로 고르지 않는다)."""
    tid = f.coordinator_uid
    if not tid:
        tid = f.facility_uuid
        notes.append(f"시설 {f.name or f.facility_uuid}: 환경제어 함수(코디네이터)가 없어 출력 태그에 시설 uuid 를 쓴다")
    inputs = {k: _series(v) for k, v in (cfg.get("inputs") or {}).items() if v}
    options = _merge({"timezone": tz}, cfg.get("options") or {})
    exc = _excluded(cfg, inputs, f"시설 {f.name or f.facility_uuid}", notes)
    if exc:
        options["excluded_inputs"] = exc
    return TargetSpec(server_id=SERVER_ID, kind=TargetKind.FACILITY, target_id=tid, facility=f.facility_uuid[:8],
                      inputs=inputs,
                      controls={k: _series(v) for k, v in (cfg.get("controls") or {}).items() if v},
                      options=options)


def _target(p: PlotInfo, tz: str, cfg: Mapping, ladders: Dict[str, tuple],
            forecast_channels, notes: List[str], site_id: str = "") -> TargetSpec:
    auto: Dict[str, object] = {"timezone": tz}
    if p.started_on:
        auto["planted_on"] = p.started_on
    if p.lat is not None:
        auto["lat"] = round(float(p.lat), 5)
    options = _merge(auto, cfg.get("options") or {})
    # 앞날 예보 = 대지 예보 계열(서버 `geo.forecast_series` — 지도 날씨·AI 와 같은 출처). 어느 입력인지는 대지의
    # 예보 출처 지정(geo_binding)이 정한다 — 여기서 고르지 않는다.
    options["forecast_series"] = {"site": site_id}
    fsrc = cfg.get("forecast") or {}
    if fsrc.get("input"):
        note = "예보 입력(forecast.input)은 대지 예보 출처 지정으로 옮겼다 — 이 값은 쓰지 않는다"
        if note not in notes:
            notes.append(note)
    elif fsrc and any(g in fsrc for g in FC.GROUPS):
        options["forecast"] = dict(fsrc)                           # 사다리를 손으로 적은 경우(개발용 JSON)
    if "forecast" in options:
        FC.parse(options)                                          # 모양 검사 — 틀리면 이 구획만 빠진다
    inputs = {k: _series(v) for k, v in (cfg.get("inputs") or {}).items() if v}
    # 관수 = 이 구획의 닫힌 날 물 결과. 고르는 칸이 아니다 — 구획이 정하고, 점이 없는 날은 모름이다(`models/field_bucket`).
    inputs.setdefault("irrigation", SeriesRef(p.unique_id, M_DAY, DAY_FIELDS.index("mm")))
    exc = _excluded(cfg, inputs, f"구획 {p.name or p.unique_id}", notes)
    if exc:
        options["excluded_inputs"] = exc
    return TargetSpec(server_id=SERVER_ID, kind=TargetKind.FIELD, target_id=p.unique_id, facility="",
                      inputs=inputs, options=options)


def _tz_name(tz) -> Optional[str]:
    """pytz(`zone`)·zoneinfo(`key`) 둘 다."""
    return getattr(tz, "zone", None) or getattr(tz, "key", None) or None


def coordinator_uid_of(facility_uuid: str) -> str:
    """시설에 연결된 환경제어 함수(코디네이터)의 unique_id, 없으면 "" — 시설 화면·`env_summary` 와 같은 판정."""
    try:
        from aot.space.coordinator_link import _find_facility_env_coordinator
        fn = _find_facility_env_coordinator(facility_uuid)
        return str(fn.unique_id) if fn is not None else ""
    except Exception:
        logger.exception("트윈: 시설 %s 코디네이터 찾기 실패", facility_uuid)
        return ""


class DbCatalog:
    """이 기기의 DB 에서 대지·구획·예보 입력 채널 메타를 읽는다 (flask 앱 문맥 필요)."""

    def __init__(self, app):
        self._app = app                  # gate.LazyApp — 처음 읽을 때 앱을 만든다
        self._input_info = None

    def sites(self) -> List[SiteInfo]:
        with self._app.get().app_context():
            return self._sites()

    def overrides(self) -> Dict:
        """대지·구획 트윈 설정(`twin_config` 표) + 저장된 선택이 없는 입력의 도형 상속값(기상대·구획 센서)."""
        with self._app.get().app_context():
            from aot.utils.twin_config import resolved_overrides
            return resolved_overrides(self._sites())

    def _sites(self) -> List[SiteInfo]:
        from shapely.geometry import shape as shapely_shape

        from aot.space.device_membership import load_containers, site_for_geometry
        from aot.space.plot_context import _shape_name, active_plots
        from aot.space.plot_geometry import geometry_of
        from aot.databases.models import GeoFacility, GeoMap, GeoShape
        from aot.utils.geo_hierarchy import containment_point
        from aot.utils.timekit import resolve_tz

        # '지금 재배 중' 판정은 지도와 같은 정본 하나(plot_context.active_plots) — 시설 구획만 뺀다
        rows = sorted((p for p in active_plots() if not getattr(p, "facility_uuid", None)), key=lambda p: p.id)
        maps = {m.unique_id: m for m in GeoMap.query.all()}
        containers: Dict[str, list] = {}
        sites: Dict[str, SiteInfo] = {}

        def site_info(geo_id, geom, pt) -> SiteInfo:
            """도형이 속한 대지(없으면 지도 하나가 대지 하나) — 없으면 만들어 돌려준다."""
            if geo_id not in containers:
                containers[geo_id] = load_containers(geo_id)
            site = site_for_geometry(geo_id, geom, containers[geo_id])
            if site is not None:
                sid, name = site.unique_id, (_shape_name(site) or "")
                tz_ent = site
            else:
                m = maps.get(geo_id)
                sid, name, tz_ent = f"map:{geo_id}", (getattr(m, "name", "") if m else ""), None
            if sid not in sites:
                tz = None
                if tz_ent is not None:
                    try:
                        tz = _tz_name(resolve_tz(tz_ent)[0])
                    except Exception:
                        tz = None
                if not tz and pt is not None:
                    from aot.utils.device_tz import resolve_tz_from_coords
                    tz = resolve_tz_from_coords(pt.y, pt.x)
                if not tz:
                    tz = _tz_name(resolve_tz(None)[0]) or "UTC"
                sites[sid] = SiteInfo(sid, name, str(tz))
            return sites[sid]

        for pl in rows:
            if (getattr(pl, "kind", "vegetation") or "vegetation") != "vegetation":
                continue
            geom = geometry_of(pl) or {}
            if geom.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            pt = containment_point(shapely_shape(geom))
            si = site_info(pl.geo_id, geom, pt)
            si.plots.append(PlotInfo(
                pl.unique_id, getattr(pl, "name", "") or "",
                pl.started_on.isoformat() if getattr(pl, "started_on", None) else "",
                lat=(pt.y if pt is not None else None), lon=(pt.x if pt is not None else None),
                subject=getattr(pl, "subject", "") or ""))

        # 시설 — 시설 외피 도형이 속한 대지에 묶는다. 시설만 있는 대지도 목록에 든다(`plots` 가 비어 있다).
        for fac in sorted(GeoFacility.query.all(), key=lambda f: f.id):
            shp = GeoShape.query.filter_by(unique_id=fac.shape_uuid).first() if fac.shape_uuid else None
            geom = (geometry_of(shp) if shp is not None else {}) or {}
            if geom.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            pt = containment_point(shapely_shape(geom))
            si = site_info(fac.geo_id, geom, pt)
            si.facilities.append(FacilityInfo(
                fac.unique_id, getattr(fac, "name", "") or "", coordinator_uid_of(fac.unique_id),
                lat=(pt.y if pt is not None else None), lon=(pt.x if pt is not None else None)))
        return list(sites.values())

    def forecast_channels(self, input_uid: str) -> List[Dict]:
        # 요청 문맥까지 연다 — 입력 모듈 정보의 지연 번역 문구(gettext)가 로케일 선택에 요청을 요구한다
        with self._app.get().test_request_context():
            from aot.databases.models import DeviceMeasurements, Input
            from aot.utils.inputs import parse_input_information
            inp = Input.query.filter_by(unique_id=input_uid).first()
            if inp is None:
                raise LookupError("입력이 없다")
            if self._input_info is None:
                self._input_info = parse_input_information()
            mdict = (self._input_info.get(inp.device) or {}).get("measurements_dict") or {}
            rows = DeviceMeasurements.query.filter_by(device_id=input_uid).all()
            out = []
            if rows:
                for r in rows:
                    meta = mdict.get(r.channel) or {}
                    out.append({"channel": r.channel, "measurement": r.measurement or meta.get("measurement"),
                                "unit": r.unit or meta.get("unit"), "enabled": bool(r.is_enabled),
                                "lead_d": meta.get("forecast_lead_d"), "daily_stat": meta.get("daily_stat")})
            else:
                for ch, meta in mdict.items():
                    out.append({"channel": ch, "measurement": meta.get("measurement"), "unit": meta.get("unit"),
                                "lead_d": meta.get("forecast_lead_d"), "daily_stat": meta.get("daily_stat")})
            return out
