## Built-In Actions (System)

### Actions: 일시중지

- Manufacturer: AoT
- Works with: Functions

self.run_all_actions()이 사용될 때 Action 실행 간의 지연을 설정합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will create a pause for the set duration. When <strong>self.run_all_actions()</strong> is executed, this will add a pause in the sequential execution of all actions.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>지속시간 (초)</td><td>Decimal</td><td>The duration to pause</td></tr></tbody></table>

### Environment Control

- Manufacturer: AoT
- Works with: Functions

통합 환경 제어(env_coordinator) Function에 액추에이터를 등록합니다. 둘 이상의 장치를 등록하려면 이 동작을 여러 번 추가하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output 채널</td><td>Select Channel (Output_Channels)</td><td>제어할 Output 채널을 선택하세요.</td></tr><tr><td>액추에이터 유형</td><td>Select</td><td>이 Output이 수행할 역할을 선택하세요.</td></tr><tr><td>비용 지수</td><td>Decimal
- Default Value: 5.0</td><td>값이 낮을수록 우선순위가 높습니다 (1 = 비용이 없는 자연 환기, 10 = 고비용 장치).</td></tr><tr><td>시간 제어 종료 시</td><td>Select(Options: [<strong>아무것도 하지 않음</strong> | 끄기 | 켜기 | 열림 % 설정 (환기창 전용)] (Default in <strong>bold</strong>)</td><td>시간 제어 구간이 종료될 때 이 액추에이터에 적용할 동작입니다.</td></tr><tr><td>종료 시 열림 %</td><td>Decimal</td><td>시간 구간이 종료될 때의 목표 열림 비율입니다 (환기창 / 개구부 전용).</td></tr><tr><td>천 투과율 개별 지정 (0-1, 차광막 전용)</td><td>Decimal</td><td>이 차광막의 천이 나머지와 다를 때만 씁니다. 0 으로 두면 연동 시설에 정해 둔 값을 씁니다. 실내 광센서가 없을 때, 실외 일사와 차광막 개도로 실내 광량을 추정하는 데 쓰입니다.</td></tr><tr><td>효과 계수 재정의 (K_*)</td><td>Decimal</td><td>0 = 기본값 사용. 측정 데이터로 보정할 때만 입력하세요. 예: 냉방기 → K_COOLER_T, 포거 → K_FOG_RH.</td></tr><tr><td>전체 행정 시간 (초)</td><td>Decimal</td><td>이 액추에이터가 0→100%까지 이동하는 데 걸리는 시간(초)입니다. 사이클당 최대 명령 변화량을 제한하여 물리적 속도보다 빠른 불가능한 명령이 전송되지 않도록 하는 데 사용됩니다. 0 = 비활성화 (slew_per_cycle 값을 그대로 사용). 예: 작동에 10분이 걸리는 환기창 모터 → 600 입력.</td></tr><tr><td>최소 반복 간격 (초)</td><td>Decimal</td><td>목표값이 변하지 않더라도 이 액추에이터에 명령을 반복 전송하는 최소 간격(초)입니다. 0 = 시스템 기본값 사용 (600초 워치독). 느린 모터식 액추에이터의 경우 릴레이 수명을 늘리기 위해 값을 높이세요.</td></tr></tbody></table>

### Execute Python 3 Code

- Manufacturer: AoT
- Works with: Inputs

Execute Python 3 code when measurements are acquired.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Python 3 Code</td></td><td>The code to execute</td></tr></tbody></table>

### LED: Kasa RGB Bulb: Change Color

- Manufacturer: AoT
- Works with: Functions

Change the color of the LED in a Kasa RGB Bulb. Select the Kasa RGB Bulb Output.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected Kasa RGB Bulb to the selected Hue, Saturation, and Brightness. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "hue": 10, "saturation": 50, "brightness": 25})</strong> will set the hue (0 - 360), saturation (0 - 100), and brightness (0 - 100) of the Kasa RGB Bulb Output with the specified ID. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the energy meter Input</td></tr><tr><td>색상 (도)</td><td>Integer</td><td>The hue to set, in degrees (0 - 360)</td></tr><tr><td>색상 (퍼센트)</td><td>Integer
- Default Value: 50</td><td>The saturation to set, in percent (0 - 100)</td></tr><tr><td>밝기 (퍼센트)</td><td>Integer
- Default Value: 50</td><td>The brightness to set, in percent (0 - 100)</td></tr></tbody></table>

