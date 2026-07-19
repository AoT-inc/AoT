"""add sort_order to aitask

Revision ID: fa3f6b126919
Revises: fa3f6b126918
Create Date: 2026-02-19 15:55:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fa3f6b126919'
down_revision = ('fa3f6b126918', '68e82f214733')
branch_labels = None
depends_on = None

def upgrade():
    # Check if column exists first to be safe (re-entrant)
    connection = op.get_bind()
    columns = sa.inspect(connection).get_columns('ai_task')
    if not any(c['name'] == 'sort_order' for c in columns):
        op.add_column('ai_task', sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'))
        # Initialize existing records
        op.execute("UPDATE ai_task SET sort_order = 0 WHERE sort_order IS NULL")

def downgrade():
    op.drop_column('ai_task', 'sort_order')
