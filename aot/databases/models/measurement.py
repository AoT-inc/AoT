# coding=utf-8
from marshmallow_sqlalchemy.fields import Nested

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db
from aot.aot_flask.extensions import ma


class Measurement(CRUDMixin, db.Model):
    """
    Defines a measurement type (e.g., temperature, humidity) with safe name and units.

    Measurement records provide a canonical list of every measurement kind used in
    the system, enabling consistent naming and unit assignment across sensors.

    @phase active
    """
    __tablename__ = "measurements"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name_safe = db.Column(db.Text)
    name = db.Column(db.Text)
    units = db.Column(db.Text)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class MeasurementSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing Measurement instances.

    @phase active
    """
    class Meta:
        model = Measurement


class Unit(CRUDMixin, db.Model):
    """
    Defines a unit of measure (e.g., celsius, percent, ppm) with safe name.

    @phase active
    """
    __tablename__ = "units"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name_safe = db.Column(db.Text)
    name = db.Column(db.Text)
    unit = db.Column(db.Text)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class UnitSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing Unit instances.

    @phase active
    """
    class Meta:
        model = Unit


class Conversion(CRUDMixin, db.Model):
    """
    Defines a unit conversion equation from one unit to another.

    Each record stores a source unit, target unit, and an equation string (e.g.,
    '(x+2)*3') used to transform raw sensor values. Protected conversions cannot
    be modified by users.

    @phase active
    """
    __tablename__ = "conversion"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    convert_unit_from = db.Column(db.Text)
    convert_unit_to = db.Column(db.Text)
    equation = db.Column(db.Text)
    protected = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class ConversionSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing Conversion instances.

    @phase active
    """
    class Meta:
        model = Conversion


class DeviceMeasurements(CRUDMixin, db.Model):
    """
    Binds a measurement and unit to a specific device input or output channel.

    DeviceMeasurements acts as the per-channel measurement definition, linking a
    physical device (by device_id) to a measurement type and unit. Supports rescaling
    via custom equations and invert options.

    @phase active
    """
    __tablename__ = "device_measurements"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    name = db.Column(db.Text, default='')
    device_type = db.Column(db.Text, default=None)
    device_id = db.Column(db.String(36), default=None)

    # Default measurement/unit
    is_enabled = db.Column(db.Boolean, default=True)
    measurement = db.Column(db.Text, default='')
    measurement_type = db.Column(db.Text, default='')
    unit = db.Column(db.Text, default='')
    channel = db.Column(db.Integer, default=None)

    # Rescale measurement
    rescale_method = db.Column(db.Text, default='linear')
    rescale_equation = db.Column(db.Text, default='(x+2)*3')
    invert_scale = db.Column(db.Boolean, default=False)
    rescaled_measurement = db.Column(db.Text, default='')
    rescaled_unit = db.Column(db.Text, default='')
    scale_from_min = db.Column(db.Float, default=0)
    scale_from_max = db.Column(db.Float, default=10)
    scale_to_min = db.Column(db.Float, default=0)
    scale_to_max = db.Column(db.Float, default=20)

    conversion_id = db.Column(db.String(36), default='')


class DeviceMeasurementsSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing DeviceMeasurements instances.

    @phase active
    """
    class Meta:
        model = DeviceMeasurements