### LED: Neopixel: Change Pixel Color

- Manufacturer: AoT
- Works with: Functions

Change the color of an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller, pixel number, and color.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong> will set the color of the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color in RGB format, each from 0 to 255 (e.g "10, 0, 0")</td></tr></tbody></table>

### LED: Neopixel: 점멸 끄기

- Manufacturer: AoT
- Works with: Functions

Stop flashing an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller and pixel number.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0})</strong> will stop flashing the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr></tbody></table>

### LED: Neopixel: 점멸 켜기

- Manufacturer: AoT
- Works with: Functions

Start flashing an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller, pixel number, and color.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong> will start flashing the color of the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color in RGB format, each from 0 to 255 (e.g "10, 0, 0")</td></tr></tbody></table>

### MQTT: 발행

- Manufacturer: AoT
- Works with: Functions
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Publish a value to an MQTT server.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will publish the saved payload text options to the MQTT server. Executing <strong>self.run_action("ACTION_ID", value={"payload": 42})</strong> will publish the specified payload (any type) to the MQTT server. You can also specify the topic (e.g. value={"topic": "my_topic", "payload": 42}). Warning: If using multiple MQTT Inputs or Functions, ensure the Client IDs are unique.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>호스트명</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>포트</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>Payload</td><td>Text</td><td>The payload to publish</td></tr><tr><td>Payload Type</td><td>Select(Options: [<strong>Text</strong> | Integer | Float/Decimal] (Default in <strong>bold</strong>)</td><td>The type to cast the payload</td></tr><tr><td>연결 유지</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_i5404Wvg</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>사용자명</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>비밀번호</td><td>Text</td><td>Password for connecting to the server</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### MQTT: 발행: 측정값

- Manufacturer: AoT
- Works with: Inputs
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Publish an Input measurement to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>측정값</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>호스트명</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>포트</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>연결 유지</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_DCRrfYCC</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>사용자명</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>비밀번호</td><td>Text</td><td>Password for connecting to the server.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### Output: 액추에이터 페어링 (위치 / 정지)

- Manufacturer: AoT
- Works with: Functions

액추에이터 페어링 출력을 목표 위치(0–100 %)로 구동하거나 정지 명령을 전송합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> drives the actuator to the configured position. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "UUID", "channel": 0, "command": "set_position", "position": 75})</strong> drives the Actuator Paired output with the given ID to 75 %. Use <strong>"command": "stop"</strong> to halt motion immediately.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>액추에이터 페어링 출력</td><td>Select Channel (Output_Channels)</td><td>제어할 액추에이터 페어링 출력 채널을 선택하세요.</td></tr><tr><td>명령</td><td>Select(Options: [<strong>위치 설정 (%)</strong> | 정지] (Default in <strong>bold</strong>)</td><td>"위치 설정"은 액추에이터를 목표 %로 구동합니다. "정지"는 즉시 동작을 멈춥니다.</td></tr><tr><td>목표 위치 (%)</td><td>Decimal</td><td>0 = 완전히 닫힘, 100 = 완전히 열림. 명령이 "위치 설정"일 때만 사용됩니다.</td></tr></tbody></table>

### PID: 메서드 설정

- Manufacturer: AoT
- Works with: Functions

PID를 사용할 메서드를 선택합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "method_id": "fe8b8f41-131b-448d-ba7b-00a044d24075"})</strong> will set a method for the PID Controller with the specified IDs. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the PID Controller to apply the method</td></tr><tr><td>메서드</td><td>Select Device</td><td>Select the Method to apply to the PID</td></tr></tbody></table>

