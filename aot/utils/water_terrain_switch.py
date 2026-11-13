# coding=utf-8
"""물 회로 지형(DEM) 바꾸기 — 미리보기·활성화·되돌리기 (계획서 15·16절 T6).

DEM 을 바꾸는 일(활성화)은 사용자가 명시적으로 한다. 활성화하기 전에 **다른 DEM 으로 계산하면 어떻게 달라지는지**를
보여 주고(미리보기), 바꾼 뒤에는 한 줄로 알리고 되돌릴 수 있게 한다. 크기 문턱 판정이나 알림은 없다.

미리보기는 요청 스레드에서 타일을 받지 않는다(2026-11-02 사례). 후보 DEM 의 타일은 지형 선계산과 같은 단일 백그라운드
일꾼(`water_terrain._submit`)이 받고, 끝나면 계보 캐시에 저장한다 — 그래서 활성화하면 이 지도는 바로 `ready` 다.

* 아무것도 저장하지 않는다: 미리보기는 메모리에만 있다(재시작하면 사라진다). 활성 DEM 도 바꾸지 않는다.
* 활성화: 후보만 켜고 **다른 DEM 입력은 끈다**(여럿이 켜져 있으면 첫 번째가 쓰이는 규칙의 모호함을 없앤다).
  예전 켜짐 상태를 기록해 두었다가 되돌리기가 그대로 복원한다.
* 되돌리기 기록은 재생성 가능한 캐시 곁의 작은 파일 하나다(설정 칸을 늘리지 않는다). 그 뒤 다른 DEM 으로 다시
  바뀌었으면(기록의 ``to`` 가 더는 활성이 아니면) 기록은 무시된다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PREVIEW_KEEP = 8                 # 메모리에 두는 미리보기 수
PREVIEW_TTL_S = 1800.0           # 이보다 오래된 결과는 새로 계산한다(관경 등 입력이 바뀌었을 수 있다)
SEG_LIMIT = 12                   # 바뀌는 구간은 변화가 큰 순서로 이만큼만
SEG_MIN_DELTA_M = 0.05           # 경사 길이 차가 이보다 작으면 '바뀌지 않음'
SWITCH_FILE = 'water_terrain_switch.json'

ST_WARMING, ST_READY, ST_FAILED, ST_EMPTY = 'warming', 'ready', 'failed', 'empty'

_lock = threading.Lock()
_previews: Dict[tuple, dict] = {}


# ── DEM 입력 목록 ───────────────────────────────────────────────────────────

def _dem_rows() -> list:
    """DEM 종류(`raster-dem`)인 지형 입력 전부. 켜짐 여부와 무관."""
    from aot.databases.models import GeoLayer
    from aot.utils.inputs import parse_input_information
    defs = parse_input_information()
    return [r for r in GeoLayer.query.order_by(GeoLayer.id).all()
            if (defs.get(r.type) or {}).get('layer_type') == 'raster-dem']


def _brief(row) -> Optional[dict]:
    return {'id': row.unique_id, 'name': row.name or ''} if row is not None else None


def current_id() -> Optional[str]:
    """지금 지형으로 쓰이는 DEM 입력 id (`get_geo_config()['terrain']`)."""
    from aot.aot_flask.utils import utils_geo
    layer = (utils_geo.get_geo_config() or {}).get('terrain')
    return layer.get('id') if isinstance(layer, dict) else None


def candidate_sampler(layer_id):
    """켜짐과 무관하게 DEM 입력 하나의 표본기. 못 만들면 None."""
    from aot.aot_flask.utils import utils_geo
    from aot.utils import dem_sampler
    keys = (utils_geo.get_geo_config(with_secrets=True) or {}).get('keys') or {}
    layers = utils_geo.get_active_geo_layers(dict(keys), layer_ids=[layer_id])
    _rest, dem = utils_geo.split_terrain_layer(layers)
    return dem_sampler.sampler_from_layer(dem, keys) if dem else None


# ── 바꾼 기록(되돌리기용) ───────────────────────────────────────────────────

def _switch_path() -> str:
    from aot.utils import water_terrain
    return os.path.join(os.path.dirname(water_terrain.cache_root()), SWITCH_FILE)


def read_switch() -> Optional[dict]:
    try:
        with open(_switch_path(), 'r', encoding='utf-8') as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    if (not isinstance(rec, dict) or not isinstance(rec.get('to'), dict) or not rec['to'].get('id')
            or not isinstance(rec.get('was_active'), list)):
        return None
    return rec


def _write_switch(rec: dict) -> None:
    path = _switch_path()
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(rec, fh, separators=(',', ':'))
        os.replace(tmp, path)
    except OSError:
        logger.warning('[water-terrain-switch] 바꾼 기록을 쓰지 못했습니다', exc_info=True)
        try:
            os.remove(tmp)
        except OSError:
            pass


def _clear_switch() -> None:
    try:
        os.remove(_switch_path())
    except OSError:
        pass


def state() -> dict:
    """드로어가 읽는 지형 바꾸기 상태 — 지금 DEM·바꿀 수 있는 DEM·되돌릴 수 있는 기록. 키는 싣지 않는다."""
    rows = _dem_rows()
    cur = current_id()
    switched = None
    rec = read_switch()
    if rec is not None and rec['to'].get('id') == cur:
        switched = {'from': rec.get('from'), 'to': rec['to'], 'at': rec.get('at')}
    return {'current': _brief(next((r for r in rows if r.unique_id == cur), None)),
            'candidates': [_brief(r) for r in rows if r.unique_id != cur],
            'switched': switched}


# ── 미리보기 ────────────────────────────────────────────────────────────────

def _pct(ratio):
    return None if ratio is None else int(round(float(ratio) * 100))


def _eff(h, sl):
    return h if sl is None else sl


def _segment_changes(net, before_rows, after_rows) -> tuple:
    """회로의 구간표를 (배관, 시작, 끝) 으로 맞춰 이전→이후를 견준다. → (바뀐 구간 상위, 바뀐 구간 수)."""
    kinds = {str(p.id): ('main' if p.sub_type == 'main' else 'branch') for p in net.pipes}

    def table(rows):
        # 대지는 구역을 품어서 같은 배관 구간이 대지·구역 양쪽 행에 나온다. 구역을 키에 넣으면 한 구간이 두 번 세어진다
        # (바뀌는 구간 수가 두 배, 12개 상한이 중복으로 찬다). 물리 구간 하나로 모으고, 겹치면 물이 더 많이 흐르는 쪽
        # (더 넓은 범위에서 노즐이 모두 열린 계산)을 쓴다 — 경사 길이는 같고 손실만 범위에 따라 다르다.
        out: Dict[tuple, dict] = {}
        for area in rows:
            for brief in area.get('pressure') or []:
                for sg in brief.get('segments') or []:
                    key = (brief.get('network'), str(sg['pipe']), round(sg['s_a'], 3), round(sg['s_b'], 3))
                    old = out.get(key)
                    if old is None or (sg.get('flow_lpm') or 0) > (old.get('flow_lpm') or 0):
                        out[key] = sg
        return out

    before, after = table(before_rows), table(after_rows)
    changes = []
    for key, sa in after.items():
        sb = before.get(key)
        h = sa['horizontal_m']
        eff_b = _eff(h, sb['slant_m']) if sb is not None else h        # 이전에 지형이 없었으면 수평 길이
        eff_a = _eff(h, sa['slant_m'])
        delta = eff_a - eff_b
        covered_changed = (sb is not None and (sb['slant_m'] is None) != (sa['slant_m'] is None)) \
            or (sb is None and sa['slant_m'] is not None)
        if abs(delta) < SEG_MIN_DELTA_M and not covered_changed:
            continue
        changes.append({'pipe': str(sa['pipe']), 'kind': kinds.get(str(sa['pipe']), 'branch'),
                        's_a': sa['s_a'], 's_b': sa['s_b'], 'horizontal_m': h,
                        'slant_before': None if sb is None else sb['slant_m'], 'slant_after': sa['slant_m'],
                        'grade_before': None if sb is None else sb.get('grade_pct'), 'grade_after': sa.get('grade_pct'),
                        'loss_before': None if sb is None else sb.get('loss_m'), 'loss_after': sa.get('loss_m'),
                        '_abs': abs(delta)})
    changes.sort(key=lambda c: (-c['_abs'], c['pipe'], c['s_a']))
    for c in changes:
        del c['_abs']
    return changes[:SEG_LIMIT], len(changes)


def compare(map_uuid, net, cand, entry) -> dict:
    """지금 지형 → 후보 지형. 후보의 타일이 이미 디스크에 있어야 한다(요청이 아니라 백그라운드가 받아 둔다)."""
    from aot.utils import water_net_link, water_terrain

    before_ref = water_terrain.terrain_ref(map_uuid, net)
    after_ref = water_terrain.Ref(cand, entry['state'], cand.version, water_terrain._cell(cand, net),
                                  entry['pipes'], entry.get('computed_at'))
    points = water_net_link._emitter_points(net)
    before_rows = water_net_link._area_rows(net, map_uuid, points)
    after_rows = water_net_link._area_rows(net, map_uuid, points, terrain=cand)

    lb = water_terrain.lengths_from_ref(net, before_ref)
    la = water_terrain.lengths_from_ref(net, after_ref)
    by_id = {a['id']: a for a in before_rows}
    areas: List[dict] = []
    for area in after_rows:
        mine = by_id.get(area['id']) or {}
        circuits = []
        for i, pa in enumerate(area.get('pressure') or []):
            pb = (mine.get('pressure') or [])[i] if i < len(mine.get('pressure') or []) else {}
            circuits.append({'level_before': pb.get('level'), 'level_after': pa.get('level'),
                             'bar_before': [pb.get('bar_min'), pb.get('bar_max')],
                             'bar_after': [pa.get('bar_min'), pa.get('bar_max')],
                             'flow_pct_before': _pct(pb.get('flow_ratio_min')),
                             'flow_pct_after': _pct(pa.get('flow_ratio_min'))})
        areas.append({'id': area['id'], 'name': area.get('name') or '', 'circuits': circuits})
    segs, seg_total = _segment_changes(net, before_rows, after_rows)
    have_before = before_ref is not None and before_ref.pipes is not None
    return {
        'totals': {'pipes': len(net.pipes), 'horizontal_m': la['totals']['horizontal_m'],
                   'slant_before': lb['totals']['slant_m'] if have_before else None,
                   'slant_after': la['totals']['slant_m'],
                   'unknown_before': lb['totals']['unknown_pipes'] if have_before else None,
                   'unknown_after': la['totals']['unknown_pipes']},
        'areas': areas, 'segments': segs, 'segments_total': seg_total,
        'cell_m': after_ref.cell_m, 'dem_state': entry['state']}


def _fresh(item) -> bool:
    return item is not None and time.time() - item['started'] < PREVIEW_TTL_S


def _public(item, cand_brief) -> dict:
    out = {'state': item['state'], 'candidate': cand_brief}
    if item.get('reason'):
        out['reason'] = item['reason']
    if item['state'] == ST_READY:
        out['result'] = item['result']
    return out


def start_preview(map_uuid, candidate_id, restart=False) -> dict:
    """미리보기를 시작하거나 지금 상태를 돌려준다. 계산 중이면 새로 시작하지 않는다(지도·후보당 하나)."""
    from flask import current_app

    brief = next((_brief(r) for r in _dem_rows() if r.unique_id == candidate_id), None)
    if brief is None:
        return {'state': ST_FAILED, 'reason': 'not-found', 'candidate': None}
    key = (str(map_uuid), str(candidate_id))
    with _lock:
        item = _previews.get(key)
        if item is not None and (item['state'] == ST_WARMING or (_fresh(item) and not restart)):
            return _public(item, brief)
        item = {'state': ST_WARMING, 'started': time.time(), 'result': None, 'reason': None}
        _previews[key] = item
        for old in sorted(_previews, key=lambda k: _previews[k]['started'])[:-PREVIEW_KEEP]:
            _previews.pop(old, None)
    app = current_app._get_current_object()

    def _run():
        try:
            with app.app_context():
                _job(item, map_uuid, candidate_id)
        except Exception:                                   # noqa: BLE001 — 백그라운드 예외는 요청에 닿지 않는다
            logger.warning('[water-terrain-switch] 미리보기 실패 (지도 %s)', map_uuid, exc_info=True)
            item.update(state=ST_FAILED, reason='error')

    from aot.utils import water_terrain
    try:
        water_terrain._submit(_run)
    except Exception:                                       # noqa: BLE001
        item.update(state=ST_FAILED, reason='error')
    return _public(item, brief)


def _job(item, map_uuid, candidate_id):
    from aot.utils import water_net_link, water_terrain
    cand = candidate_sampler(candidate_id)
    if cand is None:
        item.update(state=ST_FAILED, reason='no-sampler')
        return
    net = water_net_link.network_for_map(map_uuid)
    if net is None or getattr(net, 'frame', None) is None or not net.pipes:
        item.update(state=ST_EMPTY)
        return
    entry = water_terrain.build(map_uuid, net, cand)        # 타일을 데우고 계보 캐시에 저장 — 활성화하면 바로 ready
    if entry is None:
        item.update(state=ST_FAILED, reason='timeout')
        return
    item['result'] = compare(map_uuid, net, cand, entry)
    item['state'] = ST_READY


def preview_status(map_uuid, candidate_id) -> dict:
    return start_preview(map_uuid, candidate_id, restart=False)


# ── 활성화·되돌리기 ─────────────────────────────────────────────────────────

def _apply_active(rows, active_ids) -> None:
    from aot.aot_flask.extensions import db
    from aot.aot_flask.utils import utils_geo
    for r in rows:
        r.is_activated = r.unique_id in active_ids
    db.session.commit()
    utils_geo.invalidate_geo_config_cache()                  # 판이 바뀌면 전 지도 선계산이 예약된다


def activate(candidate_id) -> dict:
    """후보 DEM 만 켜고 다른 DEM 입력은 끈다. → state() 모양에 ``ok`` 를 더한 것. 이미 쓰는 DEM 이면 아무것도 하지 않는다."""
    rows = _dem_rows()
    target = next((r for r in rows if r.unique_id == candidate_id), None)
    if target is None:
        return {'ok': False, 'reason': 'not-found'}
    cur = current_id()
    if target.unique_id == cur:
        return {'ok': False, 'reason': 'already-active'}
    rec = {'from': _brief(next((r for r in rows if r.unique_id == cur), None)), 'to': _brief(target),
           'was_active': [r.unique_id for r in rows if r.is_activated], 'at': time.time()}
    _apply_active(rows, {target.unique_id})
    _write_switch(rec)
    return dict(state(), ok=True)


def revert() -> dict:
    """마지막으로 바꾼 것을 되돌린다 — 그때 켜져 있던 DEM 입력을 그대로 복원."""
    rec = read_switch()
    if rec is None or rec['to'].get('id') != current_id():
        return {'ok': False, 'reason': 'nothing-to-revert'}
    rows = _dem_rows()
    _apply_active(rows, set(rec['was_active']))
    _clear_switch()
    return dict(state(), ok=True)
