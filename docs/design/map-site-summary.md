# 지도 site 요약 — 팝업 재설계와 summary API

지도 위젯(AoT_map)의 site 계층을 "이름표"에서 "상태판"으로 바꾸는 정본 설계
문서. **상태: 1차 구현 완료(2026-08-09, 로컬 검증·미배포).**

구현물:
- `aot/aot_flask/geo/site_summary.py` — 집계 본체(30초 TTL 캐시 + 단일 비행),
  공용 `env_for_devices()` · `parent_site_for_shape()`
- `aot/aot_flask/routes_geo.py` — `GET /api/geo/site/<uuid>/summary`,
  zone contents 에 `env`·`site_uuid` 추가
- `aot/aot_flask/routes_geo_iec.py` — facility overview 에 `site` 추가
- `static/js/widgets/AoT_map/aot-map-widget-vector.js` — site 요약 모달,
  `_onSiteLabelClick`, 상위 이동 화살표, 시설 현재 환경 블록
- `static/js/widgets/AoT_map/aot-map-popup.js` — `buildEnvNowHtml()`,
  `_devRow` 부활
- `static/css/widget/aot-sensor-label.css` — `.aot-site-*` · `.aot-env-now-*` ·
  `.aot-modal-up` (AoT_map.py 의 CSS `?v=` 33→35, 위젯 템플릿 재생성 필요)

아래 §"구현에서 설계와 달라진 것"에 실제와 어긋난 초안 항목을 남겨 둔다.

관련 정본: [geo-device-binding.md](geo-device-binding.md) (공간-장치 소유 방향),
[color-system.md](color-system.md) (밴드 색·테마 정본).

## 배경 — 정보 피라미드가 거꾸로다

시스템은 장치 단위에서 GIS 중심으로 이동했지만, 지도 위젯의 정보 밀도는
아직 반대 방향이다(2026-08-09 로컬 UI 실측 + 코드 전수 조사):

| 계층 | 클릭 시 보이는 것 | 밀도 |
|------|-------------------|------|
| Device | 현재값 라벨, 배터리/통신 배지, 24h 차트, 노트 | 최고 |
| Facility | bay 칩(대표값+밴드색) → 3탭 모달(IEC 현황·제어·개요) | 높음 |
| Zone | 라벨 → 3탭 모달(인벤토리 개수·차트·함수) | 중간 |
| **Site** | **이름 · 면적 · 메모 미리보기 1건** | **최저** |

사용자가 줌 아웃 화면(여러 site)에서 처음 만나는 접점이 site 라벨인데,
그 팝업이 "이 필지에 들어가 볼 이유"를 전혀 만들어 주지 못한다. site 단위
집계는 **엔드포인트 자체가 없다** — zone 은 `/api/geo/zone/<uuid>/contents`
가 있지만 site 는 대응물이 없고, `label_area` 는 생성 시 빈 문자열로
저장되어 부제 줄이 항상 비어 있다(`routes_geo.py` 사이트 저장 경로).

방향: **시설 bay 칩이 이미 구현한 "대표값 + 밴드색 + 클릭 시 상세" 문법을
site 로 승격**한다. 전면 개편이 아니라 기존 집계·컴포넌트의 재사용이다.

## 설계 개요

1. 신규 엔드포인트 `GET /api/geo/site/<site_uuid>/summary` 하나가
   하위 구역 상태·오늘 할 일·노트를 한 응답에 묶는다.
2. site 라벨 클릭 시 기존 소형 팝업 대신 **중앙 모달 셸**(`.aot-center-modal`)
   을 쓴다. 행 수에 따라 높이가 변해 마커 anchor 계산이 깨지는 문제를
   원천 회피한다(장치 팝업에 차트를 안 넣는 이유와 같은 제약,
   `aot-map-widget-vector.js` 팝업 높이 주석 참조).
3. 모달 구성: 헤더(이름·상태 점·면적·개수) → 구역 상태 행 목록 →
   "오늘" 요약 타일 3개 → 노트 미리보기. 행 클릭 = 해당 도형으로 fly +
   기존 zone/facility 모달 오픈. 팝업이 곧 하위 계층 내비게이션이다.
