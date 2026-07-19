## Built-In Actions (System)

### Actions: Pause

- Manufacturer: AoT
- Works with: Functions

self.run_all_actions() 사용 시 Action 실행 사이의 지연을 설정합니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 설정된 시간만큼 일시정지를 만듭니다. <strong>self.run_all_actions()</strong>를 실행하면 모든 액션의 순차 실행 중에 일시정지가 삽입됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Duration (Seconds)</td><td>Decimal</td><td>일시정지 시간</td></tr></tbody></table>

### Camera: Capture Photo

- Manufacturer: AoT
- Works with: Functions

선택한 Camera로 사진 촬영.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 Camera로 사진을 촬영합니다. <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 Camera로 사진을 촬영합니다. camera_id 값은 시스템에 실제로 존재하는 Camera ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>촬영할 Camera 선택</td></tr></tbody></table>

### Camera: Time-lapse: Pause

- Manufacturer: AoT
- Works with: Functions

Pause a camera time-lapse

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 Camera의 타임랩스를 일시정지합니다. <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 Camera 타임랩스를 일시정지합니다. camera_id 값은 시스템에 실제로 존재하는 Camera ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>타임랩스를 일시정지할 Camera 선택</td></tr></tbody></table>

### Camera: Time-lapse: Resume

- Manufacturer: AoT
- Works with: Functions

Resume a camera time-lapse

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 Camera의 타임랩스를 재개합니다. <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 Camera 타임랩스를 재개합니다. camera_id 값은 시스템에 실제로 존재하는 Camera ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>타임랩스를 재개할 Camera 선택</td></tr></tbody></table>

### Controller: Activate

- Manufacturer: AoT
- Works with: Functions

Controller를 활성화합니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 Controller를 활성화합니다. <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 컨트롤러를 활성화합니다. controller_id 값은 시스템에 실제로 존재하는 Controller ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>활성화할 컨트롤러 선택</td></tr></tbody></table>

### Controller: Deactivate

- Manufacturer: AoT
- Works with: Functions

Controller를 비활성화합니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 Controller를 비활성화합니다. <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 컨트롤러를 비활성화합니다. controller_id 값은 시스템에 실제로 존재하는 Controller ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>비활성화할 컨트롤러 선택</td></tr></tbody></table>

### Create: Daemon Log Line

- Manufacturer: AoT
- Works with: Functions

데몬 로그에 로그 한 줄 기록.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 Daemon 로그에 한 줄을 추가합니다. <strong>self.run_action("ACTION_ID", value={"log_level": "info", "log_text": "this is a log line"})</strong>를 실행하면 지정한 로그 레벨과 로그 텍스트로 액션을 실행합니다. 로그 텍스트를 지정하지 않으면 액션 메시지가 텍스트로 사용됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Log Level</td><td>Select(Options: [<strong>Info</strong> | Warning | Error | Debug] (Default in <strong>bold</strong>)</td><td>로그에 텍스트를 기록할 로그 레벨</td></tr><tr><td>Log Line Text</td><td>Text
- Default Value: Log Line Text</td><td>데몬 로그에 삽입할 텍스트</td></tr></tbody></table>

### Create: Note

- Manufacturer: AoT
- Works with: Functions

선택한 Tag로 노트 생성.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 태그와 노트로 노트를 생성합니다. <strong>self.run_action("ACTION_ID", value={"tags": ["tag1", "tag2"], "name": "My Note", "note": "this is a message"})</strong>를 실행하면 지정한 태그 목록과 노트로 액션을 실행합니다. 태그를 하나만 사용할 경우 리스트의 유일한 요소로 넣으세요(예: ["tag1"]). note를 지정하지 않으면 액션 메시지가 노트로 사용됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Tags</td></td><td>Select one or more tags</td></tr><tr><td>Name</td><td>Text
- Default Value: Name</td><td>노트 이름</td></tr><tr><td>Note</td><td>Text
- Default Value: Note</td><td>노트 본문</td></tr><tr><td>Include Message in Note</td><td>Boolean</td><td>생성되는 노트에 action으로 전달된 메시지를 포함합니다.</td></tr></tbody></table>

### Display: Backlight: Color

- Manufacturer: AoT
- Works with: Functions

Set the display backlight color

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 디스플레이의 백라이트 색상을 변경합니다. <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "color": "255,0,0"})</strong>를 실행하면 지정한 ID와 색상으로 컨트롤러의 백라이트 색상을 변경합니다. display_id 값은 시스템에 실제로 존재하는 Function ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>백라이트 색상을 설정할 디스플레이 선택</td></tr><tr><td>Color (RGB)</td><td>Text
- Default Value: 255,0,0</td><td>R,G,B 값 형식의 색상(예: 따옴표 없이 "255,0,0")</td></tr></tbody></table>

