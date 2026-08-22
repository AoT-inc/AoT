# coding=utf-8
"""P6-49: 프로그램에 소속 탭을 둔다 — geo/program 화면에 탭 UI 추가.

`geo_program.tab_id` — `Tab.unique_id` 를 가리키는 인덱스 걸린 문자열 컬럼.

## 진짜 FK 를 걸지 않는 이유

`geo_planting.facility_uuid`(p6_39)와 같은 패턴이다. 탭이 지워져도 이 값이
가리키던 프로그램이 함께 사라지면 안 된다 — 프로그램은 `geo_plot.program_uuid`
로 다른 구획에서 참조 중일 수 있어(`plot-dangling-program` 무결성 규칙), DB
레벨 CASCADE 로 지우면 그 구획이 고아가 된다. 탭 삭제 시 소속 프로그램의
재배정(기본 탭으로 이동)은 `TabService` 의 고아 정리(`find_orphaned_entries`/
`cleanup_orphaned_entries`)가 애플리케이션 층에서 담당한다.

## 백필을 여기서 하지 않는 이유

`tab` 테이블은 이 저장소의 alembic 히스토리에 생성 마이그레이션이 없는
베이스 테이블 취급이다(항상 존재한다고 가정하고 증분 변경만 쌓는다 — misc·
roles 와 같은 부류). 여기서 기본 탭 행을 직접 만들거나 찾는 로직을 두지
않고, `routes_geo.page_programs()` 가 input 페이지(`routes_input.page_input`)
와 같은 방식으로 **요청 시점에 지연 백필**한다(NULL 인 `tab_id` 를 발견하면
그때 기본 탭을 만들어 채운다).

Revision ID: p6_49_program_tab_20260821
Revises: p6_48_program_resource_defs_20260820
Create Date: 2026-08-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_49_program_tab_20260821'
down_revision = 'p6_48_program_resource_defs_20260820'
branch_labels = None
depends_on = None

_TABLE = 'geo_program'
_INDEX = 'ix_geo_program_tab_id'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def _indexes(bind):
    return {i['name'] for i in sa.inspect(bind).get_indexes(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all 이 모델대로 만든다

    cols = _columns(bind)
    if 'tab_id' not in cols:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column('tab_id', sa.String(36), nullable=True))

    if _INDEX not in _indexes(bind):
        op.create_index(_INDEX, _TABLE, ['tab_id'])


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return

    if _INDEX in _indexes(bind):
        op.drop_index(_INDEX, table_name=_TABLE)

    cols = _columns(bind)
    if 'tab_id' in cols:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column('tab_id')
