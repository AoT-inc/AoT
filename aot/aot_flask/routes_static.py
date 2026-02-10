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
                           AOT_VERSION, THEMES, THEMES_DARK)
from aot.config import PATH_STATIC
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Dashboard, Misc, GeoSetting
from aot.aot_client import DaemonControl
from aot.aot_flask.forms import forms_dashboard
from aot.aot_flask.routes_authentication import admin_exists
from aot.aot_flask.utils.utils_general import user_has_permission
from aot.aot_flask.extensions import db

blueprint = Blueprint('routes_static',
                      __name__,
                      static_folder='../static',
                      template_folder='../templates')

logger = logging.getLogger(__name__)


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


@blueprint.context_processor
def inject_variables():
    """Variables to send with every page request."""
    try:
        db.session.expire_all()
    except Exception:
        pass
    
    form_dashboard = forms_dashboard.DashboardConfig()  # Dashboard configuration in layout

    # Order dashboards via raw SQL to avoid any ORM caching/NULLS LAST portability issues
    try:
        rows = db.session.execute(db.text(
            "SELECT unique_id FROM dashboard ORDER BY COALESCE(sort_order, 999999), id"
        ))
        ordered_uids = [r[0] for r in rows]
        if ordered_uids:
            dash_map = {d.unique_id: d for d in Dashboard.query.filter(Dashboard.unique_id.in_(ordered_uids)).all()}
            dashboards = [dash_map[uid] for uid in ordered_uids if uid in dash_map]
        else:
            dashboards = Dashboard.query.order_by(Dashboard.id.asc()).all()
    except Exception:
        # Fallback: at least return something if the table/column isn't ready yet
        dashboards = Dashboard.query.order_by(Dashboard.id.asc()).all()
    misc = Misc.query.first()

    try:
        if not current_app.config['TESTING']:
            control = DaemonControl()
            daemon_status = control.daemon_status()
        else:
            daemon_status = '0'
    except Exception as e:
        logger.debug("URL for 'inject_variables' raised and error: "
                     "{err}".format(err=e))
        daemon_status = '0'

    languages_sorted = sorted(LANGUAGES.items(), key=operator.itemgetter(1))

    # Map Global Settings
    map_global_providers = {}
    map_global_keys = {}
    try:
        mgs = GeoSetting.query.first()
        if mgs:
            state = mgs.state_dict()
            map_global_providers = state.get('providers', {})
            map_global_keys = state.get('keys', {})
    except Exception:
        pass

    # Global Geo Config
    from aot.aot_flask.utils.utils_geo import get_geo_config
    geo_config = get_geo_config()

    # API Keys
    from aot.databases.models import APIKey
    api_keys = APIKey.query.all()

    return dict(current_user=flask_login.current_user,
                geo_config=geo_config,
                custom_css=misc.custom_css,
                dark_themes=THEMES_DARK,
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
                dict_translation=TRANSLATIONS,
                settings=misc,
                template_exists=template_exists,
                themes=THEMES,
                upgrade_available=misc.aot_upgrade_available,
                map_global_providers=map_global_providers,
                map_global_keys=map_global_keys,
                api_keys=api_keys,
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
