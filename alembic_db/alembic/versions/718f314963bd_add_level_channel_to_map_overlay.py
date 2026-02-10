"""Add level_id and channel_id to map_overlay

Revision ID: 718f314963bd
Revises: 718f314963bc
Create Date: 2025-12-16 14:48:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '718f314963bd'
down_revision = '718f314963bc'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('map_overlay', schema=None) as batch_op:
        batch_op.add_column(sa.Column('level_id', sa.Integer(), nullable=True, server_default='3'))
        batch_op.add_column(sa.Column('channel_id', sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f('ix_map_overlay_level_id'), ['level_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_map_overlay_channel_id'), ['channel_id'], unique=False)

def downgrade():
    with op.batch_alter_table('map_overlay', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_map_overlay_channel_id'))
        batch_op.drop_index(batch_op.f('ix_map_overlay_level_id'))
        batch_op.drop_column('channel_id')
        batch_op.drop_column('level_id')