### Display: Backlight: Off

- Manufacturer: AoT
- Works with: Functions

Turn display backlight off

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 디스플레이의 백라이트를 끕니다. <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 컨트롤러의 백라이트를 끕니다. display_id 값은 시스템에 실제로 존재하는 Function ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>백라이트를 끌 디스플레이 선택</td></tr></tbody></table>

### Display: Backlight: On

- Manufacturer: AoT
- Works with: Functions

Turn display backlight on

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 디스플레이의 백라이트를 켭니다. <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 컨트롤러의 백라이트를 켭니다. display_id 값은 시스템에 실제로 존재하는 Function ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>백라이트를 켤 디스플레이 선택</td></tr></tbody></table>

### Display: Flashing: Off

- Manufacturer: AoT
- Works with: Functions

Turn display flashing off

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 디스플레이의 백라이트 깜빡임을 멈춥니다. <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 컨트롤러에서 백라이트 깜빡임을 멈춥니다. display_id 값은 시스템에 실제로 존재하는 Function ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>백라이트 깜빡임을 멈출 디스플레이 선택</td></tr></tbody></table>

### Display: Flashing: On

- Manufacturer: AoT
- Works with: Functions

Turn display flashing on

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 디스플레이의 백라이트 깜빡임을 시작합니다. <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 컨트롤러에서 백라이트 깜빡임을 시작합니다. display_id 값은 시스템에 실제로 존재하는 Function ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>백라이트 깜빡임을 시작할 디스플레이 선택</td></tr></tbody></table>

### Equation (Single-Measurement)

- Manufacturer: AoT
- Works with: Inputs

데이터베이스에 저장하기 전에 수식으로 채널 값을 변경합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>Equation</td><td>Text
- Default Value: x-10</td><td>저장 전에 값에 적용할 수식입니다. "x"는 측정값입니다. 예: x-10</td></tr></tbody></table>

### Execute Python 3 Code

- Manufacturer: AoT
- Works with: Inputs

측정값을 얻을 때 Python 3 코드를 실행합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Python 3 Code</td></td><td>The code to execute</td></tr></tbody></table>

### Execute: Bash/Shell Command

- Manufacturer: AoT
- Works with: Functions

Linux bash 셸 명령 실행.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 bash 명령을 실행합니다. <strong>self.run_action("ACTION_ID", value={"user": "aot", "command": "/home/pi/my_script.sh on"})</strong>를 실행하면 지정한 명령과 사용자로 액션을 실행합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>User</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>Command</td><td>Text
- Default Value: /home/pi/my_script.sh on</td><td>실행할 명령</td></tr></tbody></table>

### Flow Meter: Clear Total (Kilowatt-hour)

- Manufacturer: AoT
- Works with: Functions

에너지 미터 Input에 저장된 총 kWh를 초기화합니다. Input에 Clear Total kWh 옵션이 있어야 합니다. 이는 총 kWh뿐만 아니라 기기의 모든 에너지 통계도 초기화합니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 에너지 미터 Input의 총 kWh를 초기화합니다. <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 에너지 미터 Input의 총 kWh를 초기화합니다. input_id 값은 시스템에 실제로 존재하는 Input ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>전력계 Input 선택</td></tr></tbody></table>

