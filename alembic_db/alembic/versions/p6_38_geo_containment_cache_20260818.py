# coding=utf-8
"""P6-38: 공간 포함 관계 **파생 캐시**.

계층 질의가 매번 기하를 다시 계산한다. 실측(2026-08-18, 로컬 · 도형 150 ·
활성 구획 22):

    build_geo_parent_map(전체)        42.5 ms
    descendant_target_ids('3포장')    73.9 ms
    search_schedule('3포장')         197.3 ms

AI 가 도구를 여러 번 부르면 그대로 누적된다.

**`GeoShape.parent_id` 를 백필하지 않는다.** 그 컬럼은 파생값이 아니라 정본이다
— 시간대 상속(`resolve_timezone` 2단계)·좌표 상속·`facility_bay` 삭제 트리거가
그 체인을 읽는다. 지금 전부 NULL 이라 그 경로들이 잠들어 있는데, 기하 파생값을
거기 채우면 **tz 해석이 조용히 바뀐다.** 사람이 정한 값과 기계가 추측한 값이
같은 칸에 섞이면 나중에 둘을 가를 수도 없다.

그래서 캐시는 **버려도 되는 자리**에 따로 둔다. 정본은 여전히 기하이고,
캐시와 기하가 어긋나면 **기하가 맞다**.

도형과 식생 구획을 한 테이블에 담는 이유: 둘 다 "무엇 안에 있는가" 라는 같은
질문이고, 갈라 두면 무효화 시점을 두 벌 기억해야 한다.

Revision ID: p6_38_geo_containment_cache_20260818
Revises: p6_37_note_schedule_link_20260818
Create Date: 2026-08-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_38_geo_containment_cache_20260818'
down_revision = 'p6_37_note_schedule_link_20260818'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'geo_containment_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        # 'shape' | 'planting' — 같은 uuid 공간을 쓰지 않으므로 종류를 함께 든다.
        sa.Column('child_kind', sa.String(length=16), nullable=False),
        sa.Column('child_uuid', sa.String(length=36), nullable=False),
        # NULL = "계산했고 부모가 없다". 행이 아예 없는 것(미계산)과 다르다 —
        # 이 구분이 없으면 루트 도형은 영원히 캐시 미스라 매번 기하를 돈다.
        sa.Column('parent_uuid', sa.String(length=36), nullable=True),
        sa.Column('geo_id', sa.String(length=64), nullable=True),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('child_kind', 'child_uuid',
                            name='uq_geo_containment_child'),
    )
    op.create_index('ix_geo_containment_geo_id', 'geo_containment_cache',
                    ['geo_id'])
    op.create_index('ix_geo_containment_parent', 'geo_containment_cache',
                    ['parent_uuid'])


def downgrade():
    op.drop_index('ix_geo_containment_parent',
                  table_name='geo_containment_cache')
    op.drop_index('ix_geo_containment_geo_id',
                  table_name='geo_containment_cache')
    op.drop_table('geo_containment_cache')
