# Matter 컨트롤러 — 기존 Matter 장치를 Multi-Admin으로 들여오기

**상태**: P3(BLE 새 장치·다른 생태계로 공유·펌웨어 정책) 구현 완료 — 브랜치
`claude/matter-controller-p3`, 결정 §13. 실제 BLE 등록(P3 완료 기준)은 Linux 호스트 실기
확인이 남았다. P2(디머·커튼·센서 확장·버튼/접점 Trigger·다시 읽기) 구현 완료 — 브랜치
`claude/matter-controller-p2`, 결정 §12. 가상 장치 E2E 로 완료 기준(커튼을 통합환경제어
출력으로 사용) 확인. P0(인프라)·P1(공유 등록·센서·스위치·삭제) 구현 완료 — 브랜치
`claude/matter-controller-p0`, `claude/matter-controller-p1`. P1 은 가상 Matter 장치로 전체
스택 E2E 를 통과했다. 실제 장치·Linux 호스트·다른 생태계에서 공유받는 검증은 남았다
(§8 P1 완료 기준). 결정 기록은 §10(P0)·§11(P1).
**관련**: `device-tier.md`(복합장치) · `device-onboarding.md`(발견이 정본) ·
`plc-modbus-integration.md`(런타임 제약 C1~C6) · `sensor-freshness-and-control-cadence.md` ·
`ai-tool-architecture.md`(승인 게이트) ·
`smartthings-integration.md`(보류 — 브랜치 `claude/smartthings-design`)

---

## 요약

> AoT shall act as a vendor/ecosystem-neutral Matter Controller and support adding
> existing Matter devices through Matter Multi-Admin, regardless of the device's
> existing Administrator/Fabric.

Apple Home·Google Home·SmartThings·Alexa 등 어디에 이미 등록된 Matter 장치든,
기존 관리자가 공유(커미셔닝 창 열기)해 주면 AoT가 **자기 Fabric 하나**에 그 장치를
추가하고, 장치를 AoT의 Device / Input / Output으로 바꿔 기존 제어·AI·규칙 체계에
얹는다.

핵심 판단은 다섯이다.

1. **생태계를 모른다.** 컨트롤러 계층에 Apple/Google 같은 이름이 들어가지 않는다.
   AoT가 처리하는 질문은 "어디서 왔나"가 아니라 "커미셔닝 가능한 Matter 노드인가"뿐이다.
   생태계 이름은 UI 도움말("공유 코드 받는 법")에만 나온다.
2. **Fabric은 하나, 장치마다 만들지 않는다.** AoT Fabric의 루트 CA·NOC·운영 키는
   설치당 하나이며, 잃으면 모든 장치를 다시 공유받아야 한다. 그래서 백업 대상이고
   비밀정보로 다룬다.
3. **Matter 스택은 데몬 밖 사이드카에 둔다.** LoRaWAN을 ChirpStack에 맡기듯,
   Matter는 별도 컨테이너(`matterjs-server`)가 맡고 AoT는 웹소켓으로 붙는다.
   CHIP/matter.js 스택을 데몬 프로세스에 넣지 않는다.
4. **1단계는 같은 네트워크 공유(on-network commissioning)만.** 이미 다른 생태계에
   붙은 장치는 IP로 닿으므로 BLE·Wi-Fi 자격증명·Thread 데이터셋이 필요 없다.
   새 장치(BLE) 커미셔닝은 뒤로 미룬다.
5. **네트워크가 가장 큰 위험이다.** 코드보다 호스트 IPv6·mDNS·방화벽 설정에서
   막힌다. 설치 전 점검 단계를 기능의 일부로 만든다.

---

## 1. 현재 상태 (실측)

| 항목 | 상태 |
|---|---|
| Matter 관련 코드 | **없음** (`aot/` 전체 검색, 2026-10-08) |
| 외부 프로토콜 서버 연동 선례 | ChirpStack — `aot/aot_flask/utils/utils_chirpstack.py`(조회·`register_device_as_input/output`), `settings/chirpstack.html` |
| 공유 연결 레지스트리 선례 | Modbus — `aot/devices/modbus_client.py` `get_link(host, port)` |
| 푸시형 Input 선례 | `aot/inputs/mqtt_paho_json.py` 등 `listener()` 기반 Input |
| 명령 확인 계층 | `aot/outputs/confirmable_output.py` `ConfirmableOutputMixin` |
| 복합장치 | `is_device=True` Custom Function (`device_modbus_plc_generic.py` 등) |
| Docker 네트워크 | `aot_daemon`·`aot-app`·`aot_mcp` 모두 기본 bridge + `host.docker.internal:host-gateway` |
| 백업 | `aot/utils/docker_backup.py` — SQLite + `UPLOAD_DIRS` 디렉터리만. 외부 컨테이너 볼륨은 포함 안 됨 |
| 웹소켓 클라이언트 의존성 | `requirements.txt`에 없음 |

## 2. 개념 모델

### 2-1. Fabric과 장치

```
Matter Device
 ├── Fabric A → Apple Home         ┐
 ├── Fabric B → Google Home        │ 각 관리자가 독립적으로 가입.
 ├── Fabric C → SmartThings        │ AoT는 A~C의 자격증명을 보지도
 └── Fabric D → AoT                ┘ 가져오지도 않는다.

AoT Fabric (설치당 1개)
 ├── Fabric ID / Vendor ID
 ├── Root CA (개인키 포함)
 ├── AoT 컨트롤러 Node ID · NOC · 운영 키
 └── 노드 목록·인터뷰 캐시
```

- AoT의 ACL 조작은 **자기 Fabric 엔트리에만** 해당한다. 다른 Fabric의 ACL은
  Fabric 범위로 격리되어 있어 AoT가 볼 수도 바꿀 수도 없다.
- 장치가 받아주는 Fabric 수는 유한하다(스펙 최소 5). 자리가 없으면 커미셔닝이
  실패하며, 사용자에게 "다른 생태계 연결 하나를 해제하라"고 안내해야 한다.

### 2-2. 공유 흐름

```
기존 관리자 앱 (Apple/Google/…)
   │ 사용자 승인 → "다른 앱과 공유"
   ▼
커미셔닝 창 열림 (ECM, 새 패스코드, 최대 15분)
   │ 11자리 수동 코드 또는 QR 표시
   ▼
AoT: 코드 입력 → DNS-SD(_matterc._udp)로 장치 발견
   → PASE → 장치 인증(DCL) → AoT NOC 발급·설치 → CASE
   ▼
AoT Fabric에 노드 추가 → 인터뷰(엔드포인트·클러스터) → AoT Device 생성
```

"Multi-Admin / Share"는 QR·수동 코드와 나란한 세 번째 입력 방식이 아니다. 공유
결과는 결국 코드나 QR이다. 달라지는 것은 **전송 경로**(이미 네트워크에 있음 →
on-network)뿐이다.

### 2-3. 클라우드 API 연동과의 관계

