"""016 AI Page UX Redesign — add onboarding v2 fields + ai_status_snapshot table

Revision ID: f0a1b2c3d4e5
Revises: e2f3a4b5c6d7
Create Date: 2026-03-27 00:00:00.000000

Changes:
- ai_user_profile: add onboarding_completed, onboarding_completed_at,
                   facility_preset, user_requirement
- create ai_status_snapshot table
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f0a1b2c3d4e5'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # ----------------------------------------------------------------
    # ai_user_profile: add new 016 onboarding fields if missing
    # ----------------------------------------------------------------
    existing_cols = {c['name'] for c in inspector.get_columns('ai_user_profile')}

    if 'onboarding_completed' not in existing_cols:
        op.add_column('ai_user_profile',
                      sa.Column('onboarding_completed', sa.Boolean(), nullable=True,
                                server_default=sa.text('0')))

    if 'onboarding_completed_at' not in existing_cols:
        op.add_column('ai_user_profile',
                      sa.Column('onboarding_completed_at', sa.DateTime(), nullable=True))

    if 'facility_preset' not in existing_cols:
        op.add_column('ai_user_profile',
                      sa.Column('facility_preset', sa.String(50), nullable=True))

    if 'user_requirement' not in existing_cols:
        op.add_column('ai_user_profile',
                      sa.Column('user_requirement', sa.Text(), nullable=True))

    # ----------------------------------------------------------------
    # ai_status_snapshot: create table if not present
    # ----------------------------------------------------------------
    existing_tables = inspector.get_table_names()
    if 'ai_status_snapshot' not in existing_tables:
        op.create_table(
            'ai_status_snapshot',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('snapshot_data', sa.Text(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('week_number', sa.Integer(), nullable=True, server_default='1'),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    op.drop_column('ai_user_profile', 'user_requirement')
    op.drop_column('ai_user_profile', 'facility_preset')
    op.drop_column('ai_user_profile', 'onboarding_completed_at')
    op.drop_column('ai_user_profile', 'onboarding_completed')
    op.drop_table('ai_status_snapshot')
