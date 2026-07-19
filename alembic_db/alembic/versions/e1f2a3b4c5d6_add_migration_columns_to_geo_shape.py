"""Add schema migration tracking columns to geo_shape

Revision ID: e1f2a3b4c5d6
Revises: b3c4d5e6f7a8
Create Date: 2026-05-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e1f2a3b4c5d6'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('geo_shape', schema=None) as batch_op:
        batch_op.add_column(sa.Column('schema_version', sa.Integer(), nullable=True, server_default='2'))
        batch_op.add_column(sa.Column('original_data', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('migrated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('migrated_from_version', sa.Integer(), nullable=True))

    with op.batch_alter_table('geo_map', schema=None) as batch_op:
        batch_op.add_column(sa.Column('schema_version', sa.Integer(), nullable=True, server_default='2'))


def downgrade():
    with op.batch_alter_table('geo_map', schema=None) as batch_op:
        batch_op.drop_column('schema_version')

    with op.batch_alter_table('geo_shape', schema=None) as batch_op:
        batch_op.drop_column('migrated_from_version')
        batch_op.drop_column('migrated_at')
        batch_op.drop_column('original_data')
        batch_op.drop_column('schema_version')
