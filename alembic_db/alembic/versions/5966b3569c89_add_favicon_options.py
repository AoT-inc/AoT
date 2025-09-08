"""add favicon options

Revision ID: 5966b3569c89
Revises: 435f35958689
Create Date: 2024-10-01 13:39:25.265702

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic_db.alembic_post_utils import write_revision_post_alembic

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5966b3569c89'
down_revision = '435f35958689'
branch_labels = None
depends_on = None


def upgrade():
    # write_revision_post_alembic(revision)
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 현재 misc 테이블의 컬럼 목록을 안전하게 조회
    try:
        existing_cols = {c['name'] for c in insp.get_columns('misc')}
    except Exception:
        existing_cols = set()

    # 이미 있으면 추가하지 않음
    with op.batch_alter_table("misc") as batch_op:
        if 'favicon_display' not in existing_cols:
            batch_op.add_column(sa.Column('favicon_display', sa.Text))
        if 'brand_favicon' not in existing_cols:
            batch_op.add_column(sa.Column('brand_favicon', sa.BLOB))

    # 기본값 초기화 (컬럼이 존재할 때만 시도)
    try:
        op.execute("UPDATE misc SET favicon_display='default'")
    except Exception:
        # 일부 백엔드/상태에서 이미 값이 있거나 트랜잭션 이슈가 나면 무시
        pass

def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        existing_cols = {c['name'] for c in insp.get_columns('misc')}
    except Exception:
        existing_cols = set()

    with op.batch_alter_table("misc") as batch_op:
        if 'favicon_display' in existing_cols:
            batch_op.drop_column('favicon_display')
        if 'brand_favicon' in existing_cols:
            batch_op.drop_column('brand_favicon')

