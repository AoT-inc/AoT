# v26.0.1 (2026-02-10)

## 기능 (Features)

### 지오 시스템 (Geo System)
- **Geo Design**: 다양한 지도 유형, 데이터 추출, 도형 그리기 및 장치 배치 기능 추가.
- **Geo Input**: 지도상의 입력 장치 통합 강화.
- **Geo Setting**: 포괄적인 지도 설정 옵션.
- **AoT_map Widget**:
    - 사용자 지도 표시 관리.
    - 지도를 통한 입력, 출력, 함수 제어 및 상태 표시.
    - 노트 추가 기능.
    - **장치 도형 투명도**: 장치 도형의 투명도(0-100%) 설정 추가.
    - **지도 잠금 유지**: 지도 잠금 상태가 세션 간에 유지되도록 개선.
    - **토글 스위치 UI**: 장치 제어에 현대적인 토글 스위치 UI 적용.
    - **알약 스타일 마커**: 고대비 텍스트 라벨이 적용된 개선된 장치 마커.

### 노트 시스템 (Note System)
- **장치 노트**: 특정 입출력 및 함수 장치에 대한 노트 작성 기능 추가.
- **지도 노트**: 지도상 특정 좌표에 노트 배치 가능.
- **카드 페이지**: 노트 관리 및 조회를 위한 전용 페이지.
- **위젯 통합**: 지도 위젯과 노트 시스템 연동.

## 미구현 기능
- **관수 로직**: 유량은 단순히 지도위의 도형의 수량을 기준으로 산출되고 있으며, 코어 로직과 연동되지 않고 있습니다.
- **geo/design 설비**: 펌프, 밸브 등 설비에 대한 상세 하위 카테고리.  

## 버그 (Bugs)
- **지도 렌더링**:
    - `Trigger` 및 `Trigger: Sequence` 옵션에서 전역 지도 설정이 적용되지 않던 "회색 지도" 및 Nominatim 418 오류 수정.
    - 모달 지도 초기화 시 경쟁 상태(Race condition)로 인한 렌더링 실패 수정.

## 예정 사항 (Upcoming)
- **관수 로직**: `geo/design`에 생성된 장치를 기반으로 관수량 계산 및 오작동 추적 로직.
- **Geo Design 상세화**: 시설 장비(펌프, 밸브 등)에 대한 상세 하위 카테고리.

---

# v26.0.1 (2026-02-10) - English

## Features

### Geo System
- **Geo Design**: Added various map types, data extraction, shape drawing, and device placement capabilities.
- **Geo Input**: Enhanced input device integration on maps.
- **Geo Setting**: Comprehensive map configuration options.
- **AoT_map Widget**:
    - Custom user map display management.
    - Input, Output, Function display and control directly on the map.
    - Note addition capability.
    - **Device Shape Opacity**: Added setting to control transparency of device shapes (0-100%).
    - **Map Lock Persistence**: Map lock state is now saved across sessions.
    - **Toggle Switch UI**: Modernized device control with toggle switches.
    - **Pill Style Markers**: Improved device markers with high-contrast text labels.

### Note System
- **Device Notes**: Added note-taking capability for specific Input, Output, and Function devices.
- **Map Notes**: Ability to place notes at specific coordinates on the map.
- **Card Page**: Dedicated page for managing and viewing notes.
- **Widget Integration**: Notes system integrated with map widgets.

## Unimplemented Features
- **Irrigation Logic**: Flow rate is currently calculated simply based on the quantity of shapes on the map and is not linked to the core logic.
- **geo/design Facilities**: Detailed sub-categories for facility equipment such as pumps and valves.

## Bugs

- **Map Rendering**:
    - "Gray Map" issue in `Trigger` and `Trigger: Sequence` options where global map settings were not applying (Nominatim 418 error resolved).
    - Race conditions in modal map initialization causing rendering failures.

## Upcoming
- **Irrigation Logic**: Logic for calculating irrigation amounts and tracking malfunctions based on devices created in `geo/design`.
- **Geo Design Detail**: Detailed sub-categories for facility equipment (e.g., pumps, valves).
