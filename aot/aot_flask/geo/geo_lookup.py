# coding=utf-8
"""위치 조회 문(gate) — 주소·장소 이름 → 좌표를 GIS 입력의 지오코딩 API 로 푼다.

GIS 입력(`inputs_gis/gis_*.py`)은 저마다 `search()` 로 주소 검색을 제공한다
(`search_capabilities` 에 'address' 가 든 것). 이 모듈이 그 **유일한 입구**다 —
지도 검색창(`/api/geo/search`)과 MCP(`find.location`)가 같은 길로 부르고,
공급자 고르기·키 읽기·결과 모양 맞추기는 여기서만 한다. 호출처에 공급자 이름이나
키 읽기를 흩어 두지 않는다.

- 어느 공급자: 호출이 준 `provider`(레이어 id 또는 종류 이름) → 사용자가 지도 설정에서 고른
  검색 공급자(`GeoSetting.providers['search_provider']`) → 키 없는 기본(`gis_osm`).
  지역별 우선순위는 코드가 정하지 않는다.
- 키: GIS 입력에 저장된 옵션, 없으면 지도 전역 키(`GeoSetting.keys`).
- 결과: 공급자마다 다른 모양을 `{name, lat, lng, address, provider}` 로 맞춘다.

새 공급자: GIS 입력 모듈이 `search_capabilities` 에 'address' 를 선언하고 `search()` 를 구현하면 끝이다
(`inputs_gis/base_input_gis.py::AbstractGisInput.search` 의 계약). 이 모듈·MCP·도구 표는 고치지 않는다 —
공급자 목록은 등록된 GIS 입력(GeoLayer)과 그 모듈 선언에서 그때그때 읽는다. 특정 나라·공급자 이름은 여기에 없다.

좌표 → 주소(역지오코딩)도 같은 문이다(`find_address`). GIS 입력이 `reverse_capabilities = ['address']` 를 선언하고
`reverse()` 를 구현하면 된다. 역방향 공급자는: 호출 값 → 지도 설정의 검색 공급자(역방향을 하면) →
등록된 GIS 입력 중 역방향을 하는 첫 켜진 것(예전부터 VWorld 를 쓰던 설치가 그대로 이어지게) → `gis_osm`.
"""
import json
import logging
import math

logger = logging.getLogger(__name__)

#: 지도 설정에 검색 공급자가 없을 때 쓰는 기본(키가 필요 없다). 웹 검색창의 기존 기본과 같다.
DEFAULT_PROVIDER = 'gis_osm'
#: 한 번에 돌려줄 후보 수의 상한.
MAX_RESULTS = 10
DEFAULT_RESULTS = 5
#: 주소로 찾는다는 뜻의 능력 이름 — `search_capabilities` 에 있어야 한다.
CAP_ADDRESS = 'address'
#: 능력을 선언하는 GIS 입력 클래스 속성 — 정방향(주소→좌표) / 역방향(좌표→주소).
ATTR_SEARCH, ATTR_REVERSE = 'search_capabilities', 'reverse_capabilities'


