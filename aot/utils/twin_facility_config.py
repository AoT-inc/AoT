# coding=utf-8
"""디지털트윈(실험) 시설 설정 — 검증·판정·제안·화면 한 장 (계획서 §9.18, 설계 2026-10-23).

정본은 노지와 같은 `twin_config` 표(scope 'facility', `target_id` = `GeoFacility.unique_id`). 읽기·쓰기는
`aot.utils.twin_config` 가 하고, 이 모듈은 **시설에만 있는 규칙**을 맡는다:

- **칸**: 입력 `T_int RH_int CO2_int T_ext RH_ext CO2_ext solar wind`, 장치 실제 상태 `controls`
  (`heat cool vent fog co2_inj shade curtain`, 0~100 % — 다른 범위는 칸의 `scale` 로, 없으면 변환하지 않는다).
  시설 모델 부품(`aot.twin.models.facility_greybox`)이 받는 논리 이름과 같다(시험이 맞춰 본다).
- **상속 없음**: 시설은 대지에서 입력을 물려받지 않는다. 노지 `t_air` 는 대지 일 단위 기상이고 시설 `T_ext` 는
  시간 단위 외기라 뜻이 다르다. 대지 기상 채널은 제안으로만 보이고 사용자가 '적용'해야 들어간다.
- **켜기**: 시설 행의 `enabled` 가 True 일 때만(기본 끔) — 대지 켜짐과 무관하다.
- **출처**: 사람이 정한다(실측·미러·가상·미확인). 코드는 자동 승격하지 않는다. 가상·시험 출력 채널은 '실측' 으로
  저장할 수 없다(실제 장치가 아니다). 입력 모듈이 실측이라고 밝히지 않은 채널을 처음 '실측' 으로 정하면
  저장 응답에 `notices` 한 번 — 화면이 전역 토스트로 보인다.

지역·제공자 이름은 이 모듈에 없다. 순수 함수(`validate_config`·`verdict`)는 DB 없이 시험한다.

@phase active
@stability experimental
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from aot.utils import twin_config as TC
from aot.utils.twin_config import TwinConfigError

logger = logging.getLogger(__name__)

SCOPE = 'facility'
INPUT_KEYS = ('T_int', 'RH_int', 'CO2_int', 'T_ext', 'RH_ext', 'CO2_ext', 'solar', 'wind')
REQUIRED_INPUTS = ('T_int', 'RH_int', 'T_ext', 'RH_ext')
CONTROL_KEYS = ('heat', 'cool', 'vent', 'fog', 'co2_inj', 'shade', 'curtain')
#: 옵션 숫자 칸과 허용 범위(포함). 이 밖의 키는 거부한다.
OPTION_NUMBERS = {'T_high': (-50.0, 80.0), 'T_low': (-50.0, 80.0), 'RH_high': (0.0, 100.0),
                  'sync_window_h': (6.0, 168.0)}
#: 시설 외피 센서 종류 → 입력 칸(제안용)
INDOOR_MTYPE = {'temperature': 'T_int', 'humidity': 'RH_int', 'co2': 'CO2_int'}
OUTDOOR_MTYPE = {'temperature': 'T_ext', 'humidity': 'RH_ext', 'co2': 'CO2_ext', 'light': 'solar',
                 'wind_speed': 'wind'}
#: 대지 기상 채널 측정 이름 → 외기 칸(제안용, 이름은 입력 모듈이 정한 표준 측정 이름)
SITE_WEATHER_KEY = {'temperature': 'T_ext', 'humidity': 'RH_ext', 'speed': 'wind', 'wind_speed': 'wind',
                    'radiation': 'solar', 'solar_radiation': 'solar', 'light': 'solar'}
MAX_SUGGESTIONS = TC.MAX_SUGGESTIONS


# ── 순수 함수 ─────────────────────────────────────────────────────────────────

def _control_series(d, key: str) -> Optional[Dict]:
    out = TC._series(d, key)
    if out is None:
        return None
    sc = d.get('scale')
    if sc is not None:
        if not isinstance(sc, Mapping):
            raise TwinConfigError('%s: scale 은 {from_min, from_max} 객체여야 한다' % key)
        try:
            lo, hi = float(sc['from_min']), float(sc['from_max'])
        except (KeyError, TypeError, ValueError):
            raise TwinConfigError('%s: scale 은 {from_min, from_max} 두 수' % key)
        if not hi > lo:
            raise TwinConfigError('%s: scale 의 from_max 는 from_min 보다 커야 한다' % key)
        out['scale'] = {'from_min': lo, 'from_max': hi}
    return out


def validate_config(cfg: Mapping) -> Dict:
    """저장 전 검사·정리. 모르는 키는 버리지 않고 거부한다(조용히 사라지면 사용자가 모른다)."""
    if cfg is None:
        return {}
    if not isinstance(cfg, Mapping):
        raise TwinConfigError('설정은 객체여야 한다')
    unknown = set(cfg) - {'inputs', 'controls', 'options', 'effects'}
    if unknown:
        raise TwinConfigError('모르는 항목: %s' % ', '.join(sorted(unknown)))
    out: Dict = {}
    for part, keys, label, mk in (('inputs', INPUT_KEYS, '입력', TC._series),
                                  ('controls', CONTROL_KEYS, '장치 상태', _control_series)):
        if part not in cfg:
            continue
        d = cfg.get(part) or {}
        if not isinstance(d, Mapping):
            raise TwinConfigError('%s 는 객체여야 한다' % part)
        bad = set(d) - set(keys)
        if bad:
            raise TwinConfigError('모르는 %s: %s' % (label, ', '.join(sorted(bad))))
        out[part] = {k: mk(v, k) for k, v in d.items()}
    if 'options' in cfg:
        opts = cfg.get('options') or {}
        if not isinstance(opts, Mapping):
            raise TwinConfigError('options 는 객체여야 한다')
        bad = set(opts) - set(OPTION_NUMBERS) - {'forecast_series'}
        if bad:
            raise TwinConfigError('모르는 옵션: %s' % ', '.join(sorted(bad)))
        clean: Dict = {}
        for k, v in opts.items():
            if k == 'forecast_series':
                if v is None:
                    clean[k] = None
                    continue
                if not isinstance(v, Mapping) or not str(v.get('site') or '').strip() or set(v) - {'site'}:
                    raise TwinConfigError('options.forecast_series 는 {"site": 대지 id} 이거나 null')
                clean[k] = {'site': str(v['site']).strip()}
                continue
            lo, hi = OPTION_NUMBERS[k]
            try:
                x = float(v)
            except (TypeError, ValueError):
                raise TwinConfigError('options.%s 는 수' % k)
            if not lo <= x <= hi:
                raise TwinConfigError('options.%s 는 %g ~ %g' % (k, lo, hi))
            clean[k] = x
        json.dumps(clean)
        out['options'] = clean
    if cfg.get('effects') is not None:
        from aot.utils.twin_effects_link import validate_overrides
        eff = validate_overrides(cfg['effects'], 'facility')
        if eff:
            out['effects'] = eff
    return out


# @manual geo/map-widget#twin-tab
def verdict(enabled: Optional[bool], cfg: Mapping, excluded: Optional[Mapping] = None) -> Dict[str, object]:
    """이 설정으로 시설 트윈이 서는가 — 시설 부품(`facility_greybox`)이 실행 때 거부하는 조건과 같은 순서.

    code: `missing_inputs`(필수 입력 빠짐) · `no_controls`(장치 실제 상태 없음 = not_twinnable) ·
    `ready`. 출처 표시(실측·미러·가상)는 보지 않는다 — 위치와 사용자가 고른 계열 그대로 쓴다.
    `excluded` = 고른 입력 중 관측이 아니라(예보·모델값·시뮬레이터) 동기화에서 빠지는 칸 `{칸: 이유}` — 빠진 칸은 비어 있는 것과
    같게 센다. `enabled` 는 따로 알린다(꺼져 있어도 막힌 이유는 보인다). **개발서버 설정 점검이지 현장 판정이 아니다.**
    """
    ins = {k: v for k, v in ((cfg or {}).get('inputs') or {}).items() if k not in (excluded or {})}
    ctl = {k: v for k, v in ((cfg or {}).get('controls') or {}).items() if v}
    missing = [k for k in REQUIRED_INPUTS if not ins.get(k)]
    if missing:
        code = 'missing_inputs'
    elif not ctl:
        code = 'no_controls'
    else:
        code = 'ready'
    return {'code': code, 'enabled': bool(enabled), 'missing': missing, 'unverified': [],
            'excluded': sorted(excluded or {}), 'controls': len(ctl)}


# ── DB (flask 앱 문맥) ─────────────────────────────────────────────────────────

def save(facility_uuid: str, enabled=None, config: Optional[Mapping] = None, *, set_enabled: bool = False):
    """시설 한 행 쓰기. 돌려주는 `notices` 는 늘 빈 목록이다(응답 모양만 유지)."""
    from aot.databases.models import GeoFacility
    if GeoFacility.query.filter_by(unique_id=str(facility_uuid)).first() is None:
        raise TwinConfigError('시설을 찾을 수 없다')
    if config is not None:
        validate_config(config)
    TC.save(SCOPE, facility_uuid, enabled, config, set_enabled=set_enabled)
    return []                                    # 출처 표시 알림은 없앴다(응답 모양만 유지)


def _facility_row(facility_uuid: str):
    from aot.databases.models import GeoFacility
    return GeoFacility.query.filter_by(unique_id=str(facility_uuid)).first()


def _channel_of_measurement(measurement_id: str) -> Optional[Dict[str, object]]:
    """시설 센서가 고른 측정(`measurement_id`) → 트윈 계열 제안 한 줄."""
    from aot.databases.models import DeviceMeasurements
    dm = DeviceMeasurements.query.filter_by(unique_id=measurement_id).first()
    if dm is None or not (dm.unit or ''):
        return None
    names = TC._device_names([dm.device_id])
    if dm.device_id not in names:
        return None
    dname, module = names[dm.device_id]
    c = {'unique_id': dm.device_id, 'device_name': dname, 'channel': int(dm.channel or 0), 'name': dm.name or '',
         'measurement': dm.measurement or '', 'unit': TC.stored_unit(dm, TC._conversions([dm]))}
    return dict(TC._as_series(dict(c, provenance_hint=TC.provenance_hint(module))), label=TC._label(c))


def suggestions(facility_uuid: str, site=None) -> Dict[str, List[Dict]]:
    """칸마다 제안 — ① 시설 안·밖 센서(시설 편집에서 고른 것) ② 없는 외기 칸은 대지 기상 채널.
    장치 상태(`controls`)는 시설에 묶인 장치 목록만 `actuators` 로 알린다(상태 채널은 직접 고른다)."""
    from aot.aot_flask.geo.facility_integration import get_facility_integration
    out: Dict[str, List[Dict]] = {k: [] for k in INPUT_KEYS}
    integ, err = get_facility_integration(facility_uuid)
    if err or not integ:
        out['actuators'] = []
        return out

    def add(key, row, why):
        if len(out[key]) < MAX_SUGGESTIONS and all((x['unique_id'], x['channel']) != (row['unique_id'], row['channel'])
                                                   for x in out[key]):
            out[key].append(dict(row, why=why))

    for entries, table, why in ((integ.get('sensors_resolved') or [], INDOOR_MTYPE, 'facility_sensor_indoor'),
                                (integ.get('sensors_outdoor') or [], OUTDOOR_MTYPE, 'facility_sensor_outdoor')):
        for e in entries:
            key = table.get(e.get('measurement_type') or '')
            if key and e.get('measurement_id'):
                row = _channel_of_measurement(e['measurement_id'])
                if row:
                    add(key, row, why)
    missing = [k for k in ('T_ext', 'RH_ext', 'solar', 'wind') if not out[k]]
    sid = getattr(site, 'site_id', '') or ''
    if missing and sid and not sid.startswith('map:'):
        try:
            from aot.aot_flask.geo.device_membership import weather_device_ids
            ids, _src = weather_device_ids(sid)
            for c in TC.channels(ids):
                key = SITE_WEATHER_KEY.get(c['measurement'])
                if key in missing and c['unit']:
                    add(key, dict(TC._as_series(c), label=TC._label(c)), 'weather_site')
        except Exception:
            logger.exception('트윈 제안: 대지 기상 채널 읽기 실패 %s', sid)
    out['actuators'] = [{'output_uuid': a.get('output_uuid'), 'name': a.get('output_name'), 'kind': a.get('kind')}
                        for a in (integ.get('actuators_resolved') or [])]
    return out


def _catalog():
    from aot.twin.discovery import DbCatalog
    return DbCatalog(None)._sites()


def locate(facility_uuid: str, sites=None):
    """(대지 정보, 시설 정보) — 시설이 도형·대지에 묶여 있지 않으면 (None, None)."""
    for s in (sites if sites is not None else _catalog()):
        for f in s.facilities:
            if f.facility_uuid == facility_uuid:
                return s, f
    return None, None


# @manual geo/map-widget#twin-tab
def facility_view(facility_uuid: str, sites=None, with_suggestions: bool = True) -> Dict[str, object]:
    """시설 트윈 탭 한 장 — 설정·판정·출력 태그(코디네이터)·제안."""
    row = _facility_row(facility_uuid)
    enabled, cfg = TC.read(SCOPE, facility_uuid)
    site, fac = locate(facility_uuid, sites)
    eff_cfg = cfg
    if row is not None:                                      # 손배선이 없으면 위치로 읽은 장치가 '쓰는 값' (저장하지 않는다)
        from aot.utils import twin_effects_link as EL
        eff_cfg = EL.inherit_facility(facility_uuid, cfg)
    exc = {k: e['reason'] for k, e in TC.exclusions((eff_cfg or {}).get('inputs')).items()}
    out = {'facility_id': facility_uuid, 'eligible': row is not None, 'name': getattr(row, 'name', '') or '',
           'enabled': bool(enabled), 'config': cfg, 'excluded': exc, 'verdict': verdict(enabled, eff_cfg, exc),
           'site_id': site.site_id if site else None, 'site_name': site.name if site else '',
           'coordinator': (fac.coordinator_uid if fac else '') or None}
    if row is not None:
        out['effects'] = EL.facility_effects(facility_uuid, cfg)
    if row is not None and with_suggestions:
        out['suggestions'] = suggestions(facility_uuid, site)
    return out


def overview(sites=None) -> List[Dict[str, object]]:
    """설정 > 디지털트윈 표의 시설 행 — 켜짐·판정·대지. 제안은 싣지 않는다(무겁다)."""
    from aot.utils import twin_effects_link as EL
    sites = sites if sites is not None else _catalog()
    rows = {r.target_id: (r.enabled, r.config_dict())
            for r in TC._model().query.filter(TC._model().scope == SCOPE).all()}
    out = []
    for s in sites:
        for f in s.facilities:
            enabled, cfg = rows.get(f.facility_uuid, (None, {}))
            cfg = EL.inherit_facility(f.facility_uuid, cfg)          # 판정은 위치로 읽은 장치까지 본다
            out.append({'facility_id': f.facility_uuid, 'name': f.name, 'site_id': s.site_id, 'site_name': s.name,
                        'enabled': bool(enabled), 'coordinator': f.coordinator_uid or None,
                        'verdict': verdict(enabled, cfg, {k: e['reason'] for k, e
                                                          in TC.exclusions((cfg or {}).get('inputs')).items()})})
    out.sort(key=lambda r: (not r['enabled'], r['site_name'] or r['site_id'], r['name']))
    return out
