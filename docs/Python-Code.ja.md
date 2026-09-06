
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
    self.logger.debug("초기화 중")
    self.output_id_gpio_pwm = "a3dade60-091a-49d7-9c79-cd2adf41bc23"  # GPIO PWM Output의 UUID
    self.fan_spinning = False  # 팬의 상태를 저장
    self.fan_min_duty_cycle = 2  # 팬이 계속 회전할 수 있는 최소 듀티 사이클
    self.fan_spin_duty_cycle = 25  # 팬이 꺼져 있을 때 회전을 시작하기 위한 최소 듀티 사이클
    self.fan_charge_duty_cycle = 45  # 팬이 처음 회전하기 위해 필요한 충전 듀티 사이클
    self.fan_spin_duration_sec = 1.5  # 팬을 충전 듀티 사이클로 실행할 시간(초)

# 팬이 회전하지 않고 원하는 듀티 사이클이 너무 낮은 경우 팬을 충전합니다.
if duty_cycle and not self.fan_spinning and duty_cycle < self.fan_spin_duty_cycle:
    self.logger.debug("듀티 사이클이 너무 낮고 팬이 꺼져 있습니다. 충전 중.")
    self.logger.debug("{} %의 듀티 사이클 설정".format(self.fan_charge_duty_cycle))
    control.output_on(self.output_id_gpio_pwm,
                      output_type='pwm',
                      amount=self.fan_charge_duty_cycle,
                      output_channel=0)
    time.sleep(self.fan_spin_duration_sec)
    self.fan_spinning = True

if duty_cycle == 0:
    self.logger.debug("팬이 꺼졌습니다")
    self.fan_spinning = False
elif duty_cycle > self.fan_spin_duty_cycle:
    self.fan_spinning = True

self.logger.debug("{} %의 듀티 사이클 설정".format(duty_cycle))
control.output_on(self.output_id_gpio_pwm,
                  output_type='pwm',
                  amount=duty_cycle,
                  output_channel=0)
```
