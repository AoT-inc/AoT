"""Add ai_entry, ai_agent, ai_history tables

Revision ID: 718f314963c3
Revises: 718f314963c2
Create Date: 2026-02-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

# revision identifiers, used by Alembic.
revision = '718f314963c3'
down_revision = '718f314963c2'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    tables = insp.get_table_names()

    # 1. ai_entry table
    if 'ai_entry' not in tables:
        op.create_table(
            'ai_entry',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('name', sa.String(100), nullable=False, unique=True),
            sa.Column('model_type', sa.String(50), server_default='gemini'),
            sa.Column('model_name', sa.String(100), server_default='gemini-2.0-flash'),
            sa.Column('api_endpoint', sa.String(255), server_default=''),
            sa.Column('auth_type', sa.String(20), server_default='api_key'),
            sa.Column('auth_id', sa.String(100), server_default=''),
            sa.Column('api_key', sa.Text(), server_default=''),
            sa.Column('is_activated', sa.Boolean(), server_default='1'),
            sa.Column('created_at', sa.DateTime()),
        )

    # 2. ai_agent table (depends on ai_entry)
    if 'ai_agent' not in tables:
        op.create_table(
            'ai_agent',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('name', sa.String(100), nullable=False, unique=True),
            sa.Column('entry_id', sa.String(36), sa.ForeignKey('ai_entry.unique_id'), nullable=True),
            sa.Column('role', sa.String(20), server_default='worker'),
            sa.Column('specialty', sa.String(100), server_default='general'),
            sa.Column('system_prompt', sa.Text(), server_default='You are a helpful assistant.'),
            sa.Column('temperature', sa.Float(), server_default='0.7'),
            sa.Column('max_tokens', sa.Integer(), server_default='2048'),
            sa.Column('custom_options_json', sa.Text(), server_default='{}'),
            sa.Column('is_activated', sa.Boolean(), server_default='1'),
            sa.Column('created_at', sa.DateTime()),
        )

    # 3. ai_history table (depends on ai_agent)
    if 'ai_history' not in tables:
        op.create_table(
            'ai_history',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('agent_id', sa.String(36), sa.ForeignKey('ai_agent.unique_id'), nullable=False),
            sa.Column('goal', sa.Text(), nullable=False),
            sa.Column('insight', sa.Text()),
            sa.Column('actions_json', sa.Text(), server_default='[]'),
            sa.Column('status', sa.String(20), server_default='proposed'),
            sa.Column('execution_result', sa.Text(), server_default=''),
            sa.Column('metadata_json', sa.Text(), server_default='{}'),
            sa.Column('timestamp', sa.DateTime(), index=True),
        )

def downgrade():
    conn = op.get_bind()
    insp = Inspector.from_engine(conn)
    tables = insp.get_table_names()

    # Drop in reverse dependency order
    if 'ai_history' in tables:
        op.drop_table('ai_history')
    if 'ai_agent' in tables:
        op.drop_table('ai_agent')
    if 'ai_entry' in tables:
        op.drop_table('ai_entry')
