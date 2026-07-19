"""Add ai_library_sync_log table for raw data staging

Revision ID: b1c2d3e4
Revises: a9b8c7d6e5f4
Create Date: 2026-03-27 00:00:00.000000

Changes:
- Create ai_library_sync_log table (raw payload audit trail for AIContextSource syncs)
  Resolves GAP-04 from data pipeline audit (no raw data staging).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = 'b1c2d3e4'
down_revision = 'a9b8c7d6e5f4'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    if 'ai_library_sync_log' not in inspector.get_table_names():
        op.create_table(
            'ai_library_sync_log',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('log_id', sa.String(36), nullable=False),
            sa.Column('source_id', sa.String(36), nullable=False),
            sa.Column('facility_id', sa.String(36), nullable=False),
            sa.Column('synced_at', sa.DateTime(), nullable=True),
            sa.Column('source_type', sa.String(30), nullable=True),
            sa.Column('preset_key', sa.String(50), nullable=True),
            sa.Column('raw_payload', sa.Text(), nullable=True),
            sa.Column('records_written', sa.Integer(), nullable=True),
            sa.Column('sync_status', sa.String(20), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('log_id'),
        )
        op.create_index('ix_ai_library_sync_log_source_id',
                        'ai_library_sync_log', ['source_id'], unique=False)
        op.create_index('ix_ai_library_sync_log_facility_id',
                        'ai_library_sync_log', ['facility_id'], unique=False)


def downgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    if 'ai_library_sync_log' in inspector.get_table_names():
        op.drop_index('ix_ai_library_sync_log_facility_id',
                      table_name='ai_library_sync_log')
        op.drop_index('ix_ai_library_sync_log_source_id',
                      table_name='ai_library_sync_log')
        op.drop_table('ai_library_sync_log')
