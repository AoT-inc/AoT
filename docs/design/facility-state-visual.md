# 시설 모형 설비 작동 상태의 육안 표시

시설 3D 모형(`widgets/AoT_facility/aot-facility-3d.js`)의 설비가 작동 중인지 **자세(기하)·모션·글자**로 보인다.
색은 보조다(상태를 색으로만 말하지 않는다 — ui-guide §4-11). 아이콘·이모지 없음(§4-12), 새 색 없음.

## 계약 (`window.AoTFacility3D`)

| API | 뜻 |
|---|---|
| `resolveFittingState(fitting, runtime)` | `{on, percent, control_type, stale, bound}`. `fitting.actuator_id === actuator_states[*].output_uuid` 우선, 없으면 kind→슬롯 폴백(curtain, shade_curtain, side_window, fan, heater). 분무기 머리는 폴백 없음. runtime 없음/만료/출력 없음 = `on:null`(모름). `bound:false` 는 출력과 이어지지 않은 설비 — 건드리지 않는다 |
| `applyRuntime(root, facility, runtime, opts)` | 재빌드 없이 `fitting:<id>` 메시를 제자리에서 갱신. `opts.motion` 기본 = OS `prefers-reduced-motion` 이 아닐 때. 반환 `{animating}` |
| `tick(root, dtMs)` | 모션을 한 걸음. `true` 면 계속 그려야 한다 |

`/runtime` 의 `actuator_states[slot]` 에서 `output_uuid, on, percent, control_type` 를 읽는다(서버 응답은 바꾸지 않았다).
`binary` 는 켜짐 = 100%, `pwm`/`value` 는 `percent`.

## 자세 상수

| 설비 | 표현 |
|---|---|
| window / side_window | `open_mode` 가 없거나 `hinge`: 윗변 모서리 피벗, 바깥(+법선)으로 열림. 최대 45도 / 60도 x 열림 비율. 다른 방식은 아래 「개폐 방식」 |
| door | `hinge`: 한쪽 세로변 피벗, 최대 90도 |
| curtain / shade_curtain (천장) | 열림 r 만큼 양쪽 가장자리로 모여 두꺼워진다(r=1 이 예전 접힘 상자 2개). 벽 커튼은 윗변 고정으로 걷힘 |
| fan | 켜지면 날개 표시, 모션이면 7 rad/s 회전, 아니면 45도 정지. 켜지면 흐름 띠(아래) |
| heater | 켜지면 시설 가운데를 향한 큰 단색 화살표(아래 「히터 화살표」) + 몸체가 켜진 히터 색(`MAT.heaterOn` 값)으로 발광 |
| irrigation_device | 켜지면 반투명 물 원뿔(기존 equipment 테마색), 모션이면 줄무늬 흐름. `sub_type: 'mist'` 는 안개 원반(아래) |
| 켜진 설비 | 외곽선이 켜짐 색 `--aot-band-3`(슬라이드 토글 켜짐과 같은 색) |
| 열린 창류(창·측창·문, 열린 비율 > 0) | 판도 켜짐 색, 외곽선은 불투명·외피 위로(`depthTest:false`, renderOrder 3) — 필름 너머에서도 보인다 |
| 모름(`on:null`, 출력과 이어진 설비만) | 반투명 x0.55 |

열림 비율 = 퍼센트이며 **커튼의 "열림" 은 걷힌 정도**다(예전 ON = 접힘 과 같은 방향).
안쪽 측창·천창, 장치 아이콘, 배관은 꺼짐/켜짐 쌍둥이(`userData.twin`)의 재질·회전을 갈아 끼운다.

## 개폐 방식 (`fittings[].open_mode`)

창·측창·문은 힌지만 있는 것이 아니다 — 미닫이, 비닐하우스의 말아 올리는 측창, 위로 들리는 창이 있다.
설계 모달(설비 편집, `#fi-open-mode`)에서 고르고 `GeoFacility.fittings[].open_mode` 에 저장한다.
**값이 없거나 모르는 값이면 `hinge`** — 이 필드가 생기기 전의 설비는 그대로 힌지로 움직인다. 서버는 fittings
JSON 을 그대로 저장하므로 서버 변경은 없다. 상자 국소 축은 +X 폭, +Y 높이, +Z 법선(바깥)이다.

