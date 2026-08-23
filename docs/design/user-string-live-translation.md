# 사용자 지정 문자열 실시간 번역 (User String Live Translation)

상태: 구현 완료 · 로컬 실증 완료 · 미커밋/미배포 · 2026-08-23

구현 파일
: 모델 `aot/databases/models/user_string_translation.py` ·
  마이그레이션 `alembic_db/alembic/versions/p6_53_user_string_translation_20260823.py` ·
  서비스 `aot/ai/services/user_string_translator.py` ·
  라우트 `aot/aot_flask/routes_locale_api.py`(사전·번역 요청),
  `aot/aot_flask/routes_settings.py`(사전 관리) ·
  치환기 `aot/aot_flask/static/js/common/aot-user-i18n.js` ·
  관리 화면 `aot/aot_flask/templates/settings/translations.html` ·
  주기 잡 `aot/ai/services/ai_scheduler_service.py::_user_string_translation_job` ·
  역방향 `aot/ai/services/aot_data_tool_service.py::_with_translated_alias` ·
  테스트 `aot/tests/test_user_string_translator.py`,
  `aot/tests/test_user_string_translation_routes.py`

## 1. 문제

AoT 는 18개 언어(`aot/config/__init__.py:262` `LANGUAGES`, 카탈로그는 23개 로케일)로
UI 를 제공한다. 그러나 번역되는 것은 **개발자가 소스에 넣은 문구**뿐이다.
gettext 카탈로그(`aot/aot_flask/translations/`)에 없는 것 — 즉 **사용자가 직접 지은
이름** — 은 DB 에 저장된 원문 그대로 모든 언어에서 노출된다.

예: 한국어로 구축한 농장을 일본어 계정으로 열면

```
温度                        ← 시스템 문구: 번역됨
1번 하우스 동편 상단 온습도  ← 사용자 지정 이름: 한국어 그대로
```

한 화면에 두 언어가 섞인다. 다국어 출시 제품에서 이건 "부분 번역"이 아니라
**해당 언어 사용자에게는 읽을 수 없는 화면**이다.

## 2. 목표와 비목표

### 목표
- 사용자가 선택한 언어로 화면을 열면, 사용자 지정 이름도 그 언어로 보인다.
- 브라우저 번역기처럼 동작한다 — 페이지는 즉시 뜨고, 번역은 도착하는 대로 반영된다.
- 원문/번역 전환이 한 번의 토글로 가능하다.
- 번역이 없거나 실패해도 화면은 원문으로 정상 동작한다(기능 영향 0).

### 비목표
- DB 의 이름 자체를 다국어 컬럼으로 바꾸지 않는다. 원문이 유일한 정본이다.
- 사용자가 이름을 입력·수정하는 폼은 번역하지 않는다(3.2 참조 — 최우선 안전 조건).
- 1단계에서 장문(노트 본문, 공지 내용)은 대상이 아니다(Phase 6).

## 3. 설계 원칙

1. **원문이 정본.** 번역본은 표시 레이어의 캐시일 뿐, `Input.name` 등 원본 컬럼은
   읽기만 한다. 어떤 경로로도 번역본이 DB 에 다시 써져서는 안 된다.
2. **이중 번역 금지.** 시스템 문구는 이미 gettext 로 번역되어 있다. 번역 대상은
   "DB 에서 온 사용자 문자열"로 명시적으로 한정한다.
3. **결정적·안정적.** 같은 원문은 항상 같은 번역. 사전 테이블이 정본이고, 화면마다
   LLM 을 다시 부르지 않는다. 이름은 유한하고 거의 변하지 않으므로 최초 1회 번역 후
   영구 캐시가 성립한다.
4. **조용한 실패.** 미번역 = 원문 표시. 엔진 없음 = 기능 자동 비활성.
5. **모델 불가지.** 특정 모델을 하드코딩하지 않는다. 사용자가 등록한 AI 엔트리 중
   하나를 번역용으로 지정하며, 미지정 시 기본 라우팅을 따른다.
6. **AI 를 안 쓰는 사용자 기준.** 이 기능은 옵션이며, 꺼져 있어도 지금과 동일하게
   동작해야 한다.

