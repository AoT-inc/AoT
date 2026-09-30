# GIS API Reference

All endpoints on this page require login (session cookie or an [API key](../Security.md#api-keys)). Endpoints that change data additionally require a permission — `edit_settings`, `edit_controllers`, or `edit_plots` depending on the resource — and endpoints tied to one map or facility further check that the caller's access group covers it (`scope.can_operate`). Each section below notes the permission where it isn't `edit_settings`.

> **Known duplication:** `POST /api/geo/designs`, `GET`/`DELETE /api/geo/designs/<uuid>`, and `GET`/`POST /api/geo/overlays` are each defined twice in the codebase (once as a flask-restx resource, once as a plain Flask route). Because of Flask's route-registration order, only the flask-restx version actually runs for these five — the plain-route copies are unreachable. The behavior documented below is the one that runs. This duplication is an internal cleanup item, not part of the documented contract, and could change without notice.

---

## Design Maps { #design-maps }

A "design" is one `GeoMap` row — a named map with its own center/zoom/layer state, holding all the shapes (sites, zones, facilities, devices) drawn on it. Creating, changing, deleting or restoring a map requires `edit_settings`, and the map must be inside the caller's granted scope (`403` otherwise).

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/init_design` | Loads the most recently updated map — this is not per-user, everyone lands on the same one. If no map exists yet, creates one named `Design Map 1` at the configured default location and zoom. Returns its full state. |
| GET | `/api/geo/designs` | Lists every map as `{unique_id, name, latitude, longitude, zoom}`. The center and zoom come from each map's saved camera; only a map that has none at all falls back to `[37.5665, 126.9780]` / zoom 13. |
| GET | `/api/geo/designs/list` | A second, near-identical listing, used by map selectors. Same shape and same values as the one above. |
| GET | `/api/geo/designs/<map_uuid>` | Full state of one map: `{ok, uuid, name, state}`. 404 if not found. |
| POST | `/api/geo/designs` | Create (omit `map_uuid`) or rename/update a map. Body: `{map_uuid?, name, state}` — `state` is merged into the map's existing state, not replaced. A `map_uuid` that no longer exists is created under that same id rather than failing. On create, `center`/`zoom` from the payload are ignored and the new map opens at the configured default start view. Response: `{ok, uuid, name}`. |
| DELETE | `/api/geo/designs/<map_uuid>` | Deletes the map and everything on it (facility setpoints → facilities → shapes → the map row). Returns `409 {blocked: true}` if something outside this map still references it. |
| POST | `/api/geo/maps/<map_uuid>/restore-original` | Reverts every shape on the map that has a stored pre-migration snapshot (`original_data`) back to that snapshot. Response: `{ok, map_uuid, restored, skipped}`. 400 if the migration-tracking columns don't exist yet (`alembic upgrade head` needed). |

---

## Overlays & Shapes (GeoJSON) { #overlays-shapes-geojson }

"Overlays" are the GeoJSON features drawn on a map — sites, zones, facility outlines, device markers, equipment.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/overlays/list?map_uuid=&target_type=&parent_id=&device_id=` | The same one-map `FeatureCollection` as below — note the filter is named `target_type` here, not `type`. Without `map_uuid` it returns an empty collection. |
| GET | `/api/geo/overlays?map_uuid=<uuid>&type=&parent_id=&device_id=` | One map's features as a GeoJSON `FeatureCollection`. `type` also matches legacy aliases (`equipment` ⇒ `equipment_collection`, `aot_device` ⇒ `device`). Each feature is enriched server-side with `db_id`, `shape_uuid` (the shape's own identifier — the client-made `node_id` is a different value), resolved `device_id`/`device_type`, `parent_id`, and (for `type=facility`) 3D metadata. Bundled equipment is unpacked back into individual features on the way out. |
| POST | `/api/geo/overlays` | Bulk save/replace for one `map_uuid` + `type`. See **Details** below — this is the trickiest endpoint on the page. |
| POST | `/api/geo/overlays/delta` | Send only what changed instead of the full feature set — for large maps. Body: `{map_uuid, upserts: [...], deletes: [node_id_or_db_id, ...]}`. Equipment upserts are merged into the bundled row, and transient sprinkler dot markers are dropped here too. Also requires `edit_settings` and map scope. |
| GET | `/api/geo/sites` | All `site`-type shapes as GeoJSON. `?map_uuid=` optional. |
| GET | `/api/geo/zones` | All `zone`-type shapes as GeoJSON. `?map_uuid=` optional. |
| GET | `/api/geo/shapes/<category>` | Any shape category (`site`, `zone`, `facility`, `feature`, ...) as GeoJSON. |
| POST | `/api/geo/generate-pipes` | Computes a branch-pipe route between devices without saving it. Body: `{parent_feature, ref_line, config, map_uuid}`. |

### Details: `POST /api/geo/overlays` { #details-post-apigeooverlays }

- Matches incoming features to existing rows by `db_id`, then `node_id` — everything else is derived from those.
- **A feature missing from the payload is never deleted.** Only an explicit `deletes: [node_id_or_db_id, ...]` list, or `features: []` combined with `allow_empty: true`, removes rows. (A prior incident wiped shapes because "not present" was once treated as "delete".)
- An empty `aot_device` payload is refused outright instead of clearing every marker — device placement only goes through `POST /api/geo/device/location`.
- `equipment` features are stored as one bundled `equipment_collection` row (the whole set is replaced together), everything else is saved feature-by-feature. Because the bundle path clears the old set first, an empty equipment payload is refused unless `allow_empty: true` confirms the clear, and it reports how many rows it would have deleted.
- Transient sprinkler dot markers are dropped rather than stored, so a payload made only of them counts as empty.
- Geometry rules are checked before anything is written, and a single invalid feature aborts the whole save with a geometry error (equipment is exempt from that check).
- `aot_type`, `device_id`, and `channel_id` are stripped from the saved JSON blob — they're derived on read, not stored, so don't rely on round-tripping them.
- Response: `{ok, count, id_map: {node_id: db_id}, stats: {deleted, updated, inserted}}` (or a `stats.mode: 'bulk_bundle'` shape for the equipment path).

---

## Search { #search }

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/search` | Geocoding/address search, proxied through whichever GIS input module is configured as the search provider. Body: `{query, type: 'address' (default), layer_id?}`. `layer_id` picks a specific `GeoLayer`; otherwise the map's configured `search_provider` setting is used, falling back to `gis_osm`. Response: `{ok, results}` (shape depends on the provider). |

---

## Device Binding { #device-binding }

A "binding" links a device (sensor or actuator) to a spatial slot — a zone polygon, a facility fitting, a sensor role, etc. Binding is a first-class object with history: ending one keeps the row (for audit) rather than deleting it. Writes require `edit_settings`.

Shared fields (`spatial_kind`, `spatial_id`, `role`, `device_id`, `device_kind`, `channel_id`, `measurement_id`) — see **Details** below.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/binding?spatial_kind=&spatial_id=&role=` | Current + past bindings for one slot. Response: `{ok, bindings, history}` (`history` is only entries that have ended). `400` if `spatial_kind` or `spatial_id` is missing. |
| POST | `/api/geo/binding` | Bind a device to an unoccupied slot. `409 {conflict: true}` if the slot is already bound; `400` on an unknown device/shape. |
| PUT | `/api/geo/binding` | Replace the device on a slot — ends the old binding (kept in history) and creates a new one in one call. |
| GET | `/api/geo/binding/unbound?kinds=&facility_uuid=&map_uuid=` | Lists slots with nothing currently bound (empty zone polygons, facility fittings that lost their device), for "what needs wiring" views. `kinds` should always be narrowed to specific spatial kinds. |
| DELETE | `/api/geo/binding/<binding_uid>` | Ends a binding (`valid_to` set; row kept). Body/query: `reason` (default `unbound`). `404` if the binding id doesn't exist. |

### Details: binding fields { #details-binding-fields }

- `spatial_kind`: `shape` \| `fitting` \| `actuator` \| `sensor_role` \| `weather`.
- `spatial_id`: the slot identifier. For `spatial_kind=shape` this can be either a saved `GeoShape.unique_id` or a client-side `node_id` not yet persisted — the server resolves it either way (send `map_uuid` as well so the not-yet-saved lookup stays inside one map).
- `role`: what the slot is for (`marker`, `area`, `actuator`, `sensor`, ...). For shape slots, the role is derived server-side from the shape's own `type` — a client-supplied role is not trusted for shapes. A shape whose type isn't a place to hang a device on (only zone polygons and location markers are) is rejected outright.
- `device_id`: accepts a `<device_uuid>::<channel>` suffix; it's split and the channel becomes `channel_id`.
- `device_kind` is always re-validated/resolved server-side even if supplied.

---

## Device Location, Lists & Detail { #device-location-lists-detail }

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/device/location` | Sets/moves a device's map position. Requires `edit_settings`, like the other map-editing writes. Body: `{unique_id, type, lat, lng, map_uuid?, channel_id?}` — `type` is one of `input\|output\|pid\|trigger\|conditional\|device\|function\|custom\|generic_function`, and `unique_id` may carry a `::<channel>` suffix instead of `channel_id`. The device's own coordinates are written only for channel `0`; a call for any other channel moves that channel's marker and leaves the device coordinates alone. If `map_uuid` is given, also places (or updates) that device's marker and derives which zone it falls in. Best-effort notifies the daemon to reload the device's settings (so a timezone change from the new location takes effect immediately). `404` if no such device exists; `403` if the device — or the map named by `map_uuid` — is outside the caller's granted scope. Response: `{ok, message, overlay_id}`. |
| GET | `/api/geo/devices?map_uuid=&device_ids=&include_all=` | Devices available for placement on a map. Response: `{ok, devices, all_measurements_map}`. Supports conditional (304) responses. |
| GET | `/api/geo/inputs` | Flat per-channel list (`DeviceMeasurements`) for the sensor-fitting binding picker — activated inputs only, each entry carrying the device, the channel, and a label with the converted unit. |
| GET | `/api/geo/outputs` | Flat `Output` list for the actuator-fitting binding picker, with each output's type and interface. |
| GET | `/api/geo/device/<device_uuid>/detail` | One device's full modal payload: identity, parent area, control kind (on/off, value, PWM, 3-way), channels, sub-devices for a compound device, and runtime info (elapsed/last-duration/pending schedules). `?channel=` (default `0`) picks which channel the runtime figures come from. |
| POST | `/api/geo/link_status` | Batch battery/RSSI lookup for map badges. Body: `{ids: [...]}` (max 100). A `null` battery or link means no channel carries that value — the badge is left off rather than drawn as zero. |
| POST | `/api/geo/device/split-apply` | Splits a zone into strips/grid cells and creates one device-marker shape per cell, auto-assigning each cell to whichever device marker falls inside it. Requires `edit_plots`. `name` sets the name base; optional `device_kind` narrows which kind of device may claim a cell — leave it empty and every kind is a candidate, which on a mixed map leaves most cells ambiguous. The server recomputes the geometry from the same parameters instead of trusting the polygons the preview showed. Shares those split parameters and its *preview* endpoint (`GET /api/geo/plot/split-preview`, below) with the cultivation-plot splitter — geometry math doesn't care whether the pieces end up as devices or plots. Response: `{ok, created, info, assigned, unassigned, message?}`, where `message` says how many cells ended up with no single device inside. |

---

## Zones { #zones }

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/zone/<zone_uuid>/contents` | Device inventory for the zone's "[환경·제어]" modal (sensors/outputs/functions inside it). 30-second server cache. |
| GET | `/api/geo/zone/<zone_uuid>/allocation?on=YYYY-MM-DD` | How the zone's area is divided among its cultivation plots (per-plot area/percentage, plus the unassigned remainder). Overlapping plots can sum past 100%, flagged as `overlaps`. |
| GET | `/api/geo/zone/<zone_uuid>/output_history?output_id=<uuid>&hours=` | Legacy alias for `GET /api/geo/output/<uuid>/history` (below). The zone in the path is only checked for existence — the history itself is looked up by `output_id` alone. |
| POST | `/api/geo/zone/<zone_uuid>/photo` | Multipart `photo` upload for the zone's representative image. |
| POST | `/api/geo/zone/<zone_uuid>/rep_key` | Sets/clears which measurement is the zone's "representative" reading. |
| POST | `/api/geo/zone/<zone_uuid>/hidden_rows` | Body: `{card, keys}` — which status-card rows to hide for this zone. |
| POST | `/api/geo/zone/<zone_uuid>/output_order` | Body: `{order}` — saves device display order for the zone's device list. |
| POST | `/api/geo/shape/<shape_uuid>/description` | Free-text description (≤2000 chars) for a site or zone. |

---

## Sites { #sites }

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/site/<site_uuid>/contents` | Device inventory inside a site (excludes facility-fitting actuators — those belong to their facility, not the enclosing site). |
| GET | `/api/geo/site/<site_uuid>/summary?force=` | Aggregated status / today's tasks / notes for the site. 30-second cache unless `force=1`. |
| GET | `/api/geo/site/<site_uuid>/weather` | Currently assigned weather-station device(s). Response: `{selected, source, candidates}`. |
| POST | `/api/geo/site/<site_uuid>/weather` | Body: `{device_ids: [...]}` (key required even if empty) — sets the site's weather source. |

---

## Facilities { #facilities }

A "facility" is a structure (greenhouse, barn, etc.) with an envelope (dimensions/material) and bound sensors/actuators.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/facility/list?geo_id=<map_uuid>` | All facilities, optionally scoped to one map. Each entry includes its `rep_key` and its outer footprint. |
| GET | `/api/geo/facility/<facility_uuid>` | Full facility record: envelope, device bindings, 3D geometry and view options, bays, and the last computed capacity. |
| POST | `/api/geo/facility` | Create or update (atomic across the outer record, envelope spec, and bays). Body includes `facility_uuid?` (omit to create), `geo_id` (required), `outer_geometry` (GeoJSON geometry, required when creating), `name`, `preset`, `structure`, `bay_count`, `geometry_3d: {span_width_m, length_m, eave_height_m, ridge_height_m, spacing_m, roof_type}`, `envelope` (covering layers plus side-vent/roof-vent/curtain settings), `actuators`, `fittings`, `bays`, `notes`. |
| POST | `/api/geo/facility/<facility_uuid>/clone` | Duplicates a facility, resetting its device bindings (a clone doesn't inherit the original's wiring). The copy is placed beside the original, not on top of it. |
| DELETE | `/api/geo/facility/<facility_uuid>` | Body/query: `confirm_name` must match the facility's current name. The outer shape and the bay shapes go with it. |
| POST | `/api/geo/facility/compute` | Engineering-calculation preview (area/volume/heating & cooling load/ventilation) for a given spec, without saving. Body: the same shape as a save — `geometry_3d`, `envelope`, `bay_count`, `structure`, plus `outer_geometry`/`fittings`/`actuators` when available. The figures are first-pass reference values (±5–10%) and come with a disclaimer note. `501` if the calculation module isn't available. |
| GET | `/api/geo/facility/<facility_uuid>/integration` | Unified sensor/actuator binding view — the same data the environment coordinator itself reads, alongside the envelope, the vent openings, and the computed capacity. |
| GET | `/api/geo/facility/<facility_uuid>/wind?speed=&dir=&pct=` | Natural-ventilation wind-pressure simulation. `speed` = wind speed in m/s (default 3.0), `dir` = meteorological wind direction 0–359° (default 0), `pct` = opening aperture ratio 0–100 (default 100). Returns the effective air changes per hour, in/outflow, per-opening flow, and a per-actuator wind bias. |
| POST | `/api/geo/facility/<facility_uuid>/apply` | Sends commands to the facility's bound actuators. Body: `{horizon, commands: [{kind, action, pct?}, ...]}`, with `action` one of `off`/`on`/`set`. `horizon` (`now`/`1h`/`6h`) is not a schedule — commands go out immediately and it only sets the simulation window. A `set` is translated into whatever the output actually supports (analog value, PWM, or a timed on/off), and a `kind` with no bound output is reported in `failed` instead of failing the request. When the VEE (Virtual Execution Engine) feature flag is on, runs an advisory pre-flight simulation first; dispatch itself goes through the daemon either way. |

Creating, cloning, deleting, computing, and applying require `edit_settings`; the read endpoints need only a login. Applying also requires operate permission for that facility. Commands and checks reach only the devices still bound to the facility — a severed binding is skipped.

Live runtime monitoring/control for a facility (real-time actuator state, safety setpoints, manual override, e-stop) is a **separate API family under a different prefix** — see [Facility Runtime Control](#facility-runtime-control-apiaotfacility-apiaotcoordinator) below.

### Facility 3D Model Assets { #facility-3d-model-assets }

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

### Facility Commissioning { #facility-commissioning }

Post-install verification: run automated checks against a facility's actuators, then record a human verdict per actuator. Requires `edit_settings` except the result read. Checks are held in memory, so a restart discards one in progress. The measurement stage only advances while something feeds the check periodic sensor readings, and nothing currently supplies them — so a started check stays at its opening baseline stage: no per-actuator results appear and a verdict cannot be submitted yet.

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/facility/<facility_uuid>/commissioning/start` | Body: `{actuator_ids?}` (omit = all facility actuators). Response: `{ok, check_id, actuator_count}`. `404` if the facility is unknown, `400` if there's nothing to check. |
| GET | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>` | Poll the check's status/results. Login only, no extra permission. `403` if the check belongs to a different facility, `404` if unknown. |
| POST | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict` | Body: `{actuator_id, verdict: 'ok'\|'sensor'\|'device'\|'external'\|'skip', note?}`. The verdict decides the follow-up actions returned in the response's `actions` list: `ok` adds a calibration anchor point, `sensor` marks the sensor untrusted and excludes the check window from data hygiene, `device` lowers a control gain bound and raises an alarm, `external` excludes the check window only, `skip` does nothing. Everything but the hygiene exclusion is recorded on the facility. `400` if the verdict value is unknown or that actuator has no result yet. |

---

## Facility Runtime Control (`/api/aot/facility`, `/api/aot/coordinator`) { #facility-runtime-control-apiaotfacility-apiaotcoordinator }

This is a **different URL prefix** (`/api/aot/`, not `/api/geo/`) for the live side of a facility once its environment coordinator is running: status, safety-range setpoints, manual override, e-stop, and history. It's the same conceptual object as the facilities above (same `facility_uuid`), just a separate route family.

| Method | Path | Description |
|---|---|---|
| GET | `/api/aot/facility/<facility_uuid>/status?function_uuid=` | Lightweight status badge for polling (~5s): `{level: 'idle'\|'warn'\|'active'\|'emergency', reasons, active_count, total_count, function_active, function_stale, function_name}`. |
| GET | `/api/aot/facility/<facility_uuid>/setpoints` | Saved **safety-range** limits plus `effective` (the live target the control loop is actually following, which comes from the plot's program/stage — not from here). |
| POST | `/api/aot/facility/<facility_uuid>/setpoints` | Requires `edit_settings`. Body: any of `guide_t_min_c`/`guide_t_max_c`, `guide_rh_min_pct`/`guide_rh_max_pct`, `temp_min_c`/`temp_max_c`, `humid_min_pct`/`humid_max_pct` (all range-validated). Sending `target_vpd_kpa`/`target_co2_ppm` here is rejected — targets are set through the cultivation program, not here. Mirrors changed values into every linked environment-coordinator function and triggers a live reload. |
| POST | `/api/aot/facility/<facility_uuid>/control` | Manual single-actuator control, bypassing the coordinator, with safety-gate interlocks (e.g. won't open a vent a wind-safety gate has forced shut). Requires `edit_settings` + facility scope. Body: `{slot_key, action: 'on'\|'off'\|'set', percent?, reason?}`. On an on/off device a `set` percent becomes proportional ON time inside a 60-second cycle (under 5% is treated as off). `400` if the gate blocks the request, `502` if the command never reached the device. |
| POST | `/api/aot/facility/<facility_uuid>/estop` | Emergency stop — **this stops the environment control as well, not just the outputs.** If any running environment coordinator controls this facility, its own emergency-stop command is used: every actuator is driven to its safe value (or switched off) and the coordinator's next cycle is held back 60 seconds, so it cannot move the equipment again right after. Only when no coordinator is attached or running — or one of them does not confirm the stop — does it fall back to commanding the outputs directly into a safe preset (heater/vents/fans/CO2/irrigation/lighting off, thermal curtain deployed, shade curtain retracted); on that fallback only devices currently bound to this facility are commanded. Body: `{confirm: "STOP"}` (exact string required). Requires `edit_settings`. The response says which path it took and carries the applied/failed counts with per-coordinator and per-device results; if even one actuator or coordinator could not be reached it is **not** `ok`. |
| GET | `/api/aot/facility/<facility_uuid>/runtime` | The heavy real-time snapshot: actuator states with operation history, the saved display order, indoor/outdoor sensors, bays, plots (planned ones included), bay capacities. On/off devices also carry a usual-day baseline (7-day daily average, today excluded); the operation history is cached 120 seconds. Sensor values come from the running coordinator's own cycle snapshot, otherwise from a cache refreshed in the background (20 seconds), so a first call can arrive with the sensors still filling in. Supports conditional (304) responses. |
| GET | `/api/aot/facility/<facility_uuid>/env_summary` | The coordinator's last-cycle summary as the daemon stored it (no time-series query — a cheap single-row read). Also flags whether it is stale, together with the threshold used for that call (three control cycles, at least 300 seconds). |
| GET | `/api/aot/facility/<facility_uuid>/env_week?bay=&days=` | Daily environment trend series (default 7 days, 1–31). 10-minute cache. Returns the window it drew (start/end dates) in the facility's own time zone. |
| GET | `/api/aot/facility/<facility_uuid>/actuator_history?slot_key=&hours=` | One actuator's operation history (percent/duty series, or on/off durations as a fallback). `hours` default 24, clamped 1–168. |
| GET | `/api/aot/facility/<facility_uuid>/overview?fresh=` | Bundles status + env_summary + info + irrigation + weather hazards + the program's limits + site + area status + representative reading + hidden rows + plot GDD/DLI into one call, so the map popup doesn't fire several requests at once. 30-second cache + single-flight lock; `fresh=1` bypasses it. |
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
| GET | `/api/aot/facility/<facility_uuid>/calibration_status` | Per-actuator control-loop calibration state and commissioning state for the linked coordinator, plus the model-accuracy check (temperature/humidity error) once it has passed. |
| GET | `/api/aot/coordinator/<function_uuid>/overview` | The environment-coordinator settings page header: which facility it controls, its live plots and their programs, which actuator kinds the facility actually has (so the page can show that a setting has no matching equipment), and (if another inactive coordinator duplicates it on the same facility) an `other_coordinator` warning. |
| GET | `/api/aot/coordinator/<function_uuid>/actuators` | Actuators this coordinator can control, which are currently disabled (`disabled_actuators` option), and which disabled entries are stale (no longer resolve to a live device). If the coordinator is scoped to one bay, only that bay's actuators are listed. |

---

## Cultivation Programs { #cultivation-programs }

A "program" is a reusable growth-stage template (stages, GDD/DLI targets, irrigation/fertilizer schedule) that a plot follows. Writes require `edit_plots`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/programs?subject=&kind=&tab_id=` | List programs a plot can use. `subject` also accepts `crop` as an alias. Sorted by subject, then variety. |
| GET | `/api/geo/program/<program_uuid>` | Full program detail including its stage list. |
| POST | `/api/geo/program` | Create. Body: `name`, `subject`/`crop`, `kind` (default `vegetation`), `stages`, `photosynthesis`, `target_defs`, `resource_defs`, `notes`, or `template_key` to seed from a built-in template. A template's stages and targets are *copied*, so later changes to the template never reach the program. Always saved as `source: 'user'`. |
| POST / PUT | `/api/geo/program/<program_uuid>` | Update. Built-in/external programs reject content edits — clone first (below). A `tab_id`-only payload is allowed even on a built-in (moving it between tabs isn't a content edit). If an AI agent writes any of the fields control actually reads (stages, target definitions, target curves, photosynthesis constants), `source` flips to `ai` and any prior review is cleared — and a program in that state is not used for control until someone reviews it. Edits that only touch the name, notes or tab don't trip that. |
| DELETE | `/api/geo/program/<program_uuid>` | Rejected if any plot still references it. |
| POST | `/api/geo/program/<program_uuid>/clone` | The only way to modify a built-in/external program — clones it into an editable copy. Body may override `name`, `subject`/`crop`, `kind`, `variety`, `stages`, `target_defs`, `photosynthesis`, `targets_methods`, `notes`, `tab_id`; the copy lands in the tab you pass (the default tab if you pass none), not the original's. Records `derived_from` for reference (not a live link). |
| GET | `/api/geo/program-templates` | Catalog of built-in seed templates (not stored in the database). Each entry reports its stage count, whether it carries targets, and whether it starts broad (a whole category, with its member subjects) or from one specific subject. |
| GET | `/api/geo/target-methods` | `Method` (time-axis curve) controllers that can be used as a program's target instead of a fixed per-stage value. New curves are drawn elsewhere, not here. |
| GET | `/api/geo/target-measurements` | Measurement vocabulary a target can bind to, plus the fixed target items of every kind — so a form can show another kind's items before anything is saved. Binding is optional: a target with no measurement behind it stays display-only. |
| GET | `/api/geo/coordinator/<function_uuid>/plot-targets?on=YYYY-MM-DD` | Read-only view of the plot(s) an environment-coordinator function currently follows and their stage targets — computed through the same code path control uses, so this can't drift from what's actually happening. Also reports whether the current user may pin a reference plot, so that button only appears when it would go through. |
| POST | `/api/geo/coordinator/<function_uuid>/reference-plot` | Body: `{plot_uuid}` (empty string clears it). Pins which overlapping plot a coordinator should treat as the reference, for intercropped zones with more than one candidate. `404` if the plot doesn't exist. Nothing is copied — control follows the pinned plot's stage targets from its next cycle. |

---

## Cultivation Plots

A "plot" (구획) is one planting cycle on a piece of ground or a facility bay — its own stage timeline, targets, and schedule, independent of the shared program it follows. Writes require `edit_plots`.

### Listing & detail { #listing-detail }

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

### Lifecycle & stage { #lifecycle-stage }

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/plot` | Create (no `unique_id`) or update (with one — partial save, only given fields change). Needs either a `feature` (GeoJSON) or a `facility_uuid`(+`bay_id`); `map_uuid`/`geo_id` is required only when no `facility_uuid` is given, since the facility already knows which map it is on. |
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

### Schedule { #schedule }

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/plot/<plot_uuid>/schedule` | Adjusts stage boundaries in bulk. Body: exactly one of `days` (`{stage_key: day_count}`, duration-based) or `plan` (`{stage_key: date|null}`, absolute-date based). |
| POST | `/api/geo/plot/<plot_uuid>/schedule/shift` | Shifts one stage boundary relatively. Body: `{stage_key, days: ±N}` — converted to an absolute date at save time, so a later shift never changes what an earlier "+7 days" meant. |

### Splitting a zone into plots { #splitting-a-zone-into-plots }

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/plot/split-preview?zone_id=&parts=\|strip_width_cm=\|widths_cm=&edge_margin_m=&min_length_cm=&orientation=&angle_deg=` | Computes a proposed strip/grid split of a shape **without saving anything** — the split is deterministic (same shape + params ⇒ same result), so no preview needs to be stored. |
| POST | `/api/geo/plot/split-apply` | Body: same split params, plus `subject` (required), `kind` (default `vegetation`), `variety`, `started_on`, `expected_end_on`, `color`, `name`. **Recomputes the split server-side from the same parameters — it never trusts a client-sent preview polygon** — then creates one plot per resulting strip. Response never reports full success if any single piece failed: `{ok, created, errors: [{index, message}], message}`. |

(The device-marker version of this splitter is `POST /api/geo/device/split-apply`, documented under [Device Location, Lists & Detail](#device-location-lists-detail) — it reuses this same `split-preview` endpoint since the geometry math doesn't care what the pieces become.)

---

## Manual Schedule { #manual-schedule }

A lightweight, non-device-actuating schedule entry (a note that a worker should do something on a date) — separate from the automatic device Scheduler.

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/schedule/<target_id>` | Upcoming schedule items for a shape/plot/facility, including its descendants. |
| POST | `/api/geo/schedule` | Body: `{target_id, date, time, content, worker}`. Requires `edit_controllers` — the same editor permission the Scheduler asks for. Roles below that can read the list but not add to it. |

---

## Output Control (map popups) { #output-control-map-popups }

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/output/<output_uuid>/state` | Turns an output on/off via the daemon. Body: `{state, channel, duration}`. Requires `edit_controllers` + device scope. |
| POST | `/api/geo/output_states` | Batch raw on/off state poll for a zone popup. Body: `{ids: [...]}`. Read-only — login only, no extra permission. |
| POST | `/api/geo/output_runtimes` | Heavier batch lookup (elapsed time, last duration, next scheduled run) — meant for modal-open time only, not polling. Body: `{items: [{id, channel}, ...]}` (max 60). |
| GET | `/api/geo/output/<output_uuid>/history?hours=` | Duty-cycle/on-off history series. `hours` 1–168, default 24. |
| POST | `/api/geo/function/<kind>/<func_uuid>/activate` | `kind` is `custom`\|`conditional`\|`pid`\|`trigger`\|`function`. Body: `{active: bool}`. Requires `edit_controllers`. |

---

## Parcel Import { #parcel-import }

Importing real-world parcel/park boundaries as map shapes.

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/parcel/from_address` | Body: `{address}`. Looks up a Korean cadastral parcel polygon via VWorld (API key resolved from the registered `gis_vworld` layer). |
| POST | `/api/geo/parcel/from_csv` | Multipart `file` — a CSV whose first column is addresses; batch-imports each. |
| POST | `/api/geo/parcel/save_as_site` | Body: `{feature, name, map_uuid}` (`map_uuid` required). Requires `edit_settings` + scope over the target map. Saves an imported parcel as a `site` shape. Rejects duplicate imports of the same parcel (`409`) by geometry key, and auto-creates a label shape alongside it. |
| GET | `/api/geo/import/gg_parks/preview?sigun_nm=&limit=` | Dry-run preview of Gyeonggi-do public-park boundaries available for import. |
| POST | `/api/geo/import/gg_parks` | Body: `{map_uuid, sigun_nm, limit, delay_sec}`. Requires `edit_settings` + scope over the target map. Saves the previewed parks as `site` shapes. |

---

## Aerial / Drone Image Overlays { #aerial-drone-image-overlays }

Georeferenced raster images (drone photos, aerial imagery) draped on the map. Upload and save require `edit_controllers`; the tiling poll only needs a signed-in session.

| Method | Path | Description |
|---|---|---|
| POST | `/api/geo/overlay_image/upload` | Multipart `file` + `layer_id`. Accepts `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.webp` up to 60 MB. Auto-georeferences from EXIF/XMP metadata if the layer has no prior placement; otherwise treats it as a texture swap onto the existing corners and reports the corners it kept. Large images are tiled into a pyramid and get a downscaled preview to show right away; small ones are served as a single image. |
| POST | `/api/geo/overlay_image/save` | Body: `{layer_id, coordinates: [[lng,lat], ...] (4 corners), opacity}`. Re-triggers tiling if the corners changed — for a large image that had no placement at upload time, this is where tiling actually starts. |
| GET | `/api/geo/overlay_image/tile_status/<layer_id>` | Polls tiling progress: `{tile_status, render_mode, tile_eligible, tile_url, minzoom, maxzoom, tile_count, tile_error}`. |

---

## Proxy Services { #proxy-services }

The server relays these external services so browser clients never see the upstream API key and don't hit CORS restrictions. All are `GET`, most cache the upstream response briefly (noted where known).

| Endpoint | Target |
|---|---|
| `/api/geo/layer_secrets?ids=` | Unmasked API keys/URLs for up to 12 registered layers (page-rendered lists mask these; only layers that are enabled can be revealed here). |
| `/api/geo/proxy/rainviewer/meta` | RainViewer radar metadata (5 min cache). |
| `/api/geo/proxy/rainviewer/timestamps` | RainViewer available frame timestamps. |
| `/api/geo/proxy/isric?lon=&lat=&property=&depth=&value=` | ISRIC SoilGrids soil data (5 min cache). |
| `/api/geo/proxy/openweather?lat=&lon=&units=&input_id=` | OpenWeather overlay (key resolved server-side — the layer named by `input_id`, otherwise the global map key; a client-supplied key is ignored). |
| `/api/geo/proxy/kma?lat=&lon=&input_id=` | Korea Meteorological Administration API Hub surface data. |
| `/api/geo/proxy/openmeteo` | Open-Meteo forecast (60s failure cooldown per query to avoid hammering a down upstream). |
| `/api/geo/proxy/wms/<layer_id>?BBOX=&WIDTH=&HEIGHT=` | WMS `GetMap` tile proxy. Two-tier cache (disk + browser ETag); returns a transparent 1×1 PNG rather than an error if the upstream fails. |
| `/api/geo/tile/<layer_id>/<z>/<x>/<y>` | Generic keyed XYZ tile proxy (e.g. OpenWeather tile overlays). |
| `/api/geo/proxy/sentinelhub/<layer_id>?z=&x=&y=` | Sentinel Hub Process API tiles (OAuth2 credentials stay server-side). |
| `/api/geo/proxy/sentinelhub/<layer_id>/value?lat=&lon=` | Index value (NDVI etc.) at a point for the layer's legend box. 15 min cache. |
| `/api/geo/proxy/agromonitoring/<layer_id>?lat=&lon=` | Soil moisture/temperature/NDVI for a registered polygon. 30 min cache. |
| `/api/geo/tile_proxy?url=` | Generic tile proxy, allowlisted to `gibs.earthdata.nasa.gov`, `map.pstatic.net` (Naver), and `daumcdn.net` (Kakao) only. |

---

## Settings { #settings }

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/settings` | Global GIS settings: `saved_state`, `geo_layers` (enabled layers only), `search_inputs`, `search_provider`. Requires settings-edit permission — `saved_state` carries the map providers' API keys in the clear, so a reader without it gets a permission error. |
| POST | `/api/geo/settings` | Updates global settings — search provider, whether the map library is served locally or from a CDN, the default map center and zoom, zoom/culling thresholds, rendering toggles, and the `theme_*` keys (colors plus the label/visibility toggles and panel background). Requires settings-edit permission. Writes are serialized (one at a time) to avoid a lost-update race. |
| GET | `/api/geo/settings/length_unit` | `{length_unit, supported: ["mm","cm","m","in","ft"]}`. |
| PUT | `/api/geo/settings/length_unit` | Body: `{length_unit}`. Invalidates the cached client-side geo config immediately rather than waiting for its TTL. |

---

## Map Ordering { #map-ordering }

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/map/<map_uuid>/site_order` | Saved site-list display order, plus per-site zone order. Login only. |
| POST | `/api/geo/map/<map_uuid>/site_order` | Body: `{order}` and/or `{site_key, zone_order}`. Requires `edit_settings` + map scope. |

---

## Time & Solar { #time-solar }

| Method | Path | Description |
|---|---|---|
| GET | `/api/geo/local_time?lat=&lng=` | Local timezone/time plus a sunrise/sunset event window (yesterday through the day after tomorrow) — used by the map widget's clock dock. |
| GET | `/api/geo/sun_event?target_id=` | Today's sunrise/sunset (seconds of day) for whatever location a target inherits. |

---

## Plot/Zone Journal (`/geo/journal`) { #plotzone-journal-geojournal }

**Different prefix** — these are under `/geo/journal`, not `/api/geo`. A journal is a generated report (GDD, DLI, day length, irrigation volume, weather) for a plot, zone, or site over a date range, built once in the background and then served from a stored snapshot.

| Method | Path | Description |
|---|---|---|
| GET | `/geo/journal/plot_history?area_id=` | Plots/crops that have occupied a given map area — used by the journal target picker. |
| GET | `/geo/journal` | The Journal hub page (recent journals + the create form). Opening it also recovers journals whose build was interrupted by a restart, so they stop saying "still being generated" forever. |
| POST | `/geo/journal` | Body: `{target_type: 'plot'\|'zone'\|'site', target_id, start, end, measurements?, granularity?}`. Rejects up front (before doing any work) if the requested period/channel count would be too expensive. Kicks off an async background build. JSON callers get `{ok, unique_id, url}`; others get a redirect. Requires `edit_plots`. |
| GET | `/geo/journal/<journal_uuid>?format=html\|md\|json\|csv\|odt&granularity=` | Reads the **stored** snapshot — never recomputes source data (some presentation-only values, like curve deltas, are computed at view time). `granularity` is `day`\|`week`\|`month`\|`stage`\|`all`, and can only be coarser than what was stored; the page opens stage-by-stage when the journal has stages, otherwise at the stored unit. `409` if a file format is requested before the build finishes. `csv` includes a UTF-8 BOM for Excel; `odt` is `application/vnd.oasis.opendocument.text`. |
| DELETE | `/geo/journal/<journal_uuid>` | Deletes the journal and any notes attached to it. Requires `edit_plots`. |
| GET | `/geo/journal/target_info?target_type=&target_id=` | Earliest available data date, today's date in the target's own timezone, and available measurement groups for a target — used to pre-fill the create-journal form. Best-effort; failures degrade silently. |

---

## Other { #other }

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
