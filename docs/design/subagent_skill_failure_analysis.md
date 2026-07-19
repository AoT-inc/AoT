# 서브에이전트·스킬 세션별 오작동 원인 분석

작성일: 2026-06-10
조사 범위: `~/.claude/settings.json`, `~/.claude/hooks/`, `~/.claude/plugins/`,
프로젝트 `.claude/`, 현재 세션 환경변수

## 결론 (TL;DR)

세션마다 서브에이전트와 스킬이 깨지는 근본 원인은 **전역 `~/.claude/settings.json`이
모든 모델 호출을 MiniMax-M2.7로 강제 치환**하고 있기 때문이다. 여기에
**커스텀 에이전트/스킬 디렉터리가 아예 존재하지 않는 점**, **Foreman 거버넌스 훅의
구조적 버그**가 겹쳐 있다.

## 원인 1 — 모델 라우팅 오염 (핵심 원인)

`~/.claude/settings.json`:

```json
"env": {
  "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
  "ANTHROPIC_AUTH_TOKEN": "sk-cp-...(MiniMax 키)",
  "ANTHROPIC_MODEL": "MiniMax-M2.7",
  "ANTHROPIC_SMALL_FAST_MODEL": "MiniMax-M2.7",
  "ANTHROPIC_DEFAULT_SONNET_MODEL": "MiniMax-M2.7",
  "ANTHROPIC_DEFAULT_OPUS_MODEL": "MiniMax-M2.7",
  "ANTHROPIC_DEFAULT_HAIKU_MODEL": "MiniMax-M2.7"
},
"model": "MiniMax-M2.7"
```

영향:

1. **CLI에서 시작한 세션**: 모든 트래픽(메인 + 서브에이전트 + 스킬 실행)이
   MiniMax 프록시로 간다. MiniMax-M2.7은 Claude Code의 에이전트 하니스
   (Skill 트리거 프로토콜, Agent/Task 도구 스폰, StructuredOutput, 긴 tool-use
   루프)를 Claude만큼 충실히 따르지 못해 스킬이 발동하지 않거나 서브에이전트가
   중간에 죽는 형태로 나타난다.
2. **Desktop 앱에서 시작한 세션**: 실측 환경변수 기준 `ANTHROPIC_BASE_URL`은
   `https://api.anthropic.com`으로 덮이지만, `ANTHROPIC_MODEL=MiniMax-M2.7` 등
   모델 치환 변수와 **MiniMax용 AUTH_TOKEN은 그대로 주입**된다. 서브에이전트가
   sonnet/haiku 별칭을 해석하면 `MiniMax-M2.7`이라는 존재하지 않는 모델명이
   Anthropic API로 전송되어 model-not-found / 인증 오류로 실패한다.
   → "세션마다(=어디서 띄우든) 깨진다"는 증상과 정확히 일치하는 혼합 오염 상태.

부수 위험: 전역 settings.json에 **API 키가 평문으로 저장**되어 있다.

## 원인 2 — 커스텀 에이전트/스킬이 설치되어 있지 않음

확인 결과 아래 경로가 전부 존재하지 않는다:

- `~/.claude/agents/`, `~/.claude/skills/`
- `AoT_ai/.claude/agents/`, `AoT_ai/.claude/skills/`

즉 Foreman T0–T3 같은 커스텀 서브에이전트나 프로젝트 전용 스킬은 Claude Code
입장에서 정의된 적이 없다. Foreman 기능은 전부 MCP 서버(`mcp__foreman__*`)를
통해서만 노출되며, MCP 서버가 연결 지연/실패하는 세션에서는 해당 기능이 통째로
사라진다(이번 세션에서도 시작 시점에 MCP_DOCKER, MiniMax 서버가 "connecting"
상태였음). 사용 가능한 스킬은 내장 스킬 + `anthropic-skills` 플러그인뿐이다.

## 원인 3 — Foreman 거버넌스 훅의 구조적 버그

`~/.claude/hooks/enforce_search_first.sh` (PreToolUse, `Glob|Read` 매칭):

1. **의도**: `FOREMAN_WORKER=1` 세션에서 `search_index.py` 실행 전 Read/Glob을
   exit 2로 차단.
2. **버그**: transcript를 `json.load()`로 파싱하는데 Claude Code transcript는
   **JSONL** 형식이라 파싱이 항상 실패 → "error" → fail-open. 즉 거버넌스는
   사실상 무력화된 no-op 상태다(차단 원인은 아니지만 설계 의도대로 동작 안 함).
3. **잠재 위험**: 파싱이 성공하는 환경이라면 서브에이전트의 모든 Read/Glob이
   차단되어 서브에이전트가 파일을 전혀 못 읽게 된다. 훅은 서브에이전트에도
   동일하게 적용되기 때문.

## 보조 요인

- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`: 일부 부가 기능(텔레메트리,
  업데이트 체크 등) 차단. 스킬/에이전트 코어 동작과는 무관하나 진단 시 혼선 가능.
- `defaultMode: "bypassPermissions"` + `skipDangerousModePermissionPrompt`:
  오작동 원인은 아니지만 위 모델 오염과 결합 시 비-Claude 모델이 무제한 권한으로
  실행되는 위험한 조합.

## 권장 조치

1. `~/.claude/settings.json`에서 `env`의 ANTHROPIC_* 7개 변수와 `"model"` 키 제거
   (MiniMax를 쓰려면 별도 프로필/셸 래퍼로 분리, 전역 settings에 넣지 말 것).
2. API 키를 settings.json에서 제거하고 키 관리 도구 또는 환경 분리로 이전.
3. Foreman T0–T3를 서브에이전트로 쓸 거면 `~/.claude/agents/*.md` 또는
   프로젝트 `.claude/agents/*.md`로 실제 정의 파일 생성.
4. `enforce_search_first.sh`의 transcript 파서를 JSONL(line-by-line) 파싱으로 수정.
5. 조치 후 새 세션에서 `/agents`, `/skills`(또는 Skill 목록)과 서브에이전트 스폰을
   재검증.
