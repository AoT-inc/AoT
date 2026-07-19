# coding=utf-8
"""P5-18: Add timer_schedule column to trigger table.

Stores the weekly schedule as a JSON blob (weekly_schedule schema v1).
NULL means the daemon falls back to legacy columns (timer_start_time,
timer_end_time, timer_weekday, period) via from_legacy().

Revision ID: p5_18_add_trigger_schedule
Revises: p5_17_add_chirpstack_connection_to_misc
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_18_add_trigger_schedule'
down_revision = 'p5_17_add_chirpstack_connection_to_misc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trigger') as batch_op:
        batch_op.add_column(
            sa.Column('timer_schedule', sa.Text(), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('trigger') as batch_op:
        batch_op.drop_column('timer_schedule')
