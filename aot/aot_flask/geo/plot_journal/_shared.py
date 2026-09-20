# coding=utf-8
"""여러 하위 모듈이 함께 쓰는 로거·상수·헬퍼(순환 임포트를 막으려고 따로 둔다)."""
import logging

logger = logging.getLogger(__name__)

#: 계약의 `caveats` 에 실어 문서 머리말에 찍는 문구 키. 번역은 화면에서 한다.
#: 값이 아니라 **키**인 이유: 문구를 여기서 한국어로 박으면 22개 로케일 중
#: 하나만 맞는 문서가 나온다.
AVG_IS_TIME_WEIGHTED = 'daily-average-is-mean-of-hourly-means'
CHANNEL_ZERO_ONLY = 'output-runtime-first-channel-only'


def resolve_target_row(target_type, target_id):
    """대상 종류+id → ORM 행. 못 찾으면 `ValueError`.

    승인 게이트(§13a)와 조립(§6)이 **같은 함수로** 대상을 찾는다 — 둘이 다른
    경로로 찾으면 "게이트는 통과했는데 조립은 대상을 못 찾는" 상태가 생긴다.
    """
    if target_type == 'plot':
        from aot.databases.models import GeoPlot
        row = GeoPlot.query.filter_by(unique_id=target_id).first()
    elif target_type in ('zone', 'site'):
        from aot.databases.models import GeoShape
        row = GeoShape.query.filter_by(unique_id=target_id).first()
    else:
        raise ValueError('알 수 없는 대상 종류: %s' % target_type)
    if row is None:
        raise ValueError('대상을 찾을 수 없습니다 (%s/%s)' % (target_type, target_id))
    return row

#: 반환 행 예산. §4-1 이 시간 버킷으로 받아 접으므로 행이 일별의 24배다.
#: 저사양 기기에서는 파이썬 쪽 접기 비용이 실제 부하라 이것도 함께 센다.
MAX_JOURNAL_ROWS = 500_000
