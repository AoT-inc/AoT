# Installing on a Raspberry Pi { #top }

This page covers installing AoT with Docker on a single Raspberry Pi and, if you want, turning on the [Matter](Matter.md) controller on the same Pi.
Installing Docker Desktop on Windows or Mac is covered in the [Install guide](guide/g03-install.md). This page uses the same two files as that guide (the blueprint `docker-compose.prod.yml` and the settings sheet `.env`) and only describes what is different.

**Why a Raspberry Pi.** AoT is a server program that runs 24 hours a day. A Raspberry Pi uses little electricity, starts by itself when power returns, and runs Linux, so it can use the host network that Matter needs. Matter does not work in Docker Desktop on macOS or Windows ([Matter requirements](Matter.md#host)).

## Preparation { #prepare }

| Item | Recommended | Why |
|---|---|---|
| Model | Raspberry Pi 4 or 5 with **4 GB or more** of memory (8 GB recommended) | The web app, daemon, MCP, InfluxDB and the Matter server all run on one machine |
| Operating system | **Raspberry Pi OS (64-bit)**, Bookworm or later. Use Lite if you run it without a screen | The AoT and Matter server images exist only for 64-bit (arm64). They do not start on a 32-bit OS |
| Storage | USB 3 SSD (NVMe is also possible on a Pi 5), at least 32 GB | The measurement store writes constantly. SD cards wear out quickly and are slow |
| Power | The official power adapter for your model | Too low a voltage makes the SSD and USB devices drop out |
| Network | **Wired Ethernet** | The multicast used to find Matter devices is more stable than over Wi-Fi |
| Bluetooth | The built-in Bluetooth of the Pi 4 or 5 | Used only to register a **new** Matter device over Bluetooth for the first time. Not needed for devices shared from another app |

If you will use Matter, put the Pi on the **same network as your Matter devices** (same router, same VLAN). To use Thread devices, that network must already have a Thread border router (HomePod, Apple TV, Nest Hub, SmartThings Station and so on). The Pi does not act as one.

## 1. Write the operating system { #os }

On another computer, write the operating system to the SSD (or SD card) with [Raspberry Pi Imager](https://www.raspberrypi.com/software/).

1. Choose your model, then choose **Raspberry Pi OS (64-bit)** as the operating system (**Raspberry Pi OS Lite (64-bit)** if you do not need a screen).
2. Before writing, enter the following in the **OS customisation** settings.
    - Host name (for example `aot`) — you can find it later as `aot.local`
    - User name and password — choose them yourself, and do not tell them to other people or to an AI
    - Locale and time zone (for example `Asia/Seoul`)
    - Turn on **Enable SSH** (password or public key)
3. Plug the written drive into the Pi and connect the network cable and power. The first start takes a few minutes.

From the command line of another computer, connect (use the user name and host name you chose in step 2).

```bash
ssh <user>@aot.local
```

If `aot.local` cannot be found, look up the Pi's IP in your router's admin page and connect with `ssh <user>@<IP>`. From here on, run every command in this SSH window (inside the Pi).

Bring the operating system up to date and restart.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

!!! tip "Fix the IP address"
    So that the address you open in the browser does not change, we recommend giving the Pi a **fixed IP (DHCP reservation)** in your router's admin page.

## 2. Install Docker { #docker }

Install Docker Engine and the Compose plugin with Docker's official install script. On Linux you use Docker Engine, not Docker Desktop.

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

The last line lets you use the `docker` command without `sudo`. It takes effect only after you **disconnect SSH and connect again**. After reconnecting, check.

```bash
docker version
docker compose version
```

Both commands should print a version. Docker starts automatically at boot.

## 3. Download the files { #files }

This is the same as [step 2 of the Install guide](guide/g03-install.md). `<version>` is the **Latest** number on the [releases page](https://github.com/AoT-inc/AoT/releases) (the number without the leading `v`, for example `26.09.08`).

```bash
mkdir -p ~/AoT/docker && cd ~/AoT/docker
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<version>/docker/docker-compose.prod.yml
curl -fsSL -o .env https://raw.githubusercontent.com/AoT-inc/AoT/v<version>/docker/.env.prod.example
```

If you will use Matter, download two more files: the host check script, and a configuration that is layered on top when you register new devices over Bluetooth.

```bash
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<version>/aot/scripts/check_matter_host.sh
curl -fsSLO https://raw.githubusercontent.com/AoT-inc/AoT/v<version>/docker/docker-compose.matter-ble.yml
```

!!! note "Releases that include Matter"
    Matter is an experimental feature, and the two files above exist only in releases that include Matter. If you get `curl: (22) … 404`, that version does not have Matter yet. Use a version whose release notes mention Matter.

Run `ls -a` to check that all the downloaded files are there.

## 4. Configure and start { #start }

Open the settings sheet.

```bash
nano .env
```

Check the four lines from [step 3 of the Install guide](guide/g03-install.md). On a Raspberry Pi, set `HARDWARE_PROFILE` to **`LOW`** (only some extra AI features are turned off; sensor reading and device control are the same).

| Line | Value on a Raspberry Pi |
|---|---|
| `AOT_IMAGE_TAG` | The same version number as the downloaded files (without the leading `v`) |
| `AOT_PORT` | `8084` |
| `TZ` | The time zone of the site (for example `Asia/Seoul`) |
| `HARDWARE_PROFILE` | `LOW` |

Save with `Ctrl+O`, `Enter` and exit with `Ctrl+X`. Then start it.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

The first time, it takes a few minutes to download the images. All four of `aot-app`, `aot_daemon`, `aot_mcp` and `influxdb` should be `Up`.

In a browser on another computer, open `http://aot.local:8084` (or `http://<Pi IP>:8084`). It is **`http`, not `https`**. Creating the first administrator account and checking that everything works are the same as [steps 5 and 6 of the Install guide](guide/g03-install.md).

!!! danger "Do not delete the volumes"
    To stop, use only `docker compose -f docker-compose.prod.yml down`. `down -v` or deleting volumes erases all settings and measurements.

## 5. Coming back after a power outage { #power }

A Raspberry Pi starts by itself when power returns, Docker starts at boot, and the AoT containers come back up when Docker starts. So there is no extra setting to make as on Windows or Mac ([step 7 of the Install guide](guide/g03-install.md)).

When the installation is done, check by **unplugging the power and plugging it back in**. If AoT opens again in the browser after a few minutes, it works.

!!! warning "Do not just pull the plug"
    You cannot avoid a power outage, but when you turn it off on purpose, shut down with `sudo shutdown -h now` and then remove power. If power is cut while it is writing, the storage can be damaged. If outages are frequent where you are, we recommend a UPS.

## 6. Turn on Matter (optional) { #matter }

Do this only if you want to bring Matter devices into AoT. The details of how it works are on the [Matter](Matter.md) page. If this Pi has a native install (`/opt/AoT`) rather than the Docker install on this page, follow [Starting it on a native install](Matter.md#native) instead.

### 6-1. Check the host { #matter-check }

The check script only **reads** your settings and changes nothing. If there is a problem, it prints the command that fixes it.

```bash
cd ~/AoT/docker
bash check_matter_host.sh
```

Each line starts with `OK`, `WARN` or `FAIL`. Fix the `FAIL` lines first, then the `WARN` lines that apply. If both the network cable and Wi-Fi are connected, specify the one on the same network as your Matter devices, for example `--iface eth0`.

Items that are common on a Raspberry Pi:

- **IPv6 off, or router advertisements not received**: Raspberry Pi OS has IPv6 on by default. If it is off, turn it on with the command the script prints, and save it so it stays on after a restart.
- **`ra_routes` warning**: This is normal on a network without a Thread border router. Fix it only when you use Thread devices.
- **`mdns_5353`**: It is fine if another program (for example `avahi-daemon`) uses port 5353. It is shown for information only.

### 6-2. Start the Matter server { #matter-enable }

In `.env`, remove the `#` in front of the Matter line to turn it on.

```
COMPOSE_PROFILES=matter
```

Leave `MATTER_LOG_LEVEL` at `info`. If you raise it to `debug`, the server writes Wi-Fi passwords to the log as they are. Save and bring it up again.

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

`matter_server` and `matter_socket` should also be `Up`. In the browser, turn on **Use Matter (Experimental)** under **Manage → System Management → General Settings** and save. Open **Matter**, which now appears in the Settings menu, and check that the server shows as connected.

### 6-3. Register a new device over Bluetooth (optional) { #matter-ble }

If you only use devices **shared** from other apps (Apple Home, Google Home, SmartThings and so on), you do not need this step. Do it only to register a device straight out of the box directly in AoT.

Turn on the Bluetooth service and check.

```bash
sudo systemctl enable --now bluetooth
bash check_matter_host.sh --ble
```

When the lines that start with `ble_` are `OK`, from now on bring it up **with both files together**.

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.matter-ble.yml up -d
```

!!! warning "If you use Bluetooth, always give both files in the command"
    If you later run only `docker compose -f docker-compose.prod.yml up -d` again, the Matter server is recreated without the Bluetooth configuration. Use both files when you upgrade as well.

### 6-4. Add a device { #matter-add }

As described on the [Matter page](Matter.md#add-shared), share the device from its existing app and enter the pairing code you receive in **Add a shared device** under **Manage → System Management → Matter**.

## Upgrading { #upgrade }

This is the same as [Upgrading a Docker deployment](Upgrade-Backup-Restore.md#docker). Download the new version's `docker-compose.prod.yml`, change `AOT_IMAGE_TAG` in `.env` to the same number, then run `pull` and `up -d`. The Matter server version does not go up automatically; you set it with `MATTER_SERVER_TAG` in `.env`.

## Troubleshooting { #trouble }

| Symptom | Cause | Fix |
|---|---|---|
| The image cannot be pulled, for example `no matching manifest for linux/arm/v7` | A 32-bit operating system | Write **64-bit** Raspberry Pi OS again. `uname -m` must show `aarch64` |
| `permission denied ... docker.sock` | The `docker` group has not taken effect yet | Disconnect SSH and connect again |
| The browser does not open | Wrong address or port, or it is still starting | Check with `ps` that all four are `Up`, and that you use `http://<Pi IP>:8084` |
| Slow, or containers keep restarting | Out of memory | Check with `free -h`. If it is under 4 GB, use a larger model or turn Matter off |
| The USB SSD is not found after power returns | Not enough power | Use the official power adapter, and if the SSD draws a lot, use a USB hub with its own power supply |
| Settings > Matter shows the server as not connected | `COMPOSE_PROFILES=matter` is missing, or `matter_server` has stopped | Check `.env`, then `up -d`, and `docker compose -f docker-compose.prod.yml logs matter_server` |
| The device is not found (timeout) | The Pi and the device are on different networks, or an IPv6 or multicast problem | Run `check_matter_host.sh` again. Turn off the multicast optimisation of a mesh Wi-Fi |
| Bluetooth registration ends with a search timeout | Bluetooth is off, or it was brought up without `-f docker-compose.matter-ble.yml` | Check `check_matter_host.sh --ble`, then `up -d` with both files |

## For helper AIs { #for-ai }

- The user connects to a Raspberry Pi (64-bit Raspberry Pi OS) over SSH and installs with Docker Engine. Do not give Docker Desktop commands.
- The install folder is `~/AoT/docker` and the compose file is `docker-compose.prod.yml`. If Matter Bluetooth is used, always use `docker-compose.matter-ble.yml` together with it.
- Do not recommend `down -v`, deleting volumes or `docker system prune --volumes`.
- Do not recommend raising `MATTER_LOG_LEVEL` to `debug` (Wi-Fi passwords are left in the log).
- Do not ask for pairing codes, Wi-Fi passwords or administrator passwords.
