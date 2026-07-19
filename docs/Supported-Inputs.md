## Built-In Inputs (System)

### AoT: AoT Version

- Manufacturer: AoT
- Measurements: Version as Major.Minor.Revision
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr></tbody></table>

### AoT: CPU Load

- Manufacturer: AoT
- Measurements: CPULoad
- Libraries: os.getloadavg()
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr></tbody></table>

### AoT: Free Space

- Manufacturer: AoT
- Measurements: Unallocated Disk Space
- Libraries: os.statvfs()
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr></tbody></table>

### AoT: Output State (On/Off)

- Manufacturer: AoT
- Measurements: Boolean

This Input stores a 0 (off) or 1 (on) for the selected On/Off Output.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>On/Off Output Channel</td><td>Select Channel (Output_Channels)</td><td>Select an output to measure</td></tr></tbody></table>

### AoT: Server Ping

- Manufacturer: AoT
- Measurements: Boolean
- Libraries: ping

This Input executes the bash command "ping -c [times] -w [deadline] [host]" to determine if the host can be pinged.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AoT: Server Port Open

- Manufacturer: AoT
- Measurements: Boolean
- Libraries: nc

This Input executes the bash command "nc -zv [host] [port]" to determine if the host at a particular port is accessible.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AoT: Spacer

- Manufacturer: AoT

A spacer to organize Inputs.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Color</td><td>Text
- Default Value: #000000</td><td>The color of the name text</td></tr></tbody></table>

### AoT: System and AoT RAM

