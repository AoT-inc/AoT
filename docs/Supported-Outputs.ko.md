## Built-In Outputs (System)

### On/Off: MQTT Publish

- Manufacturer: AoT
- Interfaces: IP
- Output Types: On/Off
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

MQTT 서버로 "on" 또는 "off"(또는 원하는 문자열)를 발행합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Hostname</td><td>Text
- Default Value: localhost</td><td>MQTT 서버 호스트명</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>MQTT 서버 포트</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>발행할 토픽</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>클라이언트의 keepalive 타임아웃 값. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_T64MQp5F</td><td>MQTT 서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>On Payload</td><td>Text
- Default Value: on</td><td>켜질 때 보낼 payload</td></tr><tr><td>Off Payload</td><td>Text
- Default Value: off</td><td>꺼질 때 보낼 payload</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 연결용 비밀번호. 비활성화하려면 비워 두세요.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr></tbody></table>

### PWM: MQTT Publish

- Manufacturer: AoT
- Output Types: PWM
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

PWM 값을 MQTT 서버에 게시.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Hostname</td><td>Text
- Default Value: localhost</td><td>MQTT 서버 호스트명</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>MQTT 서버 포트</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>발행할 토픽</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>클라이언트의 keepalive 타임아웃 값. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_62CDeFuQ</td><td>MQTT 서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 연결용 비밀번호.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr><tr><td>Round Integer</td><td>Select(Options: [<strong>No Rounding</strong> | Round Nearest Whole | Round Up | Round Down] (Default in <strong>bold</strong>)</td><td>페이로드 값을 정수로 반올림.</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Startup Value</td><td>Decimal</td><td>AoT 시작 시 값</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Shutdown Value</td><td>Decimal</td><td>AoT 종료 시 값</td></tr><tr><td>Invert Signal</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>Invert Stored Signal</td><td>Boolean</td><td>측정 데이터베이스에 저장되는 값을 반전합니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>설정할 듀티 사이클</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### Value: MQTT Publish

- Manufacturer: AoT
- Output Types: Value
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

MQTT 서버에 값 게시.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Hostname</td><td>Text
- Default Value: localhost</td><td>MQTT 서버 호스트명</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>MQTT 서버 포트</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>발행할 토픽</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>클라이언트의 keepalive 타임아웃 값. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_W6Pb8H1q</td><td>MQTT 서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Off Value</td><td>Integer</td><td>Off 명령 시 전송할 값</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 연결용 비밀번호.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr></tbody></table>

## Built-In Outputs (Devices)

### Digital Potentiometer: DS3502

- Manufacturer: Maxim Integrated
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit_Extended_Bus](https://pypi.org/project/Adafruit_Extended_Bus), [adafruit-circuitpython-ds3502](https://pypi.org/project/adafruit-circuitpython-ds3502)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/analog/data-converters/digital-potentiometers/DS3502.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS3502.pdf)
- Product URL: [Link](https://www.adafruit.com/product/4286)

DS3502는 7비트 정밀도로 0 - 10k Ohm의 저항을 생성할 수 있으며, 이는 128단계에 해당합니다. Ohm 단위 값을 이 출력 컨트롤러에 전달하면 단계 값이 계산되어 기기로 전달됩니다. 가장 가까운 단계로 올림할지 내림할지 선택하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Round Step</td><td>Select(Options: [<strong>Up</strong> | Down] (Default in <strong>bold</strong>)</td><td>가장 가까운 step 값으로 반올림</td></tr></tbody></table>

### Digital-to-Analog Converter: MCP4728

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp4728](https://pypi.org/project/adafruit-circuitpython-mcp4728)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en541737)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/DeviceDoc/22187E.pdf)
- Product URL: [Link](https://www.adafruit.com/product/4470)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 4.096</td><td>VREF 전압 설정</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>VREF</td><td>Select(Options: [<strong>Internal</strong> | VDD] (Default in <strong>bold</strong>)</td><td>채널 VREF 선택</td></tr><tr><td>Gain</td><td>Select(Options: [<strong>1X</strong> | 2X] (Default in <strong>bold</strong>)</td><td>채널 Gain 선택</td></tr><tr><td>Start State</td><td>Select(Options: [<strong>Previously-Saved State</strong> | Specified Value] (Default in <strong>bold</strong>)</td><td>채널 시작 상태 선택</td></tr><tr><td>Start Value (volts)</td><td>Decimal</td><td>Specified Value 선택 시, 시작 상태 값을 설정하세요.</td></tr><tr><td>Shutdown State</td><td>Select(Options: [<strong>Previously-Saved Value</strong> | Specified Value] (Default in <strong>bold</strong>)</td><td>채널 종료 상태 선택</td></tr><tr><td>Shutdown Value (volts)</td><td>Decimal</td><td>Specified Value 선택 시, 종료 상태 값을 설정하세요.</td></tr></tbody></table>

### Motor: Stepper Motor, Bipolar (Generic) (Pi <= 4)

- Interfaces: GPIO
- Output Types: Value
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URLs: [Link 1](https://www.ti.com/product/DRV8825), [Link 2](https://www.allegromicro.com/en/products/motor-drivers/brush-dc-motor-drivers/a4988)
- Datasheet URLs: [Link 1](https://www.ti.com/lit/ds/symlink/drv8825.pdf), [Link 2](https://www.allegromicro.com/-/media/files/datasheets/a4988-datasheet.ashx)
- Product URLs: [Link 1](https://www.pololu.com/product/2133), [Link 2](https://www.pololu.com/product/1182)

이것은 DRV8825, A4988 등 바이폴라 스테퍼 모터 드라이버를 위한 범용 모듈입니다. 출력에 전달되는 값은 스텝 수입니다. 양수 값은 시계 방향, 음수 값은 반시계 방향으로 회전합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td colspan="3">If the Direction or Enable pins are not used, make sure you pull the appropriate pins on your driver high or low to set the proper direction and enable the stepper motor to be energized. Note: For Enable Mode, always having the motor energized will use more energy and produce more heat.</td></tr><tr><td>Step Pin</td><td>Integer</td><td>컨트롤러의 Step 핀 (BCM 번호)</td></tr><tr><td>Full Step Delay</td><td>Decimal
- Default Value: 0.005</td><td>컨트롤러의 Full Step 지연</td></tr><tr><td>Direction Pin</td><td>Integer</td><td>컨트롤러의 Direction 핀(BCM 번호). 비활성화하려면 None으로 설정하세요.</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>컨트롤러의 Enable 핀(BCM 번호). 비활성화하려면 None으로 설정하세요.</td></tr><tr><td>Enable Mode</td><td>Select(Options: [<strong>Only When Turning</strong> | Always] (Default in <strong>bold</strong>)</td><td>모터에 전원을 공급하기 위해 enable 핀을 high로 올릴 시점을 선택하세요.</td></tr><tr><td>Enable at Shutdown</td><td>Select(Options: [Enable | <strong>Disable</strong>] (Default in <strong>bold</strong>)</td><td>AoT가 종료될 때 enable 핀을 high(Enable)로 풀업할지 low(Disable)로 풀다운할지 선택하세요.</td></tr><tr><td colspan="3">If using a Step Resolution other than Full, and all three Mode Pins are set, they will be set high (1) or how (0) according to the values in parentheses to the right of the selected Step Resolution, e.g. (Mode Pin 1, Mode Pin 2, Mode Pin 3).</td></tr><tr><td>Step Resolution</td><td>Select(Options: [<strong>Full (modes 0, 0, 0)</strong> | Half (modes 1, 0, 0) | 1/4 (modes 0, 1, 0) | 1/8 (modes 1, 1, 0) | 1/16 (modes 0, 0, 1) | 1/32 (modes 1, 0, 1)] (Default in <strong>bold</strong>)</td><td>컨트롤러의 Step 해상도</td></tr><tr><td>Mode Pin 1</td><td>Integer</td><td>컨트롤러의 Mode Pin 1(BCM 번호). 비활성화하려면 None으로 설정하세요.</td></tr><tr><td>Mode Pin 2</td><td>Integer</td><td>컨트롤러의 Mode Pin 2(BCM 번호). 비활성화하려면 None으로 설정하세요.</td></tr><tr><td>Mode Pin 3</td><td>Integer</td><td>컨트롤러의 Mode Pin 3(BCM 번호). 비활성화하려면 None으로 설정하세요.</td></tr></tbody></table>

### Motor: ULN2003 Stepper Motor, Unipolar (Pi <= 4)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Value
- Libraries: RPi.GPIO, rpimotorlib
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO), [rpimotorlib](https://pypi.org/project/rpimotorlib)
- Manufacturer URL: [Link](https://www.ti.com/product/ULN2003A)
- Datasheet URLs: [Link 1](https://www.electronicoscaldas.com/datasheet/ULN2003A-PCB.pdf), [Link 2](https://www.ti.com/lit/ds/symlink/uln2003a.pdf?ts=1617254568263&ref_url=https%253A%252F%252Fwww.ti.com%252Fproduct%252FULN2003A)

ULN2003 드라이버용 모듈.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td colspan="3">Notes about connecting the ULN2003...</td></tr><tr><td>Pin IN1</td><td>Integer
- Default Value: 18</td><td>ULN2003의 IN1에 연결된 핀(BCM 번호)</td></tr><tr><td>Pin IN2</td><td>Integer
- Default Value: 23</td><td>ULN2003의 IN2에 연결된 핀(BCM 번호)</td></tr><tr><td>Pin IN3</td><td>Integer
- Default Value: 24</td><td>ULN2003의 IN3에 연결된 핀(BCM 번호)</td></tr><tr><td>Pin IN4</td><td>Integer
- Default Value: 25</td><td>ULN2003의 IN4에 연결된 핀(BCM 번호)</td></tr><tr><td>Step Delay</td><td>Decimal
- Default Value: 0.001</td><td>컨트롤러의 Step 지연</td></tr><tr><td colspan="3">Notes about step resolution...</td></tr><tr><td>Step Resolution</td><td>Select(Options: [<strong>Full</strong> | Half | Wave] (Default in <strong>bold</strong>)</td><td>컨트롤러의 Step 해상도</td></tr></tbody></table>

### On/Off (Virtual Multi-Channel)

- Output Types: On/Off
- Libraries: Internal

테스트용 가상 출력 기기입니다. 상태는 메모리에 저장되며 하드웨어에는 영향을 주지 않습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>가상 장치의 소비 전류</td></tr></tbody></table>

### On/Off (Virtual Single-Channel)

- Output Types: On/Off
- Libraries: Internal

테스트용 단일 채널 가상 출력 기기입니다. 상태는 메모리에 저장되며 하드웨어에는 영향을 주지 않습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>가상 장치의 소비 전류</td></tr></tbody></table>

### On/Off: 52pi EP-0099 4channel Relay (4-Channel board)

- Manufacturer: 52Pi
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)

4채널 멀티채널 릴레이 보드 제어.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>aot 시작 시 릴레이 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>aot 종료 시 릴레이 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: ChirpStack gRPC

- Interfaces: API
- Output Types: On/Off
- Libraries: requests, grpcio (optional)
- Dependencies: 

ChirpStack REST/gRPC API를 이용해 온/오프 다운링크 명령을 전송합니다. 우선 gRPC로 시도하며, grpcio/chirpstack-api가 설치되지 않았거나 접근이 실패하면 REST(/api/devices/<devEui>/queue)로 자동 전환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ChirpStack gRPC 서버</td><td>Text
- Default Value: 127.0.0.1:8080</td><td>호스트:포트 형식 (예: 127.0.0.1:8080) 또는 http(s)://호스트:포트</td></tr><tr><td>API Key</td><td>텍스트</td><td>JWT 토큰 값을 입력하세요 (Bearer 제외)</td></tr><tr><td>DevEUI</td><td>텍스트</td><td>16자리 16진수 DevEUI (구분자 허용)</td></tr><tr><td>FPort</td><td>Integer
- Default Value: 15</td><td>명령을 수신할 LoRaWAN FPort</td></tr><tr><td>Confirmed</td><td>Boolean</td><td>확인형(Confirmed)으로 명령 전송</td></tr><tr><td>Payload Format</td><td>Select(Options: [<strong>Hex 바이트</strong> | JSON 객체(UTF-8 인코딩)] (Default in <strong>bold</strong>)</td><td>페이로드 인코딩 형식을 선택하세요</td></tr><tr><td>On Payload</td><td>Text
- Default Value: 000000</td><td>예: 010110 (Hex) 또는 JSON 문자열</td></tr><tr><td>off Payload</td><td>Text
- Default Value: 000000</td><td>예: 010210 (Hex) 또는 JSON 문자열</td></tr><tr><td>확인 유예(초)</td><td>Text
- Default Value: 90</td><td>업링크 지연 허용시간</td></tr><tr><td>확정 타임아웃(초)</td><td>Text
- Default Value: 600</td><td>이 시간이 지나도 미확인 시 경고/재조치</td></tr><tr><td>하드 타임아웃 시 OFF 재전송</td><td>Boolean</td><td>duration 종료 또는 타임아웃 시 OFF를 다시 보냄</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>시작 시 상태</td><td>선택</td><td>AoT가 시작될 때 적용할 상태</td></tr><tr><td>종료 시 상태</td><td>선택</td><td>AoT가 종료될 때 적용할 상태</td></tr><tr><td>Force Command</td><td>Boolean</td><td>현재 상태와 무관하게 명령을 항상 전송</td></tr><tr><td>시작 시 트리거 실행</td><td>Boolean</td><td>시작 시 출력이 전환되면 트리거 기능 실행</td></tr></tbody></table>

### On/Off: Ecowitt Local HTTP

- Interfaces: IP
- Output Types: On/Off
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

Ecowitt 허브 IP, 서브디바이스 ID, 모델(WFC01/02=1, WFC02 신펌=3, AC1100=2)을 입력하면 로컬 HTTP API로 On/Off 제어합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Ecowitt Device IP</td><td>텍스트</td><td>Ecowitt 허브의 로컬 IP 주소(예: 192.168.1.100)</td></tr><tr><td>Ecowitt Sub-device ID</td><td>텍스트</td><td>WFC01/WFC02/AC1100의 ID (예: 11044)</td></tr><tr><td>Ecowitt Device Model</td><td>Select(Options: [WFC01 | <strong>WFC02</strong> | AC1100] (Default in <strong>bold</strong>)</td><td>1=WFC01/대부분 WFC02, 3=일부 WFC02(신펌), 2=AC1100</td></tr><tr><td>Valve Open %</td><td>Integer
- Default Value: 100</td><td>켤 때 밸브를 이 비율(0-100%)로 엽니다.</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 60</td><td>출력 상태를 조회하는 주기</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr></tbody></table>

### On/Off: Grove Multichannel Relay (4- or 8-Channel board)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.seeedstudio.com/Grove-4-Channel-SPDT-Relay-p-3119.html)
- Datasheet URL: [Link](http://wiki.seeedstudio.com/Grove-4-Channel_SPDT_Relay/)
- Product URL: [Link](https://www.seeedstudio.com/Grove-4-Channel-SPDT-Relay-p-3119.html)

4채널 또는 8채널 Grove 멀티채널 릴레이 보드를 제어합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 릴레이 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 릴레이 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Kasa HS300 6-Outlet WiFi Power Strip (old library, deprecated)

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-wi-fi-power-strip-hs300)

이 출력은 Kasa HS300 스마트 WiFi 전원 스트립의 콘센트 6개를 제어합니다. 이 모듈은 오래된 python 라이브러리를 사용하며 더 이상 사용되지 않습니다(deprecated). 사용하지 마세요. 이 폐기된 Output을 삭제하지 않으면 현재의 Kasa 모듈이 정상 동작하지 않게 됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Host</td><td>Text
- Default Value: 192.168.0.50</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 60</td><td>연결 및 output 상태를 확인하는 주기</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Kasa HS300 6-Outlet WiFi Power Strip

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-wi-fi-power-strip-hs300)

이 출력은 Kasa HS300 스마트 WiFi 전원 스트립의 콘센트 6개를 제어합니다. 최신 python-kasa 라이브러리를 사용하는 변형 버전입니다. 참고: daemon 로그에 서버 시작 관련 오류가 보이면 Asyncio RPC Port를 다른 포트로 변경해 보세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Host</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>연결 및 output 상태를 확인하는 주기. 0이면 비활성화됩니다.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18718</td><td>asyncio RPC 서버를 시작할 포트. 다른 Kasa Output과 겹치지 않아야 합니다.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Kasa KP303 3-Outlet WiFi Power Strip (old library, deprecated)

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa)
- Manufacturer URL: [Link](https://www.tp-link.com/au/home-networking/smart-plug/kp303/)

이 출력은 Kasa KP303 스마트 WiFi 전원 스트립의 콘센트 3개를 제어합니다. 이 모듈은 오래된 python 라이브러리를 사용하며 더 이상 사용되지 않습니다(deprecated). 사용하지 마세요. 이 폐기된 Output을 삭제하지 않으면 현재의 Kasa 모듈이 정상 동작하지 않게 됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Host</td><td>Text
- Default Value: 192.168.0.50</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 60</td><td>연결 및 output 상태를 확인하는 주기</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Kasa KP303 3-Outlet WiFi Power Strip

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.tp-link.com/au/home-networking/smart-plug/kp303/)

이 출력은 Kasa KP303 스마트 WiFi 전원 스트립의 콘센트 3개를 제어합니다. 최신 python-kasa 라이브러리를 사용하는 변형 버전입니다. 참고: daemon 로그에 서버 시작 관련 오류가 보이면 Asyncio RPC Port를 다른 포트로 변경해 보세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Host</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>연결 및 output 상태를 확인하는 주기. 0이면 비활성화됩니다.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18221</td><td>asyncio RPC 서버를 시작할 포트. 다른 Kasa Output과 겹치지 않아야 합니다.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Kasa WiFi Power Plug

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-plug-slim-energy-monitoring-kp115)

이 출력은 KP105, KP115, KP125, KP401, HS100, HS103, HS105, HS107, HS110을 포함한 Kasa WiFi 전원 플러그를 제어합니다. 참고: daemon 로그에 서버 시작 관련 오류가 보이면 Asyncio RPC Port를 다른 포트로 변경해 보세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Host</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>연결 및 output 상태를 확인하는 주기. 0이면 비활성화됩니다.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18095</td><td>asyncio RPC 서버를 시작할 포트. 다른 Kasa Output과 겹치지 않아야 합니다.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Kasa WiFi RGB Light Bulb

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-lighting/kasa-smart-light-bulb-multicolor-kl125)

이 출력은 KL125, KL130, KL135를 포함한 Kasa WiFi 전구를 제어합니다. 참고: daemon 로그에 서버 시작 관련 오류가 보이면 Asyncio RPC Port를 다른 포트로 변경해 보세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Host</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>연결 및 output 상태를 확인하는 주기. 0이면 비활성화됩니다.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18603</td><td>asyncio RPC 서버를 시작할 포트. 다른 Kasa Output과 겹치지 않아야 합니다.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Transition (Milliseconds)</td><td>Integer
- Default Value: 0</td><td>HSV 전환 주기</td></tr><tr><td>Brightness (Percent)</td><td>Integer</td><td>설정할 밝기 (%, 0 - 100)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (Milliseconds)</td><td>Integer
- Default Value: 0</td><td>HSV 전환 주기</td></tr><tr><td>Hue (Degree)</td><td>Integer</td><td>설정할 색상(hue), 각도 (0 - 360)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (Milliseconds)</td><td>Integer
- Default Value: 0</td><td>HSV 전환 주기</td></tr><tr><td>Saturation (Percent)</td><td>Integer</td><td>설정할 채도 (%, 0 - 100)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (Milliseconds)</td><td>Integer
- Default Value: 0</td><td>HSV 전환 주기</td></tr><tr><td>Color Temperature (Kelvin)</td><td>Integer</td><td>설정할 색온도 (Kelvin)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (Milliseconds)</td><td>Integer
- Default Value: 0</td><td>HSV 전환 주기</td></tr><tr><td>HSV</td><td>Text
- Default Value: 220, 20, 45</td><td>설정할 색상, 채도, 밝기(예: "200, 20, 50")</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (Milliseconds)</td><td>Integer
- Default Value: 1000</td><td>전환 주기</td></tr><tr><td>On</td><td>Button</td><td></td></tr><tr><td>Transition (Milliseconds)</td><td>Integer
- Default Value: 1000</td><td>전환 주기</td></tr><tr><td>Off</td><td>Button</td><td></td></tr></tbody></table>

### On/Off: MCP23017 16-Channel I/O Expander

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp230xx](https://pypi.org/project/adafruit-circuitpython-mcp230xx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/MCP23017)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/devicedoc/20001952c.pdf)
- Product URL: [Link](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG)

MCP23017의 16개 채널 제어.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 GPIO 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 GPIO 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Neopixel (WS2812) RGB Strip with Raspberry Pi

- Manufacturer: Worldsemi
- Interfaces: GPIO
- Output Types: On/Off
- Dependencies: Output Variant 1: [adafruit-circuitpython-neopixel](https://pypi.org/project/adafruit-circuitpython-neopixel); Output Variant 2: [adafruit-circuitpython-neopixel-spi](https://pypi.org/project/adafruit-circuitpython-neopixel-spi)

네오픽셀 LED 스트립의 LED를 제어합니다. 주의하여 사용하세요: 이 라이브러리는 Hardware-PWM0 버스를 사용합니다. GPIO 핀 12 또는 18만 동작합니다. 이 중 한 핀을 NeoPixel 스트립에 사용하면 다른 핀을 또 다른 출력의 Hardware-PWM 제어에 사용할 수 없으며, 그렇지 않으면 충돌이 발생해 AoT Daemon이 크래시되고 Pi가 응답하지 않을 수 있습니다. 서보, 팬, 조광 가능한 재배등 같은 다른 PWM 출력을 제어하려면 Output PWM: Raspberry Pi GPIO를 설정하고 "Library" 필드를 "Any Pin, <=40kHz"로 지정해 Software-PWM을 사용해야 합니다. "Hardware Pin, <=30MHz" 옵션을 선택하면 충돌이 발생합니다. 이 출력은 개별 LED의 색상과 밝기를 제어하는 Action과 함께 사용하는 것이 가장 좋습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Data Pin</td><td>Integer
- Default Value: 18</td><td>장치 데이터 선에 연결된 GPIO 핀을 입력하세요(BCM 번호).</td></tr><tr><td>Number of LEDs</td><td>Integer
- Default Value: 1</td><td>스트립의 LED 개수?</td></tr><tr><td>On Mode</td><td>Select(Options: [<strong>Single Color</strong> | Rainbow] (Default in <strong>bold</strong>)</td><td>켜질 때 색상 모드</td></tr><tr><td>Single Color</td><td>Text
- Default Value: 30, 30, 30</td><td>Single Color Mode에서 켤 때의 색상으로, RGB 형식(red, green, blue)이며 각각 0 - 255입니다.</td></tr><tr><td>Rainbow Speed (Seconds)</td><td>Decimal
- Default Value: 0.01</td><td>Rainbow 모드에서 색상 변경 속도</td></tr><tr><td>Rainbow Brightness</td><td>Integer
- Default Value: 20</td><td>Rainbow 모드에서 LED의 최대 밝기(1 - 255)</td></tr><tr><td>Rainbow Mode</td><td>Select(Options: [All LEDs change at once | <strong>One LED Changes at a time</strong>] (Default in <strong>bold</strong>)</td><td>무지개 표시 방식</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>LED Position</td><td>Integer</td><td>변경할 스트립의 LED 선택</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>색상 (예: 10, 0, 0)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr></tbody></table>

### On/Off: PCF8574 8-Channel I/O Expander

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8574)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8574.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

PCF8574의 8개 채널 제어.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 GPIO 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 GPIO 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: PCF8575 16-Channel I/O Expander

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8575)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8575.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

PCF8575의 16개 채널 제어.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 GPIO 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 GPIO 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Python Code

- Interfaces: Python
- Output Types: On/Off
- Dependencies: [pylint](https://pypi.org/project/pylint)

이 output이 켜지거나 꺼질 때 Python 3 코드가 실행됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>저장 시 pylint로 Python 코드 분석</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>On Command</td></td><td>Python code to execute when the output is instructed to turn on</td></tr><tr><td>Off Command</td></td><td>Python code to execute when the output is instructed to turn off</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Raspberry Pi GPIO (Pi 5)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: pinctrl

On State 옵션에 따라, 켜지거나 꺼질 때 지정한 GPIO 핀이 HIGH(3.3V) 또는 LOW(0V)로 설정됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

On State 옵션에 따라, 켜지거나 꺼질 때 지정한 GPIO 핀이 HIGH(3.3V) 또는 LOW(0V)로 설정됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Sequent Microsystems 8-Relay HAT for Raspberry Pi

- Manufacturer: Sequent Microsystems
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://sequentmicrosystems.com)
- Datasheet URL: [Link](https://cdn.shopify.com/s/files/1/0534/4392/0067/files/8-RELAYS-UsersGuide.pdf?v=1642820552)
- Product URL: [Link](https://sequentmicrosystems.com/products/8-relays-stackable-card-for-raspberry-pi)

Sequent Microsystems가 만든 8-relay HAT의 릴레이 8개를 제어합니다. 이 보드를 최대 8개까지 동시에 사용해 64개의 릴레이를 제어할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Board Stack Number</td><td>선택</td><td>여러 보드를 사용할 때 보드 스택 번호를 선택하세요.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 GPIO 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 GPIO 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Shell Script

- Output Types: On/Off
- Libraries: subprocess.Popen

이 출력이 켜지거나 꺼질 때 지정한 사용자로 Linux 셸에서 명령이 실행됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>On Command</td><td>Text
- Default Value: /home/pi/script_on_off.sh on</td><td>output을 켜도록 지시할 때 실행할 명령</td></tr><tr><td>Off Command</td><td>Text
- Default Value: /home/pi/script_on_off.sh off</td><td>output을 끄도록 지시할 때 실행할 명령</td></tr><tr><td>User</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Sparkfun Relay Board (4 Relays)

- Manufacturer: Sparkfun
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: sparkfun-qwiic-relay
- Dependencies: [sparkfun-qwiic-relay](https://pypi.org/project/sparkfun-qwiic-relay)
- Manufacturer URL: [Link](https://www.sparkfun.com)
- Product URLs: [Link 1](https://www.sparkfun.com/products/16833), [Link 2](https://www.sparkfun.com/products/16566)

릴레이 모듈의 릴레이 4개 제어.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 GPIO 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 GPIO 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: Wireless 315/433 MHz (Pi <= 4)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: rpi-rf
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO), [rpi_rf](https://pypi.org/project/rpi_rf)

이 출력은 315 또는 433 MHz 송신기를 사용해 무선 전원 콘센트를 켜거나 끕니다. 리모컨에서 생성되는 코드를 알아내려면 수신기를 연결하고 /opt/AoT/aot/devices/wireless_rpi_rf.py를 실행하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>On Command</td><td>Text
- Default Value: 22559</td><td>output을 켜도록 지시할 때 실행할 명령</td></tr><tr><td>Off Command</td><td>Text
- Default Value: 22558</td><td>output을 끄도록 지시할 때 실행할 명령</td></tr><tr><td>Protocol</td><td>Select(Options: [<strong>1</strong> | 2 | 3 | 4 | 5] (Default in <strong>bold</strong>)</td><td></td></tr><tr><td>Pulse Length</td><td>Integer
- Default Value: 189</td><td></td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Force Command</td><td>Boolean</td><td>현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### On/Off: XL9535 16-Channel I/O Expander

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link]()
- Datasheet URL: [Link]()
- Product URL: [Link]()

XL9535의 16개 채널 제어.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 GPIO 상태 설정</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 GPIO 상태 설정</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### PWM: PCA9685 16-Channel LED Controller

- Manufacturer: NXP Semiconductors
- Interfaces: I<sup>2</sup>C
- Output Types: PWM
- Libraries: adafruit-pca9685
- Dependencies: [adafruit-pca9685](https://pypi.org/project/adafruit-pca9685)
- Manufacturer URL: [Link](https://www.nxp.com/products/power-management/lighting-driver-and-controller-ics/ic-led-controllers/16-channel-12-bit-pwm-fm-plus-ic-bus-led-controller:PCA9685)
- Datasheet URL: [Link](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf)
- Product URL: [Link](https://www.adafruit.com/product/815)

PCA9685는 40~1600 Hz 주파수로 16개 채널에 PWM 신호를 출력할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Frequency (Hertz)</td><td>Integer
- Default Value: 1600</td><td>PWM 신호 출력 주파수 (40 - 1600 Hz)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Startup Value</td><td>Decimal</td><td>AoT 시작 시 값</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Shutdown Value</td><td>Decimal</td><td>AoT 종료 시 값</td></tr><tr><td>Invert Signal</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>Invert Stored Signal</td><td>Boolean</td><td>측정 데이터베이스에 저장되는 값을 반전합니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### PWM: Python 3 Code

- Interfaces: Python
- Output Types: PWM
- Dependencies: [pylint](https://pypi.org/project/pylint)

이 출력이 켜지거나 꺼질 때 Python 3 코드가 실행됩니다. "duty_cycle" 객체는 설정된 듀티 사이클을 나타내는 float 값입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>저장 시 pylint로 Python 코드 분석</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Python 3 Code</td></td><td>Python code to execute to set the PWM duty cycle (%)</td></tr><tr><td>User</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Startup Value</td><td>Decimal</td><td>AoT 시작 시 값</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Shutdown Value</td><td>Decimal</td><td>AoT 종료 시 값</td></tr><tr><td>Invert Signal</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>Invert Stored Signal</td><td>Boolean</td><td>측정 데이터베이스에 저장되는 값을 반전합니다.</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>설정할 듀티 사이클</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: PWM
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

RPi.GPIO 라이브러리를 이용한 소프트웨어 PWM 구현입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Startup Value</td><td>Decimal</td><td>AoT 시작 시 값</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Shutdown Value</td><td>Decimal</td><td>AoT 종료 시 값</td></tr><tr><td>Frequency (Hertz)</td><td>Integer
- Default Value: 1000</td><td>PWM 신호 출력 주파수(Hz)</td></tr><tr><td>Invert Signal</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>Invert Stored Signal</td><td>Boolean</td><td>측정 데이터베이스에 저장되는 값을 반전합니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>설정할 듀티 사이클</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: PWM
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)

PWM 정보 및 각 라이브러리 옵션에 사용할 수 있는 핀 확인은 매뉴얼의 PWM 섹션을 참고하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Startup Value</td><td>Decimal</td><td>AoT 시작 시 값</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Shutdown Value</td><td>Decimal</td><td>AoT 종료 시 값</td></tr><tr><td>Library</td><td>Select(Options: [<strong>Any Pin, <= 40 kHz</strong> | Hardware Pin, <= 30 MHz] (Default in <strong>bold</strong>)</td><td>PWM 신호를 생성할 방식입니다(하드웨어 핀이 더 높은 주파수를 낼 수 있음).</td></tr><tr><td>Frequency (Hertz)</td><td>Integer
- Default Value: 22000</td><td>PWM 신호 출력 주파수 (0 - 70,000 Hz)</td></tr><tr><td>Invert Signal</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>Invert Stored Signal</td><td>Boolean</td><td>측정 데이터베이스에 저장되는 값을 반전합니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>설정할 듀티 사이클</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Shell Script

- Interfaces: Shell
- Output Types: PWM
- Libraries: subprocess.Popen

이 출력의 듀티 사이클이 설정될 때 지정한 사용자로 Linux 셸에서 명령이 실행됩니다. 명령 내의 "((duty_cycle))" 문자열은 실행 전에 설정되는 듀티 사이클 값으로 치환됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Bash Command</td><td>Text
- Default Value: /home/pi/script_pwm.sh ((duty_cycle))</td><td>PWM duty cycle(%) 설정에 실행할 명령</td></tr><tr><td>User</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Startup Value</td><td>Decimal</td><td>AoT 시작 시 값</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Shutdown Value</td><td>Decimal</td><td>AoT 종료 시 값</td></tr><tr><td>Invert Signal</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>Invert Stored Signal</td><td>Boolean</td><td>측정 데이터베이스에 저장되는 값을 반전합니다.</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### Peristaltic Pump: Atlas Scientific

- Manufacturer: Atlas Scientific
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Output Types: Volume, On/Off
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/peristaltic/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO_PMP_Datasheet.pdf)
- Product URL: [Link](https://atlas-scientific.com/peristaltic/ezo-pmp/)

Atlas Scientific 연동 펌프는 최대 속도로 분주하거나 속도를 지정할 수 있습니다. 최소 유량은 0.5 ml/min, 최대 유량은 105 ml/min입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>FTDI Device</td><td>텍스트</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART Device</td><td>텍스트</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>용량 펌핑 시 사용할 유량</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Specify Flow Rate 설정 시 원하는 유량(ml/분)</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Calibration: a calibration can be performed to increase the accuracy of the pump. It's a good idea to clear the calibration before calibrating. First, remove all air from the line by pumping the fluid you would like to calibrate to through the pump hose. Next, press Dispense Amount and the pump will be instructed to dispense 10 ml (unless you changed the default value). Measure how much fluid was actually dispensed, enter this value in the Actual Volume Dispensed (ml) field, and press Calibrate to Dispensed Amount. Now any further pump volumes dispensed should be accurate.</td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td>Volume to Dispense (ml)</td><td>Decimal
- Default Value: 10.0</td><td>분주하도록 지시된 용량 (ml)</td></tr><tr><td>Dispense Amount</td><td>Button</td><td></td></tr><tr><td>Actual Volume Dispensed (ml)</td><td>Decimal
- Default Value: 10.0</td><td>실제 분주된 용량 (ml)</td></tr><tr><td>Calibrate to Dispensed Amount</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x67</td><td>장치에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Peristaltic Pump: Grove I2C Motor Driver (Board v1.3)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wiki.seeedstudio.com/Grove-I2C_Motor_Driver_V1.3)

Grove I2C 모터 드라이버 보드(v1.3)를 제어합니다. 두 모터가 동시에 회전합니다. 모터가 연동 펌프에 연결되어 있으면 이 출력으로 유체 용량을 분주할 수도 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Motor Speed (0 - 100)</td><td>Integer
- Default Value: 100</td><td>속도를 결정하는 모터 출력</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>용량 펌핑 시 사용할 유량</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Specify Flow Rate 설정 시 원하는 유량(ml/분)</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 100.0</td><td>펌프가 토출할 수 있는 최대 속도(ml/min)</td></tr></tbody></table>

### Peristaltic Pump: Grove I2C Motor Driver (TB6612FNG, Board v1.0)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wiki.seeedstudio.com/Grove-I2C_Motor_Driver-TB6612FNG)

Grove I2C 모터 드라이버 보드(v1.3)를 제어합니다. 두 모터가 동시에 회전합니다. 모터가 연동 펌프에 연결되어 있으면 이 출력으로 유체 용량을 분주할 수도 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Motor Speed (0 - 255)</td><td>Integer
- Default Value: 255</td><td>속도를 결정하는 모터 출력</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>용량 펌핑 시 사용할 유량</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Specify Flow Rate 설정 시 원하는 유량(ml/분)</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 100.0</td><td>펌프가 토출할 수 있는 최대 속도(ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>매 60초 주기마다 펌프가 켜지는 최소 시간입니다(Specify Flow Rate 모드에서만 사용).</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x14</td><td>센서에 설정할 새 I2C 주소</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Peristaltic Pump: L298N DC Motor Controller (Pi 5)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: pinctrl
- Additional URL: [Link](https://www.electronicshub.org/raspberry-pi-l298n-interface-tutorial-control-dc-motor-l298n-raspberry-pi/)

L298N은 DC 모터 2개와 방향을 제어할 수 있습니다. 이 모터가 연동 펌프를 구동한다면 Flow Rate를 설정하세요. 그러면 일정 시간 동안 켜는 것뿐만 아니라 정확한 용량을 분주하도록 출력을 지시할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Input Pin 1</td><td>Integer</td><td>컨트롤러의 입력 Pin 1 (BCM 번호)</td></tr><tr><td>Input Pin 2</td><td>Integer</td><td>컨트롤러의 입력 Pin 2 (BCM 번호)</td></tr><tr><td>Use Enable Pin</td><td>Boolean
- Default Value: True</td><td>Enable Pin 사용 활성화</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>컨트롤러의 Enable 핀 (BCM 번호)</td></tr><tr><td>Direction</td><td>Select(Options: [<strong>Forward</strong> | Backward] (Default in <strong>bold</strong>)</td><td>모터 회전 방향</td></tr><tr><td>Volume Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>펌프인 경우, 설정한 듀티 사이클에서 측정된 유량(ml/min)</td></tr></tbody></table>

### Peristaltic Pump: L298N DC Motor Controller (Pi <= 4)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Additional URL: [Link](https://www.electronicshub.org/raspberry-pi-l298n-interface-tutorial-control-dc-motor-l298n-raspberry-pi/)

L298N은 DC 모터 2개의 속도와 방향을 모두 제어할 수 있습니다. 이 모터가 연동 펌프를 구동한다면 Flow Rate를 설정하세요. 그러면 일정 시간 동안 켜는 것뿐만 아니라 정확한 용량을 분주하도록 출력을 지시할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>Input Pin 1</td><td>Integer</td><td>컨트롤러의 입력 Pin 1 (BCM 번호)</td></tr><tr><td>Input Pin 2</td><td>Integer</td><td>컨트롤러의 입력 Pin 2 (BCM 번호)</td></tr><tr><td>Use Enable Pin</td><td>Boolean
- Default Value: True</td><td>Enable Pin 사용 활성화</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>컨트롤러의 Enable 핀 (BCM 번호)</td></tr><tr><td>Enable Pin Duty Cycle</td><td>Integer
- Default Value: 50</td><td>Enable 핀에 적용할 듀티 사이클(%, 1 - 100)</td></tr><tr><td>Direction</td><td>Select(Options: [<strong>Forward</strong> | Backward] (Default in <strong>bold</strong>)</td><td>모터 회전 방향</td></tr><tr><td>Volume Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>펌프인 경우, 설정한 듀티 사이클에서 측정된 유량(ml/min)</td></tr></tbody></table>

### Peristaltic Pump: MCP23017 16-Channel I/O Expander

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp230xx](https://pypi.org/project/adafruit-circuitpython-mcp230xx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/MCP23017)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/devicedoc/20001952c.pdf)
- Product URL: [Link](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG)

각 채널에 릴레이와 연동 펌프가 연결된 MCP23017의 16개 채널을 제어합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>펌프가 켜진 상태에 해당하는 output 채널 상태</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>펌프가 토출할 수 있는 최대 속도(ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>60초 주기마다 펌프를 켜야 하는 최소 시간</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>용량 펌핑 시 사용할 유량</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Specify Flow Rate 설정 시 원하는 유량(ml/분)</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### Peristaltic Pump: PCF8574 8-Channel I/O Expander

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8574)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8574.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

각 채널에 릴레이와 연동 펌프가 연결된 PCF8574의 8개 채널을 제어합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>펌프가 켜진 상태에 해당하는 output 채널 상태</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>펌프가 토출할 수 있는 최대 속도(ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>60초 주기마다 펌프를 켜야 하는 최소 시간</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>용량 펌핑 시 사용할 유량</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Specify Flow Rate 설정 시 원하는 유량(ml/분)</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### Peristaltic Pump: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

이 출력은 GPIO 핀을 HIGH와 LOW로 전환해 일반 연동 펌프(peristaltic pump)의 전원을 제어합니다. 연동 펌프는 일정 시간 동안 켜거나, 펌프의 최대 유량을 확인한 후 최대 속도 또는 지정한 속도로 특정 용량을 분주하도록 지시할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>On State</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>On 상태에 해당하는 GPIO 상태</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>펌프가 토출할 수 있는 최대 속도(ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>60초 주기마다 펌프를 켜야 하는 최소 시간</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>용량 펌핑 시 사용할 유량</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Specify Flow Rate 설정 시 원하는 유량(ml/분)</td></tr><tr><td>Current (Amps)</td><td>Decimal</td><td>제어 중인 장치의 소비 전류</td></tr></tbody></table>

### Remote AoT Output: On/Off

- Interfaces: API
- Output Types: On/Off
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

이 Output은 API를 사용해 네트워크를 통해 다른 AoT On/Off Output을 원격 제어할 수 있게 합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Remote AoT Host</td><td>텍스트</td><td>원격 AoT의 호스트 또는 IP 주소</td></tr><tr><td>Remote AoT API Key</td><td>텍스트</td><td>원격 AoT의 API 키</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 120</td><td>출력 상태를 조회하는 주기</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Remote AoT Output</td></td><td>The Remote AoT Output to control</td></tr><tr><td>Startup State</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Shutdown State</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Force Command</td><td>Boolean</td><td>지시되면 현재 상태와 무관하게 항상 명령을 보냅니다.</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>시작 시 output이 전환될 때 function을 트리거할지 여부</td></tr></tbody></table>

### Remote AoT Output: PWM

- Interfaces: API
- Output Types: PWM
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

이 Output은 API를 사용해 네트워크를 통해 다른 AoT PWM Output을 원격 제어할 수 있게 합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Remote AoT Host</td><td>텍스트</td><td>원격 AoT의 호스트 또는 IP 주소</td></tr><tr><td>Remote AoT API Key</td><td>텍스트</td><td>원격 AoT의 API 키</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 120</td><td>출력 상태를 조회하는 주기</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Remote AoT Output</td></td><td>The Remote AoT Output to control</td></tr><tr><td>Startup State</td><td>선택</td><td>AoT 시작 시 상태 설정</td></tr><tr><td>Start Duty Cycle</td><td>Decimal</td><td>활성화 시 시작 때 설정할 duty cycle</td></tr><tr><td>Shutdown State</td><td>선택</td><td>AoT 종료 시 상태 설정</td></tr><tr><td>Shutdown Duty Cycle</td><td>Decimal</td><td>활성화 시 종료 때 설정할 duty cycle</td></tr><tr><td>Invert Signal</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>Invert Stored Signal</td><td>Boolean</td><td>측정 데이터베이스에 저장되는 값을 반전합니다.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>설정할 듀티 사이클</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### Spacer


Output 정리를 위한 구분자.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Color</td><td>Text
- Default Value: #000000</td><td>이름 텍스트 색상</td></tr></tbody></table>

### Value: GP8XXX (8413, 8403) 2-Channel DAC: 0-10 VDC

- Manufacturer: DFRobot
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Libraries: GP8XXX-IIC
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [GP8XXX-IIC](https://pypi.org/project/GP8XXX-IIC)
- Datasheet URLs: [Link 1](https://wiki.dfrobot.com/SKU_DFR0971_2_Channel_I2C_0_10V_DAC_Module), [Link 2](https://wiki.dfrobot.com/SKU_DFR1073_2_Channel_15bit_I2C_to_0-10V_DAC)
- Product URLs: [Link 1](https://www.dfrobot.com/product-2613.html), [Link 2](https://www.dfrobot.com/product-2756.html)

Output 0 to 10 VDC signal.                GP8403: 12bit DAC Dual Channel I2C to 0-5V/0-10V |                GP8413: 15bit DAC Dual Channel I2C to 0-10V
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>텍스트</td><td>I<sup>2</sup>C 장치의 주소.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>I<sup>2</sup>C 장치가 연결된 버스.</td></tr><tr><td>Device</td><td>Select(Options: [<strong>GP8403 12-bit</strong> | GP8413 15-bit] (Default in <strong>bold</strong>)</td><td>GP8XXX 장치 선택</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Start State</td><td>Select(Options: [Previously-Saved State | <strong>Specified Value</strong>] (Default in <strong>bold</strong>)</td><td>채널 시작 상태 선택</td></tr><tr><td>Start Value (volts)</td><td>Decimal</td><td>Specified Value 선택 시, 시작 상태 값을 설정하세요.</td></tr><tr><td>Shutdown State</td><td>Select(Options: [Previously-Saved Value | <strong>Specified Value</strong>] (Default in <strong>bold</strong>)</td><td>채널 종료 상태 선택</td></tr><tr><td>Shutdown Value (volts)</td><td>Decimal</td><td>Specified Value 선택 시, 종료 상태 값을 설정하세요.</td></tr><tr><td>Off Value (volts)</td><td>Decimal</td><td>지정 시 Off 때 적용할 값</td></tr></tbody></table>

