#!/usr/bin/env python3
"""장치 위치 드리프트 검사기 (읽기 전용, L0).

장치 위치는 지금 5곳에 흩어져 있다 — 장치 7모델의 lat/lng 컬럼 · 마커 GeoShape
(type aot_device/device) 좌표 · geo_binding · 레거시 GeoShape.device_id 컬럼 ·
map_config_id. 위치 정본을 하나로 모으는 L1~L4 의 안전 조건을 숫자로 낸다.

앱 컨텍스트 없이 **sqlite 파일을 읽기 전용으로 직접** 연다(`--db`). 운영 DB
사본에서 돌리기 위해서다. 라이브 DB 에 직접 돌리지 말 것 — 사본(backup API)만.

대표 자리 규칙: 마커 > 설비 항목(fitting/actuator) > 구역(shape area) >
역할(sensor_role/weather). 설비 항목·역할의 점은 시설 도형 중심으로 근사한다
(fittings 안의 좌표는 시설 로컬 좌표라 위경도가 아니다).

L4 통과 기준(서버별 넷 다 0):
  1 legacy_only_markers    레거시 device_id 만 있고 geo_binding 이력(valid_to 무관)이 전혀
                           없는 장치의 마커. 다른 자리에만 묶인 마커는 보고만
  2 far_from_place         컬럼↔대표 자리(**마커일 때만**) 거리 > --far-m(50) m 인 행
  3 explicit_tz_no_place   tz_source='explicit' 이면서 자리 없는 행
  4 dangling_map_config    map_config_id 가 실존하지 않는 GeoMap 을 가리키는 행
                           (컬럼이 없는 DB 는 "column absent" — 값 0 으로 두고 표시한다.
                           L3 부터 앱은 이 컬럼을 읽지 않고, 다음 단계에서 드롭된다)
보고만: default_coords_rows(컬럼 좌표가 기본 좌표 그대로인 행)

사용:
    python3 -m aot.scripts.check_device_location_drift --db <사본.db>
    ... --json | --verbose | --default-coords LAT,LNG | --far-m 50

종료 코드 0 = L4 기준 넷 모두 0, 1 = 하나라도 아님, 2 = 검사 실패.

@phase active
@stability experimental
"""
import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from urllib.parse import quote

# (device_kind, 테이블) — geo/device_binding.device_kind_models() 와 같은 7종.
DEVICE_TABLES = (
    ('input', 'input'), ('output', 'output'), ('device', 'custom_controller'),
    ('function', 'function'), ('pid', 'pid'), ('trigger', 'trigger'),
    ('conditional', 'conditional'))

MARKER_TYPES = ('aot_device', 'device')
PLACE_RANK = {'marker': 0, 'fitting': 1, 'actuator': 1, 'shape': 2,
              'sensor_role': 3, 'weather': 3}
PLACE_LABEL = {0: 'marker', 1: 'fitting', 2: 'area', 3: 'role'}

def dev_base(device_id):
    """`uuid::채널` 형식이면 `::` 앞만 — shapes_for_device 와 같은 규칙."""
    return str(device_id or '').split('::')[0]


CRITERIA = ('legacy_only_markers', 'far_from_place',
            'explicit_tz_no_place', 'dangling_map_config')


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _flatten(coords):
    if coords and isinstance(coords[0], (int, float)):
        yield coords
        return
    for c in coords or ():
        yield from _flatten(c)


def feature_point(feature):
    """GeoJSON feature → (lat, lng) 대표점. 점은 그 점, 그 외는 꼭짓점 평균."""
    try:
        if isinstance(feature, str):
            feature = json.loads(feature)
        coords = ((feature or {}).get('geometry') or {}).get('coordinates')
        pts = [c for c in _flatten(coords) if len(c) >= 2]
        if not pts:
            return None
        return (sum(c[1] for c in pts) / len(pts),
                sum(c[0] for c in pts) / len(pts))
    except Exception:  # noqa: BLE001 — 깨진 JSON 은 "좌표 없음" 으로 센다
        return None


def _has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone() is not None


def _cols(con, table):
    return {r[1] for r in con.execute('PRAGMA table_info("%s")' % table)}


def open_ro(path):
    con = sqlite3.connect('file:%s?mode=ro' % quote(str(path)), uri=True)
    con.row_factory = sqlite3.Row
    return con


def _neg(text):
    """문자열 시각을 '큰 것이 먼저' 정렬되게 뒤집는다(None 은 가장 뒤)."""
    if not text:
        return (1, ())
    return (0, tuple(-ord(ch) for ch in str(text)))


