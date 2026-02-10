"""Fix schema: Add map_id to dependency, drop level_id from overlay

Revision ID: 718f314963be
Revises: 718f314963bd
Create Date: 2025-12-16 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '718f314963be'
down_revision = '718f314963bd'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    
    # 1. Add map_id to map_dependency
    # Check if column exists first to be safe (sqlite limitation on add column if exists)
    # Actually add_column usually fine.
    try:
        with op.batch_alter_table('map_dependency', schema=None) as batch_op:
            batch_op.add_column(sa.Column('map_id', sa.String(length=64), nullable=False, server_default='default_map'))
            batch_op.create_index(batch_op.f('ix_map_dependency_map_id'), ['map_id'], unique=False)
    except Exception:
        pass # Column might exist if run previously
        
    # 2. Drop level_id from map_overlay
    # Since sqlite doesn't support drop column easily in older versions, batch_alter_table handles it by copy.
    with op.batch_alter_table('map_overlay', schema=None) as batch_op:
        batch_op.drop_index('ix_map_overlay_level_id')
        batch_op.drop_column('level_id')

def downgrade():
    # Helper to restore
    with op.batch_alter_table('map_overlay', schema=None) as batch_op:
        batch_op.add_column(sa.Column('level_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_map_overlay_level_id', ['level_id'], unique=False)

    with op.batch_alter_table('map_dependency', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_map_dependency_map_id'))
        batch_op.drop_column('map_id')
