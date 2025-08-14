AoT
======

환경 제어 시스템

최신 버전: 0.0.1

AoT는 라즈베리 파이에서 동작하는 오픈소스 소프트웨어로, 다양한 입력과 출력을 결합하여 환경을 감지하고 제어할 수 있습니다.
이 파일은 AoT가 Mycodo의 원본 버전에서 한국어 번역과 몇가지 앱을 추가한 수정 버전입니다.

|Build Status| |Codacy Badge| |Translation Badge| |DOI|

.. contents:: 목차
   :depth: 1

빠른 설치
-------------

필수 조건: Debian 기반 리눅스 운영체제(apt 사용 가능).

권장: GPIO 핀이 있는 싱글보드 컴퓨터(SBC).

설치 명령어:

.. code:: bash

    curl -L https://aot-inc.github.io/AoT/install | bash

자세한 내용은 `AoT 설치 <#install-aot>`__ 섹션을 참고하세요.

지원
-------

문서
~~~~~~~~~~~~~

`AoT 매뉴얼 <https://aot-inc.github.io/AoT>`__

`AoT API <https://aot-inc.github.io/AoT/aot-api.html>`__ (버전: v1)

`AoT 위키 <https://github.com/aot-inc/AoT/wiki>`__

`AoT 커스텀 모듈 저장소 <https://github.com/aot-inc/AoT-custom>`__

토론
~~~~~~~~~~

`AoT 이슈(버그 신고/기능 요청) <https://github.com/aot-inc/AoT/issues>`__

`AoT 포럼 <https://forum.radicaldiy.com>`__



AoT 소프트웨어 버그 신고
~~~~~~~~~~~~~~~~~~~~~~~~~~

AoT 소프트웨어에 버그가 있다고 생각되면 먼저 github의 `Issues <https://github.com/aot-inc/AoT/issues>`__에서 이미 논의되었거나 해결된 문제가 있는지 검색하세요. 새로운 이슈이거나 최근의 이슈라면 `새 이슈 생성 <https://github.com/aot-inc/AoT/issues/new>`__을 통해 등록해 주세요. 이슈를 생성할 때는 템플릿의 안내를 잘 읽고 요청된 정보를 최대한 자세히 작성해 주세요. 정보가 부족하면 문제 재현이 어렵고, 해결이 지연될 수 있습니다.



주요 기능
--------

-  센서, GPIO 핀, ADC 등에서 측정값을 기록하는 `입력 <https://aot-inc.github.io/AoT/Inputs/>`__ (또는 `커스텀 입력 <https://aot-inc.github.io/AoT/Inputs/#custom-inputs>`__ 생성 가능). `지원 입력 목록 <https://aot-inc.github.io/AoT/Supported-Inputs-By-Measurement/>`__ 참고.
-  GPIO 제어, PWM 신호 생성, 스크립트 실행 등 다양한 작업을 수행하는 `출력 <https://aot-inc.github.io/AoT/Outputs/>`__ (또는 `커스텀 출력 <https://aot-inc.github.io/AoT/Outputs/#custom-outputs>`__ 생성 가능). `지원 출력 목록 <https://aot-inc.github.io/AoT/Supported-Outputs/>`__ 참고.
-  입력과 출력을 다양한 방식으로 결합하는 `함수 <https://aot-inc.github.io/AoT/Functions/>`__ (예: `PID <https://aot-inc.github.io/AoT/Functions/#pid-controller>`__, `조건 <https://aot-inc.github.io/AoT/Functions/#conditional>`__, `트리거 <https://aot-inc.github.io/AoT/Functions/#trigger>`__ 등, 또는 `커스텀 함수 <https://aot-inc.github.io/AoT/Functions/#custom-functions>`__ 생성 가능). `지원 함수 목록 <https://aot-inc.github.io/AoT/Supported-Functions/>`__ 참고.
-  다양한 테마를 지원하는 `웹 인터페이스 <https://aot-inc.github.io/AoT/About/#web-interface>`__로 네트워크 어디서든 안전하게 시스템을 확인 및 설정 가능.
-  대시보드에서 실시간/과거 그래프, 게이지, 출력 상태, 측정값 등 다양한 위젯을 표시 (`커스텀 위젯 <https://aot-inc.github.io/AoT/Widgets/#custom-widgets>`__ 지원). `지원 위젯 목록 <https://aot-inc.github.io/AoT/Supported-Widgets/>`__ 참고.
-  임계값 도달 시 이메일 등으로 알림을 보내는 `알림 기능 <https://aot-inc.github.io/AoT/Alerts/>`__.
-  PID 컨트롤러의 목표값을 시간에 따라 변경하는 `설정값 추적 <https://aot-inc.github.io/AoT/Methods/>`__.
-  이벤트, 알림 등을 기록하고 그래프에 표시할 수 있는 `노트 <https://aot-inc.github.io/AoT/Notes/>`__.
-  원격 라이브 스트리밍, 이미지 캡처, 타임랩스 촬영이 가능한 `카메라 <https://aot-inc.github.io/AoT/Camera/>`__.
-  전력 소비 및 비용을 추적하는 `에너지 사용량 측정 <https://aot-inc.github.io/AoT/Energy-Usage/>`__.
-  시스템을 최신 버전으로 쉽게 업그레이드하거나 백업/복원할 수 있는 `업그레이드 시스템 <https://aot-inc.github.io/AoT/Upgrade-Backup-Restore/>`__.
-  다양한 `언어 <https://github.com/aot-inc/AoT#features>`__로 웹 인터페이스를 사용할 수 있는 `번역 <https://aot-inc.github.io/AoT/Translations/>`__ 지원.



