"""add ai_context_source table

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b9
Create Date: 2026-03-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'ai_context_source' not in existing_tables:
        op.create_table(
            'ai_context_source',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('source_id', sa.String(36), nullable=False, unique=True),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('source_name', sa.String(100), nullable=False),
            sa.Column('source_type', sa.String(30), nullable=False, server_default='rest_api'),
            sa.Column('parameter_name', sa.String(100), nullable=False),
            sa.Column('config_json', sa.Text(), nullable=True, server_default='{}'),
            sa.Column('sync_interval_min', sa.Integer(), nullable=True, server_default='60'),
            sa.Column('last_synced_at', sa.DateTime(), nullable=True),
            sa.Column('last_sync_status', sa.String(20), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    op.drop_table('ai_context_source')
