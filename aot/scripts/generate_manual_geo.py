# -*- coding: utf-8 -*-
"""Generate markdown file of Geo (Map Layer) information to be inserted into the manual."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../..")))

from collections import OrderedDict
from aot.config import INSTALL_DIRECTORY
from aot.scripts.generate_doc_output import generate_controller_doc
from aot.utils.inputs import parse_input_information

save_path = os.path.join(INSTALL_DIRECTORY, "docs/Supported-Geo-Layers.md")

geo_info = OrderedDict()
aot_info = OrderedDict()

if __name__ == "__main__":
    # Load all inputs, including GIS
    all_inputs = parse_input_information(exclude_custom=True)
    
    # Filter for only Geo/GIS inputs
    # Criteria: has 'layer_type' or is in inputs_gis directory (path check difficult here, rely on metadata)
    for input_id, input_data in all_inputs.items():
        # Check standard GIS metadata fields
        is_geo = False
        if 'layer_type' in input_data and input_data['layer_type']:
            is_geo = True
        elif 'default_url' in input_data and input_data['default_url']:
            is_geo = True
            
        if not is_geo:
            continue

        name_str = ""
        if 'input_manufacturer' in input_data and input_data['input_manufacturer']:
            name_str += f"{input_data['input_manufacturer']}"
        if 'input_name' in input_data and input_data['input_name']:
            name_str += f": {input_data['input_name']}"

        if ('input_manufacturer' in input_data and
                input_data['input_manufacturer'] in ['Linux', 'AoT', 'Raspberry Pi', 'System']):
            if name_str in aot_info and 'dependencies_module' in aot_info[name_str]:
                aot_info[name_str]['dependencies_module'].append(input_data['dependencies_module'])
            else:
                aot_info[name_str] = input_data
                if 'dependencies_module' in input_data:
                    aot_info[name_str]['dependencies_module'] = [input_data['dependencies_module']]
        else:
            if name_str in geo_info and 'dependencies_module' in geo_info[name_str]:
                geo_info[name_str]['dependencies_module'].append(input_data['dependencies_module'])
            else:
                geo_info[name_str] = input_data
                if 'dependencies_module' in input_data:
                    geo_info[name_str]['dependencies_module'] = [input_data['dependencies_module']]

    aot_info = dict(OrderedDict(sorted(aot_info.items(), key=lambda t: t[0])))
    geo_info = dict(OrderedDict(sorted(geo_info.items(), key=lambda t: t[0])))

    list_inputs = [
        (aot_info, "Built-In Map Layers (System)"),
        (geo_info, "Built-In Map Layers (Providers)")
    ]

    with open(save_path, 'w') as out_file:
        for each_list in list_inputs:
            if not each_list[0]:
                continue
                
            out_file.write(f"## {each_list[1]}\n\n")

            for name_key, each_data in each_list[0].items():
                out_file.write(f"### {name_key}\n\n")

                if 'layer_type' in each_data:
                    out_file.write(f"- Layer Type: {each_data['layer_type']}\n")
                
                if 'layer_role' in each_data:
                     # e.g., Base, Overlay, Hybrid
                    out_file.write(f"- Default Role: {each_data['layer_role'].title()}\n")

                if 'attribution' in each_data and each_data['attribution']:
                    out_file.write(f"- Attribution: {each_data['attribution']}\n")

                if 'default_url' in each_data and each_data['default_url']:
                    out_file.write(f"- Service URL: `{each_data['default_url']}`\n")

                if 'time_enabled' in each_data and each_data['time_enabled']:
                    out_file.write(f"- Time Enabled: Yes\n")

                if 'input_manufacturer' in each_data and each_data['input_manufacturer']:
                    out_file.write(f"- Manufacturer: {each_data['input_manufacturer']}\n")
                
                if 'input_library' in each_data and each_data['input_library']:
                    out_file.write(f"- Libraries: {each_data['input_library']}\n")

                # Use shared generator for Dependencies, Options table, etc.
                generate_controller_doc(out_file, each_data)

                # Check for Search Capability
                # Note: We need to check if the module has a 'search' method
                if 'file_path' in each_data:
                    from aot.utils.modules import load_module_from_file
                    mod, status = load_module_from_file(each_data['file_path'], 'inputs')
                    if mod and hasattr(mod, 'InputModule') and hasattr(mod.InputModule, 'search'):
                        out_file.write("- GIS Search: Supported (Address/Place)\n")
                        if hasattr(mod.InputModule, 'search_capabilities'):
                            caps = ", ".join(mod.InputModule.search_capabilities)
                            out_file.write(f"  - Capabilities: {caps}\n")
                        out_file.write("\n")

        # Add GIS Proxy & Search Overview
        out_file.write("## GIS Proxy & Search Capabilities\n\n")
        out_file.write("AoT provides built-in proxy and search support for common GIS services to handle CORS and provide unified search.\n\n")
        
        proxy_info = [
            ("RainViewer", "Weather Radar Tiles & Metadata", "/api/geo/proxy/rainviewer/meta"),
            ("ISRIC SoilGrids", "Soil property data lookups", "/api/geo/proxy/isric"),
            ("OpenWeatherMap", "Current weather data", "/api/geo/proxy/openweather"),
            ("Open-Meteo", "Weather forecast and historical data", "/api/geo/proxy/openmeteo")
        ]
        
        out_file.write("| Service | Description | Proxy Endpoint |\n")
        out_file.write("| :--- | :--- | :--- |\n")
        for name, desc, endpoint in proxy_info:
            out_file.write(f"| {name} | {desc} | `{endpoint}` |\n")
        out_file.write("\n")
