# coding=utf-8
"""P6-05: 타임존 상속 계층 — tz_source / 도형 tz 물질화 컬럼.

통합 시간 관리 재설계 Phase 3 (docs/design/timezone-management.md §4·§10).

추가:
  - 장치 7종(input/output/function/conditional/trigger/pid/custom_controller)에
    tz_source 컬럼: 'explicit' | 'inherited' | 'coords'. 물질화된 timezone 값이
    수동 override(pinned)인지, 소속 도형에서 상속한 캐시인지, 좌표에서 산출한
    캐시인지 구분 — 배치 갱신이 explicit 핀을 덮어쓰지 않게 한다.
  - geo_shape: timezone(물질화 IANA tz) + tz_source + tz_boundary(경계 걸침).
    도형 트리가 tz 권위이며, 장치는 device_id 로 연결된 도형에서 상속한다.
  - geo_facility: tz_source (timezone 컬럼은 기존 존재).

전부 nullable/기본값이라 기존 행에 무해. 신규 설치는 db.create_all()이 스키마를
만들므로 이 upgrade()는 기존 설치 마이그레이션용.

Revision ID: p6_05_tz_inheritance_20260721
Revises: p6_04_user_google_signup_20260721
Create Date: 2026-07-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_05_tz_inheritance_20260721'
down_revision = 'p6_04_user_google_signup_20260721'
branch_labels = None
depends_on = None


_DEVICE_TABLES = (
    'input', 'output', 'function', 'conditional',
    'trigger', 'pid', 'custom_controller',
)


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    # 장치 7종 tz_source
    for tbl in _DEVICE_TABLES:
        if _has_table(tbl) and not _has_column(tbl, 'tz_source'):
            op.add_column(tbl, sa.Column('tz_source', sa.String(length=16), nullable=True))

    # geo_shape: timezone / tz_source / tz_boundary
    if _has_table('geo_shape'):
        if not _has_column('geo_shape', 'timezone'):
            op.add_column('geo_shape', sa.Column('timezone', sa.String(length=64), nullable=True))
        if not _has_column('geo_shape', 'tz_source'):
            op.add_column('geo_shape', sa.Column('tz_source', sa.String(length=16), nullable=True))
        if not _has_column('geo_shape', 'tz_boundary'):
            op.add_column('geo_shape', sa.Column(
                'tz_boundary', sa.Boolean(), nullable=True, server_default=sa.false()))

    # geo_facility: tz_source
    if _has_table('geo_facility') and not _has_column('geo_facility', 'tz_source'):
        op.add_column('geo_facility', sa.Column('tz_source', sa.String(length=16), nullable=True))


def downgrade():
    # SQLite 는 3.35+ 에서만 DROP COLUMN 지원 — batch 로 재생성.
    for tbl in _DEVICE_TABLES:
        if _has_table(tbl) and _has_column(tbl, 'tz_source'):
            with op.batch_alter_table(tbl) as batch:
                batch.drop_column('tz_source')
    if _has_table('geo_shape'):
        with op.batch_alter_table('geo_shape') as batch:
            for col in ('tz_boundary', 'tz_source', 'timezone'):
                if _has_column('geo_shape', col):
                    batch.drop_column(col)
    if _has_table('geo_facility') and _has_column('geo_facility', 'tz_source'):
        with op.batch_alter_table('geo_facility') as batch:
            batch.drop_column('tz_source')
