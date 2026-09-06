# AoT Time Handling

This page explains how AoT handles time and timezones. The design background and
decisions live in the repository at `docs/design/timezone-management.md` (dev-only,
not published in the manual); this page covers how it actually behaves and what
developers should use.

---

## 1. At a glance — three core rules

1. **Storage is always UTC.** Every timestamp in the database, InfluxDB, and logs is
   UTC.
2. **Display uses whichever clock fits the context.** A device schedule is shown in
   *the device's local time*; a personal notification is shown in *the viewer's time*.
3. **There is one entry point for interpretation.** All timezone-related calculations
   go through `aot/utils/timekit.py`.

---

## 2. Time comes in two kinds

Everything else starts from distinguishing these two.

| | A. Instant | B. Wall-clock intent |
|---|---|---|
| Example | A sensor reading, a log entry, `created_at`, "the moment the valve opened" | "Irrigate at 06:00", "schedule it every early morning" |
| Nature | A point on the timeline | A time someone stated using a particular clock |
| Storage | UTC alone is sufficient and unambiguous | Can't be collapsed to UTC directly — needs **whose 06:00** (an anchor) |
| Display | Just convert to the desired tz | Must be converted back through the anchor tz or the intent is lost |

> **Why this matters:** "irrigate at 06:00 for a device in a +6 region" means watering
> when that field's clock reads 6 AM — not when a +9 office's clock does. A wall-clock
> intent is meaningless without also knowing **whose clock** it refers to.

---

## 3. The four timezone layers, plus the host clock

Four sources of timezone are involved in the system, and they can all differ from one
another.

| Layer | What it is | Where it's stored |
|---|---|---|
| **Device tz** | The location timezone of each device (input/output/function/PID…) | `input.timezone`, etc. (derived from coordinates/inheritance and cached) |
| **Shape tz** | The timezone of a map shape (site/zone/facility) — the **authority** for tz | `geo_shape.timezone`, `geo_facility.timezone` |
| **User tz** | An individual's display preference | `users.timezone` (falls back to the system if unset) |
| **System tz** | The farm-wide default (the last resort) | `misc.timezone` |

Separate from all four, there is the **host OS clock**.

- **The host OS clock is the sole source of "now" — it is not a timezone.** Docker
  containers are always treated as UTC and never depend on the OS's local tz. Its only
  job is to give `timekit.utc_now()` the **current UTC instant**. Scheduler firing is
  decided purely by `fire_utc <= utc_now()`; no timezone is involved in that
  comparison.
- **`misc.timezone` (the system tz) is only the "farm default" fallback of last
  resort — it does not interpret intent.** Once a device or shape has a location, it
  never falls back to the system tz. When the system tz genuinely is used, that fact
  is recorded and labeled.

---

## 4. The storage convention — why mixed naive datetimes are safe

- **New code uses tz-aware UTC** (`timekit.utc_now()`, equivalent to
  `datetime.now(timezone.utc)`).
- **A lot of legacy code still uses naive `datetime.utcnow()`.** This is not a bug —
  by project convention, **a naive datetime is assumed to be UTC**, and
  `timekit.ensure_utc()` normalizes it by attaching `+00:00` at the point it's read.
- **Round-tripping through a SQLite column is also safe.** Storing an aware UTC value
  (`00:00+00:00`) into a naive `DateTime` column makes SQLite/SQLAlchemy strip only the
  tzinfo, keeping the value itself (UTC 00:00) intact. Reading it back gives a naive
  `00:00`, which `ensure_utc` restores to `00:00+00:00`. **SQL filters**
  (`schedule_time >= utc_now()`) are correct for the same reason — the tz is stripped
  at bind time, so the comparison ends up naive-UTC vs. naive-UTC.

> **Pitfall:** a column that stores naive values must **only ever receive UTC-aware
> (or UTC-equivalent naive) values.** Storing an `Asia/Seoul`-aware value directly
> strips its tzinfo and the Seoul wall-clock value gets mistaken for UTC, landing 9
> hours off. Always convert to UTC before storing (`wall_to_utc`; `utc_now` is already
> UTC).

---

## 5. The single resolver — `aot/utils/timekit.py`

Everything timezone-related converges on this module. Gates that used to be scattered
around the codebase (`get_device_tz`, `get_user_tz`, `get_timezone_name`,
`resolve_location_tz`, etc.) now delegate to it.

