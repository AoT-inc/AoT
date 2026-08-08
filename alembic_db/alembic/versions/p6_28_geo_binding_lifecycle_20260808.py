# coding=utf-8
"""P6-28: GB-3·GB-4 — 바인딩 수명 연쇄를 DB 가 강제한다 (Phase C).

장치가 사라지거나 공간 요소가 사라지면 현재 바인딩은 끝나야 한다. 앱 계층
(`device_binding.end_all_for_device`)이 이미 그 일을 하고 삭제 경로 17곳이
전부 그 문을 지나가지만, 그것만으로는 부족하다.

이유는 이 도메인이 이미 한 번 겪었다. `geo_shape.device_id` 는 "지우는 쪽이
알아서 정리한다"는 규약이었는데, 정책이 6갈래인 채 진입점이 17곳이라 실제로
도형을 건드리는 곳은 4곳뿐이었고 나머지 13곳으로 지운 장치의 도형은 아무
에러 없이 남았다. **아무도 그 사실을 몇 주씩 몰랐다.** 원시 SQL·bulk
delete·진단 일괄 삭제는 앱 규약을 아예 통과하지 않는다.

적용 내용:
  GB-3  장치 삭제(7개 테이블) → 그 장치의 현재 바인딩 전부 'device_deleted'
  GB-4  geo_shape 삭제 → 그 도형의 현재 바인딩 'spatial_deleted'
        geo_facility 삭제 → 그 시설의 fitting/actuator/sensor_role/weather
        바인딩 'spatial_deleted'

**트리거는 도형을 지우지 않는다.** 그건 정책(마커는 지우고 구역 폴리곤은
미배정 슬롯으로 남긴다)이고 게이트웨이의 몫이다 — 정책을 DB 에 넣으면
정책을 바꿀 때마다 마이그레이션이 필요해진다. 트리거가 지키는 것은
불변식 하나: **현재 바인딩이 존재하지 않는 것을 가리키는 일은 없다.**

DDL 본문은 aot/databases/geo_integrity_ddl.py(단일 정본, 여기서 import),
설계는 docs/design/geo-device-binding.md, 차단 검증은
aot/tests/geo/test_geo_invariants_attack.py.

멱등: `apply_binding()` 이 DROP IF EXISTS 후 CREATE 하므로 두 번 돌려도
안전하다. GB-1·GB-2 도 함께 재적용된다(같은 목록).

Revision ID: p6_28_geo_binding_lifecycle_20260808
Revises: p6_27_geo_binding_20260808
Create Date: 2026-08-08
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = 'p6_28_geo_binding_lifecycle_20260808'
down_revision = 'p6_27_geo_binding_20260808'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

TABLE = 'geo_binding'

GB3_TRIGGERS = [
    'geo_itg_gb3_input', 'geo_itg_gb3_output', 'geo_itg_gb3_pid',
    'geo_itg_gb3_trigger', 'geo_itg_gb3_conditional',
    'geo_itg_gb3_custom_controller', 'geo_itg_gb3_function',
]
GB4_TRIGGERS = ['geo_itg_gb4_shape', 'geo_itg_gb4_facility']


def _apply_binding():
    """DDL 정본. import 실패 시 조용히 건너뛰지 않는다 — 불변식 없이
    통과하면 보호 없이 돌아가는 서버가 생긴다(p6_27 과 같은 방식)."""
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
        # p6_27 이 만들어 뒀어야 한다. 없으면 적용할 대상이 없다.
        logger.warning('P6-28: %s 없음 — GB-3·GB-4 미적용.', TABLE)
        return

    apply_binding = _apply_binding()
    if apply_binding(bind):
        logger.info('P6-28: GB-3·GB-4 적용 완료(GB-1·GB-2 재적용 포함).')
    else:
        logger.warning('P6-28: 불변식 미적용.')


def downgrade():
    bind = op.get_bind()
    for name in GB3_TRIGGERS + GB4_TRIGGERS:
        bind.exec_driver_sql('DROP TRIGGER IF EXISTS %s' % name)
