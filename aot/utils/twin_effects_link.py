# coding=utf-8
"""장치 → 효과 채널 자동 연결의 서버 쪽 글루 (설계서 §3 · 2026-10-26 개정).

연결은 위치가 정한다: 시설 피팅에 묶인 장치(`GeoBinding`)는 통합 payload(`facility_integration`, 코디네이터가 읽는 것과
같은 것)에서 **종류**를 읽고, 효과 목록표가 채널을 정하고, 정격·상태 출처는 읽기 모듈이 정한다. 이 모듈은 DB 에서 그 재료를
모아 순수 모듈(`aot.functions.utils.twin_effects.{reader,links,state}`)에 넘기고, 세 곳에 결과를 준다:

1. 화면 — 시설·대지 트윈 탭의 '장치 → 효과 채널' 읽는 줄(`facility_effects`·`site_effects`)
2. 실행 — 트윈이 읽는 설정에 상속값으로 채운다(`inherit_facility`): 손으로 장치 상태를 배선하지 않은 시설은
   `controls`(장치 id → 상태 계열)와 `options.effects` 를 자동으로 얻는다. 저장하지 않는다.
3. 검증 — 저장하는 덮어쓰기 `effects`(종류를 모르는 설비에 종류 주기, 장치 빼기)의 검사

사람이 장치 상태를 손으로 배선한 시설(`controls` 가 있는 설정)은 그대로 둔다 — 그것이 덮어쓰기다.
노지(시설 밖) 출력은 물 회로가 풀어 준다: 담당 폴리곤이 구획에 닿아 물을 대는 출력은 관수, 공급 부품 자리의 출력은 공급이다.
어느 쪽도 아닌 범용 출력만 역할을 묻는다. 물은 구획의 `water_day` 로 모델에 들어가므로, 물 근거가 없는 출력은 줄에 `applied: false` 로 알린다.

@phase active
@stability experimental
"""
from __future__ import annotations

import logging
from typing import Dict, List, Mapping, Optional

from aot.functions.utils.twin_effects import catalog as C
from aot.functions.utils.twin_effects import links as L
from aot.functions.utils.twin_effects import reader as R
from aot.functions.utils.twin_effects.aggregate import Device
from aot.utils import twin_device_state as TDS

logger = logging.getLogger(__name__)


def validate_overrides(obj, domain: str = C.FACILITY) -> Dict[str, Dict]:
    """저장 전 검사 — `twin_config.TwinConfigError` 로 바꿔 던진다."""
    from aot.utils.twin_config import TwinConfigError
    try:
        res = L.validate_overrides(obj, domain)
    except L.OverrideError as e:
        raise TwinConfigError('effects: %s' % e)
    return {'devices': res} if res else {}


def _overrides_of(cfg: Optional[Mapping]) -> Dict[str, Dict]:
    return dict(((cfg or {}).get('effects') or {}).get('devices') or {})


# ── 시설 ─────────────────────────────────────────────────────────────────────────

def _shape_areas(output_uuids: List[str]) -> Dict[str, float]:
    """도형 면적 — 로더가 개구부 면적을 못 구했을 때만 쓰는 마지막 근거(로더의 규칙 그대로)."""
    out: Dict[str, float] = {}
    try:
        from aot.space.device_binding import shapes_for_devices
        from aot.space.facility_geo_helpers import shape_azimuth_area
        for dev, rows in shapes_for_devices(output_uuids).items():
            shape = rows[0] if rows else None
            if shape is not None and shape.feature:
                _az, area = shape_azimuth_area(shape.feature)
                if area and area > 0:
                    out[dev] = float(area)
    except Exception:
        logger.debug('트윈 효과: 도형 면적 읽기 실패', exc_info=True)
    return out


def read_facility(facility_uuid: str) -> Optional[R.ReadResult]:
    """시설의 장치 읽기 — 못 읽으면 None(호출자가 '읽지 못함'으로 알린다)."""
    from aot.space.facility_integration import get_facility_integration
    integ, err = get_facility_integration(facility_uuid)
    if err or not integ:
        logger.warning('트윈 효과: 시설 %s 통합 읽기 실패: %s', facility_uuid, err)
        return None
    uids = [a['output_uuid'] for a in (integ.get('actuators_resolved') or []) if a.get('output_uuid')]
    supply = _facility_supply(facility_uuid)
    read = R.devices_from_integration(integ, _shape_areas(uids), (supply or {}).get('lpm'))
    read.supply = supply or {}
    return read