### Flow Meter: Clear Total (Volume)

- Manufacturer: AoT
- Works with: Functions

유량계 Input에 저장된 총 유량을 초기화합니다. Input에 Clear Total Volume 옵션이 있어야 합니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 유량계 Input의 총 유량을 초기화합니다. <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 유량계 Input의 총 유량을 초기화합니다. input_id 값은 시스템에 실제로 존재하는 Input ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>유량계 Input 선택</td></tr></tbody></table>

### Input: Force Measurements:

- Manufacturer: AoT
- Works with: Functions

Force measurements to be conducted for an input

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 Input의 측정값 획득을 강제로 수행합니다. <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong>를 실행하면 지정한 ID의 Input의 측정값 획득을 강제로 수행합니다. input_id 값은 시스템에 실제로 존재하는 Input ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Input</td><td>Select Device</td><td>Input 선택</td></tr></tbody></table>

### LED: Kasa RGB Bulb: Change Color

- Manufacturer: AoT
- Works with: Functions

Kasa RGB 전구의 LED 색상을 변경합니다. Kasa RGB Bulb Output을 선택하세요.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 Kasa RGB 전구를 선택한 색상(Hue), 채도(Saturation), 밝기(Brightness)로 설정합니다. <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "hue": 10, "saturation": 50, "brightness": 25})</strong>를 실행하면 지정한 ID의 Kasa RGB Bulb Output의 hue(0 - 360), saturation(0 - 100), brightness(0 - 100)를 설정합니다. output_id 값은 시스템에 실제로 존재하는 Output ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>전력계 Input 선택</td></tr><tr><td>Hue (Degree)</td><td>Integer</td><td>설정할 색상(hue), 각도 (0 - 360)</td></tr><tr><td>Saturation (Percent)</td><td>Integer
- Default Value: 50</td><td>설정할 채도 (%, 0 - 100)</td></tr><tr><td>Brightness (Percent)</td><td>Integer
- Default Value: 50</td><td>설정할 밝기 (%, 0 - 100)</td></tr></tbody></table>

### LED: Neopixel: Change Pixel Color

- Manufacturer: AoT
- Works with: Functions

Neopixel LED 스트립의 LED 색상을 변경합니다. Neopixel LED Strip Controller, 픽셀 번호, 색상을 선택하세요.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 LED를 선택한 색상으로 설정합니다. <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong>를 실행하면 지정한 ID의 Neopixel LED Strip Controller에서 지정한 LED의 색상을 설정합니다. controller_id 값은 시스템에 실제로 존재하는 Controller ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>네오픽셀을 조절하는 컨트롤러를 선택하세요.</td></tr><tr><td>LED Position</td><td>Integer</td><td>스트립에서 LED의 위치</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>RGB 형식 색상, 각 값은 0~255(예: "10, 0, 0")</td></tr></tbody></table>

### LED: Neopixel: Flashing Off

- Manufacturer: AoT
- Works with: Functions

Neopixel LED 스트립의 LED 깜빡임을 멈춥니다. Neopixel LED Strip Controller와 픽셀 번호를 선택하세요.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 LED를 선택한 색상으로 설정합니다. <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0})</strong>를 실행하면 지정한 ID의 Neopixel LED Strip Controller에서 지정한 LED의 깜빡임을 멈춥니다. controller_id 값은 시스템에 실제로 존재하는 Controller ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>네오픽셀을 조절하는 컨트롤러를 선택하세요.</td></tr><tr><td>LED Position</td><td>Integer</td><td>스트립에서 LED의 위치</td></tr></tbody></table>

### LED: Neopixel: Flashing On

- Manufacturer: AoT
- Works with: Functions

