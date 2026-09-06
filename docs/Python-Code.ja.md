
AoTでは、Pythonコード入力、Pythonコード出力、条件付き機能など、いくつかの場所でPython 3のコードを使用できます。

以下は、Python 3のコードを使ってAoTを操作するいくつかの便利な方法を示す例です。

コードが実行されるすべてのAoT環境では、aot/aot_client.pyに[DaemonControl()クラス](API.md#daemon-control-object)が定義されており、「control」オブジェクトを使ってデーモンと通信できます。

## 出力

### 最小デューティサイクルで回転するPWMファン

PWMで制御されるファンの中には、最小デューティサイクルを設定するまで回転が始まらないものがあります。いったんファンが回転を始めると、デューティサイクルをそれよりかなり低く設定しても回転し続けます。そのため、デューティサイクル0からファンをオンにする場合には「チャージ」フェーズが必要です。このコードは、要求されたデューティサイクルを設定する前にチャージフェーズを実行する必要があるかどうかを判定します。これを行うには、GPIO PWM出力とPythonコードPWM出力が必要です。GPIO PWM出力はファン用に設定し、PythonコードPWM出力には次のコードを設定します:

```python
import time

# Set variables the first time the code runs.
if not hasattr(self, "output_id_gpio_pwm"):
    self.logger.debug("初期化中")
    self.output_id_gpio_pwm = "a3dade60-091a-49d7-9c79-cd2adf41bc23"  # GPIO PWM出力のUUID
    self.fan_spinning = False  # ファンが回転しているかを保持します
    self.fan_min_duty_cycle = 2  # ファンが回り続けられる最小デューティサイクル
    self.fan_spin_duty_cycle = 25  # 停止状態からファンを回し始める最小デューティサイクル
    self.fan_charge_duty_cycle = 45  # ファンを回し始めるために必要なチャージ用デューティサイクル
    self.fan_spin_duration_sec = 1.5  # チャージ用デューティサイクルで回す時間(秒)

# ファンが止まっていて要求されたデューティサイクルが低すぎる場合にチャージします。
if duty_cycle and not self.fan_spinning and duty_cycle < self.fan_spin_duty_cycle:
    self.logger.debug("デューティサイクルが低すぎ、ファンは停止中です。チャージします。")
    self.logger.debug("デューティサイクルを {} % に設定".format(self.fan_charge_duty_cycle))
    control.output_on(self.output_id_gpio_pwm,
                      output_type='pwm',
                      amount=self.fan_charge_duty_cycle,
                      output_channel=0)
    time.sleep(self.fan_spin_duration_sec)
    self.fan_spinning = True

if duty_cycle == 0:
    self.logger.debug("ファンを停止しました")
    self.fan_spinning = False
elif duty_cycle > self.fan_spin_duty_cycle:
    self.fan_spinning = True

self.logger.debug("デューティサイクルを {} % に設定".format(duty_cycle))
control.output_on(self.output_id_gpio_pwm,
                  output_type='pwm',
                  amount=duty_cycle,
                  output_channel=0)
```
