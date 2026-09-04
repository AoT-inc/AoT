# Management Programs

A program is a template for **what you grow, in which stages, toward which targets**. Attach one to a plot and the current stage, target environment and expected end date follow automatically.

Programs live under **Settings > Programs** (`/geo/programs`).

!!! note "A program is not a plot"
    A program says "tomatoes, grown in 5 stages like this". A plot says "in house 3, bay 2, from March 2, using that program". **What you draw on the map is the plot**; the program is the setting it refers to. Several plots can share one program.

## Not vegetation-only { #kind }

Every program has a **kind** — Vegetation, Livestock, Facility, Other. The same structure ("what, in which stages, toward which targets") works for greenhouse crops, livestock housing and facility inspection cycles alike.

**Kinds must match.** Only a vegetation program attaches to a vegetation plot — a livestock program would put a plausible-looking stage and target on screen while the whole interpretation is wrong, and nothing would error.

## Creating a program

Pick from the selector above the list and press **Add**.

- **Empty program** — the default. Most people create one subject of their own.
- **Template** — an example to start from. **Templates are not pre-installed** — nothing is created until you add one, so crops you do not grow never fill your list.
- **Copy of one of mine** — for variety-specific versions.

Click the new entry to open the edit drawer.

!!! note "Built-in and external programs cannot be edited"
    **Copy** them instead. If the original were editable, an upgrade or an external refresh would overwrite your change and silently revert it. Read-only programs show no save button at all.

## Fields

