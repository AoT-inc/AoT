"""018 Add is_enabled to ai_context_source — activate / deactivate toggle

Revision ID: a9b8c7d6e5f4
Revises: f0a1b2c3d4e5
Create Date: 2026-03-27 00:00:00.000000

Changes:
- ai_context_source: add is_enabled (Boolean, default=True)
  Separates user-level activation toggle from is_active (soft-delete flag).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a9b8c7d6e5f4'
down_revision = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    existing_cols = {c['name'] for c in inspector.get_columns('ai_context_source')}

    if 'is_enabled' not in existing_cols:
        op.add_column(
            'ai_context_source',
            sa.Column('is_enabled', sa.Boolean(), nullable=True,
                      server_default=sa.text('1')),
        )


def downgrade():
    op.drop_column('ai_context_source', 'is_enabled')
