---
guide_id: g03-network
title: Network Connection
level: 2
minutes: 50
needs: ["g01-install"]
kind: 실습
---

# Network Connection

To reach an on-site AoT from your office or home, you need an **access path** that reaches the AoT computer at the
site over the internet. However, site internet usually goes through a carrier LTE router or a building router, and these networks **block
connections coming in from outside.** You could open a port on the router (port forwarding), but often there is
no public IP or it changes, and an open port is exposed to the whole internet.

This chapter uses the opposite direction. **The AoT computer opens a connection to the outside first**, and users
come in through that connection. You do not touch the router. This chapter covers two services that do this.

- **Tailscale**: a service that joins your devices (the AoT computer, laptops, phones) across the internet so that
  you can use them like one private network. Only devices logged in with the same account can see each other.
- **Cloudflare Tunnel**: a service that keeps a connection open from the AoT computer to Cloudflare and passes
  visitors who come to your domain address (for example `aot.example.com`) through that connection. People who
  connect need only a browser.

Both services can be started on a free plan. Finally, you will list every connection AoT opens to the outside and
build an allowlist you can hand to the site's firewall administrator.

## When you finish this chapter { #goal }

- You reach AoT from outside without opening a port on the site router
- You know which connections AoT opens to the outside and hand them over as a firewall allowlist

## Before you start { #prepare }

