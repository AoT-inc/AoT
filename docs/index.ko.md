description: Documentation for AoT, an open source GIS- and AI-based environmental monitoring and control system.

## AoT 환경 모니터링 및 제어 시스템

AoT 는 내 공간을 지도에 담고, 그곳의 기록과 장치를 연결합니다. 그리고 그 공간을 AI 가 사람과 함께 보고, 판단하고, 작업할 수 있게 만듭니다.

센서로 환경을 관측하고 장치를 원격 제어하는 오픈소스 소프트웨어이며, 특정 용도나 장소에 매이지 않습니다. 장치·센서·구조물을 **GIS 지도** 위 실제 위치에 놓을 수 있고, **MCP(Model Context Protocol) 기반 AI**가 시스템을 읽고 진단하며 사용자 승인을 받아 조작할 수 있습니다. 어떤 기능을 쓸지는 사용자가 정합니다.

[라즈베리 파이](https://en.wikipedia.org/wiki/Raspberry_Pi) 등 단일 보드 컴퓨터(SBC)에 직접 설치하거나, 일반 서버·PC에서 Docker로 실행할 수 있습니다.

### 정보

AoT가 무엇을 하고 각 요소가 어떻게 맞물리는지는 [소개](About.md)를, 기능·스크린샷 등 그 밖의 정보는 [README](https://github.com/AoT-inc/AoT)를 참고하십시오.

### 사전 요구 사항

*   단일 보드 컴퓨터 (권장: [라즈베리 파이](https://www.raspberrypi.org/) 2, 3, 4 이상) 또는 그 밖의 데비안 기반 리눅스 장비
*   데비안 기반 운영 체제(32비트 `armhf`, 64비트 `arm64`, `amd64`), Python 3.8 이상
*   활성 인터넷 연결

설치 프로그램은 CPU 아키텍처를 감지하며 `armhf`, `arm64`, `amd64`를 지원합니다. 라즈베리 파이 Zero와 Pi 1(ARMv6)은 검증하지 않았으므로 지원 대상으로 적지 않습니다.

Docker가 동작하는 리눅스·macOS·Windows 장비에서도 실행할 수 있습니다 — 아래 [Docker로 설치](#install-with-docker)를 참고하십시오.

### 설치

부팅 및 로그인 후 다음 명령을 실행하여 AoT 설치를 시작하십시오:

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

설치 후 SBC의 IP 주소로 웹 브라우저를 여십시오.

```
https://<파이 IP 주소>
```

`https://127.0.0.1`(또는 `localhost`)은 파이 자신에서 연 브라우저에서만 동작합니다. 다른 컴퓨터에서는 파이의 IP 주소를 쓰십시오. 설치 프로그램이 자체 서명 인증서를 만들기 때문에, 처음 접속하면 브라우저가 인증서 경고를 띄웁니다. 경고를 넘어 계속 진행하십시오.

이후 화면은 아래 [처음 실행](#first-run)을 참고하십시오.

### MQTT 브로커 { #mqtt-broker-security }

직접 설치는 로컬 [Mosquitto](https://mosquitto.org/) MQTT 브로커도 함께 설정합니다. 기본값은 같은 기기(`127.0.0.1`)에서 오는 연결만 받으며, AoT 의 MQTT 입력·출력 기본 주소(`localhost:1883`)와 같습니다.

*   외부 게이트웨이처럼 다른 기기가 접속해야 하면 설치 명령을 실행하기 전에 같은 터미널에서 `export AOT_MQTT_LISTEN_ALL=1` 을 실행합니다. 이 경우 모든 네트워크 인터페이스에서 **로그인 없이** 접속되므로 신뢰하는 네트워크에서만 쓰거나, `/etc/mosquitto/conf.d/aot.conf` 에 비밀번호 파일(`allow_anonymous false`, `password_file`)을 추가하세요.
*   이미 설치된 곳은 기존 `/etc/mosquitto/conf.d/aot.conf` 를 그대로 유지합니다. 이전 버전은 `listener 1883` 과 `allow_anonymous true` 를 기록해 네트워크 전체에서 로그인 없이 접속할 수 있었습니다. 설치·업그레이드는 이 파일을 바꾸지 않고, 이렇게 열려 있으면 경고만 표시합니다. 제한하려면 첫 줄을 `listener 1883 127.0.0.1` 로 바꾸고 `sudo systemctl restart mosquitto` 를 실행하세요. 네트워크의 게이트웨이가 이 브로커로 발행하지 않는지 먼저 확인한 뒤에 바꾸세요.

### Docker로 설치 { #install-with-docker }

사전 요구 사항: [Docker](https://docs.docker.com/get-docker/) (Compose v2 포함). 공식 이미지는 `linux/amd64`(일반 PC·서버)와 `linux/arm64`(라즈베리 파이·애플 실리콘)로 발행됩니다.

compose 파일이 저장소 안의 사용자 확장 디렉터리(`aot/inputs/custom_inputs` 등)를 마운트하므로, 저장소를 먼저 받아야 합니다:

```bash
git clone https://github.com/AoT-inc/AoT.git /opt/AoT
cd /opt/AoT
cp docker/.env.prod.example docker/.env
```

`docker/.env` 에서 아래 항목을 확인하십시오:

*   `AOT_IMAGE_TAG` — 설치할 버전. [릴리스](https://github.com/AoT-inc/AoT/releases)의 정확한 버전으로 고정하는 것을 권장합니다.
*   `AOT_PORT` — 웹 인터페이스를 노출할 호스트 포트(기본 `8084`).
*   `TZ` — 컨테이너 시간대(기본 `Asia/Seoul`). 시스템 시간대 설정의 **첫 실행 기본값**만 정합니다(데이터베이스를 처음 만들 때 한 번 복사되며, 이후에 바꿔도 영향이 없습니다). 로그 시각과 예약은 시스템 시간대 설정과 지도의 사이트·구역 위치를 따르므로, 첫 로그인 후 시스템 시간대를 확인하고 사이트·구역을 지도에 배치하세요. 데이터는 항상 UTC로 저장됩니다.
*   `HARDWARE_PROFILE` — `LOW`(기본), `MEDIUM`, `HIGH`. AI 비서 기능만 달라집니다. `LOW`는 VEE·EKG 기능을 끄고(AI 의도 라우터는 켜 둡니다), `MEDIUM`과 `HIGH`는 VEE·EKG를 켜며 `HIGH`는 EKG 창을 더 크게(500개 대신 5000개) 유지합니다. 센서·출력·제어는 어느 값이든 같으므로, 라즈베리 파이나 소형 VM에서는 `LOW`로 두십시오.

기동:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

해당 포트로 호스트의 IP 주소에 웹 브라우저를 여십시오.

```
http://<호스트 IP 주소>:8084
```

`http://127.0.0.1:8084`(또는 `localhost`)는 Docker 호스트 자신에서 연 브라우저에서만 동작합니다. Docker 구성은 기본적으로 HTTPS를 쓰지 않으므로 인증서 경고는 없습니다. HTTPS가 필요하면 앞단에 리버스 프록시를 두십시오([보안](Security.md) 참고).

Docker 배포판의 업그레이드는 디스크의 파일을 갈아치우는 것이 아니라, 새 이미지를 받아 컨테이너를 다시 만드는 방식입니다. [업그레이드/백업/복원](Upgrade-Backup-Restore.md#docker)을 참고하십시오.

!!! note
    Docker 구성은 호스트의 GPIO·I2C·1-Wire 장치를 컨테이너에 전달하지 않습니다. 라즈베리 파이 핀에 직접 연결한 센서·릴레이를 쓰려면 직접 설치를 사용하십시오. LoRaWAN(ChirpStack)·Modbus TCP·MQTT 등 네트워크로 붙는 장치는 어느 설치 방식에서든 동일하게 동작합니다.

### 처음 실행 { #first-run }

새로 설치하면(직접 설치·Docker 모두) 로그인 창이 아니라 공개 소개 화면(랜딩 페이지)이 먼저 열립니다. 관리자 사용자가 아직 없을 때의 순서는 다음과 같습니다.

1. 랜딩 페이지에서 **로그인**을 누릅니다. `/login`으로 이동하지만 관리자가 없으므로 곧바로 `/create_admin`으로 넘어갑니다.
2. 첫 화면은 **품질 보증에 관한 안내**(라이선스·보증·익명 통계)입니다. 읽고 **인증 확인**을 누릅니다.
3. 관리자 생성 양식이 나타납니다. 사용자 이름·이메일·비밀번호를 입력하고 제출합니다.
4. 만든 계정으로 로그인합니다. 통계 수집은 나중에 `관리 → 시스템 관리 → 일반 설정`에서 거부할 수 있습니다.

### 지원

*   [AoT on GitHub](https://github.com/AoT-inc/AoT)
*   [AoT Wiki](https://github.com/AoT-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)
*   [포럼](https://forum.radicaldiy.com)
*   [자주 묻는 질문](https://forum.radicaldiy.com/docs?category=23&tags=aot)

