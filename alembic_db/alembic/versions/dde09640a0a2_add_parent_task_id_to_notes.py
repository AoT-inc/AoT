"""Add parent_task_id to notes

Revision ID: dde09640a0a2
Revises: b8b3c27f6082
Create Date: 2026-02-22 13:41:16.485933

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

# from alembic_db.alembic_post_utils import write_revision_post_alembic

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dde09640a0a2'
down_revision = 'b8b3c27f6082'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('notes') as batch_op:
        batch_op.add_column(sa.Column('parent_task_id', sa.String(36)))
        batch_op.create_index('ix_notes_parent_task_id', ['parent_task_id'])


def downgrade():
    with op.batch_alter_table('notes') as batch_op:
        batch_op.drop_index('ix_notes_parent_task_id')
        batch_op.drop_column('parent_task_id')

