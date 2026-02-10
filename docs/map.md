# AoT Map System Technical Overview

## 1. Introduction
The AoT Map system allows users to visualize devices, input/output states, and custom shapes on an interactive map. It supports both "Site Maps" (Level 1) and specific device group maps.

## 2. Architecture

### 2.1 Backend
-   **Widget Configuration (`AoT_map.py`)**:
    -   Defines the `AoT_map` widget class.
    -   Handles option parsing (e.g., `device_shape_opacity`, `include_all_devices`).
    -   Prepares data (`generate_page_variables`) passed to the frontend, including device lists and authentication tokens.
-   **API Endpoints (`api/map.py`)**:
    -   `GET /api/maps_map_overlays`: Retrieves shapes/overlays.
    -   `POST /api/maps_map_overlays`: Saves drawn shapes.
    -   Handles `map_uuid` vs `map_id` logic and device-specific filtering.

### 2.2 Frontend (JavaScript)
The frontend architecture is modularized into bundles:

-   **`aot-map-core.js` (`AoTMapApp`)**:
    -   Main entry point. Initializes the Leaflet map.
    -   Handles global configurations (API keys, styles).
    -   Manages state persistence (Zoom, Center, Layer, **Lock State** via `localStorage`).
    -   Starts polling for device status updates.
-   **`aot-map-features.js` (`DeviceLayer`)**:
    -   Manages device markers and interactions.
    -   **Markers**: Renders "Pill Style" text markers (`aot-map-text-marker`).
    -   **Popups**: Handles dynamic popup generation with **Toggle Switches** for output control.
    -   **Sync**: Updates marker colors and toggle states based on real-time polling data.
    -   **Shapes**: Renders device-associated shapes (circles, polygons) with configurable opacity.
-   **`aot-map-controllers.js`**:
    -   Manages the editing interface (`map_option.html`).
    -   Handles drawing tools (Leaflet.Draw) and saving shapes to the backend.
    -   Loads shapes based on context (Level 1 vs Device Mode).

## 3. Key Features

### 3.1 Device Control (Toggle Switch)
-   **UI**: A CSS-styled toggle switch (`.btn-toggle`) replaces the old On/Off button.
-   **Interaction**: Clicking the label opens a popup. The popup content is regenerated dynamically on each open to ensure freshness.
-   **Logic**:
    -   Uses `isDeviceOn(status)` helper to handle various backend status values ('active', 'on', 'true', '1').
    -   Implements a **Grace Period (2000ms)** to prevent stale poll data from reverting the switch immediately after user interaction.
    -   API Call: `/output_mod/ID/CHANNEL/ACTION/UNIT/DURATION`.

### 3.2 Visual Customization
-   **Device Markers**: Text-based pill markers that adapt text color for contrast against the background color.
-   **Shape Opacity**: Configurable via `device_shape_opacity` (0-100%). Controls the transparency of shapes linked to devices.

### 3.3 Persistence
-   **Map Lock**: The "Lock Map" button state is saved in the browser's `localStorage` and restored upon page reload.
-   **View State**: Center, Zoom, and Base Layer are persisted via the backend `MapConfig` or `WidgetConfig`.

## 4. Configuration Options (`AoT_map.py`)

| Option Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `device_ids` | List | [] | Specific devices to show. |
| `include_all_devices` | Bool | True | If true, shows all accessible devices. |
| `device_shape_opacity` | Int | 50 | Opacity of device shapes (0-100). |
| `map_locked` | Bool | False | Default lock state (overridden by localStorage). |
| `show_drawn_shapes` | Bool | False | Whether to load custom drawn shapes. |

## 5. Recent Improvements (v8.17.0)
1.  **Fixed Sync**: Resolved mismatch between toggle button state and actual device state.
2.  **Fixed API**: Corrected URL structure for device control commands.
3.  **Stability**: Fixed `ReferenceError` (feats, found), `NameError` (misc), and `TypeError` (context).
4.  **UX**: Added Map Lock persistence and Opacity setting.
