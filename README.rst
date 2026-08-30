AoT
======

환경 제어 시스템

최신 버전: 26.08.16

AoT는 센서로 환경을 관측하고 장치를 원격 제어하는 오픈소스 소프트웨어입니다. 특정 용도나 장소에 매이지 않습니다 — 온실·축사·노지는 물론 공원·시설물·교통처럼 관측할 대상이 공간에 놓여 있는 곳이면 어디에나 적용할 수 있습니다.

AoT를 규정하는 것은 두 가지입니다. 모든 장치·센서·구조물이 지도 위 실제 위치를 갖는 **GIS 디지털 트윈**, 그리고 그 지도를 읽고 진단하며 사용자 승인을 받아 조작하는 **MCP(Model Context Protocol) 기반 AI** 입니다.
라즈베리 파이 등 단일 보드 컴퓨터에 직접 설치하거나, 일반 서버·PC에서 Docker로 실행할 수 있습니다.

AoT는 오픈소스 Mycodo 프로젝트에서 출발했으며, 그 입력·출력·함수 제어 모델을 토대로 유지하고 있습니다. 자세한 내용은 `유래 <https://aot-inc.github.io/AoT/About/#origins>`__ 를 참고하세요.

.. note:: 이전 2D 지도 기반 버전(v26.0.x)은 `legacy-2d <https://github.com/AoT-inc/AoT/tree/legacy-2d>`__ 브랜치에 보존되어 있습니다. 현재 버전과 데이터 호환되지 않으므로 구버전 설치를 유지하려면 업그레이드하지 마세요.

.. contents:: 목차
   :depth: 1

주요 기능
-------------

-  **벡터 GIS 지도**: MapLibre 기반 벡터 렌더링, 국내외 다양한 지도 서비스, 도형 그리기·장치 배치·드론/항공사진 오버레이
-  **3D 시설 관리**: 온실·하우스 외형을 폴리곤으로 정의하고 3D 시각화, 창호·커튼 등 구성 요소를 지도에 연결해 자동 제어
-  **AI 어시스턴트**: MCP 기반 시설 관측·진단·제어(상태 변경은 사용자 승인 게이팅). Claude·Gemini·GPT·Mistral·Groq·Ollama 등 다중 제공자 지원
-  **MCP 서버**: 표준 MCP 프로토콜(stdio/HTTP)로 시스템 전체를 도구로 노출 — Claude Desktop 등 외부 MCP 클라이언트가 직접 호출 가능
-  **통합 환경 제어**: PI 제어 기반 다중 액추에이터 조율, 풍향 차등 제어, VPD·DLI·GDD 누적 관리, 안전 게이트
-  **LoRaWAN**: ChirpStack 연동, 사이트 단위 Class A/C 스케줄러, 밸브 명령 신뢰성 보장
-  **입력·출력·함수**: 다양한 센서·릴레이 지원 위에 PID·시퀀스·타이머·조건부 제어 (Mycodo에서 이어받은 제어 모델)

버전별 상세 변경 사항은 `CHANGELOG.md <https://github.com/AoT-inc/AoT/blob/main/CHANGELOG.md>`__ 를 참고하세요.

빠른 설치
-------------

설치 방법은 두 가지입니다.

**1. 직접 설치 (Debian 기반 리눅스)** — 라즈베리 파이 등 GPIO 핀이 있는 싱글보드 컴퓨터(SBC) 권장.

.. code:: bash

    curl -L https://aot-inc.github.io/AoT/install | bash

**2. Docker로 설치** — Docker가 동작하는 리눅스/macOS/Windows.

.. code:: bash

    git clone https://github.com/AoT-inc/AoT.git /opt/AoT
    cd /opt/AoT
    cp docker/.env.prod.example docker/.env   # AOT_IMAGE_TAG 를 설치할 버전으로 수정
    docker compose -f docker/docker-compose.prod.yml up -d

자세한 내용은 `AoT 설치 <#install-aot>`__ 섹션을 참고하세요.

지원
-------

-  사용자 매뉴얼: https://aot-inc.github.io/AoT
-  문의·버그 신고: `GitHub Issues <https://github.com/AoT-inc/AoT/issues>`__

AoT 설치
--------------

설치 방식 선택
~~~~~~~~~~~~~~~~

