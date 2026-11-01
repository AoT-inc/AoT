# 디지털트윈 노드(`aot_twin`) — 뼈대 설계

- 상태: **배포형 별도 서비스(S2, 2026-10-21)** + 노지 모델(물 수지 + EnKF) + 앞날 예보 입력. 시설 모델(그레이박스·UKF)은 아직 더미다. 배포형 전환 제안: `AoT_dev/plans/2026-10-21_twin_deploy_proposal.md`
- 상위: `AoT_dev/plans/2026-10-19_digital_twin_plan.md` §4 · 출력 계약: `docs/design/digital-twin.md`
- 정책(2026-10-21 개정): 공개 main 에 들어가는 '준비 중' 기능. 설정 > 일반 > 디지털트윈 (실험) 토글(기본 꺼짐)로 켜고, 데몬과 분리된 별도 서비스로 돈다. 낮은 사양 기기는 잠근다. (10-19 의 "비공개·main 병합 금지" 는 폐기)
- 코드: `aot/twin/` · 시험: `aot/twin/tests/`, `aot/tests/test_twin_discovery_db.py` · 배포: compose `aot_twin`(profile `twin`), `install/aottwin.service`, 개발용 `docker/docker-compose.twin-nas.yml`

## 1. 구조

```
              ┌──────────── TwinNode (node.py) ────────────┐
 설정 ──────▶ │ 시작 시 벤치(bench) → Capability            │
 (settings)   │ enqueue_all → ServerQueues(서버별 큐)        │
              │      └▶ process(job):                       │
              │          engine.run_target ─▶ output.flatten │
              └───┬──────────────────────────────────┬──────┘
         TwinSource(읽기)                      TwinSink(쓰기)
   ┌──────┴───────┐                         ┌───────┴───────┐
   │ EmbeddedSource│ 로컬 Influx 직접        │ EmbeddedSink  │ write_influxdb_value
   │ RemoteSource  │ GET /api/measurements/… │ RemoteSink    │ POST /api/twin/ingest (제안)
   └───────────────┘                         └───────────────┘
```

| 파일 | 역할 |
|---|---|
| `types.py` | `TargetSpec`(대상+배선), `SeriesRef`(계열+**출처 표시**), `Point`, `TwinOutput`(계약 §10.7), `Status` |
| `interfaces.py` | `TwinSource`·`TwinSink`·`TwinModel`(계약 §10.7 그대로) |
| `output.py` | `TwinOutput` → `env_twin`/`_lead`/`_meta`, `env_twin_field`/`_lead`/`_meta` 점. 채널 번호표는 계약이 정본 |
| `expiry.py`, `consumer.py` | 유효기한 규칙, 읽는 쪽 참조 구현(머리말 먼저, 유효할 때만) |
| `engine.py` | 대상 하나 실행: 전제 점검 → 읽기 → 초기화 → 앙상블 → `TwinOutput` |
| `bench.py` | 시작 벤치 → 앙상블 수·지평·주기 (원칙 5) |
| `queue.py` | 서버별 큐: 대상 합치기, 서버 간 돌아가며, 서버당 동시 1건 |
| `models/` | `registry`(끼우는 부품) + `dummy`(자리표시자) + `field_bucket`(노지 기본 모델 — `aot.functions.utils.field_twin` 을 그대로 import 해 배선만 한다, §6.1) + `facility_greybox`(시설 기본 모델 — 그레이박스 v3 + 숨은 열질량 + UKF, `aot.functions.utils.facility_twin`, §7) |
| `sources/` | `remote`(REST), `embedded`(지연 import — flask·DB 는 호출 시점에만) |
| `settings.py`, `__main__.py` | 설정 로드·검증, `python -m aot.twin [--once]` |

### 원칙이 코드에서 지켜지는 곳

