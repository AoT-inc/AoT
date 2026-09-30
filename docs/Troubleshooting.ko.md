!!! note
    "Docker에서의 문제 해결" 절을 뺀 이 문서의 나머지는 직접(네이티브) 설치를 기준으로 합니다. Docker에서는 그 절을 먼저 보십시오. 호스트에 `/opt/AoT`가 없고, `aotflask` 서비스나 `upgrade_post.sh`도 없습니다.

## 업그레이드 후 웹 UI에 접근할 수 없음

업그레이드 후 웹 UI에 접근할 수 없게 되는 데에는 여러 원인이 있을 수 있습니다. 버그는 발견되는 대로 지속적으로 수정되고 있습니다. 따라서 비슷한 증상에 대한 해결책이 담긴 오래된 GitHub 이슈나 포럼 게시물에 의존하지 마세요. 증상의 원인이 완전히 다른 것일 수 있기 때문입니다. 가장 먼저 해야 할 일은 업그레이드 로그(/var/log/aot/aotupgrade.log)에서 오류가 있는지 검토하는 것입니다. 다음으로, 아래 명령을 실행하여 업그레이드를 다시 시도해 볼 수 있습니다.

```bash
sudo /opt/AoT/aot/scripts/upgrade_post.sh
```

## 데몬이 실행되지 않음 { #daemon-not-running }

- 내비게이션 바 왼쪽 위의 브랜드(로고) 영역을 보세요. 이상이 있을 때만 색이 입혀집니다. 색이 없으면 데몬과 웹 앱이 모두 정상이고, **빨간색**이면 데몬이 멈춘 것이며, **회색**이면 브라우저가 웹 앱에 아예 닿지 못하는 것입니다. 화면은 60초마다 `/daemonactive`를 확인하므로, 상태가 바뀐 뒤 색이 바뀌기까지 최대 1분쯤 걸릴 수 있습니다.
- 데몬 실행 여부 확인: 터미널에서 `ps aux | grep aot_daemon.py` 를 실행하고 반환되는 항목이 있는지 확인하세요.
- 로그 확인: `관리 → 시스템 로그` 페이지나 /var/log/aot/ 에서 데몬 로그에 오류가 있는지 확인하세요. 문제가 업그레이드 이후에 시작되었다면 업그레이드 로그에서도 문제의 징후가 있는지 확인하세요.
- 위 제안들을 조사한 후에도 해결책을 찾지 못했다면 GitHub 이슈에서 열려 있는 이슈를 검색하거나 포럼에서 최근 이슈를 검색해 보세요.

## 잘못된 데이터베이스 버전 { #incorrect-database-version }

- `관리 → 시스템 정보` 페이지를 확인하세요.
- "데이터베이스 버전"이 보통 글자색으로 표시되면 올바른 버전입니다. 잘못된 버전은 빨간색으로 표시되고, 그 뒤에 버전이 올바르지 않다는 안내와 있어야 할 버전이 함께 나옵니다.
- 잘못된 데이터베이스 버전이란 AoT 설정 데이터베이스(`/opt/AoT/databases/aot.db`)에 저장된 버전이 AoT 설정 파일(`/opt/AoT/aot/config.py`)에서 정해진 최신 AoT 버전에 맞지 않는다는 것을 의미합니다.
- 이는 이전 데이터베이스 버전에서 새 버전으로 업그레이드하는 과정에서 발생한 오류나, AoT 업그레이드 과정에서 데이터베이스가 업그레이드되지 않은 경우로 인해 발생할 수 있습니다.
- 발생했을 수 있는 문제에 대해 업그레이드 로그를 확인하세요. 로그는 `/var/log/aot/aotupgrade.log` 에 있으며, (가능하다면) 웹 UI에서도 접근할 수 있습니다: `관리 → 시스템 로그` 를 열고 **로그** 목록에서 **AoT 업그레이드** 를 선택하세요.
- 때로는 문제가 즉시 나타나지 않을 수 있습니다. 최신 업그레이드 이전, 실제로는 여러 AoT 버전 전에 발생한 데이터베이스 문제를 겪고 있는 경우도 드물지 않습니다.
- 데이터베이스가 얼마나 많은 버전 상태에 있을 수 있는지의 특성상, 데이터베이스 문제를 바로잡는 것은 매우 어려울 수 있습니다.

