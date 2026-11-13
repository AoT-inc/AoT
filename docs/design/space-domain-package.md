# 공간 도메인 패키지 `aot/space/` — DB 세션에 묶인 모듈 옮기기 (아키텍처 4단계 설계)

상태: A안 승인 (2026-11-09). 4a 진행 중.
앞 단계: 3단계에서 Flask·DB 세션에 기대지 않는 공간 계산 7개와 시설 ↔ 코디네이터 연결 판정을 `aot/space/` 로 옮겼다. 옛 경로 `aot.aot_flask.geo.<이름>` 은 별칭으로 남아 있다.

## 1. 풀려는 문제

데몬(환경 코디네이터, 위성 분석)·트윈·서비스·도구가 공간 판정(장치가 어느 구역에 속하나, 장치 위치, 구획 문맥)을 쓰려면 지금은 `aot.aot_flask.geo` 를 import 해야 한다. 그러면 웹 패키지가 통째로 딸려 오고, `daemon-no-flask` baseline 에 geo 몫이 남는다.

웹 밖에서 많이 쓰는 모듈은 다음과 같다(테스트 제외 import 수, 26-11-08 실측).

| 모듈 | 줄 수 | 웹 밖 import |
|---|---|---|
| `device_membership` | 1,690 | 54 + 패키지 경유 35 |
| `device_binding` | 1,571 | 20 + 41 |
| `plot_context` | 3,083 | 5 + 48 |
| `facility_sensors` | 1,757 | 11 |
| `facility_integration` | 830 | 7 |
| `device_location` | 497 | 6 |
| `forecast_series` | 1,147 | 패키지 경유 17 |
| `plot_geometry` | 777 | 4 |
| `device_kind` | 64 | 5 |

3단계 측정 결과, 이 모듈들은 함수 안 지연 import 까지 따라가면 서로 얽혀 있다. 예를 들어 `facility_integration ↔ facility_sensors` 는 서로를 부르고, `device_kind` 는 `device_binding` 을 부른다. 그래서 한 덩어리로 옮겨야 한다.

## 2. 진짜 뿌리 — 모델 층이 웹 패키지 위에 서 있다

`aot/databases/__init__.py` 는 `from aot.aot_flask.extensions import db` 와 `from flask import current_app` 로 시작한다. 모든 모델이 웹 패키지에 있는 `SQLAlchemy()` 객체 위에 정의되어 있다. 그래서 공간 모듈을 `aot/space/` 로 옮겨도 모델을 import 하는 순간 `aot.aot_flask` 가 올라온다. 3단계의 7개는 모델을 맨 위에서 import 하지 않아서 이 문제를 피했다.

`db` 를 import 하는 파일은 230개다(테스트 제외). 이 숫자를 바꾸는 것이 목적이 아니다. **`db` 객체가 사는 자리**를 옮기는 것이 목적이다.

## 3. "세션을 누가 주는가" — 세 안

지금 세션을 쓰는 방식은 이렇다.

- 웹은 요청 컨텍스트의 `db.session` 과 `Model.query` 를 쓴다.
- 데몬도 자기 Flask 앱을 띄운다(ARCHITECTURE §4 규칙 5, `aot_daemon.py`). 공간 판정을 부를 때는 `has_app_context()` 를 확인하고 없으면 `app.app_context()` 를 연다. 지금 이렇게 하는 곳은 환경 코디네이터 믹스인 2곳, 위성 분석 1곳이다.
- 트윈은 필요할 때 앱을 지연 생성한다(`twin/gate.py`).
- 컨트롤러 코드는 `databases/utils.py` 의 `session_scope` 를 쓴다.

| 안 | 내용 | 비용 | 위험 |
|---|---|---|---|
| A. `db` 객체를 아래층으로 | `SQLAlchemy()` 를 `aot/databases/sqla.py`(가칭)에서 만든다. `aot_flask/extensions.py` 는 그것을 다시 내보낸다. 모델·공간 모듈은 `aot.databases` 에서 가져온다. 함수 본문(`Model.query`, `db.session`)은 그대로 둔다. | 작다. import 줄만 바꾸고 230개 파일은 별칭 덕에 그대로 둘 수 있다. | `flask_sqlalchemy` 는 여전히 필요하다(Flask 패키지 의존은 남는다). 앱 컨텍스트가 필요한 것도 지금과 같다. |
| B. 세션을 인자로 | 공간 함수가 `session` 을 받는다. 웹은 `db.session`, 데몬은 `session_scope()` 를 넘긴다. | 크다. 공개 함수 수백 개의 시그니처와 `Model.query` 호출을 모두 `session.query(Model)` 로 바꿔야 한다. | 동작 변경 위험이 크고 리뷰가 어렵다. 지연 로딩·캐시 동작이 달라질 수 있다. |
| C. 세션 공급자 하나 | `aot/space/_session.py` 에 `current_session()` 를 둔다. 웹·데몬이 기동할 때 공급자를 바인딩한다(`aot/tools/providers.py` 방식). | 중간. `db.session` 호출을 공급자 호출로 바꾸지만 `Model.query` 는 남는다. | 바인딩을 잊은 프로세스에서 조용히 다른 세션을 쓸 수 있다. |

