# coding=utf-8
import csv
import datetime
import json
import logging
import os
import subprocess
import mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import import_module
from io import StringIO

import flask_login
from flask import (Response, flash, jsonify, redirect, render_template, request,
                   send_file, send_from_directory, url_for)
from flask.blueprints import Blueprint
from flask_babel import gettext
from flask_limiter import Limiter
from sqlalchemy import and_

from aot.config import (DOCKER_CONTAINER, INSTALL_DIRECTORY, LOG_PATH,
                           PATH_CAMERAS, PATH_NOTE_ATTACHMENTS)
from aot.databases.models import (PID, Camera, Conversion, CustomController,
                                     DeviceMeasurements, Input, Misc, Notes,
                                     NoteTags, Output, OutputChannel)
from aot.aot_client import DaemonControl
from aot.aot_flask.routes_authentication import clear_cookie_auth
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils.utils_general import get_ip_address
from aot.aot_flask.utils.utils_output import get_all_output_states
from aot.utils.database import db_retrieve_table
from aot.utils.influx import (influx_to_list, influxdb_get_count_points,
                                 influxdb_get_first_point, query_string)
from aot.utils.service_control import reload_frontend, restart_daemon
from aot.utils.system_pi import (assure_path_exists, is_int,
                                    return_measurement_info, str_is_float)
from aot.utils.influx import read_influxdb_list
from pytz import timezone

blueprint = Blueprint('routes_general',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_ip_address)


@blueprint.route('/')
def home():
    """Load the default landing page."""
    try:
        if flask_login.current_user.is_authenticated:
            if flask_login.current_user.landing_page == 'live':
                return redirect(url_for('routes_page.page_live'))
            elif flask_login.current_user.landing_page == 'dashboard':
                return redirect(url_for('routes_dashboard.page_dashboard_default'))
            elif flask_login.current_user.landing_page == 'info':
                return redirect(url_for('routes_page.page_info'))
            return redirect(url_for('routes_page.page_live'))
        return render_template('pages/landing.html')
    except:
        logger.error("User may not be logged in. Clearing cookie auth.")
    return clear_cookie_auth()


@blueprint.route('/index_page')
def index_page():
    """Load the index page."""
    try:
        if not flask_login.current_user.index_page:
            return home()
        elif flask_login.current_user.index_page == 'landing':
            return home()
        else:
            if flask_login.current_user.is_authenticated:
                if flask_login.current_user.index_page == 'live':
                    return redirect(url_for('routes_page.page_live'))
                elif flask_login.current_user.index_page == 'dashboard':
                    return redirect(url_for('routes_dashboard.page_dashboard_default'))
                elif flask_login.current_user.index_page == 'info':
                    return redirect(url_for('routes_page.page_info'))
                return redirect(url_for('routes_page.page_live'))
    except:
        logger.error("User may not be logged in. Clearing cookie auth.")
    return clear_cookie_auth()


@blueprint.route('/custom.css')
def custom_css():
    """Load custom CSS and custom UI theme"""
    css_content = ""
    try:
        from aot.aot_flask.extensions import db as _db
        _db.session.expire_all()
        settings = Misc.query.first()
        if settings and settings.custom_css:
            css_content += settings.custom_css + "\n"
        
        import json
        theme_dict = {}
        if settings and settings.custom_theme_json and settings.custom_theme_json != '{}':
            theme_dict = json.loads(settings.custom_theme_json)
        
        # Fallback to hardcoded defaults if DB is empty or lacks specific keys
        from aot.aot_flask.forms.forms_settings import SettingsCustomUI
        form = SettingsCustomUI()
        
        # 각 custom_ui 필드 → [레거시 별칭, --aot-* 실토큰] 목록.
        # 레거시 별칭만 덮어쓰면 --aot-* 토큰을 직접 소비하는 컴포넌트(위젯 등)에
        # 사용자 지정 색이 반영되지 않으므로 두 이름을 함께 발행한다.
        # bg_btn_on/off 는 --aot-btn-bg-active/inactive 와 충돌하므로(별도 aot 토큰
        # 없음) 레거시 이름만 발행한다. 매핑 근거: docs/design/color-system.md
        var_map = {
            'brand_primary': ['--brand-primary', '--aot-color-brand-primary'],
            'brand_secondary': ['--brand-secondary', '--aot-color-brand-secondary'],
            'brand_accent': ['--brand-accent', '--aot-color-brand-accent'],
            'text_color_primary': ['--text-color-primary', '--aot-color-text-primary'],
            'text_color_secondary': ['--text-color-secondary', '--aot-color-text-secondary'],
            'text_color_tertiary': ['--text-color-tertiary', '--aot-color-text-tertiary'],
            'bd_primary': ['--bd-primary'],
            'bd_secondary': ['--bd-secondary'],
            'bd_tertiary': ['--bd-tertiary'],
            'bg_upgrade': ['--bg-upgrade', '--aot-bg-upgrade'],
            'bg_active': ['--bg-active', '--aot-bg-active'],
            'bg_inactive': ['--bg-inactive', '--aot-bg-inactive'],
            'bg_llm': ['--bg-llm', '--aot-color-llm'],
            'bg_mcp': ['--bg-mcp', '--aot-color-mcp'],
            'bd_btn_primary': ['--bd-btn-primary', '--aot-btn-bg-primary'],
            'bd_btn_secondary': ['--bd-btn-secondary', '--aot-btn-bg-secondary'],
            'bd_btn_tertiary': ['--bd-btn-tertiary'],
            'bg_btn_upgrade': ['--bg-btn-upgrade', '--aot-btn-bg-upgrade'],
            'bg_btn_on': ['--bg-btn-on'],
            'bg_btn_off': ['--bg-btn-off'],
            'bg_btn_active': ['--bg-btn-active', '--aot-btn-bg-active'],
            'bg_btn_inactive': ['--bg-btn-inactive', '--aot-btn-bg-inactive'],
            'bg_btn_pause': ['--bg-btn-pause', '--aot-btn-bg-pause'],
            'bg_btn_hold': ['--bg-btn-hold', '--aot-btn-bg-hold'],
            'bd_btn_border': ['--bd-btn-border', '--aot-btn-border-primary'],
            'band_1': ['--aot-band-1'],
            'band_2': ['--aot-band-2'],
            'band_3': ['--aot-band-3'],
            'band_4': ['--aot-band-4'],
            'band_5': ['--aot-band-5'],
            'chart_1': ['--aot-chart-1'],
            'chart_2': ['--aot-chart-2'],
            'chart_3': ['--aot-chart-3'],
            'chart_4': ['--aot-chart-4'],
            'chart_5': ['--aot-chart-5'],
            'chart_6': ['--aot-chart-6']
        }

        # 다크 테마에서는 custom-dark.css(:root)가 텍스트/액센트 토큰을 재정의하는데
        # /custom.css 가 그보다 늦게 로드된다. 같은 이름을 여기서 다시 발행하면
        # 다크 재정의가 라이트 사용자색으로 덮여 어두운 배경에 어두운 글자가 되므로,
        # 다크 사용자에게는 해당 --aot-* 토큰 발행을 생략한다(레거시 별칭은 유지).
        dark_overridden = {
            '--aot-color-brand-accent',
            '--aot-color-text-primary',
            '--aot-color-text-secondary',
        }
        is_dark = False
        try:
            from aot.config import THEMES_DARK
            if flask_login.current_user.is_authenticated:
                is_dark = flask_login.current_user.theme in THEMES_DARK
        except Exception:
            pass

        css_content += "\n:root {\n"
        for k, css_vars in var_map.items():
            value = theme_dict.get(k)
            if not value:
                # Use form default if DB entry is missing
                field = getattr(form, k, None)
                if field:
                    value = field.default

            if value:
                for v in css_vars:
                    if is_dark and v in dark_overridden:
                        continue
                    css_content += f"  {v}: {value};\n"
        css_content += "}\n"
    except Exception as e:
        logger.error(f"Error serving custom.css: {e}")
        
    response = Response(css_content, mimetype='text/css')
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    return response


