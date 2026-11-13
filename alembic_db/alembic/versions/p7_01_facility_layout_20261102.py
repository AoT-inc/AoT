# coding=utf-8
"""P7-01: 시설 모형 칸 `geo_facility.layout` (시설 모형 확장 F2).

  geo_facility.layout : 층·덩어리·공간 모형(JSON, 스키마는 `aot_flask/geo/facility_layout.py`)

비어 있으면(NULL) 지금 경로를 그대로 쓴다. **기존 행은 변환하지 않는다** — 이 마이그레이션은
칸을 더할 뿐 아무것도 채우지 않는다. 재실행 안전(이미 있으면 건너뜀).
downgrade 는 칸을 지운다(layout 만 사라지고 시설의 나머지 값은 그대로다).

Revision ID: p7_01_facility_layout_20261102
Revises: p7_00_target_alias_20261028
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = 'p7_01_facility_layout_20261102'
down_revision = 'p7_00_target_alias_20261028'
branch_labels = None
depends_on = None


def _has_column(table, column):
    insp = sa.inspect(op.get_bind())
    if table not in set(insp.get_table_names()):
        return False
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade():
    if not _has_column('geo_facility', 'layout'):
        op.add_column('geo_facility', sa.Column('layout', sa.JSON(), nullable=True))


def downgrade():
    # SQLite 는 3.35+ 에서만 DROP COLUMN 지원 — batch 로 재생성.
    if _has_column('geo_facility', 'layout'):
        with op.batch_alter_table('geo_facility') as batch:
            batch.drop_column('layout')