Multi-Admin 경로는 기존 생태계의 클라우드 API를 부르지 않는다. 기존 관리자 앱이
하는 일은 공유 코드 발급뿐이고, 이후 읽기·제어는 LAN 안에서 AoT↔장치로만
오간다. 그래서 생태계 API의 요금·요청 한도가 적용되지 않는다(SmartThings API
유료화 내용은 `smartthings-integration.md` 참고). Thread 장치는 그 생태계의 허브를
경계 라우터로 그대로 쓴다. 따라서 Matter 장치라면 이 경로가 클라우드 API 연동보다
우선이다.

같은 장치를 Matter와 클라우드 API 두 길로 동시에 들여오지 않는다. 측정값이 두 번
저장되고, 한쪽 명령의 확인을 다른 쪽 상태 보고가 흐린다. 커미셔닝 시
BasicInformation(`UniqueID`·시리얼)로 이미 다른 경로로 등록된 장치인지 확인하는
것은 P2 이후 과제로 둔다.

## 3. 배치

```
┌──────────────── host network ────────────────┐
│  matter_server  (ghcr.io/matter-js/matterjs-server:1.4.0, uid 1000)
│   · 저장소: matter_data 볼륨 (/data)          │
│   · API: 웹소켓, 127.0.0.1:5580 (루프백 전용)  │
│  matter_socket  (alpine/socat) — 1.4.1 까지 임시│
│   · /data/matter-server.sock → 127.0.0.1:5580 │
└──────────────┬───────────────────────────────┘
               │ ws+unix  (matter_data 볼륨을 /app/matter_data 에 :ro 마운트)
   ┌───────────┴────────────┐
   │ aot_daemon             │  Input/Output 드라이버 — 상시 연결 1개 (구독)
   │ aot-app                │  커미셔닝·노드 조회·삭제 — 요청 시 단기 연결, 백업
   └────────────────────────┘
```

### 3-1. 구현체 선택: matterjs-server

| 후보 | 판단 |
|---|---|
| `python-matter-server` (OHF, CHIP SDK 래퍼) | **제외.** 2026-06-23 저장소 아카이브, 8.1.2가 마지막 릴리스. 후속은 matterjs-server |
| `matterjs-server` (OHF, matter.js) | **채택.** python-matter-server 웹소켓 API와 호환을 목표로 함(드롭인 대체). Home Assistant가 같은 서버를 씀 |
| CHIP SDK / matter.js를 데몬에 직접 내장 | **제외.** 데몬 기동 블로킹(C2), 의존성 크기, 업그레이드 부담 |

주의할 점:
- matterjs-server는 아직 **베타이고 CSA 재인증 전**이다. AoT 쪽은 웹소켓 API에만
  의존하고 서버 구현에 의존하지 않도록 클라이언트를 얇게 둔다.
- 장치 인증·인증서 폐기 확인은 CSA DCL을 쓴다. 인터넷이 없으면 릴리스 시점 시드
  데이터로 대체되어 신규 장치 커미셔닝이 실패할 수 있다(오프라인 농장 대비 필요).
- Thread 장치 **커미셔닝**(BLE로 Thread 데이터셋 전달)은 matter.js에서 아직 제한적이다.
  1단계는 이미 Thread에 붙어 경계 라우터 너머 IPv6로 닿는 장치만 다루므로
  영향이 없을 것으로 보나, **착수 시 실기로 확인한다.**

### 3-2. 웹소켓 노출 범위

matterjs-server의 웹소켓 API에는 **인증이 없다.** 기본값은 모든 인터페이스에
바인딩이다. 열려 있으면 LAN의 누구든 AoT Fabric으로 모든 장치를 제어하거나
노드를 삭제할 수 있다.

- 결정: AoT는 unix socket `/data/matter-server.sock`으로만 들어온다. LAN에 TCP
  포트를 열지 않는다.
- **1.4.0에는 unix socket 기능이 없다**(실측 2026-10-09: 소켓 경로를 주면
  `getaddrinfo ENOTFOUND`로 웹서버가 안 뜨고 healthcheck도 `starting`에 머문다).
  지원은 upstream #1111(2026-10-05 머지)로 1.4.1부터다. 그때까지는 서버를
  `LISTEN_ADDRESS=127.0.0.1`(host network라 호스트 루프백)에 두고, `matter_socket`
  (socat) 컨테이너가 같은 볼륨에 소켓을 만들어 루프백으로 중계한다. AoT
  컨테이너는 bridge 네트워크라 호스트 루프백에 직접 닿지 못한다. 1.4.1 정식판이
  나오면 `matter_socket`을 지우고 `LISTEN_ADDRESS=/data/matter-server.sock`으로
  바꾼다 — AoT 쪽 경로·마운트는 그대로다.
- 대안으로 docker0 게이트웨이 IP에 바인딩하는 안도 있었으나, 그 IP는 설치마다
  다를 수 있고 호스트의 모든 컨테이너에 열린다. 루프백 + 소켓이 노출면이 가장
  작다(남는 노출: 호스트의 로컬 프로세스 — 호스트 셸 접근 = 장치 제어로 본다).
- 소켓을 별도 볼륨이 아니라 **Fabric 볼륨(`/data`) 안에** 둔다. 1.4.1 이후 서버가
  직접 소켓을 만들 때 uid 1000이라 자기 소유인 `/data`에만 만들 수 있기 때문이다
  (별도 named volume은 root 소유로 생긴다). 지금 경로를 그때와 같게 맞춰 둔다. 대가: `aot_daemon`·`aot-app`이 Fabric
  자료를 **읽을 수 있다**(`:ro`). 두 컨테이너는 이미 DB의 모든 비밀을 갖고 있어
  위험이 새로 늘지는 않는다고 판단했다.
- socat은 소켓을 `0660 root:root`로, 1.4.1 서버는 umask대로(소유자 1000) 만든다.
  어느 쪽이든 접속하는 쪽은 root여야 한다(non-root는 `PermissionError`, 실측).
  AoT 이미지는 root로 돈다.
- 대시보드(`DISABLE_DASHBOARD=true`)는 기본 꺼짐. 진단이 필요하면 일시적으로 켜고
  호스트에서 SSH 터널로 `127.0.0.1:5580`에 붙는다.

### 3-3. 호스트 네트워크 요구사항

matterjs-server 문서의 OS 요구사항을 AoT 설치 조건으로 옮긴다. bridge 네트워크에서는
동작하지 않는다.

| 항목 | 요구 |
|---|---|
| 컨테이너 | `network_mode: host` (mDNS·링크 로컬 멀티캐스트) |
| IPv6 RA | `net.ipv6.conf.<iface>.accept_ra=1` (forwarding 켜져 있으면 `2`), `accept_ra_rt_info_max_plen=64` — Thread 경계 라우터가 광고하는 경로를 받기 위함 |
| 영속화 | NetworkManager(≥1.42)/systemd-networkd를 쓰면 그쪽 설정에 저장. `sysctl -w`는 덮어씌워짐 |
| 커널 | `CONFIG_IPV6_ROUTER_PREF`, (NM 미사용 시) `CONFIG_IPV6_ROUTE_INFO` |
| 방화벽 | `nf_conntrack_udp_timeout_stream` ≥ 1800(권장 3600) — 슬립 장치 리포트 유지. 목적지 포트(5540)로 필터링하지 말 것 |
| 망 구성 | 장치·경계 라우터·공유하는 폰과 **같은 LAN/VLAN**. mDNS 리플렉터·멀티캐스트 최적화(Unifi, Omada) 끄기 |

