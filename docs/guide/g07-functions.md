---
guide_id: g07-functions
title: Functions
level: 2
minutes: 60
needs: ["g05-sensors", "g06-outputs"]
kind: 실습
---

# Functions

Once sensors send values and devices accept commands, you create the rules that connect the two. In AoT these rules are
called **functions**. "Open the valves one after another at 6 a.m. every day", "Open the windows when the greenhouse gets hot",
and "Send an alert when sensor values stop" are all functions.

## When you finish this chapter { #goal }

- You choose the function type that fits your purpose
- You build open-field sequential irrigation and facility environment control as functions, and test them first without moving equipment

## Before you start { #prepare }

- AoT with sensors and devices connected ([Connecting Sensors](g05-sensors.md#check), [Connecting Outputs](g06-outputs.md#check))
- For facility environment control: the facility, the plots inside it, and the facility sensor slots (indoor and outdoor) must be filled in
- Virtual outputs to use for your first tests ([Connecting Outputs step 1](g06-outputs.md#step-1))

## Steps { #steps }

### 1. Choose the function type { #step-1 }

In Settings → **Function**, choose a type and click **Add**.
A new function is **created in the off state**, so after you finish setting it up you must click **Activate** for it to run.

| What you want to do | Type to choose | When not to use it |
|---|---|---|
| Run several valves in a set order, by day of the week and time window | **Sequence** | When you need to hold a target such as temperature or humidity |
| Move the windows, curtains, and fogging of one greenhouse together to hold the environment | **Integrated Environment Control** | When the same nozzles are also used for irrigation |
| Hold one value at a target (one heater, one fan) | **PID Controller** | When several devices must move together |
| Run something when a condition is met (an alert, turning another function on or off) | **Conditional Controller** | For tasks that simply follow the clock |
| Run at a set time, interval, or sunrise/sunset | A time trigger from the **Trigger** group | When it depends on conditions |
| Do something once on a specific date | Additional Features → **Schedule** | Control that repeats every day |

Do not let **two functions move one device at the same time**. For example, if environment control and a time trigger
both move the same window, they overwrite each other's commands.

### 2. Build sequential irrigation (Sequence) { #step-2 }

1. Add a **Sequence**, open the settings window with the gear icon, and give it a **Name** (for example, "3-1 and 3-2 sequential irrigation").
2. Under **Actions → Add Action**, choose **Output: On/Off/Duration** and click **Add**.
   Add one for the pump and one for each valve.
3. Set each row. Choose the **Output**, and check that **State** is **On**.
   If you leave State empty, the row saves without an error, but that step only turns the device off and never on.
   - Pump: **Operation Mode = Total**. Set **Lead** and **Lag** to a few seconds each so that the pump runs after the valve opens
     and stops before the valve closes.
   - Valves: **Single**, **Default Duration (sec)**. Give valves that should open together the same **Group** name.
   - Click **Save** on the right of each row to save that row.
4. Under **Time Settings**, set the start time, end time, and **Period (sec)**, then click **Save** at the bottom of the window. The period is "the interval at which a full round starts again".
   The default period of a new sequence is 60 seconds, so **be sure to change it before activating.**
5. To make it differ by day of the week, put a **Sequence Controller** widget on the dashboard, choose **Per Day** in the widget, and set
   the time windows for each day (the function settings window has no day-of-week fields).

!!! warning "Match the round time and the period"
    If one round (the sum of all valve run times) is longer than the period, the sequence starts over before finishing the round.
    If the period is too short, it runs dozens of times a day. Example: with a period of 300 seconds from 06:00 to 16:00, it runs 120 times a day.
    Set them so that **sum of valve run times < period < length of the time window**.

To skip watering when the soil is wet, there are two ways.

- Use a Conditional Controller to watch soil moisture and **Deactivate/Activate** this sequence (deactivating stops the round in progress immediately).
- Attach a measurement to **Dynamic Duration Reference** on a valve row, and that value is used as the run time (seconds).

### 3. Build facility environment control (Integrated Environment Control) { #step-3 }

Before you start, link the indoor and outdoor sensor slots ([Connecting Sensors step 7](g05-sensors.md#step-7)) and devices such as windows and curtains
([Connecting Outputs step 7](g06-outputs.md#step-7)) to the facility. Environment control acts only on these links.

1. Add **Integrated Environment Control** (it is in the "Custom Functions" group of the add list).
   Open the settings with the gear icon and rename it so that the facility is clear (for example, "Environment control: Site B greenhouse").
2. In **Linked Facility**, choose the greenhouse. Indoor and outdoor sensors are found automatically from that facility's sensor slots, and windows, curtains, and foggers
   from the devices linked to the facility. To hand over only some bays of the greenhouse, choose a **Bay Scope (optional)**.
3. In **Temperature Range** and **Humidity Range**, enter the limits that must never be crossed (default 12–32 ℃, 40–85 %).
4. The control basis defaults to **VPD** (vapor pressure deficit; it looks at humidity and temperature together). To prioritize temperature, turn on **Advanced** and
   change **Control Basis** to **Temperature first**.
5. Targets come from the **current stage of the plots** inside the facility. If there are no plots, it moves only within the ranges from item 3.
6. Click **Save**, then click **Activate** in the list.

After activating, open the settings again. The **Now** line shows the current values and targets (for example, "Humidity 78→62.5 · Temperature 31→22 · Opening 86%"),
and the **Can adjust** line shows the directions this greenhouse can move (for example, "Temperature down only · Humidity down only").
**Devices under automatic control** lists the devices the controller found, each with an on toggle. To exclude a device from automatic control,
turn its toggle off. You can also see this in the **Function Status** widget on the dashboard.

!!! warning "Settings changed while it is active are not applied"
    While environment control is active, changes to its settings are not applied. Follow the order **Deactivate → change settings → Save → Activate**.

!!! note "What happens when sensor values stop"
    If no new value arrives for twice the sensor period (at least 5 minutes), the sensor is treated as disconnected. If indoor temperature and humidity stop, the decisions that relied on
    those values stop and the devices are **left where they are**. If outdoor rain and wind values
    stop, the windows are kept closed if the last value was rain or strong wind; otherwise they are not opened any further.
    So when a sensor disconnects, control can look as if it has stopped. Find the disconnected sensor in [Monitoring](g09-monitoring.md).

### 4. Test without moving equipment { #step-4 }

1. At first, make the function move **virtual outputs**. For a sequence, set the output of each valve row to a virtual output;
   for environment control, link windows made from virtual outputs to a test facility.
2. Use the [test input](g05-sensors.md#step-6) to enter temperature and humidity values and create conditions.
3. Watch the virtual output cards and the function status, and check that things turn on and off as you expect.
4. Once confirmed, switch the outputs to the real devices and activate **while someone is next to the equipment**.

!!! warning "Do not click \"Execute All Actions\" in a sequence"
    This button runs the actions **all at once**, not in order. In a sequence, every valve and pump can
    switch on at the same time.

### 5. View the records { #step-5 }

Click Manage → **System Log** to open the **Log View** page, and view a function's records there. If you turn off **Enable Debug Logging** in the function settings, only important records
are kept, so keep it on while testing and turn it off when you are done.

## Check { #check }

You are done when, after activating a function, **the devices move in the expected order at the set time or condition, and the function status shows that decision**.

- Sequence: in the first time window, check that the valves open and close in order, and that the pump turns on after the valves and turns off before them
- Environment control: check that **Devices under automatic control** lists all windows, curtains, and foggers, and that the **Now** line shows both current values and targets
- Check that no more than one active function moves the same device

## Site A { #site-a }

Site A has two kinds of functions.

- **Open-field sequential irrigation** (trigger: Sequence): from 06:00 to 16:00, opens the 8 valves of 3-1 and 3-2 one after another, by day of the week.
  To keep the pump from stopping between valves, it is set to **Operation Mode = Total**. A separate sequence gives only 3-2 an extra hour
  each in the evening from 16:00 to 20:00.
- **Greenhouse environment control** (Integrated Environment Control): moves the left and right side windows and the fogger of the single-span greenhouse on a VPD basis.
  Targets come from the stage of the lettuce plot inside the greenhouse. When the lettuce is harvested and the plot is finished, **you must also end the plot**
  so that control does not follow an old target ([Building the Map step 9](g04-map.md#step-9)).

## Site B { #site-b }

At Site B, one Integrated Environment Control handles the whole greenhouse.

- Linked facility: the 6-bay multi-span greenhouse
- Devices it moves: side windows, roof windows, thermal curtains (all outputs joining open/close), fogger
- Target: the flowering stage of the tomato plot (VPD 1.0 kPa), safety range 9 to 36 ℃
- Outdoor values: wind and rain from the weather station. They are the reason to close the windows in strong wind or rain.

If you duplicated the same controller to try out settings, **Delete** the one you do not use. With two controllers of the same name,
it is hard to tell which one is running, and a request to the AI by name may point to the wrong one.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The function does nothing | Whether you **Activated** it. New functions are created in the off state |
| The sequence starts over without finishing a round | The sum of valve run times is longer than the period (see the warning in [step 2](#step-2)) |
| The sequence runs too often in a day | The period is short. Check that you did not leave the default 60 seconds |
| The sequence runs but the valves do not turn on | The **State** of the action row is empty or Off. Change it to **On** and save the row |
| The environment control's Can adjust list is empty | You did not link devices to the facility, or did not choose a linked facility. Run **Reload Actuators** |
| Environment control does not know the indoor values | The indoor sensor is not in a facility sensor slot ([Connecting Sensors step 7](g05-sensors.md#step-7)) |
| A window swings back and forth between two functions | Two functions are moving the same device |
| There is nothing in the log | The log level is not debug ([step 5](#step-5)) |

## Learn more { #more }

- [Functions](../Functions.md)
- [Conditional functions](../Functions.md#conditional)
- [Environment control](../ai/env-control.md)
- [Schedule](../ai/scheduler.md)
- [Supported functions](../Supported-Functions.md)
