# AoT AI 에이전트 가이드 (한국어)

AoT MCP 서버를 통해 AI 에이전트가 온실 환경제어 시스템을 관찰·진단·제어하는 방법을 설명합니다.

---

## 1. 개요

AoT MCP 서버는 **FastMCP** 기반으로, Claude Desktop 등 MCP 클라이언트에서 다음 도구들을 제공합니다.

| 분류 | 도구 | 설명 |
|------|------|------|
| 관찰 | `list_facilities` | 등록된 시설 목록 |
| 관찰 | `get_facility_state` | 현재 T / RH / VPD / CO₂ / 광량 |
| 관찰 | `get_sensor_history` | 센서 시계열 (1h / 24h / 7d) |
| 관찰 | `list_functions` | 활성 Function 목록 |
| 관찰 | `get_function_state` | env_coordinator 사이클 상태 |
| 관찰 | `list_methods` | Method(설정 곡선) 목록 |
| 관찰 | `list_outputs` | 액추에이터 현재 명령값 |
| 관찰 | `get_recent_events` | 최근 MCP 감사 로그 |
| 진단 | `analyze_control_performance` | VPD 추종 RMSE · 진동 분석 |
| 진단 | `detect_sensor_anomaly` | 센서 이상치 · 드리프트 |
| 진단 | `suggest_setpoint_adjustment` | VPD 목표 권장값 (제안만) |
| 진단 | `compare_periods` | 두 기간 통계 비교 |
| 제어 | `set_vpd_target` | VPD 목표 변경 (**승인 필요**) |
| 제어 | `update_method_point` | 곡선 제어점 수정 (**승인 필요**) |
| 제어 | `request_manual_lock` | AI 자동제어 일시 정지 (**승인 필요**) |
| 제어 | `acknowledge_alert` | 경보 확인 (**승인 필요**) |
| 흐름 | `confirm_action` | 대기 중인 쓰기 승인 |
| 흐름 | `reject_action` | 대기 중인 쓰기 거부 |
| 흐름 | `get_pending_actions` | 승인 대기 목록 |
| 정보 | `get_system_manifest` | 시스템 도메인·정책 정보 |

---

## 2. 안전 정책

### 2.1 쓰기 기본 비활성화

모든 제어 도구는 기본적으로 **비활성화** 상태입니다. 활성화 방법:

```bash
# 환경 변수로 활성화
AOT_MCP_WRITE_ENABLED=1 python -m aot.mcp_server.server

# CLI 플래그로 활성화
python -m aot.mcp_server.server --write
```

### 2.2 3계층 안전 장치

1. **Layer 1 — 권한**: 읽기 도구는 제한 없음. 쓰기 도구는 전역 플래그로 차단.
2. **Layer 2 — 값 검증**: 범위·변화량·시간당 호출 횟수 제한.
3. **Layer 3 — 사용자 승인**: 쓰기 도구는 반드시 60초 TTL 토큰으로 사용자 승인 후 실행.

### 2.3 쓰기 도구 제한표

| 도구 | 값 범위 | 1회 최대 변화량 | 시간당 최대 호출 |
|------|---------|----------------|----------------|
| `set_vpd_target` | 0.3 ~ 2.5 kPa | 0.5 kPa | 5회 |
| `update_method_point` | 0.0 ~ 3.0 kPa | 0.3 kPa | 10회 |
| `request_manual_lock` | 1 ~ 120분 | — | 3회 |
| `acknowledge_alert` | — | — | 20회 |

### 2.4 시드 프리셋 보호

이름이 `SEED:` 로 시작하는 Method는 읽기 전용입니다.
수정이 필요하면 반드시 복제 후 편집하세요.

---

## 3. 권장 워크플로

### 이상 감지 → 조정

```
1. list_facilities
   → 시설 unique_id 확인

2. get_facility_state(facility_id)
   → 현재 VPD / T / RH / CO₂ 확인
   → sensors_health = 'stale' 이면 센서 점검 먼저

3. analyze_control_performance(function_id, window='1h')
   → vpd_rmse, oscillation_index, assessment 확인

4. detect_sensor_anomaly(device_id, measurement_id)
   → verdict: 'anomaly_detected' / 'drift_detected' / 'normal'

5. suggest_setpoint_adjustment(facility_id)
   → suggested_target, reason 확인

6. (사용자 승인 후)
   set_vpd_target(function_id, value=suggested_target, reason=reason)
   → 반환: {'pending': True, 'token_id': '...', 'expires_in': 60}

7. confirm_action(token_id='...', user_id='operator')
   → 실제 적용
```

