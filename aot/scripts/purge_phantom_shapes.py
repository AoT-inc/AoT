#!/usr/bin/env python3
# coding=utf-8
"""유령 지도(GeoMap 행이 없는 geo_id)에 남은 GeoShape 를 정리한다.

`check_geo_integrity.py` 의 `phantom-map` 항목에 대응하는 처분 도구다. 검사기는
일부러 자동 삭제를 하지 않는다 — `get_overlays()` 가 GeoMap 존재를 확인하지
않아, 위젯이 낡은 map_uuid 를 들고 있으면 지도가 지워진 뒤에도 계속 렌더링될
수 있기 때문이다. 그래서 처분은 사람이 정하고, 이 스크립트가 그 실행을 맡는다.

배경 (2026-08-05 aot-005): 도형 81개 중 54개가 유령 지도 3개에 묶여 있었다.
지도만 지워지고 내용물이 남은 형태다. 화면 어디에도 나타나지 않는데, 농장 전역
기준 좌표를 구하는 `timekit._system_coords()` 가 `Misc.map_*` 가 비어 있으면
**아무 site 도형이나 첫 행**을 쓰기 때문에, 보이지 않는 죽은 도형이 농장 위치를
결정하고 있었다. 실제 시설은 36.70N/129.13E 인데 200km 떨어진 좌표가 나왔고,
그 위치를 상속한 Function·PID 가 일몰을 7분 어긋나게 계산했다.

**삭제보다 `--set-origin` 이 먼저다.** 기준 좌표를 명시하면 폴백 1단계에서
잡혀 유령 도형을 뒤지지 않으므로, 삭제 없이도 좌표 문제가 끝난다. 삭제는
그 뒤에 여유 있게 하면 된다.

안전장치:
  - 기본이 모의 실행(dry-run). 실제 삭제는 `--apply` 를 줘야 한다.
  - `--apply` 시 삭제 전 DB 를 자동 백업한다.
  - 도형마다 **모든 참조 경로를 실행 시점에 다시 확인**하고, 하나라도 걸리면
    그 도형은 건너뛴다. 사전 조사 결과를 믿지 않는다.
  - 한 트랜잭션으로 처리하고, 끝나고 남은 유령 수를 다시 세어 보고한다.

사용:
    # 무엇이 지워질지 보기만 한다 (안전)
    python3 aot/scripts/purge_phantom_shapes.py

    # 농장 기준 좌표만 채운다 (삭제 없음)
    python3 aot/scripts/purge_phantom_shapes.py --set-origin 36.703284,129.126152 --apply

    # 좌표를 채우고 유령 도형까지 정리한다
    python3 aot/scripts/purge_phantom_shapes.py --set-origin 36.703284,129.126152 --purge --apply

    # 네이티브 서버(배포 디렉터리를 건드리지 않음)
    cd /opt/AoT && ./env/bin/python /tmp/purge_phantom_shapes.py --db /opt/AoT/aot/databases/aot.db

종료 코드: 0=정상, 1=참조가 남아 건너뛴 도형 있음, 2=실행 실패.
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = '/opt/AoT/aot/databases/aot.db'

# map_overlay_id 로 도형을 참조하는 모델들. CLAUDE.md 의 "7개 모델 전부" 목록과
# 같아야 한다 — 하나라도 빠지면 참조를 끊은 채 지우게 된다.
OVERLAY_TABLES = (
    'input', 'output', 'pid', 'trigger',
    'conditional', 'custom_controller', 'function',
)


def _table_exists(cur, name):
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def _has_column(cur, table, column):
    cur.execute(f'PRAGMA table_info({table})')
    return any(row[1] == column for row in cur.fetchall())


def find_phantom_shapes(cur):
    """유령 지도에 속한 도형을 {geo_id: [(id, unique_id, type)]} 로."""
    cur.execute("""
        SELECT s.id, s.unique_id, COALESCE(s.type, ''), COALESCE(s.geo_id, '')
        FROM geo_shape s
        WHERE s.geo_id IS NULL
           OR s.geo_id NOT IN (SELECT unique_id FROM geo_map)
        ORDER BY s.id
    """)
    out = {}
    for sid, uid, stype, geo_id in cur.fetchall():
        out.setdefault(geo_id or '(NULL)', []).append((sid, uid, stype))
    return out


def references_to(cur, shape_uuid, geo_id):
    """이 도형을 붙잡고 있는 참조를 전부 찾아 목록으로 반환. 비면 삭제 가능.

    검사기가 경고한 위젯 경로를 반드시 포함한다 — 위젯은 도형 uuid 가 아니라
    **지도 uuid** 를 들고 있으므로 둘 다 본다.
    """
    hits = []

    # 1. 시설이 이 도형을 외곽선으로 쓰는가
    if _table_exists(cur, 'geo_facility'):
        cur.execute('SELECT COUNT(*) FROM geo_facility WHERE shape_uuid = ?', (shape_uuid,))
        if cur.fetchone()[0]:
            hits.append('geo_facility.shape_uuid')
        # 이 유령 지도에 속한 시설이 있는가 (도형을 지우면 시설이 외톨이가 된다)
        if geo_id and _has_column(cur, 'geo_facility', 'geo_id'):
            cur.execute('SELECT COUNT(*) FROM geo_facility WHERE geo_id = ?', (geo_id,))
            if cur.fetchone()[0]:
                hits.append('geo_facility.geo_id(같은 유령 지도에 시설 존재)')

    # 2. 살아있는 도형이 이 도형을 부모로 삼는가
    cur.execute("""
        SELECT COUNT(*) FROM geo_shape
        WHERE parent_id = ?
          AND geo_id IN (SELECT unique_id FROM geo_map)
    """, (shape_uuid,))
    if cur.fetchone()[0]:
        hits.append('geo_shape.parent_id')

    # 3. 7개 모델의 map_overlay_id
    for tbl in OVERLAY_TABLES:
        if not _table_exists(cur, tbl) or not _has_column(cur, tbl, 'map_overlay_id'):
            continue
        cur.execute(
            f"SELECT COUNT(*) FROM {tbl} "
            f"WHERE map_overlay_id IS NOT NULL AND map_overlay_id != '' "
            f"AND map_overlay_id = ?", (shape_uuid,))
        if cur.fetchone()[0]:
            hits.append(f'{tbl}.map_overlay_id')

    # 4. 위젯 (도형 uuid 또는 지도 uuid) — 검사기가 자동삭제를 막은 이유
    if _table_exists(cur, 'widget') and _has_column(cur, 'widget', 'custom_options'):
        for needle, label in ((shape_uuid, '도형'), (geo_id, '지도')):
            if not needle:
                continue
            cur.execute(
                "SELECT COUNT(*) FROM widget WHERE custom_options LIKE ?",
                (f'%{needle}%',))
            if cur.fetchone()[0]:
                hits.append(f'widget.custom_options({label} uuid)')

    return hits


def set_origin(cur, lat, lon, label=None):
    """농장 전역 기준 좌표를 Misc 에 명시한다 (폴백 1단계)."""
    if not _table_exists(cur, 'misc'):
        raise RuntimeError('misc 테이블이 없습니다')
    cur.execute('SELECT id, map_latitude, map_longitude FROM misc ORDER BY id LIMIT 1')
    row = cur.fetchone()
    if row is None:
        raise RuntimeError('misc 행이 없습니다')
    before = (row[1], row[2])
    if label is not None and _has_column(cur, 'misc', 'map_location_label'):
        cur.execute(
            'UPDATE misc SET map_latitude=?, map_longitude=?, map_location_label=? WHERE id=?',
            (lat, lon, label, row[0]))
    else:
        cur.execute('UPDATE misc SET map_latitude=?, map_longitude=? WHERE id=?',
                    (lat, lon, row[0]))
    return before


def backup_db(path):
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = f'{path}.bak_{stamp}'
    shutil.copy2(path, dest)
    for suffix in ('-wal', '-shm'):
        if os.path.exists(path + suffix):
            shutil.copy2(path + suffix, dest + suffix)
    return dest


def main():
    ap = argparse.ArgumentParser(description='유령 지도에 남은 GeoShape 정리')
    ap.add_argument('--db', default=DEFAULT_DB, help=f'DB 경로 (기본 {DEFAULT_DB})')
    ap.add_argument('--apply', action='store_true',
                    help='실제로 반영한다 (없으면 모의 실행)')
    ap.add_argument('--purge', action='store_true',
                    help='유령 도형을 삭제한다 (없으면 보고만)')
    ap.add_argument('--set-origin', metavar='LAT,LON',
                    help='농장 전역 기준 좌표를 Misc 에 설정')
    ap.add_argument('--origin-label', default=None, help='기준 좌표 표시 이름')
    ap.add_argument('--no-backup', action='store_true',
                    help='백업을 건너뛴다 (권장하지 않음)')
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f'DB 를 찾을 수 없습니다: {args.db}', file=sys.stderr)
        return 2

    mode = '실제 반영' if args.apply else '모의 실행 (아무것도 바꾸지 않음)'
    print(f'DB   : {args.db}')
    print(f'모드 : {mode}\n')

    backup = None
    if args.apply and not args.no_backup:
        try:
            backup = backup_db(args.db)
            print(f'백업 : {backup}\n')
        except Exception as exc:
            print(f'백업 실패로 중단합니다: {exc}', file=sys.stderr)
            return 2

    conn = sqlite3.connect(args.db)
    conn.isolation_level = None
    cur = conn.cursor()
    skipped = 0

    try:
        cur.execute('BEGIN')

        # ── 1. 농장 기준 좌표 ──────────────────────────────────────────────
        if args.set_origin:
            try:
                lat_s, lon_s = args.set_origin.split(',')
                lat, lon = float(lat_s), float(lon_s)
            except ValueError:
                print('--set-origin 형식은 LAT,LON 입니다', file=sys.stderr)
                cur.execute('ROLLBACK')
                return 2
            before = set_origin(cur, lat, lon, args.origin_label)
            print('[농장 기준 좌표]')
            print(f'  이전 : {before[0]}, {before[1]}')
            print(f'  이후 : {lat}, {lon}')
            print('  → 이제 폴백 1단계에서 잡히므로 site 도형을 뒤지지 않습니다.\n')

        # ── 2. 유령 도형 ──────────────────────────────────────────────────
        phantom = find_phantom_shapes(cur)
        total = sum(len(v) for v in phantom.values())
        if not total:
            print('[유령 도형] 없음')
        else:
            print(f'[유령 도형] 지도 {len(phantom)}개 / 도형 {total}개')
            for geo_id, shapes in phantom.items():
                kinds = {}
                for _, _, stype in shapes:
                    kinds[stype] = kinds.get(stype, 0) + 1
                kind_str = ', '.join(f'{k}×{v}' for k, v in sorted(kinds.items()))
                print(f'  {geo_id[:8]} : {len(shapes)}개  ({kind_str})')

                deletable, blocked = [], []
                for sid, uid, stype in shapes:
                    hits = references_to(cur, uid, geo_id)
                    (blocked if hits else deletable).append((sid, uid, stype, hits))

                for sid, uid, stype, hits in blocked:
                    print(f'    보존 id={sid} {stype}: {", ".join(hits)}')
                skipped += len(blocked)

                if args.purge and deletable:
                    if args.apply:
                        cur.executemany('DELETE FROM geo_shape WHERE id = ?',
                                        [(s[0],) for s in deletable])
                        print(f'    삭제 {len(deletable)}개')
                    else:
                        print(f'    삭제 예정 {len(deletable)}개 (모의)')
                elif deletable:
                    print(f'    삭제 가능 {len(deletable)}개 (--purge 를 줘야 지웁니다)')

        if args.apply:
            cur.execute('COMMIT')
            print('\n반영했습니다.')
        else:
            cur.execute('ROLLBACK')
            print('\n모의 실행이라 되돌렸습니다. 실제로 하려면 --apply 를 붙이십시오.')

        # ── 3. 사후 확인 ──────────────────────────────────────────────────
        if args.apply and args.purge:
            left = sum(len(v) for v in find_phantom_shapes(cur).values())
            print(f'남은 유령 도형: {left}개')
            if left and left != skipped:
                print('  (예상과 다릅니다 — check_geo_integrity 로 재확인하십시오)')

    except Exception as exc:
        try:
            cur.execute('ROLLBACK')
        except Exception:
            pass
        print(f'\n실패해서 되돌렸습니다: {exc}', file=sys.stderr)
        if backup:
            print(f'백업본: {backup}', file=sys.stderr)
        return 2
    finally:
        conn.close()

    if skipped:
        print(f'\n참조가 남아 건너뛴 도형 {skipped}개 — 처분을 직접 정하십시오.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
