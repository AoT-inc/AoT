# coding=utf-8
"""P7-08: AI 카드 첨부에 viz 스펙 칸 — ai_card_attachments.spec (Text, nullable).

AI가 조회한 값을 게이지/미니그래프 카드로 내는 kind 'viz' 첨부가 정규화된 JSON 스펙을
이 칸에 담는다(파일이 아니다). 설계 .local/plans/ai-card-viz-wiring_20261106.md.

재실행 안전(이미 있으면 건너뜀). downgrade 는 칸을 지운다(SQLite 3.35+ 네이티브 DROP COLUMN).

Revision ID: p7_09_ai_card_viz_spec_20261106
Revises: p7_08_drop_device_latlng_columns_20261106
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = 'p7_09_ai_card_viz_spec_20261106'
down_revision = 'p7_08_drop_device_latlng_columns_20261106'
branch_labels = None
depends_on = None


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if 'spec' not in _columns('ai_card_attachments'):
        with op.batch_alter_table('ai_card_attachments') as batch:
            batch.add_column(sa.Column('spec', sa.Text(), nullable=True))


def downgrade():
    if 'spec' in _columns('ai_card_attachments'):
        op.execute('ALTER TABLE "ai_card_attachments" DROP COLUMN spec')