Thread 장치는 기존 생태계의 경계 라우터(HomePod, Apple TV, Nest Hub, SmartThings
허브 등)를 통해 닿는다. AoT가 경계 라우터를 직접 운영하지는 않는다.

→ `aot/scripts/check_matter_host.sh`: 위 항목을 읽기 전용으로 점검하고 고칠 명령을
출력한다. 설정 화면의 Matter 페이지가 이 결과를 보여 주고, 실패하면 커미셔닝
버튼을 막는다.

## 4. AoT 도메인 매핑

### 4-1. 계층

```
MatterNode (matterjs-server가 보유)
   ↓ 인터뷰 결과(Descriptor·BasicInformation)
AoT Device       device_matter_node      (is_device, 노드 1개 = Device 1개)
  ├─ Input       matter_node             채널 = 구독할 속성 1개
  └─ Output      matter_node             채널 = 제어할 엔드포인트 1개
       ↓
Function / Trigger / env coordinator / AI 도구
```

`device-tier.md`의 청사진 방식을 그대로 쓴다. Modbus PLC와 달리 Matter는 자기
기술적이므로 **채널을 비워 두지 않고 인터뷰 결과로 채운다**(`device-onboarding.md`
"발견이 정본").

| 저장 위치 | 내용 |
|---|---|
| Device `custom_options` | `node_id`, BasicInformation(`VendorName`, `ProductName`, `SerialNumber`, `UniqueID`) |
| `InputChannel.custom_options` | `endpoint`, `cluster_id`, `attribute_id`, `scale` |
| `OutputChannel.custom_options` | `endpoint` (P1 은 OnOff 만 — 클러스터·명령은 드라이버에 고정) |

스키마 변경 없음(JSON 컬럼) — alembic 마이그레이션 불필요.

### 4-2. 1단계 클러스터 매핑

| 클러스터 (ID) | 속성 / 명령 | AoT | 변환 |
|---|---|---|---|
| OnOff (0x0006) | `OnOff` / On·Off·Toggle | Output on_off | — |
| TemperatureMeasurement (0x0402) | `MeasuredValue` | Input °C | ×0.01 |
| RelativeHumidityMeasurement (0x0405) | `MeasuredValue` | Input % | ×0.01 |
| IlluminanceMeasurement (0x0400) | `MeasuredValue` | Input lux | 10^((v−1)/10000) |
| BooleanState (0x0045) | `StateValue` | Input bool | — |
| PowerSource (0x002F) | `BatPercentRemaining` | Input % | ×0.5 |

2단계: LevelControl(0x0008), WindowCovering(0x0102, 커튼·차광), Occupancy(0x0406),
CO₂(0x040D), 전력·에너지 측정(0x0090/0x0091). 측정값 null은 "값 없음"으로 저장하지
않고 건너뛴다.

### 4-3. 장치 정체성과 재공유

사용자가 장치를 지우고 다시 공유하면 matterjs-server는 **새 node_id**를 준다.
그대로 두면 새 Device가 생기고 InfluxDB 이력(Device `unique_id` 기준)이 끊긴다.

- 결정: 커미셔닝 후 `BasicInformation.UniqueID`(없으면 `VendorID+ProductID+SerialNumber`)로
  기존 Device를 찾고, 있으면 `node_id`만 갈아끼운다.

## 5. 런타임 설계

### 5-1. 공유 클라이언트 `aot/devices/matter_client.py`

- 프로세스당 연결 1개(Modbus `get_link` 패턴). 백그라운드 스레드에서 asyncio 루프를
  돌리고 `start_listening`으로 노드 스냅샷과 이벤트 스트림을 받는다.
- `attribute_updated` 이벤트를 `(node_id, endpoint, cluster, attribute)` 키로
  등록된 Input에 분배한다. 상태 캐시를 유지한다.
- 재연결은 지수 백오프. 서버가 재시작되면 스냅샷을 다시 받아 캐시를 덮는다.
- 공식 클라이언트 라이브러리(`python-matter-server`의 client)는 아카이브되었고
  CHIP 클러스터 패키지를 끌고 오므로 쓰지 않는다. JSON 명령 몇 개만 직접 구현한다:
  `start_listening`, `get_nodes`, `commission_with_code`, `read_attribute`,
  `write_attribute`, `device_command`, `remove_node`. (명령 이름·인자는 착수 시
  matterjs-server 문서로 다시 확인한다.)
- `requirements.txt`에 웹소켓 클라이언트 추가(C6 — Docker 이미지는 자동설치 안 됨).

### 5-2. Input (`aot/inputs/matter_node.py`)

- `listener()` 기반 푸시형(`mqtt_paho_json.py`와 같은 구조). 장치에 따로 묻지 않는다.
  값을 쓰는 길은 둘이다: 서버가 보내는 변화(`attribute_updated`)를 즉시, 그리고
  `sample_interval_s`(기본 60초)마다 구독이 유지하는 현재 값을 다시. Matter 장치는
  바뀔 때만 보고하므로, 안정된 온도는 표본이 없으면 AoT 신선도 검사에서 낡아
  보인다 — 노드가 응답 중이면 구독이 그 값을 보증하므로 다시 써도 된다.
- 초기화에서 연결하지 않는다(C2). 클라이언트는 첫 사용 시 연결.
- 노드가 `available=false`가 되면 값을 쓰지 않는다. 신선도 판단은
  `sensor-freshness-and-control-cadence.md`의 규칙을 따른다(마지막 값을 새 값처럼
  다시 쓰지 않는다).

### 5-3. Output (`aot/outputs/matter_node.py`)

| 제약 | 적용 |
|---|---|
| C3 `output_switch()` 8초 Pyro 타임아웃 | 명령 1회 5초 예산. Thread 경유·슬립 장치는 더 걸릴 수 있음 |
| C4 `is_on()` 네트워크 금지 | 구독 캐시의 `OnOff` 값 반환 |
| C5 실패 신호 | `return 1, "메시지"` |
| 명령 확인 | `ConfirmableOutputMixin` — 구독 리포트로 상태 변경을 확인 |

한 Output 모듈에서 채널별로 on_off와 value(밝기·커튼 위치)를 섞을 수 있는지는
착수 시 확인한다. 안 되면 2단계에서 모듈을 나눈다.

### 5-4. 커미셔닝·삭제 (`aot/aot_flask/utils/utils_matter.py`)

`utils_chirpstack.py`와 같은 자리. Flask가 직접 서버에 단기 연결한다(데몬 RPC를
거치지 않음 — `aot_flask`는 `controllers`를 import하지 않는다는 규칙 유지).

- **추가**: 코드 입력 → `commission_with_code(code, network_only=True)` →
  인터뷰 → 청사진으로 Device/Input/Output 생성 → 첫 값 수신까지 기다림
  ("저장됨"이 아니라 "값이 들어옴"이 완료).