Neopixel LED 스트립의 LED 깜빡임을 시작합니다. Neopixel LED Strip Controller, 픽셀 번호, 색상을 선택하세요.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 LED를 선택한 색상으로 설정합니다. <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong>를 실행하면 지정한 ID의 Neopixel LED Strip Controller에서 지정한 LED의 색상을 깜빡이기 시작합니다. controller_id 값은 시스템에 실제로 존재하는 Controller ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>네오픽셀을 조절하는 컨트롤러를 선택하세요.</td></tr><tr><td>LED Position</td><td>Integer</td><td>스트립에서 LED의 위치</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>RGB 형식 색상, 각 값은 0~255(예: "10, 0, 0")</td></tr></tbody></table>

### MQTT: Publish

- Manufacturer: AoT
- Works with: Functions
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

MQTT 서버에 값 게시.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 저장된 페이로드 텍스트 옵션을 MQTT 서버에 발행합니다. <strong>self.run_action("ACTION_ID", value={"payload": 42})</strong>를 실행하면 지정한 페이로드(임의 타입)를 MQTT 서버에 발행합니다. 토픽을 지정할 수도 있습니다(예: value={"topic": "my_topic", "payload": 42}). 경고: 여러 MQTT Input 또는 Function을 사용할 경우 Client ID가 고유한지 확인하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Hostname</td><td>Text
- Default Value: localhost</td><td>MQTT 서버 호스트명</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>MQTT 서버 포트</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>발행할 토픽</td></tr><tr><td>Payload</td><td>텍스트</td><td>발행할 페이로드</td></tr><tr><td>Payload Type</td><td>Select(Options: [<strong>텍스트</strong> | Integer | Float/Decimal] (Default in <strong>bold</strong>)</td><td>payload를 변환할 타입</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>클라이언트의 keepalive 타임아웃 값. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_gHAszYVa</td><td>MQTT 서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 접속용 비밀번호</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr></tbody></table>

### MQTT: Publish: Measurement

- Manufacturer: AoT
- Works with: Inputs
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Input Measurement을 MQTT 서버에 게시.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>Hostname</td><td>Text
- Default Value: localhost</td><td>MQTT 서버 호스트명</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>MQTT 서버 포트</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>발행할 토픽</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>클라이언트의 keepalive 타임아웃 값. 비활성화하려면 0으로 설정하세요.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_yohHlpuN</td><td>MQTT 서버 연결에 사용할 고유 클라이언트 ID</td></tr><tr><td>Use Login</td><td>Boolean</td><td>로그인 자격 증명 전송</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>서버 접속용 사용자명</td></tr><tr><td>Password</td><td>텍스트</td><td>서버 연결용 비밀번호.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>웹소켓으로 서버에 연결.</td></tr></tbody></table>

### Output: Duty Cycle

- Manufacturer: AoT
- Works with: Functions

PWM Output의 duty cycle 설정.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 PWM 출력의 듀티 사이클을 설정합니다. <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "duty_cycle": 42})</strong>를 실행하면 지정한 ID와 채널의 PWM 출력 듀티 사이클을 설정합니다. output_id 값은 시스템에 실제로 존재하는 Output ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>제어할 Output 선택</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>PWM의 duty cycle (%, 0.0 - 100.0)</td></tr></tbody></table>

### Output: On/Off/Duration

- Manufacturer: AoT
- Works with: Functions

On/Off Output을 켜기, 끄기 또는 일정 시간 동안 켜기로 설정합니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 출력을 작동시킵니다. <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "state": "on", "duration": 300})</strong>를 실행하면 지정한 ID와 채널의 출력 상태를 설정합니다. output_id 값은 시스템에 실제로 존재하는 Output ID로 바꾸는 것을 잊지 마세요. state가 on이고 duration이 설정되면, 해당 시간이 지난 후 출력이 꺼집니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>제어할 Output 선택</td></tr><tr><td>State</td><td>선택</td><td>Output을 켜거나 끔</td></tr><tr><td>Duration (Seconds)</td><td>Decimal</td><td>On이면 output을 켤 시간을 설정할 수 있습니다. 0이면 계속 켜져 있습니다.</td></tr></tbody></table>

