# 위젯 UI 텍스트 톤앤매너 통일 — 설계 계획서

> ⚠ **이 문서는 2026-06-06 시점의 계획이며, 일부는 다르게 구현됐다.**
> 후속·정본: [widget-uiux-unification-plan.md](widget-uiux-unification-plan.md)
>
> 특히 아래 "결정 사항" 중 두 가지는 **채택되지 않았다.**
> - *사용자 `font_em_*` 옵션을 배수로 보존* → 실제 구현된
>   `aot-widget-typography.css` 는 **고정 크기**를 택했고, 그 결과 위젯 설정의
>   "Font Size (em)" 칸은 25종 중 하나만 읽는 죽은 노브로 3개월을 남아 있었다.
>   2026-09-06 에 그 칸을 없앴다(WP6a).
> - *clamp 기반 유동 스케일* → 대신 루트 글자 크기를 손가락 화면에서 115% 로
>   키우는 방식을 택했다([typography-scale.md](typography-scale.md)).
>
> 사다리 자체도 2026-09-06 에 한 벌 6단으로 합쳤다 — 아래 본문의
> "5단계 존재" 같은 서술은 그 이전 상태다.

상태: 부분 시행 (2026-06-06 작성 · 2026-09-06 후속 문서로 승계)
작성: 2026-06-06
범위: `aot/widgets/*.py`, `aot/aot_flask/static/js/widgets/**`, 위젯 관련 CSS
결정 사항(당시): 전역 타이포그래피 토큰 도입 + 의미 기반 클래스 통일 / 모바일 우선(clamp 기반 유동 스케일) / 사용자 `font_em_*` 옵션은 배수(multiplier)로 보존

---

## 1. 목표

위젯마다 제각각인 텍스트 스타일(폰트 크기·굵기·색)을 전역 토큰과 의미 기반 클래스로 통일하여
톤앤매너를 일관되게 유지하고, 동시에 모바일 화면에서 가독성이 최적화되도록 개선한다.

요구 사항 정리:

1. 모든 위젯 텍스트가 동일한 타이포그래피 스케일·색 토큰을 따른다.
2. 인라인 하드코딩(`font-size:25px`, `font-size:0.78rem` 등) 제거 → 의미 기반 클래스로 대체.
3. 모바일 화면(좁은 그리드 셀)에서 값/단위/레이블이 잘리거나 과대·과소 표시되지 않는다.
4. 사용자가 위젯별로 조절하는 `font_em_*` 옵션은 기능 유지(토큰 위에 배수로 곱셈).
5. 라이트/다크 테마 모두에서 텍스트 대비가 유지된다.

---

## 2. 현황 진단 (감사 결과)

### 2.1 이미 존재하는 자산 (재사용 대상)

| 자산 | 위치 | 상태 |
|------|------|------|
| 폰트 크기 스케일 | `aot-theme-variables.css:189-193` | `--aot-font-size-xs/sm/base/lg/xl` 5단계 존재. **위젯에서 거의 미사용** |
| 폰트 패밀리 | `aot-theme-variables.css:187-188` | `--aot-font-family`, `--aot-font-mono` 존재 |
| 텍스트 색 토큰 | `aot-theme-variables.css:47-49, 243-284` | `--aot-color-text-primary/secondary/tertiary`, `--text-color-*`, `--aot-text-main/title/secondary` 존재 |
| 의미 기반 클래스 | `widget_measurement.py:143,153` | `widget-measurement-value/unit`, `widget-title-bar` 등 일부 위젯만 보유 |
| 사용자 배수 옵션 | `widget_measurement.py:74-90` | `font_em_value/unit/timestamp` (em 배수) |

### 2.2 문제점 — 스타일 산재 현황

폰트 크기 단위가 위젯마다 px / rem / em / vw로 혼재하며, 같은 역할(값·단위·레이블)인데 값이 다르다.

