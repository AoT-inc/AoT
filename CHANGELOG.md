# v26.0.5 (2026-02-11)

## 버그 수정 (Bug Fixes)

### 업그레이드 시스템 (Upgrade System)
- **SSL 인증서 보존 수정**: 업그레이드 과정에서 SSL 인증서가 중첩 디렉터리(`ssl_certs/ssl_certs/ssl_certs/...`)에 잘못 배치되던 `cp -R` 버그 수정
  - `upgrade_install.sh`: SSL 인증서를 디렉터리 단위가 아닌 개별 파일로 복사하도록 변경
  - `upgrade_post.sh`: 중첩 디렉터리 자동 복구 로직 및 인증서 누락 시 자동 생성 기능 추가
  - nginx 시작 실패 방지 및 업그레이드 안정성 향상

---

# v26.0.5 (2026-02-11) - English

## Bug Fixes

### Upgrade System
- **SSL Certificate Preservation Fix**: Fixed `cp -R` bug that incorrectly placed SSL certificates in nested directories (`ssl_certs/ssl_certs/ssl_certs/...`) during upgrades
  - `upgrade_install.sh`: Changed to copy SSL certificates as individual files instead of directory
  - `upgrade_post.sh`: Added automatic nested directory recovery logic and certificate auto-generation if missing
  - Prevents nginx startup failures and improves upgrade stability

---

# v26.0.4 (2026-02-11)

## 성능 및 안정성 개선 (Stability & Performance)

### 데이터베이스 시스템 (Database System)
- **자동 DB 동기화 강화**: 애플리케이션 시작 시 데이터베이스 스키마를 자동으로 검사하고 최신 버전으로 마이그레이션하는 기능을 활성화했습니다. 수동 업데이트 시 발생할 수 있는 스키마 불일치 문제를 방지합니다.

### UI/UX 개선 (UI/UX Enhancements)
- **업그레이드 페이지 개선**: 업그레이드 진행 상황 페이지의 레이아웃을 확장(`container-fluid`)하고 가독성을 개선했습니다.
- **업그레이드 안정성 강화**: 업그레이드 도중 서버 재시작으로 인한 세션 끊김(로그인 페이지 리다이렉트) 발생 시 이를 감지하여 안내 메시지를 표시하도록 개선했습니다.
- **상태 표시 최적화**: 업그레이드 중에는 데몬 상태와 무관하게 로고를 빨간색으로 유지하여 작업 진행 상황을 명확히 알립니다.

---

# v26.0.4 (2026-02-11) - English

## Stability & Performance

### Database System
- **Enhanced Auto DB Sync**: Enabled automatic database schema checks and migrations on application startup. Prevents schema inconsistency issues that can occur during manual updates.

### UI/UX Enhancements
- **Improved Upgrade Page**: Expanded the layout of the upgrade progress page (`container-fluid`) and improved readability.
- **Enhanced Upgrade Stability**: Detects session disconnection (login page redirect) during upgrade due to server restart and displays a guidance message.
- **Optimized Status Display**: Forces the logo to remain red during updates regardless of daemon status to clearly indicate progress.

---

# v26.0.3 (2026-02-11)

## 기능 개선 (Improvements)

### 번역 시스템 (Translation System)
- **번역 관리 강화**: `glossary.json` 기반의 영구적인 번역 사전 시스템 도입. 업데이트 시 사용자 번역 유지.
- **번역 오류 수정**: `messages.po`의 오역 대거 수정 (Acceleration -> 가속 등).

### UI 개선 (UI Enhancements)
- **시퀀스 컨트롤러 위젯**:
    - **레이아웃 개선**: 헤더 정보 간소화 및 가독성 향상.
    - **접기/펼치기**: 세부 설정 영역을 접을 수 있는 UI 적용.
    - **모바일 대응**: 좁은 화면에서의 컬럼 정렬 및 스크롤 최적화.

### 버그 수정 (Fixes)
- **시퀀스 위젯 설정 (Sequence Widget Settings)**: 'Sequence Function' 선택 시 모든 트리거가 표시되는 문제 수정. 이제 `trigger_sequence` 타입만 올바르게 필터링되어 표시됩니다.
- **그리드스택 레이아웃 (GridStack Layout)**: 모바일/데스크탑 뷰 전환 시 위젯 배치가 깨지는 현상 수정. 이제 데스크탑 레이아웃이 정확하게 복원됩니다.
- **함수 관리 (Function Management)**: 함수 복제 및 삭제 실패 문제 해결.

### UI 모던화 (UI Modernization)
- **공통 모달 디자인 (Common Modal Design)**: `aot-modal-modern.css` 기반의 통합 디자인 시스템 적용. 타이포그래피, 입력 필드, 버튼 스타일 개선.
- **모바일 노트 입력 (Mobile Note Input)**: 키보드 입력 시 화면 밀림 및 줌 현상 방지를 위한 `Aggressive Body Lock` 및 `Anti-Zoom` 적용.

---

# v26.0.3 (2026-02-11) - English

## Improvements

### Translation System
- **Enhanced Management**: Introduced `glossary.json` based persistent translation dictionary. Custom translations are preserved during updates.
- **Translation Fixes**: Corrected numerous mistranslations in `messages.po`.

### UI Enhancements
- **Sequence Controller Widget**:
    - **Layout Improvements**: Simplified header info and improved readability.
    - **Collapsible Settings**: Added collapsible UI for detailed settings.
    - **Mobile Optimization**: Optimized column alignment and scrolling for narrow screens.

### Bug Fixes
- **Sequence Widget Settings**: Fixed issue where all triggers were shown when selecting 'Sequence Function'. Now correctly filters only `trigger_sequence` types.
- **GridStack Layout**: Resolved widget layout corruption issues when switching between mobile and desktop views. Desktop layout now restores accurately.
- **Function Management**: Fixed failures in function duplication and deletion.

### UI Modernization
- **Common Modal Design**: Applied unified design system based on `aot-modal-modern.css`. Improved typography, input fields, and button styles.
- **Mobile Note Input**: Implemented `Aggressive Body Lock` and `Anti-Zoom` to prevent screen shifting and zooming during keyboard input on mobile.

---


---

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
