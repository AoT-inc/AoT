# coding=utf-8
import logging

from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin, set_uuid
from aot.databases.sqla import db

logger = logging.getLogger("aot.misc")


class Misc(CRUDMixin, db.Model):
    """
    Singleton global configuration record for miscellaneous AoT settings.

    Misc holds system-wide preferences including branding, HTTPS enforcement,
    sample rates, energy cost tracking, timezone, and measurement database
    credentials. Only one row should exist (id=1).

    @phase active
    """
    __tablename__ = "misc"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    dismiss_notification = db.Column(db.Boolean, default=False)  # Dismiss login page license notice
    force_https = db.Column(db.Boolean, default=True)  # Force web interface to use SSL/HTTPS
    hide_alert_info = db.Column(db.Boolean, default=False)
    hide_alert_success = db.Column(db.Boolean, default=False)
    hide_alert_warning = db.Column(db.Boolean, default=False)
    # AI 메시지(자막·수신함 점) 숨기기 — 시스템 메시지(hide_alert_*)와 별개다.
    # 켜도 AI 가 보낸 카드는 수신함에 저장된다(2026-10-19).
    hide_ai_messages = db.Column(db.Boolean, default=False)
    # AI 결과 카드 자동(2026-10-22): 켜면 외부 AI 의 MCP 지침(initialize instructions)에 "핵심 결과를
    # 끝낼 때 카드로도 올려라" 규칙이 붙는다. 기본 켬 — NULL(옛 행)도 켬으로 본다.
    ai_card_auto = db.Column(db.Boolean, default=True)
    # AI 바로가기 주소(2026-10-22) — 휴대폰 AI 창구(수신함 머리줄)에 뜨는 [Claude] 같은 단추가 여는 https 주소.
    # 비우면 단추가 없다. 기본은 Claude 새 대화. 앱이 깔린 휴대폰은 운영체제가 앱으로 연다(실측은 사용자).
    ai_shortcut_url = db.Column(db.String(512), default='https://claude.ai/new')
    hide_tooltips = db.Column(db.Boolean, default=False)
    grid_cell_height = db.Column(db.Integer, default=25)
    login_message = db.Column(db.Text, default='')  # Put a message on the login screen
    max_amps = db.Column(db.Float, default=15.0)  # Maximum allowed current to be drawn
    output_usage_cost = db.Column(db.Float, default=0.05)  # Energy cost per kWh
    output_usage_currency = db.Column(db.Text, default='$')  # Energy cost currency
    output_usage_dayofmonth = db.Column(db.Integer, default=15)  # Electricity billing day of month
    output_usage_volts = db.Column(db.Integer, default=120)  # Voltage the alternating current operates
    output_usage_report_gen = db.Column(db.Boolean, default=False)
    output_usage_report_span = db.Column(db.Text, default='monthly')
    output_usage_report_day = db.Column(db.Integer, default=1)
    output_usage_report_hour = db.Column(db.Integer, default=0)
    sample_rate_controller_conditional = db.Column(db.Float, default=0.25)
    sample_rate_controller_function = db.Column(db.Float, default=0.25)
    sample_rate_controller_input = db.Column(db.Float, default=0.1)
    sample_rate_controller_math = db.Column(db.Float, default=0.25)
    sample_rate_controller_output = db.Column(db.Float, default=0.05)
    sample_rate_controller_pid = db.Column(db.Float, default=0.1)
    sample_rate_controller_widget = db.Column(db.Float, default=0.25)
    stats_opt_out = db.Column(db.Boolean, default=False)  # Opt not to send anonymous usage statistics
    enable_upgrade_check = db.Column(db.Boolean, default=True)  # Periodically check for a AoT upgrade
    aot_upgrade_available = db.Column(db.Boolean, default=False)  # Stores if an upgrade is available
    # Docker only: install a published update automatically at a set local time
    # (see docs/design/docker-auto-update.md). Off by default -- turning it on
    # means accepting a brief control pause at that hour, unattended.
    docker_auto_update = db.Column(db.Boolean, default=False)
    docker_auto_update_time = db.Column(db.String(5), default='03:00')  # 'HH:MM', local time
    rpyc_timeout = db.Column(db.Integer, default=30)
    gunicorn_threads = db.Column(db.Integer, default=None)  # 웹서버 스레드 수동 설정 (NULL = 자동 산정)
    daemon_debug_mode = db.Column(db.Boolean, default=False)
    # Matter 컨트롤러(실험). 켜야 설정 사이드바·Matter 페이지·API 가 열린다.
    matter_enabled = db.Column(db.Boolean, default=False)
    # 디지털트윈(실험, 별도 서비스 aot_twin). 판정의 정본은 aot/utils/twin_gate.py —
    # 이 칸을 직접 읽어 켜짐을 판단하지 말 것(낮은 사양 잠금이 빠진다).
    #   twin_enabled    사용자가 설정 > 일반에서 켠 플래그(기본 꺼짐)
    #   twin_run_times  실행 시각 'HH:MM,HH:MM' (현지, 기본 06:10,18:10)
    #   twin_heartbeat  서비스가 쓴다: {at, status, version, sites, plots,
    #                   last_run_at, failures, locked_reason}. 서비스가 안 돌면 비어 있거나 낡는다.
    twin_enabled = db.Column(db.Boolean, default=False)
    twin_run_times = db.Column(db.Text, default='06:10,18:10')
    twin_heartbeat = db.Column(db.JSON, nullable=True)
    #   twin_auto_forecast   대지에 트윈을 켤 때 가까운 예보 입력이 없으면 새로 만든다(기본 켜짐)
    #   twin_ignore_profile  쓰지 않는 칸 — HARDWARE_PROFILE 잠금을 없애며(2026-11) 옵션도 걷어 냈다. 되돌리기
    #                        안전하도록 DB 열(alembic p6_92)과 이 정의는 남기고 마이그레이션은 만들지 않는다.
    twin_ignore_profile = db.Column(db.Boolean, default=False)
    twin_auto_forecast = db.Column(db.Boolean, default=True)
    # 데이터 계층(예보·트윈 데이터 관리, aot/utils/influx_layers.py): Influx 버킷을 계층별로 나눠 보존 기간을 따로 둔다.
    #   {"enabled": false} 면 한 버킷(aot_db) 모드. {"retention_days": {"fc": 730, "calc": 60, "hist": 730}}.
    #   NULL = 켜짐 + 기본 보존. 판정·기본값의 정본은 influx_layers.py.
    data_layers = db.Column(db.JSON, nullable=True)
    net_test_ip = db.Column(db.String(16), default='8.8.8.8')
    net_test_port = db.Column(db.Integer, default=53)
    net_test_timeout = db.Column(db.Integer, default=3)
    default_login_page = db.Column(db.String(16), default='password')
    brand_display = db.Column(db.String(36), default='default')
    title_display = db.Column(db.String(36), default='hostname')
    hostname_override = db.Column(db.String(36), default='')
    brand_image = db.Column(db.BLOB, default=b'')
    brand_image_height = db.Column(db.Integer, default=55)
    favicon_display = db.Column(db.String(16), default='default')
    brand_favicon = db.Column(db.BLOB, default=b'')
    custom_css = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    custom_layout = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    custom_theme_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    custom_theme_presets = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')  # {"프리셋명": {color_field: "#RRGGBB", ...}}
    default_facility_id = db.Column(db.String(36), default='')

    # Common map location (used as default center/device seed)
    map_latitude = db.Column(db.Float, default=None)
    map_longitude = db.Column(db.Float, default=None)
    map_location_label = db.Column(db.Text, default='')

    # Global Timezone Setting (e.g., 'Asia/Seoul', 'UTC')
    # Default to None to indicate 'Follow System/UTC' until explicitly set
    timezone = db.Column(db.String(64), default='UTC')

    # ChirpStack LNS connection (used by the ChirpStack Devices page to list
    # devices via gRPC and pre-fill registered Inputs/Outputs)
    chirpstack_grpc_server = db.Column(db.String(255), default='')   # host:port, e.g. host.docker.internal:8080
    chirpstack_api_token = db.Column(db.Text, default='')            # ChirpStack API key (JWT, no 'Bearer ' prefix)
    chirpstack_mqtt_host = db.Column(db.String(255), default='')     # broker host for registered MQTT inputs
    chirpstack_mqtt_port = db.Column(db.Integer, default=1883)       # broker port for registered MQTT inputs

    # Google Calendar OAuth (instance-wide, admin-configured on settings/integrations).
    # client_id/secret from Google Cloud Console; per-user tokens live in
    # UserCalendarConnection, NOT here. oauth_public_base_url is this server's
    # externally-reachable origin (e.g. https://ai.aotinc.co.kr) — used to build
    # the OAuth redirect_uri deterministically so it matches the value registered
    # in Google Console (rather than trusting proxy request headers).
    google_oauth_client_id = db.Column(db.Text, default='')
    google_oauth_client_secret = db.Column(db.Text, default='')
    oauth_public_base_url = db.Column(db.String(255), default='')

    # Google Picker API key (aot/aot_flask/routes_ai_library.py Google Drive
    # source). NOT the OAuth client secret — the Picker JS widget needs a
    # separate Cloud Console "API key" (Credentials > API key) with the
    # Picker API enabled. Not a secret in the OAuth sense (it's sent to the
    # browser as a JS `developerKey`, same as any client-side Maps/Picker key),
    # so it's stored in plain text like the other instance-wide config here.
    google_picker_api_key = db.Column(db.Text, default='')

    # Measurement database
    db_name = 'influxdb'  # Default
    db_version = ''  # Default
    db_host = 'localhost'
    db_port = 0
    db_retention_policy = ''

    try:
        from aot.scripts.measurement_db import get_influxdb_info
        influx_info = get_influxdb_info()
        if influx_info['influxdb_installed'] or influx_info['influxdb_host']:
            db_name = 'influxdb'
        if influx_info['influxdb_host']:
            db_host = influx_info['influxdb_host']
        if influx_info['influxdb_port']:
            db_port = influx_info['influxdb_port']
        if influx_info['influxdb_version']:
            if influx_info['influxdb_version'].startswith("1."):
                db_version = '1'
                db_retention_policy = 'autogen'
            if influx_info['influxdb_version'].startswith("2."):
                db_version = '2'
                db_retention_policy = 'infinite'
    except:
        logger.exception("Determining influxdb version")

    measurement_db_retention_policy = db.Column(db.String(36), default=db_retention_policy)
    measurement_db_name = db.Column(db.String(36), default=db_name)
    measurement_db_version = db.Column(db.String(36), default=db_version)
    measurement_db_host = db.Column(db.String(36), default=db_host)
    measurement_db_port = db.Column(db.String(36), default=db_port)
    measurement_db_user = db.Column(db.String(36), default='aot')
    measurement_db_password = db.Column(db.String(36), default='mmdu77sj3nIoiajjs')
    measurement_db_dbname = db.Column(db.String(36), default='aot_db')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class EnergyUsage(CRUDMixin, db.Model):
    """
    Tracks energy consumption records for a device linked to a measurement.

    EnergyUsage logs the cumulative or periodic energy usage of a device,
    associated with a measurement identifier and a unique session ID.

    @phase active
    """
    __tablename__ = "energy_usage"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)  # ID for influxdb entries
    name = db.Column(db.Text, default='Name')
    device_id = db.Column(db.String(36), default='')
    measurement_id = db.Column(db.String(36), default='')