AoT 설치
--------------

필수 조건
~~~~~~~~~~~~~

필수:

-  Debian 기반 운영체제
-  인터넷 연결

권장:

-  `라즈베리 파이 <https://www.raspberrypi.org>`__ 3, 4, 5 (Zero, 1, 2는 권장하지 않음)
-  `라즈베리 파이 OS <https://www.raspberrypi.com/software/>`__를 micro SD 카드 또는 SSD에 설치

AoT는 Raspberry Pi OS 12(Bookworm), Lite/데스크탑, 32/64비트에서 테스트되었습니다.

설치 명령어
~~~~~~~~~~~~~~~

라즈베리 파이 부팅 후 터미널에서 아래 명령어를 실행하면 /opt/AoT에 AoT가 설치됩니다:

.. code:: bash

    curl -L https://aot-inc.github.io/AoT/install | bash

설치 참고사항
~~~~~~~~~~~~~

설치 스크립트가 오류 없이 완료되어야 합니다. 설치 로그는 ``/opt/AoT/install/setup.log``에 저장됩니다.

설치가 성공하면 웹 브라우저에서 ``https://127.0.0.1/``(설치한 컴퓨터의 IP로 변경)로 접속해 웹 인터페이스를 사용할 수 있습니다. 첫 방문 시 관리자 계정을 생성해야 하며, 로그인 후 좌측 상단의 시간이 올바른지 확인하세요. 시간이 맞지 않으면 데이터 저장/조회에 문제가 생길 수 있습니다. 또한 호스트명과 버전이 초록색이어야 데몬이 정상 동작 중임을 의미합니다. 빨간색이면 데몬이 비활성/응답 없음 상태입니다. 웹 인터페이스의 모든 기능이 정상 동작하려면 브라우저의 자바 차단 플러그인을 비활성화해야 합니다.

설치 중 오류가 발생해 시스템이 정상 동작하지 않는다면, 설치 로그를 첨부해 `이슈를 등록 <https://github.com/aot-inc/AoT/issues>`__해 주세요. 직접 진단을 원한다면 `문제 진단 <#diagnosing-issues>`__을 참고하세요.

개발 개선을 위해 최소한의 익명 사용 통계가 수집됩니다. 식별 정보는 저장되지 않으며, 개발팀만 접근할 수 있고 외부에 판매되지 않습니다. 어떤 기능이 얼마나 사용되는지 등만 수집되며, '설정 -> 일반' 페이지에서 '수집된 통계 보기' 링크로 확인할 수 있습니다. 일반 설정에서 수집 비활성화도 가능합니다.