@blueprint.route('/settings', methods=('GET', 'POST'))
@flask_login.login_required
def page_settings():
    return redirect('settings/general')


@blueprint.route('/output_mod/<output_id>/<channel>/<state>/<output_type>/<amount>')
@flask_login.login_required
def output_mod(output_id, channel, state, output_type, amount):
    """Manipulate output (using non-unique ID)"""
    if not utils_general.user_has_permission('edit_controllers'):
        return 'Insufficient user permissions to manipulate outputs'

    if is_int(channel):
        # if an integer was returned
        output_channel = int(channel)
    else:
        # if a channel ID was returned
        channel_dev = db_retrieve_table(OutputChannel).filter(
            OutputChannel.unique_id == channel).first()
        if channel_dev:
            output_channel = channel_dev.channel
        else:
            return f"Could not determine channel number from channel ID '{channel}'"

    daemon = DaemonControl()
    if (state in ['on', 'off'] and str_is_float(amount) and
            (
                (output_type == 'pwm' and float(amount) >= 0) or
                output_type in ['sec', 'vol', 'value']
            )):
        out_status = daemon.output_on_off(
            output_id,
            state,
            output_type=output_type,
            amount=float(amount),
            output_channel=output_channel)
        if out_status[0]:
            return f'ERROR: {out_status[1]}'
        else:
            return f'SUCCESS: {out_status[1]}'
    else:
        return 'ERROR: unknown parameters: ' \
               f'output_id: {output_id}, channel: {channel}, ' \
               f'state: {state}, output_type: {output_type}, amount: {amount}'


@blueprint.route('/note_attachment/<path:filename>')
@flask_login.login_required
def send_note_attachment(filename):
    """Return a file from the note attachment directory (supporting legacy paths)."""
    from flask import current_app
    
    # Check new path first (filename handles subdirectories like 2026/01/...)
    file_path = os.path.join(PATH_NOTE_ATTACHMENTS, filename)
    if not os.path.exists(file_path):
        # Fallback to legacy static path
        legacy_path = os.path.join(current_app.static_folder, 'uploads', 'notes', filename)
        if os.path.exists(legacy_path):
            file_path = legacy_path
        else:
            return "File not found", 404

    try:
        # Serve inline (no as_attachment=True)
        # Explicitly guess mimetype to ensure correct rendering (e.g. for images)
        mime_type, _ = mimetypes.guess_type(file_path)
        return send_file(file_path, mimetype=mime_type)
    except Exception:
        logger.exception("Send note attachment failed")
        return "Internal error", 500
@blueprint.route('/note_gallery/<unique_id>')
@flask_login.login_required
def note_gallery(unique_id):
    """Render a full-screen gallery for a specific note."""
    note = Notes.query.filter(Notes.unique_id == unique_id).first()
    if not note:
        return "Note not found", 404
    
    # Process files
    image_files = []
    if note.files:
        all_files = note.files.split(',')
        for f in all_files:
            f = f.trim() if hasattr(f, 'trim') else f.strip()
            ext = f.split('.')[-1].lower()
            if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic']:
                image_files.append(f)
                
    if not image_files:
        return "No images in this note", 404
        
    return render_template('tools/note_gallery.html', note=note, image_files=image_files)


