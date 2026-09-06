Page: `Setup -> Device`

A device is a composite entry that stands for one piece of hardware — a PLC, a LoRaWAN relay node, or even another AoT server — and gathers the Inputs and Outputs that hardware needs into one place. You enter the connection details once on the device, and they are copied to the Inputs and Outputs the device created.

The page is reached from `Settings -> Device`, listed directly above Input. Devices are kept out of the Function list, so a device is added, edited and deleted only here.

## How a device differs from an Input, an Output, or a Function { #concept }

| Entry | What it stands for |
|---|---|
| Input | One source of measurements. Reads values and stores them in the measurement database. |
| Output | One control. Switches a relay, sets a duty cycle, sends a command. |
| Function | Logic that runs on measurements and outputs (conditional, PID, trigger, and so on). |
| Device | The hardware itself. Holds the connection details, owns the Inputs and Outputs that talk to it, and switches them on and off together. |

A device measures and controls nothing by itself — its Inputs and Outputs do all the work. What it adds is a single place for the connection details, a single list of what belongs to that hardware, and one switch that activates the whole set.

Items that belong to a device are still listed on the Input and Output pages and are still configured there. The device page does not hide them and is not a replacement for those pages.

A device holds membership in two different ways:

| Membership | Meaning | Follows activation |
|---|---|---|
| Owned | The item was created by this device, or it belonged to no device when you linked it. An item has at most one owner. | Yes |
| Reference | The item already belongs somewhere else and is shown in this device as well. Marked **(Reference)** in the list. | No |

Devices can contain other devices. A sub-device is always a reference, never an owned item, and a link that would create a loop (a device ending up inside itself) is refused.

## Adding a device { #adding }

Pick a type in the dropdown at the top of the page — the entries read `Device: <type name>` — and press **Add**.

If the type has a blueprint, its Inputs and Outputs are created at once and are already linked to the device. Their channels are left empty on purpose: register maps and remote measurement lists differ per site and cannot be assumed. You fill the channels in on the Input and Output pages, or, for a remote AoT server, by picking from the list the device discovers after you save the connection details.

Adding, editing, linking and reordering devices requires the **Edit Controllers** permission.

This page has no tabs. Cards are reordered by dragging the handle on the left of each card, and the order is saved as you drop them.

## Built-in device types { #device-types }

| Type | What it creates | Connection details you enter on the device |
|---|---|---|
| Remote AoT Server | A collection Input (`AoT: Remote AoT: Measurements`) and an on/off control Output (`Remote AoT Output: On/Off`) | Remote host (a port may be included), remote API key, protocol (HTTPS/HTTP), TLS certificate verification, request timeout |
| Modbus PLC (Generic) | A Modbus TCP Input and a Modbus TCP Coil Output | Host, port (502 by default), unit/slave ID, timeout, retries |
| AoT-C (Solar 12V Relay Node) | A ChirpStack MQTT telemetry Input and a ChirpStack downlink Output | DevEUI, MQTT broker host/port/credentials/TLS, ChirpStack gRPC server and API key, and an existing LoRaWAN class scheduler to join |
| Custom (no fixed type) | Nothing — an empty container | None. You attach existing Inputs, Outputs and devices yourself. |

The AoT-C type joins an **existing** LoRaWAN class scheduler rather than creating one, so several nodes share a single scheduler.

## The device list { #device-list }

Each card shows, from left to right:

- The drag handle, for reordering.
- The device name. Clicking it copies the device's unique ID to the clipboard.
- A status badge and a count of how many Inputs and Outputs the device owns.
- **Activate** / **Deactivate**.
- The gear icon, which opens the settings drawer.

The badge is derived from what the device's Inputs and Outputs report about their communication, and is refreshed every few seconds:

| Badge | Meaning |
|---|---|
| Device OK | At least one item can report on its communication, and none reports a fault. |
| Fault | At least one item reports a communication fault. |
| Unverifiable | Nothing under this device can report communication status. This is not a failure — most drivers simply have no way to answer the question. |

The count is the number of Inputs and Outputs the device **owns**; referenced items are not counted.

## Device settings { #settings }

The gear icon opens a drawer with these sections, top to bottom:

1. **Basic settings** — name, notes and the map placement for this device (see [Placing a device on the map](#map)).
2. **Advanced Settings** — the device's own options, which for most types means the connection details.
3. **Measurement Channels / Control Channels** — a read-only view of the values and states of the channels under this device (see [Channels](#channels)).
4. **Input / Output** — link and unlink Inputs and Outputs, and see what is linked now (see [Linking](#linking)).
5. **Sub-devices** — the same, for other devices.

The buttons at the bottom are **Close**, **Delete**, **Duplicate** and **Save**.

!!! note
    A device must be deactivated before its settings can be saved. Saving while it is active is refused with an error and nothing is changed. Deactivate, save, then activate again.

## Measurement and control channels { #channels }

This section shows the current value of each measurement channel and the current state of each control channel, and nothing else. It has no buttons: linked Outputs may be simple on/off channels, paired open/close actuators, PWM channels and more, and a single set of controls here would not fit them all.

To operate or configure a channel, use the name links in the **Input / Output** section, which lead to that item's own page.

## Linking existing Inputs, Outputs and devices { #linking }

In the **Input / Output** and **Sub-devices** sections, the searchable dropdown lists everything not yet linked to this device; pick one and press **Link**. What is linked now is listed directly underneath, so the effect of the button is visible right below it.

- An Input or Output that belongs to no device becomes **owned** by this device.
- One that already belongs elsewhere is added as a **reference** and marked accordingly. The same item can be referenced by several devices.
- Another device is always added as a reference, and a link that would create a loop is refused.
- Spacers are not offered as candidates.

**Unlink** removes the membership only. The Input, Output or device itself is untouched and keeps working; it simply no longer appears in this device.

## Activation { #activation }

Activating a device activates the device itself and then the Inputs it **owns**. Deactivating does the reverse.

- Referenced items are never switched by this cascade. Two devices may reference the same Input, and one of them turning off must not stop the other's data.
- Outputs are not part of the cascade. An Output has no activation state of its own; it is registered with the daemon as soon as it is created.
- If an owned Input cannot be activated — most often right after adding a device, when its connection details are still empty — the device still activates and the failure is reported as a warning. Otherwise you could never reach the settings needed to fix it.

## Connection details and how they reach the sub-items { #connection-details }

Connection details entered on the device are copied down to the Inputs and Outputs the device created **every time you save the device**, not only when it is created. At creation those fields are still empty, so the save is the moment the values actually exist.

- The copy is one-way, parent to child. Editing a child directly is never overwritten by the parent for any field outside the copied set.
- Only the fields the device type declares as shared are copied, and only to items the device created. Items you linked yourself keep their own connection details, which you enter on their own pages.
- Only fields with the same name on both sides are copied. Where a driver names the same fact differently, the device type handles that pair explicitly (the AoT-C type does this for the DevEUI).

## Connecting another AoT server { #remote-aot }

The **Remote AoT Server** type treats one other AoT installation as a single device: the collection Input pulls that server's measurements into this one, and the control Output switches its outputs.

What you need before you start:

- The remote server's host or IP address, with a port if it does not answer on the default one (for example `192.168.0.9:8084`).
- An API key **issued on the remote server**, under `Manage -> System Management -> Users`, by editing the user and generating a key. The key is shown once, at the moment it is generated. See [Security](Security.md#api-keys).
- Whether that server is reachable over HTTPS or only over plain HTTP.

!!! note
    An API key carries every permission of the user it belongs to. A key belonging to an administrator grants control of that server's physical devices, not just its readings. For a collection-only connection, use a key with the **Read only** permission, belonging to a remote user whose role only allows viewing settings.

Keep **Verify TLS Certificate** on. While it is off, the API key can be read in transit by anyone between the two servers, and that key can open and close valves on the remote farm.

After you save the connection details:

- The device asks the remote server which measurements it has and fills in the **Remote Measurement** dropdowns on the collection Input, so you do not have to save twice. If the remote server cannot be reached, the save still succeeds and you can retry from the Input page.
- Open the collection Input, set how many measurements you want, pick a remote measurement for each channel, and set each channel's measurement unit to match the one shown in the dropdown.
- The names of the created Input and Output get the remote host appended in parentheses, so you can tell several remote servers apart in lists and graphs. The part before the parentheses is yours and is never rewritten; only the host in parentheses is maintained by AoT. The API key is never put in a name.

A remote PWM output is not part of the blueprint, because most sites do not need one. If you want it, add that Output yourself and link it in the **Input / Output** section — connection details for items you link are entered on the item itself.

## Placing a device on the map { #map }

The map section at the top of the device settings places the device on a map: choose the map, set the position, and set the marker icon, colour and size. A composite device on the map is treated as a container for the devices under it.

Map shapes and facility fittings do not store a device inside themselves. A place — a zone polygon, a facility slot, a sensor role — exists on its own, and a device is bound to it for a period of time. That is why a device can be replaced without redrawing anything, and why graphs continue across a replacement.

## Deleting and duplicating { #deleting }

**Delete** removes the device entry itself. It does not delete its Inputs and Outputs: they remain on their own pages and keep working, and only the record of belonging to this device disappears.

When a device is deleted:

- Its current bindings to places are closed, keeping the history of which hardware occupied which place and when.
- Zone polygons and facility slots are **kept** and become unassigned places, listed as such in the map and facility editors. Only the device's own position marker, which points at nothing once the device is gone, is removed with it.
- Maps are never deleted with a device.

!!! note
    An Input or Output whose owning device was deleted still records that former owner. Linking it into another device therefore attaches it as a reference rather than as an owned item, and the new device's activation will not switch it. Activate such an Input from the Input page.

**Duplicate** copies the device entry only. The new device has no Inputs or Outputs; use the blueprint of a freshly added device, or link items to the copy yourself.