### Output: Ramp Duty Cycle

- Manufacturer: AoT
- Works with: Functions

일정 시간에 걸쳐 PWM Output의 듀티 사이클을 한 값에서 다른 값으로 서서히 변화시킵니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 설정에 따라 PWM 출력의 듀티 사이클을 램프(점진 변경)합니다. <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "start": 42, "end": 62, "increment": 1.0, "duration": 600})</strong>를 실행하면 지정한 ID와 채널의 PWM 출력 듀티 사이클을 램프합니다. output_id 값은 시스템에 실제로 존재하는 Output ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>제어할 Output 선택</td></tr><tr><td>Duty Cycle: Start</td><td>Decimal</td><td>PWM의 duty cycle (%, 0.0 - 100.0)</td></tr><tr><td>Duty Cycle: End</td><td>Decimal
- Default Value: 50.0</td><td>PWM의 duty cycle (%, 0.0 - 100.0)</td></tr><tr><td>Increment (Duty Cycle)</td><td>Decimal
- Default Value: 1.0</td><td>Duration마다 변경할 duty cycle 양</td></tr><tr><td>Duration (Seconds)</td><td>Decimal</td><td>시작부터 끝까지 램프하는 시간.</td></tr></tbody></table>

### Output: Value

- Manufacturer: AoT
- Works with: Functions

Output에 값 보내기.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 값(value) 출력을 작동시킵니다. <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "value": 42})</strong>를 실행하면 지정한 ID와 채널의 출력으로 값을 전달합니다. output_id 값은 시스템에 실제로 존재하는 Output ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>제어할 Output 선택</td></tr><tr><td>Value</td><td>Decimal</td><td>Output에 보낼 값</td></tr></tbody></table>

### Output: Volume

- Manufacturer: AoT
- Works with: Functions

Output에 용량 분주 지시.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 용량(volume) 출력을 작동시킵니다. <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "volume": 42})</strong>를 실행하면 지정한 ID와 채널의 출력으로 용량을 전달합니다. output_id 값은 시스템에 실제로 존재하는 Output ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>제어할 Output 선택</td></tr><tr><td>Volume</td><td>Decimal</td><td>Output에 보낼 부피</td></tr></tbody></table>

### PID: Lower: Setpoint

- Manufacturer: AoT
- Works with: Functions

PID의 Setpoint 낮추기.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 PID Controller의 setpoint를 내립니다. <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong>를 실행하면 지정한 ID의 PID의 setpoint를 내립니다. pid_id 값은 시스템에 실제로 존재하는 PID ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>setpoint를 낮출 PID Controller를 선택하세요.</td></tr><tr><td>Lower Setpoint</td><td>Decimal</td><td>PID Setpoint를 낮출 양</td></tr></tbody></table>

### PID: Pause

- Manufacturer: AoT
- Works with: Functions

Pause a PID.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 PID Controller를 일시정지합니다. <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong>를 실행하면 지정한 ID의 PID Controller를 일시정지합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>일시정지할 PID Controller 선택</td></tr></tbody></table>

### PID: Raise: Setpoint

- Manufacturer: AoT
- Works with: Functions

PID의 Setpoint 올리기.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 PID Controller의 setpoint를 올립니다. <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong>를 실행하면 지정한 ID의 PID의 setpoint를 올립니다. pid_id 값은 시스템에 실제로 존재하는 PID ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>setpoint를 높일 PID Controller를 선택하세요.</td></tr><tr><td>Raise Setpoint</td><td>Decimal</td><td>PID Setpoint를 높일 양</td></tr></tbody></table>

### PID: Resume

- Manufacturer: AoT
- Works with: Functions

Resume a PID.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 PID Controller를 재개합니다. <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong>를 실행하면 지정한 ID의 PID Controller를 재개합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>재개할 PID Controller 선택</td></tr></tbody></table>

### PID: Set Method

