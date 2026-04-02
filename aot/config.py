# -*- coding: utf-8 -*-
#
# config.py - Global AoT settings
#
import binascii
import sys
from datetime import timedelta

import os
from flask_babel import lazy_gettext as lg

# Determine if running in a Docker container
DOCKER_CONTAINER = os.environ.get('DOCKER_CONTAINER', False) == 'TRUE'

# Append proper path for other software reading this config file
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from config_translations import TRANSLATIONS as T

MYCODO_VERSION = '8.16.0'
ALEMBIC_VERSION = '718f314963c2'
AOT_VERSION = '26.1.1'

# FORCE UPGRADE MASTER
# Set True to enable upgrading to the master branch of the AoT repository.
# Set False to enable upgrading to the latest Release version (default).
# Do not use this feature unless you know what you're doing or have been
# instructed to do so, as it can really mess up your system.
FORCE_UPGRADE_MASTER = False

# Final release for each major version number
# Used to determine proper upgrade page to display
FINAL_RELEASES = ['8.16.14']

# ENABLE FLASK PROFILER
# Accessed at https://127.0.0.1/aot-flask-profiler
ENABLE_FLASK_PROFILER = False

# Install path (the parent directory of this file)
INSTALL_DIRECTORY = os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + '/..')

# Database
DATABASE_NAME = "aot.db"
ALEMBIC_PATH = os.path.join(INSTALL_DIRECTORY, 'alembic_db')
DATABASE_PATH = os.path.join(INSTALL_DIRECTORY, 'aot/databases')
ALEMBIC_UPGRADE_POST = os.path.join(ALEMBIC_PATH, 'alembic_post_upgrade_versions')
SQL_DATABASE_AOT = os.path.join(DATABASE_PATH, DATABASE_NAME)
AOT_DB_PATH = f'sqlite:///{SQL_DATABASE_AOT}'
KMA_PATH = os.path.join(DATABASE_PATH, 'kma')

try:
    import config_override
    AOT_DB_PATH = config_override.AOT_DB_PATH
except:
    AOT_DB_PATH = f'sqlite:///{SQL_DATABASE_AOT}'

# Misc paths
PATH_1WIRE = '/sys/bus/w1/devices/'
PATH_CONTROLLERS = os.path.join(INSTALL_DIRECTORY, 'aot/controllers')
PATH_FUNCTIONS = os.path.join(INSTALL_DIRECTORY, 'aot/functions')
PATH_ACTIONS = os.path.join(INSTALL_DIRECTORY, 'aot/actions')
PATH_INPUTS = os.path.join(INSTALL_DIRECTORY, 'aot/inputs')
PATH_OUTPUTS = os.path.join(INSTALL_DIRECTORY, 'aot/outputs')
PATH_WIDGETS = os.path.join(INSTALL_DIRECTORY, 'aot/widgets')
PATH_FUNCTIONS_CUSTOM = os.path.join(PATH_FUNCTIONS, 'custom_functions')
PATH_ACTIONS_CUSTOM = os.path.join(PATH_ACTIONS, 'custom_actions')
PATH_INPUTS_GIS = os.path.join(INSTALL_DIRECTORY, 'aot/inputs_gis')
PATH_INPUTS_CUSTOM = os.path.join(PATH_INPUTS, 'custom_inputs')
PATH_OUTPUTS_CUSTOM = os.path.join(PATH_OUTPUTS, 'custom_outputs')
PATH_WIDGETS_CUSTOM = os.path.join(PATH_WIDGETS, 'custom_widgets')
PATH_TEMPLATE = os.path.join(INSTALL_DIRECTORY, 'aot/aot_flask/templates')
PATH_TEMPLATE_LAYOUT = os.path.join(PATH_TEMPLATE, 'layout.html')
PATH_TEMPLATE_LAYOUT_DEFAULT = os.path.join(PATH_TEMPLATE, 'layout_default.html')
PATH_TEMPLATE_USER = os.path.join(PATH_TEMPLATE, 'user_templates')
PATH_STATIC = os.path.join(INSTALL_DIRECTORY, 'aot/aot_flask/static')
PATH_CSS = os.path.join(INSTALL_DIRECTORY, 'aot/aot_flask/static/css')
PATH_JSON = os.path.join(INSTALL_DIRECTORY, 'aot/aot_flask/static/json')
PATH_CSS_USER = os.path.join(PATH_CSS, 'user_css')
PATH_JS_USER = os.path.join(INSTALL_DIRECTORY, 'aot/aot_flask/static/js/user_js')
PATH_FONTS_USER = os.path.join(INSTALL_DIRECTORY, 'aot/aot_flask/static/fonts/user_fonts')
PATH_USER_SCRIPTS = os.path.join(INSTALL_DIRECTORY, 'aot/user_scripts')
PATH_PYTHON_CODE_USER = os.path.join(INSTALL_DIRECTORY, 'aot/user_python_code')
PATH_MEASUREMENTS_BACKUP = os.path.join(INSTALL_DIRECTORY, 'aot/backup_measurements')
PATH_SETTINGS_BACKUP = os.path.join(INSTALL_DIRECTORY, 'aot/backup_settings')
USAGE_REPORTS_PATH = os.path.join(INSTALL_DIRECTORY, 'output_usage_reports')
DEPENDENCY_INIT_FILE = os.path.join(INSTALL_DIRECTORY, '.dependency')
UPGRADE_INIT_FILE = os.path.join(INSTALL_DIRECTORY, '.upgrade')
BACKUP_PATH = os.path.join(INSTALL_DIRECTORY, 'aot/tests/backups')  # Where AoT backups are stored

