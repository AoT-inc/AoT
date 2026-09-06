
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
    self.logger.debug("Initializing")
    self.output_id_gpio_pwm = "a3dade60-091a-49d7-9c79-cd2adf41bc23"  # UUID of the GPIO PWM Output
    self.fan_spinning = False  # stores whether the fan is spinning
    self.fan_min_duty_cycle = 2  # lowest duty cycle at which the fan keeps spinning
    self.fan_spin_duty_cycle = 25  # lowest duty cycle that starts the fan from a stop
    self.fan_charge_duty_cycle = 45  # charge duty cycle needed to get the fan turning
    self.fan_spin_duration_sec = 1.5  # seconds to run the fan at the charge duty cycle

# Charge the fan when it is not spinning and the requested duty cycle is too low.
if duty_cycle and not self.fan_spinning and duty_cycle < self.fan_spin_duty_cycle:
    self.logger.debug("Duty cycle too low and fan is off. Charging.")
    self.logger.debug("Setting duty cycle to {} %".format(self.fan_charge_duty_cycle))
    control.output_on(self.output_id_gpio_pwm,
                      output_type='pwm',
                      amount=self.fan_charge_duty_cycle,
                      output_channel=0)
    time.sleep(self.fan_spin_duration_sec)
    self.fan_spinning = True

if duty_cycle == 0:
    self.logger.debug("Fan turned off")
    self.fan_spinning = False
elif duty_cycle > self.fan_spin_duty_cycle:
    self.fan_spinning = True

self.logger.debug("Setting duty cycle to {} %".format(duty_cycle))
control.output_on(self.output_id_gpio_pwm,
                  output_type='pwm',
                  amount=duty_cycle,
                  output_channel=0)
```
