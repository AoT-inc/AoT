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
    tables = insp.get_table_names()
    if 'map_dependency' in tables:
        columns = [c['name'] for c in insp.get_columns('map_dependency')]
        indexes = [i['name'] for i in insp.get_indexes('map_dependency')]
        with op.batch_alter_table('map_dependency', schema=None) as batch_op:
            if 'map_id' not in columns:
                batch_op.add_column(sa.Column('map_id', sa.String(length=64), nullable=False, server_default='default_map'))
            if 'ix_map_dependency_map_id' not in indexes:
                batch_op.create_index(batch_op.f('ix_map_dependency_map_id'), ['map_id'], unique=False)
        
    # 2. Drop level_id from map_overlay
    if 'map_overlay' in tables:
        columns = [c['name'] for c in insp.get_columns('map_overlay')]
        indexes = [i['name'] for i in insp.get_indexes('map_overlay')]
        with op.batch_alter_table('map_overlay', schema=None) as batch_op:
            if 'ix_map_overlay_level_id' in indexes:
                batch_op.drop_index('ix_map_overlay_level_id')
            if 'level_id' in columns:
                batch_op.drop_column('level_id')

def downgrade():
    # Helper to restore
    with op.batch_alter_table('map_overlay', schema=None) as batch_op:
        batch_op.add_column(sa.Column('level_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_map_overlay_level_id', ['level_id'], unique=False)

    with op.batch_alter_table('map_dependency', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_map_dependency_map_id'))
        batch_op.drop_column('map_id')
