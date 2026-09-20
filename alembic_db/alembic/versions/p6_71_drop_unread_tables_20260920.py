# coding=utf-8
"""P6-71: 어디서도 읽지 않는 표 4개를 지운다.

ai_recommendation · ai_status_snapshot · map_dependency · tier_thresholds 는
모델과 생성 마이그레이션만 있고, 라우트·서비스·데몬 어디에도 읽거나 쓰는 코드가
없다(2026-09-20 전수 검색: 모델 파일과 테스트를 뺀 참조 0). 표가 남아 있으면
스키마를 읽는 사람과 AI 가 있는 기능으로 오해한다.

행이 있어도 잃는 것이 없다 — 그 행을 읽는 코드가 없다. downgrade 는 빈 표를
같은 열로 되살린다.

Revision ID: p6_71_drop_unread_tables_20260920
Revises: p6_70_mcp_audit_indexes_20260920
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_71_drop_unread_tables_20260920'
down_revision = 'p6_70_mcp_audit_indexes_20260920'
branch_labels = None
depends_on = None

_TABLES = ('ai_recommendation', 'ai_status_snapshot', 'map_dependency',
           'tier_thresholds')


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    for table in _TABLES:
        if _has_table(table):
            op.drop_table(table)


def downgrade():
    if not _has_table('ai_recommendation'):
        op.create_table(
            'ai_recommendation',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('recommendation_id', sa.String(36), nullable=False, unique=True),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('keyword', sa.String(100), nullable=False),
            sa.Column('reason', sa.Text(), nullable=False),
            sa.Column('source_interests', sa.Text(), nullable=True),
            sa.Column('status', sa.String(20), nullable=True, index=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
        )
    if not _has_table('ai_status_snapshot'):
        op.create_table(
            'ai_status_snapshot',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('facility_id', sa.String(36), nullable=False, index=True),
            sa.Column('snapshot_data', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('week_number', sa.Integer(), nullable=True),
        )
    if not _has_table('map_dependency'):
        op.create_table(
            'map_dependency',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('geo_id', sa.String(64), nullable=False, index=True),
            sa.Column('source_id', sa.Integer(), sa.ForeignKey('geo_shape.id'),
                      nullable=False, index=True),
            sa.Column('target_id', sa.Integer(), nullable=False, index=True),
            sa.Column('target_type', sa.String(32), nullable=False),
            sa.Column('relation_type', sa.String(32), nullable=False),
        )
    if not _has_table('tier_thresholds'):
        op.create_table(
            'tier_thresholds',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('tier_level', sa.Integer(), nullable=False),
            sa.Column('threshold_type', sa.String(50), nullable=False),
            sa.Column('access_count_min', sa.Integer(), nullable=True),
            sa.Column('access_count_max', sa.Integer(), nullable=True),
            sa.Column('promotion_window_hours', sa.Integer(), nullable=True),
            sa.Column('demotion_window_hours', sa.Integer(), nullable=True),
            sa.Column('token_size_max', sa.Integer(), nullable=True),
            sa.Column('auto_promote', sa.Boolean(), nullable=True),
            sa.Column('auto_demote', sa.Boolean(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('tier_level', 'threshold_type',
                                name='uq_tier_threshold_type'),
        )
