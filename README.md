# AoT

Latest version: 26.09.05 · [한국어](README.ko.md) · [User manual](https://aot-inc.github.io/AoT) · [Changelog](CHANGELOG.md)

**AoT puts your space on a map and links the records and devices that belong to it. It then lets AI look at that space together with people, make judgments, and get work done.**
It is open source, anything that moves a device runs only after you approve it, and which features you use is up to you.

## What AoT is

A sensor reading alone is hard to act on. You need to know where the sensor is, what is around it, and what is going on there right now. AoT keeps that information together: people see it on screen, and AI reads the same thing through MCP.

AoT collects the geographic and environmental data of a place and gives you planning, day-to-day operation, and automatic control on top of it. It is not tied to any purpose or kind of site.

## Main features

- **Control.** The Input / Output / Function model inherited from Mycodo (see [Origins](#origins)): support for many sensors and relays, PID, sequences, timers, and conditionals, with time series stored in InfluxDB.
- **Device connectivity.** Network devices over LoRaWAN, Modbus TCP, MQTT, and HTTP, and sensors and relays wired directly to Raspberry Pi pins.
- **Map.** Devices, sensors, facilities, and areas can be placed at their real positions on the dashboard's map widget and viewed and operated there. A facility can be drawn as an outline and shown in 3D, and its opening area, orientation, and wind direction can feed the control. A setup without the map is also possible.
- **AI connection.** Connect an MCP-capable AI app such as Claude Desktop over [MCP](https://modelcontextprotocol.io), and that AI queries devices, measurements, areas, schedules, and notes, diagnoses the situation, and proposes what to do. Anything that moves a device runs only after you approve it. AoT is not tied to any AI provider, and every feature works without AI.

## Quick start

**Direct install** (Debian-based Linux; recommended for Raspberry Pi and other boards with GPIO, I2C, 1-Wire):

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

**Docker** (Linux, macOS, Windows; network devices only, Raspberry Pi pins are not available):

```bash
git clone https://github.com/AoT-inc/AoT.git /opt/AoT
cd /opt/AoT
cp docker/.env.prod.example docker/.env   # set AOT_IMAGE_TAG to a release version
docker compose -f docker/docker-compose.prod.yml up -d
```

Then open the web interface (`https://<host>/` for the direct install, `http://<host>:8084/` for Docker) and create the admin account. Full instructions, upgrade, backup, and troubleshooting are in the [manual](https://aot-inc.github.io/AoT). AoT collects minimal anonymous usage statistics, which you can [turn off in settings](https://aot-inc.github.io/AoT/Configuration-Settings/).

## Where to look next

- [About](https://aot-inc.github.io/AoT/About/) — what the pieces are and how they fit.
- [ARCHITECTURE.md](ARCHITECTURE.md) — processes, packages, domain model, dependency rules. One page.
- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, conventions, CI guards.
- [Issues](https://github.com/AoT-inc/AoT/issues) — questions and bug reports. Security reports go through [SECURITY.md](SECURITY.md).

## About this repository

- Front-end JavaScript sources are not published. This repository carries the built bundles only; Python, templates, styles, tests, and migrations are complete. Third-party libraries are included under their own licenses.
- The manual is built from `docs/` with mkdocs. Design notes in `docs/design/` are working documents and are not part of the manual.
- The previous 2D-map version (v26.0.x) is preserved on the [legacy-2d](https://github.com/AoT-inc/AoT/tree/legacy-2d) branch. Its data is not compatible with the current version; do not upgrade an installation you want to keep on it.

## Origins

AoT started as a modified build of the open-source [Mycodo](https://github.com/kizniche/Mycodo) by Kyle T. Gabriel. It kept the Input / Output / Function control model, replaced the device-list screen with a map, and added MCP-based AI, facility-scale environmental control, LoRaWAN device management, and a new UI. The control model still rests on Mycodo, and its contribution is gratefully acknowledged.

## License

AoT is free software under the GNU General Public License, version 3 or later. See [LICENSE.txt](LICENSE.txt). It is distributed in the hope that it will be useful, but without any warranty.

This software includes third-party open-source software. The full list and each license are in [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
