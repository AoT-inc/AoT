## Copyright and License Notice

This document is the documentation for the AoT system, which is based on the open-source Mycodo project.

- Copyright (C) 2025 AoT
- Copyright (C) 2015–2022 Kyle T. Gabriel

Distributed under the GNU GPLv3 license.

## REST API

AoT provides a REST API (for details, see the [API Endpoint Documentation](https://aot-inc.github.io/AoT/aot-api.html)).

An API is an Application Programming Interface — put simply, a set of rules that allow programs to communicate with one another. It exposes data and functionality over the internet in a consistent format.

REST stands for Representational State Transfer. It is an architectural pattern that describes how distributed systems can expose a consistent interface. When people use the term "REST API," they generally refer to an API accessed through a predefined set of URLs over the HTTP protocol. These URLs represent various resources, and any information or content accessible at those locations may be returned as JSON, HTML, an audio file, or an image. Often, a resource has one or more methods that can be performed over HTTP (GET, POST, PUT, and DELETE).

### Authentication

An API key can be generated under **Manage → System Management → Users**, editing
the user, then **Generate API Key**. The key is a 128-byte random value, shown to
you as a base64-encoded string **only once, at the moment it is generated** — AoT
stores only a one-way hash of it, not the key itself, so it cannot be displayed
again later. If it is lost, generate a new one. See [Security](Security.md#api-keys)
for more.

AoT supports several authentication methods. All API requests must be made over HTTPS. Calls made over plain HTTP will fail. API requests made without authentication will fail.

### Bash Example

You can use ``curl``, but you must use ``-k`` so that an unsigned SSL certificate can be used, or use your own certificate and domain.

```bash
curl -k -v -X GET "https://127.0.0.1/api/settings/users" -H "authorization: Basic YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

```bash
curl -k -v -X GET "https://127.0.0.1/api/settings/users" -H "X-API-KEY: YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

The API key may also be passed as a `?api_key=` query parameter, but this form
is **deprecated and will be removed in a future release**:

```bash
# DEPRECATED — use one of the header forms above instead
curl -k -v -X GET "https://127.0.0.1/api/settings/users?api_key=YOUR_API_KEY" -H "accept: application/vnd.aot.v1+json"
```

A key in the query string is written to web-server access logs, reverse-proxy
logs and `Referer` headers, so it is effectively disclosed to anyone who can
read those. Requests using this form are logged with a deprecation warning and
recorded in the audit log (`apikey.url_auth`) so remaining callers can be found
before the form is withdrawn.

### Python Example (GET)

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

### Python Example (POST)

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

### Errors

AoT uses conventional HTTP response codes to indicate the success or failure of an API request. In general: codes in the 2xx range indicate success. Codes in the 4xx range indicate an error that failed due to the information provided (for example, a required parameter was omitted, a charge failed, and so on). Codes in the 5xx range indicate an error on the AoT server (these are rare).

4xx errors that can be handled programmatically (for example, a card being declined) include an error code that briefly describes the reported error.

### Endpoints

A vendor-specific content type header must be included to determine the API version. For version 1, this is "application/vnd.aot.v1+json," as shown in the examples above.

Visit https://{RASPBERRY_PI_IP_ADDRESS}/api to view the current API endpoint documentation for your AoT installation.

Documentation for the latest API version is also available in HTML format: `AoT API Documentation <https://aot-inc.github.io/AoT/aot-api.html>`__

## Daemon Control Object

### DaemonControl()

**class aot_client.DaemonControl**\ (*pyro_uri='PYRO:aot.pyro_server@127.0.0.1:9080'*, *pyro_timeout=None*)

The aot client object implements methods for communicating with the aot daemon and querying information from the influxdb database.

Example usage:

```python
from aot.aot_client import DaemonControl
control = DaemonControl()
control.terminate_daemon()
```

Parameters:

-  **pyro_uri** - The Pyro5 uri used to connect to the daemon.
-  **pyro_timeout** - The Pyro5 timeout duration.

### controller_activate()

**controller_activate**\ (*controller_id*)

Activates a controller.

Parameters:

-  **controller_type** - The type of controller being activated. Options are: "Function", "Input", "Output", "PID", "Trigger", or "Function".
-  **controller_id** - The unique ID of the controller to activate.

### controller_deactivate()

**controller_deactivate**\ (*controller_id*)

Deactivates a controller.

Parameters:

-  **controller_type** - The type of controller being deactivated. Options are: "Conditional", "Input", "Output", "PID", "Trigger", or "Function".
-  **controller_id** - The unique ID of the controller to deactivate.

### get_condition_measurement()

**get_condition_measurement**\ (*condition_id*)

Retrieves a measurement from a condition of a Conditional Function.

Parameters:

-  **condition_id** - The unique ID of the controller.

### get_condition_measurement_dict()

**get_condition_measurement_dict**\ (*condition_id*)

Retrieves a measurement dictionary from a condition of a Conditional Function.

Parameters:

-  **condition_id** - The unique ID of the controller.

### input_force_measurements()

**input_force_measurements**\ (*input_id*)

Forces an Input to acquire measurements.

Parameters:

-  **input_id** - The unique ID of the controller.

### lcd_backlight()

**lcd_backlight**\ (*lcd_id*, *state*)

Turns the LCD backlight on or off, provided the LCD supports this feature.

Parameters:

-  **lcd_id** - The unique ID of the controller.
-  **state** - The state of the LCD backlight. Options are: False for off, True for on.

### lcd_flash()

**lcd_flash**\ (*lcd_id*, *state*)

Starts or stops flashing the LCD backlight, provided the LCD supports this feature.

Parameters:

-  **lcd_id** - The unique ID of the controller.
-  **state** - The state of the LCD flashing. Options are: False for off, True for on.

### lcd_reset()

**lcd_reset**\ (*lcd_id*)

Resets the LCD to its default startup state. This can be used to clear the screen, fix display issues, or turn off flashing.

Parameters:

-  **lcd_id** - The unique ID of the controller.

### output_off()

**output_off**\ (*output_id*, *trigger_conditionals=True*)

Turns an output off.

Parameters:

-  **output_id** - The unique ID of the output.
-  **trigger_conditionals** - Whether to trigger controllers that monitor for state changes.

### output_on()

**output_on**\ (*output_id*, *output_type='sec'*, *amount=0.0*, *min_off=0.0*, *trigger_conditionals=True*)

Turns an output on.

Parameters:

-  **output_id** - The unique ID of the output.
-  **output_type** - The output type to send to the output module (for example, "sec", "pwm", "vol").
-  **amount** - The amount to send to the output module.
-  **min_off** - The minimum time the output must remain off after being turned on.
-  **trigger_conditionals** - Whether to trigger controllers that monitor for state changes.

### output_on_off()

**output_on_off**\ (*output_id*, *state*, *output_type='sec'*, *amount=0.0*,)

Turns an output on or off.

Parameters:

-  **output_id** - The unique ID of the output.
-  **state** - Indicates whether to turn the output on or off. Options are: "on", "off".
-  **output_type** - The output type to send to the output module (for example, "sec", "pwm", "vol").
-  **amount** - The amount to send to the output module.

### output_sec_currently_on()

**output_sec_currently_on**\ (*output_id*)

Retrieves the amount of time, in seconds, that the output has been on.

Parameters:

-  **output_id** - The unique ID of the output.

### output_setup()

**output_setup**\ (*action*, *output_id*)

Sets up an output (for example, loads/reloads settings from the database, initializes pins/classes, and so on).

Parameters:

-  **action** - The action to instruct the output to perform. Options are: "Add", "Delete", or "Modify".
-  **output_id** - The unique ID of the output.

### output_state()

**output_state**\ (*output_id*)

Retrieves the state of an output. Returns "on", "off", or a duty cycle value.

Parameters:

-  **output_id** - The unique ID of the output.

### pid_get()

**pid_get**\ (*pid_id*, *setting*)

Retrieves a parameter of a PID controller.

Parameters:

-  **pid_id** - The unique ID of the controller.
-  **setting** - The option to retrieve. Options are: "setpoint", "error", "integrator", "derivator", "kp", "ki", or "kd".

### pid_hold()

**pid_hold**\ (*pid_id*)

Sets a PID controller to the hold state.

Parameters:

-  **pid_id** - The unique ID of the controller.

### pid_mod()

**pid_mod**\ (*pid_id*)

Refreshes or reinitializes the variables of a running PID controller.

Parameters:

-  **pid_id** - The unique ID of the controller.

### pid_pause()

**pid_pause**\ (*pid_id*)

Sets a PID controller to the pause state.

Parameters:

-  **pid_id** - The unique ID of the controller.

### pid_resume()

**pid_resume**\ (*pid_id*)

Sets a PID controller to the resume state.

Parameters:

-  **pid_id** - The unique ID of the controller.

### pid_set()

**pid_set**\ (*pid_id*, *setting*, *value*)

Sets a parameter of a running PID controller.

Parameters:

-  **pid_id** - The unique ID of the controller.
-  **setting** - The option to set. Options are: "setpoint", "method", "integrator", "derivator", "kp", "ki", or "kd".
-  **value** - The value to set.

### module_function()

**module_function**\ (*controller_type*, *unique_id*, *button_id*, *args_dict*, *thread=True*, *return_from_function=False*)

Directly runs a custom function of a specific module (Input, Output, and so on). This is used primarily for **sensor calibration** tasks.

Parameters:

-  **controller_type**: The module type (for example, "Input", "Output")
-  **unique_id**: The unique ID of the module
-  **button_id**: The ID of the function to run (for example, "mid_calibrate", "clear_calibrate")
-  **args_dict**: A dictionary of parameters to pass to the function

### refresh_daemon_conditional_settings()

**refresh_daemon_conditional_settings**\ (*unique_id*)

Refreshes the settings of a running Conditional Function.

### refresh_daemon_misc_settings()

**refresh_daemon_misc_settings**\ ()

Refreshes the miscellaneous settings of the running daemon from the database values.

### refresh_daemon_trigger_settings()

**refresh_daemon_trigger_settings**\ (*unique_id*)

Refreshes the trigger settings of a running Trigger controller.

### check_daemon()

**check_daemon**\ ()

Checks the active status of the daemon. Returns "GOOD" or an error message.

---

> [!NOTE]
> A structured API specification for AI agents is available in the `ai_docs/api.json` file.
