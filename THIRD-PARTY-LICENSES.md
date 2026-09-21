# 서드파티 라이선스 고지

AoT 는 GPLv3 로 배포되며(`LICENSE.txt`), 오픈소스 [Mycodo](https://github.com/kizniche/Mycodo)
프로젝트의 파생 저작물입니다. 그 이중 저작권 표기는 `LICENSE.txt` 맨 앞에 있습니다.

이 문서는 **AoT 와 함께 배포되는 타사 저작물**을 한자리에 모은 것입니다.
각 파일의 헤더 주석이 정본이고, 이 표는 그 색인입니다 — 표와 파일 헤더가
다르면 파일 헤더가 맞습니다.

**이 문서가 다루지 않는 것**: 개발·빌드 도구(`node_modules`, 테스트 의존성)는
배포물에 포함되지 않으므로 여기 없습니다. AI 지식 라이브러리가 조회하는 **공개
데이터의 출처 표시**는 성격이 달라 따로 있습니다 — [자료 출처](docs/ai/overview.ko.md#data-credits).

---

## 1. 저장소에 포함된 브라우저 자산

`aot/aot_flask/static/` 아래에 원본 그대로 들어 있는 파일들입니다.

| 라이브러리 | 버전 | 라이선스 | 경로 |
|---|---|---|---|
| jQuery | 3.4.1 | MIT | `js/vendor/jquery-3.4.1.min.js` |
| jQuery UI Touch Punch | — | MIT / GPL 이중 | `js/vendor/jquery.ui.touch-punch.min.js` |
| Bootstrap | 4.6.0 | MIT | `js/vendor/bootstrap.min.js` |
| ClockPicker | 0.0.7 | MIT | `js/vendor/bootstrap-clockpicker.min.js` |
| Popper.js | 2017 판 | MIT | `js/vendor/popper.min.js` |
| Moment.js | 2.17.1 | MIT | `js/vendor/moment.min.js` |
| daterangepicker | 2012–2016 판 | MIT | `js/vendor/daterangepicker.js` |
| multiselect | 2.5.5 | MIT | `js/vendor/multiselect.min.js` |
| toastr | 2.1.3 | MIT | `js/vendor/toastr.min.js` |
| GridStack.js | 10.1.1 | MIT | `js/vendor/gridstack-all.js`, `css/gridstack.css` |
| Font Awesome Free | 5.11.2 | 아이콘 CC BY 4.0 · 폰트 SIL OFL 1.1 · 코드 MIT | `vendor/fontawesome-5.11.2/`, `js/vendor/fontawesome-all.min.js` |
| DataTables 번들 | DataTables 2.2.2, RowGroup 1.5.1, Scroller 2.4.3, Select 3.0.0 | MIT | `js/vendor/datatables_2_2_2/datatables.min.js` |
| FullCalendar | 5.11.5 | MIT | `vendor/fullcalendar-5.11.5/` |
| vis-timeline | 7.7.3 | Apache-2.0 OR MIT | `vendor/vis-timeline-7.7.3/` |
| three.js GLTFExporter (**로컬 자립 빌드**, 아래 참고) | r155 | MIT | `js/widgets/AoT_facility/three-gltf-exporter.js` |
| MapLibre GL JS | 4.1.2 | BSD 3-Clause | `vendor/maplibre-gl-4.1.2/` |
| Apache ECharts (**맞춤 빌드**, 아래 참고) — zrender · d3.js 일부 · tslib 포함 | 6.1.0 (zrender 6.1.0, tslib 2.3.0) | Apache-2.0 (zrender·d3 부분 BSD 3-Clause, tslib 0BSD) | `js/vendor/echarts-6.1.0/` |
| Turf.js | 번들에 표기 없음 | MIT | `js/common/turf.min.js` |
| three.js | 2023 판 (**로컬 수정본**, 아래 참고) | MIT | `js/widgets/AoT_facility/three.min.js` |
| three-mesh-bvh | 번들에 표기 없음 | MIT | `js/widgets/AoT_facility/three-mesh-bvh.js` |

### 확인해 둘 것

**Apache ECharts 는 필요한 부분만 담은 맞춤 빌드입니다.** 그래프를 그립니다.
2026-09-21 까지 쓰던 Highcharts(비상업 용도로만 무료인 상용 라이선스)를 이것으로 바꿨고,
Highcharts 파일은 저장소에서 뺐습니다. 배포판 전체 대신 AoT 가 쓰는 차트(선·막대·산점·게이지)와
컴포넌트만 esbuild 로 묶었고, 담은 목록은 파일 머리말에 있습니다. 같은 폴더에
ECharts 의 `LICENSE`·`NOTICE`, 빌드에 함께 들어가는 zrender 의 `LICENSE-zrender`,
ECharts 안에 들어 있는 d3.js 코드의 `LICENSE-d3` 를 두었습니다. 다시 만드는 방법은
`js/tools/build_echarts_vendor.mjs` 에 있고, 같은 입력이면 같은 파일이
나옵니다. 화면이 싣는 배포 번들(`js/dist/echarts-stack.bundle.js`)은 다른 번들처럼
압축하면서 주석을 지우므로, 라이선스 머리말과 고지 전문은 위 폴더에 있습니다.

**`three-gltf-exporter.js` 는 AoT 가 만든 자립 빌드입니다.** three.js 예제의
`GLTFExporter` 를 esbuild 로 묶되, three 본체는 다시 번들하지 않고 이미 로드된
전역(`window.THREE`)에서 필요한 이름만 되내보내는 심을 끼웠습니다(32KB). 원래는
CDN 에서 그 모듈을 직접 import 했는데, 그 모듈이 bare specifier `'three'` 를
쓰고 이 앱에 import map 이 없어 **한 번도 동작한 적이 없었습니다.** 재생성
방법은 파일 헤더에 적혀 있습니다.

**three.js 는 로컬 수정본입니다.** 콘솔 경고를 없애고 WebGL1 을 강제하는 패치가
적용돼 있습니다. MIT 는 수정을 허용하지만 저작권 고지 유지를 요구하므로 헤더를
그대로 두었습니다. 다시 vendoring 하면 이 패치를 재적용해야 합니다.

**`gridstack-all.js` 는 첫 줄에서 `gridstack-all.js.LICENSE.txt` 를 가리키는데
그 파일이 저장소에 없습니다.** webpack 이 만들어 주는 사이드카를 vendoring 할 때
가져오지 않은 것입니다. GridStack 의 라이선스는 위 표에 적어 두었지만, 다시
vendoring 할 때는 그 파일도 함께 가져오십시오.

---

## 2. 배포 번들에 컴파일되는 npm 패키지

`static/js/dist/`, `static/js/geo/dist/`, `static/apps/notes-widget/` 의 빌드
산출물에 코드가 그대로 포함됩니다.

| 패키지 | 버전 | 라이선스 | 쓰이는 곳 |
|---|---|---|---|
| maplibre-gl | 5.23.0 | BSD 3-Clause | 지도 |
| @mapbox/mapbox-gl-draw | 1.5.1 | ISC | 지도 도형 편집 |
| terra-draw | 1.28.8 | MIT | 지도 도형 편집 |
| react · react-dom | 19.2.x | MIT | 노트 위젯 |
| @tanstack/react-query | 5.90.x | MIT | 노트 위젯 |
| axios | 1.13.x | MIT | 노트 위젯 |
| date-fns | 4.1.0 | MIT | 노트 위젯 |
| classnames | 2.5.1 | MIT | 노트 위젯 |
| lucide-react | 0.562.x | ISC | 노트 위젯 |
| react-zoom-pan-pinch | 3.7.0 | MIT | 노트 위젯 |

---

## 3. Python 의존성

`install/requirements.txt` 에 선언되며 설치 시 PyPI 에서 받습니다. **저장소가
재배포하지 않으므로** 여기에 전량을 옮겨 적지 않습니다 — 목록이 바뀔 때마다
어긋나기만 합니다. 설치된 환경에서 언제든 정확한 목록을 뽑을 수 있습니다.

```bash
pip-licenses --format=markdown --with-urls
```

2026-08-25 기준 111개 패키지이며 MIT 43 · BSD 21 · Apache 10 이 대부분입니다.
분류자만 훑으면 걸리는 두 건은 확인해 두었습니다.

- **`pillow_heif`** — 분류자에 GPLv2 가 붙어 있지만 패키지의 `License` 필드는
  **BSD-3-Clause** 입니다. 상류의 분류자 오기이며 GPLv3 과 충돌하지 않습니다.
- **`pylint`** — **GPL-2.0-or-later** 입니다. "or later" 이므로 GPLv3 조건으로
  쓸 수 있어 역시 충돌하지 않습니다.

---

## 4. 자료(데이터) 출처

AI 지식 라이브러리가 조회하는 공개 데이터는 코드가 아니라 **자료**이고, 표시할
때 출처를 밝히는 방식으로 준수합니다. 현재 CC BY 4.0 두 곳이며 화면과 AI 답변
양쪽에 표기가 나갑니다 — [자료 출처](docs/ai/overview.ko.md#data-credits) 참고.

---

## 갱신하는 법

새 라이브러리를 vendoring 하거나 번들 의존성을 더하면 이 표에 함께 적으십시오.
표의 근거는 각 파일의 헤더 주석과 패키지 메타데이터이며, 추측으로 채우지
마십시오 — 버전을 못 찾으면 "번들에 표기 없음" 이라고 적는 편이 틀린 숫자를
적는 것보다 낫습니다.
