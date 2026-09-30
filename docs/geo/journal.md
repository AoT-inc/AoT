# Journals

A journal is a **point-in-time snapshot** of what was grown, measured, and controlled on a plot, zone, or site over a period you choose — a document you can hand off to a certification body, the next season's grower, or simply keep for your own records.

Journals live under **Additional Features > Journals** (`/geo/journal`).

!!! note "A snapshot, not a live report"
    A journal is generated once and never recalculated. If wiring or a program changes afterward, an already-saved journal still shows exactly what was true when it was made — that is the point of keeping a record.

---

## Generating a journal { #generating-a-journal }

1. Pick a **plot** — one searchable list of every plot, past, present, and planned, grouped by map. Type to search by crop, variety, name, facility, bay, zone, site, or program. Picking one fills the start and end date from that season's own dates; a season still running, with no expected end recorded, gets today where the target is.
2. To cover a whole site or zone instead of one plot, open **Or make a journal for a whole site or zone** and pick from that list — every plot inside it is covered. An area has no season dates, so the start date is filled with the day measurements actually begin there and the end date with today; if nothing has been measured yet, the page says so. The two paths are exclusive — picking one clears the other.
3. **Choose what to include** from a checklist of the measurements the target actually has. Device diagnostic channels — battery voltage, radio signal quality, firmware version, controller internals — start unchecked; turn them on if you want them in the document. A channel that is switched off right now is marked "(currently off)" and also starts unchecked, but can still be included: it may well have been recording during the period. Where a plot has both its own sensors and a weather station, the checklist splits in two — **On-site sensor measurements to include** and **Weather station measurements to include** — so that dropping the weather station's temperature does not drop the on-site one with it.
4. **Choose a recording unit**: Automatic (default), Daily, Weekly, or Monthly.
5. Check the **start** and **end** date, then press **Generate journal**.

The journal is created in the background — the page takes you straight to its permalink, which shows "Generating…" until it is done. Come back to it, or leave the page open; it refreshes itself. In the journal list it carries a "Generating…" badge until it is finished, or "Generation failed" if it could not be made. A build cut short by a restart is marked failed as well, rather than left waiting forever — generate it again.

!!! warning "Large selections are declined, not trimmed"
    Choosing a very wide area or a very long period can be declined before generation starts, with a message telling you to narrow the area or shorten the period. A journal never silently drops part of what you asked for — an incomplete document that looks complete is worse than an error.

### Recording unit — daily, weekly, or monthly { #granularity }

"Recording unit" is the finest unit the document is **saved** at. A finished journal can then be read at that unit or any coarser one:

