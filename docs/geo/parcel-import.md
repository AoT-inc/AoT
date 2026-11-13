# Parcel Import

Use Korean land data (VWorld) to quickly import site boundaries onto the map. Instead of drawing polygons manually, use address search or a CSV file to instantly generate accurate cadastral boundaries.

---

## Prerequisites { #prerequisites }

A VWorld API key must be registered.

1. Add a VWorld layer at `/geo/layer`.
2. Gear icon → Enter API key → Save.
3. Activate.

Activation is what makes the VWorld map tiles appear. Parcel import itself only needs the key: an activated VWorld layer is used first, and if none is activated, the key from a registered but inactive VWorld layer is used instead. If there is no VWorld layer at all, or its API key field is empty, the lookup fails with a message saying the VWorld GIS Input is not registered or its API Key is missing.

---

## Opening the Import Dialog { #opening-the-import-dialog }

1. Go to `/geo/design`.
2. Switch to **Site** mode in the mode bar below the map.
3. In the Site settings drawer, click **Search** next to **Add from Address**.

This opens the **Import Site by Address** dialog, which has two tabs: **Address Input** and **CSV Batch**. It slides in as a drawer on the right and pushes the map aside instead of covering it, so you can keep entering addresses while watching the boundaries appear. Only one drawer is open at a time, so the Site settings drawer closes. On a phone it covers the screen instead, and the handle along its top edge lowers it to a peek and raises it again.

The drawer is split into sections, each a **title + card**. The short per-row actions (Location and Delete on an address row, Add Address, Search, Close) are text-free **icon pills**: hover for the name in a tooltip, or long-press on a touch screen. Decisions that need words, such as upload and save, are text buttons.

---

## Address Input { #address-input }