def analyze(con, default_coords=None, far_m=50.0):
    """검사 본체. {'summary':…, 'criteria':{…}, 'rows':[…]} 를 돌려준다."""
    # 기본 좌표: 인자 > GeoSetting. 리터럴을 박지 않는다.
    if default_coords is None and _has_table(con, 'geo_setting'):
        r = con.execute('SELECT default_lat, default_lng FROM geo_setting '
                        'LIMIT 1').fetchone()
        if r and r[0] is not None and r[1] is not None:
            default_coords = (r[0], r[1])

    shapes = {}
    if _has_table(con, 'geo_shape'):
        for r in con.execute('SELECT unique_id, type, device_id, channel_id, '
                             'feature FROM geo_shape'):
            shapes[r['unique_id']] = r
    map_ids = ({r[0] for r in con.execute('SELECT unique_id FROM geo_map')}
               if _has_table(con, 'geo_map') else set())
    facilities = {}
    if _has_table(con, 'geo_facility'):
        for r in con.execute('SELECT unique_id, shape_uuid FROM geo_facility'):
            facilities[r['unique_id']] = r['shape_uuid']

    has_binding = _has_table(con, 'geo_binding')
    bindings = {}            # device_id → 현재 바인딩 [dict]
    history = {}             # device_id → 이력 전체(valid_to 무관)의 spatial_id 집합
    if has_binding:
        bcols = _cols(con, 'geo_binding')
        extra = ', '.join(c if c in bcols else 'NULL AS %s' % c
                          for c in ('id', 'valid_from', 'channel_id'))
        for r in con.execute('SELECT spatial_kind, spatial_id, role, device_id, '
                             'valid_to, %s FROM geo_binding' % extra):
            history.setdefault(r['device_id'], set()).add(r['spatial_id'])
            if r['valid_to'] is None:
                bindings.setdefault(r['device_id'], []).append(dict(r))

    # 마커: 장치 uuid → 점 좌표(여러 개면 첫 점). 레거시 컬럼은 device_id.
    marker_pt = {}
    for s in shapes.values():
        if s['type'] in MARKER_TYPES and s['device_id']:
            pt = feature_point(s['feature'])
            if pt is not None:
                marker_pt.setdefault(dev_base(s['device_id']), pt)

    def _is_point(sh):
        try:
            f = sh['feature']
            f = json.loads(f) if isinstance(f, str) else f
            return ((f or {}).get('geometry') or {}).get('type') == 'Point'
        except Exception:  # noqa: BLE001
            return False

    def place_point(dev_uuid):
        """바인딩 → (rank, (lat,lng)) 대표 자리. 없으면 None.

        리졸버와 같은 규칙: rank 0(마커)은 GeoShape.type 이 마커 종류이고 점
        기하일 때만. 같은 rank 안에서는 채널 '0' 이 있으면 그쪽, 그다음
        valid_from 최신·id 큰 것.
        """
        cands = []
        for b in bindings.get(dev_uuid, ()):
            kind, sid = b['spatial_kind'], b['spatial_id']
            if kind == 'shape':
                sh = shapes.get(sid)
                if sh is None:
                    continue
                rank = 0 if (sh['type'] in MARKER_TYPES and _is_point(sh)) else 2
            else:
                sh = shapes.get(facilities.get(sid.split(':', 1)[0]))
                rank = PLACE_RANK.get(kind, 3)
            pt = feature_point(sh['feature']) if sh is not None else None
            if pt is None:
                continue
            ch0 = 0 if str(b.get('channel_id') or '0') == '0' else 1
            cands.append((rank, ch0, _neg(b.get('valid_from')), -(b.get('id') or 0), pt))
        if not cands:
            return None
        best = min(cands, key=lambda c: c[:4])
        return best[0], best[4]

    rows, tz_dist = [], Counter()
    mc_seen, mc_has = 0, 0       # map_config_id 컬럼이 있는 장치 테이블 수 / 검사한 수
    totals = Counter()
    per_kind = {}
    for kind, table in DEVICE_TABLES:
        if not _has_table(con, table):
            continue
        cols = _cols(con, table)
        mc_seen += 1
        mc_has += 'map_config_id' in cols
        sel = ['unique_id', 'name'] + [
            c if c in cols else 'NULL AS %s' % c
            for c in ('latitude', 'longitude', 'tz_source', 'map_config_id')]
        k = per_kind.setdefault(kind, Counter())
        for r in con.execute('SELECT %s FROM "%s"' % (', '.join(sel), table)):
            uid = r['unique_id']
            col_pt = ((r['latitude'], r['longitude'])
                      if r['latitude'] is not None and r['longitude'] is not None
                      else None)
            mk = marker_pt.get(uid)
            plc = place_point(uid)
            bound = uid in bindings
            d_marker = haversine_m(*col_pt, *mk) if col_pt and mk else None
            d_place = haversine_m(*col_pt, *plc[1]) if col_pt and plc else None
            is_default = bool(
                col_pt and default_coords
                and abs(col_pt[0] - default_coords[0]) < 1e-9
                and abs(col_pt[1] - default_coords[1]) < 1e-9)
            tz_src = r['tz_source']
            tz_dist[tz_src or '(null)'] += 1
            has_place = plc is not None or mk is not None
            mc = r['map_config_id']
            flags = []
            ref_far = False
            # 50 m 기준은 마커(rank 0)에만 건다. 구역·설비 항목·역할은 시설 중심
            # 근사라 거리가 커도 드리프트가 아니다 — 참고 열(far_ref)로만 센다.
            if d_place is not None and d_place > far_m:
                if plc[0] == 0:
                    flags.append('far_from_place')
                else:
                    totals['far_ref_nonmarker'] += 1
                    ref_far = True
            if tz_src == 'explicit' and not has_place:
                flags.append('explicit_tz_no_place')
            if mc and mc not in map_ids:
                flags.append('dangling_map_config')
            k['rows'] += 1
            k['col'] += bool(col_pt)
            k['marker'] += bool(mk)
            k['binding'] += bound
            k['default_coords'] += is_default
            k['map_config'] += bool(mc)
            for f in flags:
                k[f] += 1
            if flags or is_default or ref_far:
                rows.append({
                    'kind': kind, 'name': r['name'], 'uuid': uid,
                    'flags': flags + (['default_coords'] if is_default else [])
                    + (['far_ref_nonmarker'] if ref_far else []),
                    'col_vs_marker_m': None if d_marker is None else round(d_marker, 1),
                    'col_vs_place_m': None if d_place is None else round(d_place, 1),
                    'place_rank': PLACE_LABEL[plc[0]] if plc else None})
            totals.update({'rows': 1, 'col': bool(col_pt), 'marker': bool(mk),
                           'binding': bound, 'default_coords': is_default,
                           'map_config': bool(mc)})
            for f in flags:
                totals[f] += 1
            if d_marker is not None and d_marker > far_m:
                totals['marker_far'] += 1

    # 기준 1: 레거시 device_id 만 있고 geo_binding **이력이 전혀 없는** 장치의 마커
    # (리졸버 `_legacy_fallback` 의 의도와 같다). 이력이 있는데 이 도형만 빠진
    # 마커(bound_elsewhere)는 기준에서 빼고 따로 센다 — 장치가 다른 자리에
    # 묶였거나 이 자리의 바인딩이 종료된 경우다.
    legacy_only, elsewhere = [], []
    for s_ in shapes.values():
        if s_['type'] in MARKER_TYPES and s_['device_id']:
            dev = dev_base(s_['device_id'])
            hist = history.get(dev)
            item = {'shape': s_['unique_id'], 'device_id': dev}
            if not hist:
                legacy_only.append(item)
            elif s_['unique_id'] not in hist:
                elsewhere.append(item)
    criteria = {
        'legacy_only_markers': len(legacy_only),
        'far_from_place': totals['far_from_place'],
        'explicit_tz_no_place': totals['explicit_tz_no_place'],
        'dangling_map_config': totals['dangling_map_config'],
    }
    mc_absent = mc_has == 0
    return {
        'map_config_column': ('absent' if mc_absent else
                              'present' if mc_has == mc_seen else 'partial'),
        'has_geo_binding_table': has_binding,
        'default_coords': list(default_coords) if default_coords else None,
        'far_m': far_m,
        'criteria': criteria,
        'l4_ok': not any(criteria.values()),
        'report_only': {'default_coords_rows': totals['default_coords'],
                        'markers_bound_elsewhere': len(elsewhere),
                        'far_ref_nonmarker': totals['far_ref_nonmarker'],
                        'col_vs_marker_far': totals['marker_far']},
        'summary': {'total': dict(totals),
                    'by_kind': {k: dict(v) for k, v in per_kind.items()},
                    'tz_source': dict(tz_dist)},
        'legacy_only_markers': legacy_only,
        'markers_bound_elsewhere': elsewhere,
        'rows': rows,
    }


