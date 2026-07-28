# coding=utf-8
import logging
import operator
import os
import socket
import subprocess
import traceback
import time
from io import BytesIO

import flask_login
from flask import (current_app, redirect, render_template, request,
                   send_from_directory, url_for)
from flask import send_file
from flask.blueprints import Blueprint

from aot.config import (ALEMBIC_VERSION, INSTALL_DIRECTORY, LANGUAGES,
                           AOT_VERSION, THEMES, THEMES_DARK,
                           GRAPH_SERIES_PALETTE, GRAPH_SERIES_PALETTE_DARK)


def _graph_palette(dark):
    """차트 시리즈 팔레트 — custom_ui 사용자 오버레이 적용, 실패 시 기본 상수."""
    try:
        from aot.aot_flask.utils.utils_theme import get_graph_series_palette
        return get_graph_series_palette(dark=dark)
    except Exception:
        return GRAPH_SERIES_PALETTE_DARK if dark else GRAPH_SERIES_PALETTE
from aot.config import PATH_STATIC
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Dashboard, Misc
from aot.aot_client import DaemonControl
from aot.aot_flask.forms import forms_dashboard
from aot.aot_flask.routes_authentication import admin_exists
from aot.aot_flask.utils.utils_general import is_hex_color_light, user_has_permission
from aot.aot_flask.extensions import db

