# LoRaWAN 밸브 제어 — 배터리 절감 + 명령 신뢰성 통합 설계

작성 2026-06-29 · 대상: 차기 스케줄러 + 펌웨어 업데이트 · 검증 환경: aot-004(옥정호, 네이티브 ChirpStack 4.14.1, 단일 게이트웨이 붕어섬, 활성 Class C 밸브 14대)

---

## 1. 결론 먼저 (측정 기반)

- **HB·confirmed 다운링크는 배터리에 사실상 영향 없음(<1%)**. 배터리 소모의 ~99%는 **Class C 연속 수신(RX)**.
- 현재 현장은 **클래스 컨트롤러가 전부 비활성**(class_scheduler 1 + mode_manager 9, 모두 `is_activated=0`)이라 디바이스가 부팅 기본값 Class C에서 **24/7 상주** → 배터리 최대 소모.
- 따라서 배터리 전략 = **Class C 점유 시간 최소화**. HB 주기 단축/confirmed 제거로는 의미 있는 절감 불가.

---

## 2. 전력 모델 (RAK3172 / STM32WLE5, KR920, typical)

| 상태 | 전류 |
|---|---|
| Class C 연속 RX (radio+MCU) | ~5.5 mA (상시) |
| Class A idle (Stop2+RTC) | ~0.003 mA |
| TX @14dBm | ~45 mA (airtime 동안) |
| 업링크 1회 airtime (SF7, ~18B) | ~56 ms → **0.7 µAh/회** |

### 일일 소모량 (디바이스 1대)

| 시나리오 | RX/idle | HB | 합계 | 절감 |
|---|--:|--:|--:|--:|
| **Class C 24/7 (현재)** | 132.0 | 0.03 | **132 mAh/day** | 0% |
| 스케줄러 ON: C 13h(05–18)+A 11h | 71.5 | 0.07 | **72 mAh/day** | 46% |
| AUTO: C 5h(관수시만)+A 19h | 27.6 | 0.03 | **28 mAh/day** | 79% |
| **Class A 기본 + 온디맨드 C 1.5h** | 8.3 | 0.03 | **8 mAh/day** | **94%** |

### HB·confirmed 정량 (사용자 질문에 대한 답)
- **HB**: Class C에선 RX가 지배해 HB는 무관(2분 주기여도 0.5 mAh/day). Class A에서도 30분 주기 ~0.1 mAh/day. **HB를 절반으로 줄여도 ~0.05 mAh/day 절감 — 132 mAh 앞에서 무의미.** HB는 배터리 레버가 아니라 *명령 지연(Class A)·업링크 충돌(신뢰성)* 레버다.
- **confirmed**: confirmed 다운링크 1건당 디바이스 ACK 업링크 +1회(~0.7 µAh). 50건/day여도 **0.035 mAh/day — 무시 가능**.
- **"HB+confirmed 중복"의 배터리 증가 = 합쳐도 1% 미만.** 배터리 관점에서 둘 다 최적화 대상이 아니다.

> 주: aot-004 전 디바이스 vbat=0xFFFF(INA219 미작동 센티넬)이라 **실측 배터리는 확인 불가**. 위 수치는 데이터시트 기반 엔지니어링 추정. 용량(예: 2000 mAh 가정) 대비 현재 132 mAh/day ≈ 15일, 온디맨드 시 8 mAh/day ≈ 250일.

---

## 3. 목표

1. 배터리: Class C 24/7 → **온디맨드/윈도우 기반으로 80–94% 절감**.
2. 신뢰성: 절전(Class A) 상태에서도 **명령 누락 0에 수렴**(앱레벨 재전송으로 보장).
3. 안전성: 스케줄러 장애·디바이스 리부팅 시에도 **자동으로 절전(Class A)로 폴백**(배터리 트랩 방지).

---

## 4. 펌웨어 변경안 (차기 FW)

현행(v26.07): 부팅 Class C(`DEFAULT_CLASS_A=0`), `SETUP_DEFAULT_PERIOD_MIN=2`, 스케줄러가 한 평가주기 내 Class A로 강등 가정. **그러나 스케줄러가 꺼지면 영구 Class C.** (현장 펌웨어는 5/6/8B HB 혼재 — 버전 불일치도 정리 필요.)

1. **[핵심] 자가 폴백(self-fallback) 추가** — 조인/부팅 후 일정 시간(T_fallback, 예: 10–15분) 내 서버 CFG·다운링크를 못 받으면 **자동으로 Class A로 강등**. 스케줄러 장애가 곧 배터리 방전이 되는 현 구조의 안전망. 부팅은 빠른 초기 제어를 위해 잠깐 C 유지 가능하되, 미수신 시 반드시 A로.
2. **[핵심] 타임드 온디맨드 C** — CFG에 "C로 N분 유지 후 자동 A 복귀" 명령 추가(예: `[0xD0, mode=3, hb, ttl_min]` 확장 또는 신규 SIG). 서버가 복귀를 잊어도 디바이스가 **하드 배터리 상한**을 보장. 온디맨드 제어 세션의 핵심.
3. **부팅 기본값 재검토** — `DEFAULT_CLASS_A=1`(A로 부팅) + 제어 세션 때만 C 승격. 1·2와 결합 시 가장 안전.
4. **앱레벨 ACK 유지·강화** — 현행 FP11 ctrl_ack + FP12 status(open/close_done) 유지. 이게 서버 재전송의 정지 신호(물리 작동 증거). Class A에선 명령 수신 즉시 FP11/FP12를 다음 업링크로 송신해 서버가 빨리 확인하도록.
5. **HB 정리** — 펌웨어 버전 통일(5/6/8B 혼재 제거), ext 프레임 주기(HB_EXT_EVERY_N) 유지. HB 자체는 배터리 무관하므로 *충돌·지연* 기준으로만 설정.
6. **INA219 복구** — vbat=0xFFFF 원인(미장착/캘리브레이션) 해결. 배터리 인지형 스케줄링과 모니터링의 전제.

