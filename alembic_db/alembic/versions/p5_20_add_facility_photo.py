# coding=utf-8
"""P5-20: Add photo_path column to geo_facility table.

시설 대표사진의 상대경로(uploads/facility_photos 기준)를 저장한다.
맵 팝업 [현황] 탭이 /api/aot/facility/<uuid>/info 로 읽고,
/api/aot/facility/<uuid>/photo 업로드로 갱신한다.
NULL 이면 사진 미등록.

Revision ID: p5_20_add_facility_photo
Revises: p5_19_add_runtime_summary
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_20_add_facility_photo'
down_revision = 'p5_19_add_runtime_summary'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('photo_path', sa.String(255), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('photo_path')