| Function | Purpose |
|---|---|
| `utc_now()` / `now_utc()` | tz-aware current UTC "now" |
| `ensure_utc(dt)` | Normalizes: naive assumed UTC, aware converted to UTC |
| `to_tz(dt, tz)` | UTC (or naive=UTC) to a target tz |
| `iso_utc(dt)` | The API serialization standard — always a `+00:00` ISO string |
| `resolve_tz(entity=None, *, user=None) → (tzinfo, source)` | **The single resolution chain** (below) |
| `system_tz()` / `system_tz_name()` | The farm-wide default tz (Misc) |
| `current_user_tz()` | The requesting user's personal tz (system if unset). For personal display only |
| `wall_to_utc(wall, tz)` | Wall-clock time + anchor tz → UTC-aware (schedule storage, DST-correct) |
| `utc_to_wall(dt, tz)` | UTC → wall-clock time in the anchor tz (schedule display) |

### `resolve_tz` priority chain

```
entity is a shape (GeoShape/GeoFacility):
    uses its own inheritance-aware resolver (stored value → parent → facility → centroid)
entity is a device row:
    1. entity.timezone (materialized cache)        → cache's tz_source
    2. inherited from its shape (device_id→shape→parent chain) → inherited
    3. entity coordinates → timezonefinder          → coords
    4. system (Misc.timezone)                       → system
user:
    User.timezone → system
entity=None:
    system → UTC
```

> **Reads are O(1):** a device's `timezone` column is a **materialized cache**.
> Coordinate-to-timezone conversion (`timezonefinder`) is expensive, but it only runs
> once, when a shape or device is **created or edited**, and the result is stored in
> the column. Execution paths such as scheduler firing and display only read that
> column.

---

## 6. How a schedule flows (a +9 user / +6 device example)

Say a user in Seoul (+9) schedules "irrigate at 06:00" for a valve in Bangladesh
(Dhaka, +6).

```
1. Anchor decided : the target is a device, so anchor tz = device local (Asia/Dhaka, +6)
                     (_resolve_schedule_anchor)
2. Stored          : wall_to_utc("06:00", Asia/Dhaka) = 2026-07-22 00:00Z
                     SchedulerJobMeta.schedule_time=00:00Z, anchor_tz='Asia/Dhaka'
3. Fires           : executes once utc_now() reaches 00:00Z (tz plays no part)
4. Shown (ops)     : device local 06:00 (Asia/Dhaka) — _schedule_summary.when
5. Shown (user)    : the same instant converted to Seoul → 09:00 (Asia/Seoul)
```

**The point:** only one UTC value (`00:00Z`) is stored, and `06:00` (device) and
`09:00` (user) are just two representations of that same instant. The new-task form
shows all three together as a **live dual clock**:

```
Irrigate · [Valve 6 (+6)] · 06:00
  Device-local: 2026-07-22 06:00 (Asia/Dhaka)   ← what actually fires
  Your time:    2026-07-22 09:00 (Asia/Seoul)   ← your screen
  UTC:          2026-07-22 00:00
```

> **Settled policy:** a device schedule's wall-clock time is interpreted as **the
> device's local time by default** (following the crop's solar day). The
> `datetime-local` seed value in the edit form is also shown in device-local time, so
> it matches the storage interpretation and round-trips without drifting.

---

## 7. Display rules

Context determines the tz. **The server never bakes in a specific tz.**

| Context | Clock | Method |
|---|---|---|
| Operations (scheduler, device logs, "when did it fire") | **Device tz** + label | Frontend `AoTTz.formatDevice(iso, deviceTz)` |
| Personal (user notifications, "what you just did") | **Viewer/user tz** | `AoTTz.formatViewer(iso)` |
| A calendar axis spanning multiple tz's | **Viewer tz** | FullCalendar `timeZone:'local'` |

- The server API only ever returns **UTC ISO** (`iso_utc`); the display tz is chosen
  client-side by `AoTTz`.
- The single frontend utility is `aot/aot_flask/static/js/common/aot-tz.js`
  (`window.AoTTz`).
  - `formatDevice(iso, tz)` — device local time
  - `formatViewer(iso)` — viewer (personal tz first, then browser, then system)
  - `wallToInstant(wall, tz)` — interprets a wall-clock value against a tz and returns
    the absolute instant (used for the dual clock)
  - The viewer tz is resolved as `<meta name="aot-user-tz">` (User.timezone) >
    browser tz > `aot-fallback-tz` (system).

---

## 8. Timezone inheritance (the shape tree)

Even with thousands of devices, the timezone is never computed per device. **The tz
is a property of the location group.**