4. site 라벨 자체에도 상태 점을 찍는다 — 팝업을 열기 전 1차 판단용.

## 응답 스키마

```jsonc
{
  "ok": true,
  "site": {
    "uuid": "a1b2…",
    "name": "3포장",
    "area_m2": 31827.0,
    "status": "warning",            // children.status 중 최악값 (empty 제외)
    "counts": { "zones": 2, "facilities": 4, "devices": 9 }
  },

  "children": [                     // site 직속 zone + facility, site_order 순
    {
      "uuid": "c3d4…",
      "kind": "zone",               // "zone" | "facility"
      "name": "3-2",
      "status": "fault",            // "ok" | "warning" | "fault" | "empty"
      "rep": {                      // 대표 측정값 — null 이면 표시할 값 없음
        "key": "T",                 // 우선순위: VPD > T > RH > CO2 > light > wind_ms
        "value": 37.6,
        "unit": "°C",
        "more": true                // 다른 측정 종류 존재 (bay 칩의 "+" 와 동일)
      },
      "sensors": { "valid": 2, "total": 3 },   // 600초 이내 응답 기준
      "issues": { "comm_fault": 1, "battery_low": 0 },
      "control": null               // 항상 null — 아래 §달라진 것 3
    },
    {
      "uuid": "e5f6…",
      "kind": "facility",
      "name": "육묘장",
      "status": "ok",
      "rep": { "key": "T", "value": 27.4, "unit": "°C", "more": true },
      "sensors": { "valid": 3, "total": 3 },
      "issues": { "comm_fault": 0, "battery_low": 0 },
      "control": null
    }
  ],

  "today": {
    "schedule_count": 2,            // 오늘 예정 작업 (site 하위 장치 대상만, §미결-2)
    "advice_open": 1,               // 미확인(alert_level != none) 조언 수
    "offline_devices": 1,           // comm_fault 장치 수 (children.issues 합과 일치해야 함)
    "advice_latest": {              // 없으면 null — 칩 렌더 필드의 부분집합
      "title": "3-2 온도 상승 추세",
      "alert_level": "warning",
      "timestamp": "2026-08-09T14:00:00+09:00"
    }
  },

  "notes": [                        // site 도형에 붙은 최근 2건
    {
      "unique_id": "…",
      "note": "관수 라인 점검 완료, 3-2 동쪽 밸브 교체 예정",
      "date_time": "2026-08-07T04:12:00+00:00",   // ISO — 표시 시각대는 AoTTz 가 정한다
      "files_count": 0
    }
  ],

  "generated_at": "2026-08-09T15:12:08+09:00",
  "partial": []                     // 실패한 블록명 (예: ["today.schedule"])
}
```

## 필드 계산 근거 — 전부 기존 조각의 재사용

| 필드 | 근거 코드 | 비고 |
|------|-----------|------|
| children 목록 | `aot/utils/geo_hierarchy.py` `build_geo_parent_map()` | site 직속만(`parent_map[s.id] == site.id`). 손자(zone 안 facility)는 zone 행에 합산 — 팝업 높이 예측 가능성. 같은 지도의 도형만 넘긴다 |
| 정렬 | 구역 먼저·시설 다음, 각각 이름순 | 지도를 보며 눈으로 찾는 순서 |
| 구역 소속 장치 | `aot/aot_flask/geo/device_membership.py` `device_ids_in_area()` | 마커·바인딩·그릇·참조 4겹. 마커만 보면 목록이 빈다(출력 16개 중 마커 1개). 바인딩 정본 전환(geo-device-binding Phase C-4) 후 단순화 여지 |
| rep 대표값 | `aot-map-widget-vector.js` `_sensorSummary()` (약 :1770) 의 서버 미러 | 우선순위·평균 규칙 동일. 클라이언트 중복 구현을 지우는 게 아니라 서버가 같은 규칙을 갖는 것 — **규칙 변경 시 두 곳 동기화 필요**, 장기적으로는 서버 단일화 |
| rep 채널 제외 | `facility_sensors.META_CHANNEL_KEYS` | rssi/snr/battery 는 대표값에서 뺀다 — 빼기 전에는 하트비트 0번 채널 노드가 온도 대신 배터리 전압을 대표로 내세웠다 |
| sensors.valid | 측정 시각 600초 이내 | 계측 dock(`refreshMeasurementPanelValues`)과 동일 기준 |
| issues | `aot/aot_flask/geo/device_link_status.py` `read_link_status_batch()` | Input comm_fault 는 데몬 판정, Output 두절은 `output_state()` 의 'fault' 합류. **site 전체 장치로 한 번만 호출**하고 자식별로 나눈다 — 자식마다 부르면 데몬 왕복이 자식 수만큼 늘어난다 |
| battery_low | ≤ 20% | 기존 배지(`.aot-link-badge.is-low`)와 같은 경계 |
| area_m2 | `geo/facility_calc.polygon_area_m2()` | geo 패키지의 공용 헬퍼. Polygon/MultiPolygon 모두 처리 |
| today.advice | `AISummaryService.get_latest_summary()` | 스코프 문제는 §미결-1 |
| notes | `Notes.target_id == site.unique_id` 최근 2건 | 아래 §달라진 것 4 |

