## I2C Notes

The I2C interface must be enabled via `raspi-config` or the `[gear icon] -> Settings -> Raspberry Pi` page.

## 1-Wire Notes

The 1-Wire interface must be enabled via `raspi-config` or the `[gear icon] -> Settings -> Raspberry Pi` page.

## UART Notes

[This document](http://www.co2meters.com/Documentation/AppNotes/AN137-Raspberry-Pi.zip) provides specific installation procedures for configuring the UART on a Raspberry Pi version 1 or 2.

On the Raspberry Pi 2 and later, the UART is handled differently due to the addition of Bluetooth, so different setup instructions are required. If you are installing AoT on a Raspberry Pi 3 or later, perform the following steps to configure the UART:

Run `raspi-config`

`sudo raspi-config`

Go to `Advanced Options -> Serial` and disable it. Then edit `/boot/config.txt`.

`sudo nano /boot/config.txt`

Find the line "enable_uart=0" and change it to "enable_uart=1", then reboot.