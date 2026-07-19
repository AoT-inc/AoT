import sys
sys.path.append('.')
from aot.start_flask_ui import app
from aot.ai.services.ai_context_service import AIContextService
from aot.databases.models import Misc, db
import json

with app.app_context():
    # Temporary mock Misc map location to a farm area in Korea (e.g. near Icheon: 37.2, 127.5)
    misc_settings = Misc.query.first()
    old_lat, old_lng = misc_settings.map_latitude, misc_settings.map_longitude
    misc_settings.map_latitude = 37.2
    misc_settings.map_longitude = 127.5
    db.session.commit()
    
    dash_ctx = AIContextService.get_dashboard_context(None)
    for dash in dash_ctx:
        for w in dash["widgets"]:
            if w["type"] == 'AoT_map':
                print(f"Widget {w['widget_id']} active_layers:")
                print(w.get('config_options', {}).get('active_layers'))
                print(f"Widget {w['widget_id']} wms_readings:")
                print(json.dumps(w.get('wms_readings', []), indent=2, ensure_ascii=False))

    # Restore
    misc_settings.map_latitude = old_lat
    misc_settings.map_longitude = old_lng
    db.session.commit()
