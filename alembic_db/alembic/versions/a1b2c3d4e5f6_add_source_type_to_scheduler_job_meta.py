"""Add source_type to scheduler_jobs_meta

Revision ID: a1b2c3d4e5f6
Revises: 115ed7ac7805
Create Date: 2026-02-22 12:00:00.000000

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '115ed7ac7805'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('scheduler_jobs_meta') as batch_op:
        batch_op.add_column(
            sa.Column('source_type', sa.String(20), server_default='scheduler')
        )
        batch_op.create_index('ix_scheduler_jobs_meta_source_type', ['source_type'])


def downgrade():
    with op.batch_alter_table('scheduler_jobs_meta') as batch_op:
        batch_op.drop_index('ix_scheduler_jobs_meta_source_type')
        batch_op.drop_column('source_type')
