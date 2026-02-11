# coding=utf-8
#
#  Copyright (C) 2015-2022 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <https://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
import logging

from aot.utils.constraints_pass import constraints_pass_positive_value
from flask_babel import lazy_gettext

logger = logging.getLogger(__name__)


WIDGET_INFORMATION = {
    'widget_name_unique': 'widget_spacer',
    'widget_name': 'Spacer',
    'widget_library': '',
    'no_class': True,

    'message': 'A simple widget to use as a spacer, which includes the ability to set text in its contents.',

    'widget_width': 20,
    'widget_height': 2,

    'custom_options': [
        {
            'id': 'font_em_body',
            'type': 'float',
            'default_value': 1.5,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Body Font Size (em)'),
            'phrase': lazy_gettext('The font size of the body text')
        },
        {
            'id': 'body_text',
            'type': 'text',
            'default_value': "",
            'name': lazy_gettext('Body Text'),
            'phrase': lazy_gettext('The body text of the widget')
        },
    ],

    'widget_dashboard_head': """<!-- No head content -->""",
    'widget_dashboard_title_bar': """<span style="padding-right: 0.5em; font-size: {{each_widget.font_em_name}}em">{{each_widget.name}}</span>""",
    'widget_dashboard_body': """<span style="font-size: {{widget_options['font_em_body']}}em">{{widget_options['body_text']}}</span>""",
    'widget_dashboard_js': """<!-- No JS content -->""",
    'widget_dashboard_js_ready': """<!-- No JS ready content -->""",
    'widget_dashboard_js_ready_end': """<!-- No JS ready end content -->"""
}