- Manufacturer: AoT
- Measurements: RAM Allocation
- Libraries: psutil, resource.getrusage()
- Dependencies: [psutil](https://pypi.org/project/psutil)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>AoT Frontend RAM Endpoint</td><td>Text
- Default Value: https://127.0.0.1/ram</td><td>The endpoint to get AoT frontend ram usage</td></tr></tbody></table>

### AoT: Test Input: Save your own measurement value

- Manufacturer: AoT
- Measurements: Variable measurements

This is a simple test Input that allows you to save any value as a measurement, that will be stored in the measurement database. It can be useful for testing other parts of AoT, such as PIDs, Bang-Bang, and Conditional Functions, since you can be completely in control of what values the input provides to the Functions. Note 1: Select and save the Name and Measurement Unit for each channel. Once the unit has been saved, you can convert to other units in the Convert Measurement section. Note 2: Activate the Input before storing measurements.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Enter the Value you want to store as a measurement, then press Store Measurement.</td></tr><tr><td>Channel</td><td>Integer</td><td>This is the channel to save the measurement value to</td></tr><tr><td>Value</td><td>Decimal
- Default Value: 10.0</td><td>This is the measurement value to save for this Input</td></tr><tr><td>Store Measurement</td><td>Button</td><td></td></tr></tbody></table>

### AoT: Uptime

- Manufacturer: AoT
- Measurements: Seconds Since System Startup
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr></tbody></table>

### Linux: Bash Command

- Manufacturer: Linux
- Measurements: Return Value
- Interfaces: AoT

This Input will execute a command in the shell and store the output as a float value. Perform any unit conversions within your script or command. A measurement/unit is required to be selected.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Command Timeout</td><td>Integer
- Default Value: 60</td><td>How long to wait for the command to finish before killing the process.</td></tr><tr><td>User</td><td>Text
- Default Value: aot</td><td>The user to execute the command</td></tr><tr><td>Current Working Directory</td><td>Text
- Default Value: /home/pi</td><td>The current working directory of the shell environment.</td></tr></tbody></table>

### Linux: Python 3 Code (v1.0)

- Manufacturer: Linux
- Measurements: Store Value(s)
- Interfaces: AoT
- Dependencies: [pylint](https://pypi.org/project/pylint)

All channels require a Measurement Unit to be selected and saved in order to store values to the database. Your code is executed from the same Python virtual environment that AoT runs from. Therefore, you must install Python libraries to this environment if you want them to be available to your code. This virtualenv is located at /opt/AoT/env and if you wanted to install a library, for example "my_library" using pip, you would execute "sudo /opt/AoT/env/bin/pip install my_library".
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>Analyze your Python code with pylint when saving</td></tr></tbody></table>

### Linux: Python 3 Code (v2.0)

- Manufacturer: Linux
- Measurements: Store Value(s)
- Interfaces: AoT
- Dependencies: [pylint](https://pypi.org/project/pylint)

This is an alternate Python 3 Code Input that uses a different method for storing values to the database. This was created because the Python 3 Code v1.0 Input does not allow the use of Input Actions. This method does allow the use of Input Actions. (11/21/2023 Update: The Python 3 Code (v1.0) Input now allows the execution of Actions). All channels require a Measurement Unit to be selected and saved in order to store values to the database. Your code is executed from the same Python virtual environment that AoT runs from. Therefore, you must install Python libraries to this environment if you want them to be available to your code. This virtualenv is located at /opt/AoT/env and if you wanted to install a library, for example "my_library" using pip, you would execute "sudo /opt/AoT/env/bin/pip install my_library".
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Python 3 Code</td></td><td>The code to execute. Must return a value.</td></tr><tr><td>Analyze Python Code with Pylint</td><td>Boolean
- Default Value: True</td><td>Analyze your Python code with pylint when saving</td></tr></tbody></table>

### Raspberry Pi: CPU/GPU Temperature

- Manufacturer: Raspberry Pi
- Measurements: Temperature
- Interfaces: RPi

The internal CPU and GPU temperature of the Raspberry Pi.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Path for CPU Temperature</td><td>Text
- Default Value: /sys/class/thermal/thermal_zone0/temp</td><td>Reads the CPU temperature from this file</td></tr><tr><td>Path to vcgencmd</td><td>Text
- Default Value: /usr/bin/vcgencmd</td><td>Reads the GPU from vcgencmd</td></tr></tbody></table>

### Raspberry Pi: Edge Detection

- Manufacturer: Raspberry Pi
- Measurements: Rising/Falling Edge
- Interfaces: GPIO
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Pin Mode</td><td>Select(Options: [<strong>Floating</strong> | Pull Down | Pull Up] (Default in <strong>bold</strong>)</td><td>Enables or disables the pull-up or pull-down resistor</td></tr></tbody></table>

### Raspberry Pi: GPIO State

- Manufacturer: Raspberry Pi
- Measurements: GPIO State
- Interfaces: GPIO
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)

Measures the state of a GPIO pin, returning either 0 (low) or 1 (high).
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Pin Mode</td><td>Select(Options: [<strong>Floating</strong> | Pull Down | Pull Up] (Default in <strong>bold</strong>)</td><td>Enables or disables the pull-up or pull-down resistor</td></tr></tbody></table>

### Raspberry Pi: Signal (PWM)

- Manufacturer: Raspberry Pi
- Measurements: Frequency/Pulse Width/Duty Cycle
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Raspberry Pi: Signal (Revolutions) (pigpio method #1)

- Manufacturer: Raspberry Pi
- Measurements: RPM
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)

This calculates RPM from pulses on a pin using pigpio, but has been found to be less accurate than the method #2 module. This is typically used to measure the speed of a fan from a tachometer pin, however this can be used to measure any 3.3-volt pulses from a wire. Use a resistor to pull the measurement pin to 3.3 volts, set pigpio to the lowest latency (1 ms) on the Configure -> Raspberry Pi page. Note 1: Not setting pigpio to the lowest latency will hinder accuracy. Note 2: accuracy decreases as RPM increases.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Raspberry Pi: Signal (Revolutions) (pigpio method #2)

- Manufacturer: Raspberry Pi
- Measurements: RPM
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)

This is an alternate method to calculate RPM from pulses on a pin using pigpio, and has been found to be more accurate than the method #1 module. This is typically used to measure the speed of a fan from a tachometer pin, however this can be used to measure any 3.3-volt pulses from a wire. Use a resistor to pull the measurement pin to 3.3 volts, set pigpio to the lowest latency (1 ms) on the Configure -> Raspberry Pi page. Note 1: Not setting pigpio to the lowest latency will hinder accuracy. Note 2: accuracy decreases as RPM increases.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Pin: GPIO (BCM)</td><td>Integer</td><td>The pin to measure pulses from</td></tr><tr><td>Sample Time (Seconds)</td><td>Decimal
- Default Value: 5.0</td><td>The duration of time to sample</td></tr><tr><td>Pulses Per Rev</td><td>Decimal
- Default Value: 15.8</td><td>The number of pulses per revolution to calculate revolutions per minute (RPM)</td></tr></tbody></table>

## Built-In Inputs (Devices)

### AMS: AS7262

- Manufacturer: AMS
- Measurements: Light at 450, 500, 550, 570, 600, 650 nm
- Interfaces: I<sup>2</sup>C
- Libraries: as7262
- Dependencies: [as7262](https://pypi.org/project/as7262)
- Manufacturer URL: [Link](https://ams.com/as7262)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/AS7262_DS000486_2-00.pdf/0031f605-5629-e030-73b2-f365fd36a43b)
- Product URL: [Link](https://www.sparkfun.com/products/14347)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Gain</td><td>Select(Options: [1x | 3.7x | 16x | <strong>64x</strong>] (Default in <strong>bold</strong>)</td><td>Set the sensor gain</td></tr><tr><td>Illumination LED Current</td><td>Select(Options: [<strong>12.5 mA</strong> | 25 mA | 50 mA | 100 mA] (Default in <strong>bold</strong>)</td><td>Set the illumination LED current (milliamps)</td></tr><tr><td>Illumination LED Mode</td><td>Select(Options: [<strong>On</strong> | Off] (Default in <strong>bold</strong>)</td><td>Turn the illumination LED on or off during a measurement</td></tr><tr><td>Indicator LED Current</td><td>Select(Options: [<strong>1 mA</strong> | 2 mA | 4 mA | 8 mA] (Default in <strong>bold</strong>)</td><td>Set the indicator LED current (milliamps)</td></tr><tr><td>Indicator LED Mode</td><td>Select(Options: [<strong>On</strong> | Off] (Default in <strong>bold</strong>)</td><td>Turn the indicator LED on or off during a measurement</td></tr><tr><td>Integration Time</td><td>Decimal
- Default Value: 15.0</td><td>The integration time (0 - ~91 ms)</td></tr></tbody></table>

### AMS: CCS811 (with Temperature)

- Manufacturer: AMS
- Measurements: CO2/VOC/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CCS811
- Dependencies: [Adafruit_CCS811](https://pypi.org/project/Adafruit_CCS811), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.sciosense.com/products/environmental-sensors/ccs811-gas-sensor-solution/)
- Datasheet URL: [Link](https://www.sciosense.com/wp-content/uploads/2020/01/CCS811-Datasheet.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3566), [Link 2](https://www.sparkfun.com/products/14193)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AMS: CCS811 (without Temperature)

- Manufacturer: AMS
- Measurements: CO2/VOC
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_CCS811
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ccs811](https://pypi.org/project/adafruit-circuitpython-ccs811)
- Manufacturer URL: [Link](https://www.sciosense.com/products/environmental-sensors/ccs811-gas-sensor-solution/)
- Datasheet URL: [Link](https://www.sciosense.com/wp-content/uploads/2020/01/CCS811-Datasheet.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3566)
- Additional URL: [Link](https://learn.adafruit.com/adafruit-ccs811-air-quality-sensor)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AMS: TSL2561

- Manufacturer: AMS
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: tsl2561
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-PureIO](https://pypi.org/project/Adafruit-PureIO), [tsl2561](https://pypi.org/project/tsl2561)
- Manufacturer URL: [Link](https://ams.com/tsl2561)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/TSL2561_DS000110_3-00.pdf/18a41097-2035-4333-c70e-bfa544c0a98b)
- Product URL: [Link](https://www.adafruit.com/product/439)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AMS: TSL2591

- Manufacturer: AMS
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: maxlklaxl/python-tsl2591
- Dependencies: [tsl2591](https://github.com/maxlklaxl/python-tsl2591)
- Manufacturer URL: [Link](https://ams.com/tsl25911)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/TSL2591_DS000338_6-00.pdf/090eb50d-bb18-5b45-4938-9b3672f86b80)
- Product URL: [Link](https://www.adafruit.com/product/1980)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AOSONG: AM2315/AM2320

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: quick2wire-api
- Dependencies: [quick2wire-api](https://pypi.org/project/quick2wire-api)
- Datasheet URL: [Link](https://cdn-shop.adafruit.com/datasheets/AM2315.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1293)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AOSONG: AM2315C

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: quick2wire-api
- Dependencies: [quick2wire-api](https://pypi.org/project/quick2wire-api)
- Datasheet URL: [Link](https://cdn-shop.adafruit.com/product-files/5182/5182_AM2315C.pdf)
- Product URL: [Link](https://vctec.co.kr/product/am2315c-i2c-%EC%98%A8%EB%8F%84%EC%8A%B5%EB%8F%84-%EC%84%BC%EC%84%9C-am2315c-encased-i2c-temperaturehumidity-sensor/20000)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AOSONG: DHT11

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
- Datasheet URL: [Link](http://www.adafruit.com/datasheets/DHT11-chinese.pdf)
- Product URL: [Link](https://www.adafruit.com/product/386)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AOSONG: DHT20

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://asairsensors.com/product/dht20-sip-packaged-temperature-and-humidity-sensor/)
- Datasheet URL: [Link](http://www.aosong.com/userfiles/files/media/Data%20Sheet%20DHT20%20%20A1.pdf)
- Product URLs: [Link 1](https://www.seeedstudio.com/Grove-Temperature-Humidity-Sensor-V2-0-DHT20-p-4967.html), [Link 2](https://www.antratek.de/humidity-and-temperature-sensor-dht20), [Link 3](https://www.adafruit.com/product/5183)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### AOSONG: DHT22

- Manufacturer: AOSONG
- Measurements: Humidity/Temperature
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
- Datasheet URL: [Link](http://www.adafruit.com/datasheets/DHT22.pdf)
- Product URL: [Link](https://www.adafruit.com/product/385)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### ASAIR: AHTx0

- Manufacturer: ASAIR
- Measurements: Temperature/Humidity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_AHTx0
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ahtx0](https://pypi.org/project/adafruit-circuitpython-ahtx0)
- Manufacturer URL: [Link](http://www.aosong.com/en/products-40.html)
- Datasheet URL: [Link](https://server4.eca.ir/eshop/AHT10/Aosong_AHT10_en_draft_0c.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Adafruit: I2C Capacitive Moisture Sensor

- Manufacturer: Adafruit
- Measurements: Moisture/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: adafruit_seesaw
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-seesaw](https://pypi.org/project/adafruit-circuitpython-seesaw)
- Manufacturer URL: [Link](https://learn.adafruit.com/adafruit-stemma-soil-sensor-i2c-capacitive-moisture-sensor)
- Product URL: [Link](https://www.adafruit.com/product/4026)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Analog Devices: ADT7410

- Manufacturer: Analog Devices
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADT7410
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-adt7410](https://pypi.org/project/adafruit-circuitpython-adt7410)
- Datasheet URL: [Link](https://www.analog.com/media/en/technical-documentation/data-sheets/ADT7410.pdf)
- Product URL: [Link](https://www.analog.com/en/products/adt7410.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Analog Devices: ADXL34x (343, 344, 345, 346)

- Manufacturer: Analog Devices
- Measurements: Acceleration
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADXL34x
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-adxl34x](https://pypi.org/project/adafruit-circuitpython-adxl34x)
- Datasheet URLs: [Link 1](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL343.pdf), [Link 2](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL344.pdf), [Link 3](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL345.pdf), [Link 4](https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL346.pdf)
- Product URLs: [Link 1](https://www.analog.com/en/products/adxl343.html), [Link 2](https://www.analog.com/en/products/adxl344.html), [Link 3](https://www.analog.com/en/products/adxl345.html), [Link 4](https://www.analog.com/en/products/adxl346.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Range</td><td>Select(Options: [±2 g (±19.6 m/s/s) | ±4 g (±39.2 m/s/s) | ±8 g (±78.4 m/s/s) | <strong>±16 g (±156.9 m/s/s)</strong>] (Default in <strong>bold</strong>)</td><td>Set the measurement range</td></tr></tbody></table>

### AnyLeaf: AnyLeaf EC

- Manufacturer: AnyLeaf
- Measurements: Electrical Conductivity
- Interfaces: UART
- Libraries: anyleaf
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [Pillow](https://pypi.org/project/Pillow), [scipy](https://pypi.org/project/scipy), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [anyleaf](https://pypi.org/project/anyleaf)
- Manufacturer URL: [Link](https://www.anyleaf.org/ec-module)
- Datasheet URL: [Link](https://www.anyleaf.org/static/ec-module-datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Conductivity Constant</td><td>Decimal
- Default Value: 1.0</td><td>Conductivity constant K</td></tr></tbody></table>

### AnyLeaf: AnyLeaf ORP

- Manufacturer: AnyLeaf
- Measurements: Oxidation Reduction Potential
- Interfaces: I<sup>2</sup>C
- Libraries: anyleaf
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [Pillow](https://pypi.org/project/Pillow), [scipy](https://pypi.org/project/scipy), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [anyleaf](https://pypi.org/project/anyleaf)
- Manufacturer URL: [Link](https://anyleaf.org/ph-module)
- Datasheet URL: [Link](https://anyleaf.org/static/ph-module-datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Calibrate: Voltage (Internal)</td><td>Decimal
- Default Value: 0.4</td><td>Calibration data: internal voltage</td></tr><tr><td>Calibrate: ORP (Internal)</td><td>Decimal
- Default Value: 400.0</td><td>Calibration data: internal ORP</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate: Buffer ORP (mV)</td><td>Decimal
- Default Value: 400.0</td><td>This is the nominal ORP of the calibration buffer in mV, usually labelled on the bottle.</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td>Clear Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### AnyLeaf: AnyLeaf pH

- Manufacturer: AnyLeaf
- Measurements: Ion concentration
- Interfaces: I<sup>2</sup>C
- Libraries: anyleaf
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [Pillow](https://pypi.org/project/Pillow), [scipy](https://pypi.org/project/scipy), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [anyleaf](https://pypi.org/project/anyleaf)
- Manufacturer URL: [Link](https://anyleaf.org/ph-module)
- Datasheet URL: [Link](https://anyleaf.org/static/ph-module-datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td>Cal data: V1 (internal)</td><td>Decimal</td><td>Calibration data: Voltage</td></tr><tr><td>Cal data: pH1 (internal)</td><td>Decimal
- Default Value: 7.0</td><td>Calibration data: pH</td></tr><tr><td>Cal data: T1 (internal)</td><td>Decimal
- Default Value: 23.0</td><td>Calibration data: Temperature</td></tr><tr><td>Cal data: V2 (internal)</td><td>Decimal
- Default Value: 0.17</td><td>Calibration data: Voltage</td></tr><tr><td>Cal data: pH2 (internal)</td><td>Decimal
- Default Value: 4.0</td><td>Calibration data: pH</td></tr><tr><td>Cal data: T2 (internal)</td><td>Decimal
- Default Value: 23.0</td><td>Calibration data: Temperature</td></tr><tr><td>Cal data: V3 (internal)</td><td>Decimal</td><td>Calibration data: Voltage</td></tr><tr><td>Cal data: pH3 (internal)</td><td>Decimal</td><td>Calibration data: pH</td></tr><tr><td>Cal data: T3 (internal)</td><td>Decimal</td><td>Calibration data: Temperature</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibration buffer pH</td><td>Decimal
- Default Value: 7.0</td><td>This is the nominal pH of the calibration buffer, usually labelled on the bottle.</td></tr><tr><td>Calibrate, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate, slot 2</td><td>Button</td><td></td></tr><tr><td>Calibrate, slot 3</td><td>Button</td><td></td></tr><tr><td>Clear Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas CO2 (Carbon Dioxide Gas)

- Manufacturer: Atlas Scientific
- Measurements: CO2
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/co2/)
- Datasheet URL: [Link](https://atlas-scientific.com/files/EZO_CO2_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one- or two-point calibration can be performed. After exposing the probe to a concentration of CO2 between 3,000 and 5,000 ppmv until readings stabilize, press Calibrate (High). You can place the probe in a 0 CO2 environment until readings stabilize, then press Calibrate (Zero). You can also clear the currently-saved calibration by pressing Clear Calibration, returning to the factory-set calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>High Point CO2</td><td>Integer
- Default Value: 3000</td><td>The high CO2 calibration point (3000 - 5000 ppmv)</td></tr><tr><td>Calibrate (High)</td><td>Button</td><td></td></tr><tr><td>Calibrate (Zero)</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x69</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Color

- Manufacturer: Atlas Scientific
- Measurements: RGB, CIE, LUX, Proximity
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/ezo-rgb/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO_RGB_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>LED Only For Measure</td><td>Boolean
- Default Value: True</td><td>Turn the LED on only during the measurement</td></tr><tr><td>LED Percentage</td><td>Integer
- Default Value: 30</td><td>What percentage of power to supply to the LEDs during measurement</td></tr><tr><td>Gamma Correction</td><td>Decimal
- Default Value: 1.0</td><td>Gamma correction between 0.01 and 4.99 (default is 1.0)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The EZO-RGB color sensor is designed to be calibrated to a white object at the maximum brightness the object will be viewed under. In order to get the best results, Atlas Scientific strongly recommends that the sensor is mounted into a fixed location. Holding the sensor in your hand during calibration will decrease performance.<br>1. Embed the EZO-RGB color sensor into its intended use location.<br>2. Set LED brightness to the desired level.<br>3. Place a white object in front of the target object and press the Calibration button.<br>4. A single color reading will be taken and the device will be fully calibrated.</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x70</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas DO

- Manufacturer: Atlas Scientific
- Measurements: Dissolved Oxygen
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/dissolved-oxygen.html)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/DO_EZO_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one- or two-point calibration can be performed. After exposing the probe to air for 30 seconds until readings stabilize, press Calibrate (Air). If you require accuracy below 1.0 mg/L, you can place the probe in a 0 mg/L solution for 30 to 90 seconds until readings stabilize, then press Calibrate (0 mg/L). You can also clear the currently-saved calibration by pressing Clear Calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Calibrate (Air)</td><td>Button</td><td></td></tr><tr><td>Calibrate (0 mg/L)</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x66</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas EC

- Manufacturer: Atlas Scientific
- Measurements: Electrical Conductivity
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/conductivity/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EC_EZO_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Calibration: a one- or two-point calibration can be performed. It's a good idea to clear the calibration before calibrating. Always perform a dry calibration with the probe in the air (not in any fluid). Then perform either a one- or two-point calibration with calibrated solutions. If performing a one-point calibration, use the Single Point Calibration field and button. If performing a two-point calibration, use the Low and High Point Calibration fields and buttons. Allow a minute or two after submerging your probe in a calibration solution for the measurements to equilibrate before calibrating to that solution. The EZO EC circuit default temperature compensation is set to 25 °C. If the temperature of the calibration solution is +/- 2 °C from 25 °C, consider setting the temperature compensation first. Note that at no point should you change the temperature compensation value during calibration. Therefore, if you have previously enabled temperature compensation, allow at least one measurement to occur (to set the compensation value), then disable the temperature compensation measurement while you calibrate. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td>Calibrate Dry</td><td>Button</td><td></td></tr><tr><td>Single Point EC (µS)</td><td>Integer
- Default Value: 84</td><td>The EC (µS) of the single point calibration solution</td></tr><tr><td>Calibrate Single Point</td><td>Button</td><td></td></tr><tr><td>Low Point EC (µS)</td><td>Integer
- Default Value: 12880</td><td>The EC (µS) of the low point calibration solution</td></tr><tr><td>Calibrate Low Point</td><td>Button</td><td></td></tr><tr><td>High Point EC (µS)</td><td>Integer
- Default Value: 80000</td><td>The EC (µS) of the high point calibration solution</td></tr><tr><td>Calibrate High Point</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x64</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Flow Meter

- Manufacturer: Atlas Scientific
- Measurements: Total Volume, Flow Rate
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/flow/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/flow_EZO_Datasheet.pdf)

Set the Measurement Time Base to a value most appropriate for your anticipated flow (it will affect accuracy). This flow rate time base that is set and returned from the sensor will be converted to liters per minute, which is the default unit for this input module. If you desire a different rate to be stored in the database (such as liters per second or hour), then use the Convert to Unit option.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Flow Meter Type</td><td>Select(Options: [<strong>Atlas Scientific 3/8" Flow Meter</strong> | Atlas Scientific 1/4" Flow Meter | Atlas Scientific 1/2" Flow Meter | Atlas Scientific 3/4" Flow Meter | Non-Atlas Scientific Flow Meter] (Default in <strong>bold</strong>)</td><td>Set the type of flow meter used</td></tr><tr><td>Atlas Meter Time Base</td><td>Select(Options: [Liters per Second | <strong>Liters per Minute</strong> | Liters per Hour] (Default in <strong>bold</strong>)</td><td>If using an Atlas Scientific flow meter, set the flow rate/time base</td></tr><tr><td>Internal Resistor</td><td>Select(Options: [<strong>Use Atlas Scientific Flow Meter</strong> | Disable Internal Resistor | 1 K Ω Pull-Up | 1 K Ω Pull-Down | 10 K Ω Pull-Up | 10 K Ω Pull-Down | 100 K Ω Pull-Up | 100 K Ω Pull-Down] (Default in <strong>bold</strong>)</td><td>Set an internal resistor for the flow meter</td></tr><tr><td>Custom K Value(s)</td><td>Text</td><td>If using a non-Atlas Scientific flow meter, enter the meter's K value(s). For a single K value, enter '[volume per pulse],[number of pulses]'. For multiple K values (up to 16), enter '[volume at frequency],[frequency in Hz];[volume at frequency],[frequency in Hz];...'. Leave blank to disable.</td></tr><tr><td>K Value Time Base</td><td>Select(Options: [<strong>Use Atlas Scientific Flow Meter</strong> | Liters per Second | Liters per Minute | Liters per Hour] (Default in <strong>bold</strong>)</td><td>If using a non-Atlas Scientific flow meter, set the flow rate/time base for the custom K values entered.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The total volume can be cleared with the following button or with the Clear Total Volume Function Action.</td></tr><tr><td>Clear Total: Volume</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x68</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Humidity

- Manufacturer: Atlas Scientific
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/probes/humidity-sensor/)
- Datasheet URL: [Link](https://atlas-scientific.com/files/EZO-HUM-Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>LED Mode</td><td>Select(Options: [<strong>Always On</strong> | Always Off | Only On During Measure] (Default in <strong>bold</strong>)</td><td>When to turn the LED on</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x6f</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas O2 (Oxygen Gas)

- Manufacturer: Atlas Scientific
- Measurements: O2
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://atlas-scientific.com/probes/oxygen-sensor/)
- Datasheet URL: [Link](https://files.atlas-scientific.com/EZO_O2_datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td>Temperature Compensation: Manual</td><td>Decimal
- Default Value: 20.0</td><td>If not using a measurement, set the temperature to compensate</td></tr><tr><td>LED Mode</td><td>Select(Options: [<strong>Always On</strong> | Always Off | Only On During Measure] (Default in <strong>bold</strong>)</td><td>When to turn the LED on</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one- or two-point calibration can be performed. After exposing the probe to a specific concentration of O2 until readings stabilize, press Calibrate (High). You can place the probe in a 0% O2 environment until readings stabilize, then press Calibrate (Zero). You can also clear the currently-saved calibration by pressing Clear Calibration, returning to the factory-set calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>High Point O2</td><td>Decimal
- Default Value: 20.95</td><td>The high O2 calibration point (percent)</td></tr><tr><td>Calibrate (High)</td><td>Button</td><td></td></tr><tr><td>Calibrate (Zero)</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x69</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas ORP

- Manufacturer: Atlas Scientific
- Measurements: Oxidation Reduction Potential
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/orp/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/ORP_EZO_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A one-point calibration can be performed. Enter the solution's mV, set the probe in the solution, then press Calibrate. You can also clear the currently-saved calibration by pressing Clear Calibration. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Calibration Solution mV</td><td>Integer
- Default Value: 225</td><td>The value of the calibration solution, in mV</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x62</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas PT-1000

- Manufacturer: Atlas Scientific
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/temperature/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO_RTD_Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x66</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr><tr><td>Temperature (°C)</td><td>Decimal
- Default Value: 100.0</td><td>Temperature for single point calibration</td></tr><tr><td>Calibrate</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas Pressure

- Manufacturer: Atlas Scientific
- Measurements: Pressure
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/pressure/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/EZO-PRS-Datasheet.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>LED Mode</td><td>Select(Options: [<strong>Always On</strong> | Always Off | Only On During Measure] (Default in <strong>bold</strong>)</td><td>When to turn the LED on</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x6a</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Atlas Scientific: Atlas pH

- Manufacturer: Atlas Scientific
- Measurements: Ion Concentration
- Interfaces: I<sup>2</sup>C, UART, FTDI
- Libraries: pylibftdi/fcntl/io/serial
- Dependencies: [pylibftdi](https://pypi.org/project/pylibftdi)
- Manufacturer URL: [Link](https://www.atlas-scientific.com/ph/)
- Datasheet URL: [Link](https://www.atlas-scientific.com/files/pH_EZO_Datasheet.pdf)

Calibration Measurement is an optional setting that provides a temperature measurement (in Celsius) of the water that the pH is being measured from.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>FTDI Device</td><td>Text</td><td>The FTDI device connected to the input/output/etc.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Calibration: a one-, two- or three-point calibration can be performed. It's a good idea to clear the calibration before calibrating. The first calibration must be the Mid point. The second must be the Low point. And the third must be the High point. You can perform a one-, two- or three-point calibration, but they must be performed in this order. Allow a minute or two after submerging your probe in a calibration solution for the measurements to equilibrate before calibrating to that solution. The EZO pH circuit default temperature compensation is set to 25 °C. If the temperature of the calibration solution is +/- 2 °C from 25 °C, consider setting the temperature compensation first. Note that if you have a Temperature Compensation Measurement selected from the Options, this will overwrite the manual Temperature Compensation set here, so be sure to disable this option if you would like to specify the temperature to compensate with. Status messages will be sent to the Daemon Log, accessible from Config -> AoT Logs -> Daemon Log.</td></tr><tr><td>Compensation Temperature (°C)</td><td>Decimal
- Default Value: 25.0</td><td>The temperature of the calibration solutions</td></tr><tr><td>Set Temperature Compensation</td><td>Button</td><td></td></tr><tr><td>Clear Calibration</td><td>Button</td><td></td></tr><tr><td>Mid Point pH</td><td>Decimal
- Default Value: 7.0</td><td>The pH of the mid point calibration solution</td></tr><tr><td>Calibrate Mid</td><td>Button</td><td></td></tr><tr><td>Low Point pH</td><td>Decimal
- Default Value: 4.0</td><td>The pH of the low point calibration solution</td></tr><tr><td>Calibrate Low</td><td>Button</td><td></td></tr><tr><td>High Point pH</td><td>Decimal
- Default Value: 10.0</td><td>The pH of the high point calibration solution</td></tr><tr><td>Calibrate High</td><td>Button</td><td></td></tr><tr><td colspan="3">Calibration Export/Import: Export calibration to a series of strings. These can later be imported to restore the calibration. Watch the Daemon Log for the output.</td></tr><tr><td>Export Calibration</td><td>Button</td><td></td></tr><tr><td>Calibration String</td><td>Text</td><td>The calibration string to import</td></tr><tr><td>Import Calibration</td><td>Button</td><td></td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x63</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### BOSCH: BME280 (Adafruit_BME280)

- Manufacturer: BOSCH
- Measurements: Pressure/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_BME280
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit_BME280](https://github.com/adafruit/Adafruit_Python_BME280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/bst/products/all_products/bme280)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/2652), [Link 2](https://www.sparkfun.com/products/13676)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### BOSCH: BME280 (Adafruit_CircuitPython_BME280)

- Manufacturer: BOSCH
- Measurements: Pressure/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_BME280
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-bme280](https://pypi.org/project/adafruit-circuitpython-bme280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/bst/products/all_products/bme280)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/2652), [Link 2](https://www.sparkfun.com/products/13676)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### BOSCH: BME280 (RPi.bme280)

- Manufacturer: BOSCH
- Measurements: Pressure/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: RPi.bme280
- Dependencies: [RPi.bme280](https://pypi.org/project/RPi.bme280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/bst/products/all_products/bme280)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/2652), [Link 2](https://www.sparkfun.com/products/13676)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### BOSCH: BME680 (Adafruit_CircuitPython_BME680)

- Manufacturer: BOSCH
- Measurements: Temperature/Humidity/Pressure/Gas
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_BME680
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-bme680](https://pypi.org/project/adafruit-circuitpython-bme680)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/gas-sensors-bme680/)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme680-ds001.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3660), [Link 2](https://www.sparkfun.com/products/16466)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Humidity Oversampling</td><td>Select(Options: [NONE | 1X | <strong>2X</strong> | 4X | 8X | 16X] (Default in <strong>bold</strong>)</td><td>A higher oversampling value means more stable readings with less noise and jitter. However each step of oversampling adds ~2 ms latency, causing a slower response time to fast transients.</td></tr><tr><td>Temperature Oversampling</td><td>Select(Options: [NONE | 1X | 2X | 4X | <strong>8X</strong> | 16X] (Default in <strong>bold</strong>)</td><td>A higher oversampling value means more stable readings with less noise and jitter. However each step of oversampling adds ~2 ms latency, causing a slower response time to fast transients.</td></tr><tr><td>Pressure Oversampling</td><td>Select(Options: [NONE | 1X | 2X | <strong>4X</strong> | 8X | 16X] (Default in <strong>bold</strong>)</td><td>A higher oversampling value means more stable readings with less noise and jitter. However each step of oversampling adds ~2 ms latency, causing a slower response time to fast transients.</td></tr><tr><td>IIR Filter Size</td><td>Select(Options: [0 | 1 | <strong>3</strong> | 7 | 15 | 31 | 63 | 127] (Default in <strong>bold</strong>)</td><td>Optionally remove short term fluctuations from the temperature and pressure readings, increasing their resolution but reducing their bandwidth.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>The amount to offset the temperature, either negative or positive</td></tr><tr><td>Sea Level Pressure (ha)</td><td>Decimal
- Default Value: 1013.25</td><td>The pressure at sea level for the sensor location</td></tr></tbody></table>

### BOSCH: BME680 (bme680)

- Manufacturer: BOSCH
- Measurements: Temperature/Humidity/Pressure/Gas
- Interfaces: I<sup>2</sup>C
- Libraries: bme680
- Dependencies: [bme680](https://pypi.org/project/bme680), [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/gas-sensors-bme680/)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme680-ds001.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3660), [Link 2](https://www.sparkfun.com/products/16466)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Humidity Oversampling</td><td>Select(Options: [NONE | 1X | <strong>2X</strong> | 4X | 8X | 16X] (Default in <strong>bold</strong>)</td><td>A higher oversampling value means more stable readings with less noise and jitter. However each step of oversampling adds ~2 ms latency, causing a slower response time to fast transients.</td></tr><tr><td>Temperature Oversampling</td><td>Select(Options: [NONE | 1X | 2X | 4X | <strong>8X</strong> | 16X] (Default in <strong>bold</strong>)</td><td>A higher oversampling value means more stable readings with less noise and jitter. However each step of oversampling adds ~2 ms latency, causing a slower response time to fast transients.</td></tr><tr><td>Pressure Oversampling</td><td>Select(Options: [NONE | 1X | 2X | <strong>4X</strong> | 8X | 16X] (Default in <strong>bold</strong>)</td><td>A higher oversampling value means more stable readings with less noise and jitter. However each step of oversampling adds ~2 ms latency, causing a slower response time to fast transients.</td></tr><tr><td>IIR Filter Size</td><td>Select(Options: [0 | 1 | <strong>3</strong> | 7 | 15 | 31 | 63 | 127] (Default in <strong>bold</strong>)</td><td>Optionally remove short term fluctuations from the temperature and pressure readings, increasing their resolution but reducing their bandwidth.</td></tr><tr><td>Gas Heater Temperature (°C)</td><td>Integer
- Default Value: 320</td><td>What temperature to set</td></tr><tr><td>Gas Heater Duration (ms)</td><td>Integer
- Default Value: 150</td><td>How long of a duration to heat. 20-30 ms are necessary for the heater to reach the intended target temperature.</td></tr><tr><td>Gas Heater Profile</td><td>Select</td><td>Select one of the 10 configured heating durations/set points</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>The amount to offset the temperature, either negative or positive</td></tr></tbody></table>

### BOSCH: BMP180

- Manufacturer: BOSCH
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_BMP
- Dependencies: [Adafruit-BMP](https://pypi.org/project/Adafruit-BMP), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Datasheet URL: [Link](https://ae-bst.resource.bosch.com/media/_tech/media/product_flyer/BST-BMP180-FL000.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### BOSCH: BMP280 (Adafruit_GPIO)

- Manufacturer: BOSCH
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_GPIO
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/pressure-sensors-bmp280-1.html)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf)
- Product URL: [Link](https://www.adafruit.com/product/2651)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### BOSCH: BMP280 (bmp280-python)

- Manufacturer: BOSCH
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: bmp280-python
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [bmp280](https://pypi.org/project/bmp280)
- Manufacturer URL: [Link](https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/pressure-sensors-bmp280-1.html)
- Datasheet URL: [Link](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmp280-ds001.pdf)
- Product URL: [Link](https://www.adafruit.com/product/2651)

This is similar to the other BMP280 Input, except it uses a different library, whcih includes the ability to set forced mode.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Enable Forced Mode</td><td>Boolean</td><td>Enable heater to evaporate condensation. Turn on heater x seconds every y measurements.</td></tr></tbody></table>

### CARTO: GL: Carto Maps

- Manufacturer: CARTO
- Measurements: Status
- Libraries: gis_carto
- Manufacturer URL: [Link](https://carto.com/)

CARTO DB에서 제공하는 데이터 분석 전용 지도입니다. 색감이 절제된 Positron(밝음), Dark Matter(어두움), Voyager 스타일을 제공하여, 위에 표현되는 데이터 포인트나 센서 정보가 더욱 돋보이도록 설계되었습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Active Map Styles</td></td></tbody></table>

### CO2Meter: K30

- Manufacturer: CO2Meter
- Measurements: CO2
- Interfaces: I<sup>2</sup>C, UART
- Libraries: serial (UART)
- Manufacturer URL: [Link](https://www.co2meter.com/products/k-30-co2-sensor-module)
- Datasheet URL: [Link](http://co2meters.com/Documentation/Datasheets/DS_SE_0118_CM_0024_Revised9%20(1).pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Catnip Electronics: Chirp

- Manufacturer: Catnip Electronics
- Measurements: Light/Moisture/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://wemakethings.net/chirp/)
- Product URL: [Link](https://www.tindie.com/products/miceuz/chirp-plant-watering-alarm/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The I2C address can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x20</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### ChirpStack: ChirpStack: MQTT (Payload JMESPath Expression)

- Manufacturer: ChirpStack
- Measurements: Variable measurements
- Libraries: paho-mqtt, jmespath
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt), [jmespath](https://pypi.org/project/jmespath)

ChirpStack v4 MQTT 브로커의 토픽(application/+/device/+/event/up)을 구독하여 이벤트를 수신하고, 각 이벤트 JSON에 대해 채널별 JMESPath 표현식을 적용하여 측정값을 저장합니다. 예시(https://jmespath.org): object.battery_V, object.battery_pct, max_by(rxInfo,&rssi).rssi, deviceInfo.devEui.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>MQTT Host</td><td>Text
- Default Value: localhost</td><td>MQTT 브로커 호스트명 또는 IP 주소 (예: localhost)</td></tr><tr><td>MQTT Port</td><td>Text
- Default Value: 1883</td><td>MQTT 브로커 포트 (기본 1883, TLS는 8883 권장)</td></tr><tr><td>MQTT Username</td><td>Text</td><td>선택 사항: 브로커 인증 사용자 이름</td></tr><tr><td>MQTT Password</td><td>Text</td><td>선택 사항: 브로커 인증 비밀번호</td></tr><tr><td>Enable TLS</td><td>Boolean</td><td>TLS(SSL) 연결 사용 여부 (기본 꺼짐)</td></tr><tr><td>CA Certificate Path</td><td>Text</td><td>선택 사항: TLS 사용 시 CA 인증서 경로</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_kkohqJyu</td><td>Unique client ID for connecting to the server</td></tr><tr><td>Keepalive (sec)</td><td>Text
- Default Value: 60</td><td>MQTT Keepalive 초 (기본 60초)</td></tr><tr><td>Subscribe Topics</td><td>Text
- Default Value: application/+/device/+/event/up</td><td>콤마(,)로 구분된 구독 토픽들 (예: application/+/device/+/event/up)</td></tr><tr><td>QoS</td><td>Text</td><td>MQTT QoS 레벨 (0, 1, 2)</td></tr><tr><td>Device EUIs (comma-separated)</td><td>Text</td><td>선택 사항: 특정 디바이스만 처리. EUI를 콤마(,)로 구분해 입력</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>JMESPath Expression</td><td>Text</td><td>수신 이벤트 전체(JSON)에 대해 평가합니다</td></tr></tbody></table>

### Chirpstack: ChirpStack: REST API (Payload JMESPath Expression)

- Manufacturer: Chirpstack
- Measurements: Variable measurements
- Libraries: chirpstack-rest-api, requests, jmespath

ChirpStack v4 REST API를 주기적으로 호출하여 디바이스 이벤트를 가져오고, 각 이벤트 JSON에 대해 채널별 JMESPath 표현식을 적용하여 측정값을 저장합니다. 예시(https://jmespath.org): object.battery_V, object.battery_pct, max_by(rxInfo,&rssi).rssi, deviceInfo.devEui.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>The duration to wait before the first operation</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>API Base URL</td><td>Text
- Default Value: http://localhost:8090</td><td>ChirpStack REST API의 기본 주소 (예: http://localhost:8080) (일반적으로 REST 프록시는 8090 포트)</td></tr><tr><td>API Token</td><td>Text</td><td>ChirpStack REST API 접근을 위한 Bearer 토큰 (관리 콘솔에서 발급)</td></tr><tr><td>Tenant ID</td><td>Text</td><td>선택 사항: 특정 테넌트에 속한 디바이스만 조회할 때 사용</td></tr><tr><td>Application ID</td><td>Text</td><td>선택 사항: 특정 애플리케이션에 속한 디바이스만 조회할 때 사용</td></tr><tr><td>Device EUIs (comma-separated)</td><td>Text</td><td>선택 사항: 조회할 디바이스 EUI를 콤마(,)로 구분해 입력. 비우면 애플리케이션의 모든 디바이스 대상</td></tr><tr><td>Page size / limit</td><td>Text
- Default Value: 50</td><td>한 번의 REST API 호출에서 가져올 이벤트 개수(페이지 크기)</td></tr><tr><td>Event kind</td><td>Text
- Default Value: up</td><td>가져올 이벤트의 종류 (예: up, join, status)</td></tr><tr><td>Fallback URL template</td><td>Text
- Default Value: /api/devices/{dev_eui}/events?limit={limit}&kind={kind}&after={after}</td><td>공식 파이썬 클라이언트를 사용할 수 없을 때 REST 요청에 사용할 URL 템플릿 (API Base URL 뒤에 연결됨). {dev_eui}, {limit}, {kind}, {after}가 자동 치환됨</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>JMESPath Expression</td><td>Text</td><td>Evaluated against the full event JSON</td></tr></tbody></table>

### Cozir: Cozir CO2

- Manufacturer: Cozir
- Measurements: CO2/Humidity/Temperature
- Interfaces: UART
- Libraries: pierre-haessig/pycozir
- Dependencies: [cozir](https://github.com/pierre-haessig/pycozir)
- Manufacturer URL: [Link](https://www.co2meter.com/products/cozir-2000-ppm-co2-sensor)
- Datasheet URL: [Link](https://cdn.shopify.com/s/files/1/0019/5952/files/Datasheet_COZIR_A_CO2Meter_4_15.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### ESA: GL: Soil Moisture (NASA SMAP)

- Manufacturer: ESA
- Measurements: Status
- Libraries: gis_esa
- Manufacturer URL: [Link](https://smap.jpl.nasa.gov/)

유럽우주국(ESA)의 Sentinel-2 위성 데이터를 기반으로 한 전 세계 토지 피복(Land Cover) 지도입니다. 식생, 도시, 농경지, 산림, 수역 등을 10m급 고해상도로 분석하여 색상별로 확인할 수 있어 환경 분석에 유용합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Date Mode</td><td>Select</td><tr><td>Custom Date</td><td>Text</td></tbody></table>

### Ecowitt: Ecowitt Cloud API Weather Data

- Manufacturer: Ecowitt

Ecowitt Cloud API를 사용하려면 Application Key, API Key, 장치 MAC 주소를 입력하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 60</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td>Application Key</td><td>Text</td><td>Ecowitt 플랫폼에서 발급받은 Application Key를 입력하세요.</td></tr><tr><td>API Key</td><td>Text</td><td>Ecowitt 플랫폼에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>Device MAC</td><td>Text</td><td>Ecowitt 장치의 MAC 주소를 입력하세요.</td></tr><tr><td>Call Back</td><td>Text
- Default Value: all</td><td>호출할 데이터 종류를 입력하세요 (예: all).</td></tr></tbody></table>

### Ecowitt: Ecowitt MQTT\(JSON payload)

- Manufacturer: Ecowitt
- Measurements: Variable measurements
- Interfaces: AoT
- Libraries: paho-mqtt, jmespath
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt), [jmespath](https://pypi.org/project/jmespath)

선택된 Ecowitt 장치 유형에 따라 자동 생성된 채널을 구독하고, MQTT 토픽으로 전송되는 URL 인코딩 또는 JSON 페이로드에서 각 채널의 JMESPATH 표현식으로 값을 추출하여 데이터베이스에 저장합니다. 채널별 측정 단위와 변환 설정을 사용자 정의 옵션으로 지정할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Ecowitt 장치</td><td>Select(Options: [<strong>기상대</strong> | 온습도 센서 | 온도 센서 | 토양 수분 센서 | 잎 센서 | 거리 측정기 | 공기질 측정기] (Default in <strong>bold</strong>)</td><tr><td>Host</td><td>Text
- Default Value: localhost</td><td>Host or IP address</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>Host port number</td></tr><tr><td>Topic</td><td>Text
- Default Value: gw</td><td>The topic to subscribe to</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>Maximum amount of time between received signals. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_SsE838CY</td><td>Unique client ID for connecting to the server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Send login credentials using TLS</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>Password</td><td>Text</td><td>Password for connecting to the server. Leave blank to disable.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>JMESPATH Expression</td><td>Text</td><td>JMESPATH expression to find value in JSON response</td></tr></tbody></table>

### Ecowitt: Ecowitt soil_sensor

- Manufacturer: Ecowitt

Ecowitt Cloud API를 사용하려면 Application Key, API Key, 장치 MAC 주소를 입력하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 60</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td>Application Key</td><td>Text</td><td>Ecowitt 플랫폼에서 발급받은 Application Key를 입력하세요.</td></tr><tr><td>API Key</td><td>Text</td><td>Ecowitt 플랫폼에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>Device MAC</td><td>Text</td><td>Ecowitt 장치의 MAC 주소를 입력하세요.</td></tr><tr><td>채널 선택</td><td>Text
- Default Value: 1</td><td>측정할 채널을 선택하세요.</td></tr></tbody></table>

### Ecowitt: Ecowitt temp and humidity sensor

- Manufacturer: Ecowitt

Ecowitt Cloud API를 사용하려면 Application Key, API Key, 장치 MAC 주소를 입력하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 60</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td>Application Key</td><td>Text</td><td>Ecowitt 플랫폼에서 발급받은 Application Key를 입력하세요.</td></tr><tr><td>API Key</td><td>Text</td><td>Ecowitt 플랫폼에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>Device MAC</td><td>Text</td><td>Ecowitt 장치의 MAC 주소를 입력하세요.</td></tr><tr><td>채널 선택</td><td>Text
- Default Value: 1</td><td>측정할 채널을 선택하세요.</td></tr></tbody></table>

### Esri: GL: Esri World Imagery

- Manufacturer: Esri
- Measurements: Status
- Libraries: gis_esri
- Manufacturer URL: [Link](https://www.esri.com/)

세계적인 GIS 기업 Esri의 공신력 있는 지도 서비스입니다. 선명하고 정교한 World Imagery 항공 위성 사진을 제공하여 지형의 세부 형상과 시설물을 정확하게 조망하기에 최적화되어 있습니다.


### GSI: JP: GSI Maps

- Manufacturer: GSI
- Measurements: Status
- Libraries: gis_gsi
- Manufacturer URL: [Link](https://maps.gsi.go.jp/)

일본 국토지리원(GSI)에서 제공하는 고정밀 공공 지도 서비스입니다. 일본 전역의 세부적인 지형과 지명 정보를 담고 있으며, 표준 지도뿐만 아니라 담색 지도, 항공 사진 등 전문적인 레이어를 활용할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Style</td></td></tbody></table>

### Generic: Hall Flow Meter

- Manufacturer: Generic
- Measurements: Flow Rate, Total Volume
- Interfaces: GPIO
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Pulses per Liter</td><td>Decimal
- Default Value: 1.0</td><td>Enter the conversion factor for this meter (pulses to Liter).</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Clear Total: Volume</td><td>Button</td><td></td></tr></tbody></table>

### Google: GL: Google Maps

- Manufacturer: Google
- Measurements: Status
- Libraries: gis_google
- Manufacturer URL: [Link](https://www.google.com/maps)

가장 널리 사용되는 구글의 웹 지도 서비스입니다. 방대한 지리 정보를 바탕으로 Road, Satellite, Hybrid, Terrain 등 4가지 모드를 지원하며, 특히 지형의 등고와 음영을 보여주는 Terrain 지도가 우수합니다. 또한, 구글의 Geocoding API를 이용하여 주소를 좌표로 변환할 수 있습니다. API 키는 구글 개발자 콘솔에서 발급 가능합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Google Maps API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

### ISRIC: GL: SoilGrids (Global Soil Info)

- Manufacturer: ISRIC
- Measurements: Status
- Libraries: gis_isric
- Manufacturer URL: [Link](https://soilgrids.org/)

세계 토양 정보 서비스(ISRIC)에서 제공하는 글로벌 토양 특성 지도입니다. 지질학적 분석을 위한 토양 성분(점토, 모래 등), pH 수치, 탄소 함유량 등 전 세계의 지하 자원 및 환경 정보를 레이어 형태로 시각화해 줍니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Soil Property</td></td></tbody></table>

### Infineon: DPS310

- Manufacturer: Infineon
- Measurements: Pressure/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_DPS310
- Dependencies: [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-dps310](https://pypi.org/project/adafruit-circuitpython-dps310)
- Manufacturer URL: [Link](https://www.infineon.com/cms/en/product/sensor/pressure-sensors/pressure-sensors-for-iot/dps310/)
- Datasheet URL: [Link](https://www.infineon.com/dgdl/Infineon-DPS310-DataSheet-v01_02-EN.pdf?fileId=5546d462576f34750157750826c42242)
- Product URLs: [Link 1](https://www.adafruit.com/product/4494), [Link 2](https://shop.pimoroni.com/products/adafruit-dps310-precision-barometric-pressure-altitude-sensor-stemma-qt-qwiic), [Link 3](https://www.berrybase.de/sensoren-module/luftdruck-wasserdruck/adafruit-dps310-pr-228-zisions-barometrischer-druck-und-h-246-hen-sensor)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### KMA: KMA 단기예보

- Manufacturer: KMA
- Additional URL: [Link](https://www.data.go.kr/index.do)

이 모듈은 농업용 단기예보 데이터를 제공합니다. 가장 최근 발표를 기준으로 사용자가 선택한 시간 뒤의 예보 데이터를 수집합니다. API 호출 시 공공데이터포털의 서비스키를 사용하고, JSON 응답에서 기온, 최저/최고 기온, 풍속, 풍향, 하늘상태, 습도, 강수량, 강수확률, 강수형태, 신적설 데이터를 추출합니다. (API 제공은 발표시간 + 10분 이후부터 이루어집니다.)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>API Key</td><td>Text</td><td>공공데이터포털에서 발급받은 KMA API 서비스키를 입력하세요.</td></tr><tr><td>nx 좌표</td><td>Text</td><td>nx 값을 입력하세요 (숫자).</td></tr><tr><td>ny 좌표</td><td>Text</td><td>ny 값을 입력하세요 (숫자).</td></tr><tr><td>몇 시간 뒤 예보</td><td>Select(Options: [<strong>1</strong> | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12] (Default in <strong>bold</strong>)</td><td>몇 시간 후의 예보 데이터를 사용할지 선택하세요.</td></tr><tr><td>API 타임아웃(초)</td><td>Integer
- Default Value: 60</td><td>API 응답 제한 시간을 설정하세요 (기본 60초).</td></tr><tr><td>API 재시도 횟수</td><td>Integer
- Default Value: 3</td><td>HTTP 오류 발생 시 같은 발표시각을 몇 번 재시도할지 설정하세요.</td></tr><tr><td>API 재시도 간격(초)</td><td>Decimal
- Default Value: 3.0</td><td>재시도 사이에 대기할 시간입니다 (기본 3초).</td></tr></tbody></table>

### KMA: 기상청 고해상도 500m

- Manufacturer: KMA
- Additional URL: [Link](https://apihub.kma.go.kr)

기상청 API 허브에서 무료 API 키를 발급받은 뒤, 입력 설정의 위치(위도/경도)에 따라 데이터를 요청합니다. 참고: 대한민국 기상청 API는 하루 20000회 호출이 가능하며, 1회 호출당 1개의 관측지점 데이터를 반환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>API Key</td><td>Text</td><td>기상청 API 허브에서 발급받은 API Key를 입력하세요.</td></tr><tr><td>측정 기간(초)</td><td>Decimal
- Default Value: 300</td><td>측정 주기를 초 단위로 입력하세요.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>품질검사(QC) 사용</td><td>Boolean
- Default Value: True</td><td>명백한 이상치(예: 습도 0%, 기압 0hPa 등)를 무시하거나 보정합니다.</td></tr><tr><td>QC 보정 유지시간(초)</td><td>Decimal
- Default Value: 1800</td><td>이 시간 내의 마지막 정상값으로 대체합니다.</td></tr><tr><td>수동 백필 기간(분)</td><td>Decimal
- Default Value: 1440</td><td>사용자 요청 시 과거 이 기간만큼 데이터를 불러옵니다. 기본 1440분(1일).</td></tr><tr><td>지금 백필 실행</td><td>Boolean</td><td>저장 후 활성화하면 즉시 백필을 1회 수행하고 자동으로 해제됩니다.</td></tr><tr><td>KMA 타임스탬프 오프셋(시간)</td><td>Decimal
- Default Value: 9</td><td>KMA 응답 시각이 로컬(KST,+9) 기준일 때 UTC로 저장하기 위해 빼줄 시간 (기본 9).</td></tr><tr><td>강수 계열 시계열 분리</td><td>Boolean
- Default Value: True</td><td>강수 지표(rn_ox)와 15분 강수(rn_15m)를 서로 다른 측정명으로 기록해 충돌을 방지합니다.</td></tr><tr><td>QC: 0°C 허용 범위(±°C)</td><td>Decimal
- Default Value: 3.0</td><td>직전 정상값이 0°C에서 이 범위 이내일 때만 0°C를 허용합니다. 기본 ±3°C.</td></tr></tbody></table>

### KMA: 기상청 지점 데이터

- Manufacturer: KMA
- Measurements: 습도/온도/기압/풍속/풍향
- Additional URL: [Link](https://apihub.kma.go.kr)

기상청 API 허브에서 무료 API 키를 발급받고 가까운 관측지점의 STN을 입력하세요.참고: 무료 API는 하루 20000회 호출이 가능하며, 1회 호출당 1개의 관측지점 데이터를 반환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>API Key</td><td>Text</td><td>The API Key for this service's API</td></tr><tr><td>stn</td><td>Text</td><td>The stn to acquire the weather data</td></tr></tbody></table>

### Kakao: KO: Kakao Map

- Manufacturer: Kakao
- Measurements: Status
- Libraries: gis_kakao
- Manufacturer URL: [Link](https://map.kakao.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Type</td></td></tbody></table>

### MAXIM: DS1822

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS1822.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS1822.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>Select</td><td>Select the resolution for the sensor</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS1825

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS1825.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS1825.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>Select</td><td>Select the resolution for the sensor</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS18B20 (ow-shell)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: ow-shell
- Dependencies: [ow-shell](https://packages.debian.org/search?keywords=ow-shell), [owfs](https://packages.debian.org/search?keywords=owfs)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS18B20.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS18B20.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/374), [Link 2](https://www.adafruit.com/product/381), [Link 3](https://www.sparkfun.com/products/245)
- Additional URL: [Link](https://github.com/cpetrich/counterfeit_DS18B20)

Warning: Counterfeit DS18B20 sensors are common and can cause a host of issues. Review the Additional URL for more information about how to determine if your sensor is authentic.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### MAXIM: DS18B20 (w1thermsensor)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS18B20.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS18B20.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/374), [Link 2](https://www.adafruit.com/product/381), [Link 3](https://www.sparkfun.com/products/245)
- Additional URL: [Link](https://github.com/cpetrich/counterfeit_DS18B20)

Warning: Counterfeit DS18B20 sensors are common and can cause a host of issues. Review the Additional URL for more information about how to determine if your sensor is authentic.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>The temperature offset (degrees Celsius) to apply</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>Select</td><td>Select the resolution for the sensor</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS18S20

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/DS18S20.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS18S20.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>Select</td><td>Select the resolution for the sensor</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: DS28EA00

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/DS28EA00.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/DS28EA00.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>Select</td><td>Select the resolution for the sensor</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: MAX31850K

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: 1-Wire
- Libraries: w1thermsensor
- Dependencies: [w1thermsensor](https://pypi.org/project/w1thermsensor)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/MAX31850EVKIT.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31850-MAX31851.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1727)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Set the resolution, precision, and response time for the sensor. This setting will be written to the EEPROM to allow persistence after power loss. The EEPROM has a limited amount of writes (>50k).</td></tr><tr><td>Resolution</td><td>Select</td><td>Select the resolution for the sensor</td></tr><tr><td>Set Resolution</td><td>Button</td><td></td></tr></tbody></table>

### MAXIM: MAX31855 (Gravity PT100) (smbus2)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.dfrobot.com/product-1753.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### MAXIM: MAX31855 (Gravity PT100) (wiringpi)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: wiringpi
- Dependencies: [wiringpi](https://pypi.org/project/wiringpi)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.dfrobot.com/product-1753.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### MAXIM: MAX31855 (Adafruit_MAX31855)

- Manufacturer: MAXIM
- Measurements: Temperature (Object/Die)
- Interfaces: UART
- Libraries: Adafruit_MAX31855
- Dependencies: [Adafruit_MAX31855](https://github.com/adafruit/Adafruit_Python_MAX31855), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.adafruit.com/product/269)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (using BCM numbering): Pin: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### MAXIM: MAX31855 (adafruit-circuitpython-max31855)

- Manufacturer: MAXIM
- Measurements: Temperature (Object/Die)
- Interfaces: SPI
- Libraries: adafruit-circuitpython-max31855
- Dependencies: [adafruit-circuitpython-max31855](https://pypi.org/project/adafruit-circuitpython-max31855)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31855.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf)
- Product URL: [Link](https://www.adafruit.com/product/269)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Chip Select Pin</td><td>Integer
- Default Value: 5</td><td>Enter the GPIO Chip Select Pin for your device.</td></tr></tbody></table>

### MAXIM: MAX31856

- Manufacturer: MAXIM
- Measurements: Temperature (Object/Die)
- Interfaces: UART
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/sensors/MAX31856.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31856.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3263)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (using BCM numbering): Pin: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### MAXIM: MAX31865 (Adafruit-CircuitPython-MAX31865)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: SPI
- Libraries: Adafruit-CircuitPython-MAX31865
- Dependencies: [adafruit-circuitpython-max31865](https://pypi.org/project/adafruit-circuitpython-max31865)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31865.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31865.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3328)

This module was added to allow support for multiple sensors to be connected at the same time, which the original MAX31865 module was not designed for.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Chip Select Pin</td><td>Integer
- Default Value: 8</td><td>Enter the GPIO Chip Select Pin for your device.</td></tr><tr><td>Number of wires</td><td>Select(Options: [<strong>2 Wires</strong> | 3 Wires | 4 Wires] (Default in <strong>bold</strong>)</td><td>Select the number of wires your thermocouple has.</td></tr></tbody></table>

### MAXIM: MAX31865 (RPi.GPIO)

- Manufacturer: MAXIM
- Measurements: Temperature
- Interfaces: UART
- Libraries: RPi.GPIO
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URL: [Link](https://www.maximintegrated.com/en/products/interface/sensor-interface/MAX31865.html)
- Datasheet URL: [Link](https://datasheets.maximintegrated.com/en/ds/MAX31865.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3328)

Note: This module does not allow for multiple sensors to be connected at the same time. For multi-sensor support, use the MAX31865 CircuitPython Input.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (using BCM numbering): Pin: Cable Select</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### MQTT: MQTT Subscribe (JSON payload)

- Manufacturer: MQTT
- Measurements: Variable measurements
- Interfaces: AoT
- Libraries: paho-mqtt, jmespath
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt), [jmespath](https://pypi.org/project/jmespath)

A single topic is subscribed to and the returned JSON payload contains one or more key/value pairs. The given JSON Key is used as a JMESPATH expression to find the corresponding value that will be stored for that channel. Be sure you select and save the Measurement Unit for each channel. Once the unit has been saved, you can convert to other units in the Convert Measurement section. Example expressions for jmespath (https://jmespath.org) include <i>temperature</i>, <i>sensors[0].temperature</i>, and <i>bathroom.temperature</i> which refer to the temperature as a direct key within the first entry of sensors or as a subkey of bathroom, respectively. Jmespath elements and keys that contain special characters have to be enclosed in double quotes, e.g. <i>"sensor-1".temperature</i>. Warning: If using multiple MQTT Inputs or Functions, ensure the Client IDs are unique.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Host</td><td>Text
- Default Value: localhost</td><td>Host or IP address</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>Host port number</td></tr><tr><td>Topic</td><td>Text
- Default Value: mqtt/test/input</td><td>The topic to subscribe to</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>Maximum amount of time between received signals. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_0Rd3a2p7</td><td>Unique client ID for connecting to the server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Send login credentials using TLS</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>Password</td><td>Text</td><td>Password for connecting to the server. Leave blank to disable.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>JMESPATH Expression</td><td>Text</td><td>JMESPATH expression to find value in JSON response</td></tr></tbody></table>

### MQTT: MQTT Subscribe (Value payload)

- Manufacturer: MQTT
- Measurements: Variable measurements
- Interfaces: AoT
- Libraries: paho-mqtt
- Dependencies: [paho-mqtt](https://pypi.org/project/paho-mqtt)

A topic is subscribed to for each channel Subscription Topic and the returned payload value will be stored for that channel. Be sure you select and save the Measurement Unit for each of the channels. Once the unit has been saved, you can convert to other units in the Convert Measurement section. Warning: If using multiple MQTT Inputs or Functions, ensure the Client IDs are unique.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Host</td><td>Text
- Default Value: localhost</td><td>Host or IP address</td></tr><tr><td>Port</td><td>Integer
- Default Value: 1883</td><td>Host port number</td></tr><tr><td>Keep Alive</td><td>Integer
- Default Value: 60</td><td>Maximum amount of time between received signals. Set to 0 to disable.</td></tr><tr><td>Client ID</td><td>Text
- Default Value: client_oLmvWD4k</td><td>Unique client ID for connecting to the server</td></tr><tr><td>Use Login</td><td>Boolean</td><td>Send login credentials</td></tr><tr><td>Use TLS</td><td>Boolean</td><td>Send login credentials using TLS</td></tr><tr><td>Username</td><td>Text
- Default Value: user</td><td>Username for connecting to the server</td></tr><tr><td>Password</td><td>Text</td><td>Password for connecting to the server. Leave blank to disable.</td></tr><tr><td>Use Websockets</td><td>Boolean</td><td>Use websockets to connect to the server.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>Subscription Topic</td><td>Text</td><td>The MQTT topic to subscribe to</td></tr></tbody></table>

### Mapbox: GL: Mapbox

- Manufacturer: Mapbox
- Measurements: Status
- Libraries: gis_mapbox
- Manufacturer URL: [Link](https://www.mapbox.com/)

세련된 디자인과 커스터마이징이 강점인 맵박스의 벡터 및 타일 지도입니다. Streets, Satellite, Dark, Light 스타일을 지원하며, 렌더링 성능이 매우 우수하여 부드러운 지도 조작 환경을 제공합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Mapbox Access Token</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

### Melexis: MLX90393

- Manufacturer: Melexis
- Measurements: Magnetic Flux
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_MLX90393
- Dependencies: [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-mlx90393](https://pypi.org/project/adafruit-circuitpython-mlx90393)
- Manufacturer URL: [Link](https://www.melexis.com/en/product/MLX90393/Triaxis-Micropower-Magnetometer)
- Datasheet URL: [Link](https://cdn-learn.adafruit.com/assets/assets/000/069/600/original/MLX90393-Datasheet-Melexis.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/4022), [Link 2](https://shop.pimoroni.com/products/adafruit-wide-range-triple-axis-magnetometer-mlx90393), [Link 3](https://www.berrybase.de/sensoren-module/bewegung-distanz/adafruit-wide-range-drei-achsen-magnetometer-mlx90393)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Melexis: MLX90614

- Manufacturer: Melexis
- Measurements: Temperature (Ambient/Object)
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.melexis.com/en/product/MLX90614/Digital-Plug-Play-Infrared-Thermometer-TO-Can)
- Datasheet URL: [Link](https://www.melexis.com/-/media/files/documents/datasheets/mlx90614-datasheet-melexis.pdf)
- Product URL: [Link](https://www.sparkfun.com/products/9570)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Microchip: MCP3008 (Adafruit_CircuitPython_MCP3xxx)

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: UART
- Libraries: Adafruit_CircuitPython_MCP3xxx
- Dependencies: [adafruit-circuitpython-mcp3xxx](https://pypi.org/project/adafruit-circuitpython-mcp3xxx)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en010530)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/DeviceDoc/21295d.pdf)
- Product URL: [Link](https://www.adafruit.com/product/856)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (using BCM numbering): Pin: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 3.3</td><td>Set the VREF voltage</td></tr></tbody></table>

### Microchip: MCP3008 (Adafruit_MCP3008)

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: UART
- Libraries: Adafruit_MCP3008
- Dependencies: [Adafruit-MCP3008](https://pypi.org/project/Adafruit-MCP3008)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en010530)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/DeviceDoc/21295d.pdf)
- Product URL: [Link](https://www.adafruit.com/product/856)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (using BCM numbering): Pin: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 3.3</td><td>Set the VREF voltage</td></tr></tbody></table>

### Microchip: MCP3208

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: SPI
- Libraries: MCP3208
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO)
- Manufacturer URL: [Link](https://www.microchip.com/en-us/product/MCP3208)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/devicedoc/21298e.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Pin: Cable Select</td><td>Integer</td><td>GPIO (using BCM numbering): Pin: Cable Select</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus ID.</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device ID.</td></tr><tr><td>VREF (volts)</td><td>Decimal
- Default Value: 3.3</td><td>Set the VREF voltage</td></tr></tbody></table>

### Microchip: MCP342x (x=2,3,4,6,7,8)

- Manufacturer: Microchip
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: MCP342x
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [MCP342x](https://pypi.org/project/MCP342x)
- Manufacturer URLs: [Link 1](https://www.microchip.com/wwwproducts/en/MCP3422), [Link 2](https://www.microchip.com/wwwproducts/en/MCP3423), [Link 3](https://www.microchip.com/wwwproducts/en/MCP3424), [Link 4](https://www.microchip.com/wwwproducts/en/MCP3426https://www.microchip.com/wwwproducts/en/MCP3427), [Link 5](https://www.microchip.com/wwwproducts/en/MCP3428)
- Datasheet URLs: [Link 1](http://ww1.microchip.com/downloads/en/DeviceDoc/22088c.pdf), [Link 2](http://ww1.microchip.com/downloads/en/DeviceDoc/22226a.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Microchip: MCP9808

- Manufacturer: Microchip
- Measurements: Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_MCP9808
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit_MCP9808](https://github.com/adafruit/Adafruit_Python_MCP9808)
- Manufacturer URL: [Link](https://www.microchip.com/wwwproducts/en/en556182)
- Datasheet URL: [Link](http://ww1.microchip.com/downloads/en/DeviceDoc/MCP9808-0.5C-Maximum-Accuracy-Digital-Temperature-Sensor-Data-Sheet-DS20005095B.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1782)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Microsoft: GL: Bing Maps

- Manufacturer: Microsoft
- Measurements: Status
- Libraries: gis_bing
- Manufacturer URL: [Link](https://www.bing.com/maps)

마이크로소프트의 글로벌 지도 서비스입니다. 고해상도 항공 사진(Aerial)과 이름이 포함된 항공 사진(Hybrid)을 제공하며, MS만의 깨끗하고 정밀한 도로 지도를 활용할 수 있는 장점이 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bing Maps API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

### Multiple Manufacturers: HC-SR04

- Manufacturer: Multiple Manufacturers
- Measurements: Ultrasonic Distance
- Interfaces: GPIO
- Libraries: Adafruit_CircuitPython_HCSR04
- Dependencies: [libgpiod-dev](https://packages.debian.org/search?keywords=libgpiod-dev), [pyusb](https://pypi.org/project/pyusb), [adafruit-circuitpython-hcsr04](https://pypi.org/project/adafruit-circuitpython-hcsr04)
- Manufacturer URL: [Link](https://www.cytron.io/p-5v-hc-sr04-ultrasonic-sensor)
- Datasheet URL: [Link](http://web.eece.maine.edu/~zhu/book/lab/HC-SR04%20User%20Manual.pdf)
- Product URL: [Link](https://www.adafruit.com/product/3942)
- Additional URL: [Link](https://learn.adafruit.com/ultrasonic-sonar-distance-sensors/python-circuitpython)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Trigger Pin</td><td>Integer</td><td>Enter the GPIO Trigger Pin for your device (BCM numbering).</td></tr><tr><td>Echo Pin</td><td>Integer</td><td>Enter the GPIO Echo Pin for your device (BCM numbering).</td></tr></tbody></table>

### NASA: NASA GIBS

- Manufacturer: NASA
- Measurements: Status
- Interfaces: AoT
- Libraries: gis_nasa_gibs
- Manufacturer URL: [Link](https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs)

미국 항공우주국(NASA)의 위성 관측 시스템(GIBS)을 통해 수집된 실시간 지구 관측 지도입니다. 위성 사진(Blue Marble)뿐만 아니라 기온, 구름, 화재 등 환경 관련 데이터를 날짜별로 선택하여 시계열 분석이 가능합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Satellite Layer</td></td><tr><td>Date Mode</td><td>Select</td><tr><td>Custom Date</td><td>Text</td></tbody></table>

### Naver: KO: Naver Map

- Manufacturer: Naver
- Measurements: Status
- Libraries: gis_naver
- Manufacturer URL: [Link](https://map.naver.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Type</td></td></tbody></table>

### OpenStreetMap: GL: OpenStreetMap

- Manufacturer: OpenStreetMap
- Measurements: Status
- Libraries: gis_osm
- Manufacturer URL: [Link](https://www.openstreetmap.org/)

전 세계 사용자들이 협업하여 만든 위키피디아 방식의 자유 지도 데이터입니다. 무료로 사용 가능하며, 전 세계 도로와 건물 정보가 꾸준히 업데이트되는 활발한 커뮤니티 성격의 표준 웹 지도입니다.


### OpenTopoMap: GL: OpenTopoMap

- Manufacturer: OpenTopoMap
- Measurements: Status
- Libraries: gis_opentopomap
- Manufacturer URL: [Link](https://opentopomap.org)

OpenStreetMap 데이터를 기반으로 등고선과 지형 음영을 강조한 지형도 서비스입니다. 산악 지형이나 경사면 분석 시 구분이 명확하며 가독성이 높아 등산이나 야외 활동 관련 시각화에 적합합니다.


### OpenWeather: OpenWeatherMap (City/Coords, Current)

- Manufacturer: OpenWeather
- Measurements: Humidity/Temperature/Pressure/Wind
- Additional URL: [Link](https://openweathermap.org)

Obtain a free API key at openweathermap.org. Enter a City OR Latitude/Longitude coordinates. Note: the free API subscription is limited to 60 calls per minute
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>API Key</td><td>Text</td><td>The API Key for this service's API</td></tr><tr><td>City</td><td>Text</td><td>City Name (Optional if using Coords)</td></tr></tbody></table>

### OpenWeather: OpenWeatherMap (Lat/Lon, Current/Future)

- Manufacturer: OpenWeather
- Measurements: Humidity/Temperature/Pressure/Wind
- Interfaces: AoT
- Additional URL: [Link](https://openweathermap.org)

Obtain a free API key at openweathermap.org. Notes: The free API subscription is limited to 60 calls per minute. If a Day (Future) time is selected, Minimum and Maximum temperatures are available as measurements.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>API Key</td><td>Text</td><td>The API Key for this service's API</td></tr><tr><td>Time</td><td>Select(Options: [<strong>Current (Present)</strong> | 1 Day (Future) | 2 Day (Future) | 3 Day (Future) | 4 Day (Future) | 5 Day (Future) | 6 Day (Future) | 7 Day (Future) | 1 Hour (Future) | 2 Hours (Future) | 3 Hours (Future) | 4 Hours (Future) | 5 Hours (Future) | 6 Hours (Future) | 7 Hours (Future) | 8 Hours (Future) | 9 Hours (Future) | 10 Hours (Future) | 11 Hours (Future) | 12 Hours (Future) | 13 Hours (Future) | 14 Hours (Future) | 15 Hours (Future) | 16 Hours (Future) | 17 Hours (Future) | 18 Hours (Future) | 19 Hours (Future) | 20 Hours (Future) | 21 Hours (Future) | 22 Hours (Future) | 23 Hours (Future) | 24 Hours (Future) | 25 Hours (Future) | 26 Hours (Future) | 27 Hours (Future) | 28 Hours (Future) | 29 Hours (Future) | 30 Hours (Future) | 31 Hours (Future) | 32 Hours (Future) | 33 Hours (Future) | 34 Hours (Future) | 35 Hours (Future) | 36 Hours (Future) | 37 Hours (Future) | 38 Hours (Future) | 39 Hours (Future) | 40 Hours (Future) | 41 Hours (Future) | 42 Hours (Future) | 43 Hours (Future) | 44 Hours (Future) | 45 Hours (Future) | 46 Hours (Future) | 47 Hours (Future) | 48 Hours (Future)] (Default in <strong>bold</strong>)</td><td>Select the time for the current or forecast weather</td></tr></tbody></table>

### OpenWeatherMap: GL: OpenWeatherMap

- Manufacturer: OpenWeatherMap
- Measurements: Status
- Libraries: gis_openweather
- Manufacturer URL: [Link](https://openweathermap.org/)

전 세계 날씨 정보를 지도에 중첩하여 보여주는 기상 전문 서비스입니다. 구름, 강수량, 기온, 풍속, 기압 및 레이더 정보를 실시간으로 제공하여 현재 기상 상황을 직관적으로 파악할 수 있게 돕습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>Active Layers</td></td></tbody></table>

### Panasonic: AMG8833

- Manufacturer: Panasonic
- Measurements: 8x8 Temperature Grid
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_AMG88xx/Pillow/colour
- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [colour](https://pypi.org/project/colour), [Pillow](https://pypi.org/project/Pillow), [Adafruit_AMG88xx](https://github.com/adafruit/Adafruit_AMG88xx_python)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Power Monitor: RPi 6-Channel Power Monitor (v0.1.0)

- Manufacturer: Power Monitor
- Measurements: AC Voltage, Power, Current, Power Factor
- Libraries: rpi-power-monitor
- Dependencies: [rpi_power_monitor](https://github.com/aot-inc/rpi-power-monitor)
- Manufacturer URL: [Link](https://github.com/David00/rpi-power-monitor)
- Product URL: [Link](https://power-monitor.dalbrecht.tech/)

See https://github.com/David00/rpi-power-monitor/wiki/Calibrating-for-Accuracy for calibration procedures.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Grid Voltage</td><td>Decimal
- Default Value: 124.2</td><td>The AC voltage measured at the outlet</td></tr><tr><td>Transformer Voltage</td><td>Decimal
- Default Value: 10.2</td><td>The AC voltage measured at the barrel plug of the 9 VAC transformer</td></tr><tr><td>CT1 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>The phase correction value for CT1</td></tr><tr><td>CT2 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>The phase correction value for CT2</td></tr><tr><td>CT3 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>The phase correction value for CT3</td></tr><tr><td>CT4 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>The phase correction value for CT4</td></tr><tr><td>CT5 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>The phase correction value for CT5</td></tr><tr><td>CT6 Phase Correction</td><td>Decimal
- Default Value: 1.0</td><td>The phase correction value for CT6</td></tr><tr><td>CT1 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The accuracy calibration value for CT1</td></tr><tr><td>CT2 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The accuracy calibration value for CT2</td></tr><tr><td>CT3 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The accuracy calibration value for CT3</td></tr><tr><td>CT4 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The accuracy calibration value for CT4</td></tr><tr><td>CT5 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The accuracy calibration value for CT5</td></tr><tr><td>CT6 Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The accuracy calibration value for CT6</td></tr><tr><td>AC Accuracy Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The accuracy calibration value for AC</td></tr></tbody></table>

### Power Monitor: RPi 6-Channel Power Monitor (v0.4.0)

- Manufacturer: Power Monitor
- Measurements: AC Voltage, Power, Energy, Current, Power Factor
- Libraries: rpi-power-monitor
- Dependencies: [rpi_power_monitor](https:/)
- Manufacturer URL: [Link](https://github.com/David00/rpi-power-monitor)
- Product URL: [Link](https://power-monitor.dalbrecht.tech/)

See https://david00.github.io/rpi-power-monitor/docs/v0.3.0/calibration.html for calibration documentation.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Period (Seconds) for kWh Measuring</td><td>Integer
- Default Value: 5</td><td>How often to acquire measurements to calculate kWh</td></tr><tr><td>Grid Voltage</td><td>Decimal
- Default Value: 124.2</td><td>The AC voltage measured at the outlet</td></tr><tr><td>Transformer Voltage</td><td>Decimal
- Default Value: 10.2</td><td>The AC voltage measured at the barrel plug of the 9 VAC transformer</td></tr><tr><td>AC Frequency (Hz)</td><td>Integer
- Default Value: 60</td><td>The frequency of the AC voltage</td></tr><tr><td>CT1 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The calibration value for CT1</td></tr><tr><td>CT1 Rating</td><td>Decimal
- Default Value: 100</td><td>The Amp rating for the CT1 clamp</td></tr><tr><td>CT2 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The calibration value for CT2</td></tr><tr><td>CT2 Rating</td><td>Decimal
- Default Value: 100</td><td>The Amp rating for the CT2 clamp</td></tr><tr><td>CT3 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The calibration value for CT3</td></tr><tr><td>CT3 Rating</td><td>Decimal
- Default Value: 100</td><td>The Amp rating for the CT3 clamp</td></tr><tr><td>CT4 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The calibration value for CT4</td></tr><tr><td>CT4 Rating</td><td>Decimal
- Default Value: 100</td><td>The Amp rating for the CT4 clamp</td></tr><tr><td>CT5 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The calibration value for CT5</td></tr><tr><td>CT5 Rating</td><td>Decimal
- Default Value: 100</td><td>The Amp rating for the CT5 clamp</td></tr><tr><td>CT6 Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The calibration value for CT6</td></tr><tr><td>CT6 Rating</td><td>Decimal
- Default Value: 100</td><td>The Amp rating for the CT6 clamp</td></tr><tr><td>AC Calibration</td><td>Decimal
- Default Value: 1.0</td><td>The calibration value for AC</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Clear the running kWh totals.</td></tr><tr><td>Channel to Clear</td><td>Select(Options: [All Channels | <strong>Channel 1</strong> | Channel 2 | Channel 3 | Channel 4 | Channel 5 | Channel 6] (Default in <strong>bold</strong>)</td><td>The channel(s) to clear the kWh total and start back at 0.</td></tr><tr><td>Clear kWh Total</td><td>Button</td><td></td></tr></tbody></table>

### ROHM: BH1750

- Manufacturer: ROHM
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Datasheet URL: [Link](http://rohmfs.rohm.com/en/products/databook/datasheet/ic/sensor/light/bh1721fvc-e.pdf)
- Product URL: [Link](https://www.dfrobot.com/product-531.html)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### RainViewer: GL: RainViewer (Radar) [Discontinued]

- Manufacturer: RainViewer
- Measurements: Status
- Libraries: gis_rainviewer
- Manufacturer URL: [Link](https://www.rainviewer.com/)

[Service Discontinued / 서비스 중단 안내] RainViewer의 Radar API 서비스가 2026년 1월 31일부로 종료되었습니다. 현재 이 레이어의 실시간 데이터 수신은 불가능합니다. 대안으로 OpenWeatherMap (Radar) 레이어 사용을 권장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>Color Scheme</td><td>Select</td><tr><td>Smoothing</td><td>Boolean</td></tbody></table>

### Raspberry Pi Foundation: Sense HAT

- Manufacturer: Raspberry Pi Foundation
- Measurements: hum/temp/press/compass/magnet/accel/gyro
- Interfaces: I<sup>2</sup>C
- Libraries: sense-hat
- Dependencies: [git](https://packages.debian.org/search?keywords=git), Bash Commands (see Module for details), [sense-hat](https://pypi.org/project/sense-hat)
- Manufacturer URL: [Link](https://www.raspberrypi.org/products/sense-hat/)

This module acquires measurements from the Raspberry Pi Sense HAT sensors, which include the LPS25H, LSM9DS1, and HTS221.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Remote Sensing: Satellite Analysis

- Manufacturer: Remote Sensing
- Measurements: Analysis Channels
- Interfaces: AoT
- Libraries: requests

Collects environmental data from satellite analysis and GIS layers based on the device location. Supports auto-adjustment for data gaps (e.g. coastal areas).
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Active GIS Source</td><td>Select</td><td>Select the satellite/GIS analysis source.</td></tr><tr><td>Auto-adjust Location</td><td>Boolean
- Default Value: True</td><td>Automatically search nearby valid coordinates if data is missing at the exact location (Spiral Search).</td></tr></tbody></table>

### Ruuvi: RuuviTag

- Manufacturer: Ruuvi
- Measurements: Acceleration/Humidity/Pressure/Temperature
- Interfaces: BT
- Libraries: ruuvitag_sensor
- Dependencies: [psutil](https://pypi.org/project/psutil), [bluez](https://packages.debian.org/search?keywords=bluez), [bluez-hcidump](https://packages.debian.org/search?keywords=bluez-hcidump), [ruuvitag-sensor](https://pypi.org/project/ruuvitag-sensor)
- Manufacturer URL: [Link](https://ruuvi.com/)
- Datasheet URL: [Link](https://ruuvi.com/files/ruuvitag-tech-spec-2019-7.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>Text</td><td>The Hci location of the Bluetooth device.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>Text</td><td>The adapter of the Bluetooth device.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### STMicroelectronics: VL53L0X

- Manufacturer: STMicroelectronics
- Measurements: Millimeter (Time-of-Flight Distance)
- Interfaces: I<sup>2</sup>C
- Libraries: VL53L0X_rasp_python
- Dependencies: [VL53L0X](https://github.com/grantramsay/VL53L0X_rasp_python)
- Manufacturer URL: [Link](https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html)
- Datasheet URL: [Link](https://www.st.com/resource/en/datasheet/vl53l0x.pdf)
- Product URLs: [Link 1](https://www.adafruit.com/product/3317), [Link 2](https://www.pololu.com/product/2490)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Accuracy</td><td>Select(Options: [<strong>Good Accuracy (33 ms, 1.2 m range)</strong> | Better Accuracy (66 ms, 1.2 m range) | Best Accuracy (200 ms, 1.2 m range) | Long Range (33 ms, 2 m) | High Speed, Low Accuracy (20 ms, 1.2 m)] (Default in <strong>bold</strong>)</td><td>Set the accuracy. A longer measurement duration yields a more accurate measurement</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x52</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### STMicroelectronics: VL53L1X

- Manufacturer: STMicroelectronics
- Measurements: Millimeter (Time-of-Flight Distance)
- Interfaces: I<sup>2</sup>C
- Libraries: VL53L1X
- Dependencies: [smbus2](https://pypi.org/project/smbus2), [vl53l1x](https://pypi.org/project/vl53l1x)
- Manufacturer URL: [Link](https://www.st.com/en/imaging-and-photonics-solutions/vl53l1x.html)
- Datasheet URL: [Link](https://www.st.com/resource/en/datasheet/vl53l1x.pdf)
- Product URLs: [Link 1](https://www.pololu.com/product/3415), [Link 2](https://www.sparkfun.com/products/14722)

Notes when setting a custom timing budget: A higher timing budget results in greater measurement accuracy, but also a higher power consumption. The inter measurement period must be >= the timing budget, otherwise it will be double the expected value.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Range</td><td>Select(Options: [<strong>Short Range</strong> | Medium Range | Long Range | Custom Timing Budget] (Default in <strong>bold</strong>)</td><td>Select a range or select to set a custom Timing Budget and Inter Measurement Period.</td></tr><tr><td>Timing Budget (microseconds)</td><td>Integer
- Default Value: 66000</td><td>Set the timing budget. Must be less than or equal to the Inter Measurement Period.</td></tr><tr><td>Inter Measurement Period (milliseconds)</td><td>Integer
- Default Value: 70</td><td>Set the Inter Measurement Period</td></tr></tbody></table>

### STMicroelectronics: VL53L4CD

- Manufacturer: STMicroelectronics
- Measurements: Millimeter (Time-of-Flight Distance)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit-CircuitPython-VL53l4CD
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-vl53l4cd](https://pypi.org/project/adafruit-circuitpython-vl53l4cd)
- Manufacturer URL: [Link](https://www.st.com/en/imaging-and-photonics-solutions/VL53L4CD.html)
- Datasheet URL: [Link](https://www.st.com/resource/en/datasheet/VL53L4CDpdf)
- Product URL: [Link](https://www.adafruit.com/product/3317)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Timing Budget (ms)</td><td>Integer
- Default Value: 50</td><td>Set the timing budget between 10 to 200 ms. A longer duration yields a more accurate measurement.</td></tr><tr><td>Inter-Measurement Period (ms)</td><td>Integer</td><td>Valid range between Timing Budget and 5000 ms (0 to disable)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The I2C address of the sensor can be changed. Enter a new address in the 0xYY format (e.g. 0x22, 0x50), then press Set I2C Address. Remember to deactivate the Input and change the I2C address option after setting the new address.</td></tr><tr><td>New I2C Address</td><td>Text
- Default Value: 0x29</td><td>The new I2C to set the device to</td></tr><tr><td>Set I2C Address</td><td>Button</td><td></td></tr></tbody></table>

### Seeedstudio: DHT11/22

- Manufacturer: Seeedstudio
- Measurements: Humidity/Temperature
- Interfaces: GROVE
- Libraries: grovepi
- Dependencies: [libatlas-base-dev](https://packages.debian.org/search?keywords=libatlas-base-dev), [grovepi](https://pypi.org/project/grovepi)
- Manufacturer URLs: [Link 1](https://wiki.seeedstudio.com/Grove-Temperature_and_Humidity_Sensor_Pro/), [Link 2](https://wiki.seeedstudio.com/Grove-TemperatureAndHumidity_Sensor/)

Enter the Grove Pi+ GPIO pin connected to the sensor and select the sensor type.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Sensor Type</td><td>Select(Options: [<strong>DHT11 (Blue)</strong> | DHT22 (White)] (Default in <strong>bold</strong>)</td><td>Sensor type</td></tr></tbody></table>

### Senseair: K96

- Manufacturer: Senseair
- Measurements: Methane/Moisture/CO2/Pressure/Humidity/Temperature
- Interfaces: UART
- Libraries: Serial
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Sensirion: SCD-4x (40, 41)

- Manufacturer: Sensirion
- Measurements: CO2/Temperature/Humidity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SCD4x
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-scd4x](https://pypi.org/project/adafruit-circuitpython-scd4x)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/carbon-dioxide-sensors/carbon-dioxide-sensor-scd4x/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Offset</td><td>Decimal
- Default Value: 4.0</td><td>Set the sensor temperature offset</td></tr><tr><td>Altitude (m)</td><td>Integer</td><td>Set the sensor altitude (meters)</td></tr><tr><td>Automatic Self-Calibration</td><td>Boolean</td><td>Set the sensor automatic self-calibration</td></tr><tr><td>Persist Settings</td><td>Boolean
- Default Value: True</td><td>Settings will persist after powering off</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">You can force the CO2 calibration for a specific CO2 concentration value (in ppmv). The sensor needs to be active for at least 3 minutes prior to calibration.</td></tr><tr><td>CO2 Concentration (ppmv)</td><td>Decimal
- Default Value: 400.0</td><td>Calibrate to this CO2 concentration that the sensor is being exposed to (in ppmv)</td></tr><tr><td>Calibrate CO2</td><td>Button</td><td></td></tr></tbody></table>

### Sensirion: SCD30 (Adafruit_CircuitPython_SCD30)

- Manufacturer: Sensirion
- Measurements: CO2/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SCD30
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitPython-scd30](https://pypi.org/project/adafruit-circuitPython-scd30)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/carbon-dioxide-sensors/carbon-dioxide-sensors-co2/)
- Datasheet URL: [Link](https://www.sensirion.com/fileadmin/user_upload/customers/sensirion/Dokumente/9.5_CO2/Sensirion_CO2_Sensors_SCD30_Datasheet.pdf)
- Product URLs: [Link 1](https://www.sparkfun.com/products/15112), [Link 2](https://www.futureelectronics.com/p/4115766)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">I2C Frequency: The SCD-30 has temperamental I2C with clock stretching. The datasheet recommends starting at 50,000 Hz.</td></tr><tr><td>I2C Frequency (Hz)</td><td>Integer
- Default Value: 50000</td><tr><td colspan="3">Automatic Self Ccalibration (ASC): To work correctly, the sensor must be on and active for 7 days after enabling ASC, and exposed to fresh air for at least 1 hour per day. Consult the manufacturer’s documentation for more information.</td></tr><tr><td>Enable Automatic Self Calibration</td><td>Boolean</td><tr><td colspan="3">Temperature Offset: Specifies the offset to be added to the reported measurements to account for a bias in the measured signal. Must be a positive value, and will reduce the recorded temperature by that amount. Give the sensor adequate time to acclimate after setting this value. Value is in degrees Celsius with a resolution of 0.01 degrees and a maximum value of 655.35 C.</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><tr><td colspan="3">Ambient Air Pressure (mBar): Specify the ambient air pressure at the measurement location in mBar. Setting this value adjusts the CO2 measurement calculations to account for the air pressure’s effect on readings. Values must be in mBar, from 700 to 1200 mBar.</td></tr><tr><td>Ambient Air Pressure (mBar)</td><td>Integer
- Default Value: 1200</td><tr><td colspan="3">Altitude: Specifies the altitude at the measurement location in meters above sea level. Setting this value adjusts the CO2 measurement calculations to account for the air pressure’s effect on readings.</td></tr><tr><td>Altitude (m)</td><td>Integer
- Default Value: 100</td><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A soft reset restores factory default values.</td></tr><tr><td>Soft Reset</td><td>Button</td><td></td></tr><tr><td colspan="3">Forced Re-Calibration: The SCD-30 is placed in an environment with a known CO2 concentration, this concentration value is entered in the CO2 Concentration (ppmv) field, then the Foce Calibration button is pressed. But how do you come up with that known value? That is a caveat of this approach and Sensirion suggests three approaches: 1. Using a separate secondary calibrated CO2 sensor to provide the value. 2. Exposing the SCD-30 to a controlled environment with a known value. 3. Exposing the SCD-30 to fresh outside air and using a value of 400 ppm.</td></tr><tr><td>CO2 Concentration (ppmv)</td><td>Integer
- Default Value: 800</td><td>The CO2 concentration of the sensor environment when forcing calibration</td></tr><tr><td>Force Recalibration</td><td>Button</td><td></td></tr></tbody></table>

### Sensirion: SCD30 (scd30_i2c)

- Manufacturer: Sensirion
- Measurements: CO2/Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: scd30_i2c
- Dependencies: [scd30-i2c](https://pypi.org/project/scd30-i2c)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/carbon-dioxide-sensors/carbon-dioxide-sensors-co2/)
- Datasheet URL: [Link](https://www.sensirion.com/fileadmin/user_upload/customers/sensirion/Dokumente/9.5_CO2/Sensirion_CO2_Sensors_SCD30_Datasheet.pdf)
- Product URLs: [Link 1](https://www.sparkfun.com/products/15112), [Link 2](https://www.futureelectronics.com/p/4115766)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td colspan="3">Automatic Self Ccalibration (ASC): To work correctly, the sensor must be on and active for 7 days after enabling ASC, and exposed to fresh air for at least 1 hour per day. Consult the manufacturer’s documentation for more information.</td></tr><tr><td>Enable Automatic Self Calibration</td><td>Boolean</td><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">A soft reset restores factory default values.</td></tr><tr><td>Soft Reset</td><td>Button</td><td></td></tr></tbody></table>

### Sensirion: SHT1x/7x

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: GPIO
- Libraries: sht_sensor
- Dependencies: [sht-sensor](https://pypi.org/project/sht-sensor)
- Manufacturer URLs: [Link 1](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-accurate-measurements/), [Link 2](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/pintype-digital-humidity-sensors/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Sensirion: SHT2x (sht20)

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: sht20
- Dependencies: [sht20](https://pypi.org/project/sht20)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/humidity-temperature-sensor-sht2x-digital-i2c-accurate/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Resolution</td><td>Select(Options: [11-bit | 12-bit | 13-bit | <strong>14-bit</strong>] (Default in <strong>bold</strong>)</td><td>The resolution of the temperature measurement</td></tr></tbody></table>

### Sensirion: SHT2x (smbus2)

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: smbus2
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/humidity-temperature-sensor-sht2x-digital-i2c-accurate/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Sensirion: SHT31-D

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SHT31
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-sht31d](https://pypi.org/project/adafruit-circuitpython-sht31d)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>The temperature offset (degrees Celsius) to apply</td></tr></tbody></table>

### Sensirion: SHT3x (30, 31, 35)

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_SHT31
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-SHT31](https://pypi.org/project/Adafruit-SHT31)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Enable Heater</td><td>Boolean</td><td>Enable heater to evaporate condensation. Turn on heater x seconds every y measurements</td></tr><tr><td>Heater On Seconds (Seconds)</td><td>Decimal
- Default Value: 1.0</td><td>How long to turn the heater on</td></tr><tr><td>Heater On Period</td><td>Integer
- Default Value: 10</td><td>After how many measurements to turn the heater on. This will repeat</td></tr></tbody></table>

### Sensirion: SHT4X

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SHT4X
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit_circuitpython_sht4x](https://pypi.org/project/adafruit_circuitpython_sht4x)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Sensirion: SHTC3

- Manufacturer: Sensirion
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SHT3C
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit_circuitpython_shtc3](https://pypi.org/project/adafruit_circuitpython_shtc3)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/digital-humidity-sensors-for-various-applications/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Sensorion: SHT31 Smart Gadget

- Manufacturer: Sensorion
- Measurements: Humidity/Temperature
- Interfaces: BT
- Libraries: bluepy
- Dependencies: [pi-bluetooth](https://packages.debian.org/search?keywords=pi-bluetooth), [libglib2.0-dev](https://packages.debian.org/search?keywords=libglib2.0-dev), [bluepy](https://pypi.org/project/bluepy)
- Manufacturer URL: [Link](https://www.sensirion.com/en/environmental-sensors/humidity-sensors/development-kit/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>Text</td><td>The Hci location of the Bluetooth device.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>Text</td><td>The adapter of the Bluetooth device.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Download Stored Data</td><td>Boolean
- Default Value: True</td><td>Download the data logged to the device.</td></tr><tr><td>Set Logging Interval (Seconds)</td><td>Integer
- Default Value: 600</td><td>Set the logging interval the device will store measurements on its internal memory.</td></tr></tbody></table>

### Silicon Labs: SI1145

- Manufacturer: Silicon Labs
- Measurements: Light (UV/Visible/IR), Proximity (cm)
- Interfaces: I<sup>2</sup>C
- Libraries: si1145
- Dependencies: [SI1145](https://pypi.org/project/SI1145)
- Manufacturer URL: [Link](https://learn.adafruit.com/adafruit-si1145-breakout-board-uv-ir-visible-sensor)
- Datasheet URL: [Link](https://www.silabs.com/support/resources.p-sensors_optical-sensors_si114x)
- Product URL: [Link](https://www.adafruit.com/product/1777)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Silicon Labs: Si7021

- Manufacturer: Silicon Labs
- Measurements: Temperature/Humidity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_SI7021
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-si7021](https://pypi.org/project/adafruit-circuitpython-si7021)
- Datasheet URL: [Link](https://www.silabs.com/documents/public/data-sheets/Si7021-A20.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Sonoff: TH16/10 (Tasmota firmware) with AM2301/Si7021

- Manufacturer: Sonoff
- Measurements: Humidity/Temperature
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)
- Manufacturer URL: [Link](https://sonoff.tech/product/wifi-diy-smart-switches/th10-th16)

This Input module allows the use of any temperature/humidity sensor with the TH10/TH16. Changing the Sensor Name option changes the key that's queried from the returned dictionary of measurements. If you would like to use this module with a version of this device that uses the AM2301, change Sensor Name to AM2301.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>IP Address</td><td>Text
- Default Value: 192.168.0.100</td><td>The IP address of the device</td></tr><tr><td>Sensor Name</td><td>Text
- Default Value: SI7021</td><td>The name of the sensor connected to the device (specific key name in the returned dictionary)</td></tr></tbody></table>

### Sonoff: TH16/10 (Tasmota firmware) with AM2301

- Manufacturer: Sonoff
- Measurements: Humidity/Temperature
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)
- Manufacturer URL: [Link](https://sonoff.tech/product/wifi-diy-smart-switches/th10-th16)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>IP Address</td><td>Text
- Default Value: 192.168.0.100</td><td>The IP address of the device</td></tr></tbody></table>

### Sonoff: TH16/10 (Tasmota firmware) with DS18B20

- Manufacturer: Sonoff
- Measurements: Temperature
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)
- Manufacturer URL: [Link](https://sonoff.tech/product/wifi-diy-smart-switches/th10-th16)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>IP Address</td><td>Text
- Default Value: 192.168.0.100</td><td>The IP address of the device</td></tr></tbody></table>

### Stadia Maps: GL: Stadia Maps

- Manufacturer: Stadia Maps
- Measurements: Status
- Libraries: gis_stadia
- Manufacturer URL: [Link](https://stadiamaps.com/)

고품질 디자인을 강조하는 Stadia Maps의 지도 서버입니다. Alidade Smooth, Dark, OSMBright 등 눈이 편안한 색감과 고품질 폰트가 적용된 깔끔한 레이아웃을 제공하여 전문가용 대시보드 제작에 유리합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Stadia/Stamen API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

### Statistics Korea: KO: SGIS (Statistics Korea)

- Manufacturer: Statistics Korea
- Measurements: Status
- Libraries: gis_sgis
- Manufacturer URL: [Link](https://sgis.kostat.go.kr/)

대한민국 통계청(SGIS)에서 제공하는 통계 지리 정보 서비스입니다. 한국의 시군구별 인구, 가구, 사업체 등 다양한 통계 데이터를 공간적으로 분석하고 시각화하기 위한 최적의 국내 전용 서비스입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>SGIS Service ID (Consumer Key)</td><td>Text</td><tr><td>SGIS Security Key (Consumer Secret)</td><td>Text</td><tr><td>Data Configuration</td></td><tr><td>Statistic Subject</td><td>Select</td><tr><td>Year (YYYY)</td><td>Text</td><tr><td>Target Admin Code (adm_cd)</td><td>Text</td><tr><td>Visualization</td><td>Select</td></tbody></table>

### TE Connectivity: HTU21D (Adafruit_CircuitPython_HTU21D)

- Manufacturer: TE Connectivity
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_HTU21D
- Dependencies: [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-HTU21D](https://pypi.org/project/adafruit-circuitpython-HTU21D)
- Manufacturer URL: [Link](https://www.te.com/usa-en/product-CAT-HSC0004.html)
- Datasheet URL: [Link](https://www.te.com/commerce/DocumentDelivery/DDEController?Action=showdoc&DocId=Data+Sheet%7FHPC199_6%7FA6%7Fpdf%7FEnglish%7FENG_DS_HPC199_6_A6.pdf%7FCAT-HSC0004)
- Product URL: [Link](https://www.adafruit.com/product/1899)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Temperature Offset</td><td>Decimal</td><td>The temperature offset (degrees Celsius) to apply</td></tr></tbody></table>

### TE Connectivity: HTU21D (pigpio)

- Manufacturer: TE Connectivity
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: pigpio
- Dependencies: pigpio, [pigpio](https://pypi.org/project/pigpio)
- Manufacturer URL: [Link](https://www.te.com/usa-en/product-CAT-HSC0004.html)
- Datasheet URL: [Link](https://www.te.com/commerce/DocumentDelivery/DDEController?Action=showdoc&DocId=Data+Sheet%7FHPC199_6%7FA6%7Fpdf%7FEnglish%7FENG_DS_HPC199_6_A6.pdf%7FCAT-HSC0004)
- Product URL: [Link](https://www.adafruit.com/product/1899)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### TP-Link: Kasa WiFi Power Plug/Strip Energy Statistics

- Manufacturer: TP-Link
- Measurements: kilowatt hours
- Interfaces: IP
- Libraries: python-kasa
- Dependencies: [python-kasa](https://pypi.org/project/python-kasa), [aio_msgpack_rpc](https://pypi.org/project/aio_msgpack_rpc)
- Manufacturer URL: [Link](https://www.kasasmart.com/us/products/smart-plugs/kasa-smart-plug-slim-energy-monitoring-kp115)

This measures from several Kasa power devices (plugs/strips) capable of measuring energy consumption. These include, but are not limited to the KP115 and HS600.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Device Type</td><td>Select</td><td>The type of Kasa device</td></tr><tr><td>Host</td><td>Text
- Default Value: 0.0.0.0</td><td>Host or IP address</td></tr><tr><td>Asyncio RPC Port</td><td>Integer
- Default Value: 18063</td><td>The port to start the asyncio RPC server. Must be unique from other Kasa Outputs.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">The total kWh can be cleared with the following button or with the Clear Total kWh Function Action. This will also clear all energy stats on the device, not just the total kWh.</td></tr><tr><td>Clear Total: Kilowatt-hour</td><td>Button</td><td></td></tr></tbody></table>

### Tasmota: Tasmota Outlet Energy Monitor (HTTP)

- Manufacturer: Tasmota
- Measurements: Total Energy, Amps, Watts
- Interfaces: HTTP
- Libraries: requests
- Manufacturer URL: [Link](https://tasmota.github.io)
- Product URL: [Link](https://templates.blakadder.com/plug.html)

This input queries the energy usage information from a WiFi outlet that is running the tasmota firmware. There are many WiFi outlets that support tasmota, and many of of those have energy monitoring capabilities. When used with an MQTT Output, you can both control your tasmota outlets as well as mionitor their energy usage.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Host</td><td>Text
- Default Value: 192.168.0.50</td><td>Host or IP address</td></tr></tbody></table>

### Texas Instruments: ADS1015

- Manufacturer: Texas Instruments
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADS1x15
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ads1x15](https://pypi.org/project/adafruit-circuitpython-ads1x15)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>The number of times to measure each channel. An average of the measurements will be stored.</td></tr></tbody></table>

### Texas Instruments: ADS1115: Generic Analog pH/EC

- Manufacturer: Texas Instruments
- Measurements: Ion Concentration/Electrical Conductivity
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADS1x15
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ads1x15](https://pypi.org/project/adafruit-circuitpython-ads1x15)

This input relies on an ADS1115 analog-to-digital converter (ADC) to measure pH and/or electrical conductivity (EC) from analog sensors. You can enable or disable either measurement if you want to only connect a pH sensor or an EC sensor by selecting which measurements you want to under Measurements Enabled. Select which channel each sensor is connected to on the ADC. There are default calibration values initially set for the Input. There are also functions to allow you to easily calibrate your sensors with calibration solutions. If you use the Calibrate Slot actions, these values will be calculated and will replace the currently-set values. You can use the Clear Calibration action to delete the database values and return to using the default values. If you delete the Input or create a new Input to use your ADC/sensors with, you will need to recalibrate in order to store new calibration data.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>ADC Channel: pH</td><td>Select(Options: [<strong>Channel 0</strong> | Channel 1 | Channel 2 | Channel 3] (Default in <strong>bold</strong>)</td><td>The ADC channel the pH sensor is connected</td></tr><tr><td>ADC Channel: EC</td><td>Select(Options: [Channel 0 | <strong>Channel 1</strong> | Channel 2 | Channel 3] (Default in <strong>bold</strong>)</td><td>The ADC channel the EC sensor is connected</td></tr><tr><td colspan="3">Temperature Compensation</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td colspan="3">pH Calibration Data</td></tr><tr><td>Cal data: V1 (internal)</td><td>Decimal
- Default Value: 1.5</td><td>Calibration data: Voltage</td></tr><tr><td>Cal data: pH1 (internal)</td><td>Decimal
- Default Value: 7.0</td><td>Calibration data: pH</td></tr><tr><td>Cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>Calibration data: Temperature</td></tr><tr><td>Cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.032</td><td>Calibration data: Voltage</td></tr><tr><td>Cal data: pH2 (internal)</td><td>Decimal
- Default Value: 4.0</td><td>Calibration data: pH</td></tr><tr><td>Cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>Calibration data: Temperature</td></tr><tr><td colspan="3">EC Calibration Data</td></tr><tr><td>EC cal data: V1 (internal)</td><td>Decimal
- Default Value: 0.232</td><td>EC calibration data: Voltage</td></tr><tr><td>EC cal data: EC1 (internal)</td><td>Decimal
- Default Value: 1413.0</td><td>EC calibration data: EC</td></tr><tr><td>EC cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC calibration data: EC</td></tr><tr><td>EC cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.112</td><td>EC calibration data: Voltage</td></tr><tr><td>EC cal data: EC2 (internal)</td><td>Decimal
- Default Value: 12880.0</td><td>EC calibration data: EC</td></tr><tr><td>EC cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC calibration data: EC</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">pH Calibration Actions: Place your probe in a solution of known pH.
            Set the known pH value in the "Calibration buffer pH" field, and press "Calibrate pH, slot 1".
            Repeat with a second buffer, and press "Calibrate pH, slot 2".
            You don't need to change the values under "Custom Options".</td></tr><tr><td>Calibration buffer pH</td><td>Decimal
- Default Value: 7.0</td><td>This is the nominal pH of the calibration buffer, usually labelled on the bottle.</td></tr><tr><td>Calibrate pH, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate pH, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear pH Calibration Slots</td><td>Button</td><td></td></tr><tr><td colspan="3">EC Calibration Actions: Place your probe in a solution of known EC.
            Set the known EC value in the "Calibration standard EC" field, and press "Calibrate EC, slot 1".
            Repeat with a second standard, and press "Calibrate EC, slot 2".
            You don't need to change the values under "Custom Options".</td></tr><tr><td>Calibration standard EC</td><td>Decimal
- Default Value: 1413.0</td><td>This is the nominal EC of the calibration standard, usually labelled on the bottle.</td></tr><tr><td>Calibrate EC, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate EC, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear EC Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### Texas Instruments: ADS1115

- Manufacturer: Texas Instruments
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython_ADS1x15
- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-ads1x15](https://pypi.org/project/adafruit-circuitpython-ads1x15)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>The number of times to measure each channel. An average of the measurements will be stored.</td></tr></tbody></table>

### Texas Instruments: ADS1256: Generic Analog pH/EC

- Manufacturer: Texas Instruments
- Measurements: Ion Concentration/Electrical Conductivity
- Interfaces: UART
- Libraries: wiringpi, aot-inc/PiPyADC-py3
- Dependencies: [wiringpi](https://pypi.org/project/wiringpi), [pipyadc_py3](https://github.com/aot-inc/PiPyADC-py3)

This input relies on an ADS1256 analog-to-digital converter (ADC) to measure pH and/or electrical conductivity (EC) from analog sensors. You can enable or disable either measurement if you want to only connect a pH sensor or an EC sensor by selecting which measurements you want to under Measurements Enabled. Select which channel each sensor is connected to on the ADC. There are default calibration values initially set for the Input. There are also functions to allow you to easily calibrate your sensors with calibration solutions. If you use the Calibrate Slot actions, these values will be calculated and will replace the currently-set values. You can use the Clear Calibration action to delete the database values and return to using the default values. If you delete the Input or create a new Input to use your ADC/sensors with, you will need to recalibrate in order to store new calibration data.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>ADC Channel: pH</td><td>Select(Options: [Not Connected | <strong>Channel 0</strong> | Channel 1 | Channel 2 | Channel 3 | Channel 4 | Channel 5 | Channel 6 | Channel 7] (Default in <strong>bold</strong>)</td><td>The ADC channel the pH sensor is connected</td></tr><tr><td>ADC Channel: EC</td><td>Select(Options: [Not Connected | Channel 0 | <strong>Channel 1</strong> | Channel 2 | Channel 3 | Channel 4 | Channel 5 | Channel 6 | Channel 7] (Default in <strong>bold</strong>)</td><td>The ADC channel the EC sensor is connected</td></tr><tr><td colspan="3">Temperature Compensation</td></tr><tr><td>Temperature Compensation: Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement for temperature compensation</td></tr><tr><td>Temperature Compensation: Max Age (Seconds)</td><td>Integer
- Default Value: 120</td><td>The maximum age of the measurement to use</td></tr><tr><td colspan="3">pH Calibration Data</td></tr><tr><td>Cal data: V1 (internal)</td><td>Decimal
- Default Value: 1.5</td><td>Calibration data: Voltage</td></tr><tr><td>Cal data: pH1 (internal)</td><td>Decimal
- Default Value: 7.0</td><td>Calibration data: pH</td></tr><tr><td>Cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>Calibration data: Temperature</td></tr><tr><td>Cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.032</td><td>Calibration data: Voltage</td></tr><tr><td>Cal data: pH2 (internal)</td><td>Decimal
- Default Value: 4.0</td><td>Calibration data: pH</td></tr><tr><td>Cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>Calibration data: Temperature</td></tr><tr><td colspan="3">EC Calibration Data</td></tr><tr><td>EC cal data: V1 (internal)</td><td>Decimal
- Default Value: 0.232</td><td>EC calibration data: Voltage</td></tr><tr><td>EC cal data: EC1 (internal)</td><td>Decimal
- Default Value: 1413.0</td><td>EC calibration data: EC</td></tr><tr><td>EC cal data: T1 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC calibration data: EC</td></tr><tr><td>EC cal data: V2 (internal)</td><td>Decimal
- Default Value: 2.112</td><td>EC calibration data: Voltage</td></tr><tr><td>EC cal data: EC2 (internal)</td><td>Decimal
- Default Value: 12880.0</td><td>EC calibration data: EC</td></tr><tr><td>EC cal data: T2 (internal)</td><td>Decimal
- Default Value: 25.0</td><td>EC calibration data: EC</td></tr><tr><td>Calibration</td><td>Select</td><td>Set the calibration method to perform during Input activation</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">pH Calibration Actions: Place your probe in a solution of known pH.
            Set the known pH value in the `Calibration buffer pH` field, and press `Calibrate pH, slot 1`.
            Repeat with a second buffer, and press `Calibrate pH, slot 2`.
            You don't need to change the values under `Custom Options`.</td></tr><tr><td>Calibration buffer pH</td><td>Decimal
- Default Value: 7.0</td><td>This is the nominal pH of the calibration buffer, usually labelled on the bottle.</td></tr><tr><td>Calibrate pH, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate pH, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear pH Calibration Slots</td><td>Button</td><td></td></tr><tr><td colspan="3">EC Calibration Actions: Place your probe in a solution of known EC.
            Set the known EC value in the `Calibration standard EC` field, and press `Calibrate EC, slot 1`.
            Repeat with a second standard, and press `Calibrate EC, slot 2`.
            You don't need to change the values under `Custom Options`.</td></tr><tr><td>Calibration standard EC</td><td>Decimal
- Default Value: 1413.0</td><td>This is the nominal EC of the calibration standard, usually labelled on the bottle.</td></tr><tr><td>Calibrate EC, slot 1</td><td>Button</td><td></td></tr><tr><td>Calibrate EC, slot 2</td><td>Button</td><td></td></tr><tr><td>Clear EC Calibration Slots</td><td>Button</td><td></td></tr></tbody></table>

### Texas Instruments: ADS1256

- Manufacturer: Texas Instruments
- Measurements: Voltage (Waveshare, Analog-to-Digital Converter)
- Interfaces: UART
- Libraries: wiringpi, aot-inc/PiPyADC-py3
- Dependencies: [wiringpi](https://pypi.org/project/wiringpi), [pipyadc_py3](https://github.com/aot-inc/PiPyADC-py3)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Calibration</td><td>Select</td><td>Set the calibration method to perform during Input activation</td></tr></tbody></table>

### Texas Instruments: ADS1x15

- Manufacturer: Texas Instruments
- Measurements: Voltage (Analog-to-Digital Converter)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_ADS1x15 [DEPRECATED]
- Dependencies: [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-ADS1x15](https://pypi.org/project/Adafruit-ADS1x15)

The Adafruit_ADS1x15 is deprecated. It's advised to use The Circuit Python ADS1x15 Input.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>The number of times to measure each channel. An average of the measurements will be stored.</td></tr></tbody></table>

### Texas Instruments: HDC1000

- Manufacturer: Texas Instruments
- Measurements: Humidity/Temperature
- Interfaces: I<sup>2</sup>C
- Libraries: fcntl/io
- Manufacturer URL: [Link](https://www.ti.com/product/HDC1000)
- Datasheet URL: [Link](https://www.ti.com/lit/ds/symlink/hdc1000.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Texas Instruments: INA219x

- Manufacturer: Texas Instruments
- Measurements: Electrical Current (DC)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_CircuitPython
- Dependencies: [adafruit-circuitpython-ina219](https://pypi.org/project/adafruit-circuitpython-ina219), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus)
- Manufacturer URL: [Link](https://www.ti.com/product/INA219)
- Datasheet URL: [Link](https://www.ti.com/lit/gpn/ina219)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Measurements to Average</td><td>Integer
- Default Value: 5</td><td>The number of times to measure each channel. An average of the measurements will be stored.</td></tr><tr><td>Calibration Range</td><td>Select(Options: [<strong>32V @ 2A max (default)</strong> | 32V @ 1A max | 16V @ 400mA max | 16V @ 5A max] (Default in <strong>bold</strong>)</td><td>Set the device calibration range</td></tr><tr><td>Bus Voltage Range</td><td>Select(Options: [(0x00) - 16V | <strong>(0x01) - 32V (default)</strong>] (Default in <strong>bold</strong>)</td><td>Set the bus voltage range</td></tr><tr><td>Bus ADC Resolution</td><td>Select(Options: [(0x00) - 9 Bit / 1 Sample | (0x01) - 10 Bit / 1 Sample | (0x02) - 11 Bit / 1 Sample | <strong>(0x03) - 12 Bit / 1 Sample (default)</strong> | (0x09) - 12 Bit / 2 Samples | (0x0A) - 12 Bit / 4 Samples | (0x0B) - 12 Bit / 8 Samples | (0x0C) - 12 Bit / 16 Samples | (0x0D) - 12 Bit / 32 Samples | (0x0E) - 12 Bit / 64 Samples | (0x0F) - 12 Bit / 128 Samples] (Default in <strong>bold</strong>)</td><td>Set the Bus ADC Resolution.</td></tr><tr><td>Shunt ADC Resolution</td><td>Select(Options: [(0x00) - 9 Bit / 1 Sample | (0x01) - 10 Bit / 1 Sample | (0x02) - 11 Bit / 1 Sample | <strong>(0x03) - 12 Bit / 1 Sample (default)</strong> | (0x09) - 12 Bit / 2 Samples | (0x0A) - 12 Bit / 4 Samples | (0x0B) - 12 Bit / 8 Samples | (0x0C) - 12 Bit / 16 Samples | (0x0D) - 12 Bit / 32 Samples | (0x0E) - 12 Bit / 64 Samples | (0x0F) - 12 Bit / 128 Samples] (Default in <strong>bold</strong>)</td><td>Set the Shunt ADC Resolution.</td></tr></tbody></table>

### Texas Instruments: TMP006

- Manufacturer: Texas Instruments
- Measurements: Temperature (Object/Die)
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit_TMP
- Dependencies: [Adafruit-TMP](https://pypi.org/project/Adafruit-TMP)
- Datasheet URL: [Link](http://www.adafruit.com/datasheets/tmp006.pdf)
- Product URL: [Link](https://www.adafruit.com/product/1296)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### The Things Network: The Things Network: Data Storage (TTN v2)

- Manufacturer: The Things Network
- Measurements: Variable measurements
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

This Input receives and stores measurements from the Data Storage Integration on The Things Network.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>The duration to wait before the first operation</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Application ID</td><td>Text</td><td>The Things Network Application ID</td></tr><tr><td>App API Key</td><td>Text</td><td>The Things Network Application API Key</td></tr><tr><td>Device ID</td><td>Text</td><td>The Things Network Device ID</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>Variable Name</td><td>Text</td><td>The TTN variable name</td></tr></tbody></table>

### The Things Network: The Things Network: Data Storage (TTN v3, Payload Key)

- Manufacturer: The Things Network
- Measurements: Variable measurements
- Libraries: requests
- Dependencies: [requests](https://pypi.org/project/requests)

This Input receives and stores measurements from the Data Storage Integration on The Things Network. If you have key/value pairs as your payload, enter the key name in Variable Name and the corresponding value for that key will be stored in the measurement database.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>The duration to wait before the first operation</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Application ID</td><td>Text</td><td>The Things Network Application ID</td></tr><tr><td>App API Key</td><td>Text</td><td>The Things Network Application API Key</td></tr><tr><td>Device ID</td><td>Text</td><td>The Things Network Device ID</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>Variable Name</td><td>Text</td><td>The TTN variable name</td></tr></tbody></table>

### The Things Network: The Things Network: Data Storage (TTN v3, Payload jmespath Expression)

- Manufacturer: The Things Network
- Measurements: Variable measurements
- Libraries: requests, jmespath
- Dependencies: [requests](https://pypi.org/project/requests), [jmespath](https://pypi.org/project/jmespath)

This Input receives and stores measurements from the Data Storage Integration on The Things Network. The given Payload jmespath Expression is used as a JMESPATH expression to find the corresponding value that will be stored for that channel. Be sure you select and save the Measurement Unit for each channel. Once the unit has been saved, you can convert to other units in the Convert Measurement section. Example expressions for jmespath (https://jmespath.org) include <i>temperature</i>, <i>sensors[0].temperature</i>, and <i>bathroom.temperature</i> which refer to the temperature as a direct key within the first entry of sensors or as a subkey of bathroom, respectively. Jmespath elements and keys that contain special characters have to be enclosed in double quotes, e.g. <i>"sensor-1".temperature</i>.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer</td><td>The duration to wait before the first operation</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Application ID</td><td>Text</td><td>The Things Network Application ID</td></tr><tr><td>App API Key</td><td>Text</td><td>The Things Network Application API Key</td></tr><tr><td>Device ID</td><td>Text</td><td>The Things Network Device ID</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>Payload jmespath Expression</td><td>Text</td><td>The TTN jmespath expression to return the value to store</td></tr></tbody></table>

### Thunderforest: GL: Thunderforest

- Manufacturer: Thunderforest
- Measurements: Status
- Libraries: gis_thunderforest
- Manufacturer URL: [Link](https://www.thunderforest.com/)

OpenStreetMap 데이터를 활용하여 특정 목적에 맞춘 독창적인 테마 지도를 제공합니다. 자전거 도로(Cycle), 대중교통(Transport), 밤 지도, 거친 풍경 등 시각적으로 강렬한 고유 스타일을 경험할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Thunderforest API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

### Vworld: KO: Vworld

- Manufacturer: Vworld
- Measurements: Status
- Libraries: gis_vworld
- Manufacturer URL: [Link](https://www.vworld.kr/)

대한민국 국토교통부의 공간정보 오픈플랫폼 브이월드 서비스입니다. 국내에서 가장 정밀한 국가 고해상도 항공 사진과 수치 지도, 지적도, 실시간 교통량 등을 제공하며 국내 업무 지원에 가장 특화된 국가 국가표준 지도입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>등록 도메인</td><td>Text</td><tr><td>Map Layer / Style</td></td><tr><td>범례 보기</td><td>Boolean</td></tbody></table>

### Winsen: MH-Z14A

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART
- Libraries: serial
- Dependencies: [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/co2-sensor/mh-z14a.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/mh-z14a-co2-manual-v1_4.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Automatic Self-calibration</td><td>Boolean
- Default Value: True</td><td>Enable automatic self-calibration</td></tr><tr><td>Measurement Range</td><td>Select(Options: [<strong>400 - 2000 ppmv</strong> | 400 - 5000 ppmv | 400 - 10000 ppmv] (Default in <strong>bold</strong>)</td><td>Set the measuring range of the sensor</td></tr><tr><td colspan="3">The CO2 measurement can also be obtained using PWM via a GPIO pin. Enter the pin number below or leave blank to disable this option. This also makes it possible to obtain measurements even if the UART interface is not available (note that the sensor can't be configured / calibrated without a working UART interface).</td></tr><tr><td>GPIO Override</td><td>Text</td><td>Obtain readings using PWM on this GPIO pin instead of via UART</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate Zero Point</td><td>Button</td><td></td></tr><tr><td>Span Point (ppmv)</td><td>Integer
- Default Value: 2000</td><td>The ppmv concentration for a span point calibration</td></tr><tr><td>Calibrate Span Point</td><td>Button</td><td></td></tr></tbody></table>

### Winsen: MH-Z16

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART, I<sup>2</sup>C
- Libraries: smbus2/serial
- Dependencies: [smbus2](https://pypi.org/project/smbus2)
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/co2-sensor/mh-z16.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/MH-Z16.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Winsen: MH-Z19

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART
- Libraries: serial
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/PDF/Infrared%20Gas%20Sensor/NDIR%20CO2%20SENSOR/MH-Z19%20CO2%20Ver1.0.pdf)

This is the version of the sensor that does not include the ability to conduct automatic baseline correction (ABC). See the B version of the sensor if you wish to use ABC.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Measurement Range</td><td>Select(Options: [0 - 1000 ppmv | 0 - 2000 ppmv | 0 - 3000 ppmv | <strong>0 - 5000 ppmv</strong>] (Default in <strong>bold</strong>)</td><td>Set the measuring range of the sensor</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate Zero Point</td><td>Button</td><td></td></tr><tr><td>Span Point (ppmv)</td><td>Integer
- Default Value: 2000</td><td>The ppmv concentration for a span point calibration</td></tr><tr><td>Calibrate Span Point</td><td>Button</td><td></td></tr></tbody></table>

### Winsen: MH-Z19B

- Manufacturer: Winsen
- Measurements: CO2
- Interfaces: UART
- Libraries: serial
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/co2-sensor/mh-z19b.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/MH-Z19B.pdf)

This is the B version of the sensor that includes the ability to conduct automatic baseline correction (ABC).
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Automatic Baseline Correction</td><td>Boolean</td><td>Enable automatic baseline correction (ABC)</td></tr><tr><td>Measurement Range</td><td>Select(Options: [0 - 1000 ppmv | 0 - 2000 ppmv | 0 - 3000 ppmv | <strong>0 - 5000 ppmv</strong> | 0 - 10000 ppmv] (Default in <strong>bold</strong>)</td><td>Set the measuring range of the sensor</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Calibrate Zero Point</td><td>Button</td><td></td></tr><tr><td>Span Point (ppmv)</td><td>Integer
- Default Value: 2000</td><td>The ppmv concentration for a span point calibration</td></tr><tr><td>Calibrate Span Point</td><td>Button</td><td></td></tr></tbody></table>

### Winsen: ZH03B

- Manufacturer: Winsen
- Measurements: Particulates
- Interfaces: UART
- Libraries: serial
- Manufacturer URL: [Link](https://www.winsen-sensor.com/sensors/dust-sensor/zh3b.html)
- Datasheet URL: [Link](https://www.winsen-sensor.com/d/files/ZH03B.pdf)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>UART Device</td><td>Text</td><td>The UART device location (e.g. /dev/ttyUSB1)</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Fan Off After Measure</td><td>Boolean</td><td>Turn the fan on only during the measurement</td></tr><tr><td>Fan On Duration (Seconds)</td><td>Decimal
- Default Value: 50.0</td><td>How long to turn the fan on before acquiring measurements</td></tr><tr><td>Number of Measurements</td><td>Integer
- Default Value: 3</td><td>How many measurements to acquire. If more than 1 are acquired that are less than 1001, the average of the measurements will be stored.</td></tr></tbody></table>

### Xiaomi: Miflora

- Manufacturer: Xiaomi
- Measurements: EC/Light/Moisture/Temperature
- Interfaces: BT
- Libraries: miflora
- Dependencies: [libglib2.0-dev](https://packages.debian.org/search?keywords=libglib2.0-dev), [miflora](https://pypi.org/project/miflora), [bluepy](https://pypi.org/project/bluepy)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>Text</td><td>The Hci location of the Bluetooth device.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>Text</td><td>The adapter of the Bluetooth device.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

### Xiaomi: Mijia LYWSD03MMC (ATC and non-ATC modes)

- Manufacturer: Xiaomi
- Measurements: Battery/Humidity/Temperature
- Interfaces: BT
- Libraries: bluepy/bluez
- Dependencies: [libglib2.0](https://packages.debian.org/search?keywords=libglib2.0), [bluez](https://packages.debian.org/search?keywords=bluez), [bluetooth](https://packages.debian.org/search?keywords=bluetooth), [libbluetooth-dev](https://packages.debian.org/search?keywords=libbluetooth-dev), [bluepy](https://pypi.org/project/bluepy), [bluetooth](https://github.com/pybluez/pybluez)

More information about ATC mode can be found at https://github.com/JsBergbau/MiTemperature2
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bluetooth MAC (XX:XX:XX:XX:XX:XX)</td><td>Text</td><td>The Hci location of the Bluetooth device.</td></tr><tr><td>Bluetooth Adapter (hci[X])</td><td>Text</td><td>The adapter of the Bluetooth device.</td></tr><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr><tr><td>Enable ATC Mode</td><td>Boolean</td><td>Enable sensor ATC mode</td></tr></tbody></table>

### ams: AS7341

- Manufacturer: ams
- Measurements: Light
- Interfaces: I<sup>2</sup>C
- Libraries: Adafruit-CircuitPython-AS7341
- Dependencies: [adafruit-extended-bus](https://pypi.org/project/adafruit-extended-bus), [adafruit-circuitpython-as7341](https://pypi.org/project/adafruit-circuitpython-as7341)
- Manufacturer URL: [Link](https://ams.com/as7341)
- Datasheet URL: [Link](https://ams.com/documents/20143/36005/AS7341_DS000504_3-00.pdf/5eca1f59-46e2-6fc5-daf5-d71ad90c9b2b)
- Product URLs: [Link 1](https://www.adafruit.com/product/4698), [Link 2](https://shop.pimoroni.com/products/adafruit-as7341-10-channel-light-color-sensor-breakout-stemma-qt-qwiic), [Link 3](https://www.berrybase.de/adafruit-as7341-10-kanal-licht-und-farb-sensor-breakout)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I<sup>2</sup>C Address</td><td>Text</td><td>The address of the I<sup>2</sup>C device.</td></tr><tr><td>I<sup>2</sup>C Bus</td><td>Integer</td><td>The Bus the I<sup>2</sup>C device is connected.</td></tr><tr><td>Period (Seconds)</td><td>Decimal</td><td>The duration between measurements or actions</td></tr><tr><td>Pre Output</td><td>Select</td><td>Turn the selected output on before taking every measurement</td></tr><tr><td>Pre Out Duration (Seconds)</td><td>Decimal</td><td>If a Pre Output is selected, set the duration to turn the Pre Output on for before every measurement is acquired.</td></tr><tr><td>Pre During Measure</td><td>Boolean</td><td>Check to turn the output off after (opposed to before) the measurement is complete</td></tr></tbody></table>

