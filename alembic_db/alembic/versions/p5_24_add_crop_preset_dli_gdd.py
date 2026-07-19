# coding=utf-8
"""P5-24: Add dli_target and gdd_daily to function_crop_preset.

작물 프리셋에 DLI(일적산광량, mol/m²/day)·GDD(일일 적산온도, °C·day/day) 권장값을
보관해 누적 추적기(cumulative_tracker) 목표 기본값으로 사용한다. 런타임은
photosynthesis.CROP_PRESETS(파이썬 사본)를 쓰고, 이 컬럼은 UI/시드 동기화용.

Revision ID: p5_24_add_crop_preset_dli_gdd
Revises: p5_23_add_runtime_snapshot
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_24_add_crop_preset_dli_gdd'
down_revision = 'p5_23_add_runtime_snapshot'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('function_crop_preset') as batch_op:
        batch_op.add_column(
            sa.Column('dli_target', sa.Float(), nullable=False, server_default='0.0')
        )
        batch_op.add_column(
            sa.Column('gdd_daily', sa.Float(), nullable=False, server_default='0.0')
        )


def downgrade():
    with op.batch_alter_table('function_crop_preset') as batch_op:
        batch_op.drop_column('gdd_daily')
        batch_op.drop_column('dli_target')