## 4. 아키텍처

세 층으로 나눈다.

```
[3층] 표시    브라우저: 사전 주입 → DOM 치환 → MutationObserver → 원문/번역 토글
                 ↑ GET  /api/v1/locale/user_strings.js?lang=ja&v=<지문>
                 ↓ POST /api/v1/locale/user_strings/translate  (미스 실시간 요청)
[2층] 서비스  UserStringTranslator: lookup(캐시) / request(큐) / 배치 워커(LLM 1회 N건)
[1층] 저장소  user_string_translation 테이블 (원문 해시 × 대상 언어 → 번역본)
```

### 4.1 1층 — 번역 사전 저장소

새 모델 `aot/databases/models/user_string_translation.py`,
alembic 리비전 1개(`alembic_db/alembic/versions/`).

| 컬럼 | 설명 |
|---|---|
| `source_hash` | 정규화된 원문의 sha1(앞 16자). 인덱스 |
| `source_text` | 원문 그대로 |
| `source_lang` | 감지된 원어(`ko`/`ja`/… , 미상은 `auto`) |
| `target_lang` | 대상 언어 |
| `translated_text` | 번역본. pending 이면 NULL |
| `domain` | `device`/`zone`/`crop`/`function`/`dashboard`/`note_title` … 프롬프트 힌트 |
| `status` | `pending` / `done` / `failed` / `skipped` |
| `is_locked` | 사용자가 손으로 고친 값. 재번역이 덮지 않음 |
| `engine` | 번역에 쓴 엔진/모델(감사용). `skipped` 행에서는 제외 사유를 담는다 |
| `fail_count` | 연속 실패 횟수. `MAX_FAIL_COUNT`(3) 를 넘기면 더 시도하지 않는다 |
| `created_at` / `updated_at` | |

유니크 제약: `(source_hash, target_lang)`.

정규화는 `strip()` + 연속 공백 축약까지만. 대소문자·문장부호는 보존한다(이름의
정체성이다).

### 4.2 2층 — 번역 서비스와 배치 워커

`aot/ai/services/user_string_translator.py`

- `collect_source_strings()` — 번역 대상 문자열을 DB 에서 모은다. 대상 필드 목록은 코드에
  선언적 레지스트리로 둔다(모델·컬럼·domain 3튜플). 초기 대상:

  | 모델 | 필드 | domain |
  |---|---|---|
  | `Input` / `Output` / `PID` / `Function`(CustomController 계열) | `name` | device / function |
  | `DeviceMeasurements` | `name` | measurement |
  | `Dashboard` / `Widget` | `name` | dashboard |
  | `GeoMap` / `GeoLayer` / `GeoShape` / `GeoFacility` / `GeoAsset` | `name` | zone |
  | `GeoPlot` | `name`, `subject`, `variety` | crop |
  | `GeoProgram` | `name` | program |
  | `Method` / `Camera` / `Tab` | `name` | misc |
  | `Notes` | `title` | note_title |
  | `Notice` | `title` | notice |

  **제외(번역 금지)**: `User.name`(사람 이름), `APIKey.name`·`UserAPIKey`(자격증명 라벨),
  `MCPServer.name`, `Role.name`(권한 식별자), 파일명·경로, DevEUI/UUID/MAC/IP 형태 문자열.

- `is_structurally_translatable(text)` + `collides_with_catalog(text, lang)` — 2자 미만,
  숫자/기호만, 식별자 패턴, 현재 언어 gettext 카탈로그와 충돌하는 문자열(§4.4), 그리고
  이미 대상 언어인 문자열은 `skipped` 로 기록하고 영구히 건너뛴다. 사유는 `engine`
  컬럼에 남는다(`identifier` / `catalog_collision` / `same_language` …).
- `lookup(texts, target_lang) -> dict` — 캐시 조회 전용. LLM 호출 없음. 요청 경로에서
  쓰는 유일한 함수.
- `enqueue(items, target_lang)` — 미스를 `pending` 으로 적재. `sync_sources(lang)` 이
  전체 수집 + 적재를 한 번에 한다.
