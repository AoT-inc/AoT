# Parcel Import

Use Korean land data (VWorld) to quickly import site boundaries onto the map. Instead of drawing polygons manually, use address search or a CSV file to instantly generate accurate cadastral boundaries.

---

## Prerequisites

A VWorld API key must be registered.

1. Add a VWorld layer at `/geo/layer`.
2. Gear icon → Enter API key → Save.
3. Activate.

---

## Opening the Import Dialog

1. Go to `/geo/design`.
2. Switch to **Site** mode in the mode bar below the map.
3. In the Site settings drawer, click **Search** next to **Add from Address**.

This opens the **Import Site by Address** dialog, which has two tabs: **Address Input** and **CSV Batch**.

---

## Address Input

1. Type an address (e.g., `808 Yeoksam-dong, Gangnam-gu, Seoul`). Separate several addresses with commas, or click **Add Address** to add another input row.
2. Click **Search**.
3. Matched parcels appear in the preview list below, each with its boundary drawn on the map; failed lookups are listed with the reason.

---

## CSV Batch Import

Use this to import multiple parcels at once.

### CSV File Format

Addresses only, one per row, in the **first column**. There is no header row and no name column — any extra columns are ignored, and a name for each imported Site comes from the address itself (or from the **Site Name** field at save time).

```csv
123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
124 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do
456 Ipbuk-dong, Gwonseon-gu, Suwon-si, Gyeonggi-do
```

### How to Import

1. On the **CSV Batch** tab, choose a CSV file.
2. Click **Upload and Process**.
3. Results land in the same preview list as address search — matched parcels with a ✓, failed addresses with the reason.

---

## Reviewing and Saving

Both tabs share one preview area:

- **Merge Adjacent Parcels** (checkbox, off by default) — unions any touching polygons in the preview into a single Site (via turf.js) before saving. With it off, each previewed parcel is saved as its own Site.
- **Site Name** — auto-filled from the first result (and "+ N more" when there are several); edit it before saving. With multiple, unmerged parcels, each is saved under its own resolved name rather than this field, unless there is exactly one result.
- **Save as Site** — saves every previewed parcel (or the single merged one).

After saving, the status line reports how many were **saved**, how many were **already imported** (see below), and how many **failed**.

!!! note "Importing the same parcel twice does not create a duplicate"
    If a parcel with the same geometry already exists as a Site on the current map, saving it again is skipped rather than treated as an error — it is counted separately as "already imported."

Saved parcels are `Site` type GeoShapes, editable the same as any Site feature drawn by hand.

---

## Direct API Usage

Use the REST API to call parcel import from an automation script. The web UI above is a thin client over these same three endpoints.

### Import by Address

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

### CSV Batch Import

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

### Save as Site

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "feature": { "type": "Feature", "geometry": { "type": "Polygon", "coordinates": [...] }, "properties": {} },
  "name": "Greenhouse Site 1",
  "map_uuid": "<map UUID>"
}
```

`map_uuid` must be an existing map. If a Site with the same geometry already exists on that map, the response is `409` with `{"ok": false, "duplicate": true, "shape_id": ..., "existing_name": "..."}` instead of creating a second copy.

---

## Notes

- Only Korean addresses are supported (uses the VWorld PNU API).
- If address recognition fails, try both the road address and the lot-number address.
- Large CSV imports (100+ rows) may take time to process — each row is a separate VWorld lookup.
- Imported parcels can be edited the same as any Site feature.

---

## Related Pages

- [Design Tool](design-tool.md) — Manual drawing in Site mode
- [GIS Layers](layers.md) — Registering a VWorld API key
