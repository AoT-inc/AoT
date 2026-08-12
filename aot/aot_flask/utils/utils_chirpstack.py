# coding=utf-8
"""
ChirpStack LNS helper.

- Reads the global ChirpStack connection (gRPC server + API token + MQTT broker)
  stored on the Misc settings row.
- Lists devices registered in ChirpStack via gRPC (Tenant -> Application -> Device).
- Registers a ChirpStack device as an AoT Input (chirpstack_mqtt_jmespath, uplink
  via MQTT) or Output (chirpstack_downlink, downlink via gRPC), pre-filling the
  module's custom_options so the operator does not have to retype the DevEUI.

Used by the "ChirpStack Devices" settings page (routes_settings).
"""
import json
import logging

logger = logging.getLogger(__name__)

try:
    import grpc  # type: ignore[import-not-found]
except ModuleNotFoundError:
    grpc = None

try:
    from chirpstack_api import api as cs_api  # type: ignore[import-not-found]
except ModuleNotFoundError:
    cs_api = None

from flask import current_app

from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import custom_channel_options_return_json
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_flask.utils.utils_output import manipulate_output
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Input
from aot.databases.models import InputChannel
from aot.databases.models import Misc
from aot.databases.models import Output
from aot.databases.models import OutputChannel
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import parse_output_information

INPUT_MODULE = 'chirpstack_mqtt_jmespath'   # input_name_unique (uplink, MQTT)
OUTPUT_MODULE = 'chirpstack_downlink'        # output_name_unique (downlink, gRPC)


# ----------------------------------------------------------------------------
# Connection
# ----------------------------------------------------------------------------
def get_chirpstack_conn():
    """Return (grpc_server, api_token, mqtt_host, mqtt_port) from the Misc row."""
    m = Misc.query.first()
    if not m:
        return '', '', '', 1883
    return (
        (m.chirpstack_grpc_server or '').strip(),
        (m.chirpstack_api_token or '').strip(),
        (m.chirpstack_mqtt_host or '').strip(),
        int(m.chirpstack_mqtt_port or 1883),
    )


def _normalize_server(server):
    s = (server or '').strip()
    if '://' in s:
        s = s.split('://', 1)[1]
    s = s.split('/', 1)[0]
    # Append ChirpStack's default gRPC API port if the caller omitted one.
    # grpc.insecure_channel() without an explicit port doesn't default to
    # ChirpStack's port (8080) -- it can pick an unreachable address/port
    # (e.g. an IPv6 literal on 443), failing with a confusing UNAVAILABLE
    # "Network is unreachable" instead of connecting.
    if s and ':' not in s.split(']')[-1]:  # tolerate bracketed IPv6 literals
        s = f'{s}:8080'
    return s


def _normalize_token(token):
    t = (token or '').strip()
    if t.lower().startswith('bearer '):
        t = t[7:].strip()
    return t


def grpc_available():
    return bool(grpc and cs_api)


