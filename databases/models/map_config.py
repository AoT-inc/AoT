# coding=utf-8
"""Map configuration model (supports multiple maps)."""
from datetime import datetime

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db
import json


class MapConfig(CRUDMixin, db.Model):
    """
    Represents a saved map configuration (center/zoom/provider/satellite, etc.).

    Access control: edits should be restricted to roles with edit_settings
    (e.g., Admin/Editor). Reads can be open to authenticated users.
    """
    __tablename__ = "map_config"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.String(128), nullable=False, default='New Map')

    # Center/zoom
    latitude = db.Column(db.Float, default=None)
    longitude = db.Column(db.Float, default=None)
    zoom = db.Column(db.Integer, default=12)

    # Provider details
    provider = db.Column(db.String(32), default='osm')  # osm, mapbox, vworld, google, etc.
    style_url = db.Column(db.Text, default='')
    api_key = db.Column(db.Text, default='')  # optional
    use_satellite = db.Column(db.Boolean, default=False)

    # Interaction
    map_locked = db.Column(db.Boolean, default=False)  # pan/zoom lock

    # Audit
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.String(36), default='')  # user unique_id for traceability

    def __repr__(self):
        return "<MapConfig(id={0}, name='{1}')>".format(self.id, self.name)


class MapGlobalSettings(CRUDMixin, db.Model):
    """
    Stores global geo/map configuration (provider selections, API keys, default zoom).
    """
    __tablename__ = "map_global_settings"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    providers = db.Column(db.Text, default='{}')
    keys = db.Column(db.Text, default='{}')
    zoom = db.Column(db.Integer, default=12)

    def _loads(self, value):
        if not value:
            return {}
        try:
            return json.loads(value)
        except Exception:
            return {}

    def state_dict(self):
        return {
            'providers': self._loads(self.providers),
            'keys': self._loads(self.keys),
            'zoom': self.zoom
        }
