"""add_management_fields_to_scheduler

Revision ID: e7fbf4818024
Revises: 3bfac659ac37
Create Date: 2026-03-06 10:25:00.000000

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

# from alembic_db.alembic_post_utils import write_revision_post_alembic

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT


# revision identifiers, used by Alembic.
revision = 'e7fbf4818024'
down_revision = '3bfac659ac37'
branch_labels = None
depends_on = None


def upgrade():
    write_revision_post_alembic(revision)
    
    with op.batch_alter_table('scheduler_jobs_meta') as batch_op:
        batch_op.add_column(sa.Column('is_editable', sa.Boolean(), nullable=True, server_default=sa.text('1')))
        batch_op.add_column(sa.Column('is_deletable', sa.Boolean(), nullable=True, server_default=sa.text('1')))
        batch_op.add_column(sa.Column('edit_count', sa.Integer(), nullable=True, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('last_edited_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('last_edited_by', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('deletion_reason', sa.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True))


def downgrade():
    with op.batch_alter_table('scheduler_jobs_meta') as batch_op:
        batch_op.drop_column('deletion_reason')
        batch_op.drop_column('last_edited_by')
        batch_op.drop_column('last_edited_at')
        batch_op.drop_column('edit_count')
        batch_op.drop_column('is_deletable')
        batch_op.drop_column('is_editable')
