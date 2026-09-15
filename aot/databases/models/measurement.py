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

    # 배터리 채널 전용 — 화학 종류. 전압만으로는 판별이 불가능해(납산 12.7V 만충 vs
    # 인산철 4S 13.4V 만충, 곡선 모양이 사실상 반대) 사람이 알려줘야 한다.
    # 값은 device_link_status.BATTERY_TYPES 의 키. ''(빈 값) = 자동 추정.
    battery_type = db.Column(db.Text, default='')

    # 제거 시각(naive UTC). NULL 이면 살아 있는 정의다.
    #
    # **측정 정의는 지우지 않는다.** Influx 값은 장치 id·채널 태그로 남는데,
    # 정의 행을 지우면 그 값을 어떤 채널·단위로 불러야 하는지가 사라져 떼어낸
    # 센서의 과거 기간을 구획에 다시 적용할 수 없다. 삭제 요청은
    # `_retire_instead_of_delete` 가 이 표시로 바꾸고, 표시된 행은
    # `_hide_removed` 가 모든 조회에서 감춘다 — 과거 조회만
    # `execution_options(include_removed_measurements=True)` 로 연다.
    removed_at = db.Column(db.DateTime, nullable=True, default=None)


class DeviceMeasurementsSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing DeviceMeasurements instances.

    @phase active
    """
    class Meta:
        model = DeviceMeasurements


#: 제거 표시된 측정 정의까지 읽는 실행 옵션 이름.
INCLUDE_REMOVED_MEASUREMENTS = 'include_removed_measurements'

_removed_listeners_registered = False


def _register_removed_measurement_listeners():
    """삭제를 제거 표시로 바꾸고, 표시된 행을 모든 ORM 조회에서 감춘다.

    Session **클래스**에 건다 — 웹 요청·데몬·테스트가 각자 세션을 만들어도
    모두 같은 규칙을 지나게 하려는 것이다. 모델 모듈이 import 될 때 한 번만
    등록한다(앱 팩토리에 걸면 앱을 거치지 않는 데몬·테스트가 빠진다).

    ⚠ 대량 `Query.delete()` 는 이 전환을 지나지 않는다(ORM 삭제만 바뀐다).
      운영 코드에는 측정 정의 대량 삭제가 없고, 새로 만들지 말 것.
    """
    global _removed_listeners_registered
    if _removed_listeners_registered:
        return
    _removed_listeners_registered = True

    from datetime import datetime

    from sqlalchemy import event
    from sqlalchemy.orm import Session, with_loader_criteria

    @event.listens_for(Session, 'before_flush')
    def _retire_instead_of_delete(session, flush_context, instances):
        for obj in list(session.deleted):
            if not isinstance(obj, DeviceMeasurements):
                continue
            session.expunge(obj)
            if obj.removed_at is None:
                obj.removed_at = datetime.utcnow()
            session.add(obj)

    @event.listens_for(Session, 'do_orm_execute')
    def _hide_removed(state):
        if (not state.is_select or state.is_column_load
                or state.is_relationship_load
                or state.execution_options.get(INCLUDE_REMOVED_MEASUREMENTS)):
            return
        state.statement = state.statement.options(with_loader_criteria(
            DeviceMeasurements, lambda cls: cls.removed_at.is_(None),
            include_aliases=True))


_register_removed_measurement_listeners()
