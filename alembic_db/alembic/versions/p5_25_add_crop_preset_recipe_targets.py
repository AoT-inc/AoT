# coding=utf-8
"""P5-25: Add vpd_target/co2_target/temp_min/temp_max to function_crop_preset.

작물 프리셋을 전체 환경 레시피로 확장 — env_coordinator 선택·저장 시 VPD/CO2/온도
목표 옵션을 자동 채우기 위한 권장값. 런타임은 photosynthesis.CROP_PRESETS(파이썬
사본)를 쓰고, 이 컬럼은 UI/시드 동기화용.

Revision ID: p5_25_add_crop_preset_recipe_targets
Revises: p5_24_add_crop_preset_dli_gdd
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_25_add_crop_preset_recipe_targets'
down_revision = 'p5_24_add_crop_preset_dli_gdd'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('function_crop_preset') as batch_op:
        batch_op.add_column(sa.Column('vpd_target', sa.Float(), nullable=False, server_default='0.0'))
        batch_op.add_column(sa.Column('co2_target', sa.Float(), nullable=False, server_default='0.0'))
        batch_op.add_column(sa.Column('temp_min', sa.Float(), nullable=False, server_default='0.0'))
        batch_op.add_column(sa.Column('temp_max', sa.Float(), nullable=False, server_default='0.0'))


def downgrade():
    with op.batch_alter_table('function_crop_preset') as batch_op:
        batch_op.drop_column('temp_max')
        batch_op.drop_column('temp_min')
        batch_op.drop_column('co2_target')
        batch_op.drop_column('vpd_target')