- Manufacturer: AoT
- Works with: Functions

PID에 사용할 Method 선택.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 PID Controller를 일시정지합니다. <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "method_id": "fe8b8f41-131b-448d-ba7b-00a044d24075"})</strong>를 실행하면 지정한 ID들의 PID Controller에 Method를 설정합니다. pid_id 값은 시스템에 실제로 존재하는 PID ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Method를 적용할 PID Controller 선택</td></tr><tr><td>Method</td><td>Select Device</td><td>PID에 적용할 Method 선택</td></tr></tbody></table>

### PID: Set: Setpoint

- Manufacturer: AoT
- Works with: Functions

PID의 Setpoint를 설정합니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 선택한 PID Controller의 setpoint를 설정합니다. <strong>self.run_action("ACTION_ID", value={"setpoint": 42})</strong>를 실행하면 PID Controller의 setpoint를 설정합니다(예: 42). PID ID를 지정할 수도 있습니다(예: value={"setpoint": 42, "pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"}). pid_id 값은 시스템에 실제로 존재하는 PID ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>일시정지할 PID Controller 선택</td></tr><tr><td>Setpoint</td><td>Decimal</td><td>PID Controller에 설정할 Setpoint</td></tr></tbody></table>

### Send Email

- Manufacturer: AoT
- Works with: Functions

Send an email.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 시스템 설정의 SMTP 자격 증명으로 지정한 수신자에게 이메일을 보냅니다. 여러 수신자는 쉼표로 구분하세요. 이메일 본문은 자동 생성된 메시지가 됩니다. <strong>self.run_action("ACTION_ID", value={"email_address": ["email1@email.com", "email2@email.com"], "message": "My message"})</strong>를 실행하면 지정한 수신자에게 지정한 메시지로 이메일을 보냅니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>E-Mail Address</td><td>Text
- Default Value: email@domain.com</td><td>이메일 수신자(여러 주소는 쉼표로 구분)</td></tr></tbody></table>

### Send Email with Photo

- Manufacturer: AoT
- Works with: Functions

사진을 촬영하고 첨부하여 이메일 전송.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 사진을 찍어 시스템 설정의 SMTP 자격 증명으로 지정한 수신자에게 이메일을 보냅니다. 여러 수신자는 쉼표로 구분하세요. 이메일 본문은 자동 생성된 메시지가 됩니다. <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "email_address": ["email1@email.com", "email2@email.com"], "message": "My message"})</strong>를 실행하면 지정한 ID의 카메라로 사진을 촬영해 지정한 이메일로 메시지와 첨부 사진을 보냅니다. camera_id 값은 시스템에 실제로 존재하는 Camera ID로 바꾸는 것을 잊지 마세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>사진을 촬영할 Camera 선택</td></tr><tr><td>E-Mail Address</td><td>Text
- Default Value: email@domain.com</td><td>이메일 수신자. 여러 개는 쉼표로 구분하세요.</td></tr></tbody></table>

### System: Restart

- Manufacturer: AoT
- Works with: Functions

Restart the System

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 10초 후 시스템을 재시작합니다.


### System: Shutdown

- Manufacturer: AoT
- Works with: Functions

Shutdown the System

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 10초 후 시스템을 종료합니다.


### Webhook

- Manufacturer: AoT
- Works with: Functions

트리거되면 HTTP 요청을 보냅니다. 첫 줄에는 HTTP 메서드(GET, POST, PUT, ...) 다음에 공백과 호출할 URL이 옵니다. 이후 줄은 선택적인 "name: value" 헤더 파라미터입니다. 빈 줄 뒤에는 전송할 본문 페이로드가 옵니다. {{{message}}}는 메시지로 치환되는 자리표시자이고, {{{quoted_message}}}는 URL 안전 인코딩된 메시지입니다.

사용법: <strong>self.run_action("ACTION_ID")</strong>를 실행하면 Action이 실행됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Webhook Request</td></td><td>HTTP request to execute</td></tr></tbody></table>