+------------------+------------------------------------------+------------------------------------------+
| 항목             | 직접 설치                                | Docker 설치                              |
+==================+==========================================+==========================================+
| 운영체제         | Debian 기반 리눅스(apt)                  | Docker가 동작하는 리눅스/macOS/Windows   |
+------------------+------------------------------------------+------------------------------------------+
| GPIO·I2C·1-Wire  | 지원                                     | 기본 구성에서는 지원하지 않음            |
+------------------+------------------------------------------+------------------------------------------+
| 네트워크 장치    | 지원 (Modbus TCP, MQTT, LoRaWAN, HTTP 등)| 지원                                     |
+------------------+------------------------------------------+------------------------------------------+
| 업그레이드       | 웹 인터페이스 또는 ``aot-commands``      | 이미지 pull 후 컨테이너 재생성           |
+------------------+------------------------------------------+------------------------------------------+

라즈베리 파이에 센서·릴레이를 직접 연결해 쓰는 일반적인 사용에는 **직접 설치**\ 를 권장합니다.
Docker 설치는 서버·PC에서 네트워크 기반 장치(LoRaWAN, Modbus TCP, MQTT 등)만 다루거나 시험 운용할 때 적합합니다.

직접 설치 — 필수 조건
~~~~~~~~~~~~~~~~~~~~~~~~~~~

필수:

-  Debian 기반 운영체제
-  인터넷 연결

권장:

-  `라즈베리 파이 <https://www.raspberrypi.org>`__ 3, 4, 5 (Zero, 1, 2는 권장하지 않음)
-  `라즈베리 파이 OS <https://www.raspberrypi.com/software/>`__\ 를 micro SD 카드 또는 SSD에 설치

AoT는 Raspberry Pi OS 12(Bookworm), Lite/데스크탑, 32/64비트와 Debian 12 arm 64비트에서 테스트되었습니다.

직접 설치 — 설치 명령어
~~~~~~~~~~~~~~~~~~~~~~~~~~~

라즈베리 파이 부팅 후 터미널에서 아래 명령어를 실행하면 /opt/AoT에 AoT가 설치됩니다:

.. code:: bash

    curl -L https://aot-inc.github.io/AoT/install | bash

Docker로 설치
~~~~~~~~~~~~~~~~

필수 조건: `Docker <https://docs.docker.com/get-docker/>`__ (Compose v2 포함). 공식 이미지는 ``linux/amd64`` 와 ``linux/arm64`` 를 제공합니다.

compose 파일이 저장소 안의 사용자 확장 디렉터리(``aot/inputs/custom_inputs`` 등)를 마운트하므로, 저장소를 먼저 받아야 합니다.

.. code:: bash

    git clone https://github.com/AoT-inc/AoT.git /opt/AoT
    cd /opt/AoT
    cp docker/.env.prod.example docker/.env

``docker/.env`` 에서 최소한 아래 항목을 확인합니다.

-  ``AOT_IMAGE_TAG`` — 설치할 버전. `릴리스 <https://github.com/AoT-inc/AoT/releases>`__ 의 정확한 버전(예: ``26.08.9``)으로 고정하는 것을 권장합니다.
-  ``AOT_PORT`` — 웹 인터페이스를 노출할 호스트 포트(기본 ``8084``).
-  ``TZ`` — 컨테이너 시간대(기본 ``Asia/Seoul``). 데이터는 UTC로 저장되며, 로그 표시와 지역 시간 기반 예약에 사용됩니다.
-  ``HARDWARE_PROFILE`` — ``LOW``\ (라즈베리 파이·소형 VM) 또는 ``HIGH``.

기동:

.. code:: bash

    docker compose -f docker/docker-compose.prod.yml up -d

컨테이너가 모두 뜨면 ``http://127.0.0.1:8084/`` (설치한 컴퓨터의 IP로 변경)로 접속합니다. 첫 방문 시 관리자 계정을 만드는 것은 직접 설치와 같습니다.

업그레이드는 파일을 갈아치우지 않고 이미지를 새로 받아 컨테이너를 다시 만드는 방식입니다:

.. code:: bash

    docker compose -f docker/docker-compose.prod.yml pull
    docker compose -f docker/docker-compose.prod.yml up -d

데이터베이스, 업로드 파일, 3D 모델, 백업, 사용자 스크립트는 모두 Docker 볼륨에 있어 이미지를 교체해도 보존됩니다. 이전 버전으로 되돌리려면 ``AOT_IMAGE_TAG`` 를 이전 값으로 바꾸고 다시 ``up -d`` 하면 됩니다. 웹 인터페이스에서의 원클릭·자동 업데이트를 쓰려면 별도의 업데이터 서비스가 필요합니다 — `업그레이드 문서 <https://aot-inc.github.io/AoT/Upgrade-Backup-Restore/#docker>`__ 를 참고하세요.

.. note:: Docker 구성은 호스트의 GPIO·I2C·1-Wire 장치를 컨테이너에 전달하지 않습니다. 라즈베리 파이 핀에 직접 연결한 센서·릴레이를 쓰려면 직접 설치를 사용하세요. LoRaWAN(ChirpStack), Modbus TCP, MQTT 등 네트워크로 붙는 장치는 Docker 설치에서도 그대로 사용할 수 있습니다.

