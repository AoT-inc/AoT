## I2Cに関する注意事項

I2Cインターフェースは、`raspi-config`または`[gear icon] -> Settings -> Raspberry Pi`ページから有効にする必要があります。

## 1-Wireに関する注意事項

1-Wireインターフェースは、`raspi-config`または`[gear icon] -> Settings -> Raspberry Pi`ページから有効にする必要があります。

## UARTに関する注意事項

[このドキュメント](http://www.co2meters.com/Documentation/AppNotes/AN137-Raspberry-Pi.zip)には、Raspberry Pi バージョン1または2でUARTを設定するための具体的なインストール手順が記載されています。

Raspberry Pi 2以降では、Bluetoothが追加されたことによりUARTの扱いが異なるため、別のセットアップ手順が必要です。Raspberry Pi 3以降にAoTをインストールする場合は、以下の手順でUARTを設定してください:

`raspi-config`を実行します

`sudo raspi-config`

`Advanced Options -> Serial`に進み、無効にします。次に`/boot/config.txt`を編集します。

`sudo nano /boot/config.txt`

「enable_uart=0」という行を見つけて「enable_uart=1」に変更し、再起動します。