## status 판정 규칙

```
empty   : 소속 장치 0
fault   : comm_fault ≥ 1
warning : battery_low ≥ 1  또는  sensors.valid < sensors.total
ok      : 위에 해당 없음
```

site.status 는 children 최악값이되 **empty 는 승격에서 제외**한다 —
관리사무소처럼 장치 없는 시설이 site 전체를 회색으로 만들면 안 된다.

**밴드(색)는 판정에 넣지 않는다.** 밴드 경계는 사용자가 바꿀 수 있는 표시
설정이라(시설 `view_options.sensor_ranges`, `--aot-band-*` 토큰), 그것으로
상태를 정하면 색 설정을 만진 순간 없던 "고장"이 생겼다 사라진다. 상태는
통신·배터리·응답 여부처럼 설정과 무관한 사실만으로 낸다.

## 캐싱·부분 실패

- **서버**: children 측정 집계가 제일 무겁다. `AoTFacilityRuntime`
  (`aot-facility-runtime.js` :26-51 — 8초 TTL + in-flight dedup) 패턴을
  서버측에 적용하되 TTL 30초. site 는 시설보다 갱신 민감도가 낮다.
- **클라이언트**: 모달 열 때 1회 + 열려 있는 동안 30초 폴링.
- **부분 실패**: 조언·일정 블록이 죽어도 구역 상태는 나가야 한다. 블록별
  실패를 `partial` 에 나열하고 해당 필드는 null/0. facility overview
  (`routes_geo_iec.py` :1124 — 세 소스를 한 응답에 묶는 기존 패턴)와 같은
  접근이되, overview 에는 없는 블록별 실패 표시를 추가한다.

### 세 겹으로 마무리 (2026-08-10)

위 계획은 서버 캐시만 말했고, 그것만으로는 모자랐다. 콜드 실측 **필지 요약
980ms, 구역 내용 639ms** — 게다가 구역(`/contents`)은 서버 캐시가 아예 없어
**열 때마다** 그 값이었다.

| 겹 | 무엇 | 실측 |
|---|---|---|
| 서버 | `cached_build(cache, locks, key, ttl, build)` — TTL + 키별 단일 비행. site 요약이 쓰던 것을 꺼내 공용화하고 구역 내용에도 적용(30초) | 639ms → 7ms |
| 클라이언트 | 필지·구역·장치 모달 조회를 `AoTGeoData`(파싱 결과 캐시 + 동시요청 합치기)로 통일 | 두 번째 열기 요청 0건 |
| 예열 | 라벨·도형 호버 시 미리 조회. 필지는 로드 후 한가할 때(`requestIdleCallback`) 전부 | 호버 후 클릭 시 왕복 없음 |

