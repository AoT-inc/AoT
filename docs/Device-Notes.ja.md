この情報は古くなっている場合があるため、必ずメーカーの推奨事項を確認し、各デバイスの操作方法についてはメーカーの指示に従ってください。

## エッジ検出

信号の変化(たとえば、回路を閉じる単純なスイッチなど)を検出するには、エッジ検出が必要です。アクションやイベントをトリガーするために、立ち上がりエッジ(LOWからHIGH)、立ち下がりエッジ(HIGHからLOW)、またはその両方を検出できます。信号を検出するGPIOは、適切な抵抗を使って5ボルトにプルアップするか、グラウンドにプルダウンする必要があります。安全上の理由から、内蔵のプルアップ/プルダウン抵抗を有効にするオプションは用意されていません。GPIOをプルアップ・プルダウンするには、自分で用意した抵抗を使用してください。

エッジ検出に使用できるデバイスの例: 単純なスイッチやボタン、PIRモーションセンサー、リードスイッチ、ホール効果センサー、フロートスイッチなど。

## ディスプレイ

対応しているディスプレイはわずかです。I2Cバックパック付きの16x2および20x4文字LCDディスプレイ、および[128x32](https://www.adafruit.com/product/931) / [128x64](https://www.adafruit.com/product/931) OLEDディスプレイに対応しています。詳細については[対応する機能](Supported-Functions.md)を参照してください。

## Raspberry Pi

Raspberry Piには、CPU/GPUの温度を測定するBCM2835 SoC内蔵の温度センサーがあります。これはAoTで最も簡単にセットアップできるセンサーで、そのままの状態ですぐに使用できます。

## AM2315

この[AM2315]センサーがRpi3のハードウェアI2Cで不安定になる理由が分かりました。これは、BCM2835のクロックストレッチング問題(ハードウェアのバグ: [raspberrypi/linux\#254](https://github.com/raspberrypi/linux/issues/254))を嫌う複数のI2Cデバイスの一つです。ウェイクアップの試行は一貫して失敗します。スニファーでビットストリームを確認したところ、このセンサーは20回に1回程度しか応答しない(あるいはまったく応答しない)うえ、返ってくるのは1バイトだけであることが確認できました。解決策は、I2Cバスをソフトウェアで実装することです。3.3Vに4.7kのプルアップ抵抗を追加し、i2c\_gpioデバイスオーバーレイをインストールする必要があります。これで問題なく動作するようになり、数日間動かし続けてもCRCエラーは発生せず、毎回正確な測定値が得られています。センサーの電源を入れ直す必要もありません。

ソフトウェアI2Cを有効にするには、次の行を`/boot/config.txt`に追加します:

`dtoverlay=i2c-gpio,i2c_gpio_sda=23,i2c_gpio_scl=24,i2c_gpio_delay_us=4`

再起動後、SDAをピン23(BCM)、SCLをピン24(BCM)とする新しいI2Cバスが/dev/i2c-3に作成されます。デバイスを接続する前に、適切なプルアップ抵抗を追加してください。

## K-30

K-30を接続する際は十分注意してください。逆電圧保護がないため、誤った接続をするとセンサーが破損するおそれがあります。

Raspberry Piでの配線手順については[こちら](https://www.co2meter.com/blogs/news/8307094-using-co2meter-com-sensors-with-raspberry-pi)を参照してください。

## 再起動後のUSBデバイスの永続化

GitHubの[(#547) Theoi-Meteoroi](https://github.com/AoT-inc/AoT/issues/547#issuecomment-428752904)より:

USB-シリアル変換アダプタ(CP210xなど)のようなUSBデバイスを使ってセンサーを接続するのは便利ですが、デバイスが複数ある場合、システムの再起動時に問題が発生することがあります。再起動後にデバイスが同じ名前を保持する保証はありません。たとえば、センサーAが/dev/ttyUSB0、センサーBが/dev/ttyUSB1だったとすると、再起動後にセンサーAが/dev/ttyUSB1、センサーBが/dev/ttyUSB0になることがあります。これにより、AoTが誤ったデバイスから測定値を取得してしまい、不正確な測定値が記録される原因になります。この問題を解決するには、以下の手順に従ってください。

udevを使うと、デバイスがカーネルから認識されたときに、選択した/dev/ttyUSBnに対応する永続的なデバイス名('/dev/dust-sensor')を作成できます。唯一必要なのは、USBデバイスが返す一意な属性です。よくあるケースでは属性が一意ではなく、VIDとPIDしか残りません。これは、同じVIDとPIDを報告する他のアダプタが存在しない限り問題ありません。同じVIDとPIDを持つアダプタが複数ある場合は、一意な属性が存在することを期待するしかありません。次のコマンドで属性を調べられます。各USBデバイスでこれを実行した後、差分を比較して使用する属性を見つけてください。

`udevadm info --name=/dev/ttyUSB0 --attribute-walk`

USBアダプタのシリアルフィールドには、ZH03Bのシリアル番号を書き込みました。これにより一意なシリアル番号が保証されます。

```
pi@raspberry:~ $ udevadm info --name=/dev/ttyUSB0 --attribute-walk | grep serial
SUBSYSTEMS=="usb-serial"
ATTRS{serial}=="ZH03B180904"
ATTRS{serial}=="3f980000.usb"
```

これで、udevに何をすべきか伝えるための属性が分かりました。/etc/udev/rules.dに「99-dustsensor.rules」のような名前でファイルを作成します。このファイルに、このデバイスが接続されたときに作成するデバイス名をudevに指示する記述を書きます:

`SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", ATTRS{serial}=="ZH03B180904" SYMLINK+="dust-sensor"`

新しいルールをテストするには:

```
pi@raspberry:/dev $ sudo udevadm trigger
pi@raspberry:/dev $ ls -al dust-sensor
lrwxrwxrwx 1 root root 7 Oct 6 21:04 dust-sensor -> ttyUSB0
```

これで、ダストセンサーを接続すると、常に/dev/dust-sensorとして認識されるようになります。