- `run_batch(target_lang, limit=20)` — pending 을 (언어, 도메인)별로 묶어 묶음당 LLM
  1회 호출. **응답이 쓸 수 없으면 묶음을 절반씩 쪼개 다시 시도한다** — 모델의 출력
  한도를 우리는 모르고, 한도에 걸려 잘린 응답은 개수가 안 맞아 통째로 버려지기
  때문이다(실측: gemini-2.5-flash 에서 40개 묶음이 11번째에서 잘렸다). 데몬 스케줄러에 15분 주기 잡
  (`_user_string_translation_job`)으로 등록되며, 계정 언어로 실제 쓰이는 언어만 채운다.
- `translate_now(texts, target_lang)` — 화면에 보이는 미스를 즉시 번역하는 경로
  (§4.3). 캐시 히트는 바로 돌려주고, 미스는 일일 상한 안에서 동기 번역한다.
- `reverse_lookup(text)` — 번역본 → 원문 (§4.7).

엔진 응답은 믿지 않는다. JSON 배열이 아니거나 **개수가 입력과 다르면 통째로 버린다**
— 하나라도 밀리면 이름이 서로 뒤바뀐 채 영구 캐시되기 때문이다.

프롬프트 요지(엔진 무관):

> 농업 자동화 시스템에서 사용자가 직접 지은 명칭 목록이다. `{src}` → `{dst}` 로 번역하라.
> 고유명사·브랜드·모델명·숫자·기호·단위는 원형 보존. 화면 라벨이므로 짧게.
> 설명·주석 없이 입력과 같은 길이의 JSON 배열로만 응답.

용어 일관성 보강: `AIDomainGlossary`(`aot/databases/models/ai_domain_glossary.py`)의
활성 용어와 `aot/ai/context/ext_translation_table.py` 의 작물·생육단계 정적 표를
프롬프트에 용어집으로 주입한다. 작물명처럼 이미 정답 표가 있는 것은 LLM 을 거치지 않고
표에서 바로 채운다.

원어 감지: 유니코드 스크립트 휴리스틱(한글/가나/한자/키릴/타이/라틴)으로 1차 판정하고,
라틴처럼 모호하면 `auto` 로 두고 LLM 에 감지를 위임한다.

비용 가드: 문자열당 최대 길이, 하루 최대 번역 건수, pending 큐 상한. 초과분은 원문 유지.

### 4.3 3층 — 표시(치환)

**사전 배포.** 기존 `routes_locale_api.get_js_translations`(`aot/aot_flask/routes_locale_api.py:25`)
와 같은 패턴으로 `/locale/user_strings.js?lang=<로케일>&v=<지문>` 을 추가한다.

```js
window.AOT_USER_I18N = { "1번 하우스": "1号ハウス", "동편 밸브": "東側バルブ", ... };
window.AOT_USER_I18N_PENDING = ["새로 만든 구역"];   // 아직 번역 없음
```

지문 `v` 는 사전의 `count` + `max(updated_at)` 해시다(`catalog_fingerprint()`,
컨텍스트 프로세서가 60초 캐시). `Cache-Control: private, max-age=300` +
`Vary: Cookie, Accept-Language` 는 기존 카탈로그 라우트의 교훈을 그대로 따른다
(엣지 캐시가 옛 언어를 물고 있던 사고 이력).

**`layout_default.html` 이 원본이다.** `layout.html` 은 서버 재시작 때 그 파일에서
자동 생성되므로, 배선은 반드시 양쪽에 같이 넣는다.

**클라이언트.** `aot/aot_flask/static/js/common/aot-user-i18n.js` 신설,
`layout.html` 의 카탈로그 스크립트 바로 뒤(225행 부근)에 배선.

1. 로드 즉시 `document.body` 를 1회 스캔한다. 텍스트 노드와 `title` /
   `placeholder` / `aria-label` / `data-original-title` 속성이 대상.
2. **완전 일치 치환이 기본이다.** 텍스트 노드 전체(trim 후)가 사전 키와 같을 때만 바꾼다.
   부분 문자열 치환은 오탐 위험이 커서 기본 비활성이며, 필요한 화면은 §4.5 의 마킹으로
   해결한다.
