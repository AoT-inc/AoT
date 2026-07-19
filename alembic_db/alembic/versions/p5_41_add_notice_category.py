# coding=utf-8
"""P5-41: Add category to notice posts.

Freeform category label set by the author when writing a post. The dashboard
widget's per-instance settings can then filter to only show posts matching a
selected set of categories (see widget_notice.py's execute_at_modification).

Revision ID: p5_41_add_notice_category
Revises: p5_40_drop_notice_links
Create Date: 2026-07-08
"""

revision = 'p5_41_add_notice_category'
down_revision = 'p5_40_drop_notice_links'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [c['name'] for c in inspector.get_columns('notice_posts')]
    if 'category' not in columns:
        op.add_column('notice_posts', sa.Column('category', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('notice_posts') as batch_op:
        batch_op.drop_column('category')
