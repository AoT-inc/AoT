---
guide_id: g05-sensors
title: Connecting Sensors
level: 1
minutes: 50
needs: ["g04-map"]
kind: 실습
---

# Connecting Sensors

This chapter gets sensor values into AoT. Each sensor sends its values in its own way, so you first choose the connection method,
confirm that values arrive, and then link the sensor to the map and to facilities.

## When you finish this chapter { #goal }

- You choose the connection method that fits your sensor
- You confirm that sensor values arrive, and link the sensor to the map and facilities

## Before you start { #prepare }

- AoT with the map built ([Building the Map](g04-map.md#check)). If you do not use the map, skip only [step 7](#step-7)
- How the sensor sends its values, and its connection details (see the table in step 1 below)
- If you want to try this first without equipment: you need nothing. You use a test input ([step 6](#step-6))

## Steps { #steps }

### 1. Choose the connection method { #step-1 }

| How the sensor sends values | Where to add it in AoT | What you need |
|---|---|---|
| LoRaWAN wireless sensor | Register them in bulk at Manage → System Management → **ChirpStack** | ChirpStack server address, API key |
| Equipment or existing systems that send values over MQTT | Settings → **Input** | Broker address and port, topic, where the value sits in the message |
| Weather (outdoor conditions) API | Settings → **Input** | No key for Open-Meteo; a free key for KMA (Korea Meteorological Administration) |
| PLC (Modbus TCP) | Settings → **Input** (`Modbus TCP (PLC)`) | PLC address, register address |
| Sensor wired to a Raspberry Pi (I2C, UART, 1-Wire, SPI, GPIO) | Settings → **Input** | Sensor model name, connection method, address or port. Only on AoT **installed directly** |

All sensors are added as **inputs**. For a machine that reads values and also moves equipment, such as a PLC or a LoRaWAN controller,
add the values as inputs in this chapter and the control as outputs separately in [Connecting Outputs](g06-outputs.md).

The add list under Settings → **Input** uses the format `Manufacturer: Name [Interface]`. You can find an entry by typing
something like "MQTT" or "temperature" in the **Search by name or measurement** box.

### 2. Register LoRaWAN sensors { #step-2 }

1. In Manage → System Management → **API Key Management**, save the API key you got from ChirpStack.
2. Click **ChirpStack** in the same menu to open the **ChirpStack Devices** page. Under **ChirpStack Connection**, enter the server address
   and the MQTT broker address and port, choose the key you just saved in the **API Token** list, then click **Save**.
   The **Manage API Keys** button next to the list takes you to the page where keys are saved.
3. In **Device Onboarding**, choose the sensors to register and turn on **Register Input**. In the **Channel** box, write one value position
   per line (use the value names from the sensor maker's documentation). Click **Register selected devices**.
4. Set **Max Measurement Age** of the created input to two or three times the interval at which the sensor sends values.
   For a sensor that sends every 15 minutes, about 2,700 seconds.

!!! note "Why Max Measurement Age is needed"
    LoRaWAN and MQTT sensors send values on their own without AoT asking. So even when values stop, the connection can
    look fine. Max Measurement Age is the rule "if no new value arrives within this time, treat the sensor as disconnected".


### 3. Connect MQTT sensors { #step-3 }

1. In Settings → **Input**, add `MQTT Subscribe (JSON payload)`. If each message carries only a single number,
   choose `MQTT Subscribe (Value payload)`.
2. Enter the **Host**, **Port**, and **Topic**. If the broker requires a login, turn on **Use Login**; for an encrypted connection,
   turn on **Use TLS**.
3. For each channel, write where the value sits in the **JMESPATH Expression** box. If the message you receive is `{"sensors":[{"temperature":24.8}]}`,
   the position is `sensors[0].temperature`.
4. For each channel, choose the **Measurement Unit** that matches the actual value. A temperature that arrives as values around 25 is ℃.
5. Set **Max Measurement Age** to two or three times the interval at which the equipment sends values (same as explained in [step 2](#step-2)).

!!! warning "Match the unit to the value — do not fix it by turning on a conversion"
    An MQTT input stores the received number as it is and only attaches the unit you chose as a label. If you receive ℃ values
    but choose ℉ as the unit, the screen shows "25 ℉". If you then add a ℉→℃ conversion, the value changes to −3.9
    and control goes wrong. The right fix is to **change the unit itself to ℃**.

### 4. Add a weather API input { #step-4 }

Outdoor temperature, humidity, wind, and rain are used to decide on ventilation and irrigation. If your site has no weather sensor,
bring in weather information from the internet as an input. Most of these fetch the weather **at the place where the input sits on the map**,
so after you add one, place it over your site in [step 7](#step-7).

| List name | Values provided | Key | How the location is set |
|---|---|---|---|
| `Open-Meteo: Open-Meteo (Coords, Hourly incl. Solar)` | Temperature, humidity, solar radiation, wind, rain, VPD | Not needed | Map position (or latitude and longitude) |
| `KMA: KMA High-Resolution 500m` | Temperature, humidity, wind, pressure, rain, snow, dew point | KMA API Hub key | Map position |
| `KMA: KMA Station Data` | Temperature, humidity, pressure, wind | KMA API Hub key | **Weather station** number |
| `KMA: KMA Short-term Forecast` | Forecast temperature, minimum and maximum, chance of rain, sky condition, and more | **Public Data Portal** key | nx and ny grid coordinates |
| `NASA: NASA POWER (Coords, Daily incl. ET0)` | Daily values such as evapotranspiration (ET0) and solar radiation (published 1 to 2 weeks late) | Not needed | Map position |
| `OpenWeather: OpenWeatherMap (Lat/Lon, Current/Future)` | Temperature, humidity, pressure, wind | OpenWeather key | Map position |

**Setting the location**: after you add a weather input, open its input settings with the gear icon. There is a small map at the top. Move the map
to your site, click the **Move label to current map center** button (target icon) on the left of the map, and then click **Save**. Without a location,
the system log shows "Latitude/Longitude required" and no values arrive.

If this is your first time, start with **Open-Meteo alone**. It needs no key, so it works right away. Follow this order: add → set the location → **Measurement Period** 300 → save →
**Activate**. Then click **Measure Now** in the input settings, and temperature, humidity, solar radiation, wind, and rain values appear in Live Measurement right away. For sites in Korea, if you need values from closer by,
also add KMA High-Resolution 500m.

**Getting a KMA key**

- High-Resolution 500m and Station Data: sign up at the [KMA API Hub](https://apihub.kma.go.kr/), apply for the APIs you will use, and
  copy the authentication key (authKey) from My Page.
- Short-term Forecast: at the [Public Data Portal](https://www.data.go.kr/), apply to use the KMA short-term forecast inquiry service ("기상청 단기예보 조회서비스") and
  copy the general authentication key. A new key may take some time before it can be used.

**Entering the key in AoT**

1. In Manage → System Management → **API Key Management** → **Add New API Key**, save a name (for example, "KMA API Hub") and the key.
2. In the weather input's settings, use the **Key** button next to the API key box to choose the saved key.

The chosen key is **copied as plain text** into the input box. If you change the key later, you must choose it again in every input that uses it.

!!! note "Make the period longer"
    The default period for weather inputs is 15 seconds. Weather information changes every few minutes to every hour, so set the **Measurement Period**
    to 300 seconds (5 minutes) or more. KMA APIs have a daily call limit, and free use of Open-Meteo is
    limited to non-commercial purposes.


### 5. Connect sensors wired to a Raspberry Pi { #step-5 }

This is how you use temperature and humidity, CO2, and soil sensors wired to the pins of a Raspberry Pi.

!!! warning "Not available on a Docker installation"
    AoT installed with Docker cannot use the Raspberry Pi's GPIO, I2C, UART, or 1-Wire. To use wired sensors,
    use a [direct installation](g01-install.md#step-5).

**1) Turn on the interface on the Pi**

In a Pi terminal, run `sudo raspi-config` → Interface Options, turn on the interfaces you use, and reboot.

| Interface | What to turn on | Caution |
|---|---|---|
| I2C | I2C | |
| UART | Serial Port: login shell **No**, serial hardware **Yes** | If the login shell is left on, it mixes into the sensor values |
| 1-Wire | 1-Wire | The default pin is GPIO4 |
| SPI | SPI | |

The same buttons exist on the Manage → System Management → **Raspberry Pi** page in AoT, but use raspi-config for now.

**2) Add the sensor**

Find the sensor model in the Settings → **Input** list. The brackets at the end of the name show the connection method.

| Connection method | Example list names | Fields to fill |
|---|---|---|
| I2C | `BOSCH: BME280 [I2C]`, `Sensirion: SHT31-D [I2C]`, `Sensirion: SCD30 [I2C]`, `ROHM: BH1750 [I2C]` | **I2C Address**, **I2C Bus** (usually 1) |
| UART | `Winsen: MH-Z19B [UART]`, `CO2Meter: K30 [UART]`, `Atlas Scientific: Atlas pH [UART]` | Baud rate (value from the sensor manual) |
| 1-Wire | `MAXIM: DS18B20 [1WIRE]` | **1-Wire Device ID** (choose from the list) |
| ADC (analog sensors) | `Texas Instruments: ADS1115 [I2C]` | I2C address, channel |
| GPIO | `AOSONG: DHT22 [GPIO]` | **Pin: GPIO** (BCM number) |

- **Finding the I2C address**: near the bottom of Manage → **System Information**, a table shows the addresses connected on each I2C bus (the `i2cdetect` result).
  You can also run `i2cdetect -y 1` in a Pi terminal. For sensors with a fixed address, you only need to choose it from the list.
- **1-Wire Device ID**: if the sensor is connected correctly, an ID starting with `28-` appears in the list. If it shows "None Found", check the wiring and that 1-Wire is turned on.
- **UART port**: at present it is fixed to `/dev/ttyAMA0` (the Pi's default UART). A USB adapter (`/dev/ttyUSB0`) cannot be chosen yet.
- **When you add a sensor for the first time**, if the program it needs is missing, the **Install Dependencies** window appears. Click **Install**,
  wait until "Component installation complete" appears, and then add the sensor again. An internet connection is required.
- Sensors that need pigpio, such as the DHT22, require pigpiod to be running on the Pi.

**3) Check**

Click **Activate** and use **Measure Now** in the input settings to see whether a value appears. If there is no value, open Manage → System Log → Daemon
and look for errors from that input (wrong address, cannot open the device, and so on).

### 6. Practice without equipment { #step-6 }

Add `AoT: Test Input: Save your own measurement value`. An input named **Test: Save Value** appears in the list.

1. Click the gear icon on the card to open the input settings. If you need several values, increase **Number of Channels** and save (for example, temperature and humidity = 2).
2. Under **Select Measurements (required)** at the bottom, choose a **Measurement Unit** for each channel (for example, Temperature: Celsius (°C)), enter a **Name** below it (for example, Test temperature),
   and click **Save**. If a name or unit is missing, you get an error when you activate the input.
3. Click **Activate** on the card.
4. In the **Commands** section of the input settings, enter a **Channel** and a **Value**, then click **Execute** next to **Store Measurement**. That value is stored as a measurement.
5. You are done when Additional Features → **Live Measurement** shows the value you just entered (for example, `25 °C`) with its time.

A test input does not produce values on its own. So after you enter a value and **twice the measurement period** (30 seconds by default) passes, Live Measurement
shows "No data for the last N seconds" and `--`. This is not a fault. You use this behavior as it is in [Email Alerts](g08-email.md)
to test the "when a sensor disconnects" alert.

With this input you can test [functions](g07-functions.md) and [email alerts](g08-email.md) without a real sensor.

### 7. Link sensors to the map and facilities { #step-7 }

This step tells AoT where you placed each sensor. There are two kinds of links, and **they serve different purposes.**

| Link | Where you do it | What uses it |
|---|---|---|
| Placing on the map | Settings → Map → device mode (**A** tab) → **Open** the selection list → turn it on in the window that opens → drag it into place | Per-zone value summaries, map display, the location of weather inputs |
| Facility sensor slot | Settings → **Facility** → choose the facility → **Equipment Layout** → type **Sensor** → **+ Add** → check the values to use under **Channel Selection** → name, indoor/outdoor → **Save Facility** | **Facility environment control** |

In one sensor slot you can check several values of an input together (temperature and humidity, or the temperature, humidity, wind speed, and rainfall of a weather input).
An outdoor slot has an extra box for choosing **Main sensor/Backup sensor**.

!!! warning "Always link sensors inside a facility to a facility sensor slot"
    Environment control reads **only sensors linked to facility sensor slots**. A sensor that is only placed on the map shows on
    screen but is not used for control.

A sensor you turn on in the map appears **in the middle of the screen you are currently viewing**. If that spot is outside every zone, the sensor
belongs to no zone, so always drag it into its proper place.

## Check { #check }

You are done when Additional Features → **Live Measurement** shows each sensor's value and time, and the time keeps updating.

- Check that the input card shows a value instead of `--`. To check right away, click **Measure Now** in the input settings.
- Check that clicking a zone on the map shows the sensor values for that zone.
- Check that both the indoor and outdoor sensor slots on the Facility screen are filled.

## Site A { #site-a }

Site A uses all three connection methods.

| Sensor | Method | Link |
|---|---|---|
| Open-field temperature and humidity (2 each in 3-1 and 3-2) | LoRaWAN | On the map, in each zone |
| Soil moisture and temperature (1 each in 3-1 and 3-2) | LoRaWAN | On the map, in each zone |
| Outdoor weather | Open-Meteo, KMA | On the map, over the site |
| Temperature and humidity inside the greenhouse | MQTT | Facility sensor slot (indoor, main) |

Weather inputs are values from **outside** the greenhouse. If you put one in a facility sensor slot, it must be an "outdoor" slot.
If you put it in an indoor slot, environment control treats the outdoor weather as the temperature inside the greenhouse and acts on it.

## Site B { #site-b }

Site B receives, over MQTT, the values that the existing systems were already collecting.

| Sensor | Method | Link |
|---|---|---|
| Temperature and humidity at 5 places inside the greenhouse | MQTT | Facility sensor slots (indoor). One as main, the rest as backup |
| Outdoor weather station (wind speed, wind direction, solar radiation, rainfall) | MQTT | Facility sensor slot (outdoor) |

Wind and rain values are the reason environment control closes the windows. If the weather station values stop, the windows do not open any further,
so be sure to set Max Measurement Age on the weather station input.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The input card keeps showing `--` | Whether you **Activated** the input, and whether the broker or server address and port are correct. For MQTT, the topic spelling and the value position |
| Live Measurement shows "No data for the last N seconds" | Max Measurement Age is shorter than the sensor's sending interval, or the sensor really is disconnected |
| The temperature is oddly high or low | Check the unit (see the warning in [step 3](#step-3)) |
| The zone summary says the sensor cannot be found | You did not place the sensor on the map, or placed it outside the zone |
| Environment control cannot read indoor values | You did not link the sensor to a facility sensor slot ([step 7](#step-7)) |

## Learn more { #more }

- [Inputs](../Inputs.md)
- [LoRaWAN (ChirpStack)](../LoRaWAN-ChirpStack.md)
- [PLC (Modbus TCP)](../PLC-Modbus.md)
- [Supported inputs](../Supported-Inputs.md)
- [Interface settings](../Interfaces.md)
- [I2C multiplexers](../I2C-Multiplexers.md)
- [ADC (analog-to-digital converters)](../Analog-To-Digital-Converters.md)
- [Live measurements](../Data-Viewing.md#live-measurements)
