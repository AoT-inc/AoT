## I2Cに関する注意事項

I2Cインターフェースは、`raspi-config`または`管理 → システム管理 → Raspberry Pi`ページから有効にする必要があります（Dockerでは使用できません）。変更は`管理 -> システムを再起動`の後に反映されます。

## 1-Wireに関する注意事項

1-Wireインターフェースは、`raspi-config`または`管理 → システム管理 → Raspberry Pi`ページから有効にする必要があります（Dockerでは使用できません）。変更は`管理 -> システムを再起動`の後に反映されます。

## UARTに関する注意事項

[このドキュメント](http://www.co2meters.com/Documentation/AppNotes/AN137-Raspberry-Pi.zip)には、Raspberry Pi バージョン1または2でUARTを設定するための具体的なインストール手順が記載されています。

Raspberry Pi 2以降では、Bluetoothが追加されたことによりUARTの扱いが異なるため、別のセットアップ手順が必要です。Raspberry Pi 3以降にAoTをインストールする場合は、以下の手順でUARTを設定してください:

`raspi-config`を実行します

`sudo raspi-config`

Raspberry Pi OS Bookworm以降では、シリアルポートの設定が2つに分かれています。シリアルログインシェル（ポート上のテキストコンソール）は**無効**に、シリアルハードウェア（UART本体）は**有効**にします。`管理 -> システム管理 -> Raspberry Pi`ページでは「シリアルログインシェル」「シリアルハードウェア」と表示されます。コマンドラインでは次のとおりです。

`sudo raspi-config nonint do_serial_cons 1`（ログインシェルを無効）

`sudo raspi-config nonint do_serial_hw 0`（シリアルハードウェアを有効）

`raspi-config`では`Interface Options -> Serial Port`で、ログインシェルはNo、シリアルハードウェアはYesと答えます。

設定ファイルはBookwormでは`/boot/firmware/config.txt`です（以前のリリースは`/boot/config.txt`）。手動で設定する場合は`enable_uart=1`が含まれていることを確認し、再起動します。
