# coding=utf-8
"""지도 점 마커(장치 위치 점)의 GeoShape.type 어휘 — 정본 하나.

의존이 없는 잎 모듈이라 모델·geo 패키지·스크립트 어디서든 순환 없이 가져온다.
SQL(트리거 DDL, alembic) 안의 리터럴은 상수화 대상이 아니다 — 거기서는 이
모듈을 가리키는 주석만 둔다.

@phase active
@stability stable
"""

#: 저장할 때 쓰는 마커 종류 하나.
MARKER_TYPE = 'aot_device'

#: 점 마커로 취급하는 GeoShape.type 전부 — 뒤의 'device' 는 레거시 행.
MARKER_TYPES = (MARKER_TYPE, 'device')
