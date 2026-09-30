## I2C 정보

I2C 인터페이스는 `raspi-config` 또는 `관리 -> 시스템 관리 -> 라즈베리파이` 페이지에서 활성화해야 합니다(Docker에서는 사용할 수 없습니다). 변경 내용은 `관리 -> 시스템 재시작` 후에 적용됩니다.

## 1-Wire 정보

1-Wire 인터페이스는 `raspi-config` 또는 `관리 -> 시스템 관리 -> 라즈베리파이` 페이지에서 활성화해야 합니다(Docker에서는 사용할 수 없습니다). 변경 내용은 `관리 -> 시스템 재시작` 후에 적용됩니다.

## UART 정보

[이 문서](http://www.co2meters.com/Documentation/AppNotes/AN137-Raspberry-Pi.zip)는 Raspberry Pi 버전 1 또는 2에서 UART를 구성하기 위한 특정 설치 절차를 제공합니다.

Raspberry Pi 2 이후 버전에서는 블루투스 추가로 인해 UART가 다르게 처리되므로, 다른 설정 지침이 필요합니다. Raspberry Pi 3 이상에서 AoT를 설치하는 경우 UART를 구성하려면 다음 단계를 수행하십시오:

`raspi-config` 실행

`sudo raspi-config`

Raspberry Pi OS Bookworm 이상에서는 직렬 포트 설정이 둘로 나뉩니다. 직렬 로그인 셸(포트 위의 텍스트 콘솔)은 **꺼야** 하고, 직렬 하드웨어(UART 자체)는 **켜야** 합니다. `관리 -> 시스템 관리 -> 라즈베리파이` 페이지에서는 "직렬 로그인 셸"과 "직렬 하드웨어"로 표시됩니다. 명령줄에서는 다음과 같이 합니다.

`sudo raspi-config nonint do_serial_cons 1` (로그인 셸 끄기)

`sudo raspi-config nonint do_serial_hw 0` (직렬 하드웨어 켜기)

`raspi-config`에서는 `Interface Options -> Serial Port`에서 로그인 셸은 No, 직렬 하드웨어는 Yes로 답합니다.

설정 파일은 Bookworm에서 `/boot/firmware/config.txt`입니다(이전 버전은 `/boot/config.txt`). 직접 고치려면 `enable_uart=1`이 들어 있는지 확인한 뒤 재부팅합니다.