def _facility_supply(facility_uuid: str) -> Optional[Dict]:
    """물 회로의 공급 사실 — 못 읽으면 없는 것으로 친다(분무 유량은 설계값 그대로 나간다)."""
    try:
        from aot.utils.water_net_link import facility_supply
        return facility_supply(facility_uuid)
    except Exception:
        logger.exception('트윈 효과: 시설 %s 공급 읽기 실패', facility_uuid)
        return None


def facility_effects(facility_uuid: str, cfg: Optional[Mapping] = None) -> Dict[str, object]:
    """시설 트윈 탭의 '장치 → 효과 채널' — {mode, rows, summary}. 못 읽으면 {'error': ...}."""
    read = read_facility(facility_uuid)
    if read is None:
        return {'error': 'integration_unreadable', 'rows': [], 'summary': L.summarize([]),
                'kinds': L.selectable_kinds(C.FACILITY)}
    ov = _overrides_of(cfg)
    kinds = {d.actuator_id: d.kind for d in L.effective_devices(read, ov)}
    state = TDS.resolve(kinds) if kinds else {}
    rows = L.build_rows(read, state, ov)
    manual = bool(((cfg or {}).get('controls')) or {})
    for r in rows:
        r['applied'] = True
    return {'mode': 'manual' if manual else 'auto', 'rows': rows, 'summary': L.summarize(rows),
            'kinds': L.selectable_kinds(C.FACILITY), 'supply': read.supply or None}


def inherit_facility(facility_uuid: str, cfg: Optional[Mapping]) -> Dict:
    """실행이 읽는 설정 — 장치 상태를 손으로 배선하지 않았으면 위치로 읽은 장치로 채운 사본.

    `controls` = {장치 id: 상태 계열}, `options.effects` = 장치별 종류·정격·상태 출처. 읽지 못하거나 연결할 장치가 없으면
    설정을 그대로 돌려준다(그러면 '장치 상태 없음' 판정이 선다)."""
    cfg = dict(cfg or {})
    if cfg.get('controls'):
        return cfg                                         # 손배선 = 덮어쓰기
    try:
        read = read_facility(facility_uuid)
        if read is None:
            return cfg
        devs = L.effective_devices(read, _overrides_of(cfg))
        if not devs:
            return cfg
        state = TDS.resolve({d.actuator_id: d.kind for d in devs})
    except Exception:
        logger.exception('트윈 효과: 시설 %s 장치 연결 실패', facility_uuid)
        return cfg
    controls = {uid: s['ref'] for uid, s in state.items() if s.get('ref')}
    opts = dict(cfg.get('options') or {})
    opts.setdefault('effects', L.effects_options(devs, {uid: s['basis'] for uid, s in state.items()}))
    cfg['controls'] = controls
    cfg['options'] = opts
    return cfg


# ── 대지(노지) ───────────────────────────────────────────────────────────────────

def _field_outputs(site_id: str) -> Dict[str, Dict[str, str]]:
    """대지 안에 있고 시설 설비에 매이지 않은 출력 — {id: {name, output_type}}."""
    from aot.space.device_membership import screen_members
    from aot.databases.models import GeoShape, Output
    if not site_id or str(site_id).startswith('map:'):
        return {}
    shape = GeoShape.query.filter_by(unique_id=site_id).first()
    if shape is None:
        return {}
    ids = screen_members(shape)                             # 화면이 '이 대지의 장치'로 보이는 규칙 한 곳(시설 설비는 뺀다)
    if not ids:
        return {}
    rows = Output.query.filter(Output.unique_id.in_(list(ids))).all()
    return {o.unique_id: {'name': o.name or o.unique_id[:8], 'output_type': o.output_type or ''} for o in rows}


