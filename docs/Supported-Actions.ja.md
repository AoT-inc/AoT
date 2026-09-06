## Built-In Actions (System)

### Actions: 一時停止

- Manufacturer: AoT
- Works with: Functions

Set a delay between executing Actions when self.run_all_actions() is used.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will create a pause for the set duration. When <strong>self.run_all_actions()</strong> is executed, this will add a pause in the sequential execution of all actions.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Decimal</td><td>The duration to pause</td></tr></tbody></table>

### Environment Control

- Manufacturer: AoT
- Works with: Functions

統合環境制御（env_coordinator）Functionにアクチュエーターを登録します。複数の装置を登録するには、このアクションを繰り返し追加してください。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Outputチャンネル</td><td>Select Channel (Output_Channels)</td><td>制御するOutputチャンネルを選択してください。</td></tr><tr><td>アクチュエーターの種類</td><td>Select</td><td>このOutputが担う役割を選択してください。</td></tr><tr><td>コスト指数</td><td>Decimal
- Default Value: 5.0</td><td>値が低いほど優先度が高くなります(1 = 無料の自然換気、10 = 高コストの機器)。</td></tr><tr><td>時間制御ウィンドウ終了時</td><td>Select(Options: [<strong>何もしない</strong> | オフにする | オンにする | 開度%を設定(換気窓専用)] (Default in <strong>bold</strong>)</td><td>時間制御ウィンドウが終了したときにこのアクチュエーターに適用する動作です。</td></tr><tr><td>終了時の開度%</td><td>Decimal</td><td>時間ウィンドウが終了したときの目標開度です(換気窓 / 開口部専用)。</td></tr><tr><td>生地の透過率の個別指定 (0-1, 遮光カーテンのみ)</td><td>Decimal</td><td>この遮光カーテンの生地が他と異なるときだけ使います。0 のままなら連動施設に設定した値を使います。室内の光センサーがないとき、外の日射と開度から室内の光量を推定するのに使われます。</td></tr><tr><td>効果係数オーバーライド(K_*)</td><td>Decimal</td><td>0 = デフォルト値を使用。実測データから校正する場合のみ入力してください。例: 冷房機 → K_COOLER_T、噴霧器 → K_FOG_RH。</td></tr><tr><td>全ストローク時間(秒)</td><td>Decimal</td><td>このアクチュエーターが0→100%まで動くのにかかる時間(秒)です。サイクルごとの最大コマンド変化量を制限し、物理的な速度より速い実行不可能なコマンドが送信されないようにするために使用します。0 = 無効(slew_per_cycleの値をそのまま使用)。例: 作動に10分かかる換気窓モーターの場合は600を入力。</td></tr><tr><td>最小繰り返し間隔(秒)</td><td>Decimal</td><td>目標値が変化しない場合でも、このアクチュエーターにコマンドを繰り返し送信する最小間隔(秒)です。0 = システムデフォルトを使用(600秒のウォッチドッグ)。動作の遅いモーター式アクチュエーターでは、リレーの寿命を延ばすために値を大きくしてください。</td></tr></tbody></table>

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
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the energy meter Input</td></tr><tr><td>色相 (度)</td><td>Integer</td><td>The hue to set, in degrees (0 - 360)</td></tr><tr><td>彩度 (パーセント)</td><td>Integer
- Default Value: 50</td><td>The saturation to set, in percent (0 - 100)</td></tr><tr><td>明るさ (パーセント)</td><td>Integer
- Default Value: 50</td><td>The brightness to set, in percent (0 - 100)</td></tr></tbody></table>

### LED: Neopixel: Change Pixel Color

- Manufacturer: AoT
- Works with: Functions

Change the color of an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller, pixel number, and color.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong> will set the color of the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color in RGB format, each from 0 to 255 (e.g "10, 0, 0")</td></tr></tbody></table>

### LED: Neopixel: 点滅オフ

- Manufacturer: AoT
- Works with: Functions

Stop flashing an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller and pixel number.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0})</strong> will stop flashing the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr></tbody></table>

### LED: Neopixel: 点滅オン

- Manufacturer: AoT
- Works with: Functions

Start flashing an LED in a Neopixel LED strip. Select the Neopixel LED Strip Controller, pixel number, and color.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the selected LED to the selected Color. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "led": 0, "color": "10, 10, 0"})</strong> will start flashing the color of the specified LED for the Neopixel LED Strip Controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the controller that modulates your neopixels</td></tr><tr><td>LED Position</td><td>Integer</td><td>The position of the LED on the strip</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color in RGB format, each from 0 to 255 (e.g "10, 0, 0")</td></tr></tbody></table>

