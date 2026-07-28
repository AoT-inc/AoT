## 저작권 및 라이선스 안내

이 문서는 오픈소스 Mycodo 프로젝트를 기반으로 한 AoT 시스템의 문서입니다.

- Copyright (C) 2025 AoT
- Copyright (C) 2015–2022 Kyle T. Gabriel

GNU GPLv3 라이선스에 따라 배포됩니다.

## REST API

AoT는 REST API를 제공합니다 (자세한 내용은 [API 엔드포인트 문서](https://aot-inc.github.io/AoT/aot-api.html)를 참조하십시오).

API는 응용 프로그램 프로그래밍 인터페이스로, 간단히 말해 프로그램이 서로 통신할 수 있도록 하는 규칙 집합입니다. 이는 인터넷을 통해 일관된 형식으로 데이터와 기능을 노출합니다.

REST는 표현 상태 전송(Representational State Transfer)의 약자입니다. 이는 분산 시스템이 일관된 인터페이스를 노출하는 방법을 설명하는 아키텍처 패턴입니다. 사람들이 ‘REST API’라는 용어를 사용할 때, 일반적으로 HTTP 프로토콜을 통해 미리 정의된 URL 집합을 통해 접근하는 API를 지칭합니다. 이러한 URL은 다양한 리소스를 나타내며, 해당 위치에서 접근할 수 있는 모든 정보나 콘텐츠는 JSON, HTML, 오디오 파일 또는 이미지로 반환될 수 있습니다. 종종 리소스는 HTTP를 통해 수행할 수 있는 하나 이상의 메서드(GET, POST, PUT 및 DELETE)를 가집니다.

### 인증

API 키는 **관리 → 시스템 관리 → 사용자**에서 사용자를 편집한 뒤 **API 키 생성**을 눌러 발급할 수 있습니다. 키는 128바이트 난수값이며, **생성되는 그 순간 딱 한 번만** base64로 인코딩된 문자열로 표시됩니다 — AoT는 키 자체가 아니라 단방향 해시만 저장하므로 이후에는 다시 표시할 수 없습니다. 분실했다면 새로 발급하십시오. 자세한 내용은 [보안](Security.ko.md#api-keys)을 참조하십시오.

AoT는 여러 인증 방법을 지원합니다. 모든 API 요청은 HTTPS를 통해 이루어져야 합니다. 일반 HTTP를 통해 이루어진 호출은 실패합니다. 인증 없이 이루어진 API 요청은 실패합니다.

### Bash 예제

``curl``을 사용할 수 있지만, 서명되지 않은 SSL 인증서를 사용할 수 있도록 ``-k``를 사용하거나, 자신의 인증서와 도메인을 사용해야 합니다.

```bash
curl -k -v -X GET "https://127.0.0.1/api/settings/users" -H "authorization: Basic YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

```bash
curl -k -v -X GET "https://127.0.0.1/api/settings/users" -H "X-API-KEY: YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

API 키를 `?api_key=` 쿼리 파라미터로 전달할 수도 있으나, 이 방식은
**폐기 예정이며 향후 릴리스에서 제거됩니다**:

```bash
# 폐기 예정 — 위의 헤더 방식을 사용하세요
curl -k -v -X GET "https://127.0.0.1/api/settings/users?api_key=YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

쿼리스트링에 담긴 키는 웹서버 액세스 로그·리버스 프록시 로그·`Referer` 헤더에
그대로 기록되므로, 그 로그를 볼 수 있는 사람에게 사실상 노출됩니다. 이 방식으로
들어온 요청은 폐기 경고와 함께 감사 로그(`apikey.url_auth`)에 기록되어, 제거
전에 남은 사용처를 파악할 수 있습니다.

### Python 예제 (GET)

```python
import json
import requests

ip_address = '127.0.0.1'
api_key = 'YOUR_API_KEY'
endpoint = 'settings/inputs'
url = 'https://{ip}/api/{ep}'.format(ip=ip_address, ep=endpoint)
headers = {
    'Accept': 'application/vnd.aot.v1+json',
    'X-API-KEY': api_key
}
response = requests.get(url, headers=headers, verify=False)
print("응답 상태: {}".format(response.status_code))
print("응답 헤더: {}".format(response.headers))
response_dict = json.loads(response.text)
print("응답 딕셔너리: {}".format(response_dict))
```

### Python 예제 (POST)

```python
import json
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ip_address = '127.0.0.1'
api_key = 'YOUR_API_KEY'
endpoint = 'outputs/3f5a4806-c830-432d-b329-7821da8336e4'
url = 'https://{ip}/api/{ep}'.format(ip=ip_address, ep=endpoint)
data = {"state": True}  # 출력을 켭니다
headers = {
    'Accept': 'application/vnd.aot.v1+json',
    'X-API-KEY': api_key
}
response = requests.post(url, json=data, headers=headers, verify=False)
print("응답 상태: {}".format(response.status_code))
print("응답 헤더: {}".format(response.headers))
response_dict = json.loads(response.text)
print("응답 딕셔너리: {}".format(response_dict))
```

### 오류

AoT는 API 요청의 성공 또는 실패를 나타내기 위해 일반적인 HTTP 응답 코드를 사용합니다. 일반적으로: 2xx 범위의 코드는 성공을 나타냅니다. 4xx 범위의 코드는 제공된 정보로 인해 실패한 오류를 나타냅니다 (예: 필수 매개변수가 생략되었거나, 요금 청구가 실패하는 경우 등). 5xx 범위의 코드는 AoT 서버의 오류를 나타냅니다 (이는 드뭅니다).

프로그램적으로 처리할 수 있는 4xx 오류(예: 카드가 거절됨)에는 보고된 오류를 간략하게 설명하는 오류 코드가 포함됩니다.

### 엔드포인트

API 버전을 결정하기 위해 벤더 특정 콘텐츠 유형 헤더가 포함되어야 합니다. 버전 1의 경우, 이는 "application/vnd.aot.v1+json"입니다. 위의 예제에서 볼 수 있습니다.

https://{RASPBERRY_PI_IP_ADDRESS}/api를 방문하여 AoT 설치의 현재 API 엔드포인트 문서를 확인하십시오.

최신 API 버전에 대한 문서는 HTML 형식으로도 제공됩니다: `AoT API 문서 <https://aot-inc.github.io/AoT/aot-api.html>`__

## 데몬 제어 객체

### DaemonControl()

**class aot_client.DaemonControl**\ (*pyro_uri='PYRO:aot.pyro_server@127.0.0.1:9080'*, *pyro_timeout=None*)

aot 클라이언트 객체는 aot 데몬과 통신하고 influxdb 데이터베이스에서 정보를 쿼리하는 방법을 구현합니다.

사용 예:

```python
from aot.aot_client import DaemonControl
control = DaemonControl()
control.terminate_daemon()
```

매개변수:

-  **pyro_uri** - 데몬에 연결하는 데 사용할 Pyro5 uri입니다.
-  **pyro_timeout** - Pyro5 타임아웃 기간입니다.

### controller_activate()

**controller_activate**\ (*controller_id*)

컨트롤러를 활성화합니다.

매개변수:

-  **controller_type** - 활성화되는 컨트롤러의 유형입니다. 옵션은: "Function", "Input", "Output", "PID", "Trigger" 또는 "Function"입니다.
-  **controller_id** - 활성화할 컨트롤러의 고유 ID입니다.

### controller_deactivate()

**controller_deactivate**\ (*controller_id*)

컨트롤러를 비활성화합니다.

매개변수:

-  **controller_type** - 비활성화되는 컨트롤러의 유형입니다. 옵션은: "Conditional", "Input", "Output", "PID", "Trigger" 또는 "Function"입니다.
-  **controller_id** - 비활성화할 컨트롤러의 고유 ID입니다.

### get_condition_measurement()

**get_condition_measurement**\ (*condition_id*)

조건 함수의 조건에서 측정을 가져옵니다.

매개변수:

-  **condition_id** - 컨트롤러의 고유 ID입니다.

### get_condition_measurement_dict()

**get_condition_measurement_dict**\ (*condition_id*)

조건 함수의 조건에서 측정 딕셔너리를 가져옵니다.

매개변수:

-  **condition_id** - 컨트롤러의 고유 ID입니다.

### input_force_measurements()

**input_force_measurements**\ (*input_id*)

입력에 측정을 수행하도록 유도합니다.

매개변수:

-  **input_id** - 컨트롤러의 고유 ID입니다.

### lcd_backlight()

**lcd_backlight**\ (*lcd_id*, *state*)

LCD의 백라이트를 켜거나 끕니다. LCD가 해당 기능을 지원하는 경우에 한합니다.

매개변수:

-  **lcd_id** - 컨트롤러의 고유 ID입니다.
-  **state** - LCD 백라이트의 상태입니다. 옵션은: False는 끔, True는 켬입니다.

### lcd_flash()

**lcd_flash**\ (*lcd_id*, *state*)

LCD 백라이트가 깜박이도록 시작하거나 중지합니다. LCD가 해당 기능을 지원하는 경우에 한합니다.

매개변수:

-  **lcd_id** - 컨트롤러의 고유 ID입니다.
-  **state** - LCD 깜박임의 상태입니다. 옵션은: False는 끔, True는 켬입니다.

### lcd_reset()

**lcd_reset**\ (*lcd_id*)

LCD를 기본 시작 상태로 리셋합니다. 이는 화면을 지우거나, 표시 문제를 수정하거나, 깜박임을 끄는 데 사용될 수 있습니다.

매개변수:

-  **lcd_id** - 컨트롤러의 고유 ID입니다.

### output_off()

**output_off**\ (*output_id*, *trigger_conditionals=True*)

출력을 끕니다.

매개변수:

-  **output_id** - 출력의 고유 ID입니다.
-  **trigger_conditionals** - 상태 변경을 모니터링하는 컨트롤러를 트리거할지 여부입니다.

### output_on()

**output_on**\ (*output_id*, *output_type='sec'*, *amount=0.0*, *min_off=0.0*, *trigger_conditionals=True*)

출력을 켭니다.

매개변수:

-  **output_id** - 출력의 고유 ID입니다.
-  **output_type** - 출력 모듈에 전송할 출력 유형입니다 (예: "sec", "pwm", "vol").
-  **amount** - 출력 모듈에 전송할 양입니다.
-  **min_off** - 켜진 후 꺼야 할 최소 시간입니다.
-  **trigger_conditionals** - 상태 변경을 모니터링하는 컨트롤러를 트리거할지 여부입니다.

### output_on_off()

**output_on_off**\ (*output_id*, *state*, *output_type='sec'*, *amount=0.0*,)

출력을 켜거나 끕니다.

매개변수:

-  **output_id** - 출력의 고유 ID입니다.
-  **state** - 출력을 켤지 끌지를 나타냅니다. 옵션은: "on", "off"입니다.
-  **output_type** - 출력 모듈에 전송할 출력 유형입니다 (예: "sec", "pwm", "vol").
-  **amount** - 출력 모듈에 전송할 양입니다.

### output_sec_currently_on()

**output_sec_currently_on**\ (*output_id*)

출력이 켜진 시간을 초 단위로 가져옵니다.

매개변수:

-  **output_id** - 출력의 고유 ID입니다.

### output_setup()

**output_setup**\ (*action*, *output_id*)

출력을 설정합니다 (예: 데이터베이스에서 설정을 로드/재로드하고, 핀/클래스를 초기화 등).

매개변수:

-  **action** - 출력을 지시할 작업입니다. 옵션은: "Add", "Delete" 또는 "Modify"입니다.
-  **output_id** - 출력의 고유 ID입니다.

### output_state()

**output_state**\ (*output_id*)

출력의 상태를 가져옵니다. "on", "off" 또는 듀티 사이클 값을 반환합니다.

매개변수:

-  **output_id** - 출력의 고유 ID입니다.

### pid_get()

**pid_get**\ (*pid_id*, *setting*)

PID 컨트롤러의 매개변수를 가져옵니다.

매개변수:

-  **pid_id** - 컨트롤러의 고유 ID입니다.
-  **setting** - 가져올 옵션입니다. 옵션은: "setpoint", "error", "integrator", "derivator", "kp", "ki" 또는 "kd"입니다.

### pid_hold()

**pid_hold**\ (*pid_id*)

PID 컨트롤러를 유지 상태로 설정합니다.

매개변수:

-  **pid_id** - 컨트롤러의 고유 ID입니다.

### pid_mod()

**pid_mod**\ (*pid_id*)

실행 중인 PID 컨트롤러의 변수를 새로 고치거나 초기화합니다.

매개변수:

-  **pid_id** - 컨트롤러의 고유 ID입니다.

### pid_pause()

**pid_pause**\ (*pid_id*)

PID 컨트롤러를 일시 정지 상태로 설정합니다.

매개변수:

-  **pid_id** - 컨트롤러의 고유 ID입니다.

### pid_resume()

**pid_resume**\ (*pid_id*)

PID 컨트롤러를 재개 상태로 설정합니다.

매개변수:

-  **pid_id** - 컨트롤러의 고유 ID입니다.

### pid_set()

**pid_set**\ (*pid_id*, *setting*, *value*)

실행 중인 PID 컨트롤러의 매개변수를 설정합니다.

매개변수:

-  **pid_id** - 컨트롤러의 고유 ID입니다.
-  **setting** - 설정할 옵션입니다. 옵션은: "setpoint", "method", "integrator", "derivator", "kp", "ki" 또는 "kd"입니다.
-  **value** - 설정할 값입니다.

### module_function()

**module_function**\ (*controller_type*, *unique_id*, *button_id*, *args_dict*, *thread=True*, *return_from_function=False*)

특정 모듈(입력, 출력 등)의 커스텀 함수를 직접 실행합니다. 이는 주로 **센서 보정(Calibration)** 작업을 위해 사용됩니다.

매개변수:

-  **controller_type**: 모듈 유형 (예: "Input", "Output")
-  **unique_id**: 모듈의 고유 ID
-  **button_id**: 실행할 함수의 ID (예: "mid_calibrate", "clear_calibrate")
-  **args_dict**: 함수에 전달할 매개변수 딕셔너리

### refresh_daemon_conditional_settings()

**refresh_daemon_conditional_settings**\ (*unique_id*)

실행 중인 조건 함수의 설정을 새로 고칩니다.

### refresh_daemon_misc_settings()

**refresh_daemon_misc_settings**\ ()

데이터베이스 값에서 실행 중인 데몬의 다양한 설정을 새로 고칩니다.

### refresh_daemon_trigger_settings()

**refresh_daemon_trigger_settings**\ (*unique_id*)

실행 중인 트리거 컨트롤러의 트리거 설정을 새로 고칩니다.

### check_daemon()

**check_daemon**\ ()

데몬의 활성 상태를 확인합니다. "GOOD" 또는 오류 메시지를 반환합니다.

---

> [!NOTE]
> AI 에이전트를 위한 구조화된 API 명세는 `ai_docs/api.json` 파일에서 확인할 수 있습니다.