| 원칙 | 구현 | 시험 |
|---|---|---|
| 1 파이는 트윈에 의존 안 함, 유효기한 | 모든 발행에 `valid_until`; status ≥ 2 는 `valid_until = t0`(즉시 만료). 서버가 안 닿으면 그 서버만 건너뜀. 작업 예외는 `process()` 안에 가둠 | `test_roundtrip` (만료 후 `usable_meta` = None, 서버 다운 건너뜀), `test_engine` (ERROR 는 곡선 없음) |
| 2 자문만 | 이 패키지는 장치 명령 경로를 import 하지 않는다. 쓰는 것은 `env_twin*` 측정뿐(싱크가 접두 검사) | `test_sink_rejects_non_twin_measurement`, `test_embedded_sink_refuses…` |
| 3 같은 코드 | 뼈대는 `TwinModel` 만 안다. 실제 시설 모델은 `aot.functions.utils.env_control.greybox` 를 감싸 `register()` 할 예정(아직 안 함) | — |
| 4 기존 저장소 | Influx `env_twin*`, 기존 `write_influxdb_value` 의미 그대로 | `test_output` |
| 5 성능에 맞춰 축소 | `bench.decide`: full(앙상블≤50) → deterministic(p50 만) → light(지평 24 h, 주기 늘림) | `test_bench_*`, `test_engine::test_light…` |
| 6 모델은 부품 | `registry` + `GRID_PLANS`(종류별 격자). 구획 종류로 모델 선택 | `test_field_kind_picks_field_model`, `test_field_roundtrip_mixed_site_one_node` |
| (계획서 §9) 출처 표시 | 필수 입력이 `measured` 가 아니면 `not_twinnable`(곡선 없음). 개발 시험용 `options.allow_unverified` 는 `degraded` 로만 | `test_unverified_provenance…` |

## 2. 두 방식은 같은 코드

내장·원격의 차이는 `TwinSource`/`TwinSink` 구현 둘뿐이다. 엔진·쓰기 층·큐·벤치는 공유한다.
`test_embedded_roundtrip` 은 같은 엔진을 내장 통로(가짜 `aot.utils.influx`)로, `test_roundtrip` 은 원격 통로(진짜 HTTP)로 돌린다.

`import aot.twin.node` 는 flask·sqlalchemy·influxdb_client·`aot.databases`·`aot.aot_flask` 를 **끌어오지 않는다**
(원격 노드 = AoT 서버 없는 컨테이너). 시험 `test_import_does_not_pull_server_modules` 가 가드한다.

## 3. 배포

| 방식 | 파일 | 기동 |
|---|---|---|
| **배포형 서비스(기본)** — Docker | `docker/docker-compose.yml`·`docker-compose.prod.yml` 의 `aot_twin` (profile `twin`, 기본 꺼짐, 메모리 768 MB, `unless-stopped`) | `.env` 에 `COMPOSE_PROFILES=twin` → `up -d` → 설정 > 일반 토글 |
| **배포형 서비스(기본)** — 직접 설치 | `install/aottwin.service` (`aotmcp.service` 와 같은 모양, 기본 비활성, `MemoryMax=768M`) | `upgrade_commands.sh install-aottwin` → 설정 > 일반 토글. 업그레이드 때 `restart-aottwin`(켠 기기만) |
| 개발용 JSON 노드 — NAS 원격 | `docker/docker-compose.twin-nas.yml` + `docker/twin/nas-dev.json` | 아래 §3.1 (`--config` 경로, 수신 API 필요 — **2026-10-24 수신 API 폐기, 원격 쓰기 비활성**) |

모두 profile `twin` 이라 기본 `up` 에는 안 뜬다(`docker compose config --services` 로 확인함). 진입점은 하나(`python -m aot.twin`)다: `--config`/`$AOT_TWIN_CONFIG` 가 있으면 개발용 JSON 노드, 없으면 배포형 서비스(§3.4).

### 3.1 NAS 에서 개발서버(로컬 8084)에 붙이기 — **사용자 확인 후에만 기동**

```bash
cd docker
cp twin/nas-dev.example.json twin/nas-dev.json        # <...> 채우기. nas-dev.json 은 .gitignore
export AOT_TWIN_DEV_URL=http://<개발서버 주소>:8084
export AOT_TWIN_DEV_KEY=<개발서버 API 키>              # 파일에 적지 않는다
docker compose -f docker-compose.twin-nas.yml --profile twin run --rm aot_twin --once    # 1회 왕복, 결과를 표로 출력
docker compose -f docker-compose.twin-nas.yml --profile twin up -d                        # 상시
```