### MQTT: パブリッシュ

- Manufacturer: AoT
- Works with: Functions
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Publish a value to an MQTT server.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will publish the saved payload text options to the MQTT server. Executing <strong>self.run_action("ACTION_ID", value={"payload": 42})</strong> will publish the specified payload (any type) to the MQTT server. You can also specify the topic (e.g. value={"topic": "my_topic", "payload": 42}). Warning: If using multiple MQTT Inputs or Functions, ensure the Client IDs are unique.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ホスト名</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>ポート</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>Payload</td><td>Text</td><td>The payload to publish</td></tr><tr><td>Payload Type</td><td>Select(Options: [<strong>Text</strong> | Integer | Float/Decimal] (Default in <strong>bold</strong>)</td><td>The type to cast the payload</td></tr><tr><td>キープアライブ</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_gGCfFGxb</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>ユーザー名</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>パスワード</td><td>Text</td><td>Password for connecting to the server</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### MQTT: 発行: 測定値

- Manufacturer: AoT
- Works with: Inputs
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Publish an Input measurement to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>ホスト名</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>ポート</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>キープアライブ</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_w2TVF6Rb</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>ユーザー名</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>パスワード</td><td>Text</td><td>Password for connecting to the server.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### Output: アクチュエーターペアリング(位置 / 停止)

- Manufacturer: AoT
- Works with: Functions

アクチュエーターペアリング出力を目標位置(0–100 %)まで駆動するか、停止コマンドを送信します。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> drives the actuator to the configured position. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "UUID", "channel": 0, "command": "set_position", "position": 75})</strong> drives the Actuator Paired output with the given ID to 75 %. Use <strong>"command": "stop"</strong> to halt motion immediately.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>アクチュエーターペアリング出力</td><td>Select Channel (Output_Channels)</td><td>制御するアクチュエーターペアリング出力チャンネルを選択してください。</td></tr><tr><td>コマンド</td><td>Select(Options: [<strong>位置を設定(%)</strong> | 停止] (Default in <strong>bold</strong>)</td><td>「位置を設定」はアクチュエーターを目標%まで駆動します。「停止」は動作を即座に停止します。</td></tr><tr><td>目標位置(%)</td><td>Decimal</td><td>0 = 全閉、100 = 全開。コマンドが「位置を設定」の場合のみ使用されます。</td></tr></tbody></table>

### PID: Set Method

- Manufacturer: AoT
- Works with: Functions

Select a method to set the PID to use.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "method_id": "fe8b8f41-131b-448d-ba7b-00a044d24075"})</strong> will set a method for the PID Controller with the specified IDs. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the PID Controller to apply the method</td></tr><tr><td>メソッド</td><td>Select Device</td><td>Select the Method to apply to the PID</td></tr></tbody></table>

### PID: 一時停止

- Manufacturer: AoT
- Works with: Functions

PIDを一時停止します

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong> will pause the PID Controller with the specified ID.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the PID Controller to pause</td></tr></tbody></table>

### PID: 再開

- Manufacturer: AoT
- Works with: Functions

PIDを再開します

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will resume the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value="959019d1-c1fa-41fe-a554-7be3366a9c5b")</strong> will resume the PID Controller with the specified ID.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the PID Controller to resume</td></tr></tbody></table>

### PID: 設定: 設定値

- Manufacturer: AoT
- Works with: Functions

Set the Setpoint of a PID.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"setpoint": 42})</strong> will set the setpoint of the PID Controller (e.g. 42). You can also specify the PID ID (e.g. value={"setpoint": 42, "pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"}). Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the PID Controller to pause</td></tr><tr><td>設定値</td><td>Decimal</td><td>The setpoint to set the PID Controller</td></tr></tbody></table>

### PID：上昇：設定値

- Manufacturer: AoT
- Works with: Functions

PIDの設定値を上げます

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will raise the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong> will raise the setpoint of the PID with the specified ID. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the PID Controller to raise the setpoint of</td></tr><tr><td>設定値上昇</td><td>Decimal</td><td>The amount to raise the PID setpoint by</td></tr></tbody></table>

### PID：下降：設定値

- Manufacturer: AoT
- Works with: Functions

