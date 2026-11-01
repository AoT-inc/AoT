# Matter

!!! warning "Experimental"
    Matter support is experimental. It has been verified against virtual devices, but not yet against a wide range of real devices and home ecosystems. Do not use it for anything where a lost connection would cause damage until you have tested it with your own devices.

AoT can act as a **Matter controller** that is independent of any vendor or app ecosystem. A device that is already set up in Apple Home, Google Home, SmartThings, Alexa or another Matter app can be shared with AoT through Matter **Multi-Admin**: the other app opens a short sharing window, you enter its code in AoT, and AoT joins the device to its own Matter network (called a *fabric*). The device then belongs to both ecosystems at once, and keeps working in the other app.

AoT turns the device into a normal AoT device with Inputs and Outputs, so everything else in AoT works with it: charts, Triggers, PID control, sequences, the environment coordinator, and the AI assistant.

Reading and control go directly over your local network between AoT and the device. The other ecosystem's cloud is not used, so none of its API fees or request limits apply.

You manage everything on one page: **Manage → System Management → Matter**.

## What AoT does not do { #scope }

- AoT does not know or care which app a device came from. It only asks whether the device can be added to its fabric.
- AoT does not add the same device twice. A device that is already in AoT through another route (for example a cloud integration) should not also be added through Matter, or its measurements are stored twice.
- AoT's AI assistant cannot add or remove Matter devices. Pairing codes are handled by people only. Once a device exists, its outputs are controlled like any other output, including by the assistant and its approval step.
- AoT works with devices it can reach by IP: Wi-Fi, Ethernet, or Thread through a border router that is already on your network. AoT is not itself a Thread border router.

## Requirements and turning it on { #host }

Matter needs more from the network than other AoT features. Most failures come from the host network, not from AoT. Check these before anything else.

