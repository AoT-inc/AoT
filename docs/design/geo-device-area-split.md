# 장치 담당 구역 나누기 — 기하는 빌려 쓰고, 배정은 조용히 하지 않는다

구현: `aot/aot_flask/geo/device_split.py` ·
`aot/aot_flask/routes_geo_device_split.py` ·
`aot/aot_flask/static/js/geo/design/aot-geo-device-split.js`

## 요약

site/zone 도형을 잘라 **장치 담당 구역**(`GeoShape(type='device')`)을 만들고,
조각 안에 들어온 장치 마커로 **자동 배정**한다.

밸브 5개가 놓인 밭을 5구역으로 나눠 각 밸브에 맡기는 것은 흔한 작업인데,
지금까지는 구역 폴리곤을 **손으로 다섯 번 그려야** 했다. 눈대중으로 경계를
맞추니 조각마다 폭이 달라지고, 비스듬한 밭에서는 특히 어렵다.

식생 구획 나누기(`planting_split`, 정본 `geo-vegetation-planting.md`)가 이미
같은 문제를 푼다 — 다른 것은 **결과물뿐**이다.

| | 식생 분할 | 장치 구역 분할 |
|---|---|---|
| 기하 엔진 | `planting_split.split_shape` | **같은 것을 그대로 호출** |
| 미리보기 API | `/api/geo/planting/split-preview` | **같은 것을 그대로 호출** |
| 적용 API | `/api/geo/planting/split-apply` | `/api/geo/device/split-apply` |
| 만들어지는 행 | `GeoPlanting` | `GeoShape(type='device')` |
| 뒤따르는 일 | 작물·기간 기록 | 조각 안 마커로 장치 배정 |

## 엔진을 복제하지 않는다 (설계의 핵심)

분할 기하(등분·폭 지정·`widths_cm`·`orientation`·`angle_deg`·`edge_margin_cm`)는
`planting_split` 이 이미 정본이다. 여기서 같은 계산을 다시 구현하면 **두 벌이
갈린다** — 이 저장소가 반복해서 데인 형태(읽는 경로마다 기준이 다름)와 같은
성립 조건이다. 각도 처리 하나를 고칠 때 한쪽만 고치면, 같은 밭을 식생으로
나눌 때와 장치로 나눌 때 조각이 서로 다르게 떨어진다.

미리보기 엔드포인트를 공유하는 이유도 같다. `split-preview` 는 **도형을 잘라
조각을 돌려줄 뿐 작기와 아무 상관이 없다.** 장치용으로 똑같은 것을 하나 더
만들 이유가 없다. 갈리는 것은 **적용**뿐이다.

### 다만 하한은 다르다

`planting_split` 의 `min_bed_length_m` 기본값은 **두둑 기준(2m)** 이다. 장치
담당 구역은 두둑이 아니라서 그 값을 그대로 쓰면 **밸브 하나가 맡는 좁은
구역이 조용히 버려진다.** 여기서는 자투리만 걸러낼 정도로만 낮춘다
(`_MIN_AREA_LENGTH_M = 0.5`).

## 자동 배정 — 하나일 때만 한다

조각을 만든 뒤 **그 조각 안에 들어온 장치 마커**(`aot_device` 점)를 찾아 그
장치를 조각에 배정한다. 사람이 이미 밸브를 지도에 놓아 뒀다면 추가 입력 없이
연결이 끝난다 — "밸브 5개 놓인 밭을 5구역으로" 라는 작업 순서와 정확히 맞다.

애매하면 **배정하지 않고 그대로 알린다**:

| 조각 안 후보 | 처리 | `reason` |
|---|---|---|
| 0개 | 미배정 (나중에 '장치 배정' 으로 고른다) | `no_device` |
| 정확히 1개 | 배정 | — |
| 2개 이상 | 미배정 | `ambiguous` |

조용히 첫 번째를 고르면 **사용자는 틀린 배정을 눈치채지 못한다.** 지도에는
구역이 다 생겼고 이름도 붙었으니 다 된 것처럼 보이는데, 실제로는 엉뚱한 밸브가
그 구역을 맡고 있다. 배정은 물을 어디로 보낼지의 문제라 틀리면 결과가 밭에
나타난다.

### `device_kind` 를 주지 않으면 거의 항상 애매해진다

밭 하나에 센서·밸브·함수 마커가 수십 개 섞여 있어서, 조각 안에 딱 하나만
들어오는 일이 드물다. **실측: 마커 32개인 지도를 16조각으로 잘랐더니 배정
0건, 전부 없음/애매함이었다.** "밸브만 보고 나눈다" 로 좁히면 그제서야 조각과
장치가 1:1 로 맞는다.

그래서 API 는 `device_kind` 를 받고, 화면은 장치 종류를 고르게 한다. 비워 두면
전 종류가 후보다 — 문법적으로 유효하지만 실사용에서는 거의 쓸모가 없다.

실존하지 않는 장치를 가리키는 마커(지워진 장치가 남긴 것)는 후보에서 함께
걸러진다(`resolve_device_kind` 가 `None` 을 돌려준다). 죽은 참조를 배정으로
승격시키면 고아가 정본이 된다 — `backfill_geo_binding` 과 같은 규칙이다.

### 마커는 호출당 한 번만 읽는다