- **Automatic** saves daily detail. Only where day-by-day storage would hold more than one document can carry does it fall back to weekly, and the document's notes then say that daily detail is not available for it.
- **Daily / Weekly / Monthly** save at that unit regardless of the period's length. A coarser unit makes a smaller document, but it does not make generating one quicker — the same readings are read either way.
- Folding only goes one way — a weekly or monthly journal cannot be un-folded back to daily afterward, since daily detail was never saved.
- **The finished journal is read at a unit you pick on its own page**: Daily, Weekly, Monthly, **By stage** where the plot's program has more than one stage, or **Whole period** as a single folded row. Units finer than the saved one are not offered at all. A journal with stages opens by stage — the first question is usually how each stage went, not what happened on day 37.
- **Weeks anchor to the record's own start date**, not the calendar's Monday — week 1 is the first seven days of the period (or of the plot's growing season), matching how a growing season is actually counted. Only **Monthly** follows the calendar month. A journal saved weekly is the exception: its weeks are calendar weeks starting on Monday.

---

## What is in the document { #contents }

| Section | Content |
|---|---|
| Overview | What/where, the period, the program (plot only), area, time zone |
| Stages | For a plot: each stage's guidance, targets, **and what actually happened during that stage's real span** — measured min/max/average against target, notes, photos |
| Log | One entry per day (or per week/month, [see above](#granularity)) — environment min/max/average against target, accumulated heat and light, irrigation, control device runtime, and any notes written that day. For a plot with stages these entries sit inside each stage, so there is no separate log section. |

- **Environment values carry a target and a Δ (difference)** where the program defines one for that measurement. A day/night-specific target — or [a curve](#curve-target) — is compared against the readings from that window; where the plot has no sensor for it, the log says so instead of guessing a number. Where a sensor on site and the weather station both measure the same thing, the target and Δ are put on the on-site row only.
- **If the target/site has no target defined for anything at all**, the Target and Δ columns are left out of the log table entirely rather than shown empty.
- **A meter's usage** (e.g. a water flow meter) is shown as that day's amount, derived from the meter's own reading — not attached to a particular valve, since nothing in the system records which meter serves which device.
- **Notes** attached to the plot/zone/site, to anything inside it, or simply pinned to a map location within it, all appear on the day they were written.
- **Notes on the devices this document draws its values from appear too** — sensor faults, repairs, valve checks. They are the context needed to read those values: a gap or an odd reading is usually explained there. The device name is shown in front of the note, and no coordinates are required. Notes are captured when the journal is built, so an existing journal has to be regenerated to pick them up.
- Stages outside the period are shown dimmed and labelled either "planned" or "before this journal" — a stage that ended before the period is not called planned. Their guidance and targets sit behind a "Show plan" link, and where a stage repeats the previous stage's targets the table is replaced by one line saying so. Printing expands all of it.
- Log rows follow a fixed reading order rather than an alphabetical one: **light → DLI → GDD → CO₂ → temperature/humidity → VPD → water → wind** — the order a grower actually thinks in. Indoor and outdoor readings share one table: a side indicator marks the outdoor ones, and where a sensor on site measures the same thing the outdoor row is named "Weather station …" as well. A column is labeled with the sensor's own channel name when exactly one sensor covers that measurement and no other row carries that name; otherwise it falls back to the generic measurement name.
- **The table opens on the derived indicators** — DLI, growing degree days, VPD — and "Show N more" opens the remaining measurements in the same table. Where a target has none of those three, the first few rows of the reading order above are shown instead. Several sensors measuring the same thing fold into one row showing the range, with a "N sensors" link that expands them. Printing expands both.
- An average built from less than 80% of that period's hours is marked **"partial coverage"** rather than dropped — a figure resting on half a day should not read like a full one.

---

## Growing degree days (GDD) { #gdd }

Where the program has a [base temperature](programs.md#gdd), the journal shows accumulated heat since the season started, plus each day's (or bucket's) own contribution.

Next to the total, the overview gives how much of it fell inside this journal's period, the base temperature it was counted against, and — where some days had no temperature reading — what share of the days was measured. Each stage carries the total accumulated as of the end of that stage.

If it can't be calculated, the reason is shown in place of a number rather than the row disappearing:

| Reason | Message |
|---|---|
| No program attached to the target | "No program attached" |
| Program has no base temperature set | "The program has no base temperature" |
| Not enough temperature history, no sensor, or too early in the season | "Not enough measured days" |

"A day" means the local calendar day at the target's own time zone — not UTC, and not the server's zone.

---

## Photosynthetic light (DLI) { #dli }

Daily Light Integral is compared against the program's target the same way as any other environment value (value / target / Δ).

Where there is no direct light sensor in the right unit, DLI is estimated on the basis below, and the document's "Notes on accuracy" say which reading it was derived from rather than presenting it as measured:

| Sensor measures | How DLI is estimated |
|---|---|
| PPFD (µmol/m²/s) | Used directly — not an estimate |
| Solar radiation (W/m²) | Converted assuming a standard share of solar energy is photosynthetically active |
| Illuminance (lux/klux) | Converted assuming a standard daylight spectrum |

For a plot under cover, outdoor light is scaled by the facility's [covering material's light transmittance](facility.md#covering-materials) to estimate what actually reaches the crop — a shade curtain is not counted here, only the fixed roof material. The row shows its working ("Weather station 42.3 × cover 0.78"), and the notes name the material and the factor; because the factor comes from the material alone, thickness, age and dust are not counted, so the real figure is usually a little lower. Where the facility has a shade screen, the notes also say that on days it was drawn the crop got less light than shown, since whether it was drawn on any given day is not recorded.

---

## Day length and day/night targets { #daylight }

Sunrise, sunset, and day length are computed from the target's own location and printed on each day's entry. Where a program's target is day- or night-specific, that window is now used to average the matching readings and show a real Δ — previously the target was printed with no comparison at all. If the sensor has no readings inside that window, the Δ is left out for that day rather than guessed.

### Curve targets are compared too { #curve-target }

Where the program puts [a curve](programs.md#targets) on an item, the journal evaluates that curve for the day's crop week and derives **a separate daytime and night-time target**, each compared against the matching measured average. The week is counted as a fraction — the curve interpolates linearly between week keyframes, so the target drifts by a seventh of a week each day (the same basis the controller and the plot modal use). The Target cell shows both values ("Daytime 0.79 · Nighttime 0.45"), the Δ cell shows the two differences, and the line underneath names the curve.

- **It is not folded into a single daily average.** A daily curve moves a lot within the day (a cucumber VPD curve runs from 0.4 before dawn to 1.0 at noon); folded into one number, a humid night and a dry afternoon cancel each other out.
- The calculation happens **when the journal is opened** — the stored record is untouched, so journals created before this feature fill in their Δ simply by being reopened.
- Folded to weeks or months, the target becomes that span's average and the Δ becomes a range ("Daytime -0.41 ~ +0.32"). The same holds across several sensors in one plot: sensors placed differently (inside vs. outside the canopy) can miss the same target in opposite directions, so the range is shown rather than a single folded number.
- On days with no sunrise/sunset (polar day or night), or where the curve has been deleted, the log falls back to naming the curve as before.

---

## Target deviation summary { #drift }

An **"Against target"** table appears for the document and for each stage. It is counted at viewing time from the stored deltas, so journals created before this feature fill in simply by being reopened.

| Target | Day count | Above | Below | Avg | Range |
|---|---|---|---|---|---|
| Night temp (2 sensors) | 30 ~ 48 | 30 ~ 48 | | +5.54 ~ +5.91 °C | +1.66 ~ +9.31 |

**It counts; it does not judge.** Saying "this target does not hold here" would need a tolerance band, and there is none in the data — deliberately so. The table gives day counts, averages and ranges, nothing more.

### Counted per sensor { #drift-sensors }

Where a plot has more than one sensor for the same item, each sensor is counted **separately**. Sensors placed differently — inside vs. outside the canopy, at different heights — often miss the same target in opposite directions.

- When they agree, the row collapses; "2 sensors" expands it. The collapsed values are a **range, not an average** — averaging produces a figure no sensor reported, and mixes the denominators (a sensor that measured 48 days and one that measured 30 become "51 days").
- When they disagree, the row says "Sensors disagree". No single sensor is picked as the representative, because that would not be true either.
- The denominator is **the days that sensor actually measured**, which is what makes a sentence like "exceeded on 48 of 48 days" true.

Printing expands the collapsed sensor rows.

---

## Irrigation volume { #irrigation }

| Plot type | How the amount is worked out |
|---|---|
| Open-field plot | The sprinklers drawn on the map — not the plain placement markers — that sit inside both the plot and the area the serving valve covers. Only that overlap is counted, so no share has to be guessed. |
| Facility plot (in a bay) | The bay's piping design flow rate for the serving valve, times this plot's share of the bay. Where no share is recorded, the whole flow is used rather than nothing. |

Either way, the figure shown is **time run × flow rate × share** — an estimate, not a direct measurement, and it is labelled "estimated". Where the plot also has a real flow meter, its reading is shown as well and is the one to trust. A device whose flow rate is not known leaves the Water column blank, and where no device's flow is known the column is left out altogether and the document's notes say why — neither means no water was used. In a folded (weekly/monthly) log, the volume is **summed** across the period, the same way runtime is.

---

## Weather readings { #weather-readings }

- **Wind direction** is reported as the day's **most frequent compass bearing** (with what share of readings pointed that way), not a plain average — averaging a direction that crosses due north produces a number that points nowhere real. Bearings are named on the 16-point compass (N, NNE, NE, …), in the language you are reading in.
- **The Min and Max columns stay empty on a wind direction row.** A direction has no lowest or highest value, so a number there would be an invented one — the blank is the honest answer, not a fault.
- **Wind direction is left out of the period graphs** and appears in the table only. On a straight axis 359° and 0° — the same direction — would sit at opposite ends of the chart.
- Outdoor readings are shown separately from indoor ones only by a side marker, not a separate table ([see above](#contents)).

---

## Output formats { #output-formats }

The same saved data comes out five ways, from the journal's own page:

| Format | Use |
|---|---|
| **HTML** | The page itself — also the print layout, with a cover page and a glossary/methodology page ahead of the log. **Print (save as PDF)** on the page opens your browser's print dialog. |
| **Markdown** | Download, for pasting elsewhere or editing by hand. It carries the same short explanations of the terms the document actually uses, since whoever receives the file does not have the page's guide. |
| **JSON** | Download, the full saved snapshot, for re-processing with your own tools. |
| **CSV** | Download, the log table only — one row per period/measurement, plus runtime and notes, with untranslated column headers for spreadsheet tools. Runtime rows carry the irrigation volume, and day and night targets and their Δ have columns of their own. |
| **ODT** | Download, a standard word-processor document (cover page, overview, the stages where the plot has them, and full log) that a certification body or the next season's grower can open and add their own notes to. |

Markdown, CSV, and ODT come out at the unit you are currently reading the journal at, so the file matches the page you downloaded it from. JSON is always the stored snapshot, at the unit the journal was saved at. Until a journal has finished generating, a download answers with a short "still being generated" message rather than an empty file.

---

## Adding comments { #adding-comments }

At the bottom of a finished journal is the same notes panel used everywhere else in AoT. Anything written there is a note on the journal itself, and shows up in note search like any other note.

---

## Not covered yet

- A journal is generated by picking a target and period by hand; there is no automated or scheduled generation.
- A facility whose location has not been drawn on the map will not appear in a plot's history list — give it a location under Facility settings first.

---

## Related

- [Management Programs](programs.md) — where a plot's stages, targets, and base temperature come from
- [Facility Management](facility.md) — facility bays, and covering materials used for light transmittance
- [Map Widget](map-widget.md#plot) — where a plot's live GDD/DLI is shown day to day, outside the journal