3. 되돌리기용으로 (노드, 원문) 기록을 들고 있는다. 텍스트 노드에는 속성을 달 수 없어
   DOM 안에 원문을 보관할 수 없기 때문이다. 처리한 노드는 `WeakSet` 으로 표시해 다시
   훑지 않는다 — 폴링 위젯이 잦은 화면에서 특히 중요하고, `A→B`, `B→C` 같은 사전에서
   연쇄 치환이 일어나지 않게 막는 장치이기도 하다.
4. `MutationObserver` 로 이후 삽입되는 노드를 같은 규칙으로 처리한다. 대시보드 위젯
   폴링·지도 팝업·AI 채팅 응답이 여기에 해당한다. 배치는 **타이머(16ms)** 로 미룬다 —
   `requestAnimationFrame` 은 숨은 탭에서 멈추므로, 대시보드를 여러 탭에 열어 두면 큐가
   하루 종일 쌓였다가 탭을 전환하는 순간 한꺼번에 처리되어 원문이 한 프레임 비친다
   (하네스로 재현 확인, §8).
5. 상단 바에 **원문/번역 토글**을 둔다. 브라우저 번역기의 "원문 보기"와 같은 역할이며,
   상태는 localStorage 에 남긴다.

**미스의 실시간 처리 — 이 기능이 "실시간"인 지점.**
스캔 중 `AOT_USER_I18N_PENDING` 에 있는 문자열을 실제로 만나면, 그 문자열만 모아
`POST /api/v1/user_i18n/translate {texts, lang}` 로 요청한다(300ms 디바운스, 배치).
서버는 캐시 히트를 즉시 돌려주고 미스는 소량 동기 번역하거나 pending 으로 응답한다.
번역이 도착하면 사전을 갱신하고 해당 노드만 다시 치환한다. 즉 **화면에 실제로 보이는
것만, 보이는 순간에 번역한다.**

### 4.4 오탐·이중번역 가드

- 사전 키가 현재 로케일 gettext 카탈로그의 msgid 또는 msgstr 과 충돌하면 사전에서
  제외한다. (사용자가 출력 이름을 "Pump" 나 "온도"로 지은 경우 UI 문구까지 오염되는 것을 막는다.)
- 2자 미만, 숫자/기호만인 문자열 제외.
- `<script>`, `<style>`, `<code>`, `<pre>`, `.no-translate`, `[data-no-translate]` 하위 제외.
- 원문과 번역이 같으면 치환하지 않는다(무의미한 DOM 변경 방지).

### 4.5 편집 폼 — 최우선 안전 조건

**`input` / `textarea` / `select` 의 값은 절대 번역하지 않는다.**
장치 설정 모달의 이름 칸에 번역본이 들어간 채로 사용자가 저장하면, DB 의 원문이
번역본으로 덮여 **원본이 영구 소실**된다. 이건 되돌릴 수 없는 데이터 파괴다.

- 클라이언트 치환기는 폼 컨트롤과 `contenteditable` 을 구조적으로 제외한다.
- 회귀 테스트를 고정한다: 번역 표시 상태에서 장치/구역/함수 설정을 저장한 뒤
  DB 의 `name` 이 원문 그대로인지 확인한다. 이 테스트는 매 릴리스 점검 항목에 넣는다.

### 4.6 마킹 승격 (미구현 — 필요해지면)

완전 일치로 덮지 못하는 자리가 있다. `1번 하우스 온도` 처럼 서버가 이름과 시스템
문구를 이어 붙인 라벨은 텍스트 노드 전체가 사전 키와 다르므로 그대로 남는다(하네스
확인). 그런 자리는 렌더 지점에서 명시적으로 감싸는 편이 낫다.

```jinja
{{ u(each_input.name) }}   →   <span class="u-str" data-src="1번 하우스">1번 하우스</span>
```

지금은 넣지 않았다 — 사전 기반 치환이 대부분을 덮고, 이어 붙인 라벨이 실제로 얼마나
거슬리는지는 써 봐야 알기 때문이다. 필요해지면 Jinja 필터를
`aot/aot_flask/app.py` 의 `template_filter` 등록부에 추가하고 신규·수정 코드부터
점진 적용한다. 기존 124개 출력 지점을 한꺼번에 고칠 이유는 없다.

