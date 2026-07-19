# coding=utf-8
"""P5-40: Drop notice_links table.

Manual link entry was replaced by auto-detecting links/videos/images directly
in the notice post body at render time (aot-notice-render.js), so the
separate NoticeLink table is no longer used.

Revision ID: p5_40_drop_notice_links
Revises: p5_39_add_notice_board
Create Date: 2026-07-08
"""

revision = 'p5_40_drop_notice_links'
down_revision = 'p5_39_add_notice_board'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'notice_links' in inspector.get_table_names():
        op.drop_table('notice_links')


def downgrade():
    op.create_table(
        'notice_links',
        sa.Column('id', sa.Integer(), primary_key=True, unique=True),
        sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('notice_posts.id'), nullable=False),
        sa.Column('label', sa.Text(), nullable=True),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(length=20), server_default='url', nullable=True),
        sa.Column('display_order', sa.Integer(), server_default='0', nullable=True),
    )
    with op.batch_alter_table('notice_links') as batch_op:
        batch_op.create_index('ix_notice_links_post_id', ['post_id'])
