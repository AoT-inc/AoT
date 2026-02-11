# Docker

이 문서는 AoT를 Docker 컨테이너에서 모든 기능이 작동하도록 실행하는 방법을 안내합니다. 시스템의 많은 부분이 작동하지만, 일부는 아직 완벽하지 않습니다.

***현재 실험적 기능입니다***

Docker 관련 문제로 GitHub 이슈를 제출하지 마세요. 또한 이 기능이 계속 일관성을 유지한다고 기대하지 마세요(이전 빌드가 이후 빌드와 호환되지 않을 수 있습니다).

## 설치

### 참고 사항

다음 환경에서 테스트되었습니다:

- Raspberry Pi (Raspberry Pi OS)
- PC (Ubuntu Linux 20.04, 64비트)

Docker로 AoT를 실행할 때, 로컬 설치된 AoT가 동시에 실행 중이면 포트 충돌로 인해 실행할 수 없습니다. 아래 명령어로 로컬 AoT 서비스를 중지하세요(재부팅 전까지 중지됨).

```shell script
sudo service aot stop
sudo service aotflask stop
sudo service nginx stop
```

Pi Zero용으로 빌드할 경우, docker/influxdb/Dockerfile에서 `FROM influxdb:1.8.10`을 `FROM mendhak/arm32v6-influxdb`로 변경해야 합니다.

### 필수 프로그램 설치

운영체제에 맞는 Docker Engine을 https://docs.docker.com/engine/install/ 에서 설치하세요.

도커 명령어를 사용하려면 사용자 계정을 docker 그룹에 추가하세요.

```
sudo usermod -aG docker $USER
```

그룹 변경을 적용하려면 로그아웃 후 다시 로그인하세요.

### 설정

docker-compose.yaml 파일에서 TZ=America/New_York 부분(2곳)을 자신의 시간대로 변경하세요. 이 설정은 aot_daemon과 aot_flask 아래에 있습니다.

### 빌드 및 시작

```shell script
cd AoT
docker compose up --build -d
```

### 접속

빌드가 성공하면 https://127.0.0.1 에서 AoT에 접속할 수 있습니다.

## 가상 머신

일관성을 위해 Windows, Mac, Linux에서 실행 가능한 가상 머신을 사용하여 Docker 컨테이너에 AoT를 설치하는 방법을 안내합니다. 다양한 리눅스 배포판에서 발생할 수 있는 문제를 줄이고 테스트 환경을 통일할 수 있습니다. 위 설치 방법에 문제가 있다면 아래 방법을 시도하세요.

### VirtualBox 설치

https://www.virtualbox.org/wiki/Downloads 에서 VirtualBox를 설치하세요.

### Raspbian 다운로드

