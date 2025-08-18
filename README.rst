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

[![광합성 촉진 방법](https://www.youtube.com/watch?v=q-QhT4KU1Dc)

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

