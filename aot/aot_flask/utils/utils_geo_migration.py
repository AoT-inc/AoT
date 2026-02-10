from sqlalchemy import inspect, text
import logging

logger = logging.getLogger(__name__)

_GEO_SETTING_COLUMN_CHECKED = False

def ensure_geo_setting_columns():
    """
    Ensures that critical columns exist in the GeoSetting table.
    This acts as a runtime migration utility.
    """
    global _GEO_SETTING_COLUMN_CHECKED
    if _GEO_SETTING_COLUMN_CHECKED:
        return
    
    try:
        from aot.aot_flask.extensions import db
        engine = db.engine
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('geo_setting')]
        
        # 1. theme_config
        if 'theme_config' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE geo_setting ADD COLUMN theme_config TEXT DEFAULT '{}'"))
                conn.execute(text("UPDATE geo_setting SET theme_config='{}' WHERE theme_config IS NULL"))
                
        # 2. max_polygons_device (Older schema check)
        if 'max_polygons_device' not in columns:
            # Assume other limits might be missing too
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE geo_setting ADD COLUMN max_polygons_device INTEGER DEFAULT 1000"))
                conn.execute(text("ALTER TABLE geo_setting ADD COLUMN max_polygons_site INTEGER DEFAULT 1000"))
                conn.execute(text("ALTER TABLE geo_setting ADD COLUMN max_polygons_zone INTEGER DEFAULT 1000"))

        _GEO_SETTING_COLUMN_CHECKED = True
    except Exception as e:
        logger.error(f"Failed to ensure geo_setting columns: {e}")