def render(res, verbose=False):
    out = []
    t = res['summary']['total']
    out.append('장치 위치 드리프트 — 장치 %d행, 기본 좌표 %s, 임계 %sm%s' % (
        t.get('rows', 0), res['default_coords'], res['far_m'],
        '' if res['has_geo_binding_table'] else ' (geo_binding 테이블 없음)'))
    mc_absent = res.get('map_config_column') == 'absent'
    out.append('%-12s %5s %5s %6s %7s %8s %6s' % (
        '종류', '행', '컬럼', '마커', '바인딩', '기본좌표', 'cfg'))
    for kind, v in res['summary']['by_kind'].items():
        out.append('%-12s %5d %5d %6d %7d %8d %6s' % (
            kind, v.get('rows', 0), v.get('col', 0), v.get('marker', 0),
            v.get('binding', 0), v.get('default_coords', 0),
            '-' if mc_absent else v.get('map_config', 0)))
    out.append('tz_source: %s' % json.dumps(res['summary']['tz_source'],
                                            ensure_ascii=False))
    out.append('')
    out.append('L4 기준 (모두 0 이어야 L4 가능):')
    for key in CRITERIA:
        out.append('  %-22s %d%s' % (
            key, res['criteria'][key],
            '  (column absent)' if key == 'dangling_map_config' and mc_absent
            else ''))
    ro = res['report_only']
    out.append('보고만: 기본 좌표 그대로 %d행, 컬럼↔마커 > %sm %d행, 다른 자리에만 묶인 마커 %d개,'
               ' 구역·설비·역할 자리 > %sm %d행(참고)' % (
                   ro['default_coords_rows'], res['far_m'],
                   ro['col_vs_marker_far'], ro['markers_bound_elsewhere'],
                   res['far_m'], ro['far_ref_nonmarker']))
    out.append('판정: %s' % ('L4 가능' if res['l4_ok'] else 'L4 불가'))
    bad = [r for r in res['rows']
           if set(r['flags']) - {'default_coords', 'far_ref_nonmarker'}]
    if bad:
        out.append('')
        out.append('불일치 행 %d건%s' % (len(bad), '' if verbose else
                                       ' (이름·uuid 는 --verbose)'))
        for r in bad[:100]:
            ident = ('%s %s %s' % (r['kind'], r['name'], r['uuid'])
                     if verbose else r['kind'])
            out.append('  %s flags=%s 마커=%sm 자리(%s)=%s m' % (
                ident, ','.join(r['flags']), r['col_vs_marker_m'],
                r['place_rank'], r['col_vs_place_m']))
    if verbose and res['legacy_only_markers']:
        out.append('')
        out.append('레거시 전용 마커 %d건' % len(res['legacy_only_markers']))
        for m in res['legacy_only_markers'][:100]:
            out.append('  shape=%s device=%s' % (m['shape'], m['device_id']))
    if verbose and res['markers_bound_elsewhere']:
        out.append('')
        out.append('다른 자리에만 묶인 마커 %d건 (보고만)' % len(res['markers_bound_elsewhere']))
        for m in res['markers_bound_elsewhere'][:100]:
            out.append('  shape=%s device=%s' % (m['shape'], m['device_id']))
    return '\n'.join(out)


