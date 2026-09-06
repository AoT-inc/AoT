## Built-In Widgets

### AI Periodic Advice

- Libraries: ai

Displays pre-generated periodic AI analysis. Content depth adapts to widget size automatically.

### AoT Actuator Position


Displays and controls a positional (open/close) actuator: close/stop/open buttons plus a fine-adjust slider.

### AoT PID

- Libraries: controller

PID 컨트롤러를 표시하고 제어할 수 있습니다.

### AoT PWM Output


Displays and controls a PWM output with a single slider.

### AoT 구획


구획 하나를 한 눈에 — 단계 기간 바, 목표 대비 실측, 추세, 적산온도. 일정·지침·목표를 여기서 고칩니다.

### AoT 그래프

- Libraries: Highstock
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, data-9.1.2.js, exporting-9.1.2.js, export-data-9.1.2.js, offline-exporting-9.1.2.js

동기식 그래프를 표시합니다. 선택한 데이터를 설정한 시간 만큼 X축에 표시 합니다.

### AoT 단기예보문


사용자가 선택한 시간의 기상청 발표 단기예보를 출력합니다.

### AoT 시설

- Libraries: Three.js 3D + IEC control

시설 3D 보기, 환경 요약, 목표값 편집기, 액추에이터 제어 그리드, AI 조언을 제공합니다.

### AoT 원형 게이지

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js

데이터를 원형 게이지로 표시합니다. 게이지가 올바르게 표시되도록 최대값 옵션을 마지막 구간(High)에 맞춰 설정하세요. 온도, 습도, VPD 등의 사전 설정을 선택하면, 최소/최대값 및 색상 구간이 자동으로 설정됩니다.

### AoT 지도

- Libraries: MapLibre GL JS (Leaflet-free)

선택한 장치의 위치를 지도에 표시합니다. 선택한 색상으로 작동 상태를 강조 표시하며, 3D 지형·피치·베어링을 지원합니다.

### AoT 컨트롤러 스위치


컨트롤러를 켜고 끌 수 있는 스위치.

### AoT 타이머

- Libraries: timer

토글 스위치로 장치를 켜고 끕니다. "타이머"를 켜면 타이머로 작동합니다: 단순(Simple) 모드에서는 설정한 시간 동안 한 번 작동하고(0 = 정지할 때까지 계속 작동), 반복(Cycle) 모드에서는 설정한 횟수만큼 작동/휴식 순서를 반복합니다. "예약 시작"은 장치 시간대 기준으로 지정한 시각에 작동을 시작합니다. "타이머"가 꺼져 있으면 시간 설정과 관계없이 토글이 단순히 장치를 켜거나 끕니다.

### AoT 풍향/풍속 게이지

- Libraries: Native SVG

풍향은 원형 링(0~360°)으로 표시하고, 중앙에는 풍속을 표시합니다. 주요 8개 방위(0/45/90/135/180/225/270/315°) 보조선을 제공합니다.

### 게이지 (솔리드) [Highcharts]

- Libraries: Highcharts
- Dependencies: highstock-9.1.2.js, highcharts-more-9.1.2.js, solid-gauge-9.1.2.js

솔리드 게이지를 표시합니다. 게이지가 올바르게 표시되도록 최댓값 옵션을 마지막 Stop 값으로 설정하세요.

### 공지 게시판


최신 공지 게시물 제목을 보여줍니다. 제목을 클릭하면 팝업으로 전체 내용(본문, 투표, 답글, 필독 확인)을 볼 수 있으며, 팝업에서의 모든 활동은 실제 게시물에 반영됩니다.

### 모던 카메라

- Libraries: aot.camera
- Dependencies: [opencv-python>=4.8.0](https://pypi.org/project/opencv-python>=4.8.0), [python-onvif-zeep>=0.2.12](https://pypi.org/project/python-onvif-zeep>=0.2.12)

종속성 자동 설치와 프로필을 지원하는 고급 카메라 위젯입니다.

### 스페이서


내용에 텍스트를 설정할 수 있는 간단한 여백용 위젯입니다.

### 시퀀스 컨트롤러


시퀀스 함수를 제어하고 모니터링합니다.

### 측정값 (1개)


측정값과 타임스탬프를 표시합니다.

### 측정값 (2개)


두 개의 측정값과 타임스탬프를 표시합니다.

### 카메라


카메라 이미지 또는 스트림을 표시합니다.

### 캘린더


스케줄러의 예약 이벤트를 카테고리(AI / 사용자 / 장치)별로, 그리고 연결한 구글 캘린더를 함께 달력에 표시합니다. 이벤트를 클릭하면 상세 확인·편집, 전체 스케줄러는 별도로 엽니다.

### 파이썬 코드


파이썬 코드를 실행하고 결과를 위젯 안에 표시합니다.

### 표시기


측정값에 따라 빨간색 또는 초록색 원형 이미지를 표시합니다. 출력의 켜짐/꺼짐 상태를 보여줄 때 유용합니다.

### 함수 상태


함수의 상태를 표시합니다(지원되는 경우).

