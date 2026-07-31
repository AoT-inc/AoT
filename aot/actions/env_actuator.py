# coding=utf-8
"""
actions/env_actuator.py — Register an actuator for the env_coordinator Function.

Each action record holds the metadata for one actuator
(Output channel + kind + cost + K_* calibration + end-of-window behavior).

run_action() does not control anything directly — env_coordinator queries the
Actions table every cycle, converts records to ActuatorProfiles, and passes them
to the coordination algorithm.
"""

from flask_babel import lazy_gettext

from aot.actions.base_action import AbstractFunctionAction
from aot.databases.models import Actions
from aot.utils.database import db_retrieve_table_daemon

ACTION_INFORMATION = {
    'name_unique': 'env_actuator',
    'name': 'Environment Control',
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'message': lazy_gettext(
        'Register an actuator with the Integrated Environment Control (env_coordinator) Function. '
        'Add this action multiple times to register more than one device.'
    ),

    'custom_options': [
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('Output Channel'),
            'phrase': lazy_gettext('Select the Output channel to control.'),
        },
        {
            'id': 'kind',
            'type': 'select',
            'default_value': '',
            'required': True,
            'options_select': [
                ('opening',      lazy_gettext('Vent / Opening (side wall, roof)')),
                ('cooler',       lazy_gettext('Cooler / Air Conditioner')),
                ('heater',       lazy_gettext('Heater')),
                ('fogger',       lazy_gettext('Fogger / Humidifier')),
                ('co2_injector', lazy_gettext('CO₂ Injector')),
                ('shade',        lazy_gettext('Shade Screen')),
                ('curtain',      lazy_gettext('Thermal Curtain')),
                ('lighting',     lazy_gettext('Supplemental Lighting')),
                ('circulation_fan', lazy_gettext('Circulation Fan (internal air mixing)')),
                ('exhaust_fan',     lazy_gettext('Exhaust Fan (ventilation, exhaust)')),
                ('intake_fan',      lazy_gettext('Intake Fan (fresh air intake)')),
            ],
            'name': lazy_gettext('Actuator Type'),
            'phrase': lazy_gettext('Select the role this Output performs.'),
        },
        {
            'id': 'cost',
            'type': 'float',
            'default_value': 5.0,
            'required': False,
            'name': lazy_gettext('Cost Index'),
            'phrase': lazy_gettext(
                'Lower value = higher priority (1 = free natural ventilation, 10 = high-cost device).'
            ),
        },
        {
            'id': 'end_behavior',
            'type': 'select',
            'default_value': 'nothing',
            'required': False,
            'options_select': [
                ('nothing',  lazy_gettext('Do Nothing')),
                ('off',      lazy_gettext('Turn Off')),
                ('on',       lazy_gettext('Turn On')),
                ('open_pct', lazy_gettext('Set Open % (Vent only)')),
            ],
            'name': lazy_gettext('On Time Window End'),
            'phrase': lazy_gettext(
                'Action to take on this actuator when the time control window ends.'
            ),
        },
        {
            'id': 'end_open_pct',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('End Open %'),
            'phrase': lazy_gettext(
                'Target opening percentage when the time window ends (Vent / Opening only).'
            ),
        },
        {
            'id': 'shade_transmittance',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Shade Cloth Transmittance (0-1, Shade only)'),
            'phrase': lazy_gettext(
                'Fraction of light that passes through the shade cloth when fully '
                'closed. 0.30 = 70% shading. Used only when there is NO indoor light '
                'sensor: the indoor light level is then estimated from outdoor '
                'irradiance and the shade position, so the light thresholds can see '
                'the shading the screen itself creates. '
                '0 = disabled (indoor light is assumed equal to outdoor irradiance).'
            ),
        },
        {
            'id': 'k_override',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Effect Coefficient Override (K_*)'),
            'phrase': lazy_gettext(
                '0 = use default. Enter only when calibrating from measured data. '
                'e.g. cooler → K_COOLER_T, fogger → K_FOG_RH.'
            ),
        },
        {
            'id': 'full_stroke_sec',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Full Stroke Time (s)'),
            'phrase': lazy_gettext(
                'Time (seconds) for this actuator to travel 0→100%. '
                'Used to limit the maximum command change per cycle so that '
                'impossible commands (faster than physical speed) are never sent. '
                '0 = disabled (uses slew_per_cycle as-is). '
                'Example: a vent motor that takes 10 min → enter 600.'
            ),
        },
        {
            'id': 'min_repeat_sec',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Min Repeat Interval (s)'),
            'phrase': lazy_gettext(
                'Minimum seconds between repeated commands to this actuator '
                'even if the target value has not changed. '
                '0 = use system default (600 s watchdog). '
                'Increase for slow motorized actuators to extend relay lifetime.'
            ),
        },
    ],
}


class ActionModule(AbstractFunctionAction):
    """Actuator metadata registration action for env_coordinator.

    @phase beta
    @stability beta
    @dependency AbstractFunctionAction
    """

    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

        self.output_device_id  = None
        self.output_channel_id = None
        self.kind              = None
        self.cost              = 5.0
        self.end_behavior      = 'nothing'
        self.end_open_pct      = 0.0
        self.k_override        = 0.0
        self.full_stroke_sec   = 0.0
        self.min_repeat_sec    = 0.0

        action = db_retrieve_table_daemon(Actions, unique_id=self.unique_id)
        self.setup_custom_options(ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.action_setup = True

    def run_action(self, dict_vars):
        # env_coordinator handles coordination — this action is metadata-only
        if 'message' not in dict_vars:
            dict_vars['message'] = ''
        dict_vars['message'] += (
            f" [env_actuator] kind={self.kind}, "
            f"output={self.output_device_id}, cost={self.cost}"
        )
        return dict_vars

    def is_setup(self):
        return self.action_setup
