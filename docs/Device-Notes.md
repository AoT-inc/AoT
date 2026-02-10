이 정보는 최신 정보가 아닐 수 있으므로, 항상 제조업체의 권장 사항을 참조하고 그들의 장치를 작동시키는 지침을 따르십시오.

## 엣지 감지

신호 변화(예: 회로를 완성하는 단순 스위치)를 감지하려면 엣지 감지가 필요합니다. 상승 엣지(LOW에서 HIGH로), 하강 엣지(HIGH에서 LOW로) 또는 둘 다를 감지하여 동작이나 이벤트를 트리거할 수 있습니다. 신호를 감지하기 위해 선택된 GPIO는 적절한 저항기를 사용하여 GPIO를 5볼트로 풀업하거나 접지로 풀다운해야 합니다. 안전상의 이유로 내부 풀업 또는 풀다운 저항기를 활성화하는 옵션은 사용할 수 없습니다. GPIO를 풀업 또는 풀다운하려면 자체 저항기를 사용하십시오.

엣지 감지에 사용할 수 있는 장치의 예: 단순 스위치 및 버튼, PIR 모션 센서, 리드 스위치, 홀 효과 센서, 플로트 스위치 등.

## 디스플레이

지원되는 디스플레이는 몇 가지에 불과합니다. I2C 백팩이 있는 16x2 및 20x4 문자 LCD 디스플레이와 [128x32](https://www.adafruit.com/product/931) / [128x64](https://www.adafruit.com/product/931) OLED 디스플레이가 지원됩니다. 아래 이미지는 I2C 백팩이 있는 호환 가능한 디바이스 유형입니다. 자세한 내용은 [지원되는 기능](Supported-Functions.md)을 참조하십시오.

![image4](images/LCD-front-back.jpg)

## 라즈베리 파이

라즈베리 파이는 CPU/GPU의 온도를 측정하는 BCM2835 SoC에 통합된 온도 센서를 가지고 있습니다. 이는 AoT에서 가장 쉽게 설정할 수 있는 센서로, 즉시 사용할 수 있습니다.

## AM2315

이 [AM2315] 센서가 Rpi3 하드웨어 I2C에서 신뢰할 수 없는 이유를 알아냈습니다. 이는 BCM2835 클럭 스트레칭 문제(하드웨어 버그: [raspberrypi/linux\#254](https://github.com/raspberrypi/linux/issues/254))를 싫어하는 여러 I2C 장치 중 하나입니다. 웨이크업 시도가 일관되게 실패합니다. 비트스트림을 스니퍼로 확인한 결과, 센서가 20번 시도 중 한 번(또는 전혀) 응답할 수 있지만 단일 바이트만 반환되는 것을 확인했습니다. 해결책은 I2C 버스의 소프트웨어 구현을 사용하는 것입니다. 3.3v에 4.7k 풀업 저항기를 추가하고 i2c\_gpio 디바이스 오버레이를 설치해야 합니다. 이제 잘 작동하며, 몇 일을 실행해도 CRC 오류가 사라지고 매번 정확한 판독값을 얻을 수 있습니다. 센서의 전원을 조정할 필요도 없습니다.

소프트웨어 I2C를 활성화하려면 `/boot/config.txt`에 다음 줄을 추가하십시오:

`dtoverlay=i2c-gpio,i2c_gpio_sda=23,i2c_gpio_scl=24,i2c_gpio_delay_us=4`

재부팅 후, /dev/i2c-3에 새로운 I2C 버스가 생성되며, SDA는 핀 23(BCM), SCL은 핀 24(BCM)에 있습니다. 장치를 연결하기 전에 적절한 풀업 저항기를 추가하십시오.

## K-30

![image5](images/Sensor-K30-01.jpg)

K-30을 연결할 때는 역전압 보호가 없으므로 잘못된 연결이 센서를 손상시킬 수 있으니 매우 주의하십시오.

라즈베리 파이에 대한 배선 지침은 [여기](https://www.co2meter.com/blogs/news/8307094-using-co2meter-com-sensors-with-raspberry-pi)를 참조하십시오.

## USB 장치의 재부팅 후 지속성

GitHub의 [(#547) Theoi-Meteoroi](https://github.com/aot-inc/AoT/issues/547#issuecomment-428752904)로부터:

USB-to-serial 인터페이스(CP210x)와 같은 USB 장치를 사용하여 센서를 연결하는 것은 편리하지만, 시스템이 재부팅될 때 여러 장치가 있을 경우 문제가 발생할 수 있습니다. 재부팅 후 장치가 동일한 이름으로 유지된다는 보장이 없습니다. 예를 들어, 센서 A가 /dev/ttyUSB0이고 센서 B가 /dev/ttyUSB1인 경우, 재부팅 후 센서 A는 /dev/ttyUSB1이 되고 센서 B는 /dev/ttyUSB0이 될 수 있습니다. 이는 AoT가 잘못된 장치에서 측정을 쿼리하게 하여 잘못된 측정값을 초래할 수 있습니다. 아래 지침을 따라 이 문제를 해결하십시오.

udev를 사용하여 커널에서 장치가 도착할 때 선택된 /dev/ttyUSBn에 연결된 지속적인 장치 이름('/dev/dust-sensor')을 생성합니다. 유일한 요구 사항은 USB 장치에서 반환되는 고유한 속성입니다. 일반적인 경우는 속성이 고유하지 않으며 VID와 PID만 남게 되는 것입니다. 이는 동일한 VID와 PID를 보고하는 다른 어댑터가 없는 한 괜찮습니다. 동일한 VID와 PID를 가진 여러 어댑터가 있는 경우, 고유한 속성이 있기를 바랍니다. 이 명령은 속성을 탐색합니다. 각 USB 장치에서 실행한 후 차이점을 비교하여 사용할 속성을 찾으십시오.

`udevadm info --name=/dev/ttyUSB0 --attribute-walk`

ZH03B의 시리얼 번호를 사용하여 USB 어댑터 시리얼 필드를 프로그래밍했습니다. 이렇게 하면 고유한 시리얼 번호가 보장됩니다.

```
pi@raspberry:~ $ udevadm info --name=/dev/ttyUSB0 --attribute-walk | grep serial
SUBSYSTEMS=="usb-serial"
ATTRS{serial}=="ZH03B180904"
ATTRS{serial}=="3f980000.usb"
```

이제 udev에 무엇을 해야 할지 알려줄 속성이 있습니다. /etc/udev/rules.d에 "99-dustsensor.rules"와 같은 이름의 파일을 생성합니다. 이 파일에서 udev에 이 장치가 연결될 때 생성할 장치 이름을 지시합니다:

`SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", ATTRS{serial}=="ZH03B180904" SYMLINK+="dust-sensor"`

새 규칙을 테스트하려면:

```
pi@raspberry:/dev $ sudo udevadm trigger
pi@raspberry:/dev $ ls -al dust-sensor
lrwxrwxrwx 1 root root 7 Oct 6 21:04 dust-sensor -> ttyUSB0
```

이제 먼지 센서가 연결될 때마다 /dev/dust-sensor에 나타납니다.

## 다이어그램

### DHT11 다이어그램

![Schematic-Sensor-DHT11-01](images/Schematic-Sensor-DHT11-01.jpg)

![Schematic-Sensor-DHT11-02](images/Schematic-Sensor-DHT11-02.png)

### DS18B20 다이어그램

![Schematic-Sensor-DS18B20-01](images/Schematic-Sensor-DS18B20-01.png)

![Schematic-Sensor-DS18B20-02](images/Schematic-Sensor-DS18B20-02.jpg)

![Schematic-Sensor-DS18B20-03](images/Schematic-Sensor-DS18B20-03.jpg)

### 라즈베리 파이와 릴레이 다이어그램

#### 라즈베리 파이, 4개의 릴레이, 4개의 아울렛, 1개의 DS18B20 센서

![Schematic: Pi, 4 relays, 4 outlets, and 1 DS18B20 sensor](images/Schematic-Pi-4-relays.png)

#### 라즈베리 파이, 8개의 릴레이, 8개의 아울렛

![Schematic: Pi, 8 relays, and 8 outlets](images/Schematic-Pi-8-relays.png)