- 이미지는 NAS 에 이미 있는 `aot_ai:ci-591`(P0 벤치에 쓴 것). `AOT_SRC` 로 이 브랜치의 `aot/` 를 읽기 전용 덮어 얹는다 — 이미지를 새로 빌드하지 않는다.
- 개발서버가 NAS 에서 닿아야 한다(Mac 로컬 8084 → LAN/Tailscale 주소). 맥이 꺼지면 노드는 "서버 응답 없음"으로 그 주기를 건너뛴다.
- ~~개발서버 쪽 수신 API 는 §5-1(구현됨).~~ **(2026-10-24 폐기)** 수신 API 를 걷어 냈다(§5-1). 이 NAS 경로는 2026-10-21 에 이미 내렸고, 노드의 원격 쓰기는 비활성이라 결과를 보내지 않고 그 주기를 "쓰기 실패(원격 쓰기 비활성)"로 적고 넘어간다.

### 3.2 정기 실행 — 하루 1~2회 (계획서 §9.8)

설정 JSON 의 `schedule` 이 있으면 `up -d` 한 컨테이너가 **벽시계 시각**에 `run_once()` 를 돌고 쉰다(`serve_scheduled`).

```json
"schedule": {"run_at": ["06:10", "18:10"], "timezone": "Asia/Seoul", "run_on_start": true, "retry_s": 900, "max_retries": 4}
```

- 발행은 구획 현지 오늘 00 시 기준 36 시간 유효(계약 §7)라 **하루 한 번만 돌아도 비는 시간이 없다**(다음 날 아침 발행이 앞 발행 만료 6 시간 전에 온다). 두 번째는 예보·관측을 한 번 더 새로 하는 용도다.
- `run_on_start`: 기동·재부팅 직후 한 번 따라잡는다(재기동이 잦아도 한 번 4 초 안팎).
- 서버가 안 닿거나 쓰기가 거부된 회차(`cycle_ok` 거짓)는 `retry_s` 간격으로 `max_retries` 번 다시 하되 다음 예약 시각을 넘지 않는다. 그래도 안 되면 다음 예약 시각까지 쉰다. `UNSYNCED`·`NOT_TWINNABLE` 은 정상 결과(머리말이 발행됨)라 재시도하지 않는다.
- `schedule` 이 없으면 예전처럼 `period_s` 간격(워커 스레드)이다. NAS 작업 스케줄러에서 `run --rm … --once` 를 예약하는 길도 그대로 쓸 수 있다.
- 컨테이너는 메모리 1 GB 상한, `restart: unless-stopped`.

### 3.3 앞날 입력 — 사용자가 등록한 예보 입력을 설정으로 고른다

노지 대상의 `options.forecast` 가 가리키는 AoT 예보 입력 채널을 읽어 앞날 비·ET0·기온으로 쓴다(`aot/twin/forecast.py`).
노드는 외부 API 를 부르지 않고, 제공자·지역을 가정하지 않는다. 예보 입력은 **받은 시각에 k 일 뒤 값을 채널 k 에 쓴다** — 한 값의 대상 날짜는 `저장 시각의 현지 날짜 + k`, 같은 날 여러 값이면 가장 늦게 받은 것. AoT 쪽 입력은 `OPEN_METEO_DAILY_FORECAST`(`aot/inputs/open_meteo_daily_forecast.py`, 채널 = 묶음×8 + 리드: 0 강수 일 합 · 1 ET0 · 2 최고기온 · 3 최저기온 · 4 강수확률). 같은 모양의 다른 입력(기상청 예보 등)도 쓸 수 있다.

- 신뢰 구간(오늘~+7 일) 8 일 모두에 예보 비가 있으면 발행 `ok`, 하나라도 비 없음으로 메우면 `degraded`. 반영 일수는 머리말 `rain_fc_days`(채널 26)에 싣는다.
- 예보는 점 하나라 앙상블이 없다 → 멤버마다 로그정규 비 배율 오차(평균 1), 표준편차 `log_sd + log_sd_per_day × 리드`(기본 0.35 + 0.08k, 상한 1.0). **가정값이며 검증 전**이다.
- 한계: 예보 0 mm 인 날은 배율을 곱해도 0 이라 '예보가 놓친 비' 는 담기지 않는다. 예보 ET0(FAO-56)와 지난 날 ET0(POWER·Hargreaves)의 출처가 다르면 편향이 생길 수 있다(`scale` 로 조정).

