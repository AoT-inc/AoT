# coding=utf-8
"""P3-5: Add points_json column to method_data for DailyMultiPointMethod.

Revision ID: p3_5_points_json_method_data
Revises: p2_5_function_runtime_state
Create Date: 2026-05-16
"""

revision = 'p3_5_points_json_method_data'
down_revision = 'p2_5_function_runtime_state'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('method_data') as batch_op:
        batch_op.add_column(
            sa.Column('points_json', sa.Text, nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('method_data') as batch_op:
        batch_op.drop_column('points_json')
