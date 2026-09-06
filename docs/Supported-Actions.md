## Built-In Actions (System)

### Actions: Pause

- Manufacturer: AoT
- Works with: Functions

Set a delay between executing Actions when self.run_all_actions() is used.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will create a pause for the set duration. When <strong>self.run_all_actions()</strong> is executed, this will add a pause in the sequential execution of all actions.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Duration (Seconds)</td><td>Decimal</td><td>The duration to pause</td></tr></tbody></table>

### Camera: Capture Photo

- Manufacturer: AoT
- Works with: Functions

Capture a photo with the selected Camera.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will capture a photo with the selected Camera. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will capture a photo with the Camera with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>Select the Camera to take a photo</td></tr></tbody></table>

### Camera: Time-lapse: Pause

- Manufacturer: AoT
- Works with: Functions

Pause a camera time-lapse

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected Camera time-lapse. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will pause the Camera time-lapse with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>Select the Camera to pause the time-lapse</td></tr></tbody></table>

### Camera: Time-lapse: Resume

- Manufacturer: AoT
- Works with: Functions

Resume a camera time-lapse

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will resume the selected Camera time-lapse. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will resume the Camera time-lapse with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>Select the Camera to resume the time-lapse</td></tr></tbody></table>

### Controller: Activate

- Manufacturer: AoT
- Works with: Functions

Activate a controller.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will activate the selected Controller. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will activate the controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the controller to activate</td></tr></tbody></table>

### Controller: Deactivate

- Manufacturer: AoT
- Works with: Functions

Deactivate a controller.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will deactivate the selected Controller. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will deactivate the controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the controller to deactivate</td></tr></tbody></table>

### Create: Daemon Log Line

- Manufacturer: AoT
- Works with: Functions

Create a log line in the daemon log.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will add a line to the Daemon log. Executing <strong>self.run_action("ACTION_ID", value={"log_level": "info", "log_text": "this is a log line"})</strong> will execute the action with the specified log level and log line text. If a log line text is not specified, then the action message will be used as the text.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Log Level</td><td>Select(Options: [<strong>Info</strong> | Warning | Error | Debug] (Default in <strong>bold</strong>)</td><td>The log level to insert the text into the log</td></tr><tr><td>Log Line Text</td><td>Text
- Default Value: Log Line Text</td><td>The text to insert in the Daemon log</td></tr></tbody></table>

### Create: Note

- Manufacturer: AoT
- Works with: Functions

Create a note with the selected options.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will create a note with the configured options. Executing <strong>self.run_action("ACTION_ID", value={"tags": ["tag1"], "name": "Title", "note": "body", "category": "alarm", "priority": 1})</strong> will override the stored settings. Set <strong>auto_target</strong> to link the note automatically to the parent Function.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Tags</td></td><td>Select one or more tags</td></tr><tr><td>Name</td><td>Text</td><td>Title (if blank, auto-extracted from the first line of the body)</td></tr><tr><td>Note</td></td><td>Note body</td></tr><tr><td>Include action message in body</td><td>Boolean</td><td>Append the message passed by the condition/trigger to the end of the note body</td></tr><tr><td>Auto-link to parent Function</td><td>Boolean
- Default Value: True</td><td>Automatically link the note to this action's parent Function (target_id/target_type)</td></tr><tr><td>Category</td><td>Select(Options: [<strong>General</strong> | Observation | Alarm | Maintenance] (Default in <strong>bold</strong>)</td><td>Note category</td></tr><tr><td>Priority</td><td>Select(Options: [<strong>Normal</strong> | High | Urgent] (Default in <strong>bold</strong>)</td><td>Note priority</td></tr></tbody></table>

### Display: Backlight: Color

- Manufacturer: AoT
- Works with: Functions

Set the display backlight color

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will change the backlight color on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "color": "255,0,0"})</strong> will change the backlight color on the controller with the specified ID and color. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>Select the display to set the backlight color</td></tr><tr><td>Color (RGB)</td><td>Text
- Default Value: 255,0,0</td><td>Color as R,G,B values (e.g. "255,0,0" without quotes)</td></tr></tbody></table>

