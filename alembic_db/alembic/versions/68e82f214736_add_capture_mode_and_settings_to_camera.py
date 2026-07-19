"""Add capture_mode and capture_settings to camera table

Revision ID: 68e82f214736
Revises: 68e82f214735
Create Date: 2026-03-07

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '68e82f214736'
down_revision = '68e82f214735'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    tables = insp.get_table_names()

    if 'camera' in tables:
        columns = [c['name'] for c in insp.get_columns('camera')]
        with op.batch_alter_table('camera', schema=None) as batch_op:
            if 'capture_mode' not in columns:
                batch_op.add_column(
                    sa.Column('capture_mode', sa.Text(), nullable=True, server_default='snapshot'))
            if 'capture_settings' not in columns:
                batch_op.add_column(
                    sa.Column('capture_settings', sa.JSON(), nullable=True, server_default='{}'))


def downgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)

    if 'camera' in insp.get_table_names():
        columns = [c['name'] for c in insp.get_columns('camera')]
        with op.batch_alter_table('camera', schema=None) as batch_op:
            for col in ['capture_mode', 'capture_settings']:
                if col in columns:
                    batch_op.drop_column(col)