설치 참고사항
~~~~~~~~~~~~~

설치 스크립트가 오류 없이 완료되어야 합니다. 설치 로그는 ``/opt/AoT/install/setup.log`` 에 저장됩니다.

설치가 성공하면 웹 브라우저에서 ``https://127.0.0.1/`` (Docker 설치는 ``http://127.0.0.1:8084/``, 설치한 컴퓨터의 IP로 변경)로 접속해 웹 인터페이스를 사용할 수 있습니다. 첫 방문 시 관리자 계정을 생성해야 하며, 로그인 후 좌측 상단의 시간이 올바른지 확인하세요. 시간이 맞지 않으면 데이터 저장/조회에 문제가 생길 수 있습니다. 또한 호스트명과 버전이 초록색이어야 데몬이 정상 동작 중임을 의미합니다. 빨간색이면 데몬이 비활성/응답 없음 상태입니다. 웹 인터페이스의 모든 기능이 정상 동작하려면 브라우저의 자바 차단 플러그인을 비활성화해야 합니다.

프로그램에서 도움 항목은 아직 작동하지 않습니다. - 페이지 생성중

개발 개선을 위해 최소한의 익명 사용 통계가 수집됩니다. 식별 정보는 저장되지 않으며, 개발팀만 접근할 수 있고 외부에 판매되지 않습니다. 어떤 기능이 얼마나 사용되는지 등만 수집되며, '설정 -> 일반' 페이지에서 '수집된 통계 보기' 링크로 확인할 수 있습니다. 일반 설정에서 수집 비활성화도 가능합니다.


링크
-----

공식 배포처가 아닌 곳에서 문서를 받았다면 최신 버전이 아닐 수 있습니다. 최신 버전은 아래에서 확인하세요.

https://github.com/AoT-inc/AoT

-  유튜브: `광합성 촉진 방법 <https://www.youtube.com/watch?v=q-QhT4KU1Dc>`__

라이선스
------------

`LICENSE.txt <https://github.com/AoT-inc/AoT/blob/main/LICENSE.txt>`__ 참고

AoT는 GNU 일반 공중 사용 허가서(GPL) 3버전 또는 그 이후 버전의 조건에 따라 자유롭게 사용, 수정, 배포할 수 있습니다.

AoT는 유용하게 사용되길 바라지만, 상품성이나 특정 목적 적합성에 대한 보증은 없습니다. 자세한 내용은 `GNU GPL <http://www.gnu.org/licenses/gpl-3.0.en.html>`__\ 을 참고하세요.

전체 라이선스 전문은 http://www.gnu.org/licenses/gpl-3.0.en.html 에서 확인할 수 있습니다.

이 소프트웨어에는 타사 오픈소스 소프트웨어가 포함되어 있습니다. 전체 목록과 각각의 라이선스는 `THIRD-PARTY-LICENSES.md <https://github.com/AoT-inc/AoT/blob/main/THIRD-PARTY-LICENSES.md>`__ 를 참고하세요.



Thanks
------

AoT는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)에서 출발했으며, 입력·출력·함수 제어 모델은 지금도 그 위에 놓여 있습니다.
또한 다음의 다양한 오픈소스 라이브러리를 활용하기 때문에 사용할 수 있습니다.
이 프로젝트를 가능하게 해주신 모든 분들께 감사드립니다.

**Core Libraries**

