# coding=utf-8
"""P6-43: 재배 프로그램 → **관리 프로그램**. 대상 종류(`kind`)를 갖는다.

정본: docs/design/program-layer.md

## 왜

식생은 AoT 가 관리하는 대상 중 **하나일 뿐**이다. 같은 구조("무엇을, 어떤 단계로,
어떤 목표로")가 가축(축사 온습도·환기), 시설물(점검 주기), 도로·구조물에도 그대로
쓰인다. 그런데 테이블 이름이 `geo_program` 이면 그 용도에서 이름부터 틀린 말이
되고, 결국 같은 구조를 한 벌 더 만들게 된다.

`kind` 는 대상 종류다 — `vegetation` | `livestock` | `facility` | `other`.
**좁게 시작한다**(어휘는 한 번 퍼지면 되돌리기 어렵다). `other` 가 있으므로 새 종류가
필요할 때 코드를 고치지 않고도 담을 수 있다.

기존 행은 전부 식생이므로 `vegetation` 으로 채운다.

Revision ID: p6_43_program_kind_20260819
Revises: p6_42_program_subject_20260819
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_43_program_kind_20260819'
down_revision = 'p6_42_program_subject_20260819'
branch_labels = None
depends_on = None

_OLD = 'geo_program'
_NEW = 'geo_program'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table(_OLD) and not insp.has_table(_NEW):
        op.rename_table(_OLD, _NEW)

    # ⚠ rename 뒤에는 **inspector 를 새로 만든다.** 옛 inspector 는 방금 만든
    # 이름을 모르므로 `has_table(_NEW)` 가 False 를 돌려주고, 그대로 return 하면
    # 테이블만 옮겨진 채 컬럼이 안 붙는다 — 마이그레이션은 "성공" 으로 남는다
    # (실제로 그렇게 한 번 지나갔다).
    insp = sa.inspect(bind)
    if not insp.has_table(_NEW):
        return

    cols = {c['name'] for c in insp.get_columns(_NEW)}
    if 'kind' not in cols:
        with op.batch_alter_table(_NEW) as batch:
            batch.add_column(sa.Column('kind', sa.String(24), nullable=False,
                                       server_default='vegetation'))
        # 기존 행은 전부 식생이다 — 명시적으로 채워 둔다(server_default 는 앞으로
        # 들어올 행에만 걸리고, 나중에 default 를 빼면 그 흔적이 사라진다).
        bind.execute(sa.text("UPDATE %s SET kind='vegetation' WHERE kind IS NULL"
                             % _NEW))

    idx = {i['name'] for i in sa.inspect(bind).get_indexes(_NEW)}
    if 'ix_geo_program_kind' not in idx:
        op.create_index('ix_geo_program_kind', _NEW, ['kind'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_NEW):
        return
    idx = {i['name'] for i in insp.get_indexes(_NEW)}
    if 'ix_geo_program_kind' in idx:
        op.drop_index('ix_geo_program_kind', table_name=_NEW)
    cols = {c['name'] for c in insp.get_columns(_NEW)}
    if 'kind' in cols:
        with op.batch_alter_table(_NEW) as batch:
            batch.drop_column('kind')
    if not insp.has_table(_OLD):
        op.rename_table(_NEW, _OLD)
