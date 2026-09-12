# AoT Plot Widget

`AoT_plot` keeps every currently-growing plot's status on the dashboard. Where the [map widget](map-widget.md#plot) is general-purpose — you click a plot to see it, and its popup closes — this widget is purpose-built for the opposite habit: keeping an eye on your plots continuously, the way you'd watch a crop through a season. It deliberately leaves out device control (actuators are the map or facility widget's job); tap a plot's card to see its status and schedule, and a back arrow returns you to the list.

---

## Adding the Widget

1. On the dashboard, select **Add Widget → AoT Plot**.
2. Click **Save** — the widget opens on the plot list.

!!! note "Fixed size"
    The widget keeps a fixed height rather than growing with its content — the default size is 12 grid units wide by 22 tall. You move between the list, tabs and pages instead of scrolling the widget itself; resize it like any other widget if you want more room.

---

## Plot List

One card per plot that is currently growing — planned plots (not yet started) and ended plots aren't listed. Each card shows:

- **Row 1** — the plot name on the left, and the progress percentage on the right. The percentage can pass 100% once the plot runs past its planned end date, and shows "—" when there's no end date to measure against.
- **Row 2** — a simple stage track: the current stage's segment is filled green, same as the full stage axis on the Stages tab; a plot with no programme has its elapsed portion filled green instead. There's no "today" marker on this track — row 1's percentage already says how far along the plot is.

Tap a card to open that plot's detail.

---

## Plot Detail

The header is the same as the [map widget](map-widget.md#plot)'s plot modal: a back arrow (←) on the left returns to the plot list, and the plot name sits next to it. Below the header are three tabs carried over from that same modal: **Stages**, **Environment**, and **Notes**.

### Stages

The stage-change confirmation, if one is waiting, sits at the top. Below it is the stage card — **the same timeline axis** the map widget's plot modal draws (stage names, date scale, today as a vertical line, past transitions as dots). Segments are tappable — the picked one unfolds that stage's period, targets and guidance below, and, when the programme advances by [GDD](journal.md#gdd) rather than dates, that stage's GDD progress as well.

An **Edit** button appears at the right end of the tab bar, shown only on this tab, and only if you can edit the plot.

### Environment

The same environment card the map widget's plot modal shows — current readings against this stage's targets and limits, with a row and axis per measurement, plus DLI and [accumulated heat](journal.md#gdd) alongside. Rows with no natural range of their own (CO2, soil moisture, dew point) get a trend sparkline instead, when *Trends* is on.

**[Today][Daily][Weekly]** sit at the right end of the tab bar while this tab is open — Daily is the last 7 days, Weekly the last 8 weeks. Picking a stage on the Stages axis makes that stage's span the window, as before.

Readings show **three per page**; with more than three, swipe (or drag with the mouse, or use the arrow keys once focused) left or right to move a whole page. A "1 / 3" page indicator sits below the readings.

### Notes

The latest photo from the plot's notes, then upcoming schedule and recent notes with **[Open notes]** — the same block the map widget's plot modal uses (the shared `AoTNotesBlock`). Only this plot's own notes are shown, never the zone's or facility's.

---

## Editing

**Edit** opens the same drawer as the [`/plots` page](programs.md#plots-page) — literally the same two components, so there is nothing separate to learn. Change the schedule, stage guidance, or this plot's own [target overrides](programs.md#plot-override), then press **Save**. Nothing is sent until you do; closing the modal without saving discards the change. The button itself lives at the right end of the tab bar, on the **Stages** tab.

---

## Remembering Your Place

The widget saves whether the list or a plot's detail was open, which plot, which tab, and the environment view unit ([Today]/[Daily]/[Weekly]) — and restores all of it after a page reload. Saving needs the dashboard's edit permission; without it you can still navigate freely, it just won't be remembered next time.

---

## Widget Settings

| Option | Description | Default |
|---|---|---|
| Map or site | Narrow the plot list to one map, or one site within it — the select groups options by map, each group starting with **[map] · All sites** (the whole map) followed by its sites. Leave empty (**All maps**) to show every plot in progress, across every map. | All maps |
| Program stages | Show the stage axis in the Stages tab. | On |
| Targets vs now | Show the Environment tab. | On |
| Trends | Fill rows with no gauge of their own with a recent trend line, in the Environment tab. Needs *Targets vs now*. | On |
| Accumulated heat | Show this stage's GDD progress in the Stages tab (the running total since planting lives in the environment card). | On |
| Refresh Interval | Minutes between reloads of whichever screen is open — the plot list or the open plot's detail. | 5 |

---

## Related Pages

- [Management Programs](programs.md#plots-page) — the `/plots` page this widget's editor is built from
- [Map Widget](map-widget.md#plot) — the general-purpose, click-to-open view of a plot
- [Journals](journal.md#gdd) — how accumulated heat and light are calculated