# Log files
if DOCKER_CONTAINER:
    LOG_PATH = '/var/log/aot'  # Where generated logs are stored (Docker default)
else:
    # Use local or host-specific path
    LOG_PATH = os.path.join(INSTALL_DIRECTORY, 'logs')

# Ensure log directory exists
if not os.path.exists(LOG_PATH):
    try:
        os.makedirs(LOG_PATH, exist_ok=True)
    except Exception:
        # Fallback to local logs if /var/log/aot is not writable
        LOG_PATH = os.path.join(INSTALL_DIRECTORY, 'logs')
        os.makedirs(LOG_PATH, exist_ok=True)

LOGIN_LOG_FILE = os.path.join(LOG_PATH, 'login.log')
DAEMON_LOG_FILE = os.path.join(LOG_PATH, 'aot.log')
KEEPUP_LOG_FILE = os.path.join(LOG_PATH, 'aotkeepup.log')
BACKUP_LOG_FILE = os.path.join(LOG_PATH, 'aotbackup.log')
DEPENDENCY_LOG_FILE = os.path.join(LOG_PATH, 'aotdependency.log')
IMPORT_LOG_FILE = os.path.join(LOG_PATH, 'aotimport.log')
UPGRADE_LOG_FILE = os.path.join(LOG_PATH, 'aotupgrade.log')
UPGRADE_TMP_LOG_FILE = '/tmp/aotupgrade.log'
RESTORE_LOG_FILE = os.path.join(LOG_PATH, 'aotrestore.log')
HTTP_ACCESS_LOG_FILE = '/var/log/nginx/access.log'
HTTP_ERROR_LOG_FILE = '/var/log/nginx/error.log'

# Lock files
LOCK_PATH = os.path.join(INSTALL_DIRECTORY, 'aot/tests')
LOCK_FILE_STREAM = os.path.join(LOCK_PATH, 'aot-camera-stream.pid')

# Run files
RUN_PATH = os.path.join(INSTALL_DIRECTORY, 'aot/tests')
FRONTEND_PID_FILE = os.path.join(RUN_PATH, 'aotflask.pid')
DAEMON_PID_FILE = os.path.join(RUN_PATH, 'aot.pid')

# Remote admin
STORED_SSL_CERTIFICATE_PATH = os.path.join(
    INSTALL_DIRECTORY, 'aot/aot_flask/ssl_certs/remote_admin')

# Cameras
PATH_CAMERAS = os.path.join(INSTALL_DIRECTORY, 'cameras')

# Notes
PATH_NOTE_ATTACHMENTS = os.path.join(INSTALL_DIRECTORY, 'uploads/notes')

# Determine if running in a Docker container (redundant but kept for script reading this file)
DOCKER_CONTAINER = os.environ.get('DOCKER_CONTAINER', False) == 'TRUE'