### 3.4 배포형 서비스 (S2, `service.py`·`gate.py`·`discovery.py`)

```
시작 ── twin_supported() ── 잠김 → 하트비트 locked, 일하지 않음(프로세스는 남아 드물게 하트비트 — 재시작 정책이 되살려 판정을 되풀이하지 않게)
  └─ 루프(60 초): twin_enabled()
       ├─ 꺼짐 → 하트비트 disabled. DB·Influx 를 읽지 않는다(데이터는 지우지 않는다)
       └─ 켜짐 → 계획(refresh_s 3600 초마다, 실행 시각이 바뀌면 바로): 켜진 대지 → 노지 구획 → TargetSpec
                 대지마다 실행 시각 = Misc.twin_run_times(대지 현지 시간대) + crc32(대지 id) % 20 분
                 실행: 내장 통로(로컬 Influx 읽기 · env_twin* 일괄 쓰기 write_influxdb_points)
```

- **전역 설정은 S1 의 정본을 쓴다**(`aot/utils/twin_gate.py`, alembic p6_90): `twin_enabled()`(플래그 AND 안 잠김)·`twin_supported()`(설정 화면·저장 경로와 같은 잠금 판정 = 이중 잠금: `HARDWARE_PROFILE=LOW`·작은 파이·메모리 3.5 GB 미만, `AOT_TWIN_IGNORE_PROFILE=1` 이면 프로파일 항목만 건너뜀)·`run_times()`·`write_heartbeat()`. 모듈이 없으면 꺼짐·잠금. twin_gate 는 앱 문맥 없이 돈다 — 잠긴 기기에서는 flask 앱을 올리지 않는다(계획을 만들 때만 앱을 만든다).
- **하트비트** `Misc.twin_heartbeat` = `{at, status, version, sites, plots, last_run_at, failures, locked_reason}` — `at`·`last_run_at` 은 ISO UTC(서비스 안에서는 epoch 초로 들고 `DbGate` 가 바꾼다), `status` ∈ running(켜짐 — 대기·계산 모두)·idle(꺼짐)·locked·error(마지막 회차 실패), `failures` = 대지별 마지막 회차의 실패 대상 수 합. 꺼져 있거나 잠겨 있어도 60 초마다(상태가 바뀌면 바로) — 화면은 180 초 넘게 낡으면 "실행 중이 아님".
- **자동 포함**: 대지(지도의 site 도형, 대지 밖 구획은 지도 하나 = `map:<지도 id>`) 안의 지금 재배 중인 노지 식생 구획(지도와 같은 `plot_context.active_plots`, 시설 구획 제외). `planted_on` = 구획 시작일, `timezone` = 대지 시간대, `lat` = 구획 대표점.
- **예보 사다리 자동**: 사람이 고르는 것은 예보 입력 id 하나(`forecast.input`). 입력 모듈이 채널마다 `forecast_lead_d`·`daily_stat` 을 밝히면(`OPEN_METEO_DAILY_FORECAST` 가 그렇게 한다) `(측정, 일 통계)` → 묶음(rain·et0·t_max·t_min)으로 사다리를 만든다. 꺼진 채널은 빈 리드, 사용자가 단위를 바꾼 묶음은 쓰지 않는다(모델은 mm·°C). 제공자·지역 이름은 보지 않는다.
- **사람이 고르는 것 = 대지·구획 트윈 설정**(S3, `twin_config` 표, `aot/utils/twin_config.py`, 화면은 지도 모달 '트윈' 탭 — S4): 대지 켜기, 비·기온·ET0(대지) → 구획 상속, 토양수분·지온(구획), 예보 입력, 구획 포함·제외, 출처 표시(실측·미러·가상·미확인). 구획에 키가 없으면 대지 값, 값이 null 이면 "이 구획에서는 없음". 제안(예보 입력 = 채널 메타를 밝힌 입력, 비·기온 = 대지에 지정된 기상대 채널, 관측 센서 = 구획 안이나 30 m 안 토양 채널)은 **사용자가 적용할 때만** 설정이 된다. **시설 설정**(scope `facility`, `aot/utils/twin_facility_config.py`)은 같은 표에 따로 둔다 — 입력·장치 실제 상태(`controls`)·출처를 시설 행에 직접 적고(대지 상속 없음), 켜기는 시설 행만(기본 끔), 출력 태그는 시설의 코디네이터 uuid. 시설만 켜진 대지도 계획에 들어간다(`discovery.build_plan`). 개발용 JSON(`--overrides`·`$AOT_TWIN_OVERRIDES`, 예시 `docker/twin/overrides.example.json`)은 명시했을 때만 그 위에 겹친다(기본 경로 없음). 배선이 틀린 구획은 그 구획만 빠지고 노트가 남는다.
- 비·센서가 배선되지 않은 구획은 엔진이 `not_twinnable` 머리말만 쓴다(곡선 없음 — 화면은 이유를 보인다).
- 실패 대지는 `retry_s`(900) 간격으로 `max_retries`(4) 번 다시 하되 다음 예약 시각을 넘지 않는다. 다른 대지는 영향이 없다.
- 시험: `aot/twin/tests/test_service.py`(꺼짐·잠금·하트비트·자동 포함·사다리·분산·재시도·DbGate 계약), `aot/tests/test_twin_discovery_db.py`(sqlite 로 진짜 모델).