- **단일 비행이 캐시만큼 중요하다.** 계산 하나가 influx 수십 질의라, 같은 필지를
  둘이 동시에 열거나 폴링과 클릭이 겹치면 그대로 곱해진다. 저사양 호스트에서는
  그 팬아웃이 gunicorn 스레드풀을 삼켜 사용자가 누른 요청이 큐에서 기다린다
  (시설 모달에서 실측 1초+, 콜드 4초+ — `aot-facility-runtime.js` 주석).
- **`build()` 가 None 이면 캐시에 넣지 않는다.** "못 찾음"을 30초 기억하면 방금
  만든 도형이 그동안 없는 것이 된다.
- **`can_edit` 는 캐시 밖에서 매 응답 다시 채운다.** 캐시는 전역이라 처음 연
  사람의 권한이 다음 사람에게 갈 뻔했다. 사진 교체·장치 순서 저장은
  `invalidate_zone_contents()` 로 캐시를 버린다 — 저장은 됐는데 화면이 안 바뀌는
  것만큼 헷갈리는 게 없다.
- **구역은 로드 때 전부 데우지 않는다.** 수가 많아(로컬 18개) 타일·라벨이 밀린다.
  필지는 몇 개뿐이고 콜드가 1초에 가까워 예열 값이 크다.

## 구현에서 설계와 달라진 것

초안이 실제 코드와 어긋났던 지점들이다. 같은 함정을 다시 밟지 않도록 남긴다.

1. **`rep.band` 를 서버가 계산하려던 것 → 철회.** 5단계 경계값
   (`DEFAULT_RANGES`)·색표(`BAND_PALETTE`)·단위 환산(`BAND_UNIT_SCALE`)이
   전부 JS 와 CSS 토큰에만 있고 파이썬 대응물이 **없다**. 서버에 다시 구현하면
   두 벌이 조용히 어긋나고, 사용자가 `custom_ui` 로 밴드 색을 바꿔도 서버
   값은 안 따라온다. 서버는 `key`/`value`/`unit` 까지만 내고, 색은 지도
   칩과 같은 `AoTMapSensorLabels.bandColor()` / `.textOn()` 이 낸다.
2. **`site_order` 로 자식을 정렬하려던 것 → 오해.** 그 값은 지도 안의
   *site 목록* 순서이지 site 안의 자식 순서가 아니다. 구역→시설, 이름순으로 바꿨다.
3. **`control`(자동제어) 필드 → 항상 null.** `GeoFacility` 에 IEC 함수를
   가리키는 컬럼이 없고, `/status` 는 클라이언트가 넘긴 `function_uuid` 가
   없으면 전역에서 활성 `env_coordinator` 하나를 고른다. 그대로 행에 찍었더니
   로컬 실측에서 센서도 없는 관리사무소·농기계창고·펌프실까지 "자동제어 활성"
   이 됐다. **틀린 배지는 없는 배지보다 나쁘다.** 키는 스키마 안정을 위해
   남겨 두고 시설별 링크가 생기면 채운다.
4. **notes 를 site 스코프 전체로 모으려던 것 → 도형 자신에 붙은 것만.**
   구역·장치 노트까지 끌어오려면 `note_ids_in_area` 가 Notes 전량을 순회한다.
   팝업의 노트 줄은 "여기 적어 둔 게 있나"를 알리는 자리이지 목록이 아니다.
   날짜도 서버에서 서식하지 않고 ISO 로 낸다 — 표시 시각대는 `AoTTz` 가 정한다.
5. **빈 자식 처리.** 로컬 실측에서 3포장은 시설 7개 중 6개가 장치 없는
   껍데기였다(`New facility` 2개 포함). 전부 줄로 세우면 값이 있는 두 줄이
   묻힌다. 페이로드에는 그대로 담고 **UI 가 한 줄로 접는다**("장치 없음: …") —
   `area_choices()` 가 "고를 것이 없는 구역은 목록에 내지 않는다"로 간 것과
   같은 판단이되, 존재 자체는 숨기지 않는다.
6. **`_ensureSiteShapeLayer` 호출 조건.** 예전에는 `show_site_shape` 에만
   묶여 있어 도형을 끄고 라벨만 켜면 콜백이 등록되지 않는다. zone 이 이미
   겪은 버그라 같은 형태(`shape || label`)로 맞췄다.

