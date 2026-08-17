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
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config_translations import TRANSLATIONS as T

MYCODO_VERSION = '8.16.0'
ALEMBIC_VERSION = 'p6_36_drop_planting_bed_spec_20260814'
AOT_VERSION = '26.08.9'

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
INSTALL_DIRECTORY = os.path.abspath(os.path.dirname(os.path.realpath(__file__)) + '/../..')
# Define local and project paths
PROJECT_DATABASE_PATH = os.path.join(INSTALL_DIRECTORY, 'aot/databases')
# Hybrid Latency Optimization: Use local path from AOT_LOCAL_DIR if provided.
# Note: this must NOT require the 'databases' subdir to already exist — on a
# fresh named volume it never will, which silently defeated this redirect and
# left the app on the bind-mounted PROJECT_DATABASE_PATH (virtiofs, which
# breaks SQLite WAL mmap/atomic rename -> "disk I/O error").
aot_local_dir = os.environ.get('AOT_LOCAL_DIR')
if aot_local_dir:
    DATABASE_PATH = os.path.join(aot_local_dir, 'databases')
    os.makedirs(DATABASE_PATH, exist_ok=True)
else:
    DATABASE_PATH = PROJECT_DATABASE_PATH

DATABASE_NAME = "aot.db"
ALEMBIC_PATH = os.path.join(INSTALL_DIRECTORY, 'alembic_db')
ALEMBIC_UPGRADE_POST = os.path.join(ALEMBIC_PATH, 'alembic_post_upgrade_versions')
SQL_DATABASE_AOT = os.path.join(DATABASE_PATH, DATABASE_NAME)
AOT_DB_PATH = f'sqlite:///{SQL_DATABASE_AOT}'
KMA_PATH = os.path.join(DATABASE_PATH, 'kma')

import sys as _sys
# Debug diagnostics are opt-in only. These lines used to print on every import
# of aot.config (every daemon start, flask worker, and helper script). That
# stderr noise corrupted shell command substitutions such as
#   URL=$(... github_release_info.py -m 26 2>&1)
# in the upgrade scripts, appending the debug text to the value and breaking
# the subsequent wget. Gate behind AOT_CONFIG_DEBUG to keep stderr clean.
if os.environ.get('AOT_CONFIG_DEBUG'):
    _sys.stderr.write(f"--- [CONFIG] Resolved DATABASE_PATH: {DATABASE_PATH}\n")
    _sys.stderr.write(f"--- [CONFIG] Resolved AOT_DB_PATH: {AOT_DB_PATH}\n")

try:
    import config_override
    AOT_DB_PATH = config_override.AOT_DB_PATH
except:
    AOT_DB_PATH = f'sqlite:///{SQL_DATABASE_AOT}'

# Misc paths
PATH_1WIRE = os.getenv('AOT_1WIRE_PATH', '/sys/bus/w1/devices/')
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
PATH_JS_USER = os.path.join(INSTALL_DIRECTORY, 'aot/aot_flask/static/js/vendor/user_js')
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
    aot_local_dir = os.environ.get('AOT_LOCAL_DIR')
    if aot_local_dir and os.path.exists(os.path.join(aot_local_dir, 'logs')):
        LOG_PATH = os.path.join(aot_local_dir, 'logs')
    else:
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
# aot_mcp_server.py 는 별도 프로세스(도커에서는 별도 컨테이너)라 'aot' 로거를
# 안 타고 자기 basicConfig 로 stderr 에만 쓴다. 그러면 웹 UI 에서 MCP 로그를
# 볼 방법이 아예 없다 — 도커 배포에서는 앱 컨테이너에 docker CLI 가 없어
# `docker logs` 로도 못 읽는다. LOG_PATH 는 세 컨테이너가 같은 디렉터리를
# 공유하므로(compose 의 ../logs:/var/log/aot), 여기 파일로 떨구면 읽힌다.
MCP_LOG_FILE = os.path.join(LOG_PATH, 'mcp.log')
HTTP_ACCESS_LOG_FILE = '/var/log/nginx/access.log'
HTTP_ERROR_LOG_FILE = '/var/log/nginx/error.log'
# End of global definitions

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
PATH_FACILITY_PHOTOS = os.path.join(INSTALL_DIRECTORY, 'uploads/facility_photos')
PATH_GEO_ZONE_PHOTOS = os.path.join(INSTALL_DIRECTORY, 'uploads/geo_zone_photos')

# Notice board
PATH_NOTICE_ATTACHMENTS = os.path.join(INSTALL_DIRECTORY, 'uploads/notice')