| `open_mode` | 자세 (r = 열림 비율) | 부속 메시 |
|---|---|---|
| `hinge` | 위 표와 같다 | — |
| `slide` | 판이 폭 방향(+X)으로 `w x r` 밀린다. 회전 없음. 옆 칸과 겹쳐도 그대로 둔다(실제 미닫이가 그렇다) | — |
| `lift` | 판이 높이 방향(+Y)으로 `h x r` 들린다 | — |
| `roll` | 윗변 고정, 판 높이가 `(1-r)` 로 줄어 아래에서 말려 올라간다(벽 커튼과 같은 변환). 남은 판의 아랫변 바깥(+Z)에 말린 뭉치가 걸린다 | `fitting:<id>:roll` — 원통(축 = 폭). 반지름 `rollRadius(size, r) = min(max(d, 0.03) + h·r·0.08, h/4)`, 길이 `w`. 그 설비의 재질을 복제해 불투명하게(0.85 이상). 닫히면(r ≤ 0.02) 숨김 |

모션 보간은 전부 기존 `stateAnim` 경로(`_EASE_MS`)를 탄다. 지도 위 3D(`aot-facility-map-3d.js`)도 같은
`applyRuntime` 을 facility.fittings 로 부르므로 따로 할 일이 없다(지도 메시의 `_specLite` 에도 `open_mode` 를 싣는다).
링크 그룹(함께 만든 창)은 `_syncGroup` 이 `open_mode` 도 같이 맞춘다. 종류를 창류 밖으로 바꾸면 값을 지운다.

## 흐름 띠 (fan)

날개 회전은 가까이서만 보인다. 켜진 팬은 바람이 가는 쪽으로 반투명 **흐름 띠**를 내어 멀리서도
"돌고 있다" 가 읽히게 한다. 방향은 상자 국소 **+Z** — 곧 `surface_normal`, 없으면 `rotation_deg` 가 돌린 정면이다.

- `fitting:<id>:band` — 상자의 **자식**(날개와 같다)이라 힌지·회전을 그대로 따른다. 가로·세로 평면 두 장을 십자로
  세워 어느 각도에서도 읽힌다. 길이 `max(w, h) x 1.5`, 너비 `min(w, h) x 0.8`, 상자 앞면(`d/2`)에서 시작한다.
- 재질: 그 설비 재질의 **색 그대로**(새 색 없음), `MeshBasicMaterial` 투명 0.3, `depthWrite:false`, 줄무늬 `DataTexture`
  (물 줄무늬와 같은 방식, 1x8 알파 띠, repeat 3).
- ON 일 때만 보인다. 모션이면 `tick` 이 줄무늬를 +Z 쪽으로 흘린다(`_FLOW_UV_S`); `prefers-reduced-motion` 이면
  보이되 멈춘다.
- 줄무늬 텍스처는 공유라 `applyRuntime` 은 `flow` 항목을 **한 번만** 큐에 넣는다(머리 수백 개가 각자 밀면 그만큼
  빨라졌다 — 물 줄무늬도 같은 큐를 쓰므로 함께 고쳐졌다).

## 히터 화살표

히터 열은 시설 안 공기로 간다. 그런데 히터는 외피·바닥에 끌어 놓으면 **놓은 면의 바깥 법선**을 정면으로 받으므로
(벽에 붙이면 바깥) 법선 방향 띠는 열이 온실 밖으로 나가는 것처럼 보였다. 그래서 히터는 법선을 쓰지 않는다.

- `fitting:<id>:band`(이름은 띠와 같다 — 해제·검사 경로 공유) 안에 수평 단색 화살표 두 장(가로·세로 십자).
  히터에서 **시설 가운데**(외피 `outer_cover*` 상자의 가운데, 외피가 없으면 설비들의 가운데)를 향한다.
  수평 0.3 m 안이면 정면 쪽.