## 미결 (다음 단계)

1. **조언의 site 스코프가 없다.** `AISummaryService` 스코프는 현재
   facility / farm / system 3종(`geo/widget/maps.py` :679-748).
   1차는 **farm(지도) 스코프를 그대로 노출**하도록 구현했다(`_advice`).
   `scope_type='site'` 를 어휘에 추가하고 요약 생성도 site 단위로 돌리는
   것이 정도이며, 그때 `_advice` 한 함수만 바꾸면 된다 — 응답 필드는 이미
   site 스코프를 전제로 잡아 뒀다.
2. **오늘 일정은 대상이 장치인 것만 센다.** 함수·시퀀스 대상까지 풀려면 각
   함수의 소속을 다시 해석해야 하고 그 비용이 팝업을 두 배로 만든다. 이
   축소는 `partial` 에 올리지 않는다 — 부분 실패와 의도적 축소를 섞으면
   "일부 실패"인지 "원래 안 세는 것"인지 구분할 수 없다.
3. **성능.** 로컬 실측 콜드 610~710ms / 캐시 히트 0ms(3포장: 자식 9,
   장치 7). 지배 비용은 자식별 `device_ids_in_area()`(자식마다 지도 도형
   전량을 shapely 로 훑는다)와 채널별 influx 조회다. 자식·장치가 수십 개인
   필지에서 다시 재보고, 필요하면 `_shapes_inside` 결과를 site 단위로 한 번만
   만들어 자식들이 나눠 쓰도록 고친다.
4. **캐시 무효화 훅.** `site_summary.invalidate()` 를 만들어 뒀지만 아직
   아무도 부르지 않는다. 도형·장치 변경 시점에 붙일 자리다(지금은 30초 TTL 로만 만료).

## 2차: 구역·시설 모달 개선 + 계층 이동 (2026-08-09 구현 완료)

### 현재 환경 블록 (공용)

`AoTMapPopup.buildEnvNowHtml(env)` 하나를 구역 [상태]와 시설 [현황]이 함께
쓴다. 값은 크게, 이름은 아래 작게 — 지도 라벨과 달리 **밴드 색을 칠하지
않는다**. 값이 서넛 나란히 서면 색이 겹쳐 "무엇이 문제인가"가 아니라
"알록달록하다"가 된다.

- **구역**: `/api/geo/zone/<uuid>/contents` 에 `zone.env` 추가. 집계는
  `site_summary.env_for_devices()` — 필지 요약과 **같은 함수**다. 한쪽만
  고치면 같은 구역이 두 화면에서 다른 온도를 말한다.
- **시설**: 이미 폴링 중인 `/runtime` 을 재사용한다(`AoTFacilityRuntime` 이
  8초 TTL + in-flight dedup 으로 코얼레싱 → 요청이 늘지 않는다). 그 응답의
  `indoor`(가중평균)와 `sensors`(valid/total)는 계산돼 있으면서 화면에 쓰이는
  곳이 **한 군데도 없었다**.
- 센서 응답 수는 **모자랄 때만** 적는다. 늘 "3/3"이 붙어 있으면 정작 봐야 할
  "2/3"이 그 속에 묻힌다.
- 센서가 아예 없으면 블록을 그리지 않는다. 단위 문자열 `'none'`(무차원 채널의
  저장값)은 표시에서 뺀다 — 그대로 붙이면 `522.0none` 이 된다.

### 목표 대비 편차 — 죽은 코드 부활

`_devRow`(`aot-map-popup.js`)는 정의만 되고 부르는 곳이 없었다. 서버는
`env_summary.deviation` 을 계속 보내고 있었다. [현황]의 Status Summary 블록에
넣었다 — 운전 모드는 무엇을 하는 중인지만, 추세는 어디로 가는지만 말해서
정작 **벗어난 폭**은 어디에도 없었다.

### 상위 필지로 가는 화살표 (`.aot-modal-up`)

