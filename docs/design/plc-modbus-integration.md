# PLC(Modbus TCP) 연동 설계

작성: 2026-07-27. 기준 문서 — Modbus 드라이버가 AoT의 기존 계층(공유 장치 접근,
명령 확인, 통신 상태)에 어떻게 얹히는지와, 그 배치를 강제하는 런타임 제약을 정의한다.
착수 배경·단계별 진행 기록은 `.local/plans/plc_modbus_integration_plan.md` 참조.

## 1. 구성 요소

| 파일 | 역할 |
|---|---|
| `aot/devices/modbus_client.py` | `(host, port)` 키 공유 연결 레지스트리 + 링크 상태 + 값 인코딩/디코딩 |
| `aot/inputs/modbus_tcp.py` | 코일·레지스터 폴링 Input (채널 = 읽을 레지스터 1개) |
| `aot/outputs/on_off_modbus.py` | 코일 on/off Output (채널 = 코일 1개) |

세 파일 모두 스키마를 건드리지 않는다. 접속정보는 `Input/Output.custom_options`,
레지스터 정의는 `InputChannel/OutputChannel.custom_options`(JSON 컬럼)에 들어가므로
alembic 마이그레이션이 필요 없다.

## 2. 연결은 왜 공유하는가

PLC 1대에 Input 여러 개와 Output 여러 개가 붙는 것이 정상 구성이다. 드라이버마다
독립 TCP 연결을 열면 두 가지가 깨진다.

1. **연결 수 고갈** — 상당수 PLC/게이트웨이는 동시 TCP 연결을 1~8개로 제한한다.
2. **트랜잭션 충돌** — pymodbus 클라이언트는 스레드 안전하지 않다. Input은 각자
   스레드에서 도므로, 같은 연결을 락 없이 공유하면 transaction ID가 뒤섞인다.

→ `get_link(host, port)`가 프로세스 레벨 레지스트리에서 `ModbusTCPLink`를 돌려주고,
모든 요청-응답 한 쌍을 그 연결의 `RLock`으로 감싼다. 8스레드 × 50회 = 400요청
동시 실행에서 예외 0건·값 뒤섞임 0건으로 확인했다.

`/var/lock` 파일 락은 쓰지 않는다. 그것은 데몬과 Flask가 같은 I2C 버스를 만지는
크로스 프로세스 상황용이고, Modbus는 데몬 단일 프로세스에서만 동작하므로
`threading.RLock`이 더 정확하고 가볍다. **향후 Modbus Input을 GIS 레이어로 노출하면
이 전제가 깨지므로 파일 락으로 승격해야 한다.**

## 3. 설계를 지배하는 런타임 제약

코드 검증으로 확정한 사실이며, 아래 배치는 전부 이 제약의 귀결이다.

| # | 사실 | 귀결 |
|---|---|---|
| C1 | Input 하나당 스레드 1개. 소켓 대기는 GIL을 놓는다 | 폴링 중 블로킹 자체는 허용 가능 |
| C2 | 드라이버 `__init__`/`initialize()`가 블로킹하면 **데몬 전체 기동이 멈춘다**. `ready.wait()`에 타임아웃이 없고 부팅 시 장치를 순차 활성화 | **생성·초기화 경로에서 connect 금지.** lazy connect |
| C3 | `output_switch()`는 Pyro 워커 스레드에서 동기 직접 호출. 클라이언트 타임아웃 8초 | 쓰기 1회 총 소요를 8초 훨씬 아래로 예산 편성 |
| C4 | `is_on()`은 출력 페이지 폴링마다 **전 채널 직렬 호출**된다 | **`is_on()`에서 네트워크 I/O 금지, 캐시 반환** |
| C5 | 실패 신호 표준은 `output_switch()`의 `(code, msg)` 튜플. 평문 문자열은 무시되어 **성공 처리됨** | 실패 시 반드시 `return 1, "메시지"` |
| C6 | Docker 이미지에는 virtualenv도 setuid 래퍼도 없어 `dependencies_module` 자동설치가 동작하지 않는다 | `requirements.txt`에 직접 추가 |