- Python 위젯: `font-size: 0.75rem`, `0.875rem`, `0.78rem`, `25px`, `12px`, `1.2em`, `0.72em` … 20여 종 (`AoT_advice.py`, `widget_gauge_solid.py`, `widget_trigger_sequence.py`, `AoT_PID.py` 등).
- JS 위젯: `12px`, `11px`, `0.78rem`, `1.4em`, `1.6rem`, `${baseSize}` … 별도 산재 (`AoT_facility/`, `AoT_map/`).
- 폰트 굵기: `600`, `bold`, `500`, `400`, `700` 혼용 (정규화된 토큰 없음).
- **워스트 오펜더**: `widget_trigger_sequence.py`(em 6종), `AoT_advice.py`(rem 7종), `widget_ai_insight.py`(em 4종), `AoT_PID.py`(em 4종), `widget_gauge_solid.py`(px 직접).

### 2.3 결함 토큰 (신규 필요)

- 폰트 **굵기** 토큰 없음 → `--aot-fw-*` 신설 필요.
- **라인 높이 / 자간** 토큰 없음.
- 모바일 유동 스케일 없음 → 위젯 CSS에 `clamp()`/`@media` 거의 부재(`dashboard.css`에 일반 레이아웃용 2개뿐).
- 폰트 크기 스케일이 5단계뿐 → 위젯 값(대형 숫자)·캡션(타임스탬프)까지 커버하려면 단계 확장 필요.

---

## 3. 설계

### 3.1 전역 타이포그래피 토큰 (1차 산출물)

`aot-theme-variables.css` `:root`에 추가/확장. 모바일 우선 `clamp(min, 유동, max)` 기반.

```css
/* ── 폰트 크기 스케일 (clamp: 모바일 min → 데스크톱 max) ── */
--aot-fs-caption: clamp(0.65rem, 1.6vw, 0.75rem);  /* 타임스탬프, 보조 라벨 */
--aot-fs-label:   clamp(0.72rem, 1.9vw, 0.85rem);  /* 필드 레이블 */
--aot-fs-body:    clamp(0.80rem, 2.2vw, 0.95rem);  /* 본문 기본 */
--aot-fs-unit:    clamp(0.85rem, 2.4vw, 1.05rem);  /* 단위 */
--aot-fs-title:   clamp(0.90rem, 2.6vw, 1.15rem);  /* 위젯 제목 바 */
--aot-fs-value:   clamp(1.30rem, 6.0vw, 2.40rem);  /* 측정값 등 강조 숫자 */
--aot-fs-value-lg:clamp(1.80rem, 9.0vw, 3.60rem);  /* 게이지 중앙 대형 숫자 */

/* ── 폰트 굵기 ── */
--aot-fw-regular: 400;
--aot-fw-medium:  500;
--aot-fw-semibold:600;
--aot-fw-bold:    700;

/* ── 라인 높이 / 자간 ── */
--aot-lh-tight: 1.1;   /* 대형 숫자 */
--aot-lh-base:  1.45;  /* 본문 */
--aot-ls-tight: -0.01em;
```

기존 `--aot-font-size-xs/sm/base/lg/xl`은 **하위호환 별칭**으로 새 토큰에 매핑하여 즉시 깨지지 않게 한다.

### 3.2 의미 기반 위젯 텍스트 클래스 (2차 산출물)

신규 파일 `aot/aot_flask/static/css/widget/aot-widget-typography.css`에 역할별 클래스 정의.
모든 위젯이 인라인 스타일 대신 이 클래스를 참조한다.

```css
.aot-w-title  { font-size: var(--aot-fs-title);  font-weight: var(--aot-fw-semibold);
                color: var(--aot-text-title); line-height: var(--aot-lh-base); }
.aot-w-label  { font-size: var(--aot-fs-label);  font-weight: var(--aot-fw-medium);
                color: var(--aot-text-secondary); }
.aot-w-value  { font-size: var(--aot-fs-value);  font-weight: var(--aot-fw-bold);
                color: var(--aot-text-main); line-height: var(--aot-lh-tight);
                letter-spacing: var(--aot-ls-tight); font-variant-numeric: tabular-nums; }
.aot-w-unit   { font-size: var(--aot-fs-unit);   font-weight: var(--aot-fw-medium);
                color: var(--aot-text-secondary); }
.aot-w-caption{ font-size: var(--aot-fs-caption);font-weight: var(--aot-fw-regular);
                color: var(--aot-text-secondary); }
```

