# AoT

최신 버전: 26.09.05 · [English](README.md) · [사용자 매뉴얼](https://aot-inc.github.io/AoT/ko/) · [변경 이력](CHANGELOG.md)

**AoT 는 내 공간을 지도에 담고, 그곳의 기록과 장치를 연결합니다. 그리고 그 공간을 AI 가 사람과 함께 보고, 판단하고, 작업할 수 있게 만듭니다.**
오픈소스이며, 장치를 움직이는 일은 사용자가 승인해야 실행됩니다. 어떤 기능을 쓸지는 사용자가 정합니다.

## AoT 는 무엇인가

센서 값 하나만으로는 판단하기 어렵습니다. 그 센서가 어디에 있는지, 주변에 무엇이 있는지, 지금 무슨 작업 중인지 알아야 합니다. AoT 는 이런 정보를 함께 다룹니다. 사람은 화면에서 보고, AI 는 같은 내용을 MCP 로 읽습니다.

AoT 는 한 장소의 위치·환경 데이터를 모으고, 그 위에서 계획 수립·일상 운영·자동 제어를 제공합니다. 특정 용도나 장소에 매이지 않습니다.

## 주요 기능

- **제어.** Mycodo 에서 이어받은 입력·출력·함수 모델([유래](#유래) 참고). 다양한 센서·릴레이 지원, PID·시퀀스·타이머·조건 제어, InfluxDB 시계열 저장.
- **장치 연결.** LoRaWAN·Modbus TCP·MQTT·HTTP 로 붙는 네트워크 장치와, 라즈베리 파이 핀에 직접 연결한 센서·릴레이.
- **지도.** 대시보드의 지도 위젯에 장치·센서·시설·구역을 실제 위치대로 놓고 거기서 보고 조작할 수 있습니다. 시설은 윤곽을 그려 3D 로 볼 수 있고, 개구부 면적·방향·바람 방향을 제어에 쓸 수 있습니다. 지도를 쓰지 않는 구성도 가능합니다.
- **AI 연결.** Claude Desktop 등 [MCP](https://modelcontextprotocol.io) 를 지원하는 AI 앱을 연결하면, 그 AI 가 장치·측정값·구역·일정·노트를 조회해 상태를 진단하고 할 일을 제안합니다. 장치를 움직이는 일은 사용자가 승인해야 실행됩니다. 특정 AI 제공자에 묶이지 않고, AI 없이도 모든 기능이 동작합니다.

## 빠른 시작

**직접 설치** (Debian 계열 리눅스. 라즈베리 파이처럼 GPIO·I2C·1-Wire 핀이 있는 보드에 권장):

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

**Docker** (리눅스·macOS·Windows. 네트워크 장치만 쓸 수 있고 라즈베리 파이 핀은 못 씁니다):

```bash
git clone https://github.com/AoT-inc/AoT.git /opt/AoT
cd /opt/AoT
cp docker/.env.prod.example docker/.env   # AOT_IMAGE_TAG 를 릴리스 버전으로
docker compose -f docker/docker-compose.prod.yml up -d
```

설치가 끝나면 브라우저로 접속해(직접 설치 `https://<호스트>/`, Docker `http://<호스트>:8084/`) 관리자 계정을 만듭니다. 자세한 설치·업그레이드·백업·문제 해결은 [매뉴얼](https://aot-inc.github.io/AoT/ko/)에 있습니다. AoT 는 최소한의 익명 사용 통계를 보내며, [설정에서 끌 수 있습니다](https://aot-inc.github.io/AoT/ko/Configuration-Settings/).

## 다음에 볼 곳

- [소개(About)](https://aot-inc.github.io/AoT/ko/About/) — 기능이 어떻게 연결되는지.
- [ARCHITECTURE.md](ARCHITECTURE.md) — 프로세스·패키지·데이터 모델·의존 규칙, 한 장.
- [CONTRIBUTING.md](CONTRIBUTING.md) — 개발 환경·규약·CI 검사.
- [Issues](https://github.com/AoT-inc/AoT/issues) — 문의와 버그 신고. 보안 취약점은 [SECURITY.md](SECURITY.md) 절차로.

## 이 저장소에 대하여

- 프런트엔드 JavaScript 원본은 공개하지 않습니다. 이 저장소에는 빌드된 번들만 있고, Python·템플릿·스타일·테스트·마이그레이션은 전부 들어 있습니다. 서드파티 라이브러리는 각자의 라이선스로 포함됩니다.
- 매뉴얼은 `docs/` 를 mkdocs 로 빌드합니다. `docs/design/` 의 설계 문서는 작업 문서이며 매뉴얼에 포함되지 않습니다.
- 이전 2D 지도 기반 버전(v26.0.x)은 [legacy-2d](https://github.com/AoT-inc/AoT/tree/legacy-2d) 브랜치에 보존되어 있습니다. 현재 버전과 데이터가 호환되지 않으므로, 구버전을 유지할 설치본은 업그레이드하지 마세요.

## 유래

AoT 는 Kyle T. Gabriel 의 오픈소스 [Mycodo](https://github.com/kizniche/Mycodo) 를 고쳐 쓰는 데서 시작했습니다. 입력·출력·함수 제어 모델은 그대로 두고, 장치 목록 화면을 지도로 바꾸고 MCP 기반 AI, 시설 단위 환경 제어, LoRaWAN 장치 관리, 새 UI 를 더했습니다. 지금도 제어 모델의 토대는 Mycodo 이며, 그 기여에 감사드립니다.

## 라이선스

AoT 는 GNU 일반 공중 사용 허가서(GPL) 3버전 또는 그 이후 버전을 따르는 자유 소프트웨어입니다. [LICENSE.txt](LICENSE.txt) 를 참고하세요. 유용하게 쓰이길 바라며 배포하지만 어떤 보증도 없습니다.

이 소프트웨어에는 다른 곳에서 만든 소프트웨어가 함께 들어 있으며, 각각 자기 라이선스를 따릅니다. 전체 목록과 각 라이선스는 [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) 에 있습니다.