기존 설정 없이 데이터베이스를 삭제하고 새로 시작하는 것이 훨씬 쉬울 수 있습니다. 다음 명령을 사용하여 데이터베이스 이름을 변경하고 웹 UI를 재시작하세요. 두 명령이 모두 성공하면 브라우저에서 웹 UI 페이지를 새로고침하여 새 데이터베이스를 생성하고 새 Admin 사용자를 만드세요.

```bash
mv /opt/AoT/databases/aot.db /opt/AoT/databases/aot.db.backup
sudo service aotflask restart
```

## UI 없이 백업 복원하기

예를 들어 오류로 인해 웹 UI에 접근할 수 없는 경우 명령줄에서 백업을 복원할 수 있습니다. 자세한 내용은 [백업 및 복원](https://github.com/AoT-inc/AoT/wiki/Backup-and-Restore)을 참조하세요.

## 문제 진단에 대한 추가 정보

문제 진단에 대한 자세한 내용은 [문제 진단](https://github.com/AoT-inc/AoT/wiki/Diagnosing-Issues)을 확인하세요.

## Docker에서의 문제 해결 { #docker }

Docker 설치본은 호스트에서 살필 것이 Docker 자체뿐입니다. 아래 명령은 체크아웃 디렉터리(`docker/`가 있는 곳)에서 실행하십시오.

**컨테이너가 떠 있는가?**

```bash
docker compose -f docker/docker-compose.prod.yml ps
```

`aot-app`(웹 UI), `aot_daemon`(제어 데몬), `aot_mcp`(외부 MCP 서버), `influxdb`(측정값) 네 서비스가 중요합니다. 계속 재시작되거나 종료된 서비스가 살펴볼 곳입니다. 위에서 설명한 브랜드 색도 이에 대응합니다. 빨간색은 `aot_daemon`이 멈춘 것, 회색은 `aot-app`에 닿지 못하는 것입니다.

**로그 보기**

```bash
docker compose -f docker/docker-compose.prod.yml logs --tail 200 aot-app
docker compose -f docker/docker-compose.prod.yml logs --tail 200 aot_daemon
```

`-f`를 붙이면 계속 따라갑니다. 웹 UI에 접속할 수 있다면 `관리 → 시스템 로그`에서도 같은 로그를 볼 수 있습니다.

**웹 UI가 열리지 않을 때: 포트 충돌.** 호스트 포트를 이미 다른 프로그램이 쓰고 있으면 `aot-app`이 "port is already allocated" 오류로 시작하지 못합니다. `docker/.env`에 비어 있는 포트를 지정하고 컨테이너를 다시 만드십시오.

```bash
# docker/.env
AOT_PORT=8090
docker compose -f docker/docker-compose.prod.yml up -d
```

그런 다음 `http://<호스트 IP 주소>:8090`으로 접속합니다.

**아키텍처 불일치.** 공식 이미지는 `linux/amd64`와 `linux/arm64`만 있습니다. 32비트 라즈베리 파이 OS(`armhf`)에서는 실행할 수 없으므로 그 장비에서는 직접 설치를 쓰십시오. `uname -m`으로 확인하십시오(`x86_64`, `aarch64`면 괜찮습니다).

**데이터는 어디에 있는가.** 데이터베이스·업로드 파일·백업·로그·사용자 스크립트는 체크아웃이 아니라 Docker 이름 있는 볼륨에 있습니다(`docker volume ls`). `docker compose down`, 이미지 업데이트, 컨테이너 재생성을 해도 남습니다.

!!! danger "`docker compose down -v`는 절대 실행하지 마십시오"
    `-v` 옵션은 이름 있는 볼륨을 지우며, 데이터베이스·업로드 파일·백업·InfluxDB 측정 이력이 함께 사라집니다. 되돌릴 방법이 없습니다. 스택을 멈추려면 `-v` 없이 `docker compose -f docker/docker-compose.prod.yml down`을, 서비스 하나만 다시 시작하려면 `docker compose -f docker/docker-compose.prod.yml restart aot_daemon`을 쓰십시오. 볼륨을 만지는 시도를 하기 전에는 먼저 백업을 받으십시오([업그레이드/백업/복원](Upgrade-Backup-Restore.md) 참고).

**업그레이드 이후.** 이전 버전으로 되돌리려면 `docker/.env`의 `AOT_IMAGE_TAG`를 이전 버전으로 바꾸고 `up -d`를 다시 실행하면 됩니다. [업그레이드/백업/복원](Upgrade-Backup-Restore.md#docker)을 참고하십시오.