| Field | Meaning |
|---|---|
| Name | Shown in the list |
| Kind | Vegetation / Livestock / Facility / Other ([above](#kind)) |
| Applies to | What this program covers — crop, species, animal. Pick from the list or **enter a new one** |
| Variety | Blank means the default for that subject. Filled makes it variety-specific |
| Base temperature | Basis for growing degree days. Blank means stages advance by calendar ([below](#gdd)) |
| Target curves | Attach a Method to an item and it follows a **curve** instead of the stage value |

### The stage table { #stages }

One row per stage.

- **Stage name · key** — the key is the identifier code uses (`seedling`). It is kept alongside the order so stages stay readable after edits.
- **Days** — the **length** of that stage, not a cumulative total. **Only the last stage may be blank**, meaning "until the end".
- **GDD** — the length in growing degree days. Blank means that stage is judged by calendar.
- **[Targets]** — opens that stage's targets and resources. Stages with values are marked ●.

!!! note "Targets are collapsed by default"
    With 7 stages, six fields each would put 42 inputs on screen and the stage structure would disappear behind them.

### Stage targets { #targets }

Day temp · Night temp · Humidity · CO₂ · DLI · VPD.

**Blank fields are not saved** — zero and unset must stay distinguishable.

!!! warning "For display and advice"
    Setting a target does not switch anything on by itself — that still needs an environmental control function to exist and be configured to act on it. A target's job is to let people, the AI, and (where one is configured) the control function read the same number for "what this stage should aim at".

**An item with a curve shows no number on this screen.** Showing the stage value for an item that actually follows a curve would present a figure that is not in use as if it were the target — the screen says "Follows curve: (name)" instead. What the curve actually asked for on a given day, and how far the readings sat from it, is shown split by day and night in [the journal](journal.md#curve-target).

### Overriding targets per plot { #plot-override }

A program's own target is what a **new** plot starts with — after that, each plot can hold its **own** value for any target that isn't following a curve, independently of the program and of every other plot on it.

- **Edit it on the plot, not the program** — from the [`/plots`](#plots-page) page or the [AoT Plot widget](plot-widget.md), never from here.
- The override belongs to that one plot. Changing it never touches the program, and it has no effect on any other plot that shares the same program.
- **Leaving the field blank is how you undo an override** — the plot falls back to the program's own value.
- Curve-driven items are still never editable per plot, for the same reason they show no number above.

### Stage resources { #resources }

One **Function** each for irrigation, fertigation and other.

!!! warning "The program does not switch functions on"
    It only declares them. The plot modal shows the declaration next to the **actual state** ("Irrigation · stopped"), and functions start only when a person presses **[Apply]**. Turning on irrigation means water flows, so it is not automatic.

**[Apply] touches only what is declared.** It never switches anything off — the program does not know the farm's full function list, so switching off would stop unrelated functions.

If a function is deleted later it stays in place as **"Function is gone"**. Dropping it silently would hide the fact that a stage lost its resource.

## Advancing stages by GDD { #gdd }

By calendar alone, a cool spring and a hot summer change stage on the same day. Growth follows accumulated heat, so GDD is used when **all three** are present:

1. the program has a **base temperature**
2. stages have a **GDD** target (if even one is blank, GDD is not used — two bases are never mixed in one program)
3. the plot has at least **80%** temperature history coverage

If any is missing, stages fall back to the calendar and the plot modal states **why** — "By days · No base temperature set", "Not enough temperature history".

The formula is the daily mean: `GDD = max(0, (Tmax + Tmin) / 2 − T_base)`. Temperature comes from sensors inside the plot, falling back to the enclosing zone.

!!! note "Different from the environment-control GDD"
    The env_coordinator function also accumulates GDD, but that one is **for control compensation**, uses a different formula, and requires that function to exist. Open-field plots have no coordinator, so this calculation uses temperature history alone. **The two values differing is normal.**

## Confirming, logging and undoing stage changes { #stage-events }

In the plot modal, **[Overview] > Program**.

When the calculation has moved into the next stage, a **Stage change** row appears. Check or correct the date and press **[Confirm]**.

!!! note "Confirming moves the anchor"
    Confirming "transplanting started on August 4" recalculates the remaining stages **from that day**. The program is a standard and reality does not follow standards, so each confirmed fact realigns what is left. That is why the date is editable — the observed day may differ from the computed one, and that difference drives everything after it.

Confirmed changes accumulate in the **Stage log**. **[Undo last]** reverses the most recent one.

- Entries are **never deleted** — an undone row stays, marked "undone".
- **Only the last** one can be undone; undoing arbitrary entries would make the anchor untraceable.
- A plot that has never been confirmed behaves exactly as before — existing plots are not retroactively asked to approve anything.

!!! note "Nothing advances until you confirm it"
    Once a plot has been confirmed even once, it **stays in its current stage until you confirm the next one** — target environment included — even when the calculation has already moved on. The next-stage row then reads "waiting for your confirmation". (Plots with automatic advance are the exception: that decision has already been made.)

## Editing the schedule — postpone and pull forward { #stage-schedule }

Stage lengths in the program are a **standard**; a plot only **references** them. The real schedule is edited in the plot modal under **[Settings] > Stage schedule**.

- What you edit is **how many days that stage lasts** — the same wording the programme uses, so no date arithmetic. The start date shows beside it as the result.
- Edit the **length** of any stage still ahead and press **[Save]**.
- Changing one stage **moves the ones after it.** To keep a later date fixed, shorten the next stage by the same amount.
- The last stage has no length (**until the end**) — when it ends is decided by ending the plot.
- **Typing the programme's own length back** returns that stage to the standard — there is no separate revert button.

### Stage guidance, adding and removing stages

All in the same table, and the programme is left alone — what you change here applies to this plot only.

- **[Edit]** on a stage opens **both its length field and its guidance box**. Change either, press **[Save]**, and both go in. You can write it even where the programme left none; clearing it brings the programme's own text back.
- **[Remove stage]**, bottom-left of that editor, drops a stage this season does not have (straight to transplanting, no seedling stage). **Stages already passed cannot be removed** — a confirmed change points at them, so removing one loses what was done then. Undo the change first.
- **[Add stage]** below the table opens name and length fields for a stage the standard has no room for (a top dressing, say). It goes last; adjust position with the lengths.
- The **current** stage's guidance shows **plainly under the axis on the [Status] tab** — no click. Other stages' guidance lives in this table.

### Registering the schedule as a programme { #register }

Once you have tuned lengths, added stages and written guidance, that knowledge lives **only in that plot**. **[Register as programme]**, at the bottom of the **[Program]** card on the [Settings] tab, makes it reusable.

- What goes in is the list the plot **actually follows** — stages removed stay out, added stages come along, and the lengths are the **real spans between boundaries**, not the standard. Guidance travels too.
- Targets and target items are copied from the source programme unchanged (the plot never edits them). The reply, however, carries **what this plot actually measured against each target, stage by stage** — median with p25-p75, per sensor. Stage lengths were already updated from the field; targets were the half of that loop that had no way back.
- Asking the AI to register with `adopt_targets` rewrites **only the unambiguous ones** to the measured median. Where two sensors disagree, where the stage has no readings, where a curve is attached, or where the value falls outside the item's defined range, the source value is kept and the reason is given — which sensor to trust is a person's call, not the system's.
- On screen, **pressing [Register] unfolds the comparison right below it** — per stage, `target → this plot's median`, with one line per sensor where they differ. It only shows; nothing is changed by looking.
- **The plot is not moved onto it.** Registering is a copy — changing a running season's interpretation would silently change what it was grown for. Pick the new programme in [Settings] if you want this plot on it too.
- A name already in use gets a number appended.
- Guidance you wrote **survives a stage change.** An observation on a past stage that vanishes on the next transition is worth nothing as a record.
- **[Postpone]** on the Stage change row moves the change to the date shown. **[Confirm]** means "it happened that day" (a fact); **[Postpone]** means "it will happen that day" (a plan).
- Boundaries already past are not edited here — that is what **[Confirm]** and **[Undo last]** are for.
- Setting any date makes that plot judge stages **by date rather than growing degree days**. Clear them all and GDD comes back.
- The expected end date follows the edited schedule.

## Automatic advance { #auto }

Turning on **Advance stages automatically** for a **plot** records changes without asking. It lives in the plot modal under **[Settings] > Stage schedule**.

- **It is set per plot.** Two plots on the same program may differ — whether stages can advance unwatched is a fact about that place, not about the crop.
- **Off by default.** If it were on by default, stages would advance without anyone having decided anything.
- The recorded date is **derived from the data**, not from when you looked. Opening the plot three weeks later records the same date.
- With no defensible date, nothing is recorded and the question stays for a person.
- Automatic entries are marked **"auto"** in the log.

!!! note "Resources do not become automatic too"
    Even with automatic stage advance, irrigation and fertigation functions are not switched on. That is a separate decision and still needs [Apply].

## Managing plots directly { #plots-page }

`/plots` lists every plot — filterable by map, site, zone, and kind, with a switch to include ones that have already ended. **Plots are not created here** — a plot only comes into existence by drawing it in the design tool's [Plot mode](design-tool.md#plot); this page is for managing plots that already exist.

Clicking one opens the same kind of drawer this page uses for programs: schedule (length of each stage), guidance, and that plot's [own targets](#plot-override), all in the one stage track. Nothing leaves the drawer until you press **[Save]**.

The [AoT Plot widget](plot-widget.md) opens the identical drawer from the dashboard, for keeping one plot in view without going to this page. The [map widget's plot popup](map-widget.md#plot) shows the same operational facts but does not edit any of them.

## Related

- [Design Tool](design-tool.md#plot) — where plots are drawn
- [Map Widget](map-widget.md#plot) — where plots are viewed and operated
- [AoT Plot Widget](plot-widget.md) — dashboard widget for keeping one plot in view, with the same editing drawer as this page
- [Facility Management](facility.md) — plots whose location is the bay itself, with no drawing
