# coding=utf-8
"""
PageContextService — server-side "what's on this dashboard" assembly.

The robust replacement for fragile DOM scraping (see
.local/plans/server_side_page_context_design.md). Given a dashboard_id, it reads
each widget's DATA BINDING (custom_options) — not its rendered DOM — and fetches
the current value via get_sensor_detail (the very tool the AI already uses). So
it works for every widget type (gauge SVG, graph canvas, map, …), not just
text-value widgets, and is immune to CSS-class drift.

Association (verified against live data): a dashboard's widgets are exactly the
Widget rows whose `tab_id == Dashboard.unique_id` — there is no separate Tab row
for a dashboard; the tab_id field holds the dashboard's own unique_id.

Binding format: custom_options values under any key containing "measurement" are
"<input_unique_id>,<device_measurement_unique_id>". The input id resolves the
device; the measurement id resolves which measurement of that device the widget
shows.

Read-only. Never raises — returns [] / '' on any failure.

@phase active
@stability new
@dependency Widget, DeviceMeasurements, AoTDataToolService.get_sensor_detail
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# Two comma-separated UUIDs = a measurement binding ("<input>,<measurement>").
_UUID = r'[0-9a-fA-F-]{36}'
_BINDING_RE = re.compile(rf'^({_UUID}),({_UUID})$')

# Cap how many widgets / distinct devices we touch, so a huge dashboard can't
# fan out into dozens of InfluxDB reads on the chat path.
_MAX_WIDGETS = 30
_MAX_DEVICES = 15


def _extract_bindings(custom_options):
    """Return [(input_uuid, measurement_uuid)] from a widget's custom_options
    JSON — any value under a key containing 'measurement' that looks like
    '<uuid>,<uuid>'. Empty on parse failure / no binding."""
    try:
        opts = json.loads(custom_options) if custom_options else {}
    except (ValueError, TypeError):
        return []
    if not isinstance(opts, dict):
        return []
    bindings = []
    for key, val in opts.items():
        if 'measurement' not in key.lower():
            continue
        if not isinstance(val, str):
            continue
        m = _BINDING_RE.match(val.strip())
        if m:
            bindings.append((m.group(1), m.group(2)))
    return bindings


def assemble(dashboard_id):
    """Assemble the current state of a dashboard's widgets.

    Returns a list of dicts:
      - data widget:   {widget, type, device, measurement, value, unit, time}
      - non-data widget (map/trigger/…): {widget, type, note: 'no measurement binding'}
    Read-only; [] on failure or unknown dashboard.
    """
    try:
        from aot.databases.models.dashboard import Widget
        from aot.databases.models import DeviceMeasurements
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        widgets = Widget.query.filter_by(tab_id=dashboard_id).limit(_MAX_WIDGETS).all()
        if not widgets:
            return []

        # 1. Collect bindings per widget + the set of distinct input devices.
        widget_bindings = []  # [(widget, [(input, meas), ...])]
        distinct_inputs = []
        for w in widgets:
            bindings = _extract_bindings(w.custom_options)
            widget_bindings.append((w, bindings))
            for inp, _meas in bindings:
                if inp not in distinct_inputs:
                    distinct_inputs.append(inp)
        distinct_inputs = distinct_inputs[:_MAX_DEVICES]

        # 2. Fetch current values once per distinct device (dedup — many gauges
        #    often share one weather input). Map measurement NAME -> reading.
        device_readings = {}   # input_uuid -> {measurement_name: {value, unit, time, device_name}}
        for inp in distinct_inputs:
            try:
                res = AoTDataToolService.get_sensor_detail(inp, limit=1)
            except Exception:
                res = None
            table = {}
            if isinstance(res, list):
                for entry in res:
                    readings = entry.get('readings') or []
                    if readings:
                        r0 = readings[-1]
                        table[(entry.get('measurement') or '').lower()] = {
                            'value': r0.get('v'), 'unit': r0.get('u'), 'time': r0.get('t'),
                            'device_name': entry.get('device_name'),
                        }
            device_readings[inp] = table

        # 3. Resolve each widget's measurement_uuid -> measurement name -> value.
        out = []
        for w, bindings in widget_bindings:
            if not bindings:
                out.append({'widget': _wname(w), 'type': w.graph_type, 'note': 'no measurement binding'})
                continue
            for inp, meas_uuid in bindings:
                meas_name = _measurement_name(meas_uuid, DeviceMeasurements)
                reading = device_readings.get(inp, {}).get((meas_name or '').lower())
                if reading and reading.get('value') is not None:
                    out.append({
                        'widget': _wname(w), 'type': w.graph_type,
                        'device': reading.get('device_name'),
                        'measurement': meas_name,
                        'value': reading.get('value'), 'unit': reading.get('unit'),
                        'time': reading.get('time'),
                    })
                else:
                    out.append({
                        'widget': _wname(w), 'type': w.graph_type,
                        'measurement': meas_name, 'note': 'no current value',
                    })
        return out
    except Exception as e:
        logger.debug(f"[PageContext] assemble failed for {dashboard_id}: {e}")
        return []


def _wname(w):
    try:
        return (w.name or 'Widget').strip()
    except Exception:
        return 'Widget'


def _measurement_name(meas_uuid, DeviceMeasurements):
    try:
        dm = DeviceMeasurements.query.filter_by(unique_id=meas_uuid).first()
        return (dm.measurement if dm else None) or None
    except Exception:
        return None


def assemble_as_text(dashboard_id, dashboard_name=None):
    """Server-assembled dashboard state as a compact prompt block, or '' if the
    dashboard has nothing readable. This replaces the fragile DOM-scraped
    '[Dashboard Visible Data]' block with reliable server-sourced values."""
    items = assemble(dashboard_id)
    if not items:
        return ''
    lines = []
    for it in items:
        if 'value' in it:
            unit = f" {it['unit']}" if it.get('unit') else ''
            lines.append(f"  - {it['widget']} ({it['type']}): {it.get('measurement','')} = {it['value']}{unit}")
        else:
            note = it.get('note', '')
            lines.append(f"  - {it['widget']} ({it['type']}): {note}")
    # English context block (an instruction to the AI, not user-facing output).
    # The AI reads this and answers in the USER'S language — do not hardcode a
    # human language here.
    header = f"[Current dashboard widget data (server-fetched{f', dashboard: {dashboard_name}' if dashboard_name else ''}) — what is on the user's screen right now]"
    return header + "\n" + "\n".join(lines) + "\n"