# Pyro5 URI/host, used by aot_client.py
if DOCKER_CONTAINER:
    PYRO_URI = 'PYRO:aot.pyro_server@aot_daemon:9080'
else:
    PYRO_URI = 'PYRO:aot.pyro_server@127.0.0.1:9080'

# Anonymous statistics
STATS_INTERVAL = 86400
STATS_HOST = 'fungi.aot-inc.com'
STATS_PORT = 8086
STATS_USER = 'aot_stats'
STATS_PASSWORD = 'Io8Nasr5JJDdhPOj32222'
STATS_DATABASE = 'aot_stats'
STATS_CSV = os.path.join(INSTALL_DIRECTORY, 'statistics.csv')
ID_FILE = os.path.join(INSTALL_DIRECTORY, 'statistics.id')

# Login restrictions
LOGIN_ATTEMPTS = 5
LOGIN_BAN_SECONDS = 600  # 10 minutes

# Check for upgrade every 2 days (if enabled)
UPGRADE_CHECK_INTERVAL = 172800

TAGS_URL = 'https://api.github.com/repos/aot-inc/AoT/git/refs/tags'

LANGUAGES = {
    'ko': '한국어 (Korean)',
    'en': 'English',
    'ja': '日本語 (Japanese)'
}

# AI Agent & Service Config (For future integration)
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
AI_MODEL = 'gpt-4o'
AI_AGENT_ENABLED = True # 에이전트 기반 마련 활성화

# Map defaults (Leaflet first, other providers can be enabled later)
MAP_PROVIDER = 'osm'  # available values: osm, mapbox, google (future)
MAP_API_KEY = ''  # optional, used for providers that require a key
MAP_STYLE_URL = ''  # optional style URL (e.g., mapbox style)
MAP_DEFAULT_CENTER = (0.0, 0.0)  # lat, lng default center
MAP_DEFAULT_ZOOM = 2  # wide world view by default
MAP_GEOCODER = 'none'  # none, nominatim, mapbox, google (future)

DASHBOARD_WIDGETS = [
    ('', f"{lg('Add')} {lg('Dashboard')} {lg('Widget')}"),
    ('spacer', lg('Spacer')),
    ('graph', lg('Graph')),
    ('gauge', lg('Gauge')),
    ('indicator', T['indicator']['title']),
    ('measurement', T['measurement']['title']),
    ('output', T['output']['title']),
    ('output_pwm_slider', f"{T['output']['title']}: {lg('PWM Slider')}"),
    ('pid_control', lg('PID Control')),
    ('python_code', lg('Python Code')),
    ('camera', T['camera']['title'])
]

# Camera info
CAMERA_INFO = {
    'fswebcam': {
        'name': 'fswebcam',
        'dependencies_module': [
            ('apt', 'fswebcam', 'fswebcam')
        ],
        'capable_image': True,
        'capable_stream': False
    },
    'libcamera': {
        'name': 'libcamera',
        'dependencies_module': [
            ('apt', 'libcamera-apps', 'libcamera-apps')
        ],
        'capable_image': True,
        'capable_stream': False
    },
    'opencv': {
        'name': 'OpenCV',
        'dependencies_module': [
            ('pip-pypi', 'imutils', 'imutils==0.5.4'),
            ('apt', 'libgl1', 'libgl1'),
            ('pip-pypi', 'cv2', 'opencv-python==4.6.0.66')
        ],
        'capable_image': True,
        'capable_stream': True
    },
    'picamera': {
        'name': 'PiCamera (deprecated)',
        'dependencies_module': [
            ('pip-pypi', 'picamera', 'picamerab==1.13b1')
        ],
        'capable_image': True,
        'capable_stream': True
    },
    'raspistill': {
        'name': 'raspistill (deprecated)',
        'dependencies_module': [],
        'capable_image': True,
        'capable_stream': False
    },
    'http_address': {
        'name': 'URL (urllib)',
        'dependencies_module': [
            ('pip-pypi', 'imutils', 'imutils==0.5.4'),
            ('apt', 'libgl1', 'libgl1'),
            ('pip-pypi', 'cv2', 'opencv-python==4.6.0.66')
        ],
        'capable_image': True,
        'capable_stream': True
    },
    'http_address_requests': {
        'name': 'URL (requests)',
        'dependencies_module': [
            ('pip-pypi', 'imutils', 'imutils==0.5.4'),
            ('apt', 'libgl1', 'libgl1'),
            ('pip-pypi', 'cv2', 'opencv-python==4.6.0.66')
        ],
        'capable_image': True,
        'capable_stream': False
    },
    'stream_direct': {
        'name': 'Direct Stream (Client-side HLS/Direct)',
        'dependencies_module': [],
        'capable_image': False,
        'capable_stream': False,
        'client_side_stream': True
    },
}

