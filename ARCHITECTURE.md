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
- **MCP server** (`aot/aot_mcp_server.py`) speaks the Model Context Protocol to external clients. It boots the Flask app for its context and resolves calls through the same tool registry and execution layer the in-app assistant uses, so the two paths cannot drift. State-changing tools go through an approval queue and an audit log.
- **Deployment.** Direct install: systemd units `aot.service` (daemon), `aotflask.service` (web behind nginx), `aotmcp.service`. Docker: services `aot-app`, `aot_daemon`, `aot_mcp`, `influxdb` in `docker/docker-compose.prod.yml`; data, uploads, 3D assets, backups, and user scripts live in named volumes.

## 2. Package map (`aot/`)

| Layer | Packages | What is there |
|---|---|---|
| Control model (from Mycodo) | `inputs/` `outputs/` `functions/` `actions/` `controllers/` `devices/` `camera/` | Sensor and actuator modules, function modules, the controller thread base classes, hardware driver helpers. User extensions go in `*/custom_*`. |
| Space | `inputs_gis/` `aot_flask/geo/` `aot_flask/design_engine/` `aot_flask/routes_geo*.py` | External GIS, weather, satellite, and soil layers as Inputs; map, facility, plot, program, journal, device-binding services; the design tool. Routes are split by topic (`routes_geo_layer/shape/summary/schedule/device/map/facility.py` and the earlier `_iec/_plot/_journal/_commissioning/_device_split`), all sharing the one `routes_geo` blueprint. |
| Data | `databases/` `influxdb_config/` `config/` `utils/` | SQLAlchemy models, InfluxDB client, version and path constants, shared helpers (time, units). |
| Web | `aot_flask/` `widgets/` | `routes_*.py` blueprints, templates, static assets, forms, REST API; dashboard widget modules. |
| AI and MCP | `ai/` `aot_mcp_server.py` `mcp_server/` | In-app assistant (agent loop, context assembly, learning, knowledge); the external MCP entry script. `mcp_server/audit.py` is the tool-call audit log — the rest of that package was an earlier FastMCP prototype, unused and removed. |
| Tools | `tools/` | Tool registry, execution layer, approval gate, drawer implementations (`tools/data_tools/`); consumed by both the in-app assistant and the external MCP server. |
| Operations | `scripts/` `tests/` | Install and upgrade scripts, public-snapshot publishing, CI guard scripts; the unit, geo, e2e, and AI evaluation suites. |

## 3. Domain model

**Space.** `GeoMap` holds `GeoShape`s in a tree (`type` = site, zone, feature; `parent_id`). `GeoFacility` is a facility polygon with 3D geometry and components (vents, curtains, doors) bound to it. `GeoPlot` is a managed area instance (`kind` = vegetation, livestock, facility, other) that applies a `GeoProgram` (stage template: durations, targets, resources) and accumulates a `GeoJournal`. `GeoBinding` ties a space to the devices that serve it; `GeoMarkerPosition` records where a device was and when, so history survives moves and replacements.

**Devices.** `Input` measures (channels in `DeviceMeasurements`), `Output` acts (`OutputChannel`), `Function` combines them (PID, `Conditional`, `Trigger`, sequence, custom function modules). A **Device** is a function module that declares `is_device` and owns the Inputs and Outputs a piece of hardware needs (their `parent_device_id` points at it; `DeviceMember` lists reference-only members that are shown but not owned): one place for connection details, one switch for the whole set. Protocols: GPIO, I2C, 1-Wire, Modbus TCP, MQTT, HTTP, LoRaWAN (ChirpStack).

**Data.** `Measurement`, `Unit`, `Conversion` define what a channel means. Values live in InfluxDB keyed by device `unique_id` and channel; SQLite holds only configuration and entities.

**Control.** A trigger sequence runs steps with per-step gating and is the unit the AI proposes and the user approves. The environment coordinator (a custom function) does facility-scale control: PI loops over several actuators, geometry-aware venting, a safety pre-gate for wind, rain, heat, and cold. Schedules and calendar sync live in the scheduler.

**AI.** The tool registry groups tools into drawers (device, measurement, function, schedule, record, space, definition, system). `MCPConfirmation` is the approval queue for state-changing tools, `MCPAuditLog` the record. `AIAgent` holds a model and provider configuration; AoT is provider-agnostic. `Notes` carry place, time, and related-entity metadata so the AI can retrieve the history of a location by name.

What the AI needs to know about a device, and where it comes from:

| Question | Source |
|---|---|
| What is it | Device / Input / Output module type |
| Where is it | `GeoShape` marker, `GeoMarkerPosition` history |
| What does it measure | `DeviceMeasurements` channels |
| What does it control | `OutputChannel`s |
| How does it talk | connection fields on the Device |
| Which area does it serve | `GeoBinding`, device area split |
| What may it not do | safety gate, approval-required tool set |

## 4. Dependency rules

1. `aot_flask` does not import `controllers`. It talks to the daemon over RPC. (Holds today with one exception: a fallback in `routes_function.py` that runs a sequence step when the daemon is down.)
2. Daemon-side packages (`controllers`, `functions`, `inputs`, `outputs`, `actions`) do not import Flask or `aot_flask`. (Target. A number of files still do; guard `aot/scripts/check_import_layers.py` freezes the current violations in `import_layers_baseline.txt` — new ones fail CI.)
3. The tool layer (`aot/tools`) does not import the in-app assistant (`aot/ai`); what it needs from it arrives through `aot/tools/providers.py`, bound by `aot/ai/services/tool_providers.py` when `aot.ai` is imported. (Enforced by the `tools-no-ai` guard.)
4. Models in `databases/models/` do not import routes or services.
5. Anything that reads or writes the database in the daemon goes through `databases/utils.py` session helpers, never the Flask app context.

## 5. Guards that already run

CI (`.github/workflows/`): unit suite, e2e, alembic chain and `ALEMBIC_VERSION`, import layers (§4, new violations only — the current ones are frozen in a baseline file), AI tool registry single source of truth, driver dependency pins, geo data integrity, i18n catalog sync, JS bundle drift, static cache busting, security checks, docs health and deploy. `.githooks/` mirrors several of them at commit time. Failures on `main` open an issue automatically.
