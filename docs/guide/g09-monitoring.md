---
guide_id: g09-monitoring
title: Monitoring
level: 1
minutes: 30
needs: ["g05-sensors"]
kind: 실습
---

# Monitoring

Once automatic control is running, your job is to check that it keeps running well. In this chapter you decide where to look every day,
and in what order to look for the cause when something goes wrong.

## When you finish this chapter { #goal }

- You know what to look at each day to judge whether everything is normal
- You can find sensors that stopped sending values, devices that do not respond, and functions that stopped

## Before you start { #prepare }

- An AoT system with sensors connected ([Sensor connection](g05-sensors.md#check)). It is better if functions and devices are connected too

## Steps { #steps }

### 1. The one-minute daily check { #step-1 }

| Order | Where to look | Normal |
|---|---|---|
| 1 | The **logo background color** at the top left of the screen | The color has not changed (red = the control core has stopped, gray = the web connection is lost) |
| 2 | Additional Features → **Live Measurements** | Every sensor has a value and a recent time. No "No data for the last N seconds" message |
| 3 | The **Function Status** widget on the dashboard | Functions you turned on are not "Deactivated" and show no error |
| 4 | Your inbox | No [email alert](g08-email.md) has arrived |

If these four are normal, there is nothing more to check that day. If you put items 2 and 3 on one screen as described in
[Dashboard setup](g10-dashboard.md), the check takes one minute.

### 2. Find sensors that stopped sending values { #step-2 }

- **Live Measurements**: An input that stopped sending shows "No data for the last N seconds", and `--` appears in place of the value.
  Inputs that send values on their own, such as MQTT and LoRaWAN, are shown as stopped only after the **Max Measurement Age** has passed.
- Settings → **Inputs**: The card of an input with no value shows `--`.

When you find a sensor that stopped, check in this order.

1. The sensor's power and battery (LoRaWAN sensors go silent without warning when the battery runs out)
2. Whether the equipment in between (gateway, MQTT broker, PLC) is powered on
3. In Manage → **System Log**, set the log to **Daemon** and the minimum level to WARNING, then search for the name of that input.
   If you installed with Docker, some logs in the list (web errors, Nginx, and so on) show as "not found". Looking at **Daemon** and **Web app** is enough.

### 3. Find devices that do not respond { #step-3 }

In Settings → **Outputs**, look for output cards that show **No Response** or **No Connection**. This means a command was sent
but the equipment did not confirm it. For LoRaWAN equipment, check the signal and battery. For wired equipment, check the communication cable and power.

### 4. Find functions that stopped { #step-4 }

- In Settings → **Functions**, check that no function that should be on has been turned off.
- For an environment control function, look at the status header at the top of its settings page to see the current decision and the **Can adjust** devices.
  When a sensor stops, control switches to "hold position" and may look as if it has stopped. In that case, go back to step 2 and check the sensor.
- In the System Log, set the log to **Daemon** and the minimum level to ERROR to see recent errors.

### 5. What to check each week { #step-5 }

| Where to look | What to check |
|---|---|
| Manage → **System Information** | Disk usage is not above 80%, and the daemon is "Running" |
| Manage → **Audit Log** | There are no unknown sign-ins or settings changes |
| Manage → **Upgrade** | Whether a new version is available (do not upgrade right away; read [Cautions](g11-cautions.md#step-2) first) |
| Manage → **Backup Restore** | A recent backup exists |

## Check { #check }

Briefly unplug the power of any one sensor (or turn off a test input). You are done if, a few minutes later, that sensor shows as stopped
in Live Measurements. If you have set up an [email alert](g08-email.md), an email should arrive as well.

## Site A { #site-a }

Site A has many wireless sensors, so **dropouts** are what it checks most often.

- Daily: the times of the six LoRaWAN sensors in 3-1 and 3-2 in Live Measurements
- On irrigation days: in the Sequence Controller widget, whether the valves ran in turn, and whether any valve became No Response
- Weekly: the soil sensor battery values (they arrive with the measurements)

## Site B { #site-b }

At Site B, a single environment control function runs the whole greenhouse, so the **controller status** is checked first.

- Daily: in the Function Status widget, the environment control's target, current value, and Can adjust devices
- If weather station values stop, the vents will not open any further, so also check the wind speed and rain times in Live Measurements.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The logo is red | Manage → System Information → **Restart Daemon**. If it happens again, check System Log → Daemon |
| All sensors stopped at the same time | The problem is not the sensors but a shared path (gateway, broker, site internet) |
| Live Measurements is normal but a graph is empty | Check the period and data source of the graph widget |
| The System Log shows nothing | Lower the minimum level, and turn on debug logging for the function |

## Learn more { #more }

- [Live measurements](../Data-Viewing.md#live-measurements)
- [Viewing logs](../Log-Viewer.md)
- [System information](../System-Information.md)
- [Audit log](../Security.md#audit-log)
