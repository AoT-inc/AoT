# coding=utf-8
"""aot_twin — 디지털트윈 서비스 (실험 · '준비 중' 기능, 기본 꺼짐 — 설정 > 일반 > 디지털트윈).

계획서: AoT_dev/plans/2026-10-19_digital_twin_plan.md §4 · 계약: docs/design/digital-twin.md
설계: docs/design/digital-twin-node.md

이 패키지는 import 시점에 flask·DB·Influx 를 끌어오지 않는다(원격 노드는 AoT 서버 없이 돈다).
내장 통로(`sources.embedded`)만 필요할 때 지연 import 한다.
"""
