# GIS & 지도 시스템 개요

AoT GIS 시스템은 MapLibre GL 기반의 벡터 지도 엔진 위에 장치 모니터링, 시설 설계, 외부 GIS 레이어 통합을 하나로 묶은 통합 지리정보 플랫폼입니다.

---

## 시스템 구성

```
GIS & Map System
├── 지도 엔진
│   ├── MapLibre GL (주력 — 벡터/3D)
│   └── Leaflet 호환 shim (하위 호환)
│
├── 관리 페이지
│   ├── /geo/design   — 지도 디자인 도구
│   ├── /geo/facility — 시설 관리
│   └── /geo/layer    — GIS 레이어 관리
│
├── 대시보드 위젯
│   ├── AoT_map      — 실시간 장치 모니터링 지도
│   └── AoT_facility — 3D 시설 환경 모니터링
│
└── API
    └── /api/geo/*   — 30+ REST 엔드포인트
```

---

## 핵심 기능

### 지도 디자인 도구

- **6가지 편집 모드**: Site(부지) → Zone(구역) → Facility(시설) → Plot(구획) → Equipment(설비) → Device(장치, 모드 바에서는 "A"로 표시)
- **벡터 드로잉**: 폴리곤, 폴리라인, 원, 마커 그리기 및 편집
- **필지 가져오기**: VWorld 주소 검색 또는 CSV 일괄 가져오기로 부지 경계 즉시 생성
- **델타 저장**: 변경된 피처만 전송하여 대용량 지도도 빠르게 저장

### 구획과 프로그램

- **구획(Plot)**: 어디에 무엇을, 언제부터, 무엇을 목표로 재배하는지 — Plot 모드에서 도형을 그리지만, 기록(작물·품종·날짜·단계 일정)은 도형과 별개로 저장되어 도형을 다시 그리거나 시즌이 끝나도 남는다.
- **프로그램(Program)**: 재사용 가능한 템플릿("토마토를 5단계로, 이 목표를 향해"). 구획에 연결하면 현재 단계·목표 환경·예상 종료일이 자동으로 따라온다.
- **종류(Kind)**: 구획과 프로그램 모두 종류가 있다 — 작물, 가축, 시설, 기타 — 같은 종류끼리만 연결할 수 있다.
- **일지(Journal)**: 선택한 기간 동안 구획·구역·부지가 무엇을 재배·측정·제어했는지를 그 시점 그대로 남기는(재계산되지 않는) 스냅샷으로, 인계나 인증 제출용이다.

### 시설 관리

- **3D 파라메트릭 렌더링**: Three.js 기반, 건물 구조 파라미터로 자동 생성
- **건물 외피 설정**: 자재(비닐/유리/PC 등), 단열재, 개구부(창/문/환풍구) 설정
- **공학 계산**: 냉난방 부하, 환기 용량, 자연환기 풍압 시뮬레이션 (±5~10% 참고치)
- **센서·액추에이터 바인딩**: 시설 내 AoT 장치를 역할별(온도/습도/CO₂ 등)로 연결
- **커미셔닝**: 장치 통신 확인 및 진단 워크플로우
- **AI 조언**: 시설 학습 기반 자동화 추천

### GIS 레이어

23개 외부 GIS 제공자와 연동됩니다.

| 분류 | 제공자 |
|------|--------|
| 국내 | VWorld, Kakao Maps, Naver Maps |
| 국제 일반 | OpenStreetMap, Google Maps, ESRI, Bing, Mapbox, MapTiler, Carto, Stadia |
| 위성/항공 | NASA GIBS, ESA |
| 기상 | RainViewer (레이더), OpenWeather, Open-Meteo |
| 지형 | OpenTopoMap, Thunderforest |
| 전문 | ISRIC (토양), GSI (일본), SGIS (싱가포르) |

---

## 기술 스택

| 계층 | 기술 |
|------|------|
| 지도 렌더링 | MapLibre GL JS |
| 3D 시각화 | Three.js + GLTF |
| 드로잉 도구 | terra-draw (Geoman API 호환) |
| 공간 연산 | Turf.js |
| 마커 클러스터 | Leaflet.MarkerCluster |
| WMS 지원 | MapLibre + CORS 프록시 |
| 백엔드 | Python/Flask, SQLAlchemy |
| 데이터베이스 | SQLite (설정), InfluxDB (시계열) |

---

## 데이터 모델

| 테이블 | 역할 |
|--------|------|
| `geo_map` | 저장된 지도 뷰 (중심 좌표, 줌, 제공자, 스타일) |
| `geo_setting` | 전역 GIS 설정 (싱글턴) |
| `geo_shape` | GeoJSON 오버레이 피처 (부지/구역/시설/장치) |
| `geo_layer` | 외부 GIS 레이어 소스 등록 |
| `geo_facility` | 시설 건물 스펙 (외피, 센서, 액추에이터, 베이) |
| `geo_model_asset` | 3D 에셋 라이브러리 (프리미티브/GLTF) |

---

## 피처 계층 구조

```
부지 (Site)          ← 최상위 경계 (폴리곤)
  └── 구역 (Zone)    ← 재배 블록/단지
        ├── 시설 (Facility)   ← 건물 단위
        ├── 구획 (Plot)       ← 무엇을, 언제부터, 무엇을 목표로 재배 중인지 (구획과 프로그램 참고)
        ├── 설비 (Equipment)  ← 펌프·밸브·배관·관수
        └── 장치 (Device)     ← AoT 입력/출력/함수 마커
```

구획·설비·장치가 어느 구역에 속하는지는 지도 위에 그려진 위치로 정해지며, 목록에서 고르지 않는다.

---

## 관련 페이지

- [시작하기](getting-started.md)
- [디자인 도구](design-tool.md)
- [필지 가져오기](parcel-import.md)
- [시설 관리](facility.md)
- [구획](plots.md)
- [관리 프로그램](programs.md)
- [일지](journal.md)
- [GIS 레이어 관리](layers.md)
- [지도 위젯](map-widget.md)
- [시설 위젯](facility-widget.md)
- [구획 위젯](plot-widget.md)
- [설정](settings.md)
- [API 레퍼런스](api-reference.md)
