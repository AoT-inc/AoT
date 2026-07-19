"""Verify WMS layer config and query ISRIC soil data for active map widgets."""
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
                print(f"Widget {w['widget_id']} active_layers:")
                print(w.get('config_options', {}).get('active_layers'))
                center = w.get('config_options', {}).get('fallback_center')
                print(f"center: {center}")
                
                # Check global settings
                from aot.databases.models import Misc
                misc = Misc.query.first()
                if misc:
                    print(f"Global mapping: lat={misc.map_latitude}, lng={misc.map_longitude}")
                
                # We need to know exactly why pH is missing
                # Let's query ISRIC for this exact lat/lng
                if not center or len(center) != 2:
                    lat, lng = misc.map_latitude, misc.map_longitude
                else:
                    lat, lng = center[0], center[1]
                
                import requests
                params = [('lon', lng), ('lat', lat), ('depth', '0-5cm'), ('value', 'mean'), ('property', 'phh2o')]
                res = requests.get('https://rest.isric.org/soilgrids/v2.0/properties/query', params=params, timeout=5)
                print(f"ISRIC Response: {res.status_code}")
                if res.status_code == 200:
                    data = res.json()
                    print(json.dumps(data, indent=2)[:500]) # Print first 500 chars

