description: Documentation for AoT, an open source environmental monitoring and regulation system.

## AoT Environmental Monitoring and Regulation System

AoT is open source software designed to run on the [Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi) and other single-board computers (SBCs). It couples inputs and outputs in interesting ways to sense and manipulate the environment.

### Information

See the [README](https://github.com/AoT-inc/AoT#uses) for features, projects using AoT, screenshots, and other information.

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
*   `TZ` — container timezone (default `Asia/Seoul`). Data is stored in UTC; this affects log display and local-time scheduling.
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

