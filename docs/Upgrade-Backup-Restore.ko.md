## 업그레이드

페이지\: `관리 → 업그레이드`

이미 AoT가 설치되어 있다면 웹 인터페이스의 업그레이드 옵션을 사용하거나(권장) 터미널에서 다음 명령을 실행하여 최신 [AoT 릴리스](https://github.com/AoT-inc/AoT/releases)로 업그레이드할 수 있습니다. 업그레이드 과정의 로그는 ``/var/log/aot/aotupgrade.log`` 에 생성되며 `관리 → 시스템 로그` 페이지에서도 확인할 수 있습니다.

```bash
sudo aot-commands upgrade-aot
```

## Docker 배포판 업그레이드 { #docker }

페이지\: `관리 → 업그레이드`

Docker 배포판은 디스크의 파일을 갈아치우는 방식으로 업그레이드하지 않습니다. 발행된 이미지를 받아 컨테이너를 다시 만드는 것이 업그레이드입니다. 업그레이드 페이지는 이를 감지해 다르게 동작합니다.

**업데이트 가용 여부는 릴리스 목록이 아니라 컨테이너 레지스트리에서 판정합니다.** 릴리스 태그는 밀자마자 GitHub에 생기지만, 이미지는 멀티아키텍처 빌드가 끝나는 몇 분 뒤에야 받을 수 있습니다. 그래서 실제로 발행된 이미지를 레지스트리에 물어봅니다. 화면에 "업데이트 있음"이 뜨면 지금 바로 설치할 수 있는 상태입니다.

**인터넷 테스트는 하지 않습니다.** 직접 설치의 업그레이드 화면은 먼저 [일반 설정](Configuration-Settings.md#general-settings)의 *인터넷 테스트 IP 주소·포트·타임아웃*으로 인터넷이 닿는지 확인합니다. Docker의 업그레이드 화면은 이 검사를 하지 않으므로, 이 세 설정은 Docker에서 아무 영향이 없습니다.

### 업데이터 서비스 (선택)

원클릭 업데이트와 자동 업데이트에는 작은 부가 서비스가 필요합니다. 없어도 업그레이드 페이지는 정확한 상태를 보여주며, 업데이트는 호스트에서 직접 적용합니다:

```bash
docker compose -f docker/docker-compose.prod.yml pull
docker compose -f docker/docker-compose.prod.yml up -d
```

앱은 자기 자신을 업데이트할 수 없습니다. 컨테이너를 다시 만드는 순간 그 명령을 실행하던 프로세스까지 함께 교체되어 명령이 중간에 죽기 때문입니다. 그래서 이 일은 별도 서비스가 맡습니다.

활성화하려면 ``docker/.env`` 에 두 값을 넣습니다:

```bash
AOT_PROJECT_DIR=/opt/AoT                  # 이 체크아웃의 절대 경로
AOT_HEALTH_KEY=$(openssl rand -hex 24)    # 업데이터가 새 빌드를 확인하는 데 쓰는 키
```

그리고 업데이터 오버레이와 함께 기동합니다:

```bash
docker compose -f docker/docker-compose.prod.yml \
               -f docker/docker-compose.updater.yml up -d
```

!!! warning "이 서비스는 호스트의 Docker 를 조작할 수 있습니다"
    업데이터는 Docker 소켓을 쥐고 있으며, 이는 호스트의 root 권한과 같습니다. 일부러 아주 작게 만들었고 공식 AoT 이미지만 받아오지만, 그 점을 받아들일 때만 켜십시오. 특권 컨테이너를 두고 싶지 않다면 같은 일을 호스트의 systemd 타이머로 할 수 있습니다 — ``install/aot-docker-update.service`` 를 참고하십시오.

### 업데이트 중에 일어나는 일

1. 먼저 데이터베이스와 업로드 파일을 백업합니다.
2. 새 이미지를 내려받습니다.
3. 데몬을 정상 종료합니다 — 종료 전에 출력을 지정된 정지 상태로 전환할 시간을 줍니다.
4. 새 이미지로 컨테이너를 다시 만들고, 스키마는 자동으로 마이그레이션됩니다.
5. 새 버전이 **서비스 중이며 마이그레이션까지 반영됐다**고 보고해야 성공으로 봅니다.
6. 정상적으로 뜨지 않으면 이전 버전으로 자동 복구합니다. 마이그레이션이 이미 실행된 경우에는 데이터베이스도 함께 되돌립니다 — 이미지만 되돌리면 옛 코드가 새 스키마 위에서 도는 상태가 되기 때문입니다.

진행 상황은 업그레이드 페이지에 실시간으로 표시되고, 끝난 뒤에는 마지막 시도 결과가 남습니다.

!!! note "업데이트 중에는 제어가 멈춥니다"
    컨테이너가 다시 뜨는 동안 출력은 제어되지 않습니다. 보통 몇 분이며, 그 시점에 진행 중이던 관수·보광·시퀀스는 중단됩니다.

### 자동 업데이트

업데이터 서비스가 떠 있으면 업그레이드 페이지에 다음이 나타납니다.

- **업데이트 자동 설치** — 기본은 꺼짐입니다.
- **업데이트 시각** — 매일 이 시각에 한 번 확인합니다. `관리 → 시스템 관리 → 일반 설정` 의 **시스템 시간대** 에 설정한 현지 시각 기준입니다.

시각이 되면 레지스트리를 확인해 새 버전이 발행돼 있으면 버튼을 눌렀을 때와 똑같이 설치합니다. 새 버전이 없으면 아무것도 하지 않고 확인했다는 기록만 로그에 남깁니다.

**중요한 작동이 없는 시각을 고르십시오.** 아직 "작동 중이면 연기" 기능은 없습니다. 지정한 시각이 되면 출력이 켜져 있더라도 컨테이너를 다시 만듭니다.

### 데이터

데이터베이스, 업로드 파일, 지도 오버레이 이미지, 시설 3D 모델, 백업, 사용자 스크립트, 측정값(InfluxDB)은 모두 Docker 볼륨에 있어 이미지를 교체해도 보존됩니다. 이전 버전으로 되돌리려면 ``docker/.env`` 의 ``AOT_IMAGE_TAG`` 를 바꾸고 컨테이너를 다시 만들면 됩니다 — 마지막으로 정상 동작한 태그는 업데이터가 같은 파일에 ``AOT_IMAGE_TAG_PREV`` 로 기록해 둡니다.

## 백업 / 복원 { #backup-restore }

페이지\: `관리 → 백업 복원`

시스템이 업그레이드되거나 웹 인터페이스의 ``관리 → 백업 복원`` 페이지에서 지시를 받으면 /var/AoT-backups 에 백업이 생성됩니다.

백업을 복원해야 하는 경우 ``관리 → 백업 복원`` 페이지에서 복원할 수 있습니다(권장). 복원하려는 백업을 찾아 그 옆의 **백업 복원** 버튼을 누르세요. 웹 인터페이스에 접근할 수 없는 경우 명령줄을 통해서도 복원을 시작할 수 있습니다. 다음 명령을 사용하여 복원을 시작하세요. \[backup_location\] 에는 복원할 백업의 전체 경로를 입력해야 합니다(예: 따옴표 없이 "/var/AoT-backups/AoT-backup-2018-03-11\_21-19-15-5.6.4/").

```bash
sudo aot-commands backup-restore [backup_location]
```

!!! 참고
    웹 화면에서 백업을 내려받거나 복원하는 것은 **관리자만** 할 수 있습니다. 백업에는 사용자 계정·역할·비밀번호 해시가 든 설정 데이터베이스가 들어 있고, 복원하면 사용자 계정과 역할도 백업 시점으로 돌아가기 때문입니다. 다른 역할에게는 **백업 다운로드**·**백업 복원** 버튼이 보이지 않습니다.


## Docker 배포판 백업 { #docker-backup }

Docker 에서는 `[톱니바퀴 아이콘] -> Backup Restore` 가 ``/var/AoT-backups``(네이티브 설치용)가 아니라 ``aot_backups`` 볼륨에 백업을 만듭니다. 이 백업은 시스템 전체가 아니라 **설정 단위** 백업입니다.

| | 들어 있는 것 | 들어 있지 않은 것 |
|---|---|---|
| **Docker** | 설정 데이터베이스(사용자·역할·장치·기능·대시보드), 업로드(노트·공지·시설·구역 사진), 시설 3D 모델, 지도 오버레이 이미지, 사용자 스크립트 | **InfluxDB 측정값**(센서 이력), 로그, ``custom_*`` 확장 모듈(호스트 폴더) |
| **네이티브** | ``env``·``cameras`` 를 뺀 설치 폴더 전체(데이터베이스·업로드·오버레이·스크립트) | **InfluxDB 측정값**(설치 폴더 밖의 시스템 서비스) |

업데이터가 업데이트 전에 만드는 백업도 같은 목록을 씁니다.

!!! warning "복원해도 측정값은 돌아오지 않습니다"
    백업을 복원하면 설정이 그 시점으로 돌아갑니다. 센서 이력은 지금 상태 그대로 남습니다. 이력을 지키려면 아래 두 방법 중 하나로 따로 백업하세요.

### 측정값

- **내보내기(데이터가 적거나 중간일 때):** `[톱니바퀴 아이콘] -> Export Import` 에서 측정값을 InfluxDB ZIP 으로 내보냅니다([내보내기/가져오기](Export-Import.md) 참고). 간단하지만 수년치 데이터에서는 느리고 큽니다.
- **볼륨 통째 복사(위험한 작업·이전·디스크 교체 전 권장):** 아래처럼 Docker 볼륨을 복사합니다. 측정값을 포함한 **전부**가 담깁니다.

### 볼륨 복사

```bash
# 0) 실제 볼륨 이름을 확인합니다. 접두어는 compose 프로젝트 이름
#    (compose 파일이 있는 폴더 이름, 기본값 "docker")입니다.
docker volume ls --format '{{.Name}}' | grep -E 'aot_|influxdb_'
P=docker            # <- 위에서 본 접두어로 바꾸세요
mkdir -p ~/aot-volume-backup && cd ~/aot-volume-backup

# 1) 쓰기 중인 서비스를 모두 멈춥니다(일관된 복사를 위해 InfluxDB 도 멈춰야 합니다).
docker compose -f /opt/AoT/docker/docker-compose.prod.yml stop

# 2) 볼륨마다 .tgz 하나로 묶습니다.
for v in aot_data aot_uploads aot_model_assets aot_geo_overlays aot_user_scripts influxdb_data influxdb_config; do
  docker run --rm -v ${P}_$v:/v:ro -v "$PWD":/out alpine tar czf /out/$v.tgz -C /v .
done

# 3) 다시 시작합니다.
docker compose -f /opt/AoT/docker/docker-compose.prod.yml up -d
```

복사본은 ``~/aot-volume-backup`` 에 생깁니다. 반드시 다른 장치로 옮겨 두세요 — 같은 디스크에 둔 백업은 디스크 고장을 막아 주지 못합니다.

### 복사본으로 복원

```bash
cd ~/aot-volume-backup
P=docker
docker compose -f /opt/AoT/docker/docker-compose.prod.yml stop
docker compose -f /opt/AoT/docker/docker-compose.prod.yml create   # 없는 볼륨을 빈 상태로 만듭니다
for v in aot_data aot_uploads aot_model_assets aot_geo_overlays aot_user_scripts influxdb_data influxdb_config; do
  docker run --rm -v ${P}_$v:/v -v "$PWD":/out alpine sh -c "rm -rf /v/* /v/.[!.]* 2>/dev/null; tar xzf /out/$v.tgz -C /v"
done
docker compose -f /opt/AoT/docker/docker-compose.prod.yml up -d
```

### 필요해지기 전에 복원을 시험해 두세요

여분의 기기에서, 또는 다른 프로젝트 이름(``docker compose -p restoretest ...``)으로 진행하세요. 운영 중인 스택에는 하지 마세요.

1. 스택을 한 번 띄워 볼륨을 만든 뒤 멈춥니다.
2. 그 프로젝트의 접두어로 위와 같이 ``.tgz`` 를 복원합니다.
3. 시작하고 평소 계정으로 로그인합니다.
4. 확인: 대시보드·장치가 있는지, 지도 오버레이 이미지가 보이는지, 그래프에 예전 측정값이 나오는지.

!!! danger "`docker compose down -v` 는 절대 실행하지 마세요"
    ``-v`` 는 스택의 이름 있는 볼륨을 전부 지웁니다. 데이터베이스, 업로드, 백업(``aot_backups``), **측정값**까지 확인 없이 한 번에 사라집니다. ``-v`` 없는 ``docker compose down`` 과 ``docker compose stop`` 은 안전합니다. 백업도 같은 스택의 볼륨에 있어 ``down -v`` 로 함께 지워지므로, 사본을 다른 곳에 두세요.
