## Built-In Widgets

### AI Reasoning Insight

- Libraries: ai

AI 기반 분석과 지능형 작업 추천을 제공합니다.

### Activate/Deactivate Controller


컨트롤러(Input 및 Function)를 활성화/비활성화합니다. PID 컨트롤러를 조작하려면 PID Controller Widget을 사용하세요.

### AoT Controller Switch


컨트롤러를 켜고 끄는 스위치입니다.

### AoT PID

- Libraries: controller

PID 컨트롤러를 표시하고 제어할 수 있습니다.

### AoT Plot


구획 하나를 한 눈에 봅니다 — 단계 기간 바, 목표 대비 실측, 추세, 적산온도. 일정·지침·목표를 여기서 고칩니다.

### AoT Timer

- Libraries: timer

출력을 정해진 시간만큼 켠 뒤 자동으로 끕니다 — 정해진 횟수만큼 반복하는 실행/휴식 사이클, 단발성 실행(`0` = 중지할 때까지 계속), 예약 시작 시각을 지원합니다. 진행 상황이 서버에 저장되므로 새로고침하거나 다른 브라우저에서 열어도 계속 작동합니다. 자세한 내용은 [AoT 타이머](Data-Viewing.md#widget-timer)를 참고하세요.

### AoT Weather Forecast


사용자가 선택한 기간에 대한 기상청(KMA, 대한민국 기상청) 단기 예보를 표시합니다.

### AoT Wind Direction/Speed Gauge

- Libraries: Native SVG

원형 링(0~360°)에 풍향을, 중앙에 풍속을 표시합니다. 8방위 주요 나침반 지점을 위한 보조선이 포함됩니다.

### AoT 그래프

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

동기화 그래프를 표시합니다. 선택한 데이터가 설정한 기간 동안 X축에 표시됩니다. 자세한 내용은 [AoT 그래프](Data-Viewing.md#widget-graph)를 참고하세요.

### AoT 원형 게이지

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

데이터를 원형 게이지로 표시합니다. 올바르게 표시되도록 최댓값 옵션이 마지막 구간(High)과 일치하는지 확인하세요. Temperature, Humidity, VPD 같은 프리셋을 선택하면 최소/최대값과 색상 구간이 자동으로 설정됩니다.

### AoT 지도

- Libraries: MapLibre GL

장치를 인터랙티브 지도에 표시하고 작동 상태를 색상으로 강조합니다. 자세한 내용은 [AoT 지도](Data-Viewing.md#widget-map)를 참고하세요.

### 캘린더

스케줄러의 예약 일정을 AI/사용자/장치 카테고리별로, 그리고 양방향 동기화로 연결한 Google 캘린더까지 함께 달력에 표시합니다. 일정을 클릭해 보거나 편집하고, 드래그로 시각을 다시 조정할 수 있습니다.

### Camera


카메라 이미지 또는 스트림을 표시합니다.

### Function Status


Function의 상태를 표시합니다(지원되는 경우).

### Gauge (Angular) [Highcharts]

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

각도형 게이지를 표시합니다. 게이지가 올바르게 표시되도록 Maximum 옵션을 마지막 Stop High 값으로 설정하세요.

### Gauge (Solid) [Highcharts]

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, solid-gauge-9.1.2.js

솔리드 게이지를 표시합니다. 게이지가 올바르게 표시되도록 Maximum 옵션을 마지막 Stop 값으로 설정하세요.

### Graph (Synchronous) [Highstock]

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

동기화 그래프를 표시합니다(x축의 선택 기간에 대한 모든 데이터가 다운로드됩니다).

### Indicator


측정값에 따라 빨간색 또는 초록색 원형 이미지를 표시합니다. 출력이 켜져 있는지 꺼져 있는지 보여줄 때 유용합니다.

### Measurement (1 Value)


측정값과 타임스탬프를 표시합니다.

### Measurement (2 Values)


두 개의 측정값과 타임스탬프를 표시합니다.

### Output (PWM Slider)


슬라이더를 사용해 PWM 출력을 표시하고 제어할 수 있습니다.

### Python Code


Python 코드를 실행하고 그 출력을 위젯 내에 표시합니다.

### Sequence Controller


Sequence Function을 제어하고 모니터링합니다.

### Spacer


간격 조정용으로 사용하는 간단한 위젯으로, 내용에 텍스트를 설정하는 기능이 포함되어 있습니다.
