# AoT architecture

One page. It says what runs, where the code lives, what the domain model is, and which way dependencies are allowed to point. Details live in `docs/design/` (index: [docs/design/README.md](docs/design/README.md)) and in the [manual](https://aot-inc.github.io/AoT). When this page grows past one screen, move the detail out rather than the other way round.

## 1. Processes and stores

```
                 ┌────────────────────────┐   Pyro5 RPC   ┌────────────────────────────┐
  browser ─────▶ │  Web UI                │ ◀───────────▶ │  Daemon                    │
                 │  aot/aot_flask (Flask, │               │  aot/aot_daemon.py         │
                 │  gunicorn, nginx)      │               │  controller threads:       │
                 └───────────┬────────────┘               │  Input · Output · Function │
                             │                            │  PID · Trigger · Sequence  │
  MCP client ──▶ ┌───────────┴────────────┐               └──────────────┬─────────────┘
  (Claude        │  MCP server            │                              │
   Desktop, …)   │  aot/aot_mcp_server.py │                              │
                 │  stdio or HTTP :5700   │                              │
                 └───────────┬────────────┘                              │
                             │                                           │
        ┌────────────────────┴───────────────────┐   ┌───────────────────┴───────────────┐
        │  SQLite  aot.db  (config, entities)    │   │  InfluxDB  (time series)          │
        │  migrations: alembic_db/               │   │  one series per device + channel  │
        └────────────────────────────────────────┘   └───────────────────────────────────┘
```

- **Web UI** serves pages, the dashboard, the REST API, and the in-app AI assistant. It never runs a controller itself; it asks the daemon over RPC.
- **Daemon** owns every controller thread. Inputs poll sensors and write InfluxDB; Outputs act; Functions (PID, conditionals, triggers, sequences, custom functions such as the environment coordinator) read measurements and drive Outputs.
- **MCP server** (`aot/aot_mcp_server.py`) speaks the Model Context Protocol to external clients. It boots the Flask app for its context and resolves calls through the same tool registry and execution layer the in-app assistant uses, so the two paths cannot drift. State-changing tools go through an approval queue and an audit log. It runs as a resident HTTP server or as a stdio process per client connection. The in-app assistant does not go through this server: it calls the same execution layer directly inside the web app (no subprocess). Code changes therefore reach the three paths at different moments (restart, reconnect, app restart). Clients authenticate with an API key, or with an OAuth bearer token issued either by a central authorization server (`aot/tools/mcp_central.py`, AoT verifies only) or by AoT itself acting as the authorization server (`aot/tools/mcp_embedded.py`, endpoints in `aot_flask/routes_oauth_embedded.py`). Each key carries a tool profile (`lite`, `operations`, `configuration`) that limits what is listed.
- **Deployment.** Direct install: systemd units `aot.service` (daemon), `aotflask.service` (web behind nginx), `aotmcp.service`. Docker: services `aot-app`, `aot_daemon`, `aot_mcp`, `influxdb` in `docker/docker-compose.prod.yml`; data, uploads, 3D assets, backups, and user scripts live in named volumes. The optional (experimental) Matter controller adds `matter_server` (matterjs-server on the host network) and `matter_socket` (a socat bridge exposing its loopback WebSocket as a unix socket) behind the compose profile `matter` (`COMPOSE_PROFILES=matter`); its `matter_data` volume holds the Matter fabric and is mounted read-only into `aot-app` and `aot_daemon`. The optional (experimental, preparing) digital twin runs as its own process — compose service `aot_twin` behind the profile `twin`, or the systemd unit `aottwin.service` (not enabled by default) — reads the local DB/InfluxDB directly and writes only `env_twin*` measurements; it does nothing until Settings > General > Digital Twin is on, and locks itself on low-spec devices (`aot/twin/`, `docs/design/digital-twin-node.md`). `docker/docker-compose.twin-nas.yml` runs the same service on a separate machine. Docker installs update through `aot_updater` (`docker/docker-compose.updater.yml`; it mounts the Docker socket, so it is a separate, opt-in stack) or the host unit `aot-docker-update.service`.

## 2. Package map (`aot/`)

| Layer | Packages | What is there |
|---|---|---|
| Control model (from Mycodo) | `inputs/` `outputs/` `functions/` `actions/` `controllers/` `devices/` `camera/` | Sensor and actuator modules, function modules, the controller thread base classes, hardware driver helpers. User extensions go in `*/custom_*`. |
| Cameras | `camera_drivers/` `camera/` `aot_flask/camera/` | `camera_drivers/` is the vendor-neutral driver frame (credentials, login lockout guard, events that fire triggers), shared by the daemon and web workers and independent of `camera/`. `camera/` is a separate capture package; `aot_flask/camera/` holds the web-side adapters. |
| Digital twin | `twin/` | The separate twin process (§1): discovery, forecast inputs, engine, expiry. |
| Space | `inputs_gis/` `aot_flask/geo/` `aot_flask/design_engine/` `aot_flask/routes_geo*.py` | External GIS, weather, satellite, and soil layers as Inputs; map, facility, plot, program, journal, device-binding services; the design tool. Routes are split by topic (`routes_geo_layer/shape/summary/schedule/device/map/facility.py` and the earlier `_iec/_plot/_journal/_commissioning/_device_split`), all sharing the one `routes_geo` blueprint. |
| Data | `databases/` `influxdb_config/` `config/` `utils/` `data/` | SQLAlchemy models, InfluxDB client, version and path constants, shared helpers (time, units), bundled reference data (`data/method_presets`). |
| Shared services | `services/` | Code used by the web app, the tool layer and the assistant alike: context assembly, target resolvers, warm and cold storage tiers, dashboard tabs, device references. It may not import route modules or the app factory (guard `services-no-web`); it still reaches into other `aot_flask` modules (extensions, access, geo, utils) in places. |
| Web | `aot_flask/` `widgets/` | `routes_*.py` blueprints, templates, static assets, forms, REST API; dashboard widget modules. |
| AI and MCP | `ai/` `aot_mcp_server.py` `mcp_server/` | In-app assistant (agent loop, context assembly, learning, knowledge); the external MCP entry script. `mcp_server/` holds the tool-call audit log (`audit.py`) and call-quality metrics computed from it (`quality.py`). |
| Tools | `tools/` | Tool registry, execution layer, approval gate, drawer implementations (`tools/data_tools/`), the domain surface (`tools/domain/`: operation registry, shared argument vocabulary, target resolution, response contract), MCP authentication (`mcp_auth.py`, `mcp_central.py`, `mcp_embedded.py`); consumed by both the in-app assistant and the external MCP server. |
| Operations | `scripts/` `tests/` | Install and upgrade scripts, public-snapshot publishing, CI guard scripts; the unit, geo, e2e, and AI evaluation suites. |

## 3. Domain model

**Space.** `GeoMap` holds `GeoShape`s in a tree (`type` = site, zone, feature; `parent_id`). `GeoFacility` is a facility polygon with 3D geometry and components (vents, curtains, doors) bound to it. `GeoPlot` is a managed area instance (`kind` = vegetation, livestock, facility, other) that applies a `GeoProgram` (stage template: durations, targets, resources) and accumulates a `GeoJournal`. `GeoBinding` ties a space to the devices that serve it; `GeoMarkerPosition` records where a device was and when, so history survives moves and replacements.

**Devices.** `Input` measures (channels in `DeviceMeasurements`), `Output` acts (`OutputChannel`), `Function` combines them (PID, `Conditional`, `Trigger`, sequence, custom function modules). A **Device** is a function module that declares `is_device` and owns the Inputs and Outputs a piece of hardware needs (their `parent_device_id` points at it; `DeviceMember` lists reference-only members that are shown but not owned): one place for connection details, one switch for the whole set. Protocols: GPIO, I2C, 1-Wire, Modbus TCP, MQTT, HTTP, LoRaWAN (ChirpStack), Matter (experimental; AoT joins devices from other ecosystems through Matter Multi-Admin).

**Data.** `Measurement`, `Unit`, `Conversion` define what a channel means. Values live in InfluxDB keyed by device `unique_id` and channel; SQLite holds only configuration and entities.

**Control.** A trigger sequence runs steps with per-step gating and is the unit the AI proposes and the user approves. The environment coordinator (a custom function) does facility-scale control: PI loops over several actuators, geometry-aware venting, a safety pre-gate for wind, rain, heat, and cold. Schedules and calendar sync live in the scheduler.

**AI.** Two tool surfaces sit on one execution layer. External MCP clients see, by default, the **domain surface**: 14 tools (`overview`, `find`, `measure`, `detail`, `weather`, `control`, `configure`, `cultivate`, `record`, `records`, `remove`, `screen`, `screen_view`, `help`), each taking an `operation` from a registry plus a shared argument vocabulary (`target`, `period`, …) resolved in one place (`docs/design/mcp-domain-surface.md`); tool and argument names are frozen by `test_mcp_surface_freeze.py`. The earlier per-function tools, grouped into drawers (device, measurement, function, schedule, record, space, definition, system), remain underneath as the operations' implementation, are still what the in-app assistant lists, and come back for external clients with `AOT_MCP_SURFACE=legacy`. `MCPConfirmation` is the approval queue for state-changing tools, `MCPAuditLog` the record. `AIAgent` holds a model and provider configuration; AoT is provider-agnostic. `Notes` carry place, time, and related-entity metadata so the AI can retrieve the history of a location by name. `TargetAlias` maps names people use to entities. `AIScreenCard` (with `AICardAttachment`) is a result card the server posts to the AoT screen — weather, place summaries and measured values are drawn by the server from a visualization spec, not hand-built by the model.

**Other entities.** `CameraDriver` and `CameraEvent` (camera connections and their events), `TwinConfig`, `TwinScenario` and `TwinRun` (digital twin), `OAuthClient`, `OAuthCode`, `OAuthGrant` and `MCPExternalAccount` (MCP sign-in), `GeoFavorite` (saved map places).

What the AI needs to know about a device, and where it comes from:

| Question | Source |
|---|---|
| What is it | Device / Input / Output module type |
| Where is it | `space/device_location.py` `locate()` — the one resolver; a location is the result of placement (map marker, facility component, binding), with `GeoMarkerPosition` as history |
| What does it measure | `DeviceMeasurements` channels |
| What does it control | `OutputChannel`s |
| How does it talk | connection fields on the Device |
| Which area does it serve | `GeoBinding`, device area split |
| What may it not do | safety gate, approval-required tool set |

## 4. Dependency rules

1. `aot_flask` does not import `controllers`. It talks to the daemon over RPC. (Holds today with one exception: a fallback in `routes_function.py` that runs a sequence step when the daemon is down.)
2. Daemon-side packages (`controllers`, `functions`, `inputs`, `outputs`, `actions`) do not import Flask or `aot_flask`. (Target. A number of files still do — mostly display functions that use helpers in `aot_flask/utils/`, and the environment coordinator, which still borrows one plot helper (`aot_flask/geo/coordinator_plot.py`); guard `aot/scripts/check_import_layers.py` freezes the current violations in `import_layers_baseline.txt` — new ones fail CI.) The rule keeps controller code independent of the web package; it does not mean the daemon process runs without a Flask app — see rule 5. Daemon-side code also does not import the in-app assistant (`aot.ai`); three places still do (two in the environment coordinator, one in `functions/base_function.py`); guard `daemon-no-ai` freezes them, so new ones fail.
3. The tool layer (`aot/tools`) does not import the in-app assistant (`aot/ai`); what it needs from it arrives through `aot/tools/providers.py`, bound by `aot/ai/services/tool_providers.py` when `aot.ai` is imported. (Enforced by the `tools-no-ai` guard.)
4. Models in `databases/models/` do not import routes or services. The SQLAlchemy and Marshmallow objects they are built on live in `databases/sqla.py`; `aot_flask/extensions.py` re-exports the same objects, so importing the models does not load the web package. The models still use Flask-SQLAlchemy, so `Model.query` and `db.session` need an app context as before. Guard `models-no-app` covers all of `databases/`.
5. The daemon process builds a Flask app of its own (`aot_daemon.py`: `create_app(run_scheduler=True)`), because it is the one process that runs the shared job store's schedules — two runners would fire every device-control job twice (`docs/design/scheduler-process-separation.md`, option A). Controller code still reads and writes the database through the `databases/utils.py` session helpers; reaching into that app's context from controller code is the exception, not the pattern.
6. Layer order, lowest first: `databases/models` → `utils`, space domain (`aot/space/`; the web-facing parts stay under `aot_flask/geo/`), `services` → `tools` → `ai`, web, daemon, twin, MCP server. A lower layer does not import a higher one; the guards above are this order applied to the pairs that have drifted. Pure calculations shared by several layers (psychrometrics, sensor status, light unit conversion) live in `aot/utils/`. The space domain lives in `aot/space/`: pure calculations (facility capacity, wind, bays and layout, irrigation nozzles, the facility ↔ coordinator link) and the services that read the map through the database session (device placement and binding, plot context and geometry, facility sensors and integration, device location, forecast series, weather state). The old `aot_flask/geo/<name>` paths are gone; import from `aot.space` only. Guard `space-no-web` keeps `aot/space/` off `flask_login`, `aot_flask`, `aot.ai` and `aot.tools`; plain `flask` (app-context primitives such as `current_app.logger`) and `flask_babel` are allowed, because the models already need Flask-SQLAlchemy and an app context. Known exceptions: `aot/space/facility_sensors.py` still imports one control module (`functions/utils/env_control/forecast_feedforward.py`, lazily), and the twin (`aot/twin/`) builds one Flask app lazily when it needs the space services (`twin/gate.py`; never on a locked low-spec device).

## 5. Guards that already run

CI workflows (`.github/workflows/` in this tree; the development repository runs the same checks on its own self-hosted runner rather than GitHub Actions): unit suite, e2e, alembic chain and `ALEMBIC_VERSION`, import layers (§4, new violations only — the current ones are frozen in a baseline file), AI tool registry single source of truth, driver dependency pins, geo data integrity, i18n catalog sync, JS bundle drift, MapLibre seam (map creation and engine internals only through `AoTMapSeam`; unit test `test_maplibre_seam.py`), static cache busting, security checks, docs health and deploy. `.githooks/` mirrors several of them at commit time. The workflow that opens an issue when `main` fails (`ci-failure-issue.yml`) works only where GitHub Actions run; the self-hosted runner sends no failure notifications, so its results are checked on demand.

## 6. Time

Principle: store UTC; show a place's date by converting each point with that place's clock. All time goes through `aot/utils/timekit.py`; no other module reads the OS clock or builds a timezone.

| Need | Use |
|---|---|
| Now | `utc_now()`; for naive DB columns `naive_utc(dt)` |
| Text or epoch to an instant | `parse_utc(value)` |
| Wall clock to an instant | `wall_to_utc(wall, where)` |
| Which clock | `tz_of(where)`; with its source `resolve_tz(where)` |
| An instant on a clock | `to_tz(value, where)`, `iso_at(value, where)` |
| Store or API text | `iso_utc(value)` |
| Today at a place | `today_at(where)` |

`where` is a target id, a row, a tz name, `FARM`, `VIEWER` or `None`. Unknown places fall back to the farm clock, then UTC. Browser code uses the matching names in `AoTTz`. The old entry names no longer exist. Guard: `aot/scripts/check_time_rules.py` (pre-commit and CI): the baseline is zero, so any new violation fails; the few places that cannot use the entries (output contracts such as `Z` text, the resolver's own floor, developer CLIs) are rows in the guard's `EXCEPTIONS` table with a one-line reason — a row without a reason, or one that no longer matches any violation, fails too. Design: `docs/design/timezone-management.md`.

`tz_of(id)` reads through a separate DB session, so it does not see changes that a transaction has flushed but not committed. To resolve a clock inside the same transaction, commit first or pass the row (`tz_of(row)` sees that row's uncommitted value; its parent chain is read as committed). Pinned by `aot/tests/geo/test_geo_overlays_tz_in_transaction.py`.
