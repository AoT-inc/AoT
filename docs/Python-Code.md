
There are several places where Python 3 code can be used in AoT, including the Python Code Input, the Python Code Output, and the Conditional Function.

The following are examples that demonstrate a few useful ways of interacting with AoT using Python 3 code.

In every AoT environment where code is executed, the [DaemonControl() class](API.md#daemon-control-object) is defined in aot/aot_client.py, and the "control" object can be used to communicate with the daemon.

## Outputs

### PWM fan that spins at a minimum duty cycle

Some fans controlled by PWM will not begin spinning until a minimum duty cycle is set. Once the fan starts spinning, it will keep spinning even if the duty cycle is set much lower. For this reason, a "charge" phase is needed when the fan is turned on from a duty cycle of 0. This code detects whether the requested duty cycle requires a charge phase to be run before setting the duty cycle. To do this, a GPIO PWM Output and a Python Code PWM Output are needed. The GPIO PWM Output is configured for the fan, and the Python Code PWM Output is configured with the following code:

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
