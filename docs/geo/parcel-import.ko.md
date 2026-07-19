# 필지 가져오기

한국 토지 데이터(VWorld)를 사용해 부지 경계를 지도 위에 빠르게 가져오는 기능입니다. 폴리곤을 직접 그리는 대신, 주소 검색이나 CSV 파일로 정확한 지적 경계를 즉시 생성할 수 있습니다.

---

## 사전 조건

VWorld API 키가 등록되어 있어야 합니다.

1. `/geo/layer` 에서 VWorld 레이어 추가
2. 기어 아이콘 → API Key 입력 → Save
3. Activate

---

## 주소로 필지 가져오기

1. `/geo/design` 으로 이동합니다.
2. 상단 도구 모음에서 **필지 가져오기** 버튼을 클릭합니다.
3. 주소를 입력합니다 (예: `경기도 화성시 송산면 고정리 123`).
4. **검색** 버튼을 클릭합니다.
5. 결과 목록에서 해당 필지를 선택합니다.
6. 지도 위에 필지 경계가 미리보기로 표시됩니다.
7. **부지로 저장** 버튼을 클릭합니다.

저장하면 해당 필지 경계가 `Site` 타입 GeoShape로 생성됩니다.

---

## CSV 일괄 가져오기

여러 필지를 한번에 가져올 때 사용합니다.

### CSV 파일 형식

```csv
address,name
경기도 화성시 송산면 고정리 123,1번 온실 부지
경기도 화성시 송산면 고정리 124,2번 온실 부지
경기도 수원시 권선구 입북동 456,관리동 부지
```

필드:
- `address` (필수): 도로명 또는 지번 주소
- `name` (선택): 부지 이름. 없으면 주소 문자열이 이름으로 사용됩니다.

### 가져오기 방법

1. `/geo/design` 상단 도구에서 **필지 가져오기 → CSV 가져오기** 선택
2. CSV 파일을 선택하거나 드래그앤드롭합니다.
3. 미리보기 테이블에서 데이터를 확인합니다.
4. 오류가 있는 행은 빨간색으로 표시됩니다 (주소 미인식).
5. **가져오기** 버튼을 클릭합니다.

처리 결과가 표시됩니다:
- 성공: Site 피처 생성 완료
- 실패: 주소 검색 실패 (주소 표기 확인 필요)

---

## API 직접 사용

자동화 스크립트에서 필지 가져오기를 호출하는 경우 REST API를 사용합니다.

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
  "pnu": "4159025300100230000",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[...], ...]]
  },
  "address": "경기도 화성시 송산면 고정리 123",
  "area_m2": 3256.7
}
```

### CSV 일괄 가져오기

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV 파일>
```

### 부지로 저장

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "geo_id": "<지도 UUID>",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "name": "1번 온실 부지"
}
```

---

## 참고사항

- VWorld PNU(필지번호) API를 사용하므로 국내 주소만 지원합니다.
- 주소 인식 실패 시 지번 주소와 도로명 주소를 모두 시도해보세요.
- 대규모 CSV 가져오기(100개 이상)는 처리 시간이 걸릴 수 있습니다.
- 가져온 필지는 일반 Site 피처와 동일하게 편집 가능합니다.

---

## 관련 페이지

- [디자인 도구](design-tool.md) — Site 모드 수동 그리기
- [GIS 레이어](layers.md) — VWorld API 키 등록
