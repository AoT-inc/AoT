## Built-In Widgets

### Activate/Deactivate Controller


Activate/Deactivate a Controller (Inputs and Functions). For manipulating a PID Controller, use the PID Controller Widget.

### AoT PID

- Libraries: controller

Displays and allows control of a PID Controller.

### AoT 그래프

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

동기식 그래프를 표시합니다. 선택한 데이터를 설정한 시간 만큼 X축에 표시 합니다.

### AoT 단기예보문


사용자가 선택한 시간의 기상청 발표 단기예보를 출력합니다.

### AoT 밸브 컨트롤


밸브 제어 함수의 시간창과 예정된 순서를 시각화하고, 컨트롤러 활성/비활성을 제어합니다.

### AoT 온/오프 카운터

- Libraries: timer

작동시간·휴식시간·작동횟수를 입력하면 지정된 Output이 자동으로 ON/OFF 됩니다. 현재 진행 중인 횟수는 서버에 저장되어 새로고침이나 다른 브라우저에서도 확인할 수 있습니다.

### AoT 원형 게이지

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

데이터를 원형 게이지를 표시합니다. 게이지가 올바르게 표시되도록 최대값 옵션을 마지막 구간(High)에 맞춰 설정하세요.온도, 습도, VPD 등의 사전 설정을 선택하면, 최소/최대값 및 색상 구간이 자동으로 설정됩니다.

### AoT 지도

- Libraries: Leaflet

선택한 장치의 위치를 지도에 표시합니다. 선택한 색상으로 작동 상태를 강조합니다.

### AoT 컨트롤러 스위치


컨트롤러를 켜고 끌 수 있는 스위치.

### AoT 타이머

- Libraries: timer

시간입력창에 "시/분/초"를 입력하면 입력한 시간만큼 장치가 작동하고 꺼집니다.입력된 시간이 "0"이면 종료 전까지 연속 작동합니다.토글 스위치를 "ON"으로 하면 장치가 켜지고, "OFF"로 하면 장치가 꺼집니다.

### AoT 풍향/풍속 게이지

- Libraries: Native SVG

풍향은 원형 링(0~360°)으로 표시하고, 중앙에는 풍속을 표시합니다. 주요 8개 방위(0/45/90/135/180/225/270/315°) 보조선을 제공합니다.

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

### Spacer


A simple widget to use as a spacer, which includes the ability to set text in its contents.

