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
노지(시설 밖) 출력은 종류를 알 길이 없어(범용 출력) 역할을 묻는다. 노지 관수의 모델 연결(`irr_mm`)은 다음 단계라
줄에 `applied: false` 로 알린다.

@phase active
@stability experimental
"""
from __future__ import annotations

import logging
from typing import Dict, List, Mapping, Optional

from aot.functions.utils.twin_effects import catalog as C
from aot.functions.utils.twin_effects import links as L
from aot.functions.utils.twin_effects import reader as R
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
        from aot.aot_flask.geo.device_binding import shapes_for_devices
        from aot.aot_flask.geo.facility_geo_helpers import shape_azimuth_area
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
    from aot.aot_flask.geo.facility_integration import get_facility_integration
    integ, err = get_facility_integration(facility_uuid)
    if err or not integ:
        logger.warning('트윈 효과: 시설 %s 통합 읽기 실패: %s', facility_uuid, err)
        return None
    uids = [a['output_uuid'] for a in (integ.get('actuators_resolved') or []) if a.get('output_uuid')]
    return R.devices_from_integration(integ, _shape_areas(uids))


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
            'kinds': L.selectable_kinds(C.FACILITY)}


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
    from aot.aot_flask.geo.device_membership import screen_members
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


def field_effects_options(site_id: str, cfg: Optional[Mapping]) -> Optional[Dict]:
    """노지 구획 트윈 부품의 `options.effects` — 이 대지의 노지 출력 명단 `{devices: [{id, kind}]}`(`kind` = 사용자가 고른 역할,
    모르면 None). 시설 설비에 매인 출력은 제외(시설 쪽 명단이 센다), 뺀 장치는 제외. 머리말 `effects_*` 와 시나리오 `effects[]` 의
    재료이고, 노지 관수의 모델 연결(E3) 전이라 기본 예측에는 반영되지 않는다. 출력이 없으면 None(상속 없음)."""
    ov = _overrides_of(cfg)
    devs = [{'id': k, 'kind': (ov.get(k) or {}).get('kind') or None}
            for k in sorted(_field_outputs(site_id)) if not (ov.get(k) or {}).get('exclude')]
    return {'devices': devs} if devs else None


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
                       'error': view.get('error'), 'kinds': view.get('kinds')})
    outs = {k: v for k, v in _field_outputs(getattr(site, 'site_id', '')).items() if k not in in_facility}
    if outs:
        ov = _overrides_of(cfg)
        read = R.ReadResult(names={k: v['name'] for k, v in outs.items()},
                            unknown=[{'actuator_id': k, 'name': v['name'], 'fitting_kind': v['output_type'] or None}
                                     for k, v in outs.items()])
        roles = {k: (ov.get(k) or {}).get('kind') for k in outs}
        state = TDS.resolve({k: r for k, r in roles.items() if r})
        rows = L.build_rows(read, state, ov, C.FIELD)
        for r in rows:
            r['applied'] = False                           # 노지 관수의 모델 연결(irr_mm)은 다음 단계
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
