Raspberry PiにI2Cバス経由で接続する各デバイスは、通信を行うために一意のアドレスを持つ必要があります。一部の入力デバイス(例: AM2315)は同じアドレスを共有している場合があり、これにより同時に複数台を接続することができません。デバイスによってはアドレスを変更できるものもありますが、利用可能なアドレスの範囲が限られているため、同時に使用できるデバイス数が制限されることがあります。このような状況では、同じI2Cアドレスを持つ複数のセンサーを接続できるようにするI2Cマルチプレクサが非常に役立ちます。

たとえばTCA9548A/PCA9548A: I2Cマルチプレクサには8つの選択可能なアドレスがあり、1台のRaspberry Piに8台のマルチプレクサを接続できます。各マルチプレクサには8つのチャンネルがあり、同じアドレスを持つデバイス・センサーを1台のマルチプレクサあたり最大8台まで接続できます。8台のマルチプレクサ × 8チャンネル = 同じI2Cアドレスを持つデバイス・センサーを64台まで接続可能です。

- TCA9548A/PCA9548A: I2Cマルチプレクサ [Link](https://learn.adafruit.com/adafruit-tca9548a-1-to-8-i2c-multiplexer-breakout/overview) (I2C): 選択可能なアドレス8個、8チャンネル
  - Raspbianに含まれるTCA9548A/PCA9548A用のカーネルドライバを読み込むには、`/boot/config.txt`に`dtoverlay=i2c-mux,pca9548,addr=0x70`を追加してください。ここで`0x70`はマルチプレクサのI2Cアドレスです。設定が成功すると、`[Gear Icon] -> System Information`ページに8つの新しいI2Cバスが表示されます。

- TCA9545A: I2Cバスマルチプレクサ [Link](http://store.switchdoc.com/i2c-4-channel-mux-extender-expander-board-grove-pin-headers-for-arduino-and-raspberry-pi/) (I2C): リンク先のGroveボードは、3.3Vまたは5.0Vを選択できる4つの新しいI2Cバスを作成します。
  - TCA9545A用のカーネルドライバを読み込むには、`/boot/config.txt`に`dtoverlay=i2c-mux,pca9545,addr=0x70`を追加してください。ここで`0x70`はマルチプレクサのI2Cアドレスです。設定が成功すると、`[Gear Icon] -> System Information`ページに4つの新しいI2Cバスが表示されます。
