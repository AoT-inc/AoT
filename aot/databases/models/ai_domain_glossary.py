# coding=utf-8
from sqlalchemy.dialects.mysql import LONGTEXT
from datetime import datetime

from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db

class AIDomainGlossary(CRUDMixin, db.Model):
    """
    Represents an auto-learned domain terminology dictionary.

    @phase active
    @stability stable
    """
    __tablename__ = "ai_domain_glossary"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    term = db.Column(db.String(255), unique=True, nullable=False, index=True) 
    definition = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    source = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), default="pending") 
    is_active = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AIDomainGlossary(term={self.term}, status={self.status})>"
