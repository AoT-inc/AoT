# coding=utf-8
"""ChirpStack gRPC 장치 열거 — flask·DB 에 의존하지 않는 순수 부분 (아키텍처 7c).

원래 `aot.aot_flask.utils.utils_chirpstack` 에 있었으나, 데몬(lorawan_class_scheduler)이
이것만 쓰려고 웹 계층 모듈 전체(flask·모델)를 import 하게 되어 아래층으로 뺐다.
`utils_chirpstack` 가 같은 이름으로 다시 내보내므로 기존 호출처는 그대로다.
"""
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
