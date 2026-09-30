## I2C Notes

The I2C interface must be enabled via `raspi-config` or the `Manage -> System Management -> Raspberry Pi` page (not available in Docker). Changes apply after `Manage -> Restart System`.

## 1-Wire Notes

The 1-Wire interface must be enabled via `raspi-config` or the `Manage -> System Management -> Raspberry Pi` page (not available in Docker). Changes apply after `Manage -> Restart System`.

## UART Notes

[This document](http://www.co2meters.com/Documentation/AppNotes/AN137-Raspberry-Pi.zip) provides specific installation procedures for configuring the UART on a Raspberry Pi version 1 or 2.

On the Raspberry Pi 2 and later, the UART is handled differently due to the addition of Bluetooth, so different setup instructions are required. If you are installing AoT on a Raspberry Pi 3 or later, perform the following steps to configure the UART:

Run `raspi-config`

`sudo raspi-config`

On Raspberry Pi OS Bookworm and later, the serial port has two separate settings: the serial login shell (a text console on the port) must be **off**, and the serial hardware (the UART itself) must be **on**. The `Manage -> System Management -> Raspberry Pi` page shows them as "Serial Login Shell" and "Serial Hardware". From the command line:

`sudo raspi-config nonint do_serial_cons 1` (login shell off)

`sudo raspi-config nonint do_serial_hw 0` (serial hardware on)

In `raspi-config` this is `Interface Options -> Serial Port`: answer No to the login shell, Yes to the serial hardware.

The configuration file is `/boot/firmware/config.txt` on Bookworm (`/boot/config.txt` on earlier releases). To set it by hand, make sure it contains `enable_uart=1`, then reboot.