### 4.7 역방향 — AI 가 번역된 이름을 알아듣게

사용자가 일본어 화면을 보며 "1号ハウスの温度は?" 라고 물으면 `resolve_target` /
`search_devices` 는 DB 의 "1번 하우스"를 못 찾는다.

번역 사전을 **별칭 인덱스**로 재사용한다. 원문 매칭 실패 시
`user_string_translation.translated_text` 를 역조회해 원문을 얻고, 그것으로 엔티티를
찾는다. 두 곳에 걸었다.

- `_resolve_note_target()` — `_with_translated_alias` 데코레이터로 감쌌다. **원문
  매칭을 먼저** 하고, 실패했을 때만 역조회로 재시도한다. 저장된 이름으로 부른 것을
  번역명으로 오인해 엉뚱한 엔티티로 보내면 안 되기 때문이다.
- `search_devices()` — 검색어의 원문을 검색 토큰에 더한다(기존 별칭 확장과 같은 자리).

둘 다 `aot/ai/services/aot_data_tool_service.py`.

반대 방향(AI 응답에 원문 이름이 등장)은 3층 클라이언트 치환이 AI 채팅 DOM 에도 적용되므로
자동으로 해결된다.

## 5. 설정과 관리 화면

세 겹이다. 위로 갈수록 가볍고 되돌리기 쉽다.

- **원문/번역 토글**(네비바 > 관리) — 지금 이 브라우저에서만, 즉시. 브라우저 번역기의
  "원문 보기"와 같은 역할이고 상태는 localStorage 에 남는다. 서버를 거치지 않는다.
- **계정별 토글**(사용자 설정 모달) — `User.translate_user_strings`. 끄면 사전 자체를
  내려받지 않는다. NULL(미지정)은 켬으로 읽는다. 전역이 꺼져 있으면 모달에 칸이 없고,
  그 상태의 저장이 값을 덮지 않는다 — 나중에 전역을 켰을 때 사용자가 끈 적도 없이
  꺼진 채 남는 것을 막는다.
- **전역 스위치**(설정 > 일반 > AI Service) — `AIGlobalSettings.user_string_translation_enabled`.
  `ai_enabled` 가 꺼져 있으면 함께 꺼진 것으로 본다(LLM 이 필요하므로).
  번역 엔진(`user_string_translation_agent_id`)과 일일 상한
  (`user_string_translation_daily_limit`, 기본 500)은 컬럼만 두고 UI 를 두지 않았다 —
  자동 선택과 기본값으로 충분하고, "결정된 값은 내장한다".

**번역 사전 관리 화면** — `/settings/translations`(설정 메뉴 > 이름 번역). 언어·상태로
거른 목록에서 번역을 그 자리에서 고치면 `is_locked` 가 붙어 이후 재번역이 덮지 않는다.
"지금 번역"은 주기 잡을 기다리지 않고 수집+한 배치를 즉시 돌린다. "전체 다시 번역"은
손대지 않은 행만 초기화한다. 원문 칸은 읽기 전용이다 — 여기서 고칠 수 있으면 그게 곧
원문 파괴 경로가 된다.

## 6. 성능

- 사전 크기: 이름은 보통 수백 개 규모라 수십 KB. 커지면 페이지 스코프 사전으로 분할한다
  (현재 화면이 참조하는 엔티티만 내려주기).
- 초기 스캔은 1회, 이후는 MutationObserver 증분. 위젯 폴링이 잦은 대시보드에서
  실측하고, LOW 하드웨어 프로파일(`aot/config/feature_flags.py`)에서는 기본 비활성을
  검토한다.
- LLM 호출은 최초 1회뿐이고 이후 영구 캐시다. 정상 운용 시 추가 비용은 0 에 수렴한다.