### PID: 상향: 목표값

- Manufacturer: AoT
- Works with: Functions

PID의 목표값을 높입니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will raise the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong> will raise the setpoint of the PID with the specified ID. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the PID Controller to raise the setpoint of</td></tr><tr><td>상향 목표값</td><td>Decimal</td><td>The amount to raise the PID setpoint by</td></tr></tbody></table>

### PID: 설정: 목표값

- Manufacturer: AoT
- Works with: Functions

PID의 목표값을 설정합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"setpoint": 42})</strong> will set the setpoint of the PID Controller (e.g. 42). You can also specify the PID ID (e.g. value={"setpoint": 42, "pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"}). Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the PID Controller to pause</td></tr><tr><td>목표값</td><td>Decimal</td><td>The setpoint to set the PID Controller</td></tr></tbody></table>

### PID: 일시중지

- Manufacturer: AoT
- Works with: Functions

PID를 일시 중지합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong> will pause the PID Controller with the specified ID.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the PID Controller to pause</td></tr></tbody></table>

### PID: 재개

- Manufacturer: AoT
- Works with: Functions

PID를 재개합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will resume the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong> will resume the PID Controller with the specified ID.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the PID Controller to resume</td></tr></tbody></table>

### PID: 하향: 목표값

- Manufacturer: AoT
- Works with: Functions

PID의 목표값을 낮춥니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will lower the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong> will lower the setpoint of the PID with the specified ID. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the PID Controller to lower the setpoint of</td></tr><tr><td>하향 목표값</td><td>Decimal</td><td>The amount to lower the PID setpoint by</td></tr></tbody></table>

### Send Email

- Manufacturer: AoT
- Works with: Functions

Send an email.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will email the specified recipient(s) using the SMTP credentials in the system configuration. Separate multiple recipients with commas. The body of the email will be the self-generated message. Executing <strong>self.run_action("ACTION_ID", value={"email_address": ["email1@email.com", "email2@email.com"], "message": "My message"})</strong> will send an email to the specified recipient(s) with the specified message.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>E-Mail Address</td><td>Text
- Default Value: email@domain.com</td><td>E-mail recipient(s) (separate multiple addresses with commas)</td></tr></tbody></table>

### Send Email with Photo

- Manufacturer: AoT
- Works with: Functions

Take a photo and send an email with it attached.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will take a photo and email it to the specified recipient(s) using the SMTP credentials in the system configuration. Separate multiple recipients with commas. The body of the email will be the self-generated message. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "email_address": ["email1@email.com", "email2@email.com"], "message": "My message"})</strong> will capture a photo using the camera with the specified ID and send an email to the specified email(s) with message and attached photo. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>카메라</td><td>Select Device</td><td>Select the Camera to take a photo with</td></tr><tr><td>E-Mail Address</td><td>Text
- Default Value: email@domain.com</td><td>E-mail recipient(s). Separate multiple with commas.</td></tr></tbody></table>

### 디스플레이: 깜박임: 끄기

- Manufacturer: AoT
- Works with: Functions

Turn display flashing off

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will stop the backlight flashing on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will stop the backlight flashing on the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>디스플레이</td><td>Select Device</td><td>Select the display to stop flashing the backlight</td></tr></tbody></table>

### 디스플레이: 깜박임: 켜기

- Manufacturer: AoT
- Works with: Functions

Turn display flashing on

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will start the backlight flashing on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will start the backlight flashing on the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>디스플레이</td><td>Select Device</td><td>Select the display to start flashing the backlight</td></tr></tbody></table>

### 디스플레이: 백라이트: 끄기

- Manufacturer: AoT
- Works with: Functions

