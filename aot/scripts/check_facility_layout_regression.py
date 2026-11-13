#!/usr/bin/env python3
"""시설 모형(`facility_layout`) 회귀 대조 (읽기 전용, 단계 F0).

모든 시설에 대해 기존 경로의 결과와 새 모형의 결과를 비교하고 불일치를 출력한다.
DB 는 쓰지 않는다. 입력은 둘 중 하나다.

  --db PATH     SQLite aot.db (읽기 전용으로 연다: file:...?mode=ro)
  --dump PATH   --db 와 같은 내용을 JSON 으로 덤프한 파일(`--dump-to` 로 만들 수 있다)

비교 항목
---------
A. 합계 7개: `compute_capacity(spec)` 의 floor_m2, envelope_m2, sidewall_m2, roof_m2,
   gable_m2, volume_m3, glazing_m2  ↔  `compile_layout(layout_from_legacy(spec))['totals']`.
   spec 은 `facility_integration.get_facility_integration` 이 만드는 것과 같다
   (outer_geometry = 시설 도형 feature 의 geometry).
B. 구역 귀속: fitting 마다 `build_fitting_bay_map(compute_bay_slices(spec), fittings)` 의
   구역 id (귀속 불가면 없음)  ↔  `locate(layout, x, y, z)['space_id']` (None 이면 없음).
C. 자체 정합: 공간 넓이 합이 시설 바닥 합과 같으면(공간이 덩어리를 다 채움) 공간별
   수치 합이 합계와 같아야 한다.
D. (F1) 구역 슬라이스: F1 이전 `compute_bay_slices` 의 기존 키 값(동결 사본 `_legacy_slices`)이
   그대로이고, 새 키 `outline`(x_min..x_max × 0..길이 직사각형)·`level_id`('L1')가 맞다.
E. (F1) 귀속 공통 경로: 새 `build_fitting_bay_map`/`bay_id_for_position` 이 F1 이전 x 범위 판정
   (동결 사본 `_legacy_bay_id`)과 (1) 시설의 모든 fitting, (2) 시설 폭 ±3 m 를 0.11 m 간격으로
   훑은 합성 점(z 는 끝벽 밖 포함)에서 정확히 같다.
F. (F1) `_profile_loader_mixin._bay_capacity_fraction`(제어 경로의 구역 폭 비율)이 F1 이전 계산
   (`x_max - x_min` 직접 뺄셈)과 같다.
G. (F3) `layout` 이 없는 시설은 제어 경로의 새 분기를 타지 않는다: `zone_control_bays`·`control_notes`
   가 비고, `upper_fittings` 가 비고(`control_view` 가 생기지 않는다), `plot_bay_ids` 는 옛 구역 id 다.

허용 오차 (넓히지 않는다)
------------------------
기존은 도형을 위경도로 그린 뒤 평면 근사로 넓이를 다시 구하므로 좌표 반올림만큼 다르다.
  |차이| <= max(ABS_TOL_M = 0.02, REL_TOL = 0.001 * |기존값|)
(실측 최대 상대 차이는 0.05% 이내.) 귀속은 정확히 같아야 한다.

알려진 차이 (모듈 머리말 참조 — 정확한 관계식이 성립할 때만 '알려진 차이'로 센다)
------------------------------------------------------------------------------
K1. connected N동(N>=2)의 박공: 기존은 양 끝 단면 2개만 센다. 새 모형은 동마다 2N 개.
    기대: gable_new = gable_old * N,  envelope_new = envelope_old + gable_old * (N-1).
K2. 덮개 투과율 0 재질(샌드위치 패널 등): 기존 glazing = 외피 전부(투명 가정, PoC).
    새 모형 glazing = 0.
이 관계식이 어긋나면 그대로 '불일치'다.

종료 코드: 불일치가 있으면 1, 없으면 0 (알려진 차이는 0 으로 친다).
"""
import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
sys.path.insert(0, ROOT)

from aot.space import facility_bays as FB  # noqa: E402
from aot.space.facility_bays import (  # noqa: E402
    bay_id_for_position, build_fitting_bay_map, compute_bay_slices, _pos_x)
from aot.space.facility_calc import MATERIALS, compute_capacity  # noqa: E402
from aot.space import facility_layout as FL  # noqa: E402

ABS_TOL_M = 0.02
REL_TOL = 0.001
KEYS = ('floor_m2', 'envelope_m2', 'sidewall_m2', 'roof_m2', 'gable_m2', 'volume_m3', 'glazing_m2')
_JSON_COLS = ('geometry_3d', 'envelope', 'actuators', 'bays', 'fittings')


