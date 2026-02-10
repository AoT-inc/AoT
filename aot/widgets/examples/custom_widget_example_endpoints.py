# coding=utf-8
#
#  이 소프트웨어는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로,
#  AoT 프로젝트 목적에 맞게 수정된 파생 버전입니다.
#  This software is a derivative work of the open-source Mycodo project (© Kyle T. Gabriel),
#  modified by AoT for use in its own smart agriculture systems.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Copyright (C) 2015–2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  본 파일은 GNU General Public License, 버전 3 또는 그 이후 버전에 따라 배포됩니다.
#  This file is licensed under the GNU General Public License, version 3 or (at your option) any later version.
#
#  본 소프트웨어는 유용하게 사용될 수 있으리라는 기대 하에 배포되며,
#  상품성이나 특정 목적에의 적합성에 대한 어떠한 보증도 제공하지 않습니다.
#  This software is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
#  이 라이선스 사본은 함께 제공되어야 하며,
#  제공되지 않은 경우, 아래에서 확인할 수 있습니다:
#  You should have received a copy of the GNU General Public License
#  along with this software. If not, see <https://www.gnu.org/licenses/>.
#
#  --------------------------------------------------------------
#  원본 프로젝트 정보 / Original Project Info:
#
#  Project: Mycodo (https://github.com/kizniche/Mycodo)
#  Author:  Kyle T. Gabriel (https://kylegabriel.com)
#  License: GNU GPLv3
#
#  수정자 / Modified by:
#    - Organization: AoT (Agriculture of Things)
#    - Contact: aot.inc.kr@gmail.com
#
#  리포맷 날짜 / Reformatted: 2025-04-21
#  --------------------------------------------------------------
#
import logging

from flask_login import current_user

from aot.databases.models import Role
from aot.databases.models import User
from aot.aot_flask.utils.utils_general import user_has_permission
from aot.utils.constraints_pass import constraints_pass_positive_value

logger = logging.getLogger(__name__)


def test_user():
    """
    This endpoint will display different messages for logged in and logged out users.
    Be very careful when creating endpoints so unauthorized users don't have access
    to endpoints with sensitive information.
    """
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"

    user = User.query.filter(User.name == current_user.name).first()
    role = Role.query.filter(Role.id == user.role_id).first()
    return_message = "You are logged in as '{}' with the role '{}' and can access this endpoint".format(
        user.name, role.name)
    if user_has_permission('edit_settings'):
        return_message += "<br/>This user has permission to Edit Settings"
    if user_has_permission('edit_controllers'):
        return_message += "<br/>This user has permission to Edit Controllers"
    if user_has_permission('edit_users'):
        return_message += "<br/>This user has permission to Edit Users"
    if user_has_permission('view_settings'):
        return_message += "<br/>This user has permission to View Settings"
    if user_has_permission('view_camera'):
        return_message += "<br/>This user has permission to View Cameras"
    if user_has_permission('view_stats'):
        return_message += "<br/>This user has permission to View Stats"
    if user_has_permission('view_logs'):
        return_message += "<br/>This user has permission to View Logs"
    if user_has_permission('reset_password'):
        return_message += "<br/>This user has permission to Reset Passwords"
    return return_message


def test_parameter(some_text):
    """
    This endpoint will accept a parameter
    """
    if not current_user.is_authenticated:
        return "You are not logged in and cannot access this endpoint"

    return_message = f"User passed some text: {some_text}"

    return return_message


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_example_endpoints',
    'widget_name': 'Example Widget (Endpoints)',
    'widget_library': '',
    'no_class': True,

    'url_manufacturer': 'https://www.hackaday.com',
    'url_datasheet': 'https://www.digikey.com',
    'url_product_purchase': [
        'https://www.digikey.com',
        'https://www.adafruit.com'
    ],
    'url_additional': 'https://github.com',

    'endpoints': [
        # Route URL, route endpoint name, view function, methods
        ("/test_user", "test_user", test_user, ["GET"]),
        ("/test_parameter/<some_text>", "test_parameter", test_parameter, ["GET"])
    ],

    'message': 'This widget is an example endpoint widget, which will create the new endpoint '
               'at /test_user and /test_parameter/<some_text>. Open <a href="/test_user">This Link</a> '
               'and <a href="/test_parameter/thisissometext">This Link</a> to see this new endpoints.',

    # Any dependencies required by the output module. An empty list means no dependencies are required.
    'dependencies_module': [],

    # A message to be displayed on the dependency install page
    'dependencies_message': 'Are you sure you want to install these dependencies? They require...',

    'widget_width': 8,
    'widget_height': 8,

    'custom_options': [
        {
            'id': 'font_em_body',
            'type': 'float',
            'default_value': 1.5,
            'constraints_pass': constraints_pass_positive_value,
            'name': 'Body Font Size (em)',
            'phrase': 'The font size of the body text'
        },
        {
            'id': 'body_text',
            'type': 'text',
            'default_value': """Open this Widget's configuration menu and read its description. Click <a href="/test_user">here</a> and <a href="/test_parameter/thisissometext">here</a> to view the newly-created endpoints.""",
            'name': 'Body Text',
            'phrase': 'The body text of the widget'
        },
    ],

    'widget_dashboard_head': """<!-- No head content -->""",
    'widget_dashboard_title_bar': """<span style="padding-right: 0.5em; font-size: {{each_widget.font_em_name}}em">{{each_widget.name}}</span>""",
    'widget_dashboard_body': """<span style="font-size: {{widget_options['font_em_body']}}em">{{widget_options['body_text']|safe}}</span>""",
    'widget_dashboard_js': """<!-- No JS content -->""",
    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",
    'widget_dashboard_js_ready_end': """<!-- No JS ready end content -->"""
}
