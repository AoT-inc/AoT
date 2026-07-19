# coding=utf-8
"""Map dependency model."""
from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db

class MapDependency(CRUDMixin, db.Model):
    """
    Represents a relationship between a GeoShape and another entity on the map.

    MapDependency links a source GeoShape to a target entity (overlay, sensor,
    output, or function) with a relation type of 'contains' or 'linked_to'.
    Used for Contains or Linked To logic in the Geo domain.

    @phase active
    """
    __tablename__ = "map_dependency"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    geo_id = db.Column(db.String(64), nullable=False, index=True)
    
    # excessive join optimization
    source_id = db.Column(db.Integer, db.ForeignKey('geo_shape.id'), nullable=False, index=True)
    
    # Target entity ID (could be overlay.id, device.id, etc.)
    target_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Target type: 'overlay', 'sensor', 'output', 'function'
    target_type = db.Column(db.String(32), nullable=False)
    
    # Relation type: 'contains', 'linked_to'
    relation_type = db.Column(db.String(32), nullable=False, default='linked_to')

    def __repr__(self):
        return "<MapDependency({0} -> {1}:{2})>".format(self.source_id, self.target_type, self.target_id)
