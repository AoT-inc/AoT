# coding=utf-8
"""GeoLayer 하나 → 그 입력 모듈 인스턴스 (아키텍처 4c-1, `docs/design/space-domain-package.md`).

지도 레이어 라우트(`aot.aot_flask.routes_geo_layer`)와 `utils_geo` 에 있던 것을 그대로
옮겼다. 데몬의 예보 폴백(`weather_state` → `forecast_series._fallback_cells`)도 이
조립을 쓰는데, 라우트 파일을 import 하면 웹 계층 전체가 딸려 온다. 라우트와
`utils_geo` 는 옛 이름을 같은 객체로 다시 내보낸다.

이 파일은 입력 모듈이 아니다(`INPUT_INFORMATION` 이 없다). 입력 모듈 스캔
(`parse_input_information`)이 이 폴더의 파일을 하나씩 실행하므로, 모델 import 는
함수 안에 둔다.
"""
import json
import os

from aot.utils.inputs import parse_input_information


# Helper wrapper for instantiating Inputs without full DB object
class MockInputDev:
    def __init__(self, layer):
        self.unique_id = layer.unique_id
        self.name = layer.name
        self.custom_options = '{}' # Initialize empty, will override
        self.log_level_debug = False # Required by AbstractInput.setup_logger


#: 레이어 종류 → (파일 지문, 입력 정의). `parse_input_information()` 은 부를 때마다 입력 모듈 200여 개를 다시 실행해 한 번에
#: 0.1초 남짓 걸린다 — 시간 칸마다 인스턴스를 만드는 예보 조회에서 수 초가 됐다. 그 종류의 파일이 그대로면 정의도 그대로다.
_GIS_LAYER_DEFS = {}


def _gis_layer_def(layer_type):
    """레이어 종류의 입력 정의(복사본). 파일이 바뀌었거나 처음이면 `parse_input_information()` 으로 다시 읽는다.
    못 찾은 종류는 캐시하지 않는다(새로 올린 커스텀 모듈이 바로 보이게)."""
    import copy
    hit = _GIS_LAYER_DEFS.get(layer_type)
    if hit is not None:
        try:
            st = os.stat(hit[0])
            if (st.st_mtime_ns, st.st_size) == hit[1]:
                return copy.deepcopy(hit[2])
        except OSError:
            pass
    layer_def = parse_input_information().get(layer_type, {})
    path = layer_def.get('file_path')
    if path:
        try:
            st = os.stat(path)
            _GIS_LAYER_DEFS[layer_type] = (path, (st.st_mtime_ns, st.st_size), copy.deepcopy(layer_def))
        except OSError:
            pass
    return layer_def


def _load_gis_layer_instance(unique_id):
    """GeoLayer 하나를 그 입력 모듈 인스턴스로 만든다. 못 찾으면 None.

    api/geo.py 의 검색 프록시가 하던 것과 같은 조립(옵션 기본값 채우기 →
    전역 키 폴백 → `get_custom_option` 대체)을 한 곳에 모은 것이다.
    """
    import re as _re
    from aot.utils.modules import load_module_cached
    from aot.databases.models import GeoLayer, GeoSetting

    channel_id = None
    layer = GeoLayer.query.filter_by(unique_id=unique_id).first()
    if not layer:
        # WMS 프록시와 같은 관례: 채널마다 레이어를 나눠 그릴 때 `<uid>_<채널>`.
        m = _re.match(r'^(.+)_(\d+)$', unique_id)
        if m:
            layer = GeoLayer.query.filter_by(unique_id=m.group(1)).first()
            if layer:
                channel_id = int(m.group(2))
    if not layer:
        return None

    layer_def = _gis_layer_def(layer.type)
    if not layer_def.get('file_path'):
        return None

    # 같은 파일이면 같은 모듈 객체 — 모듈 전역 캐시(예보 10분·토큰 …)가 인스턴스를 넘어 살아남는다.
    mod, _status = load_module_cached(layer_def['file_path'], 'inputs')
    if not mod or not hasattr(mod, 'InputModule'):
        return None

    try:
        opts = json.loads(layer.options) if layer.options else {}
    except Exception:
        opts = {}

    required_ids = []
    for opt_def in layer_def.get('custom_options', []):
        opt_id = opt_def.get('id')
        if not opt_id:
            continue
        if opt_id not in opts and 'default' in opt_def:
            opts[opt_id] = opt_def['default']
        if opt_def.get('required'):
            required_ids.append(opt_id)

    # 키 필드는 전역 키 저장소를 따른다(다른 GIS 입력과 같은 규칙).
    key_field = layer_def.get('key_field')
    if key_field and not opts.get(key_field):
        settings_row = GeoSetting.query.first()
        if settings_row and settings_row.keys:
            try:
                global_keys = json.loads(settings_row.keys)
            except Exception:
                global_keys = {}
            global_val = global_keys.get(layer_def.get('global_key_field', key_field))
            if global_val:
                opts[key_field] = global_val

    # 전역 저장소에는 키 필드 자리가 **하나뿐**이라 두 값짜리 자격증명
    # (예: Sentinel Hub 의 client_id + client_secret)은 절반만 채워진다.
    # 같은 종류의 다른 레이어에 이미 적어 둔 필수값을 물려받게 한다 —
    # 지수마다 레이어를 나눠 두는 것이 보통인데, 그때마다 같은 비밀값을
    # 다시 적게 하지 않기 위해서다.
    missing = [opt_id for opt_id in required_ids if not opts.get(opt_id)]
    if missing:
        for sibling in GeoLayer.query.filter_by(type=layer.type).all():
            if not missing:
                break
            if sibling.unique_id == layer.unique_id or not sibling.options:
                continue
            try:
                sib_opts = json.loads(sibling.options)
            except Exception:
                continue
            for opt_id in list(missing):
                if sib_opts.get(opt_id):
                    opts[opt_id] = sib_opts[opt_id]
                    missing.remove(opt_id)

    if channel_id is not None:
        opts['active_channels'] = [channel_id]

    inst = mod.InputModule(MockInputDev(layer))
    inst.custom_options = opts
    inst.get_custom_option = lambda opt, default=None: opts.get(opt, default)
    return inst