@blueprint.route('/camera/<unique_id>/<img_type>/<filename>')
@flask_login.login_required
def camera_img_return_path(unique_id, img_type, filename):
    """Return an image from stills or time-lapses."""
    if img_type not in ['still', 'video', 'timelapse']:
        return "img_type not still, video, or timelapse"

    camera = Camera.query.filter(
        Camera.unique_id == unique_id).first()
    function = CustomController.query.filter(
        CustomController.unique_id == unique_id).first()

    if camera:
        camera_path = assure_path_exists(
            os.path.join(PATH_CAMERAS, camera.unique_id))
        if img_type == 'still':
            if camera.path_still:
                path = camera.path_still
            else:
                path = os.path.join(camera_path, img_type)
        elif img_type == 'timelapse':
            if camera.path_timelapse:
                path = camera.path_timelapse
            else:
                path = os.path.join(camera_path, img_type)
        else:
            return "Unknown Image Type"

        path_file = os.path.join(path, filename)
        if os.path.isfile(path_file) and os.path.abspath(path_file).startswith(path):
            return send_file(path_file, mimetype='image/jpeg')

        path_file = f"/tmp/{filename}"
        if os.path.exists(path_file) and os.path.abspath(path_file).startswith("/tmp"):
            return send_file(path_file, mimetype='image/jpeg')

    elif function:
        try:
            custom_options = json.loads(function.custom_options)
        except:
            custom_options = {}

        camera_path = assure_path_exists(
            os.path.join(PATH_CAMERAS, function.unique_id))

        if img_type == 'still':
            if ('custom_path_still' in custom_options and
                    custom_options['custom_path_still']):
                path = custom_options['custom_path_still']
            else:
                path = os.path.join(camera_path, img_type)
        elif img_type == 'video':
            if ('custom_path_video' in custom_options and
                    custom_options['custom_path_video']):
                path = custom_options['custom_path_video']
            else:
                path = os.path.join(camera_path, img_type)
        elif img_type == 'timelapse':
            if ('custom_path_timelapse' in custom_options and
                    custom_options['custom_path_timelapse']):
                path = custom_options['custom_path_timelapse']
            else:
                path = os.path.join(camera_path, img_type)
        else:
            return "Unknown Image Type"

        path_file = os.path.join(path, filename)
        if os.path.isfile(path_file) and os.path.abspath(path_file).startswith(path):
            if img_type == 'video':
                return send_file(path_file, download_name=filename)
            else:
                return send_file(path_file, mimetype='image/jpeg')

        path_file = f"/tmp/{filename}"
        if (os.path.exists(path_file) and
                os.path.abspath(path_file).startswith("/tmp")):
            if img_type == 'video':
                return send_file(path_file, download_name=filename)
            else:
                return send_file(path_file, mimetype='image/jpeg')

    return "Image not found"


