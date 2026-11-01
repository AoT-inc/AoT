# coding=utf-8
"""twin_effects — 장치 작동 → 트윈 효과의 공통 틀 (설계서 plans/2026-10-25_twin_actuator_effects_design.md).

- `catalog`   효과 목록표(순수 데이터, 노드 import 안전)
- `aggregate` 같은 채널의 여러 장치를 하나의 채널 값으로 합침(env_control 의 환기 용량 코드를 재사용)
"""
