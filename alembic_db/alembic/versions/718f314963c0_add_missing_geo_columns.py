"""Add missing geo columns to various tables

Revision ID: 718f314963c0
Revises: 718f314963bf
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '718f314963c0'
down_revision = '718f314963bf'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    
    # 1. Add map_config_id (String 36)
    tables = insp.get_table_names()
    tables_map_config = ['pid', 'function', 'conditional', 'trigger']
    for table in tables_map_config:
        if table in tables:
            columns = [c['name'] for c in insp.get_columns(table)]
            if 'map_config_id' not in columns:
                with op.batch_alter_table(table, schema=None) as batch_op:
                    batch_op.add_column(sa.Column('map_config_id', sa.String(length=36), nullable=True))

    # 2. Add map_overlay_id (Integer)
    tables_map_overlay = ['pid', 'input', 'output', 'function', 'conditional', 'trigger', 'custom_controller']
    for table in tables_map_overlay:
        if table in tables:
            columns = [c['name'] for c in insp.get_columns(table)]
            if 'map_overlay_id' not in columns:
                with op.batch_alter_table(table, schema=None) as batch_op:
                    batch_op.add_column(sa.Column('map_overlay_id', sa.Integer(), nullable=True))

def downgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)

    # 1. Drop map_overlay_id
    tables_map_overlay = ['pid', 'input', 'output', 'function', 'conditional', 'trigger', 'custom_controller']
    for table in tables_map_overlay:
        columns = [c['name'] for c in insp.get_columns(table)]
        if 'map_overlay_id' in columns:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.drop_column('map_overlay_id')

    # 2. Drop map_config_id
    tables_map_config = ['pid', 'function', 'conditional', 'trigger']
    for table in tables_map_config:
        columns = [c['name'] for c in insp.get_columns(table)]
        if 'map_config_id' in columns:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.drop_column('map_config_id')