- 길이 `clamp((가운데까지 거리 - 히터 반경) x 0.7, 1.5, 5)` m, 몸통 반폭 `clamp(L x 0.12, 0.2, 0.6)`, 머리 반폭 x 2.2.
- 색은 켜진 히터 색(`MAT.heaterOn` 과 같은 값, 새 색 아님), 불투명도 0.85, 외피 위로 그린다(`depthTest:false`).
  줄무늬는 작게 보면 빗금처럼 흐려져 쓰지 않고, 흐를 것이 없으니 `flow` 를 큐에 넣지 않는다.
## 분무 머리 (`irrigation_device.sub_type: 'mist'`)

스프링클러는 물 원뿔이지만 분무·포그 노즐은 안개가 넓고 낮게 깔린다. 설계의 관수 종류 셀렉트(`#irr-sp-subtype`)에
`mist` 를 더했고, 기본 반경은 1.5 m(스프링클러 11 m 를 쓰면 원반이 집을 덮는다). 머리 몸체는 스프링클러와 같은
원뿔로 그리고(drip 처럼 숨기지 않는다), 켜지면 `fitting:<id>:water` 가 원뿔 대신 **원반**(`CylinderGeometry`) 이 된다:
반지름 `clamp(radius_m, 0.3, 6)`, 두께 `clamp(R x 0.12, 0.08, 0.3)`, 머리 끝 바로 아래(위 분사면 위). 재질은 물
재질을 복제해 더 옅게(0.22) — 색·줄무늬는 물과 같다. 유량·노즐 집계(`irrigation_nozzles.py`)는 `drip` 만 가르므로
`mist` 는 스프링클러로 센다.

## 틱 소유 규칙

- rAF 는 **호출자**가 갖는다. 코어는 타이머를 만들지 않는다.
- 위젯: `applyRuntime` 이 `animating:true` 를 주고 탭이 보이는 동안만 `tick` + `requestRender` 루프. 숨은 탭에서 멈추고 돌아오면 다시 적용한다.
- 지도: `map.triggerRepaint()` 루프를 호출자가 소유하며 컬 줌 아래·숨은 탭에서는 `applyRuntime`/`tick` 을 부르지 않는다.
- 위젯 폴링은 `applyRuntime` 만 부른다. 씬 재빌드는 설비 목록·층 모형·슬롯 구성이 바뀐 때만.

## 글자 라벨

`AoTSensorLabels.updateStates(widgetId, runtime)` — `Open 65%`(창·커튼·문) / `Running` / `Stopped` / `Unknown`, 전부 `_()` 래핑.
같은 출력이 여러 설비를 움직여도 글자는 같다(출력 없는 설비는 같은 종류끼리 한 묶음). 자리는 묶음에서 정한다
(`AoTSensorLabel.equipGroups` → `anchors`, `common/sensor-label.js`):
- **벽에 붙은 설비가 든 묶음**(바깥 법선 `surface_normal` 의 수평 성분이 있는 것 — 측창·문·벽 팬·벽 난방기):
  그 설비들을 바깥 방향별로 나눠, 방향마다 **가장 바깥 벽**(끝 벽, 0.5 m 안)에 놓인 것들의 가운데에 하나씩.
  연동 안쪽 벽·복제한 동끼리 마주 보는 벽의 것은 고르지 않는다. 같은 출력의 천창·커튼은 글자가 같으므로 따로
  두지 않는다.
- **그 밖**(천창·커튼·바닥 설비·법선 없는 것): 묶음 가운데에 **가장 가까운 설비의 자리**(거리가 같으면 먼저 놓인
  것) — 연동 동마다 놓인 천창은 가운데 동, 설비가 하나면 그 자리.
- 글자는 언제나 실제 설비 자리에 놓는다. 측창이 아닌 묶음을 위치 상자의 가운데에 두던 때는 대칭으로 놓인
  팬·난방기·천창·커튼의 글자가 모두 시설 중심 한 점에 겹쳤다(2026-11-11 수정).
