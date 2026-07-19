# coding=utf-8
#
# measurement_output.py
# 함수에서 사용할 Output 측정값을 등록하는 액션.
# run_action() 은 실행 목적이 아닌 측정값 저장용으로만 사용됩니다.
#

from flask_babel import lazy_gettext

from aot.actions.base_action import AbstractFunctionAction
from aot.databases.models import Actions
from aot.utils.database import db_retrieve_table_daemon

ACTION_INFORMATION = {
    'name_unique': 'measurement_output',
    'name': '{}: {}'.format(lazy_gettext('Measurement'), lazy_gettext('Output')),
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'message': lazy_gettext(
        'Register an Output measurement to include in the AoT Average function. '
        'Select Output channel measurements such as duration. '
        'This action is not executed; it only stores the measurement selection.'
    ),

    'custom_options': [
        {
            'id': 'select_measurement',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Output_Channels_Measurements',
            ],
            'name': '{}: {}'.format(lazy_gettext('Measurement'), lazy_gettext('Output')),
            'phrase': lazy_gettext('Output channel measurement to include in the average calculation (e.g. duration)')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': '{} ({})'.format(lazy_gettext('Max Age'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('Measurements older than this value (seconds) will be excluded from the average')
        },
    ]
}


class ActionModule(AbstractFunctionAction):
    """Output measurement input slot for AoT_AVG_MULTI function.

    This action stores an Output channel measurement selection; it has no execution logic.
    The average function queries its registered actions of this type to
    build the list of channels to average.

    @phase core
    @stability stable
    @dependency AbstractFunctionAction
    """

    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

        self.select_measurement_device_id = None
        self.select_measurement_measurement_id = None
        self.max_measure_age = None

        action = db_retrieve_table_daemon(
            Actions, unique_id=self.unique_id)
        self.setup_custom_options(
            ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.action_setup = True

    def run_action(self, dict_vars):
        """No-op: this action stores data only; the function loop reads it."""
        pass
