## Built-In Functions

### AoT Average (Last, Multiple)


Reads the latest data from the selected measurements, computes the arithmetic mean, and stores the result with the specified measurement/unit. Register the input measurements to aggregate by adding the "AoT Average: Input Measurement" action in the [Actions] list below. Only the average is stored; the original source values are not stored separately.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (seconds)</td><td>Text
- Default Value: 60</td><td>The period (in seconds) between measurements and calculations</td></tr><tr><td>Start Offset (seconds)</td><td>Integer
- Default Value: 10</td><td>The wait time (in seconds) before the first measurement</td></tr><tr><td>Max Age (seconds)</td><td>Integer
- Default Value: 360</td><td>Default maximum age (in seconds). If set separately in an individual input action, that value takes precedence.</td></tr><tr><td>Enable Debug Logging</td><td>Boolean</td><td>Log the computed average value each cycle. Leave off in production.</td></tr></tbody></table>

### AoT VPD


This function calculates the Vapor Pressure Deficit (VPD) based on leaf temperature and humidity. If leaf temperature is not provided, an offset is applied to the air temperature instead.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (seconds)</td><td>Text
- Default Value: 60</td><td>The period between measurements or actions</td></tr><tr><td>Start Offset (seconds)</td><td>Integer
- Default Value: 10</td><td>The wait time before the first action</td></tr><tr><td>Air Temperature</td><td>Select Measurement (Input, Function)</td><td>Air temperature measurement</td></tr><tr><td>Air Temperature: Max Age (seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Humidity</td><td>Select Measurement (Input, Function)</td><td>Humidity measurement</td></tr><tr><td>Humidity: Max Age (seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Leaf Temperature</td><td>Select Measurement (Input, Function)</td><td>Leaf temperature measurement</td></tr><tr><td>Leaf Temperature: Max Age (seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Leaf Temperature Offset (°C)</td><td>Decimal
- Default Value: -1.5</td><td>Offset (°C) to apply when leaf temperature is not provided</td></tr></tbody></table>

### Average (Last, Multiple)


This function retrieves the last measurement of each selected measurement, averages them, and stores the result with the selected measurement and unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement</td></td><td>Measurement to replace "x" in the equation</td></tr></tbody></table>

### Average (Past, Single)


This function retrieves past measurements (within Max Age) of the selected measurement, calculates the average, and stores the result with that measurement and unit. Note: InfluxDB 1.8.10 has a bug where the mean() function does not work correctly. Therefore, when using InfluxDB v1.x, the median() function is used instead. This issue does not occur in InfluxDB 2.x, where the mean() function can be used normally. To obtain an accurate average, upgrade to InfluxDB 2.x.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace "x" in the equation</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr></tbody></table>

### Bang-Bang Hysteretic (On/Off) (Raise/Lower)


A simple Bang-Bang control method that uses a single input value to control one output. Select the input, enter the **output, Setpoint, and Hysteresis**, then choose the Direction. 	•	Raise mode (e.g., heating): the output turns on when the input is at or below (setpoint - hysteresis), and turns off when the input is at or above (setpoint + hysteresis). 	•	Lower mode (e.g., cooling): the opposite of the above, turning the output on to lower the input.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Output</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will affect the measurement</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>The desired setpoint</td></tr><tr><td>Hysteresis</td><td>Decimal
- Default Value: 1</td><td>The amount above and below the setpoint that defines the control band</td></tr><tr><td>Direction</td><td>Select(Options: [<strong>Raise</strong> | Lower] (Default in <strong>bold</strong>)</td><td>Raise means the measurement will increase when the control is on (heating). Lower means the measurement will decrease when the output is on (cooling)</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 5</td><td>The duration between measurements or actions</td></tr></tbody></table>

### Bang-Bang Hysteretic (On/Off) (Raise/Lower/Both)


A simple Bang-Bang control method that uses a single input value to control one or two outputs. Select the input, configure the Raise and/or Lower outputs, then enter the **Setpoint and Hysteresis (operating range) and choose the Direction.     •	Raise mode (e.g., heating): the output turns on when the input is at or below (setpoint - hysteresis), and turns off when the input is at or above (setpoint + hysteresis).     •	Lower mode (e.g., cooling): the opposite of the above, turning the output on to lower the input.     •	Both: adjusts Raise and Lower to keep the input at the setpoint.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Output (Raise)</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will raise the measurement</td></tr><tr><td>Output (Lower)</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will lower the measurement</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>The desired setpoint</td></tr><tr><td>Hysteresis</td><td>Decimal
- Default Value: 1</td><td>The amount above and below the setpoint that defines the control band</td></tr><tr><td>Direction</td><td>Select(Options: [Raise | Lower | <strong>Both</strong>] (Default in <strong>bold</strong>)</td><td>Raise means the measurement will increase when the control is on (heating). Lower means the measurement will decrease when the output is on (cooling)</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 5</td><td>The duration between measurements or actions</td></tr></tbody></table>

### Bang-Bang Hysteretic (PWM) (Raise/Lower/Both)


A simple Bang-Bang control method that uses a single input value to control one PWM output. Select the input, enter the PWM output, Setpoint, and **Hysteresis**, then choose the Direction. 	•	Raise mode (e.g., heating): the output turns on when the input is at or below (setpoint - hysteresis), and turns off when the input is at or above (setpoint + hysteresis). 	•	Lower mode (e.g., cooling): the opposite of the above, turning the output on to lower the input. 	•	Both mode: adjusts Raise and Lower to keep the input at the setpoint. Note: this output only works with a PWM (Pulse Width Modulation) output.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Output</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will affect the measurement</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>The desired setpoint</td></tr><tr><td>Hysteresis</td><td>Decimal
- Default Value: 1</td><td>The amount above and below the setpoint that defines the control band</td></tr><tr><td>Direction</td><td>Select(Options: [Raise | Lower | <strong>Both</strong>] (Default in <strong>bold</strong>)</td><td>Raise means the measurement will increase when the control is on (heating). Lower means the measurement will decrease when the output is on (cooling)</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 5</td><td>The duration between measurements or actions</td></tr><tr><td>Duty Cycle (increase)</td><td>Decimal
- Default Value: 90</td><td>The duty cycle to increase the measurement</td></tr><tr><td>Duty Cycle (maintain)</td><td>Decimal
- Default Value: 55</td><td>The duty cycle to maintain the measurement</td></tr><tr><td>Duty Cycle (decrease)</td><td>Decimal
- Default Value: 20</td><td>The duty cycle to decrease the measurement</td></tr><tr><td>Duty Cycle (shutdown)</td><td>Decimal</td><td>The duty cycle to set when the function shuts down</td></tr></tbody></table>

### Camera: libcamera: Image/Video

- Dependencies: [libcamera-apps](https://packages.debian.org/search?keywords=libcamera-apps), [ffmpeg](https://packages.debian.org/search?keywords=ffmpeg)

Note: This function is currently experimental and should be used at your own risk until this notice is removed. Captures images and video from the camera using libcamera-still and libcamera-vid. This function must be enabled to take still images, capture time-lapses, and use the Camera Widget.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Status Period (seconds)</td><td>Integer
- Default Value: 60</td><td>The duration (seconds) to update the Function status on the UI</td></tr><tr><td colspan="3">Image options.</td></tr><tr><td>Custom Image Path</td><td>Text</td><td>Set a non-default path for still images to be saved</td></tr><tr><td>Custom Timelapse Path</td><td>Text</td><td>Set a non-default path for timelapse images to be saved</td></tr><tr><td>Image Extension</td><td>Select(Options: [<strong>JPG</strong> | PNG | BMP | RGB | YUV420] (Default in <strong>bold</strong>)</td><td>The file type/format to save images</td></tr><tr><td>Image: Resolution: Width</td><td>Integer
- Default Value: 720</td><td>The width of still images</td></tr><tr><td>Image: Resolution: Height</td><td>Integer
- Default Value: 480</td><td>The height of still images</td></tr><tr><td>Brightness</td><td>Decimal</td><td>The brightness of still images (-1 to 1)</td></tr><tr><td>Image: Contrast</td><td>Decimal
- Default Value: 1.0</td><td>The contrast of still images. Larger values produce images with more contrast.</td></tr><tr><td>Saturation</td><td>Decimal
- Default Value: 1.0</td><td>The saturation of still images. Larger values produce more saturated colours; 0.0 produces a greyscale image.</td></tr><tr><td>Sharpness</td><td>Decimal</td><td>The sharpness of still images. Larger values produce more saturated colours; 0.0 produces a greyscale image.</td></tr><tr><td>Shutter Speed (Microseconds)</td><td>Integer</td><td>The shutter speed, in microseconds. 0 disables and returns to auto exposure.</td></tr><tr><td>Gain</td><td>Decimal
- Default Value: 1.0</td><td>The gain of still images.</td></tr><tr><td>White Balance: Auto</td><td>Select(Options: [<strong>Auto</strong> | Incandescent | Tungsten | Fluorescent | Indoor | Daylight | Cloudy | Custom] (Default in <strong>bold</strong>)</td><td>The white balance of images</td></tr><tr><td>White Balance: Red Gain</td><td>Decimal</td><td>The red gain of white balance for still images (disabled Auto White Balance if red and blue are not set to 0)</td></tr><tr><td>White Balance: Blue Gain</td><td>Decimal</td><td>The red gain of white balance for still images (disabled Auto White Balance if red and blue are not set to 0)</td></tr><tr><td>Flip Horizontally</td><td>Boolean</td><td>Flip the image horizontally.</td></tr><tr><td>Flip Vertically</td><td>Boolean</td><td>Flip the image vertically.</td></tr><tr><td>Rotate (Degrees)</td><td>Integer</td><td>Rotate the image.</td></tr><tr><td>Custom libcamera-still Options</td><td>Text</td><td>Pass custom options to the libcamera-still command.</td></tr><tr><td colspan="3">Video options.</td></tr><tr><td>Custom Video Path</td><td>Text</td><td>Set a non-default path for videos to be saved</td></tr><tr><td>Video Extension</td><td>Select(Options: [<strong>H264 -> MP4 (with ffmpeg)</strong> | H264 | MJPEG | YUV420] (Default in <strong>bold</strong>)</td><td>The file type/format to save videos</td></tr><tr><td>Video: Resolution: Width</td><td>Integer
- Default Value: 720</td><td>The width of videos</td></tr><tr><td>Video: Resolution: Height</td><td>Integer
- Default Value: 480</td><td>The height of videos</td></tr><tr><td>Custom libcamera-vid Options</td><td>Text</td><td>Pass custom options to the libcamera-vid command.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Capture Image</td><td>Button</td><td></td></tr><tr><td colspan="3">To capture a video, enter the duration and press Capture Video.</td></tr><tr><td>Video Duration (Seconds)</td><td>Integer
- Default Value: 5</td><td>How long to record the video</td></tr><tr><td>Capture Video</td><td>Button</td><td></td></tr><tr><td colspan="3">To start a timelapse, enter the duration and period and press Start Timelapse.</td></tr><tr><td>Timelapse Duration (Seconds)</td><td>Integer
- Default Value: 2592000</td><td>How long the timelapse will run</td></tr><tr><td>Timelapse Period (Seconds)</td><td>Integer
- Default Value: 600</td><td>How often to take a timelapse photo</td></tr><tr><td>Start Timelapse</td><td>Button</td><td></td></tr><tr><td colspan="3">To stop an active timelapse, press Stop Timelapse.</td></tr><tr><td>Stop Timelapse</td><td>Button</td><td></td></tr><tr><td colspan="3">To pause or resume an active timelapse, press Pause Timelapse or Resume Timelapse.</td></tr><tr><td>Pause Timelapse</td><td>Button</td><td></td></tr><tr><td>Resume Timelapse</td><td>Button</td><td></td></tr></tbody></table>

### Data Verification


This function acquires two measurements, calculates their difference, and stores Measurement A if the difference is not greater than the configured threshold. This lets you verify one sensor's measurement against another sensor's measurement. Since the measurement is only stored when the two sensors agree, you can use the stored measurement in Conditional Functions and similar to notify the user when no measurement is present, indicating a possible sensor problem.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Measurement A</td><td>Select Measurement (Input, Function)</td><td>Measurement A</td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement B</td><td>Select Measurement (Input, Function)</td><td>Measurement B</td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Maximum Difference</td><td>Decimal
- Default Value: 10.0</td><td>The maximum allowed difference between the measurements</td></tr><tr><td>Average Measurements</td><td>Boolean</td><td>Store the average of the measurements in the database</td></tr></tbody></table>

### Difference


This function retrieves two measurements, calculates their difference, and stores the result with the selected measurement and unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Measurement: A</td><td>Select Measurement (Input, Function)</td><td></td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement: B</td><td>Select Measurement (Input, Function)</td><td></td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Reverse Order</td><td>Boolean</td><td>Reverse the order in the calculation</td></tr><tr><td>Absolute Difference</td><td>Boolean</td><td>Return the absolute value of the difference</td></tr></tbody></table>

### Display: Generic LCD 16x2 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

This function provides output to a 16x2 LCD display over I2C. This display can show 2 lines at a time, so each change to the Number of Line Sets adds 2 channels. The LCD refreshes every configured Period, displaying the next set of lines. So the first 2 displayed lines are channels 0 and 1, then 2 and 3, then 4 and 5, and so on. After all channels have been displayed, it cycles back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x20</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr><tr><td>Backlight Flashing On</td><td>Button</td><td></td></tr><tr><td>Backlight Flashing Off</td><td>Button</td><td></td></tr></tbody></table>

### Display: Generic LCD 20x4 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

This function provides output to a 20x4 LCD display over I2C. This display can show 4 lines at a time, so each change to the Number of Line Sets adds 4 channels. The LCD refreshes every configured Period, displaying the next set of lines. So the first 4 displayed lines are channels 0, 1, 2, 3, then 4, 5, 6, 7, then 8, 9, 10, 11, and so on. After all channels have been displayed, it cycles back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x20</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr></tbody></table>

### Display: Grove LCD 16x2 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

This function provides output to a Grove 16x2 LCD display over I2C. This display can show 2 lines at a time, so each change to the Number of Line Sets adds 2 channels. The LCD refreshes every configured Period, displaying the next set of lines. So the first 2 displayed lines are channels 0 and 1, then channels 2 and 3, then channels 4 and 5, and so on. After all channels have been displayed, it cycles back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3e</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Backlight I2C Address</td><td>Text
- Default Value: 0x62</td><td>I2C address to control the backlight</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Backlight Red (0 - 255)</td><td>Integer
- Default Value: 255</td><td>Set the red color value of the backlight on startup.</td></tr><tr><td>Backlight Green (0 - 255)</td><td>Integer
- Default Value: 255</td><td>Set the green color value of the backlight on startup.</td></tr><tr><td>Backlight Blue (0 - 255)</td><td>Integer
- Default Value: 255</td><td>Set the blue color value of the backlight on startup.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr><tr><td>Color (RGB)</td><td>Text
- Default Value: 255,0,0</td><td>Color as R,G,B values (e.g. "255,0,0" without quotes)</td></tr><tr><td>Set Backlight Color</td><td>Button</td><td></td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [2 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This function provides output to a 128x32 SSD1306 OLED display over I2C. This display function can show 2 lines at a time, so each change to the Number of Line Sets adds 2 channels. The LCD refreshes every configured Period, displaying the next set of lines. So the first displayed line set is channels 0 - 1, then 2 - 3, then 4 - 5, and so on. After all channels have been displayed, it cycles back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [2 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x32 SSD1306 OLED display via SPI. This display Function will show 2 lines at a time, so channels are added in sets of 2 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 1, then 2 - 3, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [4 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This function provides output to a 128x32 SSD1306 OLED display over I2C. This display function can show 4 lines at a time, so each change to the Number of Line Sets adds 4 channels. The LCD refreshes every configured Period, displaying the next set of lines. So the first displayed line set is channels 0 - 3, then 4 - 7, then 8 - 11, and so on. After all channels have been displayed, it cycles back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [4 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x32 SSD1306 OLED display via SPI. This display Function will show 4 lines at a time, so channels are added in sets of 4 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 3, then 4 - 7, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [4 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via I2C. This display Function will show 4 lines at a time, so channels are added in sets of 4 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 3, then 4 - 7, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [4 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via SPI. This display Function will show 4 lines at a time, so channels are added in sets of 4 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 3, then 4 - 7, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [8 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via I2C. This display Function will show 8 lines at a time, so channels are added in sets of 8 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 7, then 8 - 15, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [8 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via SPI. This display Function will show 8 lines at a time, so channels are added in sets of 8 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 7, then 8 - 15, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1309 OLED 128x64 [8 Lines] (I2C)

- Dependencies: [pyusb](https://pypi.org/project/pyusb), [luma.oled](https://pypi.org/project/luma.oled), [Pillow](https://pypi.org/project/Pillow), [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [libfreetype6-dev](https://packages.debian.org/search?keywords=libfreetype6-dev), [liblcms2-dev](https://packages.debian.org/search?keywords=liblcms2-dev), [libopenjp2-7](https://packages.debian.org/search?keywords=libopenjp2-7), [libtiff5](https://packages.debian.org/search?keywords=libtiff5)

This Function outputs to a 128x64 SSD1309 OLED display via I2C. This display Function will show 8 lines at a time, so channels are added in sets of 8 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 7, then 8 - 15, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>The duration between measurements or actions</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>Text</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Equation (Multi-Measure)


This function retrieves two measurements, applies them to a user-defined equation, and stores the result with the selected measurement and unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Measurement: A</td><td>Select Measurement (Input, Output, Function)</td><td>Measurement to replace a</td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement: B</td><td>Select Measurement (Input, Output, Function)</td><td>Measurement to replace b</td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Equation</td><td>Text
- Default Value: a*(2+b)</td><td>Equation using measurements a and b</td></tr></tbody></table>

### Equation (Single-Measure)


This function retrieves a measurement, applies it to a user-defined equation, and stores the result with the selected measurement and unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Output, Function)</td><td>Measurement to replace "x" in the equation</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Equation</td><td>Text
- Default Value: x*5+2</td><td>Equation using the measurement</td></tr></tbody></table>

### Example: Generic

- Dependencies: [build-essential](https://packages.debian.org/search?keywords=build-essential)

This function module is an example demonstrating the various UI option types. It is intended only for learning how to develop new custom function modules and has no other practical use. This message is displayed above the function options. This function retrieves the last selected measurement, turns the selected output on for 15 seconds, and then deactivates it. Analyze the code to develop your own function module and configure it so it can be imported from the Function Import page.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td colspan="3">The following fields are for text, integers, and decimal inputs. This message will automatically create a new line for the options that come after it. Alternatively, a new line can be created instead without a message, which are what separates each of the following three inputs.</td></tr><tr><td>Text Input</td><td>Text
- Default Value: Text_1</td><td>Type in text</td></tr><tr><td>Integer Input</td><td>Integer
- Default Value: 100</td><td>Type in an Integer</td></tr><tr><td>Devimal Input</td><td>Decimal
- Default Value: 50.2</td><td>Type in a decimal value</td></tr><tr><td colspan="3">A boolean value can be made using a checkbox.</td></tr><tr><td>Boolean Value</td><td>Boolean
- Default Value: True</td><td>Set to either True (checked) or False (Unchecked)</td></tr><tr><td colspan="3">A dropdown selection can be made of any user-defined options, with any of the options selected by default when the Function is added by the user.</td></tr><tr><td>Select Option</td><td>Select(Options: [First Option Selected | <strong>Second Option Selected</strong> | Third Option Selected] (Default in <strong>bold</strong>)</td><td>Select an option from the dropdown</td></tr><tr><td colspan="3">A specific measurement from an Input, Function, or PID Controller can be selected. The following dropdown will be populated if at least one Input, Function, or PID Controller has been created (as long as the Function has measurements, e.g. Statistics Function).</td></tr><tr><td>Controller Measurement</td><td>Select Measurement (Input, Function, PID)</td><td>Select a controller Measurement</td></tr><tr><td colspan="3">An output channel measurement can be selected that will return the Output ID, Channel ID, and Measurement ID. This is useful if you need more than just the Output and Channel IDs and require the user to select the specific Measurement of a channel.</td></tr><tr><td>Output Channel Measurement</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output channel and measurement </td></tr><tr><td colspan="3">An output can be selected that will return the Output ID if only the output ID is needed.</td></tr><tr><td>Output Device</td><td>Select Device</td><td>Select an Output device</td></tr><tr><td colspan="3">An Input, Output, Function, PID, or Trigger can be selected that will return the ID if only the controller ID is needed (e.g. for activating/deactivating a controller)</td></tr><tr><td>Controller Device</td><td>Select Device</td><td>Select an Input/Output/Function/PID/Trigger controller</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Button One will pass the Button One Value to the button_one() function of this module. This allows functions to be executed with user-specified inputs. These can be text, integers, decimals, or boolean values.</td></tr><tr><td>Button One Value</td><td>Integer
- Default Value: 650</td><td>Value for button one.</td></tr><tr><td>Button One</td><td>Button</td><td></td></tr><tr><td colspan="3">Here is another action with another user input that will be passed to the function. Note that Button One Value will also be passed to this second function, so be sure to use unique ids for each input.</td></tr><tr><td>Button Two Value</td><td>Integer
- Default Value: 1500</td><td>Value for button two.</td></tr><tr><td>Button Two</td><td>Button</td><td></td></tr></tbody></table>

### External Environment Context Collector


Collects external temperature, humidity, wind speed, rainfall, solar radiation, dew point, and CO2 from outside the facility. The integrated environment control Function uses this collector as its single source of truth. Select the external sensor for each item. Leave items blank to apply the fallback default value.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Update Period: (Seconds)</td><td>Text
- Default Value: 60</td><td>Collection period (seconds). Set it equal to or shorter than the integrated control Function's cycle.</td></tr><tr><td>External Temperature Sensor</td><td>Select Measurement (Input, Function)</td><td>Select the external air temperature measurement.</td></tr><tr><td>External Humidity Sensor</td><td>Select Measurement (Input, Function)</td><td>Select the external relative humidity measurement.</td></tr><tr><td>Wind Speed Sensor</td><td>Select Measurement (Input, Function)</td><td>Select the wind speed (m/s) measurement.</td></tr><tr><td>Rain Sensor</td><td>Select Measurement (Input, Function)</td><td>Select the rainfall amount or rain detection measurement.</td></tr><tr><td>Solar Radiation Sensor</td><td>Select Measurement (Input, Function)</td><td>Select the solar radiation (W/m²) or illuminance measurement.</td></tr><tr><td>Dew Point Sensor</td><td>Select Measurement (Input, Function)</td><td>Select the dew point (°C) measurement. If absent, it is calculated from temperature and humidity.</td></tr><tr><td>External CO₂ Sensor</td><td>Select Measurement (Input, Function)</td><td>Select the external CO₂ (ppm) measurement. If absent, the default is 400 ppm.</td></tr><tr><td>Sensor Maximum Allowed Age (seconds)</td><td>Text
- Default Value: 120</td><td>Measurements older than this are replaced with the fallback default value.</td></tr><tr><td>Fallback External Temperature (°C)</td><td>Decimal
- Default Value: 20.0</td><td>Default value to use when the sensor is absent or expired.</td></tr><tr><td>Fallback External Humidity (%)</td><td>Decimal
- Default Value: 60.0</td><td></td></tr><tr><td>Fallback Wind Speed (m/s)</td><td>Decimal</td><td></td></tr></tbody></table>

### Humidity (Wet/Dry-Bulb)


This function calculates humidity based on wet-bulb and dry-bulb temperature measurements.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Dry Bulb Temperature</td><td>Select Measurement (Input, Function)</td><td>Dry Bulb temperature measurement</td></tr><tr><td>Dry Bulb: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Wet Bulb Temperature</td><td>Select Measurement (Input, Function)</td><td>Wet Bulb temperature measurement</td></tr><tr><td>Wet Bulb: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Pressure</td><td>Select Measurement (Input, Function)</td><td>Pressure measurement</td></tr><tr><td>Pressure: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr></tbody></table>

### LoRaWAN Class Scheduler (per-site)


Single per-site authority for LoRaWAN class. Decides Class C (active/wireless control) vs Class A (rest/low-power) from environmental data, toggles the shared ChirpStack device profile(s) and broadcasts the firmware HB mode to each device, stores per-device RSSI/SNR/battery, and offers a manual override. Replaces the per-device LoRaWAN Mode Manager.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Evaluation period (Seconds)</td><td>Text
- Default Value: 600</td><tr><td>Input max age (s)</td><td>Text
- Default Value: 4000</td><tr><td>ChirpStack</td></td><tr><td>REST Port</td><td>Integer
- Default Value: 8090</td><td>Server/token from Settings -> ChirpStack; devices assigned there ("Managed by").</td></tr><tr><td>Control Mode</td></td><tr><td>Control mode</td><td>Select(Options: [<strong>AUTO - environment scoring</strong> | MANUAL - fixed daily C window] (Default in <strong>bold</strong>)</td><tr><td>Manual C start (HH:MM)</td><td>Text
- Default Value: 05:00</td><tr><td>Manual C expire (HH:MM)</td><td>Text
- Default Value: 17:00</td><tr><td>Environmental Inputs (AUTO fallback)</td></td><tr><td>Solar radiation (W/m2)</td><td>Select Measurement (Input, Function)</td><td>Light drives photosynthesis. Pick the radiation measurement (leave empty to skip).</td></tr><tr><td>Soil moisture (%)</td><td>Select Measurement (Input, Function)</td><td>Wet soil = irrigation not needed.</td></tr><tr><td>Rainfall now (mm/h)</td><td>Select Measurement (Input, Function)</td><td>Currently raining.</td></tr><tr><td>Rainfall accumulated (mm)</td><td>Select Measurement (Input, Function)</td><td>Recent accumulated rain -> soil saturated.</td></tr><tr><td>Decision</td></td><tr><td>Score >= -> ACTIVE</td><td>Decimal
- Default Value: 0.55</td><tr><td>Score < -> REST</td><td>Decimal
- Default Value: 0.4</td><tr><td>Minimum dwell (min)</td><td>Integer
- Default Value: 15</td><tr><td>Class / HB Periods</td></td><tr><td>ACTIVE Class C HB (min)</td><td>Integer
- Default Value: 10</td><tr><td>REST Class A HB (min)</td><td>Integer
- Default Value: 30</td><tr><td>Winter Class A HB (min)</td><td>Integer
- Default Value: 60</td><tr><td>Winter (forced REST)</td></td><tr><td>Winter start (MM-DD)</td><td>Text
- Default Value: 12-01</td><tr><td>Winter end (MM-DD)</td><td>Text
- Default Value: 02-28</td><tr><td>Battery Management</td></td><tr><td>Battery Type</td><td>Select(Options: [<strong>Not configured (no battery gate)</strong> | Lead-acid  (low < 11.7 V / critical < 11.4 V) | LiFePO4    (low < 12.8 V / critical < 12.0 V)] (Default in <strong>bold</strong>)</td><td>Reads battery_V from ChirpStack metrics (requires INA219 wired). Low: forces REST unless manual override is active. Critical: forces REST unconditionally; valve-open interlock still applies.</td></tr><tr><td>Low-battery HB (min)</td><td>Integer
- Default Value: 60</td><td>Heartbeat period (minutes) applied when battery is low or critical. Should be >= REST HB to maximise sleep time.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3"><b>Manual override</b></td></tr><tr><td>Force-Active minutes (0 = until expire time)</td><td>Integer</td><tr><td>Force Active (Class C) now</td><td>Button</td><td></td></tr><tr><td>Clear override</td><td>Button</td><td></td></tr></tbody></table>

### LoRaWAN Mode/Period Manager (RAK3172E)


Determines the Class/heartbeat period based on battery, time of day, valve activity, and link quality. Queues downlinks directly via ChirpStack gRPC (DeviceService.Enqueue).
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Device Role</td><td>Select(Options: [<strong>Controller (valve/actuator) — Class C preferred</strong> | Sensor — Class A, low power (no gateway GPS required) | Hybrid — manual configuration] (Default in <strong>bold</strong>)</td><td>controller: Class C during operating hours, B at night. sensor: Class A always (no gateway GPS required), longer HB at night. hybrid: follow the settings below exactly.</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>Evaluation and apply period (seconds)</td></tr><tr><td colspan="3"><b>Server Connection</b></td></tr><tr><td>ChirpStack gRPC Server</td><td>Text
- Default Value: 127.0.0.1:8080</td><td>host:port format (e.g. 127.0.0.1:8080) or http(s)://host:port</td></tr><tr><td>API Key</td><td>Text</td><td>Enter the JWT token value (without "Bearer")</td></tr><tr><td>DevEUI</td><td>Text</td><td>16-digit hexadecimal DevEUI (separators allowed)</td></tr><tr><td colspan="3"><b>Measurement Inputs</b></td></tr><tr><td>ChirpStack REST Port</td><td>Integer
- Default Value: 8090</td><td>ChirpStack REST API port (default 8090)</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 4000</td><td>How far back (seconds) to look in ChirpStack metrics history</td></tr><tr><td>Retry Interval (min)</td><td>Decimal</td><td>Interval at which to re-apply the same mode when there is no ACK (0 disables retry)</td></tr><tr><td>LoRa Class Policy</td><td>Select(Options: [<strong>Auto</strong> | CLASS-A | CLASS-B | CLASS-C] (Default in <strong>bold</strong>)</td><td>Only in Auto mode is the Class switched according to the mode; selecting a specific class keeps that class.</td></tr><tr><td>Switch Mode Only When Inputs Are Valid</td><td>Boolean</td><td>Apply the mode only when the input conditions/measurements are valid</td></tr><tr><td colspan="3"><b>Operating Hours</b><br/><small>Sets the hours during which performance mode operates. Enter 0–24, or if the start and end times are equal it means 24 hours.</small></td></tr><tr><td>Operating Hours Basis</td><td>Select(Options: [<strong>Fixed hours — the start and end hours below</strong> | Sunrise to sunset — follows the season at this location] (Default in <strong>bold</strong>)</td><td>Fixed hours keep the same clock times all year. Sunrise to sunset follows the daylight at this device's location, so performance mode tracks the season without being re-entered each month. The location is inherited from the map; if it cannot be resolved, the fixed hours below are used instead.</td></tr><tr><td>Sunrise Offset (min)</td><td>Integer</td><td>Shifts the start of the operating window relative to sunrise. Negative starts earlier (-30 begins 30 minutes before sunrise). Only used when the basis is sunrise to sunset.</td></tr><tr><td>Sunset Offset (min)</td><td>Integer</td><td>Shifts the end of the operating window relative to sunset. Positive ends later (30 keeps performance mode for 30 minutes after sunset). Only used when the basis is sunrise to sunset.</td></tr><tr><td>Performance Mode Start (hour)</td><td>Integer
- Default Value: 4</td><td>Performance mode start time (0–23)</td></tr><tr><td>Performance Mode End (hour)</td><td>Integer
- Default Value: 18</td><td>Performance mode end time (0–23)</td></tr><tr><td>Performance Mode Lead (min)</td><td>Integer
- Default Value: 10</td><td>Specifies, in minutes, how far in advance of the daytime start to switch to performance (Class C) mode.</td></tr><tr><td colspan="3"><b>HB Period per Mode</b><br/><small>Sets the heartbeat period for each mode.</small></td></tr><tr><td>Performance Mode Class</td><td>Select(Options: [Class A | Class B | <strong>Class C</strong>] (Default in <strong>bold</strong>)</td><td>LoRa class to apply to the firmware under the performance (C) policy</td></tr><tr><td>Power-saving Mode Class</td><td>Select(Options: [Class A | <strong>Class B</strong> | Class C] (Default in <strong>bold</strong>)</td><td>LoRa class to apply to the firmware under the power-saving (B) policy</td></tr><tr><td>Ultra-saving Mode Class</td><td>Select(Options: [Class A | <strong>Class B</strong> | Class C] (Default in <strong>bold</strong>)</td><td>LoRa class to apply to the firmware under the ultra-saving (A) policy</td></tr><tr><td>Performance Heartbeat (min)</td><td>Integer
- Default Value: 30</td><td>Performance (C) mode heartbeat period (min)</td></tr><tr><td>Power-saving Heartbeat (min)</td><td>Integer
- Default Value: 30</td><td>Power-saving (B) mode heartbeat period (min)</td></tr><tr><td>Ultra-saving Heartbeat (min)</td><td>Integer
- Default Value: 60</td><td>Ultra-saving (A) mode heartbeat period (min)</td></tr><tr><td colspan="3"><b>Threshold Options</b><br/><small>Sets the mode-switching thresholds.</small></td></tr><tr><td>Battery Management</td><td>Boolean</td><td>Automatically switches the mode according to the battery voltage. (Active only when the LoRa class policy is Auto.)</td></tr><tr><td>Performance Mode Threshold (V)</td><td>Decimal
- Default Value: 12.0</td><td>Voltage threshold at which stable operation is possible</td></tr><tr><td>Power-saving Threshold (V)</td><td>Decimal
- Default Value: 11.7</td><td>Voltage threshold for switching to power-saving mode</td></tr><tr><td>Ultra-saving Threshold (V)</td><td>Decimal
- Default Value: 11.4</td><td>Voltage threshold for switching to ultra-saving mode</td></tr><tr><td>Halt Mode Application When Battery Is Missing</td><td>Boolean
- Default Value: True</td><td>Holds off on mode/period changes when the battery measurement is missing or too old.</td></tr><tr><td>Link RSSI Minimum (dBm)</td><td>Integer
- Default Value: -110</td><td>At or above this value, the link is considered good</td></tr><tr><td>Link SNR Minimum (dB)</td><td>Integer
- Default Value: -10</td><td>At or above this value, the link is considered good</td></tr><tr><td>Valve Active Threshold (mA)</td><td>Decimal
- Default Value: 50.0</td><td>If battery current exceeds this value, the valve is considered active and the device stays in performance mode. 0 disables this check.</td></tr><tr><td>Enable Debug Logging</td><td>Boolean</td><td>Log "no apply" notices when mode/period is unchanged. Leave off in production.</td></tr></tbody></table>

### Neokey 4x1 Neopixel Keyboard (Execute Actions)

- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-neokey](https://pypi.org/project/adafruit-circuitpython-neokey)

This function executes specific actions when a key is pressed. After adding actions at the bottom of this module, enter one or more short action IDs for each key, separated by commas. The action ID can be found next to each action (for example, for "[Action 0559689e] Controller: Activate" the action ID is 0559689e). When entering action IDs, separate multiple IDs with commas (for example, "asdf1234" or "asdf1234,qwer5678,zxcv0987"). Actions are executed in the order of the entered text string. Enter the action IDs to execute when a key is pressed. If you enable the toggle action, the actions listed in the toggled action IDs are executed on alternate key presses. You can set the LED color before a key is pressed, after it is pressed, and while the last action is executing. The color is an RGB string with values in the range 0 to 255. For example, enter "255, 0, 0" for red and "0, 0, 255" for blue.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I2C Address</td><td>Text
- Default Value: 0x30</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>LED Brightness (0.0-1.0)</td><td>Decimal
- Default Value: 0.2</td><td>The brightness of the LEDs</td></tr><tr><td>LED Flash Period (Seconds)</td><td>Text
- Default Value: 1.0</td><td>Set the period if the LED begins flashing</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>Text</td><td>A name to distinguish this from others</td></tr><tr><td>LED Delay (Seconds)</td><td>Text
- Default Value: 1.5</td><td>How long to leave the LED on after the last action executes.</td></tr><tr><td>Action ID(s)</td><td>Text</td><td>Set which action(s) execute when the key is pressed. Enter one or more Action IDs, separated by commas</td></tr><tr><td>Enable Toggling Actions</td><td>Boolean</td><td>Alternate between executing two sets of Actions</td></tr><tr><td>Toggled Action ID(s)</td><td>Text</td><td>Set which action(s) execute when the key is pressed on even presses. Enter one or more Action IDs, separated by commas</td></tr><tr><td>Resting LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 0</td><td>The RGB color while no actions are running (e.g 10, 0, 0)</td></tr><tr><td>Actions Running LED Color: (RGB)</td><td>Text
- Default Value: 0, 255, 0</td><td>The RGB color while all but the last action is running (e.g 10, 0, 0)</td></tr><tr><td>Last Action LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 255</td><td>The RGB color while the last action is running (e.g 10, 0, 0)</td></tr><tr><td>Shutdown LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 0</td><td>The RGB color when the Function is disabled (e.g 10, 0, 0)</td></tr></tbody></table>

### PID Autotune


This function attempts to automatically tune a PID controller. That is, it enables the output and measures the response from the sensor multiple times to calculate the P, I, and D gain values. Updates on the operating status are written to the daemon log, and when autotuning completes successfully a summary is also stored in the daemon log. Only raising the current measurement is supported; lowering the measurement may require some modification of the controller code. To monitor whether the output is normally raising the measurement above the setpoint, it is recommended to graph the measurement and output on the dashboard. The autotune feature is experimental and not fully developed. It is likely it will not generate proper PID gains, so it is recommended not to rely on this function for accurate PID controller tuning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>Output</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to modulate that will affect the measurement</td></tr><tr><td>Period</td><td>Text
- Default Value: 30</td><td>The period between powering the output</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>A value sufficiently far from the current measured value that the output is capable of pushing the measurement toward</td></tr><tr><td>Noise Band</td><td>Decimal
- Default Value: 0.5</td><td>The amount above the setpoint the measurement must reach</td></tr><tr><td>Outstep</td><td>Decimal
- Default Value: 10</td><td>How many seconds the output will turn on every Period</td></tr><tr><td colspan="3">Currently, only autotuning to raise a condition (measurement) is supported.</td></tr><tr><td>Direction</td><td>Select(Options: [<strong>Raise</strong> | Lower (Cooling/Humidifying)] (Default in <strong>bold</strong>)</td><td>The direction the Output will push the Measurement</td></tr></tbody></table>

### Redundant Sensor Data


This function stores the first available measurement. It is useful when you want to configure multiple sensors for backup. If you order the sensors by priority, this function checks the first measurement for existence, and if absent, checks the next measurement, repeating the process. When a measurement is found, it is stored in the database with the custom measurement and unit. The output of this function can be used as an input throughout AoT. If you need to check three or more measurements, you can chain multiple redundancy functions by setting the output of the first function as the input of the second.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Measurement A</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace a</td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement B</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace b</td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement C</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace C</td></tr><tr><td>Measurement C: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr></tbody></table>

### Remote Backup (rsync)

- Dependencies: [rsync](https://packages.debian.org/search?keywords=rsync)

This function backs up the current system data to a remote system using rsync. The remote system must be running an SSH server and have rsync installed. This system must also have rsync installed and be able to access the remote system without a password via an SSH key file.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 1296000</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 300</td><td>The duration to wait before the first operation</td></tr><tr><td>Local User</td><td>Text
- Default Value: pi</td><td>The user on this system that will run rsync</td></tr><tr><td>Remote User</td><td>Text
- Default Value: pi</td><td>The user to log in to the remote host</td></tr><tr><td>Remote Host</td><td>Text
- Default Value: 192.168.0.50</td><td>The IP or host address to send the backup to</td></tr><tr><td>Remote Backup Path</td><td>Text
- Default Value: /home/pi/backup_aot</td><td>The path to backup to on the remote host</td></tr><tr><td>Rsync Timeout (Seconds)</td><td>Integer
- Default Value: 3600</td><td>How long to allow rsync to complete</td></tr><tr><td>Local Backup Path</td><td>Text</td><td>A local path to backup (leave blank to disable)</td></tr><tr><td>Backup Settings Export File</td><td>Boolean
- Default Value: True</td><td>Create and backup exported settings file</td></tr><tr><td>Remove Local Settings Backups</td><td>Boolean</td><td>Remove local settings backups after successful transfer to remote host</td></tr><tr><td>Backup Measurements</td><td>Boolean
- Default Value: True</td><td>Backup all influxdb measurements</td></tr><tr><td>Remove Local Measurements Backups</td><td>Boolean</td><td>Remove local measurements backups after successful transfer to remote host</td></tr><tr><td>Backup Camera Directories</td><td>Boolean
- Default Value: True</td><td>Backup all camera directories</td></tr><tr><td>Remove Local Camera Images</td><td>Boolean</td><td>Remove local camera images after successful transfer to remote host</td></tr><tr><td>SSH Port</td><td>Integer
- Default Value: 22</td><td>Specify a nonstandard SSH port</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Backup of settings are only created if the AoT version or database versions change. This is due to this Function running periodically- if it created a new backup every Period, there would soon be many identical backups. Therefore, if you want to induce the backup of settings, measurements, or camera directories and sync them to your remote system, use the buttons below.</td></tr><tr><td>Backup Settings Now</td><td>Button</td><td></td></tr><tr><td>Backup Measurements Now</td><td>Button</td><td></td></tr><tr><td>Backup Camera Directories Now</td><td>Button</td><td></td></tr></tbody></table>

### Spacer


A spacer to organize Functions.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Color</td><td>Text
- Default Value: #000000</td><td>The color of the name text</td></tr></tbody></table>

### Statistics (Last, Multiple)


This function retrieves multiple measurements, calculates statistics, and stores the results with the selected unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement</td></td><td>Measurements to perform statistics on</td></tr><tr><td>Halt on Missing Measurement</td><td>Boolean</td><td>Don't calculate statistics if >= 1 measurement is not found within Max Age</td></tr></tbody></table>

### Statistics (Past, Single)


This function retrieves multiple values from a single measurement, calculates statistics, and stores the results with the selected unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>The measurements to record</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>Measurement to perform statistics on</td></tr></tbody></table>

### Sum (Accumulate / Point)


Sums a single measurement source over time. Interval mode sums every value between cycles (per-cycle usage). Point mode samples one value at a recurring time-of-day (every N hours, in the device timezone) and sums the most recent N snapshots. The result is stored with the selected measurement and unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Sum Mode</td><td>Select(Options: [<strong>Interval sum (between cycles)</strong> | Point sum (value at a recurring time)] (Default in <strong>bold</strong>)</td><td>Interval: sum all values in the [previous run, now] window. Point: sum the most recent N snapshot values.</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output)</td><td>The single measurement source to sum</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 3600</td><td>[Interval mode] The duration between sums</td></tr><tr><td>Snapshot Time (HH:MM)</td><td>Text
- Default Value: 00:00</td><td>[Point mode] Time-of-day anchor for snapshots in the device timezone (e.g. 00:00). Use 24:00 for midnight.</td></tr><tr><td>Snapshot Interval (Hours)</td><td>Text
- Default Value: 24</td><td>[Point mode] Hours between snapshots, starting from the anchor (e.g. 24 = once daily, 6 = four times daily)</td></tr><tr><td>Point Count (N)</td><td>Integer
- Default Value: 1</td><td>[Point mode] Number of most-recent snapshot values to sum</td></tr><tr><td>Measure Now</td><td>Button</td><td></td></tr></tbody></table>

### Sum (Last, Multiple)


This function retrieves the last value of each selected measurement, sums them, and stores the result with the selected measurement and unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Measurement</td></td><td>Measurement to replace "x" in the equation</td></tr></tbody></table>

### Sum (Past, Single)


This function retrieves past measurements (within Max Age) of the selected measurement, sums them, and stores the result with the selected measurement and unit.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output)</td><td>Measurement to replace "x" in the equation</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr></tbody></table>

### Vapor Pressure Deficit (AVPD)


This function calculates the Vapor Pressure Deficit (AVPD) using leaf temperature and humidity.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Temperature</td><td>Select Measurement (Input, Function)</td><td>Temperature measurement</td></tr><tr><td>Temperature: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>Humidity</td><td>Select Measurement (Input, Function)</td><td>Humidity measurement</td></tr><tr><td>Humidity: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr></tbody></table>

### pH, EC Regulation


This function uses two pumps (acid and base solutions) to regulate pH, and can use up to four pumps (A, B, C, D nutrient solutions) to regulate electrical conductivity (EC). You only need to configure the nutrient solution outputs you intend to use. Outputs that are not configured are not activated during EC adjustment, and you can use from one to four pumps. Outputs can operate in units of duration (seconds) or volume (ml), and each output type must be matched to the selected output channel (an on/off output channel for duration control, a volume output channel for volume control). The mixing ratio of the nutrient solutions is determined by the duration or volume setting of each EC output. If you enter an email address (or multiple addresses separated by commas) in the email notification field, a notification email is sent in the following cases. <br>1) when the pH value goes outside the configured danger range, 2) when the EC value is too high and water must be added to the storage tank, 3) when no measurement can be found in the database within a given Max Age range. <br>Each email notification type has its own timer so that the same notification is not sent repeatedly, and the same notification is not sent for the duration of the configured email timer. <br>Once this duration elapses, the timer resets automatically, allowing a new notification to be sent. You can also manually reset the email timers using the Custom Commands below. <br>When the function is enabled, status text is displayed at the bottom of the screen showing the regulation information and the total duration/volume of each output.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 300</td><td>The duration between measurements or actions</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>The duration to wait before the first operation</td></tr><tr><td>Status Period (seconds)</td><td>Integer
- Default Value: 60</td><td>The duration (seconds) to update the Function status on the UI</td></tr><tr><td colspan="3">Measurement Options</td></tr><tr><td>pH Measurement</td><td>Select Measurement (Input, Function)</td><td>Measurement from the pH input</td></tr><tr><td>pH: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td>EC Measurement</td><td>Select Measurement (Input, Function)</td><td>Measurement from the EC input</td></tr><tr><td>Electrical Conductivity: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>The maximum age of the measurement to use</td></tr><tr><td colspan="3">Output Options</td></tr><tr><td>Output: pH Dose Raise (Base)</td><td>Select Channel (Output_Channels)</td><td>Select an output to raise the pH</td></tr><tr><td>Output: pH Dose Lower (Acid)</td><td>Select Channel (Output_Channels)</td><td>Select an output to lower the pH</td></tr><tr><td>pH Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>Select the output type for the selected Output Channel</td></tr><tr><td>pH Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>The amount to send to the pH dosing pumps (duration or volume)</td></tr><tr><td>Output: EC Dose Nutrient A</td><td>Select Channel (Output_Channels)</td><td>Select an output to dose nutrient A</td></tr><tr><td>Nutrient A Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>Select the output type for the selected Output Channel</td></tr><tr><td>Nutrient A Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>The amount to send to the Nutrient A dosing pump (duration or volume)</td></tr><tr><td>Output: EC Dose Nutrient B</td><td>Select Channel (Output_Channels)</td><td>Select an output to dose nutrient B</td></tr><tr><td>Nutrient B Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>Select the output type for the selected Output Channel</td></tr><tr><td>Nutrient B Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>The amount to send to the Nutrient B dosing pump (duration or volume)</td></tr><tr><td>Output: EC Dose Nutrient C</td><td>Select Channel (Output_Channels)</td><td>Select an output to dose nutrient C</td></tr><tr><td>Nutrient C Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>Select the output type for the selected Output Channel</td></tr><tr><td>Nutrient C Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>The amount to send to the Nutrient C dosing pump (duration or volume)</td></tr><tr><td>Output: EC Dose Nutrient D</td><td>Select Channel (Output_Channels)</td><td>Select an output to dose nutrient D</td></tr><tr><td>Nutrient D Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>Select the output type for the selected Output Channel</td></tr><tr><td>Nutrient D Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>The amount to send to the Nutrient D dosing pump (duration or volume)</td></tr><tr><td colspan="3">Setpoint Options</td></tr><tr><td>pH Setpoint</td><td>Decimal
- Default Value: 5.85</td><td>The desired pH setpoint</td></tr><tr><td>pH Hysteresis</td><td>Decimal
- Default Value: 0.35</td><td>The hysteresis to determine the pH range</td></tr><tr><td>EC Setpoint</td><td>Decimal
- Default Value: 150.0</td><td>The desired electrical conductivity setpoint</td></tr><tr><td>EC Hysteresis</td><td>Decimal
- Default Value: 50.0</td><td>The hysteresis to determine the EC range</td></tr><tr><td>pH Danger Range (High Value)</td><td>Decimal
- Default Value: 7.0</td><td>This high pH value for the danger range</td></tr><tr><td>pH Danger Range (Low Value)</td><td>Decimal
- Default Value: 5.0</td><td>This low pH value for the danger range</td></tr><tr><td colspan="3">Alert Notification Options</td></tr><tr><td>Notification E-Mail</td><td>Text</td><td>E-mail to notify when there is an issue (blank to disable)</td></tr><tr><td>E-Mail Timer Duration (Hours)</td><td>Decimal
- Default Value: 12.0</td><td>How long to wait between sending e-mail notifications</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Each e-mail notification timer can be manually reset before the expiration.</td></tr><tr><td>Reset EC E-mail Timer</td><td>Button</td><td></td></tr><tr><td>Reset pH E-mail Timer</td><td>Button</td><td></td></tr><tr><td>Reset Measurement Issue E-mail Timer</td><td>Button</td><td></td></tr><tr><td>Reset All E-Mail Timers</td><td>Button</td><td></td></tr><tr><td colspan="3">Each total duration and volume can be manually reset.</td></tr><tr><td>Reset All Totals</td><td>Button</td><td></td></tr><tr><td>Reset Total Raise pH Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total Lower pH Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total Raise pH Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total Lower pH Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC A Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC A Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC B Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC B Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC C Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC C Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC D Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC D Volume</td><td>Button</td><td></td></tr></tbody></table>

