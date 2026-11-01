---
guide_id: g01-install
title: Installation
level: 1
minutes: 40
needs: ["g00-overview"]
kind: 실습
---

# Installation

Install AoT with Docker, create the first administrator account, and check that it is running correctly. Docker
installs the same way on a regular PC, a server, or a 64-bit Raspberry Pi, so this guide uses it as the default
path. Installing directly on a Raspberry Pi is described separately in [Step 5](#step-5).

In this guide, the PC, server or Raspberry Pi that AoT is installed on is always called the **computer**.

!!! note "What is Docker"
    Docker is a free tool that packages a program together with everything it needs to run (a container), so that it
    runs the same way on any computer. AoT is also distributed as such a package (an image). Install it from [docs.docker.com/get-docker](https://docs.docker.com/get-docker/).

    - macOS and Windows: download and install **Docker Desktop**, and keep it running.
    - Linux and Raspberry Pi: install **Docker Engine**. The simplest way is `curl -fsSL https://get.docker.com | sh`.

    After installation, you are ready when `docker compose version` shows a version in the terminal.

## When you finish this chapter { #goal }

- You start AoT with Docker and create the first administrator account
- You can check on your own that the installation worked

## Before you start { #prepare }

- One 64-bit Linux, macOS or Windows computer (a regular PC or server, or a Raspberry Pi 4 or 5 running a 64-bit OS)
  - The Docker installation cannot be used on a 32-bit OS. Use the direct installation in [Step 5](#step-5).
- [Docker](https://docs.docker.com/get-docker/) and Compose v2
- An internet connection (the installation images are downloaded)
- A terminal for entering commands on that computer

## Steps { #steps }

### 1. Download and create the settings file { #step-1 }

```bash
git clone https://github.com/AoT-inc/AoT.git /opt/AoT
cd /opt/AoT
cp docker/.env.prod.example docker/.env
```

Open `docker/.env` and check only the four lines below. Leave the rest as they are for now.

| Item | Value to enter | Meaning |
|---|---|---|
| `AOT_IMAGE_TAG` | The exact version from [Releases](https://github.com/AoT-inc/AoT/releases) (for example `26.09.07`) | The version to install. Writing a version instead of `latest` lets you know what changed and when |
| `AOT_PORT` | `8084` | The port you open in the browser. Change it if the port is already in use |
| `TZ` | Your site's timezone (for example `Asia/Seoul`) | The default for **System Timezone** at first installation. After that, the System Timezone setting on screen is used |
| `HARDWARE_PROFILE` | `LOW` for a Raspberry Pi or small computer, `HIGH` for a regular PC or server | Sets how much load the AI features put on the computer. Control features are the same |

### 2. Start it { #step-2 }

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

The first time, it takes a few minutes to download the images. When the installation is complete, four containers should be running.

```bash
docker compose -f docker/docker-compose.prod.yml ps
```

| Container | What it does |
|---|---|
| `aot-app` | Web interface |
| `aot_daemon` | Reads sensors and controls devices (the core of AoT) |
| `aot_mcp` | Connection point for AI |
| `influxdb` | Storage for measurements |

!!! danger "Do not run `docker compose down -v`"
    `-v` also deletes the storage (volumes) that holds your settings and measurements. To stop, use only `down`. To start again, use only `up -d`.

### 3. Create the first administrator account { #step-3 }

1. Open `http://<computer IP>:8084` in a browser. On the same computer, it is `http://localhost:8084`.
2. On the first screen, click **Log In**. Because there is no administrator yet, an information screen appears first. Read it and click **I Acknowledge**.
3. On the **Create Admin** screen, enter a username, email and password, and click **Create Admin Account**.
   - Username: 3 to 64 letters and numbers
   - Password: at least 8 characters. Common passwords are rejected
4. On the login screen, log in with the account you just created. The first screen you see is **Live Measurements**. It is empty because there are no sensors yet.

### 4. Check that it is running correctly { #step-4 }

- **Logo at the top left of the screen**: if its background color does not change, everything is normal. Red means the
  control core (the daemon) has stopped. Gray means the connection to the web interface has been lost.
- **Manage → System Information**: check that the daemon status is "Running" and that there is no warning on the database version. You can also see disk usage here.
- If there is a problem, check the logs.
  ```bash
  docker compose -f docker/docker-compose.prod.yml logs -f aot-app aot_daemon
  ```
  On screen, you can see the same records under Manage → **System Log**.

### 5. Install directly on a Raspberry Pi (alternative) { #step-5 }

Use the direct installation if you want to connect sensors or relays directly to the Raspberry Pi's GPIO or I2C.
The Docker installation does not pass the computer's GPIO, I2C or 1-Wire into the containers. The direct
installation works on both 32-bit and 64-bit OSes, but a 64-bit OS is recommended if you want to use the measurement
storage (InfluxDB).

```bash
curl -L https://aot-inc.github.io/AoT/install | bash
```

- Run it on a Debian-based OS as a user other than root. It stops if `/opt/AoT` already exists.
- When the installation finishes, open `https://<Pi IP>`. A directly installed AoT uses a certificate it created itself
  (self-signed), so the browser shows a warning such as "Your connection is not private". If the address is your own Pi, continue.
  - Chrome and Edge: **Advanced** → **Proceed to <Pi IP> (unsafe)**
  - Safari: **Show Details** → **visit this website**
  - Some browsers and in-app browser windows cannot get past this warning and will not open the page. In that case, use one of the browsers above.
- From creating the administrator account onward, the steps are the same as [Step 3](#step-3).

!!! warning "The direct installation also installs an MQTT broker"
    The direct installation also installs an MQTT broker (port 1883) on the computer. By default it accepts **only connections
    from the same computer**. If another device, such as an external gateway, must connect to this broker, run
    `export AOT_MQTT_LISTEN_ALL=1` in the same terminal before the install command. The broker is then open to the whole
    network **without a login**, so use it only on a network you trust or add a login to the broker. Computers installed with
    an older version may already be open to the whole network. Upgrades do not change this setting; they only show a
    warning ([MQTT broker](../index.md#mqtt-broker-security)).

## Check { #check }

You are done when you can log in from a browser, the logo background is not red or gray, and System Information shows the daemon as "Running".

## Site A { #site-a }

Site A manages several zones and facilities from one computer and also uses the AI connection, so AoT is installed
with Docker on a small PC in the site office, with `HARDWARE_PROFILE=HIGH`. LoRaWAN sensors come in over the
network through ChirpStack, so GPIO is not needed.

## Site B { #site-b }

Site B receives values from the existing equipment over MQTT, so it does not need GPIO either. A 64-bit
Raspberry Pi is placed in the control room next to the greenhouse and AoT is installed with Docker, with
`HARDWARE_PROFILE=LOW`.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| `up -d` fails with an error that the port is already in use | Change `AOT_PORT` in `docker/.env` to a different number |
| The images cannot be downloaded | Whether the computer is amd64 or arm64, and whether it can reach the internet (`ghcr.io`) |
| The browser does not open the page | Whether `aot-app` is running (check with `docker compose ... ps`), and whether the computer IP and port are correct |
| The logo is red | Check the `aot_daemon` logs. If it is still starting for the first time, wait 1 to 2 minutes |
| `https://<Pi IP>` stops at a warning screen or does not open | This is the self-signed certificate warning. Continue as described in [Step 5](#step-5) |
| Database errors on macOS or Windows | Do not change the storage in the compose file. Mounting a folder directly corrupts the database |

## Learn more { #more }

- [Install with Docker](../index.md#install-with-docker)
- [Upgrading a Docker installation](../Upgrade-Backup-Restore.md#docker)
- [System Information](../System-Information.md)
- [Troubleshooting](../Troubleshooting.md)