- **삭제**: AoT Device 삭제 시 `remove_node` → 장치에서 AoT Fabric 제거(RemoveFabric)
  → 서버 저장소에서 노드 제거. 장치가 오프라인이라 RemoveFabric이 실패하면
  사용자에게 "장치에 AoT 연결이 남아 있음 — 다른 생태계 앱에서 지우라"고 알린다.
  이 절차가 없으면 장치의 Fabric 자리가 새고, 쌓이면 다른 생태계 추가가 막힌다.

오류 분류(UI 문구 대상):

| 원인 | 안내 |
|---|---|
| 코드 만료·창 닫힘 | 기존 앱에서 다시 공유 |
| 장치 발견 실패 | 같은 네트워크인지·호스트 점검 결과 확인 |
| Fabric 자리 없음 | 다른 생태계 연결 하나 해제 |
| 장치 인증 실패 | DCL 접속(인터넷) 확인. 개발용 장치면 test-net DCL 옵션 |
| 서버 미응답 | Matter 서버 컨테이너 상태 |

## 6. Fabric 자격증명 보관

- `matter_data` 볼륨(`/data`)에 Fabric 전체가 있다. **루트 CA 개인키 포함.**
- 백업: `matter_data`를 `aot-app`에 읽기 전용으로 마운트하고
  `docker_backup.BACKUP_ONLY_DIRS`에 둔다(백업에는 담고 자동 복원은 안 함). 같은
  폴더의 소켓 파일은 복사하지 않는다. 따라서 **백업 파일을 가진 사람은 LAN 안에서 모든 Matter 장치를 제어할 수
  있다** — 백업 다운로드 화면에 이를 표시한다.
- 복원: 서버가 돌고 있는 동안 저장소를 덮으면 안 된다. `aot-app`에는 docker.sock이
  없어 서버를 직접 멈출 수 없다. 1단계는 수동 절차로 문서화하고, 자동화는
  미결로 둔다(§9).
- `VENDOR_ID`(65521 = 0xFFF1, 테스트 VID — compose 에는 **10진수**로: 서버가 10진수로 읽어
  "0xFFF1" 은 0 이 된다, P3 E2E 실측)·`FABRIC_ID`(기본 1)는 첫 기동 후 바꾸지 않는다.
  바꾸면 기존 노드 전부가 고아가 된다. compose에 고정값으로 박는다.
- 로그·MCP 응답·AI 컨텍스트에 Fabric 자료와 **페어링 코드를 남기지 않는다.**
  페어링 코드는 15분짜리지만 그동안은 장치 탈취 수단이다.

## 7. AI·MCP

- 제어: Matter Output은 일반 Output이므로 `operate_device` 등 기존 도구와 승인
  게이트를 그대로 탄다. 추가 작업 없음.
- 커미셔닝·삭제는 **1단계에서 AI 도구로 열지 않는다.** 코드는 사람이 기존 앱에서
  받아 오는 것이고, 코드를 LLM 서비스로 보내지 않기 위해서다.
- 조회: `get_device_detail`이 Device `custom_options`의 제조사·모델을 그대로 노출하면
  충분하다. "이 장치가 Apple Home에도 있다" 같은 정보는 노출하지 않는다(판단 1).

## 8. 단계

| 단계 | 범위 | 완료 기준 |
|---|---|---|
| P0 인프라 | compose `matter_server` 서비스(host network, unix socket, 볼륨), `check_matter_host.sh`, 백업 포함, `matter_client.py` 연결·재연결 | 데몬이 서버에 붙고 서버 재시작 후 자동 복구 |
| P1 공유 등록 | 설정 > Matter 페이지(점검 결과 + 코드 입력), on-network 커미셔닝, 인터뷰 → 청사진, OnOff + §4-2 센서, 삭제(RemoveFabric) | 다른 생태계에서 공유받은 플러그를 AoT에서 켜고 끔, 센서 값이 InfluxDB에 들어옴, AoT에서 지우면 장치의 Fabric 목록에서 AoT가 사라짐 |
| P2 확장 | LevelControl·WindowCovering·에너지, 노드 이벤트 → Trigger, 재공유 시 Device 재결합(§4-3), 신선도 연동 | 커튼 장치를 env coordinator 출력으로 사용 |
| P3 새 장치 | BLE 커미셔닝(Wi-Fi 먼저, Thread는 matter.js 지원 후), AoT가 커미셔닝 창을 열어 다른 생태계로 공유, OTA 정책 | 상자에서 꺼낸 장치를 AoT만으로 등록 |

검사: `matter_client`는 가짜 웹소켓 서버로 단위 검사(이벤트 분배, 재연결, 타임아웃).
P1 완료 기준은 실기 검증으로만 판정한다.

## 9. 미결

1. ~~unix socket을 웹소켓 클라이언트·matterjs-server 양쪽에서 실제로 쓸 수 있는가~~ —
   P0에서 결정(§3-2, §10).
2. 백업 복원 시 Matter 서버를 멈추고 다시 띄우는 방법(docker.sock 없이).
3. 직접 설치(systemd) 배포판에서 matterjs-server를 Docker로 돌릴지 Node로 돌릴지.
4. AoT 고유 Vendor ID(CSA 회원 가입) — 없으면 다른 생태계 앱에 AoT 연결이 테스트
   벤더로 보인다. 기능상 문제는 없음.
5. 인터넷이 없는 현장에서 DCL 시드 데이터만으로 커미셔닝이 어디까지 되는가.
6. Thread 장치가 경계 라우터 너머에서 구독을 안정적으로 유지하는가(현장 망 —
   메시 Wi-Fi, 멀티캐스트 최적화 장비).
7. SmartThings 허브 뒤의 Zigbee·Z-Wave 장치를 허브가 Matter 브리지로 다른
   컨트롤러에 내보내는가. 공식 발표로 확인된 바 없음 — 실제 허브로 확인한다.
   된다면 비-Matter 장치까지 이 경로로 들어온다.

## 10. P0 구현 결정 (2026-10-09)