METHOD_DEP_BASE = [
    ('bash-commands',
     [os.path.join(PATH_JS_USER, 'highcharts-9.1.2.js')],
     [
        'wget --no-clobber https://code.highcharts.com/zips/Highcharts-9.1.2.zip',
        'unzip Highcharts-9.1.2.zip -d Highcharts-9.1.2',
        f'cp -rf Highcharts-9.1.2/code/highcharts.js {os.path.join(PATH_JS_USER, "highcharts-9.1.2.js")}',
        f'cp -rf Highcharts-9.1.2/code/highcharts.js.map {os.path.join(PATH_JS_USER, "highcharts.js.map")}',
        'rm -rf Highcharts-9.1.2'
     ])
]

# Method info
METHOD_INFO = {
    'Date': {
        'name': lg('Time/Date'),
        'dependencies_module': METHOD_DEP_BASE
    },
    'Duration': {
        'name': lg('Duration'),
        'dependencies_module': METHOD_DEP_BASE
    },
    'Daily': {
        'name': f"{lg('Daily')} ({lg('Time-Based')})",
        'dependencies_module': METHOD_DEP_BASE
    },
    'DailySine': {
        'name': f"{lg('Daily')} ({lg('Sine Wave')})",
        'dependencies_module': METHOD_DEP_BASE
    },
    'DailyBezier': {
        'name': f"{lg('Daily')} ({lg('Bezier Curve')})",
        'dependencies_module': [
            ('apt', 'libatlas-base-dev', 'libatlas-base-dev'),
            ('pip-pypi', 'numpy', 'numpy==1.22.3')
        ] + METHOD_DEP_BASE
    },
    'Cascade': {
        'name': lg('Method Cascade'),
        'dependencies_module': METHOD_DEP_BASE
    }
}

# Method form dropdown
METHODS = [
    ('Date', METHOD_INFO['Date']['name']),
    ('Duration', METHOD_INFO['Duration']['name']),
    ('Daily', METHOD_INFO['Daily']['name']),
    ('DailySine', METHOD_INFO['DailySine']['name']),
    ('DailyBezier', METHOD_INFO['DailyBezier']['name']),
    ('Cascade', METHOD_INFO['Cascade']['name'])
]

PID_INFO = {
    'measure': {
        0: {
            'measurement': '',
            'unit': '',
            'name': f"{T['setpoint']['title']}",
            'measurement_type': 'setpoint'
        },
        1: {
            'measurement': '',
            'unit': '',
            'name': f"{T['setpoint']['title']} ({lg('Band Min')})",
            'measurement_type': 'setpoint'
        },
        2: {
            'measurement': '',
            'unit': '',
            'name': f"{T['setpoint']['title']} ({lg('Band Max')})",
            'measurement_type': 'setpoint'
        },
        3: {
            'measurement': 'pid_p_value',
            'unit': 'pid_value',
            'name': 'P-value'
        },
        4: {
            'measurement': 'pid_i_value',
            'unit': 'pid_value',
            'name': 'I-value'
        },
        5: {
            'measurement': 'pid_d_value',
            'unit': 'pid_value',
            'name': 'D-value'
        },
        6: {
            'measurement': 'duration_time',
            'unit': 's',
            'name': f"{T['output']['title']} ({T['duration']['title']})"
        },
        7: {
            'measurement': 'duty_cycle',
            'unit': 'percent',
            'name': f"{T['output']['title']} ({T['duty_cycle']['title']})"
        },
        8: {
            'measurement': 'volume',
            'unit': 'ml',
            'name': f"{T['output']['title']} ({T['volume']['title']})"
        },
        9: {
            'measurement': 'unitless',
            'unit': 'none',
            'name': f"{T['output']['title']} ({T['value']['title']})"
        }
    }
}

