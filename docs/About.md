AoT is an open-source environmental monitoring and control system for single-board computers such as the [Raspberry Pi](https://en.wikipedia.org/wiki/Raspberry_Pi). It also runs in Docker, so it can be deployed on a wide range of hardware.

## From Mycodo to a GIS Digital Twin

AoT began as a customized build of the open-source [Mycodo](https://github.com/kizniche/Mycodo) project, which pairs sensor **Inputs** with device **Outputs** to sense and regulate an environment. Mycodo's interface is centered on text readouts and graphs.

To make large, multi-site operations easier to understand and operate, AoT reorganized this around a **GIS-based digital twin** — a map- and facility-centric interface where every device, sensor, and structure has a real place on a map. On top of this foundation, AoT adds GIS, AI, and a redesigned UI, while keeping Mycodo's proven control model underneath.

## Core Model: Inputs, Outputs, and Functions

Everything in AoT builds on three controller types:

- **Input** — acquires measurements and stores them in the InfluxDB time-series database. Measurements usually come from sensors, but can also be the return value of a Linux Bash / Python command or a math equation.
- **Output** — produces a change: switching GPIO pins (HIGH/LOW), generating PWM signals, driving pumps, publishing to MQTT, running commands, and more.
- **Function** — combines Inputs and Outputs into higher-level behavior: PID feedback loops, sequences, timers, conditionals, and Methods (a setpoint that changes over time).

## Added Capabilities

The features AoT layers on top are described below in terms of how each one works with Inputs, Outputs, and Functions.

### GIS — Map, Facility, and Information

- **Input** — register GIS data-source inputs (weather, satellite, and soil layers), and place sensor Inputs on the map, binding them to a facility or zone for spatial monitoring.
- **Output** — place Output devices (valves, relays, curtains, vents) on the map and operate them directly from the map or facility view.
- **Function** — facility-level environmental control uses the GIS geometry — opening area, azimuth, and wind direction — to coordinate multiple actuators as a single feedback loop (for example, differential venting by wind side).

### AI

- **Input** — the AI observes Input measurements and diagnoses sensor anomalies, and can create or edit Inputs on request.
- **Output** — the AI can operate Outputs, but every write action requires explicit user approval before it is applied.
- **Function** — the AI can create and edit Functions, adjust setpoints, and give environmental-control advice grounded in your own facility data.

### UI — Tabs, Custom Colors, and Styles

- **Tab system** — the Input, Output, Function, and dashboard pages are organized into tabs, so large device lists and multi-screen dashboards stay manageable.
- **Custom colors and styles** — brand colors, chart palettes, and light/dark themes are user-configurable and applied consistently across widgets and pages.

## Runs on Raspberry Pi and Docker

AoT can be installed natively on Raspberry Pi OS or Debian, or run in **Docker** on other platforms — the same application, whichever deployment fits your hardware.
