# coding=utf-8
"""P6-27: geo_binding 신설 — 공간 요소와 장치를 잇는 이력 보존 관계 테이블.

고정 자산(지형·시설·구역)이 유동 자산(장치)의 uuid 를 자기 몸에 새기고 있는
것이 이 도메인의 구조적 약점이었다. 장치를 지우면 도형이 고아가 되거나 함께
사라지고, 교체하면 도형을 다시 그려야 하고, 갈면 시계열이 끊긴다. 같은 사실이
6곳(geo_shape.device_id 컬럼, feature JSON 2키, geo_facility 의 fittings·
actuators·sensors/weather_bindings)에 흩어져 있어 어느 삭제 경로도 전부를
정리하지 못했다.

이 마이그레이션은 **테이블을 만들고 불변식을 걸 뿐 아무것도 옮기지 않는다.**
백필은 별도 스크립트(aot/scripts/backfill_geo_binding.py)로 사람이 dry-run
결과를 확인한 뒤 실행한다 — 행을 만드는 일과 스키마를 바꾸는 일을 한 트랜잭션
에 섞지 않는다(2026-08-03 교훈: 데이터를 건드리는 마이그레이션은 복원 수단이
없으면 사고가 된다).

적용 내용:
  geo_binding 테이블
  GB-1a  단일 점유 슬롯(shape/fitting/actuator)의 현재 바인딩은 1개
  GB-1b  다중 점유 슬롯(sensor_role/weather)은 같은 (장치,채널,측정값) 중복만 차단
         — sensors 는 같은 role 에 여러 장치를 등록해 가중평균하는 것이 정상이라
           단일 규칙을 일괄 적용하면 정상 기능이 DB 에서 거부된다
  GB-2   수명 정합(valid_to → ended_reason 필수, valid_to >= valid_from)
         + spatial_kind/device_kind/ended_reason 어휘 화이트리스트

DDL 본문은 aot/databases/geo_integrity_ddl.py(단일 정본, 여기서 import),
설계는 docs/design/geo-device-binding.md, 차단 검증은
aot/tests/geo/test_geo_invariants_attack.py.

멱등: 두 번 돌려도 안전하다(테이블은 존재 확인 후 생성, DDL 은 DROP IF EXISTS
후 CREATE).

Revision ID: p6_27_geo_binding_20260808
Revises: p6_26_mcp_confirmation_result_20260807
Create Date: 2026-08-08
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = 'p6_27_geo_binding_20260808'
down_revision = 'p6_26_mcp_confirmation_result_20260807'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

TABLE = 'geo_binding'


def _ddl_module():
    """DDL 정본 모듈. 실패 시 조용히 건너뛰지 않고 명확히 죽는다 — 불변식
    없이 통과하면 보호 없이 돌아가는 서버가 생긴다. alembic 이 어떤 경로
    맥락에서 호출되든 동작하도록, import 실패 시 이 파일 위치에서 저장소
    루트를 역산해 sys.path 에 넣고 재시도한다(p6_22 와 같은 방식)."""
    try:
        from aot.databases.geo_integrity_ddl import apply_binding
    except ModuleNotFoundError:
        import os
        import sys
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        if root not in sys.path:
            sys.path.insert(0, root)
        from aot.databases.geo_integrity_ddl import apply_binding
    return apply_binding


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if TABLE not in insp.get_table_names():
        op.create_table(
            TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),

            # 공간 측
            sa.Column('spatial_kind', sa.String(length=16), nullable=False),
            sa.Column('spatial_id', sa.String(length=64), nullable=False),
            sa.Column('role', sa.String(length=32), nullable=False),

            # 장치 측
            sa.Column('device_kind', sa.String(length=16), nullable=False),
            sa.Column('device_id', sa.String(length=36), nullable=False),
            sa.Column('channel_id', sa.String(length=8), nullable=False,
                      server_default='0'),
            sa.Column('measurement_id', sa.String(length=36), nullable=True),

            # 수명
            sa.Column('valid_from', sa.DateTime(), nullable=False),
            sa.Column('valid_to', sa.DateTime(), nullable=True),
            sa.Column('ended_reason', sa.String(length=16), nullable=True),

            sa.Column('params', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),

            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )
        op.create_index('ix_geo_binding_spatial_kind', TABLE,
                        ['spatial_kind'], unique=False)
        op.create_index('ix_geo_binding_spatial_id', TABLE,
                        ['spatial_id'], unique=False)
        op.create_index('ix_geo_binding_device_id', TABLE,
                        ['device_id'], unique=False)
    else:
        logger.info('P6-27: %s 이미 존재 — 테이블 생성 건너뜀.', TABLE)

    # GB-1·GB-2. 트리거/부분 인덱스는 batch_alter_table 로 표현할 수 없어
    # 정본 모듈의 원시 DDL 을 그대로 실행한다.
    apply_binding = _ddl_module()
    if apply_binding(bind):
        logger.info('P6-27: GB-1·GB-2 적용 완료.')
    else:
        logger.warning('P6-27: %s 없음 — 불변식 미적용.', TABLE)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if TABLE not in insp.get_table_names():
        return
    for name in ('geo_itg_gb2_ins', 'geo_itg_gb2_upd'):
        bind.exec_driver_sql('DROP TRIGGER IF EXISTS %s' % name)
    for name in ('geo_itg_gb1_single_current', 'geo_itg_gb1_multi_current'):
        bind.exec_driver_sql('DROP INDEX IF EXISTS %s' % name)
    op.drop_table(TABLE)
