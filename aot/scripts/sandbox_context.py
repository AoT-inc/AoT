"""Sandbox script to test map enrichment and external API integration."""
import sys
sys.path.append('.')
from aot.start_flask_ui import app
from aot.databases.models import Widget, Misc
import json
import requests

with app.app_context():
    w = Widget.query.filter_by(graph_type='AoT_map').first()
    opts = json.loads(w.custom_options)
    active_layers = opts.get('active_layers', [])
    print("Testing map enrichment standalone...")
    center = opts.get('fallback_center')
    print('center:', center)
    
    if not center or not isinstance(center, list) or len(center) != 2:
        misc_settings = Misc.query.first()
        if misc_settings and misc_settings.map_latitude and misc_settings.map_longitude:
            lat, lng = misc_settings.map_latitude, misc_settings.map_longitude
        else:
            lat, lng = 37.5665, 126.9780 
    else:
        lat, lng = center[0], center[1]
    
    print(f"Coordinates: lat={lat}, lng={lng}")

    active_isric_keys = []
    for layer_name in active_layers:
        ln_lower = str(layer_name).lower()
        if 'soilgrids' in ln_lower:
            if 'ph' in ln_lower: active_isric_keys.append('ph')
            
    print("active_isric_keys:", active_isric_keys)
    
    # NASA
    active_nasa_keys = []
    for layer_name in active_layers:
        ln_lower = str(layer_name).lower()
        if 'nasa gibs' in ln_lower or 'nasa' in ln_lower:
            if 'smap' in ln_lower or '수분' in ln_lower or 'moisture' in ln_lower:
                active_nasa_keys.append('smap')
            if 'temp' in ln_lower or '온도' in ln_lower:
                active_nasa_keys.append('temp')
                
    print("active_nasa_keys:", active_nasa_keys)
    
    if active_isric_keys:
        isric_map = {
            'ph': {'prop': 'phh2o', 'name': 'Soil pH (0-5cm)', 'unit': 'pH', 'factor': 10.0}
        }
        props_to_query = [isric_map[k]['prop'] for k in set(active_isric_keys)]
        params = [('lon', lng), ('lat', lat), ('depth', '0-5cm'), ('value', 'mean')]
        for p in props_to_query:
            params.append(('property', p))
            
        print("ISRIC Params:", params)
        res = requests.get('https://rest.isric.org/soilgrids/v2.0/properties/query', params=params, timeout=5)
        print("ISRIC Status:", res.status_code)
        if res.status_code == 200:
            data = res.json()
            if 'properties' in data and 'layers' in data['properties']:
                for layer in data['properties']['layers']:
                    prop_name = layer.get('name')
                    print("Found ISRIC Layer:", prop_name)
                    config = next((v for k, v in isric_map.items() if v['prop'] == prop_name), None)
                    print("Config:", config)
                    if config:
                        mean_val = next((d.get('mean') for d in layer.get('depths', []) if d.get('label') == '0-5cm'), None)
                        print("Mean val:", mean_val)

    if active_nasa_keys:
        nasa_map = {
            'smap': {'param': 'soil_moisture_0_to_1cm', 'name': 'Soil Moisture (Root Zone)', 'unit': 'm³/m³'},
            'temp': {'param': 'temperature_2m', 'name': 'Land Surface Temp (Day)', 'unit': '°C'}
        }
        params_to_query = ",".join([nasa_map[k]['param'] for k in set(active_nasa_keys)])
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current={params_to_query}"
        print("NASA URL:", url)
        res = requests.get(url, timeout=5)
        print("NASA Status:", res.status_code)
        if res.status_code == 200:
            data = res.json()
            print("NASA Current:", data.get('current'))
