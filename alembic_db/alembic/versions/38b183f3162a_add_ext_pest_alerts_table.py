"""add_ext_pest_alerts_table

Revision ID: 38b183f3162a
Revises: f1e2d3c4b5a6
Create Date: 2026-03-26

"""
from alembic import op
import sqlalchemy as sa

revision = '38b183f3162a'
down_revision = 'f1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing_tables = sa.inspect(bind).get_table_names()
    if 'ext_pest_alerts' not in existing_tables:
        op.create_table(
            'ext_pest_alerts',
            sa.Column('id',             sa.Integer(),     autoincrement=True, nullable=False),
            sa.Column('crop_type',      sa.String(64),    nullable=False),
            sa.Column('pest_code',      sa.String(64),    nullable=False),
            sa.Column('pest_name',      sa.String(128),   nullable=True),
            sa.Column('severity',       sa.String(32),    nullable=True),
            sa.Column('region',         sa.String(128),   nullable=True),
            sa.Column('control_method', sa.Text(),        nullable=True),
            sa.Column('fetched_at',     sa.DateTime(),    nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('crop_type', 'pest_code', name='uq_ext_pa_crop_pest'),
        )
        op.create_index('ix_ext_pest_alerts_crop_type', 'ext_pest_alerts', ['crop_type'])
        op.create_index('ix_ext_pest_alerts_pest_code', 'ext_pest_alerts', ['pest_code'])


def downgrade():
    op.drop_index('ix_ext_pest_alerts_pest_code', table_name='ext_pest_alerts')
    op.drop_index('ix_ext_pest_alerts_crop_type', table_name='ext_pest_alerts')
    op.drop_table('ext_pest_alerts')
