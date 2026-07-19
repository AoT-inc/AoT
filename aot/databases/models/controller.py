# coding=utf-8
from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db
from aot.aot_flask.extensions import ma


class CustomController(CRUDMixin, db.Model):
    """
    Represents a user-defined custom controller on a Tab.

    Custom controllers hold Python code (stored in custom_options) that is executed
    by the daemon. They support activation state, debug logging, geo-location, and
    map overlay grouping.

    @phase active
    """
    __tablename__ = "custom_controller"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    tab_id = db.Column(db.String(36), db.ForeignKey('tab.unique_id', ondelete='CASCADE'), nullable=True, index=True)
    name = db.Column(db.Text, default='Custom Function')
    position_y = db.Column(db.Integer, default=0)
    device = db.Column(db.Text, default='')

    is_activated = db.Column(db.Boolean, default=False)
    log_level_debug = db.Column(db.Boolean, default=False)
    latitude = db.Column(db.Float, default=None)
    longitude = db.Column(db.Float, default=None)
    timezone = db.Column(db.String(64), default=None)  # IANA tz, derived from coords
    location_source = db.Column(db.String(32), default='manual')
    map_config_id = db.Column(db.String(36), default=None)
    map_overlay_id = db.Column(db.Integer, default=None) # [New] Zone Grouping

    custom_options = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')

    # Method 곡선 시작 시각 (env_coordinator VPD/CO2 setpoint 가 사용 —
    # pid.method_start_time 과 동일 의미; ISO 문자열, NULL = 첫 평가 시 기록)
    method_start_time = db.Column(db.Text, default=None, nullable=True)

    def is_active(self):
        """
        :return: Whether the Controller is currently activated
        :rtype: bool
        """
        return self.is_activated

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class FunctionSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing CustomController instances.

    @phase active
    """
    class Meta:
        model = CustomController


class FunctionChannel(CRUDMixin, db.Model):
    """
    Represents a named channel within a CustomController.

    Channels allow a single controller to manage multiple sub-devices or output
    stages, each with its own name and custom options JSON.

    @phase active
    """
    __tablename__ = "function_channel"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    function_id = db.Column(db.String(36), default=None)
    channel = db.Column(db.Integer, default=None)
    name = db.Column(db.Text, default='')

    custom_options = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class FunctionChannelSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing FunctionChannel instances.

    @phase active
    """
    class Meta:
        model = FunctionChannel
