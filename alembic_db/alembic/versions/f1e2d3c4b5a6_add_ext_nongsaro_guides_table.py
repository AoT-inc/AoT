"""add_ext_nongsaro_guides_table

Revision ID: f1e2d3c4b5a6
Revises: a2a5404911f0
Create Date: 2026-03-26

Phase 2b — EXT-KR-02 implementation.
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic import op
import sqlalchemy as sa

revision = 'f1e2d3c4b5a6'
down_revision = 'a2a5404911f0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if 'ext_nongsaro_guides' not in existing_tables:
        op.create_table(
            'ext_nongsaro_guides',
            sa.Column('id',         sa.Integer(),     autoincrement=True, nullable=False),
            sa.Column('crop_type',  sa.String(64),    nullable=False),
            sa.Column('guide_type', sa.String(32),    nullable=False),
            sa.Column('title',      sa.String(256),   nullable=True),
            sa.Column('content',    sa.Text(),         nullable=True),
            sa.Column('season',     sa.String(32),    nullable=True),
            sa.Column('fetched_at', sa.DateTime(),    nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('crop_type', 'guide_type', name='uq_ext_ng_crop_type'),
        )
        op.create_index('ix_ext_nongsaro_guides_crop_type',  'ext_nongsaro_guides', ['crop_type'])
        op.create_index('ix_ext_nongsaro_guides_guide_type', 'ext_nongsaro_guides', ['guide_type'])


def downgrade():
    op.drop_index('ix_ext_nongsaro_guides_guide_type', table_name='ext_nongsaro_guides')
    op.drop_index('ix_ext_nongsaro_guides_crop_type',  table_name='ext_nongsaro_guides')
    op.drop_table('ext_nongsaro_guides')
