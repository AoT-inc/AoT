## Built-In Inputs (System)

### AoT: AoT Version

- Manufacturer: AoT
- Measurements: Version as Major.Minor.Revision
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr></tbody></table>

### AoT: CPU Load

- Manufacturer: AoT
- Measurements: CPULoad
- Libraries: os.getloadavg()
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr></tbody></table>

### AoT: Free Space

- Manufacturer: AoT
- Measurements: Unallocated Disk Space
- Libraries: os.statvfs()
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr></tbody></table>

### AoT: Output State (On/Off)

- Manufacturer: AoT
- Measurements: Boolean

이 Input은 선택한 On/Off Output에 대해 0(off) 또는 1(on)을 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>On/Off Output Channel</td><td>Select Channel (Output_Channels)</td><td>측정할 Output 선택</td></tr></tbody></table>

### AoT: Server Ping

- Manufacturer: AoT
- Measurements: Boolean
- Libraries: ping

이 Input은 bash 명령 "ping -c [times] -w [deadline] [host]"를 실행해 호스트에 ping이 되는지 확인합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AoT: Server Port Open

- Manufacturer: AoT
- Measurements: Boolean
- Libraries: nc

이 Input은 bash 명령 "nc -zv [host] [port]"를 실행해 특정 포트의 호스트에 접근 가능한지 확인합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AoT: Spacer

- Manufacturer: AoT

Input 정리를 위한 구분자.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Color</td><td>Text
- Default Value: #000000</td><td>이름 텍스트 색상</td></tr></tbody></table>

### AoT: System and AoT RAM

