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
| Advance stages automatically | Records stage changes without asking. **Off by default** ([below](#auto)) |
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
    Targets **do not change control automatically.** The plot modal repeats the same line. Today their purpose is to let people and the AI read the same numbers for "what this stage should aim at".

**An item with a curve shows no number.** Showing the stage value for an item that actually follows a curve would present a figure that is not in use as if it were the target — the screen says "Follows curve: (name)" instead.

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

## Automatic advance { #auto }

Turning on **Advance stages automatically** records changes without asking, for every plot using that program.

- **Off by default.** If it were on by default, stages would advance without anyone having decided anything.
- The recorded date is **derived from the data**, not from when you looked. Opening the plot three weeks later records the same date.
- With no defensible date, nothing is recorded and the question stays for a person.
- Automatic entries are marked **"auto"** in the log.

!!! note "Resources do not become automatic too"
    Even with automatic stage advance, irrigation and fertigation functions are not switched on. That is a separate decision and still needs [Apply].

## Related

- [Design Tool](design-tool.md#plot) — where plots are drawn
- [Map Widget](map-widget.md#plot) — where plots are viewed and operated
- [Facility Management](facility.md) — plots whose location is the bay itself, with no drawing
