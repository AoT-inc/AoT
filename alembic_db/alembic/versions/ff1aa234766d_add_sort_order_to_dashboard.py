"""add sort_order to dashboard

Revision ID: ff1aa234766d
Revises: 5966b3569c89
Create Date: 2025-09-08 09:06:05.248088

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic_db.alembic_post_utils import write_revision_post_alembic

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ff1aa234766d'
down_revision = '5966b3569c89'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('dashboard') as batch_op:
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), nullable=True))
        batch_op.create_index('ix_dashboard_sort_order', ['sort_order'], unique=False)

    op.execute('UPDATE dashboard SET sort_order = id')

def downgrade():
    with op.batch_alter_table('dashboard') as batch_op:
        batch_op.drop_index('ix_dashboard_sort_order')
        batch_op.drop_column('sort_order')