필지 요약의 줄을 눌러 구역·시설로 내려가는 길은 있는데 되돌아오는 길이 없어
지도에서 라벨을 다시 찾아 눌러야 했다. 구역·시설 모달 제목줄 왼쪽에 `←` 를
둔다(닫기 버튼과 같은 조용한 톤 — 제목보다 눈에 띄면 계층 이동이 주된 행동처럼
보인다).

- **한 단계 위가 아니라 site 가 나올 때까지 거슬러 올라간다** — 구역 안에 놓인
  시설은 부모가 구역이고 그 위가 필지다. `site_summary.parent_site_for_shape()`.
- 상위를 아직 모르는 동안에는 `hidden` 으로 자리만 잡는다. 처음부터 그리면
  상위가 없는 도형에서 눌러도 아무 일이 없는 버튼이 남는다.
- 모달 위에 모달을 쌓지 않는다 — 현재 모달을 닫고 필지 모달을 연다.
- `_loadOverview` 는 자동제어 토글 뒤에도 다시 도는데, 그때마다 리스너를 얹으면
  한 번 눌러도 여러 번 열린다(`dataset.wired` 로 1회 고정).
- 계층 해석이 지도 도형 전량을 shapely 로 훑으므로 **지도 단위 60초 캐시**.

### 곁다리로 고친 것

구역 [상태]의 "대지"(상위 필지) 줄은 **늘 비어 있었다.** `zone.parent_id` 만
보고 있었는데 그 컬럼은 운영 데이터에서 전 행이 NULL 이다(geo_hierarchy 주석).
공간 포함 관계로 푸는 공용 리졸버로 바꾸니 값이 나온다.

### 아직 안 한 것

- **Zone [상태] 탭의 인벤토리(면적·개수)를 [개요]로 분리** — 시설과 탭 구성을
  통일하는 작업. 현재 환경을 맨 위에 올려 급한 문제는 해소됐고, 탭 재편은
  기존 사용자의 조작 습관을 건드리므로 따로 판단할 일로 남긴다.
- **Zone 라벨에 밴드색 + 문제 점** — 지도 라벨 자체의 문법 변경.
- **`runtime.outdoor`(외기)** 는 여전히 미사용.

## 구현 시 주의 (이번에 실제로 걸린 것 포함)

- 위젯 JS 대부분은 `dist/aot-map-widget.bundle.js` 로 번들된다 — 소스 수정
  후 재빌드 + dist 커밋 필수(`aot-map-sensor-labels.js` 만 독립 스크립트).
  검사: `python3 aot/scripts/check_js_bundles.py`.
- **CSS 는 번들과 캐시 경로가 다르다.** `aot-sensor-label.css` 는
  `AoT_map.py` 가 `?v=<숫자>` 를 손으로 붙인다 — 규칙을 추가하고 이 숫자를
  안 올리면 브라우저가 옛 CSS 를 계속 쓴다(이번에 겪었다: 모달은 떴는데
  세 칸 레이아웃이 안 먹혀 한 줄로 흘렀다). 숫자를 올렸으면 위젯 템플릿
  재생성까지 해야 한다 — `?v=` 가 템플릿에 박혀 나간다.
  (반대로 JS 번들은 템플릿이 `{{ asset('aot-map-widget') }}` 를 그대로 들고
  있어 manifest 해시가 자동 반영된다. 둘을 같은 것으로 생각하지 말 것.)
- 클라이언트 문구는 `window._` → `window.AOT_I18N` 이고, 그 카탈로그는
  `/api/v1/locale/js` 가 **10분 캐시**로 내려준다. `.po` 를 고치고
  `.mo` 를 컴파일하고 앱을 재시작해도 브라우저가 옛 카탈로그를 들고 있으면
  새 문구가 영어로 남는다 — 번역이 안 들어간 것으로 오진하기 쉽다.
- 신규 UI 문구는 i18n 래핑 + ko/ja 번역 필요. **전체 재추출은 하지 말 것**
  (fuzzy 대량 오역 이력) — `.po` 말미에 서지컬 추가 후 해당 언어만 컴파일.
- 색·밴드는 `AoTGeoTheme` / `AoTMapSensorLabels.bandColor()` 경유 —
  하드코딩·신규 폴백 금지([color-system.md](color-system.md)).
