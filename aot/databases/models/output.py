# coding=utf-8
from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db
from aot.aot_flask.extensions import ma
from marshmallow import fields


class Output(CRUDMixin, db.Model):
    """
    Represents an actuator or output device on a Tab.

    Outputs drive physical devices (valves, lights, motors, PWM signals) via
    interfaces such as GPIO, I2C, or UART. They support on/off, duration-based,
    and PWM control modes. Can be AI-enabled for automated decision-driven activation.

    @phase active
    """
    __tablename__ = "output"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)  # ID for influxdb entries
    tab_id = db.Column(db.String(36), db.ForeignKey('tab.unique_id', ondelete='CASCADE'), nullable=True, index=True)
    output_type = db.Column(db.Text, default='wired')  # Options: 'command', 'wired', 'wireless_rpi_rf', 'pwm'
    name = db.Column(db.Text, default='Output')
    position_y = db.Column(db.Integer, default=0)
    size_y = db.Column(db.Integer, default=2)
    log_level_debug = db.Column(db.Boolean, default=False)

    # Geo location for mapping (optional)
    latitude = db.Column(db.Float, default=None)
    longitude = db.Column(db.Float, default=None)
    timezone = db.Column(db.String(64), default=None)  # IANA tz, derived from coords
    location_source = db.Column(db.Text, default='manual')  # manual/device/remote
    map_config_id = db.Column(db.String(36), default=None)
    map_overlay_id = db.Column(db.Integer, default=None) # [New] Zone Grouping
    location_updated_utc = db.Column(db.DateTime, default=None)
    marker_icon = db.Column(db.Text, default=None)  # e.g., valve/motor/temp...
    marker_color = db.Column(db.Text, default=None)
    marker_size = db.Column(db.Integer, default=3)

    # Interface options
    interface = db.Column(db.Text, default='')
    location = db.Column(db.Text, default='')

    # I2C
    i2c_location = db.Column(db.Text, default=None)  # Address location for I2C communication
    i2c_bus = db.Column(db.Integer, default='')  # I2C bus the sensor is connected to

    # FTDI
    ftdi_location = db.Column(db.Text, default=None)  # Device location for FTDI communication

    # SPI
    uart_location = db.Column(db.Text, default=None)  # Device location for UART communication
    baud_rate = db.Column(db.Integer, default=None)  # Baud rate for UART communication

    custom_options = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')

    # TODO; Delete at next major version
    # No longer used
    pin = db.Column(db.Integer, default=None)
    on_state = db.Column(db.Boolean, default=True)
    amps = db.Column(db.Float, default=0.0)
    on_until = db.Column(db.DateTime, default=None)
    off_until = db.Column(db.DateTime, default=None)
    last_duration = db.Column(db.Float, default=None)
    on_duration = db.Column(db.Boolean, default=None)
    protocol = db.Column(db.Integer, default=None)
    pulse_length = db.Column(db.Integer, default=None)
    linux_command_user = db.Column(db.Text, default=None)
    on_command = db.Column(db.Text, default=None)
    off_command = db.Column(db.Text, default=None)
    pwm_command = db.Column(db.Text, default=None)
    force_command = db.Column(db.Boolean, default=False)
    trigger_functions_at_start = db.Column(db.Boolean, default=True)
    state_startup = db.Column(db.Text, default=None)
    startup_value = db.Column(db.Float, default=0)
    state_shutdown = db.Column(db.Text, default=None)
    shutdown_value = db.Column(db.Float, default=0)
    pwm_hertz = db.Column(db.Integer, default=None)
    pwm_library = db.Column(db.Text, default=None)
    pwm_invert_signal = db.Column(db.Boolean, default=False)
    flow_rate = db.Column(db.Float, default=None)
    output_mode = db.Column(db.Text, default=None)

    # AI integration (TASK_36)
    is_ai_enabled = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class OutputSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing Output instances.

    @phase active
    """
    i2c_bus = fields.Raw()
    baud_rate = fields.Raw()
    class Meta:
        model = Output


class OutputChannel(CRUDMixin, db.Model):
    """
    Represents a named channel on a multi-channel Output device.

    Multi-channel output hardware exposes multiple independent control channels
    through a single physical interface. Each channel carries its own name and
    custom options JSON.

    @phase active
    """
    __tablename__ = "output_channel"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)  # ID for influxdb entries
    output_id = db.Column(db.Text, default=None)
    channel = db.Column(db.Integer, default=None)
    name = db.Column(db.Text, default='')

    custom_options = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class OutputChannelSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing OutputChannel instances.

    @phase active
    """
    class Meta:
        model = OutputChannel
