# coding=utf-8
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class Method(CRUDMixin, db.Model):
    """
    Defines a time-based method for scheduling output or setpoint changes.

    Methods contain ordered data points (MethodData) that represent a schedule —
    e.g., a temperature ramp or light cycle — used by PID setpoint tracking or
    scheduler job definitions.

    @phase active
    """
    __tablename__ = "method"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.Text, default='Method')
    method_type = db.Column(db.Text, default='')
    method_order = db.Column(db.Text, default='')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class MethodData(CRUDMixin, db.Model):
    """
    Represents a single data point within a time-based Method schedule.

    Each record defines a time window (time_start, time_end, duration_sec), an
    optional output action (output_id, output_state, output_duration), and
    setpoint or curve parameters for PID setpoint tracking.

    @phase active
    """
    __tablename__ = "method_data"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    method_id = db.Column(db.String(36), default=None)
    time_start = db.Column(db.Text, default=None)
    time_end = db.Column(db.Text, default=None)
    duration_sec = db.Column(db.Float, default=None)
    duration_end = db.Column(db.Float, default=None)
    output_id = db.Column(db.String(36), default=None)
    output_state = db.Column(db.Text, default=None)
    output_duration = db.Column(db.Float, default=None)
    setpoint_start = db.Column(db.Float, default=None)
    setpoint_end = db.Column(db.Float, default=None)
    amplitude = db.Column(db.Float, default=None)
    frequency = db.Column(db.Float, default=None)
    shift_angle = db.Column(db.Float, default=None)
    shift_y = db.Column(db.Float, default=None)
    x0 = db.Column(db.Float, default=None)
    y0 = db.Column(db.Float, default=None)
    x1 = db.Column(db.Float, default=None)
    y1 = db.Column(db.Float, default=None)
    x2 = db.Column(db.Float, default=None)
    y2 = db.Column(db.Float, default=None)
    x3 = db.Column(db.Float, default=None)
    y3 = db.Column(db.Float, default=None)
    linked_method_id = db.Column(db.String(36), default=None)
    points_json = db.Column(db.Text, default=None)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
