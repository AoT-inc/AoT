# coding=utf-8
"""P6-42: 재배 프로그램의 `crop` → `subject`. 대상을 작물로 국한하지 않는다.

정본: docs/design/program-layer.md

AoT 는 용도를 농업으로 한정하지 않는다(랜딩 문구: "온실·축사·노지는 물론 공원·
시설물·교통처럼…"). 그런데 프로그램의 대상 필드를 `crop` 으로 두면 공원의 잔디,
가로수, 체육시설의 녹지처럼 **작물이 아닌 대상**을 담을 자리가 없다. 어휘가 좁으면
그 화면은 그 용도에서 그냥 틀린 말이 된다.

`subject` 는 "이 프로그램이 다루는 대상" 이다 — 작물명일 수도, 수종·잔디 종류일
수도, 그 밖의 관리 대상일 수도 있다.

**지금 바꾸는 이유**: P1~P3 에서 막 만든 컬럼이고 실사용 데이터가 없다. 어휘는
한 번 퍼지면 되돌리기 어렵다.

Revision ID: p6_42_program_subject_20260819
Revises: p6_41_program_target_methods_20260819
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_42_program_subject_20260819'
down_revision = 'p6_41_program_target_methods_20260819'
branch_labels = None
depends_on = None

_TABLE = 'geo_program'
_OLD_IDX = 'ix_geo_program_crop'
_NEW_IDX = 'ix_geo_program_subject'


def _cols(insp):
    return {c['name'] for c in insp.get_columns(_TABLE)}


def _idx(insp):
    return {i['name'] for i in insp.get_indexes(_TABLE)}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return
    if _OLD_IDX in _idx(insp):
        op.drop_index(_OLD_IDX, table_name=_TABLE)
    if 'crop' in _cols(insp) and 'subject' not in _cols(insp):
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column('crop', new_column_name='subject',
                               existing_type=sa.String(64))
    insp = sa.inspect(bind)
    if _NEW_IDX not in _idx(insp):
        op.create_index(_NEW_IDX, _TABLE, ['subject'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return
    if _NEW_IDX in _idx(insp):
        op.drop_index(_NEW_IDX, table_name=_TABLE)
    if 'subject' in _cols(insp) and 'crop' not in _cols(insp):
        with op.batch_alter_table(_TABLE) as batch:
            batch.alter_column('subject', new_column_name='crop',
                               existing_type=sa.String(64))
    insp = sa.inspect(bind)
    if _OLD_IDX not in _idx(insp):
        op.create_index(_OLD_IDX, _TABLE, ['crop'])