## 7. 단계 — 진행 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| P1 | 모델 + alembic(p6_52) + `UserStringTranslator` + 스킵 규칙 + 단위 테스트 | 완료 |
| P2 | 사전 라우트 + `aot-user-i18n.js` + 가드 + 원문/번역 토글 + layout 배선 | 완료 |
| P3 | 실시간 미스 요청 API + 도착 시 재치환 | 완료 |
| P4 | 사전 관리 화면 + 수동 오버라이드 + 3단 설정 토글 | 완료 |
| P5 | AI 리졸버 역방향 별칭(`_resolve_note_target` · `search_devices`) | 완료 |
| P6 | 장문(노트 본문·공지 내용·설명) 확장 — 길이·비용 정책 별도 | 미착수 |
| — | §4.6 마킹 승격 — 이어 붙인 라벨 대응 | 보류(필요 시) |

배포 전에 남은 것은 §8 의 1·2·4 — **실제 앱에서의 확인**이다. 로컬 docker 는 메인
워크트리를 마운트하므로 이 브랜치가 반영되지 않아 여기서 하지 못했다.

## 8. 검증

로컬 docker(`docker-compose.yml`, `aot_local`)에서만 한다. 라이브 DB 금지.

### 끝난 것

- **자동 테스트 70건** (`test_user_string_translator.py` 50 ·
  `test_user_string_translation_routes.py` 20). 전체 스위트 2,908건 회귀 없음.
  - 정규화·해시·스크립트 감지·식별자 스킵·카탈로그 충돌·엔진 응답 검증
  - 적재 → 조회 → 사전 생성 왕복, `skipped` 가 브라우저까지 새지 않는 것
  - **번역이 `Input.name` 을 건드리지 않는 것**(제1 원칙)
  - 기능 off / 계정 opt-out 시 사전이 비는 것, 백엔드 예외에도 200 + 빈 사전
  - 손으로 고친 행이 일괄 재번역에서 살아남는 것, 쓰기 라우트 권한
  - 전역이 꺼진 상태의 계정 저장이 사용자 선택을 덮지 않는 것
- **브라우저 하네스 실증** (치환기를 실제 DOM 에 태움)
  - 표시 텍스트·`title` 속성 번역, 앞뒤 공백 보존
  - **편집 폼 전부 원문 유지** — `input.value` / `textarea` / `<option>` /
    `placeholder` / `contenteditable`
  - 제외 영역(`data-no-translate` · `.no-translate` · `<code>`) 원문 유지
  - 동적 삽입 노드 번역(MutationObserver), 그 안의 `input` 은 원문 유지
  - pending 문자열이 화면에 나타난 순간 서버 요청 1회 → 도착 후 치환
  - 원문/번역 토글 왕복(텍스트·속성 모두 복원)
  - `A→B`, `B→C` 사전에서 연쇄 치환이 일어나지 않음
  - 5,000 노드 스캔 16ms
  - **숨은 탭에서 rAF 가 멈춰 동적 노드가 번역되지 않는 결함을 여기서 잡았다**
    (타이머로 교체, §4.3)

### 로컬 앱 실증 (2026-08-23)

로컬 docker 스택의 마운트를 이 워크트리로 돌려 확인했다(메인 워크트리의 브랜치는
건드리지 않았다). 확인 후 마운트·alembic 스탬프·설정을 모두 원복했다.

- 실 데이터에서 **370개** 사용자 문자열 수집 — device 87 · zone 85 · crop 57 ·
  measurement 41 · dashboard 28 · note_title 26 · misc 22 · function 15 · notice 5 ·
  program 4.
- 가드가 **43개**를 배제: `catalog_collision` 22(`Spacer` `Name` `Wind` `Setpoint`
  `VPD` `RSSI` `SNR` `PID` `温度` `湿度` …), `no_letters` 11, `too_short` 8,
  `same_language` 2. 시스템 문구와 겹치는 이름이 실제로 그만큼 있었다.
- **실제 LLM(Gemini) 번역 품질** — `온습도_7`→`温湿度_7`(번호 보존),
  `토양온습도_5`→`土壌温湿度_5`, `펌프`→`ポンプ`, 지명 `구례`→`求礼` `김제`→`金堤`
  `나주`→`羅州` `여주`→`驪州` `영양`→`英陽`, 장치 코드 `v121`→`v121`(원형 보존).
- 화면(일본어 계정, 대시보드) — 사전 68개 중 **19개가 실제로 번역되어 보이고,
  원문이 남은 것은 0개**.