# ----------------------------------------------------------------------------
# Device listing (gRPC: Tenant -> Application -> Device)
# ----------------------------------------------------------------------------
def list_chirpstack_devices(server, token, limit=100):
    """List all devices accessible by the API token.

    Returns (devices, error). On success error is None and devices is a list of
    dicts: {dev_eui, name, description, application_id, application_name,
            tenant_name, device_profile_name, last_seen}.
    """
    if not grpc_available():
        return [], "gRPC client libraries (grpcio / chirpstack-api) are not installed."

    server = _normalize_server(server)
    token = _normalize_token(token)
    if not server or not token:
        return [], "ChirpStack gRPC server and API token are required."

    md = [("authorization", f"Bearer {token}")]
    devices = []
    channel = None
    try:
        channel = grpc.insecure_channel(server)
        tenant_stub = cs_api.TenantServiceStub(channel)
        app_stub = cs_api.ApplicationServiceStub(channel)
        dev_stub = cs_api.DeviceServiceStub(channel)

        # An admin API key can list tenants; a tenant key may not. Fall back to
        # listing applications without a tenant filter when tenant listing fails.
        tenants = []
        try:
            tresp = tenant_stub.List(cs_api.ListTenantsRequest(limit=limit), metadata=md, timeout=10)
            tenants = [(t.id, t.name) for t in tresp.result]
        except grpc.RpcError:
            tenants = []

        if not tenants:
            tenants = [(None, '')]  # try application listing without tenant filter

        apps_error = None
        for tenant_id, tenant_name in tenants:
            areq = cs_api.ListApplicationsRequest(limit=limit)
            if tenant_id:
                areq.tenant_id = tenant_id
            try:
                aresp = app_stub.List(areq, metadata=md, timeout=10)
            except grpc.RpcError as err:
                # If we cannot list applications for this tenant, skip it -- but
                # remember the error, since if EVERY tenant fails (including the
                # no-tenant-filter fallback) this is a real auth/connection
                # failure, not just an empty ChirpStack instance.
                logger.debug("ChirpStack ListApplications failed for tenant %s: %s", tenant_id, err)
                apps_error = f"gRPC error: {err.code().name} - {err.details()}"
                continue

            for app in aresp.result:
                dreq = cs_api.ListDevicesRequest(limit=limit, application_id=app.id)
                dresp = dev_stub.List(dreq, metadata=md, timeout=10)
                for d in dresp.result:
                    last_seen = ''
                    try:
                        if d.HasField('last_seen_at'):
                            last_seen = d.last_seen_at.ToDatetime().isoformat(sep=' ', timespec='seconds')
                    except Exception:
                        pass
                    devices.append({
                        'dev_eui': d.dev_eui,
                        'name': d.name,
                        'description': d.description,
                        'application_id': app.id,
                        'application_name': app.name,
                        'tenant_name': tenant_name,
                        'device_profile_name': d.device_profile_name,
                        'last_seen': last_seen,
                    })
        if not devices and apps_error:
            return [], apps_error
        return devices, None
    except grpc.RpcError as err:
        return [], f"gRPC error: {err.code().name} - {err.details()}"
    except Exception as err:
        return [], f"{err}"
    finally:
        try:
            if channel is not None:
                channel.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Registration helpers
# ----------------------------------------------------------------------------
def _defaults_for(parse_information, device_type):
    """Return a dict of default custom_options for the given input/output type."""
    try:
        _err, options_json = custom_options_return_json(
            [], parse_information(), device=device_type, use_defaults=True)
        opts = json.loads(options_json) if options_json else {}
        return opts if isinstance(opts, dict) else {}
    except Exception as err:
        logger.warning("ChirpStack register: failed to build defaults for %s: %s", device_type, err)
        return {}


def register_device_as_input(dev_eui, name=None, channel_jmespaths=None):
    """Create a chirpstack_mqtt_jmespath Input pre-filled for this device.

    MQTT broker host/port come from the global ChirpStack connection; the DevEUI
    filter is set so only this device's uplinks are consumed. channel_jmespaths
    (one JMESPath per channel — usually shared per device profile) pre-creates the
    measurement channels so they need not be entered per device.
    """
    messages = {"success": [], "info": [], "warning": [], "error": []}
    dev_eui = (dev_eui or '').strip().lower()
    if not dev_eui:
        messages["error"].append("DevEUI is required to register an input.")
        return messages, None

    _server, _token, mqtt_host, mqtt_port = get_chirpstack_conn()
    jmes = [j.strip() for j in (channel_jmespaths or []) if j and j.strip()]

    try:
        opts = _defaults_for(parse_input_information, INPUT_MODULE)
        opts['device_euis'] = dev_eui
        if mqtt_host:
            opts['mqtt_host'] = mqtt_host
        if mqtt_port:
            opts['mqtt_port'] = mqtt_port
        if name:
            opts['name'] = name

        new_input = Input()
        new_input.device = INPUT_MODULE
        new_input.name = (name or f"ChirpStack {dev_eui}")[:255]
        max_pos = db.session.query(db.func.max(Input.position_y)).scalar()
        new_input.position_y = (max_pos or 0) + 1
        new_input.custom_options = json.dumps(opts)
        new_input.save()
        db.session.commit()

        # Pre-create measurement channels from the per-channel JMESPath template.
        dict_inputs = parse_input_information()
        for ch, expr in enumerate(jmes):
            new_meas = DeviceMeasurements()
            new_meas.device_id = new_input.unique_id
            new_meas.channel = ch
            new_meas.save()
            new_channel = InputChannel()
            new_channel.input_id = new_input.unique_id
            new_channel.channel = ch
            _err, ch_opts = custom_channel_options_return_json(
                [], dict_inputs, None, new_input.unique_id, ch,
                device=INPUT_MODULE, use_defaults=True)
            try:
                ch_dict = json.loads(ch_opts) if isinstance(ch_opts, str) else (ch_opts or {})
            except Exception:
                ch_dict = {}
            ch_dict['jmespath_expression'] = expr
            new_channel.custom_options = json.dumps(ch_dict)
            new_channel.save()

        messages["success"].append(f"Registered input for device {dev_eui}")
        return messages, new_input.unique_id
    except Exception as err:
        logger.exception("ChirpStack register input failed")
        messages["error"].append(f"Failed to register input: {err}")
        return messages, None