### Display: Backlight: Off

- Manufacturer: AoT
- Works with: Functions

Turn display backlight off

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will turn the backlight off for the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will turn the backlight off for the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>Select the display to turn the backlight off</td></tr></tbody></table>

### Display: Backlight: On

- Manufacturer: AoT
- Works with: Functions

Turn display backlight on

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will turn the backlight on for the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will turn the backlight on for the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>Select the display to turn the backlight on</td></tr></tbody></table>

### Display: Flashing: Off

- Manufacturer: AoT
- Works with: Functions

Turn display flashing off

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will stop the backlight flashing on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will stop the backlight flashing on the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>Select the display to stop flashing the backlight</td></tr></tbody></table>

### Display: Flashing: On

- Manufacturer: AoT
- Works with: Functions

Turn display flashing on

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will start the backlight flashing on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will start the backlight flashing on the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Display</td><td>Select Device</td><td>Select the display to start flashing the backlight</td></tr></tbody></table>

### Environment Control

- Manufacturer: AoT
- Works with: Functions

Register an actuator with the Integrated Environment Control (env_coordinator) Function. Add this action multiple times to register more than one device.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output Channel</td><td>Select Channel (Output_Channels)</td><td>Select the Output channel to control.</td></tr><tr><td>Actuator Type</td><td>Select</td><td>Select the role this Output performs.</td></tr><tr><td>Cost Index</td><td>Decimal
- Default Value: 5.0</td><td>Lower value = higher priority (1 = free natural ventilation, 10 = high-cost device).</td></tr><tr><td>On Time Window End</td><td>Select(Options: [<strong>Do Nothing</strong> | Turn Off | Turn On | Set Open % (Vent only)] (Default in <strong>bold</strong>)</td><td>Action to take on this actuator when the time control window ends.</td></tr><tr><td>End Open %</td><td>Decimal</td><td>Target opening percentage when the time window ends (Vent / Opening only).</td></tr><tr><td>Cloth Transmittance Override (0-1, Shade only)</td><td>Decimal</td><td>Only for this screen, when its cloth differs from the rest. Leave 0 to use the value set on the linked facility. Used when there is no indoor light sensor: the indoor level is estimated from outdoor irradiance and the screen position.</td></tr><tr><td>Effect Coefficient Override (K_*)</td><td>Decimal</td><td>0 = use default. Enter only when calibrating from measured data. e.g. cooler → K_COOLER_T, fogger → K_FOG_RH.</td></tr><tr><td>Full Stroke Time (s)</td><td>Decimal</td><td>Time (seconds) for this actuator to travel 0→100%. Used to limit the maximum command change per cycle so that impossible commands (faster than physical speed) are never sent. 0 = disabled (uses slew_per_cycle as-is). Example: a vent motor that takes 10 min → enter 600.</td></tr><tr><td>Min Repeat Interval (s)</td><td>Decimal</td><td>Minimum seconds between repeated commands to this actuator even if the target value has not changed. 0 = use system default (600 s watchdog). Increase for slow motorized actuators to extend relay lifetime.</td></tr></tbody></table>

### Equation (Single-Measurement)

- Manufacturer: AoT
- Works with: Inputs

Modify a channel value with an equation before storing it in the database.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>Equation</td><td>Text
- Default Value: x-10</td><td>The equation to apply to the value before storing. "x" is the measurement value. Example: x-10</td></tr></tbody></table>

### Execute Python 3 Code

- Manufacturer: AoT
- Works with: Inputs

Execute Python 3 code when measurements are acquired.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Python 3 Code</td></td><td>The code to execute</td></tr></tbody></table>

### Execute: Bash/Shell Command

- Manufacturer: AoT
- Works with: Functions

Execute a Linux bash shell command.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will execute the bash command.Executing <strong>self.run_action("ACTION_ID", value={"user": "aot", "command": "/home/pi/my_script.sh on"})</strong> will execute the action with the specified command and user.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>User</td><td>Text
- Default Value: aot</td><td>The user to execute the command</td></tr><tr><td>Command</td><td>Text
- Default Value: /home/pi/my_script.sh on</td><td>Command to execute</td></tr></tbody></table>

### Flow Meter: Clear Total (Kilowatt-hour)

- Manufacturer: AoT
- Works with: Functions

Clear the total kWh saved for an energy meter Input. The Input must have the Clear Total kWh option. This will also clear all energy stats on the device, not just the total kWh.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will clear the total kWh for the selected energy meter Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will clear the total kWh for the energy meter Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the energy meter Input</td></tr></tbody></table>

### Flow Meter: Clear Total (Volume)

- Manufacturer: AoT
- Works with: Functions

Clear the total volume saved for a flow meter Input. The Input must have the Clear Total Volume option.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will clear the total volume for the selected flow meter Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will clear the total volume for the flow meter Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the flow meter Input</td></tr></tbody></table>

### Input: Force Measurements:

- Manufacturer: AoT
- Works with: Functions

Force measurements to be conducted for an input

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will force acquiring measurements for the selected Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will force acquiring measurements for the Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Input</td><td>Select Device</td><td>Select an Input</td></tr></tbody></table>

### LED: Kasa RGB Bulb: Change Color

- Manufacturer: AoT
- Works with: Functions

Change the color of the LED in a Kasa RGB Bulb. Select the Kasa RGB Bulb Output.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected Kasa RGB Bulb to the selected Hue, Saturation, and Brightness. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "hue": 10, "saturation": 50, "brightness": 25})</strong> will set the hue (0 - 360), saturation (0 - 100), and brightness (0 - 100) of the Kasa RGB Bulb Output with the specified ID. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the energy meter Input</td></tr><tr><td>Hue (Degree)</td><td>Integer</td><td>The hue to set, in degrees (0 - 360)</td></tr><tr><td>Saturation (Percent)</td><td>Integer
- Default Value: 50</td><td>The saturation to set, in percent (0 - 100)</td></tr><tr><td>Brightness (Percent)</td><td>Integer
- Default Value: 50</td><td>The brightness to set, in percent (0 - 100)</td></tr></tbody></table>