DEPENDENCIES_GENERAL = {
    'highstock': {
        'name': 'Highstock',
        'dependencies_module': [
            ('bash-commands',
             [
                 os.path.join(PATH_JS_USER, 'highstock-9.1.2.js'),
                 os.path.join(PATH_JS_USER, 'highcharts-more-9.1.2.js'),
                 os.path.join(PATH_JS_USER, 'data-9.1.2.js'),
                 os.path.join(PATH_JS_USER, 'exporting-9.1.2.js'),
                 os.path.join(PATH_JS_USER, 'export-data-9.1.2.js'),
                 os.path.join(PATH_JS_USER, 'offline-exporting-9.1.2.js')
             ],
             [
                 'wget --no-clobber https://code.highcharts.com/zips/Highcharts-Stock-9.1.2.zip',
                 'unzip Highcharts-Stock-9.1.2.zip -d Highcharts-Stock-9.1.2',
                 f'cp -rf Highcharts-Stock-9.1.2/code/highstock.js {os.path.join(PATH_JS_USER, "highstock-9.1.2.js")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/highstock.js.map {os.path.join(PATH_JS_USER, "highstock.js.map")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/highcharts-more.js {os.path.join(PATH_JS_USER, "highcharts-more-9.1.2.js")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/highcharts-more.js.map {os.path.join(PATH_JS_USER, "highcharts-more.js.map")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/data.js {os.path.join(PATH_JS_USER, "data-9.1.2.js")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/data.js.map {os.path.join(PATH_JS_USER, "data.js.map")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/exporting.js {os.path.join(PATH_JS_USER, "exporting-9.1.2.js")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/exporting.js.map {os.path.join(PATH_JS_USER, "exporting.js.map")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/export-data.js {os.path.join(PATH_JS_USER, "export-data-9.1.2.js")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/export-data.js.map {os.path.join(PATH_JS_USER, "export-data.js.map")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/offline-exporting.js {os.path.join(PATH_JS_USER, "offline-exporting-9.1.2.js")}',
                 f'cp -rf Highcharts-Stock-9.1.2/code/modules/offline-exporting.js.map {os.path.join(PATH_JS_USER, "offline-exporting.js.map")}',
                 'rm -rf Highcharts-Stock-9.1.2'
             ])
        ]
    }
}

# Conditional Functions
CONDITIONAL_CONDITIONS = [
    ('measurement',
     f"{T['measurement']['title']} ({T['single']['title']}, {T['last']['title']})"),
    ('measurement_and_ts',
     f"{T['measurement']['title']} ({T['single']['title']}, {T['last']['title']}, with Timestamp)"),
    ('measurement_past_average',
     f"{T['measurement']['title']} ({T['single']['title']}, {T['past']['title']}, {T['average']['title']})"),
    ('measurement_past_sum',
     f"{T['measurement']['title']} ({T['single']['title']}, {T['past']['title']}, {T['sum']['title']})"),
    ('measurement_dict',
     f"{T['measurement']['title']} ({T['multiple']['title']}, {T['past']['title']})"),
    ('gpio_state', lg('GPIO State')),
    ('output_state', lg('Output State')),
    ('output_duration_on', lg('Output Duration On')),
    ('controller_status', lg("Controller Running")),
]