# Determine if running in a Docker container (redundant but kept for script reading this file)
DOCKER_CONTAINER = os.environ.get('DOCKER_CONTAINER', False) == 'TRUE'

# Pyro5 URI/host, used by aot_client.py
if DOCKER_CONTAINER:
    PYRO_URI = 'PYRO:aot.pyro_server@aot_daemon:9081'
else:
    PYRO_URI = 'PYRO:aot.pyro_server@127.0.0.1:9081'

# Measurement DB (InfluxDB) connection overrides.
# In the docker-compose stack influxdb is a sibling container reachable by its
# service name, so compose sets these env vars to point the app straight at it
# (see aot_daemon/PYRO_URI above for the same service-name convention). When
# unset, the stored Misc settings are used, applying the legacy container->host
# redirect for setups where influxdb runs natively on the Docker host.
INFLUXDB_HOST = os.environ.get('INFLUXDB_HOST')
INFLUXDB_PORT = os.environ.get('INFLUXDB_PORT')


def resolve_measurement_db_host(host):
    """Resolve the effective InfluxDB host for the current runtime.

    Priority: INFLUXDB_HOST env (compose points this at the influxdb sidecar) >
    stored host, with a localhost->host.docker.internal redirect kept only for
    native-on-host influx (no env override, inside a container).
    """
    if INFLUXDB_HOST:
        return INFLUXDB_HOST
    if DOCKER_CONTAINER and host in ('localhost', '127.0.0.1'):
        return 'host.docker.internal'
    return host

# Anonymous statistics
STATS_INTERVAL = 86400
STATS_HOST = 'stats.aotinc.co.kr'
STATS_PORT = 443
STATS_USER = 'aot_stats'
# Anonymous-stats credential is NOT baked into the (public) source. Set
# AOT_NAS_SECRET in the environment to enable uploads; unset = stats disabled.
STATS_PASSWORD = os.getenv('AOT_NAS_SECRET', '')
STATS_DATABASE = 'aot_stats'
STATS_CSV = os.path.join(INSTALL_DIRECTORY, 'statistics.csv')
ID_FILE = os.path.join(INSTALL_DIRECTORY, 'statistics.id')

# Login restrictions
LOGIN_ATTEMPTS = 5
LOGIN_BAN_SECONDS = 600  # 10 minutes

# 감사로그(audit_log) 보존기간. 개인정보 안전성 확보조치 기준의 접속기록 최소
# 보존기간(1년)을 기본값으로 둔다. 발주기관이 더 긴 기간을 요구하면 이 값만
# 올리면 되고, 0 이하로 두면 자동 정리를 끈다(무한 증가하므로 권장하지 않음).
AUDIT_LOG_RETENTION_DAYS = 365

# Check for upgrade every 2 days (if enabled)
UPGRADE_CHECK_INTERVAL = 172800

TAGS_URL = 'https://api.github.com/repos/AoT-inc/AoT/git/refs/tags'

# Docker distribution image. A GitHub release tag exists the moment the tag is
# pushed, but the multi-arch image is only pullable once
# .github/workflows/docker-publish.yml finishes -- so a Docker install must ask
# the registry, not the git tag list, whether an upgrade is actually available.
DOCKER_IMAGE_REGISTRY = 'ghcr.io'
DOCKER_IMAGE_REPOSITORY = 'aot-inc/aot'
DOCKER_IMAGE = f'{DOCKER_IMAGE_REGISTRY}/{DOCKER_IMAGE_REPOSITORY}'
# Anonymous pull token endpoint (the package must be public on GHCR).
DOCKER_REGISTRY_TOKEN_URL = (
    f'https://{DOCKER_IMAGE_REGISTRY}/token'
    f'?service={DOCKER_IMAGE_REGISTRY}'
    f'&scope=repository:{DOCKER_IMAGE_REPOSITORY}:pull')
DOCKER_REGISTRY_TAGS_URL = (
    f'https://{DOCKER_IMAGE_REGISTRY}/v2/{DOCKER_IMAGE_REPOSITORY}/tags/list')
# The image tag this container was started from. docker-compose.prod.yml passes
# it through for display only -- the authoritative running version is the
# AOT_VERSION baked into the image above. Absent on installs predating that.
DOCKER_IMAGE_TAG = os.environ.get('AOT_IMAGE_TAG') or None

