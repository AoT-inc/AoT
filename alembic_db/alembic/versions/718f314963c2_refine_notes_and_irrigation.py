"""Refine notes and irrigation tables

Revision ID: 718f314963c2
Revises: 718f314963c1
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '718f314963c2'
down_revision = '718f314963c1'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    
    # 1. notes table: category, priority, is_archived
    tables = insp.get_table_names()
    if 'notes' in tables:
        columns_notes = [c['name'] for c in insp.get_columns('notes')]
        with op.batch_alter_table('notes', schema=None) as batch_op:
            if 'category' not in columns_notes:
                batch_op.add_column(sa.Column('category', sa.String(64), nullable=True, server_default='general'))
            if 'priority' not in columns_notes:
                batch_op.add_column(sa.Column('priority', sa.Integer(), nullable=True, server_default='0'))
            if 'is_archived' not in columns_notes:
                batch_op.add_column(sa.Column('is_archived', sa.Boolean(), nullable=True, server_default='0'))

    # 2. irrigation_design table: status, last_run_at, total_volume_applied, function_id
    if 'irrigation_design' in tables:
        columns_irrigation = [c['name'] for c in insp.get_columns('irrigation_design')]
        with op.batch_alter_table('irrigation_design', schema=None) as batch_op:
            if 'status' not in columns_irrigation:
                batch_op.add_column(sa.Column('status', sa.String(32), nullable=True, server_default='idle'))
            if 'last_run_at' not in columns_irrigation:
                batch_op.add_column(sa.Column('last_run_at', sa.DateTime(), nullable=True))
            if 'total_volume_applied' not in columns_irrigation:
                batch_op.add_column(sa.Column('total_volume_applied', sa.Float(), nullable=True, server_default='0.0'))
            if 'function_id' not in columns_irrigation:
                batch_op.add_column(sa.Column('function_id', sa.String(36), nullable=True))

def downgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)

    # 1. notes table
    columns_notes = [c['name'] for c in insp.get_columns('notes')]
    with op.batch_alter_table('notes', schema=None) as batch_op:
        for name in ['category', 'priority', 'is_archived']:
            if name in columns_notes:
                batch_op.drop_column(name)

    # 2. irrigation_design table
    columns_irrigation = [c['name'] for c in insp.get_columns('irrigation_design')]
    with op.batch_alter_table('irrigation_design', schema=None) as batch_op:
        for name in ['status', 'last_run_at', 'total_volume_applied', 'function_id']:
            if name in columns_irrigation:
                batch_op.drop_column(name)
