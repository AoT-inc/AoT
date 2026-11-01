---
guide_id: g11-cautions
title: Cautions
level: 1
minutes: 30
needs: []
kind: 설명
---

# Cautions

Once AoT starts moving real equipment, a single small software setting shows up directly on site. This chapter collects in one place
the points where operation most easily leads to accidents. Read it once before installation, and once more after you start operating.

## When you finish this chapter { #goal }

- You know in advance the points where operation easily leads to accidents
- You have set habits to prepare for backups, updates, and power outages

## Before you start { #prepare }

This chapter is reading only. Check the items at the end of each section against your own site.

## Steps { #steps }

### 1. Backups { #step-1 }

- In Manage → **Backup Restore**, click **Create Backup** to save the settings database, uploaded files (notes, notices, facility photos), and user scripts.
- **Measurement history is not included in this backup.** Export measurement values separately on the **Export and Import** page, which opens when you click Additional Features → **Import Export**.
- Only administrators can restore and download backups. Before a restore, AoT automatically makes one more backup of the current state.
- If you installed with Docker, download the backup files **to another computer** in case the AoT computer itself fails.

**Check**: Did you back up before updates and before large settings changes? Is a downloaded backup stored off the AoT computer?

### 2. Updates { #step-2 }

- Write an **exact version** in `AOT_IMAGE_TAG` in `docker/.env`. If something goes wrong, you can go back to the previous version and start it again.
- Control stops during an update. Running irrigation and sequences are interrupted. Update **while the equipment is idle**.
- Automatic updates (the updater) are not postponed even when outputs are on. If you turn them on, set them to a time when no work is scheduled.
- Before updating, make a [backup](#step-1) and read "Upgrade notes" in the release notes.

**Check**: Did you pin the version? Does the update time avoid the equipment's working hours?

### 3. Power outages and restarts { #step-3 }

- An output's **Startup State** is applied when AoT starts. Set valves and pumps to **Off** ([Output connection step 5](g06-outputs.md#step-5)).
- **Shutdown State** is applied only when AoT is shut down normally. It is not applied when power is lost suddenly. In that case, the state the equipment is left in
  depends on the **behavior of the relay or controller**, so check it yourself during installation.
- Sequential irrigation resumes from where it stopped after a restart. Timers also continue their running cycle.
- Environment control remembers its last decision and continues from it. It also remembers the open % of vents and curtains, but if power was lost while they were moving,
  the stored value may differ from reality. After a restart, run **Close** once to realign them.

**Check**: Did you turn the power off and on once, and confirm that all equipment returns to the expected state?

### 4. Safety belongs in hardware { #step-4 }

AoT is software. If communication is lost or the AoT computer stops, it cannot send commands. Prevent situations that could injure people
or damage equipment **with hardware, not software.**

- Vent and curtain motors: end switches (limit switches) and an electrical interlock between open and close
- Pumps: a protection device that prevents running dry, and a pressure switch
- Heaters: an overheat cutoff
- Equipment driven by two relays (open and close) is moved only through a **paired output** ([Output connection step 4](g06-outputs.md#step-4))

**Check**: Is it safe even when AoT is off?

### 5. When a sensor stops sending { #step-5 }

- When an indoor sensor stops, environment control **leaves devices where they are.** When outdoor rain or wind values stop, it does not open the vents any further.
  This can look as if control has stopped, so use [Monitoring](g09-monitoring.md#step-2) to find the sensor that stopped.
- Set up an [email alert](g08-email.md) so that a person learns about the dropout.
- Set the sensor's **Max Measurement Age** to match the interval at which the sensor sends values, so that dropouts are noticed in time ([Sensor connection step 2](g05-sensors.md#step-2)).

### 6. Time { #step-6 }

- Schedules, sequential irrigation, and sunrise/sunset use the time set in this order: **device → zone/land parcel → system time zone**. If you run only one site,
  the system time zone just needs to be correct ([Main settings step 1](g02-settings.md#step-1)).
- Sunrise and sunset are calculated from the site location drawn on the map. If the map location is wrong, the sunrise time is wrong too.
- Graph times may be shown in **the viewer's browser time**. Take care when viewing from another time zone.

### 7. Naming { #step-7 }

Names appear as they are on screen, in alert emails, and in AI answers. If a name is vague, both people and the AI will point to the wrong thing.

- Do not leave default names ("New Design Map", "New site", "Widget Name", "Name", "Output 1").
- **Do not use the same name twice.** Delete functions or controllers you copied for testing once the test is over.
- Put **where and what** in the name: "Environment control: Site B greenhouse", "3-1 valve 1".
- Do not reuse another site's name for maps or devices (for example, "Nursery" at both sites).

### 8. Permissions and AI { #step-8 }

- Administrators and editors can operate devices. Create people who only need to view with the Monitor role.
- When the AI tries to move a device or change a schedule, it runs only after a person approves it on the **AI → Requests** page. Approval
  requests disappear after 15 minutes.
- An API key given to an AI tool is shown only once. If you can make it "read-only", do so.
- If you allow access from outside ([Network connection](g03-network.md)), use long passwords for all accounts.

### 9. LoRaWAN equipment { #step-9 }

- Commands for the whole site wait in a single queue and are sent at least 1.5 seconds apart. If you move several valves at once, the last valve moves late.
- A command that has waited more than 30 seconds is discarded and treated as failed.
- Power-saving devices (Class A) cannot receive a command until they next send a value on their own. This can take several minutes.
- For this reason, **do not use LoRaWAN valves for precise control at short intervals.** They are suited to irrigation measured in minutes.

### 10. Test with virtual equipment { #step-10 }

- Check new functions and new settings first with a **virtual output** and a **test input**, then connect them to real equipment ([Functions step 4](g07-functions.md#step-4)).
- The first time you run real equipment, do it **while a person is next to the equipment**.
- Do not test by clicking around on equipment that is in operation.

## Check { #check }

If you can answer "yes" to all of the questions below, you can start operating.

- A recent backup is stored off the AoT computer
- The version is pinned, and the update time does not overlap with working hours
- You turned the power off and on and saw all equipment return to the expected state
- Hardware protection is in place so that it is safe even when AoT is off
- You are notified by email when a sensor stops sending
- There are no default names or duplicate names

## Site A { #site-a }

- The open-field valves use LoRaWAN, so commands can be late. Set valve run times in the irrigation sequence in minutes.
- If you do not end the greenhouse plot (lettuce) after harvest, environment control keeps using the targets of the last stage. When you harvest, end the plot too.

## Site B { #site-b }

- Site B uses the relays of the existing control panel. If you move the vents with the manual switch on the panel, the open % that AoT remembers no longer matches.
  If you moved them manually, run **Close** once in AoT to realign them.
- If you copied the environment controller to try out settings, delete the one you do not use after testing. With two controllers of the same name, it is unclear which one is running.

## Troubleshooting { #trouble }

If the actual behavior differs from this chapter, check the version ([Installation](g01-install.md#step-4)) and contact support
with the records from Manage → System Log.

## Learn more { #more }

- [Upgrade, backup, and restore](../Upgrade-Backup-Restore.md)
- [Export/import](../Export-Import.md)
- [Outputs](../Outputs.md)
- [Time and time zones](../time-handling.md)
- [Security](../Security.md)
- [LoRaWAN downlink pacing](../LoRaWAN-ChirpStack.md#pacing)
