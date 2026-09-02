# coding=utf-8
"""P6-62: 구획·구역 일지 스냅샷 표 — `geo_journal`.

## 왜 새 표인가

일지는 "그때 그 자리의 사실" 을 떠 둔 **파생 기록**이다. 구획(`geo_plot`)이나
도형(`geo_shape`)에 열을 더해 담을 수 있는 것이 아니다 — 한 대상에 여러 일지가
쌓이고(작기마다·기간마다), 대상이 셋(plot·zone·site)이라 어느 표에도 속하지
않는다.

## FK 를 걸지 않는 이유

`target_id` 는 `geo_plot.unique_id` 일 수도 `geo_shape.unique_id` 일 수도 있다.
표가 둘이라 FK 를 걸 수 없고, 걸 수 있더라도 걸지 않는다 — **원본이 지워져도
일지는 남아야 한다.** 지워진 구획의 작기 기록이 그 삭제로 함께 사라지면 기록을
남기는 뜻이 없다.

`created_by` 만 `users.id` 를 가리킨다(그쪽은 표가 하나다).

## 인덱스

`target_id` 하나만 건다. 카드 목록은 최신순 상한(50)이라 `created_at` 정렬이
전량 스캔이어도 문제되지 않는 규모이고, 대상별 조회(§12 `list_plot_journals`)가
실제로 자주 도는 질의다.

Revision ID: p6_62_geo_journal_20260902
Revises: p6_61_sequence_resume_on_activate_20260901
Create Date: 2026-09-02
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_62_geo_journal_20260902'
down_revision = 'p6_61_sequence_resume_on_activate_20260901'
branch_labels = None
depends_on = None


def _has_table(name):
    bind = op.get_bind()
    return bind.dialect.has_table(bind, name)


def upgrade():
    if _has_table('geo_journal'):
        return
    op.create_table(
        'geo_journal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unique_id', sa.String(length=36), nullable=False),
        sa.Column('target_type', sa.String(length=16), nullable=False),
        sa.Column('target_id', sa.String(length=36), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('tz_name', sa.String(length=64), nullable=True),
        sa.Column('title', sa.String(length=160), nullable=False,
                  server_default=''),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='pending'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unique_id'),
    )
    op.create_index('ix_geo_journal_target_id', 'geo_journal', ['target_id'])


def downgrade():
    if _has_table('geo_journal'):
        op.drop_index('ix_geo_journal_target_id', table_name='geo_journal')
        op.drop_table('geo_journal')