def _j(v):
    if isinstance(v, bytes):
        v = v.decode()
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def load_db(path):
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute('select * from geo_facility order by id'):
        d = dict(r)
        rec = {k: d.get(k) for k in ('id', 'unique_id', 'shape_uuid', 'name', 'structure', 'bay_count')}
        for k in _JSON_COLS:
            rec[k] = _j(d.get(k))
        row = con.execute('select feature from geo_shape where unique_id=?', (d.get('shape_uuid'),)).fetchone()
        rec['outer_feature'] = _j(row[0]) if row else None
        out.append(rec)
    con.close()
    return out


def _spec(f):
    actuators = f.get('actuators')
    fittings = f.get('fittings')
    return {
        'outer_geometry': (f.get('outer_feature') or {}).get('geometry'),
        'bay_count': f.get('bay_count') or 1,
        'structure': f.get('structure') or 'single',
        'geometry_3d': f.get('geometry_3d') or {},
        'envelope': f.get('envelope') or {},
        'actuators': actuators if isinstance(actuators, (list, dict)) else {},
        'fittings': fittings if isinstance(fittings, list) else [],
        'bays': f.get('bays') if isinstance(f.get('bays'), list) else [],
        'name': f.get('name'),
    }


# ---- F1 이전 동작의 동결 사본 (전후 대조용 — 고치지 말 것) ----------------------
_LEGACY_TOL = 1.0