## 4. 설정 항목 설계 — '트윈: 이 서버에서 / 다른 서버'

> **(2026-10-21) 이 절은 배포형 전환으로 대체됐다.** 서버 쪽 선택은 `twin_mode`(off·embedded·remote)가 아니라 전역 플래그 `Misc.twin_enabled`(S1, 설정 > 일반 > 디지털트윈 (실험) — 개발 설정 뒤에 숨기지 않는다)이고, 이 서버 계산은 별도 서비스가 맡는다(§3.4). 원격 노드(낮은 사양 기기용)는 뒤 단계(S6). 아래는 기록으로 남긴다.

### 4.1 두 역할을 나눈다

계획서 §4 의 표는 **이 서버의 트윈이 어디 있나**(서버 쪽 선택)다. 반대편에는 **이 기계가 다른 서버들의 트윈 노드 역할을 하나**(노드 쪽 선택)가 있다.
둘을 한 화면에 섞으면 방향이 헷갈리므로 이름을 가른다.

| 역할 | 어디에 저장 | 값 | 누가 읽나 |
|---|---|---|---|
| **A. 이 서버의 트윈** | 서버 `Misc` | `twin_mode`: `off`(기본) · `embedded`(이 서버에서) · `remote`(다른 서버) / `twin_node_url`: remote 일 때 노드 주소(표시·상태 점검용) | 서버 화면·MCP(예측 표시 여부), `aot.twin.settings.from_misc` |
| **B. 이 기계는 트윈 노드** | 노드 설정 JSON (`AOT_TWIN_CONFIG`) — 나중에 화면이 같은 JSON 을 편집 | `servers[]`: 서버 주소·`api_key_env`·대상 배선(`targets[]`) | `aot.twin.settings.load` |

- `remote`(A) 인 서버 X 는 **자기 안에 노드를 띄우지 않는다.** 노드(Y)가 X 를 읽으러 오므로, X 에는 Y 의 주소(표시용)와 Y 에게 줄 **API 키**가 필요하다. Y 의 설정(B)에는 X 의 주소·키 참조가 들어간다.
- `embedded`(A) 는 X 안에서 노드가 돈다. 대상·배선은 아직 JSON(B)이 정한다(자동 발견은 후속).
- 같은 기계가 A=`embedded` 이면서 B 로 다른 서버도 맡을 수 있다(`servers[]` 에 `embedded` 하나 + `remote` 여럿).

### 4.2 화면 위치와 숨김

- **설정 > 일반**의 개발 설정 구역(Matter 실험 스위치 `Misc.matter_enabled` 와 같은 자리·같은 방식). 개발 설정이 꺼져 있으면 트윈 항목은 **렌더하지 않는다** — 화면·MCP·API 어디에도 노출되지 않는다(비공개 결정).
- 항목: 라디오 3개(끔 / 이 서버에서 / 다른 서버) → "다른 서버"를 고르면 주소 입력 + "연결 시험" 버튼(노드의 상태 응답을 읽어 마지막 발행 시각·status 표시).
- 상태 신호등은 `usable_meta()` 규칙을 그대로 쓴다(만료·status ≥ 2 면 "없음").

### 4.3 비밀

