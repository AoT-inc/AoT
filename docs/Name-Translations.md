Page\: `[Admin] -> Configure -> Name Translations`

AoT ships with the interface itself translated into more than a dozen languages, but the *names* on your farm — device names, zone names, crop names, dashboard titles, and so on — are things you typed in yourself. Nothing in the software can know in advance what to call them in every language. Name Translations is the settings page where AoT keeps (and lets you correct) the translations it has generated for those names, so that a farm built in Korean can still be read comfortably by someone who set their account to Japanese, or English, or any other supported language.

The names you typed are never changed. What this page manages is a separate translation shown on screen for each one, per language. The stored name stays exactly as you wrote it.

## Not the interface language setting { #not-the-interface-language-setting }

It is easy to confuse this with `Language` under [General Settings](Configuration-Settings.md#general-settings), so it is worth being explicit about the difference.

<table>
<thead>
<tr class="header">
<th>Setting</th>
<th>What it translates</th>
</tr>
</thead>
<tbody>
<tr>
<td>Language (General Settings)</td>
<td>The interface itself — button labels, menu items, field names, messages. This text is built into AoT and shipped already translated.</td>
</tr>
<tr>
<td>Name Translations</td>
<td>Names you typed in yourself — a device called "1번 하우스 온도", a zone called "동편 밸브", a crop plot named "콩밭". None of this text exists until you create it, so it cannot ship pre-translated.</td>
</tr>
</tbody>
</table>

The two systems never mix. A name you gave a device is not run through the interface's translation catalog, and interface text is never treated as a name to translate.

## What this translates { #what-this-translates }

The dictionary this page manages covers names from across the system:

<table>
<thead>
<tr class="header">
<th>Category</th>
<th>What is collected</th>
</tr>
</thead>
<tbody>
<tr>
<td>Device</td>
<td>Input, Output, and Camera names.</td>
</tr>
<tr>
<td>Measurement</td>
<td>Input Channel, Output Channel, and Device Measurement names.</td>
</tr>
<tr>
<td>Function</td>
<td>PID, Function, Conditional, Trigger, and Method names.</td>
</tr>
<tr>
<td>Dashboard</td>
<td>Dashboard and Widget names.</td>
</tr>
<tr>
<td>Zone</td>
<td>Map, layer, facility, and 3D model asset names, plus the names/labels stored on drawn map shapes.</td>
</tr>
<tr>
<td>Crop</td>
<td>Plot name, subject, and variety; a management program's subject and variety.</td>
</tr>
<tr>
<td>Program</td>
<td>A management program's name, and the stage names inside it (for example "육묘", "정식", "개화") and any custom target labels it defines.</td>
</tr>
<tr>
<td>Note</td>
<td>Note titles and note tag names.</td>
</tr>
<tr>
<td>Notice</td>
<td>Notice post titles.</td>
</tr>
<tr>
<td>Other</td>
<td>Dashboard tab names.</td>
</tr>
</tbody>
</table>

A few things are deliberately left out and will never appear here:

- Text that identifies a person or credential — user names, API key labels — is never collected.
- Text that the system uses as an identifier rather than a label — a management program's resource role (for example `irrigation`), user role names, device serial/EUI-style strings — is skipped, because translating it would break the lookup that depends on it matching exactly.
- Long-form text — a management program's stage guidance and notes, note bodies, notice content — is not covered yet. Only short, label-like names are in scope.
- A name that turns out to be too short, made only of numbers/symbols, or that happens to collide with a word already used in the interface's own translation catalog (so that translating it would look like the interface itself changed) is recorded with a status of Excluded rather than translated.

## Turning it on { #turning-it-on }

Name translation has three independent switches, each controlling a different scope:

<table>
<thead>
<tr class="header">
<th>Switch</th>
<th>Where</th>
<th>What it controls</th>
</tr>
</thead>
<tbody>
<tr>
<td>Global switch</td>
<td>Settings &gt; General Settings, AI Service section</td>
<td>Turns the whole feature on or off for every user. When off, this page shows a notice that translation is turned off, and no translated names are shown anywhere.</td>
</tr>
<tr>
<td>Account switch</td>
<td>User Settings (the modal opened from your account menu, top right)</td>
<td>Lets a single user opt out even while the global switch is on. Hidden when the global switch is off.</td>
</tr>
<tr>
<td>Show original names</td>
<td>The gear/admin menu, top right</td>
<td>A per-browser, instant toggle — like a browser's own "view original" control on a translated page. It does not touch any setting on the server; it only changes what this browser tab shows right now.</td>
</tr>
</tbody>
</table>

Turning translation off at any of these levels never changes a stored name. It only stops the translated text from being displayed.

### Without an AI engine

Producing a *new* translation needs an AI engine (configured under Settings &gt; General Settings, AI Service). If none is configured, this page still works: it can collect the names currently in use, and you can type in your own translation for each one by hand — what you enter is shown on screen exactly the same as an AI-produced one would be. The button at the top of the page reads "Collect names" in this case, instead of "Translate now".

## The Name Translations page { #the-name-translations-page }

The page lists one row per collected name, for the language selected at the top. Two dropdowns filter the list:

- **Language** — which language's translations to show. Only languages that already have at least one row appear, plus the language your account currently uses.
- **Status** — All, Translated, Not translated yet, Excluded, or Failed (see [Status values](#status-values) below).

Each row shows the original name, its translation for the selected language, which category it belongs to (see the table above), and its status. The count in the top-right corner (`done / total`) is a quick read on how much of the current language is filled in.

The main button does one of two things depending on whether an AI engine is available:

- **Translate now** — scans the database for any name not yet in the dictionary, adds it to the queue, and immediately runs one batch of translation through the AI engine for the selected language. This is the same work a background job also does automatically every 15 minutes; the button exists so you do not have to wait for it.
- **Collect names** — the same scan and queue step, without the AI batch (shown when no AI engine is configured).

**Retranslate all** clears every translation for the selected language and marks it for translation again — except rows you have edited by hand, which are left untouched. A confirmation is required before this runs, since it discards existing translations for that language.

Each row also has its own **Retranslate** button, which resets just that one name and immediately re-runs translation for it. It is hidden for Excluded rows, but stays available for rows you have edited by hand — retranslating a locked row is exactly how you would discard your own correction and let the AI translate it again.

## Editing a translation { #editing-a-translation }

The Translation column is an editable field for every row that is not Excluded. Type a correction and move focus away from the field (or press Tab/Enter) to save it.

Saving a value here does two things: it stores your text as the translation shown for that name, and it **locks** the row — its status becomes Edited, and neither the periodic background job nor "Translate now" nor "Retranslate all" will overwrite it again. Clearing the field back to empty unlocks the row and returns it to Not translated yet.

This is the only way to fix a translation you disagree with. The original name itself is never editable from this page — the box next to it, under Translation, is a display-language override, not the record of what the name actually is.

## Status values { #status-values }

<table>
<thead>
<tr class="header">
<th>Status</th>
<th>Meaning</th>
</tr>
</thead>
<tbody>
<tr>
<td>Not translated yet</td>
<td>The name has been collected but has no translation for this language yet. It is shown in its original form on screen until one is added.</td>
</tr>
<tr>
<td>Translated</td>
<td>A translation was produced automatically by the AI engine and has not been touched by hand.</td>
</tr>
<tr>
<td>Edited</td>
<td>Same as Translated, but a person typed this value in on this page. It is locked: automatic translation will never overwrite it.</td>
</tr>
<tr>
<td>Excluded</td>
<td>The system decided this text should never be translated — for example, it matches a word already in the interface's own translation catalog, or it looks like an identifier rather than a label. Excluded rows show a dash instead of an editable Translation field, and the name is always displayed in its original form on screen.</td>
</tr>
<tr>
<td>Failed</td>
<td>An automatic translation attempt did not produce a usable result. The original is shown on screen in the meantime; the name stays in the queue and is retried, up to a limit, by the background job or by pressing Retranslate.</td>
</tr>
</tbody>
</table>

## Where translated names show up { #where-translated-names-show-up }

Once a name has a translation for the language you are viewing AoT in, it appears in place of the original wherever that name is shown on screen — dashboard widgets, the map, device lists, and so on. The stored data is never changed; the substitution happens only in what is displayed to you. If you type a name into a form field — renaming a device, for example — you are always shown and always editing the original text, never a translation, so there is no risk of accidentally saving a translated name over the real one.
