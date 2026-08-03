# coding=utf-8
"""P6-22: 지도 불변식 Tier-1 을 DB 계층에 적용 (트리거 + 마커 유니크 인덱스).

p6_21 이 이미 오염된 데이터를 복구했다면, 이 마이그레이션은 같은 오염이
다시는 만들어질 수 없게 한다. 불변식 정의는 docs/design/geo-data-integrity.md,
DDL 본문은 aot/databases/geo_integrity_ddl.py(단일 정본, 여기서 import),
차단 검증은 aot/tests/geo/test_geo_invariants_attack.py.

적용 내용 (Tier-1, I1~I5):
  I1  geo_shape.type 화이트리스트 밖 값 ABORT
  I2  장치 위치 마커(type='aot_device')는 (지도, 장치, 채널)당 1개 —
      COALESCE(channel_id,'0') 식 유니크 인덱스
  I3  도형 삭제 → 시설·설정점·bay 연쇄 정리 (모든 삭제 경로)
  I4  도형 삭제 → 7개 모델 map_overlay_id NULL
  I5  지도 삭제 → 도형·시설 정리 + map_config_id/map_overlay_id 해제

사전 정리 2건 (I2 인덱스가 실데이터에서 성립하기 위한 필수 선행):
  1) 마커 중복 정리 — 같은 (지도, 장치, 채널) 키의 aot_device 마커가 여러
     개면 하나만 남긴다. 유지 우선순위: 참조되는 행 > updated_at 최신 > id
     최대. 지워지는 행의 참조(map_overlay_id 7테이블 + parent_id)는 유지
     행으로 재지정하고, 원본 행 전체를 geo_integrity_p6_22_backup 테이블에
     JSON 으로 보존한다(행 삭제가 있는 마이그레이션은 반드시 복원 수단을
     남긴다 — 2026-08-03 교훈).
  2) channel_id NULL → '0' 정규화 — 장치위치 API 는 채널 '0' 으로 조회하므로
     NULL 레거시 마커를 못 찾아 INSERT 를 시도하고, I2 인덱스가 그걸 거부하면
     위치 저장이 막힌다. 정규화가 인덱스보다 먼저여야 한다.

멱등: 두 번 돌려도 안전하다(DDL 은 DROP IF EXISTS 후 CREATE, 정리는 대상이
없으면 무동작).

Revision ID: p6_22_geo_integrity_tier1_20260803
Revises: p6_21_geo_shape_type_repair_20260803
Create Date: 2026-08-03
"""
import json
import logging

import sqlalchemy as sa
from alembic import op

revision = 'p6_22_geo_integrity_tier1_20260803'
down_revision = 'p6_21_geo_shape_type_repair_20260803'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

BACKUP_TABLE = 'geo_integrity_p6_22_backup'