- 노드가 서버를 읽는 **API 키는 설정 파일에 적지 않는다.** JSON 에는 `api_key_env`(환경변수 이름)만 있고 값은 컨테이너 환경에서 온다(`.gitignore`·로그에 안 남음; `RestClient.__repr__` 도 키를 가린다).
- 서버 쪽 키는 기존 API 키 모델(`api_key.py`)로 발급하되 **트윈 전용 권한**을 둔다: 읽기는 `view_settings`(기존 `/api/measurements/past` 요구), 쓰기는 새 권한 `twin_ingest`(§5-1)만. `edit_controllers` 같은 넓은 권한을 노드에 주지 않는다. **(2026-10-24)** 키 범위 `twin_ingest` 는 수신 API 와 함께 걷어 냈다 — 남은 행은 읽기 전용으로 본다(`user_api_key.RETIRED_READONLY_SCOPES`).

### 4.4 후속 마이그레이션(아직 안 함)

`alembic_db`: `misc.twin_mode VARCHAR default 'off'`, `misc.twin_node_url VARCHAR default ''`. 폼은 `forms_settings.py` + `utils_settings.py` 에 `matter_enabled` 와 같은 모양으로.
코드는 열이 없어도 동작한다(`from_misc` 는 `getattr` 기본값 → 꺼짐) — 그래서 이 뼈대는 마이그레이션 없이 먼저 병합 가능했을 구조지만, 정책상 병합하지 않는다.

## 5. 서버 쪽에 아직 없는 것 (후속)

1. **`POST /api/twin/ingest`** — 일괄 수신. **폐기(2026-10-24, 계획서 §9.19)**: 정식 경로는 서비스 `aot_twin` 이 내장 통로로 Influx 에 직접 쓴다. 수신 경로·키 범위 `twin_ingest`·요청 가드의 쓰기 예외·옛 개발 설정 게이트(`AOT_TWIN_ENABLED`)를 지웠고, 검증 규칙은 계약 검사기 `aot/twin/contract_check.py` 로 옮겼다(노드 출력 계약 시험·원격 싱크의 가짜 서버가 쓴다). 노드의 원격 쓰기는 **비활성**이다 — `RemoteSink` 는 보내지 않고 `REMOTE_WRITE_DISABLED`("서버 수신 API 없음 — 원격 쓰기는 비활성")를 오류로 돌려주며, 설정 검증(`ServerSettings.notices`)도 mode 'remote' 에 같은 이유를 알린다(거부하지 않음). `RemoteSource`·`RemoteSink` 는 원격 재설계(S6 원격 노드, 'AoT 쪽이 계산을 맡기는 방향' — 배포 제안 §2) 때 정리한다. 아래는 당시 기록. **구현됨(2026-10-20, 통합 브랜치)** — `aot/aot_flask/api/twin.py`, 검증 `aot/utils/twin_ingest.py`, 시험 `aot/tests/test_twin_ingest.py`. 실제 모양: 개발 설정 게이트(`AOT_TWIN_ENABLED=1` 또는 `Misc.twin_mode` — 열은 마이그레이션 전이라 없으면 꺼짐), 권한은 **API 키 스코프 `twin_ingest`**(읽기 전용 + 이 경로 쓰기 하나 — 역할 표에 새 열을 만들지 않아 마이그레이션이 없다. 요청 가드·MCP 쓰기 가드는 이 키를 읽기 전용으로 센다) 또는 `edit_controllers`. 요청마다 `pubs`(발행 머리말 요약)를 실어 조각마다 유효기한을 검사한다. 쓰기는 동기 일괄(`aot.utils.influx.write_influxdb_points`). 아래는 처음 적은 제안: 기존 `POST /api/measurements/create/...` 는 (a) 단위를 Unit 표에서 검증해 `env_twin*` 가 422, (b) 한 점씩이라 한 발행 약 4.7 천 점(실측 4,728)에 부적합. 계약은 `aot/twin/sources/remote.py` 머리말에 있다: `{"source":"aot_twin","points":[{"m","id","ch","ts","v","tags"}]}` → `{"written","rejected"}`. 서버는 `m` 이 `env_twin` 으로 시작하지 않으면 거부하고, 권한 `twin_ingest` 를 요구하며, 개발 설정이 꺼져 있으면 404.
2. **내장 쓰기 일괄화** — `write_influxdb_value` 는 점마다 클라이언트를 새로 연다. 4.7 천 점이면 느리다. `write_api` 한 번에 모으는 경로가 필요.
3. **대상 자동 발견** — 지금 대상·배선은 설정 JSON 이 정한다. 서버가 `GeoFacility`/`GeoPlot` 에서 대상과 센서 배선(+ 출처 표시)을 내려 주는 API(`GET /api/twin/targets`)는 후속. 출처 표시(`measured/mirror/virtual/unknown`)를 장치 설정 필드로 두는 것도 여기 묶인다.
4. **`ping_path`** — 서버에 가벼운 상태 엔드포인트가 없어 `GET /api/settings/measurements` 로 대신한다(키 유효성도 확인됨). 실제 서버에서 확인하지 않았다.
5. **읽기 창** — `/api/measurements/past/…/<past_seconds>` 는 "지금부터 과거"만 된다. 과거 시점 재생(리플레이)에는 `historical` 엔드포인트를 쓰는 `TwinSource` 가 따로 필요.