### 권고: A안

- 목표는 import 방향(웹 → 공간 → 모델)이다. 세션 사용법 자체는 바꾸지 않는다. 데몬과 트윈은 이미 앱 컨텍스트 안에서 공간 판정을 부르므로, A안은 런타임 동작을 바꾸지 않는다.
- B·C는 "Flask 없이 도는 공간 도메인"이 목표일 때 필요하다. 그 목표는 이 계획의 범위가 아니다. 저사양 기기에서 Flask 없이 데몬을 띄우는 일이 생기면 그때 C안을 얹는다. A안 뒤에도 C안을 얹을 수 있다.
- A안의 범위와 한계: `flask_sqlalchemy` 의존과 앱 컨텍스트 요구는 남는다. 새 가드도 "aot.aot_flask 금지"까지만 건다. "flask 금지"는 걸 수 없다(`space-no-web` 의 `flask` 항목은 4단계에서 `flask_sqlalchemy` 를 예외로 둘지 함께 정한다).

## 4. 작업 순서 (A안)

각 단계는 PR 하나로 하고, 기능 변경은 0이다.

1. **4a — `db` 객체 내리기.**
   - `aot/databases/sqla.py` 에 `db = SQLAlchemy()` 를 둔다.
   - `aot_flask/extensions.py` 는 `from aot.databases.sqla import db` 로 다시 내보낸다.
   - `aot/databases/__init__.py` 와 모델은 `aot.databases.sqla` 에서 가져온다. `current_app` 사용처는 따로 정리한다.
   - 검증:
     - 같은 객체인지: `extensions.db is sqla.db`
     - 메타데이터가 같은지: 테이블 집합 해시
     - alembic 체인 검사, 단위 시험 전체, NAS E2E
2. **4b — 얽힌 덩어리 측정.**
   - 3단계 폐포 측정 스크립트(`.local/scratch/space_closure.py` 방식)를 금지 목록에서 `aot.databases`·`sqlalchemy` 를 빼고 다시 돌린다.
   - 9개 모듈과 그 동반 모듈 중 웹(`routes`·`app`·`utils`·`forms`·`access`)에 닿는 지연 import 를 목록으로 만든다.
   - 닿는 곳은 옮기지 않고 호출을 끊을 방법을 정한다: 인자 주입이나 위층에서 부르기. 이 목록은 A/B 두 방법(AST 폐포, 새 프로세스 import 관찰)이 일치할 때만 채택한다.
   - **결과 (26-11-09, main `6622fccb4`).** 금지 목록은 `space-no-web` 가드 그대로(`flask`·`flask_babel`·`flask_login`·`aot.aot_flask`·`aot.ai`·`aot.tools`)로 쟀다. `aot.databases`·`sqlalchemy`·`aot.config` 는 허용이다.
     - **A/B 일치.** 함수 밖 import 는 덩어리 24개 모듈 모두 A=B 다. 함수 안 import 는 덩어리 모듈을 다루는 단위 시험 87개 파일(3,224건 통과)을 관찰 훅을 켠 채 돌렸다. 관찰된 `aot.*` 간선 97개가 모두 A 목록 안에 있다(B ⊆ A). A 에만 있는 31개는 시험이 지나가지 않은 분기다. 대부분 웹에 남길 3개 모듈에서 나온다.
     - **덩어리.** 9개에서 함수 안 import 까지 따라가면 geo 모듈 24개다. 이 중 3개(`widget.maps`·`site_summary`·`device_link_status`)는 웹·AI 에 깊게 닿으므로 옮기지 않는다. 남은 21개 중 5개는 3단계에서 옮긴 별칭이다. 그래서 4c 에서 옮길 것은 **16개**다: 9개 + `containment_cache`·`shape_index`·`facility_io`·`plot_accumulation`·`plot_sources`·`program_io`·`weather_state`.
     - **끊을 곳(4c 에서 옮기기 전에).**
       - C1. `device_membership` → `widget.maps._measurement_display_name`. 이 함수는 순수 계산이다(`config_devices_units` 만 쓴다). 덩어리 쪽으로 내리고 `widget.maps` 가 그것을 가져간다.
       - C2. `forecast_series` → `site_summary.parent_site_for_shape`. 이 함수와 그 캐시(`_parent_index`·`_shape_name`·`_feature`)는 `GeoShape` 와 `geo_hierarchy` 만 쓴다. 덩어리 쪽으로 내리고 `site_summary` 가 그것을 가져간다.
       - C3. `weather_state` → `routes_geo_layer._load_gis_layer_instance`. 데몬의 예보 폴백(`forecast_series._fallback_cells`)이 이 길로 라우트 파일을 import 한다. 주입으로 끊으면 데몬 동작이 바뀌므로, 로더(`_gis_layer_def`·`_load_gis_layer_instance`)와 `utils_geo.MockInputDev`(필드 4개짜리 클래스)를 `aot/inputs_gis` 로 내린다. 옛 이름은 다시 내보낸다.
       - C4. `aot.aot_flask.extensions` 의 `db` 를 쓰는 5곳(`containment_cache`·`device_binding`·`facility_io`·`program_io`·`shape_index`)은 `aot.databases.sqla` 로 바꾼다.
     - **가드 결정.** 덩어리에는 `flask` 의 앱 컨텍스트 원시 기능(`current_app.logger`, `has_app_context`; 6개 모듈)과 `flask_babel.gettext`(`program_io`, try 로 감싼 지연 import)가 남는다. A안은 `flask_sqlalchemy` 와 앱 컨텍스트 의존을 받아들였으므로, `space-no-web` 에서 `flask`·`flask_babel` 을 빼고 `flask_login`·`aot.aot_flask`·`aot.ai`·`aot.tools` 는 그대로 금지한다. `current_app.logger` 를 모듈 로거로 바꾸면 로그가 가는 곳이 달라지므로, 기능 변경 0 원칙에 따라 4c 에서는 바꾸지 않는다.
     - 측정 스크립트: `.local/scratch/space_cluster.py`(`ast`·`run [--pytest …]`·`diff`). 저장소에는 넣지 않는다.