PIDの設定値を下げます

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will lower the setpoint of the selected PID Controller. Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "amount": 2})</strong> will lower the setpoint of the PID with the specified ID. Don't forget to change the pid_id value to an actual PID ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the PID Controller to lower the setpoint of</td></tr><tr><td>下限設定値</td><td>Decimal</td><td>The amount to lower the PID setpoint by</td></tr></tbody></table>

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
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>カメラ</td><td>Select Device</td><td>Select the Camera to take a photo with</td></tr><tr><td>E-Mail Address</td><td>Text
- Default Value: email@domain.com</td><td>E-mail recipient(s). Separate multiple with commas.</td></tr></tbody></table>

### Webhook

- Manufacturer: AoT
- Works with: Functions

Emits a HTTP request when triggered. The first line contains a HTTP verb (GET, POST, PUT, ...) followed by a space and the URL to call. Subsequent lines are optional "name: value"-header parameters. After a blank line, the body payload to be sent follows. {{{message}}} is a placeholder that gets replaced by the message, {{{quoted_message}}} is the message in an URL safe encoding.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will run the Action.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Webhook Request</td></td><td>HTTP request to execute</td></tr></tbody></table>

### カメラ: タイムラプス: 一時停止

- Manufacturer: AoT
- Works with: Functions

Pause a camera time-lapse

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected Camera time-lapse. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will pause the Camera time-lapse with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>カメラ</td><td>Select Device</td><td>Select the Camera to pause the time-lapse</td></tr></tbody></table>

### カメラ: タイムラプス: 再開

- Manufacturer: AoT
- Works with: Functions

Resume a camera time-lapse

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will resume the selected Camera time-lapse. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will resume the Camera time-lapse with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>カメラ</td><td>Select Device</td><td>Select the Camera to resume the time-lapse</td></tr></tbody></table>

### カメラ: 写真を撮影

- Manufacturer: AoT
- Works with: Functions