def _legacy_slices(facility):
    """F1 이전 `compute_bay_slices` 의 id·x 값(기존 키만)."""
    try:
        bay_count = int(facility.get('bay_count') or 1)
    except (TypeError, ValueError):
        bay_count = 1
    g3d = facility.get('geometry_3d') or {}
    try:
        span_w = float(g3d.get('span_width_m') or 0)
    except (TypeError, ValueError):
        span_w = 0.0
    if span_w <= 0:
        return []
    is_connected = (facility.get('structure') or 'single') == 'connected'
    try:
        spacing = 0.0 if is_connected else float(g3d.get('spacing_m') or 0)
    except (TypeError, ValueError):
        spacing = 0.0
    meta = facility.get('bays') if isinstance(facility.get('bays'), list) else []

    def bx(i):
        x0 = (i - 1) * (span_w + spacing)
        return x0, x0 + span_w
    zones = []
    for m in meta:
        if not isinstance(m, dict):
            continue
        try:
            a, b = int(m.get('bay_start') or 0), int(m.get('bay_end') or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= a <= b <= bay_count:
            zones.append((a, b, m))
    out = []
    if zones:
        zones.sort(key=lambda t: t[0])
        for i, (a, b, m) in enumerate(zones):
            x0, x1 = bx(a)[0], bx(b)[1]
            out.append({'id': str(m.get('id') or ('bay_%d' % a if a == b else 'bay_%d_%d' % (a, b))),
                        'index': i, 'bay_start': a, 'bay_end': b, 'x_min': round(x0, 3),
                        'x_max': round(x1, 3), 'x_center': round((x0 + x1) / 2.0, 3)})
        return out
    legacy = meta if (is_connected or bay_count == 1) else []
    for i in range(bay_count):
        x0, x1 = bx(i + 1)
        mm = legacy[i] if i < len(legacy) and isinstance(legacy[i], dict) else {}
        out.append({'id': str(mm.get('id') or 'bay_%d' % (i + 1)), 'index': i, 'bay_start': i + 1,
                    'bay_end': i + 1, 'x_min': round(x0, 3), 'x_max': round(x1, 3),
                    'x_center': round((x0 + x1) / 2.0, 3)})
    return out


def _legacy_bay_id(slices, position):
    """F1 이전 `bay_id_for_position`."""
    if not slices:
        return None
    x = _pos_x(position)
    if x is None:
        return None
    if x < slices[0]['x_min'] - _LEGACY_TOL or x > slices[-1]['x_max'] + _LEGACY_TOL:
        return None
    for sl in slices:
        if sl['x_min'] <= x <= sl['x_max']:
            return sl['id']
    return min(slices, key=lambda sl: abs(x - sl['x_center']))['id']


def _legacy_fraction(slices, bay_id):
    """F1 이전 `_bay_capacity_fraction`."""
    total, mine = 0.0, None
    for sl in slices or []:
        try:
            w = float(sl.get('x_max')) - float(sl.get('x_min'))
        except (TypeError, ValueError):
            return None
        if w <= 0:
            return None
        total += w
        if sl.get('id') == bay_id:
            mine = w
    if mine is None or total <= 0:
        return None
    return mine / total


def _close(new, old):
    return abs(new - old) <= max(ABS_TOL_M, REL_TOL * abs(old))


def _xyz(position):
    x = _pos_x(position)
    if x is None:
        return None
    if isinstance(position, dict):
        return x, position.get('y'), position.get('z')
    pos = list(position) + [None, None]
    return x, pos[1], pos[2]


def check_facility(f):
    """→ (match: list, known: list, mismatch: list). 각 항목은 한 줄 설명."""
    match, known, bad = [], [], []
    spec = _spec(f)
    old = compute_capacity(spec)
    layout = FL.layout_from_legacy(spec)
    errs = FL.validate_layout(layout)
    if errs:
        bad.append('layout 검증 실패: %s' % errs[:3])
        return match, known, bad
    comp = FL.compile_layout(layout)
    new = comp['totals']
    n = max(int(spec['bay_count'] or 1), 1)
    connected = spec['structure'] == 'connected'
    opaque = MATERIALS.get(layout['blocks'][0]['walls']['cover'], {}).get('transmittance', 1) == 0

    # A. 합계
    gable_old = old['gable_m2']
    for k in KEYS:
        o, v = old[k], new[k]
        if _close(v, o):
            match.append(k)
            continue
        expect = None
        why = None
        if k == 'glazing_m2' and opaque:
            expect, why = 0.0, 'K2 불투명 덮개'
        elif connected and n >= 2 and k == 'gable_m2':
            expect, why = gable_old * n, 'K1 연동 박공 2N'
        elif connected and n >= 2 and k == 'envelope_m2':
            expect, why = old['envelope_m2'] + gable_old * (n - 1), 'K1 연동 박공 2N'
        elif connected and n >= 2 and k == 'glazing_m2':
            expect, why = old['glazing_m2'] + gable_old * (n - 1), 'K1 연동 박공 2N'
        if expect is not None and _close(v, expect):
            known.append('%s %s (기존 %.2f → 새 %.2f)' % (k, why, o, v))
        else:
            bad.append('%s 기존 %.2f ≠ 새 %.2f' % (k, o, v))

    # B. 구역 귀속
    slices = compute_bay_slices(spec)
    legacy_map = build_fitting_bay_map(slices, spec['fittings'])
    checked = diff = 0
    for fit in spec['fittings']:
        fid = fit.get('id')
        if not fid:
            continue
        xyz = _xyz(fit.get('position'))
        if xyz is None:
            continue
        checked += 1
        r = FL.locate(layout, xyz[0], xyz[1], xyz[2])
        got = r['space_id'] if r else None
        exp = legacy_map.get(fid)
        if got != exp:
            diff += 1
            if diff <= 3:
                bad.append('귀속 %s pos=%s 기존 %s ≠ 새 %s' % (fid, fit.get('position'), exp, got))
    if diff > 3:
        bad.append('귀속 불일치 총 %d 건 (위는 앞 3건)' % diff)
    if checked and not diff:
        match.append('귀속 %d건' % checked)
    elif not checked:
        match.append('귀속 0건(대상 fitting 없음)')

    # D. 구역 슬라이스: 기존 키 불변 + 새 키
    old_sl = _legacy_slices(spec)
    if len(old_sl) != len(slices):
        bad.append('슬라이스 수 기존 %d ≠ 새 %d' % (len(old_sl), len(slices)))
    else:
        d_bad = 0
        length = float((spec['geometry_3d'] or {}).get('length_m') or 0) or 30.0
        for o, nw in zip(old_sl, slices):
            if any(o[k] != nw.get(k) for k in o):
                d_bad += 1
                bad.append('슬라이스 %s 기존 키 값이 달라짐 %s ≠ %s' % (o['id'], o, {k: nw.get(k) for k in o}))
            want = [[nw['x_min'], 0.0], [nw['x_max'], 0.0], [nw['x_max'], round(length, 6)], [nw['x_min'], round(length, 6)]]
            if nw.get('outline') != want or nw.get('level_id') != 'L1':
                d_bad += 1
                bad.append('슬라이스 %s outline/level_id 이상 %s %s' % (nw['id'], nw.get('outline'), nw.get('level_id')))
        if not d_bad:
            match.append('슬라이스 %d개(기존 키 불변·outline)' % len(slices))

    # E. 귀속 공통 경로 전후 대조
    old_map = {}
    for fit in spec['fittings']:
        if fit.get('id'):
            b = _legacy_bay_id(old_sl, fit.get('position'))
            if b:
                old_map[fit['id']] = b
    if old_map != legacy_map:
        bad.append('build_fitting_bay_map 전후 불일치 %s' % {k: (old_map.get(k), legacy_map.get(k))
                   for k in set(old_map) | set(legacy_map) if old_map.get(k) != legacy_map.get(k)})
    else:
        match.append('fitting 맵 전후 %d건' % len(old_map))
    if slices:
        probes, x = [], slices[0]['x_min'] - 3.0
        while x <= slices[-1]['x_max'] + 3.0:
            for z in (-5.0, 0.0, 15.0, 30.0, 45.0):
                probes.append({'id': 'p%d_%d' % (round(x * 100), z), 'position': [round(x, 3), 1.0, z]})
            x += 0.11
        got = build_fitting_bay_map(slices, probes)
        want = {p['id']: _legacy_bay_id(old_sl, p['position']) for p in probes}
        want = {k: v for k, v in want.items() if v}
        diff = [k for k in set(got) | set(want) if got.get(k) != want.get(k)]
        if diff:
            bad.append('합성 점 귀속 불일치 %d / %d 건 (예 %s)' % (len(diff), len(probes), diff[:3]))
        else:
            match.append('합성 점 %d건' % len(probes))
        single = [bay_id_for_position(slices, p['position']) == want.get(p['id']) for p in probes[::7]]
        if not all(single):
            bad.append('bay_id_for_position 전후 불일치')

    # F. 제어 경로(_profile_loader_mixin) 구역 폭 비율
    try:
        from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import _bay_capacity_fraction
    except Exception as e:                      # 호스트에 의존성이 없으면 건너뛴다(도커로 돌릴 것)
        _bay_capacity_fraction = None
        known.append('F 건너뜀: mixin 을 불러오지 못함 (%s)' % type(e).__name__)
    if _bay_capacity_fraction:
        f_bad = [sl['id'] for sl in slices
                 if _bay_capacity_fraction(slices, sl['id']) != _legacy_fraction(old_sl, sl['id'])]
        if f_bad:
            bad.append('구역 폭 비율 전후 불일치 %s' % f_bad)
        elif slices:
            match.append('구역 폭 비율 %d개' % len(slices))

    # G. layout 없는 시설은 F3 제어 분기를 타지 않는다
    if FB.zone_control_bays(spec) or FB.control_notes(spec) or FL.upper_fittings(spec.get('layout'), spec['fittings']):
        bad.append('layout 없는 시설이 제어 분기를 탄다')
    elif FB.plot_bay_ids(spec) != {sl['id'] for sl in old_sl}:
        bad.append('plot_bay_ids 가 옛 구역 id 와 다르다')
    else:
        match.append('제어 분기 없음')

    # C. 공간 합 정합
    sp = comp['spaces'].values()
    if _close(sum(s['floor_m2'] for s in sp), new['floor_m2']):
        for k in ('sidewall_m2', 'roof_m2', 'gable_m2', 'envelope_m2', 'volume_m3', 'glazing_m2'):
            tot = sum(s[k] for s in comp['spaces'].values())
            if not _close(tot, new[k]):
                bad.append('공간 합 정합 %s 공간합 %.2f ≠ 합계 %.2f' % (k, tot, new[k]))
    for w in comp['warnings']:
        bad.append('경고 %s' % w)
    return match, known, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--db')
    g.add_argument('--dump')
    ap.add_argument('--dump-to', help='--db 로 읽은 시설을 JSON 으로도 저장')
    ap.add_argument('--quiet', action='store_true', help='일치한 시설 줄은 생략')
    a = ap.parse_args(argv)

    facs = load_db(a.db) if a.db else json.load(open(a.dump))
    if a.dump_to:
        with open(a.dump_to, 'w') as fh:
            json.dump(facs, fh)

    n_ok = n_known = n_bad = 0
    for f in facs:
        m, k, b = check_facility(f)
        tag = 'MISMATCH' if b else ('KNOWN   ' if k else 'OK      ')
        n_bad += bool(b)
        n_known += bool(k) and not b
        n_ok += not b and not k
        if a.quiet and tag == 'OK      ':
            continue
        print('%s id=%s %s (%s %s동)' % (tag, f['id'], f.get('name'), f.get('structure'), f.get('bay_count')))
        for line in k:
            print('    알려진 차이: %s' % line)
        for line in b:
            print('    불일치: %s' % line)
    print('시설 %d개: 완전 일치 %d, 알려진 차이만 %d, 불일치 %d' % (len(facs), n_ok, n_known, n_bad))
    return 1 if n_bad else 0


if __name__ == '__main__':
    sys.exit(main())
