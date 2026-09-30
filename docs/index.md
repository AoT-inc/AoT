description: Documentation for AoT, an open source GIS- and AI-based environmental monitoring and control system.

## AoT Environmental Monitoring and Control System

AoT puts your space on a map and links the records and devices that belong to it. It then lets AI look at that space together with people, make judgments, and get work done.

It is open source software for monitoring an environment with sensors and controlling devices remotely, not tied to any particular purpose or kind of site. Devices, sensors, and structures can be placed at their real positions on a **GIS map**, and an **AI layer built on MCP** (Model Context Protocol) can read the system, diagnose it, and act on it with your approval. Which features you use is up to you.

It runs natively on the [Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi) and other single-board computers (SBCs), and in Docker on ordinary servers and PCs.

### Information

See [About](About.md) for what AoT does and how the pieces fit together, or the [README](https://github.com/AoT-inc/AoT) for features, screenshots, and other information.

### Prerequisites

*   Single-board computer (Recommended: [Raspberry Pi](https://www.raspberrypi.org/) 2, 3, 4, or newer) or any other Debian-based Linux machine
*   Debian-based operating system (32-bit `armhf`, 64-bit `arm64`, or `amd64`) with Python 3.8 or newer
*   An active internet connection

The installer detects the CPU architecture and supports `armhf`, `arm64`, and `amd64`. The Raspberry Pi Zero and Pi 1 (ARMv6) are not tested, so they are not listed as supported.

Alternatively, AoT can run in Docker on any Linux, macOS, or Windows machine — see [Install with Docker](#install-with-docker) below.

### Install

Once booted and logged in, run the following command to initiate the AoT install:

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

After installation, open a web browser to the SBC's IP address.

```
https://<Pi IP address>
```

`https://127.0.0.1` (or `localhost`) only works in a browser running on the Pi itself. From another computer, use the Pi's IP address. The installer creates a self-signed certificate, so the browser shows a certificate warning the first time; accept it to continue.

See [First run](#first-run) below for what you will see next.

### MQTT broker { #mqtt-broker-security }

The direct install also sets up a local [Mosquitto](https://mosquitto.org/) MQTT broker. By default it accepts connections only from the same device (`127.0.0.1`), which is where AoT's MQTT inputs and outputs point by default (`localhost:1883`).

*   To let other devices connect, such as an external gateway, run `export AOT_MQTT_LISTEN_ALL=1` in the same terminal before the install command. The broker then listens on all network interfaces **without a login**, so use it only on a trusted network, or add a password file (`allow_anonymous false`, `password_file`) to `/etc/mosquitto/conf.d/aot.conf`.
*   An existing install keeps its current `/etc/mosquitto/conf.d/aot.conf`. Earlier versions wrote `listener 1883` with `allow_anonymous true`, which is reachable from the whole network without a login. Installing or upgrading does not change that file; it prints a warning if the broker is open this way. To restrict it, change the first line to `listener 1883 127.0.0.1` and run `sudo systemctl restart mosquitto`. Do this only after checking that no gateway on the network publishes to this broker.

### Install with Docker { #install-with-docker }

Prerequisites: [Docker](https://docs.docker.com/get-docker/) with Compose v2. Official images are published for `linux/amd64` and `linux/arm64`.

The compose file mounts the custom extension directories from the repository (`aot/inputs/custom_inputs` and friends), so clone it first:

```bash
git clone https://github.com/AoT-inc/AoT.git /opt/AoT
cd /opt/AoT
cp docker/.env.prod.example docker/.env
```

Review these values in `docker/.env`:

*   `AOT_IMAGE_TAG` — the version to install. Pinning an exact [release](https://github.com/AoT-inc/AoT/releases) is recommended.
*   `AOT_PORT` — host port for the web interface (default `8084`).
*   `TZ` — container timezone (default `Asia/Seoul`). It only sets the **first-run default** of the System timezone setting (copied into the database once, when it is first created); changing it later has no effect. Log timestamps and scheduling follow the System timezone setting and the map site/zone locations, so after the first login check the System timezone and place your sites and zones on the map. Data is always stored in UTC.
*   `HARDWARE_PROFILE` — `LOW` (default), `MEDIUM`, or `HIGH`. It only switches AI-assistant features: `LOW` turns off the VEE and EKG features and the AI intent router stays on; `MEDIUM` and `HIGH` turn VEE and EKG on, and `HIGH` keeps a larger EKG window (5000 entries instead of 500). Sensors, outputs, and control are the same at every level, so keep `LOW` on a Raspberry Pi or small VM.

Start the stack:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

Then open a web browser to the host's IP address on that port.

```
http://<host IP address>:8084
```

`http://127.0.0.1:8084` (or `localhost`) only works in a browser on the Docker host itself. The Docker stack does not use HTTPS by default, so there is no certificate warning; put a reverse proxy in front of it if you need HTTPS (see [Security](Security.md)).

Upgrading a Docker deployment means pulling a new image and recreating the containers, not replacing files on disk. See [Upgrade/Backup/Restore](Upgrade-Backup-Restore.md#docker).

!!! note
    The Docker stack does not pass the host's GPIO, I2C, or 1-Wire devices into the containers. Use the direct install for sensors and relays wired to Raspberry Pi pins. Network-attached devices — LoRaWAN (ChirpStack), Modbus TCP, MQTT — work the same in either installation.

### First run { #first-run }

A fresh install (direct or Docker) opens a public landing page first, not a login form. While no Admin user exists yet, follow this path:

1. On the landing page, click **Log In**. AoT sends you to `/login`, and because there is no Admin yet, on to `/create_admin`.
2. The first screen is the **Quality Assurance Notice** (license, warranty, and anonymous statistics). Read it and click **I Acknowledge**.
3. The Admin creation form appears. Enter a username, email, and password, then submit.
4. Log in with the new account. You can opt out of statistics later under `Manage -> System Management -> General Settings`.

### Support

*   [AoT on GitHub](https://github.com/AoT-inc/AoT)
*   [AoT Wiki](https://github.com/AoT-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)
*   [Discussion Forum](https://forum.radicaldiy.com)
*   [Frequently Asked Questions](https://forum.radicaldiy.com/docs?category=23&tags=aot)