[Raspberry Pi OS (64-bit) with Desktop ISO](https://www.raspberrypi.com/software/operating-systems/) 또는 Xubuntu 등 다른 Debian 기반 리눅스 ISO를 다운로드하세요.

### 새 가상 머신 생성

- VirtualBox를 실행하고 ```New``` 클릭
- 이름 입력, Type을 ```Linux```, Version을 ```Debian (64-bit)```로 변경 후 Next
- 최소 1024MB RAM 할당 후 Next
- ```Create a virtual hard disk now``` 선택 후 Next
- ```VDI (VirtualBox Disk Image)``` 선택 후 Next
- ```Dynamically allocated``` 선택 후 Next
- 최소 12GB 할당 후 Create
- 생성된 가상 머신 선택 후 ```Settings``` 클릭
- 왼쪽 메뉴에서 ```Storage``` 클릭, ```Controller: IDE``` 아래 ```Empty``` 선택, 오른쪽 ```Attributes```에서 디스크 아이콘 클릭 후 ```Choose Virtual Optical Disk File``` 선택, 다운로드한 ISO 선택
- OK 클릭하여 설정 종료
- Start 클릭하여 가상 머신 시작

### Raspbian 설치

- 가상 머신 시작 시 ```Debian GNU/Linux menu (BIOS mode)```에서 ```install``` 선택
- 언어 선택 후 Enter
- ```Partition discs``` 화면에서 ```Guided - use entire disk``` 선택 후 Enter
- 표시된 디스크 선택 후 Enter
- ```All files in one partition (recommended for new users)``` 선택 후 Enter
- ```Finish partitioning and write changes to disk``` 선택 후 Enter
- ```<Yes>``` 선택 후 Enter
- ```Install the GRUB boot loader on a hard disk``` 화면에서 ```<Yes>``` 선택 후 Enter
- ```/dev/sda``` 선택 후 Enter
- 설치가 완료될 때까지 기다림
- ```Finish the installation``` 화면에서 ```<Continue>``` 선택 후 Enter
- 재부팅 후 Raspbian 데스크탑이 나타나면 안내에 따라 설치 완료
- 터미널을 열고 ```sudo apt update && sudo apt upgrade```로 시스템 소프트웨어를 최신 버전으로 업그레이드하세요(그래픽 설치 과정에서 이미 했다면 생략 가능).

### Docker 컨테이너에 AoT 설치

Raspbian에서 터미널을 열고 아래 명령어를 실행하세요.

#### 최신 AoT 릴리즈 가져오기 및 압축 해제

```shell script
sudo apt-get install git
git clone https://github.com/aot-inc/AoT
```

이후 [필수 프로그램 설치](#install-prerequisites) 및 [빌드 및 시작](#build-and-start) 안내를 따르세요.

### Grafana

Grafana를 활성화했다면 http://127.0.0.1:3000 에서 접속할 수 있습니다.

기본 사용자명은 admin, 비밀번호도 admin입니다.

## Docker 관리

### 재빌드

코드를 변경하고 컨테이너에 적용하려면 재빌드 및 재시작만 하면 됩니다.

```shell script
cd ~/AoT
```

### 중지

실행 중인 컨테이너를 중지하고 시스템 시작 시 자동 실행을 방지하려면:

```shell script
cd ~/AoT/docker
docker compose down
```

### 재시작

컨테이너가 중지되었거나 내려갔다면, 다시 올릴 수 있습니다. 이전에 빌드가 완료된 상태여야 합니다.

```shell script
cd ~/AoT
docker compose up -d
```

### 정리

모든 컨테이너를 내리고 이미지 데이터를 삭제하려면(볼륨 데이터는 유지):

```shell script
cd ~/AoT
docker compose down
docker system prune -a
```

## Grafana 및 Telegraf

Grafana와 Telegraf 구현에 참고한 가이드: https://towardsdatascience.com/get-system-metrics-for-5-min-with-docker-telegraf-influxdb-and-grafana-97cfd957f0ac

### Grafana 및 Telegraf 활성화

기본적으로 Grafana와 Telegraf는 비활성화되어 있습니다. 활성화하려면 docker-compose.yml에서 "Uncomment the following blocks and rebuild to enable Grafana and/or Telegraf" 문구 아래 블록을 주석 해제하고 저장 후 재빌드하세요.

Grafana는 http://127.0.0.1:3000 에서 접속할 수 있습니다.

### AoT를 데이터 소스로 추가

로그인 후 관리자 비밀번호를 변경한 뒤 "Add data source" 선택, "InfluxDB" 선택 후 아래 정보 입력:

-  Name: InfluxDB-aot
-  Default: Checked
-  URL: http://aot_influxdb:8086
-  Database: aot_db
-  User: aot
-  Password: mmdu77sj3nIoiajjs

"Save and Test" 클릭

### Telegraf 대시보드 추가

좌측 상단 Dashboards에 마우스 오버 후 Import 클릭. Grafana Dashboard URL에 928 입력 후 Load 클릭. ```InfluxDB telegraf``` 필드에서 InfluxDB-aot 선택 후 Import 클릭. 대시보드가 로드되면 상단의 ```Save Dashboard``` 클릭.

