# coding=utf-8
"""P6-48: 자원은 역할 선언으로 — 프로그램은 함수를 가리키지 않는다.

정본: docs/design/program-layer.md §P6 (2026-08-20 재설계)

`geo_program.resource_defs` — `[{role, default}]`. 이 프로그램이 쓰는 자원 역할과
단계 기본값이다.

## 왜 바꾸나

예전에는 단계마다 함수 uuid 를 적었다(`stages[].functions = [{id, role}]`).
**계획이 현장을 미리 지정하면 충돌을 풀 방법이 없다** — 프로그램은 여러 자리에서
참조하는 템플릿인데 함수 uuid 는 "이 온실의 3번 밸브" 라는 현장 사실이라, 두 번째
온실에서 쓰려면 복제해야 하고 그 순간 작물 지식이 두 벌이 되어 한쪽만 고쳐진다.

게다가 그렇게 지목한 함수를 켜는 일에는 아무 맥락도 실리지 않았다
(`_set_function_activation` 은 전역 스위치다). 두 구획이 같은 함수를 선언하면
두 번째 [적용]은 무동작이고, 어느 쪽 현장 데이터도 함수의 거동을 바꾸지 못했다.

## 기존 행 채우기

`stages[].functions` 에 **이미 역할이 함께 적혀 있다**. 그 역할만 모아
`resource_defs` 로 올린다. 어느 단계에서든 한 번이라도 쓰인 역할은
`default: True` 로 둔다 — 예전 구조에서 한 단계에만 적었더라도 그것은 "그 단계만
필요" 가 아니라 "거기까지만 적었다" 인 경우가 대부분이고, 뺀 쪽이 조용히 틀린다면
사람이 알아채기 어렵다(넣은 쪽이 틀리면 화면에 "이 자리에 없음" 으로 보인다).

## uuid 는 버리되 조용히 버리지 않는다

`stages[].functions` 를 **지우지 않고 그대로 둔다.** 읽는 쪽은 더 이상 보지 않지만
(`plot_context.stage_resources`), 그 uuid 들은 "이 함수가 그 자리에 배치돼야 한다"
는 정보다. 배치가 끝난 뒤 사람이 확인하고 지우는 것이 맞다 — geo_binding 레거시
컬럼과 같은 태도다. 몇 건을 남겼는지 로그로 남긴다.

Revision ID: p6_48_program_resource_defs_20260820
Revises: p6_47_program_target_defs_20260820
Create Date: 2026-08-20
"""
import json
import logging

import sqlalchemy as sa
from alembic import op

revision = 'p6_48_program_resource_defs_20260820'
down_revision = 'p6_47_program_target_defs_20260820'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

# 마이그레이션은 자기 시점의 어휘를 들고 있어야 한다 — `program_io` 에서 import
# 하면 나중에 역할이 늘었을 때 과거 마이그레이션의 결과가 소급해 달라진다.
_ROLES = ('irrigation', 'fertigation', 'other')


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table('geo_program'):
        return

    cols = {c['name'] for c in insp.get_columns('geo_program')}
    if 'resource_defs' not in cols:
        with op.batch_alter_table('geo_program') as batch:
            batch.add_column(sa.Column('resource_defs', sa.JSON(),
                                       nullable=True))

    rows = bind.execute(sa.text(
        'SELECT id, stages FROM geo_program '
        'WHERE resource_defs IS NULL')).fetchall()

    parked = 0
    for row_id, stages_json in rows:
        try:
            stages = json.loads(stages_json) if stages_json else []
        except (TypeError, ValueError):
            stages = []
        if not isinstance(stages, list):
            stages = []

        roles = []
        for st in stages:
            if not isinstance(st, dict):
                continue
            for item in (st.get('functions') or []):
                if isinstance(item, str):
                    item = {'id': item}
                if not isinstance(item, dict):
                    continue
                if item.get('id'):
                    parked += 1
                role = (item.get('role') or 'other').strip()
                if role in _ROLES and role not in roles:
                    roles.append(role)

        defs = [{'role': r, 'default': True} for r in roles]
        bind.execute(
            sa.text('UPDATE geo_program SET resource_defs = :d WHERE id = :i'),
            {'d': json.dumps(defs, ensure_ascii=False), 'i': row_id})

    if parked:
        logger.info(
            '[p6_48] 자원 역할을 프로그램으로 올렸습니다. 단계에 적혀 있던 함수 '
            'uuid %d 건은 `stages[].functions` 에 그대로 남겨 뒀습니다 — 읽는 '
            '쪽은 더 이상 보지 않으니, 그 함수들이 해당 도형 안에 배치돼 있는지 '
            '확인한 뒤 지우십시오.', parked)


def downgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table('geo_program'):
        return
    cols = {c['name'] for c in insp.get_columns('geo_program')}
    if 'resource_defs' in cols:
        with op.batch_alter_table('geo_program') as batch:
            batch.drop_column('resource_defs')
