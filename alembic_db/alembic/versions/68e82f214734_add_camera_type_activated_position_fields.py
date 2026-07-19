"""Add camera_type, is_activated, position_y to camera table

Revision ID: 68e82f214734
Revises: 68e82f214733
Create Date: 2026-03-06

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '68e82f214734'
down_revision = '68e82f214733'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    tables = insp.get_table_names()

    if 'camera' in tables:
        columns = [c['name'] for c in insp.get_columns('camera')]
        with op.batch_alter_table('camera', schema=None) as batch_op:
            if 'camera_type' not in columns:
                batch_op.add_column(
                    sa.Column('camera_type', sa.Text(), nullable=False, server_default='usb'))
            if 'is_activated' not in columns:
                batch_op.add_column(
                    sa.Column('is_activated', sa.Boolean(), nullable=True, server_default='0'))
            if 'position_y' not in columns:
                batch_op.add_column(
                    sa.Column('position_y', sa.Integer(), nullable=True, server_default='0'))


def downgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)

    if 'camera' in insp.get_table_names():
        columns = [c['name'] for c in insp.get_columns('camera')]
        with op.batch_alter_table('camera', schema=None) as batch_op:
            for col in ['camera_type', 'is_activated', 'position_y']:
                if col in columns:
                    batch_op.drop_column(col)