`tabular-nums`로 숫자 폭을 고정해 실시간 값 갱신 시 흔들림을 막는다.

### 3.3 사용자 `font_em_*` 옵션 보존

토큰을 base로 두고 사용자 배수를 곱셈으로 적용 (옵션 기능 유지).

```html
<span class="aot-w-value" style="font-size: calc(var(--aot-fs-value) * {{widget_options['font_em_value']}});">
```

`font_em_*`이 1이면 토큰 그대로, 사용자가 키우면 토큰 대비 배수로 확대. 인라인은 `calc(토큰 * 배수)`만 남고
색·굵기·라인높이는 클래스가 담당 → 산재 제거 + 사용자 제어 양립.

### 3.4 모바일 특화

- 모든 크기 토큰을 `clamp()`로 정의 → 그리드 셀 폭에 따라 유동.
- 컨테이너 기준 스케일이 더 정확한 위젯(게이지·시설)은 `cqw`(container query) 도입 검토:
  `@container (max-width: 220px) { .aot-w-value { font-size: clamp(1rem, 14cqw, 2rem); } }`.
- 좁은 화면에서 값/단위 줄바꿈 방지: `.aot-w-value`에 `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`.
- 터치 타깃: 텍스트가 버튼 역할일 때 최소 높이 44px 보장(별도 버튼 토큰과 연계).

---

## 4. 적용 순서 (단계별, 원자적 패치)

| 단계 | 작업 | 파일 | 검증 |
|------|------|------|------|
| P1 | 타이포 토큰 추가(3.1) + 기존 토큰 별칭 매핑 | `aot-theme-variables.css` | 토큰 정의 후 기존 화면 무변화 확인 |
| P2 | 의미 클래스 CSS 신설(3.2) + layout에 로드 | `css/widget/aot-widget-typography.css`, `layout_default.html` | 클래스 단독 렌더 확인 |
| P3 | 측정 계열 위젯 전환 | `widget_measurement.py`, `widget_measurement_multi.py`, `widget_indicator.py` | 값/단위/타임스탬프 정상 + `font_em_*` 동작 |
| P4 | 게이지·그래프 위젯 전환 | `widget_gauge_solid.py`, `widget_gauge_angular.py`, `widget_graph_synchronous.py` | 대형 숫자 clamp 동작 |
| P5 | 복합 위젯 전환 (워스트 오펜더) | `widget_trigger_sequence.py`, `AoT_advice.py`, `AoT_PID.py`, `widget_ai_insight.py`, `AoT_facility.py` | em 산재 제거 |
| P6 | JS 위젯 전환 | `js/widgets/AoT_facility/**`, `js/widgets/AoT_map/**` | 인라인 → 클래스/CSS var |
| P7 | 회귀 점검 | 모바일/데스크톱·라이트/다크 | 위젯별 스냅샷 비교 |

각 단계는 독립 배포 가능(P1·P2가 깔리면 이후 위젯은 점진 전환). 한 번에 전 위젯 재작성하지 않는다.

---

## 5. 리스크 / 주의

- `layout.html`은 시작 시 `layout_default.html`로 덮어써짐 → CSS 로드 추가는 **`layout_default.html`** 에 한다.
- `clamp()`의 `vw` 기준은 뷰포트라서 큰 화면의 작은 위젯에선 과대해질 수 있음 → 게이지·시설 위젯은 container query(`cqw`) 병행 권장(P4·P5에서 판단).
- 사용자 저장 옵션 `font_em_*` 의미(절대 em → 토큰 배수)가 바뀌므로, 기본값 1 기준으로 기존 사용자 설정이 시각적으로 유사하도록 토큰 max 값을 현행 평균에 맞춰 보정.
- 다크 테마 대비: `--aot-text-*`가 이미 테마 분기되어 있으므로 색은 토큰만 참조하면 자동 대응.

---

## 6. 이번 단계 산출물

이 문서(계획)만. 구현(P1~P7)은 승인 후 단계별 진행.
