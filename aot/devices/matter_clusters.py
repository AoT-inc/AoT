# coding=utf-8
"""Matter cluster → AoT channel mapping (pure functions, no I/O).

A commissioned node arrives from the Matter server as a flat attribute dict
keyed "endpoint/cluster/attribute" in decimal ids (aot/devices/matter_client.py).
This module reads that dict and answers three questions for the rest of AoT:

  - which Input channels the node offers (sensors we know how to scale),
  - which Output channels it offers (actuators we know how to drive),
  - who the node is (BasicInformation), so a re-shared device can be matched
    to its existing AoT Device instead of starting a new history.

Only clusters in SENSOR_SPECS / ACTUATOR_SPECS are mapped; everything else on
the node is ignored. Phase 1 scope: docs/design/matter-controller.md §4-2.

@phase experimental
@stability experimental
"""
import math

# Cluster ids (Matter Application Cluster Specification).
DESCRIPTOR = 0x001D
BASIC_INFORMATION = 0x0028
BRIDGED_DEVICE_BASIC_INFORMATION = 0x0039
POWER_SOURCE = 0x002F
BOOLEAN_STATE = 0x0045
ON_OFF = 0x0006
ILLUMINANCE_MEASUREMENT = 0x0400
TEMPERATURE_MEASUREMENT = 0x0402
PRESSURE_MEASUREMENT = 0x0403
FLOW_MEASUREMENT = 0x0404
RELATIVE_HUMIDITY_MEASUREMENT = 0x0405
OCCUPANCY_SENSING = 0x0406
CO2_CONCENTRATION = 0x040D
PM25_CONCENTRATION = 0x042A
SOIL_MEASUREMENT = 0x0430
ELECTRICAL_POWER_MEASUREMENT = 0x0090
ELECTRICAL_ENERGY_MEASUREMENT = 0x0091
LEVEL_CONTROL = 0x0008
WINDOW_COVERING = 0x0102
SWITCH = 0x003B

# Switch cluster events (Matter: InitialPress=1 … MultiPressComplete=6).
SWITCH_EV_INITIAL_PRESS = 1
SWITCH_EV_LONG_PRESS = 2
SWITCH_EV_SHORT_RELEASE = 3
SWITCH_EV_LONG_RELEASE = 4
SWITCH_EV_MULTI_PRESS_COMPLETE = 6
# Switch FeatureMap bits.
SWITCH_FEATURE_MOMENTARY = 1 << 1
SWITCH_FEATURE_RELEASE = 1 << 2
SWITCH_FEATURE_MULTI_PRESS = 1 << 4
FEATURE_MAP_ATTR = 0xFFFC

# Device types (Descriptor DeviceTypeList) whose LevelControl is a dimmer:
# Dimmable Light, Dimmable Plug-in Unit, Color Temperature Light, Extended
# Color Light.
DIMMABLE_DEVICE_TYPES = frozenset({0x0101, 0x010B, 0x010C, 0x010D})

# What a button channel records for one gesture: the press count, or this
# for a long press. Written at event time only (never re-sampled).
BUTTON_LONG_PRESS_VALUE = -1.0

# WindowCovering.
WC_FEATURE_LIFT = 1 << 0
WC_FEATURE_POSITION_AWARE_LIFT = 1 << 2
WC_CURRENT_LIFT_100THS = 14
WC_TARGET_LIFT_100THS = 11
WC_OPERATIONAL_STATUS = 10

# ConcentrationMeasurement.MeasurementUnit (attribute 8).
CONC_UNIT_PPM = 0
CONC_UNIT_UGM3 = 4
CONC_MEASUREMENT_UNIT_ATTR = 8

# Descriptor attributes.
DESCRIPTOR_DEVICE_TYPE_LIST = 0
DESCRIPTOR_SERVER_LIST = 1

# BasicInformation attributes (endpoint 0).
BI_VENDOR_NAME = 1
BI_VENDOR_ID = 2
BI_PRODUCT_NAME = 3
BI_PRODUCT_ID = 4
BI_NODE_LABEL = 5
BI_SERIAL_NUMBER = 15
BI_UNIQUE_ID = 18
# BridgedDeviceBasicInformation uses the same attribute ids for these.


def _temperature(raw):
    return raw / 100.0          # int16, 0.01 °C


def _humidity(raw):
    return raw / 100.0          # uint16, 0.01 %


