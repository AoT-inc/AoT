# coding=utf-8
"""P6-29: GB-5 — feature JSON 의 device_id/channel_id 사본을 봉인한다 (Phase C).

어느 장치인지의 정본은 `geo_binding` 이고, 읽을 때 `get_overlays` 가 리졸버
값을 주입한다. 그런데 같은 사실이 `feature.properties` 에도 사본으로 저장돼
있어, 두 값이 갈리면 어느 쪽이 맞는지 아무도 말할 수 없었다.

사본이 위험한 이유는 갈리는 것 자체가 아니라 **되살아나는 것**이다. 도형을
복제하거나 옛 페이로드를 되돌려보내면 죽은 장치 참조가 JSON 을 타고 새 행에
그대로 실린다 — `clone_map_config` 가 정확히 그 방식으로 도형 98개를
오염시켰고, 6일 뒤 "시설이 지도에서 사라짐"으로 표면화됐다(2026-07-28).

I6(aot_type)과 같은 처방이다: 검사하는 게 아니라 **표현 불가능하게** 만든다.

적용 내용:
  1. 기존 행의 `properties.device_id`/`channel_id` 제거 (컬럼 값은 그대로 둔다 —
     그쪽이 폴백의 근거이고 아직 살아 있다)
  2. GB-5 트리거 (INSERT / UPDATE OF feature 양쪽)

**`properties.unique_id` 는 건드리지 않는다**(GB-5b, 별도 게이팅). 그 키는
사본이 아니라 프런트가 엔트리를 식별하는 계약이라(채널 0 = 장치 uuid, 그 외
'uuid::N'), 서버가 조용히 비우면 지도·위젯의 엔트리 식별이 통째로 깨진다.

데이터를 건드리는 마이그레이션이므로 순서가 중요하다: **정리를 먼저 하고
트리거를 건다.** 반대로 하면 정리 UPDATE 자체가 트리거에 막힌다.

Revision ID: p6_29_geo_binding_gb5_20260808
Revises: p6_28_geo_binding_lifecycle_20260808
Create Date: 2026-08-08
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = 'p6_29_geo_binding_gb5_20260808'
down_revision = 'p6_28_geo_binding_lifecycle_20260808'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

GB5_TRIGGERS = ['geo_itg_gb5_ins', 'geo_itg_gb5_upd']


def _apply_binding():
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
    if 'geo_shape' not in insp.get_table_names():
        return

    # 1) 기존 사본 제거. 트리거를 걸기 전에 해야 한다 — 걸고 나면 이
    #    UPDATE 자체가 GB-5 에 막힌다.
    #    json_remove 는 키가 없으면 원본을 그대로 돌려주므로 멱등이다.
    res = bind.exec_driver_sql(
        "UPDATE geo_shape "
        "   SET feature = json_remove(feature, '$.properties.device_id', "
        "                                      '$.properties.channel_id') "
        " WHERE json_extract(feature, '$.properties.device_id') IS NOT NULL "
        "    OR json_extract(feature, '$.properties.channel_id') IS NOT NULL")
    logger.info('P6-29: feature JSON 사본 제거 %s행', getattr(res, 'rowcount', '?'))

    # 2) 트리거. geo_binding 이 없는 설치(p6_27 이전)는 apply_binding 이
    #    조용히 건너뛰므로 GB-5 도 안 걸린다 — 그 설치는 아직 바인딩이
    #    없어 사본이 유일한 정본이니 그게 맞다.
    apply_binding = _apply_binding()
    if apply_binding(bind):
        logger.info('P6-29: GB-5 적용 완료.')
    else:
        logger.warning('P6-29: geo_binding 없음 — GB-5 미적용.')


def downgrade():
    bind = op.get_bind()
    for name in GB5_TRIGGERS:
        bind.exec_driver_sql('DROP TRIGGER IF EXISTS %s' % name)