# Docker update state, shared between the app and the (opt-in, phase 2) updater
# sidecar through the aot_data volume. Nothing writes these yet; the app reads
# them to decide whether a one-click update path exists on this install.
DOCKER_UPDATE_PATH = os.path.join(
    os.environ.get('AOT_LOCAL_DIR') or INSTALL_DIRECTORY, 'update')
DOCKER_UPDATE_REQUEST_FILE = os.path.join(DOCKER_UPDATE_PATH, 'request.json')
DOCKER_UPDATE_STATUS_FILE = os.path.join(DOCKER_UPDATE_PATH, 'status.json')
DOCKER_UPDATE_HEARTBEAT_FILE = os.path.join(DOCKER_UPDATE_PATH, 'heartbeat.json')
DOCKER_UPDATE_LOG_FILE = os.path.join(DOCKER_UPDATE_PATH, 'update.log')
# Heartbeat older than this means the updater is gone, not merely idle.
DOCKER_UPDATE_HEARTBEAT_MAX_AGE = 120

LANGUAGES = {
    'ko': '한국어 (Korean)',
    'en': 'English',
    'de': 'Deutsche (German)',
    'es': 'Español (Spanish)',
    'fr': 'Français (French)',
    'id': 'Bahasa Indonesia (Indonesian)',
    'it': 'Italiano (Italian)',
    'nn': 'Norsk (Norwegian)',
    'nl': 'Nederlands (Dutch)',
    'pl': 'Polski (Polish)',
    'pt': 'Português (Portuguese)',
    'ru': 'русский язык (Russian)',
    'sr': 'српски (Serbian)',
    'sv': 'Svenska (Swedish)',
    'tr': 'Türkçe (Turkish)',
    'zh': '中文 (Chinese)',
    'ja': '日本語 (Japanese)'
}

# AI Agent & Service Config (For future integration)
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
AI_MODEL = 'gpt-5.4'
AI_AGENT_ENABLED = True # 에이전트 기반 마련 활성화
AI_SUMMARY_INTERVAL = 3600 # 1시간마다 요약 생성 (최적화 가능)

