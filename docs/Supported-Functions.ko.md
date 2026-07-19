## Built-In Functions

### AoT VPD


이 함수는 잎 온도와 습도를 기반으로 증기압 부족분(VPD)을 계산합니다.잎의 온도가 입력되지 않은 경우, 잎의 온도 대신 잎 온도에 오프셋을 적용합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>주기 (초)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 기간</td></tr><tr><td>시작 지연 (초)</td><td>Integer
- Default Value: 10</td><td>첫 번째 동작 전 대기 시간</td></tr><tr><td>대기 온도</td><td>Select Measurement (Input, Function)</td><td>대기 온도 측정</td></tr><tr><td>대기 온도: 최대 사용 연령 (초)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 연령</td></tr><tr><td>습도</td><td>Select Measurement (Input, Function)</td><td>습도 측정</td></tr><tr><td>습도: 최대 사용 연령 (초)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 연령</td></tr><tr><td>잎 온도</td><td>Select Measurement (Input, Function)</td><td>잎 온도 측정</td></tr><tr><td>잎 온도: 최대 사용 시간 (초)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 시간</td></tr><tr><td>잎 온도 오프셋(°C)</td><td>Decimal
- Default Value: -1.5</td><td>잎 온도가 입력되지 않았을 경우 적용할 오프셋(°C)</td></tr></tbody></table>

### AoT 평균 (최종, 다중)


이 기능은 선택된 측정값들을 읽어와, 유효한 데이터만 평균을 구한 후, 결과를 지정한 Measurement와 단위로 저장합니다.유효하지 않거나 오래된 측정값(최대 유효 시간 초과)은 평균에서 제외합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>주기 (초)</td><td>Text
- Default Value: 60</td><td>측정 및 계산 주기, 시간(초 단위)</td></tr><tr><td>시작 지연 (초)</td><td>Integer
- Default Value: 10</td><td>첫 측정 전에 대기할 시간(초)</td></tr><tr><td>최대 유효 시간 (초)</td><td>Integer
- Default Value: 360</td><td> 사용할 측정값의 최대 유효 시간</td></tr><tr><td>Measurement</td></td><td>평균을 계산할 측정 값을 선택하세요</td></tr></tbody></table>

### Camera: libcamera: Image/Video