def _water_roles(plot_ids) -> Dict[str, Dict]:
    """구획들에 물을 대거나 물을 공급하는 출력 — 위치로 푼다. {출력: {kind, plots, flow_lpm, area_m2}}.

    노즐의 임자는 일지와 같은 판정(`irrigation_flow_for_plot`, 담당 폴리곤 ∩ 구획)이고, 공급·점적은 물 회로가 안다."""
    from aot.space import plot_context
    from aot.aot_flask.geo.plot_journal import irrigation_flow_for_plot
    from aot.databases.models import GeoPlot
    from aot.utils.water_net_link import output_roles

    out: Dict[str, Dict] = {}
    ids = [str(p) for p in plot_ids]
    plots = GeoPlot.query.filter(GeoPlot.unique_id.in_(ids)).all() if ids else []
    for plot in plots:
        area = plot_context.area_m2(plot) or 0.0
        for oid, flow in (irrigation_flow_for_plot(plot) or {}).items():
            if not flow.get('lph'):
                continue
            row = out.setdefault(oid, {'kind': C.IRRIGATION_DEFAULT, 'plots': [], 'flow_lpm': 0.0, 'area_m2': 0.0})
            row['plots'].append(plot.unique_id)
            row['flow_lpm'] += float(flow['lph']) * float(flow.get('share', 1.0) or 1.0) / 60.0
            row['area_m2'] += float(area)
    for map_uuid in {p.geo_id for p in plots if p.geo_id}:
        roles = output_roles(map_uuid)
        for oid in roles['supply']:
            out[oid] = {'kind': 'pump', 'plots': []}
        for oid in roles['drip']:
            if oid in out and out[oid]['plots']:
                out[oid]['kind'] = C.IRRIGATION_DRIP
    return out


def _roles_of(plot_ids) -> Dict[str, Dict]:
    try:
        return _water_roles(plot_ids)
    except Exception:
        logger.exception('트윈 효과: 노지 출력 역할 읽기 실패')
        return {}


def field_effects_options(site_id: str, cfg: Optional[Mapping], plot_ids=()) -> Optional[Dict]:
    """노지 구획 트윈 부품의 `options.effects` — 이 대지의 노지 출력 명단 `{devices: [{id, kind, plots?}]}`. `kind` = 사용자가 고른 역할,
    없으면 위치로 푼 역할, 그래도 모르면 None. `plots` 는 물을 받는 구획(다른 구획 밸브를 이 구획의 미반영으로 세지 않는다). 시설 설비에
    매인 출력은 제외(시설 쪽 명단이 센다), 뺀 장치는 제외. 머리말 `effects_*` 와 시나리오 `effects[]` 의 재료다. 출력이 없으면 None(상속 없음)."""
    ov = _overrides_of(cfg)
    roles = _roles_of(plot_ids)
    devs = []
    for k in sorted(_field_outputs(site_id)):
        if (ov.get(k) or {}).get('exclude'):
            continue
        role = roles.get(k) or {}
        dev = {'id': k, 'kind': (ov.get(k) or {}).get('kind') or role.get('kind')}
        if role.get('plots'):
            dev['plots'] = list(role['plots'])
        devs.append(dev)
    return {'devices': devs} if devs else None


def field_scenario_depths(plot_id: str, overrides: Mapping) -> Mapping:
    """시나리오의 밸브 가정 → 구획 깊이 `irrigation_mm` — 공급 한계는 물 회로가 넣고 트윈은 깊이만 받는다(계획서 §8). 앱 컨텍스트 안에서
    부른다. 밸브 가정이 없으면 그대로 돌려준다. 이 구획에 물을 대지 않는 밸브·면적 모름은 `ScenarioError` — 시나리오는 실패로 남는다."""
    from aot.databases.models import GeoPlot
    from aot.functions.utils.twin_effects import scenario as SC
    from aot.utils.timekit import tz_of
    from aot.utils.water_net_link import planned_water

    runs = SC.valve_runs(SC.parse(overrides, C.FIELD))
    if not runs:
        return overrides
    plot = GeoPlot.query.filter_by(unique_id=plot_id).first()
    if plot is None:
        raise SC.ScenarioError('구획이 없다: %s' % plot_id)
    water = planned_water(plot, runs, tz_of(plot_id))
    foreign = sorted(k for k in runs if not (water.flows.get(k) or {}).get('lph'))
    if foreign:
        raise SC.ScenarioError('이 구획에 물을 대는 밸브가 아니다: %s' % ', '.join(foreign))
    if not water.area_m2:
        raise SC.ScenarioError('구획 면적을 몰라 깊이로 바꿀 수 없다')
    rows = (water.result or {}).get('runs') or []
    depths = [(r['t0'], r['t1'], r['litres'] / water.area_m2) for r in rows]
    notes = []
    if rows:
        sums = water.result['totals']
        notes.append('밸브 가정 → 전달 %.2f mm (설계 %.2f mm, 설계 추정)' % (
            sums['litres'] / water.area_m2, sums['design_litres'] / water.area_m2))
    caveats = list((water.result or {}).get('caveats') or ())
    if caveats:
        notes.append('공급 주의: ' + ', '.join(caveats))
    return SC.depth_overrides(overrides, depths, notes, caveats)


