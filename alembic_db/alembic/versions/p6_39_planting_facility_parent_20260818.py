# coding=utf-8
"""P6-39: 식생 구획에 시설 부모 참조를 둔다 (기하 없이도 성립하게).

정본: docs/design/geo-vegetation-planting.md §시설 구획의 정본은 부모다

## 왜 소속을 컬럼에 두는가 — VP-5 와 충돌하지 않는다

노지 두둑은 갈아엎으면 위치가 바뀐다. 그래서 기하가 정본이고, zone 소속은
**공간 포함으로 파생 가능하므로 저장하지 않는다**(VP-5). 시설은 반대다 —
동·구역이 구조물로 존재하고 사람도 "3동" 이라 부른다. 기하를 그리지 않으면
소속을 파생할 근거 자체가 없으므로, VP-5 의 전제("파생 가능하다")가 성립하지
않는다. 예외를 두는 것이 아니라 조건이 다른 경우다.

## `source_ref` 파싱으로 대신하지 않는 이유

`source_ref='<facility_uuid>:<bay_id>'` 를 소속의 정본으로 승격시키면
`unique_id = 'uuid::채널'` 과 같은 **문자열 파싱 계약**이 하나 더 생긴다 —
이 저장소가 이미 지뢰로 기록해 둔 계열이다. `source_*` 는 원래 뜻인 출처
기록으로 두고, 소속은 인덱스가 걸리는 컬럼으로 둔다.

## `feature` 를 nullable 로 완화한다

시설 구획은 기하 없이 성립한다(위치의 정본이 부모다). 대신 새 불변식이
생긴다 — **`feature` 와 `facility_uuid` 중 적어도 하나는 있어야 한다**(VP-7).
둘 다 없으면 어디에도 없는 구획이다. 강제는 저장 검증과 무결성 검사에서 한다
(SQLite 에 CHECK 제약을 걸면 나중에 조건이 바뀔 때 테이블 재생성이 필요하고,
이 도메인의 판정은 전부 애플리케이션 층에 있다).

Revision ID: p6_39_planting_facility_parent_20260818
Revises: p6_38_geo_containment_cache_20260818
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_39_planting_facility_parent_20260818'
down_revision = 'p6_38_geo_containment_cache_20260818'
branch_labels = None
depends_on = None

_TABLE = 'geo_planting'
_INDEX = 'ix_geo_planting_facility_uuid'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def _indexes(bind):
    return {i['name'] for i in sa.inspect(bind).get_indexes(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all 이 모델대로 만든다

    cols = _columns(bind)
    with op.batch_alter_table(_TABLE) as batch:
        if 'facility_uuid' not in cols:
            batch.add_column(sa.Column('facility_uuid', sa.String(36),
                                       nullable=True))
        if 'bay_id' not in cols:
            batch.add_column(sa.Column('bay_id', sa.String(40), nullable=True))
        # 기하 없이 성립하게 — 시설 구획의 위치 정본은 부모다.
        batch.alter_column('feature', existing_type=sa.JSON(), nullable=True)

    if _INDEX not in _indexes(bind):
        op.create_index(_INDEX, _TABLE, ['facility_uuid'])


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return

    # 기하 없는 행은 되돌릴 수 없다(NOT NULL 을 되살릴 수 없다). 지우지 않고
    # 남긴 채 컬럼만 걷으면 위치를 잃은 유령 구획이 되므로, 그런 행이 있으면
    # 멈춘다 — 사람이 먼저 정리할 것.
    orphan = bind.execute(sa.text(
        'SELECT COUNT(*) FROM %s WHERE feature IS NULL' % _TABLE)).scalar()
    if orphan:
        raise RuntimeError(
            '기하 없는 식생 구획 %d 건이 있어 downgrade 할 수 없습니다. '
            '기하를 채우거나 삭제한 뒤 다시 시도하세요.' % orphan)

    if _INDEX in _indexes(bind):
        op.drop_index(_INDEX, table_name=_TABLE)

    cols = _columns(bind)
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column('feature', existing_type=sa.JSON(), nullable=False)
        if 'bay_id' in cols:
            batch.drop_column('bay_id')
        if 'facility_uuid' in cols:
            batch.drop_column('facility_uuid')