blueprint = Blueprint('routes_static',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')

logger = logging.getLogger(__name__)

_daemon_status_cache = {'value': '0', 'ts': 0.0}
_DAEMON_STATUS_TTL = 30.0

_INJECT_CACHE_TTL = 10.0
_misc_cache = {'obj': None, 'ts': 0.0}
_dashboards_cache = {'objs': None, 'ts': 0.0}
_api_keys_cache = {'objs': None, 'ts': 0.0}
_ai_settings_cache = {'obj': None, 'ts': 0.0}


def _cached_misc():
    now = time.time()
    if now - _misc_cache['ts'] < _INJECT_CACHE_TTL and _misc_cache['obj'] is not None:
        return _misc_cache['obj']
    obj = Misc.query.first()
    try:
        db.session.expunge(obj)
    except Exception:
        pass
    _misc_cache['obj'] = obj
    _misc_cache['ts'] = now
    return obj


def invalidate_misc_cache():
    """settings 저장 직후 stale 값이 렌더링되지 않도록 inject_variables()의 Misc 캐시를 즉시 만료시킨다."""
    _misc_cache['obj'] = None
    _misc_cache['ts'] = 0.0


def _cached_dashboards():
    now = time.time()
    if now - _dashboards_cache['ts'] < _INJECT_CACHE_TTL and _dashboards_cache['objs'] is not None:
        return _dashboards_cache['objs']
    try:
        rows = db.session.execute(db.text(
            "SELECT unique_id FROM dashboard ORDER BY COALESCE(sort_order, 999999), id"
        ))
        ordered_uids = [r[0] for r in rows]
        if ordered_uids:
            dash_map = {d.unique_id: d for d in Dashboard.query.filter(Dashboard.unique_id.in_(ordered_uids)).all()}
            objs = [dash_map[uid] for uid in ordered_uids if uid in dash_map]
        else:
            objs = Dashboard.query.order_by(Dashboard.id.asc()).all()
    except Exception:
        objs = Dashboard.query.order_by(Dashboard.id.asc()).all()
    for o in objs:
        try:
            db.session.expunge(o)
        except Exception:
            pass
    _dashboards_cache['objs'] = objs
    _dashboards_cache['ts'] = now
    return objs


def _cached_api_keys():
    from aot.databases.models import APIKey
    now = time.time()
    if now - _api_keys_cache['ts'] < _INJECT_CACHE_TTL and _api_keys_cache['objs'] is not None:
        return _api_keys_cache['objs']
    objs = APIKey.query.all()
    for o in objs:
        try:
            db.session.expunge(o)
        except Exception:
            pass
    _api_keys_cache['objs'] = objs
    _api_keys_cache['ts'] = now
    return objs


def _cached_ai_settings():
    from aot.databases.models import AIGlobalSettings
    now = time.time()
    if now - _ai_settings_cache['ts'] < _INJECT_CACHE_TTL and _ai_settings_cache['obj'] is not None:
        return _ai_settings_cache['obj']
    obj = AIGlobalSettings.query.first()
    if obj is not None:
        try:
            db.session.expunge(obj)
        except Exception:
            pass
    _ai_settings_cache['obj'] = obj
    _ai_settings_cache['ts'] = now
    return obj



def before_request_admin_exist():
    """
    Ensure databases exist and at least one user is in the user database.
    """
    if not admin_exists():
        return redirect(url_for("routes_authentication.create_admin"))
blueprint.before_request(before_request_admin_exist)


def template_exists(path):
    path_start = "{}/aot/aot_flask/templates".format(INSTALL_DIRECTORY)
    path_full = "{}/{}".format(path_start, path)
    if os.path.exists(path_full) and os.path.abspath(path_full).startswith(path_start):
        return True


@blueprint.app_context_processor
def inject_variables():
    """Variables to send with every page request."""
    form_dashboard = forms_dashboard.DashboardConfig()
    dashboards = _cached_dashboards()
    misc = _cached_misc()

    try:
        if not current_app.config['TESTING']:
            now = time.time()
            if now - _daemon_status_cache['ts'] > _DAEMON_STATUS_TTL:
                control = DaemonControl()
                _daemon_status_cache['value'] = control.daemon_status()
                _daemon_status_cache['ts'] = now
            daemon_status = _daemon_status_cache['value']
        else:
            daemon_status = '0'
    except Exception as e:
        logger.debug("URL for 'inject_variables' raised and error: "
                     "{err}".format(err=e))
        daemon_status = '0'

    languages_sorted = sorted(LANGUAGES.items(), key=operator.itemgetter(1))

    import json
    try:
        custom_theme = json.loads(misc.custom_theme_json or '{}')
    except Exception:
        custom_theme = {}

    # nav-bar 관리 메뉴의 "업그레이드" 항목: settings/custom_ui 의 bg_upgrade
    # 배경색 밝기에 따라 텍스트를 기본/3차 색 중 무엇으로 할지 서버에서 미리 판정.
    try:
        bg_upgrade_value = custom_theme.get('bg_upgrade')
        if not bg_upgrade_value:
            from aot.aot_flask.forms.forms_settings import SettingsCustomUI
            bg_upgrade_value = SettingsCustomUI().bg_upgrade.default
        upgrade_bg_is_light = is_hex_color_light(bg_upgrade_value)
    except Exception:
        upgrade_bg_is_light = True

    from aot.aot_flask.utils.utils_geo import get_geo_config
    geo_config = get_geo_config()
    map_global_providers = geo_config.get('providers', {}) if geo_config else {}
    map_global_keys = geo_config.get('keys', {}) if geo_config else {}

    api_keys = _cached_api_keys()
    ai_settings = _cached_ai_settings()

    # MapLibre(~775KB) 전역 스택은 head 에서 동기 로드되어 렌더를 차단한다. 지도가
    # 전혀 없는 텍스트 페이지에서는 불필요하므로 끈다. 기본은 로드(True)로 두어
    # 지도 페이지/위젯의 무회귀를 보장하고(미식별 시에도 안전), 지도 템플릿이
    # 전혀 없음이 확인된 순수 텍스트 블루프린트에서만 끈다.
    # 지도 보유 블루프린트(유지): routes_geo / routes_input / routes_output /
    #   routes_function, 위젯 호스트 routes_dashboard / routes_page / routes_general.
    map_free_blueprints = {'routes_settings', 'routes_method', 'routes_scheduler'}
    try:
        needs_map = request.blueprint not in map_free_blueprints
    except Exception:
        needs_map = True

    return dict(current_user=flask_login.current_user,
                needs_map=needs_map,
                geo_config=geo_config,
                custom_css=(bool(misc.custom_css) or (misc.custom_theme_json and misc.custom_theme_json != '{}')),
                custom_theme=custom_theme,
                dark_themes=THEMES_DARK,
                graph_series_palette=_graph_palette(dark=False),
                graph_series_palette_dark=_graph_palette(dark=True),
                daemon_status=daemon_status,
                dashboards=dashboards,
                form_dashboard=form_dashboard,
                hide_alert_info=misc.hide_alert_info,
                hide_alert_success=misc.hide_alert_success,
                hide_alert_warning=misc.hide_alert_warning,
                hide_tooltips=misc.hide_tooltips,
                host=socket.gethostname(),
                languages=languages_sorted,
                aot_version=AOT_VERSION,
                permission_view_settings=user_has_permission('view_settings', silent=True),
                permission_edit_settings=user_has_permission('edit_settings', silent=True),
                dict_translation=TRANSLATIONS,
                settings=misc,
                template_exists=template_exists,
                themes=THEMES,
                upgrade_available=misc.aot_upgrade_available,
                upgrade_bg_is_light=upgrade_bg_is_light,
                map_global_providers=map_global_providers,
                map_global_keys=map_global_keys,
                api_keys=api_keys,
                ai_settings=ai_settings,
                now_timestamp=int(time.time()))


@blueprint.app_errorhandler(404)
def not_found(error):
    return render_template('404.html', error=error), 404


@blueprint.route('/favicon.png')
def favicon():
    """Return favicon image"""
    misc = Misc.query.first()

    if misc.favicon_display == 'default':
        return send_from_directory(os.path.join(PATH_STATIC, 'img'), "favicon.png")
    else:
        return send_file(
            BytesIO(misc.brand_favicon),
            mimetype='image/png'
        )


@blueprint.route('/robots.txt')
def static_from_root():
    """Return static robots.txt."""
    return send_from_directory(current_app.static_folder, request.path[1:])


@blueprint.route('/csrf-token')
def csrf_token():
    """Re-sign a fresh CSRF token for the current session.

    WTF_CSRF_TIME_LIMIT is bounded (not None) so a token embedded in a page
    left open for a long time eventually expires. generate_csrf() re-signs
    the *same* session-bound secret with a current timestamp — it doesn't
    rotate the secret or require login — so calling this periodically from
    aot-csrf-refresh.js keeps long-open pages valid without weakening
    anything. No permission check needed: refreshing a token grants nothing
    beyond what the session already had.
    """
    from flask_wtf.csrf import generate_csrf
    return {'csrf_token': generate_csrf()}


# @blueprint.route("/aot-manual_{}.pdf".format(AOT_VERSION))
# def download_pdf_manual():
#     """Return PDF Manual."""
#     path_manual = os.path.join(INSTALL_DIRECTORY, "docs")
#     return send_from_directory(path_manual, "aot-manual.pdf")


@blueprint.app_errorhandler(404)
def not_found(error):
    return render_template('404.html', error=error), 404


@blueprint.app_errorhandler(500)
def page_error(error):
    try:
        trace = traceback.format_exc()
    except:
        trace = None

    try:
        lsb_release = subprocess.Popen(
            "lsb_release -irdc", stdout=subprocess.PIPE, shell=True)
        (lsb_release_output, _) = lsb_release.communicate()
        lsb_release.wait()
        if lsb_release_output:
            lsb_release_output = lsb_release_output.decode("latin1").replace("\n", "<br/>")
    except:
        lsb_release_output = None

    try:
        model = subprocess.Popen(
            "cat /proc/device-tree/model && echo", stdout=subprocess.PIPE, shell=True)
        (model_output, _) = model.communicate()
        model.wait()
        if model_output:
            model_output = model_output.decode("latin1")
    except:
        model_output = None

    dict_return = {
        "trace": trace,
        "version_aot": AOT_VERSION,
        "version_alembic":  ALEMBIC_VERSION,
        "lsb_release": lsb_release_output,
        "model": model_output
    }

    return render_template('500.html', dict_return=dict_return), 500
