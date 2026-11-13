# coding=utf-8
"""P7-02: 옛 `irrigation_design` 표 정리 (물 회로 계획서 13절 결정 6).

물 회로(W0~W5)가 이 표의 쓰임을 모두 넘겨받았고 모델·API 도 코드에서 지웠다.
다만 자체 설치 운영자의 DB 에는 행이 남아 있을 수 있다. 그래서:

  - 표가 있고 **0행**이면 지운다.
  - 표에 **행이 있으면 그대로 둔다**(경고만 남긴다). 사용자가 쓴 설계를 이전이 지우지 않는다.
  - 표가 없으면 아무것도 하지 않는다(새 설치는 애초에 이 표를 만들지 않는다).

downgrade 는 빈 표를 되만든다(지워진 행은 돌아오지 않는다 — 지운 것은 0행뿐이다).

Revision ID: p7_02_drop_irrigation_design_20261102
Revises: p7_01_facility_layout_20261102
Create Date: 2026-11-02
"""
import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGTEXT

revision = 'p7_02_drop_irrigation_design_20261102'
down_revision = 'p7_01_facility_layout_20261102'
branch_labels = None
depends_on = None

TABLE = 'irrigation_design'
log = logging.getLogger('alembic.runtime.migration')


def _has_table():
    return TABLE in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if not _has_table():
        return
    rows = op.get_bind().execute(sa.text('SELECT COUNT(*) FROM %s' % TABLE)).scalar() or 0
    if rows:
        log.warning('%s 표에 행이 %d개 있어 지우지 않고 남겨 둡니다. 더 쓰지 않는 표이니 '
                    '필요한 내용을 옮긴 뒤 직접 지우세요.', TABLE, rows)
        return
    op.drop_table(TABLE)


def downgrade():
    if _has_table():
        return
    long_text = sa.Text().with_variant(LONGTEXT, 'mysql', 'mariadb')
    op.create_table(
        TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
        sa.Column('name', sa.String(128), nullable=False, server_default='New Design'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('boundary_json', long_text, nullable=True),
        sa.Column('rows_json', long_text, nullable=True),
        sa.Column('sprinklers_json', long_text, nullable=True),
        sa.Column('config_json', long_text, nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('total_volume_applied', sa.Float(), nullable=True),
        sa.Column('function_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(36), nullable=True))
