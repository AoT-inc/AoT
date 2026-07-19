"""Print active layers, fallback center, and WMS readings for AoT_map widgets."""
import sys
sys.path.append('.')
from aot.start_flask_ui import app
from aot.ai.services.ai_context_service import AIContextService
import json

with app.app_context():
    dash_ctx = AIContextService.get_dashboard_context(None)
    for dash in dash_ctx:
        for w in dash["widgets"]:
            if w.get("type") == 'AoT_map':
                print(f"Widget {w.get('widget_id')}")
                opts = w.get('config_options', {})
                print(f"  active_layers: {opts.get('active_layers')}")
                print(f"  fallback_center: {opts.get('fallback_center')}")
                print(f"  wms_readings: {json.dumps(w.get('wms_readings', []), ensure_ascii=False)}")