選択したカメラで写真を撮影します。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will capture a photo with the selected Camera. Executing <strong>self.run_action("ACTION_ID", value={"camera_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will capture a photo with the Camera with the specified ID. Don't forget to change the camera_id value to an actual Camera ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>カメラ</td><td>Select Device</td><td>Select the Camera to take a photo</td></tr></tbody></table>

### コントローラ: 有効化

- Manufacturer: AoT
- Works with: Functions

コントローラを有効にします。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will activate the selected Controller. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will activate the controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the controller to activate</td></tr></tbody></table>

### コントローラ: 無効化

- Manufacturer: AoT
- Works with: Functions

コントローラを無効化します。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will deactivate the selected Controller. Executing <strong>self.run_action("ACTION_ID", value={"controller_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will deactivate the controller with the specified ID. Don't forget to change the controller_id value to an actual Controller ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the controller to deactivate</td></tr></tbody></table>

### システム: シャットダウン

- Manufacturer: AoT
- Works with: Functions

Shutdown the System

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will shut down the system in 10 seconds.


### システム: 再起動

- Manufacturer: AoT
- Works with: Functions

Restart the System

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will restart the system in 10 seconds.


### ディスプレイ：バックライト：色

- Manufacturer: AoT
- Works with: Functions

Set the display backlight color

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will change the backlight color on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "color": "255,0,0"})</strong> will change the backlight color on the controller with the specified ID and color. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>表示</td><td>Select Device</td><td>Select the display to set the backlight color</td></tr><tr><td>Color (RGB)</td><td>Text
- Default Value: 255,0,0</td><td>Color as R,G,B values (e.g. "255,0,0" without quotes)</td></tr></tbody></table>

### 作成: Daemon Log Line

- Manufacturer: AoT
- Works with: Functions

デーモンログにログ行を作成します。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will add a line to the Daemon log. Executing <strong>self.run_action("ACTION_ID", value={"log_level": "info", "log_text": "this is a log line"})</strong> will execute the action with the specified log level and log line text. If a log line text is not specified, then the action message will be used as the text.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Log Level</td><td>Select(Options: [<strong>Info</strong> | Warning | Error | Debug] (Default in <strong>bold</strong>)</td><td>The log level to insert the text into the log</td></tr><tr><td>Log Line Text</td><td>Text
- Default Value: Log Line Text</td><td>The text to insert in the Daemon log</td></tr></tbody></table>

### 作成: ノート

- Manufacturer: AoT
- Works with: Functions

選択したオプションでノートを作成します。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will create a note with the configured options. Executing <strong>self.run_action("ACTION_ID", value={"tags": ["tag1"], "name": "Title", "note": "body", "category": "alarm", "priority": 1})</strong> will override the stored settings. Set <strong>auto_target</strong> to link the note automatically to the parent Function.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>タグ一覧</td></td><td>1つ以上のタグを選択してください</td></tr><tr><td>名前</td><td>Text</td><td>タイトル（空欄の場合、本文の最初の行から自動抽出）</td></tr><tr><td>ノート</td></td><td>ノート本文</td></tr><tr><td>アクションメッセージを本文に含める</td><td>Boolean</td><td>条件/トリガーから渡されたメッセージをノート本文の末尾に追加します</td></tr><tr><td>親Functionへの自動リンク</td><td>Boolean
- Default Value: True</td><td>このアクションの親Function（target_id/target_type）にノートを自動的にリンクします</td></tr><tr><td>カテゴリー</td><td>Select(Options: [<strong>一般</strong> | 観察 | アラーム | メンテナンス] (Default in <strong>bold</strong>)</td><td>ノートのカテゴリー</td></tr><tr><td>優先度</td><td>Select(Options: [<strong>通常</strong> | 高 | 緊急] (Default in <strong>bold</strong>)</td><td>ノートの優先度</td></tr></tbody></table>

### 入力: 測定を強制:

- Manufacturer: AoT
- Works with: Functions

入力の測定を強制実施

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will force acquiring measurements for the selected Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will force acquiring measurements for the Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Input</td><td>Select Device</td><td>Select an Input</td></tr></tbody></table>

### 出力: オン/オフ/期間

- Manufacturer: AoT
- Works with: Functions

オン/オフ出力をオン、オフ、または指定時間オンにします

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate an output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "state": "on", "duration": 300})</strong> will set the state of the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system. If state is on and a duration is set, the output will turn off after the duration.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>状態</td><td>Select</td><td>Turn the output on or off</td></tr><tr><td>期間 (Seconds)</td><td>Decimal</td><td>If On, you can set a duration to turn the output on. 0 stays on.</td></tr></tbody></table>

### 出力: デューティサイクル

- Manufacturer: AoT
- Works with: Functions

Set a PWM Output to set a duty cycle.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will set the PWM output duty cycle. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "duty_cycle": 42})</strong> will set the duty cycle of the PWM output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>デューティサイクル</td><td>Decimal</td><td>PWMのデューティサイクル（パーセント、0.0-100.0）</td></tr></tbody></table>

### 出力: ランプ デューティサイクル

- Manufacturer: AoT
- Works with: Functions

一定時間かけてPWM出力のデューティサイクルを段階的に変更します

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will ramp the PWM output duty cycle according to the settings. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "start": 42, "end": 62, "increment": 1.0, "duration": 600})</strong> will ramp the duty cycle of the PWM output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>デューティサイクル: 開始</td><td>Decimal</td><td>PWMのデューティサイクル（パーセント、0.0-100.0）</td></tr><tr><td>デューティサイクル: 終了</td><td>Decimal
- Default Value: 50.0</td><td>PWMのデューティサイクル（パーセント、0.0-100.0）</td></tr><tr><td>増分 (デューティサイクル)</td><td>Decimal
- Default Value: 1.0</td><td>How much to change the duty cycle every Duration</td></tr><tr><td>期間 (Seconds)</td><td>Decimal</td><td>How long to ramp from start to finish.</td></tr></tbody></table>

### 出力: 体積

- Manufacturer: AoT
- Works with: Functions

出力に量を供給するよう指示します。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate a volume output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "volume": 42})</strong> will send a volume to the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>体積</td><td>Decimal</td><td>The volume to send to the output</td></tr></tbody></table>

### 出力: 値

- Manufacturer: AoT
- Works with: Functions

Send a value to the Output.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will actuate a value output. Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "value": 42})</strong> will send a value to the output with the specified ID and channel. Don't forget to change the output_id value to an actual Output ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Output</td><td>Select Channel (Output_Channels)</td><td>Select an output to control</td></tr><tr><td>値</td><td>Decimal</td><td>The value to send to the output</td></tr></tbody></table>

### 実行: Bash/Shell Command

- Manufacturer: AoT
- Works with: Functions

Linux bashシェルコマンドを実行します。

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will execute the bash command.Executing <strong>self.run_action("ACTION_ID", value={"user": "aot", "command": "/home/pi/my_script.sh on"})</strong> will execute the action with the specified command and user.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ユーザー</td><td>Text
- Default Value: aot</td><td>コマンドを実行するユーザー</td></tr><tr><td>コマンド</td><td>Text
- Default Value: /home/pi/my_script.sh on</td><td>Command to execute</td></tr></tbody></table>

