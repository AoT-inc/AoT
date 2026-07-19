"""add ai_recommendation table

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-03-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'ai_recommendation' not in existing_tables:
        op.create_table(
            'ai_recommendation',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('recommendation_id', sa.String(36), nullable=False, unique=True),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('keyword', sa.String(100), nullable=False),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('source_interests', sa.Text(), nullable=True, server_default='[]'),
            sa.Column('status', sa.String(20), nullable=True, server_default='pending', index=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    op.drop_table('ai_recommendation')
