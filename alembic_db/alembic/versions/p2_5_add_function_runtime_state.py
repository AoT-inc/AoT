"""P2-5: add function_runtime_state table

Revision ID: p2_5_function_runtime_state
Revises: fa3f6b126919
Create Date: 2026-05-16 00:00:00.000000

PI 적분·이전 명령·히스테리시스 상태를 데몬 재시작 간에 보존하기 위한 테이블.
"""
from alembic import op
import sqlalchemy as sa

revision = 'p2_5_function_runtime_state'
down_revision = 'fa3f6b126919'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'function_runtime_state',
        sa.Column('id',               sa.Integer(),     nullable=False, primary_key=True),
        sa.Column('function_id',      sa.String(36),    nullable=False, unique=True),
        sa.Column('integral_json',    sa.Text(),        nullable=True,  server_default='{}'),
        sa.Column('prev_cmds_json',   sa.Text(),        nullable=True,  server_default='{}'),
        sa.Column('active_vars_json', sa.Text(),        nullable=True,  server_default='{}'),
        sa.Column('last_cycle_ts',    sa.Float(),       nullable=True,  server_default='0.0'),
        sa.Column('updated_at',       sa.Float(),       nullable=True,  server_default='0.0'),
    )
    op.create_index('ix_function_runtime_state_function_id',
                    'function_runtime_state', ['function_id'], unique=True)


def downgrade():
    op.drop_index('ix_function_runtime_state_function_id',
                  table_name='function_runtime_state')
    op.drop_table('function_runtime_state')