- Dependencies: [libcamera-apps](https://packages.debian.org/search?keywords=libcamera-apps), [ffmpeg](https://packages.debian.org/search?keywords=ffmpeg)

 주의: 이 기능은 현재 실험 단계이며, 이 공지가 제거될 때까지 사용자의 책임하에 사용해야 합니다.libcamera-still 및 libcamera-vid를 사용하여 카메라에서 이미지와 영상을 캡처합니다.이 기능을 활성화해야 정지 이미지 촬영, 타임랩스 촬영, 카메라 위젯(Camera Widget) 사용이 가능합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Status Period (seconds)</td><td>Integer
- Default Value: 60</td><td>UI에 Function 상태를 갱신하는 주기(초)</td></tr><tr><td colspan="3">Image options.</td></tr><tr><td>Custom Image Path</td><td>텍스트</td><td>정지 이미지를 저장할 기본 외 경로를 설정하세요.</td></tr><tr><td>Custom Timelapse Path</td><td>텍스트</td><td>타임랩스 이미지를 저장할 기본 외 경로를 설정하세요.</td></tr><tr><td>Image Extension</td><td>Select(Options: [<strong>JPG</strong> | PNG | BMP | RGB | YUV420] (Default in <strong>bold</strong>)</td><td>이미지 저장 파일 형식</td></tr><tr><td>Image: Resolution: Width</td><td>Integer
- Default Value: 720</td><td>정지 이미지 너비</td></tr><tr><td>Image: Resolution: Height</td><td>Integer
- Default Value: 480</td><td>정지 이미지 높이</td></tr><tr><td>Brightness</td><td>Decimal</td><td>정지 이미지의 밝기 (-1 ~ 1)</td></tr><tr><td>Image: Contrast</td><td>Decimal
- Default Value: 1.0</td><td>정지 이미지의 대비. 값이 클수록 대비가 강한 이미지가 생성됩니다.</td></tr><tr><td>Saturation</td><td>Decimal
- Default Value: 1.0</td><td>정지 이미지의 채도입니다. 값이 클수록 더 진한 색이 나오며, 0.0은 흑백 이미지를 만듭니다.</td></tr><tr><td>Sharpness</td><td>Decimal</td><td>정지 이미지의 선명도입니다. 값이 클수록 더 진한 색이 나오며, 0.0은 흑백 이미지를 만듭니다.</td></tr><tr><td>Shutter Speed (Microseconds)</td><td>Integer</td><td>셔터 속도(마이크로초). 0이면 비활성화되어 자동 노출로 돌아갑니다.</td></tr><tr><td>Gain</td><td>Decimal
- Default Value: 1.0</td><td>정지 이미지 게인.</td></tr><tr><td>White Balance: Auto</td><td>Select(Options: [<strong>Auto</strong> | Incandescent | Tungsten | Fluorescent | Indoor | Daylight | Cloudy | Custom] (Default in <strong>bold</strong>)</td><td>이미지의 화이트 밸런스</td></tr><tr><td>White Balance: Red Gain</td><td>Decimal</td><td>정지 이미지의 화이트 밸런스 red 게인입니다(red와 blue를 0으로 두지 않으면 Auto White Balance가 비활성화됨).</td></tr><tr><td>White Balance: Blue Gain</td><td>Decimal</td><td>정지 이미지의 화이트 밸런스 red 게인입니다(red와 blue를 0으로 두지 않으면 Auto White Balance가 비활성화됨).</td></tr><tr><td>Flip Horizontally</td><td>Boolean</td><td>이미지 좌우 반전.</td></tr><tr><td>Flip Vertically</td><td>Boolean</td><td>이미지를 상하로 뒤집습니다.</td></tr><tr><td>Rotate (Degrees)</td><td>Integer</td><td>이미지를 회전합니다.</td></tr><tr><td>Custom libcamera-still Options</td><td>텍스트</td><td>libcamera-still 명령에 사용자 지정 옵션을 전달합니다.</td></tr><tr><td colspan="3">Video options.</td></tr><tr><td>Custom Video Path</td><td>텍스트</td><td>동영상 저장용 사용자 지정 경로 설정</td></tr><tr><td>Video Extension</td><td>Select(Options: [<strong>H264 -> MP4 (with ffmpeg)</strong> | H264 | MJPEG | YUV420] (Default in <strong>bold</strong>)</td><td>영상 저장 파일 형식</td></tr><tr><td>Video: Resolution: Width</td><td>Integer
- Default Value: 720</td><td>영상 너비</td></tr><tr><td>Video: Resolution: Height</td><td>Integer
- Default Value: 480</td><td>영상 높이</td></tr><tr><td>Custom libcamera-vid Options</td><td>텍스트</td><td>libcamera-vid 명령에 사용자 정의 옵션 전달.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Capture Image</td><td>Button</td><td></td></tr><tr><td colspan="3">To capture a video, enter the duration and press Capture Video.</td></tr><tr><td>Video Duration (Seconds)</td><td>Integer
- Default Value: 5</td><td>영상 녹화 시간</td></tr><tr><td>Capture Video</td><td>Button</td><td></td></tr><tr><td colspan="3">To start a timelapse, enter the duration and period and press Start Timelapse.</td></tr><tr><td>Timelapse Duration (Seconds)</td><td>Integer
- Default Value: 2592000</td><td>타임랩스 실행 시간</td></tr><tr><td>Timelapse Period (Seconds)</td><td>Integer
- Default Value: 600</td><td>타임랩스 촬영 주기</td></tr><tr><td>Start Timelapse</td><td>Button</td><td></td></tr><tr><td colspan="3">To stop an active timelapse, press Stop Timelapse.</td></tr><tr><td>Stop Timelapse</td><td>Button</td><td></td></tr><tr><td colspan="3">To pause or resume an active timelapse, press Pause Timelapse or Resume Timelapse.</td></tr><tr><td>Pause Timelapse</td><td>Button</td><td></td></tr><tr><td>Resume Timelapse</td><td>Button</td><td></td></tr></tbody></table>

### Display: Generic LCD 16x2 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

이 함수는 I2C를 통해 16x2 LCD 디스플레이에 출력을 제공합니다. 이 디스플레이는 한 번에 2줄을 표시할 수 있으므로, 라인 세트 수(Number of Line Sets)가 변경되면 2개 채널씩 추가됩니다. 설정된 주기(Period)마다 LCD가 새로고침되며, 다음 세트의 라인이 표시됩니다. 따라서 처음 표시되는 2줄은 채널 0과 1이며, 이후 2와 3, 그다음 4와 5가 표시되는 방식으로 진행됩니다. 모든 채널이 표시된 후에는 다시 처음부터 순환됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x20</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr><tr><td>Backlight Flashing On</td><td>Button</td><td></td></tr><tr><td>Backlight Flashing Off</td><td>Button</td><td></td></tr></tbody></table>

### Display: Generic LCD 20x4 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

이 기능은 I2C를 통해 20x4 LCD 디스플레이에 출력을 제공합니다. 이 디스플레이는 한 번에 4줄을 표시할 수 있으므로, 라인 세트 수(Number of Line Sets)가 변경되면 4개 채널씩 추가됩니다. 설정된 주기(Period)마다 LCD가 새로고침되며, 다음 세트의 라인이 표시됩니다. 따라서 처음 표시되는 4줄은 채널 0, 1, 2, 3이며, 이후 4, 5, 6, 7, 그다음 8, 9, 10, 11이 표시되는 방식으로 진행됩니다. 모든 채널이 표시된 후에는 다시 처음부터 순환됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x20</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr></tbody></table>

### Display: Grove LCD 16x2 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

이 기능은 I2C를 통해 Grove 16x2 LCD 디스플레이에 출력을 제공합니다. 이 디스플레이는 한 번에 2줄을 표시할 수 있으므로, 라인 세트 수(Number of Line Sets)가 변경되면 2개 채널씩 추가됩니다. 설정된 주기(Period)마다 LCD가 새로고침되며, 다음 세트의 라인이 표시됩니다. 따라서 처음 표시되는 2줄은 채널 0과 1, 이후 채널 2와 3, 그다음 채널 4와 5가 표시되는 방식으로 진행됩니다. 모든 채널이 표시된 후에는 다시 처음부터 순환됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3e</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Backlight I2C Address</td><td>Text
- Default Value: 0x62</td><td>백라이트 제어용 I2C 주소</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>Backlight Red (0 - 255)</td><td>Integer
- Default Value: 255</td><td>시작 시 백라이트의 빨간색 값을 설정하세요.</td></tr><tr><td>Backlight Green (0 - 255)</td><td>Integer
- Default Value: 255</td><td>시작 시 백라이트의 녹색 값을 설정하세요.</td></tr><tr><td>Backlight Blue (0 - 255)</td><td>Integer
- Default Value: 255</td><td>시작 시 백라이트의 파란색 값을 설정하세요.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr><tr><td>Color (RGB)</td><td>Text
- Default Value: 255,0,0</td><td>R,G,B 값 형식의 색상(예: 따옴표 없이 "255,0,0")</td></tr><tr><td>Set Backlight Color</td><td>Button</td><td></td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [2 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 기능은 I2C를 통해 128x32 SSD1306 OLED 디스플레이에 출력을 제공합니다. 이 디스플레이 기능은 한 번에 2줄을 표시할 수 있으므로, 라인 세트 수(Number of Line Sets)가 변경되면 2개 채널씩 추가됩니다. 설정된 주기(Period)마다 LCD가 새로고침되며, 다음 세트의 라인이 표시됩니다. 따라서 처음 표시되는 라인 세트는 채널 0 - 1이며, 이후 2 - 3, 그다음 4 - 5가 표시되는 방식으로 진행됩니다. 모든 채널이 표시된 후에는 다시 처음부터 순환됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>글꼴 크기 (포인트)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [2 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 Function은 SPI를 통해 128x32 SSD1306 OLED 디스플레이에 출력합니다. 이 디스플레이 Function은 한 번에 2줄을 표시하므로, Number of Line Sets를 변경하면 채널이 2개 단위로 추가됩니다. 매 Period마다 LCD가 새로고침되어 다음 줄 세트를 표시합니다. 따라서 처음 표시되는 줄 세트는 채널 0 - 1, 다음은 2 - 3 순입니다. 모든 채널이 표시되면 다시 처음으로 순환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>SPI Device</td><td>Integer</td><td>SPI 장치</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>SPI 버스</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>디스플레이의 DC에 연결된 핀(BCM 번호)</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 CS에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>글꼴 크기 (포인트)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [4 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 기능은 I2C를 통해 128x32 SSD1306 OLED 디스플레이에 출력을 제공합니다. 이 디스플레이 기능은 한 번에 4줄을 표시할 수 있으므로, 라인 세트 수(Number of Line Sets)가 변경되면 4개 채널씩 추가됩니다. 설정된 주기(Period)마다 LCD가 새로고침되며, 다음 세트의 라인이 표시됩니다. 따라서 처음 표시되는 라인 세트는 채널 0 - 3이며, 이후 4 - 7, 그다음 8 - 11이 표시되는 방식으로 진행됩니다. 모든 채널이 표시된 후에는 다시 처음부터 순환됩니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>글꼴 크기 (포인트)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [4 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 Function은 SPI를 통해 128x32 SSD1306 OLED 디스플레이에 출력합니다. 이 디스플레이 Function은 한 번에 4줄을 표시하므로, Number of Line Sets를 변경하면 채널이 4개 단위로 추가됩니다. 매 Period마다 LCD가 새로고침되어 다음 줄 세트를 표시합니다. 따라서 처음 표시되는 줄 세트는 채널 0 - 3, 다음은 4 - 7 순입니다. 모든 채널이 표시되면 다시 처음으로 순환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>SPI Device</td><td>Integer</td><td>SPI 장치</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>SPI 버스</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>디스플레이의 DC에 연결된 핀(BCM 번호)</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 CS에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>글꼴 크기 (포인트)</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [4 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 Function은 I2C를 통해 128x64 SSD1306 OLED 디스플레이에 출력합니다. 이 디스플레이 Function은 한 번에 4줄을 표시하므로, Number of Line Sets를 변경하면 채널이 4개 단위로 추가됩니다. 매 Period마다 LCD가 새로고침되어 다음 줄 세트를 표시합니다. 따라서 처음 표시되는 줄 세트는 채널 0 - 3, 다음은 4 - 7 순입니다. 모든 채널이 표시되면 다시 처음으로 순환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>글꼴 크기 (포인트)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [4 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 Function은 SPI를 통해 128x64 SSD1306 OLED 디스플레이에 출력합니다. 이 디스플레이 Function은 한 번에 4줄을 표시하므로, Number of Line Sets를 변경하면 채널이 4개 단위로 추가됩니다. 매 Period마다 LCD가 새로고침되어 다음 줄 세트를 표시합니다. 따라서 처음 표시되는 줄 세트는 채널 0 - 3, 다음은 4 - 7 순입니다. 모든 채널이 표시되면 다시 처음으로 순환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>SPI Device</td><td>Integer</td><td>SPI 장치</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>SPI 버스</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>디스플레이의 DC에 연결된 핀(BCM 번호)</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 CS에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>글꼴 크기 (포인트)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [8 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 Function은 I2C를 통해 128x64 SSD1306 OLED 디스플레이에 출력합니다. 이 디스플레이 Function은 한 번에 8줄을 표시하므로, Number of Line Sets를 변경하면 채널이 8개 단위로 추가됩니다. 매 Period마다 LCD가 새로고침되어 다음 줄 세트를 표시합니다. 따라서 처음 표시되는 줄 세트는 채널 0 - 7, 다음은 8 - 15 순입니다. 모든 채널이 표시되면 다시 처음으로 순환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>글꼴 크기 (포인트)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [8 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

이 Function은 SPI를 통해 128x64 SSD1306 OLED 디스플레이에 출력합니다. 이 디스플레이 Function은 한 번에 8줄을 표시하므로, Number of Line Sets를 변경하면 채널이 8개 단위로 추가됩니다. 매 Period마다 LCD가 새로고침되어 다음 줄 세트를 표시합니다. 따라서 처음 표시되는 줄 세트는 채널 0 - 7, 다음은 8 - 15 순입니다. 모든 채널이 표시되면 다시 처음으로 순환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>SPI Device</td><td>Integer</td><td>SPI 장치</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>SPI 버스</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>디스플레이의 DC에 연결된 핀(BCM 번호)</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 CS에 연결된 핀(BCM 번호)</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>한 줄에 표시할 최대 문자 수</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>기본 폰트를 사용하지 않습니다. 사용할 폰트 경로를 지정하려면 활성화하세요.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>사용할 사용자 지정 폰트 경로</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>글꼴 크기 (포인트)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Display: SSD1309 OLED 128x64 [8 Lines] (I2C)

- Dependencies: [pyusb](https://pypi.org/project/pyusb), [luma.oled](https://pypi.org/project/luma.oled), [Pillow](https://pypi.org/project/Pillow), [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [libfreetype6-dev](https://packages.debian.org/search?keywords=libfreetype6-dev), [liblcms2-dev](https://packages.debian.org/search?keywords=liblcms2-dev), [libopenjp2-7](https://packages.debian.org/search?keywords=libopenjp2-7), [libtiff5](https://packages.debian.org/search?keywords=libtiff5)

이 Function은 I2C를 통해 128x64 SSD1309 OLED 디스플레이에 출력합니다. 이 디스플레이 Function은 한 번에 8줄을 표시하므로, Number of Line Sets를 변경하면 채널이 8개 단위로 추가됩니다. 매 Period마다 LCD가 새로고침되어 다음 줄 세트를 표시합니다. 따라서 처음 표시되는 줄 세트는 채널 0 - 7, 다음은 8 - 15 순입니다. 모든 채널이 표시되면 다시 처음으로 순환합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 10</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>I2C Address</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>LCD에서 순환할 라인 세트 수</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>디스플레이의 RST에 연결된 핀(BCM 번호)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>선택</td><td>라인에 표시할 내용</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>라인에 표시할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement Label</td><td>텍스트</td><td>기본 Measurement 레이블을 덮어쓰도록 설정</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>소수점 이하 자릿수</td></tr><tr><td>텍스트</td><td>Text
- Default Value: Text</td><td>표시할 텍스트</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Measurement 단위 표시 (있는 경우)</td></tr></tbody></table>

### Equation (Multi-Measure)


이 기능은 두 개의 측정값을 가져와 사용자가 설정한 수식에 적용한 후, 결과값을 선택된 측정값과 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Measurement: A</td><td>Select Measurement (Input, Output, Function)</td><td>a를 대체할 Measurement</td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement: B</td><td>Select Measurement (Input, Output, Function)</td><td>b를 대체할 Measurement</td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Equation</td><td>Text
- Default Value: a*(2+b)</td><td>measurement a와 b를 사용한 수식</td></tr></tbody></table>

### Equation (Single-Measure)


이 기능은 측정값을 가져와 사용자가 설정한 수식에 적용한 후, 결과값을 선택된 측정값과 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Output, Function)</td><td>수식의 "x"를 대체할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Equation</td><td>Text
- Default Value: x*5+2</td><td>measurement를 사용한 수식</td></tr></tbody></table>

### Example: Generic

- Dependencies: [build-essential](https://packages.debian.org/search?keywords=build-essential)

이 기능 모듈은 다양한 UI 옵션 유형을 보여주는 예제입니다. 새로운 맞춤형 기능 모듈을 개발하는 방법을 학습하는 용도로만 사용되며, 그 외의 실용적인 용도는 없습니다.이 메시지는 기능 옵션 위에 표시됩니다.이 기능은 마지막으로 선택된 측정값을 가져온 후, 선택된 출력을 15초 동안 켠 후 비활성화됩니다.코드를 분석하여 자신만의 기능 모듈을 개발하고, 기능 가져오기(Function Import) 페이지에서 가져올 수 있도록 구성하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td colspan="3">The following fields are for text, integers, and decimal inputs. This message will automatically create a new line for the options that come after it. Alternatively, a new line can be created instead without a message, which are what separates each of the following three inputs.</td></tr><tr><td>Text Input</td><td>Text
- Default Value: Text_1</td><td>텍스트를 입력</td></tr><tr><td>Integer Input</td><td>Integer
- Default Value: 100</td><td>정수를 입력</td></tr><tr><td>Devimal Input</td><td>Decimal
- Default Value: 50.2</td><td>소수 값을 입력</td></tr><tr><td colspan="3">A boolean value can be made using a checkbox.</td></tr><tr><td>Boolean Value</td><td>Boolean
- Default Value: True</td><td>True(체크) 또는 False(체크 해제)로 설정</td></tr><tr><td colspan="3">A dropdown selection can be made of any user-defined options, with any of the options selected by default when the Function is added by the user.</td></tr><tr><td>Select Option</td><td>Select(Options: [First Option Selected | <strong>Second Option Selected</strong> | Third Option Selected] (Default in <strong>bold</strong>)</td><td>드롭다운에서 옵션 선택</td></tr><tr><td colspan="3">A specific measurement from an Input, Function, or PID Controller can be selected. The following dropdown will be populated if at least one Input, Function, or PID Controller has been created (as long as the Function has measurements, e.g. Statistics Function).</td></tr><tr><td>Controller Measurement</td><td>Select Measurement (Input, Function, PID)</td><td>컨트롤러 Measurement 선택</td></tr><tr><td colspan="3">An output channel measurement can be selected that will return the Output ID, Channel ID, and Measurement ID. This is useful if you need more than just the Output and Channel IDs and require the user to select the specific Measurement of a channel.</td></tr><tr><td>Output Channel Measurement</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output channel and measurement </td></tr><tr><td colspan="3">An output can be selected that will return the Output ID if only the output ID is needed.</td></tr><tr><td>Output Device</td><td>Select Device</td><td>Output 장치 선택</td></tr><tr><td colspan="3">An Input, Output, Function, PID, or Trigger can be selected that will return the ID if only the controller ID is needed (e.g. for activating/deactivating a controller)</td></tr><tr><td>Controller Device</td><td>Select Device</td><td>Input/Output/Function/PID/Trigger 컨트롤러를 선택하세요.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Button One will pass the Button One Value to the button_one() function of this module. This allows functions to be executed with user-specified inputs. These can be text, integers, decimals, or boolean values.</td></tr><tr><td>Button One Value</td><td>Integer
- Default Value: 650</td><td>버튼 1 값.</td></tr><tr><td>Button One</td><td>Button</td><td></td></tr><tr><td colspan="3">Here is another action with another user input that will be passed to the function. Note that Button One Value will also be passed to this second function, so be sure to use unique ids for each input.</td></tr><tr><td>Button Two Value</td><td>Integer
- Default Value: 1500</td><td>버튼 2 값.</td></tr><tr><td>Button Two</td><td>Button</td><td></td></tr></tbody></table>

### Humidity (Wet/Dry-Bulb)


이 기능은 습구 및 건구 온도 측정값을 기반으로 습도를 계산합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Dry Bulb Temperature</td><td>Select Measurement (Input, Function)</td><td>건구 온도 measurement</td></tr><tr><td>Dry Bulb: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Wet Bulb Temperature</td><td>Select Measurement (Input, Function)</td><td>습구 온도 measurement</td></tr><tr><td>Wet Bulb: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Pressure</td><td>Select Measurement (Input, Function)</td><td>압력 Measurement</td></tr><tr><td>Pressure: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr></tbody></table>

### LoRaWAN 모드/주기 관리자 (RAK3172E)


배터리·시간대·밸브활동·링크품질을 기준으로 Class/하트비트 주기를 결정합니다. ChirpStack gRPC(DeviceService.Enqueue)를 통해 직접 다운링크를 큐잉합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>판정 및 적용 주기(초)</td></tr><tr><td colspan="3"><b>서버 연결</b></td></tr><tr><td>ChirpStack gRPC 서버</td><td>Text
- Default Value: 127.0.0.1:8080</td><td>호스트:포트 형식 (예: 127.0.0.1:8080) 또는 http(s)://호스트:포트</td></tr><tr><td>API Key</td><td>텍스트</td><td>JWT 토큰 값을 입력하세요 (Bearer 제외)</td></tr><tr><td>DevEUI</td><td>텍스트</td><td>16자리 16진수 DevEUI (구분자 허용)</td></tr><tr><td colspan="3"><b>측정 입력</b></td></tr><tr><td>배터리 측정</td><td>Select Measurement (Input)</td><td>배터리 전압(V) 측정값을 선택합니다.</td></tr><tr><td>RSSI 측정</td><td>Select Measurement (Input)</td><td>RSSI(주파수세기, dBm) 측정값을 선택합니다.</td></tr><tr><td>SNR 측정</td><td>Select Measurement (Input)</td><td>SNR(노이즈비율, dB) 측정값을 선택합니다.</td></tr><tr><td>엔드노드 클래스</td><td>Select Measurement (Input)</td><td>HB에서 추출한 현재 장치 클래스(1=A,2=B,3=C) 측정값</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 4000</td><td>사용할 측정치의 최대 허용 연령(초)</td></tr><tr><td>재시도 간격(분)</td><td>Decimal</td><td>ACK가 없을 때 동일 모드를 다시 적용할 간격(0이면 재시도 안 함)</td></tr><tr><td>LoRa 클래스 정책</td><td>Select(Options: [<strong>자동</strong> | CLASS-A | CLASS-B | CLASS-C] (Default in <strong>bold</strong>)</td><td>자동일 때만 모드에 따라 Class를 전환하며, 특정 클래스를 선택하면 그 클래스를 유지합니다.</td></tr><tr><td>입력값 유효 시에만 모드 전환</td><td>Boolean</td><td>입력 조건/측정값이 유효할 때만 모드 적용</td></tr><tr><td colspan="3"><b>운영 시간대</b><br/><small>성능 모드로 작동할 시간을 설정 합니다. 0~24 입력 또는 시작과 종료시간이 같으면 24시간</small></td></tr><tr><td>성능 모드 시작(시)</td><td>Integer
- Default Value: 4</td><td>성능 모드 시작 시각 (0–23)</td></tr><tr><td>성능 모드 종료(시)</td><td>Integer
- Default Value: 18</td><td>성능 모드 종료 시각 (0–23)</td></tr><tr><td>성능 모드 선행(분)</td><td>Integer
- Default Value: 10</td><td>주간 시작 전에 미리 성능(Class C) 모드로 전환할 시간을 분 단위로 지정합니다.</td></tr><tr><td colspan="3"><b>모드별 HB 주기</b><br/><small>모드 별 하트비트 주기를 설정 합니다.</small></td></tr><tr><td>성능 모드 클래스</td><td>Select(Options: [Class A | Class B | <strong>Class C</strong>] (Default in <strong>bold</strong>)</td><td>성능(C) 정책일 때 펌웨어에 적용할 LoRa 클래스</td></tr><tr><td>절전 모드 클래스</td><td>Select(Options: [Class A | <strong>Class B</strong> | Class C] (Default in <strong>bold</strong>)</td><td>절전(B) 정책일 때 펌웨어에 적용할 LoRa 클래스</td></tr><tr><td>초절전 모드 클래스</td><td>Select(Options: [Class A | <strong>Class B</strong> | Class C] (Default in <strong>bold</strong>)</td><td>초절전(A) 정책일 때 펌웨어에 적용할 LoRa 클래스</td></tr><tr><td>성능 하트비트(분)</td><td>Integer
- Default Value: 30</td><td>성능(C) 모드 하트비트 주기(분)</td></tr><tr><td>절전 하트비트(분)</td><td>Integer
- Default Value: 30</td><td>절전(B) 모드 하트비트 주기(분)</td></tr><tr><td>초절전 하트비트(분)</td><td>Integer
- Default Value: 60</td><td>초절전(A) 모드 하트비트 주기(분)</td></tr><tr><td colspan="3"><b>임계값 옵션</b><br/><small>모드 전환 임계값을 설정 합니다.</small></td></tr><tr><td>배터리 관리</td><td>Boolean</td><td>배터리 전압에 따라 모드를 자동으로 전환합니다. (LoRa 클래스 정책이 자동일 때만 동작)</td></tr><tr><td>성능 모드 임계(V)</td><td>Decimal
- Default Value: 12.0</td><td>안정적인 운영이 가능한 전압 기준</td></tr><tr><td>절전 임계(V)</td><td>Decimal
- Default Value: 11.7</td><td>절전 모드로 전환하는 전압 기준</td></tr><tr><td>초절전 임계(V)</td><td>Decimal
- Default Value: 11.4</td><td>초절전 모드로 전환하는 전압 기준</td></tr><tr><td>배터리 누락 시 모드 적용 중단</td><td>Boolean
- Default Value: True</td><td>배터리 측정이 없거나 너무 오래되면 모드/주기 변경을 보류합니다.</td></tr><tr><td>링크 RSSI 최소(dBm)</td><td>Integer
- Default Value: -110</td><td>이상일 때 링크 양호로 간주</td></tr><tr><td>링크 SNR 최소(dB)</td><td>Integer
- Default Value: -10</td><td>이상일 때 링크 양호로 간주</td></tr></tbody></table>

### Neokey 4x1 Neopixel Keyboard (Execute Actions)

- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-neokey](https://pypi.org/project/adafruit-circuitpython-neokey)

이 기능은 키가 눌릴 때 특정 동작을 실행합니다. 이 모듈 하단에 동작을 추가한 후, 각 키에 대해 하나 이상의 짧은 액션 ID를 입력하고 쉼표로 구분하십시오. 액션 ID는 동작 옆에서 찾을 수 있습니다(예: “[Action 0559689e] Controller: Activate”의 경우 액션 ID는 0559689e입니다). 액션 ID를 입력할 때 여러 개의 ID를 쉼표로 구분하여 입력합니다(예: “asdf1234” 또는 “asdf1234,qwer5678,zxcv0987”). 동작은 입력된 텍스트 문자열의 순서대로 실행됩니다. 키가 눌릴 때 실행할 액션 ID를 입력하십시오. 토글 동작을 활성화하면, 번갈아 가며 키를 누를 때마다 토글된 액션 ID에 나열된 동작이 실행됩니다. 키가 눌리기 전, 눌린 후, 마지막 동작이 실행되는 동안의 LED 색상을 설정할 수 있습니다. 색상은 RGB 문자열로 0~255 범위의 값을 가집니다. 예를 들어, 빨간색은 “255, 0, 0”, 파란색은 “0, 0, 255”로 입력합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I2C Address</td><td>Text
- Default Value: 0x30</td><td></td></tr><tr><td>I2C Bus</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>LED Brightness (0.0-1.0)</td><td>Decimal
- Default Value: 0.2</td><td>LED 밝기</td></tr><tr><td>LED Flash Period (Seconds)</td><td>Text
- Default Value: 1.0</td><td>LED 깜빡임 시작 시 주기 설정</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Name</td><td>텍스트</td><td>다른 것과 구분하기 위한 이름</td></tr><tr><td>LED Delay (Seconds)</td><td>Text
- Default Value: 1.5</td><td>마지막 action 실행 후 LED를 켜 둘 시간</td></tr><tr><td>Action ID(s)</td><td>텍스트</td><td>키를 눌렀을 때 실행할 액션을 설정합니다. 하나 이상의 Action ID를 쉼표로 구분해 입력하세요.</td></tr><tr><td>Enable Toggling Actions</td><td>Boolean</td><td>두 세트의 Action을 번갈아 실행</td></tr><tr><td>Toggled Action ID(s)</td><td>텍스트</td><td>짝수 번째 누름에서 키를 눌렀을 때 실행할 액션을 설정합니다. 하나 이상의 Action ID를 쉼표로 구분해 입력하세요.</td></tr><tr><td>Resting LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 0</td><td>실행 중인 action이 없을 때의 RGB 색상(예: 10, 0, 0)</td></tr><tr><td>Actions Running LED Color: (RGB)</td><td>Text
- Default Value: 0, 255, 0</td><td>마지막 action을 제외한 나머지 실행 중일 때의 RGB 색상(예: 10, 0, 0)</td></tr><tr><td>Last Action LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 255</td><td>마지막 action 실행 중일 때의 RGB 색상(예: 10, 0, 0)</td></tr><tr><td>Shutdown LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 0</td><td>Function이 비활성화되었을 때의 RGB 색상(예: 10, 0, 0)</td></tr></tbody></table>

### PID 오토튠


이 기능은 PID 컨트롤러 자동 튜닝을 시도합니다. 즉, 출력을 활성화하고 센서에서 응답을 여러 번 측정하여 P, I, D 게인 값을 계산합니다.작동 상태에 대한 업데이트는 데몬 로그에 기록되며, 자동 튜닝이 성공적으로 완료되면 요약 정보도 데몬 로그에 저장됩니다.현재 측정값을 증가시키는 동작만 지원하며, 측정값을 낮추는 기능은 컨트롤러 코드의 일부 수정이 필요할 수 있습니다.출력이 설정값을 초과하도록 정상적으로 측정값을 증가시키는지 모니터링하려면 대시보드에서 측정값과 출력을 그래프로 표시하는 것을 권장합니다.자동 튜닝 기능은 실험적인 기능이며, 완전히 개발된 상태가 아닙니다. PID 게인을 제대로 생성하지 못할 가능성이 높으므로, 정확한 PID 컨트롤러 튜닝을 위해 이 기능에 의존하지 않는 것이 좋습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>선택한 output이 영향을 줄 measurement를 선택하세요.</td></tr><tr><td>Output</td><td>Select Device, Measurement, and Channel (Output)</td><td>측정에 영향을 줄, 조절할 output을 선택하세요.</td></tr><tr><td>Period</td><td>Text
- Default Value: 30</td><td>출력에 전원 공급 사이의 주기</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>출력이 측정값을 밀어붙일 수 있도록, 현재 측정값에서 충분히 떨어진 값입니다.</td></tr><tr><td>Noise Band</td><td>Decimal
- Default Value: 0.5</td><td>측정값이 도달해야 하는 setpoint 초과 범위</td></tr><tr><td>Outstep</td><td>Decimal
- Default Value: 10</td><td>매 Period마다 output을 켤 시간(초)</td></tr><tr><td colspan="3">Currently, only autotuning to raise a condition (measurement) is supported.</td></tr><tr><td>Direction</td><td>Select(Options: [<strong>Raise</strong> | Lower (Cooling/Humidifying)] (Default in <strong>bold</strong>)</td><td>Output이 measurement를 밀어붙일 방향</td></tr></tbody></table>

### Spacer


Function 정리를 위한 구분자.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Color</td><td>Text
- Default Value: #000000</td><td>이름 텍스트 색상</td></tr></tbody></table>

### pH, EC 제어


이 기능은 pH를 조절하기 위해 두 개의 펌프(산 및 염기 용액)를 사용하며, 전기전도도(EC)를 조절하기 위해 최대 4개의 펌프(A, B, C, D 영양제 용액)를 사용할 수 있습니다. 사용하려는 영양제 용액 출력만 설정하면 됩니다. 설정되지 않은 출력은 EC 조정 시 활성화되지 않으며, 최소 1개에서 최대 4개의 펌프까지 사용할 수 있습니다. 출력은 지속 시간(초) 또는 부피(ml) 단위로 작동할 수 있으며, 각 출력 유형을 선택한 출력 채널에 맞게 설정해야 합니다(지속 시간 조절에는 온/오프 출력 채널, 부피 조절에는 부피 출력 채널 선택). 영양제 용액의 혼합 비율은 각 EC 출력의 지속 시간 또는 부피 설정에 의해 결정됩니다.이메일 알림 필드에 이메일 주소(또는 쉼표로 구분된 여러 개의 주소)를 입력하면, 다음 경우에 알림 이메일이 발송됩니다.<br>1) pH 값이 설정된 위험 범위를 벗어났을 때, 2) EC 값이 너무 높아 저장 탱크에 물을 추가해야 할 때, 3) 특정 Max Age 범위 내에서 데이터베이스에서 측정값을 찾을 수 없을 때.<br>각 이메일 알림 유형에는 자체 타이머가 설정되어 있어 동일한 알림이 반복적으로 전송되지 않으며, 설정된 이메일 타이머 지속 시간 동안 동일한 알림이 전송되지 않습니다.<br>이 지속 시간이 지나면 타이머가 자동으로 재설정되어 새로운 알림 전송이 허용됩니다. 또한, 아래의 사용자 지정 명령(Custom Commands)을 사용하여 이메일 타이머를 수동으로 재설정할 수도 있습니다.<br>기능이 활성화되면, 상태 텍스트가 화면 하단에 표시되며 조절 정보 및 각 출력의 총 지속 시간/부피가 나타납니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 300</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Status Period (seconds)</td><td>Integer
- Default Value: 60</td><td>UI에 Function 상태를 갱신하는 주기(초)</td></tr><tr><td colspan="3">Measurement Options</td></tr><tr><td>pH Measurement</td><td>Select Measurement (Input, Function)</td><td>pH input의 measurement</td></tr><tr><td>pH: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>EC Measurement</td><td>Select Measurement (Input, Function)</td><td>EC input의 measurement</td></tr><tr><td>Electrical Conductivity: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td colspan="3">Output Options</td></tr><tr><td>Output: pH Dose Raise (Base)</td><td>Select Channel (Output_Channels)</td><td>pH를 올릴 Output 선택</td></tr><tr><td>Output: pH Dose Lower (Acid)</td><td>Select Channel (Output_Channels)</td><td>pH를 낮출 Output 선택</td></tr><tr><td>pH Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>선택한 Output Channel의 output 타입을 선택하세요.</td></tr><tr><td>pH Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>pH 투입 펌프로 보낼 양(시간 또는 용량)</td></tr><tr><td>Output: EC Dose Nutrient A</td><td>Select Channel (Output_Channels)</td><td>양액 A 투입 Output 선택</td></tr><tr><td>Nutrient A Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>선택한 Output Channel의 output 타입을 선택하세요.</td></tr><tr><td>Nutrient A Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>Nutrient A 투입 펌프로 보낼 양(시간 또는 용량)</td></tr><tr><td>Output: EC Dose Nutrient B</td><td>Select Channel (Output_Channels)</td><td>양액 B 투입 Output 선택</td></tr><tr><td>Nutrient B Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>선택한 Output Channel의 output 타입을 선택하세요.</td></tr><tr><td>Nutrient B Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>Nutrient B 투입 펌프로 보낼 양(시간 또는 용량)</td></tr><tr><td>Output: EC Dose Nutrient C</td><td>Select Channel (Output_Channels)</td><td>양액 C 투입 Output 선택</td></tr><tr><td>Nutrient C Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>선택한 Output Channel의 output 타입을 선택하세요.</td></tr><tr><td>Nutrient C Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>Nutrient C 투입 펌프로 보낼 양(시간 또는 용량)</td></tr><tr><td>Output: EC Dose Nutrient D</td><td>Select Channel (Output_Channels)</td><td>양액 D 투입 Output 선택</td></tr><tr><td>Nutrient D Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>선택한 Output Channel의 output 타입을 선택하세요.</td></tr><tr><td>Nutrient D Output Amount</td><td>Decimal
- Default Value: 2.0</td><td>Nutrient D 투입 펌프로 보낼 양(시간 또는 용량)</td></tr><tr><td colspan="3">Setpoint Options</td></tr><tr><td>pH Setpoint</td><td>Decimal
- Default Value: 5.85</td><td>원하는 pH setpoint</td></tr><tr><td>pH Hysteresis</td><td>Decimal
- Default Value: 0.35</td><td>pH 범위 판정을 위한 히스테리시스</td></tr><tr><td>EC Setpoint</td><td>Decimal
- Default Value: 150.0</td><td>원하는 전기전도도 Setpoint</td></tr><tr><td>EC Hysteresis</td><td>Decimal
- Default Value: 50.0</td><td>EC 범위 판정을 위한 히스테리시스</td></tr><tr><td>pH Danger Range (High Value)</td><td>Decimal
- Default Value: 7.0</td><td>위험 범위의 고점 pH 값</td></tr><tr><td>pH Danger Range (Low Value)</td><td>Decimal
- Default Value: 5.0</td><td>위험 범위의 저점 pH 값</td></tr><tr><td colspan="3">Alert Notification Options</td></tr><tr><td>Notification E-Mail</td><td>텍스트</td><td>문제 발생 시 알릴 이메일(비활성화하려면 비워 두기)</td></tr><tr><td>E-Mail Timer Duration (Hours)</td><td>Decimal
- Default Value: 12.0</td><td>이메일 알림을 보내는 사이의 대기 시간</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Each e-mail notification timer can be manually reset before the expiration.</td></tr><tr><td>Reset EC E-mail Timer</td><td>Button</td><td></td></tr><tr><td>Reset pH E-mail Timer</td><td>Button</td><td></td></tr><tr><td>Reset Measurement Issue E-mail Timer</td><td>Button</td><td></td></tr><tr><td>Reset All E-Mail Timers</td><td>Button</td><td></td></tr><tr><td colspan="3">Each total duration and volume can be manually reset.</td></tr><tr><td>Reset All Totals</td><td>Button</td><td></td></tr><tr><td>Reset Total Raise pH Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total Lower pH Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total Raise pH Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total Lower pH Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC A Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC A Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC B Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC B Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC C Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC C Volume</td><td>Button</td><td></td></tr><tr><td>Reset Total EC D Duration</td><td>Button</td><td></td></tr><tr><td>Reset Total EC D Volume</td><td>Button</td><td></td></tr></tbody></table>

### 데이터 검증


이 기능 두 개의 측정값을 획득한 후 그 차이를 계산하며, 차이가 설정된 임계값보다 크지 않을 경우 측정값 A를 저장합니다. 이를 통해 한 센서의 측정값을 다른 센서의 측정값과 비교하여 검증할 수 있습니다. 두 센서의 측정값이 일치할 때만 측정값이 저장되므로, 저장된 측정값을 조건부 함수(Conditional Functions) 등에서 활용하여 측정값이 없는 경우 사용자에게 알림을 보내 센서에 문제가 있을 가능성을 알릴 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>측정값 A</td><td>Select Measurement (Input, Function)</td><td>측정값 A</td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>측정값 B</td><td>Select Measurement (Input, Function)</td><td>측정값 B</td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Maximum Difference</td><td>Decimal
- Default Value: 10.0</td><td>측정값 간 허용되는 최대 차이</td></tr><tr><td>Average Measurements</td><td>Boolean</td><td>측정값의 평균을 데이터베이스에 저장합니다.</td></tr></tbody></table>

### 뱅-뱅 히스테릭 (On/Off) (Raise/Lower/Both)


단순한 Bang-Bang 제어 방식으로, 하나의 입력값을 사용하여 하나 또는 두 개의 출력을 제어합니다.입력을 선택하고, 증가(Raise) 및/또는 감소(Lower) 출력을 설정한 후, **설정값(Setpoint)과 히스테리시스(Hysteresis: 작동 범위)를 입력하고 방향(Direction)을 선택하세요.    •	Raise 모드 (예: 난방): 입력값이 (설정값 - 히스테리시스) 이하일 때 출력이 켜짐, 입력값이 (설정값 + 히스테리시스) 이상일 때 출력이 꺼짐    •	Lower 모드 (예: 냉각): 위 동작과 반대로, 입력값을 낮추기 위해 출력을 켜려 함    •	Both: 입력값이 설정값을 유지하도록 Raise 및 Lower를 조정
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>선택한 output이 영향을 줄 measurement를 선택하세요.</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Output (Raise)</td><td>Select Device, Measurement, and Channel (Output)</td><td>측정값을 높일, 제어할 output을 선택하세요.</td></tr><tr><td>Output (Lower)</td><td>Select Device, Measurement, and Channel (Output)</td><td>측정값을 낮출, 제어할 output을 선택하세요.</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>원하는 setpoint</td></tr><tr><td>Hysteresis</td><td>Decimal
- Default Value: 1</td><td>제어 밴드를 정의하는 setpoint 위아래 범위</td></tr><tr><td>Direction</td><td>Select(Options: [Raise | Lower | <strong>Both</strong>] (Default in <strong>bold</strong>)</td><td>Raise는 제어가 켜졌을 때 측정값이 증가함을 의미합니다(가열). Lower는 출력이 켜졌을 때 측정값이 감소함을 의미합니다(냉각).</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 5</td><td>측정 또는 동작 사이의 간격</td></tr></tbody></table>

### 뱅-뱅 히스테릭 (PWM) (Raise/Lower/Both)


단순한 Bang-Bang 제어 방식으로, 하나의 입력값을 사용하여 하나의 PWM 출력을 제어합니다.입력을 선택하고, PWM 출력, 설정값(Setpoint) 및 **히스테리시스(Hysteresis)**를 입력한 후, 방향(Direction)을 선택하세요.	•	Raise 모드 (예: 난방): 입력값이 (설정값 - 히스테리시스) 이하일 때 출력이 켜짐, 입력값이 (설정값 + 히스테리시스) 이상일 때 출력이 꺼짐	•	Lower 모드 (예: 냉각): 위 동작과 반대로, 입력값을 낮추기 위해 출력을 켜려 함	•	Both 모드: 입력값이 설정값을 유지하도록 Raise 및 Lower를 조정주의: 이 출력은 PWM 출력(Pulse Width Modulation Output)에서만 작동합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>선택한 output이 영향을 줄 measurement를 선택하세요.</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Output</td><td>Select Device, Measurement, and Channel (Output)</td><td>측정에 영향을 줄, 제어할 output을 선택하세요.</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>원하는 setpoint</td></tr><tr><td>Hysteresis</td><td>Decimal
- Default Value: 1</td><td>제어 밴드를 정의하는 setpoint 위아래 범위</td></tr><tr><td>Direction</td><td>Select(Options: [Raise | Lower | <strong>Both</strong>] (Default in <strong>bold</strong>)</td><td>Raise는 제어가 켜졌을 때 측정값이 증가함을 의미합니다(가열). Lower는 출력이 켜졌을 때 측정값이 감소함을 의미합니다(냉각).</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 5</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Duty Cycle (increase)</td><td>Decimal
- Default Value: 90</td><td>Measurement를 높일 duty cycle</td></tr><tr><td>Duty Cycle (maintain)</td><td>Decimal
- Default Value: 55</td><td>Measurement를 유지할 duty cycle</td></tr><tr><td>Duty Cycle (decrease)</td><td>Decimal
- Default Value: 20</td><td>Measurement를 낮출 duty cycle</td></tr><tr><td>Duty Cycle (shutdown)</td><td>Decimal</td><td>Function 종료 시 설정할 duty cycle</td></tr></tbody></table>

### 뱅-뱅 히스테릭(On/Off) (Raise/Lower)


단순한 Bang-Bang 제어 방식으로, 하나의 입력값을 사용하여 하나의 출력을 제어합니다.입력을 선택하고, **출력, 설정값(Setpoint), 히스테리시스(Hysteresis)**를 입력한 후, 방향(Direction)을 선택하세요.	•	Raise 모드 (예: 난방): 입력값이 (설정값 - 히스테리시스) 이하일 때 출력이 켜지고, 입력값이 (설정값 + 히스테리시스) 이상일 때 출력이 꺼집니다.	•	Lower 모드 (예: 냉각): 위 동작과 반대로, 입력값을 낮추기 위해 출력을 켜려 합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>선택한 output이 영향을 줄 measurement를 선택하세요.</td></tr><tr><td>Measurement: Max Age (Seconds)</td><td>Text
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Output</td><td>Select Device, Measurement, and Channel (Output)</td><td>측정에 영향을 줄, 제어할 output을 선택하세요.</td></tr><tr><td>Setpoint</td><td>Decimal
- Default Value: 50</td><td>원하는 setpoint</td></tr><tr><td>Hysteresis</td><td>Decimal
- Default Value: 1</td><td>제어 밴드를 정의하는 setpoint 위아래 범위</td></tr><tr><td>Direction</td><td>Select(Options: [<strong>Raise</strong> | Lower] (Default in <strong>bold</strong>)</td><td>Raise는 제어가 켜졌을 때 측정값이 증가함을 의미합니다(가열). Lower는 출력이 켜졌을 때 측정값이 감소함을 의미합니다(냉각).</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 5</td><td>측정 또는 동작 사이의 간격</td></tr></tbody></table>

### 예비 센서 데이터


이 기능은 가장 먼저 사용 가능한 측정값을 저장합니다. 여러 개의 센서를 백업 용도로 설정하고자 할 때 유용합니다. 센서를 중요도 순으로 설정하면, 이 기능은 첫 번째 측정값부터 확인하여 존재 여부를 검사하고, 없을 경우 다음 측정값을 확인하는 과정을 반복합니다. 측정값을 찾으면 사용자 지정 측정값과 단위로 데이터베이스에 저장됩니다. 이 기능의 출력은 AoT 전체에서 입력으로 사용할 수 있습니다. 3개 이상의 측정값을 확인해야 하는 경우, 첫 번째 기능의 출력을 두 번째 기능의 입력으로 설정하여 여러 개의 중복 기능을 연쇄적으로 구성할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>측정값 A</td><td>Select Measurement (Input, Function)</td><td>a를 대체할 Measurement</td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>측정값 B</td><td>Select Measurement (Input, Function)</td><td>b를 대체할 Measurement</td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement C</td><td>Select Measurement (Input, Function)</td><td>C를 대체할 Measurement</td></tr><tr><td>Measurement C: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr></tbody></table>

### 원격 백업 (rsync)

- Dependencies: [rsync](https://packages.debian.org/search?keywords=rsync)

이 함수는 rsync를 사용하여 현재 시스템의 데이터를 원격 시스템에 백업합니다. 원격 시스템에는 SSH 서버가 실행 중이어야 하며, rsync가 설치되어 있어야 합니다. 또한, 이 시스템에도 rsync가 설치되어 있어야 하며, SSH 키 파일을 통해 비밀번호 없이 원격 시스템에 접근할 수 있어야 합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 1296000</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 300</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Local User</td><td>Text
- Default Value: pi</td><td>이 시스템에서 rsync를 실행할 사용자</td></tr><tr><td>Remote User</td><td>Text
- Default Value: pi</td><td>원격 호스트 로그인 사용자</td></tr><tr><td>Remote Host</td><td>Text
- Default Value: 192.168.0.50</td><td>백업을 전송할 IP 또는 호스트 주소</td></tr><tr><td>Remote Backup Path</td><td>Text
- Default Value: /home/pi/backup_aot</td><td>원격 호스트의 백업 대상 경로</td></tr><tr><td>Rsync Timeout (Seconds)</td><td>Integer
- Default Value: 3600</td><td>rsync 완료 허용 시간</td></tr><tr><td>Local Backup Path</td><td>텍스트</td><td>백업할 로컬 경로 (비우면 비활성화)</td></tr><tr><td>Backup Settings Export File</td><td>Boolean
- Default Value: True</td><td>내보낸 설정 파일 생성 및 백업</td></tr><tr><td>Remove Local Settings Backups</td><td>Boolean</td><td>원격 호스트로 전송 성공 후 로컬 설정 백업을 삭제합니다.</td></tr><tr><td>Backup Measurements</td><td>Boolean
- Default Value: True</td><td>모든 influxdb measurement 백업</td></tr><tr><td>Remove Local Measurements Backups</td><td>Boolean</td><td>원격 호스트로 전송 성공 후 로컬 측정 백업을 삭제합니다.</td></tr><tr><td>Backup Camera Directories</td><td>Boolean
- Default Value: True</td><td>모든 카메라 디렉터리 백업</td></tr><tr><td>Remove Local Camera Images</td><td>Boolean</td><td>원격 호스트로 전송 성공 후 로컬 카메라 이미지를 삭제합니다.</td></tr><tr><td>SSH Port</td><td>Integer
- Default Value: 22</td><td>비표준 SSH 포트 지정</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Backup of settings are only created if the AoT version or database versions change. This is due to this Function running periodically- if it created a new backup every Period, there would soon be many identical backups. Therefore, if you want to induce the backup of settings, measurements, or camera directories and sync them to your remote system, use the buttons below.</td></tr><tr><td>Backup Settings Now</td><td>Button</td><td></td></tr><tr><td>Backup Measurements Now</td><td>Button</td><td></td></tr><tr><td>Backup Camera Directories Now</td><td>Button</td><td></td></tr></tbody></table>

### 차이 측정


이 함수는 두 개의 측정값을 가져와 차이를 계산한 후, 결과값을 선택된 측정값과 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Measurement: A</td><td>Select Measurement (Input, Function)</td><td></td></tr><tr><td>Measurement A: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement: B</td><td>Select Measurement (Input, Function)</td><td></td></tr><tr><td>Measurement B: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Reverse Order</td><td>Boolean</td><td>계산 순서 반전</td></tr><tr><td>Absolute Difference</td><td>Boolean</td><td>차이의 절댓값 반환</td></tr></tbody></table>

### 통계 (Last, Multiple)


이 기능은 여러 개의 측정값을 가져와 통계를 계산한 후, 결과값을 선택된 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement</td></td><td>Measurements to perform statistics on</td></tr><tr><td>Halt on Missing Measurement</td><td>Boolean</td><td>Max Age 내에 측정값이 1개 이상 없으면 통계를 계산하지 않습니다.</td></tr></tbody></table>

### 통계 (Past, Single)


이 기능은 하나의 측정값에서 여러 개의 값을 가져와 통계를 계산한 후, 결과값을 선택된 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Measurements Enabled</td><td>Multi-Select</td><td>기록할 Measurement</td></tr><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>통계를 낼 Measurement</td></tr></tbody></table>

### 평균 (Last, Multiple)


이 함수는 선택된 측정값 중 마지막 측정값을 가져와 평균을 낸 후,결과값을 선택된 측정값과 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement</td></td><td>수식의 "x"를 대체할 Measurement</td></tr></tbody></table>

### 평균 (Past, Single)


이 함수는 선택된 측정값의 과거 측정값(Max Age 내)을 가져와 평균을 계산한 후, 결과값을 해당 측정값과 단위로 저장합니다.참고: InfluxDB 1.8.10에는 mean() 함수가 올바르게 작동하지 않는 버그가 있습니다.따라서 InfluxDB v1.x를 사용하는 경우 median() 함수가 대신 사용됩니다.InfluxDB 2.x에서는 이 문제가 발생하지 않으며, mean() 함수를 정상적으로 사용할 수 있습니다.정확한 평균값을 얻으려면 InfluxDB 2.x로 업그레이드하세요.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>수식의 "x"를 대체할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr></tbody></table>

### 포화수증기압차(AVPD)


이 기능은 잎의 온도 및 습도를 사용하여 포화수증기압차(AVPD)를 계산합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Temperature</td><td>Select Measurement (Input, Function)</td><td>온도 Measurement</td></tr><tr><td>Temperature: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Humidity</td><td>Select Measurement (Input, Function)</td><td>습도 Measurement</td></tr><tr><td>Humidity: Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr></tbody></table>

### 합계 (Last, Multiple)


이 기능은 선택된 측정값 중 마지막 값을 가져와 합산한 후, 결과값을 선택된 측정값과 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr><tr><td>Measurement</td></td><td>수식의 "x"를 대체할 Measurement</td></tr></tbody></table>

### 합계 (Past, Single)


이 기능은 선택된 측정값의 과거 측정값(Max Age 내)을 가져와 합산한 후, 결과값을 선택된 측정값과 단위로 저장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Period (Seconds)</td><td>Text
- Default Value: 60</td><td>측정 또는 동작 사이의 간격</td></tr><tr><td>Start Offset (Seconds)</td><td>Integer
- Default Value: 10</td><td>첫 동작 전 대기할 시간</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output)</td><td>수식의 "x"를 대체할 Measurement</td></tr><tr><td>Max Age (Seconds)</td><td>Integer
- Default Value: 360</td><td>사용할 측정값의 최대 경과 시간</td></tr></tbody></table>