- **출력 설정 화면의 폼 필드 40개 중 오염 0개.** 화면에는 `金堤` 로 보이는 자리의
  입력칸 값은 `김제` 원문 그대로였다. (실제 저장 버튼은 누르지 않았다 — Output 저장은
  실제 장치 명령을 유발하고 과거 RPC 타임아웃 이력이 있다. 폼 값이 원문임을 확인한
  것으로 저장 결과도 원문임이 따라온다.)
- 관리 화면 렌더, 오역 수정 → `is_locked` 저장 → 사전 즉시 반영(`1구역`→`第1区域`).
- 네비바 토글 왕복, 설정 화면·사용자 모달 토글 배치·번역 확인.
- **역방향** — `求礼` → site "구례", `v液肥` → 장치 `v액비` 2건. 원문으로 부른 것과
  같은 결과.
- 기능 off 상태에서 사전은 `{}` + `LANG=null`.

### 실증에서 잡은 결함 둘

1. **숨은 탭에서 동적 노드가 번역되지 않았다** — `requestAnimationFrame` 이 멈추기
   때문. 대시보드를 여러 탭에 열어 두는 사용 방식에서 큐가 쌓였다가 탭 전환 순간
   원문이 비친다. 타이머로 교체(§4.3).
2. **40개 묶음의 응답이 출력 한도에서 잘려 통째로 버려졌다** — 배치를 20으로 낮추고,
   실패 시 절반씩 쪼개 재시도하도록 고쳤다(§4.2).

### 아직 안 한 것

- 대시보드 위젯 폴링 상태에서 MutationObserver 장시간 부하 실측(라즈베리파이 등
  저사양). 하네스에서 5,000노드 16ms 는 확인했다.
- ko 외 다른 원어(영어로 이름을 지은 설치)에서의 번역 품질.
- 실제 저장 버튼을 통한 저장 왕복(위 참조 — 장치 명령 위험으로 보류).

## 9. 위험

| 위험 | 영향 | 대응 |
|---|---|---|
| 편집 폼 오염으로 원문 소실 | 치명(복구 불가) | 폼 구조적 제외(하네스 확인) + 소스 수준 회귀 테스트 + 저장 왕복 점검 |
| 시스템 문구 이중번역 | 중 | 카탈로그 충돌 키를 `skipped` 로 배제 |
| 엔진 응답이 밀려 이름이 뒤바뀜 | 중(영구 캐시) | 개수·타입 불일치 시 통째로 폐기 |
| 오역(농업 은어·관용 표현) | 중 | 용어집 주입 + 관리 화면 수동 수정(`is_locked`) |
| LLM 비용·지연 | 중 | 영구 캐시 + 배치 + 일일 상한 + 보이는 것만 번역 |
| MutationObserver 성능(저사양) | 중 | 처리 노드 `WeakSet` 스킵, 5,000노드 16ms 실측, 라즈베리파이 실측은 남음 |
| 오프라인·AI 미사용 환경 | 하 | `ai_enabled` 연동 자동 비활성, 원문 폴백 |

## 10. 검토했으나 채택하지 않은 대안

- **DB 다국어 컬럼(`name_ko`, `name_ja` …)** — 언어 추가마다 스키마 변경, 기존 코드 전면
  수정, 사용자가 언어 수만큼 이름을 입력해야 함. 원문 정본 원칙에도 어긋난다.
- **브라우저 내장 번역 API(Chrome Translator API)** — 지원 브라우저가 제한적이고
  온디바이스 모델 다운로드가 필요하며, 서버가 결과를 알 수 없어 캐시·일관성·역방향 별칭
  (§4.7)을 만들 수 없다. 사용자가 브라우저 번역을 켜면 시스템 문구까지 이중 번역된다.
- **전 페이지 서버측 치환(SSR only)** — 첫 페인트에 깜빡임이 없다는 장점은 있으나,
  124개 이상의 출력 지점을 모두 고쳐야 하고 JS 로 그리는 위젯·지도·AI 응답을 덮지 못한다.
  §4.6 의 마킹으로 필요한 곳만 보강하는 편이 낫다.
