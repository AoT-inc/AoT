## Built-In Widgets

### AI Periodic Advice

- Libraries: ai

Displays pre-generated periodic AI analysis. Content depth adapts to widget size automatically.

### AoT Actuator Position


Displays and controls a positional (open/close) actuator: close/stop/open buttons plus a fine-adjust slider.

### AoT Circular Gauge

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

Displays data in a circular gauge. Ensure the maximum value option matches the last section (High) for correct display. Selecting presets like Temperature, Humidity, or VPD automatically sets min/max values and color sections.

### AoT Controller Switch


Switch to turn controllers on and off.

### AoT Facility

- Libraries: Three.js 3D + IEC control

Facility 3D view, environment summary, setpoint editor, actuator control grid, and AI advice.

### AoT Graph

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

Displays a synchronous graph. Data selected will be displayed on the X-axis for the configured duration.

### AoT Map

- Libraries: MapLibre GL JS (Leaflet-free)

Displays the location of the selected device on a map. Highlights the operating state with the selected color. Supports 3D terrain, pitch, and bearing.

### AoT PID

- Libraries: controller

Displays and allows control of a PID Controller.

### AoT PWM Output


Displays and controls a PWM output with a single slider.

### AoT Plot


One plot at a glance: stage timeline, targets against current readings, trends, and accumulated heat. Edit its schedule, guidance and targets from here.

### AoT Timer

- Libraries: timer

Use the toggle switch to turn the device on and off. Turn on "Timer" to operate on a timer: in Simple mode the device runs once for the set time (0 = run until stopped), and in Cycle mode it repeats a Run / Rest sequence for the set number of cycles. "Scheduled Start" begins operation at a set wall-clock time in the device timezone. When "Timer" is off, the toggle simply switches the device on or off regardless of the time settings.

### AoT Weather Forecast


Displays the KMA (Korea Meteorological Administration) short-term forecast for the period selected by the user.

### AoT Wind Direction/Speed Gauge

- Libraries: Native SVG

Displays wind direction on a circular ring (0-360°) and wind speed in the center. Includes auxiliary lines for the 8 primary compass points.

### Calendar


Shows scheduled events (from the Scheduler) on a calendar, split by category (AI / User / Device), and any Google calendars you connect. Click an event for details or to edit; open the full Scheduler for more.

### Camera


Displays a camera image or stream.

### Function Status


Displays the status of a Function (if supported).

### Gauge (Solid) [Highcharts]

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, solid-gauge-9.1.2.js

Displays a solid gauge. Be sure to set the Maximum option to the last Stop value for the gauge to display properly.

### Indicator


Displays a red or green circular image based on a measurement value. Useful for showing if an Output is on or off.

### Measurement (1 Value)


Displays a measurement value and timestamp.

### Measurement (2 Values)


Displays two measurement values and timestamps.

### Modern Camera

- Libraries: aot.camera
- Dependencies: [opencv-python>=4.8.0](https://pypi.org/project/opencv-python>=4.8.0), [python-onvif-zeep>=0.2.12](https://pypi.org/project/python-onvif-zeep>=0.2.12)

Advanced camera widget with auto-dependency installation and profile support.

### Notice Board


Displays the latest notice board post titles. Clicking a title opens the full post (content, poll, replies, acknowledge) in a popup; all actions taken there are reflected on the actual post. Users with write permission can also create, edit, and delete posts directly from the widget.

### Python Code


Executes Python code and displays the output within the widget.

### Sequence Controller


Control and Monitor a Sequence Function.

### Spacer


A simple widget to use as a spacer, which includes the ability to set text in its contents.

