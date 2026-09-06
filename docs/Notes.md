# Notes

Page: `Additional Features -> Notes` — and the same notes panel opens directly from almost anywhere else in AoT.

A note is a short, timestamped piece of text — with optional photos, files, and tags — that you attach to something: a device, a sensor, a plot or zone, a facility, a journal, or just a spot on the map. Use notes for anything you would otherwise write on a sticky note or in a paper logbook: what you observed, what you did, why a reading looks odd, what needs follow-up. Notes are the record most of AoT's other screens (journals, the map, the AI) read from and write to, so a habit of writing them here pays off everywhere else.

---

## Opening notes { #opening }

There is one notes component in AoT (`AoTNotesBlock`), and it opens the same way everywhere: a card with recent entries and an **`Open Notes`** button. You will find it:

- On a device, sensor, controller, or camera's own popup or settings panel
- On a plot, zone, site, or facility card — including inside map popups
- At the bottom of a [journal](geo/journal.md)
- On a pin dropped directly on the map (see [Map visibility](#map-visibility))

Clicking **`Open Notes`** slides in a panel scoped to that one thing — on a desktop it opens beside the page (like the AI chat panel); on a phone it takes the full screen. A zone, site, or facility also shows the notes of everything inside it, so you don't have to open each device separately to see what happened there.

For browsing or managing *every* note in the system at once — searching, filtering by tag, exporting — use the full **Notes Manager** page instead: `Additional Features -> Notes` in the menu.

## Writing a note { #writing }

**From the `Open Notes` panel** (the quick way, used most of the time): type in the box at the bottom and send. You can attach photos or files and add tags from the same composer (the `+` button). The note is timestamped with the current time and saved right away — there is no draft state.

**From the Notes Manager** (`Additional Features -> Notes`): use the `+` button to open the full creation form, which additionally lets you:

- Set a **Subject** by hand, or leave it blank
- Pick a specific **date and time** instead of "now" — useful for logging something after the fact
- Attach multiple files or photos at once

**Smart subject**: if you leave the subject blank (or it's still the default "Quick Note" placeholder), AoT takes the first line of what you wrote as the title automatically, so you rarely need to type one.

**Location**: a note written from something that already has a place on the map (a device, plot, zone, site, or facility) automatically inherits that place's coordinates, even after the thing itself is later removed — the note still shows where it was written. A note made directly on the map gets its own pin (see below).

Editing an existing note's text, tags, or attachments, and deleting a note outright, is done from the Notes Manager list.

## Tags { #tags }

Tags classify notes so you can find them again later. Pick an existing tag or type a new one — new tags are created the moment you use them, there is no separate tag-management step.

AoT also tags a note with the name of whatever it's attached to automatically (a device's name, a zone's name, and so on), in addition to any tags you pick. This is why searching for a device or zone's name in the Notes Manager's tag filter turns up everything ever written about it, even notes where you didn't think to add that tag yourself.

## Map visibility { #map-visibility }

A note written on a device, plot, zone, site, or facility does **not** get its own marker on the map — that thing is already drawn there, and clicking its shape or icon opens the same notes panel. Only a note created directly on a bare map location gets an actual pin, since the pin is the only way to show where that note is.

For that kind of location note, editing it shows a **`Map Widget Visibility`** toggle: turning it off hides the pin from the map without deleting the note — it still exists and still shows up in the Notes Manager and in search.

## Photos and the gallery { #photos }

Attach photos when writing a note; they are resized automatically before upload so large camera photos don't take forever to send. A note with more than one photo shows a strip of thumbnails — click any of them, or the main photo, to open a full-screen viewer with next/previous navigation and pinch-to-zoom. Non-image files (PDFs, spreadsheets, and so on) are listed as a plain download link instead.

## Turning a passage into a schedule { #schedule-link }

Inside the `Open Notes` panel, select some text within an existing note — a bar reading **`Schedule this`** appears. Pick a date and time (and optionally who it's for) and save: AoT creates a scheduled event carrying exactly that text, and the passage stays highlighted in the note so you can see it's linked.

You don't retype anything — the selected text *is* the schedule's content, so the note and the calendar entry never drift apart into two different descriptions of the same thing.

If the note is edited later and that highlighted passage disappears from the text, the link isn't silently dropped or silently kept: it's marked so you can decide — **`Unlink only`** leaves the already-scheduled event in place and just forgets the connection, while **`Cancel the schedule`** removes the event too.

## Searching and exporting { #search }

The Notes Manager (`Additional Features -> Notes`) lists every note in the system, newest first, and loads more as you scroll. Use it to:

- Search note text and subjects
- Filter by one or more tags
- Sort by date (or other fields) in either direction
- Export the current filtered results, or
- Export a **PDF Report** covering a date range and tag combination — a formatted document rather than a raw list, useful for handing a period's notes to someone else

## Notes elsewhere in AoT { #elsewhere }

Notes are a general-purpose record, and two other parts of the manual build on them directly rather than repeating this page:

- **[Device Notes](Device-Notes.md)** covers notes as they're used specifically for devices — a different focus than the general notes system described here.
- **[Journals](geo/journal.md)** pull in every note written on a plot, zone, or site (and on the devices inside it) automatically, arranged by the day they were written, with a notes panel at the bottom of the finished journal for adding more.

## AI and notes { #ai }

The AI can read the notes attached to a zone or device — including looking at photos attached to them, not just the caption text — and can write its own quick notes when you ask it to. See [AI Overview](ai/overview.md) for how this fits into what the AI knows and how its own writes are reviewed.

## For developers { #developer }

Every **`Open Notes`** button in AoT is the same shared component. Any page can open it for a given target by dispatching a browser event:

```js
window.dispatchEvent(new CustomEvent('open-notes', {
  detail: { targetId: 'some-uuid', targetType: 'device', name: 'Zone A / Sensor 1' }
}))
```

Notes, tags, and the note-to-schedule links are also available over the REST API (create, read, update, delete, and toggle map visibility). See [API](API.md) for authentication and general API usage.

---

## Related Pages

- [Device Notes](Device-Notes.md) — notes as used on devices specifically
- [Journals](geo/journal.md) — how notes appear inside a plot/zone/site journal
- [AI Overview](ai/overview.md) — how the AI reads and writes notes
- [API](API.md) — REST API reference
