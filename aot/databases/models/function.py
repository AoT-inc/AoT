# coding=utf-8
from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db
from aot.aot_flask.extensions import ma


class Function(CRUDMixin, db.Model):
    """
    Represents a user-defined function block on a dashboard Tab.

    Functions are executable units attached to a Tab that can trigger actions,
    run custom logic, or interface with devices. They support geo-location,
    debug logging, and map overlay grouping.

    @phase active
    """
    __tablename__ = "function"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    tab_id = db.Column(db.String(36), db.ForeignKey('tab.unique_id', ondelete='CASCADE'), nullable=True, index=True)
    function_type = db.Column(db.Text, default='')
    name = db.Column(db.Text, default='Function Name')
    position_y = db.Column(db.Integer, default=0)
    log_level_debug = db.Column(db.Boolean, default=False)
    latitude = db.Column(db.Float, default=None)
    longitude = db.Column(db.Float, default=None)
    timezone = db.Column(db.String(64), default=None)  # IANA tz, derived from coords
    tz_source = db.Column(db.String(16), default=None)  # explicit | inherited | coords (see docs/design/timezone-management.md)
    location_source = db.Column(db.String(32), default='manual')
    marker_icon = db.Column(db.Text, default=None)
    marker_color = db.Column(db.Text, default=None)
    marker_size = db.Column(db.Integer, default=3)
    map_config_id = db.Column(db.String(36), default=None)
    map_overlay_id = db.Column(db.Integer, default=None) # [New] Zone Grouping


class Conditional(CRUDMixin, db.Model):
    """
    Represents a conditional logic block that activates based on sensor or device state.

    Conditionals evaluate a stored Python expression (conditional_statement) on a
    configurable period and trigger associated Actions when the condition is met.
    Supports measurement-based, GPIO, output, and controller-based triggers.

    @phase active
    """
    __tablename__ = "conditional"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    tab_id = db.Column(db.String(36), db.ForeignKey('tab.unique_id', ondelete='CASCADE'), nullable=True, index=True)
    name = db.Column(db.Text, default='Conditional')
    position_y = db.Column(db.Integer, default=0)

    is_activated = db.Column(db.Boolean, default=False)
    log_level_debug = db.Column(db.Boolean, default=False)
    
    # Geo Location
    latitude = db.Column(db.Float, default=None)
    longitude = db.Column(db.Float, default=None)
    timezone = db.Column(db.String(64), default=None)  # IANA tz, derived from coords
    tz_source = db.Column(db.String(16), default=None)  # explicit | inherited | coords (see docs/design/timezone-management.md)
    location_source = db.Column(db.String(32), default='manual')
    map_config_id = db.Column(db.String(36), default=None)
    map_overlay_id = db.Column(db.Integer, default=None) # [New] Zone Grouping

    conditional_statement = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    conditional_import = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    conditional_initialize = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    conditional_status = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    period = db.Column(db.Float, default=60.0)
    start_offset = db.Column(db.Float, default=10.0)
    pyro_timeout = db.Column(db.Float, default=30.0)
    use_pylint = db.Column(db.Boolean, default=True)
    message_include_code = db.Column(db.Boolean, default=False)

    custom_options = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')


class ConditionalConditions(CRUDMixin, db.Model):
    """
    Stores individual condition clauses that compose a Conditional's full trigger logic.

    Each row represents a single condition axis — measurement sensor, GPIO pin,
    output state, or controller — linked back to a parent Conditional record.

    @phase active
    """
    __tablename__ = "conditional_data"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    conditional_id = db.Column(db.String(36), default=None)
    condition_type = db.Column(db.Text, default=None)

    # Sensor
    measurement = db.Column(db.Text, default='')  # which measurement to monitor
    max_age = db.Column(db.Integer, default=120)  # max age of the measurement

    # GPIO State
    gpio_pin = db.Column(db.Integer, default=0)

    # Output State
    output_id = db.Column(db.String(36), default='')

    # Controller
    controller_id = db.Column(db.String(36), default='')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class Trigger(CRUDMixin, db.Model):
    """
    Represents an event-driven trigger that activates outputs or actions at scheduled times.

    Triggers can be time-based (timer, sunrise/sunset), event-based (measurement edge,
    output state change), or infrared signal receivers. Each trigger is associated
    with a Tab and fires configured actions when its condition is met.

    @phase active
    """
    __tablename__ = "trigger"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    tab_id = db.Column(db.String(36), db.ForeignKey('tab.unique_id', ondelete='CASCADE'), nullable=True, index=True)
    trigger_type = db.Column(db.Text, default=None)
    action_type = db.Column(db.Text, default='')
    name = db.Column(db.Text, default='Trigger Name')
    position_y = db.Column(db.Integer, default=0)
    is_activated = db.Column(db.Boolean, default=False)
    log_level_debug = db.Column(db.Boolean, default=False)

    # Used to hold unique IDs
    unique_id_1 = db.Column(db.String(36), default=None)
    unique_id_2 = db.Column(db.String(36), default=None)
    unique_id_3 = db.Column(db.String(36), default=None)

    # Output
    output_state = db.Column(db.Text, default='')  # What action to watch output for
    output_duration = db.Column(db.Float, default=0.0)
    output_duty_cycle = db.Column(db.Float, default=0.0)

    # Sunrise/sunset
    rise_or_set = db.Column(db.Text, default='sunrise')
    latitude = db.Column(db.Float, default=None)
    longitude = db.Column(db.Float, default=None)
    timezone = db.Column(db.String(64), default=None)  # IANA tz, derived from coords
    tz_source = db.Column(db.String(16), default=None)  # explicit | inherited | coords (see docs/design/timezone-management.md)
    location_source = db.Column(db.String(32), default='manual')
    map_config_id = db.Column(db.String(36), default=None)
    map_overlay_id = db.Column(db.Integer, default=None) # [New] Zone Grouping
    date_offset_days = db.Column(db.Integer, default=0)
    time_offset_minutes = db.Column(db.Integer, default=0)

    # Timer
    period = db.Column(db.Float, default=60.0)
    timer_start_offset = db.Column(db.Integer, default=0)
    timer_start_time = db.Column(db.Text, default='16:30')
    timer_end_time = db.Column(db.Text, default='19:00')
    timer_weekday = db.Column(db.Text, default=None)  # '0,1,2,3,4,5,6' Mon-Sun; None = all days
    timer_schedule = db.Column(db.Text, default=None)  # JSON weekly_schedule v1; None = use legacy columns

    # Receive infrared from remote (deprecated, TODO: remove)
    program = db.Column(db.Text, default='aot')
    word = db.Column(db.Text, default='button_a')

    # Method
    method_start_time = db.Column(db.Text, default=None)
    method_end_time = db.Column(db.Text, default=None)
    trigger_actions_at_period = db.Column(db.Boolean, default=True)
    trigger_actions_at_start = db.Column(db.Boolean, default=True)

    # Edge
    measurement = db.Column(db.Text, default='')
    edge_detected = db.Column(db.Text, default='')

    # Unused  TODO: remove
    zenith = db.Column(db.Float, default=90.8)


class TriggerSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing Trigger instances.

    @phase active
    """
    class Meta:
        model = Trigger


class Actions(CRUDMixin, db.Model):
    """
    Represents an individual action that a Function or Trigger can execute.

    Actions define what happens when a trigger fires — e.g., send an email,
    switch an output, adjust a PWM, or run a shell command. Each action is
    linked to a function and carries custom options as JSON.

    @phase active
    """
    __tablename__ = "function_actions"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    function_id = db.Column(db.String(36), default=None)
    function_type = db.Column(db.Text, default='')
    action_type = db.Column(db.Text, default='')  # what action, such as 'email', 'execute command', 'flash LCD'

    custom_options = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')

    # Actions
    pause_duration = db.Column(db.Float, default=5.0)
    do_unique_id = db.Column(db.String(36), default='')
    do_action_string = db.Column(db.Text, default='')  # string, such as the email address or command
    do_output_state = db.Column(db.Text, default='')  # 'on' or 'off'
    do_output_amount = db.Column(db.Float, default=0.0)
    do_output_duration = db.Column(db.Float, default=0.0)
    do_output_pwm = db.Column(db.Float, default=0.0)
    do_output_pwm2 = db.Column(db.Float, default=0.0)
    do_camera_duration = db.Column(db.Float, default=5.0)

    # Infrared remote send (deprecated, TODO: remove)
    remote = db.Column(db.Text, default='my_remote')
    code = db.Column(db.Text, default='KEY_A')
    send_times = db.Column(db.Integer, default=1)

    @property
    def position(self):
        try:
            import json
            opts = json.loads(self.custom_options) if self.custom_options else {}
            # Order source of truth is 'gridstack_y', written by the drag-reorder
            # (/function_save_order) and by action_add. Legacy 'position' (e.g.
            # small creation indices written by AI action creation) is stale once
            # a user reorders, so gridstack_y must win. Fall back to 'position'
            # only for actions never touched by the new reorder UI, then 9999.
            pos = opts.get('gridstack_y')
            if pos is None:
                pos = opts.get('position')
            return int(pos) if pos is not None else 9999
        except:
            return 9999

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class FunctionRuntimeState(CRUDMixin, db.Model):
    """
    PI 상태(적분·이전 명령·히스테리시스)를 데몬 재시작 간에 보존한다.

    각 env_coordinator Function 인스턴스마다 row 하나.
    사이클 종료 시 업데이트, 초기화 시 로드한다.

    @phase active
    """
    __tablename__ = 'function_runtime_state'
    __table_args__ = {'extend_existing': True}

    id               = db.Column(db.Integer, primary_key=True)
    function_id      = db.Column(db.String(36), nullable=False, unique=True, index=True)
    integral_json    = db.Column(db.Text, default='{}')
    prev_cmds_json   = db.Column(db.Text, default='{}')
    active_vars_json = db.Column(db.Text, default='{}')
    last_cycle_ts    = db.Column(db.Float, default=0.0)
    updated_at       = db.Column(db.Float, default=0.0)
    calibration_state_json = db.Column(db.Text, default=None, nullable=True)
    # 맵 팝업 [현황] 탭용 사이클 요약 스냅샷 (모드/편차/추세/환기/예보 선행)
    summary_json     = db.Column(db.Text, default=None, nullable=True)
    # 맵 위젯 /runtime 용 센서 스냅샷 (indoor/outdoor/sensors/fitting_sensors).
    # 사이클마다 갱신 — 웹이 InfluxDB 를 직접 조회하지 않게 한다. NULL = 미존재.
    runtime_json     = db.Column(db.Text, default=None, nullable=True)

    def __repr__(self):
        return f'<FunctionRuntimeState function_id={self.function_id}>'
