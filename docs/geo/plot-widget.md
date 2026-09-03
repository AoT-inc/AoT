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
| **Progress** | The stage timeline as a bar — segments for each stage, today marked on it, past transitions shown. |
| **Targets vs now** | Current readings against this stage's targets and limits — the same environment card used in the map widget's zone/facility/plot popups. One measurement gets a gauge; the rest are listed as text. |
| **Trends** | Fills in the rows from the block above that have no gauge with a recent sparkline. Needs *Targets vs now* turned on. |
| **Accumulated heat** | How far the current stage has progressed toward its [GDD](journal.md#gdd) transition threshold — shown only when the program declares a base temperature. |

---

## Editing

**Edit** opens the same drawer as the [`/plots` page](programs.md#plots-page) — literally the same two components, so there is nothing separate to learn. Change the schedule, stage guidance, or this plot's own [target overrides](programs.md#plot-override), then press **Save**. Nothing is sent until you do; closing the modal without saving discards the change.

---

## Widget Settings

| Option | Description | Default |
|---|---|---|
| Progress | Show the stage timeline block. | On |
| Targets vs now | Show current readings against this stage's targets and limits. | On |
| Trends | Fill rows with no gauge with a recent trend line. Needs *Targets vs now*. | On |
| Gauge metric | Which measurement gets the gauge — VPD, Temperature, Humidity, or Soil moisture. Falls back to the first available one if this plot doesn't measure the chosen metric. | VPD |
| Accumulated heat | Show the GDD block. | On |
| Refresh Interval | Minutes between reloads. Stages move by the day, so short intervals only add load. | 5 |

---

## Related Pages

- [Management Programs](programs.md#plots-page) — the `/plots` page this widget's editor is built from
- [Map Widget](map-widget.md#plot) — the general-purpose, click-to-open view of a plot
- [Journals](journal.md#gdd) — how accumulated heat and light are calculated