3. **4c — 덩어리 옮기기.**
   - **4c-1 — 끊기 (26-11-09).** 옮기기 전에 C1~C4 를 끊고 가드를 고쳤다. 기능 변경은 0이다.
     - C1: `_measurement_display_name` 정본을 `aot/space/measurement_names.py` 로 옮겼다. `widget.maps` 는 그것을 다시 가져간다.
     - C2: `parent_site_for_shape`·`_parent_index`·`_shape_name`·`_facility_of_shape`·`_feature` 를 `aot/space/site_parent.py` 로 옮겼다. `site_summary` 는 잠금(`_CACHE_LOCK`)과 부모 색인 캐시(`_PARENT_CACHE`)를 **같은 객체로** 가져간다. 그래서 `invalidate()` 는 지금처럼 같은 잠금 아래에서 그 캐시를 비운다.
     - C3: `_gis_layer_def`·`_load_gis_layer_instance`·`_GIS_LAYER_DEFS`·`MockInputDev` 를 `aot/inputs_gis/layer_instance.py` 로 옮겼다. 이 파일에는 `INPUT_INFORMATION` 이 없어서 입력 모듈 스캔이 건너뛴다. 모델 import 는 함수 안에 있다. 라우트와 `utils_geo` 는 옛 이름을 다시 내보낸다.
     - C4: 5곳의 `db` 를 `aot.databases.sqla` 에서 가져온다.
     - 가드: `space-no-web` 에서 `flask`·`flask_babel` 을 뺐다.
     - 재측정(AST): 덩어리는 21개(옮길 16개와 3단계 별칭 5개)다. `widget.maps`·`site_summary`·`device_link_status` 는 더 이상 닿지 않는다. 남은 바깥 간선은 `flask`(6개 모듈)와 `flask_babel`(`program_io`)뿐이고, 둘 다 이제 허용이다.
   - 3단계와 같은 방식이다: `git mv`, 옛 경로 별칭(같은 모듈 객체), 데몬·트윈 import 를 직접 새 경로로.
   - **4c-2 — 16개 옮기기 (26-11-09).** 4b 의 16개를 `git mv` 로 `aot/space/` 에 옮겼다. 옛 경로는 같은 모듈 객체를 돌려주는 별칭이다(`test_space_package.py` 에 동일성 시험 16개 추가).
     - 옮긴 모듈 안의 서로 간 import 와 3단계 7개로 가는 import 는 새 경로로 바꿨다.
     - 데몬·트윈 쪽(`functions/`·`twin/`·`utils/`·`inputs/`) import 도 새 경로로 바꿨다. 웹·도구·AI 쪽은 4d 에서 바꾼다.
     - `daemon-no-flask` baseline 6건이 해소됐다(22 → 16줄). 환경 코디네이터에 남은 웹 간선은 `coordinator_plot` 하나다.
     - 원본을 경로로 읽는 시험과 검사 스크립트(`check_geo_writes`·`check_device_kind_literals`)의 경로를 새 자리로 맞췄다. 트윈 시험 2곳은 가짜 `forecast_series` 를 새 경로에 끼운다.
     - 새 시험: 16개 모듈을 하나씩 새 프로세스에서 import 해도 `aot.aot_flask`·`aot.ai`·`aot.tools` 가 올라오지 않는다(순환 import 순서 확인 겸). `flask_login` 은 모델(`User`)이 올리므로 실행 시험에서는 보지 않는다. 직접 import 는 가드가 막는다.
     - 재측정(AST, 금지 = 새 가드 목록): `aot.space` 덩어리는 24개이고, 금지 모듈로 가는 간선은 이행 간선을 포함해 0이다.
     - 로거 이름이 `aot.space.<이름>` 으로 바뀐다. 핸들러는 `aot` 에 붙어 있으므로 로그가 가는 곳은 같다.
   - `aot.aot_flask.geo` 패키지 `__init__` 의 eager import 는 그대로 둔다(웹은 계속 그 경로를 쓴다).
   - 검증:
     - 별칭 동일성
     - 공개 이름 해시, URL 맵 규칙 해시
     - geo·env_control 단위 시험
     - 폐루프 A/B 20개 시나리오
     - NAS E2E
     - baseline 감소