## 6. 노지 모델 연결 (`models/field_bucket.py`)

### 6.1 배선

엔진은 모델에 `run_target` 이 있으면 실행 전체를 맡긴다(전제 검사 — 필수 입력 `theta` 의 출처 표시 — 는 엔진이 먼저 한다). EnKF 는 심은 날부터 이력 전체를 동화해야 해서 "마지막 값으로 초기화"하는 범용 경로가 맞지 않기 때문이다. 상태는 아직 저장하지 않고 매 실행 처음부터 동화한다(NAS 실측: 128 멤버 × 76 일, REST 읽기 포함 1.9 s — 계획서 §9.6).

- 입력은 **설정이 가리키는 AoT 측정 계열만** 읽는다(외부 API 를 부르지 않는다): `theta`(필수), `rain`(필수), `t_air`(ET0 계열이 없으면 필수 — Hargreaves), `et0`(선택, 예: NASA POWER 입력의 ET0 채널), `soil_t`(선택 — 위치 변화 감지).
- 비 출처 선택 = `rain` 배선 + `options.rain = {agg, scale, kind, max_lag_d}`. 기상청 입력(15 분 강수를 5 분마다 되읽음)은 `hourly_mean_sum`·`scale 4`·`station`, 재분석 일 자료 입력은 `daily_last`·`reanalysis`·`max_lag_d 7` 처럼 둔다. `kind` 가 `meta.rain_src` 로 나간다.
- 앞날: 예보 계열을 아직 배선하지 않는다 → **비 없음 가정**, ET0·기온은 최근 7 일 평균, 발행 status = `degraded`. 띠에는 비 예보 불확실성이 없다.
- 출력: `env_twin_field` 0~2(θ_root %)·10~12(Dr)·20~22(Ks)·30~32(Ts1)·50~52(GDD)·**90~92(센서 칸 예측, 센서 %)**·70/71/74(물 부족·심한 물 부족·과습 확률), 선행 {1,3,7} 일 보관, 머리말(`sync_rmse_theta_1d`·`coverage_80` 은 최근 14 일 1 일 선행).

### 6.2 P1 재현 확인 (오프라인, 개발서버 덤프 `plans/twin_p1_field/dump.json`, 5 시드)

| 비 입력(배선) | ET0 | 1 일 선행 RMSE | P1 §9.5 |
|---|---|---|---|
| 기상청 김제 ch6 (`hourly_mean_sum`, ×4) | Hargreaves(기상청 기온) | 3.34 ± 0.10 %p | 3.12 |
| 기상청 김제 ch6 | POWER PM(계열로 넣음) | 3.42 | 3.12 |
| POWER 강수(계열로 넣음, `daily_last`) | POWER PM | **2.52 ± 0.08 %p** | 2.52 |

기상청 쪽 0.2 %p 차이는 초기 사전분포에서 온다(P1 은 07-25 첫 관측으로, 부품은 동화 시작일 첫 관측으로 θ0 를 잡는다). POWER 비는 P1 과 같은 값이 나온다 — 부품이 P1 과 같은 계산을 한다.

## 7. 더미 모델의 한계 — 이 뼈대가 증명하지 않는 것

