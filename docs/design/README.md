# 설계 문서 색인

`docs/design/` 은 작업 문서다. 매뉴얼(`docs/*.md`)에 포함되지 않으며 mkdocs 빌드에서 제외된다.
각 문서는 결정과 그 이유를 남기기 위해 있고, 상단에 상태(초안·확정·구현 완료)를 적는다.
새 문서를 만들면 여기에 한 줄을 추가한다. 전체 그림은 루트 [ARCHITECTURE.md](../../ARCHITECTURE.md).

## 공간·지도

- [geo-data-integrity.md](geo-data-integrity.md) — 지도 데이터 불변식 카탈로그(I1~I12)와 강제 계층
- [geo-device-binding.md](geo-device-binding.md) — 공간(고정 자산)과 장치(유동 자산)의 소유 방향 역전
- [geo-device-area-split.md](geo-device-area-split.md) — 장치 담당 구역 나누기
- [geo-device-placement-ui-contract.md](geo-device-placement-ui-contract.md) — geo/design 장치 추가·배치 UI 계약
- [geo-map-load-visibility.md](geo-map-load-visibility.md) — geo/design 로딩 시 표시 상태와 화면 최대화
- [geo-plot-instance.md](geo-plot-instance.md) — 공간 구획(GeoPlot): 프로그램이 적용되는 인스턴스 계층
- [geo-vegetation-planting.md](geo-vegetation-planting.md) — 식생 구획(작기): 짧게 살고 겹치는 공간 단위
- [program-layer.md](program-layer.md) — 관리 프로그램(GeoProgram): 대상 종류별 단계·목표·자원 템플릿
- [coordinator-plot-targets.md](coordinator-plot-targets.md) — 코디네이터가 구획에서 목표를 가져온다
- [map-modal-ia.md](map-modal-ia.md) — 지도 모달 정보 구조 통일
- [map-site-summary.md](map-site-summary.md) — 지도 site 요약 팝업과 summary API
- [map-widget-modal-decomposition.md](map-widget-modal-decomposition.md) — 지도 위젯 `loadGeoJSONLayers` 분해
- [maplibre-version-policy.md](maplibre-version-policy.md) — MapLibre 4·5 병행 정책

## 장치·연결

- [device-tier.md](device-tier.md) — 복합장치(Device) 1급 엔티티 설계
- [device-onboarding.md](device-onboarding.md) — 장치 온보딩: 목록에서 고르기를 폴백으로
- [plc-modbus-integration.md](plc-modbus-integration.md) — PLC(Modbus TCP) 연동
- [lorawan_power_reliability_plan.md](lorawan_power_reliability_plan.md) — LoRaWAN 밸브 제어: 배터리 절감과 명령 신뢰성
- [battery_optimization_report.md](battery_optimization_report.md) — 모바일 배터리 최적화 보고

## 제어

- [env-coordinator-settings-redesign.md](env-coordinator-settings-redesign.md) — 통합환경제어 설정 화면 재설계
- [sensor-freshness-and-control-cadence.md](sensor-freshness-and-control-cadence.md) — 센서 신선도와 제어 주기
- [measurement_range_plan.md](measurement_range_plan.md) — 측정값 안전·위험 범위
- [timer-counter-integration-plan.md](timer-counter-integration-plan.md) — 타이머와 on/off 카운터 통합
- [scheduler-process-separation.md](scheduler-process-separation.md) — 스케줄러 프로세스 분리

## AI·MCP

- [ai-agent-loop.md](ai-agent-loop.md) — 단일 에이전트 루프 재설계
- [ai-tool-architecture.md](ai-tool-architecture.md) — AI 도구 표면: 해소·질의·표면의 분리
- [ai-library-redesign.md](ai-library-redesign.md) — AI 라이브러리(통합 지식 저장소) 재설계

## 시간

- [timezone-management.md](timezone-management.md) — 통합 시간 관리 설계
- [timezone_audit.md](timezone_audit.md) — 전역 시간 처리 점검 보고

## UI·디자인 시스템

- [ui-guide.md](ui-guide.md) — 디자인 시스템: 에센스에서 화면까지(정본)
- [color-system.md](color-system.md) — 색상 시스템과 `settings/custom_ui` 연동
- [typography-scale.md](typography-scale.md) — 손가락 화면의 기준 글자 크기
- [z-index-system.md](z-index-system.md) — z-index 체계
- [widget-conventions.md](widget-conventions.md) — 새 위젯을 만들 때 지킬 다섯 가지
- [widget-uiux-unification-plan.md](widget-uiux-unification-plan.md) — 위젯 UI/UX 통일 계획
- [widget_style_cleanup_plan.md](widget_style_cleanup_plan.md) — 위젯 스타일 정리 계획
- [widget_typography_plan.md](widget_typography_plan.md) — 위젯 텍스트 톤앤매너 통일
- [dataviz-primitives.md](dataviz-primitives.md) — 데이터 시각화 프리미티브(밴드 바·불릿·기간 바)
- [user-string-live-translation.md](user-string-live-translation.md) — 사용자 지정 문자열 실시간 번역

## 권한·시스템

- [access-scope-groups.md](access-scope-groups.md) — 그룹 기반 접근 권한: 역할 × 그룹

## 배포·검사

- [docker-auto-update.md](docker-auto-update.md) — Docker 배포판 업데이트
- [docker-image-publishing-pipeline.md](docker-image-publishing-pipeline.md) — 도커 이미지 발행 파이프라인
- [e2e-testing.md](e2e-testing.md) — E2E(종단) 검사 하네스

## 개발 과정 기록

- [subagent_skill_failure_analysis.md](subagent_skill_failure_analysis.md) — 서브에이전트·스킬 세션 오작동 원인 분석
