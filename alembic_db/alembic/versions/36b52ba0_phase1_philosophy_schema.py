"""phase1_philosophy_schema

Revision ID: 36b52ba0
Revises: fa3f6b126919
Create Date: 2026-03-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '36b52ba0'
down_revision = ('fa3f6b126919', 'a2a5404911f0')
branch_labels = None
depends_on = None


def upgrade():
    # Re-entrancy guard: fetch existing tables once
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # Create ai_context_record table
    if 'ai_context_record' not in existing_tables:
        op.create_table(
            'ai_context_record',
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('parameter_name', sa.String(100), nullable=False),
            sa.Column('value', sa.Text, nullable=False),
            sa.Column('source', sa.String(100), nullable=True),
            sa.Column('context_state', sa.String(20), server_default='system_generated'),
            sa.Column('confirmed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('confirmed_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('created_by', sa.String(20), server_default='system'),
        )
    else:
        print('  [SKIP] ai_context_record already exists')

    # Create ai_facility_learning table
    if 'ai_facility_learning' not in existing_tables:
        op.create_table(
            'ai_facility_learning',
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('facility_id', sa.String(36), nullable=False, unique=True, index=True),
            sa.Column('learning_started_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('last_feedback_at', sa.DateTime(), nullable=True),
            sa.Column('feedback_count_total', sa.Integer(), server_default='0'),
            sa.Column('confirmations_json', sa.Text, server_default='{}'),
            sa.Column('learning_phase_active', sa.Boolean(), server_default=True),
            sa.Column('stalled_since', sa.DateTime(), nullable=True),
            sa.Column('onboarding_complete', sa.Boolean(), server_default=False),
        )
    else:
        print('  [SKIP] ai_facility_learning already exists')

    # Create ai_feedback_event table
    if 'ai_feedback_event' not in existing_tables:
        op.create_table(
            'ai_feedback_event',
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('event_type', sa.String(20), nullable=False),
            sa.Column('parameter_name', sa.String(100), nullable=False),
            sa.Column('previous_value', sa.Text, nullable=True),
            sa.Column('new_value', sa.Text, nullable=True),
            sa.Column('reasoning', sa.Text, nullable=True),
            sa.Column('context_record_id', sa.String(36), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )
    else:
        print('  [SKIP] ai_feedback_event already exists')

    # Create ai_onboarding_record table
    if 'ai_onboarding_record' not in existing_tables:
        op.create_table(
            'ai_onboarding_record',
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('onboarding_started_at', sa.DateTime(), server_default=sa.func.now()),
            sa.Column('contract_acknowledged_at', sa.DateTime(), nullable=True),
            sa.Column('onboarding_completed_at', sa.DateTime(), nullable=True),
            sa.Column('facility_type', sa.String(50), nullable=True),
            sa.Column('operator_experience', sa.String(20), nullable=True),
            sa.Column('critical_parameters_json', sa.Text, nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
        )
    else:
        print('  [SKIP] ai_onboarding_record already exists')

    # Add context_state column to notes table (check existence first for re-entrancy)
    columns = [c['name'] for c in inspector.get_columns('notes')]
    if 'context_state' not in columns:
        op.add_column('notes', sa.Column('context_state', sa.String(20), server_default='system_generated', nullable=True))
    else:
        print('  [SKIP] notes.context_state already exists')


def downgrade():
    # Drop context_state from notes (check existence first)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [c['name'] for c in inspector.get_columns('notes')]
    if 'context_state' in columns:
        op.drop_column('notes', 'context_state')

    # Drop all new tables
    op.drop_table('ai_onboarding_record')
    op.drop_table('ai_feedback_event')
    op.drop_table('ai_facility_learning')
    op.drop_table('ai_context_record')
