# 라즈베리 파이에 설치 { #top }

라즈베리 파이 한 대에 AoT 를 Docker 로 설치하고, 필요하면 같은 파이에서 [Matter](Matter.md) 컨트롤러까지 켜는 절차입니다.
Windows·Mac 의 Docker Desktop 설치는 [설치 가이드](guide/g03-install.md)에 있습니다. 이 페이지는 그 가이드와 같은 두 파일(설계도 `docker-compose.prod.yml`, 설정표 `.env`)을 쓰고, 다른 점만 따로 적습니다.

**왜 라즈베리 파이인가.** AoT 는 24시간 켜 두는 서버 프로그램입니다. 라즈베리 파이는 전기를 적게 쓰고, 전원이 들어오면 스스로 켜지며, Linux 라서 Matter 에 필요한 호스트 네트워크를 그대로 쓸 수 있습니다. macOS·Windows 의 Docker Desktop 에서는 Matter 가 동작하지 않습니다([Matter 요구 사항](Matter.md#host)).

## 준비 { #prepare }

| 항목 | 권장 | 이유 |
|---|---|---|
| 기종 | Raspberry Pi 4 또는 5, 메모리 **4 GB 이상**(8 GB 권장) | 웹 앱·데몬·MCP·InfluxDB 에 Matter 서버까지 한 대에서 돕니다 |
| 운영체제 | **Raspberry Pi OS (64-bit)**, Bookworm 이상. 화면 없이 쓸 거면 Lite | AoT 와 Matter 서버 이미지는 64비트(arm64)만 있습니다. 32비트 OS 에서는 뜨지 않습니다 |
| 저장장치 | USB 3 SSD(Pi 5 는 NVMe 도 가능). 최소 32 GB | 측정값 저장소가 계속 씁니다. SD 카드는 수명이 짧고 느립니다 |
| 전원 | 기종에 맞는 공식 전원 어댑터 | 전압이 모자라면 SSD·USB 장치가 끊깁니다 |
| 네트워크 | **유선 이더넷** | Matter 장치를 찾는 멀티캐스트가 Wi-Fi 보다 안정적입니다 |
| 블루투스 | Pi 4·5 내장 블루투스 | Matter **새** 장치를 블루투스로 처음 등록할 때만 씁니다. 다른 앱에서 공유받는 장치에는 필요 없습니다 |

Matter 를 쓸 거라면 파이를 **Matter 장치들과 같은 네트워크**(같은 공유기·같은 VLAN)에 둡니다. Thread 장치를 쓰려면 그 네트워크에 Thread 경계 라우터(HomePod, Apple TV, Nest Hub, SmartThings Station 등)가 이미 있어야 합니다. 파이가 그 역할을 하지는 않습니다.

## 1. 운영체제 굽기 { #os }

다른 컴퓨터에서 [Raspberry Pi Imager](https://www.raspberrypi.com/software/)로 SSD(또는 SD 카드)에 운영체제를 굽습니다.

1. 기종을 고르고, 운영체제는 **Raspberry Pi OS (64-bit)**(화면이 필요 없으면 **Raspberry Pi OS Lite (64-bit)**)를 고릅니다.
2. 굽기 전 **OS 사용자 지정** 설정에서 다음을 넣습니다.
    - 호스트 이름(예: `aot`) — 나중에 `aot.local` 로 찾을 수 있습니다
    - 사용자 이름과 비밀번호 — 직접 정하고, 다른 사람이나 AI 에게 알려 주지 않습니다
    - 로케일·시간대(예: `Asia/Seoul`)
    - **SSH 사용** 켜기(비밀번호 또는 공개 키)
3. 구운 저장장치를 파이에 꽂고, 랜선과 전원을 연결합니다. 처음 켜질 때는 몇 분 걸립니다.

다른 컴퓨터의 명령창에서 접속합니다(사용자 이름과 호스트 이름은 2단계에서 정한 것).

```bash
ssh <사용자>@aot.local
```

`aot.local` 을 찾지 못하면 공유기 관리 화면에서 파이의 IP 를 찾아 `ssh <사용자>@<IP>` 로 접속합니다. 이후 명령은 모두 이 SSH 창(파이 안)에서 실행합니다.

운영체제를 최신으로 올리고 다시 시작합니다.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

!!! tip "IP 를 고정해 두세요"
    브라우저로 접속할 주소가 바뀌지 않도록, 공유기 관리 화면에서 파이에 **고정 IP(DHCP 예약)** 를 걸어 두는 것을 권합니다.

## 2. Docker 설치 { #docker }

Docker 공식 설치 스크립트로 Docker Engine 과 Compose 플러그인을 설치합니다. Linux 에서는 Docker Desktop 이 아니라 Docker Engine 을 씁니다.

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

마지막 줄은 `sudo` 없이 `docker` 명령을 쓰게 합니다. **SSH 를 끊었다가 다시 접속**해야 적용됩니다. 다시 접속한 뒤 확인합니다.

```bash
docker version
docker compose version
```

두 명령 모두 버전을 출력하면 됩니다. Docker 는 부팅할 때 자동으로 시작됩니다.

## 3. 파일 받기 { #files }

[설치 가이드 2단계](guide/g03-install.md#step-2)와 같습니다. `<버전>` 은 [릴리스 페이지](https://github.com/AoT-inc/AoT/releases)의 **Latest** 번호입니다(앞의 `v` 를 뺀 숫자, 예: `26.09.08`).

```bash
mkdir -p ~/AoT/docker && cd ~/AoT/docker
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<버전>/docker/docker-compose.prod.yml
curl -fsSL -o .env https://raw.githubusercontent.com/AoT-inc/AoT/v<버전>/docker/.env.prod.example
```

Matter 를 쓸 거라면 두 파일을 더 받습니다. 호스트 점검 스크립트와, 블루투스로 새 장치를 등록할 때 겹쳐 쓰는 설정입니다.

```bash
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<버전>/aot/scripts/check_matter_host.sh
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<버전>/docker/docker-compose.matter-ble.yml
```

!!! note "Matter 가 들어간 릴리스부터"
    Matter 는 실험 기능이고, 위 두 파일은 Matter 가 들어간 릴리스부터 있습니다. `curl: (22) … 404` 가 나오면 그 버전에는 아직 Matter 가 없는 것입니다. 릴리스 노트에서 Matter 가 언급된 버전을 쓰세요.

`ls -a` 로 받은 파일이 모두 있는지 확인합니다.

## 4. 설정하고 켜기 { #start }

설정표를 엽니다.

```bash
nano .env
```

[설치 가이드 3단계](guide/g03-install.md#step-3)의 네 줄을 확인합니다. 라즈베리 파이에서는 `HARDWARE_PROFILE` 을 **`LOW`** 로 둡니다(일부 AI 부가 기능만 꺼지고, 센서 읽기·장치 제어는 같습니다).

| 줄 | 라즈베리 파이 값 |
|---|---|
| `AOT_IMAGE_TAG` | 받은 파일과 같은 버전 번호(앞의 `v` 없이) |
| `AOT_PORT` | `8084` |
| `TZ` | 현장 시간대(예: `Asia/Seoul`) |
| `HARDWARE_PROFILE` | `LOW` |

`Ctrl+O`, `Enter` 로 저장하고 `Ctrl+X` 로 나옵니다. 그리고 켭니다.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

처음에는 이미지를 받느라 몇 분 걸립니다. `aot-app`, `aot_daemon`, `aot_mcp`, `influxdb` 네 개가 모두 `Up` 이면 됩니다.

다른 컴퓨터의 브라우저에서 `http://aot.local:8084`(또는 `http://<파이 IP>:8084`)를 엽니다. **`https` 가 아니라 `http`** 입니다. 첫 관리자 계정 만들기와 동작 확인은 [설치 가이드 5~6단계](guide/g03-install.md#step-5)와 같습니다.

!!! danger "볼륨을 지우지 마세요"
    멈출 때는 `docker compose -f docker-compose.prod.yml down` 만 씁니다. `down -v` 나 볼륨 지우기는 설정과 측정값을 모두 지웁니다.

## 5. 정전 뒤 다시 돌기 { #power }

라즈베리 파이는 전원이 들어오면 스스로 켜지고, Docker 는 부팅할 때 시작되며, AoT 컨테이너는 Docker 가 켜지면 다시 뜹니다. 그래서 Windows·Mac 처럼 따로 할 설정([설치 가이드 7단계](guide/g03-install.md#step-7))이 없습니다.

설치가 끝나면 **전원을 뽑았다가 다시 꽂아** 확인합니다. 몇 분 뒤 브라우저에서 AoT 가 다시 열리면 됩니다.

!!! warning "전원을 그냥 뽑아 끄지는 마세요"
    정전은 어쩔 수 없지만, 일부러 끌 때는 `sudo shutdown -h now` 로 끈 뒤 전원을 뺍니다. 쓰는 중에 전원이 끊기면 저장장치가 손상될 수 있습니다. 정전이 잦은 곳이면 UPS 를 권합니다.

## 6. Matter 켜기(선택) { #matter }

Matter 장치를 AoT 로 가져올 때만 합니다. 자세한 동작은 [Matter](Matter.md) 페이지에 있습니다. 이 페이지의 Docker 설치가 아니라 네이티브(`/opt/AoT`)로 설치한 파이라면 [네이티브 설치에서 시작](Matter.md#native)을 따릅니다.

### 6-1. 호스트 점검 { #matter-check }

점검 스크립트는 설정을 **읽기만** 하고 바꾸지 않습니다. 문제가 있으면 고치는 명령을 함께 출력합니다.

```bash
cd ~/AoT/docker
bash check_matter_host.sh
```

각 줄은 `OK`, `WARN`, `FAIL` 로 시작합니다. `FAIL` 부터 고치고, 해당되는 `WARN` 을 고칩니다. 랜선과 Wi-Fi 가 둘 다 연결돼 있으면 Matter 장치와 같은 네트워크 쪽을 `--iface eth0` 처럼 지정합니다.

라즈베리 파이에서 흔한 항목:

- **IPv6 꺼짐·라우터 광고 미수신**: Raspberry Pi OS 는 기본으로 IPv6 가 켜져 있습니다. 꺼져 있다면 스크립트가 출력하는 명령대로 켜고, 다시 시작한 뒤에도 유지되도록 저장합니다.
- **`ra_routes` 경고**: Thread 경계 라우터가 없는 네트워크에서는 정상입니다. Thread 장치를 쓸 때만 고칩니다.
- **`mdns_5353`**: 다른 프로그램(예: `avahi-daemon`)이 5353 포트를 써도 괜찮습니다. 정보로만 보여 줍니다.

### 6-2. Matter 서버 켜기 { #matter-enable }

`.env` 에서 Matter 줄의 앞에 붙은 `#` 을 지워 켭니다.

```
COMPOSE_PROFILES=matter
```

`MATTER_LOG_LEVEL` 은 `info` 그대로 둡니다. `debug` 로 올리면 서버가 Wi-Fi 비밀번호를 로그에 그대로 남깁니다. 저장하고 다시 올립니다.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

`matter_server` 와 `matter_socket` 이 추가로 `Up` 이면 됩니다. 브라우저에서 **관리 → 시스템 관리 → 일반 설정** 의 **Matter 사용 (실험)** 을 켜고 저장합니다. 설정 메뉴에 나타난 **Matter** 를 열어 서버가 연결됨으로 나오는지 확인합니다.

### 6-3. 블루투스로 새 장치 등록(선택) { #matter-ble }

다른 앱(Apple Home, Google Home, SmartThings 등)에서 **공유받는** 장치만 쓴다면 이 단계는 필요 없습니다. 상자에서 막 꺼낸 장치를 AoT 로 바로 등록할 때만 합니다.

블루투스 서비스를 켜고 점검합니다.

```bash
sudo systemctl enable --now bluetooth
bash check_matter_host.sh --ble
```

`ble_` 로 시작하는 줄이 `OK` 가 되면, 앞으로는 **두 파일을 함께** 써서 올립니다.

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.matter-ble.yml up -d
```

!!! warning "블루투스를 쓰기로 했다면 명령에 두 파일을 항상 함께"
    나중에 `docker compose -f docker-compose.prod.yml up -d` 만 다시 실행하면 블루투스 설정이 빠진 채로 Matter 서버가 다시 만들어집니다. 업그레이드할 때도 두 파일을 함께 씁니다.

### 6-4. 장치 추가 { #matter-add }

[Matter 페이지](Matter.md#add-shared)대로, 기존 앱에서 장치를 공유해 받은 페어링 코드를 **관리 → 시스템 관리 → Matter** 의 **공유된 장치 추가**에 넣습니다.

## 업그레이드 { #upgrade }

[Docker 배포판 업그레이드](Upgrade-Backup-Restore.md#docker)와 같습니다. 새 버전의 `docker-compose.prod.yml` 을 받고 `.env` 의 `AOT_IMAGE_TAG` 를 같은 번호로 바꾼 뒤 `pull` 과 `up -d` 를 합니다. Matter 서버 버전은 자동으로 올라가지 않으며 `.env` 의 `MATTER_SERVER_TAG` 로 정합니다.

## 안 될 때 { #trouble }

| 증상 | 원인 | 해결 |
|---|---|---|
| `no matching manifest for linux/arm/v7` 등 이미지를 받지 못함 | 32비트 운영체제 | **64-bit** Raspberry Pi OS 로 다시 굽습니다. `uname -m` 이 `aarch64` 여야 합니다 |
| `permission denied ... docker.sock` | `docker` 그룹 적용 전 | SSH 를 끊고 다시 접속합니다 |
| 브라우저가 열리지 않음 | 주소·포트가 틀리거나 아직 시작 중 | `ps` 로 네 개가 `Up` 인지, `http://<파이 IP>:8084` 인지 확인 |
| 느리거나 컨테이너가 자꾸 다시 시작됨 | 메모리 부족 | `free -h` 로 확인. 4 GB 미만이면 큰 기종을 쓰거나 Matter 를 끕니다 |
| 전원을 다시 넣은 뒤 USB SSD 를 못 찾음 | 전원 부족 | 공식 전원 어댑터를 쓰고, SSD 가 전원을 많이 먹으면 전원이 따로 있는 USB 허브를 씁니다 |
| 설정 > Matter 에 서버 연결 안 됨 | `COMPOSE_PROFILES=matter` 가 빠졌거나 `matter_server` 가 멈춤 | `.env` 확인 후 `up -d`, `docker compose -f docker-compose.prod.yml logs matter_server` |
| 장치를 찾지 못함(시간 초과) | 파이와 장치가 다른 네트워크이거나 IPv6·멀티캐스트 문제 | `check_matter_host.sh` 다시 실행. 메시 Wi-Fi 의 멀티캐스트 최적화를 끕니다 |
| 블루투스 등록이 검색 시간 초과로 끝남 | 블루투스가 꺼져 있거나 `-f docker-compose.matter-ble.yml` 없이 올림 | `check_matter_host.sh --ble` 확인 후 두 파일로 `up -d` |

## 도우미 AI 에게 { #for-ai }

- 사용자는 라즈베리 파이(64비트 Raspberry Pi OS)에 SSH 로 접속해 Docker Engine 으로 설치합니다. Docker Desktop 명령을 주지 마세요.
- 설치 폴더는 `~/AoT/docker`, compose 파일은 `docker-compose.prod.yml` 이고, Matter 블루투스를 쓰면 `docker-compose.matter-ble.yml` 을 항상 함께 씁니다.
- `down -v`·볼륨 지우기·`docker system prune --volumes` 를 권하지 마세요.
- `MATTER_LOG_LEVEL` 을 `debug` 로 올리라고 권하지 마세요(Wi-Fi 비밀번호가 로그에 남습니다).
- 페어링 코드, Wi-Fi 비밀번호, 관리자 비밀번호를 묻지 마세요.
