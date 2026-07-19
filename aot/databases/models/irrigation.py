from datetime import datetime
from sqlalchemy.dialects.mysql import LONGTEXT
from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db

class IrrigationDesign(CRUDMixin, db.Model):
    """
    Stores a sprinkler irrigation system design for a facility.

    IrrigationDesign captures boundary geometry, row layouts, and sprinkler placements
    as JSON, along with an operational status (idle, running, completed, error) and
    total water volume tracking. Can be linked to a Function for execution.

    @phase active
    """
    __tablename__ = "irrigation_design"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    name = db.Column(db.String(128), nullable=False, default='New Design')
    description = db.Column(db.Text, default='')
    
    # Core Data (Stored as Text/JSON) - Use LONGTEXT for MySQL to avoid 64KB limit
    boundary_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    rows_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}') # Generated Rows
    sprinklers_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}') # Generated Sprinklers
    
    # Configuration State (Spacing, Angle, Offset, etc.)
    config_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    
    # Operational Tracking
    status = db.Column(db.String(32), default='idle') # idle, running, completed, error
    last_run_at = db.Column(db.DateTime, default=None)
    total_volume_applied = db.Column(db.Float, default=0.0)
    
    # Association with core logic (Optional links)
    function_id = db.Column(db.String(36), nullable=True) # Linked sequence or custom function
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.String(36), default='')

    def __repr__(self):
        return "<IrrigationDesign(id={0}, name='{1}')>".format(self.id, self.name)
