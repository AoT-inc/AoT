---
guide_id: g06-outputs
title: Connecting Outputs
level: 2
minutes: 50
needs: ["g05-sensors"]
kind: 실습
---

# Connecting Outputs

Things that AoT turns on and off, such as valves, pumps, fans, and foggers, are called **outputs**. In this chapter you
register outputs, turn them on and off by hand, and join equipment that moves with two lines, "open" and "close",
such as windows and curtains, into one. You also decide what state each output returns to when power goes out and comes back.

## When you finish this chapter { #goal }

- You register devices such as valves, pumps, and foggers as outputs and turn them on and off by hand
- You join windows and curtains that move with two lines, open and close, into one output
- You decide and check what state the devices are in after a power outage or reboot

## Before you start { #prepare }

- AoT with sensors connected ([Connecting Sensors](g05-sensors.md#check))
- Information about the device to connect: what switches it on and off (a relay, a LoRaWAN valve controller, a PLC, equipment that takes commands over MQTT),
  and for windows and curtains, the time (seconds) it takes to move from one end to the other
- If you want to try this first without real equipment: you need nothing. You use a virtual output ([step 1](#step-1))

!!! warning "Make the first connection while someone is next to the equipment"
    When you save an output or restart AoT, the configured startup state can be sent to the equipment.
    Connect at a time when it is safe for pumps, valves, and windows to actually move, and while someone can see the equipment.

## Steps { #steps }

### 1. Add an output { #step-1 }

In Settings → **Output**, choose a type from the list at the top and click **Add**. The type you choose depends on
what switches the device on and off.

| What switches it on and off | Type to choose (end of the name in the list) | Values you must enter |
|---|---|---|
| A relay connected to a Raspberry Pi pin | `Raspberry Pi GPIO` ([step 2](#step-2)) | Pin number, on state (HIGH/LOW) |
| LoRaWAN valve controller | `ChirpStack gRPC` | API Key, DevEUI |
| PLC (Modbus TCP) | `Modbus TCP Coil (PLC)` | Host, port, unit ID, coil address |
| Equipment that takes commands over MQTT | `MQTT Publish` | Hostname, port, Topic, on and off payloads |
| **Practice without equipment** | `Virtual Single-Channel` | None |

For equipment that both sends values and takes commands, such as a LoRaWAN valve controller or a PLC, add the control side here as an **output**.
Add the measurements from the same equipment separately as inputs in [Connecting Sensors](g05-sensors.md).

Name each output **exactly as people call it on site** (for example, "3-1 valve 1", "Side window left"). This name appears in lists, on the map, and in alert emails.
Do not leave default names such as "Name" or "Output 1".

### 2. Connect with Raspberry Pi GPIO or I2C { #step-2 }

This is how you wire a relay board to a Raspberry Pi to switch valves, fans, and pumps on and off.

!!! warning "Not available on a Docker installation"
    AoT installed with Docker cannot use the Pi's GPIO or I2C. Use a [direct installation](g01-install.md#step-5).
    To use I2C, first turn on I2C in raspi-config as in [Connecting Sensors step 5](g05-sensors.md#step-5).

**When you connect a relay directly to a GPIO pin**

| Pi | List name | Fields to fill |
|---|---|---|
| Raspberry Pi 4 or earlier | `Raspberry Pi GPIO (Pi <= 4) [GPIO]` | **Pin: GPIO** (BCM number), **On State** |
| Raspberry Pi 5 | `Raspberry Pi GPIO (Pi 5) [GPIO]` | Same |

- **The pin number is the BCM number**, not the physical pin number on the board (1 to 40). Example: physical pin 11 = GPIO17.
- **On State**: if your relay board switches on with a LOW signal (common with relay modules on the market), change it to **LOW**. If it is set the wrong way,
  clicking "off" turns the relay on. When you first connect, click **Off** and check that the relay switches off before anything else.
- For PWM outputs that adjust brightness or speed, use `PWM: Raspberry Pi GPIO (Pi <= 4) [GPIO]`. The one that uses the pigpio library
  is recommended (you can tell them apart by the gray description in the list). There is no PWM output for Raspberry Pi 5 yet.

**When you use an I2C relay or expansion board**

If you run out of pins, add more channels over I2C. Enter the **I2C Address** and **I2C Bus**, and set the name, on state, and startup/shutdown state for each channel.

| Board | Words in the list name | Default address |
|---|---|---|
| 8-channel expander chip | `PCF8574 8-Channel` | 0x20 to 0x27 |
| 16-channel expander chip | `MCP23017 16-Channel`, `PCF8575 16-Channel` | 0x20 to 0x27 |
| Relay HATs and boards | `Grove Multichannel Relay`, `Sequent Microsystems 8-Relay HAT`, `Sparkfun Relay Board` | See the board manual |
| 16-channel PWM | `PCA9685 16-Channel` | 0x40 and up |

Check the address in the I2C address table under Manage → **System Information**.

**Pins to avoid**

| Pin (BCM) | Already used by |
|---|---|
| GPIO2, GPIO3 | I2C |
| GPIO14, GPIO15 | UART |
| GPIO4 | 1-Wire (when turned on) |
| GPIO7 to 11 | SPI (when turned on) |

!!! note "The click at power-on"
    While the Pi boots, AoT has not yet taken control of the pins, so a pin can float or go HIGH for a moment and the relay may click.
    For equipment that must not switch on at that moment (such as pumps), add a pull-down resistor or choose a pin that stays LOW during boot.
    The [startup state](#step-5) is applied only after AoT is running.

### 3. Turn devices on and off by hand { #step-3 }

Click the **On** and **Off** buttons on the channel row of the output card. The button for the current state is filled with a darker color.
To switch on for only a few seconds, open the output settings with the gear icon on the card, enter seconds in **Duration**, and click **Send**.

Equipment that returns a command confirmation (such as LoRaWAN valves) also shows status text on the channel row.

| Display | Meaning |
|---|---|
| Confirming… | The command was sent and AoT is waiting for the equipment to confirm |
| No response | No confirmation arrived within the set time. The card returns to the previous state |
| No Connection | AoT cannot communicate with the equipment |

With LoRaWAN equipment, "Confirming…" can last from a few seconds to several minutes. Commands wait in a single queue and
go out one at a time (at least 1.5 seconds apart), and depending on the equipment type, AoT waits until the equipment next
contacts it. Moving several valves at once adds to the delay. The detailed behavior is described in
[Downlink: device control](../LoRaWAN-ChirpStack.md#downlink).

### 4. Join open/close equipment into one { #step-4 }

Side windows, roof windows, thermal curtains, and shade curtains usually have one motor with a separate "open" relay and "close" relay.
In AoT, first register each of the two as an output ([step 1](#step-1)), then create one more output that joins them.

1. In Settings → **Output**, add `Actuator Paired`.
   If several windows share one motor power line, choose `Actuator Paired (Shared Bus)`.
2. Choose the **Actuator Kind**: Side Vent, Roof Vent, Thermal Curtain, Shade Curtain, Ball Valve.
3. In **Output: Open** and **Output: Close**, choose the two outputs you created in step 1.
4. In **Travel Time Open (s)** and **Travel Time Close (s)**, enter the time it takes to move from one end to the other.
   AoT uses this time to calculate how many percent open the device is now. If you do not know it, leave it empty and measure it in step 6.
5. After saving, click **Close** on the card so that you start from the fully closed state (0%).

The card of the joined output shows **Close / Stop / Open** buttons and the current open percentage. When changing direction,
it first switches off the relay for the other direction, pauses briefly (**Reverse Pause (s)**, 5 seconds by default), and then moves.

!!! warning "After joining, move the equipment only through the joined output"
    Even if you switch on the "open" or "close" output used for the join directly, AoT switches off the opposite relay first, so the two relays are never on together. However, moving them directly
    makes the **open %** that AoT remembers differ from reality. Always move windows and curtains only through the joined output, and ask the person in charge of the equipment
    whether the motor side has an electrical interlock.

### 5. Set the state after a power outage or reboot { #step-5 }

The channel settings of each output have a **Startup State** and a **Shutdown State**. These values decide what AoT does with that output
when AoT starts and when it stops.

| Device | Recommended startup state | Reason |
|---|---|---|
| Valves, pumps, foggers | Off | So that water does not flow by itself when power returns |
| PLC coils | Do Nothing, or Off | So that AoT does not overturn the state the PLC holds with its own logic |
| Windows and curtains joined with open/close | (no setting) | A joined output has no startup state; it only remembers its **last position** |

!!! note "If power goes out while the equipment is moving"
    If AoT shuts down while a window is moving, the remembered position may differ from reality when it starts again.
    After a restart, click **Close** once to set it back to 0%.

!!! level-2 "Stakeholder"
    Some equipment makes a relay click briefly during the short moment when AoT restarts or when a controller powers up.
    This behavior is a property of the relay board or controller, not an AoT setting. Before installation,
    check it by switching the power off and on, and if it is a problem, block it in hardware.

### 6. Measure the travel time (windows and curtains) { #step-6 }

If you do not know the travel time, in the **Commands** section at the bottom of the joined output's settings, click **Execute** on
**▶ Start Calibration**, and when the window reaches the end, click **Execute** on **■ Stop & Save**. The elapsed time is saved
as the travel time. If opening and closing take different times, change the **Calibration Direction** and measure once more.

If you already know the times, enter them in **Travel Time Open (s)** and **Travel Time Close (s)** and click **Save**.
If you fill in only one of them, the same value is used for the other direction as well.

### 7. Link devices to the map and facilities { #step-7 }

If you place an output on the map, AoT knows which zone or facility the device belongs to. Environment control functions look at this link
to choose which windows and curtains to move.

- Open-field valves: in the device mode of the map design screen, choose the output, show it, and drag it into place
  ([Map design tool](../geo/design-tool.md)).
- Windows, curtains, and foggers inside a facility: in Settings → **Facility** → choose the facility → **Equipment Layout**, click a group such as side windows,
  windows, or curtains in the Components, choose an output from the device list of each slot, and click **Save Facility**. For a slot marked "2 linked",
  choosing one side also links the same output to its paired slot ([Facility management](../geo/facility.md)).

### 8. Reference: the Settings → Device menu { #step-8 }

The Settings menu has a separate item called **Device**. It is meant to group a machine that runs on its own and handles both inputs and outputs,
such as a controller or PLC, into one unit, and **it is still being refined.** This guide does not use it.
Add the equipment's measurements as inputs and its control as outputs. This section will be expanded when the feature is complete.

## Check { #check }

You are done when, as you turn each output on and off by hand, **the equipment actually moves and the card changes to "Active/Inactive"**.

- Valves and pumps: on → check with your own eyes that water comes out → off
- Joined window: close (0%) → open 50% → check that it is about half open → close
- After restarting AoT, check that every output returns to the startup state you set

## Site A { #site-a }

Site A has both open-field valves and facility windows.

- **8 open-field valves** (4 in zone 3-1, 4 in zone 3-2) and 2 pumps. The valves are switched on and off by LoRaWAN valve controllers.
  If you open several at once, the commands go out one after another, so the last valve opens a few seconds later.
  The names show the zone and the order (for example, "3-1 valve 1" instead of "v311").
- **Left and right side windows of the facility (single-span greenhouse)**. For each, the open and close outputs are joined with `Actuator Paired (Shared Bus)`,
  because the two windows share one motor power line.
- **1 fogger**: an on/off output.

## Site B { #site-b }

Site B is a place where AoT was added to existing facility control equipment. The "open" and "close" relays of the existing control panel
are used as they are; in AoT they were only joined, as below.

| Equipment | Existing relays | In AoT |
|---|---|---|
| Side window | 1 open line, 1 close line | `Actuator Paired`, kind = Side Vent |
| Roof window | 1 open line, 1 close line | `Actuator Paired`, kind = Roof Vent |
| Thermal curtain | 1 open line, 1 close line | `Actuator Paired`, kind = Thermal Curtain |
| Fogger | 1 on line | On/off output |

When you use existing equipment, **always measure the travel time again.** Old motors are often slower than the nameplate value,
and it is also common for opening and closing to take different times.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The card goes back to "No response" | Equipment power and communication. For LoRaWAN, the signal between the gateway and the equipment, and whether the equipment contacted ChirpStack recently |
| The joined window does not move | Choose **Output: Open/Close** again and save. If you created the output by duplicating another, these fields are empty |
| The window does not reach the end, or runs too long | The travel time differs from reality. Measure it again with [step 6](#step-6) |
| The displayed % differs from the actual opening | Set 0% with Close, then try again |
| A valve opened after a restart | That output's startup state is set to On |

## Learn more { #more }

- [Outputs](../Outputs.md)
- [Supported outputs](../Supported-Outputs.md)
- [Interface settings](../Interfaces.md)
- [LoRaWAN downlink](../LoRaWAN-ChirpStack.md#downlink)
- [Downlink pacing](../LoRaWAN-ChirpStack.md#pacing)
