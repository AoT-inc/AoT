# Journals

A journal is a **point-in-time snapshot** of what was grown, measured, and controlled on a plot, zone, or site over a period you choose — a document you can hand off to a certification body, the next season's grower, or simply keep for your own records.

Journals live under **Additional Features > Journals** (`/geo/journal`).

!!! note "A snapshot, not a live report"
    A journal is generated once and never recalculated. If wiring or a program changes afterward, an already-saved journal still shows exactly what was true when it was made — that is the point of keeping a record.

---

## Generating a journal

1. Pick an **area** (a site or zone).
2. If the journal is about one **plot**, a history list appears below the area — every growing season ("plot") that has occupied that ground, past and present, filterable by crop, variety, name, facility/bay/zone/site, or program. Pick one and the start/end dates fill in automatically from that season's actual dates.
3. To cover the whole area instead of one plot, leave the plot field on **Whole area**.
4. **Choose what to include** from a checklist of the measurements the target actually has. Device diagnostic channels — battery voltage, RSSI/SNR, firmware version — start unchecked; turn them on if you want them in the document.
5. **Choose a recording unit**: Automatic (default), Daily, Weekly, or Monthly.
6. Set the **start** and **end** date, then press **Generate journal**.

The journal is created in the background — the page takes you straight to its permalink, which shows "Generating…" until it is done. Come back to it, or leave the page open; it refreshes itself.

!!! warning "Large selections are declined, not trimmed"
    Choosing a very wide area or a very long period can be declined before generation starts, with a message telling you to narrow the area or shorten the period. A journal never silently drops part of what you asked for — an incomplete document that looks complete is worse than an error.

### Recording unit — daily, weekly, or monthly { #granularity }

Data is always kept at **daily** detail internally. "Recording unit" only controls how the finished document folds it for reading:

- **Automatic** keeps daily rows for roughly the first two months of a period and switches to weekly beyond that, so a year-long journal doesn't turn into hundreds of near-identical rows.
- **Daily / Weekly / Monthly** force that grouping regardless of length.
- Folding only goes one way — a weekly or monthly journal cannot be un-folded back to daily afterward, since it was never saved at that level of the document.
- **Weeks anchor to the record's own start date**, not the calendar's Monday — week 1 is the first seven days of the period (or of the plot's growing season), matching how a growing season is actually counted. Only **Monthly** follows the calendar month.

---

## What is in the document { #contents }

| Section | Content |
|---|---|
| Overview | What/where, the period, the program (plot only), area, time zone |
| Stages | For a plot: each stage's guidance, targets, **and what actually happened during that stage's real span** — measured min/max/average against target, notes, photos |
| Log | One entry per day (or per week/month, [see above](#granularity)) — environment min/max/average against target, accumulated heat and light, irrigation, control device runtime, and any notes written that day |

- **Environment values carry a target and a Δ (difference)** where the program defines one for that measurement. Where the target is day/night-specific, or is itself a curve, or the plot has no sensor for it, the log says so instead of guessing a number.
- **If the target/site has no target defined for anything at all**, the Target and Δ columns are left out of the log table entirely rather than shown empty.
- **A meter's usage** (e.g. a water flow meter) is shown as that day's amount, derived from the meter's own reading — not attached to a particular valve, since nothing in the system records which meter serves which device.
- **Notes** attached to the plot/zone/site, to anything inside it, or simply pinned to a map location within it, all appear on the day they were written.
- Stages that haven't started yet within the period are shown dimmed, with a "planned" badge — their guidance and targets are printed, but there is nothing measured to show yet.
- Log rows follow a fixed reading order rather than an alphabetical one: **light → DLI → CO₂ → temperature/humidity → VPD → water → wind** — the order a grower actually thinks in. Indoor and outdoor readings share one table (marked by a side indicator) instead of two separate ones. A column is labeled with the sensor's own channel name when exactly one sensor covers that measurement; with several, it falls back to the generic measurement name.

---

## Growing degree days (GDD) { #gdd }

Where the program has a [base temperature](programs.md#gdd), the journal shows accumulated heat since the season started, plus each day's (or bucket's) own contribution.

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

Where there is no direct light sensor in the right unit, DLI is estimated and marked **"Estimated"**:

| Sensor measures | How DLI is estimated |
|---|---|
| PPFD (µmol/m²/s) | Used directly — not an estimate |
| Solar radiation (W/m²) | Converted assuming a standard share of solar energy is photosynthetically active |
| Illuminance (lux/klux) | Converted assuming a standard daylight spectrum |

For a plot under cover, outdoor light is scaled by the facility's [covering material's light transmittance](facility.md#covering-materials) to estimate what actually reaches the crop — a shade curtain is not counted here, only the fixed roof material.

---

## Day length and day/night targets { #daylight }

Sunrise, sunset, and day length are computed from the target's own location and printed on each day's entry. Where a program's target is day- or night-specific, that window is now used to average the matching readings and show a real Δ — previously the target was printed with no comparison at all. If the sensor has no readings inside that window, the Δ is left out for that day rather than guessed.

---

## Irrigation volume { #irrigation }

| Plot type | How the amount is worked out |
|---|---|
| Open-field plot | The map's own **irrigation coverage areas** — not the placement markers — that actually overlap the plot. Their combined flow rate stands for the whole plot. |
| Facility plot (in a bay) | The bay's piping design flow rate for the serving valve, times this plot's share of that valve's zone. |

Either way, the figure shown is **time run × flow rate × share** — an estimate, not a direct measurement. Where the plot also has a real flow meter, its reading is shown as well and is the one to trust. In a folded (weekly/monthly) log, the volume is **summed** across the period, the same way runtime is.

---

## Weather readings

- **Wind direction** is reported as the day's **most frequent compass bearing** (with what share of readings pointed that way), not a plain average — averaging a direction that crosses due north produces a number that points nowhere real.
- Outdoor readings are shown separately from indoor ones only by a side marker, not a separate table ([see above](#contents)).

---

## Output formats

The same saved data comes out five ways, from the journal's own page:

| Format | Use |
|---|---|
| **HTML** | The page itself — also the print layout, with a cover page and a glossary/methodology page ahead of the log. Use your browser's Print to save as PDF. |
| **Markdown** | Download, for pasting elsewhere or editing by hand. |
| **JSON** | Download, the full saved snapshot, for re-processing with your own tools. |
| **CSV** | Download, the log table only — one row per period/measurement, plus runtime and notes, with untranslated column headers for spreadsheet tools. |
| **ODT** | Download, a standard word-processor document (cover page, overview, and full log) that a certification body or the next season's grower can open and add their own notes to. |

---

## Adding comments

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
