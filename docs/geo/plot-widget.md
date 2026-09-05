# AoT Plot Widget

`AoT_plot` keeps one plot's status on the dashboard. Where the [map widget](map-widget.md#plot) is general-purpose — you click a plot to see it, and its popup closes — this widget is purpose-built for the opposite habit: watching one plot continuously, the way you'd keep an eye on one crop through a season. It deliberately leaves out device control (actuators are the map or facility widget's job); what it shows is that plot's status and schedule, nothing else.

---

## Adding the Widget

1. On the dashboard, select **Add Widget → AoT Plot**.
2. Click **Save** — the widget starts with nothing selected.

!!! note "Which plot to watch is picked in the widget itself"
    There is no "select a plot" field in the settings form. Pick it from the searchable dropdown at the top of the widget body instead — what you're watching changes often enough that reopening settings every time would defeat the point of a monitoring widget.

---

## Choosing a Plot

The dropdown lists every plot from the same shared plot list the map widget uses, searchable by name. Once a plot you can edit is selected, an **Edit** button appears next to the dropdown.

---

## Screen Layout

The body is read-only outside the Edit modal, in four optional blocks:

| Block | Shows |
|---|---|
| **Program stages** | The stage timeline — **the same axis** the [map widget](map-widget.md#plot)'s plot modal draws under [Overview] (stage names, date scale, next stage). One difference: here the segments are **clickable** — the picked one turns green, its dates, targets and guidance unfold below, and the environment card's window follows it. Today is a vertical line; past transitions are dots. |
| **Targets vs now** | Current readings against this stage's targets and limits — the **same card** the [map widget](map-widget.md#plot)'s plot modal shows under [Overview] (it calls the same builder). Every measurement gets its own row and axis, and DLI and [accumulated heat](journal.md#gdd) come along. **[Today][Daily][Weekly]** in the card header pick the window — Daily is the last 7 days (7 points), Weekly the last 8 weeks (8 points). **The unit picks the window too**: a week bucket over a 7-day window would leave a single point, and a range chart needs more than one. Click a stage on the timeline and that stage's span becomes the window. The data is fetched only when you press, so leaving it on [Today] costs nothing. |
| **Trends** | Fills the rows that have no range of their own (CO2, soil moisture, dew point) with a recent trend sparkline. Needs *Targets vs now*. |
| **Notes** | What is coming up, a preview of recent notes, and [Open notes]. The **same block** the map widget's plot modal uses (the shared `AoTNotesBlock`) — it shows this plot's own notes only, never the zone's or facility's. |
| **Accumulated heat** | How far the current stage has come towards the next one in [GDD](journal.md#gdd) (`This stage`). Shown **only when the programme moves stages by GDD** — with date-driven stages the question does not arise. The running total since planting is a separate `GDD` row in the environment card (`Cumulative since start`). |

---

## Editing

**Edit** opens the same drawer as the [`/plots` page](programs.md#plots-page) — literally the same two components, so there is nothing separate to learn. Change the schedule, stage guidance, or this plot's own [target overrides](programs.md#plot-override), then press **Save**. Nothing is sent until you do; closing the modal without saving discards the change.

---

## Widget Settings

| Option | Description | Default |
|---|---|---|
| Program stages | Show the stage timeline block. | On |
| Targets vs now | Show current readings against this stage's targets and limits. | On |
| Trends | Fill rows with no gauge with a recent trend line. Needs *Targets vs now*. | On |
| Accumulated heat | Show this stage's GDD progress (the running total lives in the environment card) | On |
| Refresh Interval | Minutes between reloads. Stages move by the day, so short intervals only add load. | 5 |

---

## Related Pages

- [Management Programs](programs.md#plots-page) — the `/plots` page this widget's editor is built from
- [Map Widget](map-widget.md#plot) — the general-purpose, click-to-open view of a plot
- [Journals](journal.md#gdd) — how accumulated heat and light are calculated
