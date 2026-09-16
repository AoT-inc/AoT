# GIS API Reference

All endpoints on this page require login (session cookie or an [API key](../Security.md#api-keys)). Endpoints that change data additionally require a permission — `edit_settings`, `edit_controllers`, or `edit_plots` depending on the resource — and endpoints tied to one map or facility further check that the caller's access group covers it (`scope.can_operate`). Each section below notes the permission where it isn't `edit_settings`.

> **Known duplication:** `POST /api/geo/designs`, `GET`/`DELETE /api/geo/designs/<uuid>`, and `GET`/`POST /api/geo/overlays` are each defined twice in the codebase (once as a flask-restx resource, once as a plain Flask route). Because of Flask's route-registration order, only the flask-restx version actually runs for these five — the plain-route copies are unreachable. The behavior documented below is the one that runs. This duplication is an internal cleanup item, not part of the documented contract, and could change without notice.

---

## Design Maps

A "design" is one `GeoMap` row — a named map with its own center/zoom/layer state, holding all the shapes (sites, zones, facilities, devices) drawn on it.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/init_design` | Loads (or auto-creates, if none exist) the current user's most recently used map. Returns its full state. |
| GET | `/api/geo/designs` | Lists every map as `{unique_id, name, latitude, longitude, zoom}` (center/zoom derived from stored state; defaults to `[37.5665, 126.9780]` / zoom 13 if unset). |
| GET | `/api/geo/designs/list` | A second, near-identical map listing (added later in `routes_geo.py`, doesn't collide with the one above since the path differs). Same shape. |
| GET | `/api/geo/designs/<map_uuid>` | Full state of one map: `{ok, uuid, name, state}`. 404 if not found. |
| POST | `/api/geo/designs` | Create (omit `map_uuid`) or rename/update a map. Body: `{map_uuid?, name, state}` — `state` is merged into the map's existing state, not replaced. Response: `{ok, uuid, name}`. |
| DELETE | `/api/geo/designs/<map_uuid>` | Deletes the map and everything on it (facility setpoints → facilities → shapes → the map row). Returns `409 {blocked: true}` if something outside this map still references it. |
| POST | `/api/geo/maps/<map_uuid>/restore-original` | Reverts every shape on the map that has a stored pre-migration snapshot (`original_data`) back to that snapshot. Response: `{ok, map_uuid, restored, skipped}`. 400 if the migration-tracking columns don't exist yet (`alembic upgrade head` needed). |

---

## Overlays & Shapes (GeoJSON)

"Overlays" are the GeoJSON features drawn on a map — sites, zones, facility outlines, device markers, equipment.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/overlays/list` | All `GeoShape` rows across every map, flat, no GeoJSON wrapping. |
| GET | `/api/geo/overlays?map_uuid=<uuid>&type=&parent_id=&device_id=` | One map's features as a GeoJSON `FeatureCollection`. `type` also matches legacy aliases (`equipment` ⇒ `equipment_collection`, `aot_device` ⇒ `device`). Each feature is enriched server-side with `db_id`, resolved `device_id`/`device_type`, `parent_id`, and (for `type=facility`) 3D metadata. |
| POST | `/api/geo/overlays` | Bulk save/replace for one `map_uuid` + `type`. See **Details** below — this is the trickiest endpoint on the page. |
| POST | `/api/geo/overlays/delta` | Send only what changed instead of the full feature set — for large maps. Body: `{geo_id, added: [...], modified: [...], deleted: [uuid, ...]}`. Also requires `edit_settings` and map scope. |
| GET | `/api/geo/sites` | All `site`-type shapes as GeoJSON. `?map_uuid=` optional. |
| GET | `/api/geo/zones` | All `zone`-type shapes as GeoJSON. `?map_uuid=` optional. |
| GET | `/api/geo/shapes/<category>` | Any shape category (`site`, `zone`, `facility`, `feature`, ...) as GeoJSON. |
| POST | `/api/geo/generate-pipes` | Computes a branch-pipe route between devices without saving it. Body: `{parent_feature, ref_line, config, map_uuid}`. |

### Details: `POST /api/geo/overlays`

- Matches incoming features to existing rows by `db_id`, then `node_id` — everything else is derived from those.
- **A feature missing from the payload is never deleted.** Only an explicit `deletes: [node_id_or_db_id, ...]` list, or `features: []` combined with `allow_empty: true`, removes rows. (A prior incident wiped shapes because "not present" was once treated as "delete".)
- `aot_device` markers can never be bulk-wiped through this endpoint at all — device placement only goes through `POST /api/geo/device/location`.
- `equipment` features are stored as one bundled `equipment_collection` row (the whole set is replaced together), everything else is saved feature-by-feature.
- `aot_type`, `device_id`, and `channel_id` are stripped from the saved JSON blob — they're derived on read, not stored, so don't rely on round-tripping them.
- Response: `{ok, count, id_map: {node_id: db_id}, stats: {deleted, updated, inserted}}` (or a `stats.mode: 'bulk_bundle'` shape for the equipment path).

---

## Search

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/search` | Geocoding/address search, proxied through whichever GIS input module is configured as the search provider. Body: `{query, type: 'address' (default), layer_id?}`. `layer_id` picks a specific `GeoLayer`; otherwise the map's configured `search_provider` setting is used, falling back to `gis_osm`. Response: `{ok, results}` (shape depends on the provider). |

---

## Device Binding

A "binding" links a device (sensor or actuator) to a spatial slot — a zone polygon, a facility fitting, a sensor role, etc. Binding is a first-class object with history: ending one keeps the row (for audit) rather than deleting it.

Shared fields (`spatial_kind`, `spatial_id`, `role`, `device_id`, `device_kind`, `channel_id`, `measurement_id`) — see **Details** below.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/binding?spatial_kind=&spatial_id=&role=` | Current + past bindings for one slot. Response: `{ok, bindings, history}` (`history` is only entries that have ended). |
| POST | `/api/geo/binding` | Bind a device to an unoccupied slot. `409 {conflict: true}` if the slot is already bound; `400` on an unknown device/shape. |
| PUT | `/api/geo/binding` | Replace the device on a slot — ends the old binding (kept in history) and creates a new one in one call. |
| GET | `/api/geo/binding/unbound?kinds=&facility_uuid=&map_uuid=` | Lists slots with nothing currently bound (empty zone polygons, facility fittings that lost their device), for "what needs wiring" views. `kinds` should always be narrowed to specific spatial kinds. |
| DELETE | `/api/geo/binding/<binding_uid>` | Ends a binding (`valid_to` set; row kept). Body/query: `reason` (default `unbound`). `404` if the binding id doesn't exist. |

### Details: binding fields

- `spatial_kind`: `shape` \| `fitting` \| `actuator` \| `sensor_role` \| `weather`.
- `spatial_id`: the slot identifier. For `spatial_kind=shape` this can be either a saved `GeoShape.unique_id` or a client-side `node_id` not yet persisted — the server resolves it either way.
- `role`: what the slot is for (`marker`, `area`, `actuator`, `sensor`, ...). For shape slots, the role is derived server-side from the shape's own `type` — a client-supplied role is not trusted for shapes.
- `device_id`: accepts a `<device_uuid>::<channel>` suffix; it's split and the channel becomes `channel_id`.
- `device_kind` is always re-validated/resolved server-side even if supplied.

---

## Device Location, Lists & Detail

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/device/location` | Sets/moves a device's map position. Body: `{unique_id, type, lat, lng, map_uuid?, channel_id?}` — `type` is one of `input\|output\|pid\|trigger\|conditional\|device\|function\|custom\|generic_function`. If `map_uuid` is given, also places (or updates) that device's marker and derives which zone it falls in. Best-effort notifies the daemon to reload the device's settings (so a timezone change from the new location takes effect immediately). Response: `{ok, message, overlay_id}`. |
| GET | `/api/geo/devices?map_uuid=&device_ids=&include_all=` | Devices available for placement on a map. Response: `{ok, devices, all_measurements_map}`. Supports conditional (304) responses. |
| GET | `/api/geo/inputs` | Flat per-channel list (`DeviceMeasurements`) for the sensor-fitting binding picker. |
| GET | `/api/geo/outputs` | Flat `Output` list for the actuator-fitting binding picker. |
| GET | `/api/geo/device/<device_uuid>/detail` | One device's full modal payload: identity, parent area, control kind (on/off, value, PWM, 3-way), channels, sub-devices for a compound device, and runtime info (elapsed/last-duration/pending schedule). |
| POST | `/api/geo/link_status` | Batch battery/RSSI lookup for map badges. Body: `{ids: [...]}` (max 100). |
| POST | `/api/geo/device/split-apply` | Splits a zone into strips/grid cells and creates one device-marker shape per cell, auto-assigning each cell to whichever device marker falls inside it. Requires `edit_plots`. Shares its split parameters and its *preview* endpoint (`GET /api/geo/plot/split-preview`, below) with the cultivation-plot splitter — geometry math doesn't care whether the pieces end up as devices or plots. Response: `{ok, created, info, assigned, unassigned, message?}`. |

---

## Zones

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/zone/<zone_uuid>/contents` | Device inventory for the zone's "[환경·제어]" modal (sensors/outputs/functions inside it). 30-second server cache. |
| GET | `/api/geo/zone/<zone_uuid>/allocation?on=YYYY-MM-DD` | How the zone's area is divided among its cultivation plots (per-plot area/percentage, plus the unassigned remainder). Overlapping plots can sum past 100%, flagged as `overlaps`. |
| GET | `/api/geo/zone/<zone_uuid>/output_history?output_id=<uuid>&hours=` | Legacy alias for `GET /api/geo/output/<uuid>/history` (below), scoped to a zone. |
| POST | `/api/geo/zone/<zone_uuid>/photo` | Multipart `photo` upload for the zone's representative image. |
| POST | `/api/geo/zone/<zone_uuid>/rep_key` | Sets/clears which measurement is the zone's "representative" reading. |
| POST | `/api/geo/zone/<zone_uuid>/hidden_rows` | Body: `{card, keys}` — which status-card rows to hide for this zone. |
| POST | `/api/geo/zone/<zone_uuid>/output_order` | Body: `{order}` — saves device display order for the zone's device list. |
| POST | `/api/geo/shape/<shape_uuid>/description` | Free-text description (≤2000 chars) for a site or zone. |

---

## Sites

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/site/<site_uuid>/contents` | Device inventory inside a site (excludes facility-fitting actuators — those belong to their facility, not the enclosing site). |
| GET | `/api/geo/site/<site_uuid>/summary?force=` | Aggregated status / today's tasks / notes for the site. 30-second cache unless `force=1`. |
| GET | `/api/geo/site/<site_uuid>/weather` | Currently assigned weather-station device(s). Response: `{selected, source, candidates}`. |
| POST | `/api/geo/site/<site_uuid>/weather` | Body: `{device_ids: [...]}` (key required even if empty) — sets the site's weather source. |

---

## Facilities

A "facility" is a structure (greenhouse, barn, etc.) with an envelope (dimensions/material) and bound sensors/actuators.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/facility/list?geo_id=<map_uuid>` | All facilities, optionally scoped to one map. Each entry includes its `rep_key`. |
| GET | `/api/geo/facility/<facility_uuid>` | Full facility record: envelope, bindings, 3D/render settings. |
| POST | `/api/geo/facility` | Create or update (atomic across the outer record, envelope spec, and bays). Body includes `unique_id?` (omit to create), `name`, `shape_uuid`, `preset`, `structure`, `bay_count`, `envelope: {material, bay_width_m, length_m, eave_height_m, ridge_height_m}`. |
| POST | `/api/geo/facility/<facility_uuid>/clone` | Duplicates a facility, resetting its device bindings (a clone doesn't inherit the original's wiring). |
| DELETE | `/api/geo/facility/<facility_uuid>` | Body/query: `confirm_name` must match the facility's current name. |
| POST | `/api/geo/facility/compute` | Engineering-calculation preview (area/volume/heating & cooling load/ventilation) for a given envelope, without saving. Body: `{envelope: {...}, bay_count}`. `501` if the calculation module isn't available. |
| GET | `/api/geo/facility/<facility_uuid>/integration` | Unified sensor/actuator binding view — the same data the environment coordinator itself reads. |
| GET | `/api/geo/facility/<facility_uuid>/wind?wind_speed=&wind_dir=` | Natural-ventilation wind-pressure simulation. |
| POST | `/api/geo/facility/<facility_uuid>/apply` | Sends commands to the facility's bound actuators. Body: `{horizon, commands: [{kind, action, pct?}, ...]}`. When the VEE (Virtual Execution Engine) feature flag is on, runs an advisory pre-flight simulation first; dispatch itself goes through the daemon either way. |

Live runtime monitoring/control for a facility (real-time actuator state, safety setpoints, manual override, e-stop) is a **separate API family under a different prefix** — see [Facility Runtime Control](#facility-runtime-control-apiaotfacility-apiaotcoordinator) below.

### Facility 3D Model Assets

Reusable 3D models (primitives or imported `.glb`/`.gltf` files) that can be attached to a facility instead of its default parametric shape. All require login only (no extra permission check beyond that), and are scoped to `owner_user_id = current_user.id` for listing/creation (not enforced on get/update/delete/attach by id).

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/model_assets?kind=&tag=` | List the current user's model assets. |
| POST | `/api/geo/model_assets` | Create one. JSON body or multipart (`file` field, required for `kind=imported_gltf`). Fields: `name`, `kind` (default `primitive`), `spec_json`, `authored_unit` (default `m`), `tags`, `notes`. Uploaded files: ≤25MB, allowed extensions only, `.glb` files are magic-byte validated (`glTF` header). Triggers a preview-image render after creation. |
| GET | `/api/geo/model_assets/<asset_uuid>` | Fetch one asset. 404 if missing. |
| PUT | `/api/geo/model_assets/<asset_uuid>` | Update `name`/`spec_json`/`authored_unit`/`tags`/`notes`/`sort_order` (only the keys present in the body are changed). Re-renders the preview. |
| DELETE | `/api/geo/model_assets/<asset_uuid>` | Deletes the asset row and its files on disk. `409` (with `referencing_facilities`) if any facility still uses it. |
| POST | `/api/geo/model_assets/<asset_uuid>/regenerate_preview` | Forces the thumbnail to re-render. |
| POST | `/api/geo/facility/<facility_uuid>/attach_model` | Attaches a model asset to a facility (sets `render_mode='asset'`). Body: `{asset_uuid, transform?}` (`transform` default: identity position/rotation, scale 1). |
| DELETE | `/api/geo/facility/<facility_uuid>/attach_model` | Detaches it (`render_mode` reverts to `parametric`). |

### Facility Commissioning

Post-install verification: run automated checks against a facility's actuators, then record a human verdict per actuator. Requires `edit_settings` except the result read.

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/facility/<facility_uuid>/commissioning/start` | Body: `{actuator_ids?}` (omit = all facility actuators). Response: `{ok, check_id, actuator_count}`. `400` if there's nothing to check. |
| GET | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>` | Poll the check's status/results. Login only, no extra permission. `403` if the check belongs to a different facility, `404` if unknown. |
| POST | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict` | Body: `{actuator_id, verdict: 'ok'\|'sensor'\|'device'\|'external'\|'skip', note?}`. The verdict can trigger follow-up actions recorded on the facility (marking a sensor untrusted, adjusting a control gain bound, adding a calibration anchor point, raising an alarm) — returned in the response's `actions` list. |

---

## Facility Runtime Control (`/api/aot/facility`, `/api/aot/coordinator`)

This is a **different URL prefix** (`/api/aot/`, not `/api/geo/`) for the live side of a facility once its environment coordinator is running: status, safety-range setpoints, manual override, e-stop, and history. It's the same conceptual object as the facilities above (same `facility_uuid`), just a separate route family.

| Method | Path | Description |
|---|---|---|
| GET | `/api/aot/facility/<facility_uuid>/status?function_uuid=` | Lightweight status badge for polling (~5s): `{level: 'idle'\|'warn'\|'active'\|'emergency', reasons, active_count, total_count, function_active, function_stale}`. |
| GET | `/api/aot/facility/<facility_uuid>/setpoints` | Saved **safety-range** limits plus `effective` (the live target the control loop is actually following, which comes from the plot's program/stage — not from here). |
| POST | `/api/aot/facility/<facility_uuid>/setpoints` | Requires `edit_settings`. Body: any of `guide_t_min_c`/`guide_t_max_c`, `guide_rh_min_pct`/`guide_rh_max_pct`, `temp_min_c`/`temp_max_c`, `humid_min_pct`/`humid_max_pct` (all range-validated). Sending `target_vpd_kpa`/`target_co2_ppm` here is rejected — targets are set through the cultivation program, not here. Mirrors changed values into every linked environment-coordinator function and triggers a live reload. |
| POST | `/api/aot/facility/<facility_uuid>/control` | Manual single-actuator control, bypassing the coordinator, with safety-gate interlocks (e.g. won't open a vent a wind-safety gate has forced shut). Requires `edit_settings` + facility scope. Body: `{slot_key, action: 'on'\|'off'\|'set', percent?, reason?}`. `400` if the gate blocks the request. |
| POST | `/api/aot/facility/<facility_uuid>/estop` | Emergency stop — forces every actuator to a safe preset (heater/vents/fans/CO2/irrigation/lighting off, thermal curtain deployed, shade curtain retracted). Body: `{confirm: "STOP"}` (exact string required). Requires `edit_settings`. |
| GET | `/api/aot/facility/<facility_uuid>/runtime` | The heavy real-time snapshot: actuator states with duty/last-run history, indoor/outdoor sensors, bays, plots, bay capacities. 120-second process cache; supports conditional (304) responses. |
| GET | `/api/aot/facility/<facility_uuid>/env_summary` | The coordinator's last-cycle summary as the daemon stored it (no time-series query — a cheap single-row read). |
| GET | `/api/aot/facility/<facility_uuid>/env_week?bay=&days=` | Daily environment trend series (default 7 days, 1–31). 10-minute cache. |
| GET | `/api/aot/facility/<facility_uuid>/actuator_history?slot_key=&hours=` | One actuator's operation history (percent/duty series, or on/off durations as a fallback). `hours` default 24, clamped 1–168. |
| GET | `/api/aot/facility/<facility_uuid>/overview?fresh=` | Bundles status + env_summary + info + irrigation + weather hazards + site + area status + representative reading + hidden rows + plot GDD/DLI into one call, so the map popup doesn't fire several requests at once. 30-second cache + single-flight lock; `fresh=1` bypasses it. |
| POST | `/api/aot/facility/<facility_uuid>/function_state` | Body: `{action: 'activate'\|'deactivate'}` — turns the linked environment-coordinator function on/off. Requires `edit_controllers` + scope. |
| GET | `/api/aot/facility/<facility_uuid>/info` | Representative photo/description/dimensions for the map popup. |
| POST | `/api/aot/facility/<facility_uuid>/info` | Body: `{description}` (≤2000 chars). Requires `edit_settings`. |
| POST | `/api/aot/facility/<facility_uuid>/photo` | Multipart `photo` upload (png/jpg/jpeg/gif/webp). Requires `edit_settings`. |
| GET | `/facility_photo/<filename>` | Serves an uploaded facility photo (login required; path-traversal guarded). |
| POST | `/api/aot/facility/<facility_uuid>/rep_key` | Sets/clears the facility's representative measurement. `422` if the facility has no mapped shape. Requires `edit_settings`. |
| POST | `/api/aot/facility/<facility_uuid>/hidden_rows` | Same shape as the zone version above, for a facility. Requires `edit_settings`. |
| POST | `/api/aot/facility/<facility_uuid>/actuator_order` | Body: `{order: [slot_key, ...]}`. Requires `edit_settings`. |
| GET | `/api/aot/facility/<facility_uuid>/bays` | `{ok, bays: [{id, name}]}` for a bay-scope picker. |
| POST | `/api/aot/facility/<facility_uuid>/bay_capacity` | Body: `{bay_id, unit, total}` (`total<=0` clears it). Requires `edit_plots` — deliberately a season-operator permission, not `edit_settings`. |
| GET | `/api/aot/facility/<facility_uuid>/calibration_status` | Per-actuator control-loop calibration state and commissioning state for the linked coordinator. |
| GET | `/api/aot/coordinator/<function_uuid>/overview` | The environment-coordinator settings page header: which facility it controls, its live plots and their programs, and (if another inactive coordinator duplicates it on the same facility) an `other_coordinator` warning. |
| GET | `/api/aot/coordinator/<function_uuid>/actuators` | Actuators this coordinator can control, which are currently disabled (`disabled_actuators` option), and which disabled entries are stale (no longer resolve to a live device). |

---

## Cultivation Programs

A "program" is a reusable growth-stage template (stages, GDD/DLI targets, irrigation/fertilizer schedule) that a plot follows. Writes require `edit_plots`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/programs?subject=&kind=&tab_id=` | List programs a plot can use. `subject` also accepts `crop` as an alias. Variety-specific programs for the same subject sort ahead of the generic default. |
| GET | `/api/geo/program/<program_uuid>` | Full program detail including its stage list. |
| POST | `/api/geo/program` | Create. Body: `name`, `subject`/`crop`, `kind` (default `vegetation`), `stages`, `photosynthesis`, `target_defs`, `resource_defs`, `notes`, or `template_key` to seed from a built-in template. Always saved as `source: 'user'`. |
| POST / PUT | `/api/geo/program/<program_uuid>` | Update. Built-in/external programs reject content edits — clone first (below). A `tab_id`-only payload is allowed even on a built-in (moving it between tabs isn't a content edit). If an AI agent makes the edit, `source` flips to `ai` and any prior review is cleared. |
| DELETE | `/api/geo/program/<program_uuid>` | Rejected if any plot still references it. |
| POST | `/api/geo/program/<program_uuid>/clone` | The only way to modify a built-in/external program — clones it into an editable copy. Body may override `name`, `subject`/`crop`, `kind`, `variety`, `stages`, `target_defs`, `photosynthesis`, `targets_methods`, `notes`, `tab_id`. Records `derived_from` for reference (not a live link). |
| GET | `/api/geo/program-templates` | Catalog of built-in seed templates (not stored in the database). |
| GET | `/api/geo/target-methods` | `Method` (time-axis curve) controllers that can be used as a program's target instead of a fixed per-stage value. |
| GET | `/api/geo/target-measurements` | Measurement vocabulary a target can bind to, plus each kind's default target definitions. |
| GET | `/api/geo/coordinator/<function_uuid>/plot-targets?on=YYYY-MM-DD` | Read-only view of the plot(s) an environment-coordinator function currently follows and their stage targets — computed through the same code path control uses, so this can't drift from what's actually happening. |
| POST | `/api/geo/coordinator/<function_uuid>/reference-plot` | Body: `{plot_uuid}` (empty string clears it). Pins which overlapping plot a coordinator should treat as the reference, for intercropped zones with more than one candidate. |

---

## Cultivation Plots

A "plot" (구획) is one planting cycle on a piece of ground or a facility bay — its own stage timeline, targets, and schedule, independent of the shared program it follows. Writes require `edit_plots`.

### Listing & detail

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/plots?map_uuid=&on=&include_ended=&include_planned=&facility_uuid=` | Plot list. Defaults to active plots only on one map; `include_ended`/`include_planned` widen that; omit `map_uuid` for a cross-map "operations" view. |
| GET | `/api/geo/plot/<plot_uuid>` | Single plot detail (auto-approves any pending stage transition first). Includes `can_edit`, `can_design`, and its own upcoming device schedule. |
| GET | `/api/geo/plot/<plot_uuid>/contents` | The "[환경·제어]" modal inventory — devices classified as inside the plot, irrigation that reaches it, or nearest-fallback per device kind. Facility-backed plots (no polygon of their own) get a bay-scoped variant. 30-second cache. |
| GET | `/api/geo/plot/<plot_uuid>/resource_usage?days=` | Irrigation runtime/volume for the "[현황]" card. `days` 1–30. |
| GET | `/api/geo/plot/<plot_uuid>/env_series` / `/env_week?days=&end=&stage=&unit=` | Environment trend series for the plot, in the plot's own timezone. Pass `stage=<key>` to use that stage's own window instead of `days`/`end`. |
| GET | `/api/geo/plot/<plot_uuid>/sensors` | The devices currently referenced by this plot (derived, not stored). |
| GET | `/api/geo/zone/<zone_uuid>/allocation?on=` | See [Zones](#zones) above — a zone-scoped view of its plots' area split. |
| POST | `/api/geo/plots/history` | "What was planted here before" — past plots whose geometry overlaps a given shape (crop-rotation lookups). Body: one of `plot_uuid`, `zone_uuid`, or a raw `geometry`, plus `map_uuid` if it can't be inferred. |

### Lifecycle & stage

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/plot` | Create (no `unique_id`) or update (with one — partial save, only given fields change). Needs `map_uuid`/`geo_id` plus either a `feature` (GeoJSON) or a `facility_uuid`(+`bay_id`). |
| DELETE | `/api/geo/plot/<plot_uuid>` | **Hard** delete, for mis-entries. Normal end-of-cycle should use `/end` below instead. |
| POST | `/api/geo/plot/<plot_uuid>/end` | Soft-ends the cycle (sets an end date; doesn't delete). Body: `{ended_on, reason: default 'harvested'}`. |
| POST | `/api/geo/plot/<plot_uuid>/succeed` | Ends the current cycle and immediately replants the same spot in one call. Body: `{ended_on, reason, subject, started_on, program_uuid?, variety?}` — omitting `program_uuid` inherits the prior program, an explicit `null` clears it (fallow). |
| POST | `/api/geo/plot/<plot_uuid>/copy` | Creates a new plot reusing a past cycle's geometry (replant the same footprint). Body: `{started_on, subject}`. |
| POST | `/api/geo/plot/<plot_uuid>/stage` | Confirms a stage transition — the write that moves the anchor date all stage-math is computed from. Body: `{stage_key, stage_index, started_on, source, note}`. |
| DELETE | `/api/geo/plot/<plot_uuid>/stage` | Undoes the last accepted stage transition (row kept, marked undone). |
| POST | `/api/geo/plot/<plot_uuid>/stage-guidance` | Sets this plot's own free-text guidance for a stage, independent of the program's guidance. Body: `{stage_key, guidance}`. |
| POST | `/api/geo/plot/<plot_uuid>/stage-name` | Renames a stage for this plot only. Body: `{stage_key, name}`. Unlike stage-guidance, past stages can also be renamed. |
| POST | `/api/geo/plot/<plot_uuid>/stage-target` | Overrides a stage's target value for this plot only. Body: `{stage_key, target_key, value}` — an empty `value` reverts to the program's own value. **This isn't display-only** — control reads plot overrides ahead of the program's reference value. |
| POST | `/api/geo/plot/<plot_uuid>/stages` | Adds a custom stage to this plot only, without touching the shared program. Body: `{name, days, after, guidance}`. |
| DELETE | `/api/geo/plot/<plot_uuid>/stages/<stage_key>` | Removes a plot-specific stage. Rejected if the stage has already elapsed. |
| POST | `/api/geo/plot/<plot_uuid>/save-as-program` | Registers this plot's current stage schedule as a reusable program — a copy, not a live link (the plot keeps following what it already had). Body: `{name, adopt_targets}` — `adopt_targets` adopts this plot's own measured-median values into the new program where unambiguous. |
| POST | `/api/geo/plot/<plot_uuid>/resources` | Manually fires the resource functions (e.g. irrigation) declared for the plot's current stage. **Never** auto-triggered by a stage transition or auto-advance, since it turns on water. |

### Schedule

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/plot/<plot_uuid>/schedule` | Adjusts stage boundaries in bulk. Body: exactly one of `days` (`{stage_key: day_count}`, duration-based) or `plan` (`{stage_key: date|null}`, absolute-date based). |
| POST | `/api/geo/plot/<plot_uuid>/schedule/shift` | Shifts one stage boundary relatively. Body: `{stage_key, days: ±N}` — converted to an absolute date at save time, so a later shift never changes what an earlier "+7 days" meant. |

### Splitting a zone into plots

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/plot/split-preview?zone_id=&parts=\|strip_width_cm=\|widths_cm=&edge_margin_m=&min_length_cm=&orientation=&angle_deg=` | Computes a proposed strip/grid split of a shape **without saving anything** — the split is deterministic (same shape + params ⇒ same result), so no preview needs to be stored. |
| POST | `/api/geo/plot/split-apply` | Body: same split params, plus `subject` (required), `kind` (default `vegetation`), `variety`, `started_on`, `expected_end_on`, `color`, `name`. **Recomputes the split server-side from the same parameters — it never trusts a client-sent preview polygon** — then creates one plot per resulting strip. Response never reports full success if any single piece failed: `{ok, created, errors: [{index, message}], message}`. |

(The device-marker version of this splitter is `POST /api/geo/device/split-apply`, documented under [Device Location, Lists & Detail](#device-location-lists-detail) — it reuses this same `split-preview` endpoint since the geometry math doesn't care what the pieces become.)

---

## Manual Schedule

A lightweight, non-device-actuating schedule entry (a note that a worker should do something on a date) — separate from the automatic device Scheduler.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/schedule/<target_id>` | Upcoming schedule items for a shape/plot/facility, including its descendants. |
| POST | `/api/geo/schedule` | Body: `{target_id, date, time, content, worker}`. |

---

## Output Control (map popups)

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/output/<output_uuid>/state` | Turns an output on/off via the daemon. Body: `{state, channel, duration}`. Requires `edit_controllers` + device scope. |
| POST | `/api/geo/output_states` | Batch raw on/off state poll for a zone popup. Body: `{ids: [...]}`. Read-only — login only, no extra permission. |
| POST | `/api/geo/output_runtimes` | Heavier batch lookup (elapsed time, last duration, next scheduled run) — meant for modal-open time only, not polling. Body: `{items: [{id, channel}, ...]}` (max 60). |
| GET | `/api/geo/output/<output_uuid>/history?hours=` | Duty-cycle/on-off history series. `hours` 1–168, default 24. |
| POST | `/api/geo/function/<kind>/<func_uuid>/activate` | `kind` is `custom`\|`conditional`\|`pid`\|`trigger`\|`function`. Body: `{active: bool}`. Requires `edit_controllers`. |

---

## Parcel Import

Importing real-world parcel/park boundaries as map shapes.

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/parcel/from_address` | Body: `{address}`. Looks up a Korean cadastral parcel polygon via VWorld (API key resolved from the registered `gis_vworld` layer). |
| POST | `/api/geo/parcel/from_csv` | Multipart `file` — a CSV whose first column is addresses; batch-imports each. |
| POST | `/api/geo/parcel/save_as_site` | Body: `{feature, name, map_uuid}` (`map_uuid` required). Saves an imported parcel as a `site` shape. Rejects duplicate imports of the same parcel (`409`) by geometry key, and auto-creates a label shape alongside it. |
| GET | `/api/geo/import/gg_parks/preview?sigun_nm=&limit=` | Dry-run preview of Gyeonggi-do public-park boundaries available for import. |
| POST | `/api/geo/import/gg_parks` | Body: `{map_uuid, sigun_nm, limit, delay_sec}`. Saves the previewed parks as `site` shapes. |

---

## Aerial / Drone Image Overlays

Georeferenced raster images (drone photos, aerial imagery) draped on the map. Requires `edit_controllers`.

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/overlay_image/upload` | Multipart `file` + `layer_id`. Auto-georeferences from EXIF/XMP metadata if the layer has no prior placement; otherwise treats it as a texture swap onto the existing corners. Large images are tiled into a pyramid; small ones are served as a single image. |
| POST | `/api/geo/overlay_image/save` | Body: `{layer_id, coordinates: [[lng,lat], ...] (4 corners), opacity}`. Re-triggers tiling if the corners changed. |
| GET | `/api/geo/overlay_image/tile_status/<layer_id>` | Polls tiling progress: `{tile_status, render_mode, tile_url, minzoom, maxzoom, tile_count, tile_error}`. |

---

## Proxy Services

The server relays these external services so browser clients never see the upstream API key and don't hit CORS restrictions. All are `GET`, most cache the upstream response briefly (noted where known).

| Endpoint | Target |
|---|---|
| `/api/geo/layer_secrets?ids=` | Unmasked API keys/URLs for up to 12 of the caller's own registered layers (page-rendered lists mask these; a layer must be actively enabled to reveal its key here). |
| `/api/geo/proxy/rainviewer/meta` | RainViewer radar metadata (5 min cache). |
| `/api/geo/proxy/rainviewer/timestamps` | RainViewer available frame timestamps. |
| `/api/geo/proxy/isric?lon=&lat=&property=&depth=&value=` | ISRIC SoilGrids soil data (5 min cache). |
| `/api/geo/proxy/openweather?lat=&lon=&units=&input_id=` | OpenWeather overlay (key resolved server-side from `input_id`; a client-supplied key is ignored). |
| `/api/geo/proxy/kma?lat=&lon=&input_id=` | Korea Meteorological Administration API Hub surface data. |
| `/api/geo/proxy/openmeteo` | Open-Meteo forecast (60s failure cooldown per query to avoid hammering a down upstream). |
| `/api/geo/proxy/wms/<layer_id>?BBOX=&WIDTH=&HEIGHT=` | WMS `GetMap` tile proxy. Two-tier cache (disk + browser ETag); returns a transparent 1×1 PNG rather than an error if the upstream fails. |
| `/api/geo/tile/<layer_id>/<z>/<x>/<y>` | Generic keyed XYZ tile proxy (e.g. OpenWeather tile overlays). |
| `/api/geo/proxy/sentinelhub/<layer_id>?z=&x=&y=` | Sentinel Hub Process API tiles (OAuth2 credentials stay server-side). |
| `/api/geo/proxy/sentinelhub/<layer_id>/value?lat=&lon=` | Index value (NDVI etc.) at a point for the layer's legend box. 15 min cache. |
| `/api/geo/proxy/agromonitoring/<layer_id>?lat=&lon=` | Soil moisture/temperature/NDVI for a registered polygon. 30 min cache. |
| `/api/geo/tile_proxy?url=` | Generic tile proxy, allowlisted to `gibs.earthdata.nasa.gov`, `map.pstatic.net` (Naver), and `daumcdn.net` (Kakao) only. |

---

## Settings

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/settings` | Global GIS settings: `saved_state`, `geo_layers`, `search_inputs`, `search_provider`. |
| POST | `/api/geo/settings` | Updates global settings — search provider, zoom/culling thresholds, rendering toggles, and the `theme_*` color keys. Writes are serialized (one at a time) to avoid a lost-update race. |
| GET | `/api/geo/settings/length_unit` | `{length_unit, supported: ["mm","cm","m","in","ft"]}`. |
| PUT | `/api/geo/settings/length_unit` | Body: `{length_unit}`. Invalidates the cached client-side geo config immediately rather than waiting for its TTL. |

---

## Map Ordering

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/map/<map_uuid>/site_order` | Saved site-list display order, plus per-site zone order. |
| POST | `/api/geo/map/<map_uuid>/site_order` | Body: `{order}` and/or `{site_key, zone_order}`. |

---

## Time & Solar

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/local_time?lat=&lng=` | Local timezone/time plus a sunrise/sunset event window (yesterday through the day after tomorrow) — used by the map widget's clock dock. |
| GET | `/api/geo/sun_event?target_id=` | Today's sunrise/sunset (seconds of day) for whatever location a target inherits. |

---

## Plot/Zone Journal (`/geo/journal`)

**Different prefix** — these are under `/geo/journal`, not `/api/geo`. A journal is a generated report (GDD, DLI, day length, irrigation volume, weather) for a plot, zone, or site over a date range, built once in the background and then served from a stored snapshot.

| Method | Path | Description |
|---|---|---|
| GET | `/geo/journal/plot_history?area_id=` | Plots/crops that have occupied a given map area — used by the journal target picker. |
| GET | `/geo/journal` | The Journal hub page (recent journals + the create form). |
| POST | `/geo/journal` | Body: `{target_type: 'plot'\|'zone'\|'site', target_id, start, end, measurements?, granularity?}`. Rejects up front (before doing any work) if the requested period/channel count would be too expensive. Kicks off an async background build. JSON callers get `{ok, unique_id, url}`; others get a redirect. Requires `edit_plots`. |
| GET | `/geo/journal/<journal_uuid>?format=html\|md\|json\|csv\|odt&granularity=` | Reads the **stored** snapshot — never recomputes source data (some presentation-only values, like curve deltas, are computed at view time). `409` if a file format is requested before the build finishes. `csv` includes a UTF-8 BOM for Excel; `odt` is `application/vnd.oasis.opendocument.text`. |
| DELETE | `/geo/journal/<journal_uuid>` | Deletes the journal and any notes attached to it. Requires `edit_plots`. |
| GET | `/geo/journal/target_info?target_type=&target_id=` | Earliest available data date and available measurement groups for a target — used to pre-fill the create-journal form. Best-effort; failures degrade silently. |

---

## Other

- `POST /api/tools/kma_lookup` — a small standalone utility (different prefix, `/api/tools/`, not `/api/geo/`): nearest-neighbor lookup of the Korea Meteorological Administration's grid coordinates (nx, ny) for a given lat/lon.

---

## Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request (validation error) |
| 401 | Authentication required |
| 403 | Forbidden (permission, scope, or read-only API key) |
| 404 | Resource not found |
| 409 | Conflict (e.g. a binding slot already occupied, a delete blocked by references, a duplicate parcel import) |
| 500 | Server error |
