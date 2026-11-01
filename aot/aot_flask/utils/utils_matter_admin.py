# coding=utf-8
"""Settings > Matter, phase 3: brand-new devices over Bluetooth, sharing an
AoT device to another ecosystem, and firmware updates.
Design: docs/design/matter-controller.md §13.

New devices (BLE)
-----------------
Commissioning a device out of the box takes minutes (Bluetooth discovery up
to 3 min, then the device joins Wi-Fi/Thread and is found on IP), longer
than one web request may wait. It runs as a job: a thread drives the Matter
server, a small JSON file holds the job's state (any gunicorn worker can
read it), and the page polls. The thread only talks to the Matter server;
creating the AoT device happens in the user's own poll request, so the
usual permission and group-scope checks apply to it.

The network credentials (Wi-Fi password, Thread dataset) are secrets the
Matter server stores unencrypted in its data volume — which AoT backs up.
So AoT never stores them, and does not leave them in the server's
credential list either: they are set under a one-off id right before
commissioning and removed right after, whatever the outcome (and swept up
later if the job died). They exist in this process only as local variables
of the job thread; the job file never sees them.

Residual risk (design §13): the server's storage is an append-only log, so
a removed password can remain in that log on disk — and in AoT backups —
until the server compacts it. matterjs-server 1.4.0 offers no way to avoid
or erase that.

Sharing
-------
open_commissioning_window gives a new pairing code for an AoT device (an
Enhanced Commissioning Window, up to 15 minutes). The code is shown once
and never stored or logged, like the codes people paste into AoT.

Firmware updates
----------------
The Matter server looks for updates itself (CSA DCL) but never installs
one unless asked (update_node). AoT keeps it that way: an update is only
ever started by a person, from certified (main-net DCL) sources, and the
progress is the device's own OTA Requestor state.

@phase experimental
@stability experimental
"""
import contextlib
import fcntl
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid

from flask_babel import gettext

from aot.aot_flask.utils import utils_matter
from aot.config import DATABASE_PATH

logger = logging.getLogger(__name__)

# Long enough for the slowest stages in matter.js 0.17.9 to run one after the
# other (BLE discovery 3 min, Wi-Fi scan+connect 2 min, operational discovery
# 2 min); a job that is still running after this has failed anyway.
NEW_DEVICE_TIMEOUT_S = 600.0
JOB_RETENTION_S = 24 * 3600
JOB_STALE_S = NEW_DEVICE_TIMEOUT_S + 120.0
REGISTER_STALE_S = 120.0

SHARE_TIMEOUT_DEFAULT_S = 900
SHARE_TIMEOUT_MIN_S = 180        # Matter: an ECM window lasts 3-15 minutes
SHARE_TIMEOUT_MAX_S = 900

OTA_STATE_IDLE = 1
OTA_STATE_NAMES = {
    1: 'idle', 2: 'querying', 3: 'delayed_on_query', 4: 'downloading',
    5: 'applying', 6: 'delayed_on_apply', 7: 'rolling_back', 8: 'delayed_on_consent',
}
ERR_OTA_DISABLED = 10
ERR_OTA_UPDATE = 11

ADMIN_COMMISSIONING_CLUSTER = 60      # AdministratorCommissioning
OPERATIONAL_CREDENTIALS = 62
OTA_REQUESTOR = 42

_JOB_ID_RE = re.compile(r'^[0-9a-f]{32}$')
_HEX_RE = re.compile(r'^(?:[0-9a-fA-F]{2})+$')


# ------------------------------------------------------------------ jobs

def _jobs_dir():
    path = os.path.join(DATABASE_PATH, 'matter_jobs')
    os.makedirs(path, exist_ok=True)
    return path


def _job_path(job_id):
    if not isinstance(job_id, str) or not _JOB_ID_RE.match(job_id):
        return None
    return os.path.join(_jobs_dir(), job_id + '.json')


