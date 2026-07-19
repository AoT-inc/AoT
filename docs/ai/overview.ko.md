# AI 기능 개요

AoT는 MCP(Model Context Protocol) 기반 AI 에이전트를 통해 온실·재배 시설의 환경을 관찰·진단·제어합니다. AI는 시스템을 보조하는 역할로, 모든 제어 동작은 사용자 승인 후 실행됩니다.

---

## AI 에이전트 구조 { #agents }

```
Claude / OpenAI API
        ↓
   MCP Server (FastMCP)
        ↓
   ┌────────────────────┐
   │  관찰 도구 (읽기)   │  → InfluxDB / SQLite 조회
   │  진단 도구         │  → 이상 감지, 성능 분석
   │  제어 도구 (쓰기)   │  → 사용자 승인 필요
   └────────────────────┘
        ↓
   AoT 시스템 (Daemon / Output Controller)
```

---

## 주요 도구 목록

### 관찰 (읽기 — 즉시 실행)

| 도구 | 설명 |
|------|------|
| `list_facilities` | 등록된 시설 목록 |
| `get_facility_state` | 현재 T / RH / VPD / CO₂ / 광량 |
| `get_sensor_history` | 센서 시계열 (1h / 24h / 7d) |
| `list_functions` | 활성 Function 목록 |
| `get_function_state` | env_coordinator 사이클 상태 |
| `list_methods` | Method(설정 곡선) 목록 |
| `list_outputs` | 액추에이터 현재 명령값 |
| `get_recent_events` | 최근 MCP 감사 로그 |

### 진단 (읽기 — 즉시 실행)

| 도구 | 설명 |
|------|------|
| `analyze_control_performance` | VPD 추종 RMSE·진동 분석 |
| `detect_sensor_anomaly` | 센서 이상치·드리프트 감지 |
| `suggest_setpoint_adjustment` | VPD 목표 권장값 제안 |
| `compare_periods` | 두 기간 통계 비교 |

### 제어 (쓰기 — 사용자 승인 필요)

| 도구 | 설명 | 제한 |
|------|------|------|
| `set_vpd_target` | VPD 목표값 변경 | ±0.5 kPa/회, 5회/h |
| `update_method_point` | Method 제어점 수정 | ±0.3 kPa/회, 10회/h |
| `request_manual_lock` | AI 자동제어 일시 정지 | 1~120분, 3회/h |
| `acknowledge_alert` | 경보 확인 | 20회/h |

---

## 3계층 안전 장치

### Layer 1 — 전역 쓰기 플래그

제어 도구는 기본적으로 **비활성화**됩니다. 활성화:

```bash
# 환경 변수
AOT_MCP_WRITE_ENABLED=1 python -m aot.mcp_server.server

# CLI 플래그
python -m aot.mcp_server.server --write
```

### Layer 2 — 값 범위 검증

각 제어 도구에 범위·변화량·호출 횟수 제한이 적용됩니다.

| 도구 | 값 범위 | 1회 최대 변화량 | 시간당 최대 |
|------|---------|----------------|------------|
| `set_vpd_target` | 0.3~2.5 kPa | 0.5 kPa | 5회 |
| `update_method_point` | 0.0~3.0 kPa | 0.3 kPa | 10회 |
| `request_manual_lock` | 1~120분 | — | 3회 |

### Layer 3 — 사용자 승인 토큰

쓰기 도구는 실행 즉시 적용되지 않고 60초 TTL 토큰을 반환합니다. 사용자가 `confirm_action`으로 승인해야 실제로 적용됩니다.

```
set_vpd_target(value=1.2)
    → { "pending": true, "token_id": "xxx", "expires_in": 60 }
        ↓
confirm_action(token_id="xxx", user_id="operator")
    → { "ok": true, ... }   ← 이 시점에 실제 적용
```

---

## 지식 라이브러리 (Knowledge Library) { #knowledge-library }

`AI -> 라이브러리`(`/ai/library`) 페이지에서 AI 답변의 근거가 되는 **컨텍스트 소스**를 등록합니다. 문서(PDF·텍스트), 웹 URL, REST API, 내부 쿼리를 소스로 추가할 수 있습니다.

### 지식 다이제스트 파이프라인

문서·웹 URL처럼 긴 산문형 소스는 등록 시 **한 번만** 전처리됩니다.

1. 소스를 여러 **청크(chunk)**로 분할합니다.
2. 각 청크를 LLM으로 **요약(digest) + 키워드 추출**하여 `ai_knowledge_chunk` 테이블에 캐시합니다.
3. 질의 시점에는 LLM 호출 없이 **DB 조회 + 결정론적 검색**만 수행합니다 → 답변이 빠르고 비용이 낮습니다.

각 청크는 컨텍스트 레코드와 동일한 **3단계 신뢰 파이프라인**(`system_generated` → `pending` → `user_confirmed`)을 재사용하므로, 문서형 지식도 같은 검토 UX로 승인·관리합니다.

### 멀티사이트 스코핑 (facility_id)

각 청크는 소스의 `facility_id`(사이트/시설 경계)를 함께 저장합니다. 지식 검색은 이 값으로 필터링됩니다.

- **사이트 A에 업로드한 문서는 사이트 B의 답변에 절대 노출되지 않습니다.**
- `facility_id` 없이 검색하면 라이브러리 지식이 **모두 제외**됩니다(교차-사이트 유출을 막기 위한 의도된 동작이며, 단순 무필터가 아닙니다).

이 스코핑은 여러 시설을 한 시스템에서 운영할 때 각 시설의 매뉴얼·재배 지침이 서로 섞이지 않도록 보장합니다.

---

## MCP 서버 실행

```bash
# 읽기 전용 (기본)
python -m aot.mcp_server.server

# 쓰기 활성화
AOT_MCP_WRITE_ENABLED=1 python -m aot.mcp_server.server --write
```

Claude Desktop에서 연결하려면 `claude_desktop_config.json`에 추가합니다:

```json
{
  "mcpServers": {
    "aot": {
      "command": "python",
      "args": ["-m", "aot.mcp_server.server"],
      "env": {
        "AOT_MCP_WRITE_ENABLED": "1"
      }
    }
  }
}
```

---

## 관련 페이지

- [환경 제어 자동화](env-control.md)
- [AI 가이드 (전체)](../ai_guide.ko.md)
