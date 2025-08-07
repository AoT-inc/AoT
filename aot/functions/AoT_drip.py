# coding=utf-8
from flask_babel import lazy_gettext
from aot.functions.base_function import AbstractFunction

FUNCTION_INFORMATION = {
    'function_name_unique': 'drip_calculator',
    'function_name': 'AoT: 점적 계산기',
    'message': '점적 라인의 유량과 물 사용량을 계산합니다.',
    'options_disabled': [],
    'custom_options': [
        {'id': 'flow_rate', 'type': 'float', 'required': True, 'name': lazy_gettext('유량 (L/h)')},
        {'id': 'spacing_cm', 'type': 'float', 'required': True, 'name': lazy_gettext('토출 간격 (cm)')},
        {'id': 'num_lines', 'type': 'integer', 'required': True, 'name': lazy_gettext('라인 수')},
        {'id': 'emitters_per_line', 'type': 'integer', 'required': True, 'name': lazy_gettext('라인당 점적 수')},
        {'id': 'line_length', 'type': 'float', 'required': True, 'name': lazy_gettext('라인 길이 (m)')},
        {'id': 'start_delay', 'type': 'integer', 'required': False, 'name': lazy_gettext('작동 지연시간 (초)')}
    ]
}

class CustomModule(AbstractFunction):
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)
        self.setup_custom_options(FUNCTION_INFORMATION['custom_options'])
        self.flow_rate = float(self.get_custom_option('flow_rate'))
        self.spacing_cm = float(self.get_custom_option('spacing_cm'))
        self.num_lines = int(self.get_custom_option('num_lines'))
        self.emitters_per_line = int(self.get_custom_option('emitters_per_line'))
        self.line_length = float(self.get_custom_option('line_length'))

    def get_total_emitters(self):
        return self.num_lines * self.emitters_per_line

    def get_hourly_usage(self):
        return self.flow_rate * self.get_total_emitters()  # L/h