측정 데이터베이스
~~~~~~~~~~~~~~~~~~~~

AoT는 측정값 저장을 위해 InfluxDB(1.x: 32비트, 2.x: 64비트)를 지원합니다. 설치 중 1.x, 2.x, 또는 직접 설정(로컬/원격) 중 선택할 수 있습니다. 설치 후에도 설정 변경이 가능합니다.

도커(Docker)
~~~~~~

도커 지원은 실험적입니다. 사용을 원한다면 docker `README.md <https://github.com/aot-inc/AoT/blob/master/docker/README.md>`__를 참고하세요. 개발에 참여하고 싶다면 github의 `Docker 이슈(#637) <https://github.com/aot-inc/AoT/issues/637>`__를 참고하세요.

REST API
--------

최신 API 문서는 `API 정보 <https://aot-inc.github.io/AoT/API/>`__ 및 `API 엔드포인트 문서 <https://aot-inc.github.io/AoT/aot-api.html>`__에서 확인할 수 있습니다.

PID 제어란?
-----------------

`비례-적분-미분(PID) 제어기 <https://ko.wikipedia.org/wiki/PID_제어기>`__는 산업 현장에서 널리 사용되는 피드백 제어 방식입니다. 온도 등 측정값을 원하는 상태(설정값)로 효율적으로 맞춥니다. 잘 튜닝된 PID 제어기는 빠르게 설정값에 도달하고, 오버슈트와 진동이 적으며, 안정적으로 유지합니다.

.. figure:: docs/images/PID-Animation.gif
   :alt: PID Animation

|AoT|

위 그래프는 온도 조절 예시입니다. 빨간 선은 시간에 따라 변하는 설정값, 파란 선은 실제 온도, 초록 막대는 20초마다 히터가 동작한 시간을 나타냅니다. 최소한의 튜닝만으로도 ±0.5°C 이내로 안정적으로 제어할 수 있습니다. 추가 튜닝 시 변동폭을 더 줄일 수 있습니다.

자세한 내용은 `PID 컨트롤러 <https://aot-inc.github.io/AoT/Functions/#pid-controller>`__ 및 `PID 튜닝 <https://aot-inc.github.io/AoT/Functions/#pid-tuning>`__을 참고하세요.

지원 입력 및 출력
----------------------------

지원되는 모든 입력, 출력, 기타 장치는 매뉴얼의 `지원 장치 <https://aot-inc.github.io/AoT/Supported-Inputs-By-Measurement/>`__에서 확인할 수 있습니다.

커스텀 입력, 출력, 함수, 액션, 위젯
-------------------------------------------------------

AoT는 커스텀 입력, 출력, 함수, 액션, 위젯 모듈을 가져와 사용할 수 있습니다. 자세한 내용은 매뉴얼의 `커스텀 입력 <https://aot-inc.github.io/AoT/Inputs/#custom-inputs>`__, `커스텀 출력 <https://aot-inc.github.io/AoT/Outputs/#custom-outputs>`__, `커스텀 함수 <https://aot-inc.github.io/AoT/Functions/#custom-functions>`__, `커스텀 액션 <https://aot-inc.github.io/AoT/Functions/#custom-actions>`__, `커스텀 위젯 <https://aot-inc.github.io/AoT/Data-Viewing/#custom-widgets>`__을 참고하세요.

지원 목록에 추가하고 싶다면 직접 모듈을 만들어 pull request를 보내거나 `새 이슈 <https://github.com/aot-inc/AoT/issues/new?assignees=&labels=&template=feature-request.md&title=>`__를 등록해 주세요.

또한, 기본 제공되지 않는 커스텀 모듈은 별도의 저장소(`aot-inc/AoT-custom <https://github.com/aot-inc/AoT-custom>`__)에서 관리됩니다.


링크
-----

공식 배포처가 아닌 곳에서 문서를 받았다면 최신 버전이 아닐 수 있습니다. 최신 버전은 아래에서 확인하세요.

