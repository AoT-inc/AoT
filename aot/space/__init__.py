# coding=utf-8
"""공간 도메인 — 시설·구획·관수의 계산과, 지도를 DB 세션으로 읽는 공간 서비스
(장치 배치·바인딩, 구획 맥락, 시설 센서·통합, 장치 위치, 예보 계열, 날씨 상태)
(ARCHITECTURE.md §4, 아키텍처 3단계·4c).

웹 패키지(`aot.aot_flask`)에 기대지 않는 공간 계산을 둔다. 데몬·트윈·웹이 모두
아래에서 가져다 쓰므로 여기서 위층(웹 앱·라우트·로그인·AI·도구층)을 import 하지
않는다(`check_import_layers.py` 의 `space-no-web` 규칙). 모델이 Flask-SQLAlchemy 를
쓰므로 `flask` 의 앱 컨텍스트 원시 기능과 `flask_babel` 은 허용한다(아키텍처 4c-1).

이 `__init__` 은 아무것도 미리 import 하지 않는다 — 하위 모듈 하나를 쓰려고
패키지 전체를 띄우지 않게(옛 `aot.aot_flask.geo` 의 `__init__` 은 웹 계층을
통째로 올린다).
"""
