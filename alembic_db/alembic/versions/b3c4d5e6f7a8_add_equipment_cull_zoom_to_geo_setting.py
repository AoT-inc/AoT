"""add equipment_cull_zoom to geo_setting

Revision ID: b3c4d5e6f7a8
Revises: 7a3b8c2d9e4f, c9e7b3a2f1d8
Create Date: 2026-05-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = ('7a3b8c2d9e4f', 'c9e7b3a2f1d8')
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = sa.inspect(connection).get_columns('geo_setting')
    if not any(c['name'] == 'equipment_cull_zoom' for c in columns):
        op.add_column('geo_setting', sa.Column('equipment_cull_zoom', sa.Integer(), nullable=True, server_default='15'))


def downgrade():
    op.drop_column('geo_setting', 'equipment_cull_zoom')