def gen(camera):
    """Video streaming generator function."""
    while True:
        frame = camera.get_frame(timeout=camera.FRAME_WAIT_TIMEOUT)
        if frame is None:
            # 카메라가 계속 프레임을 못 만들고 있음(연결/인증 실패 등) — 요청
            # 스레드를 영구히 붙잡지 않도록 스트림을 종료한다.
            break
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@blueprint.route('/video_feed/<unique_id>')
@flask_login.login_required
def video_feed(unique_id):
    """Video streaming route. Put this in the src attribute of an img tag."""
    camera_options = Camera.query.filter(Camera.unique_id == unique_id).first()
    camera_stream = import_module('aot.aot_flask.camera.camera_' + camera_options.library).Camera
    camera_stream.set_camera_options(camera_options)
    return Response(gen(camera_stream(unique_id=unique_id)),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@blueprint.route('/outputstate')
@flask_login.login_required
def gpio_state():
    """Return all output states."""
    return jsonify(get_all_output_states())


@blueprint.route('/outputstate_unique_id/<unique_id>/<channel_id>')
@flask_login.login_required
def gpio_state_unique_id(unique_id, channel_id):
    """Return the GPIO state, for dashboard output."""
    # Robustly handle composite IDs (uuid::channel)
    if unique_id and '::' in unique_id:
        unique_id = unique_id.split('::')[0]

    channel = OutputChannel.query.filter(OutputChannel.unique_id == channel_id).first()
    daemon_control = DaemonControl()
    if channel:
        state = daemon_control.output_state(unique_id, channel.channel)
    else:
        # If looking up by channel UUID failed, try using channel_id as int if possible, or default to 0
        # This is a fallback for legacy or mismatched data
        try:
             chan_idx = int(channel_id)
        except:
             chan_idx = 0
        state = daemon_control.output_state(unique_id, chan_idx)
    
    return jsonify(state)


@blueprint.route('/inputstate')
@flask_login.login_required
def input_state_all():
    """Return activation states of all inputs."""
    states = {}
    inputs = Input.query.all()
    for inp in inputs:
        states[inp.unique_id] = bool(getattr(inp, 'is_activated', False))
    return jsonify(states)


@blueprint.route('/widget_execute/<unique_id>')
@flask_login.login_required
def widget_execute(unique_id):
    """Return the response from the execution of widget code."""
    daemon_control = DaemonControl()
    return_value = daemon_control.widget_execute(unique_id)
    return jsonify(return_value)


@blueprint.route('/time')
@flask_login.login_required
def get_time():
    """Return the current time."""
    from aot.utils.time_utils import get_local_now
    return jsonify(get_local_now().strftime('%m/%d %H:%M'))


@blueprint.route('/dl/<dl_type>/<path:filename>')
@flask_login.login_required
def download_file(dl_type, filename):
    """Serve log file to download."""
    if dl_type == 'log':
        return send_from_directory(LOG_PATH, filename, as_attachment=True)

    return '', 204


@blueprint.route('/last/<unique_id>/<measure_type>/<measurement_id>/<period>')
@flask_login.login_required
def last_data(unique_id, measure_type, measurement_id, period):
    """Return the most recent time and value from influxdb."""
    if not str_is_float(period):
        return '', 204

    if measure_type not in ['input', 'function', 'output', 'pid']:
        return '', 204

    measure = DeviceMeasurements.query.filter(
        DeviceMeasurements.unique_id == measurement_id).first()

    if measure:
        conversion = Conversion.query.filter(
            Conversion.unique_id == measure.conversion_id).first()
    else:
        conversion = None

    channel, unit, measurement = return_measurement_info(
        measure, conversion)

    if hasattr(measure, 'measurement_type') and measure.measurement_type == 'setpoint':
        setpoint_pid = PID.query.filter(PID.unique_id == measure.device_id).first()
        if setpoint_pid and ',' in setpoint_pid.measurement:
            pid_measurement = setpoint_pid.measurement.split(',')[1]
            setpoint_measurement = DeviceMeasurements.query.filter(
                DeviceMeasurements.unique_id == pid_measurement).first()
            if setpoint_measurement:
                conversion = Conversion.query.filter(
                    Conversion.unique_id == setpoint_measurement.conversion_id).first()
                _, unit, measurement = return_measurement_info(setpoint_measurement, conversion)

    try:
        if period != '0':
            data = query_string(
                unit, unique_id,
                measure=measurement, channel=channel,
                value='LAST', past_sec=period)
        else:
            data = query_string(
                unit, unique_id,
                measure=measurement, channel=channel, value='LAST')

        if not data:
            return '', 204

        live_data = []
        settings = Misc.query.first()
        if settings.measurement_db_name == 'influxdb':
            for table in data:
                for row in table.records:
                    if '_value' in row.values and '_time' in row.values:
                        live_data = f"[{row.values['_time'].timestamp()},{row.values['_value']}]"

        return Response(live_data, mimetype='text/json')
    except Exception as err:
        logger.exception(f"URL for 'last_data' raised and error: {err}")
        return '', 204

@blueprint.route('/past/<unique_id>/<measure_type>/<measurement_id>/<past_seconds>')
@flask_login.login_required
def past_data(unique_id, measure_type, measurement_id, past_seconds):
    """
    Return data from the past X seconds to now.
    Used for synchronous graph display.
    Wrapper around async_data.
    """
    try:
        past_sec_int = int(past_seconds)
    except:
        return '', 204

    if past_sec_int <= 0:
        return '', 204

    start_seconds = datetime.datetime.utcnow().timestamp() - past_sec_int
    return async_data(unique_id, measure_type, measurement_id, str(start_seconds), '0')


# ──────────────────────────────────────────────────────────────────────────
# Batch data endpoint
#
# Dashboards with many widgets each fire their own /last/... (current value) and
# /past/... (history) request on every poll tick. With the browser's ~6
# concurrent-connection cap per origin, dozens of widgets serialise into a long
# queue and the page renders blank while it drains. /data_batch collapses all of
# a tick's requests into ONE POST: the jQuery transport (aot-data-batch.js)
# coalesces matching GETs client-side, and here we resolve them together.
#
# 'last' items: metadata is resolved on the request thread (the Flask-scoped ORM
# session is not thread-safe), then the InfluxDB I/O runs concurrently — each
# query_string() opens its own client and uses the daemon session, both of which
# are safe off the request context. 'past' items reuse async_data() and run
# sequentially (graph widgets are few and that path is heavier/ORM-bound).
# ──────────────────────────────────────────────────────────────────────────
_BATCH_MAX_ITEMS = 300
_BATCH_MAX_WORKERS = 8


def _resolve_last_params(measurement_id):
    """Resolve (unit, channel, measurement) for a /last query on the request
    thread. Mirrors last_data()'s metadata block, including the setpoint special
    case. Returns None when the measurement cannot be resolved."""
    measure = DeviceMeasurements.query.filter(
        DeviceMeasurements.unique_id == measurement_id).first()
    if not measure:
        return None

    conversion = Conversion.query.filter(
        Conversion.unique_id == measure.conversion_id).first()
    channel, unit, measurement = return_measurement_info(measure, conversion)

    if getattr(measure, 'measurement_type', None) == 'setpoint':
        setpoint_pid = PID.query.filter(PID.unique_id == measure.device_id).first()
        if setpoint_pid and ',' in setpoint_pid.measurement:
            pid_measurement = setpoint_pid.measurement.split(',')[1]
            setpoint_measurement = DeviceMeasurements.query.filter(
                DeviceMeasurements.unique_id == pid_measurement).first()
            if setpoint_measurement:
                conversion = Conversion.query.filter(
                    Conversion.unique_id == setpoint_measurement.conversion_id).first()
                _, unit, measurement = return_measurement_info(
                    setpoint_measurement, conversion)

    return unit, channel, measurement


def _query_last_value(unique_id, unit, channel, measurement, period):
    """Run a single LAST InfluxDB query off the request thread. Returns
    [epoch_seconds, value] or None. Safe to call concurrently."""
    try:
        if period != '0':
            data = query_string(
                unit, unique_id, measure=measurement, channel=channel,
                value='LAST', past_sec=period)
        else:
            data = query_string(
                unit, unique_id, measure=measurement, channel=channel,
                value='LAST')
        if not data:
            return None
        for table in data:
            for row in table.records:
                if '_value' in row.values and '_time' in row.values:
                    return [row.values['_time'].timestamp(), row.values['_value']]
        return None
    except Exception as err:
        logger.debug(f"_query_last_value failed for {unique_id}: {err}")
        return None


def _past_payload(unique_id, measure_type, measurement_id, past_seconds):
    """Return the /past payload (list of [ts, value]) for one item, or None.
    Reuses async_data() and normalises its Response/tuple/str return shapes."""
    try:
        past_sec_int = int(past_seconds)
    except (TypeError, ValueError):
        return None
    if past_sec_int <= 0:
        return None
    start_seconds = datetime.datetime.utcnow().timestamp() - past_sec_int
    resp = async_data(
        unique_id, measure_type, measurement_id, str(start_seconds), '0')
    # async_data returns jsonify(...) on success, ('', 204) on no data, or a
    # plain string on lookup failure.
    if isinstance(resp, (tuple, str)):
        return None
    try:
        return resp.get_json()
    except Exception:
        return None


@blueprint.route('/data_batch', methods=['POST'])
@flask_login.login_required
def data_batch():
    """Resolve many /last and /past requests in a single round trip.

    Body:  {"items": [{"kind": "last"|"past", "unique_id", "measure_type",
                       "measurement_id", "period"}, ...]}
    Reply: {"results": [<payload> | null, ...]}  aligned to items order, where a
           'last' payload is [ts, value] and a 'past' payload is [[ts, value],...].
    """
    payload = request.get_json(silent=True) or {}
    items = payload.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({'results': []})
    items = items[:_BATCH_MAX_ITEMS]

    settings = Misc.query.first()
    db_name = settings.measurement_db_name if settings else None

    results = [None] * len(items)
    last_jobs = []  # (index, unique_id, unit, channel, measurement, period)

    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        unique_id = it.get('unique_id')
        measure_type = it.get('measure_type')
        measurement_id = it.get('measurement_id')
        period = str(it.get('period', '0'))
        if (not unique_id or not measurement_id or
                measure_type not in ('input', 'function', 'output', 'pid')):
            continue

        if it.get('kind') == 'past':
            results[i] = _past_payload(
                unique_id, measure_type, measurement_id, period)
            continue

        # kind == 'last' (default)
        if not str_is_float(period) or db_name != 'influxdb':
            continue
        resolved = _resolve_last_params(measurement_id)
        if not resolved:
            continue
        unit, channel, measurement = resolved
        last_jobs.append((i, unique_id, unit, channel, measurement, period))

    if last_jobs:
        max_workers = min(_BATCH_MAX_WORKERS, len(last_jobs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(
                    _query_last_value, j[1], j[2], j[3], j[4], j[5]): j[0]
                for j in last_jobs
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = None

    return jsonify({'results': results})


@blueprint.route('/export_data/<unique_id>/<measurement_id>/<start_seconds>/<end_seconds>')
@flask_login.login_required
def export_data(unique_id, measurement_id, start_seconds, end_seconds):
    """
    Return data from start_seconds to end_seconds from influxdb.
    Used for exporting data.
    """
    settings = Misc.query.first()
    output = Output.query.filter(Output.unique_id == unique_id).first()
    input_dev = Input.query.filter(Input.unique_id == unique_id).first()

    if output:
        name = output.name
    elif input_dev:
        name = input_dev.name
    else:
        name = None

    device_measurement = DeviceMeasurements.query.filter(
        DeviceMeasurements.unique_id == measurement_id).first()
    if device_measurement:
        conversion = Conversion.query.filter(
            Conversion.unique_id == device_measurement.conversion_id).first()
    else:
        conversion = None
    channel, unit, measurement = return_measurement_info(
        device_measurement, conversion)

    # Use timezone-aware conversion for export strings (UTC for InfluxDB)
    from aot.utils.time_utils import utc_now
    
    # start_seconds is expected to be a Unix timestamp (float)
    # timestamps are inherently UTC. 
    # We convert to a UTC-aware datetime for consistent formatting.
    start = datetime.datetime.fromtimestamp(float(start_seconds), datetime.timezone.utc)
    start_str = start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    
    end = datetime.datetime.fromtimestamp(float(end_seconds), datetime.timezone.utc)
    end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    data = query_string(
        unit, unique_id,
        measure=measurement, channel=channel,
        start_str=start_str, end_str=end_str)

    if not data:
        flash(gettext('No measurements to export in this time period'), 'error')
        return redirect(url_for('routes_page.page_export'))

    # Generate column names
    col_1 = 'timestamp (UTC)'
    col_2 = f'{name} {measurement} ({unique_id})'
    csv_filename = f'{unique_id}_{name}_{measurement}.csv'

    def iter_csv(_data):
        """Stream CSV file to user for download."""
        line = StringIO()
        writer = csv.writer(line)
        writer.writerow([col_1, col_2])

        if settings.measurement_db_name == 'influxdb':
            for table in _data:
                for row in table.records:
                    writer.writerow([row.values['_time'].timestamp(), row.values['_value']])
                    line.seek(0)
                    yield line.read()
                    line.truncate(0)
                    line.seek(0)

    response = Response(iter_csv(data), mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename="{csv_filename}"'
    return response


def _query_count_and_first_point(unit, device_id, measurement, channel, settings,
                                  start_str=None, end_str=None):
    """Query COUNT and first data point from InfluxDB for a given time range.

    Returns (count_points, first_point) or (None, None) if no data found.
    """
    data = query_string(
        unit, device_id,
        measure=measurement,
        channel=channel,
        start_str=start_str,
        end_str=end_str,
        value='COUNT')

    if not data:
        return None, None

    count_points = None
    if settings.measurement_db_name == 'influxdb':
        count_points = influxdb_get_count_points(data)

    data = query_string(
        unit, device_id,
        measure=measurement,
        channel=channel,
        start_str=start_str,
        end_str=end_str,
        limit=1)

    if not data:
        return None, None

    first_point = None
    if settings.measurement_db_name == 'influxdb':
        first_point = influxdb_get_first_point(data)

    return count_points, first_point


@blueprint.route('/async/<device_id>/<device_type>/<measurement_id>/<start_seconds>/<end_seconds>')
@flask_login.login_required
def async_data(device_id, device_type, measurement_id, start_seconds, end_seconds):
    """
    Return data from start_seconds to end_seconds from influxdb.
    Used for asynchronous graph display of many points (up to millions).
    """
    count_points = None
    first_point = None

    settings = Misc.query.first()

    if device_type == 'tag':
        notes_list = []
        tag = NoteTags.query.filter(NoteTags.unique_id == device_id).first()

        start = datetime.datetime.utcfromtimestamp(float(start_seconds))
        if end_seconds == '0':
            end = datetime.datetime.utcnow()
        else:
            end = datetime.datetime.utcfromtimestamp(float(end_seconds))

        notes = Notes.query.filter(
            and_(Notes.date_time >= start, Notes.date_time <= end)).all()
        for each_note in notes:
            if tag.unique_id in each_note.tags.split(','):
                notes_list.append(
                    [each_note.date_time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"), each_note.name, each_note.note])

        if notes_list:
            return jsonify(notes_list)
        else:
            return '', 204

    if device_type in ['input', 'function', 'output', 'pid']:
        measure = DeviceMeasurements.query.filter(
            DeviceMeasurements.unique_id == measurement_id).first()
    else:
        measure = None

    if not measure:
        return "Could not find measurement"

    if measure:
        conversion = Conversion.query.filter(
            Conversion.unique_id == measure.conversion_id).first()
    else:
        conversion = None
    channel, unit, measurement = return_measurement_info(
        measure, conversion)

    # Get all data if start/end not specified
    if start_seconds == '0' and end_seconds == '0':
        end = datetime.datetime.utcnow()
        end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        count_points, first_point = _query_count_and_first_point(
            unit, device_id, measurement, channel, settings)

    # Set the time frame to the past start epoch to now
    elif start_seconds != '0' and end_seconds == '0':
        start = datetime.datetime.utcfromtimestamp(float(start_seconds))
        start_str = start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        end = datetime.datetime.utcnow()
        end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        count_points, first_point = _query_count_and_first_point(
            unit, device_id, measurement, channel, settings,
            start_str=start_str, end_str=end_str)

    else:
        start = datetime.datetime.utcfromtimestamp(float(start_seconds))
        start_str = start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        end = datetime.datetime.utcfromtimestamp(float(end_seconds))
        end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        count_points, first_point = _query_count_and_first_point(
            unit, device_id, measurement, channel, settings,
            start_str=start_str, end_str=end_str)

    if count_points is None or first_point is None:
        return '', 204

    start_str = first_point.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    logger.debug(f'Count = {count_points}')
    logger.debug(f'Start = {first_point}')
    logger.debug(f'End   = {end}')

    # How many seconds between the start and end period
    time_difference_seconds = end.timestamp() - first_point.timestamp()
    logger.debug(f'Difference seconds = {time_difference_seconds}')

    # If there are more than 700 points in the time frame, we need to group
    # data points into 700 groups with points averaged in each group.
    if count_points > 700:
        # Average period between input reads
        seconds_per_point = time_difference_seconds / count_points
        logger.debug(f'Seconds per point = {seconds_per_point}')

        # How many seconds to group data points in
        group_seconds = int(time_difference_seconds / 700)
        logger.debug(f'Group seconds = {group_seconds}')

        try:
            data = query_string(
                unit, device_id,
                measure=measurement,
                channel=channel,
                start_str=start_str,
                end_str=end_str,
                group_sec=group_seconds)

            if not data:
                return '', 204

            if settings.measurement_db_name == 'influxdb':
                return jsonify(influx_to_list(data))
        except Exception as err:
            logger.error(f"URL for 'async_data' raised and error: {err}")
            return '', 204
    else:
        try:
            data = query_string(
                unit, device_id,
                measure=measurement,
                channel=channel,
                start_str=start_str,
                end_str=end_str)

            if not data:
                return '', 204

            if settings.measurement_db_name == 'influxdb':
                return jsonify(influx_to_list(data))
        except Exception as err:
            logger.error(f"URL for 'async_data' raised and error: {err}")
            return '', 204


@blueprint.route('/async_usage/<device_id>/<unit>/<channel>/<start_seconds>/<end_seconds>')
@flask_login.login_required
def async_usage_data(device_id, unit, channel, start_seconds, end_seconds):
    """
    Return data from start_seconds to end_seconds from influxdb.
    Used for asynchronous energy usage display of many points (up to millions).
    """
    settings = Misc.query.first()

    first_point = None

    # Set the time frame to the past year if start/end not specified
    if start_seconds == '0' and end_seconds == '0':
        # Get how many points there are in the past year
        end = datetime.datetime.utcnow()
        end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        start = datetime.datetime.utcfromtimestamp(float(end.timestamp() - 60 * 60 * 24 * 365))
        start_str = start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        data = query_string(
            unit, device_id,
            channel=channel,
            value='COUNT',
            start_str=start_str,
            end_str=end_str)

        if not data:
            return '', 204

        if settings.measurement_db_name == 'influxdb':
            count_points = influxdb_get_count_points(data)

        # Get the timestamp of the first point in the past year
        data = query_string(
            unit, device_id,
            channel=channel,
            limit=1)

        if not data:
            return '', 204

        if settings.measurement_db_name == 'influxdb':
            first_point = influxdb_get_first_point(data)

    # Set the time frame to the past start epoch to now
    elif start_seconds != '0' and end_seconds == '0':
        start = datetime.datetime.utcfromtimestamp(float(start_seconds))
        start_str = start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        end = datetime.datetime.utcnow()
        end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        data = query_string(
            unit, device_id,
            channel=channel,
            value='COUNT',
            start_str=start_str,
            end_str=end_str)

        if not data:
            return '', 204

        if settings.measurement_db_name == 'influxdb':
            count_points = influxdb_get_count_points(data)

        # Get the timestamp of the first point in the past year
        data = query_string(
            unit, device_id,
            channel=channel,
            start_str=start_str,
            end_str=end_str,
            limit=1)

        if not data:
            return '', 204

        if settings.measurement_db_name == 'influxdb':
            first_point = influxdb_get_first_point(data)
    else:
        start = datetime.datetime.utcfromtimestamp(float(start_seconds))
        start_str = start.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        end = datetime.datetime.utcfromtimestamp(float(end_seconds))
        end_str = end.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        data = query_string(
            unit, device_id,
            channel=channel,
            value='COUNT',
            start_str=start_str,
            end_str=end_str)

        if not data:
            return '', 204

        if settings.measurement_db_name == 'influxdb':
            count_points = influxdb_get_count_points(data)

        # Get the timestamp of the first point in the past year
        data = query_string(
            unit, device_id,
            channel=channel,
            start_str=start_str,
            end_str=end_str,
            limit=1)

        if not data:
            return '', 204

        if settings.measurement_db_name == 'influxdb':
            first_point = influxdb_get_first_point(data)

    if not first_point:
        logger.error("No first point")
        return '', 204

    start_str = first_point.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    logger.debug(f'Count = {count_points}')
    logger.debug(f'Start = {start}')
    logger.debug(f'End   = {end}')

    # How many seconds between the start and end period
    time_difference_seconds = (end - start).total_seconds()
    logger.debug(f'Difference seconds = {time_difference_seconds}')

    # If there are more than 700 points in the time frame, we need to group
    # data points into 700 groups with points averaged in each group.
    if count_points > 700:
        # Average period between input reads
        seconds_per_point = time_difference_seconds / count_points
        logger.debug(f'Seconds per point = {seconds_per_point}')

        # How many seconds to group data points in
        group_seconds = int(time_difference_seconds / 700)
        logger.debug(f'Group seconds = {group_seconds}')

        try:
            data = query_string(
                unit, device_id,
                channel=channel,
                start_str=start_str,
                end_str=end_str,
                group_sec=group_seconds)

            if not data:
                return '', 204

            if settings.measurement_db_name == 'influxdb':
                return jsonify(influx_to_list(data))
        except Exception as err:
            logger.error(f"URL for 'async_data' raised and error: {err}")
            return '', 204
    else:
        try:
            data = query_string(
                unit, device_id,
                channel=channel,
                start_str=start_str,
                end_str=end_str)

            if not data:
                return '', 204

            if settings.measurement_db_name == 'influxdb':
                return jsonify(influx_to_list(data))
        except Exception as err:
            logger.error(f"URL for 'async_usage' raised and error: {err}")
            return '', 204


@blueprint.route('/daemonactive')
@flask_login.login_required
def daemon_active():
    """Return 'alive' if the daemon is running."""
    try:
        control = DaemonControl()
        return control.daemon_status()
    except Exception as err:
        logger.error(f"URL for 'daemon_active' raised and error: {err}")
        return '0'


@blueprint.route('/systemctl/<action>')
@flask_login.login_required
def computer_command(action):
    """Execute one of several commands as root."""
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    try:
        if action not in ['restart', 'shutdown', 'daemon_restart', 'frontend_reload']:
            flash(gettext("Unrecognized command: %(action)s", action=action), "success")
            return redirect('/settings')

        if action == 'daemon_restart':
            restart_daemon(logger=logger)
        elif action == 'frontend_reload':
            logger.info("Reloading frontend in 10 seconds")
            reload_frontend(delay_sec=10, logger=logger)
        elif DOCKER_CONTAINER:
            # restart/shutdown are host-level commands (systemd installs only)
            flash(gettext("'%(action)s' is not supported in Docker", action=action), "error")
            return redirect('/settings')
        else:
            cmd = f'{INSTALL_DIRECTORY}/aot/scripts/aot_wrapper {action} 2>&1'
            subprocess.Popen(cmd, shell=True)

        if action == 'restart':
            flash(gettext("System rebooting in 10 seconds"), "success")
        elif action == 'shutdown':
            flash(gettext("System shutting down in 10 seconds"), "success")
        elif action == 'daemon_restart':
            flash(gettext("Command to restart the daemon sent"), "success")
        elif action == 'frontend_reload':
            flash(gettext("Frontend reloading in 10 seconds"), "success")

        return redirect('/settings')

    except Exception as err:
        logger.error(f"System command '{action}' raised and error: {err}")
        flash(gettext("System command '%(action)s' raised and error: %(err)s", action=action, err=err), "error")
        return redirect(url_for('routes_general.home'))


# @blueprint.route('/generate_thermal_image/<unique_id>/<timestamp>')
# @flask_login.login_required
# def generate_thermal_image_from_timestamp(unique_id, timestamp):
#     """Return a file from the note attachment directory."""
#     ts_now = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
#     camera_path = assure_path_exists(
#         os.path.join(PATH_CAMERAS, unique_id))
#     filename = f'Still-{unique_id}-{ts_now}.jpg'.replace(" ", "_")
#     save_path = assure_path_exists(os.path.join(camera_path, 'thermal'))
#     assure_path_exists(save_path)
#     path_file = os.path.join(save_path, filename)
#
#     input_dev = Input.query.filter(Input.unique_id == unique_id).first()
#     pixels = []
#     success = True
#
#     start = int(int(timestamp) / 1000.0)  # Round down
#     end = start + 1  # Round up
#
#     start_timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000000000Z', time.gmtime(start))
#     end_timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000000000Z', time.gmtime(end))
#
#     for each_channel in range(input_dev.channels):
#         measurement = f'channel_{each_channel}'
#         data = query_string(measurement, unique_id,
#                                  start_str=start_timestamp,
#                                  end_str=end_timestamp)
#
#         if not data:
#             logger.error('No measurements to export in this time period')
#             success = False
#         else:
#             pixels.append(data[0][1])
#
#     if success:
#         from aot.utils.image import generate_thermal_image_from_pixels
#         generate_thermal_image_from_pixels(pixels, 8, 8, path_file)
#         return send_file(path_file, mimetype='image/jpeg')
#     else:
#         return "Could not generate image"

# ==============================================================================
#  Decoupled Timestamp API (Formerly in AoT_timer.py)
# ==============================================================================

def _resolve_channel_index(device_unique_id, channel_id):
    """
    Returns an integer channel index if resolvable, else None.
    Accepts either plain integer strings (e.g., '0') or OutputChannel.unique_id (UUID).
    """
    # Fast path: integer-like channel_id
    try:
        if isinstance(channel_id, int): return channel_id
        return int(channel_id)
    except Exception:
        pass
    # UUID path: look up OutputChannel by unique_id
    try:
        from aot.utils.database import db_retrieve_table_daemon # Import locally to avoid circular
        oc = db_retrieve_table_daemon(OutputChannel).filter(OutputChannel.unique_id == channel_id).first()
        if oc is not None and getattr(oc, 'channel', None) is not None:
            return int(getattr(oc, 'channel'))
    except Exception as e:
        logger.debug(f"_resolve_channel_index lookup failed for device {device_unique_id}, channel_id {channel_id}: {e}")
    return None

# Note: _read_latest_started_at_safe is now handled by aot.utils.runtime.get_started_at

@blueprint.route('/output_started_at_public/<string:device_unique_id>/<string:channel_id>')
def output_started_at_public(device_unique_id, channel_id):
    """
    Returns the most recent ON start timestamp for this output/channel.
    Response includes both started_at_epoch and elapsed_sec so the frontend
    can show the correct running time even when InfluxDB data is unavailable.

    Fallback chain:
      1. InfluxDB output_started_at measurement
      2. Daemon output_sec_currently_on (compute start = now - elapsed)
      3. 204 No Content
    """
    try:
        import time as _time
        from aot.utils.runtime import get_started_at

        # --- Primary path: get start epoch ---
        started_ts = get_started_at(device_unique_id, channel_id)

        # --- Secondary path: daemon elapsed seconds ---
        elapsed_sec = None
        try:
            from aot.aot_client import DaemonControl
            from aot.utils.runtime import _resolve_channel_index
            ch_idx = _resolve_channel_index(device_unique_id, channel_id)
            if ch_idx is None:
                try:
                    ch_idx = int(channel_id)
                except (TypeError, ValueError):
                    ch_idx = 0
            ctrl = DaemonControl()
            state = ctrl.output_state(device_unique_id, output_channel=ch_idx)
            if state == 'on' or (isinstance(state, (int, float)) and state > 0):
                raw = ctrl.output_sec_currently_on(device_unique_id, output_channel=ch_idx)
                if raw is not None and float(raw) > 0:
                    elapsed_sec = int(float(raw))
                    # Compute start epoch from elapsed if primary path failed
                    if started_ts is None:
                        started_ts = int(_time.time()) - elapsed_sec
        except Exception:
            pass

        if started_ts is None:
            return '', 204

        now_epoch = int(_time.time())
        if elapsed_sec is None:
            elapsed_sec = max(0, now_epoch - int(started_ts))

        started_dt = datetime.datetime.utcfromtimestamp(int(started_ts)).replace(tzinfo=timezone('UTC'))
        payload = {
            "started_at_epoch": int(started_ts),
            "started_at_iso": started_dt.isoformat(),
            "elapsed_sec": elapsed_sec,      # JS가 직접 사용 가능한 경과 초
            "server_now_epoch": now_epoch,   # 서버-클라이언트 시계 보정용
            "source": "runtime_service"
        }
        return jsonify(payload)
    except Exception as e:
        logger.debug(f"output_started_at_public error: {e}")
        return '', 204


# ══════════════════════════════════════════════════════════════════════════════
# Geo / Facility — Model Asset API (Phase 1)
# ══════════════════════════════════════════════════════════════════════════════

@blueprint.route('/geo/model_assets')
@flask_login.login_required
def geo_model_assets_page():
    """Asset library page (D-plan main entry)."""
    from aot.aot_flask.routes_static import inject_variables
    from aot.databases.models import GeoSetting
    setting = GeoSetting.query.first()
    return render_template(
        'pages/geo_model_assets.html',
        length_unit=(setting.length_unit if setting else 'm'),
        **inject_variables(),
    )


@blueprint.route('/api/geo/model_assets', methods=['GET'])
@flask_login.login_required
def api_geo_model_assets_list():
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    kind = request.args.get('kind')
    tag = request.args.get('tag')
    uid = flask_login.current_user.id if flask_login.current_user.is_authenticated else None
    assets, err = ModelAssetManager.list_assets(owner_user_id=uid, kind=kind, tag=tag)
    if err:
        return jsonify({'error': err}), 500
    return jsonify(assets)


@blueprint.route('/api/geo/model_assets', methods=['POST'])
@flask_login.login_required
def api_geo_model_assets_create():
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    file_storage = request.files.get('file')
    if request.is_json:
        data = request.get_json(force=True) or {}
    else:
        data = request.form.to_dict()
        import json as _json
        if 'spec_json' in data:
            try:
                data['spec_json'] = _json.loads(data['spec_json'])
            except Exception:
                pass

    uid = flask_login.current_user.id if flask_login.current_user.is_authenticated else None
    asset, err = ModelAssetManager.create_asset(data, file_storage=file_storage, owner_user_id=uid)
    if err:
        return jsonify({'error': err}), 400
    return jsonify(asset), 201


@blueprint.route('/api/geo/model_assets/<string:asset_uuid>', methods=['GET'])
@flask_login.login_required
def api_geo_model_asset_get(asset_uuid):
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    asset, err = ModelAssetManager.get_asset(asset_uuid)
    if err:
        return jsonify({'error': err}), 404
    return jsonify(asset)


@blueprint.route('/api/geo/model_assets/<string:asset_uuid>', methods=['PUT'])
@flask_login.login_required
def api_geo_model_asset_update(asset_uuid):
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    data = request.get_json(force=True) or {}
    asset, err = ModelAssetManager.update_asset(asset_uuid, data)
    if err:
        return jsonify({'error': err}), 400
    return jsonify(asset)


@blueprint.route('/api/geo/model_assets/<string:asset_uuid>', methods=['DELETE'])
@flask_login.login_required
def api_geo_model_asset_delete(asset_uuid):
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    _, err, ref_names = ModelAssetManager.delete_asset(asset_uuid)
    if err:
        if ref_names:
            return jsonify({'error': err, 'referencing_facilities': ref_names}), 409
        return jsonify({'error': err}), 404
    return jsonify({'deleted': asset_uuid}), 200


@blueprint.route('/api/geo/model_assets/<string:asset_uuid>/regenerate_preview', methods=['POST'])
@flask_login.login_required
def api_geo_model_asset_preview(asset_uuid):
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    from aot.aot_flask.geo.preview_renderer import render_preview
    from aot.databases.models import GeoModelAsset
    row = GeoModelAsset.query.filter_by(unique_id=asset_uuid).first()
    if not row:
        return jsonify({'error': 'Asset not found'}), 404
    try:
        render_preview(row)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'preview_png': row.preview_png, 'preview_status': row.preview_status})


@blueprint.route('/api/geo/facility/<string:facility_uuid>/attach_model', methods=['POST'])
@flask_login.login_required
def api_geo_facility_attach_model(facility_uuid):
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    data = request.get_json(force=True) or {}
    asset_uuid = data.get('asset_uuid')
    if not asset_uuid:
        return jsonify({'error': 'asset_uuid required'}), 400
    result, err = ModelAssetManager.attach_to_facility(facility_uuid, asset_uuid, data.get('transform'))
    if err:
        return jsonify({'error': err}), 400
    return jsonify(result)


@blueprint.route('/api/geo/facility/<string:facility_uuid>/attach_model', methods=['DELETE'])
@flask_login.login_required
def api_geo_facility_detach_model(facility_uuid):
    from aot.aot_flask.geo.model_asset_io import ModelAssetManager
    result, err = ModelAssetManager.detach_from_facility(facility_uuid)
    if err:
        return jsonify({'error': err}), 400
    return jsonify(result)


@blueprint.route('/api/geo/settings/length_unit', methods=['GET', 'PUT'])
@flask_login.login_required
def api_geo_length_unit():
    from aot.databases.models import GeoSetting
    from aot.aot_flask.geo.units import SUPPORTED_UNITS
    setting = GeoSetting.query.first()
    if not setting:
        return jsonify({'error': 'GeoSetting not initialized'}), 500

    if request.method == 'GET':
        return jsonify({'length_unit': setting.length_unit or 'm', 'supported': list(SUPPORTED_UNITS)})

    data = request.get_json(force=True) or {}
    unit = data.get('length_unit', 'm')
    if unit not in SUPPORTED_UNITS:
        return jsonify({'error': f"Invalid unit '{unit}'. Supported: {SUPPORTED_UNITS}"}), 400
    setting.length_unit = unit
    from aot.aot_flask.extensions import db
    db.session.commit()
    # Keep the cached geo config in sync — otherwise the change is invisible for
    # up to the cache TTL (get_geo_config feeds window.AOT_GEO_CONFIG).
    from aot.aot_flask.utils.utils_geo import invalidate_geo_config_cache
    invalidate_geo_config_cache()
    return jsonify({'length_unit': setting.length_unit})
