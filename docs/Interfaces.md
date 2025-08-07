## I2C 정보

I2C 인터페이스는 `raspi-config` 또는 `[기어 아이콘] -> 설정 -> Raspberry Pi` 페이지에서 활성화해야 합니다.

## 1-Wire 정보

1-Wire 인터페이스는 `raspi-config` 또는 `[기어 아이콘] -> 설정 -> Raspberry Pi` 페이지에서 활성화해야 합니다.

## UART 정보

[이 문서](http://www.co2meters.com/Documentation/AppNotes/AN137-Raspberry-Pi.zip)는 Raspberry Pi 버전 1 또는 2에서 UART를 구성하기 위한 특정 설치 절차를 제공합니다.

Raspberry Pi 2 이후 버전에서는 블루투스 추가로 인해 UART가 다르게 처리되므로, 다른 설정 지침이 필요합니다. Raspberry Pi 3 이상에서 AoT를 설치하는 경우 UART를 구성하려면 다음 단계를 수행하십시오:

`raspi-config` 실행

`sudo raspi-config`

`고급 옵션 -> 직렬`로 이동하여 비활성화합니다. 그런 다음 `/boot/config.txt`를 편집합니다.

`sudo nano /boot/config.txt`

"enable_uart=0"이라는 줄을 찾아 "enable_uart=1"로 변경한 후 재부팅합니다.