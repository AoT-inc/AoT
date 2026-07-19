"""Append map-data-enrichment instruction to the AI global system prompt."""
from aot.start_flask_ui import app
from aot.databases.models import AIGlobalSettings, db

with app.app_context():
    settings = AIGlobalSettings.query.first()
    if settings and settings.system_prompt_template:
        if "wms_readings" not in settings.system_prompt_template:
            # Append the new instruction just before instruction 9 if possible, or at the end
            lines = settings.system_prompt_template.split('\n')
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if line.startswith("8.") and "Dashboard & Viewport Awareness" in line:
                    new_lines.append("   - **Map Data Enrichment**: If the user asks about map layers, soil properties (pH, clay, etc.), satellite data, or environmental data that isn't measured by a local sensor, YOU MUST check `dashboards` -> `widgets` -> `wms_readings`! The backend automatically extracts live measurements (like SoilGrids pH, NASA temperature) for active map layers.")
            
            settings.system_prompt_template = '\n'.join(new_lines)
            db.session.commit()
            print("DB Prompt updated successfully.")
        else:
            print("Instruction already exists in DB.")
    else:
        print("No custom prompt in DB. Default will be used.")