더미는 "외기를 향해 지수적으로 끌려간다"뿐이다. 왕복(읽기→쓰기→유효기한→소비자 읽기)과 분위수·사건 평균의 배관만 검증한다. **예측 정확도, 동기화(UKF/EnKF), 보정(coverage_80), 실제 `sync_rmse_*`는 전혀 검증하지 않았다**(메타에서 비어 있다).
`GRID_PLANS` 에 노지 시 격자(`hourly`, `env_twin_field_h`)는 넣지 않았다 — 서리·잎 젖음은 노지 모델 세션이 모델과 함께 추가한다. 출력 층(`output.py`)에는 시 격자 표가 이미 있다.

## 8. 시험 기록 (2026-10-20)

- `python3 -m pytest aot/twin/tests` → **56 passed** (≈10 s).
- 변이 확인: `expiry.is_expired` 를 항상 False 로 바꾸면 시험 2건이 실패한다(되돌림).
- CLI 왕복(`python -m aot.twin --once`, 가짜 AoT 서버 ↔ 원격 통로, 시설 1 + 노지 1):
  `facility status=OK points=4728 written=4728`, `field status=OK points=150 written=150`, rejected 0. 저장 계열: `env_twin` 16, `env_twin_lead` 16, `env_twin_meta` 8, `env_twin_field` 8, `env_twin_field_lead` 8, `env_twin_field_meta` 6. 벤치: 더미 멤버 1개 0.003 s → full(앙상블 50).
- (2026-10-20 통합 브랜치) **NAS → 개발서버 왕복 성공** — 들깨 1 구 383 점 written, rejected 0, 1.9 s. 경로·수치는 계획서 §9.6.

## 7. 시설 모델 연결 (`models/facility_greybox.py`)

노지(§6)와 같은 모양이다: 모델·필터는 `aot.functions.utils.facility_twin` 에 두고(그레이박스 `_ode` 를 그대로 부른다 — 원칙 3) 이 파일은 배선과 출력 조립만 한다.

- **실행** `run_target`: 입력 이력(기본 48 h)을 읽어 9상태 UKF 로 마지막 측정 시각까지 동기화 → 일치도(1스텝·1 h 선행 RMSE)로 신호등 → 사후에서 멤버를 뽑아 600 s 격자 48 h 예측(현재 설정 유지·외기는 24 h 전 같은 시각 반복) → 분위수·위험 확률.
- **전제**: `T_int` `RH_int` `T_ext` `RH_ext` 가 배선·실측 표시여야 하고, `controls` 에 장치가 **실제로 한 일**(개도·가동 %) 계열이 하나 이상 있어야 한다(계약 §3 전제 b). 출처가 실측이 아닌 장치 입력은 `allow_unverified`(개발) 없이는 `not_twinnable`.
- **지연 import**: `env_control/__init__` 이 DB·Influx 모듈을 끌어오므로 시설 모델은 실행할 때 가져온다(노드 import 가드 시험이 지킨다). 시설 대상이 없는 노드는 그 모듈을 끌어오지 않는다.
- **비용** (M1, 합성 쌍둥이 자료): 동기화 48 h@120 s 약 3 s, 멤버 50 × 48 h 예측 포함 약 12 s. NAS 는 약 2.8 배(벤치 §9.2 비율).
- **전망 외기 (예보 단일 출처 3단계)**: `options.forecast_series.site`(대지 uuid)가 있으면 그 대지에 지정된 예보 입력의 시간별 시계열을 소스의 `read_forecast` 로 읽는다(원격: `GET /api/twin/forecast_series`, 내장: `geo.forecast_series.read` — 앱 컨텍스트 필요, 시설 대상이 DB 계획에 아직 없어 후속). 순간 값(기온·습도·풍속)은 직선 보간, 칸 값(일사)은 계단. 지평 밖·없는 변수·지정 없음·낡음은 일주기 지속으로 메우고(`degraded`, 이유는 `reason`) 머리말 `weather_src` 는 5(예보 사용)/4(지속만). 읽기 실패는 예보 없음과 같다(원칙 1). `RunResult.info["forecast"]` 에 출처·지평·변수별 예보 비율.
- **아직 없는 것**: 예보 지평 7일(입력이 48 h — 서버 쪽 확장 결정 대기), 노지 트윈의 예보 연결(일 사다리 → 같은 시계열), 정책 포함 폐루프, 영양·kumamoto 대상 표.