### LED: Neopixel: Change Pixel Color

- Manufacturer: AoT
- Works with: Functions

Change the color of an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller, pixel number, and color.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong> will set the color of the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color in RGB format, each from 0 to 255 (e.g "10, 0, 0")</td></tr></tbody></table>

### LED: Neopixel: Flashing Off

- Manufacturer: AoT
- Works with: Functions

Stop flashing an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller and pixel number.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0})</strong> will stop flashing the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr></tbody></table>

### LED: Neopixel: Flashing On

- Manufacturer: AoT
- Works with: Functions

Start flashing an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller, pixel number, and color.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong> will start flashing the color of the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color in RGB format, each from 0 to 255 (e.g "10, 0, 0")</td></tr></tbody></table>

### MQTT: Publish

- Manufacturer: AoT
- Works with: Functions
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Publish a value to an MQTT server.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will publish the saved payload text options to the MQTT server. Executing <strong>self.run_action("ACTION_ID", value={"payload": 42})</strong> will publish the specified payload (any type) to the MQTT server. You can also specify the topic (e.g. value={"topic": "my_topic", "payload": 42}). Warning: If using multiple MQTT Inputs or Functions, ensure the Client IDs are unique.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Hostname</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>Payload</td><td>Text</td><td>The payload to publish</td></tr><tr><td>Payload Type</td><td>Select(Options: [<strong>Text</strong> | Integer | Float/Decimal] (Default in <strong>bold</strong>)</td><td>The type to cast the payload</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_KxKxkCAE</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>Password</td><td>Text</td><td>Password for connecting to the server</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### MQTT: Publish: Measurement

- Manufacturer: AoT
- Works with: Inputs
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Publish an Input measurement to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>Hostname</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_VliOX51V</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>Password</td><td>Text</td><td>Password for connecting to the server.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### Measurement: Function

- Manufacturer: AoT
- Works with: Functions

Register a Function measurement to include in the AoT Average function. Select computed output values from other functions. This action is not executed; it only stores the measurement selection.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement: Function</td><td>Select Measurement (Function)</td><td>Function computed measurement to include in the average calculation</td></tr><tr><td>Max Age (seconds)</td><td>Integer
- Default Value: 360</td><td>Measurements older than this value (seconds) will be excluded from the average</td></tr></tbody></table>

### Measurement: Input

- Manufacturer: AoT
- Works with: Functions

Register an Input measurement to include in the AoT Average function. This action is not executed; it only stores the measurement selection.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement: Input</td><td>Select Measurement (Input)</td><td>Input sensor measurement to include in the average calculation</td></tr><tr><td>Max Age (seconds)</td><td>Integer
- Default Value: 360</td><td>Measurements older than this value (seconds) will be excluded from the average</td></tr></tbody></table>

### Measurement: Output

- Manufacturer: AoT
- Works with: Functions

Register an Output measurement to include in the AoT Average function. Select Output channel measurements such as duration. This action is not executed; it only stores the measurement selection.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement: Output</td><td>Select Measurement (Output_Channels_Measurements)</td><td>Output channel measurement to include in the average calculation (e.g. duration)</td></tr><tr><td>Max Age (seconds)</td><td>Integer
- Default Value: 360</td><td>Measurements older than this value (seconds) will be excluded from the average</td></tr></tbody></table>

### Output: Actuator Paired (Position / Stop)

- Manufacturer: AoT
- Works with: Functions

Drive an Actuator Paired output to a target position (0–100 %) or send a Stop command.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> drives the actuator to the configured position. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "UUID", "channel": 0, "command": "set_position", "position": 75})</strong> drives the Actuator Paired output with the given ID to 75 %. Use <strong>"command": "stop"</strong> to halt motion immediately.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Actuator Paired Output</td><td>Select Channel (Output_Channels)</td><td>Select the Actuator Paired output channel to control.</td></tr><tr><td>Command</td><td>Select(Options: [<strong>Set Position (%)</strong> | Stop] (Default in <strong>bold</strong>)</td><td>"Set Position" drives the actuator to the target %. "Stop" halts motion immediately.</td></tr><tr><td>Target Position (%)</td><td>Decimal</td><td>0 = fully closed, 100 = fully open. Used only when Command is "Set Position".</td></tr></tbody></table>

### Output: Duty Cycle

- Manufacturer: AoT
- Works with: Functions

Set a PWM Output to set a duty cycle.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the PWM output duty cycle. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "duty_cycle": 42})</strong> will set the duty cycle of the PWM output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>Duty cycle for the PWM (percent, 0.0 - 100.0)</td></tr></tbody></table>