### 제어 흐름 예시

```python
# 1. VPD 목표 변경 요청
result = set_vpd_target(
    function_id='abc-123',
    value=1.2,
    reason='VPD 너무 낮음, 증산 촉진 필요'
)
# → {'pending': True, 'token_id': 'xxx-yyy', 'expires_in': 60, ...}

# 2. 사용자가 UI 또는 confirm_action 으로 승인
result = confirm_action(token_id='xxx-yyy', user_id='operator')
# → {'ok': True, 'tool_name': 'set_vpd_target', 'result': {...}}
```

---

## 4. 도메인 지식

### VPD (Vapor Pressure Deficit)

VPD = SVP × (1 − RH/100)  
SVP = 0.6108 × exp(17.27T / (T + 237.3)) [kPa]

| 범위 | 상태 | 권장 작물 단계 |
|------|------|--------------|
| < 0.4 kPa | 너무 낮음 — 증산 억제, 곰팡이 위험 | — |
| 0.4 ~ 0.8 kPa | 적정 (유묘기) | 발아·정식 초기 |
| 0.8 ~ 1.2 kPa | 적정 (영양생장기) | 성장기 |
| 1.2 ~ 1.8 kPa | 적정 (생식생장기) | 개화·착과기 |
| > 1.8 kPa | 너무 높음 — 수분 스트레스 위험 | — |

### 제어 3계층 (env_coordinator)

- **L1 EnvTarget**: Method 곡선 또는 고정값에서 VPD/CO₂ 목표 읽기
- **L2 SituationReport**: 편차·제한인자·추세 평가
- **L3 Coordinator**: PI + 슬루율 + 적분 와인드업 방지 → 액추에이터 명령

### 분석 판정 기준

`analyze_control_performance` 반환값:

| assessment | 의미 | 조치 |
|-----------|------|------|
| `excellent` | RMSE < 0.1 kPa | 유지 |
| `good` | RMSE 0.1 ~ 0.2 kPa | 모니터링 |
| `oscillating` | 부호 변환 > 30% | tolerance_vpd ↑ 또는 주기 연장 |
| `poor_tracking` | RMSE ≥ 0.2 kPa | 제한인자 확인, K 캘리브레이션 검토 |

---

## 5. Claude Desktop 설정

`~/.config/claude/config.json` (macOS: `~/Library/Application Support/Claude/config.json`):

```json
{
  "mcpServers": {
    "aot": {
      "command": "python",
      "args": ["-m", "aot.mcp_server.server"],
      "cwd": "/path/to/AoT_ai",
      "env": {
        "AOT_MCP_WRITE_ENABLED": "1",
        "AOT_MCP_AGENT_ID": "claude"
      }
    }
  }
}
```

쓰기 기능이 필요 없으면 `AOT_MCP_WRITE_ENABLED` 를 제거하거나 `0` 으로 설정하세요.

---

## 6. 금지 사항

AI 에이전트는 다음 작업을 수행해서는 안 됩니다.

- 안전 게이트 (강풍/폭우/온도 한계) 비활성화
- 시드 프리셋 (`SEED:*`) 직접 수정
- 액추에이터 하드웨어 한계 초과 명령
- 사용자 승인 없이 쓰기 도구 실행
- VPD를 1회에 0.5 kPa 이상 변경

---

## 7. 자주 하는 실수

| 증상 | 원인 | 해결 |
|------|------|------|
| `WriteDisabled` 오류 | 쓰기 비활성화 상태 | `AOT_MCP_WRITE_ENABLED=1` 설정 |
| `seed_protected` 오류 | SEED 프리셋 수정 시도 | Method 복제 후 편집 |
| `sensors_health: stale` | ext_context 만료 | 센서 연결 및 ext_context_collector 확인 |
| 토큰 만료 | 60초 내 미승인 | 다시 도구 호출 후 즉시 승인 |
| `rate_limit` 오류 | 시간당 호출 초과 | 다음 시간대 재시도 |