- A **Linux host**: the Docker deployment, or a native install with only the Matter server in Docker ([native install](#native)). Docker Desktop on macOS or Windows cannot provide the multicast networking Matter needs. A single Raspberry Pi is enough: see [Raspberry Pi Install](Raspberry-Pi-Install.md).
- The host must be on the **same network** (same VLAN) as the Matter devices.
- The Matter server runs on the **host network** of the machine, with **IPv6** enabled, IPv6 router advertisements accepted, and **mDNS** working. Some mesh Wi-Fi systems and routers that "optimize" multicast break this.
- To add a **new** device over Bluetooth, the host also needs a Bluetooth adapter and BlueZ. This is optional ([see below](#ble)).

### 1. Check the host { #check-host }

Run the check script on the host, not in a container. It only reads settings, it never changes anything, and it prints the command that fixes each problem it finds.

```bash
aot/scripts/check_matter_host.sh
```

| Option | Meaning |
|---|---|
| `--iface <name>` | Check this network interface. Without it, the interface of the default route is used |
| `--ble` | Also check Bluetooth for adding new devices: BlueZ, adapter present, not blocked by rfkill, powered on, D-Bus socket |
| `--json` | Print the result as JSON |

Each line starts with `OK`, `WARN` or `FAIL`. The exit code is `0` when there is no `FAIL`. Fix every `FAIL` first, then the warnings that apply to you.

### 2. Start the Matter server { #enable }

The Matter server is part of the Docker deployment but is **off by default**. In `docker/.env` add:

```
COMPOSE_PROFILES=matter
```

Then start the stack as usual:

```bash
docker compose -f docker/docker-compose.prod.yml up -d
```

This starts two extra containers: `matter_server` (the Matter stack) and `matter_socket` (a small bridge that gives AoT a local socket to talk to it). The data volume `matter_data` holds the fabric.

Other settings in `docker/.env`:

| Setting | Meaning |
|---|---|
| `MATTER_SERVER_TAG` | Version of the Matter server image. The automatic updater does **not** update this service; raise the tag yourself when you want a newer version |
| `MATTER_TEST_DCL` | `false` by default. Set it to `true` only to add development/test devices (vendor ID `0xFFF1`). Leave it off in production |
| `MATTER_LOG_LEVEL` | Keep at `info`. At `debug` the server writes raw requests to its log, including Wi-Fi passwords |
| `MATTER_BLUETOOTH_ADAPTER` | Bluetooth adapter number when using the Bluetooth file below (`0` = `hci0`) |

In AoT, turn on **Use Matter (Experimental)** under **Manage → System Management → General Settings** and save. Matter then appears in the Settings menu (it is hidden while off).

Open **Manage → System Management → Matter**. The **Matter Server** card shows **Status** (**Connected** / **Not connected**), the server version, the **Fabric ID**, and how many devices there are and how many are **Reachable**. If it is not connected, the page shows the last error and these same start-up instructions.

### 3. Optional: Bluetooth for new devices { #ble }

Adding a device that is fresh out of the box needs Bluetooth on the host. Run `aot/scripts/check_matter_host.sh --ble`, fix what it reports, then start the server with the extra compose file:

```bash
docker compose -f docker/docker-compose.prod.yml -f docker/docker-compose.matter-ble.yml up -d
```

From then on, always use both files in your compose commands. Running `up -d` with the first file alone recreates the server without Bluetooth. The container stays unprivileged and only gets read access to the host's D-Bus.

If Bluetooth is not enabled, the page says so under **Add a new device**; adding a shared device and adding a device that is already on the network still work.

### 4. Starting it on a native install { #native }

If AoT is installed natively (the `aot`, `aotflask` and `aotmcp` services in `/opt/AoT`) rather than with Docker, run only the Matter server in Docker and tell the AoT services where it is. Run these commands on the host, in `/opt/AoT`; they need administrator rights.

1. Check the host ([step 1](#check-host) above). Add `--ble` if you will use Bluetooth.
2. Install Docker Engine (skip this if it is already installed).
    ```bash
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    ```
3. Start the Matter server. To add new devices over Bluetooth, always add `-f docker/docker-compose.matter-ble.yml` to this and every later command.
    ```bash
    sudo docker compose -f docker/docker-compose.matter-native.yml up -d
    ```
4. Give the three AoT services the server address and restart them.
    ```bash
    for s in aot aotflask aotmcp; do
      sudo install -D -m 644 install/aot-matter.conf /etc/systemd/system/$s.service.d/matter.conf
    done
    sudo systemctl daemon-reload
    sudo systemctl restart aot aotflask aotmcp
    ```
5. Turn on **Use Matter (Experimental)** under **Manage → System Management → General Settings**. If the packages Matter needs are missing, you are sent to the package page to install them. Then check on the **Matter** page that the server shows as connected.

How this differs from a Docker install:

- There is no socket relay (`matter_socket`). AoT runs on the host and reaches the server's loopback port (`127.0.0.1:5580`) directly. That port has no authentication, so anyone who can log in to this host can control the Matter devices.
- The Matter data (Docker volume `aot_matter_matter_data`) is not part of the AoT backup. It holds the fabric root CA key, so back it up separately and keep the copy secret.
    ```bash
    sudo docker run --rm -v aot_matter_matter_data:/data -v "$PWD":/backup alpine tar czf /backup/matter_data.tgz -C /data .
    ```
- Upgrading AoT does not change the Matter server. Raise its version yourself with `MATTER_SERVER_TAG`.

## Adding a device shared from another app { #add-shared }

Use this for a device that is already set up in another Matter app.

1. In that app, open the device and choose its **share**, **pairing mode** or **linked Matter apps** option. The wording differs by app, and it is often found under "Turn on pairing mode" or "Connect to another hub or app".
2. The app shows an 11-digit pairing code (and a QR code). It works for about 15 minutes.
3. In AoT, open **Add a shared device**, type the code into **Pairing code** and press **Add**.

Adding normally takes under a minute. A wrong or expired code can take several minutes before AoT gives up, so keep the page open.

AoT then creates, and activates, one **AoT device** for the Matter device. Under it:

- a **sensor Input** with one channel for every measurement the device offers, and
- **Outputs** for the controllable endpoints: one switch Output and one dimmer Output with a channel per endpoint, and one Output per curtain.

The toast tells you how many sensors and switches were added. The device shows up in the **Matter Devices** list and on the [Device](Device.md) page. AoT also names itself on the device so that the other app shows "AoT" as a connected app.

AoT never stores or logs pairing codes. The code is passed straight to the Matter server and is only valid for a short time, but until it expires it is as good as a key to the device, so do not paste it anywhere else.

If you remove a device and share it again later, AoT recognises it (by its manufacturer-assigned unique ID) and **reconnects it to the existing AoT device** instead of making a new one, so the measurement history continues.

## Adding a brand-new device over Bluetooth { #new-device }

Use **Add a new device** for a device straight out of the box or reset to factory settings. AoT finds it over Bluetooth, joins it to your network, and adds it to its own fabric, so no other app is needed.

You need:

- the pairing code printed on the device or its box,
- Bluetooth enabled on the Matter server ([see above](#ble)), and the device kept close to the AoT server, and
- for **Network**, one of:
    - **Wi-Fi**: enter the **Wi-Fi network name** and **Wi-Fi password**. If the device only supports 2.4 GHz, choose a 2.4 GHz network.
    - **Thread**: paste the **Thread dataset (hex)** of your Thread network. A Thread border router must already be running on the network.
    - **Already on the network (Ethernet)**: the device already has network access, so no credentials are needed.

Press **Add**. The job runs in the background and the page checks on it every few seconds. It can take several minutes (finding the device, joining the network, and finding it again on the network); AoT gives up after about 12 minutes. When the device appears, its AoT device is created automatically. You may close the page; a device that joined while the page was closed appears in the list as **No AoT device** and you can turn it into one with **Create AoT device** (see [Missing and orphan devices](#orphans)).

!!! warning "About the Wi-Fi password and Thread dataset"
    AoT does **not** keep the Wi-Fi password or the Thread dataset. They are given to the Matter server once to join the device, and then removed from the server's list of credentials, whether the job succeeded or failed. They are not written to AoT's job files or logs.

    However, the Matter server stores its data as an append-only log, and the password or dataset can **remain in that log in plain text**, even after the credential is removed and after a restart. AoT cannot erase it with the current server. This data is part of the AoT backup (`matter_data`). So:

    - treat every backup that contains `matter_data` as secret ([Upgrade, Backup, Restore](Upgrade-Backup-Restore.md#docker-backup)), and
    - if this matters for your network, change the Wi-Fi password after the devices are added.

## What gets created { #created }

### Sensors { #sensors }

The Input is read from the device's own reports. A value is written when the device reports a change and also on a regular sample (every 60 seconds by default, set by **Sample Interval (seconds)** on the Input), so that a steady value does not look stale. A device that does not answer stops producing values, and the device shows a communication failure. Readings the device marks as "no value" are skipped, never stored as zero.

| Measurement | Unit stored |
|---|---|
| Temperature | °C |
| Relative humidity | % |
| Illuminance | lux |
| Contact (open/closed) | on/off |
| Battery | % |
| Pressure | kPa |
| Flow | L/min |
| Occupancy | on/off |
| CO₂ | ppm |
| PM2.5 | µg/m³ |
| Soil moisture | % |
| Power, voltage, current | W, V, A |
| Cumulative energy | kWh |
| Button | press count (a long press is recorded as −1) |

CO₂ and PM2.5 are only added when the device reports them in the unit AoT stores, so a value in another unit is never mis-scaled. The same applies to any value AoT does not recognise: it is ignored.

Contacts, occupancy and buttons also run any **edge Trigger** attached to the Input when the value changes (on = rising, off = falling), the same way a GPIO input does. A button records only when it is pressed, not as a repeating sample.

Battery-powered devices that sleep are read from the device's reports instead of being polled, so that polling does not drain them.

### Outputs { #outputs }

| Device | AoT output | How it behaves |
|---|---|---|
| Switch, plug, relay | On/Off output | Turns on and off |
| Dimmable light | PWM output, 0–100 % | A duty of 1–100 % sets the level; 0 % or off turns it off; "on" without a value turns it on at its previous level. Only devices that identify themselves as dimmable are treated as dimmers: a plain relay plug is never driven as a "30 % level" |
| Curtain, shade, vent window | Value output, 0–100 % **position**, **100 = open** | See below |

Switches and dimmers each get one Output with one channel per endpoint (a two-gang plug is one Output with two channels). Each curtain gets its own Output, so the environment coordinator can use it on its own. A dimmable endpoint becomes a dimmer channel **instead of** a switch channel.

**Curtains and window coverings.** AoT uses 100 = fully open and 0 = fully closed, and converts to the device's own convention (Matter itself uses 0 = open) for you. A device that reports its position moves to the exact percentage. A device that cannot report its position treats 50 % or more as "open" and below 50 % as "close". AoT remembers the last position (while moving, about every 10 seconds), so the [environment coordinator](ai/env-control.md) can use the curtain as a shading or vent actuator.

!!! warning "For a curtain, off means stop, not close"
    A command to switch the curtain **off** stops its movement. It does not close it. This also applies to any feature that uses "off" to mean "closed", such as an emergency stop or an end-of-run action: they stop the curtain where it is. To close a curtain, send the value **0**. (The map's **Close** button and the AI assistant's close command already send 0; their off/stop stops.)

The module names are `MATTER_NODE` (Input), `MATTER_ON_OFF`, `MATTER_LEVEL` and `MATTER_COVERING` (Outputs). Their option lists are in [Supported Inputs](Supported-Inputs.md) and [Supported Outputs](Supported-Outputs.md).

### Matter Devices list { #list }

The **Matter Devices** card lists every device on AoT's fabric.

| Column | Meaning |
|---|---|
| **Device** | Name, maker and model (and the firmware version or update progress) |
| **Sensors and switches** | How many sensor and switch entries AoT created |
| **Reachable** | **Reachable**, or **Not reachable** when the server has lost the device. The server marks a device unreachable about 5 minutes after it stops answering |
| **AoT device** | The AoT device that wraps it, or **No AoT device** |

Buttons on each row: **Read again**, **Share this device**, **Firmware**, **Remove**, and **Create AoT device** (only for a device without an AoT device).

**Read again** re-reads the device and adds sensors or controls that AoT supports now but did not when the device was added (for example after an AoT update). It only adds. Existing channels are left alone, and a dimmable endpoint that was registered as a switch is not converted automatically; remove its switch output, then read again, and it becomes a dimmer.

## Sharing AoT's devices with another app { #share }

You can also go the other way: a device that AoT already controls can be shared onward so that Apple Home, Google Home or another app can use it too.

1. In the **Matter Devices** list press **Share this device** on the device (it must be **Reachable**).
2. A dialog shows an 11-digit code, which you can **Copy**, and the QR code text for apps that ask for it. The code works for 15 minutes. (The sharing window can be between 180 and 900 seconds; the page uses 900.)
3. In the other app choose Add device, then Matter, and enter the code. Most apps accept the 11-digit code instead of scanning.
4. **Keep the dialog open until the other app has added the device.** Closing the dialog, or pressing **Close sharing**, closes the sharing window and the code stops working.

Opening the sharing window again invalidates the earlier code. AoT does not store the code. If the device has no free slot for another ecosystem, AoT refuses before it starts and tells you to remove one of the device's other connections first.

### Connected ecosystems { #fabrics }

The same dialog lists **Connected ecosystems**: every app or hub the device is currently connected to (name, maker, and **Connections used** out of the number the device supports). The row for AoT itself is marked **This is AoT**.

**Disconnect** removes another ecosystem from the device. The other app then loses control of the device and has to add it again. AoT checks the device afterwards to be sure the connection is gone. AoT cannot disconnect itself here: to remove AoT from a device, [remove the device](#remove).

If another app removes AoT from the device ("evicts" it), the device may still look **Reachable** for several minutes. AoT reads the sensors directly from the device, so a sample that fails is not written and the device is shown with a communication failure, and commands fail with an error.

## Firmware updates { #firmware }

**Firmware** opens a dialog with the current version. **Check for an update** asks whether a newer version exists. AoT never installs firmware by itself; a person always starts the update.

AoT installs an update only if:

- it comes from the certified source (the CSA's production distributed compliance ledger). Test and locally supplied images are not certified and AoT refuses them,
- the device is reachable, and
- the device is idle, not already updating.

Press **Update**, and confirm. The device restarts and may be unavailable for a few minutes. **Do not update a device that is controlling something critical at that moment** (a pump, a heater, a vent). Progress (downloading, installing, and so on) shows in the device row.

## Missing and orphan devices { #orphans }

- **Not on the Matter server — share it again to reconnect, or remove it** means AoT still has the device but the Matter server no longer knows it (for example the server's data was reset). Share the device again from the other app: AoT reconnects it to the same AoT device, or press **Remove**.
- **No AoT device** means the device is on AoT's fabric but has no AoT device, for example because the page was closed while it was being added. Press **Create AoT device**.

## Removing a device { #remove }

Press **Remove** on the row (or delete the AoT device on the [Device](Device.md) page). Confirm. AoT then:

1. removes itself from the device, so that it frees its connection slot (this is needed: slots left behind eventually stop other apps from adding the device),
2. deletes the AoT device and its Inputs and Outputs, and
3. keeps the recorded measurement history in the database.

If the device is off or cannot be reached, the removal still goes ahead, but AoT cannot remove itself from the device, and you get a warning. Remove AoT from the device in the other app's list of connected apps.

If anything still uses one of its Inputs or Outputs (a sequence, a PID, a widget, a Trigger), the removal is **refused and nothing is changed**; take it out of those first.

## Permissions and groups { #permissions }

| Action | Permission needed |
|---|---|
| Open the page and see the list | View Settings |
| See a device's **Connected ecosystems** | View Settings, and the device must be in a group you can operate |
| Add (shared or new), **Create AoT device**, **Read again**, **Remove** | Edit Settings **and** Edit Controllers |
| **Share this device**, **Close sharing**, **Disconnect**, firmware check and update | Edit Settings **and** Edit Controllers, and the device must be in a group you can operate |

When [Groups](Configuration-Settings.md#groups) are in use, actions on a specific device (viewing its connections, sharing, disconnecting, firmware) are checked against the groups of its AoT device. A device that has no AoT device belongs to no group, so only users who are not limited to groups (a Role with "Access all groups") may act on it. If the check cannot be made, the action is refused.

## Backups { #backup }

The Matter fabric lives in the `matter_data` volume and is included in AoT backups. It contains the fabric's **root CA private key**. Anyone who has it can control every Matter device that was added to AoT, from inside your network, and if it is lost, every device has to be shared again. See [Upgrade, Backup, Restore](Upgrade-Backup-Restore.md#docker-backup): protect backup files, and note that restoring a backup from the web does not restore `matter_data`.

Do not change the vendor ID or fabric ID after the first start. All existing devices would be orphaned.

## Troubleshooting { #troubleshooting }

When adding fails, AoT gives a reason. The causes map to these cases.

| Message | What to do |
|---|---|
| The Matter server is not reachable | Check that the `matter_server` and `matter_socket` containers are running, and that `COMPOSE_PROFILES=matter` is set |
| The pairing code is not valid | Check the digits and try again |
| The device did not accept the code | The sharing window may have closed: share again and enter the new code. For a new device, check the code on the device or its box |
| The device was not found on the network | The device must be on the same network as AoT and its sharing window still open. Run `aot/scripts/check_matter_host.sh`. For a new device: keep it close to the server, in pairing mode, and check Bluetooth with `--ble` |
| The device did not finish joining in time | Share it again from the other app (or put a new device back in pairing mode) and try again |
| The Matter server did not accept the network details (`network_rejected`) | Check the Wi-Fi name and password, or the Thread dataset |
| Bluetooth is not available to the Matter server (`ble_unavailable`) | Run `check_matter_host.sh --ble` and start the server with `docker-compose.matter-ble.yml` |
| The device could not join the Wi-Fi network (`wifi_failed`) | Check the name and password, and use a 2.4 GHz network if the device needs it |
| The device could not join the Thread network (`thread_failed`) | Check the Thread dataset and that a Thread border router is running |
| The device has no free slot for another ecosystem | Remove one of the device's other connections in that app, then share again |
| The device could not prove it is certified | The AoT server needs internet access to the CSA's device ledger. A development/test device needs `MATTER_TEST_DCL=true` |

Other things to know:

- Values stop coming in, but the device looks **Reachable**: see the eviction case in [Connected ecosystems](#fabrics). Check the device in the other app.
- After a Thread border router or mesh Wi-Fi change, devices can become unreachable for a while. Run the host check again.
