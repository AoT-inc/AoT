description: Documentation for AoT, an open source GIS- and AI-based environmental monitoring and control system.

## AoT Environmental Monitoring and Control System

AoT puts your space on a map and links the records and devices that belong to it. It then lets AI look at that space together with people, make judgments, and get work done.

It is open source software for monitoring an environment with sensors and controlling devices remotely, not tied to any particular purpose or kind of site. Devices, sensors, and structures can be placed at their real positions on a **GIS map**, and an **AI layer built on MCP** (Model Context Protocol) can read the system, diagnose it, and act on it with your approval. Which features you use is up to you.

It runs natively on the [Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi) and other single-board computers (SBCs), and in Docker on ordinary servers and PCs.

### Information

See [About](About.md) for what AoT does and how the pieces fit together, or the [README](https://github.com/AoT-inc/AoT) for features, screenshots, and other information.

### Prerequisites

*   Single-board computer (Recommended: [Raspberry Pi](https://www.raspberrypi.org/), any version: Zero, 1, 2, 3, or 4)
*   Debian-based operating system
*   An active internet connection

Alternatively, AoT can run in Docker on any Linux, macOS, or Windows machine — see [Install with Docker](#install-with-docker) below.

### Install

Once booted and logged in, run the following command to initiate the AoT install:

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

After installation, open a web browser to the SBC's IP address and you will be prompted to create an Admin user and login.

```
https://127.0.0.1
```

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
*   `HARDWARE_PROFILE` — `LOW` (Raspberry Pi, small VM) or `HIGH`.

Start the stack:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

Then open a web browser to the host's IP address on that port, and you will be prompted to create an Admin user and login.

```
http://127.0.0.1:8084
```

Upgrading a Docker deployment means pulling a new image and recreating the containers, not replacing files on disk. See [Upgrade/Backup/Restore](Upgrade-Backup-Restore.md#docker).

!!! note
    The Docker stack does not pass the host's GPIO, I2C, or 1-Wire devices into the containers. Use the direct install for sensors and relays wired to Raspberry Pi pins. Network-attached devices — LoRaWAN (ChirpStack), Modbus TCP, MQTT — work the same in either installation.

### Support

*   [AoT on GitHub](https://github.com/AoT-inc/AoT)
*   [AoT Wiki](https://github.com/AoT-inc/AoT/wiki)
*   [AoT API](https://aot-inc.github.io/AoT/aot-api.html)
*   [Discussion Forum](https://forum.radicaldiy.com)
*   [Frequently Asked Questions](https://forum.radicaldiy.com/docs?category=23&tags=aot)

