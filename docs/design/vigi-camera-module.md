# VIGI 카메라 모듈 — 설계 (2026-11-04 확정)

> 상태: **확정본**. 2026-11-04 사용자가 §12 의 질문 13건에 답했다("추천안대로" 승인, 답은 §12 에 적었다). 구현은 §11 의 단계 순서를 따르고, 단계마다 사용자 승인을 받는다.
> 근거 자료: 조사 보고서 `vigi-camera-research-20261104.md`(공식 VIGI IPC Open API V1.1 분석, 비공개 작업 폴더),
> 현장 인계 문서(aot-lite-012, C540V 실측). 이 문서는 실카메라·배포 서버에 접속하지 않고 썼다.
> **작업 환경(2026-11-04 사용자 결정)**: 카메라 작업은 배포 서버에서 하지 않는다. 기본 시험 환경은 로컬 8084 다. 배포 서버 접속·파일 복사·재시작 단계는 없다.
> 표시: **[문서]** 공식 문서로 확인 · **[실측]** 현장 실측 · **[미확인]** 근거 없음 → §12 질문 또는 §10 실카메라 확인.

## 0. 요약

- **제조사 중립 틀 `aot/camera_drivers/`** 를 새로 만들고, 그 안에 첫 구현으로 **VIGI 드라이버**를 둔다. 미완성 모던 패키지 `aot/camera/`(service·api·backend_*)는 import 하지 않는다. 카탈로그 사전(`aot/camera/types.py::CAMERA_TYPES` — 26-11 옛 패키지 처분 뒤 `aot/utils/camera_types.py`)에 항목 하나만 더한다 — 화면이 실제로 읽는 유일한 사전이기 때문이다.
- 영상은 **레거시 경로**에 붙인다. `Camera.library = 'vigi'` + `aot/aot_flask/camera/camera_vigi.py`(파일 이름 규약). `/video_feed`·`/camera/last_image`·촬영·타임랩스·위젯이 그대로 동작한다.
- **Open API(제어·능력·이벤트)는 데몬만 다룬다.** 카메라당 세션 하나, 인증 실패 래치를 쓰는 곳도 데몬 하나다. Flask 는 데몬 RPC 로 부탁한다. RTSP 영상은 지금처럼 Flask 가 받되, 인증 래치는 **DB 에 두고** 모든 프로세스가 지킨다. gunicorn 워커가 여럿이라 메모리 래치로는 막지 못한다.
- 데이터는 **새 테이블 두 개**에 둔다. 1:1 드라이버 설정 `camera_driver` 와 이벤트 기록 `camera_event` 다. 여기에 `camera.tab_id`(그룹 스코프)와 `trigger.event_kinds` 컬럼을 더한다. 마이그레이션은 한 건이다(§5.5). `custom_options` 는 쓰지 않는다. 이 값은 fswebcam·raspistill **명령줄에 그대로 붙는 문자열**이다(`aot/devices/camera.py:169`).
- 감지 이벤트는 **새 트리거 종류 `trigger_camera_event`** 로 Function 에 들어간다. 기존 푸시형 입력(`rpi_edge`, `matter_node`)이 `trigger_edge` 를 발화하는 방식과 같다. 다만 이벤트 종류별로 거를 수 있게 한다.
- 카메라를 움직이는 조작(PTZ·경보 등)은 **카메라의 탭으로 그룹 스코프 판정**을 받는다. 탭이 없는 기존 카메라는 지금처럼 전원 공개다.
- 인증 보호(조사 §5)는 **계약**이다. 실패 1회면 래치하고 중단한다. 자동 재시도는 없다. 재인증은 성공한 자격 증명으로만 한다. 비밀번호는 로그에 남기지 않는다. 검증 안 된 자격 증명은 **프로세스를 통틀어 한 번만** 시도한다.

## 1. 범위

| 포함 | 제외 |
|---|---|
| VIGI IPC(Open API V1.1) 카메라: 연결·능력 협상·라이브·스냅샷·PTZ·프리셋·주야 모드·수동 경보·SD 상태·이벤트 구독·검색 | **NVR**(사용자 결정) |
| 이벤트 → Function 트리거 | 녹화 재생·다운로드·양방향 음성(MULTITRANS, RTP 직접 파싱 필요) — 틀에 자리만 둔다 |
| 다른 제조사가 들어올 인터페이스 | ONVIF 범용 드라이버 구현(자리만, 별도 단계) |
| 화면: 설정 모달·OpenAPI 안내·검색·PTZ·이벤트 | CV(영상 분석) 구현(붙을 자리만 정의) |
| | AI·MCP 도구 추가(MCP 표면 동결 규칙, `test_mcp_surface_freeze.py`) |

## 2. 현재 구조에서 그대로 쓰는 것과 고칠 점 (실측: 코드)

- `/video_feed/<id>`(`routes_general.py:575`)는 `import_module('aot.aot_flask.camera.camera_' + library)` 로 모듈을 고른다. 응답은 `BaseCamera` 스레드가 만든 JPEG 를 MJPEG 로 중계한다. `camera_vigi.py` 하나만 두면 붙는다.
- `routes_camera.py` 권한 표: 보기는 `view_camera`, 바꾸기·움직이기는 `edit_controllers` 다. 새 엔드포인트도 이 표에 넣는다.
- `Camera` 에는 **`tab_id` 가 없다.** 그래서 그룹 스코프 판정 대상(`scope._DEVICE_MODEL_NAMES` 7종)에 없고, 카메라 조작은 지금 "전원 공개"다. PTZ·수동 경보는 카메라를 실제로 움직이거나 울리므로 이것이 문제가 된다. → **`Camera.tab_id` 를 더한다**(Q5 확정, §5.5·§6.3).
- gunicorn 은 `gthread` 에 워커 N 개다(`install/gunicorn_conf.py`). `BaseCamera` 의 스레드·프레임은 **워커마다 따로** 있다. 두 워커가 같은 카메라를 보면 RTSP 연결이 둘 생기고 인증도 두 번 일어난다.
- 브랜치 `art/elastic-pike-144f1d`(미병합)의 의존 관계:
  - `base_camera.py`: 카메라별 유예(`idle_grace`)와 종료 처리. `camera_options` 를 클래스 변수 하나에서 **unique_id 별 사전**으로 바꿨다. 지금 main 의 `camera_ip_camera.py` 는 마지막에 설정한 카메라가 이기는 공유 변수다. `camera_vigi.py` 는 **이 수정 위에 선다** → P2 전에 main 병합이 선행 조건이다(Q12 허용). 병합 PR 은 관리 세션이 처리하고, 이 설계는 의존 관계만 적는다.
  - `net_auth.RetryBackoff` 는 인증 실패 뒤에도 60→900 초 간격으로 **다시 시도한다**. `fetch_snapshot` 은 Basic 다음에 Digest 를 **차례로 시도한다**(실패가 2회 쌓일 수 있다). 둘 다 VIGI 계약(실패 1회 즉시 중단)과 어긋나므로 **VIGI 경로에서는 쓰지 않는다.** 마스킹(`redact_url`)과 URL 인코딩(`build_stream_url`)만 재사용한다. 이 브랜치는 수정하지 않는다.
  - PR #536 의 위젯 수정(`AoT_camera.py`)은 레거시 `Camera` 목록과 `/video_feed` 를 쓴다. VIGI 카메라는 `Camera` 행이라 위젯이 그대로 보여 준다. 위젯 안 PTZ 는 2026-11-04 사용자 결정으로 넣었다(§9.3 위젯 측 간결판).

## 3. 모듈 경계와 패키지 배치