FUNCTION_INFO = {
    'function_actions': {
        'name': lg('Execute Actions'),
        'dependencies_module': []
    },
    'conditional_conditional': {
        'name': f"{T['conditional']['title']} {T['controller']['title']}",
        'dependencies_module': [
            ('pip-pypi', 'pylint', 'pylint==3.0.1')
        ]
    },
    'pid_pid': {
        'name': f"{T['pid']['title']} {T['controller']['title']}",
        'dependencies_module': []
    },
    'trigger_edge': {
        'name': f"{T['trigger']['title']}: {T['edge']['title']}",
        'dependencies_module': []
    },
    'trigger_output': {
        'name': f"{T['trigger']['title']}: {T['output']['title']} ({T['on']['title']}/{T['off']['title']})",
        'dependencies_module': []
    },
    'trigger_output_pwm': {
        'name': f"{T['trigger']['title']}: {T['output']['title']} ({T['pwm']['title']})",
        'dependencies_module': []
    },
    'trigger_timer_daily_time_point': {
        'name': f"{T['trigger']['title']}: {lg('Daily Time Point')}",
        'message': 'Time Point Trigger Functions will execute Actions every day at the specified Time.',
        'dependencies_module': []
    },
    'trigger_timer_daily_time_span': {
        'name': f"{T['trigger']['title']}: {lg('Daily Time Span')}",
        'message': 'Time Span Trigger Functions will execute Actions every day within the set Start and End times, every Period. The first execution will be the Start Time.',
        'dependencies_module': []
    },
    'trigger_timer_duration': {
        'name': f"{T['trigger']['title']}: {T['duration']['title']}",
        'message': 'Duration Trigger Functions will execute Actions every Period from when it is activated. A start offset can be added to delay the first execution.',
        'dependencies_module': []
    },
    'trigger_run_pwm_method': {
        'name': f"{T['trigger']['title']}: {lg('Run PWM Method')}",
        'dependencies_module': []
    },
    'trigger_sunrise_sunset': {
        'name': f"{T['trigger']['title']}: {lg('Sunrise/Sunset')}",
        'dependencies_module': [
            ('pip-pypi', 'suntime', 'suntime==1.2.5')
        ]
    },
    'trigger_sequence': {
        'name': f"{T['trigger']['title']}: {lg('Sequence')}",
        'dependencies_module': []
    }
}

FUNCTIONS = [
    ('function_actions', FUNCTION_INFO['function_actions']['name']),
    ('conditional_conditional', FUNCTION_INFO['conditional_conditional']['name']),
    ('pid_pid', FUNCTION_INFO['pid_pid']['name']),
    ('trigger_edge', FUNCTION_INFO['trigger_edge']['name']),
    ('trigger_output', FUNCTION_INFO['trigger_output']['name']),
    ('trigger_output_pwm', FUNCTION_INFO['trigger_output_pwm']['name']),
    ('trigger_timer_daily_time_point', FUNCTION_INFO['trigger_timer_daily_time_point']['name']),
    ('trigger_timer_daily_time_span', FUNCTION_INFO['trigger_timer_daily_time_span']['name']),
    ('trigger_timer_duration', FUNCTION_INFO['trigger_timer_duration']['name']),
    ('trigger_run_pwm_method', FUNCTION_INFO['trigger_run_pwm_method']['name']),
    ('trigger_sunrise_sunset', FUNCTION_INFO['trigger_sunrise_sunset']['name'])
]

# User Roles
USER_ROLES = [
    dict(id=1, name='Admin',
         edit_settings=True, edit_controllers=True, edit_users=True,
         view_settings=True, view_camera=True, view_stats=True, view_logs=True,
         reset_password=True),
    dict(id=2, name='Editor',
         edit_settings=True, edit_controllers=True, edit_users=False,
         view_settings=True, view_camera=True, view_stats=True, view_logs=True,
         reset_password=True),
    dict(id=3, name='Monitor',
         edit_settings=False, edit_controllers=False, edit_users=False,
         view_settings=True, view_camera=True, view_stats=True, view_logs=True,
         reset_password=True),
    dict(id=4, name='Guest',
         edit_settings=False, edit_controllers=False, edit_users=False,
         view_settings=False, view_camera=False, view_stats=False, view_logs=False,
         reset_password=False),
    dict(id=5, name='Kiosk',
         edit_settings=False, edit_controllers=False, edit_users=False,
         view_settings=False, view_camera=True, view_stats=True, view_logs=False,
         reset_password=False)
]

