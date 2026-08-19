# coding=utf-8
"""P6-40: 재배 프로그램(GeoCropProgram) + 식생 구획의 프로그램 참조.

정본: docs/design/program-layer.md

## 왜

작물의 "단계별 기간·목표 환경" 지식이 네 곳에 흩어져 서로 만나지 않는다:
`STAGE_DURATION_MAP`(AI 전용 하드코딩) · 스마트팜코리아 setpoint 캐시(AI 전용) ·
`FunctionCropPreset`(제어 전용, 단계 없음) · Method 곡선(사람이 손으로 그림).
AI 는 "지금 개화기, 최적 22~26℃" 를 아는데 그 값이 제어로 흐르지 않는다.

이 테이블이 그 지식을 한 층으로 모으고, 식생 구획이 참조한다.

## 구획은 **버전까지** 고정한다

`program_uuid` 만으로는 부족하다. 프로그램을 고치면 진행 중인 작기의 해석이 바뀌어
"그때 무엇을 목표로 길렀나" 의 답이 조용히 달라진다.

Revision ID: p6_40_program_20260819
Revises: p6_39_planting_facility_parent_20260818
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_40_program_20260819'
down_revision = 'p6_39_planting_facility_parent_20260818'
branch_labels = None
depends_on = None

_TABLE = 'geo_program'
_PLANTING = 'geo_planting'
_IDX_CROP = 'ix_geo_program_crop'
_IDX_PROG = 'ix_geo_planting_program_uuid'


def _cols(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def _idx(bind, table):
    return {i['name'] for i in sa.inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('name', sa.String(128), nullable=False),
            sa.Column('crop', sa.String(64), nullable=False),
            sa.Column('variety', sa.String(64), nullable=True),
            sa.Column('source', sa.String(16), nullable=False,
                      server_default='user'),
            sa.Column('source_ref', sa.String(120), nullable=True),
            sa.Column('source_note', sa.Text, nullable=True),
            sa.Column('derived_from', sa.String(36), nullable=True),
            sa.Column('reviewed_at', sa.DateTime, nullable=True),
            sa.Column('version', sa.Integer, nullable=False, server_default='1'),
            sa.Column('stages', sa.JSON, nullable=False),
            sa.Column('photosynthesis', sa.JSON, nullable=True),
            sa.Column('notes', sa.Text, nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=True),
            sa.Column('updated_at', sa.DateTime, nullable=True),
        )
    if _IDX_CROP not in _idx(bind, _TABLE):
        op.create_index(_IDX_CROP, _TABLE, ['crop'])

    if insp.has_table(_PLANTING):
        cols = _cols(bind, _PLANTING)
        with op.batch_alter_table(_PLANTING) as batch:
            if 'program_uuid' not in cols:
                batch.add_column(sa.Column('program_uuid', sa.String(36),
                                           nullable=True))
            if 'program_version' not in cols:
                batch.add_column(sa.Column('program_version', sa.Integer,
                                           nullable=True))
        if _IDX_PROG not in _idx(bind, _PLANTING):
            op.create_index(_IDX_PROG, _PLANTING, ['program_uuid'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table(_PLANTING):
        if _IDX_PROG in _idx(bind, _PLANTING):
            op.drop_index(_IDX_PROG, table_name=_PLANTING)
        cols = _cols(bind, _PLANTING)
        with op.batch_alter_table(_PLANTING) as batch:
            if 'program_version' in cols:
                batch.drop_column('program_version')
            if 'program_uuid' in cols:
                batch.drop_column('program_uuid')

    # 프로그램 표는 사람이 만든 것을 담을 수 있으므로 **지우기 전에 확인한다.**
    # 내장(builtin)만 남아 있으면 시드로 되살릴 수 있어 그대로 지운다.
    if insp.has_table(_TABLE):
        user_rows = bind.execute(sa.text(
            "SELECT COUNT(*) FROM %s WHERE source NOT IN ('builtin','external')"
            % _TABLE)).scalar()
        if user_rows:
            raise RuntimeError(
                '사용자/AI 가 만든 재배 프로그램 %d 건이 있어 downgrade 할 수 '
                '없습니다. 내보내거나 삭제한 뒤 다시 시도하세요.' % user_rows)
        op.drop_table(_TABLE)
