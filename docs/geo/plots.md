# Plots

A plot is the unit of a growing plan — **what is being grown, where, since when, and toward what**. A zone says "this area is block 3-1"; a plot says "in this part of block 3-1, lettuce has been there since March 20, following that programme."

!!! note "A plot is not the shape you drew"
    The rectangle, circle or polygon drawn in the [design tool](design-tool.md#plot) is the plot's location. The plot itself is the record attached to it — crop, variety, dates, stage schedule and targets. That is why a plot survives after its season ends: the shape can be redrawn or reused, but the record of what grew there stays.

## Not vegetation-only { #kind }

A plot has a **kind** — Vegetation, Livestock, Facility, Other — the same vocabulary [Management Programs](programs.md#kind) uses. Only a programme of the same kind can attach to it; a livestock programme on a vegetation plot would put a plausible-looking stage and target on screen while the interpretation is wrong, with nothing to flag it. The kind also decides what the crop/variety fields are labelled — "Crop / Variety" for vegetation, "Species / Breed" for livestock, and so on.

## Where a plot lives { #location }

A plot's location comes from where it sits, not from a field you fill in:

- **Ground plots** — drawn on a map, inside a [zone](design-tool.md#editing-modes). Their area comes from the drawn shape.
- **Facility plots** — assigned to a bay of a [facility](facility.md), with no shape to draw. A single-span house has one bay by default; a multi-span house has one per span.

You never pick the enclosing zone or facility yourself — like equipment and devices, it is derived from the plot's position (ground) or its bay assignment (facility).

**Overlapping is allowed.** Intercropping and mixed cropping are normal, so nothing stops two plots from covering the same ground, and the area percentages are not required to sum to 100%.

## Creating a plot { #create }

Plots are not created from the page described below — that page manages plots that already exist. A plot comes into existence by:

- drawing it in the design tool's [Plot mode](design-tool.md#plot), including [splitting a zone into several plots at once](design-tool.md#split);
- assigning a bay to a crop in a facility's vegetation step; or
- [succeeding](#lifecycle) a plot that has just ended, which starts a new one in the same spot.

## The `/plots` page { #page }

`/plots` lists every plot on the farm — active, planned and ended, all at once.

**Viewing is open to everyone**; only editing needs permission (see [Permissions](#permissions)). Nothing is scoped away by group, because "what is planted right now" is information that is fine for anyone to see.

!!! note "Search is the only filter"
    Earlier versions narrowed the list with dropdowns for map, site, zone and kind. Choosing between five dropdowns to find one plot means learning what to pick before you can search — while the person looking almost always already knows the **name** of what they're after. The single search box matches crop, variety, plot name, facility, bay, map, site, zone and programme name at once, so everything the dropdowns did is now typed instead of selected.

    Because search is the only way to narrow the list, the list itself holds **everything**, ended and planned included — a filter that isn't there can't be used to bring back a plot that was excluded before the fetch. Row badges tell past from future apart instead:

    - **Ended** — the season is over; the record stays as history.
    - **In N days** / **Planned** — the start date hasn't arrived yet.

Each row shows the crop and variety, where it is (facility and bay, or map/site/zone), and — depending on what applies — days since planting, the current stage name, its share of the bay, or its area in m². An **Edit** button appears on rows you have permission to change.

## Editing a plot { #edit }

Clicking a row (or opening a plot from the [Plot widget](plot-widget.md) or the [map widget](map-widget.md#plot)) opens the same kind of drawer [Management Programs](programs.md) uses — same shell, same stage track — because the two screens do the same kind of work (fixing a growing schedule in place) and should not require learning twice.

**Nothing leaves the drawer until you press Save.** Closing it without saving discards every change, including any stage-schedule edits made in the same session.

The basics block holds:

| Field | Notes |
|---|---|
| Kind | Vegetation / Livestock / Facility / Other ([above](#kind)) |
| Crop / Variety | Labels follow the kind; variety left blank means "the default for this crop" |
| Plot name | Optional — shown in lists when set |
| Programme | Narrowed to program of the plot's own kind. Attaching one brings in its stage schedule and targets |
| Start date / Expected end | Expected end updates as the schedule is edited elsewhere in the drawer |
| Share (facility plots only) | [Below](#crop) |
| Colour | Optional, for map display |

If you can also edit farm settings, the drawer adds shortcuts next to the bay and programme fields — "Facility settings" and "Create a new programme" — so a missing bay or programme can be fixed without losing the plot you're editing. Those shortcuts are hidden otherwise, since a link to a screen you can't use is not useful.

## Crop, variety and share of the bay { #crop }

For a ground plot, area is not entered here — it comes from the shape drawn in the design tool, and is shown read-only in the plot's row and popups.

For a facility plot, there is no shape, so the drawer instead asks for its **share** of the bay: a single number, interpreted as a count or a percentage depending on whether that bay has a total capacity set (rows, trays, m² or houses) in facility settings. Until a capacity is set, the drawer says so and treats the number as a plain figure rather than a count against a total.

## Stages and schedule { #stages }

A plot attached to a programme gets that programme's stage track: names, lengths, and (if the programme defines them) growing-degree-day targets. From there, everything specific to *this* plot's season — postponing or pulling a stage forward, adding or removing a stage, writing per-stage guidance, confirming a stage transition, and turning on automatic advance — is edited in the same drawer and works exactly as described in [Management Programs](programs.md#stage-schedule). This page does not repeat that mechanics; see:

- [Editing the schedule — postpone and pull forward](programs.md#stage-schedule)
- [Confirming, logging and undoing stage changes](programs.md#stage-events)
- [Advancing stages by GDD](programs.md#gdd)
- [Automatic advance](programs.md#auto)

## Targets: the plot is the plan, the programme is the reference { #targets }

A programme's stage targets are only what a plot **starts with**. Once attached, each plot can hold its **own** value for any target that isn't following a curve — independently of the programme and of every other plot that shares it.

This matters because a coordinator function reads a plot's *current* target, not the programme's. If plots could not carry their own values, the only way to adjust one plot's target would be to edit the programme — which would silently change every other plot on it too. Overriding on the plot instead keeps that adjustment where it belongs.

- **Edit it on the plot** — in this drawer's stage track, or the [Plot widget](plot-widget.md)'s edit drawer (the same component). It cannot be set from the programme screen.
- **Leaving the field blank is how you undo an override** — the plot falls back to the programme's own value. There is no separate revert control.
- Curve-driven targets are never editable per plot, for the same reason they show no number on the programme screen either.

Full mechanics — which items can be overridden, how blank values behave, how curves interact — are in [Overriding targets per plot](programs.md#plot-override).

## Registering the plot's schedule as a programme { #register }

Once a plot's schedule has drifted from its programme — stages postponed, added or removed, guidance written — that knowledge lives only in the plot. **Register as programme**, in the edit drawer's footer, copies what the plot actually follows into a reusable programme, the way **Clone** does on the programmes screen.

The button only appears once the plot has a stage schedule to register. Registering is a **copy**: the plot keeps referencing its current programme, and the new one is available to attach to other plots afterward. See [Registering the schedule as a programme](programs.md#register) for what is copied, how measured targets are compared against the source, and how naming conflicts are handled.

## Ending, succession and deletion { #lifecycle }

This page does not end, succeed or delete a plot — those actions live in the plot's popup on the [map widget](map-widget.md#plot) (and, for bay-based plots, the facility screen). What changes here is what those actions leave behind:

- **Ending** a plot records an end date without removing the row — it keeps appearing on this page, marked **Ended**.
- **Succeeding** a plot ends it and starts a new one in the same spot in a single step, optionally carrying the programme and variety forward.
- **Deleting** a plot removes the row entirely, for miskeyed entries — a normal end of season uses ending instead, so the history stays.

## Journal and dashboard widgets { #related-uses }

A plot's ongoing record continues past this page:

- [Journals](journal.md) — the printable/exportable document for a plot's season: GDD, DLI, day length, irrigation volume, weather, and how closely readings tracked target.
- [AoT Plot Widget](plot-widget.md) — keeps one plot's stage, targets and notes on the dashboard, with the same edit drawer as this page.
- [Map Widget](map-widget.md#plot) — the general-purpose, click-to-open view of a plot's operational status; read-only for targets and schedule.

## Permissions { #permissions }

Viewing this page needs no permission — what is planted where is treated as information anyone on the farm may see. Editing needs `edit_plots`; the facility-settings and create-programme shortcuts in the drawer additionally need permission to edit farm settings, and are simply absent without it.

## Related

- [Management Programs](programs.md) — where a plot's stage track, targets and schedule mechanics are defined in full
- [Design Tool](design-tool.md#plot) — where plots are drawn, and zones split into several at once
- [AoT Plot Widget](plot-widget.md) — dashboard widget with the same editing drawer as this page
- [Map Widget](map-widget.md#plot) — where plots are viewed and operated from the map
- [Journals](journal.md) — the recorded document a plot's season produces
- [Facility Management](facility.md) — bays, which facility plots attach to instead of a drawn shape