```
aot/camera_drivers/                 제조사 중립 틀 (aot.camera.* import 금지 — 검사로 고정)
  __init__.py                       registry: vendor 키 → Driver 클래스
  driver.py                         CameraDriver 인터페이스, CamResult, 오류 분류
  capabilities.py                   능력 어휘(제조사 중립)와 Capabilities 값 객체
  auth_guard.py                     인증 래치·자격 증명 지문·시도 임대(DB, 프로세스 공용)
  frames.py                         FrameSource 인터페이스, FrameHub(팬아웃), 최신 프레임 파일
  events.py                         CameraEvent, 데몬 내 이벤트 버스, 트리거 디스패처
  discovery.py                      검색 정책(서브넷 고르기·속도 제한), Probe 인터페이스
  service.py                        데몬 쪽 CameraDriverService(세션·구독 스레드 관리, RPC 진입점)
  vigi/
    openapi.py                      HTTPS JSON 클라이언트: doAuth 2단계, call(method, params), 오류코드 표
    driver.py                       VigiDriver(CameraDriver)
    capability_map.py               getModuleList·get*Capability → 능력 어휘
    subscribe.py                    subscribeMsg 연결 유지·multipart 파서·하트비트 감시
    probe.py                        20443 doAuth(params null) 식별, 554 탐침
    streams.py                      RTSP 경로 규칙(/stream1 주, /stream2 부, /stream6 MJPEG)
    errors.py                       -10020/-10021/-10022 등 → 오류 분류
aot/aot_flask/camera/camera_vigi.py 레거시 규약 어댑터(library='vigi'): FrameSource → BaseCamera
aot/aot_flask/routes_camera_driver.py  설정·연결 확인·PTZ·이벤트·검색 엔드포인트(데몬 RPC 호출)
aot/tests/fixtures/vigi_mock/       Open API 모의 서버(§9)
```

### 3.1 드라이버 인터페이스 (제조사 중립)

```text
class CameraDriver:
    vendor: str                                   # 'vigi', 이후 'onvif' 등
    def verify(credential) -> CamResult           # 연결 확인 — 사용자가 누를 때만 호출된다
    def capabilities() -> Capabilities            # 캐시 우선, 새로 묻기는 verify/사용자 요청 때
    def device_info() -> CamResult
    def stream_profiles() -> list[StreamProfile]  # 주/부/MJPEG, RTSP URL 생성(자격 증명 제외)
    def ptz_move(vector, speed) / ptz_stop() / ptz_goto(preset) / ptz_set_preset(id, name)
    def set_day_night(mode) / manual_alarm(start|stop)
    def open_event_stream(kinds) -> EventStream   # 반복자: CameraEvent | Heartbeat
```

- 지원하지 않는 기능은 메서드가 `CamResult(state='unsupported')` 를 돌려준다. 화면은 `Capabilities` 를 보고 그 기능을 **아예 그리지 않는다.** 제품별 하드코딩 표는 두지 않는다.
- **`CamResult` 는 성공을 따로 증명한다.** 상태는 `accepted`(카메라가 `error_code: 0` 으로 받음) · `refused`(권한·스코프·래치로 거부) · `failed`(오류코드나 네트워크 오류) · `unsupported` · `unverified`(응답이 비었거나 형식이 틀림) 다섯이다. **빈 응답이나 HTTP 200 만으로는 `accepted` 가 아니다.** CLAUDE.md 의 실패 판정 규칙대로 JSON 의 `error_code` 를 먼저 본다. PTZ 의 `accepted` 는 "카메라가 명령을 받았다"는 뜻일 뿐이고, 화면도 "이동 완료"라고 쓰지 않는다.

### 3.2 능력 협상

`verify` 에 성공하면 한 번 `getModuleList` 를 부르고, 그 결과에 따라 `getPTZCapability`·`getAudioCapability`·`getVideoCapability`·`getEventEnhanceCapability` 를 부른다. 결과는 `camera_driver.capabilities`(JSON)에 시각과 함께 저장한다. 다시 묻는 것은 사용자가 "기능 다시 읽기"를 누르거나 펌웨어 버전(`getDeviceInfo.swVer`)이 바뀌었을 때뿐이다.

| 능력 어휘(중립) | VIGI 근거 |
|---|---|
| `ptz.pan_tilt` | 모듈 `ptz` |
| `ptz.zoom` | 모듈 `ptz_zoom` |
| `ptz.preset` (최대 8) | `ptz` + 프리셋 id 1~8 **[문서]** |
| `ptz.speed_max` | `getPTZCapability` |
| `day_night` | `dayNightMode` |
| `alarm.sound` / `alarm.light` / `alarm.manual` | `sound_alarm_enabled` / `light_alarm_enabled` / `manualAlarm` |
| `audio.speaker` / `audio.mic` | `audio_speaker` / `audio_microphone` |
| `storage.sd` | `sdCard` |
| `events.push` | `msgPush` |
| `event.<kind>` (12종) | 각 감지 모듈 이름(아래 표) |
| `event.enhance.people` / `.vehicle` | `getEventEnhanceCapability` 비트마스크 |
| `record.playback` / `record.download` | `playback` / `download` (이번 범위에서는 표시만) |

