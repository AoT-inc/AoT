# Management Programs

A program is a template for **what you grow, in which stages, toward which targets**. Attach one to a plot and the current stage, target environment and expected end date follow automatically.

Programs live under **Settings > Programs** (`/geo/programs`).

!!! note "A program is not a plot"
    A program says "tomatoes, grown in 5 stages like this". A plot says "in house 3, bay 2, from March 2, using that program". **What you draw on the map is the plot**; the program is the setting it refers to. Several plots can share one program.

## Not vegetation-only { #kind }

Every program has a **kind** — Vegetation, Livestock, Facility, Other. The same structure ("what, in which stages, toward which targets") works for greenhouse crops, livestock housing and facility inspection cycles alike.

**Kinds must match.** Only a vegetation program attaches to a vegetation plot — a livestock program would put a plausible-looking stage and target on screen while the whole interpretation is wrong, and nothing would error.

## Creating a program { #creating-a-program }

Pick from the selector above the list and press **Add**.

- **Empty program** — what the selector starts on. You write the stages yourself.
- **From a template** — a group listing the examples, each with how many stages it has. **Templates are not pre-installed** — nothing is created until you add one, so crops you do not grow never fill your list. It is also the easiest way in: the stages and their lengths arrive filled in, and you change what differs.

The new program is created in the tab you are looking at, and its edit drawer opens straight away with the name ready to change.

**Copying one of your own is not in this selector.** Open the program you want to start from and press **[Duplicate]** in the drawer footer — one way of doing it, and the selector stays short as your list grows.

!!! note "Built-in and external programs cannot be edited"
    **Duplicate** them instead. If the original were editable, an upgrade or an external refresh would overwrite your change and silently revert it. Read-only programs show neither a save nor a delete button — only [Duplicate].

## Fields { #fields }