- Manufacturer: AoT
- Measurements: RAM Allocation
- Libraries: psutil, resource.getrusage()
- Dependencies: [psutil](https://pypi.org/project/psutil)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>AoT Frontend RAM Endpoint</td><td>Text
- Default Value: https://127.0.0.1/ram</td><td>AoT 프런트엔드 RAM 사용량 조회 엔드포인트</td></tr></tbody></table>

### AoT: Test Input: Save your own measurement value

- Manufacturer: AoT
- Measurements: Variable measurements

이것은 임의의 값을 측정값으로 저장해 측정 데이터베이스에 기록할 수 있는 간단한 테스트 Input입니다. 입력이 Function에 제공하는 값을 완전히 제어할 수 있어 PID, Bang-Bang, Conditional Function 등 AoT의 다른 부분을 테스트하는 데 유용합니다. 참고 1: 각 채널의 Name과 Measurement Unit을 선택하고 저장하세요. 단위를 저장한 후에는 Convert Measurement 섹션에서 다른 단위로 변환할 수 있습니다. 참고 2: 측정값을 저장하기 전에 Input을 활성화하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Enter the Value you want to store as a measurement, then press Store Measurement.</td></tr><tr><td>Channel</td><td>Integer</td><td>측정값을 저장할 채널입니다.</td></tr><tr><td>Value</td><td>Decimal
- Default Value: 10.0</td><td>이 Input에 저장할 측정값입니다.</td></tr><tr><td>Store Measurement</td><td>Button</td><td></td></tr></tbody></table>

### AoT: Uptime

- Manufacturer: AoT
- Measurements: Seconds Since System Startup
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr></tbody></table>

### Linux: Bash Command

- Manufacturer: Linux
- Measurements: Return Value
- Interfaces: AoT

이 Input은 셸에서 명령을 실행하고 그 출력을 float 값으로 저장합니다. 단위 변환은 스크립트나 명령 안에서 수행하세요. 측정 항목/단위를 반드시 선택해야 합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Command Timeout</td><td>Integer
- Default Value: 60</td><td>프로세스를 종료하기 전에 명령 완료를 기다리는 시간</td></tr><tr><td>User</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>Current Working Directory</td><td>Text
- Default Value: /home/pi</td><td>셸 환경의 현재 작업 디렉터리</td></tr></tbody></table>

### Linux: Python 3 Code (v1.0)

- Manufacturer: Linux
- Measurements: Store Value(s)
- Interfaces: AoT
- Dependencies: [pylint](https://pypi.org/project/pylint)

값을 데이터베이스에 저장하려면 모든 채널에 Measurement Unit을 선택하고 저장해야 합니다. 코드는 AoT가 실행되는 것과 동일한 Python 가상환경에서 실행됩니다. 따라서 코드에서 사용할 Python 라이브러리는 이 환경에 설치해야 합니다. 이 virtualenv는 /opt/AoT/env에 있으며, 예를 들어 pip로 "my_library"를 설치하려면 "sudo /opt/AoT/env/bin/pip install my_library"를 실행합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>저장 시 pylint로 Python 코드 분석</td></tr></tbody></table>

### Linux: Python 3 Code (v2.0)

- Manufacturer: Linux
- Measurements: Store Value(s)
- Interfaces: AoT
- Dependencies: [pylint](https://pypi.org/project/pylint)

이것은 값을 데이터베이스에 저장하는 방식이 다른 대체 Python 3 Code Input입니다. Python 3 Code v1.0 Input이 Input Action 사용을 허용하지 않아 만들어졌으며, 이 방식은 Input Action 사용을 허용합니다. (2023/11/21 업데이트: 이제 Python 3 Code (v1.0) Input도 Action 실행을 허용합니다.) 값을 데이터베이스에 저장하려면 모든 채널에 Measurement Unit을 선택하고 저장해야 합니다. 코드는 AoT가 실행되는 것과 동일한 Python 가상환경에서 실행됩니다. 따라서 코드에서 사용할 Python 라이브러리는 이 환경에 설치해야 합니다. 이 virtualenv는 /opt/AoT/env에 있으며, 예를 들어 pip로 "my_library"를 설치하려면 "sudo /opt/AoT/env/bin/pip install my_library"를 실행합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Python 3 Code</td></td><td>The code to execute. Must return a value.</td></tr><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>저장 시 pylint로 Python 코드 분석</td></tr></tbody></table>

### Raspberry Pi: CPU/GPU Temperature

- Manufacturer: Raspberry Pi
- Measurements: Temperature
- Interfaces: RPi

Raspberry Pi 내부 CPU 및 GPU 온도
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Path for CPU Temperature</td><td>Text
- Default Value: /sys/class/thermal/thermal_zone0/temp</td><td>이 파일에서 CPU 온도 읽기</td></tr><tr><td>Path to vcgencmd</td><td>Text
- Default Value: /usr/bin/vcgencmd</td><td>vcgencmd로 GPU 값 읽기</td></tr></tbody></table>

### Raspberry Pi: Edge Detection

- Manufacturer: Raspberry Pi
- Measurements: Rising/Falling Edge
- Interfaces: GPIO
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Pin Mode</td><td>Select(Options: [<strong>Floating</strong> | Pull Down | Pull Up] (Default in <strong>bold</strong>)</td><td>풀업 또는 풀다운 저항을 활성화하거나 비활성화합니다.</td></tr></tbody></table>

### Raspberry Pi: GPIO State

- Manufacturer: Raspberry Pi
- Measurements: GPIO State
- Interfaces: GPIO
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

GPIO 핀 상태를 측정하여 0(low) 또는 1(high)을 반환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Pin Mode</td><td>Select(Options: [<strong>Floating</strong> | Pull Down | Pull Up] (Default in <strong>bold</strong>)</td><td>풀업 또는 풀다운 저항을 활성화하거나 비활성화합니다.</td></tr></tbody></table>

### Raspberry Pi: Signal (PWM)

- Manufacturer: Raspberry Pi
- Measurements: Frequency/Pulse Width/Duty Cycle
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Raspberry Pi: Signal (Revolutions) (pigpio method #1)

- Manufacturer: Raspberry Pi
- Measurements: RPM
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)

이것은 pigpio로 핀의 펄스로부터 RPM을 계산하지만, method #2 모듈보다 덜 정확한 것으로 확인되었습니다. 보통 타코미터 핀으로 팬의 속도를 측정하는 데 사용하지만, 배선의 3.3V 펄스라면 무엇이든 측정할 수 있습니다. 저항을 사용해 측정 핀을 3.3V로 풀업하고, Configure -> Raspberry Pi 페이지에서 pigpio를 최저 지연(1 ms)으로 설정하세요. 참고 1: pigpio를 최저 지연으로 설정하지 않으면 정확도가 떨어집니다. 참고 2: RPM이 높아질수록 정확도가 낮아집니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Raspberry Pi: Signal (Revolutions) (pigpio method #2)

- Manufacturer: Raspberry Pi
- Measurements: RPM
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)

이것은 pigpio로 핀의 펄스로부터 RPM을 계산하는 대체 방식으로, method #1 모듈보다 더 정확한 것으로 확인되었습니다. 보통 타코미터 핀으로 팬의 속도를 측정하는 데 사용하지만, 배선의 3.3V 펄스라면 무엇이든 측정할 수 있습니다. 저항을 사용해 측정 핀을 3.3V로 풀업하고, Configure -> Raspberry Pi 페이지에서 pigpio를 최저 지연(1 ms)으로 설정하세요. 참고 1: pigpio를 최저 지연으로 설정하지 않으면 정확도가 떨어집니다. 참고 2: RPM이 높아질수록 정확도가 낮아집니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>펄스를 측정할 핀</td></tr><tr><td>Sample Time (Seconds)</td><td>Decimal
- Default Value: 5.0</td><td>샘플링 지속 시간</td></tr><tr><td>Pulses Per Rev</td><td>Decimal
- Default Value: 15.8</td><td>분당 회전수(RPM) 계산을 위한 1회전당 펄스 수</td></tr></tbody></table>

## Built-In Inputs (Devices)

### AMS: AS7262

- Manufacturer: AMS
- Measurements: Light at 450, 500, 550, 570, 600, 650 nm
- Interfaces: I<sup>2</sup>C
- Libraries: as7262
- Dependencies: [as7262](https://pypi.org/project/as7262)
- Manufacturer URL: [Link](https://ams.com/as7262)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/AS7262_DS000486_2-00.pdf/0031f605-5629-e030-73b2-f365fd36a43b)
- Product URL: [Link](https://www.sparkfun.com/products/14347)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Gain</td><td>Select(Options: [1x | 3.7x | 16x | <strong>64x</strong>] (Default in <strong>bold</strong>)</td><td>센서 게인 설정</td></tr><tr><td>Illumination LED Current</td><td>Select(Options: [<strong>12.5 mA</strong> | 25 mA | 50 mA | 100 mA] (Default in <strong>bold</strong>)</td><td>조명 LED 전류 설정 (mA)</td></tr><tr><td>Illumination LED Mode</td><td>Select(Options: [<strong>On</strong> | Off] (Default in <strong>bold</strong>)</td><td>측정 중 조명 LED를 켜거나 끕니다.</td></tr><tr><td>Indicator LED Current</td><td>Select(Options: [<strong>1 mA</strong> | 2 mA | 4 mA | 8 mA] (Default in <strong>bold</strong>)</td><td>표시 LED 전류 설정 (mA)</td></tr><tr><td>Indicator LED Mode</td><td>Select(Options: [<strong>On</strong> | Off] (Default in <strong>bold</strong>)</td><td>측정 중 표시 LED를 켜거나 끕니다.</td></tr><tr><td>Integration Time</td><td>Decimal
- Default Value: 15.0</td><td>적분 시간 (0 - 약 91 ms)</td></tr></tbody></table>

### AMS: CCS811 (with Temperature)

- Manufacturer: AMS
- Measurements: CO2/VOC/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CCS811
- Dependencies: [Adafruit_CCS811](https://pypi.org/project/Adafruit_CCS811), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.sciosense.com/products/environmental-sensors/ccs811-gas-sensor-solution/)
- Datasheet URL: [Link](https://www.sciosense.com/wp-content/uploads/2020/01/CCS811-Datasheet.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3566), [Link 2](https://www.sparkfun.com/products/14193)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AMS: CCS811 (without Temperature)

- Manufacturer: AMS
- Measurements: CO2/VOC
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_CCS811
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ccs811](https://pypi.org/project/adafruit-circuitpython-ccs811)
- Manufacturer URL: [Link](https://www.sciosense.com/products/environmental-sensors/ccs811-gas-sensor-solution/)
- Datasheet URL: [Link](https://www.sciosense.com/wp-content/uploads/2020/01/CCS811-Datasheet.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3566)
- Additional URL: [Link](https://learn.adafruit.com/adafruit-ccs811-air-quality-sensor)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AMS: TSL2561

- Manufacturer: AMS
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: tsl2561
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-PureIO](https://pypi.org/project/Adafruit-PureIO), [tsl2561](https://pypi.org/project/tsl2561)
- Manufacturer URL: [Link](https://ams.com/tsl2561)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/TSL2561_DS000110_3-00.pdf/18a41097-2035-4333-c70e-bfa544c0a98b)
- Product URL: [Link](https://www.adafruit.com/product/439)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AMS: TSL2591

- Manufacturer: AMS
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: maxlklaxl/python-tsl2591
- Dependencies: [tsl2591](https://github.com/maxlklaxl/python-tsl2591)
- Manufacturer URL: [Link](https://ams.com/tsl25911)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/TSL2591_DS000338_6-00.pdf/090eb50d-bb18-5b45-4938-9b3672f86b80)
- Product URL: [Link](https://www.adafruit.com/product/1980)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AOSONG: AM2315/AM2320

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: quick2wire-api
- Dependencies: [quick2wire-api](https://pypi.org/project/quick2wire-api)
- Datasheet URL: [Link](https://cdn-shop.adafruit.com/datasheets/AM2315.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1293)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AOSONG: AM2315C

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: quick2wire-api
- Dependencies: [quick2wire-api](https://pypi.org/project/quick2wire-api)
- Datasheet URL: [Link](https://cdn-shop.adafruit.com/product-files/5182/5182_AM2315C.pdf)
- Product URL: [Link](https://vctec.co.kr/product/am2315c-i2c-%EC%98%A8%EB%8F%84%EC%8A%B5%EB%8F%84-%EC%84%BC%EC%84%9C-am2315c-encased-i2c-temperaturehumidity-sensor/20000)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AOSONG: DHT11

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
- Datasheet URL: [Link](http://www.adafruit.com/datasheets/DHT11-chinese.pdf)
- Product URL: [Link](https://www.adafruit.com/product/386)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AOSONG: DHT20

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://asairsensors.com/product/dht20-sip-packaged-temperature-and-humidity-sensor/)
- Datasheet URL: [Link](http://www.aosong.com/userfiles/files/media/Data%20Sheet%20DHT20%20%20A1.pdf)
- Product URLs: [Link 1](https://www.seeedstudio.com/Grove-Temperature-Humidity-Sensor-V2-0-DHT20-p-4967.html), [Link 2](https://www.antratek.de/humidity-and-temperature-sensor-dht20), [Link 3](https://www.adafruit.com/product/5183)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### AOSONG: DHT22

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
- Datasheet URL: [Link](http://www.adafruit.com/datasheets/DHT22.pdf)
- Product URL: [Link](https://www.adafruit.com/product/385)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### ASAIR: AHTx0

- Manufacturer: ASAIR
- Measurements: Temperature/Humidity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_AHTx0
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ahtx0](https://pypi.org/project/adafruit-circuitpython-ahtx0)
- Manufacturer URL: [Link](http://www.aosong.com/en/products-40.html)
- Datasheet URL: [Link](https://server4.eca.ir/eshop/AHT10/Aosong_AHT10_en_draft_0c.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Adafruit: I2C Capacitive Moisture Sensor

- Manufacturer: Adafruit
- Measurements: Moisture/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: adafruit_seesaw
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-seesaw](https://pypi.org/project/adafruit-circuitpython-seesaw)
- Manufacturer URL: [Link](https://learn.adafruit.com/adafruit-stemma-soil-sensor-i2c-capacitive-moisture-sensor)
- Product URL: [Link](https://www.adafruit.com/product/4026)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Analog Devices: ADT7410

- Manufacturer: Analog Devices
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADT7410
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-adt7410](https://pypi.org/project/adafruit-circuitpython-adt7410)
- Datasheet URL: [Link](https://www.analog.com/media/en/technical-documentation/data-sheets/ADT7410.pdf)
- Product URL: [Link](https://www.analog.com/en/products/adt7410.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Analog Devices: ADXL34x (343, 344, 345, 346)

- Manufacturer: Analog Devices
- Measurements: Acceleration
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADXL34x
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-adxl34x](https://pypi.org/project/adafruit-circuitpython-adxl34x)
- Datasheet URLs: [Link 1](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL343.pdf), [Link 2](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL344.pdf), [Link 3](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL345.pdf), [Link 4](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL346.pdf)
- Product URLs: [Link 1](https://www.analog.com/en/products/adxl343.html), [Link 2](https://www.analog.com/en/products/adxl344.html), [Link 3](https://www.analog.com/en/products/adxl345.html), [Link 4](https://www.analog.com/en/products/adxl346.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Range</td><td>Select(Options: [±2 g (±19.6 m/s/s) | ±4 g (±39.2 m/s/s) | ±8 g (±78.4 m/s/s) | <strong>±16 g (±156.9 m/s/s)</strong>] (Default in <strong>bold</strong>)</td><td>측정 범위 설정</td></tr></tbody></table>

### AnyLeaf: AnyLeaf EC

- Manufacturer: AnyLeaf
- Measurements: Electrical Conductivity
- Interfaces: UART
- Libraries: anyleaf
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [Pillow](https://pypi.org/project/Pillow), [scipy](https://pypi.org/project/scipy), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [anyleaf](https://pypi.org/project/anyleaf)
- Manufacturer URL: [Link](https://www.anyleaf.org/ec-module)
- Datasheet URL: [Link](https://www.anyleaf.org/static/ec-module-datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Conductivity Constant</td><td>Decimal
- Default Value: 1.0</td><td>전도도 상수 K</td></tr></tbody></table>

### AnyLeaf: AnyLeaf ORP

- Manufacturer: AnyLeaf
- Measurements: Oxidation Reduction Potential
- Interfaces: I<sup>2</sup>C
- Libraries: anyleaf
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [Pillow](https://pypi.org/project/Pillow), [scipy](https://pypi.org/project/scipy), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [anyleaf](https://pypi.org/project/anyleaf)
- Manufacturer URL: [Link](https://anyleaf.org/ph-module)
- Datasheet URL: [Link](https://anyleaf.org/static/ph-module-datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Calibrate: Voltage (Internal)</td><td>Decimal
- Default Value: 0.4</td><td>보정 데이터: 내부 전압</td></tr><tr><td>Calibrate: ORP (Internal)</td><td>Decimal
- Default Value: 400.0</td><td>보정 데이터: 내부 ORP</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate: Buffer ORP (mV)</td><td>Decimal
- Default Value: 400.0</td><td>이것은 보정 버퍼의 공칭 ORP 값(mV)으로, 보통 병에 표기되어 있습니다.</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td>Clear Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### AnyLeaf: AnyLeaf pH

- Manufacturer: AnyLeaf
- Measurements: Ion concentration
- Interfaces: I<sup>2</sup>C
- Libraries: anyleaf
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [Pillow](https://pypi.org/project/Pillow), [scipy](https://pypi.org/project/scipy), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [anyleaf](https://pypi.org/project/anyleaf)
- Manufacturer URL: [Link](https://anyleaf.org/ph-module)
- Datasheet URL: [Link](https://anyleaf.org/static/ph-module-datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Cal data: V1 (internal)</td><td>Decimal</td><td>보정 데이터: 전압</td></tr><tr><td>Cal data: pH1 (internal)</td><td>Decimal
- Default Value: 7.0</td><td>보정 데이터: pH</td></tr><tr><td>Cal data: T1 (internal)</td><td>Decimal
- Default Value: 23.0</td><td>보정 데이터: 온도</td></tr><tr><td>Cal data: V2 (internal)</td><td>Decimal
- Default Value: 0.17</td><td>보정 데이터: 전압</td></tr><tr><td>Cal data: pH2 (internal)</td><td>Decimal
- Default Value: 4.0</td><td>보정 데이터: pH</td></tr><tr><td>Cal data: T2 (internal)</td><td>Decimal
- Default Value: 23.0</td><td>보정 데이터: 온도</td></tr><tr><td>Cal data: V3 (internal)</td><td>Decimal</td><td>보정 데이터: 전압</td></tr><tr><td>Cal data: pH3 (internal)</td><td>Decimal</td><td>보정 데이터: pH</td></tr><tr><td>Cal data: T3 (internal)</td><td>Decimal</td><td>보정 데이터: 온도</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibration buffer pH</td><td>Decimal
- Default Value: 7.0</td><td>보정 버퍼의 공칭 pH 값으로, 보통 병에 표기되어 있습니다.</td></tr><tr><td>Calibrate, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate, slot 2</td><td>Button</td><td></td></tr><tr><td>Calibrate, slot 3</td><td>Button</td><td></td></tr><tr><td>Clear Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas CO2 (Carbon Dioxide Gas)

- Manufacturer: Atlas Scientific
- Measurements: CO2
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/co2/)
- Datasheet URL: [Link](https://atlas-scientific.com/files/EZO_CO2_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one- or two-point calibration can be performed. After exposing the probe to a concentration of CO2 between 3,000 and 5,000 ppmv until readings stabilize, press Calibrate (High). You can place the probe in a 0 CO2 environment until readings stabilize, then press Calibrate (Zero). You can also clear the currently-saved calibration by pressing Clear Calibration, returning to the factory-set calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>High Point CO2</td><td>Integer
- Default Value: 3000</td><td>고점 CO2 보정 지점 (3000 - 5000 ppmv)</td></tr><tr><td>Calibrate (High)</td><td>Button</td><td></td></tr><tr><td>Calibrate (Zero)</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x69</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Color

- Manufacturer: Atlas Scientific
- Measurements: RGB, CIE, LUX, Proximity
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/ezo-rgb/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO_RGB_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>LED Only For Measure</td><td>Boolean
- Default Value: True</td><td>측정 중에만 LED 켜기</td></tr><tr><td>LED Percentage</td><td>Integer
- Default Value: 30</td><td>측정 중 LED에 공급할 전력 비율(%)</td></tr><tr><td>Gamma Correction</td><td>Decimal
- Default Value: 1.0</td><td>감마 보정값, 0.01~4.99(기본값 1.0)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The EZO-RGB color sensor is designed to be calibrated to a white object at the maximum brightness the object will be viewed under. In order to get the best results, Atlas Scientific strongly recommends that the sensor is mounted into a fixed location. Holding the sensor in your hand during calibration will decrease performance.<br>1. Embed the EZO-RGB color sensor into its intended use location.<br>2. Set LED brightness to the desired level.<br>3. Place a white object in front of the target object and press the Calibration button.<br>4. A single color reading will be taken and the device will be fully calibrated.</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x70</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas DO

- Manufacturer: Atlas Scientific
- Measurements: Dissolved Oxygen
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/dissolved-oxygen.html)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/DO_EZO_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one- or two-point calibration can be performed. After exposing the probe to air for 30 seconds until readings stabilize, press Calibrate (Air). If you require accuracy below 1.0 mg/L, you can place the probe in a 0 mg/L solution for 30 to 90 seconds until readings stabilize, then press Calibrate (0 mg/L). You can also clear the currently-saved calibration by pressing Clear Calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Calibrate (Air)</td><td>Button</td><td></td></tr><tr><td>Calibrate (0 mg/L)</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x66</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas EC

- Manufacturer: Atlas Scientific
- Measurements: Electrical Conductivity
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/conductivity/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EC_EZO_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Calibration: a one- or two-point calibration can be performed. It's a good idea to clear the calibration before calibrating. Always perform a dry calibration with the probe in the air (not in any fluid). Then perform either a one- or two-point calibration with calibrated solutions. If performing a one-point calibration, use the Single Point Calibration field and button. If performing a two-point calibration, use the Low and High Point Calibration fields and buttons. Allow a minute or two after submerging your probe in a calibration solution for the measurements to equilibrate before calibrating to that solution. The EZO EC circuit default temperature compensation is set to 25 °C. If the temperature of the calibration solution is +/- 2 °C from 25 °C, consider setting the temperature compensation first. Note that at no point should you change the temperature compensation value during calibration. Therefore, if you have previously enabled temperature compensation, allow at least one measurement to occur (to set the compensation value), then disable the temperature compensation measurement while you calibrate. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td>Calibrate Dry</td><td>Button</td><td></td></tr><tr><td>Single Point EC (µS)</td><td>Integer
- Default Value: 84</td><td>단일점 보정 용액의 EC(µS)</td></tr><tr><td>Calibrate Single Point</td><td>Button</td><td></td></tr><tr><td>Low Point EC (µS)</td><td>Integer
- Default Value: 12880</td><td>저점 보정액의 EC (µS)</td></tr><tr><td>Calibrate Low Point</td><td>Button</td><td></td></tr><tr><td>High Point EC (µS)</td><td>Integer
- Default Value: 80000</td><td>고점 보정 용액의 EC(µS)</td></tr><tr><td>Calibrate High Point</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x64</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Flow Meter

- Manufacturer: Atlas Scientific
- Measurements: Total Volume, Flow Rate
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/flow/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/flow_EZO_Datasheet.pdf)

예상 유량에 가장 적합한 값으로 Measurement Time Base를 설정하세요(정확도에 영향을 줍니다). 센서에서 설정·반환되는 이 유량 시간 기준은 이 입력 모듈의 기본 단위인 분당 리터(L/min)로 변환됩니다. 초당 또는 시간당 리터 등 다른 단위로 데이터베이스에 저장하려면 Convert to Unit 옵션을 사용하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Flow Meter Type</td><td>Select(Options: [<strong>Atlas Scientific 3/8" Flow Meter</strong> | Atlas Scientific 1/4" Flow Meter | Atlas Scientific 1/2" Flow Meter | Atlas Scientific 3/4" Flow Meter | Non-Atlas Scientific Flow Meter] (Default in <strong>bold</strong>)</td><td>사용할 유량계 종류 설정</td></tr><tr><td>Atlas Meter Time Base</td><td>Select(Options: [Liters per Second | <strong>Liters per Minute</strong> | Liters per Hour] (Default in <strong>bold</strong>)</td><td>Atlas Scientific 유량계 사용 시 유량/시간 기준을 설정하세요.</td></tr><tr><td>Internal Resistor</td><td>Select(Options: [<strong>Use Atlas Scientific Flow Meter</strong> | Disable Internal Resistor | 1 K Ω Pull-Up | 1 K Ω Pull-Down | 10 K Ω Pull-Up | 10 K Ω Pull-Down | 100 K Ω Pull-Up | 100 K Ω Pull-Down] (Default in <strong>bold</strong>)</td><td>유량계용 내부 저항 설정</td></tr><tr><td>Custom K Value(s)</td><td>텍스트</td><td>Atlas Scientific 제품이 아닌 유량계를 사용하는 경우 해당 유량계의 K 값을 입력하세요. 단일 K 값은 '[펄스당 유량],[펄스 수]'로 입력합니다. 여러 K 값(최대 16개)은 '[주파수에서의 유량],[주파수(Hz)];[주파수에서의 유량],[주파수(Hz)];...'로 입력합니다. 비활성화하려면 비워 두세요.</td></tr><tr><td>K Value Time Base</td><td>Select(Options: [<strong>Use Atlas Scientific Flow Meter</strong> | Liters per Second | Liters per Minute | Liters per Hour] (Default in <strong>bold</strong>)</td><td>Atlas Scientific 제품이 아닌 유량계를 사용하는 경우, 입력한 사용자 지정 K 값에 대한 유량/시간 기준을 설정하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The total volume can be cleared with the following button or with the Clear Total Volume Function Action.</td></tr><tr><td>Clear Total: Volume</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x68</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Humidity

- Manufacturer: Atlas Scientific
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/probes/humidity-sensor/)
- Datasheet URL: [Link](https://atlas-scientific.com/files/EZO-HUM-Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>LED Mode</td><td>Select(Options: [<strong>Always On</strong> | Always Off | Only On During Measure] (Default in <strong>bold</strong>)</td><td>LED를 켤 시점</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x6f</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas O2 (Oxygen Gas)

- Manufacturer: Atlas Scientific
- Measurements: O2
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/probes/oxygen-sensor/)
- Datasheet URL: [Link](https://files.atlas-scientific.com/EZO_O2_datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Temperature Compensation: Manual</td><td>Decimal
- Default Value: 20.0</td><td>측정값을 사용하지 않는 경우, 보정할 온도를 설정하세요.</td></tr><tr><td>LED Mode</td><td>Select(Options: [<strong>Always On</strong> | Always Off | Only On During Measure] (Default in <strong>bold</strong>)</td><td>LED를 켤 시점</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one- or two-point calibration can be performed. After exposing the probe to a specific concentration of O2 until readings stabilize, press Calibrate (High). You can place the probe in a 0% O2 environment until readings stabilize, then press Calibrate (Zero). You can also clear the currently-saved calibration by pressing Clear Calibration, returning to the factory-set calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>High Point O2</td><td>Decimal
- Default Value: 20.95</td><td>고점 O2 보정 지점 (%)</td></tr><tr><td>Calibrate (High)</td><td>Button</td><td></td></tr><tr><td>Calibrate (Zero)</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x69</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas ORP

- Manufacturer: Atlas Scientific
- Measurements: Oxidation Reduction Potential
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/orp/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/ORP_EZO_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one-point calibration can be performed. Enter the solution's mV, set the probe in the solution, then press Calibrate. You can also clear the currently-saved calibration by pressing Clear Calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Calibration Solution mV</td><td>Integer
- Default Value: 225</td><td>보정액 값 (mV)</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x62</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas PT-1000

- Manufacturer: Atlas Scientific
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/temperature/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO_RTD_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x66</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr><tr><td>Temperature (°C)</td><td>Decimal
- Default Value: 100.0</td><td>단일점 보정용 온도</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Pressure

- Manufacturer: Atlas Scientific
- Measurements: Pressure
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/pressure/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO-PRS-Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>LED Mode</td><td>Select(Options: [<strong>Always On</strong> | Always Off | Only On During Measure] (Default in <strong>bold</strong>)</td><td>LED를 켤 시점</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x6a</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas pH

- Manufacturer: Atlas Scientific
- Measurements: Ion Concentration
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/ph/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/pH_EZO_Datasheet.pdf)

Calibration Measurement는 pH를 측정하는 물의 온도(°C)를 제공하는 선택적 설정입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Calibration: a one-, two- or three-point calibration can be performed. It's a good idea to clear the calibration before calibrating. The first calibration must be the Mid point. The second must be the Low point. And the third must be the High point. You can perform a one-, two- or three-point calibration, but they must be performed in this order. Allow a minute or two after submerging your probe in a calibration solution for the measurements to equilibrate before calibrating to that solution. The EZO pH circuit default temperature compensation is set to 25 °C. If the temperature of the calibration solution is +/- 2 °C from 25 °C, consider setting the temperature compensation first. Note that if you have a Temperature Compensation Measurement selected from the Options, this will overwrite the manual Temperature Compensation set here, so be sure to disable this option if you would like to specify the temperature to compensate with. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Compensation Temperature (°C)</td><td>Decimal
- Default Value: 25.0</td><td>보정액의 온도</td></tr><tr><td>Set Temperature Compensation</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td>Mid Point pH</td><td>Decimal
- Default Value: 7.0</td><td>중점 보정액의 pH</td></tr><tr><td>Calibrate Mid</td><td>Button</td><td></td></tr><tr><td>Low Point pH</td><td>Decimal
- Default Value: 4.0</td><td>저점 보정액의 pH</td></tr><tr><td>Calibrate Low</td><td>Button</td><td></td></tr><tr><td>High Point pH</td><td>Decimal
- Default Value: 10.0</td><td>고점 보정액의 pH</td></tr><tr><td>Calibrate High</td><td>Button</td><td></td></tr><tr><td colspan="3">Calibration Export/Import: Export calibration to a series of strings. These can later be imported to restore the calibration. Watch the Daemon Log for the output.</td></tr><tr><td>Export Calibration</td><td>Button</td><td></td></tr><tr><td>Calibration String</td><td>텍스트</td><td>가져올 보정 문자열</td></tr><tr><td>Import Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x63</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### BOSCH: BME280 (Adafruit_BME280)

- Manufacturer: BOSCH
- Measurements: Pressure/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_BME280
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit_BME280](https://github.com/adafruit/Adafruit_Python_BME280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/bst/products/all_products/bme280)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/2652), [Link 2](https://www.sparkfun.com/products/13676)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### BOSCH: BME280 (Adafruit_CircuitPython_BME280)

- Manufacturer: BOSCH
- Measurements: Pressure/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_BME280
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-bme280](https://pypi.org/project/adafruit-circuitpython-bme280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/bst/products/all_products/bme280)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/2652), [Link 2](https://www.sparkfun.com/products/13676)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### BOSCH: BME280 (RPi.bme280)

- Manufacturer: BOSCH
- Measurements: Pressure/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: RPi.bme280
- Dependencies: [RPi.bme280](https://pypi.org/project/RPi.bme280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/bst/products/all_products/bme280)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/2652), [Link 2](https://www.sparkfun.com/products/13676)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### BOSCH: BME680 (Adafruit_CircuitPython_BME680)

- Manufacturer: BOSCH
- Measurements: Temperature/Humidity/Pressure/Gas
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_BME680
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-bme680](https://pypi.org/project/adafruit-circuitpython-bme680)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/gas-sensors-bme680/)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme680-ds001.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3660), [Link 2](https://www.sparkfun.com/products/16466)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Humidity Oversampling</td><td>Select(Options: [NONE | 1X | <strong>2X</strong> | 4X | 8X | 16X] (Default in <strong>bold</strong>)</td><td>oversampling 값이 높을수록 노이즈와 지터가 줄어 측정값이 더 안정적입니다. 다만 oversampling 단계마다 약 2 ms의 지연이 추가되어 빠른 과도 변화에 대한 응답 시간이 느려집니다.</td></tr><tr><td>Temperature Oversampling</td><td>Select(Options: [NONE | 1X | 2X | 4X | <strong>8X</strong> | 16X] (Default in <strong>bold</strong>)</td><td>oversampling 값이 높을수록 노이즈와 지터가 줄어 측정값이 더 안정적입니다. 다만 oversampling 단계마다 약 2 ms의 지연이 추가되어 빠른 과도 변화에 대한 응답 시간이 느려집니다.</td></tr><tr><td>Pressure Oversampling</td><td>Select(Options: [NONE | 1X | 2X | <strong>4X</strong> | 8X | 16X] (Default in <strong>bold</strong>)</td><td>oversampling 값이 높을수록 노이즈와 지터가 줄어 측정값이 더 안정적입니다. 다만 oversampling 단계마다 약 2 ms의 지연이 추가되어 빠른 과도 변화에 대한 응답 시간이 느려집니다.</td></tr><tr><td>IIR Filter Size</td><td>Select(Options: [0 | 1 | <strong>3</strong> | 7 | 15 | 31 | 63 | 127] (Default in <strong>bold</strong>)</td><td>선택적으로 온도 및 압력 측정값에서 단기 변동을 제거하여 해상도를 높이지만 대역폭은 줄입니다.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>온도를 보정할 값(음수 또는 양수)</td></tr><tr><td>Sea Level Pressure (ha)</td><td>Decimal
- Default Value: 1013.25</td><td>센서 위치의 해수면 기압</td></tr></tbody></table>

### BOSCH: BME680 (bme680)

- Manufacturer: BOSCH
- Measurements: Temperature/Humidity/Pressure/Gas
- Interfaces: I<sup>2</sup>C
- Libraries: bme680
- Dependencies: [bme680](https://pypi.org/project/bme680), [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/gas-sensors-bme680/)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme680-ds001.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3660), [Link 2](https://www.sparkfun.com/products/16466)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Humidity Oversampling</td><td>Select(Options: [NONE | 1X | <strong>2X</strong> | 4X | 8X | 16X] (Default in <strong>bold</strong>)</td><td>oversampling 값이 높을수록 노이즈와 지터가 줄어 측정값이 더 안정적입니다. 다만 oversampling 단계마다 약 2 ms의 지연이 추가되어 빠른 과도 변화에 대한 응답 시간이 느려집니다.</td></tr><tr><td>Temperature Oversampling</td><td>Select(Options: [NONE | 1X | 2X | 4X | <strong>8X</strong> | 16X] (Default in <strong>bold</strong>)</td><td>oversampling 값이 높을수록 노이즈와 지터가 줄어 측정값이 더 안정적입니다. 다만 oversampling 단계마다 약 2 ms의 지연이 추가되어 빠른 과도 변화에 대한 응답 시간이 느려집니다.</td></tr><tr><td>Pressure Oversampling</td><td>Select(Options: [NONE | 1X | 2X | <strong>4X</strong> | 8X | 16X] (Default in <strong>bold</strong>)</td><td>oversampling 값이 높을수록 노이즈와 지터가 줄어 측정값이 더 안정적입니다. 다만 oversampling 단계마다 약 2 ms의 지연이 추가되어 빠른 과도 변화에 대한 응답 시간이 느려집니다.</td></tr><tr><td>IIR Filter Size</td><td>Select(Options: [0 | 1 | <strong>3</strong> | 7 | 15 | 31 | 63 | 127] (Default in <strong>bold</strong>)</td><td>선택적으로 온도 및 압력 측정값에서 단기 변동을 제거하여 해상도를 높이지만 대역폭은 줄입니다.</td></tr><tr><td>Gas Heater Temperature (°C)</td><td>Integer
- Default Value: 320</td><td>설정할 온도</td></tr><tr><td>Gas Heater Duration (ms)</td><td>Integer
- Default Value: 150</td><td>가열할 시간입니다. 히터가 목표 온도에 도달하려면 20-30 ms가 필요합니다.</td></tr><tr><td>Gas Heater Profile</td><td>선택</td><td>설정된 10개의 가열 시간/설정값 중 하나를 선택하세요.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>온도를 보정할 값(음수 또는 양수)</td></tr></tbody></table>

### BOSCH: BMP180

- Manufacturer: BOSCH
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_BMP
- Dependencies: [Adafruit-BMP](https://pypi.org/project/Adafruit-BMP), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Datasheet URL: [Link](https://ae-bst.resource.bosch.com/media/_tech/media/product_flyer/BST-BMP180-FL000.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### BOSCH: BMP280 (Adafruit_GPIO)

- Manufacturer: BOSCH
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_GPIO
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/pressure-sensors-bmp280-1.html)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf)
- Product URL: [Link](https://www.adafruit.com/product/2651)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### BOSCH: BMP280 (bmp280-python)

- Manufacturer: BOSCH
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: bmp280-python
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [bmp280](https://pypi.org/project/bmp280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/pressure-sensors-bmp280-1.html)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf)
- Product URL: [Link](https://www.adafruit.com/product/2651)

이것은 다른 BMP280 Input과 비슷하지만, forced mode를 설정하는 기능이 포함된 다른 라이브러리를 사용합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Enable Forced Mode</td><td>Boolean</td><td>결로를 증발시키기 위해 히터를 활성화합니다. y회 측정마다 히터를 x초 동안 켭니다.</td></tr></tbody></table>

### CARTO: GL: Carto Maps

- Manufacturer: CARTO
- Measurements: Status
- Libraries: gis_carto
- Manufacturer URL: [Link](https://carto.com/)

CARTO DB에서 제공하는 데이터 분석 전용 지도입니다. 색감이 절제된 Positron(밝음), Dark Matter(어두움), Voyager 스타일을 제공하여, 위에 표현되는 데이터 포인트나 센서 정보가 더욱 돋보이도록 설계되었습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Active Map Styles</td></td></tbody></table>

### CO2Meter: K30

- Manufacturer: CO2Meter
- Measurements: CO2
- Interfaces: I<sup>2</sup>C, UART
- Libraries: serial (UART)
- Manufacturer URL: [Link](https://www.co2meter.com/products/k-30-co2-sensor-module)
- Datasheet URL: [Link](http://co2meters.com/Documentation/Datasheets/DS_SE_0118_CM_0024_Revised9%20(1).pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Catnip Electronics: Chirp

- Manufacturer: Catnip Electronics
- Measurements: Light/Moisture/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wemakethings.net/chirp/)
- Product URL: [Link](https://www.tindie.com/products/miceuz/chirp-plant-watering-alarm/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x20</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### ChirpStack: ChirpStack: MQTT (Payload JMESPath Expression)

- Manufacturer: ChirpStack
- Measurements: Variable measurements
- Libraries: paho-mqtt, jmespath
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt), [jmespath](https://pypi.org/project/jmespath)

ChirpStack v4 MQTT 브로커의 토픽(application/+/device/+/event/up)을 구독하여 이벤트를 수신하고, 각 이벤트 JSON에 대해 채널별 JMESPath 표현식을 적용하여 측정값을 저장합니다. 예시(https://jmespath.org): object.battery_V, object.battery_pct, max_by(rxInfo,&rssi).rssi, deviceInfo.devEui.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>MQTT Host</td><td>Text
- Default Value: localhost</td><td>MQTT 브로커 호스트명 또는 IP 주소 (예: localhost)</td></tr><tr><td>MQTT Port</td><td>Text
- Default Value: 1883</td><td>MQTT 브로커 포트 (기본 1883, TLS는 8883 권장)</td></tr><tr><td>MQTT Username</td><td>텍스트</td><td>선택 사항: 브로커 인증 사용자 이름</td></tr><tr><td>MQTT Password</td><td>텍스트</td><td>선택 사항: 브로커 인증 비밀번호</td></tr><tr><td>Enable TLS</td><td>Boolean</td><td>TLS(SSL) 연결 사용 여부 (기본 꺼짐)</td></tr><tr><td>CA Certificate Path</td><td>텍스트</td><td>선택 사항: TLS 사용 시 CA 인증서 경로</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_kkohqJyu</td><td>서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Keepalive (sec)</td><td>Text
- Default Value: 60</td><td>MQTT Keepalive 초 (기본 60초)</td></tr><tr><td>Subscribe Topics</td><td>Text
- Default Value: application/+/device/+/event/up</td><td>콤마(,)로 구분된 구독 토픽들 (예: application/+/device/+/event/up)</td></tr><tr><td>QoS</td><td>텍스트</td><td>MQTT QoS 레벨 (0, 1, 2)</td></tr><tr><td>Device EUIs (comma-separated)</td><td>텍스트</td><td>선택 사항: 특정 디바이스만 처리. EUI를 콤마(,)로 구분해 입력</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>JMESPath Expression</td><td>텍스트</td><td>수신 이벤트 전체(JSON)에 대해 평가합니다</td></tr></tbody></table>

### Chirpstack: ChirpStack: REST API (Payload JMESPath Expression)

- Manufacturer: Chirpstack
- Measurements: Variable measurements
- Libraries: chirpstack-rest-api, requests, jmespath

ChirpStack v4 REST API를 주기적으로 호출하여 디바이스 이벤트를 가져오고, 각 이벤트 JSON에 대해 채널별 JMESPath 표현식을 적용하여 측정값을 저장합니다. 예시(https://jmespath.org): object.battery_V, object.battery_pct, max_by(rxInfo,&rssi).rssi, deviceInfo.devEui.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>API Base URL</td><td>Text
- Default Value: http://localhost:8090</td><td>ChirpStack REST API의 기본 주소 (예: http://localhost:8080) (일반적으로 REST 프록시는 8090 포트)</td></tr><tr><td>API Token</td><td>텍스트</td><td>ChirpStack REST API 접근을 위한 Bearer 토큰 (관리 콘솔에서 발급)</td></tr><tr><td>Tenant ID</td><td>텍스트</td><td>선택 사항: 특정 테넌트에 속한 디바이스만 조회할 때 사용</td></tr><tr><td>Application ID</td><td>텍스트</td><td>선택 사항: 특정 애플리케이션에 속한 디바이스만 조회할 때 사용</td></tr><tr><td>Device EUIs (comma-separated)</td><td>텍스트</td><td>선택 사항: 조회할 디바이스 EUI를 콤마(,)로 구분해 입력. 비우면 애플리케이션의 모든 디바이스 대상</td></tr><tr><td>Page size / limit</td><td>Text
- Default Value: 50</td><td>한 번의 REST API 호출에서 가져올 이벤트 개수(페이지 크기)</td></tr><tr><td>Event kind</td><td>Text
- Default Value: up</td><td>가져올 이벤트의 종류 (예: up, join, status)</td></tr><tr><td>Fallback URL template</td><td>Text
- Default Value: /api/devices/{dev_eui}/events?limit={limit}&kind={kind}&after={after}</td><td>공식 파이썬 클라이언트를 사용할 수 없을 때 REST 요청에 사용할 URL 템플릿 (API Base URL 뒤에 연결됨). {dev_eui}, {limit}, {kind}, {after}가 자동 치환됨</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>JMESPath Expression</td><td>텍스트</td><td>전체 이벤트 JSON에 대해 평가</td></tr></tbody></table>

### Cozir: Cozir CO2

- Manufacturer: Cozir
- Measurements: CO2/Humidity/Temperature
- Interfaces: UART
- Libraries: pierre-haessig/pycozir
- Dependencies: [cozir](https://github.com/pierre-haessig/pycozir)
- Manufacturer URL: [Link](https://www.co2meter.com/products/cozir-2000-ppm-co2-sensor)
- Datasheet URL: [Link](https://cdn.shopify.com/s/files/1/0019/5952/files/Datasheet_COZIR_A_CO2Meter_4_15.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### ESA: GL: Soil Moisture (NASA SMAP)

- Manufacturer: ESA
- Measurements: Status
- Libraries: gis_esa
- Manufacturer URL: [Link](https://smap.jpl.nasa.gov/)

유럽우주국(ESA)의 Sentinel-2 위성 데이터를 기반으로 한 전 세계 토지 피복(Land Cover) 지도입니다. 식생, 도시, 농경지, 산림, 수역 등을 10m급 고해상도로 분석하여 색상별로 확인할 수 있어 환경 분석에 유용합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Date Mode</td><td>선택</td><tr><td>Custom Date</td><td>텍스트</td></tbody></table>

### Ecowitt: Ecowitt Cloud API Weather Data

- Manufacturer: Ecowitt

Ecowitt Cloud API를 사용하려면 Application Key, API Key, 장치 MAC 주소를 입력하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 60</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td>Application Key</td><td>텍스트</td><td>Ecowitt 플랫폼에서 발급받은 Application Key를 입력하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>Ecowitt 플랫폼에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>Device MAC</td><td>텍스트</td><td>Ecowitt 장치의 MAC 주소를 입력하세요.</td></tr><tr><td>Call Back</td><td>Text
- Default Value: all</td><td>호출할 데이터 종류를 입력하세요 (예: all).</td></tr></tbody></table>

### Ecowitt: Ecowitt MQTT\(JSON payload)

- Manufacturer: Ecowitt
- Measurements: Variable measurements
- Interfaces: AoT
- Libraries: paho-mqtt, jmespath
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt), [jmespath](https://pypi.org/project/jmespath)

선택된 Ecowitt 장치 유형에 따라 자동 생성된 채널을 구독하고, MQTT 토픽으로 전송되는 URL 인코딩 또는 JSON 페이로드에서 각 채널의 JMESPATH 표현식으로 값을 추출하여 데이터베이스에 저장합니다. 채널별 측정 단위와 변환 설정을 사용자 정의 옵션으로 지정할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Ecowitt 장치</td><td>Select(Options: [<strong>기상대</strong> | 온습도 센서 | 온도 센서 | 토양 수분 센서 | 잎 센서 | 거리 측정기 | 공기질 측정기] (Default in <strong>bold</strong>)</td><tr><td>Host</td><td>Text
- Default Value: localhost</td><td>호스트 또는 IP 주소</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>호스트 포트 번호</td></tr><tr><td>Topic</td><td>Text
- Default Value: gw</td><td>구독할 토픽</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>수신 신호 사이의 최대 시간. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_SsE838CY</td><td>서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>TLS로 로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 연결용 비밀번호. 비활성화하려면 비워 두세요.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>JMESPATH Expression</td><td>텍스트</td><td>JSON 응답에서 값을 찾는 JMESPATH 표현식</td></tr></tbody></table>

### Ecowitt: Ecowitt soil_sensor

- Manufacturer: Ecowitt

Ecowitt Cloud API를 사용하려면 Application Key, API Key, 장치 MAC 주소를 입력하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 60</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td>Application Key</td><td>텍스트</td><td>Ecowitt 플랫폼에서 발급받은 Application Key를 입력하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>Ecowitt 플랫폼에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>Device MAC</td><td>텍스트</td><td>Ecowitt 장치의 MAC 주소를 입력하세요.</td></tr><tr><td>채널 선택</td><td>Text
- Default Value: 1</td><td>측정할 채널을 선택하세요.</td></tr></tbody></table>

### Ecowitt: Ecowitt temp and humidity sensor

- Manufacturer: Ecowitt

Ecowitt Cloud API를 사용하려면 Application Key, API Key, 장치 MAC 주소를 입력하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 60</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td>Application Key</td><td>텍스트</td><td>Ecowitt 플랫폼에서 발급받은 Application Key를 입력하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>Ecowitt 플랫폼에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>Device MAC</td><td>텍스트</td><td>Ecowitt 장치의 MAC 주소를 입력하세요.</td></tr><tr><td>채널 선택</td><td>Text
- Default Value: 1</td><td>측정할 채널을 선택하세요.</td></tr></tbody></table>

### Esri: GL: Esri World Imagery

- Manufacturer: Esri
- Measurements: Status
- Libraries: gis_esri
- Manufacturer URL: [Link](https://www.esri.com/)

세계적인 GIS 기업 Esri의 공신력 있는 지도 서비스입니다. 선명하고 정교한 World Imagery 항공 위성 사진을 제공하여 지형의 세부 형상과 시설물을 정확하게 조망하기에 최적화되어 있습니다.


### GSI: JP: GSI Maps

- Manufacturer: GSI
- Measurements: Status
- Libraries: gis_gsi
- Manufacturer URL: [Link](https://maps.gsi.go.jp/)

일본 국토지리원(GSI)에서 제공하는 고정밀 공공 지도 서비스입니다. 일본 전역의 세부적인 지형과 지명 정보를 담고 있으며, 표준 지도뿐만 아니라 담색 지도, 항공 사진 등 전문적인 레이어를 활용할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>지도 스타일</td></td></tbody></table>

### Generic: Hall Flow Meter

- Manufacturer: Generic
- Measurements: Flow Rate, Total Volume
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Pulses per Liter</td><td>Decimal
- Default Value: 1.0</td><td>이 계량기의 변환 계수를 입력하세요(펄스 → 리터).</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Clear Total: Volume</td><td>Button</td><td></td></tr></tbody></table>

### Google: GL: Google Maps

- Manufacturer: Google
- Measurements: Status
- Libraries: gis_google
- Manufacturer URL: [Link](https://www.google.com/maps)

가장 널리 사용되는 구글의 웹 지도 서비스입니다. 방대한 지리 정보를 바탕으로 Road, Satellite, Hybrid, Terrain 등 4가지 모드를 지원하며, 특히 지형의 등고와 음영을 보여주는 Terrain 지도가 우수합니다. 또한, 구글의 Geocoding API를 이용하여 주소를 좌표로 변환할 수 있습니다. API 키는 구글 개발자 콘솔에서 발급 가능합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Google Maps API Key</td><td>텍스트</td><tr><td>지도 스타일</td></td></tbody></table>

### ISRIC: GL: SoilGrids (Global Soil Info)

- Manufacturer: ISRIC
- Measurements: Status
- Libraries: gis_isric
- Manufacturer URL: [Link](https://soilgrids.org/)

세계 토양 정보 서비스(ISRIC)에서 제공하는 글로벌 토양 특성 지도입니다. 지질학적 분석을 위한 토양 성분(점토, 모래 등), pH 수치, 탄소 함유량 등 전 세계의 지하 자원 및 환경 정보를 레이어 형태로 시각화해 줍니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Soil Property</td></td></tbody></table>

### Infineon: DPS310

- Manufacturer: Infineon
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_DPS310
- Dependencies: [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-dps310](https://pypi.org/project/adafruit-circuitpython-dps310)
- Manufacturer URL: [Link](https://www.infineon.com/cms/en/product/sensor/pressure-sensors/pressure-sensors-for-iot/dps310/)
- Datasheet URL: [Link](https://www.infineon.com/dgdl/Infineon-DPS310-DataSheet-v01_02-EN.pdf?fileId=5546d462576f34750157750826c42242)
- Product URLs: [Link 1](https://www.adafruit.com/product/4494), [Link 2](https://shop.pimoroni.com/products/adafruit-dps310-precision-barometric-pressure-altitude-sensor-stemma-qt-qwiic), [Link 3](https://www.berrybase.de/sensoren-module/luftdruck-wasserdruck/adafruit-dps310-pr-228-zisions-barometrischer-druck-und-h-246-hen-sensor)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### KMA: KMA 단기예보

- Manufacturer: KMA
- Additional URL: [Link](https://www.data.go.kr/index.do)

이 모듈은 농업용 단기예보 데이터를 제공합니다. 가장 최근 발표를 기준으로 사용자가 선택한 시간 뒤의 예보 데이터를 수집합니다. API 호출 시 공공데이터포털의 서비스키를 사용하고, JSON 응답에서 기온, 최저/최고 기온, 풍속, 풍향, 하늘상태, 습도, 강수량, 강수확률, 강수형태, 신적설 데이터를 추출합니다. (API 제공은 발표시간 + 10분 이후부터 이루어집니다.)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>공공데이터포털에서 발급받은 KMA API 서비스키를 입력하세요.</td></tr><tr><td>nx 좌표</td><td>텍스트</td><td>nx 값을 입력하세요 (숫자).</td></tr><tr><td>ny 좌표</td><td>텍스트</td><td>ny 값을 입력하세요 (숫자).</td></tr><tr><td>몇 시간 뒤 예보</td><td>Select(Options: [<strong>1</strong> | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12] (Default in <strong>bold</strong>)</td><td>몇 시간 후의 예보 데이터를 사용할지 선택하세요.</td></tr><tr><td>API 타임아웃(초)</td><td>Integer
- Default Value: 60</td><td>API 응답 제한 시간을 설정하세요 (기본 60초).</td></tr><tr><td>API 재시도 횟수</td><td>Integer
- Default Value: 3</td><td>HTTP 오류 발생 시 같은 발표시각을 몇 번 재시도할지 설정하세요.</td></tr><tr><td>API 재시도 간격(초)</td><td>Decimal
- Default Value: 3.0</td><td>재시도 사이에 대기할 시간입니다 (기본 3초).</td></tr></tbody></table>

### KMA: 기상청 고해상도 500m

- Manufacturer: KMA
- Additional URL: [Link](https://apihub.kma.go.kr)

기상청 API 허브에서 무료 API 키를 발급받은 뒤, 입력 설정의 위치(위도/경도)에 따라 데이터를 요청합니다. 참고: 대한민국 기상청 API는 하루 20000회 호출이 가능하며, 1회 호출당 1개의 관측지점 데이터를 반환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>기상청 API 허브에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 300</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>품질검사(QC) 사용</td><td>Boolean
- Default Value: True</td><td>명백한 이상치(예: 습도 0%, 기압 0hPa 등)를 무시하거나 보정합니다.</td></tr><tr><td>QC 보정 유지시간(초)</td><td>Decimal
- Default Value: 1800</td><td>이 시간 내의 마지막 정상값으로 대체합니다.</td></tr><tr><td>수동 백필 기간(분)</td><td>Decimal
- Default Value: 1440</td><td>사용자 요청 시 과거 이 기간만큼 데이터를 불러옵니다. 기본 1440분(1일).</td></tr><tr><td>지금 백필 실행</td><td>Boolean</td><td>저장 후 활성화하면 즉시 백필을 1회 수행하고 자동으로 해제됩니다.</td></tr><tr><td>KMA 타임스탬프 오프셋(시간)</td><td>Decimal
- Default Value: 9</td><td>KMA 응답 시각이 로컬(KST,+9) 기준일 때 UTC로 저장하기 위해 빼줄 시간 (기본 9).</td></tr><tr><td>강수 계열 시계열 분리</td><td>Boolean
- Default Value: True</td><td>강수 지표(rn_ox)와 15분 강수(rn_15m)를 서로 다른 측정명으로 기록해 충돌을 방지합니다.</td></tr><tr><td>QC: 0°C 허용 범위(±°C)</td><td>Decimal
- Default Value: 3.0</td><td>직전 정상값이 0°C에서 이 범위 이내일 때만 0°C를 허용합니다. 기본 ±3°C.</td></tr></tbody></table>

### KMA: 기상청 지점 데이터

- Manufacturer: KMA
- Measurements: 습도/온도/기압/풍속/풍향
- Additional URL: [Link](https://apihub.kma.go.kr)

기상청 API 허브에서 무료 API 키를 발급받고 가까운 관측지점의 STN을 입력하세요.참고: 무료 API는 하루 20000회 호출이 가능하며, 1회 호출당 1개의 관측지점 데이터를 반환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>이 서비스 API의 API Key</td></tr><tr><td>stn</td><td>텍스트</td><td>기상 데이터를 가져올 관측소(stn)</td></tr></tbody></table>

### Kakao: KO: Kakao Map

- Manufacturer: Kakao
- Measurements: Status
- Libraries: gis_kakao
- Manufacturer URL: [Link](https://map.kakao.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Type</td></td></tbody></table>

### MAXIM: DS1822

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS1822.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS1822.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>선택</td><td>센서 해상도 선택</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS1825

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS1825.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS1825.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>선택</td><td>센서 해상도 선택</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS18B20 (ow-shell)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: ow-shell
- Dependencies: [ow-shell](https://packages.debian.org/search?keywords=ow-shell), [owfs](https://packages.debian.org/search?keywords=owfs)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS18B20.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS18B20.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/374), [Link 2](https://www.adafruit.com/product/381), [Link 3](https://www.sparkfun.com/products/245)
- Additional URL: [Link](https://github.com/cpetrich/counterfeit_DS18B20)

경고: 가짜 DS18B20 센서가 흔하며 여러 문제를 일으킬 수 있습니다. 센서가 정품인지 판별하는 방법은 Additional URL에서 확인하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### MAXIM: DS18B20 (w1thermsensor)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS18B20.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS18B20.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/374), [Link 2](https://www.adafruit.com/product/381), [Link 3](https://www.sparkfun.com/products/245)
- Additional URL: [Link](https://github.com/cpetrich/counterfeit_DS18B20)

경고: 가짜 DS18B20 센서가 흔하며 여러 문제를 일으킬 수 있습니다. 센서가 정품인지 판별하는 방법은 Additional URL에서 확인하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>적용할 온도 오프셋 (°C)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>선택</td><td>센서 해상도 선택</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS18S20

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS18S20.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS18S20.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>선택</td><td>센서 해상도 선택</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS28EA00

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/DS28EA00.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS28EA00.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>선택</td><td>센서 해상도 선택</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: MAX31850K

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/MAX31850EVKIT.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31850-MAX31851.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1727)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>선택</td><td>센서 해상도 선택</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: MAX31855 (Gravity PT100) (smbus2)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.dfrobot.com/product-1753.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### MAXIM: MAX31855 (Gravity PT100) (wiringpi)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: wiringpi
- Dependencies: [wiringpi](https://pypi.org/project/wiringpi)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.dfrobot.com/product-1753.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### MAXIM: MAX31855 (Adafruit_MAX31855)

- Manufacturer: MAXIM
- Measurements: Temperature (Object/Die)
- Interfaces: UART
- Libraries: Adafruit_MAX31855
- Dependencies: [Adafruit_MAX31855](https://github.com/adafruit/Adafruit_Python_MAX31855), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.adafruit.com/product/269)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (BCM 번호): 핀: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### MAXIM: MAX31855 (adafruit-circuitpython-max31855)

- Manufacturer: MAXIM
- Measurements: Temperature (Object/Die)
- Interfaces: SPI
- Libraries: adafruit-circuitpython-max31855
- Dependencies: [adafruit-circuitpython-max31855](https://pypi.org/project/adafruit-circuitpython-max31855)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.adafruit.com/product/269)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Chip Select Pin</td><td>Integer
- Default Value: 5</td><td>장치의 GPIO Chip Select 핀 입력.</td></tr></tbody></table>

### MAXIM: MAX31856

- Manufacturer: MAXIM
- Measurements: Temperature (Object/Die)
- Interfaces: UART
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/MAX31856.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31856.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3263)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (BCM 번호): 핀: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### MAXIM: MAX31865 (Adafruit-CircuitPython-MAX31865)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: SPI
- Libraries: Adafruit-CircuitPython-MAX31865
- Dependencies: [adafruit-circuitpython-max31865](https://pypi.org/project/adafruit-circuitpython-max31865)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31865.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31865.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3328)

이 모듈은 원래 MAX31865 모듈이 지원하지 않던, 여러 센서를 동시에 연결하는 기능을 지원하기 위해 추가되었습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Chip Select Pin</td><td>Integer
- Default Value: 8</td><td>장치의 GPIO Chip Select 핀 입력.</td></tr><tr><td>Number of wires</td><td>Select(Options: [<strong>2 Wires</strong> | 3 Wires | 4 Wires] (Default in <strong>bold</strong>)</td><td>열전대의 배선 수 선택.</td></tr></tbody></table>

### MAXIM: MAX31865 (RPi.GPIO)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: UART
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31865.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31865.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3328)

참고: 이 모듈은 여러 센서를 동시에 연결할 수 없습니다. 다중 센서 지원이 필요하면 MAX31865 CircuitPython Input을 사용하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (BCM 번호): 핀: Cable Select</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### MQTT: MQTT Subscribe (JSON payload)

- Manufacturer: MQTT
- Measurements: Variable measurements
- Interfaces: AoT
- Libraries: paho-mqtt, jmespath
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt), [jmespath](https://pypi.org/project/jmespath)

단일 토픽을 구독하며, 반환된 JSON 페이로드에는 하나 이상의 키/값 쌍이 담깁니다. 지정한 JSON Key는 JMESPATH 표현식으로 사용되어 해당 채널에 저장할 값을 찾습니다. 각 채널의 Measurement Unit을 반드시 선택하고 저장하세요. 단위를 저장한 후에는 Convert Measurement 섹션에서 다른 단위로 변환할 수 있습니다. jmespath (https://jmespath.org) 표현식 예로는 <i>temperature</i>, <i>sensors[0].temperature</i>, <i>bathroom.temperature</i>가 있으며, 각각 sensors 첫 항목의 직접 키 또는 bathroom의 하위 키로서의 temperature를 가리킵니다. 특수 문자를 포함한 jmespath 요소와 키는 큰따옴표로 묶어야 합니다. 예: <i>"sensor-1".temperature</i>. 경고: 여러 MQTT Input 또는 Function을 사용할 경우 Client ID가 고유한지 확인하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Host</td><td>Text
- Default Value: localhost</td><td>호스트 또는 IP 주소</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>호스트 포트 번호</td></tr><tr><td>Topic</td><td>Text
- Default Value: mqtt/test/input</td><td>구독할 토픽</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>수신 신호 사이의 최대 시간. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_0Rd3a2p7</td><td>서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>TLS로 로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 연결용 비밀번호. 비활성화하려면 비워 두세요.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>JMESPATH Expression</td><td>텍스트</td><td>JSON 응답에서 값을 찾는 JMESPATH 표현식</td></tr></tbody></table>

### MQTT: MQTT Subscribe (Value payload)

- Manufacturer: MQTT
- Measurements: Variable measurements
- Interfaces: AoT
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

각 채널의 Subscription Topic마다 토픽을 구독하며, 반환된 페이로드 값이 해당 채널에 저장됩니다. 각 채널의 Measurement Unit을 반드시 선택하고 저장하세요. 단위를 저장한 후에는 Convert Measurement 섹션에서 다른 단위로 변환할 수 있습니다. 경고: 여러 MQTT Input 또는 Function을 사용할 경우 Client ID가 고유한지 확인하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Host</td><td>Text
- Default Value: localhost</td><td>호스트 또는 IP 주소</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>호스트 포트 번호</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>수신 신호 사이의 최대 시간. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_oLmvWD4k</td><td>서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>TLS로 로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 연결용 비밀번호. 비활성화하려면 비워 두세요.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Subscription Topic</td><td>텍스트</td><td>구독할 MQTT 토픽</td></tr></tbody></table>

### Mapbox: GL: Mapbox

- Manufacturer: Mapbox
- Measurements: Status
- Libraries: gis_mapbox
- Manufacturer URL: [Link](https://www.mapbox.com/)

세련된 디자인과 커스터마이징이 강점인 맵박스의 벡터 및 타일 지도입니다. Streets, Satellite, Dark, Light 스타일을 지원하며, 렌더링 성능이 매우 우수하여 부드러운 지도 조작 환경을 제공합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Mapbox Access Token</td><td>텍스트</td><tr><td>지도 스타일</td></td></tbody></table>

### Melexis: MLX90393

- Manufacturer: Melexis
- Measurements: Magnetic Flux
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_MLX90393
- Dependencies: [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mlx90393](https://pypi.org/project/adafruit-circuitpython-mlx90393)
- Manufacturer URL: [Link](https://www.melexis.com/en/product/MLX90393/Triaxis-Micropower-Magnetometer)
- Datasheet URL: [Link](https://cdn-learn.adafruit.com/assets/assets/000/069/600/original/MLX90393-Datasheet-Melexis.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/4022), [Link 2](https://shop.pimoroni.com/products/adafruit-wide-range-triple-axis-magnetometer-mlx90393), [Link 3](https://www.berrybase.de/sensoren-module/bewegung-distanz/adafruit-wide-range-drei-achsen-magnetometer-mlx90393)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Melexis: MLX90614

- Manufacturer: Melexis
- Measurements: Temperature (Ambient/Object)
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.melexis.com/en/product/MLX90614/Digital-Plug-Play-Infrared-Thermometer-TO-Can)
- Datasheet URL: [Link](https://www.melexis.com/-/media/files/documents/datasheets/mlx90614-datasheet-melexis.pdf)
- Product URL: [Link](https://www.sparkfun.com/products/9570)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Microchip: MCP3008 (Adafruit_CircuitPython_MCP3xxx)

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: UART
- Libraries: Adafruit_CircuitPython_MCP3xxx
- Dependencies: [adafruit-circuitpython-mcp3xxx](https://pypi.org/project/adafruit-circuitpython-mcp3xxx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en010530)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/DeviceDoc/21295d.pdf)
- Product URL: [Link](https://www.adafruit.com/product/856)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (BCM 번호): 핀: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 3.3</td><td>VREF 전압 설정</td></tr></tbody></table>

### Microchip: MCP3008 (Adafruit_MCP3008)

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: UART
- Libraries: Adafruit_MCP3008
- Dependencies: [Adafruit-MCP3008](https://pypi.org/project/Adafruit-MCP3008)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en010530)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/DeviceDoc/21295d.pdf)
- Product URL: [Link](https://www.adafruit.com/product/856)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (BCM 번호): 핀: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 3.3</td><td>VREF 전압 설정</td></tr></tbody></table>

### Microchip: MCP3208

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: SPI
- Libraries: MCP3208
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.microchip.com/en-us/product/MCP3208)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/devicedoc/21298e.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (BCM 번호): 핀: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>SPI 버스 ID.</td></tr><tr><td>SPI Device</td><td>Integer</td><td>SPI 장치 ID.</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 3.3</td><td>VREF 전압 설정</td></tr></tbody></table>

### Microchip: MCP342x (x=2,3,4,6,7,8)

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: MCP342x
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [MCP342x](https://pypi.org/project/MCP342x)
- Manufacturer URLs: [Link 1](https://www.microchip.com/wwwproducts/en/MCP3422), [Link 2](https://www.microchip.com/wwwproducts/en/MCP3423), [Link 3](https://www.microchip.com/wwwproducts/en/MCP3424), [Link 4](https://www.microchip.com/wwwproducts/en/MCP3426https://www.microchip.com/wwwproducts/en/MCP3427), [Link 5](https://www.microchip.com/wwwproducts/en/MCP3428)
- Datasheet URLs: [Link 1](http://ww1.microchip.com/downloads/en/DeviceDoc/22088c.pdf), [Link 2](http://ww1.microchip.com/downloads/en/DeviceDoc/22226a.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Microchip: MCP9808

- Manufacturer: Microchip
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_MCP9808
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit_MCP9808](https://github.com/adafruit/Adafruit_Python_MCP9808)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en556182)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/DeviceDoc/MCP9808-0.5C-Maximum-Accuracy-Digital-Temperature-Sensor-Data-Sheet-DS20005095B.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1782)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Microsoft: GL: Bing Maps

- Manufacturer: Microsoft
- Measurements: Status
- Libraries: gis_bing
- Manufacturer URL: [Link](https://www.bing.com/maps)

마이크로소프트의 글로벌 지도 서비스입니다. 고해상도 항공 사진(Aerial)과 이름이 포함된 항공 사진(Hybrid)을 제공하며, MS만의 깨끗하고 정밀한 도로 지도를 활용할 수 있는 장점이 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bing Maps API Key</td><td>텍스트</td><tr><td>지도 스타일</td></td></tbody></table>

### Multiple Manufacturers: HC-SR04

- Manufacturer: Multiple Manufacturers
- Measurements: Ultrasonic Distance
- Interfaces: GPIO
- Libraries: Adafruit_CircuitPython_HCSR04
- Dependencies: [libgpiod-dev](https://packages.debian.org/search?keywords=libgpiod-dev), [pyusb](https://pypi.org/project/pyusb), [adafruit-circuitpython-hcsr04](https://pypi.org/project/adafruit-circuitpython-hcsr04)
- Manufacturer URL: [Link](https://www.cytron.io/p-5v-hc-sr04-ultrasonic-sensor)
- Datasheet URL: [Link](http://web.eece.maine.edu/~zhu/book/lab/HC-SR04%20User%20Manual.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3942)
- Additional URL: [Link](https://learn.adafruit.com/ultrasonic-sonar-distance-sensors/python-circuitpython)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Trigger Pin</td><td>Integer</td><td>장치의 GPIO Trigger 핀을 입력하세요(BCM 번호).</td></tr><tr><td>Echo Pin</td><td>Integer</td><td>장치의 GPIO Echo 핀을 입력하세요(BCM 번호).</td></tr></tbody></table>

### NASA: NASA GIBS

- Manufacturer: NASA
- Measurements: Status
- Interfaces: AoT
- Libraries: gis_nasa_gibs
- Manufacturer URL: [Link](https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs)

미국 항공우주국(NASA)의 위성 관측 시스템(GIBS)을 통해 수집된 실시간 지구 관측 지도입니다. 위성 사진(Blue Marble)뿐만 아니라 기온, 구름, 화재 등 환경 관련 데이터를 날짜별로 선택하여 시계열 분석이 가능합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Satellite Layer</td></td><tr><td>Date Mode</td><td>선택</td><tr><td>Custom Date</td><td>텍스트</td></tbody></table>

### Naver: KO: Naver Map

- Manufacturer: Naver
- Measurements: Status
- Libraries: gis_naver
- Manufacturer URL: [Link](https://map.naver.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Type</td></td></tbody></table>

### OpenStreetMap: GL: OpenStreetMap

- Manufacturer: OpenStreetMap
- Measurements: Status
- Libraries: gis_osm
- Manufacturer URL: [Link](https://www.openstreetmap.org/)

전 세계 사용자들이 협업하여 만든 위키피디아 방식의 자유 지도 데이터입니다. 무료로 사용 가능하며, 전 세계 도로와 건물 정보가 꾸준히 업데이트되는 활발한 커뮤니티 성격의 표준 웹 지도입니다.


### OpenTopoMap: GL: OpenTopoMap

- Manufacturer: OpenTopoMap
- Measurements: Status
- Libraries: gis_opentopomap
- Manufacturer URL: [Link](https://opentopomap.org)

OpenStreetMap 데이터를 기반으로 등고선과 지형 음영을 강조한 지형도 서비스입니다. 산악 지형이나 경사면 분석 시 구분이 명확하며 가독성이 높아 등산이나 야외 활동 관련 시각화에 적합합니다.


### OpenWeather: OpenWeatherMap (City/Coords, Current)

- Manufacturer: OpenWeather
- Measurements: Humidity/Temperature/Pressure/Wind
- Additional URL: [Link](https://openweathermap.org)

Obtain a free API key at openweathermap.org. Enter a City OR Latitude/Longitude coordinates. Note: the free API subscription is limited to 60 calls per minute
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>이 서비스 API의 API Key</td></tr><tr><td>City</td><td>텍스트</td><td>도시 이름 (좌표 사용 시 선택)</td></tr></tbody></table>

### OpenWeather: OpenWeatherMap (Lat/Lon, Current/Future)

- Manufacturer: OpenWeather
- Measurements: Humidity/Temperature/Pressure/Wind
- Interfaces: AoT
- Additional URL: [Link](https://openweathermap.org)

openweathermap.org에서 무료 API 키를 발급받으세요. 참고: 무료 API 구독은 분당 60회 호출로 제한됩니다. Day (Future) 시간을 선택하면 최저 및 최고 온도를 측정값으로 사용할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>API Key</td><td>텍스트</td><td>이 서비스 API의 API Key</td></tr><tr><td>Time</td><td>Select(Options: [<strong>Current (Present)</strong> | 1 Day (Future) | 2 Day (Future) | 3 Day (Future) | 4 Day (Future) | 5 Day (Future) | 6 Day (Future) | 7 Day (Future) | 1 Hour (Future) | 2 Hours (Future) | 3 Hours (Future) | 4 Hours (Future) | 5 Hours (Future) | 6 Hours (Future) | 7 Hours (Future) | 8 Hours (Future) | 9 Hours (Future) | 10 Hours (Future) | 11 Hours (Future) | 12 Hours (Future) | 13 Hours (Future) | 14 Hours (Future) | 15 Hours (Future) | 16 Hours (Future) | 17 Hours (Future) | 18 Hours (Future) | 19 Hours (Future) | 20 Hours (Future) | 21 Hours (Future) | 22 Hours (Future) | 23 Hours (Future) | 24 Hours (Future) | 25 Hours (Future) | 26 Hours (Future) | 27 Hours (Future) | 28 Hours (Future) | 29 Hours (Future) | 30 Hours (Future) | 31 Hours (Future) | 32 Hours (Future) | 33 Hours (Future) | 34 Hours (Future) | 35 Hours (Future) | 36 Hours (Future) | 37 Hours (Future) | 38 Hours (Future) | 39 Hours (Future) | 40 Hours (Future) | 41 Hours (Future) | 42 Hours (Future) | 43 Hours (Future) | 44 Hours (Future) | 45 Hours (Future) | 46 Hours (Future) | 47 Hours (Future) | 48 Hours (Future)] (Default in <strong>bold</strong>)</td><td>현재 또는 예보 날씨의 시간을 선택하세요.</td></tr></tbody></table>

### OpenWeatherMap: GL: OpenWeatherMap

- Manufacturer: OpenWeatherMap
- Measurements: Status
- Libraries: gis_openweather
- Manufacturer URL: [Link](https://openweathermap.org/)

전 세계 날씨 정보를 지도에 중첩하여 보여주는 기상 전문 서비스입니다. 구름, 강수량, 기온, 풍속, 기압 및 레이더 정보를 실시간으로 제공하여 현재 기상 상황을 직관적으로 파악할 수 있게 돕습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>텍스트</td><tr><td>활성 레이어</td></td></tbody></table>

### Panasonic: AMG8833

- Manufacturer: Panasonic
- Measurements: 8x8 Temperature Grid
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_AMG88xx/Pillow/colour
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [colour](https://pypi.org/project/colour), [Pillow](https://pypi.org/project/Pillow), [Adafruit_AMG88xx](https://github.com/adafruit/Adafruit_AMG88xx_python)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Power Monitor: RPi 6-Channel Power Monitor (v0.1.0)

- Manufacturer: Power Monitor
- Measurements: AC Voltage, Power, Current, Power Factor
- Libraries: rpi-power-monitor
- Dependencies: [rpi_power_monitor](https://github.com/aot-inc/rpi-power-monitor)
- Manufacturer URL: [Link](https://github.com/David00/rpi-power-monitor)
- Product URL: [Link](https://power-monitor.dalbrecht.tech/)

보정 절차는 https://github.com/David00/rpi-power-monitor/wiki/Calibrating-for-Accuracy 를 참고하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Grid Voltage</td><td>Decimal
- Default Value: 124.2</td><td>콘센트에서 측정한 AC 전압</td></tr><tr><td>Transformer Voltage</td><td>Decimal
- Default Value: 10.2</td><td>9 VAC 변압기의 배럴 플러그에서 측정된 AC 전압</td></tr><tr><td>CT1 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>CT1의 위상 보정값</td></tr><tr><td>CT2 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>CT2의 위상 보정값</td></tr><tr><td>CT3 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>CT3의 위상 보정값</td></tr><tr><td>CT4 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>CT4의 위상 보정값</td></tr><tr><td>CT5 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>CT5의 위상 보정값</td></tr><tr><td>CT6 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>CT6의 위상 보정값</td></tr><tr><td>CT1 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT1의 정확도 보정 값</td></tr><tr><td>CT2 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT2의 정확도 보정 값</td></tr><tr><td>CT3 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT3의 정확도 보정 값</td></tr><tr><td>CT4 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT4의 정확도 보정 값</td></tr><tr><td>CT5 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT5의 정확도 보정 값</td></tr><tr><td>CT6 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT6의 정확도 보정 값</td></tr><tr><td>AC Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>AC 정확도 보정값</td></tr></tbody></table>

### Power Monitor: RPi 6-Channel Power Monitor (v0.4.0)

- Manufacturer: Power Monitor
- Measurements: AC Voltage, Power, Energy, Current, Power Factor
- Libraries: rpi-power-monitor
- Dependencies: [rpi_power_monitor](https:/)
- Manufacturer URL: [Link](https://github.com/David00/rpi-power-monitor)
- Product URL: [Link](https://power-monitor.dalbrecht.tech/)

보정 문서는 https://david00.github.io/rpi-power-monitor/docs/v0.3.0/calibration.html 을 참고하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Period (Seconds) for kWh Measuring</td><td>Integer
- Default Value: 5</td><td>kWh 계산을 위해 측정값을 취득하는 주기</td></tr><tr><td>Grid Voltage</td><td>Decimal
- Default Value: 124.2</td><td>콘센트에서 측정한 AC 전압</td></tr><tr><td>Transformer Voltage</td><td>Decimal
- Default Value: 10.2</td><td>9 VAC 변압기의 배럴 플러그에서 측정된 AC 전압</td></tr><tr><td>AC Frequency (Hz)</td><td>Integer
- Default Value: 60</td><td>AC 전압의 주파수</td></tr><tr><td>CT1 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT1의 보정값</td></tr><tr><td>CT1 Rating</td><td>Decimal
- Default Value: 100</td><td>CT1 클램프의 전류(Amp) 정격</td></tr><tr><td>CT2 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT2의 보정값</td></tr><tr><td>CT2 Rating</td><td>Decimal
- Default Value: 100</td><td>CT2 클램프의 전류(Amp) 정격</td></tr><tr><td>CT3 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT3의 보정값</td></tr><tr><td>CT3 Rating</td><td>Decimal
- Default Value: 100</td><td>CT3 클램프의 전류(Amp) 정격</td></tr><tr><td>CT4 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT4의 보정값</td></tr><tr><td>CT4 Rating</td><td>Decimal
- Default Value: 100</td><td>CT4 클램프의 전류(Amp) 정격</td></tr><tr><td>CT5 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT5의 보정값</td></tr><tr><td>CT5 Rating</td><td>Decimal
- Default Value: 100</td><td>CT5 클램프의 전류(Amp) 정격</td></tr><tr><td>CT6 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>CT6의 보정값</td></tr><tr><td>CT6 Rating</td><td>Decimal
- Default Value: 100</td><td>CT6 클램프의 전류(Amp) 정격</td></tr><tr><td>AC Calibration</td><td>Decimal
- Default Value: 1.0</td><td>AC의 보정값</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Clear the running kWh totals.</td></tr><tr><td>Channel to Clear</td><td>Select(Options: [All Channels | <strong>Channel 1</strong> | Channel 2 | Channel 3 | Channel 4 | Channel 5 | Channel 6] (Default in <strong>bold</strong>)</td><td>kWh 합계를 초기화하고 0부터 다시 시작할 채널</td></tr><tr><td>Clear kWh Total</td><td>Button</td><td></td></tr></tbody></table>

### ROHM: BH1750

- Manufacturer: ROHM
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Datasheet URL: [Link](http://rohmfs.rohm.com/en/products/databook/datasheet/ic/sensor/light/bh1721fvc-e.pdf)
- Product URL: [Link](https://www.dfrobot.com/product-531.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### RainViewer: GL: RainViewer (Radar) [Discontinued]

- Manufacturer: RainViewer
- Measurements: Status
- Libraries: gis_rainviewer
- Manufacturer URL: [Link](https://www.rainviewer.com/)

[Service Discontinued / 서비스 중단 안내] RainViewer의 Radar API 서비스가 2026년 1월 31일부로 종료되었습니다. 현재 이 레이어의 실시간 데이터 수신은 불가능합니다. 대안으로 OpenWeatherMap (Radar) 레이어 사용을 권장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>텍스트</td><tr><td>Color Scheme</td><td>선택</td><tr><td>Smoothing</td><td>Boolean</td></tbody></table>

### Raspberry Pi Foundation: Sense HAT

- Manufacturer: Raspberry Pi Foundation
- Measurements: hum/temp/press/compass/magnet/accel/gyro
- Interfaces: I<sup>2</sup>C
- Libraries: sense-hat
- Dependencies: [git](https://packages.debian.org/search?keywords=git), Bash Commands (see Module for details), [sense-hat](https://pypi.org/project/sense-hat)
- Manufacturer URL: [Link](https://www.raspberrypi.org/products/sense-hat/)

이 모듈은 LPS25H, LSM9DS1, HTS221을 포함한 Raspberry Pi Sense HAT 센서로부터 측정값을 획득합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Remote Sensing: Satellite Analysis

- Manufacturer: Remote Sensing
- Measurements: Analysis Channels
- Interfaces: AoT
- Libraries: requests

기기 위치를 기준으로 위성 분석과 GIS 레이어에서 환경 데이터를 수집합니다. 데이터 공백(예: 해안 지역)에 대한 자동 보정을 지원합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Active GIS Source</td><td>선택</td><td>위성/GIS 분석 소스 선택.</td></tr><tr><td>Auto-adjust Location</td><td>Boolean
- Default Value: True</td><td>정확한 위치에 데이터가 없으면 인근의 유효한 좌표를 자동으로 검색합니다(Spiral Search).</td></tr></tbody></table>

### Ruuvi: RuuviTag

- Manufacturer: Ruuvi
- Measurements: Acceleration/Humidity/Pressure/Temperature
- Interfaces: BT
- Libraries: ruuvitag_sensor
- Dependencies: [psutil](https://pypi.org/project/psutil), [bluez](https://packages.debian.org/search?keywords=bluez), [bluez-hcidump](https://packages.debian.org/search?keywords=bluez-hcidump), [ruuvitag-sensor](https://pypi.org/project/ruuvitag-sensor)
- Manufacturer URL: [Link](https://ruuvi.com/)
- Datasheet URL: [Link](https://ruuvi.com/files/ruuvitag-tech-spec-2019-7.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>텍스트</td><td>블루투스 장치의 Hci 위치.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>텍스트</td><td>Bluetooth 장치의 어댑터.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### STMicroelectronics: VL53L0X

- Manufacturer: STMicroelectronics
- Measurements: Millimeter (Time-of-Flight Distance)
- Interfaces: I<sup>2</sup>C
- Libraries: VL53L0X_rasp_python
- Dependencies: [VL53L0X](https://github.com/grantramsay/VL53L0X_rasp_python)
- Manufacturer URL: [Link](https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html)
- Datasheet URL: [Link](https://www.st.com/resource/en/datasheet/vl53l0x.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3317), [Link 2](https://www.pololu.com/product/2490)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Accuracy</td><td>Select(Options: [<strong>Good Accuracy (33 ms, 1.2 m range)</strong> | Better Accuracy (66 ms, 1.2 m range) | Best Accuracy (200 ms, 1.2 m range) | Long Range (33 ms, 2 m) | High Speed, Low Accuracy (20 ms, 1.2 m)] (Default in <strong>bold</strong>)</td><td>정확도를 설정합니다. 측정 시간이 길수록 더 정확한 측정값을 얻습니다.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x52</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### STMicroelectronics: VL53L1X

- Manufacturer: STMicroelectronics
- Measurements: Millimeter (Time-of-Flight Distance)
- Interfaces: I<sup>2</sup>C
- Libraries: VL53L1X
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [vl53l1x](https://pypi.org/project/vl53l1x)
- Manufacturer URL: [Link](https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x.html)
- Datasheet URL: [Link](https://www.st.com/resource/en/datasheet/vl53l1x.pdf)
- Product URLs: [Link 1](https://www.pololu.com/product/3415), [Link 2](https://www.sparkfun.com/products/14722)

사용자 지정 timing budget 설정 시 참고: timing budget이 높을수록 측정 정확도가 높아지지만 소비 전력도 커집니다. inter measurement period는 timing budget 이상이어야 하며, 그렇지 않으면 예상값의 두 배가 됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Range</td><td>Select(Options: [<strong>Short Range</strong> | Medium Range | Long Range | Custom Timing Budget] (Default in <strong>bold</strong>)</td><td>범위를 선택하거나 사용자 지정 Timing Budget 및 Inter Measurement Period를 설정하도록 선택하세요.</td></tr><tr><td>Timing Budget (microseconds)</td><td>Integer
- Default Value: 66000</td><td>타이밍 버짓을 설정합니다. Inter Measurement Period 이하여야 합니다.</td></tr><tr><td>Inter Measurement Period (milliseconds)</td><td>Integer
- Default Value: 70</td><td>Inter Measurement 주기 설정</td></tr></tbody></table>

### STMicroelectronics: VL53L4CD

- Manufacturer: STMicroelectronics
- Measurements: Millimeter (Time-of-Flight Distance)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit-CircuitPython-VL53l4CD
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-vl53l4cd](https://pypi.org/project/adafruit-circuitpython-vl53l4cd)
- Manufacturer URL: [Link](https://www.st.com/en/imaging-and-photonics-solutions/VL53L4CD.html)
- Datasheet URL: [Link](https://www.st.com/resource/en/datasheet/VL53L4CDpdf)
- Product URL: [Link](https://www.adafruit.com/product/3317)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Timing Budget (ms)</td><td>Integer
- Default Value: 50</td><td>timing budget을 10~200 ms 사이로 설정하세요. 시간이 길수록 더 정확한 측정값이 나옵니다.</td></tr><tr><td>Inter-Measurement Period (ms)</td><td>Integer</td><td>유효 범위는 Timing Budget에서 5000 ms 사이(0이면 비활성화)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The I2C address of the sensor can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate the Input and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x29</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Seeedstudio: DHT11/22

- Manufacturer: Seeedstudio
- Measurements: Humidity/Temperature
- Interfaces: GROVE
- Libraries: grovepi
- Dependencies: [libatlas-base-dev](https://packages.debian.org/search?keywords=libatlas-base-dev), [grovepi](https://pypi.org/project/grovepi)
- Manufacturer URLs: [Link 1](https://wiki.seeedstudio.com/Grove-Temperature_and_Humidity_Sensor_Pro/), [Link 2](https://wiki.seeedstudio.com/Grove-TemperatureAndHumidity_Sensor/)

센서에 연결된 Grove Pi+ GPIO 핀을 입력하고 센서 종류를 선택하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Sensor Type</td><td>Select(Options: [<strong>DHT11 (Blue)</strong> | DHT22 (White)] (Default in <strong>bold</strong>)</td><td>센서 유형</td></tr></tbody></table>

### Senseair: K96

- Manufacturer: Senseair
- Measurements: Methane/Moisture/CO2/Pressure/Humidity/Temperature
- Interfaces: UART
- Libraries: Serial
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Sensirion: SCD-4x (40, 41)

- Manufacturer: Sensirion
- Measurements: CO2/Temperature/Humidity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SCD4x
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-scd4x](https://pypi.org/project/adafruit-circuitpython-scd4x)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/carbon-dioxide-sensors/carbon-dioxide-sensor-scd4x/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Offset</td><td>Decimal
- Default Value: 4.0</td><td>센서 온도 오프셋 설정</td></tr><tr><td>Altitude (m)</td><td>Integer</td><td>센서 고도 설정 (미터)</td></tr><tr><td>Automatic Self-Calibration</td><td>Boolean</td><td>센서 자동 자가 보정 설정</td></tr><tr><td>Persist Settings</td><td>Boolean
- Default Value: True</td><td>전원을 꺼도 설정 유지</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">You can force the CO2 calibration for a specific CO2 concentration value (in ppmv). The sensor needs to be active for at least 3 minutes prior to calibration.</td></tr><tr><td>CO2 Concentration (ppmv)</td><td>Decimal
- Default Value: 400.0</td><td>센서가 노출된 CO2 농도(ppmv)로 보정합니다.</td></tr><tr><td>Calibrate CO2</td><td>Button</td><td></td></tr></tbody></table>

### Sensirion: SCD30 (Adafruit_CircuitPython_SCD30)

- Manufacturer: Sensirion
- Measurements: CO2/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SCD30
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitPython-scd30](https://pypi.org/project/adafruit-circuitPython-scd30)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/carbon-dioxide-sensors/carbon-dioxide-sensors-co2/)
- Datasheet URL: [Link](https://www.sensirion.com/fileadmin/user_upload/customers/sensirion/Dokumente/9.5_CO2/Sensirion_CO2_Sensors_SCD30_Datasheet.pdf)
- Product URLs: [Link 1](https://www.sparkfun.com/products/15112), [Link 2](https://www.futureelectronics.com/p/4115766)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">I2C Frequency: The SCD-30 has temperamental I2C with clock stretching. The datasheet recommends starting at 50,000 Hz.</td></tr><tr><td>I2C Frequency (Hz)</td><td>Integer
- Default Value: 50000</td><tr><td colspan="3">Automatic Self Ccalibration (ASC): To work correctly, the sensor must be on and active for 7 days after enabling ASC, and exposed to fresh air for at least 1 hour per day. Consult the manufacturer’s documentation for more information.</td></tr><tr><td>Enable Automatic Self Calibration</td><td>Boolean</td><tr><td colspan="3">Temperature Offset: Specifies the offset to be added to the reported measurements to account for a bias in the measured signal. Must be a positive value, and will reduce the recorded temperature by that amount. Give the sensor adequate time to acclimate after setting this value. Value is in degrees Celsius with a resolution of 0.01 degrees and a maximum value of 655.35 C.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><tr><td colspan="3">Ambient Air Pressure (mBar): Specify the ambient air pressure at the measurement location in mBar. Setting this value adjusts the CO2 measurement calculations to account for the air pressure’s effect on readings. Values must be in mBar, from 700 to 1200 mBar.</td></tr><tr><td>Ambient Air Pressure (mBar)</td><td>Integer
- Default Value: 1200</td><tr><td colspan="3">Altitude: Specifies the altitude at the measurement location in meters above sea level. Setting this value adjusts the CO2 measurement calculations to account for the air pressure’s effect on readings.</td></tr><tr><td>Altitude (m)</td><td>Integer
- Default Value: 100</td><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A soft reset restores factory default values.</td></tr><tr><td>Soft Reset</td><td>Button</td><td></td></tr><tr><td colspan="3">Forced Re-Calibration: The SCD-30 is placed in an environment with a known CO2 concentration, this concentration value is entered in the CO2 Concentration (ppmv) field, then the Foce Calibration button is pressed. But how do you come up with that known value? That is a caveat of this approach and Sensirion suggests three approaches: 1. Using a separate secondary calibrated CO2 sensor to provide the value. 2. Exposing the SCD-30 to a controlled environment with a known value. 3. Exposing the SCD-30 to fresh outside air and using a value of 400 ppm.</td></tr><tr><td>CO2 Concentration (ppmv)</td><td>Integer
- Default Value: 800</td><td>강제 보정 시 센서 환경의 CO2 농도</td></tr><tr><td>Force Recalibration</td><td>Button</td><td></td></tr></tbody></table>

### Sensirion: SCD30 (scd30_i2c)

- Manufacturer: Sensirion
- Measurements: CO2/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: scd30_i2c
- Dependencies: [scd30-i2c](https://pypi.org/project/scd30-i2c)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/carbon-dioxide-sensors/carbon-dioxide-sensors-co2/)
- Datasheet URL: [Link](https://www.sensirion.com/fileadmin/user_upload/customers/sensirion/Dokumente/9.5_CO2/Sensirion_CO2_Sensors_SCD30_Datasheet.pdf)
- Product URLs: [Link 1](https://www.sparkfun.com/products/15112), [Link 2](https://www.futureelectronics.com/p/4115766)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td colspan="3">Automatic Self Ccalibration (ASC): To work correctly, the sensor must be on and active for 7 days after enabling ASC, and exposed to fresh air for at least 1 hour per day. Consult the manufacturer’s documentation for more information.</td></tr><tr><td>Enable Automatic Self Calibration</td><td>Boolean</td><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A soft reset restores factory default values.</td></tr><tr><td>Soft Reset</td><td>Button</td><td></td></tr></tbody></table>

### Sensirion: SHT1x/7x

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: GPIO
- Libraries: sht_sensor
- Dependencies: [sht-sensor](https://pypi.org/project/sht-sensor)
- Manufacturer URLs: [Link 1](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-accurate-measurements/), [Link 2](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/pintype-digital-humidity-sensors/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Sensirion: SHT2x (sht20)

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: sht20
- Dependencies: [sht20](https://pypi.org/project/sht20)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/humidity-temperature-sensor-sht2x-digital-i2c-accurate/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Resolution</td><td>Select(Options: [11-bit | 12-bit | 13-bit | <strong>14-bit</strong>] (Default in <strong>bold</strong>)</td><td>온도 Measurement의 분해능</td></tr></tbody></table>

### Sensirion: SHT2x (smbus2)

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/humidity-temperature-sensor-sht2x-digital-i2c-accurate/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Sensirion: SHT31-D

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SHT31
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-sht31d](https://pypi.org/project/adafruit-circuitpython-sht31d)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>적용할 온도 오프셋 (°C)</td></tr></tbody></table>

### Sensirion: SHT3x (30, 31, 35)

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_SHT31
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-SHT31](https://pypi.org/project/Adafruit-SHT31)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Enable Heater</td><td>Boolean</td><td>결로를 증발시키기 위해 히터를 활성화합니다. y회 측정마다 히터를 x초 동안 켭니다.</td></tr><tr><td>Heater On Seconds (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>히터 켜짐 시간</td></tr><tr><td>Heater On Period</td><td>Integer
- Default Value: 10</td><td>몇 번 측정 후 히터를 켤지. 반복 적용됩니다.</td></tr></tbody></table>

### Sensirion: SHT4X

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SHT4X
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit_circuitpython_sht4x](https://pypi.org/project/adafruit_circuitpython_sht4x)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Sensirion: SHTC3

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SHT3C
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit_circuitpython_shtc3](https://pypi.org/project/adafruit_circuitpython_shtc3)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Sensorion: SHT31 Smart Gadget

- Manufacturer: Sensorion
- Measurements: Humidity/Temperature
- Interfaces: BT
- Libraries: bluepy
- Dependencies: [pi-bluetooth](https://packages.debian.org/search?keywords=pi-bluetooth), [libglib2.0-dev](https://packages.debian.org/search?keywords=libglib2.0-dev), [bluepy](https://pypi.org/project/bluepy)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/development-kit/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>텍스트</td><td>블루투스 장치의 Hci 위치.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>텍스트</td><td>Bluetooth 장치의 어댑터.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Download Stored Data</td><td>Boolean
- Default Value: True</td><td>장치에 기록된 데이터 다운로드.</td></tr><tr><td>Set Logging Interval (Seconds)</td><td>Integer
- Default Value: 600</td><td>기기가 내부 메모리에 측정값을 저장할 로깅 간격을 설정하세요.</td></tr></tbody></table>

### Silicon Labs: SI1145

- Manufacturer: Silicon Labs
- Measurements: Light (UV/Visible/IR), Proximity (cm)
- Interfaces: I<sup>2</sup>C
- Libraries: si1145
- Dependencies: [SI1145](https://pypi.org/project/SI1145)
- Manufacturer URL: [Link](https://learn.adafruit.com/adafruit-si1145-breakout-board-uv-ir-visible-sensor)
- Datasheet URL: [Link](https://www.silabs.com/support/resources.p-sensors_optical-sensors_si114x)
- Product URL: [Link](https://www.adafruit.com/product/1777)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Silicon Labs: Si7021

- Manufacturer: Silicon Labs
- Measurements: Temperature/Humidity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SI7021
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-si7021](https://pypi.org/project/adafruit-circuitpython-si7021)
- Datasheet URL: [Link](https://www.silabs.com/documents/public/data-sheets/Si7021-A20.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Sonoff: TH16/10 (Tasmota firmware) with AM2301/Si7021

- Manufacturer: Sonoff
- Measurements: Humidity/Temperature
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)
- Manufacturer URL: [Link](https://sonoff.tech/product/wifi-diy-smart-switches/th10-th16)

이 Input 모듈은 TH10/TH16과 함께 어떤 온습도 센서든 사용할 수 있게 해줍니다. Sensor Name 옵션을 변경하면 반환된 측정값 딕셔너리에서 조회하는 키가 바뀝니다. AM2301을 사용하는 버전의 기기에서 이 모듈을 사용하려면 Sensor Name을 AM2301로 변경하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>IP Address</td><td>Text
- Default Value: 192.168.0.100</td><td>장치의 IP 주소</td></tr><tr><td>Sensor Name</td><td>Text
- Default Value: SI7021</td><td>기기에 연결된 센서의 이름입니다(반환된 딕셔너리의 특정 키 이름).</td></tr></tbody></table>

### Sonoff: TH16/10 (Tasmota firmware) with AM2301

- Manufacturer: Sonoff
- Measurements: Humidity/Temperature
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)
- Manufacturer URL: [Link](https://sonoff.tech/product/wifi-diy-smart-switches/th10-th16)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>IP Address</td><td>Text
- Default Value: 192.168.0.100</td><td>장치의 IP 주소</td></tr></tbody></table>

### Sonoff: TH16/10 (Tasmota firmware) with DS18B20

- Manufacturer: Sonoff
- Measurements: Temperature
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)
- Manufacturer URL: [Link](https://sonoff.tech/product/wifi-diy-smart-switches/th10-th16)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>IP Address</td><td>Text
- Default Value: 192.168.0.100</td><td>장치의 IP 주소</td></tr></tbody></table>

### Stadia Maps: GL: Stadia Maps

- Manufacturer: Stadia Maps
- Measurements: Status
- Libraries: gis_stadia
- Manufacturer URL: [Link](https://stadiamaps.com/)

고품질 디자인을 강조하는 Stadia Maps의 지도 서버입니다. Alidade Smooth, Dark, OSMBright 등 눈이 편안한 색감과 고품질 폰트가 적용된 깔끔한 레이아웃을 제공하여 전문가용 대시보드 제작에 유리합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Stadia/Stamen API Key</td><td>텍스트</td><tr><td>지도 스타일</td></td></tbody></table>

### Statistics Korea: KO: SGIS (Statistics Korea)

- Manufacturer: Statistics Korea
- Measurements: Status
- Libraries: gis_sgis
- Manufacturer URL: [Link](https://sgis.kostat.go.kr/)

대한민국 통계청(SGIS)에서 제공하는 통계 지리 정보 서비스입니다. 한국의 시군구별 인구, 가구, 사업체 등 다양한 통계 데이터를 공간적으로 분석하고 시각화하기 위한 최적의 국내 전용 서비스입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>SGIS Service ID (Consumer Key)</td><td>텍스트</td><tr><td>SGIS Security Key (Consumer Secret)</td><td>텍스트</td><tr><td>Data Configuration</td></td><tr><td>Statistic Subject</td><td>선택</td><tr><td>Year (YYYY)</td><td>텍스트</td><tr><td>Target Admin Code (adm_cd)</td><td>텍스트</td><tr><td>Visualization</td><td>선택</td></tbody></table>

### TE Connectivity: HTU21D (Adafruit_CircuitPython_HTU21D)

- Manufacturer: TE Connectivity
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_HTU21D
- Dependencies: [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-HTU21D](https://pypi.org/project/adafruit-circuitpython-HTU21D)
- Manufacturer URL: [Link](https://www.te.com/usa-en/product-CAT-HSC0004.html)
- Datasheet URL: [Link](https://www.te.com/commerce/DocumentDelivery/DDEController?Action=showdoc&DocId=Data+Sheet%7FHPC199_6%7FA6%7Fpdf%7FEnglish%7FENG_DS_HPC199_6_A6.pdf%7FCAT-HSC0004)
- Product URL: [Link](https://www.adafruit.com/product/1899)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>적용할 온도 오프셋 (°C)</td></tr></tbody></table>

### TE Connectivity: HTU21D (pigpio)

- Manufacturer: TE Connectivity
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
- Manufacturer URL: [Link](https://www.te.com/usa-en/product-CAT-HSC0004.html)
- Datasheet URL: [Link](https://www.te.com/commerce/DocumentDelivery/DDEController?Action=showdoc&DocId=Data+Sheet%7FHPC199_6%7FA6%7Fpdf%7FEnglish%7FENG_DS_HPC199_6_A6.pdf%7FCAT-HSC0004)
- Product URL: [Link](https://www.adafruit.com/product/1899)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### TP-Link: Kasa WiFi Power Plug/Strip Energy Statistics

- Manufacturer: TP-Link
- Measurements: kilowatt hours
- Interfaces: IP
- Libraries: python-kasa
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-plug-slim-energy-monitoring-kp115)

이것은 에너지 소비 측정이 가능한 여러 Kasa 전원 기기(플러그/스트립)로부터 측정합니다. KP115와 HS600 등을 포함하지만 이에 국한되지 않습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Device Type</td><td>선택</td><td>Kasa 장치 유형</td></tr><tr><td>Host</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18063</td><td>asyncio RPC 서버를 시작할 포트. 다른 Kasa Output과 겹치지 않아야 합니다.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The total kWh can be cleared with the following button or with the Clear Total kWh Function Action. This will also clear all energy stats on the device, not just the total kWh.</td></tr><tr><td>Clear Total: Kilowatt-hour</td><td>Button</td><td></td></tr></tbody></table>

### Tasmota: Tasmota Outlet Energy Monitor (HTTP)

- Manufacturer: Tasmota
- Measurements: Total Energy, Amps, Watts
- Interfaces: HTTP
- Libraries: requests
- Manufacturer URL: [Link](https://tasmota.github.io)
- Product URL: [Link](https://templates.blakadder.com/plug.html)

이 Input은 tasmota 펌웨어가 실행 중인 WiFi 콘센트로부터 에너지 사용 정보를 조회합니다. tasmota를 지원하는 WiFi 콘센트는 많고 그중 상당수가 에너지 모니터링 기능을 갖추고 있습니다. MQTT Output과 함께 사용하면 tasmota 콘센트를 제어하는 동시에 에너지 사용량을 모니터링할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Host</td><td>Text
- Default Value: 192.168.0.50</td><td>호스트 또는 IP 주소</td></tr></tbody></table>

### Texas Instruments: ADS1015

- Manufacturer: Texas Instruments
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADS1x15
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ads1x15](https://pypi.org/project/adafruit-circuitpython-ads1x15)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>각 채널을 측정할 횟수입니다. 측정값들의 평균이 저장됩니다.</td></tr></tbody></table>

### Texas Instruments: ADS1115: Generic Analog pH/EC

- Manufacturer: Texas Instruments
- Measurements: Ion Concentration/Electrical Conductivity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADS1x15
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ads1x15](https://pypi.org/project/adafruit-circuitpython-ads1x15)

이 Input은 ADS1115 아날로그-디지털 변환기(ADC)를 사용해 아날로그 센서로부터 pH 및/또는 전기전도도(EC)를 측정합니다. pH 센서나 EC 센서만 연결하려면 Measurements Enabled에서 원하는 측정 항목을 선택해 각 측정을 켜거나 끌 수 있습니다. 각 센서가 ADC의 어느 채널에 연결되어 있는지 선택하세요. Input에는 초기 기본 보정값이 설정되어 있습니다. 또한 보정액으로 센서를 쉽게 보정할 수 있는 기능도 제공됩니다. Calibrate Slot 액션을 사용하면 이 값들이 계산되어 현재 설정값을 대체합니다. Clear Calibration 액션을 사용하면 데이터베이스 값을 삭제하고 기본값으로 되돌릴 수 있습니다. Input을 삭제하거나 해당 ADC/센서를 쓸 새 Input을 만들면, 새 보정 데이터를 저장하기 위해 다시 보정해야 합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>ADC Channel: pH</td><td>Select(Options: [<strong>Channel 0</strong> | Channel 1 | Channel 2 | Channel 3] (Default in <strong>bold</strong>)</td><td>pH 센서가 연결된 ADC 채널</td></tr><tr><td>ADC Channel: EC</td><td>Select(Options: [Channel 0 | <strong>Channel 1</strong> | Channel 2 | Channel 3] (Default in <strong>bold</strong>)</td><td>EC 센서가 연결된 ADC 채널</td></tr><tr><td colspan="3">Temperature Compensation</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td colspan="3">pH Calibration Data</td></tr><tr><td>Cal data: V1 (internal)</td><td>Decimal
- Default Value: 1.5</td><td>보정 데이터: 전압</td></tr><tr><td>Cal data: pH1 (internal)</td><td>Decimal
- Default Value: 7.0</td><td>보정 데이터: pH</td></tr><tr><td>Cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>보정 데이터: 온도</td></tr><tr><td>Cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.032</td><td>보정 데이터: 전압</td></tr><tr><td>Cal data: pH2 (internal)</td><td>Decimal
- Default Value: 4.0</td><td>보정 데이터: pH</td></tr><tr><td>Cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>보정 데이터: 온도</td></tr><tr><td colspan="3">EC Calibration Data</td></tr><tr><td>EC cal data: V1 (internal)</td><td>Decimal
- Default Value: 0.232</td><td>EC 보정 데이터: 전압</td></tr><tr><td>EC cal data: EC1 (internal)</td><td>Decimal
- Default Value: 1413.0</td><td>EC 보정 데이터: EC</td></tr><tr><td>EC cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC 보정 데이터: EC</td></tr><tr><td>EC cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.112</td><td>EC 보정 데이터: 전압</td></tr><tr><td>EC cal data: EC2 (internal)</td><td>Decimal
- Default Value: 12880.0</td><td>EC 보정 데이터: EC</td></tr><tr><td>EC cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC 보정 데이터: EC</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">pH Calibration Actions: Place your probe in a solution of known pH.
            Set the known pH value in the "Calibration buffer pH" field, and press "Calibrate pH, slot 1".
            Repeat with a second buffer, and press "Calibrate pH, slot 2".
            You don't need to change the values under "Custom Options".</td></tr><tr><td>Calibration buffer pH</td><td>Decimal
- Default Value: 7.0</td><td>보정 버퍼의 공칭 pH 값으로, 보통 병에 표기되어 있습니다.</td></tr><tr><td>Calibrate pH, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate pH, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear pH Calibration Slots</td><td>Button</td><td></td></tr><tr><td colspan="3">EC Calibration Actions: Place your probe in a solution of known EC.
            Set the known EC value in the "Calibration standard EC" field, and press "Calibrate EC, slot 1".
            Repeat with a second standard, and press "Calibrate EC, slot 2".
            You don't need to change the values under "Custom Options".</td></tr><tr><td>Calibration standard EC</td><td>Decimal
- Default Value: 1413.0</td><td>이것은 보정 표준액의 공칭 EC 값으로, 보통 병에 표기되어 있습니다.</td></tr><tr><td>Calibrate EC, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate EC, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear EC Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### Texas Instruments: ADS1115

- Manufacturer: Texas Instruments
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADS1x15
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ads1x15](https://pypi.org/project/adafruit-circuitpython-ads1x15)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>각 채널을 측정할 횟수입니다. 측정값들의 평균이 저장됩니다.</td></tr></tbody></table>

### Texas Instruments: ADS1256: Generic Analog pH/EC

- Manufacturer: Texas Instruments
- Measurements: Ion Concentration/Electrical Conductivity
- Interfaces: UART
- Libraries: wiringpi, aot-inc/PiPyADC-py3
- Dependencies: [wiringpi](https://pypi.org/project/wiringpi), [pipyadc_py3](https://github.com/aot-inc/PiPyADC-py3)

이 Input은 ADS1256 아날로그-디지털 변환기(ADC)를 사용해 아날로그 센서로부터 pH 및/또는 전기전도도(EC)를 측정합니다. pH 센서나 EC 센서만 연결하려면 Measurements Enabled에서 원하는 측정 항목을 선택해 각 측정을 켜거나 끌 수 있습니다. 각 센서가 ADC의 어느 채널에 연결되어 있는지 선택하세요. Input에는 초기 기본 보정값이 설정되어 있습니다. 또한 보정액으로 센서를 쉽게 보정할 수 있는 기능도 제공됩니다. Calibrate Slot 액션을 사용하면 이 값들이 계산되어 현재 설정값을 대체합니다. Clear Calibration 액션을 사용하면 데이터베이스 값을 삭제하고 기본값으로 되돌릴 수 있습니다. Input을 삭제하거나 해당 ADC/센서를 쓸 새 Input을 만들면, 새 보정 데이터를 저장하기 위해 다시 보정해야 합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>ADC Channel: pH</td><td>Select(Options: [Not Connected | <strong>Channel 0</strong> | Channel 1 | Channel 2 | Channel 3 | Channel 4 | Channel 5 | Channel 6 | Channel 7] (Default in <strong>bold</strong>)</td><td>pH 센서가 연결된 ADC 채널</td></tr><tr><td>ADC Channel: EC</td><td>Select(Options: [Not Connected | Channel 0 | <strong>Channel 1</strong> | Channel 2 | Channel 3 | Channel 4 | Channel 5 | Channel 6 | Channel 7] (Default in <strong>bold</strong>)</td><td>EC 센서가 연결된 ADC 채널</td></tr><tr><td colspan="3">Temperature Compensation</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>온도 보상에 사용할 Measurement 선택</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td colspan="3">pH Calibration Data</td></tr><tr><td>Cal data: V1 (internal)</td><td>Decimal
- Default Value: 1.5</td><td>보정 데이터: 전압</td></tr><tr><td>Cal data: pH1 (internal)</td><td>Decimal
- Default Value: 7.0</td><td>보정 데이터: pH</td></tr><tr><td>Cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>보정 데이터: 온도</td></tr><tr><td>Cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.032</td><td>보정 데이터: 전압</td></tr><tr><td>Cal data: pH2 (internal)</td><td>Decimal
- Default Value: 4.0</td><td>보정 데이터: pH</td></tr><tr><td>Cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>보정 데이터: 온도</td></tr><tr><td colspan="3">EC Calibration Data</td></tr><tr><td>EC cal data: V1 (internal)</td><td>Decimal
- Default Value: 0.232</td><td>EC 보정 데이터: 전압</td></tr><tr><td>EC cal data: EC1 (internal)</td><td>Decimal
- Default Value: 1413.0</td><td>EC 보정 데이터: EC</td></tr><tr><td>EC cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC 보정 데이터: EC</td></tr><tr><td>EC cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.112</td><td>EC 보정 데이터: 전압</td></tr><tr><td>EC cal data: EC2 (internal)</td><td>Decimal
- Default Value: 12880.0</td><td>EC 보정 데이터: EC</td></tr><tr><td>EC cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC 보정 데이터: EC</td></tr><tr><td>Calibration</td><td>선택</td><td>Input 활성화 시 수행할 보정 방식을 설정하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">pH Calibration Actions: Place your probe in a solution of known pH.
            Set the known pH value in the `Calibration buffer pH` field, and press `Calibrate pH, slot 1`.
            Repeat with a second buffer, and press `Calibrate pH, slot 2`.
            You don't need to change the values under `Custom Options`.</td></tr><tr><td>Calibration buffer pH</td><td>Decimal
- Default Value: 7.0</td><td>보정 버퍼의 공칭 pH 값으로, 보통 병에 표기되어 있습니다.</td></tr><tr><td>Calibrate pH, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate pH, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear pH Calibration Slots</td><td>Button</td><td></td></tr><tr><td colspan="3">EC Calibration Actions: Place your probe in a solution of known EC.
            Set the known EC value in the `Calibration standard EC` field, and press `Calibrate EC, slot 1`.
            Repeat with a second standard, and press `Calibrate EC, slot 2`.
            You don't need to change the values under `Custom Options`.</td></tr><tr><td>Calibration standard EC</td><td>Decimal
- Default Value: 1413.0</td><td>이것은 보정 표준액의 공칭 EC 값으로, 보통 병에 표기되어 있습니다.</td></tr><tr><td>Calibrate EC, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate EC, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear EC Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### Texas Instruments: ADS1256

- Manufacturer: Texas Instruments
- Measurements: Voltage (Waveshare, Analog-to-Digital Converter)
- Interfaces: UART
- Libraries: wiringpi, aot-inc/PiPyADC-py3
- Dependencies: [wiringpi](https://pypi.org/project/wiringpi), [pipyadc_py3](https://github.com/aot-inc/PiPyADC-py3)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Calibration</td><td>선택</td><td>Input 활성화 시 수행할 보정 방식을 설정하세요.</td></tr></tbody></table>

### Texas Instruments: ADS1x15

- Manufacturer: Texas Instruments
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_ADS1x15 [DEPRECATED]
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-ADS1x15](https://pypi.org/project/Adafruit-ADS1x15)

Adafruit_ADS1x15는 더 이상 사용되지 않습니다(deprecated). Circuit Python ADS1x15 Input 사용을 권장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>각 채널을 측정할 횟수입니다. 측정값들의 평균이 저장됩니다.</td></tr></tbody></table>

### Texas Instruments: HDC1000

- Manufacturer: Texas Instruments
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: fcntl/io
- Manufacturer URL: [Link](https://www.ti.com/product/HDC1000)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/hdc1000.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Texas Instruments: INA219x

- Manufacturer: Texas Instruments
- Measurements: Electrical Current (DC)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython
- Dependencies: [adafruit-circuitpython-ina219](https://pypi.org/project/adafruit-circuitpython-ina219), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus)
- Manufacturer URL: [Link](https://www.ti.com/product/INA219)
- Datasheet URL: [Link](https://www.ti.com/lit/gpn/ina219)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>각 채널을 측정할 횟수입니다. 측정값들의 평균이 저장됩니다.</td></tr><tr><td>Calibration Range</td><td>Select(Options: [<strong>32V @ 2A max (default)</strong> | 32V @ 1A max | 16V @ 400mA max | 16V @ 5A max] (Default in <strong>bold</strong>)</td><td>장치 보정 범위 설정</td></tr><tr><td>Bus Voltage Range</td><td>Select(Options: [(0x00) - 16V | <strong>(0x01) - 32V (default)</strong>] (Default in <strong>bold</strong>)</td><td>버스 전압 범위 설정</td></tr><tr><td>Bus ADC Resolution</td><td>Select(Options: [(0x00) - 9 Bit / 1 Sample | (0x01) - 10 Bit / 1 Sample | (0x02) - 11 Bit / 1 Sample | <strong>(0x03) - 12 Bit / 1 Sample (default)</strong> | (0x09) - 12 Bit / 2 Samples | (0x0A) - 12 Bit / 4 Samples | (0x0B) - 12 Bit / 8 Samples | (0x0C) - 12 Bit / 16 Samples | (0x0D) - 12 Bit / 32 Samples | (0x0E) - 12 Bit / 64 Samples | (0x0F) - 12 Bit / 128 Samples] (Default in <strong>bold</strong>)</td><td>Bus ADC 해상도 설정.</td></tr><tr><td>Shunt ADC Resolution</td><td>Select(Options: [(0x00) - 9 Bit / 1 Sample | (0x01) - 10 Bit / 1 Sample | (0x02) - 11 Bit / 1 Sample | <strong>(0x03) - 12 Bit / 1 Sample (default)</strong> | (0x09) - 12 Bit / 2 Samples | (0x0A) - 12 Bit / 4 Samples | (0x0B) - 12 Bit / 8 Samples | (0x0C) - 12 Bit / 16 Samples | (0x0D) - 12 Bit / 32 Samples | (0x0E) - 12 Bit / 64 Samples | (0x0F) - 12 Bit / 128 Samples] (Default in <strong>bold</strong>)</td><td>Shunt ADC 해상도 설정.</td></tr></tbody></table>

### Texas Instruments: TMP006

- Manufacturer: Texas Instruments
- Measurements: Temperature (Object/Die)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_TMP
- Dependencies: [Adafruit-TMP](https://pypi.org/project/Adafruit-TMP)
- Datasheet URL: [Link](http://www.adafruit.com/datasheets/tmp006.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1296)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### The Things Network: The Things Network: Data Storage (TTN v2)

- Manufacturer: The Things Network
- Measurements: Variable measurements
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

이 Input은 The Things Network의 Data Storage Integration으로부터 측정값을 수신해 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Application ID</td><td>텍스트</td><td>The Things Network 애플리케이션 ID</td></tr><tr><td>App API Key</td><td>텍스트</td><td>The Things Network 애플리케이션 API 키</td></tr><tr><td>Device ID</td><td>텍스트</td><td>The Things Network 디바이스 ID</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Variable Name</td><td>텍스트</td><td>TTN 변수 이름</td></tr></tbody></table>

### The Things Network: The Things Network: Data Storage (TTN v3, Payload Key)

- Manufacturer: The Things Network
- Measurements: Variable measurements
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

이 Input은 The Things Network의 Data Storage Integration으로부터 측정값을 수신해 저장합니다. 페이로드가 키/값 쌍으로 되어 있다면 Variable Name에 키 이름을 입력하세요. 해당 키의 값이 측정 데이터베이스에 저장됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Application ID</td><td>텍스트</td><td>The Things Network 애플리케이션 ID</td></tr><tr><td>App API Key</td><td>텍스트</td><td>The Things Network 애플리케이션 API 키</td></tr><tr><td>Device ID</td><td>텍스트</td><td>The Things Network 디바이스 ID</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Variable Name</td><td>텍스트</td><td>TTN 변수 이름</td></tr></tbody></table>

### The Things Network: The Things Network: Data Storage (TTN v3, Payload jmespath Expression)

- Manufacturer: The Things Network
- Measurements: Variable measurements
- Libraries: requests, jmespath
- Dependencies: [requests](https://pypi.org/project/requests), [jmespath](https://pypi.org/project/jmespath)

이 Input은 The Things Network의 Data Storage Integration으로부터 측정값을 수신해 저장합니다. 지정한 Payload jmespath Expression은 JMESPATH 표현식으로 사용되어 해당 채널에 저장할 값을 찾습니다. 각 채널의 Measurement Unit을 반드시 선택하고 저장하세요. 단위를 저장한 후에는 Convert Measurement 섹션에서 다른 단위로 변환할 수 있습니다. jmespath (https://jmespath.org) 표현식 예로는 <i>temperature</i>, <i>sensors[0].temperature</i>, <i>bathroom.temperature</i>가 있으며, 각각 sensors 첫 항목의 직접 키 또는 bathroom의 하위 키로서의 temperature를 가리킵니다. 특수 문자를 포함한 jmespath 요소와 키는 큰따옴표로 묶어야 합니다. 예: <i>"sensor-1".temperature</i>.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Application ID</td><td>텍스트</td><td>The Things Network 애플리케이션 ID</td></tr><tr><td>App API Key</td><td>텍스트</td><td>The Things Network 애플리케이션 API 키</td></tr><tr><td>Device ID</td><td>텍스트</td><td>The Things Network 디바이스 ID</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Payload jmespath Expression</td><td>텍스트</td><td>저장할 값을 반환하는 TTN jmespath 표현식</td></tr></tbody></table>

### Thunderforest: GL: Thunderforest

- Manufacturer: Thunderforest
- Measurements: Status
- Libraries: gis_thunderforest
- Manufacturer URL: [Link](https://www.thunderforest.com/)

OpenStreetMap 데이터를 활용하여 특정 목적에 맞춘 독창적인 테마 지도를 제공합니다. 자전거 도로(Cycle), 대중교통(Transport), 밤 지도, 거친 풍경 등 시각적으로 강렬한 고유 스타일을 경험할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Thunderforest API Key</td><td>텍스트</td><tr><td>지도 스타일</td></td></tbody></table>

### Vworld: KO: Vworld

- Manufacturer: Vworld
- Measurements: Status
- Libraries: gis_vworld
- Manufacturer URL: [Link](https://www.vworld.kr/)

대한민국 국토교통부의 공간정보 오픈플랫폼 브이월드 서비스입니다. 국내에서 가장 정밀한 국가 고해상도 항공 사진과 수치 지도, 지적도, 실시간 교통량 등을 제공하며 국내 업무 지원에 가장 특화된 국가 국가표준 지도입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>텍스트</td><tr><td>등록 도메인</td><td>텍스트</td><tr><td>Map Layer / Style</td></td><tr><td>범례 보기</td><td>Boolean</td></tbody></table>

### Winsen: MH-Z14A

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART
- Libraries: serial
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/co2-sensor/mh-z14a.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/mh-z14a-co2-manual-v1_4.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Automatic Self-calibration</td><td>Boolean
- Default Value: True</td><td>자동 자가 보정 사용</td></tr><tr><td>Measurement Range</td><td>Select(Options: [<strong>400 - 2000 ppmv</strong> | 400 - 5000 ppmv | 400 - 10000 ppmv] (Default in <strong>bold</strong>)</td><td>센서 측정 범위 설정</td></tr><tr><td colspan="3">The CO2 measurement can also be obtained using PWM via a GPIO pin. Enter the pin number below or leave blank to disable this option. This also makes it possible to obtain measurements even if the UART interface is not available (note that the sensor can't be configured / calibrated without a working UART interface).</td></tr><tr><td>GPIO Override</td><td>텍스트</td><td>UART 대신 이 GPIO 핀의 PWM으로 값을 읽습니다.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate Zero Point</td><td>Button</td><td></td></tr><tr><td>Span Point (ppmv)</td><td>Integer
- Default Value: 2000</td><td>스팬점 보정용 농도(ppmv)</td></tr><tr><td>Calibrate Span Point</td><td>Button</td><td></td></tr></tbody></table>

### Winsen: MH-Z16

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART, I<sup>2</sup>C
- Libraries: smbus2/serial
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/co2-sensor/mh-z16.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/MH-Z16.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Winsen: MH-Z19

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART
- Libraries: serial
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/PDF/Infrared%20Gas%20Sensor/NDIR%20CO2%20SENSOR/MH-Z19%20CO2%20Ver1.0.pdf)

이것은 자동 기준선 보정(ABC) 기능이 없는 버전의 센서입니다. ABC를 사용하려면 센서의 B 버전을 참고하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Measurement Range</td><td>Select(Options: [0 - 1000 ppmv | 0 - 2000 ppmv | 0 - 3000 ppmv | <strong>0 - 5000 ppmv</strong>] (Default in <strong>bold</strong>)</td><td>센서 측정 범위 설정</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate Zero Point</td><td>Button</td><td></td></tr><tr><td>Span Point (ppmv)</td><td>Integer
- Default Value: 2000</td><td>스팬점 보정용 농도(ppmv)</td></tr><tr><td>Calibrate Span Point</td><td>Button</td><td></td></tr></tbody></table>

### Winsen: MH-Z19B

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART
- Libraries: serial
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/co2-sensor/mh-z19b.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/MH-Z19B.pdf)

이것은 자동 기준선 보정(ABC) 기능이 포함된 B 버전의 센서입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Automatic Baseline Correction</td><td>Boolean</td><td>자동 기준선 보정(ABC) 활성화</td></tr><tr><td>Measurement Range</td><td>Select(Options: [0 - 1000 ppmv | 0 - 2000 ppmv | 0 - 3000 ppmv | <strong>0 - 5000 ppmv</strong> | 0 - 10000 ppmv] (Default in <strong>bold</strong>)</td><td>센서 측정 범위 설정</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate Zero Point</td><td>Button</td><td></td></tr><tr><td>Span Point (ppmv)</td><td>Integer
- Default Value: 2000</td><td>스팬점 보정용 농도(ppmv)</td></tr><tr><td>Calibrate Span Point</td><td>Button</td><td></td></tr></tbody></table>

### Winsen: ZH03B

- Manufacturer: Winsen
- Measurements: Particulates
- Interfaces: UART
- Libraries: serial
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/dust-sensor/zh3b.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/ZH03B.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Fan Off After Measure</td><td>Boolean</td><td>측정 중에만 팬 켜기</td></tr><tr><td>Fan On Duration (Seconds)</td><td>Decimal
- Default Value: 50.0</td><td>측정값을 얻기 전에 팬을 켜 둘 시간</td></tr><tr><td>Number of Measurements</td><td>Integer
- Default Value: 3</td><td>획득할 측정 횟수입니다. 1보다 크고 1001 미만인 횟수를 획득하면 측정값들의 평균이 저장됩니다.</td></tr></tbody></table>

### Xiaomi: Miflora

- Manufacturer: Xiaomi
- Measurements: EC/Light/Moisture/Temperature
- Interfaces: BT
- Libraries: miflora
- Dependencies: [libglib2.0-dev](https://packages.debian.org/search?keywords=libglib2.0-dev), [miflora](https://pypi.org/project/miflora), [bluepy](https://pypi.org/project/bluepy)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>텍스트</td><td>블루투스 장치의 Hci 위치.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>텍스트</td><td>Bluetooth 장치의 어댑터.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

### Xiaomi: Mijia LYWSD03MMC (ATC and non-ATC modes)

- Manufacturer: Xiaomi
- Measurements: Battery/Humidity/Temperature
- Interfaces: BT
- Libraries: bluepy/bluez
- Dependencies: [libglib2.0](https://packages.debian.org/search?keywords=libglib2.0), [bluez](https://packages.debian.org/search?keywords=bluez), [bluetooth](https://packages.debian.org/search?keywords=bluetooth), [libbluetooth-dev](https://packages.debian.org/search?keywords=libbluetooth-dev), [bluepy](https://pypi.org/project/bluepy), [bluetooth](https://github.com/pybluez/pybluez)

More information about ATC mode can be found at https://github.com/JsBergbau/MiTemperature2
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>텍스트</td><td>블루투스 장치의 Hci 위치.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>텍스트</td><td>Bluetooth 장치의 어댑터.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr><tr><td>Enable ATC Mode</td><td>Boolean</td><td>센서 ATC 모드 활성화</td></tr></tbody></table>

### ams: AS7341

- Manufacturer: ams
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit-CircuitPython-AS7341
- Dependencies: [adafruit-extended-bus](https://pypi.org/project/adafruit-extended-bus), [adafruit-circuitpython-as7341](https://pypi.org/project/adafruit-circuitpython-as7341)
- Manufacturer URL: [Link](https://ams.com/as7341)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/AS7341_DS000504_3-00.pdf/5eca1f59-46e2-6fc5-daf5-d71ad90c9b2b)
- Product URLs: [Link 1](https://www.adafruit.com/product/4698), [Link 2](https://shop.pimoroni.com/products/adafruit-as7341-10-channel-light-color-sensor-breakout-stemma-qt-qwiic), [Link 3](https://www.berrybase.de/adafruit-as7341-10-kanal-licht-und-farb-sensor-breakout)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Pre Output</td><td>선택</td><td>매 측정 전에 선택한 output을 켭니다.</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>Pre Output을 선택한 경우, 매 측정값 획득 전에 Pre Output을 켤 시간을 설정하세요.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>측정 완료 전이 아니라 후에 output을 끄려면 체크하세요.</td></tr></tbody></table>

