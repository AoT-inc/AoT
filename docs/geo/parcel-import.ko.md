# 필지 가져오기

한국 토지 데이터(VWorld)를 사용해 부지 경계를 지도 위에 빠르게 가져오는 기능입니다. 폴리곤을 직접 그리는 대신, 주소 검색이나 CSV 파일로 정확한 지적 경계를 즉시 생성할 수 있습니다.

---

## 사전 조건

VWorld API 키가 등록되어 있어야 합니다.

1. `/geo/layer` 에서 VWorld 레이어 추가
2. 기어 아이콘 → API Key 입력 → Save
3. Activate

---

## 가져오기 창 열기

1. `/geo/design` 으로 이동합니다.
2. 지도 아래 모드 바에서 **Site** 모드로 전환합니다.
3. Site 설정 드로어에서 **Add from Address** 옆의 **Search** 버튼을 클릭합니다.

그러면 **Import Site by Address** 창이 열리는데, 여기에는 **Address Input**과 **CSV Batch** 두 탭이 있습니다.

---

## 주소로 가져오기 (Address Input)

1. 주소를 입력합니다 (예: `서울시 강남구 역삼동 808`). 콤마로 구분해 여러 개를 한 번에 넣거나, **Add Address** 버튼으로 입력란을 늘릴 수 있습니다.
2. **Search** 버튼을 클릭합니다.
3. 찾은 필지가 아래 미리보기 목록에 나타나고 지도 위에도 경계가 그려집니다. 실패한 항목은 사유와 함께 표시됩니다.

---

## CSV 일괄 가져오기 (CSV Batch)

여러 필지를 한 번에 가져올 때 사용합니다.

### CSV 파일 형식

주소만 한 줄에 하나씩, **첫 번째 열**에 넣습니다. 헤더 행도, 이름 열도 없습니다 — 다른 열이 있어도 무시되며, 가져온 각 Site의 이름은 주소 자체(또는 저장 시 **Site Name** 필드)에서 옵니다.

```csv
경기도 화성시 송산면 고정리 123
경기도 화성시 송산면 고정리 124
경기도 수원시 권선구 입북동 456
```

### 가져오기 방법

1. **CSV Batch** 탭에서 CSV 파일을 선택합니다.
2. **Upload and Process** 버튼을 클릭합니다.
3. 결과는 주소 검색과 같은 미리보기 목록에 나타납니다 — 성공한 필지는 ✓, 실패한 주소는 사유와 함께.

---

## 확인 후 저장

두 탭 모두 아래 미리보기 영역을 공유합니다.

- **Merge Adjacent Parcels** (체크박스, 기본 꺼짐) — 미리보기에서 서로 맞닿은 폴리곤을 turf.js로 하나의 Site로 합쳐서 저장합니다. 꺼두면 미리보기의 각 필지가 각자 별도 Site로 저장됩니다.
- **Site Name** — 첫 결과 이름으로 자동 채워집니다(여러 건이면 "+ N개"가 붙음). 저장 전 수정할 수 있습니다. 병합하지 않은 여러 필지를 저장할 때는(결과가 정확히 1건이 아닌 한) 이 필드 대신 각 필지가 자신의 이름으로 저장됩니다.
- **Save as Site** — 미리보기의 모든 필지(또는 병합된 결과 하나)를 저장합니다.

저장 후 상태줄에 **saved**(저장됨) · **already imported**(이미 가져옴, 아래 참조) · **failed**(실패) 건수가 각각 표시됩니다.

!!! note "같은 필지를 두 번 가져와도 중복 생성되지 않습니다"
    현재 지도에 같은 기하(geometry)의 Site가 이미 있으면, 다시 저장을 시도해도 오류가 아니라 건너뛰기로 처리되고 "이미 가져옴"으로 따로 집계됩니다.

저장된 필지는 `Site` 타입 GeoShape이며, 손으로 그린 Site 피처와 동일하게 편집할 수 있습니다.

---

## API 직접 사용

자동화 스크립트에서 필지 가져오기를 호출하는 경우 REST API를 사용합니다. 위 화면 UI도 결국 아래 세 엔드포인트를 그대로 부르는 얇은 클라이언트입니다.

### 주소로 가져오기

```http
POST /api/geo/parcel/from_address
Content-Type: application/json

{
  "address": "경기도 화성시 송산면 고정리 123"
}
```

응답:
```json
{
  "ok": true,
  "feature": {
    "type": "Feature",
    "geometry": { "type": "Polygon", "coordinates": [[[...], ...]] },
    "properties": { "name": "..." }
  },
  "name": "경기도 화성시 송산면 고정리 123",
  "pnu": "4159025300100230000"
}
```
실패 시: `{"ok": false, "error": "..."}`.

### CSV 일괄 가져오기

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV 파일, 한 줄에 주소 하나, 첫 번째 열만 사용>
```

응답:
```json
{
  "ok": true,
  "features": [ /* 성공한 주소마다 GeoJSON Feature 하나씩 */ ],
  "names": [ "..." ],
  "errors": [ "<주소>: <사유>", "..." ]
}
```

### 부지로 저장

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "feature": { "type": "Feature", "geometry": { "type": "Polygon", "coordinates": [...] }, "properties": {} },
  "name": "1번 온실 부지",
  "map_uuid": "<지도 UUID>"
}
```

`map_uuid` 는 실제로 존재하는 지도여야 합니다. 같은 지도에 같은 기하의 Site가 이미 있으면, 새로 만드는 대신 `409` 와 함께 `{"ok": false, "duplicate": true, "shape_id": ..., "existing_name": "..."}` 를 돌려줍니다.

---

## 참고사항

- VWorld PNU(필지번호) API를 사용하므로 국내 주소만 지원합니다.
- 주소 인식 실패 시 지번 주소와 도로명 주소를 모두 시도해보세요.
- 대규모 CSV 가져오기(100개 이상)는 각 행마다 VWorld 조회가 따로 일어나 처리 시간이 걸릴 수 있습니다.
- 가져온 필지는 일반 Site 피처와 동일하게 편집 가능합니다.

---

## 관련 페이지

- [디자인 도구](design-tool.md) — Site 모드 수동 그리기
- [GIS 레이어](layers.md) — VWorld API 키 등록