def site_effects(site, cfg: Optional[Mapping] = None) -> Dict[str, object]:
    """대지 트윈 탭의 '이 대지의 장치 → 효과 채널' — 시설별 묶음과 노지(시설 밖) 묶음.

    시설 안 장치는 종류가 위치로 정해져 있다. 노지 출력은 범용이라 종류를 모른다 — 역할을 고른 것만 채널을 얻는다."""
    groups: List[Dict[str, object]] = []
    in_facility = set()
    for f in (getattr(site, 'facilities', None) or []):
        view = facility_effects(f.facility_uuid, _facility_cfg(f.facility_uuid))
        in_facility.update(r['id'] for r in view.get('rows') or [])
        if not view.get('rows') and not view.get('error'):
            continue                                       # 연결할 장치가 없는 시설(창고·사무실 등)은 줄도 묶음도 만들지 않는다
        groups.append({'kind': 'facility', 'id': f.facility_uuid, 'name': f.name or f.facility_uuid[:8],
                       'rows': view.get('rows') or [], 'summary': view.get('summary'), 'mode': view.get('mode'),
                       'error': view.get('error'), 'kinds': view.get('kinds'), 'supply': view.get('supply')})
    outs = {k: v for k, v in _field_outputs(getattr(site, 'site_id', '')).items() if k not in in_facility}
    if outs:
        ov = _overrides_of(cfg)
        water = _roles_of([p.unique_id for p in (getattr(site, 'plots', None) or [])])
        read = R.ReadResult(names={k: v['name'] for k, v in outs.items()})
        kinds = {}
        for k, v in outs.items():
            chosen, role = (ov.get(k) or {}).get('kind'), water.get(k) or {}
            kinds[k] = chosen or role.get('kind')
            if role and not chosen:                        # 위치로 풀렸다 — 역할을 묻지 않는다
                read.devices.append(Device(k, role['kind'], {x: role[x] for x in ('flow_lpm', 'area_m2') if role.get(x)}))
                read.sources[k] = {'flow_lpm': C.SRC_GEOMETRY, 'area_m2': C.SRC_GEOMETRY}
            else:
                read.unknown.append({'actuator_id': k, 'name': v['name'], 'fitting_kind': v['output_type'] or None})
        state = TDS.resolve({k: r for k, r in kinds.items() if r})
        rows = L.build_rows(read, state, ov, C.FIELD)
        for r in rows:
            role = water.get(r['id']) or {}
            r['plots'] = list(role.get('plots') or [])
            r['applied'] = bool(r['plots']) or r['status'] == C.SUPPLY     # 물 근거가 있으면 구획의 `water_day` 로 모델에 들어간다
        groups.append({'kind': 'field', 'id': getattr(site, 'site_id', ''), 'name': '', 'rows': rows,
                       'summary': L.summarize(rows), 'mode': 'auto', 'error': None,
                       'kinds': L.selectable_kinds(C.FIELD)})
    total: Dict[str, int] = {}
    for g in groups:
        for k, v in (g.get('summary') or {}).items():
            total[k] = total.get(k, 0) + v
    return {'groups': groups, 'summary': total or L.summarize([])}


def _facility_cfg(facility_uuid: str) -> Dict:
    from aot.utils import twin_config as TC
    return TC.read('facility', facility_uuid)[1]