이벤트 종류 어휘(중립 → VIGI 모듈). VIGI 의 `event_type` 문자열 철자는 문서 예시(`TamperDetection`)로 한 건만 확인했다. 나머지는 **[미확인]** 이다. 매핑 표는 `capability_map.py` 한 곳에 두고 실카메라에서 확정한다(§10 #V4).

`motion`(motionDetection) · `crossline`(CrossLineDetection) · `intrusion`(InvasionDetection) · `area_entry`(AreaEntryDetection) · `area_leave`(AreaLeaveDetection) · `people`(PeopleDetection) · `vehicle`(VehicleDetection) · `drop_take`(DropAndTakeDetection) · `loiter`(LoiterDetection) · `tamper`(tamperDetection) · `scene_change`(SceneChangeDetection) · `audio_anomaly`(AudioAnomalyDetection)

강화 이벤트(`xxx_yyy_enhance` 꼴)는 같은 종류에 `enhanced='people'|'vehicle'` 속성을 붙인 것으로 정규화한다. 알 수 없는 `event_type` 은 버리지 않는다. `kind='unknown'` 과 원문으로 기록만 하고 트리거로는 보내지 않는다.

### 3.3 프레임 소스 추상화 (CV 가 붙을 자리)

```text
FrameSource       open() / read() -> Frame{jpeg: bytes|None, image: ndarray|None, ts_utc, seq} / close()
  RtspCv2Source   /stream1·/stream2 (H.264, cv2 + rtsp_open 옵션)
  RtspMjpegSource /stream6 (JPEG 페이로드라 다시 인코딩하지 않는다)
FrameHub          카메라당 프로세스당 하나. 소스 하나 → 구독자 여럿(최신 프레임만 유지, 느린 구독자는 건너뜀)
  구독자: MjpegRelay(/video_feed) · LatestFrameFile(스냅샷용) · (향후) CvPipeline
```

- `camera_vigi.Camera.frames(unique_id)` 는 `FrameHub` 에서 JPEG 를 꺼내 `BaseCamera` 규약대로 내보낸다. 레거시 코드는 바꾸지 않는다.
- **CV 의 자리**: `FrameHub.subscribe(rate_hz, want='image'|'jpeg')` 다. CV 는 gunicorn 워커 안에서 돌리지 않는다(요청 스레드 풀과 경쟁하고 워커 수만큼 중복된다). 향후 CV 는 데몬 또는 별도 작업 프로세스가 **자기 `FrameHub` 를 열어** 구독한다. 그 결과는 `CameraEvent(kind='cv.<이름>')` 로 같은 이벤트 버스에 들어오게 한다. 그러면 VIGI 이벤트와 CV 이벤트가 같은 트리거 경로를 탄다. 이번 범위는 인터페이스와 이벤트 종류의 이름 공간(`cv.` 접두사 예약)까지다.

### 3.4 이벤트 버스

데몬 안에 `CameraEventBus` 하나를 둔다. 생산자는 VIGI 구독 스레드다(향후 CV). 소비자는 ① `camera_event` 기록과 ② `trigger_camera_event` 디스패처다. 버스는 메모리 큐(상한 1,000, 넘치면 가장 오래된 것을 버리고 버린 수를 센다)이고 소비자 스레드 하나가 처리한다. 구독 스레드는 트리거 실행을 기다리지 않는다.

## 4. 프로세스 역할

| 일 | 맡는 프로세스 | 이유 |
|---|---|---|
| Open API 인증·stok 보관·제어 호출·능력 질의 | **데몬** (`CameraDriverService`) | 카메라당 stok 하나. 클라이언트 수 제한(-10021)과 잠금(-10022)을 한 곳에서 관리한다 |
| 이벤트 구독(`subscribeMsg`) | **데몬** | 오래 사는 연결이다. 트리거 실행(`trigger_all_actions`)도 데몬에 있다 |
| 네트워크 검색 | **데몬**(Flask 는 시작·결과 조회만) | 수십 초 걸리는 일을 요청 스레드에 두지 않는다 |
| 라이브 RTSP → MJPEG | **Flask**(레거시 그대로) | `/video_feed` 규약. 래치는 DB 에서 읽는다 |
| 스냅샷 | Flask(최신 프레임 파일) / 데몬(`camera_record`) | §7 |
| 설정 저장·화면 | Flask | 저장 뒤 데몬에 `camera_driver_refresh(uid)` 를 알린다 |

데몬 RPC(`DaemonControl` 에 추가): `camera_driver_refresh`, `camera_driver_verify`, `camera_driver_call(uid, op, args)`, `camera_scan_start(subnet)`, `camera_scan_result(scan_id)`. 이 가운데 **카메라를 움직이거나 울리는 op(`ptz_*`, `manual_alarm`, `set_day_night`, 이벤트 스위치 쓰기)** 는 `check_scope_gates.DAEMON_CONTROL_CALLS` 에 이름을 올린다. 그래야 그 호출을 부르는 Flask 뷰가 `GATED_CONTROL_VIEWS` 에 들어오는지 검사가 본다(§6.3).

## 5. 데이터 모델

### 5.1 결정: 새 테이블 (마이그레이션 1건)

`Camera.custom_options` 를 쓰지 않는 이유:
1. 이 값은 fswebcam·raspistill 등 **명령줄에 그대로 붙는 문자열**이다(`devices/camera.py:169,226`). JSON 을 넣어 두었다가 library 가 바뀌면 그 JSON 이 셸 인자가 된다.
2. 텍스트 칸이라 검사·부분 갱신·인덱스가 없다. 래치는 여러 프로세스가 비교 후 갱신(compare-and-set)해야 하는데 텍스트 JSON 으로는 할 수 없다.
3. 비밀번호를 봉인(`aot/utils/crypto.seal_secret`)해서 둘 칸이 필요하다. 지금 `Camera.auth_password` 는 평문이다.

`Camera` 에 컬럼을 더하는 대신 **1:1 테이블**로 두는 이유: 제조사 중립 틀에 속하는 값이라 다른 드라이버도 같은 테이블을 쓴다. 레거시 카메라 행에는 영향이 없다. 드라이버를 지우면 행 하나만 사라진다.

### 5.2 `camera_driver` (Camera 1:1)

| 컬럼 | 형 | 뜻 |
|---|---|---|
| `camera_id` | str36, PK·FK `camera.unique_id` ON DELETE CASCADE | |
| `vendor` | text | `'vigi'` |
| `host` | text | IP 또는 호스트 이름 |
| `mac` | text, null | 검색·`getDeviceInfo` 로 얻은 MAC. DHCP 로 IP 가 바뀌어도 같은 장치인지 알아보는 근거. **주소를 자동으로 고치지 않는다**(Q8): 검색에서 같은 MAC 이 다른 IP 로 보이면 "주소가 바뀐 것 같습니다 — 새 주소로 바꾸기" 제안만 띄우고, 사용자가 누르면 저장한 뒤 연결 확인 1회를 한다 |
| `openapi_port` / `rtsp_port` | int | 20443 / 554 기본 |
| `username` | text | 기본 `admin`, 사용자가 바꿀 수 있다(Q6). 문서의 digest 식은 `admin` 을 쓰므로 Open API 는 이 값을 식의 사용자명 자리에 넣는다. 다른 계정이 Open API 에서 되는지는 **[미확인]** 이고, 안 되면 인증 실패 1회로 래치된다(계약 그대로) |
| `password_sealed` | text | `seal_secret`. 로그·RPC 응답·화면에 평문을 내지 않는다 |
| `credential_fp` | text | (username, password) 를 서버 비밀값으로 HMAC 한 지문. 비밀번호를 복원할 수 없다 |
| `verified_fp` | text, null | **마지막으로 인증에 성공한** 자격 증명의 지문 |
| `auth_state` | text | `unverified` · `ok` · `failed` · `locked` · `openapi_off` · `cert_changed` |
| `auth_iface` / `auth_code` / `auth_at` | text / int / datetime(UTC) | 마지막 실패가 난 곳(`openapi`·`rtsp`), 오류코드(-10020, 401 등), 시각 |
| `attempt_lease_until` | datetime(UTC), null | 검증 안 된 자격 증명의 **시도 임대**(§6.1) |
| `tls_pin_sha256` | text, null | 처음 연결 확인에 성공했을 때 고정한 인증서 지문(TOFU, Q7 확정). 이후 지문이 다르면 **자격 증명을 보내기 전에** 멈추고 `auth_state='cert_changed'` 로 둔다. 화면이 새 지문을 보여 주고 사용자가 "새 인증서 믿기"를 눌러야 다시 고정한다 |
| `device_info` / `capabilities` / `capabilities_at` | JSON / JSON / datetime | §3.2 |
| `live_profile` | text | `main` · `sub` · `mjpeg` (기본 `sub`) |
| `events_enabled` | bool | 구독 켬/끔 |
| `event_kinds` | JSON list | 구독할 종류. 비면 `all` |
| `event_state` / `event_state_at` / `event_note` | text / datetime / text | `off` · `connecting` · `subscribed` · `backoff` · `stopped_auth` · `stopped_limit`. 화면 표시용 |

`Camera` 쪽은 `camera_type='ip'`, `library='vigi'`, `url_stream` 은 비워 둔다(어댑터가 `host`·`live_profile` 로 만든다). `auth_username/password` 도 비워 둔다. 평문을 새로 만들지 않기 위해서다.

### 5.3 `camera_event` (기록)

`id` · `camera_id`(인덱스) · `kind` · `enhanced` · `raw_type` · `camera_time_utc`(카메라가 보낸 epoch) · `received_at_utc`(서버 시각, **판정은 이 값으로**) · `dispatch_state`(`none`·`dispatched`·`dispatch_error`·`suppressed_cooldown`·`suppressed_rate`) · `dispatch_note`. 시간은 전부 `timekit`(`utc_now()`, `parse_utc`)으로 다룬다. 카메라 시계가 서버와 120 초 넘게 어긋나면 `event_note` 에 남기고 화면에 "카메라 시계가 맞지 않습니다"를 띄운다. 보존 기간은 카메라당 30일 또는 1만 행(먼저 닿는 쪽)이고, 데몬이 하루 한 번 정리한다(Q10 확정). 이벤트를 InfluxDB 측정값으로도 쓰는 일(그래프·Conditional 용)은 이번에 하지 않고 CV 단계에서 다시 본다.

### 5.4 트리거 연결 — `Trigger` 에 새 컬럼 (Q9 확정)

`trigger_type='trigger_camera_event'`:
- `unique_id_1` = 카메라 `unique_id`
- **`event_kinds`(새 컬럼, JSON list)** = 받을 이벤트 종류(중립 어휘, §3.2). 빈 목록은 저장할 때 거절한다. `measurement` 같은 다른 뜻의 칸은 재사용하지 않는다.
- `period` = 같은 트리거의 **최소 재발화 간격(초)**, 기본 60. 이 종류에서 `period` 는 타이머 주기로 쓰이지 않는다. 카메라가 같은 움직임을 몇 초마다 다시 보내도 출력이 반복해서 켜지지 않게 한다.

### 5.5 마이그레이션 최종본 (리비전 1건)

`alembic_db` 에 새 리비전 하나를 둔다. 이름은 기존 관례를 따른다(예: `p7_05_camera_driver_<날짜>`). `check_alembic_head.py` 로 체인을 확인한다.

| 변경 | 내용 |
|---|---|
| 새 테이블 `camera_driver` | §5.2 의 컬럼 전부. PK·FK `camera_id → camera.unique_id` ON DELETE CASCADE |
| 새 테이블 `camera_event` | §5.3 의 컬럼 전부. 인덱스 `(camera_id, received_at_utc)` |
| `camera.tab_id` 추가 | `String(36)`, FK `tab.unique_id` **ON DELETE CASCADE**, nullable, index. `Input`·`Output` 의 `tab_id` 와 같은 정의다(탭을 지우면 그 탭의 카메라와 `camera_driver` 행도 지워진다 — 탭 삭제 확인 화면이 카메라도 세어 보여야 한다). SET NULL 로 두면 스코프 밖 사람이 탭을 지워 카메라를 "미지정 = 전원 공개"로 만들 수 있다(스코프 정본의 "탭을 빼면 안 된다"). 기존 행은 NULL 로 둔다(백필 없음 = 전원 공개 유지) |
| `trigger.event_kinds` 추가 | JSON, nullable. `trigger_camera_event` 에서만 쓴다 |

내리기(downgrade)는 위 넷을 거꾸로 지운다. SQLite 에서 컬럼을 지우려면 batch 모드가 필요하다.

`camera.tab_id` 를 더하면서 함께 바꾸는 것(같은 단계 P2):
- `scope._DEVICE_MODEL_NAMES` 에 `Camera` 를 넣는다. 그러면 `tab_of_device`·`can_operate_device` 가 카메라를 찾는다.
- `test_scope_groups.py::EnforcementBoundaryTest` 의 명부에 카메라 조작 뷰를 근거와 함께 더한다. `check_scope_grants.py` 의 `unscoped-device` 건수에 카메라가 잡히는지 확인한다.
- 카메라 수정·삭제(`utils_camera.camera_mod`·`camera_delete`)는 A1b 규칙대로 **부수 효과보다 먼저** 그 카메라의 탭으로 묻는다. 생성은 넣을 탭으로 묻는다.
- 설정 모달에 "탭" 선택 줄을 더한다(비워 두면 전원 공개, 부연으로 알림). 카메라 목록 화면은 지금처럼 모두 보인다(보기는 B 범위).

## 6. 인증·잠금 보호 (계약)

조사 §5 를 그대로 계약으로 삼는다. 아래 규칙은 테스트로 고정한다(§10). **"카메라에 틀린 자격 증명이 두 번 가는 경로가 하나도 없다"** 가 완료 조건이다.

### 6.1 규칙

1. **실패 1회면 즉시 중단(래치).** Open API `-10020`, RTSP 401·403 중 어느 하나라도 오면 `auth_state='failed'` 로 바꾸고 그 카메라의 모든 경로(제어·구독·RTSP·스냅샷·촬영)를 멈춘다. `-10022` 는 `locked` 로 바꾸고 화면에 "카메라가 로그인을 잠갔습니다. 카메라를 다시 켜거나 잠금이 풀릴 때까지 기다리세요"를 띄운다(해제 시간 **[미확인]**).
2. **자동 재시도 없음.** 래치는 사용자만 푼다. 푸는 방법은 두 가지다: 비밀번호를 새로 저장하거나(지문이 바뀜) "다시 연결" 버튼을 누르는 것이다. 어느 쪽이든 **시도는 1회**다. 백오프 후 다시 시도하는 일은 인증 실패에는 없다. 네트워크 오류에만 있다.
3. **재인증은 성공한 자격 증명으로만.** stok 만료나 구독 재연결로 다시 인증할 때는 `credential_fp == verified_fp` 일 때만 한다. 다르면(사용자가 비밀번호를 바꿨는데 아직 확인하지 않음) 재인증하지 않고 `unverified` 로 둔다.
4. **검증 안 된 자격 증명은 프로세스를 통틀어 한 번만.** `verified_fp` 가 없거나 다르면 시도하기 전에 DB 에서 compare-and-set 으로 `attempt_lease_until` 을 잡는다(`UPDATE … WHERE attempt_lease_until IS NULL OR < now`). 잡은 프로세스만 시도한다. 성공하면 `verified_fp` 를 기록한다. 실패하면 래치한다. 두 워커가 동시에 라이브를 열어도 틀린 비밀번호는 한 번만 간다.
5. **검증 순서.** 연결 확인은 데몬이 Open API `doAuth` 로 먼저 한다. 성공해야 RTSP 를 연다. Open API 가 꺼져 있으면(`openapi_off`) RTSP 가 그 1회 시도를 맡는다. 두 인터페이스의 잠금이 공유되는지 **[미확인]** 이므로 어느 쪽 실패든 양쪽을 다 멈춘다.
6. **비밀번호를 남기지 않는다.** 로그·예외 메시지·RPC 응답·`camera_event`·화면에 평문 비밀번호, digest `response`, `stok` 을 남기지 않는다. URL 은 `redact_url` 로, stok 은 앞 4자만 남긴다. 로그 수집 테스트가 비밀번호 문자열이 없는지 검사한다.
7. **식별 탐침은 자격 증명 없이.** 검색의 `doAuth(params:null)` 은 nonce 만 받고 2단계로 가지 않는다. 이것이 잠금 카운터에 들어가는지 **[미확인]** 이므로 카메라당 검색 1회에 1번만 보낸다.
8. **오류 분류.** `-10021`(클라이언트 수 초과)은 인증 실패가 **아니다.** 래치하지 않고 백오프한다(§6.2). 오류코드를 모르는 인증 계열 응답은 안전하게 `failed` 로 취급한다.
9. **2단계 전송 뒤 응답이 없으면 래치한다.** 자격 증명(2단계)이 이미 나갔는데 응답을 받지 못하면(시간 초과·연결 끊김) 결과를 모르므로 `failed` 로 래치하고 같은 자격 증명을 다시 보내지 않는다(2026-11-04 P1 구현, 관리 세션 승인). 연결 단계에서 실패해 본문이 나가지 않았다면 래치하지 않는다.

### 6.2 이벤트 구독 수명

```
off ──(events_enabled & auth ok)──▶ connecting ──doAuth(verified_fp 로)──▶ subscribed
subscribed ──스트림 종료/하트비트 끊김(70초)──▶ backoff ──▶ connecting
connecting ──-10020/-10022──▶ stopped_auth (래치, 사용자 대기)
connecting ──-10021──▶ stopped_limit → 백오프 60→120→…→900초(지터 ±20%), 래치 아님
connecting ──네트워크 오류──▶ backoff 5→10→…→300초(지터)
```

- **stok 30분**: 구독 연결이 stok 만료 뒤에도 살아 있는지 **[미확인]** 이다. 그래서 미리 끊고 다시 붙지 않는다(빈틈이 생기고 클라이언트 슬롯을 하나 더 쓸 수 있다). 연결이 끝나면 다시 붙는다. 제어 호출용 stok 은 25분 지나면 다음 호출 전에 새로 받는다. 세션 무효 오류가 오면 성공한 자격 증명으로 **1회만** 다시 인증한다. 그것도 실패하면 래치한다.
- **하트비트**: 문서상 `{"Heartbeat":"30"}` 이다. 2주기 + 10초(70초) 동안 아무것도 오지 않으면 끊고 백오프한다.
- **슬롯 아끼기**: 카메라당 구독 연결은 1개다. 제어 호출은 요청마다 연결을 새로 연다(문서 원칙). 동시 제어 호출은 카메라당 1개로 줄을 세운다.
- 데몬이 다시 시작되면 `events_enabled` 인 카메라만 다시 붙는다. 다만 `auth_state` 가 `ok` 이고 `verified_fp` 가 일치할 때만이다.
- 구독이 끊겨 있던 구간은 `event_note` 에 "N분 동안 이벤트를 받지 못했다"로 남긴다(이벤트 유실을 숨기지 않는다).

### 6.3 이벤트 → Function 트리거 (물리 제어 경계)

- 디스패처는 이벤트 하나에 대해 `Trigger(trigger_type='trigger_camera_event', unique_id_1=카메라, is_activated)` 중 종류가 맞는 것을 고른다. `period` 쿨다운 안이면 `suppressed_cooldown` 으로 기록만 한다. 아니면 `control.trigger_all_actions(trigger.unique_id, message=…)` 를 부른다. `rpi_edge.py`·`matter_node.py::_fire_edge` 와 같은 길이다.
- **실패 판정**: `trigger_all_actions` 는 예외를 삼키고 문자열을 돌려준다(`aot_daemon.py:1355`). 예외가 났거나 `Could not trigger` 로 시작하면 `dispatch_error` 로 둔다. 그 밖에는 `dispatched` 로만 기록하고, **"출력이 켜졌다"로 기록하지 않는다.** 동작이 실제로 실행됐는지는 각 Action 이 자기 기록으로 판정한다(기존 경로). 이 기록을 화면에 보여 줄 때도 "트리거 실행 요청됨"이라고 쓴다.
- **폭주 방지**: 트리거별 쿨다운에 더해 카메라당 1분에 디스패치 30건 상한을 둔다. 넘치면 `suppressed_rate` 로 기록하고 알린다. 카메라 쪽 `setMsgpushInterval` 은 사용자가 바꿀 수 있게 보여만 준다.
- **그룹 스코프**:
  - 트리거 생성·수정은 기존 규칙(생성 = 넣을 탭, 수정 = 자기 탭)을 그대로 지난다. 이벤트를 **읽는** 쪽(카메라)은 보기 축이다. 보기는 지금 전원 공개다(A 범위 밖).
  - 데몬 안에서 발화하는 트리거는 "사람이 없는 호출 = 면제" 축이다(기존 edge 트리거와 같다). 새 우회로를 만들지 않는다.
  - **카메라를 움직이는 조작(PTZ·프리셋 이동·수동 경보·주야 모드·알림 스위치 쓰기)** 은 `edit_controllers` 역할 검사에 더해 **각 뷰의 맨 앞에서** `can_operate_device(camera_uid)` 를 묻는다(거부가 부수 효과보다 먼저). 판정 근거는 새 `Camera.tab_id` 다(§5.5). 탭이 없는 카메라는 default-open(전원 공개)이고, 이는 다른 장치와 같은 원칙이다.
  - 데몬 RPC 쪽에서도 다시 묻지 않는다. 사람의 신원은 Flask 요청에만 있으므로 경계는 Flask 뷰다. 대신 그 뷰들을 `GATED_CONTROL_VIEWS` 에 올리고, 데몬 RPC 이름을 `DAEMON_CONTROL_CALLS` 에 올려 빠진 게이트를 검사가 잡게 한다.

## 7. 스냅샷 (Q1 확정: 제안 A)

Open API 에는 정지 이미지가 없다 **[문서]**. ONVIF `GetSnapshotUri` 는 C540V 가 지원하지 않는다 **[실측]**. HTTP 정지 이미지 주소가 있는지는 **[미확인]** 이다(자격 증명을 들고 추측 주소를 두드리는 시험은 하지 않는다).

**채택안 A**:
1. 그 카메라의 라이브 `FrameHub` 가 돌고 있으면 **마지막 프레임**을 쓴다. 새 연결도 새 인증도 없다. 워커가 여럿이라 다른 워커의 허브는 메모리로 볼 수 없다. 그래서 허브의 `LatestFrameFile` 구독자가 1초에 한 번 이하로 `<임시 폴더>/aot-cam/<uid>.jpg` 에 원자적으로 쓴다(임시 파일 → rename). 스냅샷은 그 파일이 3초 안에 쓰인 것이면 쓴다.
2. 돌고 있지 않으면 **`/stream6`(MJPEG) 을 한 번 열어** 첫 JPEG 를 받고 바로 닫는다. JPEG 페이로드라 키프레임을 기다리지 않는다(H.264 서브스트림 첫 프레임 4.3초 실측과 비교). 예상치는 연결 시간(1.5초 내외)에 한 장인데 **[미확인]** 이므로 §10 에서 잰다.
3. 둘 다 래치가 걸려 있으면 시도하지 않는다.

| 대안 | 장점 | 단점 |
|---|---|---|
| A. 제안(최신 프레임 → `/stream6` 1회) | 키프레임 대기 없음, 인증 0~1회 | 640×360 고정(서브 MJPEG 해상도). 고화질 스냅샷은 아님 |
| B. `/stream1` 에서 키프레임까지 받아 한 장 | 2560×1440 고화질 | 첫 프레임 6초 내외, CPU 부담, 파이급에서 타임랩스 주기와 충돌 |
| C. 기존 `ip_snapshot`(HTTP 정지 이미지) | 가장 가벼움 | VIGI 에 주소가 있는지 모름. elastic-pike 의 `fetch_snapshot` 은 Basic→Digest 로 2회 시도할 수 있어 계약 위반 |
| D. 카메라 웹 UI 비공개 경로 | — | 문서에 없음, 펌웨어마다 바뀔 수 있음. 채택하지 않는다 |

**구현 메모(P2)**: `/stream6` 은 OpenCV(FFmpeg)가 디코딩한 프레임을 JPEG 로 다시 인코딩해서 쓴다(JPEG 페이로드를 그대로 꺼내지 않는다). 640×360 이라 비용은 작다.
**구현 메모(P2, 탭 삭제)**: `Camera.tab_id` 는 DB 연쇄 삭제만으로 두지 않는다. 로컬 SQLite 는 FK 강제가 꺼져 있어 연쇄가 돌지 않으므로, `TabService.delete_tab` 이 페이지 종류와 무관하게 그 탭의 카메라를 앱 경로로 지운다(스트림 정지 → `camera_event`·`camera_driver` 행 → 카메라).

타임랩스·촬영(`devices/camera.py::camera_record`, 데몬)은 `library=='vigi'` 분기에서 A 의 2번(`/stream6` 1회)을 쓴다. 고화질 촬영 옵션(B)은 **이번 범위 밖**이다. 나중 단계에서 `FrameSource` 를 하나 더 두는 것으로 붙인다.

## 8. 네트워크 검색 (Q2 확정: 1차안만)

**1차: 버튼 → 포트 탐침 + 무인증 `doAuth`**
- 사용자가 "카메라 찾기"를 눌렀을 때만 돈다. 주기 검색은 없다. 권한은 `edit_controllers` 다. 동시에 한 건만, 같은 서브넷 재검색은 60초 뒤부터 할 수 있다.
- 대상: RFC1918(10/8, 172.16/12, 192.168/16) 범위만. 서버 인터페이스의 서브넷이 /24 보다 넓으면 **서버 IP 를 포함한 /24 하나**로 줄인다. 공인 IP·루프백·링크 로컬은 거절한다.
- 동시 연결 16개, 연결 시간 제한 0.5초, 호스트당 TCP 20443·554 두 포트, 전체 상한 30초.
- 20443 이 열리면 `{"method":"doAuth","params":null}` 를 **1회** 보낸다. `errCode -10020` 과 `authenticate.realm`·`nonce` 가 오면 "VIGI(OpenAPI 켜짐)"로 표시한다. 인증서는 이 단계에서 검증하지 않는다. 비밀을 보내지 않고 식별만 하기 때문이다.
- 554 만 열리면 "RTSP 장치 — VIGI 인지 모름(OpenAPI 가 꺼져 있을 수 있음)"으로 표시하고 OpenAPI 안내로 잇는다.
- 결과 목록: IP · 식별 결과 · 이미 등록됨 여부(`camera_driver.host`). 모델·MAC 은 인증 전에는 모른다(ODP 를 쓰지 않으므로). 연결 확인에 성공하면 `getDeviceInfo` 로 채운다.
- **Docker 주의(조사에서 새로 짚은 점)**: 브리지 네트워크 컨테이너의 "직접 붙은 서브넷"은 `172.x` 도커 망이지 현장 LAN 이 아니다. TCP 탐침 자체는 NAT 를 넘어 LAN 에 닿지만, 서브넷을 자동으로 고르면 엉뚱한 망을 뒤진다. 그래서 Docker 설치에서는 **사용자가 검색 화면에서 서브넷을 입력한다**(Q2 확정). 입력값도 RFC1918·/24 규칙을 똑같이 지나야 하고, 넓은 대역은 /24 로 줄이지 않고 거절한다(사용자가 고른 범위를 몰래 바꾸지 않는다). 마지막 입력값은 기억해 다음에 미리 채운다. 네이티브 설치는 자동으로 고르고, 사용자가 바꿀 수 있다. Docker 판별은 기존 `aot.utils.system_environment.detect()` 를 쓴다.

**2차: WS-Discovery — 미룸**(Q2). 나중에 넣을 때는 네이티브 설치(또는 `network_mode: host`)에서만 켠다. 브리지에서는 멀티캐스트가 넘어가지 않기 때문이다. `wsdiscovery` 는 requirements 에 없다.

**ODP**: 전송 방식(L2 프레임 0x7210 인지 UDP 23001 인지)이 확정될 때까지 미룬다.

**IP 직접 입력**은 늘 있다. 검색은 입력을 돕는 것일 뿐이다.

## 9. 화면

정본 `docs/design/ui-guide.md` 를 따른다: `.aot-option-modal` 골격, `.aot-modal-option-row`(왼쪽 라벨·오른쪽 컨트롤), 부연은 `.aot-option-tip`, 버튼은 알약, 입력은 밑줄, 테두리·새 색·인라인 style·아이콘·이모지를 쓰지 않는다. 문구는 전부 번역 함수로 감싸고 ko·ja 를 채운다. UUID 는 화면에 내지 않는다. 그리기 전에 기존 `camera_options.html` 의 골격을 찾아 재사용한다.

### 9.1 카메라 추가 → 종류 "TP-Link VIGI"
- 추가 화면의 종류 목록에 VIGI 를 넣는다(`CAMERA_TYPES` 항목 + `CAMERA_TYPE_TO_LIBRARY`). 고른 뒤 두 길이 있다: "카메라 찾기"(§8) 또는 "주소 직접 입력".

### 9.2 설정 모달 (VIGI 카메라)
구획 순서(한 줄에 결정 하나):
0. **탭** — 이 카메라가 속한 탭(§5.5). 부연: "탭을 비워 두면 조작 권한이 있는 모든 사람이 이 카메라를 움직일 수 있습니다."
1. **연결** — 주소 · 계정(기본 `admin`, 바꿀 수 있음) · 비밀번호(저장된 값은 보여 주지 않고 "저장됨"만) · `[연결 확인]`. 상태 한 줄: 확인 안 됨 / 연결됨(모델·펌웨어) / **인증 실패 — 자동으로 다시 시도하지 않습니다** / **카메라가 로그인을 잠갔습니다** / OpenAPI 꺼짐 / **카메라 인증서가 바뀌었습니다**.
   - 인증서가 바뀐 상태: 이전·새 지문의 앞 16자를 보이고 `[새 인증서 믿기]` 를 둔다. 부연: "카메라를 초기화했거나 펌웨어를 바꿨다면 정상입니다. 그런 적이 없으면 누르지 마세요." 누르기 전에는 자격 증명을 보내지 않는다.
   - 인증 실패 상태의 부연: "비밀번호를 확인한 뒤 다시 저장하거나 [다시 연결] 을 누르세요. 한 번만 시도합니다."
2. **OpenAPI 안내** (승인된 안내 문구, `.aot-option-tip`) — "PTZ·이벤트 같은 기능을 쓰려면 카메라 웹 화면의 설정 → 네트워크 설정에서 OpenAPI 를 켜고 적용하세요. 켜지 않아도 영상은 볼 수 있습니다." `openapi_off` 상태일 때만 강조해서 보인다(의미색 승인 범위 안).
3. **영상** — 라이브 화질(주 2560×1440 / 부 / MJPEG). 부연: "주 화질은 서버 부담이 큽니다."
4. **기능** — `Capabilities` 로 그린다. PTZ 있음/없음, 프리셋 수, 줌, 주야 모드, 경보, SD 카드 상태(읽기). 없는 기능은 그리지 않는다. `[기능 다시 읽기]`.
5. **이벤트** — 구독 켬/끔, 받을 종류(지원하는 종류만 체크 목록), 구독 상태(연결됨·다시 연결 중·중단됨+이유), 최근 이벤트 5건(종류·서버 시각). 카메라 쪽 "알림 보내기(msg_push)"가 꺼진 종류는 부연에 "카메라에서 이 감지의 알림이 꺼져 있어 받지 못합니다"를 띄우고 **`[알림 켜기]`** 를 둔다(Q4 확정).
   - 이 버튼이 바꾸는 것은 그 감지의 `msg_push_enabled` **하나뿐**이다. `get…Switch` 로 현재 값을 읽고, `msg_push_enabled` 만 바꿔 `set…Switch` 로 돌려보낸다. 감지 켜기(`enabled`)·민감도·경보·녹화·영역은 건드리지 않는다. 감지 자체가 꺼져 있으면 버튼 대신 "카메라 웹 화면에서 이 감지를 먼저 켜세요"를 띄운다.
   - 카메라 설정을 바꾸는 쓰기이므로 §6.3 의 조작 게이트(역할 + 스코프)를 지나고, 결과는 `CamResult` 로 판정한다. 쓴 뒤 다시 읽어 값이 바뀐 것을 확인해야 "켜졌습니다"라고 쓴다.
   - 감지 영역·민감도 편집은 범위 밖이다.
6. **트리거로 쓰기** — "이 카메라의 이벤트로 동작 만들기" 링크. Function 화면의 새 트리거 종류로 이동하고 카메라를 미리 채운다.

### 9.3 PTZ 컨트롤러 (설정 측 전체판 · 위젯 측 간결판, 능력이 있을 때만)
화면 부품은 전역 PTZ 컨트롤러 하나다(`ui-guide.md` §4-8 「PTZ 컨트롤러」: `components/aot-ptz.css` + `common/aot-ptz.js` + `macros/aot_ptz.html`). 첫 시안(텍스트 알약 나열)은 사용자가 반려했고(2026-11-04), 일반 PTZ 컨트롤러를 단순하게 줄인 모양으로 바꿨다.
- **방향**: 원형 패드를 X 로 나눈 상하좌우 4조각, 가운데는 비운 원(누르는 곳이 아님). 대각선은 없다. 조각 안의 삼각형이 움직이는 쪽을 가리킨다. **줌**: 패드 옆 `+`(위)·`−`(아래). 모양 표시는 이 컨트롤러에 한해 사용자가 허락했다(이모지·아이콘 글꼴·이미지 없이 CSS 도형).
- **누르고 있는 동안만 움직인다**: 누름 → `cruiseMove`, 뗌 → `stopMove`. 마우스·터치·키보드(포커스 뒤 화살표·`+`/`−`) 모두 같다. 포인터가 조각 밖으로 나가거나, 취소되거나, 창이 가려지거나, 모달이 닫혀도 정지를 보낸다. 누르는 동안 그 조각이 활성 버튼 면으로 바뀐다. 브라우저는 0.5초마다 유지 신호를 보내고, **데드맨**: 떼기 신호가 사라져도(탭 닫힘·네트워크) 서버가 마지막 이동 명령 2초 뒤 `stopMove` 를 보낸다. 명령은 카메라마다 한 줄로 이어 보낸다(정지가 이동을 앞지르지 않게).
- **프리셋 1~8**: 번호 칩 한 줄, 누르면 이동. 저장·삭제는 설정 측에서만, `[편집]` 한 단계 뒤에 둔다 — 편집 중에는 칩이 '고르기'가 되고, 고른 번호에 `[삭제]`·`[현재 위치 저장]`(각각 확인 대화). 카메라 앱의 프리셋(최대 300)과 개수가 다를 수 있다(문서상 API 는 1~8).
- **주야**: 자동·주간·야간 세 칸 전환. 누르면 바로 적용(`적용` 버튼 없음), 받아들여지지 않으면 앞 칸으로 되돌린다. 처음 그릴 때 현재 모드를 한 번 읽는다.
- **수동 경보**: 줄 이름 '수동 경보' 옆 `[끄기]` `[울리기]`. 울리기는 확인 대화를 거친다(소리·빛이 실제로 난다).
- **결과 문구**: `accepted` → "카메라가 명령을 받았습니다", `failed` → 이유, `refused` → 권한·스코프 이유. "이동했습니다"라고 쓰지 않는다. 위젯은 문구 줄이 없어 받아들여지지 않았을 때만 알림(토스트)으로 알린다.
- **설정 측**: 카메라 설정 모달의 **미리보기 바로 아래**(누르는 동안 영상이 함께 보이도록). 조작 권한(역할 `edit_controllers` + 그 카메라의 탭 스코프)이 없으면 페이지가 그리지 않는다.
- **위젯 측**(2026-11-04 사용자 결정 — 이전의 "대시보드 위젯 안 PTZ 는 범위 밖"을 대신한다): 모던 카메라 위젯(`AoT_camera`) 영상 위에 반투명으로 겹친다 — 오른쪽 위 프리셋 칩, 왼쪽 아래 작은 패드·줌(왼쪽 위는 LIVE 등 상태 글자 자리). 마우스를 올리면(데스크톱)·영상을 한 번 탭하면(터치) 나타나고 3.5초 쓰지 않으면 숨는다. 위젯 옵션 '카메라 조작부 표시'(기본 켬). 경보·프리셋 편집은 없다. VIGI 이고 연결이 확인됐고 PTZ 능력이 있고 조작 권한이 있을 때만 서버가 그린다. 화면에서 숨기는 것은 정리일 뿐이고 제어 경로가 같은 두 문을 다시 묻는다.

### 9.4 Function — 트리거 "카메라 이벤트"
기존 트리거 모달 골격에 줄 셋: 카메라(VIGI 이고 이벤트를 켠 것만, 꺼져 있으면 경고) · 이벤트 종류(다중, `event_kinds`) · 최소 재발화 간격(초). 부연: "카메라가 보낸 이벤트를 서버가 받은 시각에 실행합니다. 구독이 끊긴 동안의 이벤트는 실행되지 않습니다."

## 10. 테스트 계획

### 10.1 모의 Open API 서버 (`aot/tests/fixtures/vigi_mock/`, 8084·CI 공용)
자체 서명 HTTPS 와 문서 예시를 근거로 다음을 흉내 낸다:
- `doAuth` 2단계(SHA-256 챌린지, 올바른 response 검증, 틀리면 `-10020`). **틀린 시도 횟수 카운터**와 N회 뒤 `-10022` 잠금. 모든 시도를 기록해서 테스트가 "카메라에 간 인증 시도 수"를 셀 수 있게 한다.
- stok TTL(테스트에서는 몇 초로 줄임)과 만료 응답.
- 클라이언트 수 상한 → `-10021`.
- `getModuleList` 변형 셋: PT 카메라(C540V 가정) / 고정형 / 줌 있음. `getPTZCapability` 등.
- `subscribeMsg`: multipart/mixed 로 이벤트·하트비트. 중간에 끊기, 하트비트 멈추기, 모르는 `event_type`, 강화 이벤트.
- 제어 메서드의 `error_code` 0/음수, 빈 본문, 형식 오류.

모의 서버로 검증하는 것(단위·통합, DB 는 테스트 DB):
| 계약 | 검사 |
|---|---|
| 실패 1회 래치 | 틀린 비밀번호로 연결 확인·구독·제어·라이브·스냅샷을 모두 불러도 모의 서버의 실패 카운트가 **1** |
| 프로세스 간 1회 | 두 프로세스(또는 두 DB 세션)가 동시에 검증 안 된 자격 증명으로 시도 → 시도 1, 다른 쪽은 `refused` |
| 재인증 제한 | stok 만료 → `verified_fp` 로 1회 재인증. 지문이 바뀌었으면 재인증 0회 |
| -10021 은 래치 아님 | 백오프 간격 수열 확인, `auth_state` 그대로 |
| -10022 | `locked`, 이후 시도 0 |
| 비밀 비노출 | 전 경로 caplog·예외·RPC 응답에 비밀번호·digest response·전체 stok 이 없음 |
| `CamResult` 판정 | HTTP 200 + `error_code≠0`, 빈 본문 → `accepted` 아님 |
| 능력 협상 | 변형별로 화면에 그릴 기능 집합 |
| 구독 수명 | 하트비트 70초 감시(시계 주입), 끊김 → 백오프 → 재구독, 끊긴 구간 기록 |
| 이벤트 → 트리거 | 종류 거르기, 쿨다운, 분당 상한, `trigger_all_actions` 실패 문자열 → `dispatch_error` |
| 스코프 | `check_scope_gates.py` 가 새 제어 RPC 를 잡는지, 거부가 부수 효과보다 먼저인지(`test_refusal_happens_before_side_effects` 형식) |
| 검색 | RFC1918 외 거절, /24 축소, 탐침에 자격 증명 없음, 동시성·상한, 브리지 감지 시 자동 서브넷 비활성 |
| 시간 | `timekit` 만 사용, 다른 시간대·DST 에서 `received_at` 기록·쿨다운 계산 |
| 경계 | `aot.camera_drivers` 가 `aot.camera.*` 를 import 하지 않음 |

RTSP 쪽: `FrameSource` 는 가짜 소스로 단위 시험한다. 실제 RTSP 401 동작은 **8084 에서** 인증을 켠 RTSP 서버(mediamtx 등)로 확인한다(Q11 허용, 로컬만). 확인할 것: 틀린 비밀번호 → 401 1회 → 래치 → RTSP 서버 로그의 인증 시도 1회, 두 워커가 동시에 열 때도 1회, `/stream6` MJPEG 한 장 추출.

### 10.1.1 8084 기본 시험 (8084 를 해치지 않는 방법)

기본 시험 환경은 로컬 8084 다(2026-11-04 사용자 결정). 모의 서버는 8084 스택에 섞지 않는다.
- **모의 Open API 서버와 RTSP 시험 서버는 별도 컨테이너로 띄운다.** 8084 의 compose 파일·볼륨·이미지는 바꾸지 않는다. 시험 스크립트가 컨테이너를 띄우고(`docker run --rm`, 이름 `aot-test-vigi-mock`·`aot-test-rtsp`), 끝나면 내린다. 호스트 포트는 겹치지 않는 값(예: Open API 20443 → 호스트 30443, RTSP 554 → 18554)을 쓰고, 8084 앱은 `host.docker.internal:<포트>` 로 붙는다.
- RTSP 시험 서버에는 시험용 영상 하나(합성 패턴)만 싣는다. 경로는 `/stream1`·`/stream2`·`/stream6` 셋이고, 계정은 시험값을 쓴다(저장소의 시험 픽스처에 둔다).
- **8084 의 DB 는 로컬 시뮬레이터 데이터다.** 화면 시험용 카메라·트리거는 이름에 `시험-` 을 붙여 만들고, 시험이 끝나면 화면에서 지운다. 자동화된 단위·통합 시험은 8084 DB 가 아니라 시험 DB 를 쓴다.
- 마이그레이션은 8084 에 자동 적용되므로(로컬 개발 환경 함정), 마이그레이션이 든 단계는 적용 전 8084 DB 를 백업하고 downgrade 를 한 번 확인한다.
- 8084 화면 시험 항목: 추가·연결 확인·실패 표시(래치 문구)·인증서 변경 표시·기능 표시·PTZ 버튼(모의 서버가 받은 명령 순서)·알림 켜기·이벤트 → `trigger_camera_event` → 시뮬레이터 출력(기록에 남는지)·검색(모의 서버 발견, Docker 서브넷 입력). 로컬은 시뮬레이터라 물리 동작은 확인하지 않는다.
- NAS Gitea CI 의 E2E 는 지금처럼 별도 경로로 돈다. 8084 시험이 그것을 대신하지 않는다.

### 10.2 실카메라가 필요한 것 — **보류**

V1~V7 은 **전부 보류**다. 배포 서버를 거쳐 실카메라에 닿지 않는다(2026-11-04 사용자 결정). 실카메라에 닿는 방법(예: 로컬망에 같은 기종 카메라를 둔다)이 정해질 때까지 미룬다(§12 Q14). 방법이 정해지면 V1~V3 부터, P1 의 모의 서버 시험을 통과한 뒤, 사용자가 있을 때 각 1회 한다. 구현 세션은 실카메라에 직접 접속하지 않는다.

보류 동안 모듈은 [문서] 근거와 모의 서버만으로 만든다. 그래서 V 항목으로 확정할 값(이벤트 종류 철자, 세션 무효 오류코드 등)은 `capability_map.py`·`errors.py` 한 곳에 모아 두고, 모르는 값이 오면 안전한 쪽(기록만, 인증 계열이면 래치)으로 처리한다.
| # | 항목 | 방법 | 위험 |
|---|---|---|---|
| V1 | OpenAPI 켜짐·20443 응답 | 무인증 `doAuth` 1회 | 낮음(잠금 카운터 영향 **[미확인]**) |
| V2 | `getModuleList`·PTZ 능력 | 올바른 비밀번호로 1회 | 올바른 자격 1회 |
| V3 | 인증서 형태(자체 서명·TLS 버전) | `openssl s_client`, 인증 없음 | 없음 |
| V4 | `subscribeMsg` 실제 포맷·`event_type` 철자 12종·하트비트 | 구독 1개, 사용자가 카메라 앞에서 동작 | 클라이언트 슬롯 1개 |
| V5 | stok 만료 뒤 구독 유지 여부, 세션 무효 오류코드 | 구독을 35분 유지 | 없음 |
| V6 | `/stream6` 1장 받는 시간 | 실카메라에 닿는 로컬 환경에서 1회 측정 | 올바른 자격 1회 |
| V7 | PTZ 이동·정지·프리셋, 수동 경보 | 사용자가 카메라를 보며 | 실제로 움직이고 울림 |
| V8 | 잠금 임계·해제 시간 | **시험하지 않는다.** TP-Link 문의 | — |

## 11. 단계별 구현 순서와 완료 기준

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **P0 선행** | `art/elastic-pike-144f1d` main 병합(관리 세션 처리, P2 전까지) | 병합 커밋이 main 에 있음 |
| **P1 틀·클라이언트** | `camera_drivers` 골격, `driver.py`·`capabilities.py`·`auth_guard.py`, `vigi/openapi.py`·`errors.py`·`capability_map.py`, 모의 서버 | §10.1 의 래치·재인증·비노출·`CamResult`·능력 테스트 통과(DB 없이 + 테스트 DB). 네트워크는 모의 서버만. (V1~V3 은 보류, §10.2) |
| **P2 모델·등록·라이브** | 마이그레이션(§5.5 전부), `Camera` 스코프 명부 등록·카메라 CRUD 게이트, `CameraDriverService`(데몬, verify·refresh RPC), 설정 모달 0~4 구획(TOFU 포함), `camera_vigi.py`·`FrameHub`·`LatestFrameFile`, 스냅샷(§7), `camera_record` 분기 | 8084 에서 추가→연결 확인(모의)→상태 표시. 프로세스 간 1회 시험 통과. 기존 카메라 종류 회귀 테스트 통과. 8084 에서 별도 컨테이너의 인증 RTSP 서버로 401 래치 확인. `check_alembic_head.py`·`test_scope_groups.py`·번역 검사 통과 |
| **P3 제어** | PTZ·프리셋·데드맨·주야·수동 경보, 제어 RPC, 스코프 게이트, `DAEMON_CONTROL_CALLS`·`GATED_CONTROL_VIEWS` 등록 | 모의 서버가 받은 명령 순서 검증(누름/뗌/데드맨). `check_scope_gates.py`·`test_scope_groups.py` 통과 |
| **P4 이벤트** | `subscribe.py`, 이벤트 버스, `camera_event`, `trigger_camera_event`(`event_kinds` 컬럼·설정 화면·utils_trigger·FUNCTION_INFO), 알림 켜기 버튼, 모달 5~6 구획 | 구독 수명·디스패치 테스트 통과. 8084 에서 모의 이벤트 → 트리거 → 시뮬레이터 출력 동작이 기록에 남음 |
| **P5 검색** | `discovery.py`·`vigi/probe.py`, 검색 화면(Docker 는 서브넷 입력), IP 바뀜 제안 | 검색 테스트 통과, 8084 에서 모의 서버 발견 |
| **P6 실카메라·배포** | V1~V7(실카메라에 닿는 방법이 정해진 뒤, 그 전까지 보류). 배포는 **정식 병합·릴리스 경로로만**, 서버 직접 반영 없음 | 정해진 환경에서 V 항목 결과 기록. 릴리스 절차(CLAUDE.md 「릴리스」)를 지남 |

각 단계는 NAS Gitea CI(`gitea_ci.sh`)의 단위 스위트를 통과해야 끝난다. 화면이 바뀌는 단계(P2~P5)는 E2E 도 통과해야 한다.

## 12. 사용자 결정 (2026-11-04, "추천안대로" 승인)

| # | 질문 | 결정 | 반영 |
|---|---|---|---|
| Q1 | 스냅샷 | 제안 A(최신 프레임 → 없으면 `/stream6` 1회). 고화질(B) 타임랩스는 범위 밖, 나중 단계 | §7 |
| Q2 | 검색 | 1차안 그대로(버튼, RFC1918 /24, 20443·554, 무인증 `doAuth` 1회). Docker 는 사용자가 서브넷 입력. WS-Discovery 미룸 | §8 |
| Q3 | 구조 | `aot/camera_drivers/` + 레거시 어댑터 + Open API 데몬 전담 | §3·§4 |
| Q4 | 카메라 설정 쓰기 | 트리거에 필요한 알림 스위치(`msg_push_enabled`)만 켜는 버튼. 감지 영역·민감도 편집은 범위 밖 | §9.2-5 |
| Q5 | 카메라 스코프 | `Camera.tab_id` 추가(마이그레이션 + `_DEVICE_MODEL_NAMES` 에 `Camera` + `EnforcementBoundaryTest` 갱신). 기존 카메라는 탭 없음 = 전원 공개 유지 | §5.5·§6.3 |
| Q6 | 계정 | 기본 `admin`, 바꿀 수 있게 | §5.2·§9.2 |
| Q7 | 인증서 | TOFU 고정, 바뀌면 멈추고 사용자에게 묻기 | §5.2·§9.2 |
| Q8 | IP 바뀜 | 자동 수정 없음, 제안만 | §5.2 |
| Q9 | 트리거 칸 | 새 컬럼 `trigger.event_kinds`(같은 마이그레이션) | §5.4·§5.5 |
| Q10 | 이벤트 기록 | 30일/1만 행. InfluxDB 측정값 기록은 CV 단계에서 재검토 | §5.3 |
| Q11 | RTSP 시험 | 인증 RTSP 서버 시험 허용(로컬만). 2026-11-04 수정: 8084 기준, 별도 컨테이너로 | §10.1·§10.1.1 |
| Q12 | 선행 병합 | `art/elastic-pike-144f1d` 를 P2 전에 main 병합 허용. PR 은 관리 세션이 처리 | §2·§11 |
| Q13 | 실카메라 V1~V3 | P1 모의 서버 시험 통과 뒤, 사용자가 있을 때 1회. 2026-11-04 수정: 배포 서버를 거치지 않으므로 실카메라에 닿는 방법이 정해질 때까지 보류 | §10.2·§11 |
| — | 작업 환경(2026-11-04 추가) | 배포 서버에서 작업하지 않음, 기본 시험은 로컬 8084, 배포는 정식 병합·릴리스로만 | 머리말·§10.1.1·§11 |

### 사용자 확인 항목 (열림)
- **Q14 실카메라에 닿는 방법**: 로컬망에 같은 기종(C540V 또는 PTZ 가 있는 VIGI)을 둘지, 다른 방법을 쓸지. 정해질 때까지 V1~V7 은 보류다.

### 남은 미결 (실카메라 확인으로 닫는다, 사용자 결정 아님 — 지금은 보류)
- `event_type` 철자 11종, 세션 무효 오류코드, stok 만료 뒤 구독 유지 여부(V4·V5).
- 무인증 `doAuth` 와 다른 계정이 잠금 카운터·Open API 에서 어떻게 다뤄지는지([미확인], 시험으로 확인하지 않는다).
- `/stream6` 한 장 받는 시간(V6).
- 기존 `ip_camera` 경로에도 "실패 1회 즉시 중단" 계약을 적용할지는 이 설계 밖이다(관리 세션 판단).
