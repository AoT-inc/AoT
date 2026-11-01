# coding=utf-8
"""facility_twin — 시설(온실) 디지털트윈 동기화 (계약 docs/design/digital-twin.md §3~§8, 계획서 P1).

- `model.FacilityTwinModel`: 그레이박스 v3(`env_control/greybox`) 의 ODE 를 **그대로 불러** 숨은 열질량 Tm 과
  느린 파라미터(외피 열손실 배율 θ_UA · 누기 배율 θ_leak)를 얹은 9상태 모델. 식을 복사하지 않는다(원칙 3).
- `ukf.FacilityUKF`: 측정 T·RH·CO₂ 로 9상태를 동기화하는 무향 칼만 필터(계약 §3).
- `sync.assimilate`: 이력(측정·외기·장치 명령)을 시간 격자에 올려 필터를 돌리고, 잔차·선행 오차(일치도)를 낸다.

실험 단계. 제어(코디네이터)는 이 모듈을 읽지 않는다(계약 §8).
"""
from .model import MODEL_REV, FacilityConfig, FacilityTwinModel  # noqa: F401
from .ukf import FacilityUKF  # noqa: F401
