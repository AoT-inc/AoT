# coding=utf-8
from sqlalchemy.dialects.mysql import LONGTEXT
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class AIUserProfile(CRUDMixin, db.Model):
    """
    Stores user-specific AI interaction profiles, including proficiency and learning notes.

    @phase active
    @stability stable
    @dependency User
    """
    __tablename__ = "ai_user_profile"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    # Link to AoT User
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Proficiency Tracking
    # Levels: beginner, intermediate, advanced
    proficiency_level = db.Column(db.String(20), default='beginner')
    proficiency_score = db.Column(db.Integer, default=0)
    
    # AI's evolving notes about the user
    learning_notes_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    
    last_active = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 016: Onboarding v2 (Getting to Know Each Other flow)
    onboarding_completed = db.Column(db.Boolean, default=False)
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)
    facility_preset = db.Column(db.String(50), nullable=True)
    user_requirement = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True)

    # Relationship
    user = db.relationship('User', backref=db.backref('ai_profile', uselist=False))

    def __repr__(self):
        return f"<AIUserProfile(user_id={self.user_id}, level={self.proficiency_level})>"