Turn display backlight off

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will turn the backlight off for the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will turn the backlight off for the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>디스플레이</td><td>Select Device</td><td>Select the display to turn the backlight off</td></tr></tbody></table>

### 디스플레이: 백라이트: 색상

- Manufacturer: AoT
- Works with: Functions

Set the display backlight color

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will change the backlight color on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "color": "255,0,0"})</strong> will change the backlight color on the controller with the specified ID and color. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>디스플레이</td><td>Select Device</td><td>Select the display to set the backlight color</td></tr><tr><td>Color (RGB)</td><td>Text
- Default Value: 255,0,0</td><td>Color as R,G,B values (e.g. "255,0,0" without quotes)</td></tr></tbody></table>

### 디스플레이: 백라이트: 켜기

- Manufacturer: AoT
- Works with: Functions

Turn display backlight on

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will turn the backlight on for the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will turn the backlight on for the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>디스플레이</td><td>Select Device</td><td>Select the display to turn the backlight on</td></tr></tbody></table>

### 방정식 (Single-Measurement)

- Manufacturer: AoT
- Works with: Inputs

Modify a channel value with an equation before storing it in the database.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>측정값</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>방정식</td><td>Text
- Default Value: x-10</td><td>The equation to apply to the value before storing. "x" is the measurement value. Example: x-10</td></tr></tbody></table>

### 시스템: 시스템 종료

- Manufacturer: AoT
- Works with: Functions

Shutdown the System

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will shut down the system in 10 seconds.


### 시스템: 재시작

- Manufacturer: AoT
- Works with: Functions

Restart the System

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will restart the system in 10 seconds.


### 실행: Bash/Shell Command

- Manufacturer: AoT
- Works with: Functions

리눅스 bash 셸 명령을 실행합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will execute the bash command.Executing <strong>self.run_action("ACTION_ID", value={"user": "aot", "command": "/home/pi/my_script.sh on"})</strong> will execute the action with the specified command and user.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>사용자</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>명령</td><td>Text
- Default Value: /home/pi/my_script.sh on</td><td>Command to execute</td></tr></tbody></table>

### 원격: Daemon Log Line

- Manufacturer: AoT
- Works with: Functions

