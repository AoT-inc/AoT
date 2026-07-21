## Built-In Widgets

### AI Reasoning Insight

- Libraries: ai

AI-driven analysis and intelligent action recommendations.

### Activate/Deactivate Controller


Activate/Deactivate a Controller (Inputs and Functions). For manipulating a PID Controller, use the PID Controller Widget.

### AoT Controller Switch


Switch to turn controllers on and off.

### AoT PID

- Libraries: controller

Displays and allows control of a PID Controller.

### AoT Timer

- Libraries: timer

Turns an output on for a set time, then off automatically — supports a repeating run/rest cycle for a set number of cycles, a single one-shot run (`0` = run until stopped), and a scheduled start time. Progress is saved on the server, so it keeps running after a page refresh or on another browser. See [AoT Timer](Data-Viewing.md#widget-timer) for details.

### AoT Weather Forecast


Displays the KMA (Korea Meteorological Administration) short-term forecast for the period selected by the user.

### AoT Wind Direction/Speed Gauge

- Libraries: Native SVG

Displays wind direction on a circular ring (0-360°) and wind speed in the center. Includes auxiliary lines for the 8 primary compass points.

### AoT Graph

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

Displays a synchronous graph. Data selected will be displayed on the X-axis for the configured duration. See [AoT Graph](Data-Viewing.md#widget-graph) for details.

### AoT Circular Gauge

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

Displays data in a circular gauge. Ensure the maximum value option matches the last section (High) for correct display. Selecting presets like Temperature, Humidity, or VPD automatically sets min/max values and color sections.

### AoT Map

- Libraries: MapLibre GL

Displays your devices on an interactive map and highlights their operating state with color. See [AoT Map](Data-Viewing.md#widget-map) for details.

### Camera


Displays a camera image or stream.

### Function Status


Displays the status of a Function (if supported).

### Gauge (Angular) [Highcharts]

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

Displays an angular gauge. Be sure to set the Maximum option to the last Stop High value for the gauge to display properly.

### Gauge (Solid) [Highcharts]

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, solid-gauge-9.1.2.js

Displays a solid gauge. Be sure to set the Maximum option to the last Stop value for the gauge to display properly.

### Graph (Synchronous) [Highstock]

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

Displays a synchronous graph (all data is downloaded for the selected period on the x-axis).

### Indicator


Displays a red or green circular image based on a measurement value. Useful for showing if an Output is on or off.

### Measurement (1 Value)


Displays a measurement value and timestamp.

### Measurement (2 Values)


Displays two measurement values and timestamps.

### Output (PWM Slider)


Displays and allows control of a PWM output using a slider.

### Python Code


Executes Python code and displays the output within the widget.

### Sequence Controller


Control and Monitor a Sequence Function.

### Spacer


A simple widget to use as a spacer, which includes the ability to set text in its contents.

