## Built-In Functions

### AoT VPD


この関数は、葉温と湿度に基づいて飽差(VPD)を計算します。葉温が入力されていない場合は、代わりに気温にオフセットを適用します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (秒)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔</td></tr><tr><td>開始オフセット (秒)</td><td>Integer
- Default Value: 10</td><td>最初のアクション実行前の待機時間</td></tr><tr><td>気温</td><td>Select Measurement (Input, Function)</td><td>気温測定</td></tr><tr><td>気温: 最大経過時間 (秒)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>湿度</td><td>Select Measurement (Input, Function)</td><td>湿度測定</td></tr><tr><td>湿度: 最大経過時間 (秒)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>葉温</td><td>Select Measurement (Input, Function)</td><td>葉温測定</td></tr><tr><td>葉温: 最大経過時間 (秒)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>葉温オフセット(°C)</td><td>Decimal
- Default Value: -1.5</td><td>葉温が入力されていない場合に適用するオフセット(°C)</td></tr></tbody></table>

### AoT平均(Last, Multiple)


この関数は、選択された測定値の最新データを読み取り、算術平均を計算して、指定した測定値/単位で結果を保存します。集計する入力測定値は、下部の[アクション]リストで「AoT Average: Input Measurement」アクションを追加して登録してください。保存されるのは平均値のみで、元の値は個別には保存されません。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (秒)</td><td>Text
- Default Value: 60</td><td>測定と計算の間隔(秒)</td></tr><tr><td>開始オフセット (秒)</td><td>Integer
- Default Value: 10</td><td>最初の測定前の待機時間(秒)</td></tr><tr><td>最大経過時間 (秒)</td><td>Integer
- Default Value: 360</td><td>デフォルトの最大有効期間(秒)。個別の入力アクションで別途設定されている場合は、そちらの値が優先されます。</td></tr><tr><td>デバッグロギングを有効化</td><td>Boolean</td><td>周期ごとに計算された平均値をログに記録します。運用環境ではオフのままにしてください。</td></tr></tbody></table>

### Display: Generic LCD 16x2 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

この機能は、I2C経由で16x2 LCDディスプレイに出力を提供します。このディスプレイは一度に2行表示できるため、ライン セット数(Number of Line Sets)を変更するたびに2チャンネルずつ追加されます。LCDは設定された周期(Period)ごとに更新され、次のラインセットが表示されます。したがって、最初に表示される2行はチャンネル0と1、続いて2と3、次に4と5という順に表示されます。すべてのチャンネルが表示された後は、最初に戻って繰り返します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x20</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr><tr><td>Backlight Flashing On</td><td>Button</td><td></td></tr><tr><td>Backlight Flashing Off</td><td>Button</td><td></td></tr></tbody></table>

### Display: Generic LCD 20x4 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

この機能は、I2C経由で20x4 LCDディスプレイに出力を提供します。このディスプレイは一度に4行表示できるため、ライン セット数(Number of Line Sets)を変更するたびに4チャンネルずつ追加されます。LCDは設定された周期(Period)ごとに更新され、次のラインセットが表示されます。したがって、最初に表示される4行はチャンネル0、1、2、3、続いて4、5、6、7、次に8、9、10、11という順に表示されます。すべてのチャンネルが表示された後は、最初に戻って繰り返します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x20</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr></tbody></table>

### Display: Grove LCD 16x2 (I2C)