| 항목 | 결정 | 위치 |
|---|---|---|
| 켜는 방법 | compose **profile** `matter`. `docker/.env`에 `COMPOSE_PROFILES=matter`. 기본 설치에서는 서비스가 안 뜨고 `matter_data`는 빈 볼륨 | `docker-compose.prod.yml`, `docker-compose.yml`, `.env.prod.example` |
| 별도 compose 파일로 빼지 않은 이유 | updater가 `docker-compose.prod.yml`만으로 aot-app/aot_daemon/aot_mcp를 재생성한다. 소켓 마운트를 다른 파일에 두면 자동 업데이트 한 번에 끊긴다. 반대로 `matter_server`는 updater의 재생성 목록에 없어 자동 업데이트되지 않는다 — 버전은 `MATTER_SERVER_TAG`로 올린다 | 같은 곳 |
| 서버 버전 | `matterjs-server:1.4.0` 고정(SCHEMA 13, 최소 11) | compose |
| 소켓 중계 | `matter_socket`(alpine/socat:1.8.1.1) — 1.4.1 정식판에서 제거(§3-2) | compose |
| 클라이언트 | `aot/devices/matter_client.py` — 프로세스당 연결 1개, 리더 스레드, 스냅샷은 리더 스레드에서 스트림 순서대로 적용, 지수 백오프 재접속(스냅샷까지 간 세션 뒤에는 초기화), 끊기면 대기 명령 즉시 실패(이미 도착한 응답은 유지), 깨진 메시지는 버리고 연결 유지, 명령 기본 시간초과 5초(C3). 생성·import 시 접속 안 함(C2). 구독 콜백 안에서 명령을 보내면 즉시 오류(리더 스레드가 자기 응답을 기다리게 되므로) | |
| 백업 | Fabric 폴더는 백업에만(자동 복원 없음). 복사 중 파일이 바뀌어 실패하면 재시도 후 그 폴더만 빼고 백업은 성공 — 업데이트 전 백업이 막히지 않게 | `docker_backup.BACKUP_ONLY_DIRS` |
| 컨테이너 안 점검 | `python -m aot.devices.matter_client` | |
| 호스트 점검 | `aot/scripts/check_matter_host.sh [--iface X] [--json]` — 읽기 전용 | |
| 의존성 | `websockets==16.0` | `requirements.txt` |

## 11. P1 구현 결정 (2026-10-09)

| 항목 | 결정 | 이유 |
|---|---|---|
| 모듈 | 장치 `device_matter_node`, Input `MATTER_NODE`, Output `MATTER_ON_OFF`, 매핑 `aot/devices/matter_clusters.py`, 연결부 `aot/devices/matter_onboarding.py`, 서비스 `aot/aot_flask/utils/utils_matter.py`, 화면 설정 > Matter | |
| 장치 만들기 | 설정 > Matter 에서만. 장치 화면의 "추가"로 만들면 `execute_at_creation`이 거절한다 | 노드가 AoT Fabric 에 먼저 있어야 의미가 있다 |
| 채널 채우기 | 커미셔닝 결과로 청사진을 동적으로 만든다(`build_blueprint`). 노드 정보는 스레드 로컬로 `function_add` 에 넘긴다 | `function_add`는 모듈 이름만 받는다. 동시 등록끼리 섞이지 않게 스레드 로컬 |
| 등록 방식 | 요청 하나에서 끝까지 기다림(동기), 제한 240초 | gunicorn gthread 300초. 여러 워커에서 백그라운드 작업은 결과가 다른 워커로 갈 수 있다. 실측: 틀린 코드는 ~227초 뒤 실패 |
| 완료 | 장치를 만들고 바로 활성화(하위 Input 시작) | "저장됨"이 아니라 "값이 들어옴"(§5-4) |
| 재공유 | `BasicInformation.UniqueID`(없으면 VID:PID:Serial)로 기존 장치를 찾아 `node_id`만 바꾸고 하위를 재시작 | 이력이 이어진다(§4-3) |
| 삭제 | `controller_del`·탭 삭제 경로에서, 하위가 시퀀스·PID·위젯 등에 아직 쓰이면 **아무것도 바꾸지 않고 거절**(비활성화도 하지 않음). 아니면 `remove_node` 후 하위 Input/Output 도 지운다. 서버에 닿지 않아도 삭제는 진행, 경고만 | Fabric 을 떠나는 것은 되돌릴 수 없다. 다른 장치는 하위가 남지만, Matter 하위는 노드 없이 동작할 수 없다. 남은 노드는 설정 > Matter 에 고아로 보여 나중에 지울 수 있다. 탭 삭제는 장치마다 동기로 지우므로(최대 ~35초/대) 응답 없는 Matter 장치가 많은 탭은 오래 걸린다 |
| 장치 쪽 Fabric | 노드가 응답할 때만 서버가 RemoveFabric 을 보낸다. 응답하지 않으면 "장치에 AoT 가 남아 있다" 경고 | 서버 동작(실측) |
| 값 쓰기 | 변화 즉시 + 주기 표본(§5-2). 서버 연결이 끊겼거나 노드가 unavailable 이면 쓰지 않는다. null 은 쓰지 않는다. 변화는 리더 스레드에서 큐에 넣기만 하고 Input 자신의 스레드에서 받은 시각으로 하나씩 쓴다 | 신선도 규칙. 쓰기는 Input Action(DB·데몬 RPC)을 돌리므로 리더에서 하면 그 프로세스의 모든 Matter 응답이 멈춘다. 빠른 열림·닫힘도 둘 다 남긴다 |
| 명령 | `device_command` On/Off, 5초 제한. invoke 가 성공하면 그 자체로 확정(`confirm_command`), 이후 OnOff 보고가 다르면 보고가 고친다. 상태를 모르면 `is_on()`은 None. 재연결·다시 응답할 때만 캐시로 상태를 다시 심고, 대기 중인 명령은 건드리지 않는다 | C3·C4. 구독은 바뀔 때만 보고하므로 같은 상태로의 명령(PID 의 반복 OFF)은 보고가 없다 — 보고만 기다리면 fault 가 된다. 보고가 begin_command 보다 먼저 처리되는 경합도 없앤다. 실측: 응답 0.1~0.2초 |
| 시작 상태 | 첫 스냅샷 뒤 별도 스레드에서 적용 | 구독 콜백은 리더 스레드라 명령을 보낼 수 없다 |
| 미응답 감지 | 서버가 장치를 unavailable 로 표시하기까지 약 5분(구독 만료 ~2분 + 서버 고정 유예 3분, 실측) | matterjs-server `RECONNECT_TIMEOUT`. 그동안 Input 은 마지막 표본 이후 쓰지 않으므로 신선도 쪽에서 먼저 드러난다 |
| 웹소켓 연결 | 데몬: 프로세스당 상시 연결 1개, ping 20초. 웹: 요청마다 연결을 열고 닫으며 ping 제한을 커미셔닝 시간보다 길게 | 데몬은 끊김이 빨리 드러나야 한다(연결이 살아 보이는 동안 Input 은 값을 현재값으로 쓴다). 웹은 실패하는 커미셔닝 동안 서버가 ping 에 답하지 않는다(~227초 실측). gunicorn 워커마다 노드 전체 사본·이벤트를 상시로 들고 있을 이유가 없다 |
| Fabric 라벨 | 커미셔닝 전에 `set_default_fabric_label` "AoT" | 안 하면 다른 앱에 AoT 연결이 "HomeAssistant" 로 보인다(실측) |
| 토스트 | 서버 문구를 이스케이프해서 띄운다 | toastr 는 HTML 을 해석하고, 문구에 장치가 스스로 정한 이름이 섞인다 |
| 실패한 생성 | 청사진이 만든 하위를 지운다 | 부모가 저장되지 않으면 하위만 남아, 재시도마다 쌓인다 |
| 테스트 장치 | `ENABLE_TEST_NET_DCL`은 compose 기본 꺼짐. 개발용 장치(VID 0xFFF1, matter.js 예제 등)는 켜야 등록된다 | 실제 설치에서 테스트 인증서를 받지 않는다 |

