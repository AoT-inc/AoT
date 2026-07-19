"""add_tier_and_context_state_to_notes

Revision ID: 7a3b8c2d9e4f
Revises: d4e5f6a7b8c9
Create Date: 2026-04-29 19:35:00.000000

Description: Adds tier and context_state columns to notes table.
             - tier: adaptive document storage tier (1=hot/summary, 2=warm/standard, 3=cold/archive)
             - context_state: system_generated or human_written
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '7a3b8c2d9e4f'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    
    tables = insp.get_table_names()
    
    if 'notes' in tables:
        columns = [c['name'] for c in insp.get_columns('notes')]
        
        with op.batch_alter_table('notes', schema=None) as batch_op:
            if 'tier' not in columns:
                batch_op.add_column(sa.Column('tier', sa.Integer(), nullable=False, server_default='2'))
                batch_op.create_index(batch_op.f('ix_notes_tier'), ['tier'], unique=False)
            
            if 'context_state' not in columns:
                batch_op.add_column(sa.Column('context_state', sa.String(20), nullable=True, server_default='system_generated'))


def downgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    
    tables = insp.get_table_names()
    
    if 'notes' in tables:
        columns = [c['name'] for c in insp.get_columns('notes')]
        
        with op.batch_alter_table('notes', schema=None) as batch_op:
            if 'context_state' in columns:
                batch_op.drop_column('context_state')
            
            if 'tier' in columns:
                batch_op.drop_index(batch_op.f('ix_notes_tier'))
                batch_op.drop_column('tier')