### Output: On/Off/Duration

- Manufacturer: AoT
- Works with: Functions

Turn an On/Off Output On, Off, or On for a duration.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate an output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "state": "on", "duration": 300})</strong> will set the state of the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system. If state is on and a duration is set, the output will turn off after the duration.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>State</td><td>Select</td><td>Turn the output on or off</td></tr><tr><td>Duration (Seconds)</td><td>Decimal</td><td>If On, you can set a duration to turn the output on. 0 stays on.</td></tr></tbody></table>

### Output: Ramp Duty Cycle

- Manufacturer: AoT
- Works with: Functions

Ramp a PWM Output from one duty cycle to another duty cycle over a period of time.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will ramp the PWM output duty cycle according to the settings. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "start": 42, "end": 62, "increment": 1.0, "duration": 600})</strong> will ramp the duty cycle of the PWM output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>Duty Cycle: Start</td><td>Decimal</td><td>Duty cycle for the PWM (percent, 0.0 - 100.0)</td></tr><tr><td>Duty Cycle: End</td><td>Decimal
- Default Value: 50.0</td><td>Duty cycle for the PWM (percent, 0.0 - 100.0)</td></tr><tr><td>Increment (Duty Cycle)</td><td>Decimal
- Default Value: 1.0</td><td>How much to change the duty cycle every Duration</td></tr><tr><td>Duration (Seconds)</td><td>Decimal</td><td>How long to ramp from start to finish.</td></tr></tbody></table>

