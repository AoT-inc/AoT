# GIS API 레퍼런스

모든 GIS API 엔드포인트는 로그인이 필요합니다. 수정이 필요한 엔드포인트는 `edit_settings` 또는 `edit_controllers` 권한이 필요합니다.

---

## 지도 디자인

### 새 디자인 초기화

```http
GET /api/geo/init_design
```

새 빈 지도 디자인을 생성하고 UUID를 반환합니다.

### 디자인 조회

```http
GET /api/geo/designs/<map_uuid>
```

저장된 지도의 전체 상태(피처, 줌, 중심 좌표, 레이어 설정)를 반환합니다.

### 디자인 목록

```http
GET /api/geo/designs
```

등록된 모든 지도 목록을 반환합니다.

### 디자인 저장

```http
POST /api/geo/designs
Content-Type: application/json

{
  "name": "메인 농장 지도",
  "lat": 37.5665,
  "lng": 126.9780,
  "zoom": 16
}
```

### 디자인 삭제

```http
DELETE /api/geo/designs/<map_uuid>
```

---

## 오버레이 (피처)

### 오버레이 목록

```http
GET /api/geo/overlays/list
```

모든 GeoShape 피처 목록을 반환합니다.

### 오버레이 로드

```http
GET /api/geo/overlays?geo_id=<map_uuid>
```

특정 지도의 모든 피처를 GeoJSON FeatureCollection으로 반환합니다.

### 오버레이 저장 (전체)

```http
POST /api/geo/overlays
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [...] },
      "properties": {
        "type": "site",
        "name": "1번 부지",
        "unique_id": "<uuid>"
      }
    }
  ]
}
```

### 델타 저장 (효율적)

전체 피처 대신 추가·수정·삭제된 피처만 전송합니다. 대용량 지도에서 성능이 향상됩니다.

```http
POST /api/geo/overlays/delta
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "added": [...],
  "modified": [...],
  "deleted": ["<uuid1>", "<uuid2>"]
}
```

---

## 시설

### 시설 목록

```http
GET /api/geo/facility/list
```

### 시설 조회

```http
GET /api/geo/facility/<facility_uuid>
```

외피 파라미터, 센서/액추에이터 바인딩, 3D 설정 포함 전체 시설 데이터를 반환합니다.

### 시설 생성/수정

```http
POST /api/geo/facility
Content-Type: application/json

{
  "unique_id": "<uuid>",
  "name": "1동 온실",
  "shape_uuid": "<geo_shape_uuid>",
  "preset": "greenhouse",
  "structure": "single",
  "bay_count": 1,
  "envelope": {
    "material": "vinyl_double",
    "bay_width_m": 8.0,
    "length_m": 50.0,
    "eave_height_m": 3.5,
    "ridge_height_m": 2.0
  },
  "sensors": [
    {
      "role": "indoor_temp",
      "device_id": "<input_uuid>",
      "measurement_id": "<measurement_uuid>",
      "name": "실내 온도 센서"
    }
  ],
  "actuators": [
    {
      "role": "heater",
      "device_id": "<output_uuid>",
      "name": "난방기"
    }
  ]
}
```

### 시설 삭제

```http
DELETE /api/geo/facility/<facility_uuid>
```

### 용량 계산 미리보기

저장하지 않고 외피 파라미터에 대한 공학 계산 결과를 반환합니다.

```http
POST /api/geo/facility/compute
Content-Type: application/json

{
  "envelope": {
    "material": "vinyl_double",
    "bay_width_m": 8.0,
    "length_m": 50.0,
    "eave_height_m": 3.5,
    "ridge_height_m": 2.0
  },
  "bay_count": 3
}
```

응답:
```json
{
  "area_m2": 1200.0,
  "volume_m3": 5400.0,
  "heating_load_kw": 42.3,
  "cooling_load_kw": 31.7,
  "forced_ventilation_m3h": 32400,
  "natural_ventilation_m3h": 15000
}
```

### 통합 상태 조회

시설 내 모든 센서·액추에이터의 현재 값을 통합하여 반환합니다.

```http
GET /api/geo/facility/<facility_uuid>/integration
```

### 런타임 상태

실시간 센서값, 액추에이터 상태, 경보 요약을 반환합니다.

```http
GET /api/geo/facility/<facility_uuid>/runtime
```

### 환기 시뮬레이션

자연환기 풍압 시뮬레이션 결과를 반환합니다.

```http
GET /api/geo/facility/<facility_uuid>/wind?wind_speed=3.5&wind_dir=270
```

### 설정 적용

시설에 바인딩된 액추에이터에 명령을 전송합니다.

```http
POST /api/geo/facility/<facility_uuid>/apply
Content-Type: application/json

{
  "actions": [
    { "role": "heater", "state": true }
  ]
}
```

---

## 커미셔닝

### 커미셔닝 시작

```http
POST /api/geo/facility/<facility_uuid>/commissioning/start
```

응답:
```json
{
  "check_id": "<uuid>",
  "status": "running"
}
```

### 커미셔닝 결과 조회

```http
GET /api/geo/facility/<facility_uuid>/commissioning/<check_id>
```

### 결과 승인/보류

```http
POST /api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict
Content-Type: application/json

{
  "device_id": "<uuid>",
  "verdict": "approved"
}
```

---

## 필지 가져오기

### 주소로 필지 조회

```http
POST /api/geo/parcel/from_address
Content-Type: application/json

{
  "address": "경기도 화성시 송산면 고정리 123"
}
```

### CSV 일괄 가져오기

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV 파일>
```

### 필지를 부지로 저장

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "name": "1번 온실 부지"
}
```

---

## 프록시 서비스

CORS 정책으로 인해 클라이언트가 직접 접근하기 어려운 외부 서비스를 AoT 서버가 중계합니다.

| 엔드포인트 | 대상 서비스 |
|-----------|------------|
| `GET /api/geo/proxy/rainviewer/*` | RainViewer 강우 레이더 |
| `GET /api/geo/proxy/isric` | ISRIC SoilGrids 토양 데이터 |
| `GET /api/geo/proxy/openweather` | OpenWeather 기상 오버레이 |
| `GET /api/geo/proxy/openmeteo` | Open-Meteo 기상 예보 |
| `GET /api/geo/proxy/wms/<unique_id>` | WMS 레이어 타일 |
| `GET /api/geo/tile_proxy` | 범용 타일 프록시 (NASA, Naver, Kakao) |

---

## 설정

### 전역 설정 조회

```http
GET /api/geo/settings
```

### 전역 설정 저장

```http
POST /api/geo/settings
Content-Type: application/json

{ ... }
```

자세한 요청 형식은 [GIS 설정](settings.md#api)을 참조하세요.

---

## 장치 목록

지도에 배치 가능한 AoT 장치 목록을 반환합니다.

```http
GET /api/geo/devices
GET /api/geo/inputs
GET /api/geo/outputs
```

---

## 자동 배관 생성

장치 간 최적 배관 경로를 자동으로 생성합니다.

```http
POST /api/geo/generate-pipes
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "device_ids": ["<uuid1>", "<uuid2>", "<uuid3>"]
}
```

---

## 응답 코드

| 코드 | 의미 |
|------|------|
| 200 | 성공 |
| 201 | 생성 성공 |
| 400 | 잘못된 요청 (입력값 오류) |
| 401 | 인증 필요 |
| 403 | 권한 없음 |
| 404 | 리소스 없음 |
| 500 | 서버 오류 |