검증 수단: `@matter/examples@0.15.6` 가상 플러그·온습도 센서를 host 네트워크에 띄워
실제 matterjs-server 로 등록·제어·제거를 확인했다(Docker Desktop VM 안의 mDNS 로 충분).

## 12. P2 구현 결정 (2026-10-10)

| 항목 | 결정 | 이유 |
|---|---|---|
| 센서 추가 | 압력(kPa)·유량(L/min)·재실(bool)·CO₂(ppm)·PM2.5(µg/m³)·토양수분(SoilMeasurement → `volumetric_water_content` %)·전력(W)·전압(V)·전류(A)·누적에너지(kWh) | AoT 기존 측정 이름에 맞춤. CO₂·PM2.5 는 장치의 단위 속성(attr 8)이 AoT 가 저장하는 단위일 때만 — 다른 단위를 잘못 환산해 저장하지 않는다. 누적에너지는 태그 키 구조체 `{"0": mWh}` |
| 디머 | `MATTER_LEVEL`, AoT `pwm`(0~100 %). 1~100 % → MoveToLevelWithOnOff(level 1~254), 0 %/off → OnOff Off(없으면 level 1), 값 없는 on → On. 장치가 보낸 레벨에 머무는 동안은 명령한 듀티를 상태로 보인다(40 → 40.2 로 보이지 않게) | AoT 의 모든 조명 디머가 pwm 이고, 코디네이터 조명 어댑터·PWM 위젯·PID 가 듀티를 말한다. 장치는 level 0 을 거절한다(실측) |
| 디머로 볼 엔드포인트 | Descriptor DeviceTypeList 가 디밍형(0x0101 Dimmable Light, 0x010B Dimmable Plug-in, 0x010C, 0x010D)일 때만. 그때만 같은 엔드포인트의 OnOff 를 별도 스위치로 만들지 않는다(`supersedes`). 그 밖의 LevelControl 은 무시하고 스위치로 둔다 | LevelControl 은 일반 On/Off 조명·플러그에도 선택 사항이다. 릴레이 플러그를 디머로 만들면 코디네이터가 히터·펌프를 30 % "레벨"(= 항상 켜짐)로 몰게 된다(검토) |
| 커튼·차광·환기창 | `MATTER_COVERING`, AoT `value`, **엔드포인트마다 Output 하나(채널 0)**. AoT 100 = 열림 ↔ Matter 0 = 열림을 모듈 안에서 뒤집는다. 위치 인식(PositionAwareLift)이면 GoToLiftPercentage, 아니면 ≥50 % 열기·<50 % 닫기. off = StopMotion | 코디네이터는 위치 액추에이터의 마지막 위치를 채널 0 에서만 읽는다. off 를 정지로 쓰는 것은 값 위젯·actuator_paired 와 같다 |
| 코디네이터 연동 | `OUTPUT_INFORMATION['self_positioning']` (새 키, `parse_output_information` 화이트리스트) → `select_adapter` 가 PairedAdapter 를 고른다. 0 % 도 위치 명령으로 간다 | 기본 ValueAdapter 는 0 % 를 `output_off`(= 정지)로 보내 "닫기"가 "멈춤"이 된다. paired 집합에 넣으면 자동 발견·3방향 UI·다리 인터록까지 끌려온다 |
| 위치 기억 | 정지했을 때(작동 상태 lift 비트 0)와 이동 중 10초에 한 번, 채널 0 `last_position_pct`(AoT 기준)와 InfluxDB 에 기록. 작업 스레드에서 | 코디네이터 `_sync_prev_from_devices` 가 재시작·수동 조작 뒤 이 값을 기준으로 삼는다. 장치는 이동 중 초당 ~5회 보고한다(실측). 리더 스레드에서 DB 를 쓰지 않는다 |
| 숫자 상태 | 디머·커튼은 ConfirmableOutputMixin 의 불리언 확정을 쓰지 않는다. 장치 보고가 상태, invoke 성공이 명령 성공. `_shared_link` 로 노드 장애만 fault 로 | 그 장치는 값을 True/False 로 덮는다. 공통부는 `aot/devices/matter_output.py` |
| 실패 신호 | 디머·커튼 모두 `(1, msg)`. base_output 의 value 경로도 이제 pwm·on_off 처럼 `_switch_failed` 를 본다(공통 변경) | 예전 value 경로는 반환값을 버려 모듈이 예외를 던져야 했고, 그러면 명령 감사·Trigger 가 건너뛰어졌다(검토) |
| 지도 | `self_positioning` value 출력은 지도 마커·팝업에서 paired 와 같은 닫기/정지/열기(값 0 / off / 값 100)로. 출력 페이지는 값 입력 그대로 | 지도에서 ON/OFF 토글로 그려져 켜기가 아무것도 안 하고 끄기가 정지가 되던 것(검토). 출력 페이지의 3방향 카드는 paired 릴레이 다리를 엮는다 |
| off 의 뜻 | 커튼의 off 는 정지다(paired 와 같음). 비상정지·종료 동작·AI `operate_device close` 등 "off = 닫힘"으로 쓰는 호출은 커튼을 멈출 뿐 닫지 않는다 | 기존 paired 와 같은 의미라 새로 생긴 위험은 아니다. 닫힘이 필요하면 값 0 을 보내야 한다 — 미결로 남긴다 |
| 버튼 | Switch 이벤트로만 기록하는 채널(`event_only`): 누른 횟수(멀티프레스면 장치가 센 값, 놓기 기능 없는 버튼은 InitialPress 마다 1), 길게 누름 = −1. 표본으로 다시 쓰지 않는다. 기록하면서 edge Trigger(rising) 실행 | 다시 쓰면 Input Action 에 새 누름처럼 보인다. edge Trigger 는 GPIO 입력과 같은 기존 장치다 |
| 보고된 변화와 가용성 | 구독으로 보고된 변화(속성·버튼)는 노드 가용성 표시와 관계없이 쓴다 | 보고 자체가 살아 있다는 증거다. 장애 뒤 가용성 표시가 늦게 따라오는 사이의 접점 변화를 버리면 그 edge 도 영영 사라진다(검토) |
| 접점·재실 | 값이 바뀔 때(보고 경로만) edge Trigger 실행 — 켜짐 rising, 꺼짐 falling. 첫 기록·표본에서는 실행하지 않음 | edge Trigger 는 Input 에 묶이고 채널은 메시지에만 나온다(제약) |
| 신선도 | 기본값 유지(`max_age_s` 비움 → 300초 유도). 표본 60초면 4번 놓쳐도 신선 | 모듈별 기본 수명 훅이 없고, 표본 주기를 150초 넘게 늘릴 때만 사용자가 늘리면 된다 |
| 다시 읽기 | 설정 > Matter "다시 읽기": 노드를 다시 읽어 지원하게 된 채널을 덧붙인다(기존 채널은 건드리지 않음, 입력·출력 모두 채널 번호 재사용 안 함). 스위치로 등록된 디밍 엔드포인트에는 디머를 덧붙이지 않고 안내만 한다(스위치 출력을 지우고 다시 읽으면 디머가 된다) | P1 에 등록된 장치가 P2 기능(전력·디머 등)을 얻는 길. 한 엔드포인트를 두 출력이 명령하면 자동화끼리 싸운다 |
| 위치 기록 실패 | 저장이 실패하면(설정자가 값을 돌려주지 않음) 다음 보고에서 다시 쓴다 | 정지 시 기록이 실패하면 코디네이터가 매 사이클 이동 중 값으로 되맞춘다(검토) |
| 디머 정착 창 | 레벨 명령 뒤 2초 동안은 명령과 다른 레벨 보고를 옛 값으로 보고 명령값을 유지 | 끈 상태에서 켜면 장치가 OnOff=true 를 새 레벨보다 수십 ms 먼저 보내 옛 레벨이 잠깐 기록됐다(E2E) |
| 커튼 목표 출처 | 우리가 보낸 목표면 호출자가 준 출처(값 위젯은 'manual'), 아니면 'system' | 값 위젯이 사람의 조작을 "System" 으로 보이던 것(E2E) |
| 검증 장치 | `@matter/examples` 0.15.6 기반 가상 디머·커튼(이동 시뮬레이션)·센서팩·버튼·접점 | SoilMeasurement 는 그 버전에 없어 실기 검증 전 |