`device_membership.load_markers(geo_id)` 를 조각마다 부르면 조회가 조각 수만큼
반복된다. 한 번 읽어 `device_ids_in_geometry` 에 넘긴다.

## 쓰기는 전부 기존 계약을 지나간다

- **배정은 게이트웨이 경유**(`device_binding.bind`) — `check_geo_writes.py` 의
  GB-7 이 강제한다. `bind` 는 점유된 슬롯을 거부하므로, 이미 배정된 장치가
  걸리면 `BindingError` 가 나고 그 조각은 `no_device` 로 남는다(경고 로그).
  덮어쓰지 않는다.
- **`role='area'`, `entity='shape'`** 로 배정한다. 마커 배정(`position`)이
  아니다 — 구역 폴리곤이므로.
- **`type='device'` 는 만들 때 정한다**(GEO-I7 — 넣은 뒤에는 못 바꾼다).
  장치를 고르지 않고 그린 구역 폴리곤도 `type='device'` 로 저장하는 기존 정책과
  같다. `aot_device` 로 남기면 나중에 장치를 배정할 수단이 영영 없어진다.
- **`feature.properties` 에 구조 속성을 넣지 않는다**(`_clean_feature`).
  `aot_type`/`device_id`/`channel_id` 는 읽을 때 파생해 주입되는 값이라 저장하면
  안 된다(GEO-I6 / GB-5 트리거가 막는다). 종류는 `GeoShape.type` 이 정본이고,
  장치 연결은 `GeoBinding` 이 정본이다. 저장하는 것은 `name` 뿐이다.

## 하지 않는 것

- **마커를 옮기거나 만들지 않는다.** 배치는 `device_placement` 의 일이다.
  이 도구는 이미 놓인 마커를 **읽기만** 한다.
- **소속(membership)을 건드리지 않는다.** 장치가 어느 zone 에 속하는지는
  위치에서 파생되는 별개 축이다(`device_membership` 의 경고 참조). 담당 구역과
  소속은 다른 질문이고, 섞으면 구역을 나눌 때마다 장치 소속이 바뀐다.
- **화면이 본 폴리곤을 저장하지 않는다.** 적용은 미리보기와 **같은 파라미터로
  서버가 다시 계산**한다. 본 것과 저장된 것이 같다는 보장은 재계산이 한다
  (식생 분할과 같은 이유).

## 미배정을 숨기지 않는다

응답은 `assigned` 와 `unassigned` 를 모두 싣고, 미배정이 있으면 메시지에
개수를 적는다(`'%d of %d areas had no single device inside'`).

지도에는 구역이 다 생겼는데 절반이 장치 없이 남은 것을 모르면, **그 구역은
아무 일도 하지 않으면서 있는 것처럼 보인다.** 성공 개수만 보고하는 것은
이 저장소가 여러 번 겪은 "조용한 실패" 의 전형이다.

## 불변식 (DS-n)

| | 내용 | 강제 |
|---|---|---|
| DS-1 | 분할 기하는 `planting_split.split_shape` 만 쓴다 (복제 금지) | 문서 · 코드 구조 |
| DS-2 | 만들어지는 행은 `GeoShape(type='device')` — 생성 시 확정 | GEO-I7 |
| DS-3 | `feature.properties` 에 `aot_type`/`device_id`/`channel_id` 금지 | GEO-I6 · GB-5 트리거 |
| DS-4 | 조각 안 후보가 **정확히 1개**일 때만 배정 | `_auto_bind` |
| DS-5 | 배정은 `device_binding.bind` 경유, 점유 슬롯은 덮어쓰지 않는다 | GB-7 검사 |
| DS-6 | 미배정 건수를 응답에서 숨기지 않는다 | 라우트 |
| DS-7 | 마커를 만들거나 옮기지 않는다 | 문서 |

## API

```
POST /api/geo/device/split-apply     (login_required + 편집 권한)
```

본문은 식생 분할과 같은 분할 파라미터(`split_args_from`/`split_kwargs_from` 를
`routes_geo_planting` 에서 공유) + `name`(구역 이름 접두, 조각마다 `이름 N`) +
`device_kind`.

응답: `{ok, created[], info, assigned, unassigned[], message}`.
`created[]` 는 `{unique_id, index, name, device_id|null, area_m2}`.

도형 조회와 파라미터 검증이 **먼저** 끝난다(`compute_split`) — 거기서 걸리면
아무것도 만들지 않는다.

미리보기는 식생과 공유한다: `POST /api/geo/planting/split-preview`.

## 화면

`aot-geo-device-split.js` — 장치 모드의 **구역 나누기**. 흐름은 식생 분할과
같다(도형 선택 → 조건 변경 시 점선 제안이 지도에 따라옴 → 만들기).

**미리보기 GL 레이어 id 는 식생 것과 겹치면 안 된다** — 겹치면 서로를 지운다.
`_aot_devsplit_*` 접두를 쓴다.

## 남은 것

- 배정 실패(점유 슬롯)를 `no_device` 와 구분해 표면화할지 — 지금은 둘 다
  `no_device` 로 합쳐지고 근거는 로그에만 남는다.
- 조각 안 후보가 여럿일 때 화면에서 바로 고르게 할지(지금은 만든 뒤 '장치
  배정' 으로 따로 고른다).
