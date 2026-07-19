# Parcel Import

Use Korean land data (VWorld) to quickly import site boundaries onto the map. Instead of drawing polygons manually, use address search or a CSV file to instantly generate accurate cadastral boundaries.

---

## Prerequisites

A VWorld API key must be registered.

1. Add a VWorld layer at `/geo/layer`.
2. Gear icon → Enter API key → Save.
3. Activate.

---

## Import by Address

1. Go to `/geo/design`.
2. Click the **Parcel Import** button in the top toolbar.
3. Enter an address (e.g., `123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do`).
4. Click **Search**.
5. Select the parcel from the results.
6. The parcel boundary appears as a preview on the map.
7. Click **Save as Site**.

The parcel boundary is saved as a `Site` type GeoShape.

---

## CSV Batch Import

Use this to import multiple parcels at once.

### CSV File Format

```csv
address,name
123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do,Greenhouse Site 1
124 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do,Greenhouse Site 2
456 Ipbuk-dong, Gwonseon-gu, Suwon-si, Gyeonggi-do,Admin Building Site
```

Fields:
- `address` (required): Street address or lot number address
- `name` (optional): Site name. If omitted, the address string is used as the name.

### How to Import

1. Select **Parcel Import → CSV Import** in the top toolbar of `/geo/design`.
2. Select or drag and drop a CSV file.
3. Review the data in the preview table.
4. Rows with errors are highlighted in red (address not recognized).
5. Click **Import**.

Processing results are displayed:
- Success: Site feature created
- Failure: Address search failed (check address format)

---

## Direct API Usage

Use the REST API to call parcel import from an automation script.

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
  "pnu": "4159025300100230000",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[...], ...]]
  },
  "address": "123 Gojung-ri, ...",
  "area_m2": 3256.7
}
```

### CSV Batch Import

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV file>
```

### Save as Site

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "geo_id": "<map UUID>",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "name": "Greenhouse Site 1"
}
```

---

## Notes

- Only Korean addresses are supported (uses VWorld PNU API).
- If address recognition fails, try both the road address and lot number address.
- Large CSV imports (100+ rows) may take time to process.
- Imported parcels can be edited the same as any Site feature.

---

## Related Pages

- [Design Tool](design-tool.md) — Manual drawing in Site mode
- [GIS Layers](layers.md) — Registering a VWorld API key
