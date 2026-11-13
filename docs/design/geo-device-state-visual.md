# 시설 밖 장치 마커·담당 구역의 작동 상태 표시

시설 3D 모형의 설비 상태(`facility-state-visual.md`)와 짝이 되는 문서다. 시설에 속하지
않은 **출력 장치 마커**(`geo_binding` 으로 좌표에 묶인 점, `GeoShape(type='aot_device')`)와
**장치 담당 구역**(`GeoShape(type='device')`, `geo-device-area-split.md`)이 지도 위에서
켜짐·꺼짐·모름을 바로 드러낸다. 구현은 `widgets/AoT_map/aot-map-widget-vector.js` 하나다.

## 조사에서 확인한 것 (2026-11-07)

- 마커는 MapLibre 레이어가 아니라 DOM 마커다(`maplibregl.Marker`). `addDeviceMarkers` 가
  `show_device_labels` 에 따라 알약(이름+값) 또는 점을 만들고, `refreshDeviceMarkersAppearance`
  가 제자리에서 갱신한다. 상태는 **배경색 하나**로만 말했다(켜짐 = 장치색 채움, 꺼짐 = 흰 바탕).
  `fault`·`pending`·응답 없음은 전부 꺼짐과 같은 모양이었다.
- 구역은 `/api/geo/overlays?type=aot_device` 가 돌려주는 피처(점·구역 폴리곤 모두, `properties.device_id`
  는 바인딩에서 해석)를 `aot-devices-line`·`aot-devices-fill` 두 레이어로 그린다.
  `_updateDeviceShapeOpacity` 가 켜진 장치의 **면을 0.9 로 칠했다** — 대시보드 면 칠하기 금지와 어긋난다.
- 상태 폴러는 이미 따로 있었다(`setupOutputStateRefresh`, `output_update_interval`, 기본 5초).
  다만 `GET /outputstate` 로 **전 출력**을 받고 조건부 요청이 없어, 지도에 없는 출력까지 매번 본문을 받았다.
- `POST /api/geo/output_states` 는 구역 팝업이 5초마다 치는 경량 경로인데 ETag 가 없었다.
- `maps.py` 의 `map_global_style.offColor`(`draw-fill-off-color`)는 템플릿 변수로는 넘어가지만
  **템플릿도 JS 도 읽지 않는다.** 지도별 state_json 색 병합을 2026-08-05 에 끊으면서(색의 정본은
  전역 theme_config) 소비처가 함께 사라진 잔재다. 같은 블록이 두 번 적혀 있던 중복만 걷었다.
- MapLibre 4.1.2 의 `line-dasharray` 는 데이터 구동이 아니다 — 점선은 레이어를 하나 더 두고
  `setFilter` 로 가른다.

## 상태 어휘 — 세 낱말

판정은 팝업과 같은 공용 분류기 `AoTOutputState.classify()` 다.

| 분류기 kind | 표시 | 글자 |
|---|---|---|
| on | 켜짐 | `_('Running')` |
| off | 꺼짐 | `_('Stopped')` |
| pending · fault · unknown(응답에 없음) | 모름 | `_('Unknown')` |

`fault`(무응답)와 `pending`(확인 중)을 모름으로 접는 이유: 지도는 한눈에 보는 면이고 세부는
팝업이 이미 말한다. 꺼짐으로 접으면 오프라인 장치가 "멈춤" 으로 보인다 — 분류기 머리말이 막는
바로 그 거짓이다. 3방향 액추에이터(`value_3way`)는 종전처럼 **움직이는 동안만** 켜짐이다.

## 표현 — 색은 보조, 테두리와 글자가 말한다

새 색 없음(`settings/custom_ui` 정본), 아이콘·이모지 없음, 면 칠하기 없음.

