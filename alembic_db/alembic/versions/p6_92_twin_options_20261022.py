# coding=utf-8
"""P6-92: 디지털트윈(실험) 설정 옵션 — misc.twin_ignore_profile / twin_auto_forecast.

설정 > 디지털트윈(settings/twin) 페이지의 두 옵션.

  twin_ignore_profile  HARDWARE_PROFILE=LOW 잠금만 건너뛴다. 기본 꺼짐. 환경변수
                       AOT_TWIN_IGNORE_PROFILE 과 같은 효과의 화면 옵션이다(파이 모델·기기
                       메모리 잠금은 그대로).
  twin_auto_forecast   대지에 트윈을 켤 때 가까운 예보 입력이 없으면 새로 만든다. 기본 켜짐
                       (기존 행도 켜짐으로 채운다 — 트윈을 쓰는 사람이 따로 만들 일이 없게).

재실행 안전: 이미 있는 칸은 건너뛴다. downgrade 는 두 칸을 지운다.

Revision ID: p6_92_twin_options_20261022
Revises: p6_91_twin_config_20261021
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_92_twin_options_20261022'
down_revision = 'p6_91_twin_config_20261021'
branch_labels = None
depends_on = None

TABLE = 'misc'


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    have = _columns(TABLE)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        if 'twin_ignore_profile' not in have:
            batch_op.add_column(sa.Column(
                'twin_ignore_profile', sa.Boolean(), nullable=True, server_default=sa.text("0")))
        if 'twin_auto_forecast' not in have:
            batch_op.add_column(sa.Column(
                'twin_auto_forecast', sa.Boolean(), nullable=True, server_default=sa.text("1")))
    op.get_bind().execute(sa.text(f"UPDATE {TABLE} SET twin_auto_forecast = 1 WHERE twin_auto_forecast IS NULL"))
    op.get_bind().execute(sa.text(f"UPDATE {TABLE} SET twin_ignore_profile = 0 WHERE twin_ignore_profile IS NULL"))


def downgrade():
    have = _columns(TABLE)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for col in ('twin_auto_forecast', 'twin_ignore_profile'):
            if col in have:
                batch_op.drop_column(col)