class GeoLookupError(Exception):
    """조회를 시작도 못 한 이유. `code` 는 호출처가 가르는 짧은 이름, `status` 는 웹 응답 코드."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _load_provider(layer_id):
    """검색 공급자 인스턴스를 만든다 — 레이어 unique_id 또는 종류 이름(`gis_vworld` …).

    레이어가 없는 종류 이름이면 같은 종류의 등록된 레이어(켜진 것 먼저)의 옵션을 물려받는다.
    키는 레이어 옵션 → 지도 전역 키 순.
    """
    from aot.databases.models import GeoLayer, GeoSetting
    from aot.utils.inputs import parse_input_information
    from aot.utils.modules import load_module_from_file
    from aot.aot_flask.utils.utils_geo import MockInputDev

    dict_inputs = parse_input_information()
    layer = (GeoLayer.query.filter_by(unique_id=layer_id).first()
             or GeoLayer.query.filter(GeoLayer.name == layer_id).first())
    custom_opts = {}
    file_path = None
    layer_type = layer_id

    if layer:
        layer_type = layer.type
        file_path = dict_inputs.get(layer.type, {}).get('file_path')
        custom_opts = _json_dict(layer.options)
    else:
        if layer_id in dict_inputs:
            file_path = dict_inputs[layer_id].get('file_path')
        existing = (GeoLayer.query.filter_by(type=layer_id, is_activated=True).first()
                    or GeoLayer.query.filter_by(type=layer_id).first())
        if existing:
            custom_opts = _json_dict(existing.options)

    if not file_path:
        raise GeoLookupError('provider_not_found', 'Provider not found', 404)

    mod, _status = load_module_from_file(file_path, 'inputs')
    if not mod or not hasattr(mod, 'InputModule'):
        raise GeoLookupError('invalid_provider', 'Invalid Provider Module', 500)

    layer_def = dict_inputs.get(layer_type, {})
    key_field = layer_def.get('key_field')
    if key_field and not custom_opts.get(key_field):
        settings = GeoSetting.query.first()
        global_keys = _json_dict(settings.keys) if settings else {}
        global_val = global_keys.get(layer_def.get('global_key_field', key_field))
        if global_val:
            custom_opts[key_field] = global_val

    holder = type('obj', (object,), {'unique_id': layer_id, 'name': 'SearchProxy'})()
    inst = mod.InputModule(MockInputDev(holder))
    inst.custom_options = custom_opts
    inst.get_custom_option = lambda opt, default=None: inst.custom_options.get(opt, default)

    if not hasattr(inst, 'search'):
        raise GeoLookupError('not_supported', 'Search not supported by this provider', 400)
    return inst, layer_type


def _json_dict(raw):
    if isinstance(raw, dict):
        return dict(raw)
    try:
        val = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def chosen_provider_id():
    """사용자가 지도 설정에서 고른 검색 공급자 id. 없으면 기본."""
    from aot.databases.models import GeoSetting
    settings = GeoSetting.query.first()
    if settings and settings.providers:
        picked = _json_dict(settings.providers).get('search_provider')
        if picked:
            return picked
    return DEFAULT_PROVIDER


def raw_search(query, provider=None, search_type='address', **kwargs):
    """공급자의 `search()` 결과를 그대로 돌려준다(목록 또는 `{'error': …}`). 시작 못 하면 GeoLookupError.

    지도 검색창처럼 공급자의 원 결과(meta 등)가 필요한 호출처용이다. 새 호출처는 `find_location` 을 쓴다.
    """
    inst, _type = _load_provider(provider or chosen_provider_id())
    return inst.search(query, search_type=search_type, **kwargs)


def _providers_with(attr):
    """등록된 GIS 입력 중 그 모듈이 `attr` 에 'address' 를 선언한 것 — `[{id, type, name, activated}]`."""
    from aot.databases.models import GeoLayer
    from aot.utils.inputs import parse_input_information
    from aot.utils.modules import load_module_from_file

    dict_inputs = parse_input_information()
    out, seen_caps = [], {}
    for layer in GeoLayer.query.order_by(GeoLayer.id).all():
        if layer.type not in seen_caps:
            caps = ()
            path = dict_inputs.get(layer.type, {}).get('file_path')
            if path:
                try:
                    mod, _s = load_module_from_file(path, 'inputs')
                    caps = tuple(getattr(getattr(mod, 'InputModule', None), attr, ()) or ())
                except Exception:
                    caps = ()
            seen_caps[layer.type] = caps
        if CAP_ADDRESS in seen_caps[layer.type]:
            out.append({'id': layer.unique_id, 'type': layer.type, 'name': layer.name,
                        'activated': bool(layer.is_activated)})
    return out


def search_providers():
    """주소 검색(주소→좌표)을 할 수 있는 등록된 GIS 입력. 안내·오류 응답용."""
    return _providers_with(ATTR_SEARCH)


def reverse_providers():
    """좌표→주소를 할 수 있는 등록된 GIS 입력. 안내·오류 응답용."""
    return _providers_with(ATTR_REVERSE)


def _finite_coord(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    return lat, lng


def find_location(query, provider=None, limit=DEFAULT_RESULTS, search_type='address'):
    """주소·장소 이름 → 좌표 후보. MCP 와 안쪽 호출이 쓰는 문.

    Returns:
        ok:        {'status': 'ok', 'provider': {id, type}, 'query', 'count', 'results': [{name, lat, lng, address, provider}]}
        못 찾음:   {'status': 'no_match', 'provider', 'query', 'results': []}
        실패:      {'status': 'error', 'code': str, 'error': str, 'providers': [...]}
    """
    query = (query or '').strip()
    if not query:
        return {'status': 'error', 'code': 'missing_query', 'error': 'query is required (an address or place name).'}
    try:
        limit = max(1, min(int(limit), MAX_RESULTS))
    except (TypeError, ValueError):
        limit = DEFAULT_RESULTS

    layer_id = provider or chosen_provider_id()
    try:
        inst, layer_type = _load_provider(layer_id)
        raw = inst.search(query, search_type=search_type, limit=limit)
    except GeoLookupError as e:
        return _fail(e.code, e.message)
    except Exception as e:
        logger.warning('[geo_lookup] %s search failed: %s', layer_id, e)
        return _fail('failed', f'{type(e).__name__}: {e}')

    prov = {'id': layer_id, 'type': layer_type}
    if raw is None:
        return _fail('not_supported', 'This provider does not support search.', prov)
    if isinstance(raw, dict):
        msg = raw.get('error') or 'Search failed.'
        code = str(raw.get('code') or '') or (
            'no_key' if 'key' in str(msg).lower() and 'missing' in str(msg).lower() else 'failed')
        return _fail(code, str(msg), prov)

    results, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        coord = _finite_coord(item.get('lat'), item.get('lng'))
        if coord is None or coord in seen:
            continue
        seen.add(coord)
        address = str(item.get('address') or '').strip()
        results.append({
            'name': str(item.get('name') or address or query),
            'lat': coord[0], 'lng': coord[1],
            'address': address,
            'provider': layer_type,
        })
        if len(results) >= limit:
            break

    if not results:
        out = {'status': 'no_match', 'provider': prov, 'query': query, 'results': []}
        try:
            out['providers'] = search_providers()
        except Exception:
            pass
        return out
    return {'status': 'ok', 'provider': prov, 'query': query, 'count': len(results), 'results': results}


def _fail(code, message, prov=None, listing=None):
    out = {'status': 'error', 'code': code, 'error': message}
    if prov:
        out['provider'] = prov
    try:
        out['providers'] = (listing or search_providers)()
    except Exception:
        pass
    return out


def _reverse_provider_id():
    """역방향 공급자 — 지도 설정의 검색 공급자가 역방향을 하면 그것, 아니면 등록된 첫 켜진 역방향 입력, 아니면 기본."""
    from aot.databases.models import GeoSetting
    settings = GeoSetting.query.first()
    picked = _json_dict(settings.providers).get('search_provider') if settings and settings.providers else None
    candidates = reverse_providers()
    if picked and any(c['id'] == picked or c['type'] == picked for c in candidates):
        return picked
    for c in candidates:
        if c['activated']:
            return c['id']
    return DEFAULT_PROVIDER


def find_address(lat, lng, provider=None):
    """좌표 → 주소. MCP(`get_address`)와 안쪽 호출이 쓰는 문.

    Returns:
        ok:   {'status': 'ok', 'provider': {id, type}, 'lat', 'lng', 'address', 'type'}
        실패: {'status': 'error', 'code': str, 'error': str, 'providers': [...]}  (no_key · failed · not_supported · …)
    """
    coord = _finite_coord(lat, lng)
    if coord is None:
        return _fail('bad_coordinates', 'lat/lng must be valid WGS84 coordinates.', listing=lambda: reverse_providers())
    lat, lng = coord
    layer_id = provider or _reverse_provider_id()
    try:
        inst, layer_type = _load_provider(layer_id)
        raw = inst.reverse(lat, lng)
    except GeoLookupError as e:
        return _fail(e.code, e.message, listing=lambda: reverse_providers())
    except Exception as e:
        logger.warning('[geo_lookup] %s reverse failed: %s', layer_id, e)
        return _fail('failed', f'{type(e).__name__}: {e}', listing=lambda: reverse_providers())

    prov = {'id': layer_id, 'type': layer_type}
    if raw is None:
        return _fail('not_supported', 'This provider does not support reverse geocoding.', prov, lambda: reverse_providers())
    if not isinstance(raw, dict) or raw.get('error') or not str(raw.get('address') or '').strip():
        msg = (raw.get('error') if isinstance(raw, dict) else None) or 'No address found.'
        code = (raw.get('code') if isinstance(raw, dict) else None) or 'failed'
        return _fail(str(code), str(msg), prov, lambda: reverse_providers())
    return {'status': 'ok', 'provider': prov, 'lat': lat, 'lng': lng,
            'address': str(raw['address']).strip(), 'type': raw.get('type')}
