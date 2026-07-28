# coding=utf-8
"""P6-14: 복합장치(Device) 부가 소속 테이블 — 다대다 + 장치 간 계층.

Phase 1(p6_11)의 parent_device_id 는 "자동 생성·소유하고 활성화를 cascade하는
단 하나의 상위 장치"를 가리키는 1급(primary) 관계로 그대로 남는다. 이 리비전은
그와 별개로, 이미 다른 장치 소속인 항목(또는 장치 자신)을 추가로 다른 장치의
구성에 참조 전용으로 끼워 넣는 새 테이블 `device_member` 하나만 만든다 — 기존
컬럼은 건드리지 않는다.

  device_member(device_id, member_type, member_id)
    device_id   -> 참조하는 쪽 장치의 CustomController.unique_id
    member_type -> 'input' | 'output' | 'device'
    member_id   -> 참조되는 Input/Output/CustomController 의 unique_id

FK 제약을 걸지 않은 이유는 p6_11과 동일하다 — member_type 에 따라 대상 테이블이
갈리는 다형 참조라 단일 FK로 표현되지 않는다.

새 테이블이라 기존 데이터에 영향이 없다(빈 테이블로 시작).

Revision ID: p6_14_device_membership_20260728
Revises: p6_13_api_key_hash_20260728
Create Date: 2026-07-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_14_device_membership_20260728'
down_revision = 'p6_13_api_key_hash_20260728'
branch_labels = None
depends_on = None

_TABLE = 'device_member'


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
        sa.Column('device_id', sa.String(length=36), nullable=False),
        sa.Column('member_type', sa.String(length=16), nullable=False),
        sa.Column('member_id', sa.String(length=36), nullable=False),
        sa.UniqueConstraint('device_id', 'member_type', 'member_id', name='uq_device_member'),
    )
    op.create_index('ix_device_member_device_id', _TABLE, ['device_id'])
    op.create_index('ix_device_member_member_id', _TABLE, ['member_id'])


def downgrade():
    if not _has_table(_TABLE):
        return
    try:
        op.drop_index('ix_device_member_member_id', table_name=_TABLE)
        op.drop_index('ix_device_member_device_id', table_name=_TABLE)
    except Exception:
        pass
    op.drop_table(_TABLE)
