# coding=utf-8
"""P6-11: 복합장치(Device) 티어 — 상위 장치 소속 컬럼 신설.

복합 기능을 가진 단독 장치(PLC, 관수 제어기, 양액기 등)를 AoT에서 한 단위로
다루기 위한 뼈대. 장치 자체는 새 테이블이 아니라 기존 CustomController 행으로
표현한다 — 그 모델이 이미 위치값(latitude/longitude/timezone/map_config_id),
활성화 수명주기(is_activated), custom_options, 노트 바인딩에 쓰이는 unique_id 를
전부 갖추고 있어 장치가 요구하는 속성과 일치하기 때문이다.

이번 리비전이 추가하는 것은 "누가 이 항목을 소유하는가" 한 가지뿐이다.

  parent_device_id -> 이 항목을 자동 생성·소유하는 상위 장치의
                      CustomController.unique_id (NULL = 독립 항목)

대상 테이블: input, output, function, custom_controller

FK 제약을 걸지 않은 이유: 부모가 custom_controller 이고 자식도 같은 테이블일 수
있어(장치 안의 하위 Function) 자기참조가 생기며, 5개 컨트롤러 테이블에 걸친 다형
참조라 단일 FK로 표현되지 않는다. 부모 삭제 시 자식 정리는 애플리케이션 삭제
경로가 담당한다.

전 컬럼 nullable 이라 기존 행은 손상 없이 NULL 로 남는다 — 이 리비전만으로는
동작 변화가 없고, 청사진 기반 자동 생성(Phase 2)이 붙어야 값이 채워진다.

Revision ID: p6_11_device_tier_20260728
Revises: p6_10_fix_broken_conversions_20260727
Create Date: 2026-07-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_11_device_tier_20260728'
down_revision = 'p6_10_fix_broken_conversions_20260727'
branch_labels = None
depends_on = None

_COLUMN = 'parent_device_id'
_TABLES = ('input', 'output', 'function', 'custom_controller')


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def _index_name(table):
    return 'ix_{table}_{col}'.format(table=table, col=_COLUMN)


def upgrade():
    for table in _TABLES:
        if not _has_table(table) or _has_column(table, _COLUMN):
            continue
        # SQLite 는 ALTER 로 컬럼을 붙일 때 배치 모드가 필요하다.
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.String(length=36), nullable=True))
        # 장치 상세 화면이 "이 장치의 하위 전부"를 매번 조회하므로 인덱스를 둔다.
        op.create_index(_index_name(table), table, [_COLUMN])


def downgrade():
    for table in _TABLES:
        if not _has_table(table) or not _has_column(table, _COLUMN):
            continue
        try:
            op.drop_index(_index_name(table), table_name=table)
        except Exception:
            pass
        with op.batch_alter_table(table) as batch:
            batch.drop_column(_COLUMN)
