# static/js — 구조 규칙

정적 JS 자산의 디렉터리 규칙. 새 파일은 아래 분류에 맞춰 둘 것.

## 빌드

이 디렉터리는 빌드 오케스트레이터(`package.json`)를 가진다. 일부 JS는 빌드 산출물이다.
```bash
npm run install:all   # 최초 1회 (geo + apps/notes-widget 의존성)
npm run build         # 전체 빌드
npm run build:geo     # geo 번들만 (rollup → geo/dist/)
```
- `geo/` — rollup 번들(`src/index.js` 엔트리 → `geo/dist/aot-geo-all.bundle.js`). **번들 직접 편집 금지, `src/` 수정 후 재빌드.**
- `notes/` — `apps/notes-widget`(Vite) 산출물.
- 빌드/배포 절차 상세는 루트 `CLAUDE.md`의 "JS 빌드/배포" 절 참조.

| 디렉터리 | 용도 | 판단 기준 |
|----------|------|-----------|
| `vendor/` | 서드파티 라이브러리 | AoT가 작성하지 않음(미니파이/버전 박힌 이름). **절대 수정 금지.** jquery, bootstrap*, popper, moment, gridstack, toastr, daterangepicker, multiselect, fontawesome, clockpicker, `vendor/user_js/`(highcharts), `vendor/datatables_2_2_2/` |
| `common/` | 1st-party 비-UI 공용 유틸 | 여러 곳에서 쓰는 헬퍼(시간/TZ/라벨 등). `aot-time-utils`, `aot-tz`, `sensor-label`, `aot-chart-core`(Highcharts 공용: 전역 기본값·다중 y축 단위 배치·모바일 축 숨김·스크롤 redraw 가드) |
| `components/` | 1st-party 재사용 UI 부품 | 특정 위젯/페이지에 종속되지 않는 UI 블록(`aot-*`). 피커·탭·스위치·`aot-time-wheel` 등 |
| `widgets/` | 대시보드 위젯 전용 JS | 특정 위젯에만 쓰임. 위젯명 하위폴더(`widgets/AoT_facility/…`) |
| `app/` | 앱 진입 스크립트 | 페이지 부트스트랩. `dashboard.js`, `tab_management.js`, `api_key_manager.js` |
| `geo/` `map/` `ai/` `location/` `notes/` | 페이지/도메인 모듈 | 특정 페이지·대형 도메인에 묶인 코드 |

## 파일명 규칙
- 1st-party 파일은 `aot-` 접두 + kebab-case (`aot-time-wheel.js`).

## 참조 무결성 체크
정적 자산을 옮기거나 이름을 바꾼 뒤에는 반드시 실행:

```bash
python3 aot/scripts/check_static_refs.py
```

`templates/`, `widgets/*.py`, 생성된 `user_templates/`에서 `/static/js|css/…` 및
`url_for('static', filename='…')` 참조를 스캔해 디스크에 파일이 존재하는지 검증한다.
종료코드 0 = 정상, 1 = 깨진 참조 존재.

## 알려진 선결 이슈
- `vendor/user_js/solid-gauge-9.1.2.js` — **파일 자체가 레포에 없음**(`widget_gauge_solid`가 참조).
  Highcharts solid-gauge 모듈을 받아 `vendor/user_js/`에 넣어야 위젯이 정상 동작. (미해결)

해소 완료: highcharts-more/highstock 버전 누락 참조, `asset_library.js` 경로 오류 →
올바른 파일로 교정. `lib/`(미참조 사장 코드) 제거.