4. **4d — 별칭 정리.**
   - 옛 경로 import 를 일괄 치환하고 별칭 파일을 삭제한다. 3단계의 7개도 포함한다.
   - 다른 세션의 geo 작업이 조용할 때 한다(병합 충돌을 줄이려고).
   - **결과 (26-11-09).** 기능 변경은 0이다.
     - `aot.aot_flask.geo.<23개>` 를 쓰던 곳을 모두 `aot.aot_flask.geo` → `aot.space` 로 바꿨다(파일 약 215개: 시험 124·웹 70·도구 13·데몬 12·스크립트 11·AI 5 등). 네 형태(`from …X import`, `from …geo import X, Y`, `import …X`, `mock.patch`·`sys.modules` 문자열)를 모두 바꿨다. 한 줄에 옮긴 이름과 웹에 남는 이름이 섞이면 두 줄로 나눴다.
     - 별칭 파일 23개를 지웠다. `aot/aot_flask/geo/__init__.py` 의 eager import 두 개(`FacilityManager`·`get_facility_integration`)는 지우지 않고 `aot.space` 에서 가져온다. 그래서 `from aot.aot_flask.geo import FacilityManager` 는 그대로 된다. 서브모듈 속성(`geo.plot_context`)은 더 이상 없다.
     - `geo_overlays` 의 상대 import(`from .device_binding`)도 새 경로로 바꿨다.
     - `aot/databases/models/geo_program.py` 의 지연 import 1곳(`program_io.fixed_target_defs`)도 `aot.space` 로 바꿨다. 함수 안 import 이고 `models-no-app` 가드의 금지 목록에 `aot.space` 는 없다. 웹 패키지를 가리키던 것보다 한 층 낮아졌다.
     - `test_space_package.py` 의 동일성 시험 23개는 "옛 경로를 import 하면 `ModuleNotFoundError`" 시험으로 바꿨다. 별칭이 되살아나 사본이 생기는 것을 막는다.
     - `test_import_layers.py` 의 판정 시험 2곳은 검사기 입력 문자열이다. 지운 이름 대신 웹에 남는 `geo.plot_io` 로 바꿨다(판정 내용은 같다).
     - 매뉴얼 장부: 함수 안 import 줄이 바뀌어 지문만 달라진 절 38개를 stamp 했다. 메인 체크아웃(같은 main)의 '오래됨' 목록과 같아진 것을 확인했다.
     - 남은 웹 간선: 환경 코디네이터의 `aot_flask.geo.coordinator_plot`(`daemon-no-flask` baseline 1줄)은 4d 범위 밖이다.

## 5. 위험과 막는 법

- **별칭이 사본을 만드는 사고(9월 P1-1b).** 별칭 파일은 `sys.modules[__name__] = 정본` 한 줄로 쓴다. 동일성 시험(`test_space_package.py`)에 이름을 추가한다.
- **실제 제어 경로.** 환경 코디네이터가 `device_binding`·`facility_integration` 을 쓴다. 4a·4c 는 폐루프 A/B 와 E2E 없이 병합하지 않는다.
- **병합 충돌.** geo 는 다른 세션이 자주 고치는 곳이다(시설 모형 S 시리즈, 장치 위치 L 시리즈). 열린 PR 이 geo 를 건드리는지 착수 전에 확인한다(26-11-08 기준 #452 `plot_context`, #198 `facility_sensors`).
- **매뉴얼 장부.** 경로가 바뀐 절만 stamp 한다. 이미 '오래됨'이던 절은 건드리지 않는다. 기준 체크아웃과 '오래됨' 목록을 비교해서 가린다.
