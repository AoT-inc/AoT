# coding=utf-8
"""Settings > Matter: commission shared devices, list nodes, remove nodes.

The web process talks to the Matter server sidecar through the same shared
client the daemon uses (aot/devices/matter_client.py, one connection per
process). Design: docs/design/matter-controller.md §5-4.

Like utils_chirpstack, helpers return their outcome instead of raising to
the route, and they never block longer than their own timeout. Commissioning
is synchronous: it takes from a few seconds to about a minute, and gunicorn
runs gthread workers with a 300s timeout, so one settings request holding a
thread for that long is acceptable — and it keeps the outcome on the request
that asked for it, which a background job would not with several workers.

The pairing code is a credential for up to 15 minutes: it is never logged
and never stored.

@phase experimental
@stability experimental
"""
import contextlib
import json
import logging
import os
import re

from flask_babel import gettext

from aot.databases.models import CustomController, Input, Output
from aot.devices import matter_clusters, matter_onboarding

logger = logging.getLogger(__name__)

# Waiting for this process's client to connect (first use after start).
CONNECT_WAIT_S = 5.0
# commission_with_code: discovery + PASE + attestation + CASE + interview.
# Observed: a wrong passcode fails after ~227s; stay under gunicorn's 300s.
COMMISSION_TIMEOUT_S = 240.0
REMOVE_TIMEOUT_S = 30.0
# What other ecosystems' apps show for AoT's connection on a shared device.
FABRIC_LABEL = 'AoT'

# 11-digit manual code (optionally 21 with vendor/product), or a QR payload.
_MANUAL_RE = re.compile(r'^\d{11}$|^\d{21}$')
_QR_RE = re.compile(r'^MT:[0-9A-Z.\-]+$')

# matterjs-server error codes (ws-controller WebSocketMessageTypes.ts).
ERR_COMMISSION_FAILED = 1
ERR_NODE_NOT_EXISTS = 5
ERR_INVALID_ARGUMENTS = 8


@contextlib.contextmanager
def _open_client():
    """A connection for this request only.

    The web process does not keep a Matter connection: every gunicorn worker
    would otherwise hold a full mirror of every node, decode every attribute
    event and reconnect forever (with a warning a minute on installs without
    the sidecar). The daemon is the long-lived listener. A settings request
    pays one connect + snapshot, which on a farm-sized fabric is milliseconds.

    Keepalive is relaxed here: the server stops answering pings while a
    failed commissioning attempt runs (~227s observed).
    """
    from aot.devices.matter_client import DEFAULT_SOCKET_PATH, MatterServerClient
    client = MatterServerClient(
        socket_path=os.environ.get('AOT_MATTER_SOCKET') or DEFAULT_SOCKET_PATH,
        url=os.environ.get('AOT_MATTER_URL') or None,
        ping_interval=30.0, ping_timeout=COMMISSION_TIMEOUT_S + 60.0, quiet=True)
    client.ensure_started()
    try:
        yield client
    finally:
        client.stop(timeout=2.0)