def register_device_as_output(dev_eui, name=None,
                              on_payload=None, off_payload=None, f_port=None):
    """Create a chirpstack_downlink Output pre-filled for this device.

    The gRPC server + API token come from the global ChirpStack connection; the
    DevEUI is set so downlinks target this device. on/off payload + FPort are the
    COMMON values (usually shared per device profile) — pass them once during
    onboarding so they need not be typed per device.
    """
    messages = {"success": [], "info": [], "warning": [], "error": []}
    dev_eui = (dev_eui or '').strip().lower()
    if not dev_eui:
        messages["error"].append("DevEUI is required to register an output.")
        return messages, None

    server, token, _mqtt_host, _mqtt_port = get_chirpstack_conn()

    dict_outputs = parse_output_information()
    if OUTPUT_MODULE not in dict_outputs:
        messages["error"].append(f"Output module '{OUTPUT_MODULE}' not found.")
        return messages, None

    try:
        opts = _defaults_for(parse_output_information, OUTPUT_MODULE)
        if server:
            opts['cs_server'] = server
        if token:
            opts['cs_api_token'] = token
        opts['dev_eui'] = dev_eui
        # Common payload template (applied to all onboarded devices, override later if needed)
        if on_payload:
            opts['on_payload'] = on_payload
        if off_payload:
            opts['off_payload'] = off_payload
        if f_port not in (None, ''):
            try:
                opts['f_port'] = int(f_port)
            except Exception:
                pass

        new_output = Output()
        new_output.output_type = OUTPUT_MODULE
        new_output.name = (name or f"ChirpStack {dev_eui}")[:255]
        channels_dict = dict_outputs[OUTPUT_MODULE].get('channels_dict', {0: {}})
        new_output.size_y = len(channels_dict) + 1
        max_pos = db.session.query(db.func.max(Output.position_y)).scalar()
        new_output.position_y = (max_pos or 0) + 1
        new_output.custom_options = json.dumps(opts)
        new_output.save()
        db.session.commit()

        # Measurements defined by the module (chirpstack_downlink: duration_time)
        for ch, measure_info in dict_outputs[OUTPUT_MODULE].get('measurements_dict', {}).items():
            new_measurement = DeviceMeasurements()
            if 'name' in measure_info:
                new_measurement.name = str(measure_info['name'])
            new_measurement.device_id = new_output.unique_id
            new_measurement.measurement = measure_info.get('measurement', '')
            new_measurement.unit = measure_info.get('unit', '')
            new_measurement.channel = ch
            new_measurement.save()

        # Output channels with default channel options
        for ch in channels_dict:
            new_channel = OutputChannel()
            new_channel.channel = ch
            new_channel.output_id = new_output.unique_id
            _err, ch_opts = custom_channel_options_return_json(
                [], dict_outputs, None, new_output.unique_id, ch,
                device=OUTPUT_MODULE, use_defaults=True)
            new_channel.custom_options = ch_opts if isinstance(ch_opts, str) else json.dumps(ch_opts or {})
            new_channel.save()

        # Tell the running daemon about the new output so it can later be
        # deleted/modified (mirrors utils_output.output_add()); skipping this
        # left the daemon unaware of chirpstack-onboarded outputs, causing a
        # KeyError on delete.
        if not current_app.config['TESTING']:
            daemon_messages = manipulate_output('Add', new_output.unique_id)
            messages["error"].extend(daemon_messages["error"])
            messages["success"].extend(daemon_messages["success"])

        messages["success"].append(f"Registered output for device {dev_eui}")
        return messages, new_output.unique_id
    except Exception as err:
        logger.exception("ChirpStack register output failed")
        messages["error"].append(f"Failed to register output: {err}")
        return messages, None