## 4. 타임아웃 예산 (실측)

pymodbus 3.14 시뮬레이터 실측값이다.

- 요청 1회 최악 소요 = `timeout × (retries + 1)`
- `connect()` 최악 소요 = `timeout` (재시도 배수 없음)
- 연결 거부(포트 닫힘)는 즉시 실패, 서버 재기동 후에는 다음 호출에서 자동 복구

→ **기본값 `timeout_s=1.0`, `retries=1`.** 명령 1회는 write + readback 2요청이지만
write가 실패하면 거기서 끝나므로, 최악 경로는 `connect 1.0s + write 2.0s ≈ 3.0s`로
C3의 8초 예산 안에 든다. pymodbus의 ctor 기본값은 `retries=3`이라 그대로 두면 이 값이
5.0s가 된다 — **반드시 명시 지정해야 한다.**

## 5. 명령 확인 (Output)

새 상태기계를 만들지 않고 기존 `ConfirmableOutputMixin`을 쓴다. `on_off_kasa_plugs.py`가
이미 "명령 후 즉시 동기 재조회 → confirm" 패턴으로 이 인프라를 쓰고 있고, Modbus의
write→readback이 정확히 같은 모양이기 때문이다.

```
prev_state 기록
  → write_coil + read_coils (같은 락 구간)
      실패: begin_command(dispatched_ok=False) → (1, msg)
      성공: begin_command(dispatched_ok=True) → confirm_command(actual)
              actual ≠ 요청이면 (1, msg)
```

**호출 순서가 핵심이다.** `begin_command()`를 쓰기 *앞*에서 부르면 통신이 실패해도
낙관적 ON이 남아 UI에 팬텀 ON이 뜬다. 반드시 전송을 시도한 뒤 `dispatched_ok`와 함께
부른다. `dispatched_ok=False`는 낙관적 전환 없이 이전 상태를 유지시킨다.

`confirmation_capable()`은 항상 `True`다 — 매 명령의 readback이 곧 장치 피드백이다.
`is_pending()` 창은 사실상 0에 가깝다(쓰기와 확인이 같은 호출에서 끝남).

**readback의 한계**: PLC의 코일 레지스터가 바뀐 것만 증명한다. 릴레이 고착이나 배선
단선 등 물리 상태는 증명하지 못한다. 확인하려면 별도 피드백 접점을 Input으로 읽어
비교해야 한다.

## 6. 통신 상태 (링크 축)

`ConfirmableOutputMixin.comm_is_fault()`는 세 축의 OR 합성이다: offline 축, 명령 축,
그리고 **링크 축**. 링크 축은 드라이버가 `self._shared_link`에 `is_healthy() -> bool`을
가진 객체를 지정하면 활성화되며, `ModbusTCPLink`가 바로 그 계약의 첫 실사용 구현체다.

이 배선이 있어야 **명령이 한동안 없어도 PLC가 죽으면 그 PLC의 전 채널이 fault로**
보인다. 빼먹으면 조용히 죽은 PLC가 UI에 아무 흔적도 남기지 않는다.

두절 확정은 **연속 2회 실패**부터다(`FAILURES_BEFORE_UNHEALTHY`). 단발 프레임 유실로
PLC 전체가 빨갛게 칠해지는 것을 막기 위한 값이다.

Input 쪽에는 이 배선이 필요 없다. 폴링형(`has_loop`) Input이라 `controller_input.py`가
측정 신선도(`last_measurement` + `STALE_FACTOR`)로 통신 상태를 자동 판정한다.
**그래서 읽기 실패 시 아무 값도 저장하지 않는 것이 곧 신호다** — 자리 채움값을 넣으면
오히려 두절을 가린다.

## 7. 기동 직후 초기 상태 (Output)

