# coding=utf-8
"""
Geo Information Service Routes.
Unified Geo System.

주제별 라우트는 형제 모듈(routes_geo_layer/shape/summary/schedule/device/map/facility 등)에
있다. 이 파일은 공유 blueprint 선언과 전역 훅(after_request·context_processor)만 갖는다.
"""
from flask import Blueprint, request
from aot.aot_flask.routes_static import inject_variables
from aot.aot_flask.utils import utils_geo

blueprint = Blueprint('routes_geo', __name__)




@blueprint.after_request
def add_cors_headers(response):
    """Add CORS headers to API responses so cross-origin callers can read them."""
    if request.path.startswith('/api/'):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-API-KEY'
    return response

@blueprint.context_processor
def inject_dictionary():
    context = inject_variables()
    
    # Inject Unified Geo Config
    if 'geo_config' not in context:
        context['geo_config'] = utils_geo.get_geo_config()
        # Alias for backward compatibility if needed, but we aim for unified 'geo_config'
        # context['gis_global_config'] = context['geo_config'] 
        
    return context

# 주제별 형제 모듈 — 같은 blueprint 를 공유하며 데코레이트한다.
# 서로 참조하는 모듈은 참조되는 쪽을 먼저 import 한다.
from aot.aot_flask import routes_geo_layer
from aot.aot_flask import routes_geo_shape
from aot.aot_flask import routes_geo_summary
from aot.aot_flask import routes_geo_schedule
from aot.aot_flask import routes_geo_device
from aot.aot_flask import routes_geo_map
from aot.aot_flask import routes_geo_facility
from aot.aot_flask import routes_geo_commissioning
from aot.aot_flask import routes_geo_iec
from aot.aot_flask import routes_geo_plot
from aot.aot_flask import routes_geo_journal
from aot.aot_flask import routes_geo_device_split   # routes_geo_plot 뒤여야 함
