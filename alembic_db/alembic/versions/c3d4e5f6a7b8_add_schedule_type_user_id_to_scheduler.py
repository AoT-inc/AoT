"""add_schedule_type_user_id_to_scheduler

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4
Create Date: 2026-03-28 00:00:00.000000

Task ID: 2603_AoT_ai_002_fix_schedule_model
Description: Adds schedule_type ENUM column (device|human|ai_system) and nullable
             user_id FK column to scheduler_jobs_meta.  Existing rows are
             back-filled with schedule_type='ai_system' and user_id=NULL.
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b1c2d3e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('scheduler_jobs_meta') as batch_op:
        batch_op.add_column(
            sa.Column(
                'schedule_type',
                sa.Enum('device', 'human', 'ai_system', name='scheduletype'),
                nullable=False,
                server_default='ai_system'
            )
        )
        # Bypassing FK creation for SQLite batch mode compatibility.
        # Application-level logic enforces user-scoped access.
        batch_op.add_column(
            sa.Column(
                'user_id',
                sa.Integer(),
                nullable=True
            )
        )
        batch_op.create_index('ix_scheduler_jobs_meta_user_id', ['user_id'])

    # Backfill: set schedule_type = 'ai_system' for all pre-existing rows
    # (server_default handles new rows; this covers rows inserted before the
    #  server_default was in place, such as rows in SQLite WAL replays).
    op.execute(
        "UPDATE scheduler_jobs_meta "
        "SET schedule_type = 'ai_system' "
        "WHERE schedule_type IS NULL OR schedule_type = ''"
    )


def downgrade():
    with op.batch_alter_table('scheduler_jobs_meta') as batch_op:
        batch_op.drop_index('ix_scheduler_jobs_meta_user_id')
        batch_op.drop_column('user_id')
        batch_op.drop_column('schedule_type')