데몬 재기동 후 코일의 실제 상태를 알아야 하지만, 읽을 위치가 까다롭다.

- `is_on()`에서 읽기 → **불가.** 출력 페이지가 전 채널의 `is_on()`을 직렬 폴링하므로
  (C4), PLC 무응답 시 `타임아웃 × 채널 수`만큼 페이지 전체가 멈춘다.
- `initialize()`에서 동기로 읽기 → **불가.** 부팅 시 순차 활성화를 막는다(C2).

→ `initialize()`가 **데몬 스레드 하나를 띄워 1회 프라임**하고, 성공 시
`confirm_command(ch, actual, 'startup-probe')`로 캐시를 채운다. 프라임 완료 전에는
`is_setup()`이 `False`라 `is_on()`이 `None`을 반환하고 UI는 "확인 불가"로 표시된다 —
꺼져 있다고 단정하지 않는다.

PLC가 부팅 시점에 죽어 있어도 프라임 종료 시 `output_setup=True`로 둔다. 살아난 뒤
조작 불가로 남는 것을 막기 위해서이고, 링크 상태는 이미 `comm_is_fault`가 알린다.

## 8. pymodbus 3.x 주의사항

`pymodbus==3.14.0`에 핀 고정한다. 2.x와 호환성이 깨진 것은 알려져 있었으나 3.x 안에서도
계속 이동 중이다.

| 항목 | 사실 |
|---|---|
| slave 지정 | `slave=`가 아니라 **`device_id=`** |
| 인자 형태 | `count`/`device_id` 전부 키워드 전용 |
| 32bit 디코딩 | `BinaryPayloadDecoder` 제거 → `convert_from_registers(regs, DATATYPE, word_order=...)` |
| 데이터스토어 | `ModbusSequentialDataBlock`/`ModbusServerContext`는 v4에서 제거 예정(`SimData`/`SimDevice`로 이행) — **서버 측만 해당, AoT는 클라이언트만 사용** |

`word_order`를 채널 옵션으로 노출한 이유도 여기 있다. 32bit 값의 레지스터 순서는
벤더마다 다르며, 주소가 맞는데 값이 엉뚱하면 대부분 이 항목이다.

pymodbus의 import는 `modbus_client.py` 안쪽(첫 요청 시점)으로 미뤄져 있다. 덕분에
**라이브러리가 설치되지 않은 환경에서도 Input/Output 스캐너가 모듈을 읽을 수 있다.**

## 9. 보안

Modbus 프로토콜에는 인증도 암호화도 없다. PLC는 반드시 격리망(VLAN 또는 방화벽
allow-list)에 두고 WAN 노출을 금지한다. 접속정보(host/port/unit id)는 그 자체로
민감정보가 아니므로 `custom_options` 평문 저장으로 충분하다.

AI(MCP) 쪽은 별도 도구를 만들지 않았다. Modbus 장치도 일반 Input/Output으로 등록되므로
기존 `set_output_state`/`operate_device`(`physical=True`)로 노출되며, **PLC 제어는
자동으로 사람 승인 게이트를 통과한다.**

## 10. 검증 수준

전부 **pymodbus 시뮬레이터** 기준이며 라이브 DB는 접촉하지 않았다(상태 주입 방식).
공유 클라이언트 6항목, Input 8항목, Output 7항목 통과.

**실장비로 확인하지 못한 것 — 첫 실기 연결 시 반드시 재확인할 것:**

- 실제 PLC의 동시 TCP 연결 수 제한
- 벤더 레지스터 맵의 주소 기준(0-based / 1-based)과 워드 순서 관례
- 폴링 주기가 PLC scan cycle에 주는 부하
- 릴레이 물리 동작(readback으로는 증명 불가 — 5절 참조)
- Modbus RTU(시리얼). 시리얼은 진짜 배타 자원이고 Flask 접근 가능성도 달라지므로,
  착수 시 `/var/lock` 파일 락 채택을 재검토해야 한다(2절).
