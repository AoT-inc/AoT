## Built-In Outputs (System)

### PWM: MQTT Publish

- Manufacturer: AoT
- Output Types: PWM
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish a PWM value to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ホスト名</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>ポート</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>キープアライブ</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_OWKsusPT</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>ユーザー名</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>パスワード</td><td>Text</td><td>Password for connecting to the server.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr><tr><td>Round Integer</td><td>Select(Options: [<strong>No Rounding</strong> | Round Nearest Whole | Round Up | Round Down] (Default in <strong>bold</strong>)</td><td>Round the payload value to an integer.</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>起動値</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>シャットダウン値</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>信号を反転</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>保存された信号を反転</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### オン オフ: MQTT Publish Multi

- Manufacturer: AoT
- Interfaces: IP
- Output Types: On/Off
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish "on"/"off" payloads to a control topic for multiple channels, and subscribe to a status topic to reflect each channel's actual operating state. All channels share the same broker connection and the two topics. Each channel sends its own control payload and matches its own status payload values. Increase the channel count and save to add channels.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>チャネル数</td><td>Integer
- Default Value: 1</td><td>Number of channels. Save to add or remove channel rows.</td></tr><tr><td>ホスト名</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>ポート</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>制御トピック</td><td>Text
- Default Value: paho/test/control</td><td>The MQTT topic used to publish on/off commands (control direction).</td></tr><tr><td>状態トピック</td><td>Text
- Default Value: paho/test/status</td><td>The MQTT topic to subscribe to for confirming each channel's operating state. Leave blank to disable status feedback.</td></tr><tr><td>キープアライブ</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_ZPSJWnro</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>ユーザー名</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>パスワード</td><td>Text</td><td>Password for connecting to the server. Leave blank to disable.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr><tr><td>コマンドタイムアウト（秒）</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>チャンネル名</td><td>Text</td><td>A friendly name shown in the UI for this channel.</td></tr><tr><td>Onペイロード (制御)</td><td>Text
- Default Value: on</td><td>The payload published to the Control Topic to turn this channel ON.</td></tr><tr><td>Offペイロード (制御)</td><td>Text
- Default Value: off</td><td>The payload published to the Control Topic to turn this channel OFF.</td></tr><tr><td>Onペイロード (状態)</td><td>Text</td><td>When this exact value is received on the Status Topic, the channel is marked ON. Leave blank to disable ON detection for this channel.</td></tr><tr><td>Offペイロード (状態)</td><td>Text</td><td>When this exact value is received on the Status Topic, the channel is marked OFF. Leave blank to disable OFF detection for this channel.</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the channel state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the channel state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the channel switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: MQTT Publish

- Manufacturer: AoT
- Interfaces: IP
- Output Types: On/Off
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish "on" or "off" (or any other strings of your choosing) to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ホスト名</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>ポート</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>キープアライブ</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_sXxbFx3V</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>オンペイロード</td><td>Text
- Default Value: on</td><td>The payload to send when turned on</td></tr><tr><td>オフペイロード</td><td>Text
- Default Value: off</td><td>The payload to send when turned off</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>ユーザー名</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>パスワード</td><td>Text</td><td>Password for connecting to the server. Leave blank to disable.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

### 値: Actuator Paired (Shared Bus)

- Manufacturer: AoT
- Output Types: Value

開/閉リレーを他のアクチュエーターと共有し、各アクチュエーターが自分のセレクターリレーでバスに接続される換気窓・カーテン・バルブの時間ベース開度制御（0–100%）です。6チャンネルリレーボードで4つの窓を制御できます。アクチュエーターごとにこの出力を追加し、同じ開/閉チャンネルを指定すると互いに自動でスケジュール調整されます。セレクター接点は共有バスが無通電のときのみ開閉されます。専用の開/閉リレーを持つ場合は「Actuator Paired」を使用してください。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>アクチュエーター種類</td><td>Select(Options: [<strong>側面換気口</strong> | 屋根換気口 | 保温カーテン | 遮光カーテン | ボールバルブ] (Default in <strong>bold</strong>)</td><td>制御中のアクチュエーターの種類。</td></tr><tr><td>出力: セレクター</td><td>Select Channel (Output_Channels)</td><td>共有バスをこのアクチュエーターに接続する on/off 出力チャンネルです。バスが通電する前にオンになり、バスが停止した後にオフになるため、負荷がかかった状態で開閉されません。このアクチュエーターがバスを専有する場合のみ空欄にしてください。</td></tr><tr><td>出力: 開（共有バス）</td><td>Select Channel (Output_Channels)</td><td>開（OPEN）リレーに接続された on/off 出力チャンネルです。同じ開/閉チャンネルを指定したアクチュエーターは1つのバスを共有し、互いにスケジュール調整されます。</td></tr><tr><td>出力: 閉（共有バス）</td><td>Select Channel (Output_Channels)</td><td>閉（CLOSE）リレーに接続された on/off 出力チャンネルです。同じ開/閉チャンネルを指定したアクチュエーターは1つのバスを共有し、互いにスケジュール調整されます。</td></tr><tr><td>開放移動時間 (秒)</td><td>Decimal</td><td>完全に閉じた状態(0%)から完全に開いた状態(100%)まで移動するのにかかる時間(秒)です。未設定の場合、閉鎖移動時間が代替値として使用されます。下部のキャリブレーションボタンを使用すると自動で測定できます。</td></tr><tr><td>閉鎖移動時間 (秒)</td><td>Decimal</td><td>完全に開いた状態(100%)から完全に閉じた状態(0%)まで移動するのにかかる時間(秒)です。未設定の場合、開放移動時間が代替値として使用されます。</td></tr><tr><td>リミットスイッチあり</td><td>Boolean
- Default Value: True</td><td>このアクチュエーターの両端にリミットスイッチがある場合に有効にします。終端目標（0%、100%）を計算上の走行時間より長く駆動できるようになり、複数のアクチュエーターが1回のバス運転で終端に到達します — 全窓の緊急閉鎖が窓ごとではなく1回で完了します。リミットスイッチがない場合はモーターが拘束されるため無効にしてください。</td></tr><tr><td>並列駆動を許可</td><td>Boolean
- Default Value: True</td><td>同じバスで同じリレーを駆動する他のアクチュエーターと同時に動作させます。バスと電源がそれらのモーターを同時に賄える場合のみ有効にしてください。逆方向はこの設定に関係なく同時駆動されません。同じバス上のアクチュエーターが1つでもこれを無効にすると、バス全体が1台ずつ動作します。</td></tr><tr><td>バッチ収集時間 (秒)</td><td>Decimal
- Default Value: 2.0</td><td>この時間内に届いたコマンドをまとめて計画します。バス上の全アクチュエーターを対象とする制御サイクルが、個別移動の待ち行列ではなく1つのバッチになります。</td></tr><tr><td>セレクター整定時間 (秒)</td><td>Decimal
- Default Value: 0.5</td><td>セレクターリレーが切り替わってから共有バスに通電するまでの待ち時間です（バス停止後、セレクターを解放する前にも同様に適用）。接点が負荷のかかった状態で開閉されないようにします。</td></tr><tr><td>リレー確認タイムアウト (秒)</td><td>Decimal
- Default Value: 15.0</td><td>セレクターまたはバスリレーが新しい状態を報告するまで待つ時間で、超過するとこのアクチュエーターを諦めます。有線リレーは即時に確認され、無線リレーはデバイスが応答した時点で確認されます。未確認のセレクター状態でバスに通電することはありません。</td></tr><tr><td>逆方向一時停止 (秒)</td><td>Decimal
- Default Value: 5.0</td><td>共有バスが方向を変える際（開↔閉）にモーター保護のため挿入される待ち時間です。新しい方向が始まるまで、両方のバスリレーがこの時間オフのままになります。</td></tr><tr><td>起動時にリレーを強制オフ</td><td>Boolean
- Default Value: True</td><td>デーモン起動後、オンと報告しているセレクター・バスリレーをオフにします。走行中に再起動するとモーターが回り続ける可能性があるためです。実際にオンと報告しているリレーにのみコマンドを送るため、トグル方式の出力が誤って作動することはありません。</td></tr><tr><td>開放開始位置 (%)</td><td>Decimal</td><td>参考用（情報表示）です。機構が目視で開き始めるモーター位置（%）です。コマンド値はモーター位置としてそのまま使用され、この項目で再スケールされません。</td></tr><tr><td>全開位置 (%)</td><td>Decimal
- Default Value: 100.0</td><td>参考用（情報表示）です。全開とみなすモーター位置（%）です。コマンド値はこの項目で制限されません。0% のコマンドはこれに関係なく物理的な終端まで移動します（緊急全閉）。</td></tr><tr><td>最小移動ステップ (%)</td><td>Decimal
- Default Value: 5.0</td><td>自動環境制御でモーターの寿命を保護します。目標が最後に送信した位置と最低この分だけ異なる場合にのみモーターが動き、コマンドはこのグリッドに丸められます（例: 5% → 0, 5, 10 …）。0 にすると無効になり、わずかな変動でもモーターが動きます。</td></tr><tr><td>最終位置 (%)</td><td>Decimal</td><td>最後に確認された位置です。移動のたびに自動的に更新されるため、デーモンの再起動後も値が保持されます。実際の位置が分かっている場合のみ手動で編集してください。</td></tr><tr><td>最終目標値 (%)</td><td>Decimal
- Default Value: -1.0</td><td>最後に手動で指令された目標位置です。-1は未設定を意味します。手動設定指令のたびに保存されるため、デーモンの再起動後も目標値が保持されます。</td></tr><tr><td>最小コマンド間隔 (秒)</td><td>Decimal
- Default Value: 1.0</td><td>直前のコマンドからこの秒数以内に届いた新しい目標を拒否します。ボタンの連打でコマンドが溜まり、モーターが激しく往復するのを防ぎます。停止はこの間隔に関係なく常に受け付けられます。</td></tr><tr><td>方向反転</td><td>Boolean</td><td>ソフトウェア上で開リレーと閉リレーを入れ替えます。0% で物理的にアクチュエーターが展開し、100% で戻る配線の場合に有効にしてください。反転したアクチュエーターは互いに逆のリレーに通電するため、反転していないものと並列駆動されません。</td></tr><tr><td>キャリブレーション方向</td><td>Select(Options: [<strong>開く</strong> | 閉じる] (Default in <strong>bold</strong>)</td><td>開始をクリック → アクチュエーターが動作 → 完全に開くか閉じたら停止をクリック → 経過時間が開放移動時間または閉鎖移動時間に保存されます。</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>▶ キャリブレーション開始</td><td>Button</td><td></td></tr><tr><td>■ 停止して保存</td><td>Button</td><td></td></tr></tbody></table>

### 値: Actuator Paired

- Manufacturer: AoT
- Output Types: Value

換気窓、カーテン、ボールバルブの時間ベース開度制御(0〜100%)です。開ける用リレーと閉じる用リレーを1つのパーセンテージ指令に接続します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>アクチュエーター種類</td><td>Select(Options: [<strong>側面換気口</strong> | 屋根換気口 | 保温カーテン | 遮光カーテン | ボールバルブ] (Default in <strong>bold</strong>)</td><td>制御中のアクチュエーターの種類。</td></tr><tr><td>出力: 開く</td><td>Select Channel (Output_Channels)</td><td>開くリレーに接続されたon/off出力チャンネル。</td></tr><tr><td>出力: 閉じる</td><td>Select Channel (Output_Channels)</td><td>閉じるリレーに接続されたon/off出力チャンネル。</td></tr><tr><td>開放移動時間 (秒)</td><td>Decimal</td><td>完全に閉じた状態(0%)から完全に開いた状態(100%)まで移動するのにかかる時間(秒)です。未設定の場合、閉鎖移動時間が代替値として使用されます。下部のキャリブレーションボタンを使用すると自動で測定できます。</td></tr><tr><td>閉鎖移動時間 (秒)</td><td>Decimal</td><td>完全に開いた状態(100%)から完全に閉じた状態(0%)まで移動するのにかかる時間(秒)です。未設定の場合、開放移動時間が代替値として使用されます。</td></tr><tr><td>開放開始位置 (%)</td><td>Decimal</td><td>参考用(情報提供)。機構が視覚的に開き始めるモーター位置(%)です。指令値はモーター位置としてそのまま使用され、このフィールドによって再スケーリングされることはありません — 22%の指令はモーター位置22に直接マッピングされます。</td></tr><tr><td>全開位置 (%)</td><td>Decimal
- Default Value: 100.0</td><td>参考用(情報提供)。完全に開いた状態とみなされるモーター位置(%)です。指令値はモーター位置としてそのまま使用され、このフィールドによって制限されることはありません。0%の指令は常に物理的なエンドストップ(緊急全閉)まで移動します。</td></tr><tr><td>最小移動ステップ (%)</td><td>Decimal
- Default Value: 5.0</td><td>自動環境制御のためのモーター寿命保護機能です。目標値が最後に送信された位置とこの値以上異なる場合にのみモーターが動作し、指令はこのグリッドに合わせて丸められます(例: 5% → 0, 5, 10 …)。これによりPI制御器の周期ごとの小さな変動が吸収され、モーターが毎周期駆動されるのを防ぎます。無効にするには0に設定してください — その場合、わずかな変動でもモーターが駆動されます(従来の動作)。</td></tr><tr><td>最終位置 (%)</td><td>Decimal</td><td>最後に確認された位置です。移動のたびに自動的に更新されるため、デーモンの再起動後も値が保持されます。実際の位置が分かっている場合のみ手動で編集してください。</td></tr><tr><td>最終目標値 (%)</td><td>Decimal
- Default Value: -1.0</td><td>最後に手動で指令された目標位置です。-1は未設定を意味します。手動設定指令のたびに保存されるため、デーモンの再起動後も目標値が保持されます。</td></tr><tr><td>最小コマンド間隔 (秒)</td><td>Decimal
- Default Value: 1.0</td><td>直前の指令からこの秒数以内に到着した新しい開/閉指令を拒否します。連打による指令の積み重ねと急激な反転を防ぎます。停止指令はこの間隔に関わらず常に受け付けられます。</td></tr><tr><td>逆方向一時停止 (秒)</td><td>Decimal
- Default Value: 5.0</td><td>方向を反転(開↔閉)する際にモーターを保護するために挿入される待機時間です。新しい方向が始まる前に、両方のリレーがこの秒数の間OFF状態を維持します。</td></tr><tr><td>方向反転</td><td>Boolean</td><td>開ける用リレーと閉じる用リレーをソフトウェア上で入れ替えます。0%で物理的にアクチュエーターが展開し、100%で引き戻される場合(例: 閉じる=展開として配線された保温カーテン)に有効にしてください。</td></tr><tr><td>キャリブレーション方向</td><td>Select(Options: [<strong>開く</strong> | 閉じる] (Default in <strong>bold</strong>)</td><td>開始をクリック → アクチュエーターが動作 → 完全に開くか閉じたら停止をクリック → 経過時間が開放移動時間または閉鎖移動時間に保存されます。</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>▶ キャリブレーション開始</td><td>Button</td><td></td></tr><tr><td>■ 停止して保存</td><td>Button</td><td></td></tr></tbody></table>

### 値: MQTT Publish

- Manufacturer: AoT
- Output Types: Value
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)
- Additional URL: [Link](http://www.eclipse.org/paho/)

Publish a value to an MQTT server.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ホスト名</td><td>Text
- Default Value: localhost</td><td>The hostname of the MQTT server</td></tr><tr><td>ポート</td><td>Integer
- Default Value: 1883</td><td>The port of the MQTT server</td></tr><tr><td>Topic</td><td>Text
- Default Value: paho/test/single</td><td>The topic to publish with</td></tr><tr><td>キープアライブ</td><td>Integer
- Default Value: 60</td><td>The keepalive timeout value for the client. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_Mpk1emIH</td><td>Unique client ID for connecting to the MQTT server</td></tr><tr><td>オフ値</td><td>Integer</td><td>The value to send when an Off command is given</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>ユーザー名</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>パスワード</td><td>Text</td><td>Password for connecting to the server.</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Encrypt the connection with TLS (broker port is usually 8883). Required when the broker is reachable over the internet.</td></tr><tr><td>TLS CA Certificate</td><td>Text</td><td>Path to the CA certificate file that signed the broker certificate. Leave blank to use the system CA store (for brokers with a publicly-trusted certificate, e.g. Let's Encrypt).</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr></tbody></table>

## Built-In Outputs (Devices)

### On/Off: ChirpStack gRPC

- Interfaces: API
- Output Types: On/Off
- Libraries: requests, paho-mqtt, grpcio (optional)
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

Sends on/off downlink commands via ChirpStack REST/gRPC API. Attempts gRPC first; falls back to REST (/api/devices/<devEui>/queue) if grpcio/chirpstack-api is not installed or unreachable.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ChirpStack gRPC Server</td><td>Text
- Default Value: 127.0.0.1:8080</td><td>Host:port format (e.g., 127.0.0.1:8080) or http(s)://host:port</td></tr><tr><td>API Key</td><td>Text</td><td>Enter the JWT token value (without Bearer prefix)</td></tr><tr><td>DevEUI</td><td>Text</td><td>16-digit hexadecimal DevEUI (separators allowed)</td></tr><tr><td>FPort</td><td>Integer
- Default Value: 15</td><td>指令を受信するLoRaWAN FPort</td></tr><tr><td>Confirmed</td><td>Boolean</td><td>Send command as confirmed (await acknowledgment)</td></tr><tr><td>Payload Format</td><td>Select(Options: [<strong>Hex Bytes</strong> | JSON Object (UTF-8 encoded)] (Default in <strong>bold</strong>)</td><td>Select the payload encoding format</td></tr><tr><td>On Payload</td><td>Text
- Default Value: 000000</td><td>e.g., 010110 (Hex) or JSON string</td></tr><tr><td>Off Payload</td><td>Text
- Default Value: 000000</td><td>e.g., 010210 (Hex) or JSON string</td></tr><tr><td>Enable Debug Logging</td><td>Boolean</td><td>Log connection/enqueue/confirmation notices (INFO/WARNING) for this device. Errors are always logged. Leave off in production.</td></tr><tr><td>コマンドタイムアウト（秒）</td><td>Text
- Default Value: 8</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Startup State</td><td>Select</td><td>State to apply when AoT starts</td></tr><tr><td>Shutdown State</td><td>Select</td><td>State to apply when AoT shuts down</td></tr><tr><td>Force Command</td><td>Boolean</td><td>Always send command regardless of current state</td></tr><tr><td>Trigger Functions at Startup</td><td>Boolean</td><td>Execute trigger function when output switches at startup</td></tr></tbody></table>

### PWM: PCA9685 16-Channel LEDコントローラー

- Manufacturer: NXP Semiconductors
- Interfaces: I<sup>2</sup>C
- Output Types: PWM
- Libraries: adafruit-pca9685
- Dependencies: [adafruit-pca9685](https://pypi.org/project/adafruit-pca9685)
- Manufacturer URL: [Link](https://www.nxp.com/products/power-management/lighting-driver-and-controller-ics/ic-led-controllers/16-channel-12-bit-pwm-fm-plus-ic-bus-led-controller:PCA9685)
- Datasheet URL: [Link](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf)
- Product URL: [Link](https://www.adafruit.com/product/815)

The PCA9685 can output a PWM signal to 16 channels at a frequency between 40 and 1600 Hz.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>周波数（ヘルツ）</td><td>Integer
- Default Value: 1600</td><td>The Herts to output the PWM signal (40 - 1600)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>起動値</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>シャットダウン値</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>信号を反転</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>保存された信号を反転</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### PWM: Python 3 Code

- Interfaces: Python
- Output Types: PWM
- Dependencies: [pylint](https://pypi.org/project/pylint)

Python 3 code will be executed when this output is turned on or off. The "duty_cycle" object is a float value that represents the duty cycle that has been set.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>Analyze your Python code with pylint when saving</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Python 3 Code</td></td><td>Python code to execute to set the PWM duty cycle (%)</td></tr><tr><td>ユーザー</td><td>Text
- Default Value: aot</td><td>コマンドを実行するユーザー</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>起動値</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>シャットダウン値</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>信号を反転</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>保存された信号を反転</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: PWM
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

A software implementation of PWM using the RPi.GPIO library.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ピン: GPIO (BCM)</td><td>Integer</td><td>状態を制御するピン</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>起動値</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>シャットダウン値</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>周波数（ヘルツ）</td><td>Integer
- Default Value: 1000</td><td>The Hertz to output the PWM signal</td></tr><tr><td>信号を反転</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>保存された信号を反転</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: PWM
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)

See the PWM section of the manual for PWM information and determining which pins may be used for each library option.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ピン: GPIO (BCM)</td><td>Integer</td><td>状態を制御するピン</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>起動値</td><td>Decimal</td><td>The value when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>シャットダウン値</td><td>Decimal</td><td>The value when AoT shuts down</td></tr><tr><td>ライブラリ</td><td>Select(Options: [<strong>Any Pin, <= 40 kHz</strong> | Hardware Pin, <= 30 MHz] (Default in <strong>bold</strong>)</td><td>Which method to produce the PWM signal (hardware pins can produce higher frequencies)</td></tr><tr><td>周波数（ヘルツ）</td><td>Integer
- Default Value: 22000</td><td>The Herts to output the PWM signal (0 - 70,000)</td></tr><tr><td>信号を反転</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>保存された信号を反転</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### PWM: Shell Script

- Interfaces: Shell
- Output Types: PWM
- Libraries: subprocess.Popen

Commands will be executed in the Linux shell by the specified user when the duty cycle is set for this output. The string "((duty_cycle))" in the command will be replaced with the duty cycle being set prior to execution.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>Bashコマンド</td><td>Text
- Default Value: /home/pi/script_pwm.sh ((duty_cycle))</td><td>PWMデューティ比（％）を設定するために実行するコマンド</td></tr><tr><td>ユーザー</td><td>Text
- Default Value: aot</td><td>コマンドを実行するユーザー</td></tr><tr><td>起動状態</td><td>Select</td><td>AoT起動時の状態を設定してください</td></tr><tr><td>起動値</td><td>Decimal</td><td>AoT起動時の値</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>AoT終了時の状態を設定してください</td></tr><tr><td>シャットダウン値</td><td>Decimal</td><td>AoT終了時の値</td></tr><tr><td>信号を反転</td><td>Boolean</td><td>PWM信号を反転</td></tr><tr><td>保存された信号を反転</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>指示があれば現在の状態に関係なくコマンドを常に送信する</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>制御対象デバイスの消費電流</td></tr></tbody></table>

### オン オフ (Virtual Multi-Channel)

- Output Types: On/Off
- Libraries: Internal

A virtual output device for testing. States are stored in memory and have no effect on hardware.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the virtual device</td></tr></tbody></table>

### オン オフ (Virtual Single-Channel)

- Output Types: On/Off
- Libraries: Internal

A single-channel virtual output device for testing. State is stored in memory and has no effect on hardware.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the virtual device</td></tr></tbody></table>

### オン オフ: 52pi EP-0099 4channel Relay (4-Channel board)

- Manufacturer: 52Pi
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)

Controls the 4 channel multichannel relay board.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the relay when aot starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the relay when aot shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Ecowitt Local HTTP

- Interfaces: IP
- Output Types: On/Off
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

EcowittハブのIP、サブデバイスID、モデル(WFC01/02=1、WFC02新ファームウェア=3、AC1100=2)を入力すると、ローカルHTTP API経由でOn/Offを制御できます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Ecowitt Device IP</td><td>Text</td><td>Local IP address of the Ecowitt hub (e.g., 192.168.1.100)</td></tr><tr><td>Ecowitt Sub-device ID</td><td>Text</td><td>ID of WFC01/WFC02/AC1100 (e.g., 11044)</td></tr><tr><td>Ecowitt Device Model</td><td>Select(Options: [WFC01 | <strong>WFC02</strong> | AC1100] (Default in <strong>bold</strong>)</td><td>1=WFC01/大部分のWFC02、3=一部のWFC02(新ファームウェア)、2=AC1100</td></tr><tr><td>Valve Open %</td><td>Integer
- Default Value: 100</td><td>When turning on, open valve to this percent (0-100)</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 60</td><td>How often to query the state of the output</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr></tbody></table>

### オン オフ: Grove Multichannel Relay (4- or 8-Channel board)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.seeedstudio.com/Grove-4-Channel-SPDT-Relay-p-3119.html)
- Datasheet URL: [Link](http://wiki.seeedstudio.com/Grove-4-Channel_SPDT_Relay/)
- Product URL: [Link](https://www.seeedstudio.com/Grove-4-Channel-SPDT-Relay-p-3119.html)

Controls the 4 or 8 channel Grove multichannel relay board.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the relay when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the relay when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Kasa HS300 6-Outlet WiFi Power Strip (old library, deprecated)

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-wi-fi-power-strip-hs300)

This output controls the 6 outlets of the Kasa HS300 Smart WiFi Power Strip. This module uses an outdated python library and is deprecated. Do not use it. You will break the current Kasa modules if you do not delete this deprecated Output.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ホスト</td><td>Text
- Default Value: 192.168.0.50</td><td>ホストまたはIPアドレス</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 60</td><td>The period between checking if connected and output states.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text
- Default Value: Outlet Name</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Kasa HS300 6-Outlet WiFi Power Strip

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-wi-fi-power-strip-hs300)

This output controls the 6 outlets of the Kasa HS300 Smart WiFi Power Strip. This is a variant that uses the latest python-kasa library. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ホスト</td><td>Text
- Default Value: 0.0.0.0</td><td>ホストまたはIPアドレス</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18099</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text
- Default Value: Outlet Name</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Kasa KP303 3-Outlet WiFi Power Strip (old library, deprecated)

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa)
- Manufacturer URL: [Link](https://www.tp-link.com/au/home-networking/smart-plug/kp303/)

This output controls the 3 outlets of the Kasa KP303 Smart WiFi Power Strip. This module uses an outdated python library and is deprecated. Do not use it. You will break the current Kasa modules if you do not delete this deprecated Output.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ホスト</td><td>Text
- Default Value: 192.168.0.50</td><td>ホストまたはIPアドレス</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 60</td><td>The period between checking if connected and output states.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text
- Default Value: Outlet Name</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Kasa KP303 3-Outlet WiFi Power Strip

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.tp-link.com/au/home-networking/smart-plug/kp303/)

This output controls the 3 outlets of the Kasa KP303 Smart WiFi Power Strip. This is a variant that uses the latest python-kasa library. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ホスト</td><td>Text
- Default Value: 0.0.0.0</td><td>ホストまたはIPアドレス</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18039</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text
- Default Value: Outlet Name</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Kasa WiFi Power Plug

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-plug-slim-energy-monitoring-kp115)

This output controls Kasa WiFi Power Plugs, including the KP105, KP115, KP125, KP401, HS100, HS103, HS105, HS107, and HS110. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ホスト</td><td>Text
- Default Value: 0.0.0.0</td><td>ホストまたはIPアドレス</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18361</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td>コマンドタイムアウト（秒）</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Kasa WiFi RGB Light Bulb

- Manufacturer: TP-Link
- Interfaces: IP
- Output Types: On/Off
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-lighting/kasa-smart-light-bulb-multicolor-kl125)

This output controls the the Kasa WiFi Light Bulbs, including the KL125, KL130, and KL135. Note: if you see errors in the daemon log about the server starting, try changing the Asyncio RPC Port to another port.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>ホスト</td><td>Text
- Default Value: 0.0.0.0</td><td>ホストまたはIPアドレス</td></tr><tr><td>Status Update (Seconds)</td><td>Text
- Default Value: 300</td><td>The period between checking if connected and output states. 0 disables.</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18749</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Transition (ミリ秒)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>明るさ (パーセント)</td><td>Integer</td><td>The brightness to set, in percent (0 - 100)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (ミリ秒)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>色相 (度)</td><td>Integer</td><td>The hue to set, in degrees (0 - 360)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (ミリ秒)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>彩度 (パーセント)</td><td>Integer</td><td>The saturation to set, in percent (0 - 100)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (ミリ秒)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>色温度 (ケルビン)</td><td>Integer</td><td>The color temperature to set, in degrees Kelvin</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (ミリ秒)</td><td>Integer
- Default Value: 0</td><td>The hsv transition period</td></tr><tr><td>HSV</td><td>Text
- Default Value: 220, 20, 45</td><td>The hue, saturation, brightness to set, e.g. "200, 20, 50"</td></tr><tr><td>Set</td><td>Button</td><td></td></tr><tr><td>Transition (ミリ秒)</td><td>Integer
- Default Value: 1000</td><td>The transition period</td></tr><tr><td>オン</td><td>Button</td><td></td></tr><tr><td>Transition (ミリ秒)</td><td>Integer
- Default Value: 1000</td><td>The transition period</td></tr><tr><td>オフ</td><td>Button</td><td></td></tr></tbody></table>

### オン オフ: MCP23017 16-Channel I/Oエクスパンダー

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Dependencies: [swig](https://packages.debian.org/search?keywords=swig), [liblgpio-dev](https://packages.debian.org/search?keywords=liblgpio-dev), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp230xx](https://pypi.org/project/adafruit-circuitpython-mcp230xx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/MCP23017)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/devicedoc/20001952c.pdf)
- Product URL: [Link](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG)

Controls the 16 channels of the MCP23017.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Modbus TCP Coil (PLC)

- Manufacturer: Modbus
- Interfaces: IP
- Output Types: On/Off
- Libraries: pymodbus
- Dependencies: [pymodbus](https://pypi.org/project/pymodbus)

Modbus TCP 装置（PLC、リレーボード、ゲートウェイ）のコイルを制御します。1 チャンネルが1 つのコイルアドレスです。コマンドのたびにコイルを読み戻して実際に変わったかを確認し、値が異なれば失敗として報告します。同じホストとポートを指す入力・出力は自動的に 1 本の接続を共有します。読み戻しは PLC のレジスタを確認するだけで、リレーや配線が動いたかは確認できません。Modbus には認証も暗号化もないため、装置は隔離されたネットワークに置いてください。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>チャネル数</td><td>Integer
- Default Value: 1</td><td>制御するコイルの数。保存するとチャンネル行が追加・削除されます。</td></tr><tr><td>ホスト</td><td>Text</td><td>Modbus TCP 装置の IP アドレスまたはホスト名</td></tr><tr><td>ポート</td><td>Integer
- Default Value: 502</td><td>Modbus TCP 装置の TCP ポート（標準: 502）</td></tr><tr><td>単位ID</td><td>Integer
- Default Value: 1</td><td>装置の Modbus ユニット/スレーブ ID。装置を直接指定する場合は通常 1、シリアルゲートウェイ経由ならそのスレーブアドレスです</td></tr><tr><td>タイムアウト（秒）</td><td>Decimal
- Default Value: 1.0</td><td>応答を待つ時間。1 回の要求は最大でタイムアウト x (リトライ + 1) かかり、コマンド 1 つは要求を 2 回送ります</td></tr><tr><td>リトライ</td><td>Integer
- Default Value: 1</td><td>失敗と扱うまでの要求ごとのリトライ回数。低く保ってください — 値が大きいと応答のない装置がコマンドを占有する時間もその分だけ倍になります</td></tr><tr><td>コマンドタイムアウト（秒）</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>チャンネル名</td><td>Text</td><td>このチャンネルを画面に表示する名前です。</td></tr><tr><td>コイルアドレス</td><td>Integer</td><td>制御するコイルの 0 から数えるアドレス。ベンダー文書は 1 から数えるアドレスを使うことが多いため（例: coil 0 を 00001 と表記）、レジスタマップと照合してください</td></tr><tr><td>起動状態</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>AoT の起動時にチャンネルの状態を設定します。「何もしない」は PLC が持つコイルの状態をそのままにして読み取るだけです</td></tr><tr><td>シャットダウン状態</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>AoT の終了時にチャンネルの状態を設定します</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>起動時にチャンネルが切り替わったときに関数を実行するかどうか</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>指示があれば現在の状態に関係なくコマンドを常に送信する</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>制御対象デバイスの消費電流</td></tr></tbody></table>

### オン オフ: Neopixel (WS2812) RGB Strip with Raspberry Pi

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
- Default Value: 20</td><td>The maximum brightness of LEDs in Rainbow Mode (1 - 255)</td></tr><tr><td>Rainbow Mode</td><td>Select(Options: [All LEDs change at once | <strong>One LED Changes at a time</strong>] (Default in <strong>bold</strong>)</td><td>How the rainbow is displayed</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>LED Position</td><td>Integer</td><td>Which LED in the strip to change</td></tr><tr><td>RGB Color</td><td>Text
- Default Value: 10, 0, 0</td><td>The color (e.g 10, 0, 0)</td></tr><tr><td>Set</td><td>Button</td><td></td></tr></tbody></table>

### オン オフ: PCF8574 8-Channel I/Oエクスパンダー

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8574)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8574.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

Controls the 8 channels of the PCF8574.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: PCF8575 16-Channel I/Oエクスパンダー

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8575)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8575.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

Controls the 16 channels of the PCF8575.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Python Code

- Interfaces: Python
- Output Types: On/Off
- Dependencies: [pylint](https://pypi.org/project/pylint)

Python 3 code will be executed when this output is turned on or off.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>Analyze your Python code with pylint when saving</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>オンコマンド</td></td><td>出力オンが指示されたときに実行するPythonコード</td></tr><tr><td>オフコマンド</td></td><td>出力オフが指示されたときに実行するPythonコード</td></tr><tr><td>起動状態</td><td>Select</td><td>AoT起動時の状態を設定してください</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>AoT終了時の状態を設定してください</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>起動時に出力が切り替わったときに関数を実行するかどうか</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>指示があれば現在の状態に関係なくコマンドを常に送信する</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>制御対象デバイスの消費電流</td></tr></tbody></table>

### オン オフ: Raspberry Pi GPIO (Pi 5)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: pinctrl

The specified GPIO pin will be set HIGH (3.3 volts) or LOW (0 volts) when turned on or off, depending on the On State option.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ピン: GPIO (BCM)</td><td>Integer</td><td>状態を制御するピン</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

The specified GPIO pin will be set HIGH (3.3 volts) or LOW (0 volts) when turned on or off, depending on the On State option.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ピン: GPIO (BCM)</td><td>Integer</td><td>状態を制御するピン</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Sequent Microsystems 8-Relay HAT for Raspberry Pi

- Manufacturer: Sequent Microsystems
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://sequentmicrosystems.com)
- Datasheet URL: [Link](https://cdn.shopify.com/s/files/1/0534/4392/0067/files/8-RELAYS-UsersGuide.pdf?v=1642820552)
- Product URL: [Link](https://sequentmicrosystems.com/products/8-relays-stackable-card-for-raspberry-pi)

Controls the 8 relays of the 8-relay HAT made by Sequent Microsystems. 8 of these boards can be used simultaneously, allowing 64 relays to be controlled.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Board Stack Number</td><td>Select</td><td>Select the board stack number when multiple boards are used</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Shell Script

- Output Types: On/Off
- Libraries: subprocess.Popen

Commands will be executed in the Linux shell by the specified user when this output is turned on or off.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>オンコマンド</td><td>Text
- Default Value: /home/pi/script_on_off.sh on</td><td>Command to execute when the output is instructed to turn on</td></tr><tr><td>オフコマンド</td><td>Text
- Default Value: /home/pi/script_on_off.sh off</td><td>Command to execute when the output is instructed to turn off</td></tr><tr><td>ユーザー</td><td>Text
- Default Value: aot</td><td>コマンドを実行するユーザー</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: Sparkfun Relay Board (4 Relays)

- Manufacturer: Sparkfun
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: sparkfun-qwiic-relay
- Dependencies: [sparkfun-qwiic-relay](https://pypi.org/project/sparkfun-qwiic-relay)
- Manufacturer URL: [Link](https://www.sparkfun.com)
- Product URLs: [Link 1](https://www.sparkfun.com/products/16833), [Link 2](https://www.sparkfun.com/products/16566)

Controls the 4 relays of the relay module.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: XL9535 16-Channel I/Oエクスパンダー

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link]()
- Datasheet URL: [Link]()
- Product URL: [Link]()

Controls the 16 channels of the XL9535.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state of the GPIO when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state of the GPIO when AoT shuts down</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### オン オフ: ワイヤレス 315/433 MHz (Pi <= 4)

- Interfaces: GPIO
- Output Types: On/Off
- Libraries: rpi-rf
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO), [rpi_rf](https://pypi.org/project/rpi_rf)

This output uses a 315 or 433 MHz transmitter to turn wireless power outlets on or off. Run /opt/AoT/aot/devices/wireless_rpi_rf.py with a receiver to discover the codes produced from your remote.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ピン: GPIO (BCM)</td><td>Integer</td><td>状態を制御するピン</td></tr><tr><td>オンコマンド</td><td>Text
- Default Value: 22559</td><td>出力がオンに指示されたときに実行するコマンド</td></tr><tr><td>オフコマンド</td><td>Text
- Default Value: 22558</td><td>出力がオフに指示されたときに実行するコマンド</td></tr><tr><td>プロトコル</td><td>Select(Options: [<strong>1</strong> | 2 | 3 | 4 | 5] (Default in <strong>bold</strong>)</td><td></td></tr><tr><td>パルス長</td><td>Integer
- Default Value: 189</td><td></td></tr><tr><td>起動状態</td><td>Select</td><td>AoT起動時の状態を設定してください</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>AoT終了時の状態を設定してください</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>起動時に出力が切り替わったときに関数を実行するかどうか</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>現在の状態に関係なくコマンドを常に送信する</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>制御対象デバイスの消費電流</td></tr></tbody></table>

### スペーサー


A spacer to organize Outputs.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>色</td><td>Text
- Default Value: #000000</td><td>The color of the name text</td></tr></tbody></table>

### デジタル・アナログ変換器: MCP4728

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp4728](https://pypi.org/project/adafruit-circuitpython-mcp4728)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en541737)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/DeviceDoc/22187E.pdf)
- Product URL: [Link](https://www.adafruit.com/product/4470)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 4.096</td><td>Set the VREF voltage</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>VREF</td><td>Select(Options: [<strong>Internal</strong> | VDD] (Default in <strong>bold</strong>)</td><td>Select the channel VREF</td></tr><tr><td>Gain</td><td>Select(Options: [<strong>1X</strong> | 2X] (Default in <strong>bold</strong>)</td><td>Select the channel Gain</td></tr><tr><td>Start State</td><td>Select(Options: [<strong>Previously-Saved State</strong> | Specified Value] (Default in <strong>bold</strong>)</td><td>Select the channel start state</td></tr><tr><td>Start Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the start state value</td></tr><tr><td>Shutdown State</td><td>Select(Options: [<strong>Previously-Saved Value</strong> | Specified Value] (Default in <strong>bold</strong>)</td><td>Select the channel shutdown state</td></tr><tr><td>Shutdown Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the shutdown state value</td></tr></tbody></table>

### デジタル分圧器: DS3502

- Manufacturer: Maxim Integrated
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit_Extended_Bus](https://pypi.org/project/Adafruit_Extended_Bus), [adafruit-circuitpython-ds3502](https://pypi.org/project/adafruit-circuitpython-ds3502)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/analog/data-converters/digital-potentiometers/DS3502.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS3502.pdf)
- Product URL: [Link](https://www.adafruit.com/product/4286)

The DS3502 can generate a 0 - 10k Ohm resistance with 7-bit precision. This equates to 128 possible steps. A value, in Ohms, is passed to this output controller and the step value is calculated and passed to the device. Select whether to round up or down to the nearest step.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Round Step</td><td>Select(Options: [<strong>Up</strong> | Down] (Default in <strong>bold</strong>)</td><td>Round direction to the nearest step value</td></tr></tbody></table>

### ペリスタルティックポンプ: Atlas Scientific

- Manufacturer: Atlas Scientific
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Output Types: Volume, On/Off
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/peristaltic/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO_PMP_Datasheet.pdf)
- Product URL: [Link](https://atlas-scientific.com/peristaltic/ezo-pmp/)

Atlas Scientific peristaltic pumps can be set to dispense at their maximum rate or a rate can be specified. Their minimum flow rate is 0.5 ml/min and their maximum is 105 ml/min.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDIデバイス</td><td>Text</td><td>入力 出力等に接続されたFTDIデバイス</td></tr><tr><td>UARTデバイス</td><td>Text</td><td>UARTデバイスの場所 (例: /dev/ttyUSB1)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Calibration: a calibration can be performed to increase the accuracy of the pump. It's a good idea to clear the calibration before calibrating. First, remove all air from the line by pumping the fluid you would like to calibrate to through the pump hose. Next, press Dispense Amount and the pump will be instructed to dispense 10 ml (unless you changed the default value). Measure how much fluid was actually dispensed, enter this value in the Actual Volume Dispensed (ml) field, and press Calibrate to Dispensed Amount. Now any further pump volumes dispensed should be accurate.</td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td>Volume to Dispense (ml)</td><td>Decimal
- Default Value: 10.0</td><td>The volume (ml) that is instructed to be dispensed</td></tr><tr><td>Dispense Amount</td><td>Button</td><td></td></tr><tr><td>Actual Volume Dispensed (ml)</td><td>Decimal
- Default Value: 10.0</td><td>The actual volume (ml) that was dispensed</td></tr><tr><td>Calibrate to Dispensed Amount</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>新規I2Cアドレス</td><td>Text
- Default Value: 0x67</td><td>デバイスに設定する新しいI2Cアドレス</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### ペリスタルティックポンプ: Grove I2C Motor Driver (Board v1.3)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wiki.seeedstudio.com/Grove-I2C_Motor_Driver_V1.3)

Controls the Grove I2C Motor Driver Board (v1.3). Both motors will turn at the same time. This output can also dispense volumes of fluid if the motors are attached to peristaltic pumps.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>Motor Speed (0 - 100)</td><td>Integer
- Default Value: 100</td><td>The motor output that determines the speed</td></tr><tr><td>流量メソッド</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>一定量をポンプで送る際の流量</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 100.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr></tbody></table>

### ペリスタルティックポンプ: Grove I2C Motor Driver (TB6612FNG, Board v1.0)

- Manufacturer: Grove
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wiki.seeedstudio.com/Grove-I2C_Motor_Driver-TB6612FNG)

Controls the Grove I2C Motor Driver Board (v1.3). Both motors will turn at the same time. This output can also dispense volumes of fluid if the motors are attached to peristaltic pumps.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>Motor Speed (0 - 255)</td><td>Integer
- Default Value: 255</td><td>The motor output that determines the speed</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 100.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump turns on for every 60 second period (only used for Specify Flow Rate mode).</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>新規I2Cアドレス</td><td>Text
- Default Value: 0x14</td><td>The new I2C to set the sensor to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### ペリスタルティックポンプ: L298N DC Motor Controller (Pi 5)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: pinctrl
- Additional URL: [Link](https://www.electronicshub.org/raspberry-pi-l298n-interface-tutorial-control-dc-motor-l298n-raspberry-pi/)

The L298N can control 2 DC motors, and direction. If these motors control peristaltic pumps, set the Flow Rate and the output can can be instructed to dispense volumes accurately in addition to being turned on for durations.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>Input Pin 1</td><td>Integer</td><td>The Input Pin 1 of the controller (BCM numbering)</td></tr><tr><td>Input Pin 2</td><td>Integer</td><td>The Input Pin 2 of the controller (BCM numbering)</td></tr><tr><td>Use Enable Pin</td><td>Boolean
- Default Value: True</td><td>Enable the use of the Enable Pin</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>The Enable pin of the controller (BCM numbering)</td></tr><tr><td>方向</td><td>Select(Options: [<strong>Forward</strong> | Backward] (Default in <strong>bold</strong>)</td><td>The direction to turn the motor</td></tr><tr><td>Volume Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>If a pump, the measured flow rate (ml/min) at the set Duty Cycle</td></tr></tbody></table>

### ペリスタルティックポンプ: L298N DC Motor Controller (Pi <= 4)

- Manufacturer: STMicroelectronics
- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Additional URL: [Link](https://www.electronicshub.org/raspberry-pi-l298n-interface-tutorial-control-dc-motor-l298n-raspberry-pi/)

The L298N can control 2 DC motors, both speed and direction. If these motors control peristaltic pumps, set the Flow Rate and the output can can be instructed to dispense volumes accurately in addition to being turned on for durations.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>Input Pin 1</td><td>Integer</td><td>The Input Pin 1 of the controller (BCM numbering)</td></tr><tr><td>Input Pin 2</td><td>Integer</td><td>The Input Pin 2 of the controller (BCM numbering)</td></tr><tr><td>Use Enable Pin</td><td>Boolean
- Default Value: True</td><td>Enable the use of the Enable Pin</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>The Enable pin of the controller (BCM numbering)</td></tr><tr><td>Enable Pin Duty Cycle</td><td>Integer
- Default Value: 50</td><td>The duty cycle to apply to the Enable Pin (percent, 1 - 100)</td></tr><tr><td>方向</td><td>Select(Options: [<strong>Forward</strong> | Backward] (Default in <strong>bold</strong>)</td><td>The direction to turn the motor</td></tr><tr><td>Volume Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>If a pump, the measured flow rate (ml/min) at the set Duty Cycle</td></tr></tbody></table>

### ペリスタルティックポンプ: MCP23017 16-Channel I/Oエクスパンダー

- Manufacturer: MICROCHIP
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Dependencies: [swig](https://packages.debian.org/search?keywords=swig), [liblgpio-dev](https://packages.debian.org/search?keywords=liblgpio-dev), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mcp230xx](https://pypi.org/project/adafruit-circuitpython-mcp230xx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/MCP23017)
- Datasheet URL: [Link](https://ww1.microchip.com/downloads/en/devicedoc/20001952c.pdf)
- Product URL: [Link](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG)

Controls the 16 channels of the MCP23017 with a relay and peristaltic pump connected to each channel.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the output channel that corresponds to the pump being on</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump should be turned on for every 60 second period</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### ペリスタルティックポンプ: PCF8574 8-Channel I/Oエクスパンダー

- Manufacturer: Texas Instruments
- Interfaces: I<sup>2</sup>C
- Output Types: Volume, On/Off
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.ti.com/product/PCF8574)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/pcf8574.pdf)
- Product URL: [Link](https://www.amazon.com/gp/product/B07JGSNWFF)

Controls the 8 channels of the PCF8574 with a relay and peristaltic pump connected to each channel.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the output channel that corresponds to the pump being on</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump should be turned on for every 60 second period</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>Desired Flow Rate (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### ペリスタルティックポンプ: Raspberry Pi GPIO (Pi <= 4)

- Interfaces: GPIO
- Output Types: Volume, On/Off
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

This output turns a GPIO pin HIGH and LOW to control power to a generic peristaltic pump. The peristaltic pump can then be turned on for a duration or, after determining the pump's maximum flow rate, instructed to dispense a specific volume at the maximum rate or at a specified rate.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td>ピン: GPIO (BCM)</td><td>Integer</td><td>状態を制御するピン</td></tr><tr><td>オン状態</td><td>Select(Options: [<strong>HIGH</strong> | LOW] (Default in <strong>bold</strong>)</td><td>The state of the GPIO that corresponds to an On state</td></tr><tr><td>Fastest Rate (ml/min)</td><td>Decimal
- Default Value: 150.0</td><td>The fastest rate that the pump can dispense (ml/min)</td></tr><tr><td>Minimum On (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>The minimum duration the pump should be turned on for every 60 second period</td></tr><tr><td>Flow Rate Method</td><td>Select(Options: [<strong>Fastest Flow Rate</strong> | Specify Flow Rate] (Default in <strong>bold</strong>)</td><td>The flow rate to use when pumping a volume</td></tr><tr><td>希望流量 (ml/min)</td><td>Decimal
- Default Value: 10.0</td><td>Desired flow rate in ml/minute when Specify Flow Rate set</td></tr><tr><td>電流 (アンペア)</td><td>Decimal</td><td>The current draw of the device being controlled</td></tr></tbody></table>

### モーター: ULN2003 ステッピングモーター, ユニポーラ (Pi <= 4)

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

### モーター: ステッピングモーター, バイポーラ (一般的) (Pi <= 4)

- Interfaces: GPIO
- Output Types: Value
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URLs: [Link 1](https://www.ti.com/product/DRV8825), [Link 2](https://www.allegromicro.com/en/products/motor-drivers/brush-dc-motor-drivers/a4988)
- Datasheet URLs: [Link 1](https://www.ti.com/lit/ds/symlink/drv8825.pdf), [Link 2](https://www.allegromicro.com/-/media/files/datasheets/a4988-datasheet.ashx)
- Product URLs: [Link 1](https://www.pololu.com/product/2133), [Link 2](https://www.pololu.com/product/1182)

This is a generic module for bipolar stepper motor drivers such as the DRV8825, A4988, and others. The value passed to the output is the number of steps. A positive value turns clockwise and a negative value turns counter-clockwise.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td colspan="3">Channel Options</td></tr><tr><td colspan="3">If the Direction or Enable pins are not used, make sure you pull the appropriate pins on your driver high or low to set the proper direction and enable the stepper motor to be energized. Note: For Enable Mode, always having the motor energized will use more energy and produce more heat.</td></tr><tr><td>Step Pin</td><td>Integer</td><td>The Step pin of the controller (BCM numbering)</td></tr><tr><td>Full Step Delay</td><td>Decimal
- Default Value: 0.005</td><td>The Full Step Delay of the controller</td></tr><tr><td>Direction Pin</td><td>Integer</td><td>The Direction pin of the controller (BCM numbering). 無効にするには None に設定してください</td></tr><tr><td>Enable Pin</td><td>Integer</td><td>The Enable pin of the controller (BCM numbering). 無効にするには None に設定してください</td></tr><tr><td>Enable Mode</td><td>Select(Options: [<strong>Only When Turning</strong> | Always] (Default in <strong>bold</strong>)</td><td>Choose when to pull the enable pin high to energize the motor.</td></tr><tr><td>Enable at Shutdown</td><td>Select(Options: [Enable | <strong>Disable</strong>] (Default in <strong>bold</strong>)</td><td>Choose whether the enable pin in pulled high (Enable) or low (Disable) when AoT shuts down.</td></tr><tr><td colspan="3">If using a Step Resolution other than Full, and all three Mode Pins are set, they will be set high (1) or how (0) according to the values in parentheses to the right of the selected Step Resolution, e.g. (Mode Pin 1, Mode Pin 2, Mode Pin 3).</td></tr><tr><td>Step Resolution</td><td>Select(Options: [<strong>Full (modes 0, 0, 0)</strong> | Half (modes 1, 0, 0) | 1/4 (modes 0, 1, 0) | 1/8 (modes 1, 1, 0) | 1/16 (modes 0, 0, 1) | 1/32 (modes 1, 0, 1)] (Default in <strong>bold</strong>)</td><td>The Step Resolution of the controller</td></tr><tr><td>Mode Pin 1</td><td>Integer</td><td>The Mode Pin 1 of the controller (BCM numbering). 無効にするには None に設定してください</td></tr><tr><td>Mode Pin 2</td><td>Integer</td><td>The Mode Pin 2 of the controller (BCM numbering). 無効にするには None に設定してください</td></tr><tr><td>Mode Pin 3</td><td>Integer</td><td>The Mode Pin 3 of the controller (BCM numbering). 無効にするには None に設定してください</td></tr></tbody></table>

### リモート AoT Output: PWM

- Interfaces: API
- Output Types: PWM
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

This Output allows remote control of another AoT PWM Output over a network using the API.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Remote AoT Host</td><td>Text</td><td>リモートAoTのホストまたはIPアドレス（ポートを含められます。例: 192.168.0.9:8084）</td></tr><tr><td>Remote AoT API Key</td><td>Text</td><td>リモートAoTのAPIキー。そのサーバーに表示された値をそのまま入力します</td></tr><tr><td>プロトコル</td><td>Select(Options: [<strong>HTTPS</strong> | HTTP] (Default in <strong>bold</strong>)</td><td>信頼できるネットワークで平文HTTPからのみ到達できる場合を除き、HTTPSを使用してください</td></tr><tr><td>TLS証明書を検証</td><td>Boolean
- Default Value: True</td><td>リモートサーバーの証明書を検証します。信頼できるネットワーク上の自己署名証明書の場合のみ無効にしてください — 無効の間は中間者にAPIキーを読み取られる可能性があります</td></tr><tr><td>リクエストタイムアウト（秒）</td><td>Integer
- Default Value: 60</td><td>デューティ比コマンドのHTTP読み取りタイムアウト。リモートホストで最も時間のかかるコマンドより長く設定してください</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 120</td><td>How often to query the state of the output</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Remote AoT Output</td></td><td>The Remote AoT Output to control</td></tr><tr><td>起動状態</td><td>Select</td><td>Set the state when AoT starts</td></tr><tr><td>Start Duty Cycle</td><td>Decimal</td><td>The duty cycle to set at startup, if enabled</td></tr><tr><td>シャットダウン状態</td><td>Select</td><td>Set the state when AoT shuts down</td></tr><tr><td>Shutdown Duty Cycle</td><td>Decimal</td><td>The duty cycle to set at shutdown, if enabled</td></tr><tr><td>信号を反転</td><td>Boolean</td><td>Invert the PWM signal</td></tr><tr><td>保存された信号を反転</td><td>Boolean</td><td>Invert the value that is saved to the measurement database</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the Duty Cycle.</td></tr><tr><td>Duty Cycle</td><td>Decimal</td><td>The duty cycle to set</td></tr><tr><td>Set Duty Cycle</td><td>Button</td><td></td></tr></tbody></table>

### リモート AoT Output: オン オフ

- Interfaces: API
- Output Types: On/Off
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

This Output allows remote control of another AoT On/Off Output over a network using the API.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Remote AoT Host</td><td>Text</td><td>リモートAoTのホストまたはIPアドレス（ポートを含められます。例: 192.168.0.9:8084）</td></tr><tr><td>Remote AoT API Key</td><td>Text</td><td>リモートAoTのAPIキー。そのサーバーに表示された値をそのまま入力します</td></tr><tr><td>プロトコル</td><td>Select(Options: [<strong>HTTPS</strong> | HTTP] (Default in <strong>bold</strong>)</td><td>信頼できるネットワークで平文HTTPからのみ到達できる場合を除き、HTTPSを使用してください</td></tr><tr><td>TLS証明書を検証</td><td>Boolean
- Default Value: True</td><td>リモートサーバーの証明書を検証します。信頼できるネットワーク上の自己署名証明書の場合のみ無効にしてください — 無効の間は中間者にAPIキーを読み取られる可能性があります</td></tr><tr><td>State Query Period (Seconds)</td><td>Integer
- Default Value: 120</td><td>How often to query the state of the output</td></tr><tr><td>Request Timeout (Seconds)</td><td>Integer
- Default Value: 60</td><td>HTTP read timeout for ON/OFF commands. Must be longer than the slowest command on the remote host (e.g. if the remote command has time.sleep(15), set this to at least 20).</td></tr><tr><td>コマンドタイムアウト（秒）</td><td>Text
- Default Value: 5</td><td>How long to optimistically hold the commanded state while awaiting the device (0 = immediate). For wireless/remote devices set the expected response delay; wired devices can leave this at 0.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Remote AoT Output</td></td><td>The Remote AoT Output to control</td></tr><tr><td>起動状態</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>Set the state when AoT starts</td></tr><tr><td>シャットダウン状態</td><td>Select(Options: [<strong>Do Nothing</strong> | Off | On] (Default in <strong>bold</strong>)</td><td>Set the state when AoT shuts down</td></tr><tr><td>強制コマンド</td><td>Boolean</td><td>Always send the command if instructed, regardless of the current state</td></tr><tr><td>起動時に関数をトリガー</td><td>Boolean</td><td>Whether to trigger functions when the output switches at startup</td></tr></tbody></table>

### 値: GP8XXX (8413, 8403) 2-Channel DAC: 0-10 VDC

- Manufacturer: DFRobot
- Interfaces: I<sup>2</sup>C
- Output Types: Value
- Libraries: GP8XXX-IIC
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [GP8XXX-IIC](https://pypi.org/project/GP8XXX-IIC)
- Datasheet URLs: [Link 1](https://wiki.dfrobot.com/SKU_DFR0971_2_Channel_I2C_0_10V_DAC_Module), [Link 2](https://wiki.dfrobot.com/SKU_DFR1073_2_Channel_15bit_I2C_to_0-10V_DAC)
- Product URLs: [Link 1](https://www.dfrobot.com/product-2613.html), [Link 2](https://www.dfrobot.com/product-2756.html)

Output 0 to 10 VDC signal.                GP8403: 12bit DAC Dual Channel I2C to 0-5V/0-10V |                GP8413: 15bit DAC Dual Channel I2C to 0-10V
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Device</td><td>Select(Options: [<strong>GP8403 12-bit</strong> | GP8413 15-bit] (Default in <strong>bold</strong>)</td><td>Select your GP8XXX device</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Start State</td><td>Select(Options: [Previously-Saved State | <strong>Specified Value</strong>] (Default in <strong>bold</strong>)</td><td>Select the channel start state</td></tr><tr><td>Start Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the start state value</td></tr><tr><td>Shutdown State</td><td>Select(Options: [Previously-Saved Value | <strong>Specified Value</strong>] (Default in <strong>bold</strong>)</td><td>Select the channel shutdown state</td></tr><tr><td>Shutdown Value (volts)</td><td>Decimal</td><td>If Specified Value is selected, set the shutdown state value</td></tr><tr><td>Off Value (volts)</td><td>Decimal</td><td>If Specified Value to apply when turned off</td></tr></tbody></table>