**P2 완료 기준 확인(2026-10-10, 가상 장치 E2E)**: 시설 + 통합환경제어 Function + `env_actuator`
(종류 shade)를 Matter 커튼 출력에 묶고 활성화 → 코디네이터가 광량 조건으로 차광을 닫았다
(감사: `output.control channel=0 state=on type=value amount=0.0 origin=env_coordinator`,
장치 Matter 10000 = 완전히 닫힘, `last_position_pct` 0.0). 어댑터는 PairedAdapter.

## 13. P3 구현 결정 (2026-10-10)

| 항목 | 결정 | 이유 |
|---|---|---|
| 새 장치(상자에서 꺼낸 장치) | 설정 > Matter "새 장치 추가": 코드 + 네트워크(Wi-Fi / Thread / 이미 네트워크에 있음). `commission_with_code(network_only=False)` 로 BLE 탐색 → PASE → 네트워크 설정 → IP 재발견. 서비스는 `aot/aot_flask/utils/utils_matter_admin.py` | matterjs-server 1.4.0 은 `BLUETOOTH_ADAPTER` 로 BLE 를 켠다(`--ble` 플래그 없음). Thread 는 데이터셋만 주면 네트워크 이름을 matter.js 가 알아낸다(0.17.9 소스) |
| 작업(job)과 폴링 | 새 장치 등록은 스레드에서 돌고 상태는 `DATABASE_PATH/matter_jobs/<id>.json`. 페이지가 3초마다 묻는다. 제한 600초 | BLE 탐색 3분 + Wi-Fi 연결 2분 + IP 재발견 2분이 이어질 수 있어 요청 하나(gunicorn 300초)에 담기지 않는다. 파일이라 어느 워커가 받아도 같은 답 |
| AoT 장치 만들기 | 작업 스레드는 Matter 서버와만 이야기하고, 노드가 들어오면 **사용자의 폴링 요청 안에서** `register_node`. 파일 잠금으로 한 번만 | 권한·그룹 스코프 검사가 사용자 맥락에서 그대로 적용된다 |
| 네트워크 비밀 | Wi-Fi 비밀번호·Thread 데이터셋을 AoT 에 저장하지 않는다. 등록 직전 일회용 id 로 서버에 넣고(`set_wifi_credentials`/`set_thread_dataset`) 끝나면 성공·실패와 관계없이 서버의 자격증명 목록에서 지운다(`remove_*`). 작업 파일·로그·오류 문구에 남기지 않는다(오류 문구에서 지움) | 서버는 이것을 데이터 볼륨에 암호화 없이 저장하고, 그 볼륨은 AoT 백업에 들어간다. 페어링 코드와 같은 원칙 |
| **남는 위험(미해결)** | 서버 저장소는 추가 전용 기록(WAL, `/data/config/wal/*.jsonl`)이라 지운 뒤에도 비밀번호·데이터셋이 그 기록에 평문으로 남는다(재시작 후에도, P3 E2E 실측). matterjs-server 1.4.0 API 로는 지울 수 없고, Wi-Fi 를 자격증명 저장소를 거치지 않고 넘기는 길도 없다. 화면 안내·백업 경고에 그대로 적는다. 대응: 백업 파일을 비밀로 다루고, 필요하면 등록 뒤 Wi-Fi 비밀번호를 바꾼다. upstream 이 기록 압축이나 일회성 전달을 지원하면 다시 본다 | "지웠다"고 말하면 거짓이 된다 |
| 서버 로그 수준 | `MATTER_LOG_LEVEL=debug` 를 켜 두지 않는다(compose 주석) | debug 에서 서버가 WS 요청 원문(비밀번호 포함)을 남긴다 |
| BLE 켜기 | `docker/docker-compose.matter-ble.yml` 오버라이드(`BLUETOOTH_ADAPTER`, `NOBLE_BINDINGS=dbus`, `/run/dbus:ro`). 컨테이너는 비특권(uid 1000) 유지. 점검: `check_matter_host.sh --ble` | BLE 는 선택이고 호스트 BlueZ 가 있어야 한다. dbus 방식은 권한 상승이 필요 없다. updater 는 matter_server 를 재생성하지 않으니 오버라이드가 유지된다 |
| BLE 프록시 | P3 범위 밖 | 서버가 루프백에만 열려 있어 다른 호스트의 프록시가 닿지 못한다 |
| 다른 생태계로 공유 | 장치 행 "공유": `open_commissioning_window`(강화 창, 기본 15분, 3~15분으로 제한) → 11자리 코드 + `MT:` 페이로드 텍스트 + 남은 시간. "공유 닫기" = `RevokeCommissioning`. 코드는 저장·기록하지 않음. 시작 전 장치의 Fabric 자리(0/62/2·3)가 꽉 찼으면 거절 | QR 이미지는 만들지 않는다(TOTP 와 같은 판단 — 의존성 없이, 앱들은 11자리 코드를 받는다) |
| 연결된 생태계 | 공유 창에 장치의 Fabric 목록(`get_matter_fabrics`, 라벨·제조사·AoT 여부)과 다른 생태계 "연결 해제"(`remove_matter_fabric`). AoT 자신의 Fabric 은 여기서 지우지 못한다(장치 삭제로만 — 하위 정리 때문) | 장치가 어디에 공유돼 있는지 보이고, 자리를 비울 수 있다 |
| 펌웨어(OTA) 정책 | 서버의 자동 확인(DCL)은 그대로 두되 **설치는 사람만 시작**한다(`update_node`). CSA 인증 출처(main-net DCL)만 설치, 장치가 응답 중이고 OTA 상태가 Idle 일 때만. 진행은 장치의 OTA Requestor 상태(0/42/2·3)를 목록에 표시 | 서버는 요청 없이는 펌웨어를 밀지 않는다(소스 확인). 농장 장치는 재부팅이 곧 제어 중단이므로 자동 설치하지 않는다. 테스트넷·로컬 이미지는 인증되지 않았다 |
| 쫓겨남(eviction) | 공유받은 생태계는 AoT 의 Fabric 을 지울 수 있다. 그때 서버는 노드를 몇 분 넘게 `available` 로 보이고 명령만 시간초과된다(실측). 그래서 Input 의 주기 표본은 캐시가 아니라 장치에서 **바로 읽고**(`read_attribute`, 10초), 실패하면 쓰지 않고 통신 장애로 표시한다 | 낡은 캐시 값을 새 값처럼 기록하지 않기 위해(§5-2 의 신선도 원칙). 노드당 표본 주기마다 읽기 한 번 |
| 다른 생태계 연결 해제 확인 | `remove_matter_fabric` 는 아무것도 지우지 못해도 `{}` 를 준다(실측) → 장치의 Fabric 목록을 다시 읽어 확인한다 | |
| 공유 닫기 | 열린 창이 없을 때 서버는 "cluster code 4"(WindowNotOpen)로 답한다 → 성공으로 본다. 창을 두 번 열면 서버가 앞 창을 먼저 닫아 이전 코드는 무효(실측) | |
| BLE 표시 | 어댑터가 BLE 를 지원하지 않아도 서버는 `bluetooth_enabled: true` 를 낸다(Docker Desktop 실측) → 등록이 3분 탐색 시간초과로 끝난다. 그래서 `check_matter_host.sh --ble` 가 진짜 판정이다 | |
| AoT 의 Fabric 자리 | 장치마다 Fabric 번호를 스스로 매긴다. AoT 가 그 장치에서 몇 번인지는 장치의 CurrentFabricIndex(0/62/5, AoT 가 읽은 값)로 판정한다. 모르면 다른 생태계 연결 해제를 모두 거절한다 | 서버의 `fabric_index` 는 서버 자신의 표 자리(보통 1)라, 구글에서 공유받은 장치(구글 1·AoT 2)에서 구글을 AoT 로 표시하고 AoT 자신을 지울 뻔했다(검토) |
| 남은 자격증명 청소 | 작업 파일에 자격증명 id(비밀 아님)를 남기고, 새 작업 시작 전·작업이 낡았을 때 `get_all_credentials` 의 `aot-*` 중 살아 있는 작업 것이 아닌 것을 지운다 | 워커가 작업 중 죽으면(재시작·업데이트) `finally` 가 돌지 않아 비밀번호가 서버에 평문으로 남는다(검토) |
| 작업 파일 | 쓰기는 임시 파일(mkstemp) + 교체, 갱신은 영구 잠금 파일(flock) 아래. 등록은 'registering' 으로 표시해 한 번만, 그 요청이 죽으면 2분 뒤 다시 | 동시 쓰기로 성공한 등록이 실패로 기록되거나 장치가 둘 생기는 경합(검토) |
| 배터리(ICD) 장치 표본 | ICD Management(0x0046)가 있는 장치는 실시간 읽기 대신 구독 캐시로 표본한다. 일반 장치는 읽기를 보낸 시각으로 기록하고, 읽는 동안 온 변화는 그 뒤에 쓴다 | 잠자는 장치는 10초 안에 답하지 못해 표본마다 장애가 되고 배터리가 닳는다(검토) |
| 그룹 스코프 | 장치별 동작의 스코프 조회가 실패하면 막는다(503). AoT 장치가 없는 노드는 그룹 제한이 없는 사용자만 | 실패 시 통과하던 것(검토) |
| 고아 노드 | AoT 장치 없이 Fabric 에만 있는 노드에 "AoT 장치 만들기"(`adopt_node`) — 새 장치 등록 중 탭을 닫은 경우 등 | 작업은 폴링 요청에서 장치를 만들므로, 아무도 폴링하지 않으면 노드만 남는다 |
| 검증 결과(2026-10-10, 가상 장치·서버 2대 E2E) | 공유 → 다른 서버가 11자리 코드로 등록, 양쪽 제어 / 다시 공유하면 앞 코드 무효 / 공유 닫기 / 연결된 생태계 목록·해제(AoT 자신 거절) / 쫓겨난 뒤 Input 표본 중단·통신 장애 표시·명령 오류 / 펌웨어 확인("최신")·OTA 꺼짐 안내 / 새 장치 작업(이미 네트워크·Wi-Fi 경로, 6개 동시 폴링에 장치 1개, 작업 중 자격증명 존재 → 끝나면 목록에서 사라짐) / 고아 노드 장치 만들기 / 로그에 코드·비밀번호 없음. 남은 것: 쫓겨난 노드가 목록에서 "응답 중"으로 남는 것(서버의 available 이 늦다, Input 은 장애로 표시), 서버 WAL 의 비밀번호 잔존(위 "남는 위험") | |
| 검증 | 공유·Fabric·OTA 확인·자격증명 넣고 지우기는 가상 장치·서버 2대로 E2E. 실제 BLE 등록은 이 환경(macOS Docker Desktop)에서 불가 — Linux 호스트 실기 확인이 P3 완료 기준 | |

