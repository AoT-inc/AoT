# coding=utf-8
"""Hand-off between the Matter settings page and the Matter device module.

Creating an AoT Device goes through the generic function_add() path, which
only knows the module name. The Matter device needs more than that at
creation time: which node it is and which channels the node offers, so the
child Input/Output are created with their channels filled in (design §4-1,
"discovery is canonical"). utils_matter puts the commissioned node here for
the duration of one function_add() call; the device module's
execute_at_creation() reads it. Without it, execute_at_creation() refuses —
a Matter device only makes sense for a node that is already on the AoT fabric.

Thread-local, so two people commissioning at once on different gunicorn
threads cannot see each other's node.

@phase experimental
@stability experimental
"""
import contextlib
import copy
import threading

from aot.devices import matter_clusters

INPUT_DRIVER = 'MATTER_NODE'
OUTPUT_DRIVER = 'MATTER_ON_OFF'          # kept for P1 callers
OUTPUT_DRIVERS = tuple(spec['driver'] for spec in matter_clusters.ACTUATOR_SPECS)
DEVICE_MODULE = 'device_matter_node'

# Measurement each output channel records (one DeviceMeasurements row per
# channel, or the UI has nowhere to show it). On/off records runtime; dimmer
# and covering record their level/position like the pwm and paired outputs.
_OUTPUT_CHANNEL_MEASUREMENT = {
    'on_off': ('duration_time', 's'),
    'pwm': ('duty_cycle', 'percent'),
    'value': ('duty_cycle', 'percent'),
}

_local = threading.local()


@contextlib.contextmanager
def pending_node(node):
    """Make `node` visible to execute_at_creation() on this thread.

    Yields a dict that execute_at_creation() fills with the ids of the
    children it created ({'inputs': [...], 'outputs': [...]}), so the caller
    can activate them without re-querying by parent id.
    """
    _local.node = node
    _local.created = {'inputs': [], 'outputs': []}
    try:
        yield _local.created
    finally:
        _local.node = None
        _local.created = None


def current_node():
    return getattr(_local, 'node', None)


@contextlib.contextmanager
def adding_children():
    """Let a refresh add Inputs/Outputs to an existing Matter device.

    Settings > Matter's refresh creates children for endpoints that appeared
    since the device was made, outside pending_node(). This marks that path
    so refuse_outside_settings() lets it through.
    """
    _local.children = True
    try:
        yield
    finally:
        _local.children = False


def refuse_outside_settings(error, new_row, dict_info=None):
    """execute_at_creation() of the MATTER_* Input/Outputs.

    They only work bound to a node on the AoT fabric, and only Settings >
    Matter binds them. Created anywhere else (the Outputs/Inputs page, an AI
    tool) they are an orphan with node_id 0 that does nothing.
    """
    from flask_babel import gettext

    if current_node() is None and not getattr(_local, 'children', False):
        error.append(gettext(
            'Matter devices are added from Settings > Matter with the pairing code '
            'shared from the other app.'))
    return error, new_row


def record_created(created):
    """Called by execute_at_creation() with create_blueprint_members()'s ids."""
    target = getattr(_local, 'created', None)
    if target is None or not created:
        return
    for key in ('inputs', 'outputs'):
        target[key].extend(created.get(key) or [])


def device_options(node):
    """custom_options values the Device row gets for this node."""
    info = matter_clusters.device_identity(node)
    return {
        'node_id': int(node['node_id']),
        'identity_key': info['identity_key'] or '',
        'vendor_name': info['vendor_name'] or '',
        'product_name': info['product_name'] or '',
        'serial_number': info['serial_number'] or '',
    }


def build_blueprint(static_blueprint, node):
    """The module's static blueprint with channels filled in from the node.

    A node with no sensors gets no Input, one with no switches no Output —
    an empty child would only confuse (and an Input with no channels cannot
    be activated).
    """
    inputs, outputs = matter_clusters.discover_channels(node)
    blueprint = {'inputs': [], 'outputs': []}
    for spec in static_blueprint.get('inputs', []):
        if spec.get('device') == INPUT_DRIVER and inputs:
            spec = copy.deepcopy(spec)
            spec['channels'] = [
                {
                    'name': ch['name'],
                    'measurement': ch['measurement'],
                    'unit': ch['unit'],
                    'endpoint': ch['endpoint'],
                    'cluster_id': ch['cluster_id'],
                    'attribute_id': ch['attribute_id'],
                    'matter_kind': ch['matter_kind'],
                }
                for ch in inputs
            ]
            blueprint['inputs'].append(spec)
    for spec in static_blueprint.get('outputs', []):
        driver = spec.get('device')
        mine = [ch for ch in outputs if ch['driver'] == driver]
        if not mine:
            continue
        actuator = matter_clusters.actuator_spec(mine[0]['matter_kind'])
        groups = [[ch] for ch in mine] if actuator.get('per_endpoint') else [mine]
        for group in groups:
            out_spec = copy.deepcopy(spec)
            if len(groups) > 1:
                # One Output per endpoint: name each after its endpoint.
                out_spec['name'] = spec.get('name', '{device_name}') + ' ' + group[0]['name']
            measurement, unit = _OUTPUT_CHANNEL_MEASUREMENT[group[0]['output_type']]
            out_spec['channels'] = [
                {
                    'name': ch['name'],
                    'measurement': measurement,
                    'unit': unit,
                    'endpoint': ch['endpoint'],
                }
                for ch in group
            ]
            blueprint['outputs'].append(out_spec)
    return blueprint
