# Notes 및 장치 메모 (Notes & Device Notes)

최종 업데이트: 2026-02-02
AoT 버전: 26.0.1

AoT 시스템은 각 기기, 센서, 컨트롤러 및 시스템 전반에 대한 메모(Notes)를 관리할 수 있는 통합 시스템을 제공합니다. 이 문서는 노트 시스템의 구조와 사용법, 그리고 개발자를 위한 API 정보를 포함합니다.

## 1. 주요 기능 및 특징

- **통합 관리**: 시스템 전역 또는 특정 장치(Input, Output, Function 등)에 귀속된 노트를 관리합니다.
- **GPS 연동**: 노트 생성 시 현재 위치 또는 장치의 고정 위치(`gps_lat`, `gps_lng`)를 함께 저장하여 지도상에서 확인할 수 있습니다.
- **스마트 제목**: 노트를 생성할 때 제목(`name`)을 입력하지 않거나 기본값인 경우, 본문의 첫 줄(최대 50자)을 자동으로 추출하여 제목으로 사용합니다.
- **멀티미디어 첨부**: 사진, 카메라 촬영 이미지, 일반 파일을 노트에 첨부할 수 있습니다. 파일은 `static/uploads/notes/YYYY/MM/` 경로에 UUID가 붙은 고유 파일명으로 저장됩니다.
- **태그 시스템**: `#widget`, `#system` 등 태그를 통해 노트를 분류합니다. 내부적으로 태그는 이름이 아닌 고유 UUID로 관리되며, `map_hidden` 태그를 통해 지도 표시 여부를 제어합니다.
- **전역 위젯**: `layout_default.html`에 통합된 **Notes Widget**을 통해 어느 페이지에서나 즉시 노트를 작성하고 열람할 수 있습니다.

---

## 2. 사용 가이드

### 태그 옵션

| 설정 | 설명 |
| :--- | :--- |
| 이름 | 태그의 이름입니다. 공백을 포함할 수 없습니다. |
| 이름 변경 | 태그의 이름을 변경합니다. |

### 노트 옵션

| 설정 | 설명 |
| :--- | :--- |
| 이름 | 노트의 이름(제목)입니다. |
| 사용자 지정 날짜/시간 | 현재 시간이 아닌 특정 시점의 메모를 기록할 때 사용합니다. |
| 첨부 파일 | 이미지(JPG, PNG) 및 문서 파일을 함께 저장합니다. |
| 태그 | 노트를 최소한 하나 이상의 태그와 연결합니다 (멀티 선택 가능). |
| 노트 | 본문 텍스트입니다. 마크다운 형식을 일부 지원하며 고정 폭 폰트로 표시됩니다. |

---

## 3. 개발자 가이드 (API 및 통합)

### 3.1 Notes Widget (Frontend 호출)
모든 페이지의 우측 상단 또는 특정 버튼을 통해 호출되는 React 기반 위젯입니다. 다음 이벤트를 통해 특정 장치에 대한 노트를 열 수 있습니다.

```javascript
window.dispatchEvent(new CustomEvent('open-notes', { 
  detail: { 
    targetId: 'device_unique_id', // 대상 장치의 UUID
    targetType: 'input',         // 대상 유형 (input, output, function 등)
    name: '장치 이름'             // 표시될 이름
  } 
}));
```

### 3.2 Backend API (routes_notes_api.py)
- **GET `/notes/target/<target_id>`**: 특정 대상에 할당된 모든 노트를 가져옵니다.
- **POST `/notes/create`**: 새로운 노트를 생성합니다.
  - **Data (JSON 또는 Multipart)**:
    - `note`: 메모 본문.
    - `target_id`, `target_type`: 대상 정보.
    - `tags`: 쉼표로 구분된 태그 이름 문자열 (내부에서 UUID로 변환 및 자동 생성).
    - `gps_lat`, `gps_lng`: 위치 정보.
    - `files`: 첨부 파일 (Multipart 전송 시).
- **GET `/notes/geo`**: 위치 정보(`gps_lat`, `gps_lng`)가 포함된 노트 목록을 반환합니다. 단, `map_hidden` 태그가 포함된 노트는 제외됩니다.
- **POST `/notes/toggle_map_visibility`**: 특정 노트(또는 동일 대상의 전체 노트)의 지도 표시 여부를 토글합니다 (`map_hidden` 태그 가감 방식).
- **GET `/notes/tags`**: 시스템에 등록된 모든 태그 목록(ID 및 이름)을 가져옵니다.

### 3.3 데이터베이스 모델 (Notes Table)
- `unique_id`: 노트의 고유 식별자(UUID).
- `target_id`: 장치 또는 대상의 unique_id.
- `target_type`: 대상의 종류 (site, input, output, function, etc.)
- `gps_lat` / `gps_lng`: 위치 정보 (Float).
- `note`: 실제 메모 내용 (LONGTEXT).
- `tags`: 쉼표로 구분된 태그 UUID 목록 (Text).
- `files`: 저장된 파일의 상대 경로 목록 (Text).