## 14. 선택 기능·네이티브 설치 (2026-10-10)

- **선택 기능**: 설정 > 일반 `Misc.matter_enabled`(p6_84, 기본 꺼짐). 켜야 설정 메뉴·Matter
  페이지·API 가 열린다. 장치가 있으면 끄지 않는다. 의존성은 `DEPENDENCIES_GENERAL['matter']`
  — 네이티브는 패키지 관리로 설치, Docker 는 이미지가 들고 있다(C6).
- **네이티브(systemd) 설치**: Matter 서버만 Docker 로 띄운다(`docker/docker-compose.matter-native.yml`).
  소켓 중계는 없다 — AoT 가 호스트에서 돌아 루프백 5580 에 바로 닿으므로 세 서비스에
  `AOT_MATTER_URL=ws://127.0.0.1:5580/ws`(`install/aot-matter.conf` drop-in). 경로 `/ws` 는
  실측(루트 `/` 는 404). 서버 설정은 prod 의 matter_server 와 같아야 하고
  `test_matter_native_files.py` 가 지킨다. 루프백 포트에 인증이 없으므로 그 호스트의 셸
  접근은 장치 제어와 같다(§3-2 와 같은 판단). 네이티브 백업은 Matter 볼륨을 담지 않는다.
- 첫 실기기 후보: aot-gw-001(Pi 4 8GB, 네이티브, Debian 13, hci0, LAN 링크로컬 IPv6 만).
  호스트 점검 FAIL 2건(accept_ra, NetworkManager 관리 — Thread 전용), Docker 없음,
  블루투스 전원 꺼짐(AutoEnable).

## 참고

- matterjs-server: <https://github.com/matter-js/matterjs-server> — `docs/docker.md`, `docs/os_requirements.md`
- python-matter-server (아카이브): <https://github.com/matter-js/python-matter-server>
