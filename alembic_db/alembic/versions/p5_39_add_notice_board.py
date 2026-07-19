# coding=utf-8
"""P5-39: Add notice board tables.

Notice board: posts (with optional links, a single poll, replies, and
read-acknowledgement tracking), scheduled publish/expire, and pin support.

Revision ID: p5_39_add_notice_board
Revises: p5_38_add_goal_loop_flag
Create Date: 2026-07-07
"""

revision = 'p5_39_add_notice_board'
down_revision = 'p5_38_add_goal_loop_flag'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # Flask-SQLAlchemy's db.create_all() (run at app/daemon startup) may have
    # already created these tables straight from the ORM models before this
    # migration runs, so every create_table here is guarded.
    if 'notice_posts' not in existing_tables:
        op.create_table(
            'notice_posts',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('date_time', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('title', sa.Text(), nullable=True),
            sa.Column('body', sa.Text(), nullable=True),
            sa.Column('files', sa.Text(), nullable=True),
            sa.Column('pinned', sa.Boolean(), server_default=sa.false(), nullable=True),
            sa.Column('publish_at', sa.DateTime(), nullable=True),
            sa.Column('expire_at', sa.DateTime(), nullable=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        )

    if 'notice_links' not in existing_tables:
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

    if 'notice_polls' not in existing_tables:
        op.create_table(
            'notice_polls',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('notice_posts.id'), nullable=False, unique=True),
            sa.Column('question', sa.Text(), nullable=True),
            sa.Column('multi', sa.Boolean(), server_default=sa.false(), nullable=True),
            sa.Column('closes_at', sa.DateTime(), nullable=True),
        )

    if 'notice_poll_options' not in existing_tables:
        op.create_table(
            'notice_poll_options',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('poll_id', sa.Integer(), sa.ForeignKey('notice_polls.id'), nullable=False),
            sa.Column('label', sa.Text(), nullable=True),
            sa.Column('display_order', sa.Integer(), server_default='0', nullable=True),
        )
        with op.batch_alter_table('notice_poll_options') as batch_op:
            batch_op.create_index('ix_notice_poll_options_poll_id', ['poll_id'])

    if 'notice_poll_votes' not in existing_tables:
        op.create_table(
            'notice_poll_votes',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('poll_id', sa.Integer(), sa.ForeignKey('notice_polls.id'), nullable=False),
            sa.Column('option_id', sa.Integer(), sa.ForeignKey('notice_poll_options.id'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('date_time', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('option_id', 'user_id', name='uq_notice_poll_vote_option_user'),
        )
        with op.batch_alter_table('notice_poll_votes') as batch_op:
            batch_op.create_index('ix_notice_poll_votes_poll_id', ['poll_id'])
            batch_op.create_index('ix_notice_poll_votes_option_id', ['option_id'])
            batch_op.create_index('ix_notice_poll_votes_user_id', ['user_id'])

    if 'notice_replies' not in existing_tables:
        op.create_table(
            'notice_replies',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('notice_posts.id'), nullable=False),
            sa.Column('date_time', sa.DateTime(), nullable=True),
            sa.Column('body', sa.Text(), nullable=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        )
        with op.batch_alter_table('notice_replies') as batch_op:
            batch_op.create_index('ix_notice_replies_post_id', ['post_id'])

    if 'notice_acks' not in existing_tables:
        op.create_table(
            'notice_acks',
            sa.Column('id', sa.Integer(), primary_key=True, unique=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('notice_posts.id'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('date_time', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('post_id', 'user_id', name='uq_notice_ack_post_user'),
        )
        with op.batch_alter_table('notice_acks') as batch_op:
            batch_op.create_index('ix_notice_acks_post_id', ['post_id'])
            batch_op.create_index('ix_notice_acks_user_id', ['user_id'])


def downgrade():
    op.drop_table('notice_acks')
    op.drop_table('notice_replies')
    op.drop_table('notice_poll_votes')
    op.drop_table('notice_poll_options')
    op.drop_table('notice_polls')
    op.drop_table('notice_links')
    op.drop_table('notice_posts')
