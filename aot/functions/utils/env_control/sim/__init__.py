# coding=utf-8
"""
env_control/sim — 통합환경제어 폐루프 시뮬레이터(Phase 0).

  plant      시설 참값 모델(열·수분·CO₂ 수지 + 장치 물리). 제어기의 효과 모델과 독립.
  scenarios  외기 시나리오·고장 주입(재현 가능, 씨앗 고정).
  metrics    추적 결과 → KPI(목표 대역 체류율·고온 적산·장치 반전·결로·젖음·물·에너지).

하네스(실제 `CustomModule` 을 이 시설에 물려 돌리는 쪽)는 `aot/scripts/env_closedloop/`.
이 패키지는 제어 경로에서 import 되지 않는다 — 시험 도구다.
"""