def normalize_code(raw):
    """Strip separators people copy along with the code. None if not a code."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.upper().startswith('MT:'):
        code = 'MT:' + text[3:].strip().upper()
        return code if _QR_RE.match(code) else None
    digits = re.sub(r'[\s\-]', '', text)
    return digits if _MANUAL_RE.match(digits) else None


def server_status(wait_s=2.0):
    """Connection status for the page."""
    with _open_client() as client:
        client.wait_ready(wait_s)
        return client.status()


def _matter_devices():
    """{node_id: CustomController} for every Matter device in AoT."""
    result = {}
    for row in CustomController.query.filter_by(
            device=matter_onboarding.DEVICE_MODULE).all():
        node_id = _node_id_of(row)
        if node_id:
            result[node_id] = row
    return result


def _options(row):
    try:
        opts = json.loads(row.custom_options) if row.custom_options else {}
    except Exception:
        return {}
    return opts if isinstance(opts, dict) else {}


def _node_id_of(row):
    try:
        return int(_options(row).get('node_id') or 0) or None
    except (TypeError, ValueError):
        return None


def list_nodes():
    """Nodes on the AoT fabric joined with their AoT devices.

    A node without an AoT device is an orphan (its device was deleted while
    the server was unreachable, or creating the device failed); the page
    offers to remove it from the fabric.
    """
    from aot.devices.matter_client import MatterNotConnected
    with _open_client() as client:
        if not client.wait_ready(CONNECT_WAIT_S):
            # Without the server we cannot tell orphans from missing nodes;
            # the route shows the connection error instead of a wrong list.
            raise MatterNotConnected(client.status().get('last_error') or 'not connected')
        server_nodes = client.nodes()
    devices = _matter_devices()
    rows = []
    for node_id, node in sorted(server_nodes.items()):
        info = matter_clusters.device_identity(node)
        inputs, outputs = matter_clusters.discover_channels(node)
        device = devices.get(node_id)
        rows.append({
            'node_id': node_id,
            'available': bool(node.get('available')),
            'name': matter_clusters.display_name(node),
            'vendor_name': info['vendor_name'] or '',
            'product_name': info['product_name'] or '',
            'sensor_count': len(inputs),
            'switch_count': len(outputs),
            'device_id': device.unique_id if device else None,
            'device_name': device.name if device else None,
            'missing': False,
            # Firmware version and OTA progress, from the cache (no network).
            'firmware': _firmware_state(node),
        })
    # AoT devices whose node is no longer on the server (removed in another
    # tool, or the server's storage was reset). They cannot work until the
    # device is shared again (which re-binds them, §4-3) or deleted.
    on_server = set(server_nodes)
    for node_id, device in sorted(devices.items()):
        if node_id in on_server:
            continue
        opts = _options(device)
        rows.append({
            'node_id': node_id,
            'available': False,
            'name': device.name,
            'vendor_name': opts.get('vendor_name') or '',
            'product_name': opts.get('product_name') or '',
            'sensor_count': 0,
            'switch_count': 0,
            'device_id': device.unique_id,
            'device_name': device.name,
            'missing': True,
            'firmware': {'version': '', 'state': None, 'progress': None},
        })
    return rows


def error_category(err):
    """(category, details) for a Matter error — no translation, so it can be
    stored by a background job and turned into text later in the user's
    request (error_message()). Categories follow the guidance in design §5-4
    plus the new-device (BLE) cases of §13."""
    from aot.devices.matter_client import (MatterCommandError, MatterCommandTimeout,
                                           MatterNotConnected)
    if isinstance(err, MatterNotConnected):
        return 'not_connected', ''
    if isinstance(err, MatterCommandTimeout):
        return 'timeout', ''
    if isinstance(err, MatterCommandError):
        details = str(err.details or '')
        low = details.lower()
        credentials_step = (err.command in ('set_wifi_credentials', 'set_thread_dataset')
                            or 'credential' in low or 'dataset' in low or 'password' in low)
        if err.error_code == ERR_INVALID_ARGUMENTS and credentials_step:
            # e.g. a password the server refuses, an unknown credentials id —
            # not a wrong pairing code.
            return 'network_rejected', details
        if (err.error_code == ERR_INVALID_ARGUMENTS or 'checksum' in low
                or 'invalid pairing code' in low):
            return 'invalid_code', details
        if ('ble interface not initialized' in low or 'nodejs-ble' in low
                or 'bluetooth' in low or 'noble' in low):
            return 'ble_unavailable', details
        # nodejs-ble: "Timeout while connecting to peripheral …" — the device
        # is out of range or not advertising, not a wrong code.
        if 'peripheral' in low or 'bleerror' in low:
            return 'not_found', details
        if 'wifi' in low and ('connect' in low or 'network' in low):
            return 'wifi_failed', details
        if 'thread' in low and ('connect' in low or 'network' in low or 'add' in low):
            return 'thread_failed', details
        if 'fabric' in low and ('full' in low or 'nospace' in low.replace(' ', '')
                                or 'no space' in low or 'resource' in low):
            return 'fabric_full', details
        if 'attestation' in low or 'certificate' in low or 'dcl' in low:
            return 'attestation', details
        if ('discover' in low or 'not found' in low or 'no device' in low
                or 'mdns' in low or 'resolve' in low):
            return 'not_found', details
        if 'pase' in low or 'passcode' in low or 'timeout' in low or 'timed out' in low:
            return 'code_rejected', details
        return 'other', details
    return 'other', str(err)


def error_message(category, details='', new_device=False):
    """User-facing text for an error_category() result (needs app context)."""
    if category == 'not_connected':
        return gettext(
            'The Matter server is not reachable. Check that the matter_server and '
            'matter_socket containers are running.')
    if category == 'timeout':
        if new_device:
            return gettext(
                'The device did not finish joining in time. Put it back into pairing mode '
                '(see its manual) and try again.')
        return gettext(
            'The device did not finish joining in time. Share it again from the other '
            'app and enter the new code.')
    if category == 'invalid_code':
        return gettext('The pairing code is not valid. Check the digits and try again.')
    if category == 'network_rejected':
        return gettext(
            'The Matter server did not accept the network details. Check the Wi-Fi '
            'name and password or the Thread dataset.')
    if category == 'ble_unavailable':
        return gettext(
            'Bluetooth is not available to the Matter server. Run '
            'aot/scripts/check_matter_host.sh --ble on the host and start the server with '
            'docker/docker-compose.matter-ble.yml.')
    if category == 'wifi_failed':
        return gettext(
            'The device could not join the Wi-Fi network. Check the network name and '
            'password, and that the network is 2.4 GHz if the device needs it.')
    if category == 'thread_failed':
        return gettext(
            'The device could not join the Thread network. Check the Thread dataset and '
            'that a Thread border router is running.')
    if category == 'fabric_full':
        return gettext(
            'The device has no free slot for another ecosystem. Remove one of its '
            'other connections in that app, then share again.')
    if category == 'attestation':
        return gettext(
            'The device could not prove it is certified. Check that this AoT server '
            'can reach the internet (CSA DCL) and try again.')
    if category == 'not_found':
        if new_device:
            return gettext(
                'The device was not found. Keep it close to this AoT server, make sure it '
                'is in pairing mode, and check Bluetooth on the host.')
        return gettext(
            'The device was not found on the network. Make sure it is on the same '
            'network as this AoT server and that its sharing window is still open, '
            'then run aot/scripts/check_matter_host.sh on the host.')
    if category == 'code_rejected':
        if new_device:
            return gettext(
                'The device did not accept the code. Check the code on the device or its '
                'box and try again.')
        return gettext(
            'The device did not accept the code. The sharing window may have closed — '
            'share it again from the other app and enter the new code.')
    return gettext('Adding the device failed: %(details)s', details=details or '?')


def _firmware_state(node):
    from aot.aot_flask.utils.utils_matter_admin import update_state
    return update_state(node)


def _friendly_error(err):
    """Map a server error to the guidance in design §5-4."""
    return error_message(*error_category(err))


def commission(raw_code):
    """Commission a shared device and create its AoT device.

    Returns a dict: {'ok': bool, 'error': str|None, 'node_id', 'device_id',
    'rebound': bool, 'sensor_count', 'switch_count', 'warnings': [str]}.
    """
    from aot.devices.matter_client import MatterError

    result = {'ok': False, 'error': None, 'node_id': None, 'device_id': None,
              'rebound': False, 'sensor_count': 0, 'switch_count': 0, 'warnings': []}
    code = normalize_code(raw_code)
    if code is None:
        result['error'] = gettext(
            'Enter the 11-digit pairing code (or the MT: code) shown by the other app.')
        return result

    with _open_client() as client:
        if not client.wait_ready(CONNECT_WAIT_S):
            result['error'] = _friendly_error(_not_connected())
            return result
        _set_fabric_label(client)
        try:
            node = client.send_command(
                'commission_with_code', {'code': code, 'network_only': True},
                timeout=COMMISSION_TIMEOUT_S)
        except MatterError as err:
            logger.warning("Matter commissioning failed: %s", type(err).__name__)
            result['error'] = _friendly_error(err)
            return result

    if not isinstance(node, dict) or node.get('node_id') is None:
        result['error'] = gettext('The Matter server returned no device.')
        return result

    result['node_id'] = int(node['node_id'])
    inputs, outputs = matter_clusters.discover_channels(node)
    result['sensor_count'], result['switch_count'] = len(inputs), len(outputs)
    if not inputs and not outputs:
        result['warnings'].append(gettext(
            'The device joined, but AoT does not support any of its sensors or switches yet.'))

    reg = register_node(node)
    result.update({'device_id': reg['device_id'], 'rebound': reg['rebound']})
    result['warnings'].extend(reg['warnings'])
    if reg['error']:
        result['error'] = reg['error']
        return result
    result['ok'] = True
    return result


def _set_fabric_label(client):
    """Name the AoT fabric "AoT" on devices joined from now on. Without it the
    other ecosystem's app lists AoT under the server's default label
    ("HomeAssistant"). Best effort: an older server may not know the command."""
    from aot.devices.matter_client import MatterError
    try:
        client.send_command('set_default_fabric_label', {'label': FABRIC_LABEL},
                            timeout=5.0)
    except MatterError as err:
        logger.info("Matter: could not set fabric label: %s", err)


def _not_connected():
    from aot.devices.matter_client import MatterNotConnected
    return MatterNotConnected('not connected')


def adopt_node(node_id):
    """Create the AoT device for a node that is on the fabric without one.

    Happens when creating the device failed after commissioning, when a
    new-device job finished with nobody left polling it (tab closed), or when
    the device was deleted while the server was unreachable. Same path as a
    fresh commission (re-binds by identity if it can).
    Returns {'ok', 'error', 'device_id', 'rebound', 'warnings'}.
    """
    out = {'ok': False, 'error': None, 'device_id': None, 'rebound': False, 'warnings': []}
    with _open_client() as client:
        if not client.wait_ready(CONNECT_WAIT_S):
            out['error'] = error_message('not_connected')
            return out
        node = client.get_node(node_id)
    if node is None:
        out['error'] = gettext('This device is not on the Matter server.')
        return out
    if _matter_devices().get(int(node_id)) is not None:
        out['error'] = gettext('This device already has an AoT device.')
        return out
    reg = register_node(node)
    out.update({'device_id': reg['device_id'], 'rebound': reg['rebound'],
                'warnings': reg['warnings'], 'error': reg['error']})
    out['ok'] = not reg['error']
    return out


def find_device_by_identity(identity_key):
    if not identity_key:
        return None
    for row in CustomController.query.filter_by(
            device=matter_onboarding.DEVICE_MODULE).all():
        if _options(row).get('identity_key') == identity_key:
            return row
    return None


def register_node(node):
    """Create the AoT device for a commissioned node, or re-bind an existing
    one that has the same device identity (design §4-3: a device removed and
    shared again gets a new node id; its AoT history should continue)."""
    from aot.utils.device_blueprint import sync_inherited_options

    out = {'device_id': None, 'rebound': False, 'error': None, 'warnings': []}
    node_id = int(node['node_id'])

    existing = _matter_devices().get(node_id)
    if existing is not None:
        out['device_id'] = existing.unique_id
        return out

    identity = matter_clusters.device_identity(node)['identity_key']
    match = find_device_by_identity(identity)
    if match is not None:
        opts = _options(match)
        opts.update(matter_onboarding.device_options(node))
        match.custom_options = json.dumps(opts)
        match.save()
        from aot.functions.custom_functions.device_matter_node import FUNCTION_INFORMATION
        sync_inherited_options(match, FUNCTION_INFORMATION['device_blueprint'])
        _restart_children(match.unique_id)
        out['device_id'] = match.unique_id
        out['rebound'] = True
        return out

    out.update(_create_device(node))
    return out


def _create_device(node):
    from aot.aot_flask.utils.utils_function import function_add
    from aot.aot_flask.utils.utils_controller import controller_activate

    out = {'device_id': None, 'error': None, 'warnings': []}

    messages, dep_msg, device_id = {'error': []}, '', None
    with matter_onboarding.pending_node(node) as created:
        try:
            messages, _dep_name, _unmet, dep_msg, device_id = function_add(
                _IdForm(function_type=matter_onboarding.DEVICE_MODULE),
                tab_id=_device_tab_id())
        except Exception as err:
            logger.exception("Matter: creating the AoT device failed")
            messages = {'error': [str(err)]}

    if messages.get('error') or not device_id:
        out['error'] = '; '.join(str(m) for m in messages.get('error') or []) or dep_msg \
            or gettext('Creating the AoT device failed.')
        # The blueprint saves each child as it goes; when a later step fails
        # the parent is never saved. Remove what was made so a retry does not
        # stack another set of parentless children (and daemon outputs).
        _discard_created(created)
        # The node stays on the fabric without an AoT device: it is listed as
        # an orphan on the page, where it can be retried or removed.
        return out
    out['device_id'] = device_id

    # Output rows from the blueprint keep size_y for one channel; the output
    # page sizes its card from it (device_blueprint does not update it).
    _finish_outputs(created['outputs'], out)

    # "Done" means values arrive, not "saved" (design §5-4): activate the
    # device, which activates its Inputs. A switch-only device is activated
    # too, so the device list does not show it as off.
    act = controller_activate(device_id)
    for msg in act.get('error') or []:
        out['warnings'].append(str(msg))
    return out


def _discard_created(created):
    from aot.aot_flask.utils.utils_input import input_del
    from aot.aot_flask.utils.utils_output import output_del

    for input_id in created.get('inputs') or []:
        try:
            input_del(input_id)
        except Exception:
            logger.exception("Matter: could not discard input %s", input_id)
    for output_id in created.get('outputs') or []:
        try:
            output_del(_IdForm(output_id=output_id))
        except Exception:
            logger.exception("Matter: could not discard output %s", output_id)


def _device_tab_id():
    from aot.services.tab_service import TabService
    tab = TabService.get_default_tab('device')
    return tab.unique_id if tab else None


class _IdForm:
    """The utils_* helpers read ids from form fields (.input_id.data etc.)."""

    class _Field:
        def __init__(self, data):
            self.data = data

    def __init__(self, **ids):
        for key, value in ids.items():
            setattr(self, key, self._Field(value))


def _restart_children(device_id):
    """After a re-bind the children must pick up the new node id."""
    from aot.aot_flask.utils.utils_input import input_activate, input_deactivate
    from aot.aot_flask.utils.utils_output import manipulate_output

    for row in Input.query.filter_by(parent_device_id=device_id).all():
        if row.is_activated:
            input_deactivate(_IdForm(input_id=row.unique_id))
            input_activate(_IdForm(input_id=row.unique_id))
    for row in Output.query.filter_by(parent_device_id=device_id).all():
        manipulate_output('Modify', row.unique_id)


def refresh_device(device_id):
    """Read the node again and add what AoT can now drive but the device lacks.

    Devices registered before a cluster was supported (a P1 plug that also
    measures power, a dimmable light registered as a plain switch) otherwise
    never gain those channels. Existing channels are never removed or
    rewritten — they may carry user names, conversions and references.

    Returns {'ok', 'error', 'added_inputs', 'added_outputs', 'warnings'}.
    """
    from aot.devices.matter_client import MatterNotConnected

    out = {'ok': False, 'error': None, 'added_inputs': 0, 'added_outputs': 0,
           'warnings': []}
    from aot.aot_flask.access import scope
    device = CustomController.query.filter_by(
        unique_id=device_id, device=matter_onboarding.DEVICE_MODULE).first()
    if device is None:
        out['error'] = gettext('Unknown Matter device.')
        return out
    if not scope.can_operate_device(device.unique_id):
        out['error'] = scope.deny_message()
        return out
    node_id = _node_id_of(device)

    with _open_client() as client:
        if not client.wait_ready(CONNECT_WAIT_S):
            out['error'] = _friendly_error(MatterNotConnected('not connected'))
            return out
        node = client.get_node(node_id) if node_id else None
    if node is None:
        out['error'] = gettext(
            'This device is not on the Matter server. Share it again to reconnect it.')
        return out

    from aot.functions.custom_functions.device_matter_node import FUNCTION_INFORMATION
    wanted = matter_onboarding.build_blueprint(FUNCTION_INFORMATION['device_blueprint'], node)
    inputs, outputs = _matter_children(device.unique_id)

    # -- inputs: one Input per node; append missing channels to it ---------
    have = set()
    for row in inputs:
        for ch in _channel_options(row, input_side=True):
            have.add(_input_key(ch))
    missing_in = [ch for spec in wanted['inputs'] for ch in spec['channels']
                  if _input_key(ch) not in have]
    if missing_in:
        if inputs:
            _append_input_channels(inputs[0], missing_in)
            _restart_input(inputs[0])
        else:
            spec = dict(wanted['inputs'][0], channels=missing_in)
            created = _create_children(device, {'inputs': [spec], 'outputs': []}, out)
            for input_id in created['inputs']:
                _activate_input(input_id, out)
        out['added_inputs'] = len(missing_in)

    # -- outputs: per driver; per-endpoint drivers get new Outputs ----------
    have_out = set()
    by_driver = {}
    for row in outputs:
        by_driver.setdefault(row.output_type, []).append(row)
        for ch in _channel_options(row, input_side=False):
            have_out.add((row.output_type, ch.get('endpoint')))
    switch_endpoints = {ep for drv, ep in have_out if drv == matter_onboarding.OUTPUT_DRIVER}
    for spec in wanted['outputs']:
        driver = spec['device']
        missing = [ch for ch in spec['channels'] if (driver, ch['endpoint']) not in have_out]
        if driver == 'MATTER_LEVEL':
            # A dimmable light registered earlier as a plain switch: adding a
            # dimmer next to that switch would leave two outputs commanding
            # one endpoint (and automations fighting). Keep the switch; the
            # user converts by deleting it and reading again.
            kept = [ch for ch in missing if ch['endpoint'] in switch_endpoints]
            for ch in kept:
                out['warnings'].append(gettext(
                    'Endpoint %(endpoint)s is a dimmer but is still set up as a switch. Delete '
                    'that switch output and read the device again to control it as a dimmer.',
                    endpoint=ch['endpoint']))
            missing = [ch for ch in missing if ch['endpoint'] not in switch_endpoints]
        if not missing:
            continue
        per_endpoint = matter_clusters.actuator_spec(
            _kind_for_driver(driver)).get('per_endpoint')
        if by_driver.get(driver) and not per_endpoint:
            _append_output_channels(by_driver[driver][0], missing)
        else:
            created = _create_children(device, {'inputs': [], 'outputs': [
                dict(spec, channels=missing)]}, out)
            _finish_outputs(created['outputs'], out)
        out['added_outputs'] += len(missing)
        for ch in missing:
            have_out.add((driver, ch['endpoint']))

    out['ok'] = out['error'] is None
    return out


def _input_key(ch):
    try:
        return (int(ch.get('endpoint')), int(ch.get('cluster_id')), int(ch.get('attribute_id')))
    except (TypeError, ValueError):
        return None


def _kind_for_driver(driver):
    for spec in matter_clusters.ACTUATOR_SPECS:
        if spec['driver'] == driver:
            return spec['kind']
    return None


def _channel_options(row, input_side):
    from aot.databases.models import InputChannel, OutputChannel
    model, key = (InputChannel, 'input_id') if input_side else (OutputChannel, 'output_id')
    result = []
    for ch in model.query.filter_by(**{key: row.unique_id}).all():
        try:
            opts = json.loads(ch.custom_options) if ch.custom_options else {}
        except Exception:
            opts = {}
        result.append(opts if isinstance(opts, dict) else {})
    return result


def _append_input_channels(row, channel_specs):
    """Add channels after the existing ones (channel numbers are never reused:
    measurement history is keyed by them)."""
    from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
    from aot.databases.models import DeviceMeasurements, InputChannel
    from aot.utils.inputs import parse_input_information

    dict_inputs = parse_input_information()
    used = [c.channel for c in InputChannel.query.filter_by(input_id=row.unique_id).all()]
    used += [m.channel for m in DeviceMeasurements.query.filter_by(device_id=row.unique_id).all()]
    nxt = max(used) + 1 if used else 0
    for spec in channel_specs:
        error = []
        error, opts_json = custom_channel_options_return_json(
            error, dict_inputs, None, row.unique_id, nxt,
            device=matter_onboarding.INPUT_DRIVER, use_defaults=True)
        try:
            opts = json.loads(opts_json) if opts_json else {}
        except Exception:
            opts = {}
        for key, value in spec.items():
            if key not in ('measurement', 'unit'):
                opts[key] = value
        ic = InputChannel()
        ic.input_id = row.unique_id
        ic.channel = nxt
        ic.custom_options = json.dumps(opts)
        ic.save()
        dm = DeviceMeasurements()
        dm.device_id = row.unique_id
        dm.channel = nxt
        dm.name = str(spec.get('name') or '')
        dm.measurement = spec['measurement']
        dm.unit = spec['unit']
        dm.is_enabled = True
        dm.save()
        nxt += 1


def _append_output_channels(row, channel_specs):
    from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
    from aot.aot_flask.utils.utils_output import manipulate_output
    from aot.databases.models import DeviceMeasurements, OutputChannel
    from aot.utils.outputs import parse_output_information

    dict_outputs = parse_output_information()
    # Never reuse a channel number: a deleted channel's measurement rows and
    # history are keyed by it.
    used = [c.channel for c in OutputChannel.query.filter_by(output_id=row.unique_id).all()]
    used += [m.channel for m in DeviceMeasurements.query.filter_by(device_id=row.unique_id).all()]
    nxt = max(used) + 1 if used else 0
    for spec in channel_specs:
        error = []
        error, opts_json = custom_channel_options_return_json(
            error, dict_outputs, None, row.unique_id, nxt,
            device=row.output_type, use_defaults=True)
        try:
            opts = json.loads(opts_json) if opts_json else {}
        except Exception:
            opts = {}
        for key, value in spec.items():
            if key not in ('measurement', 'unit'):
                opts[key] = value
        oc = OutputChannel()
        oc.output_id = row.unique_id
        oc.channel = nxt
        oc.custom_options = json.dumps(opts)
        oc.save()
        dm = DeviceMeasurements.query.filter_by(device_id=row.unique_id, channel=nxt).first()
        if dm is None:
            dm = DeviceMeasurements()
            dm.device_id = row.unique_id
            dm.channel = nxt
        dm.name = str(spec.get('name') or '')
        dm.measurement = spec['measurement']
        dm.unit = spec['unit']
        dm.is_enabled = True
        dm.save()
        nxt += 1
    row.size_y = OutputChannel.query.filter_by(output_id=row.unique_id).count() + 1
    row.save()
    manipulate_output('Modify', row.unique_id)


def _create_children(device, blueprint, out):
    from aot.utils.device_blueprint import create_blueprint_members
    with matter_onboarding.adding_children():
        error, created = create_blueprint_members([], device, blueprint)
    for msg in error:
        out['warnings'].append(str(msg))
    return created


def _finish_outputs(output_ids, out):
    """Size each Output's card (device_blueprint leaves size_y for one
    channel) and make the daemon re-read it: output_add() registered it
    BEFORE the blueprint wrote node_id and the channel rows, so the daemon's
    copy has no node and no endpoint."""
    from aot.aot_flask.utils.utils_output import manipulate_output
    from aot.databases.models import OutputChannel
    for output_id in output_ids:
        row = Output.query.filter_by(unique_id=output_id).first()
        if row is not None:
            row.size_y = max(OutputChannel.query.filter_by(output_id=output_id).count(), 1) + 1
            row.save()
        for msg in manipulate_output('Modify', output_id).get('error') or []:
            out['warnings'].append(str(msg))


def _activate_input(input_id, out):
    from aot.aot_flask.utils.utils_input import input_activate
    for msg in input_activate(_IdForm(input_id=input_id)).get('error') or []:
        out['warnings'].append(str(msg))


def _restart_input(row):
    from aot.aot_flask.utils.utils_input import input_activate, input_deactivate
    if row.is_activated:
        input_deactivate(_IdForm(input_id=row.unique_id))
        input_activate(_IdForm(input_id=row.unique_id))


def remove_node(node_id):
    """Remove a node from the AoT fabric.

    Returns (ok, warning). The server sends RemoveFabric to the device only
    when it is reachable; otherwise it forgets the node locally and the device
    keeps an AoT entry until it is removed in the other app or reset. That is
    reported as a warning, not an error — the node is gone from AoT either way.
    """
    from aot.devices.matter_client import MatterCommandError, MatterError

    with _open_client() as client:
        if not client.wait_ready(CONNECT_WAIT_S):
            return False, _friendly_error(_not_connected())

        node = client.get_node(node_id)
        reachable = bool(node and node.get('available'))
        try:
            client.send_command('remove_node', {'node_id': int(node_id)},
                                timeout=REMOVE_TIMEOUT_S)
        except MatterCommandError as err:
            if err.error_code == ERR_NODE_NOT_EXISTS:
                return True, None   # already gone
            return False, gettext('Removing the device failed: %(details)s',
                                  details=str(err.details or err))
        except MatterError as err:
            return False, _friendly_error(err)

    if not reachable:
        return True, gettext(
            'The device was not reachable, so it still lists AoT as connected. Remove '
            'AoT from it in the other app (or reset it) to free that slot.')
    return True, None


def on_device_delete(device_row, messages):
    """Hook for controller_del(): take a Matter device off the AoT fabric and
    delete the children that only worked through it.

    Refuses (messages['error']) while a child is still used by a sequence,
    PID, widget, …: leaving the fabric cannot be undone, and the children
    would otherwise stay behind driving a node that no longer exists.
    Otherwise never blocks the delete: if the server is down the node stays
    on the fabric and is listed as an orphan on Settings > Matter.
    """
    if device_row is None or device_row.device != matter_onboarding.DEVICE_MODULE:
        return
    blocked = _children_in_use(device_row.unique_id)
    if blocked:
        messages['error'].extend(blocked)
        return
    node_id = _node_id_of(device_row)
    if node_id:
        try:
            ok, note = remove_node(node_id)
        except Exception:
            logger.exception("Matter remove_node failed for node %s", node_id)
            ok, note = False, None
        if not ok:
            messages['warning'].append(gettext(
                'AoT could not remove itself from the Matter device now. It is listed on '
                'Settings > Matter, where you can remove it later.'))
        elif note:
            messages['warning'].append(note)
    _delete_children(device_row.unique_id, messages)


def _matter_children(device_id):
    inputs = [r for r in Input.query.filter_by(parent_device_id=device_id).all()
              if r.device == matter_onboarding.INPUT_DRIVER]
    outputs = [r for r in Output.query.filter_by(parent_device_id=device_id).all()
               if r.output_type in matter_onboarding.OUTPUT_DRIVERS]
    return inputs, outputs


def _children_in_use(device_id):
    """Deletion-blocked messages for children something still refers to."""
    from aot.services.device_references import (deletion_blocked_message,
                                                find_device_referrers)
    inputs, outputs = _matter_children(device_id)
    rows = {r.unique_id: r for r in inputs + outputs}
    if not rows:
        return []
    # Siblings go together, so they may point at each other.
    referrers = find_device_referrers(list(rows), ignore_ids=list(rows) + [device_id])
    return [deletion_blocked_message(rows[uid].name, labels)
            for uid, labels in referrers.items() if labels]


def _delete_children(device_id, messages):
    from aot.aot_flask.utils.utils_input import input_del
    from aot.aot_flask.utils.utils_output import output_del

    inputs, outputs = _matter_children(device_id)
    for row in inputs:
        result = input_del(row.unique_id)
        for msg in result.get('error') or []:
            messages['warning'].append(str(msg))
    for row in outputs:
        result = output_del(_IdForm(output_id=row.unique_id))
        for msg in result.get('error') or []:
            messages['warning'].append(str(msg))