- **서로 다른 묶음의 글자가 사실상 한 자리**(가로 2 m·높이 1.5 m 안 — 측면 보온커튼과 그 바깥 측창처럼 같은 벽·같은
  높이)면 자리마다 쌓임 순번 `stack`(0, 1, 2 …, 먼저 놓인 묶음이 0)을 매기고, 그리는 쪽이 그 순번만큼 글자를
  한 줄씩 위로 올린다(지도: 마커 기본 오프셋 `_baseY`, 시설 위젯: 화면 y). 라벨 겹침 회피 옵션
  (`enable_label_collision`)이 꺼진 위젯에서도 갈려야 하므로 자리 단계에서 정한다(2026-11-11).
- 지도에서는 그래도 같은 자리에 놓이는 글자(천창과 그 아래 센서 등)를 센서 값 라벨의 겹침 회피
  (`aot-map-sensor-labels.js` `_spreadLabels`, 옵션이 켜졌을 때)가 상태 글자까지 한 묶음으로 떼어 놓는다.
  떼어 놓는 거리는 쌓인 기본 오프셋 위에 더한다.
- 묶음 전체를 시설 가운데 하나에 두던 때(#642)는 측창·천창·팬 글자가 시설 가운데로 모여 겹쳤다.

개폐형(창·측창·문·커튼) 글자는 "[설비 이름] n%" 이다(0% 도 "이름 0%"). 설비에 이름이 없을 때만 예전 "Opened n%"/"Closed".

지도 상태 글자(`aot-map-sensor-labels.js`)도 같은 함수를 쓴다. 지도에서 창을 움직이는 것은 3D 작동 상태 폴러
(`_wireFacilityState3D`, 5초)인데 글자 폴러는 `refresh_seconds`(기본 60초)라, 창은 움직이는데 개폐율 글자가
그대로였다. 3D 폴러가 새 응답을 받으면 `AoTMapSensorLabels.setRuntime` 으로 같은 응답의 글자를 바로 다시 그린다.

출력에 묶인 지도 상태 글자를 누르면 그 출력의 장치 모달(`_openDeviceModal`, 맥락 `{facilityUuid}`)이 열린다.
- **제어:** 시설 런타임에서 그 출력의 슬롯을 찾아, 시설 모달 제어 목록(`.aot-act-tabs-body`)의 그 행을
  `AoTMapPopup.buildActuatorRow` 로 그대로 그린다(`_mountFacilityActRow`). 개폐형이면 닫기·정지·열기 +
  "수동/시스템/목표 n% · 현재 n%" + 손잡이(목표)·점(현재) 슬라이더이고, 명령은 시설 제어 경로(`_sendActControl`)로
  간다. 행이 하나라 끌기 손잡이는 없다. 슬라이더만 두면 지금 몇 % 인지·어디로 가는 중인지 말하지 못했다(#675 → 2026-11-11).
  on/off 는 장치 모달의 토글을 그대로 쓴다. 시설 밖에서 연 개폐형 장치 모달도 같은 값 표기(`aot-device-posinfo`)를 둔다.
- **뒤로가기:** 그 시설 모달(시설 칩을 누를 때와 같은 창, 첫 동). 서버의 `parent` 는 장치가 놓인 구역·필지라,
  예전에는 시설에서 왔는데 엉뚱한 곳으로 올라갔다.
- 개도 글자는 msgid `Now`(현재). `Current` 는 PWM 출력의 '전류'와 번역을 같이 써서 "전류 40%" 로 보였다.

## 시설 라벨 펼침 (지도)

지도 위젯의 시설 라벨은 고정 줌 기준 하나로 켜지지 않고 **시설마다 둘 중 한 상태**다. 규칙은 하나 — 시설이 화면에서 충분히 크면 펼침, 아니면 칩만.

- **접힘**: 시설 칩(`.aot-bay-chip`)만 보인다. 칩 3행에 `Running n/m`(켜진 출력/그 시설에 묶인 출력 전체)이 적힌다.
- **펼침**: 칩 + 그 시설의 설비 상태 글자·센서 값 라벨(`data-facility-label`, 클래스 `aot-facility-open`).
  펼친 시설에서는 설비별 글자가 같은 말을 하므로 요약은 비운다.

규칙(상수는 `aot-map-modals.js` `FACILITY_EXPAND` 한 곳, 길이는 "시설 긴 변의 화면 투영 ÷ 같은 방향의 지도 화면 길이"):

| 상수 | 값 | 뜻 |
|---|---|---|
| `open` | 0.40 | 이상이면 펼침 |
| `close` | 0.34 | 펼침을 끄는 기준(경계에서 줌을 오가도 깜빡이지 않게 낮게) |
| `chipMin` | 0.015 | 이보다 작은 시설(점)은 칩도 접는다(`aot-facility-tiny`) |

- **칩 클릭**: #666 이전 그대로다 — 시설을 가시 영역 한가운데에 놓고 맞춰 확대(`_openBayPopup` → `_focusMapOn`)하며
  시설 모달을 연다(시설 도형을 누르는 길은 없다). 칩을 누른 시설은 **도착한 시설**(`expandArrived`, 하나뿐)이 되어 점유율과
  무관하게 펼쳐 둔다 — 확대 뒤 점유율이 위젯에 따라 0.14~0.88 이라 기준 하나로는 성립하지 않았기 때문이다(실측 아래).
  클릭 때의 시야로 줌 아웃하면 접히고, 다른 칩을 누르면 옮겨 간다. 모달에 가려지는 것은 기존 그대로다.
- **칩 클릭 뒤 점유율 실측**(맥북 E2E, 시설 20 m×10 m, 줌 17 에서 클릭; 위젯 폭×높이): 대지 시야 / 모달 열린 채 / 닫은 뒤 —
  173×166: 0.26/0.88/0.88, 362×191: 0.12/0.88/0.14, 618×189: 0.07/0.41/0.21, 698×189: 0.06/0.08/0.19, 938×189: 0.05/0.14/0.14.
- 접힌 시설의 라벨은 CSS(`[data-facility-label]:not(.aot-facility-open)`, 위젯이 한 번 심는 스타일)로 DOM 에 있어도
  그려지지 않고 클릭도 받지 않는다. 계산은 카메라가 움직이는 동안(`move`·`moveend`·`resize`) 한다.
- 기존 유형 토글(출력 라벨·센서 값, `.aot-type-hidden`)은 펼침과 별개로 그대로 먹는다.
- `label_min_zoom`(L1) 은 **시설 밖의 라벨**(구역 장치·출력·입력·구획·노트)의 최소 줌으로 남는다. 시설 칩(`bay`)과
  시설 안쪽 라벨은 이 표의 대상이 아니다(`_applyZoomGate` 가 `data-facility-label` 을 건너뛴다).
- 요약은 컬 줌과 무관하게 접힌 시설에 적힌다. 신선도: 공급자(`AoTFacilityRuntime.get`)가 HTTP 실패·비정상 응답에
  null 을 돌려주면 수를 지어내지 않고 `Unknown`, stale 이어도 `Unknown`, 304 는 그대로 유지한다.
  `actuator_states` 는 slot_key 기준이라 `output_uuid` 로 중복을 걸러 센다. 비례 장치도 `on` 으로만 센다.
구현: `_applyFacilityExpand`·`_toggleFacilityExpand`·`_applyRunSummaries`(`aot-map-modals.js`),
E2E `test_journey_map_facility_state.py`.

## 외피 개구 — 창 자리의 벽·지붕이 실제로 뚫린다

외피는 `core/parametric.js` `buildOuterCoverPanels` 가 판으로 쪼개 그린다(`outer_cover_u<unit>_x_neg|x_pos|y_neg|y_pos|roof`).
측벽·마구리는 `ShapeGeometry.holes`, 지붕은 단면 폴리라인(아치=3차 베지에 18분할·gable·gable2·flat)을 호 길이 `s` 로
표를 만들어 `(s, z)` 격자로 쓸고 천창 사각형 `[s0,s1]×[z0,z1]` 안 조각을 건너뛴다 — 네 지붕형이 같은 코드다.
개구는 `coverOpeningsFromFittings(fittings)` 가 `side_window`·`window`·`door` 에서 뽑는다(`{walls, caps, roof}`):
법선 |nx|≥0.9 = 측벽, |nz|≥0.9 = 마구리, 그 밖에 ny≥0.3 = 지붕(설비 중심을 단면에 사영해 `s` 중심, `size.h` 가 경사 폭,
`size.w` 가 z 폭). 법선 없는 `window` 는 용마루 천창(`size.w` 가 x, `size.d` 가 z)으로만 본다. 판에서 `d + 0.1`(최소 0.25 m)
보다 멀리 떠 있는 상자는 개구가 아니다 — 보강 외피의 창, 공중에 뜬 창. 동이 여럿이고 간격이 있으면 측벽 허용 오차는 간격의
절반 아래로 더 줄여 틈의 창이 두 동을 다 뚫지 않게 한다. 겹치거나 맞닿는 구멍은 하나의 외접 사각형으로 합치고 안에 든 것은 버린다
(`_mergeRects` — 한 Shape 에 겹치는 holes 가 있으면 earcut 이 깨지고, 지붕 테두리 선이 서로의 안쪽을 지난다). 마구리 구멍 윗변은
그 x 구간의 단면 높이 최솟값 아래로 자른다(`_profileMinY` — 아치·박공 가장자리의 창이 윤곽 밖으로 나가지 않게). 구멍 테두리는 벽
테두리와 같은 선 재질 하나(`outer_cover_u0_roof_holes`). 각 판은 `userData.holes` 에 뚫은 수를 적는다(E2E·하네스가 읽는다).
창 상자(`fitting:<id>`)는 중심이 구멍 중심, 폭·높이가 구멍과 같으므로 닫힘 자세가 구멍을 정확히 덮고, 힌지(윗변)·권취·들창은
구멍 가장자리에서 움직인다.

번들: `facility-3d`(대시보드 위젯·지도 지연 로드)·`geo-design-facility3d`·`geo-facility` 모두 `core/parametric.js` 를
`aot-facility-3d.js` 보다 앞에 둔다. 없으면 뷰어는 옛 단일 껍질(`outer_cover_0`, 구멍 없음)로 폴백하고 콘솔 경고 한 줄을
낸다(`_warnNoParametric`) — 2026-11-07 이전 위젯·지도가 그 상태였다. `buildScene` 도 `buildFacilityMesh`(지도)처럼 저장된
설비 위에 외피 생성 항목을 id 로 병합한 한 목록으로 구멍과 설비 메시를 함께 만든다. 설계 화면은 창을 더하고 옮기고 크기를 바꾸고
지우면 `ctx.refreshCover(fittings)` 로 외피 판만 다시 자른다(장면 재빌드 없음, 한 프레임에 한 번, 외피 재질은 장면당 하나를 재사용).

### 레이아웃형 시설(`layout`)

`core/layout-mesh.js` 의 자유 평면 외피도 같은 규칙으로 뚫린다(`AoTLayoutMesh.build(layout, {…, fittings})`). 덩어리마다
`outer_cover_<block>_walls|_gable|_roof` 가 `userData.holes` 를 적는다. 벽은 축에 나란하지 않아도 된다 — 법선의 수평 성분이
0.9 이상인 창을, 법선이 나란하고(|cos| ≥ 0.9) 높이가 그 덩어리 벽 안이며 가장 가까운 **외벽 구간 하나**에만 뚫는다(같은 층
다른 덩어리와 맞닿은 변은 외벽이 아니고, 위아래 층은 높이로 갈린다). 박공 끝 구멍은 그 폭 위 지붕선 아래에서 멈춘다. 곡면·박공
지붕은 파라메트릭과 같은 `(s, v)` 격자(`v` = 용마루 방향, `ridge_axis` x·z 모두), 평지붕은 윗면 조각에서 천창 사각형을 빼고
테두리 선(`layout_roof_holes_<block>`)을 긋는다. 상자 방향은 `_quatFromNormal` 과 같다 — 폭 `w` 는 수평 접선, 높이 `h` 는 면을
따라 위, 법선이 수직이면 `w` 가 X·`h` 가 Z. 설계 화면은 `refreshCover` 가 모형 외피를 다시 짓고 층 보기를 되살린다. 지도 경로
(`_buildLayoutFacilityMesh`)는 저장된 설비만으로 뚫는다.