### Output: Value

- Manufacturer: AoT
- Works with: Functions

Send a value to the Output.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate a value output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "value": 42})</strong> will send a value to the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>Value</td><td>Decimal</td><td>The value to send to the output</td></tr></tbody></table>

### Output: Volume

- Manufacturer: AoT
- Works with: Functions

Instruct the Output to dispense a volume.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate a volume output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "volume": 42})</strong> will send a volume to the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>Volume</td><td>Decimal</td><td>The volume to send to the output</td></tr></tbody></table>

### PID: Lower: Setpoint

- Manufacturer: AoT
- Works with: Functions

Lower the Setpoint of a PID.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will lower the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong> will lower the setpoint of the PID with the specified ID. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the PID Controller to lower the setpoint of</td></tr><tr><td>Lower Setpoint</td><td>Decimal</td><td>The amount to lower the PID setpoint by</td></tr></tbody></table>

### PID: Pause

- Manufacturer: AoT
- Works with: Functions

Pause a PID.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong> will pause the PID Controller with the specified ID.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the PID Controller to pause</td></tr></tbody></table>

### PID: Raise: Setpoint

- Manufacturer: AoT
- Works with: Functions

Raise the Setpoint of a PID.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will raise the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong> will raise the setpoint of the PID with the specified ID. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the PID Controller to raise the setpoint of</td></tr><tr><td>Raise Setpoint</td><td>Decimal</td><td>The amount to raise the PID setpoint by</td></tr></tbody></table>

### PID: Resume

- Manufacturer: AoT
- Works with: Functions

Resume a PID.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will resume the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong> will resume the PID Controller with the specified ID.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the PID Controller to resume</td></tr></tbody></table>

### PID: Set Method

- Manufacturer: AoT
- Works with: Functions

Select a method to set the PID to use.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "method_id": "fe8b8f41-131b-448d-ba7b-00a044d24075"})</strong> will set a method for the PID Controller with the specified IDs. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the PID Controller to apply the method</td></tr><tr><td>Method</td><td>Select Device</td><td>Select the Method to apply to the PID</td></tr></tbody></table>

### PID: Set: Setpoint

- Manufacturer: AoT
- Works with: Functions

Set the Setpoint of a PID.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"setpoint": 42})</strong> will set the setpoint of the PID Controller (e.g. 42). You can also specify the PID ID (e.g. value={"setpoint": 42, "pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"}). Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Controller</td><td>Select Device</td><td>Select the PID Controller to pause</td></tr><tr><td>Setpoint</td><td>Decimal</td><td>The setpoint to set the PID Controller</td></tr></tbody></table>

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
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Camera</td><td>Select Device</td><td>Select the Camera to take a photo with</td></tr><tr><td>E-Mail Address</td><td>Text
- Default Value: email@domain.com</td><td>E-mail recipient(s). Separate multiple with commas.</td></tr></tbody></table>

### System: Restart

- Manufacturer: AoT
- Works with: Functions

Restart the System

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will restart the system in 10 seconds.


### System: Shutdown

- Manufacturer: AoT
- Works with: Functions

Shutdown the System

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will shut down the system in 10 seconds.


### Webhook

- Manufacturer: AoT
- Works with: Functions

Emits a HTTP request when triggered. The first line contains a HTTP verb (GET, POST, PUT, ...) followed by a space and the URL to call. Subsequent lines are optional "name: value"-header parameters. After a blank line, the body payload to be sent follows. {{{message}}} is a placeholder that gets replaced by the message, {{{quoted_message}}} is the message in an URL safe encoding.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will run the Action.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Webhook Request</td></td><td>HTTP request to execute</td></tr></tbody></table>