# Web UI themes
THEMES = [
    ('/static/css/bootstrap-4-themes/aot.css', 'AoT'),
    ('/static/css/bootstrap-4-themes/cerulean.css', 'Cerulean'),
    ('/static/css/bootstrap-4-themes/cosmo.css', 'Cosmo'),
    ('/static/css/bootstrap-4-themes/cyborg.css', 'Cyborg'),
    ('/static/css/bootstrap-4-themes/darkly.css', 'Darkly'),
    ('/static/css/bootstrap-4-themes/flatly.css', 'Flatly'),
    ('/static/css/bootstrap-4-themes/journal.css', 'Journal'),
    ('/static/css/bootstrap-4-themes/literia.css', 'Literia'),
    ('/static/css/bootstrap-4-themes/lumen.css', 'Lumen'),
    ('/static/css/bootstrap-4-themes/lux.css', 'Lux'),
    ('/static/css/bootstrap-4-themes/materia.css', 'Materia'),
    ('/static/css/bootstrap-4-themes/minty.css', 'Minty'),
    ('/static/css/bootstrap-4-themes/pulse.css', 'Pulse'),
    ('/static/css/bootstrap-4-themes/sandstone.css', 'Sandstone'),
    ('/static/css/bootstrap-4-themes/simplex.css', 'Simplex'),
    ('/static/css/bootstrap-4-themes/slate.css', 'Slate'),
    ('/static/css/bootstrap-4-themes/solar.css', 'Solar'),
    ('/static/css/bootstrap-4-themes/spacelab.css', 'Spacelab'),
    ('/static/css/bootstrap-4-themes/superhero.css', 'Superhero'),
    ('/static/css/bootstrap-4-themes/united.css', 'United'),
    ('/static/css/bootstrap-4-themes/yeti.css', 'Yeti')
]

THEMES_DARK = [
    '/static/css/bootstrap-4-themes/cyborg.css',
    '/static/css/bootstrap-4-themes/darkly.css',
    '/static/css/bootstrap-4-themes/slate.css',
    '/static/css/bootstrap-4-themes/solar.css',
    '/static/css/bootstrap-4-themes/superhero.css'
]

try:
    user_themes = os.path.join(PATH_CSS_USER, "bootstrap-4-themes")
    for file in os.listdir(os.fsencode(user_themes)):
        filename = os.fsdecode(file)
        if filename.endswith(".css"):
            theme_location = f"/static/css/user_css/bootstrap-4-themes/{filename}"
            theme_display = filename.split('.')[0].replace('-', ' ').replace('_', ' ').title()
            THEMES.append((theme_location, theme_display))

            if 'dark' in filename.lower():
                THEMES_DARK.append(theme_location)
except:
    pass

class ProdConfig(object):
    """Production Configuration."""
    SQL_DATABASE_AOT = os.path.join(DATABASE_PATH, DATABASE_NAME)
    AOT_DB_PATH = f'sqlite:///{SQL_DATABASE_AOT}'
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{SQL_DATABASE_AOT}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    RATELIMIT_STORAGE_URI = "memory://"

    FLASK_PROFILER = {
        "enabled": True,
        "storage": {
            "engine": "sqlalchemy",
            "db_url": f"sqlite:///{os.path.join(DATABASE_PATH, 'profile.db')}"
        },
        "basicAuth": {
            "enabled": True,
            "username": "admin231",
            "password": "admin421378956"
        },
        "ignore": [
            "^/static/.*",
            "/login",
            "/settings/users"
        ],
        "endpointRoot": "aot-flask-profiler"
    }

    WTF_CSRF_TIME_LIMIT = 60 * 60 * 24 * 7  # 1 week expiration
    REMEMBER_COOKIE_DURATION = timedelta(days=90)
    SESSION_TYPE = "filesystem"

    # [Security] Session Cookie Settings
    # Relaxed for Development/LAN Access
    SESSION_COOKIE_SECURE = False 
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_SSL_STRICT = False

    # Ensure file containing the Flask secret_key exists
    FLASK_SECRET_KEY_PATH = os.path.join(DATABASE_PATH, 'flask_secret_key')
    if not os.path.isfile(FLASK_SECRET_KEY_PATH):
        secret_key = binascii.hexlify(os.urandom(32)).decode()
        if not os.path.exists(DATABASE_PATH):
            os.makedirs(DATABASE_PATH)
        with open(FLASK_SECRET_KEY_PATH, 'w') as file:
            file.write(secret_key)
    SECRET_KEY = open(FLASK_SECRET_KEY_PATH, 'rb').read()


class TestConfig(object):
    """Testing Configuration."""
    SQLALCHEMY_DATABASE_URI = 'sqlite://'  # in-memory db only. tests drop the tables after they run
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PRESERVE_CONTEXT_ON_EXCEPTION = False
    RATELIMIT_ENABLED = False
    SECRET_KEY = '1234'
    SESSION_TYPE = "filesystem"
    TESTING = True
    DEBUG = True
