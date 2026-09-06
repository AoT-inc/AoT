# LoRaWAN (ChirpStack)

AoT connects to LoRaWAN devices through a **ChirpStack v4** network server. Uplinks arrive
over the ChirpStack MQTT broker and become Input measurements; downlinks are queued through
the ChirpStack API by an Output. Both modules are built in.

The connection is configured once under **Settings → ChirpStack**, and from that same page
you select devices already registered in ChirpStack and register them in AoT as Inputs and
Outputs without retyping DevEUIs and keys.

## What AoT does not do { #scope }

AoT is not a LoRaWAN network server and not a gateway manager. It is a ChirpStack *client*.

Everything below stays on the ChirpStack side and has no equivalent screen in AoT:

- Registering the gateway, and the region/channel plan it runs
- Creating tenants, applications, device profiles, and devices (DevEUI, AppKey, join)
- The RX2 data rate — which, as [Downlink pacing](#pacing) explains, AoT's send rate is
  matched to
- Whether a device profile allows Class C

So the order is always: get the device joined and sending uplinks in ChirpStack first, then
bring it into AoT. If a device has never joined, nothing in AoT will make it appear.

## Connecting AoT to ChirpStack { #connection }

### 1. Store the API key { #api-key }

The ChirpStack API key is **not typed on the ChirpStack page**. It is stored in the key
store under **Settings → API Key Management**, and the ChirpStack page only selects which
stored key to use. Add a key there first:

| Field | Notes |
|---|---|
| Name | A label of your choosing — this is what the ChirpStack page's dropdown shows |
| Provider/Manufacturer | Optional. Shown in parentheses after the name in the dropdown |
| API Key | The key value issued by ChirpStack. Paste the token body only |

Paste the token **without a `Bearer ` prefix**. If one is present it is stripped before use,
but keeping the value clean avoids confusion elsewhere.

The permissions of the key decide what AoT can see. An admin key can enumerate tenants and
therefore every application under them. A tenant-scoped key cannot list tenants; AoT detects
this and falls back to listing applications with no tenant filter, so such a key still works
— its devices simply show with an empty Tenant column.

### 2. Fill in the connection { #connection-fields }

Go to **Settings → ChirpStack**:

| Field | Notes |
|---|---|
| ChirpStack gRPC Server | `host:port` of the ChirpStack API. If you omit the port, `:8080` is appended |
| API Token | Pick one of the stored API keys. **Manage API Keys** opens the key store |
| MQTT Broker Host | Host of the broker ChirpStack publishes events to |
| MQTT Broker Port | Usually `1883` |

Press **Save**. **Refresh** re-reads the device list without changing anything.

A scheme (`http://`, `https://`) and any trailing path on the server field are ignored — only
host and port are used. Always give a port when yours is not 8080: without one the client can
resolve to an unreachable address and fail with a confusing "network unreachable" instead of a
clear authentication or connection error.

!!! note "Two different transports"
    The gRPC server address is used for **downlinks and device listing**. The MQTT broker is
    used for **uplinks**. They are separate services and often on different ports of the same
    host, so a working device list does not prove uplinks will arrive, and vice versa.

If the gRPC client libraries are missing, the page shows a notice at the top and the device
list stays empty. They ship in AoT's requirements, so this normally only appears in a
hand-built environment.

### 3. Confirm the device list { #device-list }

With the connection saved, the page lists every device the key can reach, sorted by tenant,
then application, then name, with **Tenant** and **Application** dropdowns to narrow the list.
Each row has a **Details** button showing DevEUI, tenant, application, last seen, and whether
that device is already registered in AoT as an Input or an Output.

A message reading that no devices were found means the key reached ChirpStack but saw nothing
— devices must exist in ChirpStack before they can appear here. An error message instead means
the connection or the key itself failed.

## Registering devices { #onboarding }

The **Device Onboarding** section appears only once the device list is populated. Tick the
devices you want in the table at the bottom, then choose what to create:

**Input (uplink)** — turn on **Register Input** to create one ChirpStack MQTT Input per
selected device. The **Channels** box takes *one JMESPath expression per line*, and the number
of lines becomes the number of measurement channels. Because devices sharing a device profile
send the same payload structure, the same block of expressions usually applies to all of them
at once. Example:

```
object.battery_V
object.node_class
rxInfo[0].rssi
rxInfo[0].snr
```

**Output (downlink)** — turn on **Register Output** to create one ChirpStack downlink Output
per selected device, and give the values that are common to the device profile: the **On
payload** and **Off payload** as hex (for example `010110` / `010210`) and the **FPort** the
firmware listens on.

Then press **Register selected devices**. For each device AoT creates the modules with the
DevEUI, the broker address, and the server and key already filled in, so nothing has to be
retyped per device. Everything created here is an ordinary Input or Output — open it under
[Inputs](Inputs.md) or [Outputs](Outputs.md) to rename it, adjust channels, or change payloads.

!!! warning "Connection values are copied, not referenced"
    Registration copies the current MQTT host and port into each Input, and the current gRPC
    server and API key into each Output. They are a snapshot. If you later change the server
    address or rotate the API key on the ChirpStack settings page, **already-registered Inputs
    and Outputs keep the old values** and must be updated individually. Only the MQTT broker
    used by an Output's confirmation listener is read live from the settings.

Registering the same device twice creates a second module rather than updating the first. Use
the **Registered** line in a device's Details to see what already exists.

## Uplink: reading measurements { #uplink }

The Input created by onboarding is **ChirpStack: MQTT (Payload JMESPath Expression)**. It
subscribes to the ChirpStack v4 uplink topic `application/+/device/+/event/up` and evaluates
one JMESPath expression per channel against each event's JSON.

| Option | Notes |
|---|---|
| MQTT Host / Port | Broker address. Filled from the ChirpStack settings at registration |
| MQTT Username / Password | Optional broker authentication |
| Enable TLS / CA Certificate Path | Optional. Port 8883 is the usual TLS port |
| Subscribe Topics | Comma-separated. Defaults to the ChirpStack v4 uplink topic |
| Device EUIs | Comma-separated filter. Onboarding sets this to the one device |
| QoS, Keepalive, Client ID | Standard MQTT settings |

Per channel there is only a name and the **JMESPath Expression**, evaluated against the whole
event object. Useful starting points:

| Expression | Value |
|---|---|
| `object.battery_V` | A decoded field — whatever your ChirpStack codec produces under `object` |
| `max_by(rxInfo,&rssi).rssi` | Best gateway RSSI for this uplink |
| `max_by(rxInfo,&snr).snr` | Best gateway SNR |

Things worth knowing about how values are stored:

- The expression must resolve to something convertible to a number. A `null` result stores
  nothing for that channel and is not an error — it is how a field absent from one uplink is
  handled.
- An expression that fails to compile disables its channel and is logged once at startup, so
  a typo shows up in the log rather than as silently missing data.
- Measurements are timestamped from the uplink's own `time` field, not from arrival.
- Channels switched off under **Select Measurements to Enable** are dropped just before
  storage. This applies to pushed measurements too, so disabling a channel really does stop
  it being recorded.
- The Input is listener-based. Its **Period** is not a polling interval, and nothing is
  fetched on a schedule.

Communication status for this Input follows the **broker link**, not the device: an uplink
proves the device is alive, but silence does not prove the opposite, since a sensor may
simply have nothing to report. If you need a device to be declared offline after a silence,
build that from measurement age with a Function.

Two other Inputs exist for cases the MQTT path does not cover:

- **ChirpStack: REST API (Payload JMESPath Expression)** polls the ChirpStack REST API on a
  period instead of subscribing. Use it when the broker is not reachable from AoT. It needs
  its own API base URL (the REST proxy is typically on port 8090) and token.
- **RAK3172 Valve Controller: Heartbeat (ChirpStack MQTT)** decodes that firmware's FPort 225
  heartbeat directly — battery, node class, heartbeat period, valve states, RSSI and SNR —
  without JMESPath expressions.

## Downlink: controlling devices { #downlink }

The Output created by onboarding is **On/Off: ChirpStack gRPC**. Turning a channel on or off
enqueues a downlink for the device.

| Option | Notes |
|---|---|
| ChirpStack gRPC Server / API Key | Copied from the settings page at registration |
| DevEUI | The target device |
| FPort | The port the firmware listens on for commands |
| Payload Format | `Hex Bytes` or `JSON Object` |
| On Payload / Off Payload | The frames to send |
| Confirmed | Request a LoRaWAN confirmed downlink |
| Command Timeout (seconds) | How long the commanded state is held optimistically while waiting for the device. Pre-filled with 8 for this module |
| Enable Debug Logging | Logs connection and enqueue notices. Leave off in normal operation |

AoT tries gRPC first and falls back to the REST queue endpoint if the gRPC client is
unavailable or the call fails, including trying port 8090 when the gRPC server is on 8080.
Either way the frame lands in the device's ChirpStack queue.

**Enqueued is not delivered.** A Class C device can be reached at any time. A Class A device
receives a queued downlink only in the receive window that follows its *next uplink*, so on a
long heartbeat interval a command can sit in the queue for a long time. Whether Class C is
permitted is a property of the device profile in ChirpStack; see
[Class scheduling](#class-scheduling) for how AoT drives that.

### Confirmation { #confirmation }

This Output does not assume the device switched just because a frame was queued. It subscribes
to that DevEUI's uplink topic on the MQTT broker and watches for the firmware's acknowledgement
and status frames. Consequences:

- Until a device report arrives, the channel is **pending**, not on. The runtime clock for a
  timed command starts at the device's response, so transmission latency does not inflate the
  reported on-duration.
- ChirpStack v4 does not retransmit an unacknowledged downlink, so AoT retransmits the same
  command itself within the timeout window. The retry interval is a third of the command
  timeout but **never shorter than the pacing interval** — a retry that cannot physically go
  out any sooner would only queue up and expire.
- If the window closes with no confirmation, the command is reported as **failed** and the
  channel returns to the state it had before the command. It does not keep showing a state
  the device never confirmed.
- A channel that gave up unconfirmed is treated as offline: later commands go out **once**, as
  a probe, with no retransmission burst, so an absent device cannot pull the whole site's
  downlink budget. A single confirmation brings it back to normal.

The broker used by this listener is read live from **Settings → ChirpStack**, so if uplinks
work for Inputs but confirmations never arrive, the broker is not usually the cause.

## Downlink pacing { #pacing }

Every downlink in AoT — from Outputs, from the class scheduler, and every retry — passes
through **one site-wide rate limiter**. This is the single most important thing to understand
about a LoRaWAN site that misbehaves under load.

**Why it exists.** A site typically has one gateway, and a gateway is half-duplex: while it is
transmitting it cannot hear anything. A Class C downlink goes out in RX2, and at a low RX2 data
rate a single small frame occupies over a second of transmit time. If commands are queued
back-to-back, the gateway is deaf for most of every minute — precisely when the devices are
sending back the acknowledgements the retry logic waits for. The lost acknowledgements trigger
more retries, which produce more transmit time, which lose more acknowledgements. Field
measurement of exactly this collapse showed acknowledgement-within-5-seconds rates dropping to
around 61%.

**How it behaves.** A minimum gap is enforced between any two downlinks site-wide, and a send
that would have to wait more than 30 seconds for its slot is **dropped and reported as failed**
rather than sent late. A valve command that has waited half a minute is stale anyway, and
releasing a backlog all at once recreates the very flood the pacing exists to prevent.

**The gap is tied to the RX2 data rate**, and the two must move together. The interval is a
built-in constant, not a settings field, so matching it to a different RX2 data rate is a code
change, not a configuration change:

| ChirpStack RX2 data rate | Approx. airtime per frame | Matching gap |
|---|---|---|
| `rx2_dr = 0` (SF12) | ~1.32 s | 4.0 s |
| `rx2_dr = 2` (SF10) | ~0.37 s | 1.5 s — AoT's current value |
| `rx2_dr = 3` (SF9) | ~0.19 s | 0.8 s |

The failure mode to avoid: leaving RX2 at SF12 in ChirpStack while AoT paces for SF10. Each
transmission then occupies most of the interval, the gateway is deaf almost continuously, and
the collapse described above returns. Raising the RX2 data rate without shortening the gap is
merely conservative; shortening the gap without raising the data rate is not.

Two effects of pacing are visible elsewhere and are not faults:

- Activating or reloading many LoRaWAN Outputs takes time, because their startup state frames
  are also paced. AoT deliberately defers those to the background so the daemon starts
  promptly.
- Saving an Output's settings does **not** send its shutdown and startup frames, precisely so
  that renaming a valve does not spend two downlinks and move it. Deleting an Output does
  apply the shutdown state, so the device is left in a safe state.

## Class scheduling { #class-scheduling }

Class C keeps a device reachable at any moment; it also keeps its receiver on, which costs
power. On a battery or solar node, running Class C around the clock is usually the wrong
trade. The **LoRaWAN Class Scheduler** Function is the single per-site authority for that
decision: it toggles Class C support on the shared ChirpStack device profile and broadcasts
the matching heartbeat mode to the devices, so class and heartbeat interval stay consistent
instead of being set per device.

Its main settings:

| Setting | Notes |
|---|---|
| Control mode | `AUTO` scores environmental inputs; `MANUAL` uses a fixed daily Class C window |
| Manual C start / expire | The daily window in `MANUAL` mode |
| Score thresholds, minimum dwell | In `AUTO` mode, when to enter and leave the active state, and the shortest time to stay put |
| Class / heartbeat periods | Heartbeat interval for the active, rest, and winter states |
| Winter start / end | A date range forced to the rest state |
| Battery type | Enables a battery gate — a node too low to spend power is not put into Class C |
| REST Port | The ChirpStack REST port, default 8090. Server and key come from the ChirpStack settings |

There are manual override buttons to force the active state for a number of minutes and to
clear that override. The scheduler has no measurement configuration of its own — telemetry
channels are created when devices are assigned to it.

An older per-device **LoRaWAN Mode/Period Manager (RAK3172E)** Function still exists and works,
but the per-site scheduler replaces it. Prefer one scheduler for many devices over one manager
per device.

## Adding a node as a single device { #device-view }

If a node is both a sensor and an actuator, registering an Input and an Output separately
leaves you managing two entries that share a DevEUI. The **Device** page offers composite
device types that create the pair from one set of connection details — for a ChirpStack relay
node, **AoT-C (Solar 12V Relay Node)**. You enter the DevEUI, the MQTT broker, and the gRPC
server and key once, and the telemetry Input and downlink Output are created and kept in step
with them.

Its **Class Scheduler** field picks an *existing* LoRaWAN Class Scheduler to manage this
DevEUI. It does not create a scheduler — the point is that many devices share one. Leave it
unset to manage the class yourself.

## Troubleshooting { #troubleshooting }

Work down this list in order; each step assumes the ones above it passed.

**The device list is empty or shows an error.**

1. Confirm ChirpStack itself has devices, from its own web interface.
2. Check the gRPC server field: host and port, with the port explicit if it is not 8080. A
   scheme and path are ignored, so those are not the cause.
3. Check that the selected API key's value is the ChirpStack token and not something else. The
   dropdown shows key names, so it is easy to select the wrong stored key.
4. If devices from one tenant are missing, the key is probably scoped to another tenant. An
   admin key sees everything.
5. If the page reports the gRPC client libraries are missing, the environment is incomplete —
   see [Dependencies](Dependencies.md).

**No uplinks reach AoT although ChirpStack shows them.**

1. The device list uses gRPC; uplinks use MQTT. Verify the MQTT broker host and port
   separately, and that AoT can reach the broker (a container may not resolve the same host
   name you use in a browser).
2. Check the Input's **Device EUIs** filter. A DevEUI that does not match the uplink's is a
   silent drop, by design.
3. Check the **Subscribe Topics** field still matches the ChirpStack v4 uplink topic.
4. Set the Input's log level to debug and watch the log: the evaluated expression and its
   result are logged per uplink. An expression resolving to `null` — a wrong path, or a codec
   that is not decoding — is the usual cause of an Input that connects but stores nothing.
5. Confirm the channel is enabled under **Select Measurements to Enable**. A disabled channel
   is discarded just before storage.
6. Confirm ChirpStack's codec is actually decoding the payload. If `object` is empty in the
   event JSON, no expression under `object.` can produce a value.

**Commands do not reach the device.**

1. Check the device's class. On Class A, a queued downlink waits for the next uplink; on a
   long heartbeat that can be many minutes.
2. Look at the device's queue in ChirpStack. Frames sitting in the queue mean AoT's side
   worked and delivery is the problem. An empty queue with a failure in AoT means the enqueue
   itself failed — check the gRPC server and key on that Output, remembering they were copied
   at registration and may be stale.
3. If commands fail in bursts while single commands succeed, this is [pacing](#pacing).
   Confirm ChirpStack's RX2 data rate matches what AoT paces for, and reduce how many devices
   are switched at the same instant.
4. If the Output reports failures but the devices actually did switch, confirmations are not
   getting back: check the MQTT broker settings, and that the firmware's acknowledgement port
   and format are the ones this module expects.
5. Repeated failure on one channel marks it offline, after which commands go out only as
   single probes. That is intended, and one successful confirmation clears it.

**Everything works, then degrades under load.** This is the pacing and RX2 interaction almost
every time. Read [Downlink pacing](#pacing) before changing timeouts — raising the command
timeout to buy more retries makes a saturated link worse, not better.

For general device and daemon issues, see [Troubleshooting](Troubleshooting.md).