### 方程式 (Single-Measurement)

- Manufacturer: AoT
- Works with: Inputs

Modify a channel value with an equation before storing it in the database.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定</td></td><td>Select the measurement to send as the payload</td></tr><tr><td>方程式</td><td>Text
- Default Value: x-10</td><td>The equation to apply to the value before storing. "x" is the measurement value. Example: x-10</td></tr></tbody></table>

### 流量計：累計をクリア キロワット時 

- Manufacturer: AoT
- Works with: Functions

Clear the total kWh saved for an energy meter Input. The Input must have the Clear Total kWh option. This will also clear all energy stats on the device, not just the total kWh.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will clear the total kWh for the selected energy meter Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will clear the total kWh for the energy meter Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the energy meter Input</td></tr></tbody></table>

### 流量計：累計をクリア 流量 

- Manufacturer: AoT
- Works with: Functions

Clear the total volume saved for a flow meter Input. The Input must have the Clear Total Volume option.

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will clear the total volume for the selected flow meter Input. Executing <strong>self.run_action("ACTION_ID", value={"input_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will clear the total volume for the flow meter Input with the specified ID. Don't forget to change the input_id value to an actual Input ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>コントローラ</td><td>Select Device</td><td>Select the flow meter Input</td></tr></tbody></table>

### 測定: 入力

- Manufacturer: AoT
- Works with: Functions

AoT平均関数に含めるInput測定値を登録します。この操作は実行されず、測定値の選択のみが保存されます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定: 入力</td><td>Select Measurement (Input)</td><td>平均計算に含めるInputセンサー測定値</td></tr><tr><td>最大経過時間 (秒)</td><td>Integer
- Default Value: 360</td><td>この値(秒)より古い測定値は平均から除外されます</td></tr></tbody></table>

### 測定: 出力

- Manufacturer: AoT
- Works with: Functions

AoT平均関数に含めるOutput測定値を登録します。持続時間などのOutputチャンネル測定値を選択してください。この操作は実行されず、測定値の選択のみが保存されます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定: 出力</td><td>Select Measurement (Output_Channels_Measurements)</td><td>平均計算に含めるOutputチャンネル測定値(例: 持続時間)</td></tr><tr><td>最大経過時間 (秒)</td><td>Integer
- Default Value: 360</td><td>この値(秒)より古い測定値は平均から除外されます</td></tr></tbody></table>

### 測定: 機能

- Manufacturer: AoT
- Works with: Functions

AoT平均関数に含めるFunction測定値を登録します。他の関数で計算された出力値を選択してください。この操作は実行されず、測定値の選択のみが保存されます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定: 機能</td><td>Select Measurement (Function)</td><td>平均計算に含めるFunctionの計算測定値</td></tr><tr><td>最大経過時間 (秒)</td><td>Integer
- Default Value: 360</td><td>この値(秒)より古い測定値は平均から除外されます</td></tr></tbody></table>

### 表示: バックライト: オフ

- Manufacturer: AoT
- Works with: Functions

Turn display backlight off

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will turn the backlight off for the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will turn the backlight off for the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>表示</td><td>Select Device</td><td>Select the display to turn the backlight off</td></tr></tbody></table>

### 表示: バックライト: オン

- Manufacturer: AoT
- Works with: Functions

Turn display backlight on

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will turn the backlight on for the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will turn the backlight on for the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>表示</td><td>Select Device</td><td>Select the display to turn the backlight on</td></tr></tbody></table>

### 表示: フラッシング: オフ

- Manufacturer: AoT
- Works with: Functions

Turn display flashing off

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will stop the backlight flashing on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will stop the backlight flashing on the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>表示</td><td>Select Device</td><td>Select the display to stop flashing the backlight</td></tr></tbody></table>

### 表示: フラッシング: オン

- Manufacturer: AoT
- Works with: Functions

Turn display flashing on

Usage: Executing <strong>self.run_action("ACTION_ID")</strong> will start the backlight flashing on the selected display. Executing <strong>self.run_action("ACTION_ID", value={"display_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b"})</strong> will start the backlight flashing on the controller with the specified ID. Don't forget to change the display_id value to an actual Function ID that exists in your system.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>表示</td><td>Select Device</td><td>Select the display to start flashing the backlight</td></tr></tbody></table>