def _illuminance(raw):
    # MeasuredValue = 10000 * log10(lux) + 1; 0 means "too low to measure".
    if raw <= 0:
        return 0.0
    return round(math.pow(10, (raw - 1) / 10000.0), 3)


def _boolean(raw):
    return 1.0 if raw else 0.0


def _battery(raw):
    return raw / 2.0            # uint8, half-percent steps


def _pressure(raw):
    return raw / 10.0           # int16, 0.1 kPa


def _flow(raw):
    return round(raw / 10.0 * 1000.0 / 60.0, 3)   # uint16 0.1 m³/h -> L/min


def _occupancy(raw):
    return 1.0 if int(raw) & 0x01 else 0.0        # bitmap, bit0 = occupied


def _float(raw):
    return float(raw)           # concentration MeasuredValue is float32


def _percent(raw):
    return float(raw)           # uint8 percent


def _milli(raw):
    return raw / 1000.0         # int64 mW / mV / mA -> W / V / A


def _energy(raw):
    # EnergyMeasurementStruct, tag-keyed: {"0": energy mWh, "1": start, ...}
    if not isinstance(raw, dict):
        return None
    mwh = raw.get('0', raw.get(0))
    return None if mwh is None else mwh / 1_000_000.0   # mWh -> kWh


# key: stable id used in channel custom_options ('matter_kind').
SENSOR_SPECS = [
    {'kind': 'temperature', 'cluster_id': TEMPERATURE_MEASUREMENT, 'attribute_id': 0,
     'measurement': 'temperature', 'unit': 'C', 'label': 'Temperature',
     'convert': _temperature},
    {'kind': 'humidity', 'cluster_id': RELATIVE_HUMIDITY_MEASUREMENT, 'attribute_id': 0,
     'measurement': 'humidity', 'unit': 'percent', 'label': 'Humidity',
     'convert': _humidity},
    {'kind': 'illuminance', 'cluster_id': ILLUMINANCE_MEASUREMENT, 'attribute_id': 0,
     'measurement': 'light', 'unit': 'lux', 'label': 'Illuminance',
     'convert': _illuminance},
    {'kind': 'boolean_state', 'cluster_id': BOOLEAN_STATE, 'attribute_id': 0,
     'measurement': 'boolean', 'unit': 'bool', 'label': 'State',
     'convert': _boolean},
    {'kind': 'battery', 'cluster_id': POWER_SOURCE, 'attribute_id': 12,
     'measurement': 'battery', 'unit': 'percent', 'label': 'Battery',
     'convert': _battery},
    {'kind': 'pressure', 'cluster_id': PRESSURE_MEASUREMENT, 'attribute_id': 0,
     'measurement': 'pressure', 'unit': 'kPa', 'label': 'Pressure',
     'convert': _pressure},
    {'kind': 'flow', 'cluster_id': FLOW_MEASUREMENT, 'attribute_id': 0,
     'measurement': 'rate_volume', 'unit': 'l_min', 'label': 'Flow',
     'convert': _flow},
    {'kind': 'occupancy', 'cluster_id': OCCUPANCY_SENSING, 'attribute_id': 0,
     'measurement': 'boolean', 'unit': 'bool', 'label': 'Occupancy',
     'convert': _occupancy},
    # Concentrations carry their own unit (attribute 8). Only the unit AoT
    # stores is mapped; a device in another unit is skipped, never mis-scaled.
    {'kind': 'co2', 'cluster_id': CO2_CONCENTRATION, 'attribute_id': 0,
     'measurement': 'co2', 'unit': 'ppm', 'label': 'CO2',
     'convert': _float, 'require_unit': CONC_UNIT_PPM},
    {'kind': 'pm25', 'cluster_id': PM25_CONCENTRATION, 'attribute_id': 0,
     'measurement': 'particulate_matter_2_5', 'unit': 'ug_m3', 'label': 'PM2.5',
     'convert': _float, 'require_unit': CONC_UNIT_UGM3},
    {'kind': 'soil_moisture', 'cluster_id': SOIL_MEASUREMENT, 'attribute_id': 1,
     'measurement': 'volumetric_water_content', 'unit': 'percent',
     'label': 'Soil Moisture', 'convert': _percent},
    {'kind': 'power', 'cluster_id': ELECTRICAL_POWER_MEASUREMENT, 'attribute_id': 8,
     'measurement': 'power', 'unit': 'W', 'label': 'Power', 'convert': _milli},
    {'kind': 'voltage', 'cluster_id': ELECTRICAL_POWER_MEASUREMENT, 'attribute_id': 4,
     'measurement': 'electrical_potential', 'unit': 'V', 'label': 'Voltage',
     'convert': _milli},
    {'kind': 'current', 'cluster_id': ELECTRICAL_POWER_MEASUREMENT, 'attribute_id': 5,
     'measurement': 'electrical_current', 'unit': 'A', 'label': 'Current',
     'convert': _milli},
    {'kind': 'energy', 'cluster_id': ELECTRICAL_ENERGY_MEASUREMENT, 'attribute_id': 1,
     'measurement': 'energy', 'unit': 'kWh', 'label': 'Energy',
     'convert': _energy, 'struct': True},
    # A momentary button has no value to sample: the channel is written from
    # Switch events only (see the Input). CurrentPosition is just its key.
    {'kind': 'button', 'cluster_id': SWITCH, 'attribute_id': 1,
     'measurement': 'unitless', 'unit': 'none', 'label': 'Button',
     'convert': _float, 'event_only': True, 'require_feature': SWITCH_FEATURE_MOMENTARY},
]