1. Type an address (e.g., `808 Yeoksam-dong, Gangnam-gu, Seoul`). Separate several addresses with commas, or click **Add Address** (＋) to add another input row. You can also fill a row by picking the spot on the map instead of typing (see [Fill an Address from the Location Sheet](#pick-location) below).
2. Click **Search** (magnifier).
3. Matched parcels appear in the preview list below, each with its boundary drawn on the map; failed lookups are listed with the reason.

### Fill an Address from the Location Sheet { #pick-location }

If you do not know the address or do not want to type it, press the **Location** (pin) button at the right of an address row. The [Location sheet](design-tool.md#location-sheet) unfolds inside the drawer. The drawer stays open, so the row you were typing, the preview and the progress are untouched. Pick the spot in the sheet by address search, My location, Map center, Mark on the map, Favorites or Recent, then press **Use this address** to fill that row.

- Pressing **Location** on the same row again folds the sheet; pressing it on another row only changes which row gets filled.
- A filled row can be edited by hand, and Search and Enter work as before. A filled address counts as one address, so commas inside it do not split it into several.
- The server finds the spot's address by reverse lookup from the coordinates. It can take a few seconds; meanwhile **Use this address** is disabled and its name reads **Looking up the address…**. If no address is found it stays disabled — pick another spot or type the address.
- The address the sheet gives may not be a lot-number address, and addresses outside Korea cannot be resolved by VWorld. If the parcel lookup fails for such an address, the status line only adds a note ("Parcel lookup can only find addresses that VWorld can resolve. Edit the address and try again.") — nothing is converted for you, so edit the address and search again.

---

## CSV Batch Import

Use this to import multiple parcels at once.

### CSV File Format { #csv-file-format }

The **CSV Format** card at the top of the **CSV Batch** tab states the same rules.

Addresses only, one per row, in the **first column**. There is no header row and no name column — any extra columns are ignored, and a name for each imported Site comes from the address itself (or from the **Site Name** field at save time).

```csv
123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
124 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
456 Ipbuk-dong, Gwonseon-gu, Suwon-si, Gyeonggi-do
```

Save the file comma-separated and UTF-8 (in Excel, "CSV UTF-8"). No header row is skipped, so a header would be looked up as an address and listed as a failure.

The card gives a note for each place the addresses may come from:

- **VWorld** — use the lot-number (jibun) address. Parcels are matched by lot number, so road-name addresses can fail when the point falls on the road. Korean addresses only.
- **Google Maps** — move the address column of the Google Maps / My Maps export to the first column. Google returns road-name addresses, so some rows may fail; check the failure list. Addresses outside Korea cannot be read.

### How to Import { #how-to-import }

1. On the **CSV Batch** tab, choose a CSV file.
2. Click **Upload and Process**.
3. Results land in the same preview list as address search — matched parcels with a ✓, failed addresses with the reason.

---

## Reviewing and Saving { #reviewing-and-saving }

Both tabs share one preview area:

- **Merge Adjacent Parcels** (checkbox, off by default) — unions any touching polygons in the preview into a single Site (via turf.js) before saving. With it off, each previewed parcel is saved as its own Site. Parcels imported from a CSV are merged only when this box is ticked — never automatically.
- **Site Name** — auto-filled from the first result (with "and N more parcels" appended when there are several); edit it before saving. With multiple, unmerged parcels, each is saved under its own resolved name rather than this field, unless there is exactly one result.
- **Save as Site** — saves every previewed parcel (or the single merged one). Saving needs permission to edit settings, and the map must be inside your access group; without either, nothing is saved and every parcel is simply counted as failed. Searching and previewing stay open to anyone signed in.

After saving, the status line reports how many were **saved**, how many were **already imported** (see below), and how many **failed**. If at least one parcel was saved or already imported, the drawer closes and the map reloads, showing each Site with a name label at its centre.

!!! note "Importing the same parcel twice does not create a duplicate"
    If a parcel with the same geometry already exists as a Site on the current map, saving it again is skipped rather than treated as an error — it is counted separately as "already imported."

Saved parcels are `Site` type GeoShapes, editable the same as any Site feature drawn by hand.

---

## Direct API Usage

Use the REST API to call parcel import from an automation script. The web UI above is a thin client over these same three endpoints.

### Import by Address { #import-by-address }

```http
POST /api/geo/parcel/from_address
Content-Type: application/json

{
  "address": "123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do"
}
```

Response:
```json
{
  "ok": true,
  "feature": {
    "type": "Feature",
    "geometry": { "type": "Polygon", "coordinates": [[[...], ...]] },
    "properties": { "name": "..." }
  },
  "name": "123 Gojung-ri, ...",
  "pnu": "4159025300100230000"
}
```
On failure: `{"ok": false, "error": "..."}`. When the address or parcel could not be found, the failure response also carries `upstream_failed`, which is `true` if every VWorld call that was made failed (the VWorld service itself is down or erroring) and `false` if VWorld answered but simply had no match.

### CSV Batch Import { #csv-batch-import_1 }

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV file, one address per line, first column only>
```

Response:
```json
{
  "ok": true,
  "features": [ /* GeoJSON Feature, one per resolved address */ ],
  "names": [ "..." ],
  "errors": [ "<address>: <reason>", "..." ]
}
```

### Save as Site { #save-as-site }

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "feature": { "type": "Feature", "geometry": { "type": "Polygon", "coordinates": [...] }, "properties": {} },
  "name": "Greenhouse Site 1",
  "map_uuid": "<map UUID>"
}
```

Requires `edit_settings` and scope over the target map (`403` otherwise). `map_uuid` must be an existing map. If a Site with the same geometry already exists on that map, the response is `409` with `{"ok": false, "duplicate": true, "shape_id": ..., "existing_name": "..."}` instead of creating a second copy.

---

## Notes { #notes }

- Only Korean addresses are supported (uses the VWorld PNU API).
- If address recognition fails, try both the road address and the lot-number address.
- Large CSV imports (100+ rows) may take time to process — each row is a separate VWorld lookup.
- Imported parcels can be edited the same as any Site feature.

---

## Related Pages

- [Design Tool](design-tool.md) — Manual drawing in Site mode
- [GIS Layers](layers.md) — Registering a VWorld API key
