# coding=utf-8
"""P7-03: 지도 즐겨찾기 표 (현재 위치 시트의 '즐겨찾기').

  geo_favorite : 사용자가 담아 둔 장소(이름·좌표·주소·순서) — 서버(농장) 단위, 개인용(shared=0)은 담은 사람만

재실행 안전(이미 있으면 건너뜀). downgrade 는 표를 지운다(즐겨찾기만 사라지고 지도·노트는 그대로다).

Revision ID: p7_03_geo_favorite_20261104
Revises: p7_02_drop_irrigation_design_20261102
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = 'p7_03_geo_favorite_20261104'
down_revision = 'p7_02_drop_irrigation_design_20261102'
branch_labels = None
depends_on = None


def upgrade():
    if 'geo_favorite' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        'geo_favorite',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('address', sa.String(240), nullable=True),
        sa.Column('created_by', sa.String(64), nullable=True),
        sa.Column('shared', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Float(), nullable=False))


def downgrade():
    if 'geo_favorite' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('geo_favorite')
