AoT is a smart environmental automation system developed based on the open-source project Mycodo.

# About AoT

AoT is an environmental monitoring and control system. It is designed to operate on single-board computers like the Raspberry Pi and extends Mycodo's powerful automation framework to better suit agriculture, IoT, and smart farming environments.

AoT consists of two main components: the backend (daemon) and the frontend (web server). The backend performs various automation tasks such as collecting sensor data, switching relays, generating PWM signals, managing MQTT communication, controlling pumps, and handling environmental feedback through PID control. The frontend provides configuration and monitoring capabilities through a web interface accessible from any browser-supported device.

Initially developed for edible mushroom cultivation, AoT is now used for a variety of purposes, including remote environmental monitoring, climate and irrigation control, time-lapse photography, and setting triggers based on temperature thresholds or sunrise/sunset.

AoT stores input values collected from various sensors and command outputs (e.g., Bash, Python) in InfluxDB. Output controllers influence the environment through GPIO manipulation or script execution, while function controllers connect inputs and outputs to implement closed-loop feedback control. This makes it ideal for precise environmental control in applications such as fermentation, terrariums, and sous vide cooking.

Key features of AoT include:
- Scheduled actions (based on date/time, duration, sunrise/sunset)
- Dynamic setpoints with heat cycles and ramp functions
- Custom triggers and conditional logic

---

## License and Copyright Information

This software is based on the open-source project [Mycodo](https://github.com/kizniche/Mycodo) developed by Kyle T. Gabriel, and AoT modifies and extends it to suit its purpose.

- **Copyright © 2025 AoT (aot.inc.kr@gmail.com)**
- **Original Copyright © 2015–2022 Kyle T. Gabriel**

AoT is distributed under the GPLv3 license. The full license details can be found on the [GNU License page](https://www.gnu.org/licenses/) and in [Mycodo's LICENSE file](https://github.com/kizniche/Mycodo/blob/master/LICENSE).
