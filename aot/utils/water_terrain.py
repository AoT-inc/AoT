# coding=utf-8
"""물 회로 ↔ 지형(DEM) 연결의 파생 저장과 백그라운드 선계산 (계획서 15·16절 T3).

요청 스레드는 **절대 타일을 받지 않는다**(2026-11-02 타일 폭주가 서버 스레드를 점유한 사례). 요청 경로는
디스크 캐시(`terrain_ref`)만 읽고, 없으면 수평 길이·평지로 계산하면서 선계산을 예약한다. 선계산은
프로세스당 하나의 백그라운드 스레드가 한다(`prefetch` 로 타일을 데우고 `fetch=False` 로 구간표를 푼다).

계보 캐시 — 재생성 가능한 파생값이라 마이그레이션이 없다. 원천(배관 feature)에는 아무것도 쓰지 않는다.

    위치   <AOT_LOCAL_DIR>/water_terrain_cache/<지도 uuid>/<키>.json   (`dem_cache_root()` 와 같은 관례)
    키     hash(지도 uuid, 설비 기하 해시, 표본기 version, RULES_VERSION)
    정리   지도당 최근 3개, 전체 64 MB (오래된 것부터)

상태 ``state``: ``none``(DEM 없음) · ``warming``(키에 맞는 저장값이 없다 — 수평 폴백, 선계산 예약) ·
``partial``(저장값이 있으나 읽지 못한 구간·마디가 있다) · ``ready``(전부 읽었다).
낡은 저장값은 보이지 않는다: 키가 다르면 파일을 못 찾으므로 곧 ``warming`` 이다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, NamedTuple, Optional

logger = logging.getLogger(__name__)

# 표본 간격 규칙(min(셀/2, 5 m), 하한 2 m, 구간당 200점)이나 저장 모양이 바뀌면 올린다.
RULES_VERSION = 'step-min(cell/2,5)-lo2-cap200/v1'
KEEP_PER_MAP = 3
CACHE_MAX_BYTES = 64 * 1024 * 1024
JOB_BUDGET_S = 600.0            # 선계산 한 번의 상한. 넘기면 저장하지 않고 다음 예약에 이어서(타일은 디스크에 남는다)
RETRY_AFTER_S = 60.0            # 요청이 같은 지도를 다시 예약할 수 있는 최소 간격
CHUNK_M = 300.0                 # 타일 데우기에서 배관을 자르는 길이(구간당 200점 상한 안)

STATE_NONE, STATE_WARMING, STATE_PARTIAL, STATE_READY = 'none', 'warming', 'partial', 'ready'


class Ref(NamedTuple):
    """요청 경로가 받는 지형 참조. ``sampler`` 는 저장값이 있을 때만 있다(없으면 수평·평지로 계산한다)."""
    sampler: object
    state: str
    version: Optional[str]
    cell_m: Optional[float]
    pipes: Optional[dict]
    computed_at: Optional[float] = None      # 저장값을 푼 시각(epoch 초). 이 지형으로 계산한 때이지 DEM 을 만든 날이 아니다


# ── 저장 위치 ───────────────────────────────────────────────────────────────

def cache_root() -> str:
    from aot.utils.dem_sampler import dem_cache_root
    return os.path.join(os.path.dirname(dem_cache_root()), 'water_terrain_cache')


def geometry_hash(net) -> str:
    """계산에 쓰이는 기하만: 배관 좌표·종류·관 종류, 노즐 위치·종류. 관경·유량은 길이에 영향이 없어 뺀다."""
    def pt(p):
        return [round(float(p[0]), 2), round(float(p[2]), 2)]

    pipes = sorted([str(p.id), p.sub_type or '', bool(p.vertical), [pt(q) for q in p.line]]
                   for p in net.pipes)
    ems = sorted([str(e.id), e.kind or '', pt(e.point) if e.point is not None else None]
                 for e in net.emitters)
    frame = getattr(net, 'frame', None)
    origin = [round(frame.lng0, 7), round(frame.lat0, 7)] if frame is not None else None
    blob = json.dumps([origin, pipes, ems], separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:20]


def cache_key(map_uuid, net, sampler) -> str:
    base = '|'.join([str(map_uuid), geometry_hash(net), str(sampler.version), RULES_VERSION])
    return hashlib.sha256(base.encode('utf-8')).hexdigest()[:24]


def _path(map_uuid, key, root=None) -> str:
    return os.path.join(root or cache_root(), str(map_uuid), key + '.json')


def read_entry(map_uuid, key, root=None) -> Optional[dict]:
    path = _path(map_uuid, key, root)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            entry = json.load(fh)
    except OSError:
        return None
    except ValueError:                       # 손상 — 지우고 낡은 것으로 본다
        _remove(path)
        return None
    if (not isinstance(entry, dict) or entry.get('key') != key or entry.get('rules') != RULES_VERSION
            or entry.get('state') not in (STATE_READY, STATE_PARTIAL) or not isinstance(entry.get('pipes'), dict)):
        _remove(path)
        return None
    try:
        os.utime(path, None)                 # 최근 사용 순으로 정리하려고
    except OSError:
        pass
    return entry


def write_entry(map_uuid, key, entry, root=None) -> bool:
    """tmp 에 쓰고 rename — 쓰는 도중 다른 프로세스가 읽어도 부분 파일을 보지 못한다."""
    path = _path(map_uuid, key, root)
    tmp = '%s.%d.%d.tmp' % (path, os.getpid(), threading.get_ident())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(entry, fh, separators=(',', ':'))
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning('[water-terrain] 캐시를 쓰지 못했습니다: %s', type(exc).__name__)
        _remove(tmp)
        return False
    prune(map_uuid, root)
    return True


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def prune(map_uuid=None, root=None, keep=KEEP_PER_MAP, max_bytes=CACHE_MAX_BYTES):
    """지도당 최근 ``keep`` 개만, 전체 ``max_bytes`` 이하로. 오래된(mtime) 것부터 지운다."""
    root = root or cache_root()
    files = []
    try:
        maps = [str(map_uuid)] if map_uuid else os.listdir(root)
    except OSError:
        return
    for m in maps:
        d = os.path.join(root, m)
        try:
            names = os.listdir(d)
        except OSError:
            continue
        rows = []
        for n in names:
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if n.endswith('.tmp') and time.time() - st.st_mtime > 3600:
                _remove(p)
                continue
            if n.endswith('.json'):
                rows.append((st.st_mtime, st.st_size, p))
        rows.sort(reverse=True)
        for _mt, _sz, p in rows[keep:]:
            _remove(p)
        files.extend(rows[:keep])
    # 전체 상한은 모든 지도를 봐야 한다
    if map_uuid:
        files = []
        try:
            for m in os.listdir(root):
                d = os.path.join(root, m)
                for n in os.listdir(d):
                    if n.endswith('.json'):
                        p = os.path.join(d, n)
                        try:
                            st = os.stat(p)
                            files.append((st.st_mtime, st.st_size, p))
                        except OSError:
                            pass
        except OSError:
            return
    total = sum(sz for _m, sz, _p in files)
    for _mt, sz, p in sorted(files):
        if total <= max_bytes:
            break
        _remove(p)
        total -= sz


# ── 계산(순수: 회로와 표본기만 있으면 된다) ──────────────────────────────────

def _chunks(net, pipe):
    from aot.functions.utils.water_net.graph import line_length
    from aot.functions.utils.water_net.terrain import _sub_line
    total = line_length(pipe.line)
    n = max(1, int(math.ceil(total / CHUNK_M)))
    for i in range(n):
        yield _sub_line(pipe.line, total * i / n, total * (i + 1) / n)


def warm_tiles(net, sampler, deadline) -> bool:
    """회로의 배관 경로와 마디가 지나는 타일을 받는다(백그라운드 전용). 예산을 넘기면 False."""
    frame = net.frame
    for pipe in net.pipes:
        for sub in _chunks(net, pipe):
            if time.time() >= deadline:
                return False
            ll = [frame.to_lnglat(p) for p in sub]
            sampler.prefetch(ll, sampler.suggest_step_m(ll[0][1]))
    points = list(net.node_pos.values()) + [e.point for e in net.emitters if e.point is not None]
    for p in points:
        if time.time() >= deadline:
            return False
        lng, lat = frame.to_lnglat(p)
        sampler.elevation(lng, lat, fetch=True)
    return True


def compute_entry(net, sampler, map_uuid, key) -> dict:
    """캐시에서만 읽어(fetch=False) 배관별 수평·경사 길이를 푼다. 읽지 못한 배관·마디가 있으면 partial."""
    from aot.functions.utils.water_net.graph import line_length
    from aot.functions.utils.water_net.terrain import Terrain

    tr = Terrain(net, net.frame, sampler, fetch=False)
    pipes: Dict[str, dict] = {}
    unknown = 0
    for p in net.pipes:
        length = line_length(p.line)
        got = tr.slant(p.id, 0.0, length) if length > 1e-9 else None
        if got is None:
            unknown += 1
        pipes[str(p.id)] = {'horizontal_m': round(length, 3),
                            'slant_m': None if got is None else round(got[1], 3)}
    nodes = list(net.node_pos) + [('nozzle', e.id) for e in net.emitters if e.point is not None]
    unknown_nodes = sum(1 for n in nodes if tr.node_elevation(n) is None)
    meta = tr.meta
    return {'key': key, 'rules': RULES_VERSION, 'map': str(map_uuid), 'version': meta['version'],
            'cell_m': meta['cell_m'], 'geometry': geometry_hash(net),
            'state': STATE_READY if not unknown and not unknown_nodes else STATE_PARTIAL,
            'unknown_pipes': unknown, 'unknown_nodes': unknown_nodes,
            'computed_at': time.time(), 'pipes': pipes}


def build(map_uuid, net, sampler, root=None, budget_s=JOB_BUDGET_S) -> Optional[dict]:
    """선계산 한 번: 이미 있으면 그대로, 아니면 타일을 데우고 풀어 저장한다. 예산을 넘기면 None(저장 안 함)."""
    key = cache_key(map_uuid, net, sampler)
    entry = read_entry(map_uuid, key, root)
    if entry is not None:
        return entry
    if not warm_tiles(net, sampler, time.time() + budget_s):
        return None
    entry = compute_entry(net, sampler, map_uuid, key)
    write_entry(map_uuid, key, entry, root)
    return entry


# ── 요청 경로 ───────────────────────────────────────────────────────────────

def _sampler():
    try:
        from aot.utils import dem_sampler
        return dem_sampler.get_sampler()
    except Exception:                                       # noqa: BLE001 — DEM 이 없는 설치와 같게 본다
        logger.debug('[water-terrain] 표본기를 만들지 못했습니다', exc_info=True)
        return None


def _cell(sampler, net):
    try:
        return round(float(sampler.cell_m(getattr(net.frame, 'lat0', 0.0))), 2)
    except Exception:                                       # noqa: BLE001
        return None


def terrain_ref(map_uuid, net) -> Optional[Ref]:
    """공용 진입점. DEM 이 없으면 None(예전과 같은 응답). 타일은 받지 않는다."""
    memo = getattr(net, '_terrain_ref_memo', None)
    if memo is not None and memo[0] == map_uuid:
        return memo[1]
    ref = None
    if getattr(net, 'frame', None) is not None:
        sampler = _sampler()
        if sampler is not None:
            entry = None
            try:
                entry = read_entry(map_uuid, cache_key(map_uuid, net, sampler))
            except Exception:                               # noqa: BLE001 — 저장소 문제가 요청을 깨지 않는다
                logger.debug('[water-terrain] 캐시를 읽지 못했습니다', exc_info=True)
            if entry is None:
                schedule(map_uuid)
                ref = Ref(None, STATE_WARMING, sampler.version, _cell(sampler, net), None)
            else:
                ref = Ref(sampler, entry['state'], sampler.version, _cell(sampler, net), entry['pipes'],
                          entry.get('computed_at'))
    try:
        net._terrain_ref_memo = (map_uuid, ref)
    except AttributeError:
        pass
    return ref


def terrain_for(map_uuid, net=None) -> Optional[Ref]:
    """``terrain_ref`` 의 지도 단위 입구 — 회로를 아직 안 만들었으면 만든다."""
    if net is None:
        from aot.utils import water_net_link
        net = water_net_link.network_for_map(map_uuid)
    return terrain_ref(map_uuid, net) if net is not None else None


def lengths_from_ref(net, ref, wanted=None) -> dict:
    """참조 하나에서 배관별 수평·경사 길이와 합계를 읽는다(계산 없음). ``wanted`` 는 배관 id 문자열 집합(None 이면 전부).

    ``slant_m`` 이 None 이면 못 읽어 수평 길이로 남은 배관이다(합계 ``slant_m`` 에는 수평 길이로 더하고 ``unknown_pipes`` 로 센다).
    """
    from aot.functions.utils.water_net.graph import line_length

    stored = (ref.pipes if ref is not None else None) or {}
    pipes = {}
    for p in net.pipes:
        pid = str(p.id)
        if wanted is not None and pid not in wanted:
            continue
        row = stored.get(pid)
        if row is not None:
            pipes[pid] = {'horizontal_m': row['horizontal_m'], 'slant_m': row['slant_m']}
        else:
            pipes[pid] = {'horizontal_m': round(line_length(p.line), 3), 'slant_m': None}
    h = sum(r['horizontal_m'] for r in pipes.values())
    s = sum(r['horizontal_m'] if r['slant_m'] is None else r['slant_m'] for r in pipes.values())
    return {'state': ref.state if ref is not None else STATE_NONE,
            'version': ref.version if ref is not None else None,
            'pipes': pipes,
            'totals': {'horizontal_m': round(h, 3), 'slant_m': round(s, 3),
                       'unknown_pipes': sum(1 for r in pipes.values() if r['slant_m'] is None)}}


def pipe_lengths_for(map_uuid, shape_uuid=None) -> Optional[dict]:
    """T4·T5 가 읽는다. → {state, version, pipes:{id:{horizontal_m, slant_m}}, totals}.

    ``shape_uuid`` 가 있으면 그 대지·구역의 노즐이 물린 회로의 배관만.
    """
    from aot.utils import water_net_link

    net = water_net_link.network_for_map(map_uuid)
    if net is None:
        return None
    wanted = None
    if shape_uuid:
        inside = water_net_link.emitters_in_shape(net, shape_uuid)
        if inside is None:
            return None
        wanted = circuit_pipe_ids(net, inside)
    return lengths_from_ref(net, terrain_ref(map_uuid, net), wanted)


def circuit_pipe_ids(net, emitter_ids) -> set:
    """노즐들이 물린 회로의 배관 id(문자열) — 구역 합계의 범위."""
    comps = {net.component_id(e) for e in emitter_ids} - {None}
    return {str(pid) for c in comps for pid in net.component_pipes(c)}


def dem_name() -> Optional[str]:
    """활성 DEM 입력의 이름(사용자가 붙인 이름). 키는 읽지 않는다. 없으면 None."""
    try:
        from aot.aot_flask.utils import utils_geo
        layer = (utils_geo.get_geo_config() or {}).get('terrain')
        name = layer.get('name') if isinstance(layer, dict) else None
        return str(name) if name else None
    except Exception:                                       # noqa: BLE001
        logger.debug('[water-terrain] DEM 이름을 읽지 못했습니다', exc_info=True)
        return None


def _iso(ts, where):
    """epoch 초 → 그 장소 시계의 ISO. 시계를 못 풀면 UTC ISO 로 둔다(화면은 날짜만 쓴다)."""
    if ts is None:
        return None
    from datetime import datetime, timezone
    from aot.utils.timekit import iso_at, iso_utc
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    got = iso_at(dt, where)
    return got if isinstance(got, str) else iso_utc(dt)


def area_block(net, map_uuid, emitter_ids, where=None) -> Optional[dict]:
    """`/api/geo/water_net` 의 ``areas[].terrain`` — 구역 하나의 지형 상태·합계·배관별 길이. DEM 이 없으면 None(키를 싣지 않는다).

    ``where`` 는 계산 시각을 보일 장소 id(구역 도형 uuid) — 못 풀면 UTC 로 둔다.
    """
    ref = terrain_ref(map_uuid, net)
    if ref is None:
        return None
    got = lengths_from_ref(net, ref, circuit_pipe_ids(net, emitter_ids))
    got['kinds'] = {str(p.id): ('main' if p.sub_type == 'main' else 'branch')      # 구간표가 배관에 이름을 붙일 때 쓴다
                    for p in net.pipes if str(p.id) in got['pipes']}
    memo = getattr(net, '_dem_name_memo', None)               # 응답 하나 안에서 구역마다 설정을 다시 읽지 않는다
    if memo is None:
        memo = (dem_name(),)
        try:
            net._dem_name_memo = memo
        except AttributeError:
            pass
    got['dem_name'] = memo[0]
    got['computed_at'] = _iso(ref.computed_at, where)         # 이 지형으로 계산한 시각(그 구역의 시계)
    got['cell_m'] = ref.cell_m
    return got


# ── 백그라운드 ──────────────────────────────────────────────────────────────

_lock = threading.Lock()
_inflight = set()
_last_attempt: Dict[str, float] = {}
_executor = None


def _submit(fn):
    """동시 1개 — 줄 선 일은 차례로 한다. 시험은 이 함수를 바꿔 끼운다."""
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='water-terrain')
    _executor.submit(fn)


def wait_idle(timeout=30.0) -> bool:
    """줄 선 백그라운드 일이 모두 끝나길 기다린다(시험용). 실행기가 없으면 바로 True — 기본 동작은 그대로."""
    ex = _executor
    if ex is None:
        return True
    try:
        ex.submit(lambda: None).result(timeout=timeout)       # 동시 1개 · 선입선출이라 이 일이 끝나면 앞의 일도 끝났다
        return True
    except Exception:                                       # noqa: BLE001
        return False


def schedule(map_uuid, force=False) -> bool:
    """지도의 선계산을 예약한다. 프로세스 안에서 지도당 하나만 돌고(단일 비행), 요청이 불러 올 때는 재시도 간격을 둔다."""
    key = str(map_uuid)
    try:
        from flask import current_app, has_app_context
        if not has_app_context():
            return False
        app = current_app._get_current_object()
    except Exception:                                       # noqa: BLE001
        return False
    with _lock:
        if key in _inflight:
            return False
        if not force and time.time() - _last_attempt.get(key, 0.0) < RETRY_AFTER_S:
            return False
        _inflight.add(key)

    def _run():
        try:
            with app.app_context():
                _job(key)
        except Exception:                                   # noqa: BLE001 — 백그라운드 예외는 요청에 닿지 않는다
            logger.warning('[water-terrain] 선계산 실패 (지도 %s)', key, exc_info=True)
        finally:
            with _lock:
                _inflight.discard(key)
                _last_attempt[key] = time.time()

    try:
        _submit(_run)
    except Exception:                                       # noqa: BLE001
        with _lock:
            _inflight.discard(key)
        return False
    return True


def _job(map_uuid):
    from aot.utils import water_net_link
    sampler = _sampler()
    if sampler is None:
        return
    net = water_net_link.network_for_map(map_uuid)
    if net is None or getattr(net, 'frame', None) is None or not net.pipes:
        return
    build(map_uuid, net, sampler)


def schedule_all_maps():
    """활성 DEM 이 바뀐 직후 — 설비가 있는 지도 전부(키가 같은 지도는 job 이 바로 끝난다)."""
    if _sampler() is None:
        return 0
    try:
        from aot.databases.models import GeoShape
        rows = GeoShape.query.with_entities(GeoShape.geo_id).filter(
            GeoShape.type.in_(['equipment_collection', 'equipment'])).distinct().all()
    except Exception:                                       # noqa: BLE001
        return 0
    return sum(1 for (m,) in rows if m and schedule(m, force=True))


def on_equipment_saved(map_uuid):
    """설비 묶음 저장 직후. DEM 이 없으면 아무것도 하지 않는다."""
    if map_uuid and _sampler() is not None:
        schedule(map_uuid, force=True)


_seen_version = [None]


def on_geo_config_changed():
    """지도 설정(활성 DEM 포함)이 바뀐 직후. 요청 스레드에서는 예약만 하고, 판 식별자가 바뀐 때만 전 지도를 다시 예약한다."""
    try:
        from flask import current_app, has_app_context
        if not has_app_context():
            return False
        app = current_app._get_current_object()
    except Exception:                                       # noqa: BLE001
        return False

    def _run():
        try:
            with app.app_context():
                sampler = _sampler()
                version = sampler.version if sampler is not None else None
                if version is None or version == _seen_version[0]:
                    _seen_version[0] = version
                    return
                _seen_version[0] = version
                schedule_all_maps()
        except Exception:                                   # noqa: BLE001
            logger.warning('[water-terrain] DEM 변경 처리 실패', exc_info=True)

    try:
        _submit(_run)
    except Exception:                                       # noqa: BLE001
        return False
    return True