데몬 로그에 로그 줄을 생성합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will add a line to the Daemon log. Executing <strong>self.run_action("ACTION_ID", value={"log_level": "info", "log_text": "this is a log line"})</strong> will execute the action with the specified log level and log line text. If a log line text is not specified, then the action message will be used as the text.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Log Level</td><td>Select(Options: [<strong>Info</strong> | Warning | Error | Debug] (Default in <strong>bold</strong>)</td><td>The log level to insert the text into the log</td></tr><tr><td>Log Line Text</td><td>Text
- Default Value: Log Line Text</td><td>The text to insert in the Daemon log</td></tr></tbody></table>

### 원격: 노트

- Manufacturer: AoT
- Works with: Functions

선택한 옵션으로 노트를 생성합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will create a note with the configured options. Executing <strong>self.run_action("ACTION_ID", value={"tags": ["tag1"], "name": "Title", "note": "body", "category": "alarm", "priority": 1})</strong> will override the stored settings. Set <strong>auto_target</strong> to link the note automatically to the parent Function.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>태그</td></td><td>하나 이상의 태그를 선택하세요</td></tr><tr><td>이름</td><td>Text</td><td>제목 (비워두면 본문 첫 줄에서 자동 추출)</td></tr><tr><td>노트</td></td><td>노트 본문</td></tr><tr><td>액션 메시지 본문에 포함</td><td>Boolean</td><td>조건/트리거가 전달한 메시지를 노트 본문 끝에 추가합니다</td></tr><tr><td>상위 Function 자동 연결</td><td>Boolean
- Default Value: True</td><td>노트를 이 액션의 부모 Function에 자동으로 연결합니다 (target_id/target_type)</td></tr><tr><td>카테고리</td><td>Select(Options: [<strong>일반</strong> | 관찰 | 경보 | 유지관리] (Default in <strong>bold</strong>)</td><td>노트 카테고리</td></tr><tr><td>중요도</td><td>Select(Options: [<strong>보통</strong> | 높음 | 긴급] (Default in <strong>bold</strong>)</td><td>노트 중요도</td></tr></tbody></table>

### 웹훅

- Manufacturer: AoT
- Works with: Functions

Emits a HTTP request when triggered. The first line contains a HTTP verb (GET, POST, PUT, ...) followed by a space and the URL to call. Subsequent lines are optional "name: value"-header parameters. After a blank line, the body payload to be sent follows. {{{message}}} is a placeholder that gets replaced by the message, {{{quoted_message}}} is the message in an URL safe encoding.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will run the Action.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Webhook Request</td></td><td>HTTP request to execute</td></tr></tbody></table>

### 유량계: 전체 초기화

- Manufacturer: AoT
- Works with: Functions

Clear the total volume saved for a flow meter Input. The Input must have the Clear Total Volume option.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will clear the total volume for the selected flow meter Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will clear the total volume for the flow meter Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the flow meter Input</td></tr></tbody></table>

### 입력: 측정 강제 실행:

- Manufacturer: AoT
- Works with: Functions

입력에 대한 측정을 강제로 수행합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will force acquiring measurements for the selected Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will force acquiring measurements for the Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Input</td><td>Select Device</td><td>Select an Input</td></tr></tbody></table>

### 전력계: 전체 초기화

- Manufacturer: AoT
- Works with: Functions

Clear the total kWh saved for an energy meter Input. The Input must have the Clear Total kWh option. This will also clear all energy stats on the device, not just the total kWh.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will clear the total kWh for the selected energy meter Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will clear the total kWh for the energy meter Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the energy meter Input</td></tr></tbody></table>

### 출력: 값

- Manufacturer: AoT
- Works with: Functions

출력으로 값을 전송합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate a value output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "value": 42})</strong> will send a value to the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>값</td><td>Decimal</td><td>The value to send to the output</td></tr></tbody></table>

### 출력: 듀티 사이클

- Manufacturer: AoT
- Works with: Functions

PWM 출력을 듀티 사이클로 설정합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the PWM output duty cycle. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "duty_cycle": 42})</strong> will set the duty cycle of the PWM output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>듀티 사이클</td><td>Decimal</td><td>듀티 사이클 PWM (퍼센트, 0.0 - 100.0)</td></tr></tbody></table>

### 출력: 램프 듀티 사이클

- Manufacturer: AoT
- Works with: Functions

PWM 출력을 일정 시간 동안 한 듀티 사이클에서 다른 듀티 사이클로 점진적으로 변경합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will ramp the PWM output duty cycle according to the settings. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "start": 42, "end": 62, "increment": 1.0, "duration": 600})</strong> will ramp the duty cycle of the PWM output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>듀티 사이클: 시작</td><td>Decimal</td><td>듀티 사이클 PWM (퍼센트, 0.0 - 100.0)</td></tr><tr><td>듀티 사이클: 종료</td><td>Decimal
- Default Value: 50.0</td><td>듀티 사이클 PWM (퍼센트, 0.0 - 100.0)</td></tr><tr><td>증가 (듀티 사이클)</td><td>Decimal
- Default Value: 1.0</td><td>How much to change the duty cycle every Duration</td></tr><tr><td>지속시간 (초)</td><td>Decimal</td><td>How long to ramp from start to finish.</td></tr></tbody></table>

### 출력: 부피

- Manufacturer: AoT
- Works with: Functions

출력에 부피를 분배하도록 지시합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate a volume output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "volume": 42})</strong> will send a volume to the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>부피</td><td>Decimal</td><td>The volume to send to the output</td></tr></tbody></table>