- Dependencies: [smbus2](https://pypi.org/project/smbus2)

この機能は、I2C経由でGrove 16x2 LCDディスプレイに出力を提供します。このディスプレイは一度に2行表示できるため、ライン セット数(Number of Line Sets)を変更するたびに2チャンネルずつ追加されます。LCDは設定された周期(Period)ごとに更新され、次のラインセットが表示されます。したがって、最初に表示される2行はチャンネル0と1、続いてチャンネル2と3、次にチャンネル4と5という順に表示されます。すべてのチャンネルが表示された後は、最初に戻って繰り返します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x3e</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Backlight I2C Address</td><td>Text
- Default Value: 0x62</td><td>I2C address to control the backlight</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Backlight Red (0 - 255)</td><td>Integer
- Default Value: 255</td><td>Set the red color value of the backlight on startup.</td></tr><tr><td>Backlight Green (0 - 255)</td><td>Integer
- Default Value: 255</td><td>Set the green color value of the backlight on startup.</td></tr><tr><td>Backlight Blue (0 - 255)</td><td>Integer
- Default Value: 255</td><td>Set the blue color value of the backlight on startup.</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Backlight On</td><td>Button</td><td></td></tr><tr><td>Backlight Off</td><td>Button</td><td></td></tr><tr><td>Color (RGB)</td><td>Text
- Default Value: 255,0,0</td><td>Color as R,G,B values (e.g. "255,0,0" without quotes)</td></tr><tr><td>Set Backlight Color</td><td>Button</td><td></td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [2 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

この機能は、I2C経由で128x32 SSD1306 OLEDディスプレイに出力を提供します。このディスプレイ機能は一度に2行表示できるため、ライン セット数(Number of Line Sets)を変更するたびに2チャンネルずつ追加されます。LCDは設定された周期(Period)ごとに更新され、次のラインセットが表示されます。したがって、最初に表示されるラインセットはチャンネル0-1、続いて2-3、次に4-5という順に表示されます。すべてのチャンネルが表示された後は、最初に戻って繰り返します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [2 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x32 SSD1306 OLED display via SPI. This display Function will show 2 lines at a time, so channels are added in sets of 2 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 1, then 2 - 3, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [4 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

この機能は、I2C経由で128x32 SSD1306 OLEDディスプレイに出力を提供します。このディスプレイ機能は一度に4行表示できるため、ライン セット数(Number of Line Sets)を変更するたびに4チャンネルずつ追加されます。LCDは設定された周期(Period)ごとに更新され、次のラインセットが表示されます。したがって、最初に表示されるラインセットはチャンネル0-3、続いて4-7、次に8-11という順に表示されます。すべてのチャンネルが表示された後は、最初に戻って繰り返します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x32 [4 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x32 SSD1306 OLED display via SPI. This display Function will show 4 lines at a time, so channels are added in sets of 4 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 3, then 4 - 7, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [4 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via I2C. This display Function will show 4 lines at a time, so channels are added in sets of 4 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 3, then 4 - 7, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [4 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via SPI. This display Function will show 4 lines at a time, so channels are added in sets of 4 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 3, then 4 - 7, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 17</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 12</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [8 Lines] (I2C)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via I2C. This display Function will show 8 lines at a time, so channels are added in sets of 8 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 7, then 8 - 15, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1306 OLED 128x64 [8 Lines] (SPI)

- Dependencies: [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [Pillow](https://pypi.org/project/Pillow), [pyusb](https://pypi.org/project/pyusb), [Adafruit-GPIO](https://pypi.org/project/Adafruit-GPIO), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-framebuf](https://pypi.org/project/adafruit-circuitpython-framebuf), [adafruit-circuitpython-ssd1306](https://pypi.org/project/adafruit-circuitpython-ssd1306)

This Function outputs to a 128x64 SSD1306 OLED display via SPI. This display Function will show 8 lines at a time, so channels are added in sets of 8 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 7, then 8 - 15, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>SPI Device</td><td>Integer</td><td>The SPI device</td></tr><tr><td>SPI Bus</td><td>Integer</td><td>The SPI bus</td></tr><tr><td>DC Pin</td><td>Integer
- Default Value: 16</td><td>The pin (BCM numbering) connected to DC of the display</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 19</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td>CS Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to CS of the display</td></tr><tr><td>Characters Per Line</td><td>Integer
- Default Value: 21</td><td>The maximum number of characters to display per line</td></tr><tr><td>Use Non-Default Font</td><td>Boolean</td><td>Don't use the default font. Enable to specify the path to a font to use.</td></tr><tr><td>Non-Default Font Path</td><td>Text
- Default Value: /usr/share/fonts/truetype/dejavu//DejaVuSans.ttf</td><td>The path to the non-default font to use</td></tr><tr><td>Font Size (pt)</td><td>Integer
- Default Value: 10</td><td>The size of the font, in points</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Display: SSD1309 OLED 128x64 [8 Lines] (I2C)

- Dependencies: [pyusb](https://pypi.org/project/pyusb), [luma.oled](https://pypi.org/project/luma.oled), [Pillow](https://pypi.org/project/Pillow), [libjpeg-dev](https://packages.debian.org/search?keywords=libjpeg-dev), [zlib1g-dev](https://packages.debian.org/search?keywords=zlib1g-dev), [libfreetype6-dev](https://packages.debian.org/search?keywords=libfreetype6-dev), [liblcms2-dev](https://packages.debian.org/search?keywords=liblcms2-dev), [libopenjp2-7](https://packages.debian.org/search?keywords=libopenjp2-7), [libtiff5](https://packages.debian.org/search?keywords=libtiff5)

This Function outputs to a 128x64 SSD1309 OLED display via I2C. This display Function will show 8 lines at a time, so channels are added in sets of 8 when Number of Line Sets is modified. Every Period, the LCD will refresh and display the next set of lines. Therefore, the first set of lines that are displayed are channels 0 - 7, then 8 - 15, and so on. After all channels have been displayed, it will cycle back to the beginning.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 10</td><td>測定またはアクションの間隔時間</td></tr><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x3c</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>Number of Line Sets</td><td>Integer
- Default Value: 1</td><td>How many sets of lines to cycle on the LCD</td></tr><tr><td>Reset Pin</td><td>Integer
- Default Value: 17</td><td>The pin (BCM numbering) connected to RST of the display</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>Line Display Type</td><td>Select</td><td>What to display on the line</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output, PID)</td><td>Measurement to display on the line</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement Label</td><td>Text</td><td>Set to overwrite the default measurement label</td></tr><tr><td>Measurement Decimal</td><td>Integer
- Default Value: 1</td><td>The number of digits after the decimal</td></tr><tr><td>テキスト</td><td>Text
- Default Value: Text</td><td>Text to display</td></tr><tr><td>Display Unit</td><td>Boolean
- Default Value: True</td><td>Display the measurement unit (if available)</td></tr></tbody></table>

### Equation (Multi-Measure)


この機能は2つの測定値を取得し、ユーザー定義の数式に適用した後、その結果を選択した測定値と単位で保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>測定: A</td><td>Select Measurement (Input, Output, Function)</td><td>Measurement to replace a</td></tr><tr><td>測定 A: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>測定: B</td><td>Select Measurement (Input, Output, Function)</td><td>Measurement to replace b</td></tr><tr><td>測定 B: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>方程式</td><td>Text
- Default Value: a*(2+b)</td><td>Equation using measurements a and b</td></tr></tbody></table>

### Example: Generic

- Dependencies: [build-essential](https://packages.debian.org/search?keywords=build-essential)

この機能モジュールは、さまざまなUIオプションの種類を示すサンプルです。新しいカスタム機能モジュールの開発方法を学習する目的にのみ使用されるもので、それ以外の実用的な用途はありません。このメッセージは機能オプションの上に表示されます。この機能は最後に選択された測定値を取得し、選択した出力を15秒間オンにした後、無効化します。コードを分析して独自の機能モジュールを開発し、機能インポート(Function Import)ページからインポートできるように設定してください。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td colspan="3">The following fields are for text, integers, and decimal inputs. This message will automatically create a new line for the options that come after it. Alternatively, a new line can be created instead without a message, which are what separates each of the following three inputs.</td></tr><tr><td>Text Input</td><td>Text
- Default Value: Text_1</td><td>Type in text</td></tr><tr><td>Integer Input</td><td>Integer
- Default Value: 100</td><td>Type in an Integer</td></tr><tr><td>Devimal Input</td><td>Decimal
- Default Value: 50.2</td><td>Type in a decimal value</td></tr><tr><td colspan="3">A boolean value can be made using a checkbox.</td></tr><tr><td>Boolean Value</td><td>Boolean
- Default Value: True</td><td>Set to either True (checked) or False (Unchecked)</td></tr><tr><td colspan="3">A dropdown selection can be made of any user-defined options, with any of the options selected by default when the Function is added by the user.</td></tr><tr><td>Select Option</td><td>Select(Options: [First Option Selected | <strong>Second Option Selected</strong> | Third Option Selected] (Default in <strong>bold</strong>)</td><td>Select an option from the dropdown</td></tr><tr><td colspan="3">A specific measurement from an Input, Function, or PID Controller can be selected. The following dropdown will be populated if at least one Input, Function, or PID Controller has been created (as long as the Function has measurements, e.g. Statistics Function).</td></tr><tr><td>Controller Measurement</td><td>Select Measurement (Input, Function, PID)</td><td>Select a controller Measurement</td></tr><tr><td colspan="3">An output channel measurement can be selected that will return the Output ID, Channel ID, and Measurement ID. This is useful if you need more than just the Output and Channel IDs and require the user to select the specific Measurement of a channel.</td></tr><tr><td>Output Channel Measurement</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output channel and measurement </td></tr><tr><td colspan="3">An output can be selected that will return the Output ID if only the output ID is needed.</td></tr><tr><td>Output Device</td><td>Select Device</td><td>Select an Output device</td></tr><tr><td colspan="3">An Input, Output, Function, PID, or Trigger can be selected that will return the ID if only the controller ID is needed (e.g. for activating/deactivating a controller)</td></tr><tr><td>Controller Device</td><td>Select Device</td><td>Select an Input/Output/Function/PID/Trigger controller</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Button One will pass the Button One Value to the button_one() function of this module. This allows functions to be executed with user-specified inputs. These can be text, integers, decimals, or boolean values.</td></tr><tr><td>Button One Value</td><td>Integer
- Default Value: 650</td><td>Value for button one.</td></tr><tr><td>Button One</td><td>Button</td><td></td></tr><tr><td colspan="3">Here is another action with another user input that will be passed to the function. Note that Button One Value will also be passed to this second function, so be sure to use unique ids for each input.</td></tr><tr><td>Button Two Value</td><td>Integer
- Default Value: 1500</td><td>Value for button two.</td></tr><tr><td>Button Two</td><td>Button</td><td></td></tr></tbody></table>

### LoRaWAN モード/周期マネージャー (RAK3172E)


バッテリー・時間帯・バルブ動作・リンク品質に基づいてClass/ハートビート周期を決定します。ChirpStack gRPC(DeviceService.Enqueue)を通じて直接ダウンリンクをキューイングします。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>デバイスの役割</td><td>Select(Options: [<strong>コントローラー (バルブ/アクチュエーター) — Class C優先</strong> | センサー — Class A、低消費電力 (ゲートウェイGPS不要) | ハイブリッド — 手動設定] (Default in <strong>bold</strong>)</td><td>コントローラー: 稼働時間中はClass C、夜間はClass B。センサー: 常時Class A(ゲートウェイGPS不要)、夜間はHBを延長。ハイブリッド: 以下の設定をそのまま適用します。</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>判定および適用周期 (秒)</td></tr><tr><td colspan="3"><b>サーバー接続</b></td></tr><tr><td>ChirpStack gRPC サーバー</td><td>Text
- Default Value: 127.0.0.1:8080</td><td>host:port形式 (例: 127.0.0.1:8080) またはhttp(s)://host:port</td></tr><tr><td>API Key</td><td>Text</td><td>JWTトークンの値を入力してください (「Bearer」は除く)</td></tr><tr><td>DevEUI</td><td>Text</td><td>16桁の16進数DevEUI (区切り文字使用可)</td></tr><tr><td colspan="3"><b>測定入力</b></td></tr><tr><td>ChirpStack REST Port</td><td>Integer
- Default Value: 8090</td><td>ChirpStack REST APIポート (デフォルト8090)</td></tr><tr><td>測定: 最大経過時間 (Seconds)</td><td>Text
- Default Value: 4000</td><td>ChirpStackのメトリクス履歴をさかのぼって参照する範囲(秒)</td></tr><tr><td>再試行間隔 (分)</td><td>Decimal</td><td>ACKがない場合に同じモードを再適用する間隔(0で再試行を無効化)</td></tr><tr><td>LoRaクラスポリシー</td><td>Select(Options: [<strong>自動</strong> | CLASS-A | CLASS-B | CLASS-C] (Default in <strong>bold</strong>)</td><td>自動モードのときのみモードに応じてClassが切り替わります。特定のクラスを選択した場合は、そのクラスが維持されます。</td></tr><tr><td>入力値が有効な場合のみモードを切り替える</td><td>Boolean</td><td>入力条件/測定値が有効な場合のみモードを適用します</td></tr><tr><td colspan="3"><b>稼働時間帯</b><br/><small>パフォーマンスモードで動作する時間を設定します。0〜24を入力するか、開始時刻と終了時刻を同じにすると24時間になります。</small></td></tr><tr><td>運用時間の基準</td><td>Select(Options: [<strong>固定時刻 — 下の開始・終了時刻</strong> | 日の出〜日の入り — この位置の季節に追従] (Default in <strong>bold</strong>)</td><td>固定時刻は一年中同じ時刻を使います。日の出〜日の入り基準はこの装置がある場所の昼の長さに追従するため、毎月時刻を入力し直さなくても性能モードが季節に追従します。位置は地図から継承し、位置を解決できない場合は下の固定時刻を代わりに使用します。</td></tr><tr><td>日の出オフセット (分)</td><td>Integer</td><td>運用区間の開始を日の出を基準にずらします。負の値でより早く始まります(-30 なら日の出の30分前から)。基準が日の出〜日の入りのときのみ使用されます。</td></tr><tr><td>日の入りオフセット (分)</td><td>Integer</td><td>運用区間の終了を日の入りを基準にずらします。正の値でより遅く終わります(30 なら日の入り後30分まで性能モードを維持)。基準が日の出〜日の入りのときのみ使用されます。</td></tr><tr><td>パフォーマンスモード開始 (時)</td><td>Integer
- Default Value: 4</td><td>パフォーマンスモード開始時刻 (0–23)</td></tr><tr><td>パフォーマンスモード終了 (時)</td><td>Integer
- Default Value: 18</td><td>パフォーマンスモード終了時刻 (0–23)</td></tr><tr><td>パフォーマンスモード先行(分)</td><td>Integer
- Default Value: 10</td><td>日中開始のどれくらい前にパフォーマンス(Class C)モードへ切り替えるかを分単位で指定します。</td></tr><tr><td colspan="3"><b>モード別HB周期</b><br/><small>モードごとのハートビート周期を設定します。</small></td></tr><tr><td>パフォーマンスモードクラス</td><td>Select(Options: [Class A | Class B | <strong>Class C</strong>] (Default in <strong>bold</strong>)</td><td>パフォーマンス(C)ポリシー時にファームウェアへ適用するLoRaクラス</td></tr><tr><td>省電力モードクラス</td><td>Select(Options: [Class A | <strong>Class B</strong> | Class C] (Default in <strong>bold</strong>)</td><td>省電力(B)ポリシー時にファームウェアへ適用するLoRaクラス</td></tr><tr><td>超省電力モードクラス</td><td>Select(Options: [Class A | <strong>Class B</strong> | Class C] (Default in <strong>bold</strong>)</td><td>超省電力(A)ポリシー時にファームウェアへ適用するLoRaクラス</td></tr><tr><td>パフォーマンスハートビート(分)</td><td>Integer
- Default Value: 30</td><td>パフォーマンス(C)モードのハートビート周期(分)</td></tr><tr><td>省電力ハートビート(分)</td><td>Integer
- Default Value: 30</td><td>省電力(B)モードのハートビート周期(分)</td></tr><tr><td>超省電力ハートビート(分)</td><td>Integer
- Default Value: 60</td><td>超省電力(A)モードのハートビート周期(分)</td></tr><tr><td colspan="3"><b>しきい値オプション</b><br/><small>モード切替のしきい値を設定します。初期値は4Sリン酸鉄(公称12.8V)を前提としています。12V鉛蓄電池の場合は 12.00 / 11.70 / 11.40 に変更してください — 二つの化学は電圧曲線が全く異なります。</small></td></tr><tr><td>バッテリー管理</td><td>Boolean</td><td>バッテリー電圧に応じてモードを自動的に切り替えます。(LoRaクラスポリシーが自動の場合のみ動作)</td></tr><tr><td>パフォーマンスモードしきい値(V)</td><td>Decimal
- Default Value: 13.2</td><td>安定運用が可能な電圧しきい値 (4Sリン酸鉄: 13.20V ≈ 70%、鉛蓄電池12V: 12.00V)</td></tr><tr><td>省電力しきい値(V)</td><td>Decimal
- Default Value: 13.0</td><td>省電力モードに切り替える電圧しきい値 (4Sリン酸鉄: 13.00V ≈ 25%、鉛蓄電池12V: 11.70V)</td></tr><tr><td>超省電力しきい値(V)</td><td>Decimal
- Default Value: 12.8</td><td>超省電力モードに切り替える電圧しきい値 (4Sリン酸鉄: 12.80V ≈ 10%、ニー以下、鉛蓄電池12V: 11.40V)</td></tr><tr><td>バッテリー未検出時はモード適用を停止</td><td>Boolean
- Default Value: True</td><td>バッテリー測定値がない、または古すぎる場合、モード/周期の変更を保留します。</td></tr><tr><td>リンクRSSI最小値(dBm)</td><td>Integer
- Default Value: -110</td><td>この値以上であればリンクは良好とみなされます</td></tr><tr><td>リンクSNR最小値(dB)</td><td>Integer
- Default Value: -10</td><td>この値以上であればリンクは良好とみなされます</td></tr><tr><td>バルブ作動しきい値(mA)</td><td>Decimal
- Default Value: 50.0</td><td>バッテリー電流がこの値を超えると、バルブが作動中とみなされ、デバイスはパフォーマンスモードを維持します。0にするとこのチェックを無効化します。</td></tr><tr><td>デバッグロギングを有効化</td><td>Boolean</td><td>モード/周期に変更がない場合に「適用なし」通知をログに記録します。運用環境ではオフにしてください。</td></tr></tbody></table>

### LoRaWANクラススケジューラー(サイトごと)


LoRaWANクラスを管理するサイト単位の単一の管理機能です。環境データに基づいてClass C(アクティブ/無線制御)とClass A(休止/低電力)を判定し、共有ChirpStackデバイスプロファイルを切り替え、各デバイスにファームウェアのHBモードをブロードキャストします。デバイスごとのRSSI/SNR/バッテリー情報を保存し、手動での上書きにも対応します。デバイスごとのLoRaWANモードマネージャーを置き換えるものです。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>評価周期 (Seconds)</td><td>Text
- Default Value: 600</td><tr><td>入力の最大有効時間 (秒)</td><td>Text
- Default Value: 4000</td><tr><td>ChirpStack</td></td><tr><td>RESTポート</td><td>Integer
- Default Value: 8090</td><td>サーバー/トークンは設定 -> ChirpStackから取得され、デバイスもそちらで割り当てます(「管理元」)。</td></tr><tr><td>制御モード</td></td><tr><td>制御モード</td><td>Select(Options: [<strong>自動 - 環境スコアに基づく</strong> | 手動 - 固定の日次Cウィンドウ] (Default in <strong>bold</strong>)</td><tr><td>手動C開始 (HH:MM)</td><td>Text
- Default Value: 05:00</td><tr><td>手動C失効 (HH:MM)</td><td>Text
- Default Value: 17:00</td><tr><td>環境入力 (AUTOモードのフォールバック)</td></td><tr><td>日射量 (W/m2)</td><td>Select Measurement (Input, Function)</td><td>光は光合成を左右します。日射量の測定値を選択してください(スキップする場合は空欄のままにしてください)。</td></tr><tr><td>土壌水分 (%)</td><td>Select Measurement (Input, Function)</td><td>土壌が湿っている場合は灌水は不要です。</td></tr><tr><td>現在の降雨量 (mm/h)</td><td>Select Measurement (Input, Function)</td><td>現在降雨中。</td></tr><tr><td>累積降雨量 (mm)</td><td>Select Measurement (Input, Function)</td><td>最近の累積降雨 -> 土壌飽和。</td></tr><tr><td>判定</td></td><tr><td>スコア >= -> ACTIVE</td><td>Decimal
- Default Value: 0.55</td><tr><td>スコア < -> REST</td><td>Decimal
- Default Value: 0.4</td><tr><td>最小滞留時間 (分)</td><td>Integer
- Default Value: 15</td><tr><td>クラス / HB 周期</td></td><tr><td>ACTIVE時のClass C HB (分)</td><td>Integer
- Default Value: 10</td><tr><td>REST時のClass A HB (分)</td><td>Integer
- Default Value: 30</td><tr><td>冬季のClass A HB (分)</td><td>Integer
- Default Value: 60</td><tr><td>冬季 (強制REST)</td></td><tr><td>冬季開始 (MM-DD)</td><td>Text
- Default Value: 12-01</td><tr><td>冬季終了 (MM-DD)</td><td>Text
- Default Value: 02-28</td><tr><td>バッテリー管理</td></td><tr><td>バッテリー種別</td><td>Select(Options: [<strong>未設定（バッテリー基準なし）</strong> | 鉛蓄電池  (低下 < 11.7 V / 危険 < 11.4 V) | LiFePO4    (低下 < 12.8 V / 危険 < 12.0 V)] (Default in <strong>bold</strong>)</td><td>ChirpStackのメトリクスからbattery_Vを読み取ります(INA219の配線が必要)。低下時: 手動オーバーライドが有効でない限りRESTを強制します。危険時: 無条件でRESTを強制し、バルブ開放インターロックも引き続き適用されます。</td></tr><tr><td>バッテリー低下時のHB (分)</td><td>Integer
- Default Value: 60</td><td>バッテリーが低下または危険な状態のときに適用されるハートビート周期(分)です。スリープ時間を最大化するには、REST HB以上に設定してください。</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3"><b>手動上書き</b></td></tr><tr><td>強制アクティブ時間(分)(0 = 有効期限まで)</td><td>Integer</td><tr><td>今すぐ強制アクティブ化 (Class C)</td><td>Button</td><td></td></tr><tr><td>上書きを解除</td><td>Button</td><td></td></tr></tbody></table>

### Neokey 4x1 Neopixel Keyboard (Execute Actions)

- Dependencies: [pyusb](https://pypi.org/project/pyusb), [Adafruit-extended-bus](https://pypi.org/project/Adafruit-extended-bus), [adafruit-circuitpython-neokey](https://pypi.org/project/adafruit-circuitpython-neokey)

この機能は、キーが押されたときに特定のアクションを実行します。このモジュールの下部にアクションを追加した後、各キーに対して1つ以上の短いアクションIDをカンマ区切りで入力してください。アクションIDは各アクションの横に表示されます(例:「[Action 0559689e] Controller: Activate」の場合、アクションIDは0559689eです)。複数のアクションIDを入力する場合は、カンマで区切ってください(例:「asdf1234」または「asdf1234,qwer5678,zxcv0987」)。アクションは入力された文字列の順序で実行されます。キーが押されたときに実行するアクションIDを入力してください。トグルアクションを有効にすると、キーを押すたびに交互に、トグルされたアクションIDに記載されたアクションが実行されます。キーが押される前、押された後、そして最後のアクションが実行されている間のLEDの色を設定できます。色は0~255の範囲の値を持つRGB文字列です。例えば、赤は「255, 0, 0」、青は「0, 0, 255」と入力します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>I2Cアドレス</td><td>Text
- Default Value: 0x30</td><td></td></tr><tr><td>I2Cバス</td><td>Integer
- Default Value: 1</td><td></td></tr><tr><td>LED Brightness (0.0-1.0)</td><td>Decimal
- Default Value: 0.2</td><td>The brightness of the LEDs</td></tr><tr><td>LED Flash Period (Seconds)</td><td>Text
- Default Value: 1.0</td><td>Set the period if the LED begins flashing</td></tr><tr><td colspan="3">Channel Options</td></tr><tr><td>名前</td><td>Text</td><td>他と区別するための名前</td></tr><tr><td>LED Delay (Seconds)</td><td>Text
- Default Value: 1.5</td><td>How long to leave the LED on after the last action executes.</td></tr><tr><td>Action ID(s)</td><td>Text</td><td>Set which action(s) execute when the key is pressed. Enter one or more Action IDs, separated by commas</td></tr><tr><td>Enable Toggling Actions</td><td>Boolean</td><td>Alternate between executing two sets of Actions</td></tr><tr><td>Toggled Action ID(s)</td><td>Text</td><td>Set which action(s) execute when the key is pressed on even presses. Enter one or more Action IDs, separated by commas</td></tr><tr><td>Resting LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 0</td><td>The RGB color while no actions are running (e.g 10, 0, 0)</td></tr><tr><td>Actions Running LED Color: (RGB)</td><td>Text
- Default Value: 0, 255, 0</td><td>The RGB color while all but the last action is running (e.g 10, 0, 0)</td></tr><tr><td>Last Action LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 255</td><td>The RGB color while the last action is running (e.g 10, 0, 0)</td></tr><tr><td>Shutdown LED Color (RGB)</td><td>Text
- Default Value: 0, 0, 0</td><td>The RGB color when the Function is disabled (e.g 10, 0, 0)</td></tr></tbody></table>

### PIDオートチューン


この機能はPIDコントローラーの自動調整を試みます。つまり、出力を有効化し、センサーからの応答を複数回測定してP、I、Dのゲイン値を計算します。動作状況の更新はデーモンログに記録され、オートチューニングが正常に完了すると、要約情報もデーモンログに保存されます。現在の測定値を上げる動作のみがサポートされており、測定値を下げる場合はコントローラーコードの修正が必要になることがあります。出力が正常に測定値を設定値以上に上げているかを監視するには、ダッシュボードで測定値と出力をグラフ表示することを推奨します。オートチューニング機能は実験的なものであり、完全には開発されていません。適切なPIDゲインを生成できない可能性が高いため、正確なPIDコントローラー調整をこの機能に頼らないことを推奨します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>出力</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to modulate that will affect the measurement</td></tr><tr><td>期間</td><td>Text
- Default Value: 30</td><td>The period between powering the output</td></tr><tr><td>設定値</td><td>Decimal
- Default Value: 50</td><td>A value sufficiently far from the current measured value that the output is capable of pushing the measurement toward</td></tr><tr><td>ノイズバンド</td><td>Decimal
- Default Value: 0.5</td><td>The amount above the setpoint the measurement must reach</td></tr><tr><td>アウトステップ</td><td>Decimal
- Default Value: 10</td><td>How many seconds the output will turn on every Period</td></tr><tr><td colspan="3">Currently, only autotuning to raise a condition (measurement) is supported.</td></tr><tr><td>方向</td><td>Select(Options: [<strong>Raise</strong> | Lower (Cooling/Humidifying)] (Default in <strong>bold</strong>)</td><td>The direction the Output will push the Measurement</td></tr></tbody></table>

### Spacer


A spacer to organize Functions.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>色</td><td>Text
- Default Value: #000000</td><td>The color of the name text</td></tr></tbody></table>

### pH、EC調整


この機能はpH調整に2台のポンプ(酸性・塩基性溶液)を使用し、電気伝導度(EC)調整には最大4台のポンプ(A、B、C、D養液)を使用できます。使用する養液の出力のみを設定すれば十分です。設定されていない出力はEC調整時に作動せず、1台から4台のポンプを使用できます。出力は継続時間(秒)または量(ml)単位で動作でき、各出力タイプは選択した出力チャンネルに合わせる必要があります(継続時間制御にはオン/オフ出力チャンネル、量制御には量出力チャンネル)。養液の混合比率は、各EC出力の継続時間または量の設定によって決まります。メール通知フィールドにメールアドレス(またはカンマ区切りで複数のアドレス)を入力すると、次の場合に通知メールが送信されます。<br>1) pH値が設定された危険範囲を外れたとき、2) EC値が高すぎて貯水タンクに水を追加する必要があるとき、3) 指定したMax Age範囲内でデータベースに測定値が見つからないとき。<br>各メール通知タイプには専用のタイマーがあり、同じ通知が繰り返し送信されることはなく、設定されたメールタイマーの期間中は同じ通知が送信されません。<br>この期間が経過するとタイマーは自動的にリセットされ、新しい通知を送信できるようになります。以下のカスタムコマンド(Custom Commands)を使用して、メールタイマーを手動でリセットすることもできます。<br>この機能が有効な場合、画面下部にステータステキストが表示され、調整情報と各出力の合計継続時間/量が表示されます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 300</td><td>測定またはアクションの間隔時間</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>Status Period (seconds)</td><td>Integer
- Default Value: 60</td><td>The duration (seconds) to update the Function status on the UI</td></tr><tr><td colspan="3">Measurement Options</td></tr><tr><td>pH Measurement</td><td>Select Measurement (Input, Function)</td><td>Measurement from the pH input</td></tr><tr><td>pH: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>EC Measurement</td><td>Select Measurement (Input, Function)</td><td>Measurement from the EC input</td></tr><tr><td>電気伝導率: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td colspan="3">Output Options</td></tr><tr><td>Output: pH Dose Raise (Base)</td><td>Select Channel (Output_Channels)</td><td>Select an output to raise the pH</td></tr><tr><td>Output: pH Dose Lower (Acid)</td><td>Select Channel (Output_Channels)</td><td>Select an output to lower the pH</td></tr><tr><td>pH Output Type</td><td>Select(Options: [<strong>Duration (seconds)</strong> | Volume (ml)] (Default in <strong>bold</strong>)</td><td>Select the output type for the selected Output Channel</td></tr><tr><td>pH Output Amount</td><td>Decimal
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

### カメラ: libcamera: 画像/ビデオ

- Dependencies: [libcamera-apps](https://packages.debian.org/search?keywords=libcamera-apps), [ffmpeg](https://packages.debian.org/search?keywords=ffmpeg)

注意:この機能は現在実験的なものであり、本通知が削除されるまでは自己責任でご使用ください。libcamera-stillおよびlibcamera-vidを使用してカメラから画像と動画をキャプチャします。静止画の撮影、タイムラプスの撮影、カメラウィジェットの使用にはこの機能を有効にする必要があります。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Status Period (seconds)</td><td>Integer
- Default Value: 60</td><td>The duration (seconds) to update the Function status on the UI</td></tr><tr><td colspan="3">Image options.</td></tr><tr><td>Custom Image Path</td><td>Text</td><td>Set a non-default path for still images to be saved</td></tr><tr><td>Custom Timelapse Path</td><td>Text</td><td>Set a non-default path for timelapse images to be saved</td></tr><tr><td>Image Extension</td><td>Select(Options: [<strong>JPG</strong> | PNG | BMP | RGB | YUV420] (Default in <strong>bold</strong>)</td><td>The file type/format to save images</td></tr><tr><td>画像: 解像度: 幅</td><td>Integer
- Default Value: 720</td><td>The width of still images</td></tr><tr><td>画像: 解像度: 高さ</td><td>Integer
- Default Value: 480</td><td>The height of still images</td></tr><tr><td>明るさ</td><td>Decimal</td><td>The brightness of still images (-1 to 1)</td></tr><tr><td>画像: コントラスト</td><td>Decimal
- Default Value: 1.0</td><td>The contrast of still images. Larger values produce images with more contrast.</td></tr><tr><td>彩度</td><td>Decimal
- Default Value: 1.0</td><td>The saturation of still images. Larger values produce more saturated colours; 0.0 produces a greyscale image.</td></tr><tr><td>シャープネス</td><td>Decimal</td><td>The sharpness of still images. Larger values produce more saturated colours; 0.0 produces a greyscale image.</td></tr><tr><td>シャッタースピード (マイクロ秒)</td><td>Integer</td><td>The shutter speed, in microseconds. 0 disables and returns to auto exposure.</td></tr><tr><td>ゲイン</td><td>Decimal
- Default Value: 1.0</td><td>The gain of still images.</td></tr><tr><td>ホワイトバランス: Auto</td><td>Select(Options: [<strong>Auto</strong> | Incandescent | Tungsten | Fluorescent | Indoor | Daylight | Cloudy | Custom] (Default in <strong>bold</strong>)</td><td>The white balance of images</td></tr><tr><td>ホワイトバランス: Red Gain</td><td>Decimal</td><td>The red gain of white balance for still images (disabled Auto White Balance if red and blue are not set to 0)</td></tr><tr><td>ホワイトバランス: Blue Gain</td><td>Decimal</td><td>The red gain of white balance for still images (disabled Auto White Balance if red and blue are not set to 0)</td></tr><tr><td>Flip Horizontally</td><td>Boolean</td><td>Flip the image horizontally.</td></tr><tr><td>Flip Vertically</td><td>Boolean</td><td>Flip the image vertically.</td></tr><tr><td>回転 (度)</td><td>Integer</td><td>Rotate the image.</td></tr><tr><td>Custom libcamera-still Options</td><td>Text</td><td>Pass custom options to the libcamera-still command.</td></tr><tr><td colspan="3">Video options.</td></tr><tr><td>Custom Video Path</td><td>Text</td><td>Set a non-default path for videos to be saved</td></tr><tr><td>Video Extension</td><td>Select(Options: [<strong>H264 -> MP4 (with ffmpeg)</strong> | H264 | MJPEG | YUV420] (Default in <strong>bold</strong>)</td><td>The file type/format to save videos</td></tr><tr><td>ビデオ: 解像度: 幅</td><td>Integer
- Default Value: 720</td><td>The width of videos</td></tr><tr><td>ビデオ: 解像度: 高さ</td><td>Integer
- Default Value: 480</td><td>The height of videos</td></tr><tr><td>Custom libcamera-vid Options</td><td>Text</td><td>Pass custom options to the libcamera-vid command.</td></tr><tr><td colspan="3">Commands</td></tr><tr><td>Capture Image</td><td>Button</td><td></td></tr><tr><td colspan="3">To capture a video, enter the duration and press Capture Video.</td></tr><tr><td>Video Duration (Seconds)</td><td>Integer
- Default Value: 5</td><td>How long to record the video</td></tr><tr><td>Capture Video</td><td>Button</td><td></td></tr><tr><td colspan="3">To start a timelapse, enter the duration and period and press Start Timelapse.</td></tr><tr><td>Timelapse Duration (Seconds)</td><td>Integer
- Default Value: 2592000</td><td>How long the timelapse will run</td></tr><tr><td>Timelapse Period (Seconds)</td><td>Integer
- Default Value: 600</td><td>How often to take a timelapse photo</td></tr><tr><td>Start Timelapse</td><td>Button</td><td></td></tr><tr><td colspan="3">To stop an active timelapse, press Stop Timelapse.</td></tr><tr><td>Stop Timelapse</td><td>Button</td><td></td></tr><tr><td colspan="3">To pause or resume an active timelapse, press Pause Timelapse or Resume Timelapse.</td></tr><tr><td>Pause Timelapse</td><td>Button</td><td></td></tr><tr><td>Resume Timelapse</td><td>Button</td><td></td></tr></tbody></table>

### データ検証


この機能は2つの測定値を取得してその差を計算し、差が設定した閾値を超えていない場合に測定値Aを保存します。これにより、あるセンサーの測定値を別のセンサーの測定値と照合して検証できます。2つのセンサーの値が一致した場合にのみ測定値が保存されるため、保存された測定値を条件付き関数(Conditional Functions)などで利用し、測定値が存在しない場合にユーザーへ通知してセンサーの不具合の可能性を知らせることができます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>測定 A</td><td>Select Measurement (Input, Function)</td><td>Measurement A</td></tr><tr><td>測定 A: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>測定 B</td><td>Select Measurement (Input, Function)</td><td>Measurement B</td></tr><tr><td>測定 B: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Maximum Difference</td><td>Decimal
- Default Value: 10.0</td><td>The maximum allowed difference between the measurements</td></tr><tr><td>Average Measurements</td><td>Boolean</td><td>Store the average of the measurements in the database</td></tr></tbody></table>

### バンバン・ヒステリシス制御(On/Off)(Raise/Lower)


シンプルなBang-Bang制御方式で、1つの入力値を使用して1つの出力を制御します。入力を選択し、**出力、設定値(Setpoint)、ヒステリシス(Hysteresis)**を入力してから、方向(Direction)を選択してください。	•	Raiseモード(例:暖房):入力値が(設定値-ヒステリシス)以下になると出力がオンになり、(設定値+ヒステリシス)以上になるとオフになります。	•	Lowerモード(例:冷房):上記の逆で、入力値を下げるために出力をオンにします。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>測定: 最大経過時間 (Seconds)</td><td>Text
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>出力</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will affect the measurement</td></tr><tr><td>設定値</td><td>Decimal
- Default Value: 50</td><td>希望する設定値</td></tr><tr><td>ヒステリシス</td><td>Decimal
- Default Value: 1</td><td>制御帯域を定義する設定値の上下幅</td></tr><tr><td>方向</td><td>Select(Options: [<strong>Raise</strong> | Lower] (Default in <strong>bold</strong>)</td><td>Raise means the measurement will increase when the control is on (heating). Lower means the measurement will decrease when the output is on (cooling)</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 5</td><td>測定またはアクションの間隔時間</td></tr></tbody></table>

### バンバン・ヒステリシス制御(On/Off)(Raise/Lower/Both)


シンプルなBang-Bang制御方式で、1つの入力値を使用して1つまたは2つの出力を制御します。入力を選択し、Raise出力および/またはLower出力を設定した上で、**設定値(Setpoint)とヒステリシス(Hysteresis:作動範囲)**を入力し、方向(Direction)を選択してください。     •	Raiseモード(例:暖房):入力値が(設定値-ヒステリシス)以下になると出力がオンになり、(設定値+ヒステリシス)以上になるとオフになります。     •	Lowerモード(例:冷房):上記の逆で、入力値を下げるために出力をオンにします。     •	Both:入力値を設定値に保つよう、RaiseとLowerを調整します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>測定: 最大経過時間 (Seconds)</td><td>Text
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Output (Raise)</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will raise the measurement</td></tr><tr><td>Output (Lower)</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will lower the measurement</td></tr><tr><td>設定値</td><td>Decimal
- Default Value: 50</td><td>希望する設定値</td></tr><tr><td>ヒステリシス</td><td>Decimal
- Default Value: 1</td><td>制御帯域を定義する設定値の上下幅</td></tr><tr><td>方向</td><td>Select(Options: [Raise | Lower | <strong>Both</strong>] (Default in <strong>bold</strong>)</td><td>Raise means the measurement will increase when the control is on (heating). Lower means the measurement will decrease when the output is on (cooling)</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 5</td><td>測定またはアクションの間隔時間</td></tr></tbody></table>

### バンバン・ヒステリシス制御(PWM)(Raise/Lower/Both)


シンプルなBang-Bang制御方式で、1つの入力値を使用して1つのPWM出力を制御します。入力を選択し、PWM出力、設定値(Setpoint)、**ヒステリシス(Hysteresis)**を入力してから、方向(Direction)を選択してください。	•	Raiseモード(例:暖房):入力値が(設定値-ヒステリシス)以下になると出力がオンになり、(設定値+ヒステリシス)以上になるとオフになります。	•	Lowerモード(例:冷房):上記の逆で、入力値を下げるために出力をオンにします。	•	Bothモード:入力値を設定値に保つよう、RaiseとLowerを調整します。注意:この出力はPWM(パルス幅変調)出力でのみ動作します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定</td><td>Select Measurement (Input, Function)</td><td>Select a measurement the selected output will affect</td></tr><tr><td>測定: 最大経過時間 (Seconds)</td><td>Text
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>出力</td><td>Select Device, Measurement, and Channel (Output)</td><td>Select an output to control that will affect the measurement</td></tr><tr><td>設定値</td><td>Decimal
- Default Value: 50</td><td>The desired setpoint</td></tr><tr><td>ヒステリシス</td><td>Decimal
- Default Value: 1</td><td>The amount above and below the setpoint that defines the control band</td></tr><tr><td>方向</td><td>Select(Options: [Raise | Lower | <strong>Both</strong>] (Default in <strong>bold</strong>)</td><td>Raise means the measurement will increase when the control is on (heating). Lower means the measurement will decrease when the output is on (cooling)</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 5</td><td>測定またはアクションの間隔時間</td></tr><tr><td>Duty Cycle (increase)</td><td>Decimal
- Default Value: 90</td><td>The duty cycle to increase the measurement</td></tr><tr><td>Duty Cycle (maintain)</td><td>Decimal
- Default Value: 55</td><td>The duty cycle to maintain the measurement</td></tr><tr><td>Duty Cycle (decrease)</td><td>Decimal
- Default Value: 20</td><td>The duty cycle to decrease the measurement</td></tr><tr><td>Duty Cycle (shutdown)</td><td>Decimal</td><td>The duty cycle to set when the function shuts down</td></tr></tbody></table>

### リモートバックアップ(rsync)

- Dependencies: [rsync](https://packages.debian.org/search?keywords=rsync)

この関数は、rsyncを使用して現在のシステムデータをリモートシステムにバックアップします。リモートシステムではSSHサーバーが稼働しており、rsyncがインストールされている必要があります。また、このシステムにもrsyncがインストールされており、SSHキーファイルを使用してパスワードなしでリモートシステムにアクセスできる必要があります。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 1296000</td><td>測定またはアクションの間隔時間</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 300</td><td>初回動作までの待機時間</td></tr><tr><td>Local User</td><td>Text
- Default Value: pi</td><td>The user on this system that will run rsync</td></tr><tr><td>Remote User</td><td>Text
- Default Value: pi</td><td>The user to log in to the remote host</td></tr><tr><td>Remote Host</td><td>Text
- Default Value: 192.168.0.50</td><td>The IP or host address to send the backup to</td></tr><tr><td>Remote Backup Path</td><td>Text
- Default Value: /home/pi/backup_aot</td><td>The path to backup to on the remote host</td></tr><tr><td>Rsync Timeout (Seconds)</td><td>Integer
- Default Value: 3600</td><td>How long to allow rsync to complete</td></tr><tr><td>Local Backup Path</td><td>Text</td><td>A local path to backup (leave blank to disable)</td></tr><tr><td>Backup Settings Export File</td><td>Boolean
- Default Value: True</td><td>Create and backup exported settings file</td></tr><tr><td>Remove Local Settings Backups</td><td>Boolean</td><td>Remove local settings backups after successful transfer to remote host</td></tr><tr><td>Backup Measurements</td><td>Boolean
- Default Value: True</td><td>Backup all influxdb measurements</td></tr><tr><td>Remove Local Measurements Backups</td><td>Boolean</td><td>Remove local measurements backups after successful transfer to remote host</td></tr><tr><td>Backup Camera Directories</td><td>Boolean
- Default Value: True</td><td>Backup all camera directories</td></tr><tr><td>Remove Local Camera Images</td><td>Boolean</td><td>Remove local camera images after successful transfer to remote host</td></tr><tr><td>SSH Port</td><td>Integer
- Default Value: 22</td><td>Specify a nonstandard SSH port</td></tr><tr><td colspan="3">Commands</td></tr><tr><td colspan="3">Backup of settings are only created if the AoT version or database versions change. This is due to this Function running periodically- if it created a new backup every Period, there would soon be many identical backups. Therefore, if you want to induce the backup of settings, measurements, or camera directories and sync them to your remote system, use the buttons below.</td></tr><tr><td>Backup Settings Now</td><td>Button</td><td></td></tr><tr><td>Backup Measurements Now</td><td>Button</td><td></td></tr><tr><td>Backup Camera Directories Now</td><td>Button</td><td></td></tr></tbody></table>

### 冗長センサーデータ


この機能は最初に取得できた測定値を保存します。複数のセンサーをバックアップ用に設定したい場合に便利です。センサーを優先順位で並べておくと、この機能は最初の測定値の有無を確認し、存在しない場合は次の測定値を確認するという処理を繰り返します。測定値が見つかると、カスタム測定項目と単位でデータベースに保存されます。この機能の出力はAoT全体で入力として使用できます。3つ以上の測定値を確認する必要がある場合は、最初の機能の出力を2番目の機能の入力に設定することで、複数の冗長機能を連鎖させることができます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>Measurement A</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace a</td></tr><tr><td>測定 A: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement B</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace b</td></tr><tr><td>測定 B: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement C</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace C</td></tr><tr><td>測定 C: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr></tbody></table>

### 合計 (Last, Multiple)


この機能は選択した各測定値の最新値を取得して合計し、結果を選択した測定値と単位で保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement</td></td><td>Measurement to replace "x" in the equation</td></tr></tbody></table>

### 合計 (Past, Single)


この機能は選択した測定値の過去の測定値(Max Age以内)を取得して合計し、結果を選択した測定値と単位で保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function, Output)</td><td>Measurement to replace "x" in the equation</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr></tbody></table>

### 合計 (累積 / 時点)


単一の測定値ソースを時間経過に沿って合計します。間隔モードはサイクル間のすべての値を合計します(サイクルごとの使用量)。時点モードは、繰り返される時刻(デバイスのタイムゾーンでN時間ごと)に値を1つずつサンプリングし、直近N個のスナップショットを合計します。結果は選択した測定項目と単位で保存されます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>合計モード</td><td>Select(Options: [<strong>間隔合計 (サイクル間)</strong> | 時点合計 (繰り返し時刻の値)] (Default in <strong>bold</strong>)</td><td>間隔: [前回の実行, 現在]の区間内のすべての値を合計します。時点: 直近N個のスナップショット値を合計します。</td></tr><tr><td>測定</td><td>Select Measurement (Input, Function, Output)</td><td>合計対象となる単一の測定値ソース</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 3600</td><td>[インターバルモード] 合計間の時間間隔</td></tr><tr><td>スナップショット時刻 (HH:MM)</td><td>Text
- Default Value: 00:00</td><td>[ポイントモード] デバイスのタイムゾーンにおけるスナップショットの基準時刻(例: 00:00)。深夜0時は24:00を使用してください。</td></tr><tr><td>スナップショット間隔 (時間)</td><td>Text
- Default Value: 24</td><td>[ポイントモード] 基準時刻からのスナップショット間隔(時間)(例: 24 = 1日1回、6 = 1日4回)</td></tr><tr><td>ポイント数 (N)</td><td>Integer
- Default Value: 1</td><td>[ポイントモード] 合計する直近スナップショット値の数</td></tr><tr><td>今すぐ測定</td><td>Button</td><td></td></tr></tbody></table>

### 外部環境コンテキスト収集器


施設外部の気温・湿度・風速・降雨・日射量・露点・CO₂を収集します。統合環境制御Functionは、この収集器を唯一の信頼できる情報源として使用します。各項目に対応する外部センサーを選択してください。設定しない項目は空欄のままにすると、フォールバックのデフォルト値が適用されます。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>更新周期: (Seconds)</td><td>Text
- Default Value: 60</td><td>収集周期(秒)。統合制御Functionのサイクル以下に設定してください。</td></tr><tr><td>外部温度センサー</td><td>Select Measurement (Input, Function)</td><td>外部気温の測定値を選択してください。</td></tr><tr><td>外部湿度センサー</td><td>Select Measurement (Input, Function)</td><td>外部相対湿度の測定値を選択してください。</td></tr><tr><td>風速センサー</td><td>Select Measurement (Input, Function)</td><td>風速(m/s)の測定値を選択してください。</td></tr><tr><td>雨量センサー</td><td>Select Measurement (Input, Function)</td><td>降雨量または降雨検知の測定値を選択してください。</td></tr><tr><td>日射センサー</td><td>Select Measurement (Input, Function)</td><td>日射量(W/m²)または照度の測定値を選択してください。</td></tr><tr><td>露点センサー</td><td>Select Measurement (Input, Function)</td><td>露点(°C)の測定値を選択してください。未設定の場合は、気温と湿度から計算されます。</td></tr><tr><td>外部CO₂センサー</td><td>Select Measurement (Input, Function)</td><td>外部CO₂(ppm)の測定値を選択してください。未設定の場合、デフォルト値は400ppmです。</td></tr><tr><td>センサーの最大許容経過時間(秒)</td><td>Text
- Default Value: 120</td><td>この時間より古い測定値は、フォールバックのデフォルト値に置き換えられます。</td></tr><tr><td>フォールバック外部温度 (°C)</td><td>Decimal
- Default Value: 20.0</td><td>センサーが存在しない場合、または有効期限が切れている場合に使用するデフォルト値。</td></tr><tr><td>フォールバック外部湿度 (%)</td><td>Decimal
- Default Value: 60.0</td><td></td></tr><tr><td>フォールバック風速 (m/s)</td><td>Decimal</td><td></td></tr></tbody></table>

### 差分


この関数は、2つの測定値を取得して差分を計算し、結果を選択した測定値と単位で保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>測定: A</td><td>Select Measurement (Input, Function)</td><td></td></tr><tr><td>測定 A: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>測定: B</td><td>Select Measurement (Input, Function)</td><td></td></tr><tr><td>測定 B: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Reverse Order</td><td>Boolean</td><td>Reverse the order in the calculation</td></tr><tr><td>Absolute Difference</td><td>Boolean</td><td>Return the absolute value of the difference</td></tr></tbody></table>

### 平均(Last, Multiple)


この関数は、選択された各測定値の最新値を取得して平均を計算し、結果を選択した測定値と単位で保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement</td></td><td>Measurement to replace "x" in the equation</td></tr></tbody></table>

### 平均(Past, Single)


この関数は、選択された測定値の過去の測定値(最大有効期間内)を取得して平均を計算し、結果をその測定値と単位で保存します。注意: InfluxDB 1.8.10には、mean()関数が正しく動作しないバグがあります。そのため、InfluxDB v1.xを使用している場合は、代わりにmedian()関数が使用されます。この問題はInfluxDB 2.xでは発生せず、mean()関数を通常どおり使用できます。正確な平均値を得るには、InfluxDB 2.xへのアップグレードをお勧めします。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>測定</td><td>Select Measurement (Input, Function)</td><td>Measurement to replace "x" in the equation</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr></tbody></table>

### 方程式 (Single-Measure)


この機能は測定値を取得し、ユーザー定義の数式に適用した後、その結果を選択した測定値と単位で保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Output, Function)</td><td>Measurement to replace "x" in the equation</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Equation</td><td>Text
- Default Value: x*5+2</td><td>Equation using the measurement</td></tr></tbody></table>

### 湿度 (乾湿球)


この機能は、湿球温度と乾球温度の測定値をもとに湿度を計算します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定有効</td><td>Multi-Select</td><td>記録する測定項目</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>Dry Bulb Temperature</td><td>Select Measurement (Input, Function)</td><td>Dry Bulb temperature measurement</td></tr><tr><td>乾球: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Wet Bulb Temperature</td><td>Select Measurement (Input, Function)</td><td>Wet Bulb temperature measurement</td></tr><tr><td>湿球: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Pressure</td><td>Select Measurement (Input, Function)</td><td>Pressure measurement</td></tr><tr><td>圧力: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr></tbody></table>

### 統計 (Last, Multiple)


この機能は複数の測定値を取得して統計を計算し、選択した単位で結果を保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定有効</td><td>Multi-Select</td><td>記録する測定項目</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement</td></td><td>Measurements to perform statistics on</td></tr><tr><td>Halt on Missing Measurement</td><td>Boolean</td><td>Don't calculate statistics if >= 1 measurement is not found within Max Age</td></tr></tbody></table>

### 統計 (Past, Single)


この機能は単一の測定値から複数の値を取得して統計を計算し、選択した単位で結果を保存します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>測定有効</td><td>Multi-Select</td><td>記録する測定項目</td></tr><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>測定またはアクションの間隔時間</td></tr><tr><td>最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Measurement</td><td>Select Measurement (Input, Function)</td><td>Measurement to perform statistics on</td></tr></tbody></table>

### 飽差 (AVPD)


この機能は葉温と湿度を使用して飽差(AVPD)を計算します。
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>期間 (Seconds)</td><td>Text
- Default Value: 60</td><td>The duration between measurements or actions</td></tr><tr><td>開始オフセット (Seconds)</td><td>Integer
- Default Value: 10</td><td>初回動作までの待機時間</td></tr><tr><td>Temperature</td><td>Select Measurement (Input, Function)</td><td>Temperature measurement</td></tr><tr><td>温度: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr><tr><td>Humidity</td><td>Select Measurement (Input, Function)</td><td>Humidity measurement</td></tr><tr><td>湿度: 最大経過時間 (Seconds)</td><td>Integer
- Default Value: 360</td><td>使用する測定値の最大経過時間</td></tr></tbody></table>

