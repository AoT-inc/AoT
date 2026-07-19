# coding=utf-8
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class Tab(CRUDMixin, db.Model):
    """
    Unified Tab model for all pages (Dashboard, Input, Output, Function).
    Replaces the Dashboard table and extends tab functionality to all page types.
    """
    __tablename__ = "tab"
    __table_args__ = (
        db.UniqueConstraint('page_type', 'position', name='unique_page_position'),
        {'extend_existing': True}
    )

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.Text, nullable=False)
    page_type = db.Column(db.String(32), nullable=False, index=True)  # 'dashboard', 'input', 'output', 'function'
    position = db.Column(db.Integer, default=0, index=True, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return "<{cls}(id={s.id}, name={s.name}, page_type={s.page_type}, position={s.position})>".format(
            s=self, cls=self.__class__.__name__)