```
Site (GeoShape)      → the tz authority. Explicit override | one-time centroid resolve → materialized
 └ Zone (GeoShape)   → inherits from Site. Override if needed → materialized
     └ Device        → inherits from its Zone/Site (cached)
```

- The shape tree is built from `geo_shape.parent_id` (self-referencing); the link to a
  physical device is `geo_shape.device_id`.
- `tz_source` (`explicit` | `inherited` | `coords`) records where a value came from.
  `explicit` (a manual override, or a boundary-group selection) is treated as
  **pinned** and is not overwritten by automatic updates.
- **Materialization and propagation:** after a map save commits
  (`save_overlays`/`save_delta`), `GeoOverlayManager.materialize_timezones(map_uuid)`
  computes and caches tz in site→zone→device order and propagates it to linked
  devices. A parent shape's tz override flows down to its children and devices.

---

## 9. Timezone boundaries / the date line

An operational group doesn't split just because it straddles a boundary.

- Even when a field straddles a tz boundary, **the site settles on a single tz and the
  whole subtree inherits it** — one field, one clock.
- Boundary detection happens **once, at edit time**: when a shape is saved,
  `GeoShape.detect_tz_boundary()` looks up the tz at all four corners of its bounding
  box and marks `tz_boundary=True` if they differ.
- `timezonefinder` resolves tz by **legal (political) boundary**, so it already
  correctly returns "legal time that differs from solar time" cases such as all of
  China at +8, Spain at +1, or Kazakhstan's Almaty at +5.

---

## 10. Developer quick reference — "what to use, when"

| What you want | What to use |
|---|---|
| "Now" (UTC) | `timekit.utc_now()` |
| Normalize a stored naive/aware datetime to UTC | `timekit.ensure_utc(dt)` |
| Serialize a timestamp for an API response | `timekit.iso_utc(dt)` → frontend `AoTTz` |
| Find an entity's timezone | `timekit.resolve_tz(entity)` (or `device_tz.get_device_tz`) |
| Get the local timezone from a location id | `device_tz.resolve_location_tz(target_id)` |
| Schedule wall-clock time → storage | `timekit.wall_to_utc(wall, anchor_tz)` |
| Schedule UTC → display | `timekit.utc_to_wall(dt, tz)` or `to_tz` |
| Personal display tz (per request) | `timekit.current_user_tz()` |
| Show a device's time in the frontend | `AoTTz.formatDevice(iso, deviceTz)` |
| Show my own time in the frontend | `AoTTz.formatViewer(iso)` |

---

## 11. Pitfalls

- **Only UTC values in a naive column.** Storing a non-UTC aware value strips its
  tzinfo and it gets misread (see §4).
- **Interpret wall-clock values against the anchor tz.** Using the user's browser tz
  or the system tz instead breaks for devices in a different tz. Schedules use
  `wall_to_utc(wall, device_anchor)`.
- **`get_user_tz()` is actually the system tz**, despite its name — it is not the
  personal tz (it exists for wall-clock interpretation and daemon compatibility). Use
  `current_user_tz()` for personal display.
- **`serialize_ts()` converts on the server using the system tz.** Don't use it for
  anything device-related — use `iso_utc` + `AoTTz` instead. (The scheduler's
  `_serialize_job` still uses `serialize_ts` for its `decided_at`/`executed_at`/
  `created_at` audit metadata — a known, minor gap.)
- **Don't treat `datetime.now()` (system local) as "UTC now."** It happens to match
  inside Docker, but drifts on a non-UTC host. Use `utc_now()` instead. (A
  `datetime.now()` used for elapsed-time measurement or offset calculation is
  intentional and stays as-is.)
- **A device's `timezone` cache only updates on a location-edit event.** If you change
  coordinates and the tz doesn't change, check the materialization
  (`materialize_timezones`) path or the coordinate listener.

---

## 12. Related files

- Backend single entry point: `aot/utils/timekit.py`
- Coordinate-to-tz / location resolution: `aot/utils/device_tz.py`
- Shape tz / inheritance / boundaries: `aot/databases/models/geo.py`,
  `aot/aot_flask/geo/geo_overlays.py`
- Coordinate-to-tz auto-materialization listener:
  `aot/databases/device_tz_listeners.py`
- Schedule anchor / display: `aot/ai/services/aot_data_tool_service.py`,
  `aot/aot_flask/routes_scheduler.py`
- Frontend display utility: `aot/aot_flask/static/js/common/aot-tz.js`
- Design and decisions: `docs/design/timezone-management.md` (dev-only, not published
  in the manual)
- Earlier audit report: `docs/design/timezone_audit.md` (dev-only, not published in
  the manual)