https://github.com/aot-inc/AoT



라이선스
-------

`License.txt <https://github.com/aot-inc/AoT/blob/master/LICENSE.txt>`__ 참고

AoT는 GNU 일반 공중 사용 허가서(GPL) 3버전 또는 그 이후 버전의 조건에 따라 자유롭게 사용, 수정, 배포할 수 있습니다.

AoT는 유용하게 사용되길 바라지만, 상품성이나 특정 목적 적합성에 대한 보증은 없습니다. 자세한 내용은 `GNU GPL <http://www.gnu.org/licenses/gpl-3.0.en.html>`__을 참고하세요.

전체 라이선스 전문은 http://www.gnu.org/licenses/gpl-3.0.en.html 에서 확인할 수 있습니다.

이 소프트웨어에는 타사 오픈소스 소프트웨어가 포함될 수 있습니다. 각 파일의 라이선스 정보를 참고하세요.



Thanks
------

AoT는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로 대한민국 실정에 맞게 수정된 버전입니다.
또한 다음의 다양한 오픈소스 라이브러리를 활용하기 때문에 사용할 수 있습니다.
이 프로젝트를 가능하게 해주신 모든 분들께 감사드립니다.

-  `Alembic <https://alembic.sqlalchemy.org>`__
-  `Argparse <https://pypi.org/project/argparse>`__
-  `Bcrypt <https://pypi.org/project/bcrypt>`__
-  `Bootstrap <https://getbootstrap.com>`__
-  `Daemonize <https://pypi.org/project/daemonize>`__
-  `Date Range Picker <https://github.com/dangrossman/daterangepicker>`__
-  `Distro <https://pypi.org/project/distro>`__
-  `Email_Validator <https://pypi.org/project/email_validator>`__
-  `Filelock <https://pypi.org/project/filelock>`__
-  `Flask <https://pypi.org/project/flask>`__
-  `Flask_Accept <https://pypi.org/project/flask_accept>`__
-  `Flask_Babel <https://pypi.org/project/flask_babel>`__
-  `Flask_Compress <https://pypi.org/project/flask_compress>`__
-  `Flask_Limiter <https://pypi.org/project/flask_limiter>`__
-  `Flask_Login <https://pypi.org/project/flask_login>`__
-  `Flask_Marshmallow <https://pypi.org/project/flask_marshmallow>`__
-  `Flask_Profiler <https://github.com/muatik/flask-profiler>`__
-  `Flask_RESTX <https://pypi.org/project/flask_restx>`__
-  `Flask_Session <https://pypi.org/project/flask_session>`__
-  `Flask_SQLAlchemy <https://pypi.org/project/flask_sqlalchemy>`__
-  `Flask_Talisman <https://pypi.org/project/flask_talisman>`__
-  `Flask_WTF <https://pypi.org/project/flask_wtf>`__
-  `FontAwesome <https://fontawesome.com>`__
-  `Geocoder <https://pypi.org/project/geocoder>`__
-  `gridstack.js <https://github.com/gridstack/gridstack.js>`__
-  `Gunicorn <https://gunicorn.org>`__
-  `Highcharts <https://www.highcharts.com>`__
-  `importlib_metadata <https://github.com/python/importlib_metadata>`__
-  `InfluxDB <https://github.com/influxdata/influxdb>`__
-  `influxdb <https://github.com/influxdata/influxdb-python>`__
-  `influxdb_client <https://github.com/influxdata/influxdb-client-python>`__
-  `jQuery <https://jquery.com>`__
-  `Marshmallow_SQLAlchemy <https://pypi.org/project/marshmallow_sqlalchemy>`__
-  `Pyro5 <https://github.com/irmen/Pyro5>`__
-  `SQLAlchemy <https://www.sqlalchemy.org>`__
-  `SQLite <https://www.sqlite.org>`__
-  `toastr <https://github.com/CodeSeven/toastr>`__
-  `Werkzeug <https://palletsprojects.com/p/werkzeug/>`__
-  `WTForms <https://pypi.org/project/wtforms>`__