-  `Alembic <https://alembic.sqlalchemy.org>`__
-  `APScheduler <https://pypi.org/project/APScheduler>`__
-  `Argparse <https://pypi.org/project/argparse>`__
-  `Axios <https://axios-http.com/>`__
-  `Bcrypt <https://pypi.org/project/bcrypt>`__
-  `Beautiful Soup 4 <https://www.crummy.com/software/BeautifulSoup/>`__
-  `Bootstrap <https://getbootstrap.com>`__
-  `Date Range Picker <https://github.com/dangrossman/daterangepicker>`__
-  `Distro <https://pypi.org/project/distro>`__
-  `Email_Validator <https://pypi.org/project/email_validator>`__
-  `Filelock <https://pypi.org/project/filelock>`__
-  `Flask <https://pypi.org/project/flask>`__
-  `Flask_Accept <https://pypi.org/project/flask_accept>`__
-  `Flask_Babel <https://pypi.org/project/flask_babel>`__
-  `Flask-Caching <https://pypi.org/project/Flask-Caching/>`__
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
-  `Jinja2 <https://pypi.org/project/Jinja2/>`__
-  `jQuery <https://jquery.com>`__
-  `Lucide React <https://lucide.dev/>`__
-  `Marshmallow_SQLAlchemy <https://pypi.org/project/marshmallow_sqlalchemy>`__
-  `Mosquitto <https://mosquitto.org/>`__
-  `NumPy <https://numpy.org/>`__
-  `OpenCV <https://opencv.org/>`__
-  `paho-mqtt <https://pypi.org/project/paho-mqtt/>`__
-  `pdfplumber <https://pypi.org/project/pdfplumber/>`__
-  `Pillow <https://pypi.org/project/Pillow/>`__
-  `Pillow-HEIF <https://pypi.org/project/pillow-heif/>`__
-  `Pyro5 <https://github.com/irmen/Pyro5>`__
-  `pyserial <https://pypi.org/project/pyserial/>`__
-  `python-dateutil <https://pypi.org/project/python-dateutil/>`__
-  `pytz <https://pypi.org/project/pytz/>`__
-  `PyYAML <https://pypi.org/project/PyYAML/>`__
-  `React <https://react.dev/>`__
-  `React Zoom Pan Pinch <https://github.com/prc5/react-zoom-pan-pinch>`__
-  `Requests <https://pypi.org/project/requests/>`__
-  `SciPy <https://scipy.org/>`__
-  `Shapely <https://pypi.org/project/Shapely/>`__
-  `SQLAlchemy <https://www.sqlalchemy.org>`__
-  `SQLite <https://www.sqlite.org>`__
-  `TailwindCSS <https://tailwindcss.com/>`__
-  `TanStack Query <https://tanstack.com/query/latest>`__
-  `timezonefinder <https://pypi.org/project/timezonefinder/>`__
-  `toastr <https://github.com/CodeSeven/toastr>`__
-  `Vite <https://vitejs.dev/>`__
-  `Waitress <https://docs.pylonsproject.org/projects/waitress/en/latest/>`__
-  `Werkzeug <https://palletsprojects.com/p/werkzeug/>`__
-  `WTForms <https://pypi.org/project/wtforms>`__


**GIS & Maps**

AoT는 벡터 렌더링 기반의 GIS와 다양한 지도 서비스를 지원합니다:
단, 모든 지도가 정상적으로 작동하지 않을 수 있습니다.

-  `Bing Maps <https://www.bing.com/maps>`__
-  `Carto <https://carto.com/>`__
-  `ESA WorldCover <https://esa-worldcover.org/en>`__
-  `Esri <https://www.esri.com/>`__
-  `Google Maps <https://www.google.com/maps>`__
-  `GSI Maps (Japan) <https://maps.gsi.go.jp/>`__
-  `ISRIC SoilGrids <https://soilgrids.org/>`__
-  `Kakao Maps <https://map.kakao.com/>`__
-  `Leaflet <https://leafletjs.com/>`__
-  `Mapbox <https://www.mapbox.com/>`__
-  `MapLibre GL JS <https://maplibre.org/>`__
-  `NASA GIBS <https://wiki.earthdata.nasa.gov/display/GIBS>`__
-  `Naver Maps <https://map.naver.com/>`__
-  `OpenStreetMap <https://www.openstreetmap.org/>`__
-  `OpenTopoMap <https://opentopomap.org/>`__
-  `OpenWeatherMap <https://openweathermap.org/>`__
-  `RainViewer <https://www.rainviewer.com/>`__
-  `SGIS (Statistics Korea) <https://sgis.kostat.go.kr/>`__
-  `Stadia Maps <https://stadiamaps.com/>`__
-  `Thunderforest <https://www.thunderforest.com/>`__
-  `Turf.js <https://turfjs.org/>`__
-  `VWorld (Spatial Information Open Platform) <https://www.vworld.kr/>`__


**3D Visualization**

-  `Three.js <https://threejs.org/>`__
-  `three-mesh-bvh <https://github.com/gkjohnson/three-mesh-bvh>`__
-  `trimesh <https://trimesh.org/>`__
-  `pyrender <https://pyrender.readthedocs.io/>`__


**AI Integration**

AoT는 다중 AI 제공자를 지원하며, MCP(Model Context Protocol)를 통해 AI가 시설을 직접 관측/진단/제어할 수 있습니다:

-  `Anthropic (Claude) <https://www.anthropic.com/>`__
-  `Google (Gemini) <https://ai.google.dev/>`__
-  `OpenAI <https://openai.com/>`__
-  `Mistral AI <https://mistral.ai/>`__
-  `Groq <https://groq.com/>`__
-  `Ollama <https://ollama.com/>`__
-  `MiniMax <https://www.minimax.io/>`__
-  `FastMCP <https://github.com/jlowin/fastmcp>`__

