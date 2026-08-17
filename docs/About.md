AoT is an open-source system for monitoring an environment with sensors and controlling devices remotely. It is not tied to any particular purpose or kind of site — greenhouses, barns, and fields, but equally parks, public infrastructure, and traffic: anywhere the things you want to watch are laid out in space.

It runs natively on single-board computers such as the [Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi), and in Docker on ordinary servers and PCs.

Two things define AoT:

- a **GIS digital twin** — every device, sensor, and structure has a real place on a map, and the map is the primary interface rather than a list of readouts;
- an **AI layer built on MCP** (Model Context Protocol) — an assistant that can read that map, diagnose it, and act on it, with your approval for anything that moves hardware.

Underneath both sits a proven Input / Output / Function control model, inherited from the Mycodo project AoT started out from (see [Origins](#origins)).

## GIS — Map, Facility, and Information

The map is not a viewer bolted onto a device list; it is where devices live.

- **Spatial hierarchy** — sites, zones, facilities, and planting areas form a real hierarchy, so a question like "what is happening in the east house" has a definite answer.
- **Facilities in 3D** — greenhouse and barn outlines are defined as polygons and visualized in 3D; vents, curtains, and other components are bound to the geometry and controlled from there.
- **GIS data sources** — weather, satellite, and soil layers are registered as Inputs, so external map data flows into the same time-series database as your sensors.
- **Devices on the map** — sensor Inputs and Output devices (valves, relays, curtains, vents) are placed on the map and operated directly from the map or facility view.
- **Geometry drives control** — facility-level environmental control uses the geometry itself: opening area, azimuth, and wind direction coordinate several actuators as a single feedback loop (for example, differential venting by wind side).

## AI and MCP

AoT exposes its whole system — devices, measurements, spatial tree, functions, schedules, notes — as MCP tools. Two paths use the same tool registry, so they never drift apart:

- **In-app assistant** — the chat assistant on the dashboard. A single agent loop sees the full tool catalog and chooses tools itself.
- **External MCP server** — `aot/aot_mcp_server.py` speaks standard MCP over stdio or HTTP, so an external client such as Claude Desktop can call AoT tools directly.

What the AI can do:

- **Observe and diagnose** — read sensor history, summarize zone conditions, spot anomalies, and answer questions grounded in your own facility data rather than generic advice.
- **Operate** — switch Outputs, schedule device control, and adjust setpoints. **Every state-changing action passes an approval gate** before it is applied: an approval card in the chat, or a pending queue for external MCP clients.
- **Build** — create and edit Inputs, Outputs, Functions, GIS shapes, and plantings on request.

Model choice is yours: Claude, Gemini, GPT, Mistral, Groq, and local Ollama models are all supported. AoT does not require, bundle, or default to any single provider.

## Control Model: Inputs, Outputs, and Functions

Everything above rests on three controller types:

- **Input** — acquires measurements and stores them in the InfluxDB time-series database. Measurements usually come from sensors, but can also be the return value of a Linux Bash / Python command, a math equation, or a GIS data source.
- **Output** — produces a change: switching GPIO pins (HIGH/LOW), generating PWM signals, driving pumps, publishing to MQTT, running commands, and more.
- **Function** — combines Inputs and Outputs into higher-level behavior: PID feedback loops, sequences, timers, conditionals, and Methods (a setpoint that changes over time).

A wide catalog of sensors, relays, and controllers is supported out of the box — see [Supported Inputs](Supported-Inputs.md) and [Supported Outputs](Supported-Outputs.md).

## Connectivity

- **LoRaWAN** — ChirpStack integration with a site-level Class A/C scheduler and downlink pacing for reliable valve commands.
- **Modbus TCP, MQTT, HTTP** — network-attached devices work identically in the direct and Docker installations.
- **GPIO, I2C, 1-Wire** — available in the direct install on Raspberry Pi pins.

## User Interface

- **Tab system** — Input, Output, Function, and dashboard pages are organized into tabs, so large device lists and multi-screen dashboards stay manageable.
- **Custom colors and styles** — brand colors, chart palettes, and light/dark themes are user-configurable and applied consistently across widgets and pages.

## Runs on Raspberry Pi and Docker

AoT can be installed natively on Raspberry Pi OS or Debian, or run in **Docker** on other platforms — the same application, whichever deployment fits your hardware.

## Origins { #origins }

AoT began as a customized build of the open-source [Mycodo](https://github.com/kizniche/Mycodo) project by Kyle T. Gabriel, which pairs sensor Inputs with device Outputs to sense and regulate an environment through a text- and graph-centered interface.

AoT kept that control model and rebuilt everything around it: a GIS digital twin in place of the device-list interface, an MCP-based AI layer, facility-scale environmental control, LoRaWAN device management, and a redesigned UI. Mycodo remains the foundation of the Input / Output / Function layer, and its contribution is gratefully acknowledged.
