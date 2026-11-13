# coding=utf-8
"""지도 위젯 AI 컨텍스트용 GIS 판독 (아키텍처 7c).

예전에는 `aot/inputs/satellite_analysis.py` 에 있었으나, 앱 컨텍스트(flask)를 여는
AI 전용 함수라 데몬 계층(입력 모듈)에서 AI 서비스 층으로 옮겼다. 동작은 그대로다.
발견된 모듈 목록(`ANALYSIS_MODULES`)은 입력 모듈 쪽이 계속 소유한다.
"""
import json
import logging

logger = logging.getLogger(__name__)


def discover_and_query_for_ai(active_layers, lat, lng):
    """
    Dynamic AI context enrichment for map widgets.
    Parallelized in Phase 17 to prevent 30s+ blocks.
    """
    import importlib
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from flask import current_app
    from aot.inputs.satellite_analysis import ANALYSIS_MODULES

    if not active_layers or lat is None or lng is None:
        return []

    # v14.1: Capture app object in main thread — current_app is not available in worker threads
    app = current_app._get_current_object()

    results = []

    def fetch_module_reading(module_name, display_name):
        # Filter layers that match this module
        matched_layer = None
        display_lower = display_name.lower()
        for layer_name in active_layers:
            if display_lower in str(layer_name).lower():
                matched_layer = layer_name
                break

        if not matched_layer:
            return None

        try:
            # v14.1: Use captured app object instead of current_app (thread-safe)
            with app.app_context():
                with app.test_request_context(): # For babel _()
                    mod = importlib.import_module(f"aot.inputs_gis.{module_name}")
                    if not hasattr(mod, 'InputModule'):
                        return None
                    
                    instance = mod.InputModule(None, testing=True)
                    # Inject keys
                    try:
                        from aot.databases.models import GeoSetting
                        settings = GeoSetting.query.first()
                        if settings and settings.keys:
                            instance.global_api_keys = json.loads(settings.keys) or {}
                    except: pass

                    readings = instance.get_ai_reading(lat, lng)
                    if not readings:
                        return None
                    
                    batch = []
                    for r in readings:
                        batch.append({
                            "layer": matched_layer,
                            "property_detail": r.get('label', ''),
                            "value": r.get('value'),
                            "unit": r.get('unit', '')
                        })
                    return batch
        except Exception as e:
            logger.warning(f"[AI Enrichment] Thread failed for module {module_name}: {e}")
            return None

    # Parallel Execution (Max 5 GIS sources, 10s timeout per module)
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_mod = {executor.submit(fetch_module_reading, m[0], m[1]): m[0] for m in ANALYSIS_MODULES}
        for future in as_completed(future_to_mod):
            try:
                data = future.result(timeout=10) # 10 second limit per module
                if data:
                    results.extend(data)
            except Exception as e:
                mod_name = future_to_mod[future]
                logger.error(f"[AI Enrichment] Module {mod_name} timed out or failed: {e}")
    
    return results
