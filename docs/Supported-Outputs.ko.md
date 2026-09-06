## Built-In Outputs (System)

### PWM: MQTT Publish

- Manufacturer: AoT
- Output Types: PWM
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish a PWM value to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>호스트명</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>포트</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>연결 유지</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_4VcVsWjU</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>사용자명</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>비밀번호</td><td>Text</td><td>Password for connecting to the server.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr><tr><td>Round Integer</td><td>Select(Options: [<strong>No Rounding</strong> | Round Nearest Whole | Round Up | Round Down] (Default in <strong>bold</strong>)</td><td>Round the payload value to an integer.</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>시작 값</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>종료 값</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>신호 반전</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>저장된 신호 반전</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### 값: Actuator Paired (Shared Bus)

- Manufacturer: AoT
- Output Types: Value

열기/닫기 릴레이를 다른 액추에이터와 공유하고, 각 액추에이터가 자기 선택 릴레이로 버스를 무는 환기창·커튼·밸브의 시간 기반 개도 제어(0–100%)입니다. 6채널 릴레이 보드로 창 4개를 제어할 수 있습니다. 액추에이터마다 이 출력을 하나씩 추가하고 같은 열기/닫기 채널을 지정하면 서로 자동으로 순서가 조정됩니다. 선택 릴레이 접점은 공유 버스가 꺼진 상태에서만 개폐됩니다. 액추에이터가 전용 열기/닫기 릴레이를 가진 경우에는 "Actuator Paired"를 사용하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>액추에이터 종류</td><td>Select(Options: [<strong>측면 환기창</strong> | 지붕 환기창 | 보온 커튼 | 차광 커튼 | 볼 밸브] (Default in <strong>bold</strong>)</td><td>제어 중인 액추에이터 유형.</td></tr><tr><td>출력: 선택 릴레이</td><td>Select Channel (Output_Channels)</td><td>공유 버스를 이 액추에이터에 연결하는 on/off 출력 채널입니다. 버스가 켜지기 전에 붙고 버스가 꺼진 뒤에 떨어지므로 부하가 걸린 상태에서 개폐되지 않습니다. 이 액추에이터가 버스를 독점하는 경우에만 비워 두세요.</td></tr><tr><td>출력: 열기(공유 버스)</td><td>Select Channel (Output_Channels)</td><td>열기(OPEN) 릴레이에 연결된 on/off 출력 채널입니다. 같은 열기/닫기 채널을 지정한 액추에이터들은 하나의 버스를 공유하며 서로 순서가 조정됩니다.</td></tr><tr><td>출력: 닫기(공유 버스)</td><td>Select Channel (Output_Channels)</td><td>닫기(CLOSE) 릴레이에 연결된 on/off 출력 채널입니다. 같은 열기/닫기 채널을 지정한 액추에이터들은 하나의 버스를 공유하며 서로 순서가 조정됩니다.</td></tr><tr><td>열기 이동 시간 (초)</td><td>Decimal</td><td>완전히 닫힌 상태(0%)에서 완전히 열린 상태(100%)까지 이동하는 데 걸리는 시간(초)입니다. 설정하지 않으면 닫기 이동 시간이 대체값으로 사용됩니다. 아래 보정 버튼을 사용하면 자동으로 측정할 수 있습니다.</td></tr><tr><td>닫기 이동 시간 (초)</td><td>Decimal</td><td>완전히 열린 상태(100%)에서 완전히 닫힌 상태(0%)까지 이동하는 데 걸리는 시간(초)입니다. 설정하지 않으면 열기 이동 시간이 대체값으로 사용됩니다.</td></tr><tr><td>리밋스위치 있음</td><td>Boolean
- Default Value: True</td><td>이 액추에이터의 양 끝에 리밋스위치가 있으면 켜세요. 끝점 목표(0%, 100%)를 계산된 주행시간보다 길게 구동할 수 있게 되어, 여러 액추에이터가 한 번의 버스 운전으로 끝점에 도달합니다 — 전체 창 긴급 폐쇄가 창마다 한 번씩이 아니라 한 번에 끝납니다. 리밋스위치가 없으면 모터가 구속되므로 끄세요.</td></tr><tr><td>병렬 구동 허용</td><td>Boolean
- Default Value: True</td><td>같은 버스에서 같은 릴레이를 구동하는 다른 액추에이터와 동시에 움직이게 합니다. 버스와 전원이 해당 모터를 모두 동시에 감당할 수 있을 때만 켜세요. 반대 방향은 이 설정과 무관하게 절대 동시에 구동되지 않습니다. 같은 버스의 액추에이터 중 하나라도 이 옵션을 끄면 버스 전체가 한 번에 하나씩만 움직입니다.</td></tr><tr><td>배치 수집 시간 (초)</td><td>Decimal
- Default Value: 2.0</td><td>이 시간 안에 도착한 명령을 함께 계획합니다. 버스의 모든 액추에이터를 대상으로 하는 제어 주기가 개별 이동의 대기열이 아니라 하나의 배치가 됩니다.</td></tr><tr><td>선택 릴레이 정착 시간 (초)</td><td>Decimal
- Default Value: 0.5</td><td>선택 릴레이가 바뀐 뒤 공유 버스에 전원이 들어가기까지의 대기 시간입니다(버스가 멈춘 뒤 선택 릴레이를 떼기 전에도 동일하게 적용). 접점이 부하 상태에서 개폐되지 않게 합니다.</td></tr><tr><td>릴레이 확인 제한 시간 (초)</td><td>Decimal
- Default Value: 15.0</td><td>선택 릴레이나 버스 릴레이가 새 상태를 보고할 때까지 기다리는 시간이며, 초과하면 이 액추에이터를 포기합니다. 유선 릴레이는 즉시 확인되고, 무선 릴레이는 장치가 응답할 때 확인됩니다. 확인되지 않은 선택 릴레이 상태에서는 버스에 절대 전원을 넣지 않습니다.</td></tr><tr><td>역방향 일시정지 (초)</td><td>Decimal
- Default Value: 5.0</td><td>공유 버스가 방향을 바꿀 때(열기↔닫기) 모터 보호를 위해 삽입되는 대기 시간입니다. 새 방향이 시작되기 전까지 두 버스 릴레이가 모두 이 시간 동안 꺼진 상태를 유지합니다.</td></tr><tr><td>시작 시 릴레이 강제 차단</td><td>Boolean
- Default Value: True</td><td>데몬이 시작된 뒤, 켜짐으로 보고되는 선택·버스 릴레이를 끕니다. 주행 중 재시작하면 모터가 계속 돌 수 있기 때문입니다. 실제로 켜짐으로 보고된 릴레이에만 명령을 보내므로 토글 방식 출력이 오히려 켜지는 일은 없습니다.</td></tr><tr><td>열림 시작 위치 (%)</td><td>Decimal</td><td>참고용(정보 표시)입니다. 기구가 육안으로 열리기 시작하는 모터 위치(%)입니다. 명령값은 모터 위치로 그대로 사용되며 이 항목으로 재조정되지 않습니다.</td></tr><tr><td>완전 열림 위치 (%)</td><td>Decimal
- Default Value: 100.0</td><td>참고용(정보 표시)입니다. 완전 개방으로 간주하는 모터 위치(%)입니다. 명령값은 이 항목으로 제한되지 않습니다. 0% 명령은 이와 무관하게 물리적 끝점까지 이동합니다(긴급 완전 폐쇄).</td></tr><tr><td>최소 이동 단계 (%)</td><td>Decimal
- Default Value: 5.0</td><td>자동 환경 제어에서 모터 수명을 보호합니다. 목표가 마지막으로 보낸 위치와 최소 이만큼 차이 날 때만 모터가 움직이며, 명령은 이 격자에 맞춰집니다(예: 5% → 0, 5, 10 …). 0으로 두면 비활성화되어 미세한 변동에도 모터가 움직입니다.</td></tr><tr><td>마지막 위치 (%)</td><td>Decimal</td><td>마지막으로 알려진 위치입니다. 이동할 때마다 자동으로 업데이트되어 데몬이 재시작되어도 값이 유지됩니다. 실제 위치를 알고 있는 경우에만 수동으로 편집하세요.</td></tr><tr><td>마지막 목표값 (%)</td><td>Decimal
- Default Value: -1.0</td><td>마지막으로 수동 명령한 목표 위치입니다. -1은 설정되지 않음을 의미합니다. 수동 설정 명령마다 저장되어 데몬이 재시작되어도 목표값이 유지됩니다.</td></tr><tr><td>최소 명령 간격 (초)</td><td>Decimal
- Default Value: 1.0</td><td>직전 명령으로부터 이 시간 안에 도착한 새 목표를 거부합니다. 버튼 연타로 명령이 쌓여 모터가 급격히 반복 동작하는 것을 막습니다. 정지는 이 간격과 무관하게 항상 수락됩니다.</td></tr><tr><td>방향 반전</td><td>Boolean</td><td>소프트웨어에서 열기와 닫기 릴레이를 서로 바꿉니다. 0%가 물리적으로 액추에이터를 전개하고 100%가 되돌리는 배선일 때 켜세요. 반전된 액추에이터는 서로 반대 릴레이에 전원을 넣으므로 반전되지 않은 것과 절대 병렬로 구동되지 않습니다.</td></tr><tr><td>캘리브레이션 방향</td><td>Select(Options: [<strong>열기</strong> | 닫기] (Default in <strong>bold</strong>)</td><td>시작 클릭 → 액추에이터 이동 → 완전히 열리거나 닫히면 정지 클릭 → 경과 시간이 열기 이동 시간 또는 닫기 이동 시간에 저장됩니다.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>▶ 캘리브레이션 시작</td><td>Button</td><td></td></tr><tr><td>■ 정지 및 저장</td><td>Button</td><td></td></tr></tbody></table>

### 값: Actuator Paired

- Manufacturer: AoT
- Output Types: Value

환기창, 커튼, 볼 밸브의 시간 기반 개도 제어(0–100%)입니다. 열기 릴레이와 닫기 릴레이를 하나의 백분율 명령에 연결합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>액추에이터 종류</td><td>Select(Options: [<strong>측면 환기창</strong> | 지붕 환기창 | 보온 커튼 | 차광 커튼 | 볼 밸브] (Default in <strong>bold</strong>)</td><td>제어 중인 액추에이터 유형.</td></tr><tr><td>출력: 열기</td><td>Select Channel (Output_Channels)</td><td>열기 릴레이에 연결된 on/off 출력 채널.</td></tr><tr><td>출력: 닫기</td><td>Select Channel (Output_Channels)</td><td>닫기 릴레이에 연결된 on/off 출력 채널.</td></tr><tr><td>열기 이동 시간 (초)</td><td>Decimal</td><td>완전히 닫힌 상태(0%)에서 완전히 열린 상태(100%)까지 이동하는 데 걸리는 시간(초)입니다. 설정하지 않으면 닫기 이동 시간이 대체값으로 사용됩니다. 아래 보정 버튼을 사용하면 자동으로 측정할 수 있습니다.</td></tr><tr><td>닫기 이동 시간 (초)</td><td>Decimal</td><td>완전히 열린 상태(100%)에서 완전히 닫힌 상태(0%)까지 이동하는 데 걸리는 시간(초)입니다. 설정하지 않으면 열기 이동 시간이 대체값으로 사용됩니다.</td></tr><tr><td>열림 시작 위치 (%)</td><td>Decimal</td><td>참고용(정보 제공). 기구가 시각적으로 열리기 시작하는 모터 위치(%)입니다. 명령값은 모터 위치로 직접 사용되며 이 필드에 의해 재조정되지 않습니다 — 22% 명령은 모터 위치 22로 직접 매핑됩니다.</td></tr><tr><td>완전 열림 위치 (%)</td><td>Decimal
- Default Value: 100.0</td><td>참고용(정보 제공). 완전히 열린 것으로 간주되는 모터 위치(%)입니다. 명령값은 모터 위치로 직접 사용되며 이 필드에 의해 제한되지 않습니다. 0% 명령은 항상 물리적 끝단(비상 완전 닫힘)으로 이동합니다.</td></tr><tr><td>최소 이동 단계 (%)</td><td>Decimal
- Default Value: 5.0</td><td>자동 환경 제어를 위한 모터 수명 보호입니다. 목표값이 마지막으로 전송된 위치와 최소 이 값만큼 차이날 때만 모터가 움직이며, 명령은 이 격자에 맞춰집니다(예: 5% → 0, 5, 10 …). 이는 PI 제어기의 주기별 작은 변동을 흡수하여 모터가 매 주기마다 구동되지 않도록 합니다. 비활성화하려면 0으로 설정하세요 — 그러면 사소한 변동마다 모터가 구동됩니다(기존 동작).</td></tr><tr><td>마지막 위치 (%)</td><td>Decimal</td><td>마지막으로 알려진 위치입니다. 이동할 때마다 자동으로 업데이트되어 데몬이 재시작되어도 값이 유지됩니다. 실제 위치를 알고 있는 경우에만 수동으로 편집하세요.</td></tr><tr><td>마지막 목표값 (%)</td><td>Decimal
- Default Value: -1.0</td><td>마지막으로 수동 명령한 목표 위치입니다. -1은 설정되지 않음을 의미합니다. 수동 설정 명령마다 저장되어 데몬이 재시작되어도 목표값이 유지됩니다.</td></tr><tr><td>최소 명령 간격 (초)</td><td>Decimal
- Default Value: 1.0</td><td>이전 명령으로부터 이 시간(초) 이내에 도착하는 새로운 열기/닫기 명령을 거부합니다. 빠른 버튼 연타로 인한 모터 명령 누적과 급격한 반전을 방지합니다. 정지 명령은 이 간격과 관계없이 항상 수락됩니다.</td></tr><tr><td>역방향 일시정지 (초)</td><td>Decimal
- Default Value: 5.0</td><td>방향을 반전(열기↔닫기)할 때 모터를 보호하기 위해 삽입되는 정지 시간입니다. 새 방향이 시작되기 전 이 시간(초) 동안 두 릴레이가 모두 OFF 상태를 유지합니다.</td></tr><tr><td>방향 반전</td><td>Boolean</td><td>소프트웨어에서 열기 릴레이와 닫기 릴레이를 서로 바꿉니다. 0%에서 액추에이터가 물리적으로 펼쳐지고 100%에서 다시 접히는 경우 활성화하세요(예: 닫기 = 펼침으로 배선된 보온 커튼).</td></tr><tr><td>캘리브레이션 방향</td><td>Select(Options: [<strong>열기</strong> | 닫기] (Default in <strong>bold</strong>)</td><td>시작 클릭 → 액추에이터 이동 → 완전히 열리거나 닫히면 정지 클릭 → 경과 시간이 열기 이동 시간 또는 닫기 이동 시간에 저장됩니다.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>▶ 캘리브레이션 시작</td><td>Button</td><td></td></tr><tr><td>■ 정지 및 저장</td><td>Button</td><td></td></tr></tbody></table>

### 값: MQTT Publish

- Manufacturer: AoT
- Output Types: Value
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish a value to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>호스트명</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>포트</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>연결 유지</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_CMaHNYP4</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>꺼짐 값</td><td>Integer</td><td>The value to send when an Off command is given</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>사용자명</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>비밀번호</td><td>Text</td><td>Password for connecting to the server.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### 끄기: MQTT Publish Multi

- Manufacturer: AoT
- Interfaces: IP
- Output Types: On/Off
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish "on"/"off" payloads to a control topic for multiple channels, and subscribe to a status topic to reflect each channel's actual operating state. All channels share the same broker connection and the two topics. Each channel sends its own control payload and matches its own status payload values. Increase the channel count and save to add channels.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>채널 수</td><td>Integer
- Default Value: 1</td><td>Number of channels. Save to add or remove channel rows.</td></tr><tr><td>호스트명</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>포트</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>제어 토픽</td><td>Text
- Default Value: paho/test/control</td><td>The MQTT topic used to publish on/off commands (control direction).</td></tr><tr><td>상태 토픽</td><td>Text
- Default Value: paho/test/status</td><td>The MQTT topic to subscribe to for confirming each channel's operating state. Leave blank to disable status feedback.</td></tr><tr><td>연결 유지</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_iAERpBfD</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>사용자명</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>비밀번호</td><td>Text</td><td>Password for connecting to the server. Leave blank to disable.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr><tr><td>명령 제한 시간 (초)</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>채널 이름</td><td>Text</td><td>A friendly name shown in the UI for this channel.</td></tr><tr><td>On 페이로드 (제어)</td><td>Text
- Default Value: on</td><td>The payload published to the Control Topic to turn this channel ON.</td></tr><tr><td>Off 페이로드 (제어)</td><td>Text
- Default Value: off</td><td>The payload published to the Control Topic to turn this channel OFF.</td></tr><tr><td>On 페이로드 (상태)</td><td>Text</td><td>When this exact value is received on the Status Topic, the channel is marked ON. Leave blank to disable ON detection for this channel.</td></tr><tr><td>Off 페이로드 (상태)</td><td>Text</td><td>When this exact value is received on the Status Topic, the channel is marked OFF. Leave blank to disable OFF detection for this channel.</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the channel state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the channel state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the channel switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: MQTT Publish

- Manufacturer: AoT
- Interfaces: IP
- Output Types: On/Off
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish "on" or "off" (or any other strings of your choosing) to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>호스트명</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>포트</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>연결 유지</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_KUkvzjtt</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>켜기 페이로드</td><td>Text
- Default Value: on</td><td>The payload to send when turned on</td></tr><tr><td>끄기 페이로드</td><td>Text
- Default Value: off</td><td>The payload to send when turned off</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>사용자명</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>비밀번호</td><td>Text</td><td>Password for connecting to the server. Leave blank to disable.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

## Built-In Outputs (Devices)

### On/Off: ChirpStack gRPC

- Interfaces: API
- Output Types: On/Off
- Libraries: requests, paho-mqtt, grpcio (optional)
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Sends on/off downlink commands via ChirpStack REST/gRPC API. Attempts gRPC first; falls back to REST (/api/devices/<devEui>/queue) if grpcio/chirpstack-api is not installed or unreachable.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ChirpStack gRPC Server</td><td>Text
- Default Value: 127.0.0.1:8080</td><td>Host:port format (e.g., 127.0.0.1:8080) or http(s)://host:port</td></tr><tr><td>API Key</td><td>Text</td><td>Enter the JWT token value (without Bearer prefix)</td></tr><tr><td>DevEUI</td><td>Text</td><td>16-digit hexadecimal DevEUI (separators allowed)</td></tr><tr><td>FPort</td><td>Integer
- Default Value: 15</td><td>명령을 수신할 LoRaWAN FPort</td></tr><tr><td>Confirmed</td><td>Boolean</td><td>Send command as confirmed (await acknowledgment)</td></tr><tr><td>Payload Format</td><td>Select(Options: [<strong>Hex Bytes</strong> | JSON Object (UTF-8 encoded)] (Default in <strong>bold</strong>)</td><td>Select the payload encoding format</td></tr><tr><td>On Payload</td><td>Text
- Default Value: 000000</td><td>e.g., 010110 (Hex) or JSON string</td></tr><tr><td>Off Payload</td><td>Text
- Default Value: 000000</td><td>e.g., 010210 (Hex) or JSON string</td></tr><tr><td>Enable Debug Logging</td><td>Boolean</td><td>Log connection/enqueue/confirmation notices (INFO/WARNING) for this device. Errors are always logged. Leave off in production.</td></tr><tr><td>명령 제한 시간 (초)</td><td>Text
- Default Value: 8</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Startup State</td><td>Select</td><td>State to apply when AoT starts</td></tr><tr><td>Shutdown State</td><td>Select</td><td>State to apply when AoT shuts down</td></tr><tr><td>Force Command</td><td>Boolean</td><td>Always send command regardless of current state</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>Execute trigger function when output switches at startup</td></tr></tbody></table>

### PWM: PCA9685 16-Channel LED 컨트롤러

- Manufacturer: NXP Semiconductors
- Interfaces: I<sup>2</sup>C
- Output Types: PWM
- Libraries: adafruit-pca9685
- Dependencies: [adafruit-pca9685](https://pypi.org/project/adafruit-pca9685)
- Manufacturer URL: [Link](https://www.nxp.com/products/power-management/lighting-driver-and-controller-ics/ic-led-controllers/16-channel-12-bit-pwm-fm-plus-ic-bus-led-controller:PCA9685)
- Datasheet URL: [Link](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf)
- Product URL: [Link](https://www.adafruit.com/product/815)

The PCA9685 can output a PWM signal to 16 channels at a frequency between 40 and 1600 Hz.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>주파수 (헤르츠)</td><td>Integer
- Default Value: 1600</td><td>The Herts to output the PWM signal (40 - 1600)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>시작 값</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>종료 값</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>신호 반전</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>저장된 신호 반전</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### PWM: Python 3 Code

- Interfaces: Python
- Output Types: PWM
- Dependencies: [pylint](https://pypi.org/project/pylint)

Python 3 code will be executed when this output is turned on or off. The "duty_cycle" object is a float value that represents the duty cycle that has been set.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>Analyze your Python code with pylint when saving</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Python 3 Code</td></td><td>Python code to execute to set the PWM duty cycle (%)</td></tr><tr><td>사용자</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>시작 값</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>종료 값</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>신호 반전</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>저장된 신호 반전</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: PWM
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

A software implementation of PWM using the RPi.GPIO library.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>핀: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>시작 값</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>종료 값</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>주파수 (헤르츠)</td><td>Integer
- Default Value: 1000</td><td>The Hertz to output the PWM signal</td></tr><tr><td>신호 반전</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>저장된 신호 반전</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: PWM
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)

See the PWM section of the manual for PWM information and determining which pins may be used for each library option.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>핀: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>시작 값</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>종료 값</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>라이브러리</td><td>Select(Options: [<strong>Any Pin, <= 40 kHz</strong> | Hardware Pin, <= 30 MHz] (Default in <strong>bold</strong>)</td><td>Which method to produce the PWM signal (hardware pins can produce higher frequencies)</td></tr><tr><td>주파수 (헤르츠)</td><td>Integer
- Default Value: 22000</td><td>The Herts to output the PWM signal (0 - 70,000)</td></tr><tr><td>신호 반전</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>저장된 신호 반전</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Shell Script

- Interfaces: Shell
- Output Types: PWM
- Libraries: subprocess.Popen

Commands will be executed in the Linux shell by the specified user when the duty cycle is set for this output. The string "((duty_cycle))" in the command will be replaced with the duty cycle being set prior to execution.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Bash 명령어</td><td>Text
- Default Value: /home/pi/script_pwm.sh ((duty_cycle))</td><td>PWM 듀티 사이클 (%)을 설정하기 위해 실행할 명령</td></tr><tr><td>사용자</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>시작 상태</td><td>Select</td><td>AoT가 시작될 때 출력의 상태</td></tr><tr><td>시작 값</td><td>Decimal</td><td>AoT가 시작될 때의 값</td></tr><tr><td>종료 상태</td><td>Select</td><td>AoT가 종료될 때 출력의 상태</td></tr><tr><td>종료 값</td><td>Decimal</td><td>AoT가 종료될 때의 값</td></tr><tr><td>신호 반전</td><td>Boolean</td><td>PWM 신호 반전</td></tr><tr><td>저장된 신호 반전</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>항상 명령을 보냅니다. 현재 상태에 관계없이</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>출력이 제어하는 장비의 전류 소비량</td></tr></tbody></table>

### 값: GP8XXX (8413, 8403) 2-Channel DAC: 0-10 VDC

- Manufacturer: DFRobot
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Libraries: GP8XXX-IIC
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [GP8XXX-IIC](https://pypi.org/project/GP8XXX-IIC)
- Datasheet URLs: [Link 1](https://wiki.dfrobot.com/SKU_DFR0971_2_Channel_I2C_0_10V_DAC_Module), [Link 2](https://wiki.dfrobot.com/SKU_DFR1073_2_Channel_15bit_I2C_to_0-10V_DAC)
- Product URLs: [Link 1](https://www.dfrobot.com/product-2613.html), [Link 2](https://www.dfrobot.com/product-2756.html)

Output 0 to 10 VDC signal.                GP8403: 12bit DAC Dual Channel I2C to 0-5V/0-10V |                GP8413: 15bit DAC Dual Channel I2C to 0-10V
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Device</td><td>Select(Options: [<strong>GP8403 12-bit</strong> | GP8413 15-bit] (Default in <strong>bold</strong>)</td><td>Select your GP8XXX device</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Start State</td><td>Select(Options: [Previously-Saved State | <strong>Specified Value</strong>] (Default in <strong>bold</strong>)</td><td>Select the channel start state</td></tr><tr><td>Start Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the start state value</td></tr><tr><td>Shutdown State</td><td>Select(Options: [Previously-Saved Value | <strong>Specified Value</strong>] (Default in <strong>bold</strong>)</td><td>Select the channel shutdown state</td></tr><tr><td>Shutdown Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the shutdown state value</td></tr><tr><td>Off Value (volts)</td><td>Decimal</td><td>If Specified Value to apply when turned off</td></tr></tbody></table>

### 끄기 (Virtual Multi-Channel)

- Output Types: On/Off
- Libraries: Internal

A virtual output device for testing. States are stored in memory and have no effect on hardware.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the virtual device</td></tr></tbody></table>

### 끄기 (Virtual Single-Channel)

- Output Types: On/Off
- Libraries: Internal

A single-channel virtual output device for testing. State is stored in memory and has no effect on hardware.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the virtual device</td></tr></tbody></table>

### 끄기: 52pi EP-0099 4channel Relay (4-Channel board)

- Manufacturer: 52Pi
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)

Controls the 4 channel multichannel relay board.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the relay when aot starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the relay when aot shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Ecowitt Local HTTP

- Interfaces: IP
- Output Types: On/Off
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

Ecowitt 허브 IP, 서브디바이스 ID, 모델(WFC01/02=1, WFC02 신펌=3, AC1100=2)을 입력하면 로컬 HTTP API로 On/Off 제어합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Ecowitt Device IP</td><td>Text</td><td>Local IP address of the Ecowitt hub (e.g., 192.168.1.100)</td></tr><tr><td>Ecowitt Sub-device ID</td><td>Text</td><td>ID of WFC01/WFC02/AC1100 (e.g., 11044)</td></tr><tr><td>Ecowitt Device Model</td><td>Select(Options: [WFC01 | <strong>WFC02</strong> | AC1100] (Default in <strong>bold</strong>)</td><td>1=WFC01/대부분 WFC02, 3=일부 WFC02(신펌), 2=AC1100</td></tr><tr><td>Valve Open %</td><td>Integer
- Default Value: 100</td><td>When turning on, open valve to this percent (0-100)</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 60</td><td>How often to query the state of the output</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr></tbody></table>

### 끄기: Grove Multichannel Relay (4- or 8-Channel board)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.seeedstudio.com/Grove-4-Channel-SPDT-Relay-p-3119.html)
- Datasheet URL: [Link](http://wiki.seeedstudio.com/Grove-4-Channel_SPDT_Relay/)
- Product URL: [Link](https://www.seeedstudio.com/Grove-4-Channel-SPDT-Relay-p-3119.html)

Controls the 4 or 8 channel Grove multichannel relay board.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the relay when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the relay when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Kasa HS300 6-Outlet WiFi Power Strip (old library, deprecated)

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-wi-fi-power-strip-hs300)

This output controls the 6 outlets of the Kasa HS300 Smart WiFi Power Strip. This module uses an outdated python library and is deprecated. Do not use it. You will break the current Kasa modules if you do not delete this deprecated Output.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>호스트</td><td>Text
- Default Value: 192.168.0.50</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 60</td><td>The period between checking if connected and output states.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Kasa HS300 6-Outlet WiFi Power Strip

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-wi-fi-power-strip-hs300)

This output controls the 6 outlets of the Kasa HS300 Smart WiFi Power Strip. This is a variant that uses the latest python-kasa library. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>호스트</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18079</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Kasa KP303 3-Outlet WiFi Power Strip (old library, deprecated)

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa)
- Manufacturer URL: [Link](https://www.tp-link.com/au/home-networking/smart-plug/kp303/)

This output controls the 3 outlets of the Kasa KP303 Smart WiFi Power Strip. This module uses an outdated python library and is deprecated. Do not use it. You will break the current Kasa modules if you do not delete this deprecated Output.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>호스트</td><td>Text
- Default Value: 192.168.0.50</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 60</td><td>The period between checking if connected and output states.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Kasa KP303 3-Outlet WiFi Power Strip

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.tp-link.com/au/home-networking/smart-plug/kp303/)

This output controls the 3 outlets of the Kasa KP303 Smart WiFi Power Strip. This is a variant that uses the latest python-kasa library. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>호스트</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18479</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text
- Default Value: Outlet Name</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Kasa WiFi Power Plug

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-plug-slim-energy-monitoring-kp115)

This output controls Kasa WiFi Power Plugs, including the KP105, KP115, KP125, KP401, HS100, HS103, HS105, HS107, and HS110. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>호스트</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18233</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td>명령 제한 시간 (초)</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Kasa WiFi RGB Light Bulb

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-lighting/kasa-smart-light-bulb-multicolor-kl125)

This output controls the the Kasa WiFi Light Bulbs, including the KL125, KL130, and KL135. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>호스트</td><td>Text
- Default Value: 0.0.0.0</td><td>호스트 또는 IP 주소</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18012</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Transition (밀리초)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>밝기 (퍼센트)</td><td>Integer</td><td>The brightness to set, in percent (0 - 100)</td></tr><tr><td>설정</td><td>Button</td><td></td></tr><tr><td>Transition (밀리초)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>색상 (도)</td><td>Integer</td><td>The hue to set, in degrees (0 - 360)</td></tr><tr><td>설정</td><td>Button</td><td></td></tr><tr><td>Transition (밀리초)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>색상 (퍼센트)</td><td>Integer</td><td>The saturation to set, in percent (0 - 100)</td></tr><tr><td>설정</td><td>Button</td><td></td></tr><tr><td>Transition (밀리초)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>색온도 (켈빈)</td><td>Integer</td><td>The color temperature to set, in degrees Kelvin</td></tr><tr><td>설정</td><td>Button</td><td></td></tr><tr><td>Transition (밀리초)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>HSV</td><td>Text
- Default Value: 220, 20, 45</td><td>The hue, saturation, brightness to set, e.g. "200, 20, 50"</td></tr><tr><td>설정</td><td>Button</td><td></td></tr><tr><td>Transition (밀리초)</td><td>Integer
- Default Value: 1000</td><td>The transition period</td></tr><tr><td>켜기</td><td>Button</td><td></td></tr><tr><td>Transition (밀리초)</td><td>Integer
- Default Value: 1000</td><td>The transition period</td></tr><tr><td>끄기</td><td>Button</td><td></td></tr></tbody></table>

### 끄기: MCP23017 16-Channel I/O 확장기

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Dependencies: [swig](https://packages.debian.org/search?keywords=swig), [liblgpio-dev](https://packages.debian.org/search?keywords=liblgpio-dev), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp230xx](https://pypi.org/project/adafruit-circuitpython-mcp230xx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/MCP23017)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/devicedoc/20001952c.pdf)
- Product URL: [Link](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG)

Controls the 16 channels of the MCP23017.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Modbus TCP Coil (PLC)

- Manufacturer: Modbus
- Interfaces: IP
- Output Types: On/Off
- Libraries: pymodbus
- Dependencies: [pymodbus](https://pypi.org/project/pymodbus)

Modbus TCP 장치(PLC, 릴레이 보드, 게이트웨이)의 코일을 제어합니다. 채널 하나가 코일 주소 하나입니다. 명령을 보낼 때마다 코일을 다시 읽어 실제로 바뀌었는지 확인하며, 값이 다르면 실패로 알립니다. 같은 호스트와 포트를 가리키는 입력·출력은 자동으로 하나의 연결을 공유합니다. 재조회는 PLC 레지스터를 확인할 뿐, 릴레이나 배선이 움직였는지는 확인하지 못합니다. Modbus에는 인증도 암호화도 없으므로 장치는 격리된 네트워크에 두십시오.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>채널 수</td><td>Integer
- Default Value: 1</td><td>제어할 코일 개수. 저장하면 채널 행이 추가되거나 제거됩니다.</td></tr><tr><td>호스트</td><td>Text</td><td>Modbus TCP 장치의 IP 주소 또는 호스트 이름</td></tr><tr><td>포트</td><td>Integer
- Default Value: 502</td><td>Modbus TCP 장치의 TCP 포트 (표준: 502)</td></tr><tr><td>단위 ID</td><td>Integer
- Default Value: 1</td><td>장치의 Modbus 유닛/슬레이브 ID. 장치를 직접 지정할 때는 보통 1이며, 시리얼 게이트웨이 뒤에 있으면 그 슬레이브 주소입니다</td></tr><tr><td>타임아웃 (초)</td><td>Decimal
- Default Value: 1.0</td><td>응답을 기다리는 시간. 요청 1회는 최대 타임아웃 x (재시도 + 1) 만큼 걸리며, 명령 하나는 요청을 두 번 보냅니다</td></tr><tr><td>재시도</td><td>Integer
- Default Value: 1</td><td>실패로 처리하기 전까지 요청당 재시도 횟수. 낮게 유지하십시오 — 값이 크면 응답 없는 장치가 명령을 붙잡는 시간이 그만큼 배로 늘어납니다</td></tr><tr><td>명령 제한 시간 (초)</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>채널 이름</td><td>Text</td><td>이 채널을 화면에 표시할 이름입니다.</td></tr><tr><td>코일 주소</td><td>Integer</td><td>제어할 코일의 0부터 세는 주소. 벤더 문서는 1부터 세는 주소를 쓰는 경우가 많으므로(예: coil 0을 00001로 표기) 레지스터 맵과 대조하십시오</td></tr><tr><td>시작 상태</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>AoT가 시작될 때 채널 상태를 설정합니다. "아무것도 안 함"은 PLC가 가진 코일 상태를 그대로 두고 읽어오기만 합니다</td></tr><tr><td>종료 상태</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>AoT가 종료될 때 채널 상태를 설정합니다</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>시작 시 채널이 전환될 때 함수를 실행할지 여부</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>항상 명령을 보냅니다. 현재 상태에 관계없이</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>출력이 제어하는 장비의 전류 소비량</td></tr></tbody></table>

### 끄기: Neopixel (WS2812) RGB Strip with Raspberry Pi

- Manufacturer: Worldsemi
- Interfaces: GPIO
- Output Types: On/Off
- Dependencies: Output Variant 1: [adafruit-circuitpython-neopixel](https://pypi.org/project/adafruit-circuitpython-neopixel); Output Variant 2: [adafruit-circuitpython-neopixel-spi](https://pypi.org/project/adafruit-circuitpython-neopixel-spi)

Control the LEDs of a neopixel light strip. USE WITH CAUTION: This library uses the Hardware-PWM0 bus. Only GPIO pins 12 or 18 will work. If you use one of these pins for a NeoPixel strip, you can not use the other for Hardware-PWM control of another output or there will be conflicts that can cause the AoT Daemon to crash and the Pi to become unresponsive. If you need to control another PWM output like a servo, fan, or dimmable grow lights, you will need to use the Software-PWM by setting the Output PWM: Raspberry Pi GPIO and set the "Library" field to "Any Pin, <=40kHz". If you select the "Hardware Pin, <=30MHz" option, it will cause conflicts. This output is best used with Actions to control individual LED color and brightness.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Data Pin</td><td>Integer
- Default Value: 18</td><td>Enter the GPIO Pin connected to your device data wire (BCM numbering).</td></tr><tr><td>Number of LEDs</td><td>Integer
- Default Value: 1</td><td>How many LEDs in the string?</td></tr><tr><td>On Mode</td><td>Select(Options: [<strong>Single Color</strong> | Rainbow] (Default in <strong>bold</strong>)</td><td>The color mode when turned on</td></tr><tr><td>Single Color</td><td>Text
- Default Value: 30, 30, 30</td><td>The Color when turning on in Single Color Mode, RGB format (red, green, blue), 0 - 255 each.</td></tr><tr><td>Rainbow Speed (Seconds)</td><td>Decimal
- Default Value: 0.01</td><td>The speed to change colors in Rainbow Mode</td></tr><tr><td>Rainbow Brightness</td><td>Integer
- Default Value: 20</td><td>The maximum brightness of LEDs in Rainbow Mode (1 - 255)</td></tr><tr><td>Rainbow Mode</td><td>Select(Options: [All LEDs change at once | <strong>One LED Changes at a time</strong>] (Default in <strong>bold</strong>)</td><td>How the rainbow is displayed</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>LED Position</td><td>Integer</td><td>Which LED in the strip to change</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color (e.g 10, 0, 0)</td></tr><tr><td>설정</td><td>Button</td><td></td></tr></tbody></table>

### 끄기: PCF8574 8-Channel I/O 확장기

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8574)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8574.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

Controls the 8 channels of the PCF8574.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: PCF8575 16-Channel I/O 확장기

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8575)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8575.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

Controls the 16 channels of the PCF8575.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Python Code

- Interfaces: Python
- Output Types: On/Off
- Dependencies: [pylint](https://pypi.org/project/pylint)

Python 3 code will be executed when this output is turned on or off.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>Analyze your Python code with pylint when saving</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>켜기 명령</td></td><td>출력이 켜짐 상태가 되면 실행할 파이썬 코드</td></tr><tr><td>끄기 명령</td></td><td>출력이 꺼짐 상태가 되면 실행할 파이썬 코드</td></tr><tr><td>시작 상태</td><td>Select</td><td>AoT가 시작될 때 출력의 상태</td></tr><tr><td>종료 상태</td><td>Select</td><td>AoT가 종료될 때 출력의 상태</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>시작 시 작동 함수</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>항상 명령을 보냅니다. 현재 상태에 관계없이</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>출력이 제어하는 장비의 전류 소비량</td></tr></tbody></table>

### 끄기: Raspberry Pi GPIO (Pi 5)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: pinctrl

The specified GPIO pin will be set HIGH (3.3 volts) or LOW (0 volts) when turned on or off, depending on the On State option.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>핀: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

The specified GPIO pin will be set HIGH (3.3 volts) or LOW (0 volts) when turned on or off, depending on the On State option.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>핀: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Sequent Microsystems 8-Relay HAT for Raspberry Pi

- Manufacturer: Sequent Microsystems
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://sequentmicrosystems.com)
- Datasheet URL: [Link](https://cdn.shopify.com/s/files/1/0534/4392/0067/files/8-RELAYS-UsersGuide.pdf?v=1642820552)
- Product URL: [Link](https://sequentmicrosystems.com/products/8-relays-stackable-card-for-raspberry-pi)

Controls the 8 relays of the 8-relay HAT made by Sequent Microsystems. 8 of these boards can be used simultaneously, allowing 64 relays to be controlled.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Board Stack Number</td><td>Select</td><td>Select the board stack number when multiple boards are used</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Shell Script

- Output Types: On/Off
- Libraries: subprocess.Popen

Commands will be executed in the Linux shell by the specified user when this output is turned on or off.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>켜기 명령</td><td>Text
- Default Value: /home/pi/script_on_off.sh on</td><td>Command to execute when the output is instructed to turn on</td></tr><tr><td>끄기 명령</td><td>Text
- Default Value: /home/pi/script_on_off.sh off</td><td>Command to execute when the output is instructed to turn off</td></tr><tr><td>사용자</td><td>Text
- Default Value: aot</td><td>명령을 실행할 사용자</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: Sparkfun Relay Board (4 Relays)

- Manufacturer: Sparkfun
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: sparkfun-qwiic-relay
- Dependencies: [sparkfun-qwiic-relay](https://pypi.org/project/sparkfun-qwiic-relay)
- Manufacturer URL: [Link](https://www.sparkfun.com)
- Product URLs: [Link 1](https://www.sparkfun.com/products/16833), [Link 2](https://www.sparkfun.com/products/16566)

Controls the 4 relays of the relay module.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: XL9535 16-Channel I/O 확장기

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link]()
- Datasheet URL: [Link]()
- Product URL: [Link]()

Controls the 16 channels of the XL9535.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 끄기: 무선 315/433 MHz (Pi <= 4)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: rpi-rf
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO), [rpi_rf](https://pypi.org/project/rpi_rf)

This output uses a 315 or 433 MHz transmitter to turn wireless power outlets on or off. Run /opt/AoT/aot/devices/wireless_rpi_rf.py with a receiver to discover the codes produced from your remote.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>핀: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>켜기 명령</td><td>Text
- Default Value: 22559</td><td>출력이 켜지도록 지시되었을 때 실행할 명령</td></tr><tr><td>끄기 명령</td><td>Text
- Default Value: 22558</td><td>출력이 꺼지도록 지시되었을 때 실행할 명령</td></tr><tr><td>프로토콜</td><td>Select(Options: [<strong>1</strong> | 2 | 3 | 4 | 5] (Default in <strong>bold</strong>)</td><td></td></tr><tr><td>펄스 길이</td><td>Integer
- Default Value: 189</td><td></td></tr><tr><td>시작 상태</td><td>Select</td><td>AoT가 시작될 때 출력의 상태</td></tr><tr><td>종료 상태</td><td>Select</td><td>AoT가 종료될 때 출력의 상태</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>시작 시 작동 함수</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>현재 상태와 상관없이 항상 명령을 전송</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>출력이 제어하는 장비의 전류 소비량</td></tr></tbody></table>

### 디지털 포텐시미터: DS3502

- Manufacturer: Maxim Integrated
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit_Extended_Bus](https://pypi.org/project/Adafruit_Extended_Bus), [adafruit-circuitpython-ds3502](https://pypi.org/project/adafruit-circuitpython-ds3502)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/analog/data-converters/digital-potentiometers/DS3502.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS3502.pdf)
- Product URL: [Link](https://www.adafruit.com/product/4286)

The DS3502 can generate a 0 - 10k Ohm resistance with 7-bit precision. This equates to 128 possible steps. A value, in Ohms, is passed to this output controller and the step value is calculated and passed to the device. Select whether to round up or down to the nearest step.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Round Step</td><td>Select(Options: [<strong>Up</strong> | Down] (Default in <strong>bold</strong>)</td><td>Round direction to the nearest step value</td></tr></tbody></table>

### 디지털-아날로그 변환기: MCP4728

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp4728](https://pypi.org/project/adafruit-circuitpython-mcp4728)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en541737)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/DeviceDoc/22187E.pdf)
- Product URL: [Link](https://www.adafruit.com/product/4470)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 4.096</td><td>Set the VREF voltage</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>VREF</td><td>Select(Options: [<strong>Internal</strong> | VDD] (Default in <strong>bold</strong>)</td><td>Select the channel VREF</td></tr><tr><td>Gain</td><td>Select(Options: [<strong>1X</strong> | 2X] (Default in <strong>bold</strong>)</td><td>Select the channel Gain</td></tr><tr><td>Start State</td><td>Select(Options: [<strong>Previously-Saved State</strong> | Specified Value] (Default in <strong>bold</strong>)</td><td>Select the channel start state</td></tr><tr><td>Start Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the start state value</td></tr><tr><td>Shutdown State</td><td>Select(Options: [<strong>Previously-Saved Value</strong> | Specified Value] (Default in <strong>bold</strong>)</td><td>Select the channel shutdown state</td></tr><tr><td>Shutdown Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the shutdown state value</td></tr></tbody></table>

### 모터: ULN2003 스텝 모터, 일반 (Pi <= 4)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Value
- Libraries: RPi.GPIO, rpimotorlib
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO), [rpimotorlib](https://pypi.org/project/rpimotorlib)
- Manufacturer URL: [Link](https://www.ti.com/product/ULN2003A)
- Datasheet URLs: [Link 1](https://www.electronicoscaldas.com/datasheet/ULN2003A-PCB.pdf), [Link 2](https://www.ti.com/lit/ds/symlink/uln2003a.pdf?ts=1617254568263&ref_url=https%253A%252F%252Fwww.ti.com%252Fproduct%252FULN2003A)

This is a module for the ULN2003 driver.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td colspan="3">Notes about connecting the ULN2003...</td></tr><tr><td>Pin IN1</td><td>Integer
- Default Value: 18</td><td>The pin (BCM numbering) connected to IN1 of the ULN2003</td></tr><tr><td>Pin IN2</td><td>Integer
- Default Value: 23</td><td>The pin (BCM numbering) connected to IN2 of the ULN2003</td></tr><tr><td>Pin IN3</td><td>Integer
- Default Value: 24</td><td>The pin (BCM numbering) connected to IN3 of the ULN2003</td></tr><tr><td>Pin IN4</td><td>Integer
- Default Value: 25</td><td>The pin (BCM numbering) connected to IN4 of the ULN2003</td></tr><tr><td>Step Delay</td><td>Decimal
- Default Value: 0.001</td><td>The Step Delay of the controller</td></tr><tr><td colspan="3">Notes about step resolution...</td></tr><tr><td>Step Resolution</td><td>Select(Options: [<strong>Full</strong> | Half | Wave] (Default in <strong>bold</strong>)</td><td>The Step Resolution of the controller</td></tr></tbody></table>

### 모터: 스텝 모터, 양극 (일반) (Pi <= 4)

- Interfaces: GPIO
- Output Types: Value
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URLs: [Link 1](https://www.ti.com/product/DRV8825), [Link 2](https://www.allegromicro.com/en/products/motor-drivers/brush-dc-motor-drivers/a4988)
- Datasheet URLs: [Link 1](https://www.ti.com/lit/ds/symlink/drv8825.pdf), [Link 2](https://www.allegromicro.com/-/media/files/datasheets/a4988-datasheet.ashx)
- Product URLs: [Link 1](https://www.pololu.com/product/2133), [Link 2](https://www.pololu.com/product/1182)

This is a generic module for bipolar stepper motor drivers such as the DRV8825, A4988, and others. The value passed to the output is the number of steps. A positive value turns clockwise and a negative value turns counter-clockwise.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td colspan="3">If the Direction or Enable pins are not used, make sure you pull the appropriate pins on your driver high or low to set the proper direction and enable the stepper motor to be energized. Note: For Enable Mode, always having the motor energized will use more energy and produce more heat.</td></tr><tr><td>Step Pin</td><td>Integer</td><td>The Step pin of the controller (BCM numbering)</td></tr><tr><td>Full Step Delay</td><td>Decimal
- Default Value: 0.005</td><td>The Full Step Delay of the controller</td></tr><tr><td>Direction Pin</td><td>Integer</td><td>The Direction pin of the controller (BCM numbering). 비활성화하려면 None으로 설정</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>The Enable pin of the controller (BCM numbering). 비활성화하려면 None으로 설정</td></tr><tr><td>Enable Mode</td><td>Select(Options: [<strong>Only When Turning</strong> | Always] (Default in <strong>bold</strong>)</td><td>Choose when to pull the enable pin high to energize the motor.</td></tr><tr><td>Enable at Shutdown</td><td>Select(Options: [Enable | <strong>Disable</strong>] (Default in <strong>bold</strong>)</td><td>Choose whether the enable pin in pulled high (Enable) or low (Disable) when AoT shuts down.</td></tr><tr><td colspan="3">If using a Step Resolution other than Full, and all three Mode Pins are set, they will be set high (1) or how (0) according to the values in parentheses to the right of the selected Step Resolution, e.g. (Mode Pin 1, Mode Pin 2, Mode Pin 3).</td></tr><tr><td>Step Resolution</td><td>Select(Options: [<strong>Full (modes 0, 0, 0)</strong> | Half (modes 1, 0, 0) | 1/4 (modes 0, 1, 0) | 1/8 (modes 1, 1, 0) | 1/16 (modes 0, 0, 1) | 1/32 (modes 1, 0, 1)] (Default in <strong>bold</strong>)</td><td>The Step Resolution of the controller</td></tr><tr><td>Mode Pin 1</td><td>Integer</td><td>The Mode Pin 1 of the controller (BCM numbering). 비활성화하려면 None으로 설정</td></tr><tr><td>Mode Pin 2</td><td>Integer</td><td>The Mode Pin 2 of the controller (BCM numbering). 비활성화하려면 None으로 설정</td></tr><tr><td>Mode Pin 3</td><td>Integer</td><td>The Mode Pin 3 of the controller (BCM numbering). 비활성화하려면 None으로 설정</td></tr></tbody></table>

### 스페이서


A spacer to organize Outputs.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>색상</td><td>Text
- Default Value: #000000</td><td>The color of the name text</td></tr></tbody></table>

### 원격 AoT Output: PWM

- Interfaces: API
- Output Types: PWM
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

This Output allows remote control of another AoT PWM Output over a network using the API.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Remote AoT Host</td><td>Text</td><td>원격 AoT의 호스트 또는 IP 주소 (포트를 포함할 수 있습니다. 예: 192.168.0.9:8084)</td></tr><tr><td>Remote AoT API Key</td><td>Text</td><td>원격 AoT의 API 키. 그 서버에 표시된 값을 그대로 입력합니다</td></tr><tr><td>프로토콜</td><td>Select(Options: [<strong>HTTPS</strong> | HTTP] (Default in <strong>bold</strong>)</td><td>신뢰할 수 있는 망에서 평문 HTTP로만 접근되는 경우가 아니라면 HTTPS를 사용하세요</td></tr><tr><td>TLS 인증서 검증</td><td>Boolean
- Default Value: True</td><td>원격 서버의 인증서를 검증합니다. 신뢰할 수 있는 망의 자체 서명 인증서일 때만 끄세요 — 꺼 두는 동안에는 중간자가 API 키를 읽을 수 있습니다</td></tr><tr><td>요청 제한시간(초)</td><td>Integer
- Default Value: 60</td><td>듀티사이클 명령의 HTTP 읽기 제한시간. 원격 호스트에서 가장 오래 걸리는 명령보다 길어야 합니다</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 120</td><td>How often to query the state of the output</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Remote AoT Output</td></td><td>The Remote AoT Output to control</td></tr><tr><td>시작 상태</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>Start Duty Cycle</td><td>Decimal</td><td>The duty cycle to set at startup, if enabled</td></tr><tr><td>종료 상태</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>Shutdown Duty Cycle</td><td>Decimal</td><td>The duty cycle to set at shutdown, if enabled</td></tr><tr><td>신호 반전</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>저장된 신호 반전</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### 원격 AoT Output: 끄기

- Interfaces: API
- Output Types: On/Off
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

This Output allows remote control of another AoT On/Off Output over a network using the API.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Remote AoT Host</td><td>Text</td><td>원격 AoT의 호스트 또는 IP 주소 (포트를 포함할 수 있습니다. 예: 192.168.0.9:8084)</td></tr><tr><td>Remote AoT API Key</td><td>Text</td><td>원격 AoT의 API 키. 그 서버에 표시된 값을 그대로 입력합니다</td></tr><tr><td>프로토콜</td><td>Select(Options: [<strong>HTTPS</strong> | HTTP] (Default in <strong>bold</strong>)</td><td>신뢰할 수 있는 망에서 평문 HTTP로만 접근되는 경우가 아니라면 HTTPS를 사용하세요</td></tr><tr><td>TLS 인증서 검증</td><td>Boolean
- Default Value: True</td><td>원격 서버의 인증서를 검증합니다. 신뢰할 수 있는 망의 자체 서명 인증서일 때만 끄세요 — 꺼 두는 동안에는 중간자가 API 키를 읽을 수 있습니다</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 120</td><td>How often to query the state of the output</td></tr><tr><td>Request Timeout (Seconds)</td><td>Integer
- Default Value: 60</td><td>HTTP read timeout for ON/OFF commands. Must be longer than the slowest command on the remote host (e.g. if the remote command has time.sleep(15), set this to at least 20).</td></tr><tr><td>명령 제한 시간 (초)</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Remote AoT Output</td></td><td>The Remote AoT Output to control</td></tr><tr><td>시작 상태</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>Set the state when AoT starts</td></tr><tr><td>종료 상태</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>Set the state when AoT shuts down</td></tr><tr><td>강제 명령</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>시작 시 작동 함수</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr></tbody></table>

### 페리스탈틱 풀머: Atlas Scientific

- Manufacturer: Atlas Scientific
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Output Types: Volume, On/Off
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/peristaltic/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO_PMP_Datasheet.pdf)
- Product URL: [Link](https://atlas-scientific.com/peristaltic/ezo-pmp/)

Atlas Scientific peristaltic pumps can be set to dispense at their maximum rate or a rate can be specified. Their minimum flow rate is 0.5 ml/min and their maximum is 105 ml/min.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI 장치</td><td>Text</td><td>입력/출력 등에 연결된 FTDI 장치</td></tr><tr><td>UART 장치</td><td>Text</td><td>UART 장치 위치 (예: /dev/ttyUSB1)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Calibration: a calibration can be performed to increase the accuracy of the pump. It's a good idea to clear the calibration before calibrating. First, remove all air from the line by pumping the fluid you would like to calibrate to through the pump hose. Next, press Dispense Amount and the pump will be instructed to dispense 10 ml (unless you changed the default value). Measure how much fluid was actually dispensed, enter this value in the Actual Volume Dispensed (ml) field, and press Calibrate to Dispensed Amount. Now any further pump volumes dispensed should be accurate.</td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td>Volume to Dispense (ml)</td><td>Decimal
- Default Value: 10.0</td><td>The volume (ml) that is instructed to be dispensed</td></tr><tr><td>Dispense Amount</td><td>Button</td><td></td></tr><tr><td>Actual Volume Dispensed (ml)</td><td>Decimal
- Default Value: 10.0</td><td>The actual volume (ml) that was dispensed</td></tr><tr><td>Calibrate to Dispensed Amount</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>새 I2C 주소</td><td>Text
- Default Value: 0x67</td><td>새로운 I2C 장치로 설정</td></tr><tr><td>I2C 주소 설정</td><td>Button</td><td></td></tr></tbody></table>

### 페리스탈틱 풀머: Grove I2C Motor Driver (Board v1.3)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wiki.seeedstudio.com/Grove-I2C_Motor_Driver_V1.3)

Controls the Grove I2C Motor Driver Board (v1.3). Both motors will turn at the same time. This output can also dispense volumes of fluid if the motors are attached to peristaltic pumps.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>Motor Speed (0 - 100)</td><td>Integer
- Default Value: 100</td><td>The motor output that determines the speed</td></tr><tr><td>유량 방식</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>펌핑할 때 사용할 유량</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 100.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr></tbody></table>

### 페리스탈틱 풀머: Grove I2C Motor Driver (TB6612FNG, Board v1.0)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wiki.seeedstudio.com/Grove-I2C_Motor_Driver-TB6612FNG)

Controls the Grove I2C Motor Driver Board (v1.3). Both motors will turn at the same time. This output can also dispense volumes of fluid if the motors are attached to peristaltic pumps.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>Motor Speed (0 - 255)</td><td>Integer
- Default Value: 255</td><td>The motor output that determines the speed</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 100.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump turns on for every 60 second period (only used for Specify Flow Rate mode).</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>새 I2C 주소</td><td>Text
- Default Value: 0x14</td><td>The new I2C to set the sensor to</td></tr><tr><td>I2C 주소 설정</td><td>Button</td><td></td></tr></tbody></table>

### 페리스탈틱 풀머: L298N DC Motor Controller (Pi 5)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: pinctrl
- Additional URL: [Link](https://www.electronicshub.org/raspberry-pi-l298n-interface-tutorial-control-dc-motor-l298n-raspberry-pi/)

The L298N can control 2 DC motors, and direction. If these motors control peristaltic pumps, set the Flow Rate and the output can can be instructed to dispense volumes accurately in addition to being turned on for durations.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>Input Pin 1</td><td>Integer</td><td>The Input Pin 1 of the controller (BCM numbering)</td></tr><tr><td>Input Pin 2</td><td>Integer</td><td>The Input Pin 2 of the controller (BCM numbering)</td></tr><tr><td>Use Enable Pin</td><td>Boolean
- Default Value: True</td><td>Enable the use of the Enable Pin</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>The Enable pin of the controller (BCM numbering)</td></tr><tr><td>방향</td><td>Select(Options: [<strong>Forward</strong> | Backward] (Default in <strong>bold</strong>)</td><td>The direction to turn the motor</td></tr><tr><td>Volume Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>If a pump, the measured flow rate (ml/min) at the set Duty Cycle</td></tr></tbody></table>

### 페리스탈틱 풀머: L298N DC Motor Controller (Pi <= 4)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Additional URL: [Link](https://www.electronicshub.org/raspberry-pi-l298n-interface-tutorial-control-dc-motor-l298n-raspberry-pi/)

The L298N can control 2 DC motors, both speed and direction. If these motors control peristaltic pumps, set the Flow Rate and the output can can be instructed to dispense volumes accurately in addition to being turned on for durations.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>Input Pin 1</td><td>Integer</td><td>The Input Pin 1 of the controller (BCM numbering)</td></tr><tr><td>Input Pin 2</td><td>Integer</td><td>The Input Pin 2 of the controller (BCM numbering)</td></tr><tr><td>Use Enable Pin</td><td>Boolean
- Default Value: True</td><td>Enable the use of the Enable Pin</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>The Enable pin of the controller (BCM numbering)</td></tr><tr><td>Enable Pin Duty Cycle</td><td>Integer
- Default Value: 50</td><td>The duty cycle to apply to the Enable Pin (percent, 1 - 100)</td></tr><tr><td>방향</td><td>Select(Options: [<strong>Forward</strong> | Backward] (Default in <strong>bold</strong>)</td><td>The direction to turn the motor</td></tr><tr><td>Volume Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>If a pump, the measured flow rate (ml/min) at the set Duty Cycle</td></tr></tbody></table>

### 페리스탈틱 풀머: MCP23017 16-Channel I/O 확장기

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Dependencies: [swig](https://packages.debian.org/search?keywords=swig), [liblgpio-dev](https://packages.debian.org/search?keywords=liblgpio-dev), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp230xx](https://pypi.org/project/adafruit-circuitpython-mcp230xx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/MCP23017)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/devicedoc/20001952c.pdf)
- Product URL: [Link](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG)

Controls the 16 channels of the MCP23017 with a relay and peristaltic pump connected to each channel.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>이름</td><td>Text</td><td>다른 것과 구별하기 위한 이름</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the output channel that corresponds to the pump being on</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump should be turned on for every 60 second period</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 페리스탈틱 풀머: PCF8574 8-Channel I/O 확장기

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8574)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8574.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

Controls the 8 channels of the PCF8574 with a relay and peristaltic pump connected to each channel.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the output channel that corresponds to the pump being on</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump should be turned on for every 60 second period</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### 페리스탈틱 풀머: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

This output turns a GPIO pin HIGH and LOW to control power to a generic peristaltic pump. The peristaltic pump can then be turned on for a duration or, after determining the pump's maximum flow rate, instructed to dispense a specific volume at the maximum rate or at a specified rate.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>핀: GPIO (BCM)</td><td>Integer</td><td>상태를 제어할 핀</td></tr><tr><td>켜짐 상태</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump should be turned on for every 60 second period</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>원하는 유량 (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>현재 (암페어)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