# driver: the AoT Output module that drives this kind.
# per_endpoint: one Output per endpoint (each on channel 0) instead of one
#   Output with a channel per endpoint — the environment coordinator reads a
#   position actuator's last position from channel 0 only.
# supersedes: on the same endpoint, this kind replaces those (a dimmable
#   light's OnOff is driven through its dimmer, not as a second switch).
ACTUATOR_SPECS = [
    {'kind': 'on_off', 'cluster_id': ON_OFF, 'state_attribute_id': 0,
     'output_type': 'on_off', 'label': 'Switch', 'driver': 'MATTER_ON_OFF'},
    # Only for endpoints that say they are dimmable. LevelControl is optional
    # on plain On/Off lights and plug-in units too; a relay plug that happens
    # to expose it must stay a switch, or a heater/pump would be driven as a
    # 30 % "level" (always on) instead of being cycled.
    {'kind': 'level', 'cluster_id': LEVEL_CONTROL, 'state_attribute_id': 0,
     'output_type': 'pwm', 'label': 'Dimmer', 'driver': 'MATTER_LEVEL',
     'supersedes': ('on_off',), 'device_types': DIMMABLE_DEVICE_TYPES},
    {'kind': 'covering', 'cluster_id': WINDOW_COVERING,
     'state_attribute_id': WC_CURRENT_LIFT_100THS,
     'output_type': 'value', 'label': 'Curtain', 'driver': 'MATTER_COVERING',
     'per_endpoint': True, 'require_feature': WC_FEATURE_LIFT},
]

_SENSOR_BY_KIND = {s['kind']: s for s in SENSOR_SPECS}
_ACTUATOR_BY_KIND = {a['kind']: a for a in ACTUATOR_SPECS}


def attribute_path(endpoint, cluster_id, attribute_id):
    return f"{int(endpoint)}/{int(cluster_id)}/{int(attribute_id)}"


def _parse_path(path):
    try:
        endpoint, cluster_id, attribute_id = (int(p) for p in path.split('/'))
    except (ValueError, AttributeError):
        return None
    return endpoint, cluster_id, attribute_id


def endpoint_clusters(attributes):
    """{endpoint: set(cluster ids)} from Descriptor.ServerList, falling back
    to the clusters that actually have attributes on that endpoint."""
    seen = {}
    for path in attributes:
        parsed = _parse_path(path)
        if parsed is None:
            continue
        endpoint, cluster_id, _attr = parsed
        seen.setdefault(endpoint, set()).add(cluster_id)
    result = {}
    for endpoint, clusters in seen.items():
        server_list = attributes.get(
            attribute_path(endpoint, DESCRIPTOR, DESCRIPTOR_SERVER_LIST))
        if isinstance(server_list, list) and server_list:
            result[endpoint] = {int(c) for c in server_list}
        else:
            result[endpoint] = clusters
    return result