### 출력: 켜기/끄기/지속시간

- Manufacturer: AoT
- Works with: Functions

On/Off 출력을 켜거나 끄거나 일정 시간 동안 켭니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate an output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "state": "on", "duration": 300})</strong> will set the state of the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system. If state is on and a duration is set, the output will turn off after the duration.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>상태</td><td>Select</td><td>Turn the output on or off</td></tr><tr><td>지속시간 (초)</td><td>Decimal</td><td>If On, you can set a duration to turn the output on. 0 stays on.</td></tr></tbody></table>

### 측정값: 입력

- Manufacturer: AoT
- Works with: Functions

AoT 평균 함수에 포함할 Input 측정값을 등록합니다. 이 동작은 실행되지 않으며, 측정값 선택만 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>측정값: 입력</td><td>Select Measurement (Input)</td><td>평균 계산에 포함할 Input 센서 측정값</td></tr><tr><td>최대 유효 시간 (초)</td><td>Integer
- Default Value: 360</td><td>이 값(초)보다 오래된 측정값은 평균에서 제외됩니다</td></tr></tbody></table>

### 측정값: 출력

- Manufacturer: AoT
- Works with: Functions

AoT 평균 함수에 포함할 Output 측정값을 등록합니다. 지속 시간 등 Output 채널 측정값을 선택하세요. 이 동작은 실행되지 않으며, 측정값 선택만 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>측정값: 출력</td><td>Select Measurement (Output_Channels_Measurements)</td><td>평균 계산에 포함할 Output 채널 측정값 (예: 지속 시간)</td></tr><tr><td>최대 유효 시간 (초)</td><td>Integer
- Default Value: 360</td><td>이 값(초)보다 오래된 측정값은 평균에서 제외됩니다</td></tr></tbody></table>

### 측정값: 함수

- Manufacturer: AoT
- Works with: Functions

AoT 평균 함수에 포함할 Function 측정값을 등록합니다. 다른 함수에서 계산된 출력값을 선택하세요. 이 동작은 실행되지 않으며, 측정값 선택만 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>측정값: 함수</td><td>Select Measurement (Function)</td><td>평균 계산에 포함할 Function 계산 측정값</td></tr><tr><td>최대 유효 시간 (초)</td><td>Integer
- Default Value: 360</td><td>이 값(초)보다 오래된 측정값은 평균에서 제외됩니다</td></tr></tbody></table>

### 카메라: 사진 캡처

- Manufacturer: AoT
- Works with: Functions

선택한 카메라에서 사진 촬영하기

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will capture a photo with the selected Camera. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will capture a photo with the Camera with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>카메라</td><td>Select Device</td><td>Select the Camera to take a photo</td></tr></tbody></table>

### 카메라: 타임랩스: 일시중지

- Manufacturer: AoT
- Works with: Functions

Pause a camera time-lapse

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected Camera time-lapse. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will pause the Camera time-lapse with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>카메라</td><td>Select Device</td><td>Select the Camera to pause the time-lapse</td></tr></tbody></table>

### 카메라: 타임랩스: 재개

- Manufacturer: AoT
- Works with: Functions

Resume a camera time-lapse

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will resume the selected Camera time-lapse. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will resume the Camera time-lapse with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>카메라</td><td>Select Device</td><td>Select the Camera to resume the time-lapse</td></tr></tbody></table>

### 컨트롤러: 비활성화

- Manufacturer: AoT
- Works with: Functions

컨트롤러를 비활성화합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will deactivate the selected Controller. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will deactivate the controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the controller to deactivate</td></tr></tbody></table>

### 컨트롤러: 활성화

- Manufacturer: AoT
- Works with: Functions

컨트롤러를 활성화합니다.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will activate the selected Controller. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will activate the controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>컨트롤러</td><td>Select Device</td><td>Select the controller to activate</td></tr></tbody></table>