def _strip_ids(res):
    """기본 출력에서 uuid·이름을 뺀다(--verbose 에서만 노출)."""
    res = dict(res)
    res['rows'] = [{k: v for k, v in r.items() if k not in ('name', 'uuid')}
                   for r in res['rows']]
    res['legacy_only_markers'] = [{} for _ in res['legacy_only_markers']]
    res['markers_bound_elsewhere'] = [{} for _ in res['markers_bound_elsewhere']]
    return res


def parse_coords(text):
    lat, lng = (float(x) for x in text.split(','))
    return lat, lng


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True, metavar='PATH',
                    help='검사할 sqlite 파일 (운영은 사본만)')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--verbose', action='store_true',
                    help='이름·uuid 와 레거시 전용 마커 목록 포함')
    ap.add_argument('--default-coords', metavar='LAT,LNG',
                    help='기본 좌표(생략 시 그 DB 의 GeoSetting)')
    ap.add_argument('--far-m', type=float, default=50.0)
    args = ap.parse_args(argv)
    try:
        con = open_ro(args.db)
        res = analyze(con, parse_coords(args.default_coords)
                      if args.default_coords else None, args.far_m)
    except Exception as exc:  # noqa: BLE001
        print('ERROR: 검사 실패 — %s' % exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res if args.verbose else _strip_ids(res),
                         ensure_ascii=False, indent=2))
    else:
        print(render(res, args.verbose))
    return 0 if res['l4_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
