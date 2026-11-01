# coding=utf-8
"""water_net — 지도 설비를 수원-펌프-필터-밸브-배관-노즐의 물 회로로 다루는 순수 모듈
(계획서 plans/2026-11-01_equipment_water_network_proposal.md). DB·Flask 를 import 하지 않는다.

- `parts`  부품 표(종류·묶음·정격 키·단위·라벨의 단일 출처)
- `graph`  배관 기하를 물길 그래프로(시설·지도 공용). 유량 계산은 없다
- `adapters`  시설 fitting·지도 feature → `graph.Network`
- `checks`  회로 점검 항목
- `balance`  L0 유량 수지(작동 구간 → 전달량·탱크·전력·작동 판정)
- `result`  물 결과 계약의 단일 출처, 회로 해시
"""
