description: Documentation for AoT, an open source GIS- and AI-based environmental monitoring and control system.

## AoT 환경 모니터링 및 제어 시스템

AoT는 센서로 환경을 관측하고 장치를 원격 제어하는 오픈소스 소프트웨어로, 특정 용도나 장소에 매이지 않습니다. 모든 장치·센서·구조물이 지도 위 실제 위치를 갖는 **GIS 디지털 트윈**과, 그 지도를 읽고 진단하며 사용자 승인을 받아 조작하는 **MCP(Model Context Protocol) 기반 AI**를 중심으로 만들어졌습니다.

[라즈베리 파이](https://en.wikipedia.org/wiki/Raspberry_Pi) 등 단일 보드 컴퓨터(SBC)에 직접 설치하거나, 일반 서버·PC에서 Docker로 실행할 수 있습니다.

### 정보

AoT가 무엇을 하고 각 요소가 어떻게 맞물리는지는 [소개](About.md)를, 기능·스크린샷 등 그 밖의 정보는 [README](https://github.com/AoT-inc/AoT)를 참고하십시오.

### 사전 요구 사항

*   단일 보드 컴퓨터 (권장: [라즈베리 파이](https://www.raspberrypi.org/), 모든 버전: Zero, 1, 2, 3, 4)
*   데비안 기반 운영 체제
*   활성 인터넷 연결

Docker가 동작하는 리눅스·macOS·Windows 장비에서도 실행할 수 있습니다 — 아래 [Docker로 설치](#install-with-docker)를 참고하십시오.

### 설치

부팅 및 로그인 후 다음 명령을 실행하여 AoT 설치를 시작하십시오:

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

설치 후 SBC의 IP 주소로 웹 브라우저를 열면 관리자 사용자를 생성하고 로그인하라는 메시지가 표시됩니다.

```
https://127.0.0.1
```

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
*   `TZ` — 컨테이너 시간대(기본 `Asia/Seoul`). 데이터는 UTC로 저장되며, 이 값은 로그 표시와 지역 시간 기반 예약에 영향을 줍니다.
*   `HARDWARE_PROFILE` — `LOW`(라즈베리 파이·소형 VM) 또는 `HIGH`.

기동:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

해당 포트로 웹 브라우저를 열면 관리자 사용자를 생성하고 로그인하라는 메시지가 표시됩니다.

```
http://127.0.0.1:8084
```

Docker 배포판의 업그레이드는 디스크의 파일을 갈아치우는 것이 아니라, 새 이미지를 받아 컨테이너를 다시 만드는 방식입니다. [업그레이드/백업/복원](Upgrade-Backup-Restore.md#docker)을 참고하십시오.

!!! note
    Docker 구성은 호스트의 GPIO·I2C·1-Wire 장치를 컨테이너에 전달하지 않습니다. 라즈베리 파이 핀에 직접 연결한 센서·릴레이를 쓰려면 직접 설치를 사용하십시오. LoRaWAN(ChirpStack)·Modbus TCP·MQTT 등 네트워크로 붙는 장치는 어느 설치 방식에서든 동일하게 동작합니다.

### 지원

*   [AoT on GitHub](https://github.com/AoT-inc/AoT)
*   [AoT Wiki](https://github.com/AoT-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)
*   [포럼](https://forum.radicaldiy.com)
*   [자주 묻는 질문](https://forum.radicaldiy.com/docs?category=23&tags=aot)