---

## 5. 스케줄러 변경안 (차기 class_scheduler)

현행 `lorawan_class_scheduler`는 이미 ACTIVE(C)↔REST(A)↔겨울(A) 전환 로직 보유. 문제는 **비활성 + 구형 mode_manager 9개와 혼재**.

1. **단일 권위로 통합·활성화** — 구형 per-device `lorawan_mode_manager` 9개 제거, per-site `lorawan_class_scheduler` 1개만 활성화. (현재 둘 다 off라 24/7 C의 직접 원인.)
2. **기본 REST(Class A)** — 야간·비관수 시간은 무조건 A. ACTIVE(C)는 *실제 제어가 필요한 구간*에서만.
3. **온디맨드 C 세션** — 사용자가 UI에서 제어를 시작하면 해당 사이트(또는 디바이스)를 **C로 짧게 승격(force-active N분) 후 자동 A 복귀**. 펌웨어 타임드-C(4-2)와 이중 안전. 가장 큰 절감(94%).
4. **AUTO 창 최소화** — 환경 스코어(일사/토양/강우)로 C 구간을 관수 실제 필요 시간으로 압축. 고정 MANUAL이면 창을 실제 운영시간으로 좁힘.
5. **전이 순서 보존** — C 진입: profile.supports_class_c ON → 디바이스 CFG C. C 해제: 디바이스 CFG A → profile OFF. (현행 로직 유지 — 전이 중 다운링크 유실 방지.)
6. **배터리 인지(INA219 복구 후)** — 저전압 디바이스는 C 창 단축/HB 연장.

---

## 6. 명령 신뢰성 (배터리 절전과 동시 충족)

별도 분석 결론: **ChirpStack v4.14.1은 미응답 confirmed 다운링크를 자동 재전송하지 않음**(13건 전송, 재전송 0 실측). 따라서:

1. **LoRaWAN confirmed 폐기** — 자동 재전송 없고 ACK 업링크 트래픽만 추가(반이중 게이트웨이에 불리). aot-004 출력 `confirmed`는 다음 정의된 재시작 때 되돌림.
2. **앱레벨 재전송 도입** — AoT 출력이 **FP12 status(실제 작동 증거)**를 타임아웃 내 못 받으면 명령 재발송(최대 N회, 백오프). 가장 강한 신호 기반이라 confirmed보다 우수. 이미 로컬에 구현된 출력 모듈 작업 활용:
   - 자기 DevEUI 업링크 MQTT 구독 → `ingest_uplink`
   - **vid 필터**(한 컨트롤러=여러 밸브, 형제 밸브 오염 방지)
   - `is_on` 신뢰성(in-flight 의도표시→confirmed, 실패 시 거짓전환 없음)
   - **per-DevEUI 직렬화·페이싱**(동시 다운링크 충돌 방지)
   - → 여기에 *재전송 루프* 추가.
3. **Class A에서의 명령 전달** — 명령은 디바이스의 다음 업링크(HB) RX 창에서 전달. 즉시성이 필요하면 온디맨드 C 세션으로 승격. 둘 다 앱레벨 재전송으로 누락 0 수렴.

---

## 7. 적용 순서 (마이그레이션)

1. (즉시·무코드) aot-004 `state_startup`을 `Do Nothing`으로 — 재시작마다 밸브에 close 나가는 부작용 제거. confirmed=true 원복(다음 의도된 재시작에 묶음).
2. 펌웨어: 자가폴백 + 타임드-C + 부팅 A + INA219 복구 + 버전 통일.
3. 스케줄러: mode_manager 제거 → class_scheduler 단일 활성, 기본 REST, 온디맨드 C, AUTO 창 압축.
4. AoT 출력: confirmed 폐기 + 앱레벨 재전송(로컬 모듈 작업 배포).
5. 검증: event_up(FP12)/event_tx_ack로 명령 작동률, node_class 추이로 C 점유시간, (INA219 복구 후) vbat 추이로 실측 절감 확인.

---

## 8. 결정 필요 사항

- 부팅 클래스: A 기본(안전) vs C 잠깐 후 폴백(초기 제어성) — 권장: **A 기본 + 온디맨드 C**.
- 온디맨드 C 세션 길이(N분)와 자동복귀 TTL.
- REST/ACTIVE HB 주기(배터리 무관, 지연·충돌 기준): 권장 ACTIVE 10분 / REST 30–60분.
- AUTO vs MANUAL 창, 관수 운영시간 정의.
- 앱레벨 재전송 정책: 타임아웃·최대 횟수·백오프.

---

## 부록: 검증 근거(2026-06-29)
- 11:30–13:30 실데이터: 전송 67 vs ctrl_ack 60(≈10% 양방향 RF 유실), event_log 오류 0, 큐 병목 없음. → 누락은 PHY 유실 + 재전송 부재.
- confirmed 실증: FPort1 더미 confirmed → 1초 내 LoRaWAN ACK(밸브 무동작). 단 13건 startup confirmed에서 재전송 0 → 자동 재전송 없음 확인.
- 19:49(MANUAL 종료 후)에도 전 디바이스 class=C → 스케줄러 비활성으로 24/7 C 확정.
- 관련 메모리: [[project_aot004_valve_command_loss]], [[project_chirpstack_output_uplink_confirm]], [[project_chirpstack_aot004_classc]], [[project_rak3172_valve_controller]].