def _ddl_module():
    """DDL 정본 모듈(aot/databases/geo_integrity_ddl.py). 실패 시 조용히
    건너뛰지 않고 명확히 죽는다 — 트리거 없이 통과하면 보호 없이 돌아가는
    서버가 생긴다. alembic 이 어떤 경로 맥락에서 호출되든 동작하도록,
    import 실패 시 이 파일 위치(<root>/alembic_db/alembic/versions/)에서
    저장소 루트를 역산해 sys.path 에 넣고 재시도한다."""
    try:
        from aot.databases.geo_integrity_ddl import (
            DEVICE_LINK_TABLES, TIER1_STATEMENTS)
    except ModuleNotFoundError:
        import os
        import sys
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        if root not in sys.path:
            sys.path.insert(0, root)
        from aot.databases.geo_integrity_ddl import (
            DEVICE_LINK_TABLES, TIER1_STATEMENTS)
    return DEVICE_LINK_TABLES, TIER1_STATEMENTS


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'geo_shape' not in insp.get_table_names():
        logger.info('P6-22: geo_shape 없음 — 건너뜀.')
        return

    link_tables, tier1 = _ddl_module()

    # ── 0) 삭제 행 백업 테이블 ─────────────────────────────────────────
    bind.execute(sa.text(
        'CREATE TABLE IF NOT EXISTS %s ('
        ' shape_id INTEGER, row_json TEXT, reason TEXT,'
        " created_at TEXT DEFAULT (datetime('now')))" % BACKUP_TABLE))

    # ── 1) 마커 중복 정리 ──────────────────────────────────────────────
    cols = [c['name'] for c in insp.get_columns('geo_shape')]
    rows = bind.execute(sa.text(
        "SELECT * FROM geo_shape "
        "WHERE type='aot_device' AND device_id IS NOT NULL")).mappings().all()

    groups = {}
    for r in rows:
        key = (r['geo_id'], r['device_id'], r['channel_id'] or '0')
        groups.setdefault(key, []).append(r)

    # 참조 집합: 삭제 판단이 아니라 '유지 행 선택'과 '재지정'에 쓴다.
    referenced = set()
    for t in link_tables:
        if t not in insp.get_table_names():
            continue
        if 'map_overlay_id' not in [c['name'] for c in insp.get_columns(t)]:
            continue
        for (oid,) in bind.execute(sa.text(
                'SELECT DISTINCT map_overlay_id FROM "%s" '
                'WHERE map_overlay_id IS NOT NULL' % t)):
            referenced.add(oid)
    for (pid,) in bind.execute(sa.text(
            'SELECT DISTINCT parent_id FROM geo_shape '
            'WHERE parent_id IS NOT NULL')):
        referenced.add(pid)

    removed = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members = sorted(
            members,
            key=lambda r: (r['id'] in referenced,
                           str(r['updated_at'] or ''), r['id']))
        keeper, losers = members[-1], members[:-1]
        for loser in losers:
            for t in link_tables:
                if t not in insp.get_table_names():
                    continue
                if 'map_overlay_id' not in [c['name']
                                            for c in insp.get_columns(t)]:
                    continue
                bind.execute(sa.text(
                    'UPDATE "%s" SET map_overlay_id=:k '
                    'WHERE map_overlay_id=:l' % t),
                    {'k': keeper['id'], 'l': loser['id']})
            bind.execute(sa.text(
                'UPDATE geo_shape SET parent_id=:k WHERE parent_id=:l'),
                {'k': keeper['id'], 'l': loser['id']})
            bind.execute(sa.text(
                'INSERT INTO %s (shape_id, row_json, reason) '
                'VALUES (:i, :j, :r)' % BACKUP_TABLE),
                {'i': loser['id'],
                 'j': json.dumps({c: (loser[c] if not isinstance(
                     loser[c], (bytes, bytearray)) else None)
                     for c in cols}, ensure_ascii=False, default=str),
                 'r': 'dup marker %s keep=%s' % (key, keeper['id'])})
            bind.execute(sa.text('DELETE FROM geo_shape WHERE id=:i'),
                         {'i': loser['id']})
            removed += 1
            logger.info('P6-22: 중복 마커 정리 id=%s (유지 id=%s, key=%s)',
                        loser['id'], keeper['id'], key)
    logger.info('P6-22: 마커 중복 %d건 정리 (백업: %s).',
                removed, BACKUP_TABLE)

    # ── 1.5) 역사적 dangling 참조 NULL 정리 ────────────────────────────
    # p6_21 은 지도에 마커가 있는 장치만 좌표로 재연결했다(추측 금지 원칙).
    # 마커가 없어 남은 dangling 은 여기서 NULL 로 확정한다. 이유: SQLite 는
    # 삭제된 rowid 를 재사용하므로, 죽은 id 를 품고 있으면 미래에 생성되는
    # 무관한 도형이 그 id 를 받아 장치가 엉뚱한 zone 에 재부착될 수 있다.
    # NULL 은 현재 관측 동작(어차피 해석 안 됨)과 동일하면서 그 사고를 막는다.
    live_shape_ids = {r[0] for r in bind.execute(
        sa.text('SELECT id FROM geo_shape'))}
    live_map_ids = {r[0] for r in bind.execute(
        sa.text('SELECT unique_id FROM geo_map'))}
    cleared = 0
    for t in link_tables:
        if t not in insp.get_table_names():
            continue
        tcols = [c['name'] for c in insp.get_columns(t)]
        if 'map_overlay_id' in tcols:
            for row in bind.execute(sa.text(
                    'SELECT unique_id, map_overlay_id FROM "%s" '
                    'WHERE map_overlay_id IS NOT NULL' % t)):
                if row[1] not in live_shape_ids:
                    bind.execute(sa.text(
                        'UPDATE "%s" SET map_overlay_id=NULL '
                        'WHERE unique_id=:u' % t), {'u': row[0]})
                    cleared += 1
                    logger.info('P6-22: dangling map_overlay_id 해제 '
                                '%s.%s (죽은 도형 id=%s)', t, row[0], row[1])
        if 'map_config_id' in tcols:
            for row in bind.execute(sa.text(
                    'SELECT unique_id, map_config_id FROM "%s" '
                    'WHERE map_config_id IS NOT NULL' % t)):
                if row[1] not in live_map_ids:
                    bind.execute(sa.text(
                        'UPDATE "%s" SET map_config_id=NULL '
                        'WHERE unique_id=:u' % t), {'u': row[0]})
                    cleared += 1
                    logger.info('P6-22: dangling map_config_id 해제 '
                                '%s.%s (죽은 지도 %s)', t, row[0], row[1])
    logger.info('P6-22: 역사적 dangling 참조 %d건 NULL 처리.', cleared)

    # ── 2) 채널 정규화 ─────────────────────────────────────────────────
    res = bind.execute(sa.text(
        "UPDATE geo_shape SET channel_id='0' "
        "WHERE type='aot_device' AND channel_id IS NULL"))
    logger.info('P6-22: channel_id NULL→0 정규화 %s건.', res.rowcount)

    # ── 3) Tier-1 DDL 적용 ─────────────────────────────────────────────
    for stmt in tier1:
        bind.exec_driver_sql(stmt)
    logger.info('P6-22: Tier-1 트리거·인덱스 적용 완료 — '
                '이후 위반은 GEO-I* 태그로 즉시 거부된다.')


def downgrade():
    """트리거·인덱스만 제거한다. 정리된 중복/정규화는 되돌리지 않는다 —
    원본 행이 필요하면 geo_integrity_p6_22_backup 을 쓴다."""
    bind = op.get_bind()
    _, tier1 = _ddl_module()
    for stmt in tier1:
        if stmt.startswith('DROP '):
            bind.exec_driver_sql(stmt)
