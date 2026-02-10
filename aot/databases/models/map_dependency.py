# coding=utf-8
"""Map dependency model."""
from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db

class MapDependency(CRUDMixin, db.Model):
    """
    Represents a relationship between a map overlay and another entity
    (another overlay, sensor, output, or function).
    Used for 'Contains' or 'Linked To' logic.
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
