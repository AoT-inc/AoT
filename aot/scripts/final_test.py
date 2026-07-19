import sys
sys.path.append('.')
from aot.start_flask_ui import app
from aot.ai.services.ai_context_service import AIContextService
import json

with app.app_context():
    dash_ctx = AIContextService.get_dashboard_context(None)
    for dash in dash_ctx:
        for w in dash["widgets"]:
            if w["type"] == 'AoT_map':
                print(f"Widget {w['widget_id']} wms_readings:")
                print(json.dumps(w.get('wms_readings', []), indent=2, ensure_ascii=False))
