# coding=utf-8
"""P5-15: Add timer_weekday column to trigger table.

Stores comma-separated active day-of-week values (0=Mon ... 6=Sun).
NULL / empty string means all days are active (backward compatible default).

Revision ID: p5_15_add_trigger_weekday
Revises: p5_14_merge_counter_into_timer
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_15_add_trigger_weekday'
down_revision = 'p5_14_merge_counter_into_timer'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trigger') as batch_op:
        batch_op.add_column(
            sa.Column('timer_weekday', sa.Text(), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('trigger') as batch_op:
        batch_op.drop_column('timer_weekday')
