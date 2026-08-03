# coding=utf-8
"""P6-23: 지도 불변식 Tier-2 적용 (I6 aot_type 저장 금지 · I7 type 불변 ·
I8 유령 지도 금지).

Tier-1(p6_22)이 삭제·복제 계열을 봉인했다면, Tier-2 는 재분류·드리프트
계열을 봉인한다. 게이팅 조건이었던 앱 수정(S4)은 이 리비전과 같은
배포에 포함된다: 서버가 저장 직전 properties.aot_type 을 제거하고,
/delta 가 기존 행을 클라이언트 aot_type 으로 재분류하지 않으며, 필지
가져오기가 실존 지도를 요구한다.

사전 정리는 1건뿐이다:
  1) 저장된 aot_type 제거 — 기존 행의 feature JSON 최상위
     properties.aot_type 을 json_remove 로 걷어낸다. 종류의 정본은 type
     컬럼이고(p6_21 이 이미 정합), 읽기 시 get_overlays 가 주입한다.
     equipment_collection 번들의 '자식' 피처는 DB 행이 없어 JSON 이 유일한
     정체성이므로 건드리지 않는다(경로가 최상위만 가리킨다).

유령 지도 도형(geo_id 가 어떤 GeoMap 도 가리키지 않는 행)은 여기서
**지우지 않는다.** 트리거는 INSERT/UPDATE 만 검사하므로 기존 행을 두고도
I8 을 켤 수 있고(신규 유령만 차단), "도달 불가능한 누수"라는 판단은
위험하다 — get_overlays 는 GeoMap 존재를 확인하지 않아 위젯에 저장된
낡은 map_uuid 로 여전히 렌더링될 수 있다(리허설에서 aot-005 도형 66% 가
삭제 대상으로 잡히며 발각). 기존 유령은 check_geo_integrity 의
phantom-map 항목으로 보고만 하고 사람이 판단한다.

이후 TIER2_STATEMENTS 를 적용한다. 멱등.

Revision ID: p6_23_geo_integrity_tier2_20260803
Revises: p6_22_geo_integrity_tier1_20260803
Create Date: 2026-08-03
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = 'p6_23_geo_integrity_tier2_20260803'
down_revision = 'p6_22_geo_integrity_tier1_20260803'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')


def _ddl_module():
    try:
        from aot.databases.geo_integrity_ddl import TIER2_STATEMENTS
    except ModuleNotFoundError:
        import os
        import sys
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        if root not in sys.path:
            sys.path.insert(0, root)
        from aot.databases.geo_integrity_ddl import TIER2_STATEMENTS
    return TIER2_STATEMENTS


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'geo_shape' not in insp.get_table_names():
        logger.info('P6-23: geo_shape 없음 — 건너뜀.')
        return

    # ── 1) 저장된 aot_type 제거 ────────────────────────────────────────
    res = bind.execute(sa.text(
        "UPDATE geo_shape SET feature = json_remove(feature,"
        " '$.properties.aot_type') "
        "WHERE json_extract(feature, '$.properties.aot_type') IS NOT NULL"))
    logger.info('P6-23: 저장된 aot_type %s건 제거 (읽기 시 type 컬럼에서'
                ' 주입).', res.rowcount)

    # ── 2) 유령 지도 도형은 보고만 한다 (삭제 금지 — docstring 참조) ────
    live_maps = {r[0] for r in bind.execute(
        sa.text('SELECT unique_id FROM geo_map'))}
    phantom_ids = {}
    for r in bind.execute(sa.text('SELECT geo_id FROM geo_shape')):
        if r[0] not in live_maps:
            phantom_ids[r[0]] = phantom_ids.get(r[0], 0) + 1
    if phantom_ids:
        logger.warning('P6-23: 유령 지도 도형 존재 — 삭제하지 않음. '
                       'check_geo_integrity 의 phantom-map 항목으로 확인 후 '
                       '사람이 판단할 것: %s', phantom_ids)

    # ── 3) Tier-2 DDL 적용 (기존 유령 행이 있어도 신규만 차단) ──────────
    for stmt in _ddl_module():
        bind.exec_driver_sql(stmt)
    logger.info('P6-23: Tier-2 트리거 적용 완료 — aot_type 저장·type 재분류·'
                '유령 지도는 이제 표현 불가능하다 (GEO-I6/I7/I8).')


def downgrade():
    """Tier-2 트리거만 제거한다. aot_type 제거는 되돌리지 않는다 —
    읽기 시 get_overlays 가 type 컬럼에서 주입하므로 정보 손실이 없다."""
    bind = op.get_bind()
    for stmt in _ddl_module():
        if stmt.startswith('DROP '):
            bind.exec_driver_sql(stmt)