# MCP Bridge Settings
# v23 (MCP_T06): Configurable failure cooldown. Override via env var MCP_FAILURE_COOLDOWN.
MCP_FAILURE_COOLDOWN_SECONDS = int(os.environ.get('MCP_FAILURE_COOLDOWN', '300'))

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
            ('pip-pypi', 'cv2', 'opencv-python>=4.8.0')
        ],
        'capable_image': True,
        'capable_stream': True
    },
    'http_address_requests': {
        'name': 'URL (requests)',
        'dependencies_module': [
            ('pip-pypi', 'imutils', 'imutils==0.5.4'),
            ('apt', 'libgl1', 'libgl1'),
            ('pip-pypi', 'cv2', 'opencv-python>=4.8.0')
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
        # libatlas-base-dev 는 뺐다(2026-08-10). numpy 는 이미 requirements.txt
        # 에 있어 이미지에 baked-in 이고, manylinux 휠이 OpenBLAS 를 자체 번들
        # (site-packages/numpy.libs/libopenblas64_*.so)해서 시스템 BLAS 가 필요
        # 없다 — libatlas 없는 컨테이너에서 이 메서드가 쓰는 np.roots() 가
        # 정상 동작함을 실측했다. 네이티브 설치는 upgrade_commands.sh 의
        # APT_PKGS 가 libatlas-base-dev 를 무조건 깔아서 여기 선언이 있으나
        # 없으나 늘 충족된 상태다. 즉 이 선언은 네이티브에선 무의미하고
        # Docker 에선 dpkg 검사 실패 -> "has unmet dependencies" 로 Bezier
        # 메서드 생성만 막는 순수 오탐이었다.
        'dependencies_module': [
            ('pip-pypi', 'numpy', 'numpy==1.26.4')
        ] + METHOD_DEP_BASE
    },
    'Cascade': {
        'name': lg('Method Cascade'),
        'dependencies_module': METHOD_DEP_BASE
    },
    'DailyMultiPoint': {
        'name': f"{lg('Daily')} ({lg('Multi-Point')})",
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
    ('Cascade', METHOD_INFO['Cascade']['name']),
    ('DailyMultiPoint', METHOD_INFO['DailyMultiPoint']['name'])
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
    ('sun_state', lg('Sun: Day or Night')),
    ('sun_event_countdown', lg('Sun: Time Until Event')),
]

# 태양 이벤트 — 조건/예약에서 고르는 앵커. aot.utils.solar.SUN_EVENTS 와 동일.
SUN_EVENTS = [
    ('sunrise', lg('Sunrise')),
    ('sunset', lg('Sunset')),
    ('solar_noon', lg('Solar Noon')),
    ('civil_dawn', lg('Civil Dawn')),
    ('civil_dusk', lg('Civil Dusk')),
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
        'message': lg(
            'A PID (Proportional-Integral-Derivative) Controller continuously '
            'regulates a measured condition toward a target Setpoint by adjusting '
            'one or two Outputs. Select a measurement to read, set the Setpoint and '
            'the P/I/D gains, and choose the Output(s) to raise and/or lower the '
            'value. The controller is commonly used to automate temperature, '
            'humidity, CO2, or pH.'),
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
        'message': lg('Time Point Trigger Functions will execute Actions every day at the specified Time.'),
        'dependencies_module': []
    },
    'trigger_timer_daily_time_span': {
        'name': f"{T['trigger']['title']}: {lg('Daily Time Span')}",
        'message': lg('Time Span Trigger Functions will execute Actions every day within the set Start and End times, every Period. The first execution will be the Start Time.'),
        'dependencies_module': []
    },
    'trigger_timer_duration': {
        'name': f"{T['trigger']['title']}: {T['duration']['title']}",
        'message': lg('Duration Trigger Functions will execute Actions every Period from when it is activated. A start offset can be added to delay the first execution.'),
        'dependencies_module': []
    },
    'trigger_run_pwm_method': {
        'name': f"{T['trigger']['title']}: {lg('Run PWM Method')}",
        'dependencies_module': []
    },
    'trigger_sunrise_sunset': {
        'name': f"{T['trigger']['title']}: {lg('Sunrise/Sunset')}",
        # 태양시는 시스템 전반의 기본값(aot.utils.solar)이라 선택 설치가 아니라
        # 정식 의존성(astral, requirements.txt)이다.
        'dependencies_module': []
    },
    'trigger_sequence': {
        'name': f"{T['trigger']['title']}: {lg('Sequence')}",
        'message': lg(
            'A Sequence Trigger runs an ordered list of Actions one step at a time '
            'when activated. Add Actions to the sequence and they execute from top '
            'to bottom, with an optional delay between steps. Use it to automate '
            'multi-step routines — for example, open a vent, wait, then turn on a '
            'fan.'),
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

# 측정값 5단계 밴드 팔레트 (단일 소스 — aot-theme-variables.css --aot-band-1..5)
# 차가움(낮음) → 적정 → 뜨거움(높음). settings/custom_ui 의 band_1..5 필드가
# 이를 사용자 정의할 수 있다 — 코드에서는 utils_theme.get_band_palette() 로
# 오버레이된 값을 읽을 것 (이 상수 직접 사용은 폴백 경로에서만).
BAND_PALETTE = ['#2DB4FF', '#54BCC1', '#32c85a', '#FEAE5F', '#CF5C58']

# 전역 차트 시리즈 팔레트 (단일 소스 — docs/design/color-system.md 5절)
# 그래프류 위젯(AoT_graph, AoT_PID, widget_graph_synchronous)의 Highcharts
# 시리즈 기본색. 앞 6색은 AoT 시맨틱 색과 정렬(#FEA60B=warning, #DF5353=danger,
# #008DDE≈info), 이후는 Highcharts 관례 색. 앞 6색(라이트/다크 공통)은
# settings/custom_ui 의 chart_1..6 필드로 사용자 정의 가능 — 코드에서는
# utils_theme.get_graph_series_palette() 로 오버레이된 값을 읽을 것.
GRAPH_SERIES_PALETTE = [
    '#FEA60B', '#8BC1C1', '#93B261', '#F4D624', '#DF5353', '#008DDE',
    '#7cb5ec', '#434348', '#90ed7d', '#f7a35c', '#8085e9', '#f15c80',
    '#e4d354', '#2b908f', '#f45b5b', '#91e8e1'
]
GRAPH_SERIES_PALETTE_DARK = [
    '#FEA60B', '#8BC1C1', '#93B261', '#F4D624', '#DF5353', '#008DDE',
    '#2b908f', '#90ee7e', '#f45b5b', '#7798BF', '#aaeeee', '#ff0066',
    '#eeaaee', '#55BF3B', '#DF5353', '#7798BF', '#aaeeee'
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

    # [Security] "Remember Me" (90-day) cookie — mirror the session cookie's
    # settings explicitly rather than relying on flask-login's defaults
    # (SECURE=None, SAMESITE=None), so the 90-day login stays independent of
    # the session cookie and isn't dropped by a stricter browser default.
    REMEMBER_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'

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