- AoT installed with Docker that opens at `http://<computer IP>:8084` on the site network ([Installation](g01-install.md#check))
- A terminal where you can connect to the AoT computer and type commands
- The device you will connect from (laptop or phone)
- Depending on the method you choose: a Tailscale account, or a Cloudflare account and one domain connected to Cloudflare

## Steps { #steps }

### 1. Choose a method { #step-1 }

| | Method A: Tailscale | Method B: Cloudflare Tunnel |
|---|---|---|
| Who connects | A few administrators | Many people, including first-time visitors |
| On the connecting device | Install the Tailscale app | Browser only |
| Address | Private address (`http://<computer name>:8084`) | Your domain (`https://aot.example.com`) |
| Domain | Not needed | Needed |
| Web encryption | Encrypted by the Tailscale tunnel | HTTPS provided by Cloudflare |
| AoT setting change | None | `AOT_BEHIND_TLS=1` required |

If this is your first time, we recommend **Method A**. It needs fewer settings, and the AoT interface is not exposed to the internet.
You can also use both (Method A for administrators, Method B for visiting inspectors).

### 2. Method A: Connect with Tailscale { #step-2 }

1. Install Tailscale on the AoT computer (**the computer itself**, not a container) and log in.
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
   Open the address shown on screen in a browser and log in. The computer then joins your Tailscale network.
2. Install the Tailscale app on the laptop or phone you will connect from, and log in with **the same account**.
3. In the Tailscale admin console (Machines), check the name of the AoT computer.
4. On the connecting device, open `http://<computer name>:8084`.

Nothing needs to change on the AoT side. **Do not set** `AOT_BEHIND_TLS`.

### 3. Method B: Connect with Cloudflare Tunnel { #step-3 }

1. In the Cloudflare dashboard, go to Zero Trust → Networks → Tunnels, create a new tunnel,
   and choose **Docker** as the connector installation method. Copy the token shown.
2. Start the connector on the AoT computer. When started with `--network host`, the connector reaches port 8084 on the computer directly.
   ```bash
   docker run -d --name cloudflared --restart unless-stopped --network host \
     cloudflare/cloudflared:latest tunnel --no-autoupdate run --token <token>
   ```
3. Add an address (for example `aot.example.com`) to the tunnel's Public Hostname, and set the service to
   `HTTP` · `localhost:8084`.
4. Add one line to `docker/.env` and start AoT again.
   ```bash
   AOT_BEHIND_TLS=1
   ```
   ```bash
   docker compose -f docker/docker-compose.prod.yml up -d
   ```
5. **Put one more front door in place with Cloudflare Access.** In Zero Trust → Access → Applications,
   register the same address and add only the email addresses you want to allow to the policy. Cloudflare then
   asks for email verification before the AoT login screen appears.

!!! warning "With `AOT_BEHIND_TLS=1` turned on, you must use the HTTPS address on site as well"
    When this value is on, the login cookie is sent only over HTTPS connections. If you open `http://<computer IP>:8084`
    on the site network, you cannot log in. Use `https://aot.example.com` on site as well, or keep
    Method A alongside it for on-site use. The detailed reason is in
    [Cookies behind a reverse proxy](../Security.md#behind-tls).

### 4. Build an allowlist for outgoing connections { #step-4 }

If the site firewall also blocks outgoing connections (government offices, schools, factory networks), pick **only the
rows for the features you use** from the tables below and hand them to the administrator. You do not need to ask
for any incoming connection to AoT to be opened.

**Operating system of the AoT computer**

| Purpose | Destination | Port | If blocked |
|---|---|---|---|
| Time synchronization (NTP) | The NTP servers used by the operating system | UDP 123 | The computer clock drifts, and schedule and record times become wrong |
| Installation and update images | `ghcr.io` | TCP 443 | Installation and updates are not possible (a running system keeps running) |
| Tailscale (Method A) | Tailscale coordination and relay servers | UDP 41641, TCP 443 | Remote access is not possible |
| Cloudflare Tunnel (Method B) | Cloudflare tunnel servers | TCP and UDP 7844 | Remote access is not possible |

**Connections AoT opens on its own — these run without any setup**

| Purpose | Destination | Port | If blocked |
|---|---|---|---|
| New version check (every 48 hours) | `ghcr.io` | TCP 443 | Only the "new version" notice does not appear. Can be turned off in settings |
| Internet connection check (when you open the Manage → Upgrade screen on a directly installed AoT; not done on a Docker installation) | `8.8.8.8` (can be changed under **Upgrade Settings** → **Internet Test IP Address** and **Internet Test Port** in General Settings) | TCP 53 | That screen says no internet connection was detected |

**Connections AoT opens — only when you have set up that feature**

| Feature | Destination (examples) | Port | If blocked |
|---|---|---|---|
| Email alerts | The SMTP server you set (for example `smtp.gmail.com`) | TCP 465 or 587 | Alert emails are not sent |
| Weather inputs | The server of each input you added, such as `api.open-meteo.com`, `apihub.kma.go.kr`, `apis.data.go.kr`, `api.openweathermap.org` | TCP 443 | Values stop for that input only |
| MQTT devices | The broker you set | TCP 1883 or 8883 | Values and control for that device stop |
| LoRaWAN (ChirpStack) | The ChirpStack server you set | TCP 8080 (API), 1883 (MQTT) | Device list and downlink control are not possible |
| PLC (Modbus TCP) | The PLC you set | TCP 502 | That device is disconnected |
| Map overlay layers and address/parcel search | The servers of the layers you added (`api.vworld.kr`, `nominatim.openstreetmap.org`, etc.) | TCP 443 | Overlay layers are empty and search does not work |
| AI connection | The AI service you chose (`api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com`, etc.) | TCP 443 | AI chat and summaries do not work |
| Google Calendar integration | `accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com` | TCP 443 | Calendar sync does not work |
| Connection to another AoT server | The AoT address you registered | TCP 443 | Remote device values do not arrive |
| Webhook actions and cameras | The address you entered | The port of that address | Only that feature fails |
| Module dependency installation | `pypi.org`, `files.pythonhosted.org` | TCP 443 | You cannot add inputs or outputs that need dependencies |

**The browser of the person viewing the screen** — the items below are fetched directly by **the device that connects**,
not by the AoT computer. If they are blocked on the viewer's network (an office firewall, for example), they are missing only on that person's screen.

| Purpose | Destination | If blocked |
|---|---|---|
| Base map tiles | The base map server you chose (OpenStreetMap, VWorld, Esri, etc.) | The map background is blank |
| Fonts and some screen effects | `fonts.googleapis.com`, `cdnjs.cloudflare.com` | Text appears in the default font, and some icons and effects are missing |

!!! level-3 "Engineer"
    The only port the AoT containers publish to the outside is the web interface (`AOT_PORT`, default 8084).
    MCP (5700) and InfluxDB (8087) are opened only on `127.0.0.1` by default. If a remote AI client needs to reach
    MCP over Tailscale, set `AOT_MCP_BIND` in `docker/.env` to the computer's Tailscale address.
    Do not open it on `0.0.0.0`.

## Check { #check }

You are done when the login screen opens from outside and you stay logged in when you move to other menus after logging in.

1. Turn off Wi-Fi on your phone (so it uses LTE) and open the Method A or Method B address.
2. After logging in, move through Dashboard → Settings → Dashboard. You must not be sent back to the login
   screen along the way.
3. Open the Manage → Upgrade screen and check that the **Latest Version** appears along with the **Installed Version**. If AoT cannot reach the internet,
   a notice that the image list could not be read appears instead of the latest version.

## Site A { #site-a }

Site A has both open fields and a facility, and its sensors come in by three different methods. So three rows go
into its allowlist.

- LoRaWAN sensors → the ChirpStack server's API (8080) and MQTT (1883)
- Weather inputs → `api.open-meteo.com` and the Korea Meteorological Administration (KMA) API server
- MQTT sensors inside the facility → the broker in use (1883)

Administrators connect with Method A, and visiting inspectors are given the Method B address.

## Site B { #site-b }

At Site B, AoT was added to existing facility control equipment. Sensor values are received from the MQTT broker
on the existing equipment side. So if the broker is on the same building network, there are almost no rows to add
to the firewall (one or two rows for NTP, the image registry and remote access). Method A alone is enough for remote access.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| Right after logging in, the login screen appears again | You came in through an HTTPS address while `AOT_BEHIND_TLS` is off, or through `http://` while it is on. Make the access method and the setting match |
| The Tailscale address does not open | Check that the connecting device and the AoT computer use the same Tailscale account, and that Tailscale shows "Connected" on both |
| 502 error at the Cloudflare address | Check that the Public Hostname service is `localhost:8084` and that the connector was started with `--network host` |
| Only the map background is blank | Most likely **the viewer's network**, not AoT, is blocking the tile server. Open it from a different network (phone LTE) and compare |
| Only alert emails are not sent | Carrier and building networks often block mail ports (25, 465, 587). Try changing to 587. If that does not work, ask the administrator to add the SMTP server address and port to the allowlist |

## Learn more { #more }

- [Cookies behind a reverse proxy](../Security.md#behind-tls)
- [General settings — force HTTPS](../Configuration-Settings.md#general-settings)
- [Alert settings (SMTP)](../Configuration-Settings.md#alert-settings)
- [LoRaWAN (ChirpStack) connection](../LoRaWAN-ChirpStack.md#connection)