| Field | Meaning |
|---|---|
| Name | Shown in the list |
| Kind | Vegetation / Livestock / Facility / Other ([above](#kind)) |
| Applies to | What this program covers — crop, species, animal. Pick from the list or **enter a new one** |
| Variety | Blank means the default for that subject. Filled makes it variety-specific |
| Description | What this programme is for, in your own words — read back whenever the programme comes up, including by the AI when it advises on a plot using it |
| Heat unit base temperature | Basis for growing degree days. Under **Advanced settings**, and only on vegetation programmes. Blank means stages advance by calendar ([below](#gdd)) |
| Target curves | Under **Advanced settings**, and only when there is a Method to pick. Attach one to an item and it follows a **curve** instead of the stage value |

### The stage table { #stages }

**Program stages** draws the whole run as one bar — one segment per stage, each as wide as its length, with the total shown as **Whole run**. A segment is a button: press it and that stage alone opens below, drag it sideways to change the order. **[Add stage]**, between the bar and the panel, puts a new stage **right after** the one you have open.

The open stage holds:

- **Stage name** — what this stage is called. The **Stage code** folded away below it is the identifier the system uses (`seedling`); leave it blank and it is made from the name. Changing it on a stage already in use cuts the link to what has been recorded.
- **Days** — the **length** of that stage, not a cumulative total. **Only the last stage may be blank**, meaning "until the end".
- **Heat units** — the same length counted in banked warmth, on vegetation programmes only. Blank means that stage is judged by calendar.
- **Guidance** — what to do in this stage. It is the text someone reads when they open a plot that is in this stage on the map.
- **[Delete this stage]** — at the bottom of the panel.

!!! note "Per-stage targets and resources stay hidden until you ask for them"
    A target box appears in the panel only once **Use different values per stage** is switched on under Targets, and a resource box only once **Different per stage** is switched on under Resources. With them off, every stage aims at the programme's own numbers — with 7 stages, a box on each one would put dozens of inputs on screen and the stage structure would disappear behind them.

### Stage targets { #targets }

A vegetation programme comes with Day temp · Night temp · Humidity · CO₂ · DLI · VPD; Livestock, Facility and Other start with none. Under **Targets** you switch on the items you manage with **In use**, and **[Add item]** makes one of your own — EC, pH, stocking density — with a name, a unit and a measurement type where a sensor reads it (leave that blank and the item is yours to read). The items a programme comes with can be switched off but not deleted: switch one back on later and the values you had are still there, while deleting an item of your own takes its stage values with it.

The number set under Targets is what **every** stage aims at; a stage only holds what **differs** from it, and a value outside that item's own range is refused.

**Blank fields are not saved** — zero and unset must stay distinguishable.

!!! warning "For display and advice"
    Setting a target does not switch anything on by itself — that still needs an environmental control function to exist and be configured to act on it. A target's job is to let people, the AI, and (where one is configured) the control function read the same number for "what this stage should aim at".

**Day temp, Night temp and Humidity are a guide, not a target.** VPD stays the environment coordinator's primary target, but the same VPD can be reached with a combination that is too hot and humid or too cold and dry. The coordinator keeps its temperature and humidity within **the stage value ± 5 °C / ± 10 %** — Day temp between sunrise and sunset at the facility's location, Night temp otherwise — and still inside its hard limits. A stage with no value leaves the facility's own guide range in charge. The coordinator's settings show the range it used as **Guide range**.

**An item with a curve shows no number on this screen.** Showing the stage value for an item that actually follows a curve would present a figure that is not in use as if it were the target — the screen says "Follows curve: (name)" instead. What the curve actually asked for on a given day, and how far the readings sat from it, is shown split by day and night in [the journal](journal.md#curve-target).

### Overriding targets per plot { #plot-override }

A program's own target is what a **new** plot starts with — after that, each plot can hold its **own** value for any target that isn't following a curve, independently of the program and of every other plot on it.

- **Edit it on the plot, not the program** — from the [`/plots`](#plots-page) page or the [AoT Plot widget](plot-widget.md), never from here.
- The override belongs to that one plot. Changing it never touches the program, and it has no effect on any other plot that shares the same program.
- **Leaving the field blank is how you undo an override** — the plot falls back to the program's own value.
- Curve-driven items are still never editable per plot, for the same reason they show no number above.

### Stage resources { #resources }

**Resources** is where the programme says what it needs — **Watering**, **Fertigation** and **Other**, each one a switch. A programme that is not Vegetation is offered **Other** only; no vocabulary for feed or drinking water has been invented yet.

!!! warning "The program does not switch functions on"
    It only declares them. A plot using the programme looks at where it sits and reports whether the equipment for each of these is actually there, so you find out before the crop does. Only watering can be found that way today, and only inside a facility — it is matched to irrigation valves placed on the facility plan. The rest is recorded as intent until there is a way to recognise it.

Each switch here is the **default for every stage**. Turn on **Different per stage** and a stage can switch one of them off — a dry-down before harvest, for instance. Each stage row then says whether it is **"set for this stage"** or **"follows the programme"**, so a stage that was switched off on purpose is not read as an oversight.

The plot's [Overview] shows each declared resource next to the **actual state** — the functions found and "running" or "stopped", or **"No device for this here yet"** where the equipment has simply not been placed. Where nothing could ever match it here — an open-field plot, a role with no vocabulary — the row is left out rather than standing as a permanent complaint. **[Apply]** appears only when something declared was found and is stopped, and it asks before starting anything: turning on watering means water flows.

**[Apply] touches only what is declared.** It never switches anything off — the program does not know the farm's full function list, so switching off would stop unrelated functions. Where one role matches several functions it starts none of them and says so; which valve to run is a person's call.

## Advancing stages by GDD { #gdd }

By calendar alone, a cool spring and a hot summer change stage on the same day. Growth follows accumulated heat, so GDD is used when **all four** are present:

1. the program has a **Heat unit base temperature** (under Advanced settings, vegetation programmes only)
2. stages have **Heat units** (if any but the last is blank, GDD is not used — two bases are never mixed in one program)
3. the plot has at least **80%** temperature history coverage
4. the plot's own schedule has **no dates set on it** — a date you set wins, and stages go by it until you clear them all

If any is missing, stages fall back to the calendar and the plot modal states **why** — "By days · No base temperature set", "Not enough temperature history".

The formula is the daily mean: `GDD = max(0, (Tmax + Tmin) / 2 − T_base)`. Temperature comes from sensors inside the plot, falling back to the enclosing zone. Where the program also carries a **Suggested GDD per day**, the plot shows what has been banked against what that daily rate would have banked over the same days.

!!! note "Different from the environment-control GDD"
    The env_coordinator function also accumulates GDD, but that one is **for control compensation**, uses a different formula, and requires that function to exist. Open-field plots have no coordinator, so this calculation uses temperature history alone. **The two values differing is normal.**

## Confirming, logging and undoing stage changes { #stage-events }

Confirm changes in the plot window under **[Overview] > Stage change**; the stage log and undo are under **[Settings] > Program**.

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

### Stage guidance, adding and removing stages { #stage-guidance-adding-and-removing-stages }

All in the same table, and the programme is left alone — what you change here applies to this plot only.

- **[Edit]** on a stage opens **both its length field and its guidance box**. Change either, press **[Save]**, and both go in. You can write it even where the programme left none; clearing it brings the programme's own text back.
- **[Remove stage]**, bottom-left of that editor, drops a stage this season does not have (straight to transplanting, no seedling stage). **The stage a confirmed change points at, and anything before it, cannot be removed** — removing one loses what was done then. Undo the change first. Until the first change has been confirmed there is nothing to lose, so a season that skips the first stage can drop it outright.
- **[Add stage]** below the table opens name and length fields for a stage the standard has no room for (a top dressing, say). It goes last; adjust position with the lengths.
- The **current** stage's guidance shows **plainly under the axis on the [Overview] tab** — no click. Other stages' guidance lives in this table.

### Registering the schedule as a programme { #register }

Once you have tuned lengths, added stages and written guidance, that knowledge lives **only in that plot**. **[Register as programme]**, at the bottom of the **[Program]** card on the [Settings] tab, makes it reusable.

- What goes in is the list the plot **actually follows** — stages removed stay out, added stages come along, and the lengths are the **real spans between boundaries**, not the standard (the last stage goes in as "until the end"). Guidance travels too.
- **The values this plot actually follows travel with it** — a target you changed on this plot becomes the new programme's number. The target items themselves (their names, units and ranges) are copied from the source programme. The reply also carries **what this plot actually measured against each target, stage by stage** — median with p25-p75, per sensor. Stage lengths were already updated from the field; targets were the half of that loop that had no way back.
- Asking the AI to register with `adopt_targets` rewrites **only the unambiguous ones** to the measured median. Where two sensors disagree, where the stage has no readings, where a curve is attached, or where the value falls outside the item's defined range, the source value is kept and the reason is given — which sensor to trust is a person's call, not the system's.
- On screen, **pressing [Register] unfolds the comparison right below it** — per stage, `target → this plot's median`, with one line per sensor where they differ. It only shows; nothing is changed by looking.
- **The plot is not moved onto it.** Registering is a copy — changing a running season's interpretation would silently change what it was grown for. Pick the new programme in [Settings] if you want this plot on it too.
- **[Register as programme] opens a name box and a [Register] button.** Leave the name blank and one is made from what is planted and this plot's name; a name already in use gets a number appended.
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

`/plots` lists every plot — running, planned and ended alike. The only way to narrow it is the **Search** box, which matches crop, variety, plot name, facility, zone, site, map and program name at once (see [Plots](plots.md#page)). **Plots are not created here** — a plot only comes into existence by drawing it in the design tool's [Plot mode](design-tool.md#plot); this page is for managing plots that already exist.

Clicking one opens the same kind of drawer this page uses for programs: schedule (length of each stage), guidance, and that plot's [own targets](#plot-override), all in the one stage track. Nothing leaves the drawer until you press **[Save]**.

The [AoT Plot widget](plot-widget.md) opens the identical drawer from the dashboard, for keeping one plot in view without going to this page. The [map widget's plot popup](map-widget.md#plot) shows the same operational facts but does not edit any of them.

## Related

- [Design Tool](design-tool.md#plot) — where plots are drawn
- [Map Widget](map-widget.md#plot) — where plots are viewed and operated
- [AoT Plot Widget](plot-widget.md) — dashboard widget for keeping one plot in view, with the same editing drawer as this page
- [Facility Management](facility.md) — plots whose location is the bay itself, with no drawing