@contextlib.contextmanager
def _job_lock(job_id):
    """Exclusive lock for one job, across threads and gunicorn workers. The
    lock file is never deleted while the job exists: a deleted-and-recreated
    lock file lets two holders in at once."""
    with open(_job_path(job_id) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write_job(job):
    path = _job_path(job['id'])
    fd, tmp = tempfile.mkstemp(dir=_jobs_dir(), prefix='.job-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(job, f)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def _read_job(job_id):
    path = _job_path(job_id)
    if path is None or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _update_job(job_id, **fields):
    path = _job_path(job_id)
    if path is None or not os.path.exists(path):
        return
    with _job_lock(job_id):
        job = _read_job(job_id)
        if job is None:
            return
        job.update(fields)
        job['updated'] = time.time()
        _write_job(job)


def _prune_jobs():
    """Drop finished jobs older than a day (job file and its lock together)."""
    now = time.time()
    try:
        names = os.listdir(_jobs_dir())
    except OSError:
        return
    for name in names:
        full = os.path.join(_jobs_dir(), name)
        try:
            if name.startswith('.job-') and now - os.path.getmtime(full) > 3600:
                os.remove(full)          # temp file of a crashed write
                continue
            if not name.endswith('.json'):
                continue
            if now - os.path.getmtime(full) <= JOB_RETENTION_S:
                continue
            os.remove(full)
            with contextlib.suppress(OSError):
                os.remove(full[:-len('.json')] + '.json.lock')
        except OSError:
            pass


def _live_cred_ids():
    """Credential ids of jobs that may still be using them."""
    live = set()
    now = time.time()
    try:
        names = os.listdir(_jobs_dir())
    except OSError:
        return live
    for name in names:
        if not name.endswith('.json'):
            continue
        job = _read_job(name[:-len('.json')])
        if (job and job.get('cred_id') and job.get('state') in ('starting', 'commissioning')
                and now - job.get('created', 0) <= JOB_STALE_S):
            live.add(job['cred_id'])
    return live


def sweep_stale_credentials(client):
    """Remove network credentials AoT left on the Matter server.

    A job's `finally` removes its temporary credentials, but a worker that
    dies mid-job (container restart, update, OOM) never gets there, and the
    server keeps the Wi-Fi password / Thread dataset in plain text in its
    data volume — which AoT backs up. Every `aot-…` id that no live job owns
    is removed. Returns the number removed. Never raises.
    """
    removed = 0
    try:
        creds = client.send_command('get_all_credentials', None, timeout=10.0) or {}
    except Exception:
        return 0
    live = _live_cred_ids()
    for kind, command in (('wifi', 'remove_wifi_credentials'),
                          ('thread', 'remove_thread_dataset')):
        for entry in creds.get(kind) or []:
            cred_id = (entry or {}).get('id') if isinstance(entry, dict) else None
            if not isinstance(cred_id, str) or not cred_id.startswith('aot-') \
                    or cred_id in live:
                continue
            try:
                client.send_command(command, {'id': cred_id}, timeout=10.0)
                removed += 1
            except Exception:
                logger.warning("Matter: could not remove leftover credentials %s", cred_id)
    if removed:
        logger.warning("Matter: removed %d leftover network credential(s) from the server",
                       removed)
    return removed


# ----------------------------------------------------------- new devices

def validate_network(network):
    """Check the network part of a new-device request. Returns (clean, error).

    clean is {'kind': 'wifi', 'ssid', 'password'} | {'kind': 'thread',
    'dataset'} | {'kind': 'none'} (the device is already on the network, e.g.
    an Ethernet device in pairing mode).
    """
    if network is None:
        network = {}
    if not isinstance(network, dict):
        return None, gettext('Unknown network type.')
    kind = network.get('kind') or 'wifi'
    if kind == 'none':
        return {'kind': 'none'}, None
    if kind == 'wifi':
        ssid = network.get('ssid')
        password = network.get('password')
        if not isinstance(ssid, str) or not ssid.strip():
            return None, gettext('Enter the Wi-Fi network name.')
        if len(ssid.encode('utf-8')) > 32:
            return None, gettext('A Wi-Fi network name is at most 32 bytes.')
        if not isinstance(password, str) or not (8 <= len(password) <= 64):
            return None, gettext('Enter the Wi-Fi password (8 to 64 characters).')
        return {'kind': 'wifi', 'ssid': ssid, 'password': password}, None
    if kind == 'thread':
        dataset = network.get('dataset')
        dataset = dataset.strip().replace(' ', '') if isinstance(dataset, str) else ''
        if not _HEX_RE.match(dataset) or not (16 <= len(dataset) <= 508):
            return None, gettext(
                'Enter the Thread operational dataset as hex (from your border router).')
        return {'kind': 'thread', 'dataset': dataset}, None
    return None, gettext('Unknown network type.')


def bluetooth_status(wait_s=2.0):
    """{'connected', 'bluetooth_enabled'} from the server's own info."""
    with utils_matter._open_client() as client:
        client.wait_ready(wait_s)
        info = client.server_info() or {}
        return {'connected': client.is_connected(),
                'bluetooth_enabled': bool(info.get('bluetooth_enabled'))}


def start_new_device(raw_code, network, user_id=None):
    """Start commissioning a device that is not on any network yet.

    Returns {'ok', 'job_id', 'error'}. The work continues in a thread; poll
    new_device_status(job_id).
    """
    code = utils_matter.normalize_code(raw_code)
    if code is None:
        return {'ok': False, 'job_id': None, 'error': gettext(
            'Enter the 11-digit pairing code (or the MT: code) from the device or its box.')}
    clean, error = validate_network(network)
    if error:
        return {'ok': False, 'job_id': None, 'error': error}

    with utils_matter._open_client() as client:
        client.wait_ready(2.0)
        info = client.server_info() or {}
        status = {'connected': client.is_connected(),
                  'bluetooth_enabled': bool(info.get('bluetooth_enabled'))}
        if status['connected']:
            sweep_stale_credentials(client)
    if not status['connected']:
        return {'ok': False, 'job_id': None,
                'error': utils_matter.error_message('not_connected')}
    if clean['kind'] != 'none' and not status['bluetooth_enabled']:
        return {'ok': False, 'job_id': None,
                'error': utils_matter.error_message('ble_unavailable')}

    _prune_jobs()
    job_id = uuid.uuid4().hex
    _write_job({
        'id': job_id, 'state': 'starting', 'user_id': user_id,
        'network': clean['kind'], 'created': time.time(), 'updated': time.time(),
        'node_id': None, 'error_category': None, 'error_details': None,
        'result': None,
        # Not secret: lets a later sweep remove what a dead job left behind.
        'cred_id': _cred_id(job_id) if clean['kind'] in ('wifi', 'thread') else None,
        'creds_removed': clean['kind'] not in ('wifi', 'thread'),
    })
    threading.Thread(target=_run_new_device, args=(job_id, code, clean), daemon=True,
                     name=f'matter-new-{job_id[:8]}').start()
    return {'ok': True, 'job_id': job_id, 'error': None}


def _run_new_device(job_id, code, network):
    """Job thread. Holds the network secret only in `network` (this frame)."""
    from aot.devices.matter_client import (DEFAULT_SOCKET_PATH, MatterError,
                                           MatterServerClient)
    client = MatterServerClient(
        socket_path=os.environ.get('AOT_MATTER_SOCKET') or DEFAULT_SOCKET_PATH,
        url=os.environ.get('AOT_MATTER_URL') or None,
        ping_interval=30.0, ping_timeout=NEW_DEVICE_TIMEOUT_S + 60.0, quiet=True)
    cred_id = _cred_id(job_id)
    cred_set = None
    try:
        client.ensure_started()
        if not client.wait_ready(utils_matter.CONNECT_WAIT_S):
            _update_job(job_id, state='failed', error_category='not_connected')
            return
        utils_matter._set_fabric_label(client)
        args = {'code': code, 'network_only': network['kind'] == 'none'}
        # Mark for removal BEFORE sending: if the reply is lost or times out
        # the server may have stored the secret anyway.
        if network['kind'] == 'wifi':
            cred_set = 'wifi'
            client.send_command('set_wifi_credentials', {
                'ssid': network['ssid'], 'credentials': network['password'], 'id': cred_id},
                timeout=10.0)
            args['wifi_credentials_id'] = cred_id
        elif network['kind'] == 'thread':
            cred_set = 'thread'
            client.send_command('set_thread_dataset', {
                'dataset': network['dataset'], 'id': cred_id}, timeout=10.0)
            args['thread_dataset_id'] = cred_id
        _update_job(job_id, state='commissioning')
        node = client.send_command('commission_with_code', args,
                                   timeout=NEW_DEVICE_TIMEOUT_S)
        if not isinstance(node, dict) or node.get('node_id') is None:
            _update_job(job_id, state='failed', error_category='other',
                        error_details='no device returned')
            return
        _update_job(job_id, state='commissioned', node_id=int(node['node_id']))
    except MatterError as err:
        category, details = utils_matter.error_category(err)
        logger.warning("Matter new-device job %s failed: %s", job_id[:8], category)
        _update_job(job_id, state='failed', error_category=category,
                    error_details=_scrub(details, network))
    except Exception as err:
        logger.exception("Matter new-device job %s crashed", job_id[:8])
        _update_job(job_id, state='failed', error_category='other',
                    error_details=_scrub(type(err).__name__, network))
    finally:
        # Never leave the secret on the server (it stores it unencrypted).
        # If this fails (connection lost), sweep_stale_credentials() removes
        # it before the next job or when the job is found stale.
        try:
            if cred_set == 'wifi':
                client.send_command('remove_wifi_credentials', {'id': cred_id}, timeout=10.0)
            elif cred_set == 'thread':
                client.send_command('remove_thread_dataset', {'id': cred_id}, timeout=10.0)
            if cred_set:
                _update_job(job_id, creds_removed=True)
        except Exception:
            logger.warning("Matter: could not remove temporary %s credentials %s now; "
                           "they will be swept later", cred_set, cred_id)
        network.pop('password', None)
        network.pop('dataset', None)
        client.stop(timeout=2.0)


def _cred_id(job_id):
    return f'aot-{job_id[:12]}'


def _scrub(text, network):
    """Server error text can echo what it was given; keep secrets out."""
    text = str(text or '')
    for key in ('password', 'dataset'):
        secret = network.get(key)
        if secret:
            text = text.replace(secret, '***')
    return text[:300]


def new_device_status(job_id):
    """State of a job for the page. Registers the AoT device once the node is
    on the fabric — here, in the polling user's request (permissions and
    group scope apply), exactly once across workers (file lock)."""
    job = _read_job(job_id)
    if job is None:
        return {'state': 'unknown', 'error': gettext('Unknown or expired job.')}

    if job['state'] in ('starting', 'commissioning') and \
            time.time() - job.get('created', 0) > JOB_STALE_S:
        # The thread died with its worker (restart, update): its credentials
        # may still be on the server.
        _update_job(job_id, state='failed', error_category='timeout')
        if not job.get('creds_removed'):
            with contextlib.suppress(Exception):
                with utils_matter._open_client() as client:
                    if client.wait_ready(utils_matter.CONNECT_WAIT_S):
                        sweep_stale_credentials(client)
        job = _read_job(job_id)

    if job['state'] == 'registering' and \
            time.time() - job.get('updated', 0) > REGISTER_STALE_S:
        _update_job(job_id, state='commissioned')     # that request died; retry
        job = _read_job(job_id)

    if job['state'] == 'commissioned':
        # Registration creates rows; the lock makes it happen once even when
        # several workers answer polls at the same moment. _update_job takes
        # the same lock, so release it before _register() writes.
        registering = False
        with _job_lock(job_id):
            job = _read_job(job_id)
            if job['state'] == 'commissioned':
                job['state'] = 'registering'
                job['updated'] = time.time()
                _write_job(job)
                registering = True
        if registering:
            try:
                job = _register(job)
            except Exception:
                _update_job(job_id, state='commissioned')
                raise
        else:
            job = _read_job(job_id)

    out = {'state': job['state'], 'node_id': job.get('node_id'), 'error': None,
           'result': job.get('result')}
    if job['state'] == 'failed':
        out['error'] = utils_matter.error_message(
            job.get('error_category') or 'other', job.get('error_details') or '',
            new_device=True)
    return out


def _register(job):
    from aot.devices import matter_clusters
    with utils_matter._open_client() as client:
        if not client.wait_ready(utils_matter.CONNECT_WAIT_S):
            _update_job(job['id'], state='commissioned')   # try again on the next poll
            return _read_job(job['id'])
        node = client.get_node(job['node_id'])
    if node is None:
        _update_job(job['id'], state='failed', error_category='other',
                    error_details='node missing after commissioning')
        return _read_job(job['id'])
    inputs, outputs = matter_clusters.discover_channels(node)
    reg = utils_matter.register_node(node)
    result = {'device_id': reg['device_id'], 'rebound': reg['rebound'],
              'sensor_count': len(inputs), 'switch_count': len(outputs),
              'warnings': reg['warnings']}
    if reg['error']:
        _update_job(job['id'], state='failed', error_category='other',
                    error_details=str(reg['error'])[:300], result=result)
    else:
        _update_job(job['id'], state='done', result=result)
    return _read_job(job['id'])


# --------------------------------------------------------------- sharing

def _ready_client_or_error(client):
    if not client.wait_ready(utils_matter.CONNECT_WAIT_S):
        return utils_matter.error_message('not_connected')
    return None


def _attr(node, endpoint, cluster, attribute):
    from aot.devices.matter_clusters import attribute_path
    return ((node or {}).get('attributes') or {}).get(
        attribute_path(endpoint, cluster, attribute))


def open_share_window(node_id, timeout_s=SHARE_TIMEOUT_DEFAULT_S):
    """A pairing code another ecosystem can use to add this device.

    Returns {'ok', 'error', 'manual_code', 'qr_code', 'expires_in'}.
    """
    from aot.devices.matter_client import MatterError
    out = {'ok': False, 'error': None, 'manual_code': None, 'qr_code': None,
           'expires_in': None}
    try:
        timeout_s = int(timeout_s)
    except (TypeError, ValueError):
        timeout_s = SHARE_TIMEOUT_DEFAULT_S
    timeout_s = max(SHARE_TIMEOUT_MIN_S, min(SHARE_TIMEOUT_MAX_S, timeout_s))
    with utils_matter._open_client() as client:
        error = _ready_client_or_error(client)
        if error:
            out['error'] = error
            return out
        node = client.get_node(node_id)
        if not node:
            out['error'] = gettext('This device is not on the Matter server.')
            return out
        if not node.get('available'):
            out['error'] = gettext(
                'The device is not reachable right now, so it cannot be shared.')
            return out
        supported = _attr(node, 0, OPERATIONAL_CREDENTIALS, 2)
        used = _attr(node, 0, OPERATIONAL_CREDENTIALS, 3)
        if isinstance(supported, int) and isinstance(used, int) and used >= supported:
            out['error'] = utils_matter.error_message('fabric_full')
            return out
        try:
            res = client.send_command('open_commissioning_window', {
                'node_id': int(node_id), 'timeout': timeout_s}, timeout=30.0)
        except MatterError as err:
            out['error'] = gettext('Opening the sharing window failed: %(details)s',
                                   details=_details(err))
            return out
    out.update({'ok': True, 'manual_code': (res or {}).get('setup_manual_code'),
                'qr_code': (res or {}).get('setup_qr_code'), 'expires_in': timeout_s})
    return out


def close_share_window(node_id):
    """Close an open sharing window early (the code stops working)."""
    from aot.devices.matter_client import MatterError
    with utils_matter._open_client() as client:
        error = _ready_client_or_error(client)
        if error:
            return {'ok': False, 'error': error}
        try:
            client.send_command('device_command', {
                'node_id': int(node_id), 'endpoint_id': 0,
                'cluster_id': ADMIN_COMMISSIONING_CLUSTER,
                'command_name': 'RevokeCommissioning', 'payload': {}}, timeout=15.0)
        except MatterError as err:
            low = _details(err).lower().replace(' ', '')
            # No window open: nothing to close. The server reports the
            # cluster status (4 = WindowNotOpen), not the name (observed).
            if 'windownotopen' in low or 'clustercode4' in low:
                return {'ok': True, 'error': None}
            return {'ok': False, 'error': gettext(
                'Closing the sharing window failed: %(details)s', details=_details(err))}
    return {'ok': True, 'error': None}


def list_fabrics(node_id):
    """Ecosystems (fabrics) the device belongs to, read live from the device.

    Returns {'ok', 'error', 'fabrics': [{fabric_index, label, vendor_id,
    vendor_name, own}], 'supported', 'used'}.
    """
    from aot.devices.matter_client import MatterError
    out = {'ok': False, 'error': None, 'fabrics': [], 'supported': None, 'used': None}
    with utils_matter._open_client() as client:
        error = _ready_client_or_error(client)
        if error:
            out['error'] = error
            return out
        node = client.get_node(node_id)
        own_index = _own_fabric_index(node)
        out['supported'] = _attr(node, 0, OPERATIONAL_CREDENTIALS, 2)
        out['used'] = _attr(node, 0, OPERATIONAL_CREDENTIALS, 3)
        try:
            rows = client.send_command('get_matter_fabrics', {'node_id': int(node_id)},
                                       timeout=20.0) or []
        except MatterError as err:
            out['error'] = gettext('Reading the device\'s connections failed: %(details)s',
                                   details=_details(err))
            return out
    for row in rows if isinstance(rows, list) else []:
        out['fabrics'].append({
            'fabric_index': row.get('fabric_index'),
            'label': row.get('fabric_label') or '',
            'vendor_id': row.get('vendor_id'),
            'vendor_name': row.get('vendor_name') or '',
            'own': own_index is not None and row.get('fabric_index') == own_index,
        })
    out['ok'] = True
    return out


def remove_other_fabric(node_id, fabric_index):
    """Remove another ecosystem's connection from the device. AoT's own is
    refused here — that goes through deleting the AoT device, which also
    cleans up its sensors and switches."""
    from aot.devices.matter_client import MatterError
    try:
        fabric_index = int(fabric_index)
    except (TypeError, ValueError):
        return {'ok': False, 'error': gettext('Unknown connection.')}
    with utils_matter._open_client() as client:
        error = _ready_client_or_error(client)
        if error:
            return {'ok': False, 'error': error}
        # The device numbers its fabrics itself; AoT's slot on THIS device is
        # its CurrentFabricIndex as read by AoT — not the server's own
        # fabric_index (that is the slot in the server's table, usually 1).
        own_index = _own_fabric_index(client.get_node(node_id))
        if own_index is None or fabric_index == own_index:
            return {'ok': False, 'error': gettext(
                'This is AoT\'s own connection. Remove the device instead.')}
        try:
            client.send_command('remove_matter_fabric', {
                'node_id': int(node_id), 'fabric_index': fabric_index}, timeout=20.0)
            # The server answers {} even when nothing was removed (observed),
            # so confirm against the device's own list.
            remaining = client.send_command('get_matter_fabrics', {'node_id': int(node_id)},
                                            timeout=20.0) or []
        except MatterError as err:
            return {'ok': False, 'error': gettext(
                'Removing the connection failed: %(details)s', details=_details(err))}
    if any(isinstance(row, dict) and row.get('fabric_index') == fabric_index
           for row in remaining):
        return {'ok': False, 'error': gettext(
            'The device did not remove that connection. Try again.')}
    return {'ok': True, 'error': None}


def _own_fabric_index(node):
    """AoT's fabric index on this device: OperationalCredentials
    CurrentFabricIndex (0/62/5), which a device reports per reading fabric."""
    value = _attr(node, 0, OPERATIONAL_CREDENTIALS, 5)
    return value if isinstance(value, int) and value > 0 else None


def _details(err):
    return str(getattr(err, 'details', None) or err)[:300]


# --------------------------------------------------------------- updates

def update_state(node):
    """{'version', 'state', 'progress'} from the node's cache (no network)."""
    from aot.devices.matter_clusters import BASIC_INFORMATION
    state = _attr(node, 0, OTA_REQUESTOR, 2)
    return {
        'version': _attr(node, 0, BASIC_INFORMATION, 10) or '',
        'state': OTA_STATE_NAMES.get(state) if isinstance(state, int) else None,
        'progress': _attr(node, 0, OTA_REQUESTOR, 3),
    }


def check_update(node_id):
    """Ask the server whether a newer certified firmware exists.

    Returns {'ok', 'error', 'update': None | {version, version_string,
    release_notes_url, source, certified}}.
    """
    from aot.devices.matter_client import MatterCommandError, MatterError
    with utils_matter._open_client() as client:
        error = _ready_client_or_error(client)
        if error:
            return {'ok': False, 'error': error, 'update': None}
        try:
            res = client.send_command('check_node_update', {'node_id': int(node_id)},
                                      timeout=60.0)
        except MatterCommandError as err:
            if err.error_code == ERR_OTA_DISABLED:
                return {'ok': False, 'update': None, 'error': gettext(
                    'Firmware updates are turned off on the Matter server.')}
            return {'ok': False, 'update': None, 'error': gettext(
                'Checking for an update failed: %(details)s', details=_details(err))}
        except MatterError as err:
            return {'ok': False, 'update': None,
                    'error': utils_matter.error_message(*utils_matter.error_category(err))}
    if not res:
        return {'ok': True, 'error': None, 'update': None}
    source = res.get('update_source') or ''
    return {'ok': True, 'error': None, 'update': {
        'version': res.get('software_version'),
        'version_string': res.get('software_version_string') or str(res.get('software_version')),
        'release_notes_url': res.get('release_notes_url') or '',
        'source': source,
        # Only firmware published on the CSA main-net DCL is certified.
        'certified': source == 'main-net-dcl',
    }}


def start_update(node_id, version):
    """Start a firmware update a person asked for. Only certified sources,
    only on an idle, reachable device."""
    from aot.devices.matter_client import MatterCommandError, MatterError
    check = check_update(node_id)
    if not check['ok']:
        return {'ok': False, 'error': check['error']}
    update = check['update']
    if not update:
        return {'ok': False, 'error': gettext('No update is available for this device.')}
    if not update['certified']:
        return {'ok': False, 'error': gettext(
            'This update does not come from the certified (CSA) source, so AoT does not '
            'install it.')}
    # The person confirmed a specific version; never fall back to "whatever
    # is available now".
    try:
        version = int(version)
    except (TypeError, ValueError):
        return {'ok': False, 'error': gettext(
            'The available update changed. Check again before updating.')}
    if version != update['version']:
        return {'ok': False, 'error': gettext(
            'The available update changed. Check again before updating.')}
    with utils_matter._open_client() as client:
        error = _ready_client_or_error(client)
        if error:
            return {'ok': False, 'error': error}
        node = client.get_node(node_id)
        if not node or not node.get('available'):
            return {'ok': False, 'error': gettext(
                'The device is not reachable right now.')}
        state = _attr(node, 0, OTA_REQUESTOR, 2)
        if isinstance(state, int) and state != OTA_STATE_IDLE:
            return {'ok': False, 'error': gettext(
                'The device is already busy with an update.')}
        try:
            client.send_command('update_node', {'node_id': int(node_id),
                                                'software_version': version}, timeout=60.0)
        except MatterCommandError as err:
            return {'ok': False, 'error': gettext(
                'Starting the update failed: %(details)s', details=_details(err))}
        except MatterError as err:
            return {'ok': False,
                    'error': utils_matter.error_message(*utils_matter.error_category(err))}
    return {'ok': True, 'error': None}
