# coding=utf-8
"""P6-34: 식생 구획(작기) 테이블 — geo_planting.

지도에 site > zone > facility > equipment > aot_device 는 있지만 **어디에 무엇이
심겨 있는지**를 담는 자리가 없었다. 작물 정보는 시설 안에만 절반쯤 있었고
(`facility.bays[].crop` — 문자열 하나라 이력이 없다), 노지 zone 은 아무것도
몰랐다. 그래서 구역 하나에 작물이 여러 종류면 구분할 방법이 아예 없었고,
"이 자리에 최근 3년간 뭐가 있었나"(연작 장해·윤작)에 답할 근거가 없었다.

GeoShape 에 종류를 하나 더 붙이지 않고 별도 테이블로 만든다. GeoShape 는 전부
반영구이고 만료 개념이 없어서, 3개월 뒤 죽는 종류를 섞으면 GeoShape 를 읽는
모든 경로가 "만료된 건 빼라"를 각자 기억해야 한다. 근거는
docs/design/geo-vegetation-planting.md.

겹침(간작·혼작)은 정상이므로 **유일성 제약을 걸지 않는다.** 나중에 "겹치면 안
될 것 같다"는 직관으로 유니크 인덱스를 추가하지 말 것 — 겹침은 버그가 아니라
요구사항이다(VP-3).

Revision ID: p6_34_geo_planting_20260813
Revises: p6_33_api_key_scope_20260811
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_34_geo_planting_20260813'
down_revision = 'p6_33_api_key_scope_20260811'
branch_labels = None
depends_on = None

_TABLE = 'geo_planting'


def _has_table(table):
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    # 재실행 안전: 이미 있으면 만들지 않는다.
    if _has_table(_TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unique_id', sa.String(length=36), nullable=False),

        # 공간 — GeoMap.unique_id. zone 소속 컬럼은 두지 않는다(공간 포함으로
        # 파생). 물질화한 소속이 어떻게 썩는지는 map_overlay_id 가 보여줬다.
        sa.Column('geo_id', sa.String(length=64), nullable=False),
        sa.Column('feature', sa.JSON(), nullable=False),

        # 작물
        sa.Column('crop', sa.String(length=64), nullable=False),
        sa.Column('variety', sa.String(length=64), nullable=True),

        # 시간 — Date 이고 DateTime 이 아니다. 농사의 단위는 날이라
        # 시분초는 의미가 없고 tz 변환 문제만 부른다.
        sa.Column('planted_on', sa.Date(), nullable=False),
        sa.Column('ended_on', sa.Date(), nullable=True),
        sa.Column('expected_end_on', sa.Date(), nullable=True),
        sa.Column('ended_reason', sa.String(length=16), nullable=True),

        # 출처 — bay 는 참조가 아니라 스냅샷(bay_count 변경이 과거 이력을
        # 바꾸지 못하게).
        sa.Column('source_kind', sa.String(length=16), nullable=False,
                  server_default='drawn'),
        sa.Column('source_ref', sa.String(length=80), nullable=True),

        # 표시
        sa.Column('name', sa.String(length=120), nullable=True),
        sa.Column('color', sa.String(length=16), nullable=True),

        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),

        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unique_id'),
    )

    # 조회 축 둘: 지도 단위 렌더(geo_id), 유효 여부 필터(ended_on).
    # 겹침 유일성 인덱스는 만들지 않는다 — VP-3.
    op.create_index(op.f('ix_geo_planting_geo_id'), _TABLE, ['geo_id'])
    op.create_index(op.f('ix_geo_planting_ended_on'), _TABLE, ['ended_on'])


def downgrade():
    if not _has_table(_TABLE):
        return
    op.drop_index(op.f('ix_geo_planting_ended_on'), table_name=_TABLE)
    op.drop_index(op.f('ix_geo_planting_geo_id'), table_name=_TABLE)
    op.drop_table(_TABLE)