def convert(kind, raw):
    """Scale a raw attribute value for a sensor kind. None for null/garbage —
    callers skip the write rather than storing a fake value (design §4-2)."""
    spec = _SENSOR_BY_KIND.get(kind)
    if spec is None or raw is None or isinstance(raw, (list, str)):
        return None
    if isinstance(raw, dict) and not spec.get('struct'):
        return None
    try:
        value = spec['convert'](raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def sensor_spec(kind):
    return _SENSOR_BY_KIND.get(kind)


def actuator_spec(kind):
    return _ACTUATOR_BY_KIND.get(kind)


def _feature_ok(attributes, endpoint, spec):
    """A cluster feature the mapping relies on (e.g. a momentary button, a
    lift-capable covering). A device that does not report its FeatureMap is
    given the benefit of the doubt."""
    if 'require_feature' not in spec:
        return True
    fmap = attributes.get(attribute_path(endpoint, spec['cluster_id'], FEATURE_MAP_ATTR))
    return not isinstance(fmap, int) or bool(fmap & spec['require_feature'])


def _unit_ok(attributes, endpoint, spec):
    """For concentration clusters: the device's unit must be the one we store."""
    if 'require_unit' not in spec:
        return True
    unit = attributes.get(attribute_path(endpoint, spec['cluster_id'],
                                         CONC_MEASUREMENT_UNIT_ATTR))
    return unit == spec['require_unit']


def _endpoint_label(attributes, endpoint):
    """Bridged endpoints carry their own name; plain ones don't."""
    for attr in (BI_NODE_LABEL, BI_PRODUCT_NAME):
        value = attributes.get(attribute_path(endpoint, BRIDGED_DEVICE_BASIC_INFORMATION, attr))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _name(label, endpoint, endpoint_label, count):
    if endpoint_label:
        return f"{endpoint_label} {label}"
    if count > 1:
        return f"{label} {endpoint}"
    return label


def discover_channels(node):
    """Channels a node offers, in a stable order (endpoint, then spec order).

    Returns (inputs, outputs); each item is a dict that goes straight into the
    channel's custom_options plus a display name:
      input:  {matter_kind, endpoint, cluster_id, attribute_id, measurement, unit, name}
      output: {matter_kind, endpoint, cluster_id, output_type, name}
    A sensor whose attribute is missing from the node is skipped (the cluster
    is listed but the server never reported the value, e.g. a feature the
    device does not implement).
    """
    attributes = (node or {}).get('attributes') or {}
    clusters_by_endpoint = endpoint_clusters(attributes)

    sensor_counts = {}
    actuator_counts = {}
    for endpoint, clusters in clusters_by_endpoint.items():
        for spec in SENSOR_SPECS:
            path = attribute_path(endpoint, spec['cluster_id'], spec['attribute_id'])
            if (spec['cluster_id'] in clusters and path in attributes
                    and _unit_ok(attributes, endpoint, spec)
                    and _feature_ok(attributes, endpoint, spec)):
                sensor_counts[spec['kind']] = sensor_counts.get(spec['kind'], 0) + 1
        if endpoint != 0:
            for kind in _actuator_kinds(attributes, endpoint, clusters):
                actuator_counts[kind] = actuator_counts.get(kind, 0) + 1

    inputs, outputs = [], []
    for endpoint in sorted(clusters_by_endpoint):
        clusters = clusters_by_endpoint[endpoint]
        ep_label = _endpoint_label(attributes, endpoint)
        for spec in SENSOR_SPECS:
            if spec['cluster_id'] not in clusters:
                continue
            path = attribute_path(endpoint, spec['cluster_id'], spec['attribute_id'])
            if (path not in attributes or not _unit_ok(attributes, endpoint, spec)
                    or not _feature_ok(attributes, endpoint, spec)):
                continue
            inputs.append({
                'matter_kind': spec['kind'],
                'endpoint': endpoint,
                'cluster_id': spec['cluster_id'],
                'attribute_id': spec['attribute_id'],
                'measurement': spec['measurement'],
                'unit': spec['unit'],
                'name': _name(spec['label'], endpoint, ep_label,
                              sensor_counts.get(spec['kind'], 1)),
            })
        if endpoint == 0:
            continue    # root endpoint: utility clusters only
        for kind in _actuator_kinds(attributes, endpoint, clusters):
            spec = _ACTUATOR_BY_KIND[kind]
            outputs.append({
                'matter_kind': kind,
                'endpoint': endpoint,
                'cluster_id': spec['cluster_id'],
                'output_type': spec['output_type'],
                'driver': spec['driver'],
                'name': _name(spec['label'], endpoint, ep_label,
                              actuator_counts.get(kind, 1)),
            })
    return inputs, outputs


def endpoint_device_types(attributes, endpoint):
    """Device type ids from Descriptor.DeviceTypeList ([{"0": type, "1": rev}])."""
    entries = attributes.get(attribute_path(endpoint, DESCRIPTOR, DESCRIPTOR_DEVICE_TYPE_LIST))
    types = set()
    for entry in entries if isinstance(entries, list) else ():
        if isinstance(entry, dict):
            value = entry.get('0', entry.get(0))
            if isinstance(value, int):
                types.add(value)
    return types


def _device_type_ok(attributes, endpoint, spec):
    if 'device_types' not in spec:
        return True
    return bool(endpoint_device_types(attributes, endpoint) & spec['device_types'])


def _actuator_kinds(attributes, endpoint, clusters):
    """Actuator kinds on one endpoint, after `supersedes` (spec order)."""
    present = [spec for spec in ACTUATOR_SPECS
               if spec['cluster_id'] in clusters and _feature_ok(attributes, endpoint, spec)
               and _device_type_ok(attributes, endpoint, spec)]
    replaced = {k for spec in present for k in spec.get('supersedes', ())}
    return [spec['kind'] for spec in present if spec['kind'] not in replaced]


def covering_position_aware(attributes, endpoint):
    """True if the covering can go to a percentage (PositionAwareLift)."""
    fmap = attributes.get(attribute_path(endpoint, WINDOW_COVERING, FEATURE_MAP_ATTR))
    return isinstance(fmap, int) and bool(fmap & WC_FEATURE_POSITION_AWARE_LIFT)


def button_value(event_id, data, multi_press, release=True):
    """The number a button channel records for one Switch event, or None for
    events that are only part of a gesture.

    With MultiPress the device itself counts and reports MultiPressComplete;
    without it every ShortRelease is one press — or, on a switch without the
    MomentarySwitchRelease feature (it only ever sends InitialPress), every
    InitialPress. A long press records BUTTON_LONG_PRESS_VALUE once, at
    LongPress (when it is recognised).
    """
    if event_id == SWITCH_EV_LONG_PRESS:
        return BUTTON_LONG_PRESS_VALUE
    if not release and not multi_press:
        return 1.0 if event_id == SWITCH_EV_INITIAL_PRESS else None
    if multi_press:
        if event_id == SWITCH_EV_MULTI_PRESS_COMPLETE:
            count = (data or {}).get('totalNumberOfPressesCounted')
            return float(count) if isinstance(count, int) and count > 0 else None
        return None
    if event_id == SWITCH_EV_SHORT_RELEASE:
        return 1.0
    return None


def device_identity(node):
    """BasicInformation fields plus a stable identity key.

    identity_key prefers UniqueID (spec: persists across factory reset is NOT
    guaranteed, but survives re-commissioning, which is what we need), then
    VendorID:ProductID:SerialNumber. None when the node offers neither — such
    a device cannot be matched on re-share and gets a new AoT Device.
    """
    attributes = (node or {}).get('attributes') or {}

    def bi(attr):
        return attributes.get(attribute_path(0, BASIC_INFORMATION, attr))

    info = {
        'vendor_name': bi(BI_VENDOR_NAME),
        'vendor_id': bi(BI_VENDOR_ID),
        'product_name': bi(BI_PRODUCT_NAME),
        'product_id': bi(BI_PRODUCT_ID),
        'node_label': bi(BI_NODE_LABEL),
        'serial_number': bi(BI_SERIAL_NUMBER),
        'unique_id': bi(BI_UNIQUE_ID),
    }
    key = None
    if isinstance(info['unique_id'], str) and info['unique_id'].strip():
        key = f"uid:{info['unique_id'].strip()}"
    elif (info['vendor_id'] is not None and info['product_id'] is not None
          and isinstance(info['serial_number'], str) and info['serial_number'].strip()):
        key = f"vps:{info['vendor_id']}:{info['product_id']}:{info['serial_number'].strip()}"
    info['identity_key'] = key
    return info


def display_name(node):
    """Human name for a new AoT Device: the node's own label, else product."""
    info = device_identity(node)
    for value in (info['node_label'], info['product_name'], info['vendor_name']):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"Matter node {(node or {}).get('node_id', '?')}"