| 대상 | 켜짐 | 꺼짐 | 모름 |
|---|---|---|---|
| 점 마커(`.map-marker-dot`) | 테두리 4px | 테두리 2px | 테두리 2px **점선** |
| 알약 마커(`.marker-pill`) | 테두리 3px + `Running` | 테두리 2px + `Stopped` | 테두리 2px 점선 + `Unknown` |
| 담당 구역(`aot-devices-line`) | 선 4px | 선 2px | 선 2px 점선(`aot-devices-line-unknown`) |
| 장치 이름 라벨(geo-design `label_aux`) | 글자 `Running` | 글자 `Stopped` | 글자 `Unknown` |

- 마커 요소에는 `data-state="on|off|unknown"` 과 `aot-dev-state-*` 클래스가 함께 붙는다.
  점 마커는 글자가 없으므로 `title` 로 같은 낱말을 둔다(라벨 글자는 `show_device_labels` 종속).
- 구역의 **면 불투명도는 위젯 옵션값(`device_shape_opacity`) 그대로**다. 상태로 바꾸지 않는다.
- 색 자체는 종전과 같다(켜진 알약 = 장치 테마색 채움). 바뀐 것은 색 **외에** 두께·점선·글자가 더해진 것이다.

## 폴링 — 새 요청을 만들지 않는다

- 위젯의 상태 폴러를 `POST /api/geo/output_states` 로 옮겼다. 몸체는 **이 지도에 놓인 출력의
  uuid 목록**만이라 응답도 그만큼이다. 주기는 종전 `output_update_interval`(기본 5초, 최소 2초).
- 서버는 `utils_http.json_conditional` 로 ETag 를 달고, 같으면 **304(본문 없음)** 를 준다.
  클라이언트는 `If-None-Match` + `cache:'no-store'` 로 부른다(브라우저 캐시가 304 를 가로채지
  않도록 — 조건부 요청 규칙은 `ops-archive.md` 「주기 폴링은 조건부 요청으로」).
- 제어 직후(`_refreshOutputStatesAfterCommand`)는 `force` 라 조건을 걸지 않는다 — 명령보다 오래된 캐시본을 돌려받으면 안 된다.
- 같은 대시보드의 지도 위젯 여러 개가 같은 uuid 집합을 물으면 in-flight 를 합친다(종전 TTL 캐시 유지).
- 구역 팝업의 같은 폴링에도 `If-None-Match` 를 실었다. 응답이 같으면 DOM 갱신도 건너뛴다.
- 출력이 하나도 놓이지 않은 지도는 요청을 보내지 않는다.

## 검사

- `aot/tests/e2e/test_journey_map_device_state.py` — 시드가 놓은 출력 마커·담당 구역이 꺼짐 →
  켜짐 → 꺼짐을 따라 글자·테두리·구역 선 폭이 바뀌는지, 20초 동안 `output_states` 요청이 5초당
  1건을 넘지 않는지, 304 가 실제로 돌아오는지(ETag 가 살아 있는지), 점 마커 화면(`show_device_labels`
  꺼짐)에서도 상태 클래스가 붙는지 본다.
- `aot/tests/test_geo_output_states_conditional.py` — 라우트가 ETag 를 달고 304 를 돌려주는지.

## 남은 과제 — 보기 권한은 의도된 공개다

- `POST /api/geo/output_states` 는 `login_required` 만 보고, 몸체로 받은 uuid 의 상태를 그룹과
  상관없이 돌려준다. **구멍이 아니라 A 단계 결정이다** — `access-scope-groups.md` §1-A
  「결정 (2026-08-22)」은 그룹이 조작만 막고 보기는 전원 공개로 두었다. 같은 출력의 측정값도
  `/data_batch`·`/last` 로 똑같이 읽히고, 마커 자체도 모두에게 보인다. 이 경로만 거르면 마커는
  보이는데 상태만 '모름'이 되어 격리로 오해된다(같은 문서 원칙 4).
- 보기 제한(B 단계)을 시작할 때는 원칙 4 의 값 조회 목록에 이 경로가 이미 올라 있으니 그
  목록과 함께 다룬다.
