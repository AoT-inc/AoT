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

---

## Address Input { #address-input }

1. Type an address (e.g., `808 Yeoksam-dong, Gangnam-gu, Seoul`). Separate several addresses with commas, or click **Add Address** to add another input row.
2. Click **Search**.
3. Matched parcels appear in the preview list below, each with its boundary drawn on the map; failed lookups are listed with the reason.

---

## CSV Batch Import

Use this to import multiple parcels at once.

### CSV File Format { #csv-file-format }

Addresses only, one per row, in the **first column**. There is no header row and no name column — any extra columns are ignored, and a name for each imported Site comes from the address itself (or from the **Site Name** field at save time).

```csv
123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
124 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
456 Ipbuk-dong, Gwonseon-gu, Suwon-si, Gyeonggi-do
```

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
On failure: `{"ok": false, "error": "..."}`.

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
