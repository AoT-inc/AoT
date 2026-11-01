# coding=utf-8
"""field_twin — 노지 구획 디지털트윈 (계약 docs/design/digital-twin.md §10).

- `model.FieldBucketModel`: FAO-56 이중 작물계수 + 3층 버킷 물 수지(계약 §10.7 인터페이스).
- `enkf.FieldEnKF`: 상태·토양 파라미터·센서 보정 증강 EnKF 동기화.
- `validity`: 동화 전 센서 유효성 검사(계약 §10.5).
- `forcing`: 일 격자 비·ET0 묶기(출처는 부르는 쪽이 고른다).

실험 단계 — 공개하지 않는다(계획서 §7-4). 화면·MCP 에 연결하지 않았다.
"""
from .model import MODEL_REV, FieldBucketModel  # noqa: F401
from .enkf import FieldEnKF  # noqa: F401
from .params import CROPS, TEXTURES, FieldPrior, SensorSpec, nearest_texture  # noqa: F401
