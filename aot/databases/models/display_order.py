# coding=utf-8
from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db


class DisplayOrder(CRUDMixin, db.Model):
    """
    Stores the sort order of top-level page categories in the UI navigation bar.

    DisplayOrder holds comma-separated or named orderings for LCD, method, remote_host,
    timer, and other page groups. Some columns are deprecated (math, inputs, output, etc.)
    and scheduled for removal at the next major revision.

    @phase active
    @stability deprecated
    """
    __tablename__ = "displayorder"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    lcd = db.Column(db.Text, default='')
    method = db.Column(db.Text, default='')
    remote_host = db.Column(db.Text, default='')
    timer = db.Column(db.Text, default='')

    # TODO: Deprecated, remove at next major revision
    math = db.Column(db.Text, default='')
    inputs = db.Column(db.Text, default='')
    output = db.Column(db.Text, default='')
    dashboard = db.Column(db.Text, default='')
    function = db.Column(db.Text, default='')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
