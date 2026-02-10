
AoT에서 Python 3 코드를 사용할 수 있는 다양한 장소가 있으며, 여기에는 Python Code Input, Python Code Output, 그리고 Conditional Function이 포함됩니다.

다음은 Python 3 코드를 사용하여 AoT와 상호작용하는 몇 가지 유용한 방법을 보여주는 예제입니다.

코드가 실행되는 모든 AoT 환경에서는 [DaemonControl() 클래스](API.md#daemon-control-object)가 aot/aot_client.py에 정의되어 있으며, "control" 객체를 사용하여 데몬과 통신할 수 있습니다.

## 출력

### 최소 듀티 사이클로 회전하는 PWM 팬

PWM으로 제어되는 일부 팬은 최소 듀티 사이클이 설정될 때까지 회전을 시작하지 않습니다. 팬이 회전하기 시작하면 듀티 사이클을 훨씬 낮게 설정해도 팬은 계속 회전합니다. 이러한 이유로, 듀티 사이클이 0에서 팬이 켜질 때 "충전" 단계가 필요합니다. 이 코드는 요청된 듀티 사이클이 듀티 사이클을 설정하기 전에 충전 단계를 실행해야 하는지 감지합니다. 이를 위해 GPIO PWM Output과 Python Code PWM Output이 필요합니다. GPIO PWM Output은 팬에 대해 구성되고, Python Code PWM Output은 다음 코드로 구성됩니다:

```python
import time

# 코드가 처음 실행될 때 변수를 설정합니다.
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

