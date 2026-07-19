import sys
import os
# Add parent dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from aot.aot_flask.extensions import db
from aot.aot_flask.app import create_app
from aot.databases.models.map_overlay import MapOverlay

app = create_app()

with app.app_context():
    try:
        print("Inserting test overlay...")
        test_ov = MapOverlay(
            map_id='test_map_uuid',
            type='feature',
            level_id=1,
            channel_id='test_channel',
            feature={"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0,0]}}
        )
        db.session.add(test_ov)
        db.session.commit()
        print("Inserted. Querying...")
        
        ov = MapOverlay.query.filter_by(map_id='test_map_uuid').first()
        print(f"ID: {ov.id}, Level: {ov.level_id}, Channel: {ov.channel_id}")
        
        # Clean up
        db.session.delete(ov)
        db.session.commit()
        print("Success!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

