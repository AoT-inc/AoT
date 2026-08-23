# coding=utf-8
#
#  app.py - Flask web server for AoT
#
import base64
import logging
import os
import sys
import time

import flask_login
from flask import Flask, flash, jsonify, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import event
from flask_babel import Babel, gettext
from flask_compress import Compress
from flask_limiter import Limiter
from flask_login import current_user
from flask_session import Session
from flask_talisman import Talisman

from aot.config import INSTALL_DIRECTORY, LANGUAGES, ProdConfig
from aot.databases.models import Misc, User, Widget, populate_db
from aot.databases.utils import session_scope
from aot.aot_flask import (routes_admin, routes_authentication,
                                 routes_dashboard, routes_device, routes_function,
                                 routes_general, routes_input, routes_geo,
                                 routes_method, routes_output, routes_page,
                                 routes_password_reset, routes_remote_admin,
                                 routes_settings, routes_static, routes_notes_api,
                                 routes_ai_agent, routes_tab, routes_camera, routes_orch_api, routes_mcp_api,
                                 routes_ai_monitoring)
from aot.aot_flask.api import api_blueprint, init_api
from aot.aot_flask.extensions import db
from aot.aot_flask.utils.utils_general import get_ip_address
from aot.aot_flask.utils import utils_geo
from aot.utils import google_oauth
from aot.utils.layouts import update_layout
from aot.utils.widgets import parse_widget_information

logger = logging.getLogger(__name__)


def _resolve_mcp_python():
    """Return the python interpreter to launch the AoT MCP server subprocess.

    The subprocess must share the Flask app's installed dependencies, so we use
    the running interpreter (sys.executable) — it is the venv python on a normal
    install. A candidate venv is only honored if it actually has site-packages;
    a bare/stale venv whose bin/python3 exists but lacks dependencies (seen in
    Docker dev where /app/env is an empty venv) would otherwise be chosen and the
    subprocess would fail with ModuleNotFoundError.
    """
    def _has_site_packages(py):
        try:
            import subprocess
            out = subprocess.run(
                [py, '-c', 'import flask_login'],
                capture_output=True, timeout=10)
            return out.returncode == 0
        except Exception:
            return False

    candidates = []
    aot_local_dir = os.environ.get('AOT_LOCAL_DIR')
    if aot_local_dir:
        candidates.append(os.path.join(aot_local_dir, 'env', 'bin', 'python3'))
    candidates.append(os.path.join(INSTALL_DIRECTORY, 'env', 'bin', 'python3'))
    for py in candidates:
        if os.path.exists(py) and _has_site_packages(py):
            return py
    return sys.executable  # same interpreter running Flask — always has the deps


def warm_start_mcp_servers(app):
    """Warm-start activated MCP server subprocesses so their tools are available
    to the AI from the very first query.

    Without this the AoT MCP server sits 'stopped' after boot; the manifest path
    deliberately refuses to start a stopped server on a request thread, so the AI
    silently gets ZERO device tools (search_devices / get_device_list /
    operate_device) until a manual restart.

    Call ONLY from the web entry (start_flask_ui) — NOT from create_app, because
    the daemon also builds an app via create_app and must not spawn these heavy
    (~186MB measured) subprocesses. **The built-in AoT server is skipped entirely**
    — its tools come from the in-process execution layer, so there is nothing to
    warm and spawning it would undo that. Runs in a daemon thread so it never blocks boot. One
    retry covers the transient 'started but not ready yet' 0-tools race."""
    import threading
    import time as _t

    def _warm():
        try:
            with app.app_context():
                from aot.databases.models.mcp_server import MCPServer
                from aot.ai.services.mcp_bridge_service import MCPBridgeService
                for srv in MCPServer.query.filter_by(is_activated=True).all():
                    # 내장 서버(AoT 자기 자신)는 예열할 프로세스가 없다. 도구
                    # 실행층이 이 프로세스 안에 있고(tool_execution) 내부 AI 는
                    # 그것을 직접 부른다 — 여기서 띄우면 없앤 subprocess(실측
                    # 186MB)가 기동 때마다 그대로 돌아온다.
                    if 'aot_mcp_server' in (srv.command or ''):
                        logger.info(
                            "[Startup] MCP '%s' 는 내장 실행층이라 예열하지 않습니다.",
                            srv.name)
                        continue
                    n = 0
                    for attempt in (1, 2):
                        try:
                            n = len(MCPBridgeService.get_tools(srv.unique_id, force_refresh=True))
                        except Exception as e:
                            logger.warning(f"[Startup] MCP warm-start error for '{srv.name}' (try {attempt}): {e}")
                            n = 0
                        if n > 0:
                            break
                        _t.sleep(2)  # let the subprocess finish its initialize handshake
                    logger.info(f"[Startup] Warm-started MCP '{srv.name}' — {n} tool(s) available to the AI.")
        except Exception as e:
            logger.warning(f"[Startup] MCP warm-start pass failed: {e}")

    threading.Thread(target=_warm, name='mcp-warmup', daemon=True).start()


def create_app(config=ProdConfig):

    """
    Application factory:
        http://flask.pocoo.org/docs/0.11/patterns/appfactories/

    :param config: configuration object that holds config constants
    :returns: Flask
    """
    app = Flask(__name__)
    app.config.from_object(config)

    # Give this process's 'aot' logger somewhere to go. Only aot_daemon.py
    # ever set this up (inline, at its own module import time) -- gunicorn
    # importing this module never does, so every logger.info()/warning()
    # anywhere under aot.* (this file included) was silently going nowhere
    # under gunicorn: with no handler anywhere in the logger's ancestry,
    # Python's handler of last resort only prints WARNING+ to stderr, so
    # even that was invisible for INFO calls specifically (2026-08-16, found
    # chasing a log line that never appeared). Idempotent, so re-entrant
    # create_app() calls (aot_mcp_server.py also calls this) are harmless.
    from aot.utils.logging_setup import configure_aot_file_logging
    configure_aot_file_logging()

    # Standardize JSON datetime serialization to UTC ISO 8601 with offset
    # (e.g. '2026-05-06T12:34:56+00:00'). Frontend converts to device/viewer TZ.
    try:
        from flask.json.provider import DefaultJSONProvider
        from datetime import datetime as _dt, date as _date, timezone as _tz

        class _AoTJSONProvider(DefaultJSONProvider):
            def default(self, obj):
                if isinstance(obj, _dt):
                    if obj.tzinfo is None:
                        obj = obj.replace(tzinfo=_tz.utc)
                    return obj.astimezone(_tz.utc).isoformat()
                if isinstance(obj, _date):
                    return obj.isoformat()
                return super().default(obj)

        app.json = _AoTJSONProvider(app)
    except Exception as _json_err:
        logger.warning("[json] AoT JSON provider init failed: %s", _json_err)

    # ProxyFix for Docker/Nginx environments
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
    
    app.config['TEMPLATES_AUTO_RELOAD'] = app.debug
    # 1년 캐시 (버전 쿼리스트링으로 캐시 무효화)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000

    from sqlalchemy.pool import NullPool, QueuePool, StaticPool
    # gunicorn multi-worker: NullPool (fork 후 커넥션 공유 방지)
    # 단일 프로세스(dev/Docker): QueuePool (커넥션 재사용으로 SQLite 락 경합 해소)
    # 인메모리 SQLite: StaticPool — 커넥션마다 빈 DB 가 새로 생기므로 하나를
    #   공유해야 하고, 풀 크기 인자는 StaticPool 이 받지 않는다(pool_size 등을
    #   넘기면 create_engine 이 TypeError 로 죽는다).
    _db_uri = str(app.config.get('SQLALCHEMY_DATABASE_URI') or '')
    _is_memory_sqlite = _db_uri.startswith('sqlite') and (
        ':memory:' in _db_uri or _db_uri.rstrip('/') == 'sqlite:')
    _is_gunicorn = "gunicorn" in os.environ.get("SERVER_SOFTWARE", "") or \
                   any("gunicorn" in arg for arg in __import__("sys").argv)
    if _is_memory_sqlite:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {'check_same_thread': False},
            'poolclass': StaticPool,
        }
    elif _is_gunicorn:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {'timeout': 30, 'check_same_thread': False},
            'pool_pre_ping': True,
            'poolclass': NullPool,
        }
    else:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'connect_args': {'timeout': 30, 'check_same_thread': False},
            'pool_pre_ping': True,
            'poolclass': QueuePool,
            'pool_size': 5,
            'max_overflow': 10,
            'pool_timeout': 30,
            'pool_recycle': 3600,
        }

    register_extensions(app)
    register_blueprints(app)
    register_widget_endpoints(app)

    from aot.aot_flask.cli_geo import register_geo_cli
    register_geo_cli(app)

    @app.after_request
    def _no_cache_html(response):
        """HTML 문서는 캐시하되 매 요청마다 서버 재검증(no-cache)하도록 강제.

        정적 자산(css/js)은 SEND_FILE_MAX_AGE_DEFAULT=1년 + ?v= 쿼리로 캐싱하지만,
        HTML 에 캐시 헤더가 없으면 브라우저가 휴리스틱으로 옛 HTML 을 보관해
        옛 ?v= 를 계속 참조 → CSS/JS 변경이 반영되지 않는 문제가 발생한다.
        HTML 에 no-cache 를 주면 항상 최신 ?v= 를 받아 정적 자산 캐시가 정확히 무효화된다.
        (no-store 가 아니라 no-cache: ETag 로 304 재검증되어 트래픽 부담은 적음.)
        """
        try:
            if response.mimetype == 'text/html':
                response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        except Exception:
            pass
        return response

    @app.after_request
    def _static_cache_policy(response):
        """정적 자산의 캐시 수명을 **버전 유무로** 가른다.

        `SEND_FILE_MAX_AGE_DEFAULT` 는 1년이다. 버전 쿼리가 붙은 URL 에는 그것이 맞다 —
        내용이 바뀌면 URL 이 바뀌므로 재검증이 무의미하다. 그러나 **버전이 없는 URL 은
        내용이 바뀌어도 URL 이 그대로**여서, 1년 캐시가 곧 "1년간 옛 코드 실행" 이 된다.

        2026-08-13 지도 삭제 사고가 그것이다. `geo_design.html` 이 `aot-map-data.js` 를
        버전 없이 불렀고, 08-03 에 그 파일이 바뀌었는데도(삭제 목록을 싣는 코드 추가)
        그 전에 방문한 브라우저는 서버에 묻지도 않고 옛 사본을 계속 실행했다. 같은 날
        서버가 "페이로드에 없음 = 삭제" 를 폐지한 터라, 목록을 못 싣는 옛 클라이언트의
        삭제는 **정상 응답을 받으며 아무것도 지우지 않았다.**

        버전이 없으면 오래 캐시하지 않는다. 실수를 없애지는 못하지만 **실패 반경을 1년에서
        5분으로 줄인다** — 이 한 층만 있었어도 그 사고는 나지 않았다.

        주의: Flask 는 after_request 를 **역순**으로 실행한다. 정적 응답의 Cache-Control 을
        건드리는 핸들러를 이보다 **앞서** 등록하면 이 정책을 덮어쓴다.
        """
        try:
            if request.endpoint == 'static':
                if request.args.get('v'):
                    response.headers['Cache-Control'] = \
                        'public, max-age=31536000, immutable'
                else:
                    response.headers['Cache-Control'] = \
                        'public, max-age=300, must-revalidate'
        except Exception:
            pass
        return response

    register_response_guards(app)

    @app.context_processor
    def inject_current_locale():
        """실제 Flask-Babel 로케일을 템플릿에 주입.

        <html lang> 표기를 session['language'] 가 아니라 get_locale() 결과
        (유저 DB → 세션 → .language → Accept-Language 순)와 일치시켜,
        선언된 lang 과 렌더링된 콘텐츠 언어 불일치로 인한 브라우저 자동번역
        팝업을 방지한다.
        """
        try:
            from flask_babel import get_locale
            locale = get_locale()
            current_locale = str(locale).replace('_', '-') if locale else 'en'
        except Exception:
            current_locale = 'en'
        return {'current_locale': current_locale}

    @app.context_processor
    def inject_system_timezone():
        """시스템 전역 기본 tz(Misc.timezone)를 템플릿에 주입 — AoTTz 의
        aot-fallback-tz meta 용. 개인 tz(current_user.timezone)가 우선이고
        이건 미로그인/미설정 + 브라우저 tz 불가일 때의 최후 폴백."""
        try:
            from aot.utils.timekit import system_tz_name
            return {'system_timezone': system_tz_name() or 'UTC'}
        except Exception:
            return {'system_timezone': 'UTC'}

    @app.context_processor
    def inject_manual_url():
        """도움말 매뉴얼 URL을 현재 UI 언어에 맞춰 생성.

        매뉴얼(mkdocs-static-i18n)은 en=루트, ko=/ko, ja=/ja 로 발행된다.
        번역이 없는 UI 언어는 영어(루트)로 폴백한다.
        템플릿에서 manual_url('Data-Viewing/#dashboard') 형태로 사용.
        """
        MANUAL_LANGS = {'ko', 'ja'}  # en 및 그 외 = 루트(영어)
        def manual_url(path):
            try:
                from flask_babel import get_locale
                lang = str(get_locale() or 'en').split('_')[0].split('-')[0]
            except Exception:
                lang = 'en'
            prefix = '/' + lang if lang in MANUAL_LANGS else ''
            return 'https://aot-inc.github.io/AoT{}/{}'.format(prefix, path.lstrip('/'))
        return {'manual_url': manual_url}

    # ── 정적 자산 자동 버전 — url_for('static', …) 에 내용 해시를 붙인다 ──
    #
    # 손으로 ?v= 를 올리는 규약은 지킬 수 없다: 어긴 것이 화면에도 로그에도 테스트에도
    # 드러나지 않고(개발자는 늘 새 코드를 본다), 파일을 고치는 사람과 참조를 적은 사람이
    # 다르며, 한 번 놓치면 1년 캐시라 그 사용자는 1년간 옛 코드를 실행한다.
    # 2026-08-13 지도 삭제 사고가 그렇게 났다. 그래서 사람이 아니라 기계가 붙인다.
    #
    # 토큰은 **내용 해시**다. mtime 은 git pull 만 해도 바뀌어, 내용이 같은 파일까지
    # 전 사용자에게 재다운로드를 시킨다. 해시는 (mtime, size) 가 그대로면 재사용하므로
    # 파일당 프로세스 수명 동안 한 번만 계산된다(실측: 126종 3.7MB → 41.9ms, 이후
    # 페이지당 0.22ms).
    #
    # 이것이 덮는 것은 `url_for('static', …)` 뿐이다. 리터럴 "/static/…" 문자열은
    # 지나지 않으므로 `aot/scripts/check_static_cache_busting.py` 가 따로 막는다.
    _static_ver_cache = {}

    def _static_version(filename):
        path = os.path.join(app.static_folder, filename)
        try:
            st = os.stat(path)
        except OSError:
            return None          # 없는 파일은 버전 없이 — 404 는 별개 문제다
        key = (st.st_mtime, st.st_size)
        hit = _static_ver_cache.get(filename)
        if hit and hit[0] == key:
            return hit[1]
        import hashlib
        h = hashlib.md5()        # 무결성이 아니라 캐시 키다 — 속도 우선
        try:
            with open(path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(65536), b''):
                    h.update(chunk)
        except OSError:
            return None
        token = h.hexdigest()[:10]
        _static_ver_cache[filename] = (key, token)
        return token

    @app.url_defaults
    def _static_cache_bust(endpoint, values):
        if endpoint != 'static':
            return
        filename = values.get('filename')
        if not filename or 'v' in values:   # 명시 지정은 존중한다
            return
        token = _static_version(filename)
        if token:
            values['v'] = token

    # JS 가 런타임에 <script>/<link> 를 만드는 자리(약 8곳)는 url_for 를 지나지 않는다.
    # 그쪽에 줄 단일 버전 값. 프로세스 시작마다 바뀌므로 배포하면 갱신된다 — 파일별
    # 해시가 아니어도 되는 이유는 이 경로가 소수이고 목적이 "배포 후 갱신" 이기 때문이다.
    from aot.config import AOT_VERSION as _AOT_VERSION
    _ASSET_BUILD_ID = '%s-%x' % (_AOT_VERSION, int(time.time()))

    @app.context_processor
    def inject_user_i18n_fingerprint():
        """사용자 지정 이름 번역 사전의 캐시 지문.

        layout 이 user_strings.js 의 ?v= 에 붙인다. 번역이 하나라도 추가되면
        값이 바뀌어 브라우저가 새 사전을 받는다. 기능이 꺼져 있으면 조회조차
        하지 않는다 — 이건 모든 페이지 렌더에서 도는 경로다.

        docs/design/user-string-live-translation.md
        """
        try:
            from aot.ai.services import user_string_translator as ust
            if not ust.is_enabled():
                return {'user_i18n_fingerprint': 'off'}
            from flask_babel import get_locale
            return {'user_i18n_fingerprint':
                    ust.catalog_fingerprint(str(get_locale()))}
        except Exception:
            return {'user_i18n_fingerprint': 'off'}

    @app.context_processor
    def inject_static_build_id():
        return {'static_build_id': _ASSET_BUILD_ID}

    # ── Bundle asset() — content-hash cache-busting for built JS bundles ──
    # Reads static/js/dist/manifest.json (bundle name -> content hash, written by
    # tools/bundle.mjs) and returns "/static/js/dist/<name>.bundle.js?v=<hash>".
    # Eliminates manual ?v= bumping (stale-cache footgun). Usable in page
    # templates AND widget head strings (both rendered by this Jinja env).
    _BUNDLE_MANIFEST_PATH = os.path.join(
        os.path.dirname(__file__), 'static', 'js', 'dist', 'manifest.json')
    _bundle_manifest = {'data': None, 'mtime': 0}

    @app.context_processor
    def inject_bundle_asset():
        import json

        def asset(name):
            base = '/static/js/dist/%s.bundle.js' % name
            try:
                st = os.stat(_BUNDLE_MANIFEST_PATH)
                if _bundle_manifest['data'] is None or st.st_mtime != _bundle_manifest['mtime']:
                    with open(_BUNDLE_MANIFEST_PATH, encoding='utf-8') as fh:
                        _bundle_manifest['data'] = json.load(fh)
                    _bundle_manifest['mtime'] = st.st_mtime
                h = (_bundle_manifest['data'] or {}).get(name)
            except Exception:
                h = None
            return ('%s?v=%s' % (base, h)) if h else base

        return {'asset': asset}

    # ── Google account status — used by the nav-bar "User Settings" modal
    # (Google sign-in / connect) and the login page's "Sign in with Google"
    # button. Global injection avoids threading these through every route
    # that renders layout_default.html.
    @app.context_processor
    def inject_google_account_status():
        from flask_login import current_user
        connection = None
        if current_user.is_authenticated:
            from aot.databases.models import UserCalendarConnection
            connection = (UserCalendarConnection.query
                          .filter_by(user_id=current_user.id, provider='google')
                          .first())
        return {
            'google_connection': connection,
            'google_login_configured': google_oauth.is_configured(),
        }

    @app.template_filter('from_json_safe')
    def from_json_safe(value):
        import json
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}

    return app


def register_extensions(app):
    """register extensions to the app."""
    app.jinja_env.add_extension('jinja2.ext.do')  # Global values in jinja

    db.init_app(app)  # Influx db time-series database

    # Enable WAL mode for SQLite concurrent access (Flask + Daemon + APScheduler)
    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def _set_sqlite_wal(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    init_api(app)

    app = extension_babel(app)  # Language translations
    app = extension_compress(app)  # Compress app responses with gzip
    app = extension_limiter(app)  # Limit authentication blueprint requests to 200 per minute
    app = extension_login_manager(app)  # User login management
    app = register_api_key_scope_guard(app)  # readonly API 키의 쓰기 차단
    app = extension_session(app)  # Server side session
    app = extension_csrf(app) # CSRF Protection
    app = extension_cache(app)  # API response caching

    # Phase 5 EKG: register Notes post-commit signal listener (idempotent)
    try:
        from aot.ai.services.experience_knowledge_graph import EKGService
        EKGService.register_signal_listener()
    except Exception as _ekg_init_err:
        logger.warning("[EKG] Signal listener registration failed: %s", _ekg_init_err)

    # Auto-populate device.timezone from latitude/longitude on insert/update
    try:
        from aot.databases.device_tz_listeners import register_device_tz_listeners
        register_device_tz_listeners()
    except Exception as _tz_init_err:
        logger.warning("[device_tz] Listener registration failed: %s", _tz_init_err)

    # P3: invalidate the AI system-knowledge snapshot whenever the user adds/edits/
    # removes a device/function/zone, so answers reflect the change immediately
    # instead of a stale pre-change snapshot.
    try:
        from aot.databases.change_tracking import register_change_listeners
        register_change_listeners()
    except Exception as _ct_init_err:
        logger.warning("[change_tracking] Listener registration failed: %s", _ct_init_err)

    # Create and populate database if it doesn't exist
    with app.app_context():
        if os.environ.get("ALEMBIC_RUNNING") != "1":
            # db.create_all() 을 여기서 무조건 부르지 않는다 — 기존 DB 가 있는데
            # SQLAlchemy 모델 메타데이터로 먼저 테이블을 만들어 버리면, alembic 이
            # 같은 테이블을 자기 DDL(정확한 인덱스 이름 등)로 만들려 할 때
            # "table already exists" 로 실패하고 alembic_version 은 갱신되지 않는다
            # — 재시도해도 영원히 같은 이유로 막힌다(2026-08-18 koat 26.08.11 업그레이드
            # 실패 + 완전 신규 설치도 동일 증상으로 재현됨, p6_37/p6_38 두 신규 테이블).
            # db.create_all() 이 필요한 경우(완전 신규 설치)와 그렇지 않은 경우를
            # 가르는 판단은 alembic_upgrade_db() 하나에게만 맡긴다.
            # Database migration on startup
            from aot.databases.models import alembic_upgrade_db
            alembic_upgrade_db(app)

            populate_db()

            # Seed AI Domain Glossary (term_alias, control_intent) within app context
            try:
                from aot.ai.services.ai_agent_service import bootstrap_ai_glossary, _warm_semantic_cache
                bootstrap_ai_glossary()
                # Semantic cache warmup also needs an app context; the module-import
                # call in initialize_engine_registry() defers to here.
                _warm_semantic_cache()
            except Exception as _bg_err:
                logger.warning("[Startup] bootstrap_ai_glossary failed: %s", _bg_err)

            # 지워진 장치의 사용자 코드 파일을 걷어낸다. 배포된 서버가 스스로
            # 낫게 하는 것이 목적이다 — 고아를 남긴 것은 코드의 잘못이므로,
            # 그 뒷정리를 운영자나 사용자에게 시켜서는 안 된다.
            from aot.utils.code_verification import purge_orphan_user_code
            purge_orphan_user_code()

            # Ensure AoT system MCP server entry exists and is active on every startup
            try:
                from aot.databases.models.mcp_server import MCPServer
                _aot_mcp = (
                    MCPServer.query.filter(MCPServer.command.contains('aot_mcp_server')).first()
                    or MCPServer.query.filter(MCPServer.name.ilike('%aot%')).first()
                )
                if _aot_mcp:
                    if not _aot_mcp.is_activated:
                        _aot_mcp.is_activated = True
                        db.session.commit()
                        logger.info(f"[Startup] Re-activated AoT MCP server: '{_aot_mcp.name}'")
                    
                    # [TASK_40] v29.1: Resolve the interpreter for the MCP subprocess.
                    # Must be the SAME interpreter running Flask so the subprocess shares
                    # its installed dependencies (flask_login, etc.). sys.executable is the
                    # venv python on a normal install; resolving from INSTALL_DIRECTORY/env
                    # can pick a stale/empty venv whose bin/python3 exists but has no
                    # site-packages (observed in Docker dev), causing ModuleNotFoundError.
                    python_bin = _resolve_mcp_python()
                    script_path = os.path.join(INSTALL_DIRECTORY, 'aot', 'aot_mcp_server.py')
                    _aot_mcp.command = f"{python_bin} {script_path}"
                    
                    if not _aot_mcp.scope or _aot_mcp.scope != 'general':
                        _aot_mcp.scope = 'general'
                    
                    db.session.commit()
                    logger.info(f"[Startup] Synchronized AoT MCP server command: '{_aot_mcp.command}'")
                else:
                    python_bin = _resolve_mcp_python()
                    script_path = os.path.join(INSTALL_DIRECTORY, 'aot', 'aot_mcp_server.py')
                    _aot_mcp = MCPServer(
                        name='AoT System Expert Server',
                        command=f"{python_bin} {script_path}",
                        scope='general',
                        is_activated=True
                    )
                    db.session.add(_aot_mcp)
                    db.session.commit()
                    logger.info(f"[Startup] Auto-created AoT MCP server: '{_aot_mcp.unique_id}'")
                # NOTE: the MCP subprocess is warm-STARTED in start_flask_ui.py (the
                # gunicorn entry), NOT here. create_app() also runs in the daemon
                # process, which does not serve AI chat and must not spawn a heavy
                # (~400MB) MCP subprocess. Warming only in the web entry keeps it
                # web-only. See warm_start_mcp_servers() below.
            except Exception as e:
                logger.warning(f"[Startup] AoT MCP server auto-setup failed: {e}")

            # Auto-provision AOT_MCP_API_KEY for the AoT System Expert Server.
            # This is a stdio MCP subprocess the app spawns and talks to itself
            # (see mcp_bridge_service.py / mcp_auth.authenticate_stdio) — without
            # a key in its env, every initialize handshake fails auth and the AI
            # gets 0 tools.
            #
            # 키는 **전용 서비스 계정** 명의로 발급한다. 예전에는 "키가 없는 첫
            # Admin/Editor" 를 골라 그 사람 명의로 발급했는데, 그러면 감사 로그가
            # 내부 AI 의 행위를 그 사람의 행위로 기록해 "누가 지시했는가" 가
            # 무너지고, 그 사람이 자기 키를 재발급하는 순간(api_key_hash 는 컬럼
            # 하나라 덮어쓰기다) 내부 AI 가 아무 에러 없이 도구를 전부 잃었다.
            # 자세한 배경은 mcp_auth.ensure_service_account 의 docstring 참조.
            try:
                if _aot_mcp:
                    from aot.ai.services.mcp_auth import ensure_service_account
                    from aot.databases.models import User
                    from aot.utils.system_pi import base64_encode_bytes
                    import base64 as _b64

                    service_user = ensure_service_account()
                    if service_user is None:
                        logger.warning(
                            "[Startup] Could not auto-provision AOT_MCP_API_KEY — no role "
                            "with edit_controllers exists to attach the service account to.")
                    else:
                        env_vars = dict(_aot_mcp.env_vars or {})
                        existing = env_vars.get('AOT_MCP_API_KEY')
                        holder = None
                        if existing:
                            try:
                                raw = _b64.b64decode(existing, validate=False)
                            except Exception:
                                raw = b''
                            holder = User.find_by_api_key(raw) if raw else None

                        # 갈아 끼우는 경우는 둘이다: 설정된 키가 유효하지 않거나,
                        # 예전 방식으로 **사람 계정** 명의로 발급돼 있는 경우.
                        # 그 사람의 api_key_hash 는 건드리지 않는다 — 본인이 외부
                        # 접속(ChatGPT/Claude 등)에 쓰고 있을 수 있고, 여기서 지우면
                        # 그쪽이 조용히 죽는다.
                        if holder is None or holder.id != service_user.id:
                            # 서비스 계정의 옛 키는 폐기하고 새로 하나만 남긴다.
                            # 사람 계정과 달리 여러 개를 들고 있을 이유가 없고,
                            # 남겨 두면 어느 것이 실제로 쓰이는 키인지 모른다.
                            for old in service_user.active_api_keys():
                                old.revoke()
                            raw_key = service_user.issue_api_key(
                                'AoT System Expert Server')
                            env_vars['AOT_MCP_API_KEY'] = base64_encode_bytes(raw_key)
                            _aot_mcp.env_vars = env_vars
                            db.session.commit()
                            if holder is not None:
                                logger.info(
                                    f"[Startup] AOT_MCP_API_KEY was issued in the name of the "
                                    f"human account '{holder.name}'; switched to the service "
                                    f"account '{service_user.name}'. That user's own API key "
                                    f"was left intact.")
                            else:
                                logger.info(
                                    f"[Startup] Auto-provisioned AOT_MCP_API_KEY for AoT System "
                                    f"Expert Server (service account: '{service_user.name}')")
            except Exception as e:
                logger.warning(f"[Startup] AOT_MCP_API_KEY auto-provision failed: {e}")

            # Auto-activate InfluxDB MCP Server if measurement_db_password is set.
            # This removes the need for users to manually visit InfluxDB web UI to configure.
            try:
                from aot.databases.models.mcp_server import MCPServer
                from aot.databases.models.misc import Misc
                _settings = Misc.query.first()
                if _settings and _settings.measurement_db_password:
                    _influx_mcp = MCPServer.query.filter(
                        MCPServer.command.contains('influxdb-mcp-server')
                    ).first()
                    if _influx_mcp and not _influx_mcp.is_activated:
                        _influx_mcp.is_activated = True
                        db.session.commit()
                        logger.info(f"[Startup] Auto-activated InfluxDB MCP server (token found in misc): '{_influx_mcp.name}'")
            except Exception as e:
                logger.warning(f"[Startup] InfluxDB MCP auto-activation failed: {e}")

            # Cleanup orphaned MCPServers (no agent mapped)
            # 'general' scope = shared system server, exempt from orphan cleanup
            try:
                from aot.databases.models.mcp_server import MCPServer, AgentMCPAccess
                from aot.databases.models.ai import AIAgent
                for mcp in MCPServer.query.filter_by(is_activated=True).all():
                    if mcp.scope == 'general':
                        continue  # 공유 서버는 에이전트 매핑 없어도 유지
                    has_agent = db.session.query(AgentMCPAccess).join(
                        AIAgent, AgentMCPAccess.agent_unique_id == AIAgent.unique_id
                    ).filter(AgentMCPAccess.mcp_unique_id == mcp.unique_id).first()
                    if not has_agent:
                        mcp.is_activated = False
                        logger.info(f"Startup cleanup: deactivated orphaned MCPServer '{mcp.name}'")
                db.session.commit()
            except Exception as e:
                logger.warning(f"Startup MCP cleanup failed: {e}")

    # Initialize APScheduler after DB is ready
    if os.environ.get("ALEMBIC_RUNNING") != "1" and os.environ.get("AOT_SKIP_SCHEDULER") != "1":
        from aot.ai.services.ai_scheduler_service import AISchedulerService
        AISchedulerService.init_app(app)
        

    # v17.0: Memory Profiler (Phase 0 - Baseline measurement)
    # Enable via environment variable: ENABLE_MEMORY_PROFILING=1
    if os.environ.get("ENABLE_MEMORY_PROFILING") == "1":
        try:
            from aot.utils.memory_profiler import MemoryProfiler
            MemoryProfiler.start_profiling()

            # Schedule hourly snapshots
            from apscheduler.schedulers.background import BackgroundScheduler
            profiler_scheduler = BackgroundScheduler()
            profiler_scheduler.add_job(
                func=MemoryProfiler.log_snapshot,
                trigger='interval',
                hours=1,
                id='memory_profiling'
            )
            profiler_scheduler.start()
            logger.info("[MemoryProfiler] Enabled with hourly snapshots")
        except Exception as e:
            logger.warning(f"[MemoryProfiler] Failed to initialize: {e}")

    # [Security] Initialize Talisman with robust defaults
    # CSP: Using 'self' as base, keeping '*' for legacy widget compatibility
    csp = {
        'default-src': ["'self'", '*', "'unsafe-inline'", "'unsafe-eval'"],
        'img-src': ["'self'", '*', 'data:', 'blob:', 'rtsp:', 'rtsps:'],
        # font-src must be explicit: CSP '*' does NOT match the 'data:' scheme, so
        # base64-embedded fonts (e.g. FullCalendar's IcoMoon icon font on /scheduler)
        # would fall back to default-src and be blocked without 'data:' here.
        'font-src': ["'self'", '*', 'data:'],
        'style-src': ["'self'", '*', "'unsafe-inline'"],
        'script-src': ["'self'", '*', "'unsafe-inline'", "'unsafe-eval'"],
        'connect-src': ["'self'", '*', 'rtsp:', 'rtsps:'],
        'media-src': ["'self'", '*', 'data:', 'blob:', 'rtsp:', 'rtsps:'],
        'worker-src': ["'self'", '*', 'blob:']
    }

    force_https = False
    # Skip reading Misc during Alembic runs (schema may be mid-upgrade)
    if os.environ.get("ALEMBIC_RUNNING") != "1":
        # Check user option to force all web connections to use SSL
        # Fail if the URI is empty (pytest is running)
        if app.config['SQLALCHEMY_DATABASE_URI'] != 'sqlite://':
            with session_scope(app.config['SQLALCHEMY_DATABASE_URI']) as new_session:
                misc = new_session.query(Misc).first()
                if misc:
                    update_layout(misc.custom_layout)
                    force_https = misc.force_https

    # CSRF 토큰 만료를 없애는 대신 넉넉히 늘리고(12시간), aot-csrf-refresh.js가
    # 20분마다 재서명된 토큰으로 갱신해 실제로 이 한계에 닿지 않게 한다.
    # (과거엔 기본값 3600s → 1시간 후 저장 시 오류가 나서 아예 None으로 없앴으나,
    # 무기한 토큰은 유출 시 영구히 유효하다는 문제가 있다.)
    app.config['WTF_CSRF_TIME_LIMIT'] = 12 * 60 * 60

    # Disable force_https and adjust cookies for Docker environment
    from aot.config import DOCKER_CONTAINER
    if DOCKER_CONTAINER:
        force_https = False
        app.config['SESSION_COOKIE_SECURE'] = False
        app.config['WTF_CSRF_SSL_STRICT'] = False
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # "90일간 유지"(remember_token)에도 세션 쿠키와 같은 Secure 를 적용한다.
    #
    # Talisman 의 `session_cookie_secure` 는 이름 그대로 **세션 쿠키만** 건드린다.
    # 그래서 force_https 를 켠 HTTPS 서버에서 session 에는 Secure 가 붙는데
    # remember_token 에는 안 붙는 상태였다(2026-08-12 실측) — **가장 오래 사는
    # 자격증명이 가장 약하게 보호되던 셈**이다. 90일짜리 토큰이 평문 HTTP 요청
    # 한 번(주소창에 http:// 를 치거나, 혼합 콘텐츠, 다운그레이드 유도)에 그대로
    # 실려 나간다. 세션 쿠키는 Secure 라 안 나가는데 이쪽만 나간다.
    app.config['REMEMBER_COOKIE_SECURE'] = force_https

    # force_https above already accounts for the user's Misc.force_https
    # setting (General Settings → "Force HTTPS") and the Docker override —
    # previously this was computed and then discarded here, so the setting
    # had no effect regardless of what the admin chose in the UI.
    Talisman(app,
             content_security_policy=csp,
             force_https=force_https,
             strict_transport_security=force_https,
             session_cookie_secure=force_https,
             session_cookie_http_only=True,
             frame_options='SAMEORIGIN')


def register_blueprints(app):
    """register blueprints to the app."""
    app.register_blueprint(routes_admin.blueprint)  # register admin views
    app.register_blueprint(routes_authentication.blueprint)  # register login/logout views
    app.register_blueprint(routes_password_reset.blueprint)  # register password reset views
    app.register_blueprint(routes_dashboard.blueprint)  # register dashboard views
    app.register_blueprint(routes_function.blueprint)  # register function views
    app.register_blueprint(routes_general.blueprint)  # register general routes
    app.register_blueprint(routes_device.blueprint)  # register device routes
    app.register_blueprint(routes_input.blueprint)  # register input routes
    app.register_blueprint(routes_method.blueprint)  # register method views
    app.register_blueprint(routes_output.blueprint)  # register output views
    app.register_blueprint(routes_page.blueprint)  # register page views
    app.register_blueprint(routes_remote_admin.blueprint)  # register remote admin views
    app.register_blueprint(routes_settings.blueprint)  # register settings views
    app.register_blueprint(routes_geo.blueprint)  # register geo views
    app.register_blueprint(routes_static.blueprint)  # register static routes
    app.register_blueprint(routes_notes_api.blueprint)  # register notes api routes
    app.register_blueprint(routes_ai_agent.blueprint)  # register ai agent routes
    app.register_blueprint(routes_tab.blueprint)  # register tab routes
    app.register_blueprint(routes_camera.blueprint)  # register camera routes
    app.register_blueprint(routes_orch_api.blueprint)  # register orch api routes
    app.register_blueprint(routes_mcp_api.blueprint)   # register mcp api routes
    app.register_blueprint(routes_ai_monitoring.ai_monitoring_bp)  # register ai monitoring routes
    from aot.aot_flask import routes_ai_api, routes_locale_api, routes_scheduler, routes_ai_context, routes_ai_portal, routes_integrations
    app.register_blueprint(routes_ai_api.blueprint)  # register ai api routes
    app.register_blueprint(routes_ai_context.blueprint)  # register ai context routes
    app.register_blueprint(routes_ai_portal.blueprint)  # register ai portal routes
    app.register_blueprint(routes_locale_api.blueprint)  # register locale api routes
    app.register_blueprint(routes_scheduler.blueprint)  # register scheduler routes
    app.register_blueprint(routes_integrations.blueprint)  # register external integrations (Google Calendar OAuth)
    from aot.aot_flask.routes_ai_library import ai_library_bp
    app.register_blueprint(ai_library_bp)  # register ai library routes
    from aot.aot_flask import routes_notice
    app.register_blueprint(routes_notice.blueprint)  # register notice board routes
    from aot.aot_flask import routes_legal
    app.register_blueprint(routes_legal.blueprint)  # register public legal pages (privacy/terms)


def register_widget_endpoints(app):
    if app.config['TESTING']:  # TODO: Add pytest endpoint test and remove this
        return

    try:
        dict_widgets = parse_widget_information()
    except Exception:
        logger.exception("register_widget_endpoints: parse_widget_information failed")
        return

    # Register endpoints for ALL widget types, not only those currently present in
    # the dashboard DB. Previously this was gated on the Widget table at startup, so
    # a widget added after the last restart would 404 on its endpoints until the next
    # restart. Each endpoint is added independently so one failure can't abort the rest.
    added = 0
    for each_widget_type, info in dict_widgets.items():
        if not isinstance(info, dict) or 'endpoints' not in info:
            continue
        for ep in info['endpoints']:
            try:
                rule, endpoint, view_func, methods = ep
            except Exception:
                logger.warning(
                    "register_widget_endpoints: malformed endpoint in %s: %r",
                    each_widget_type, ep)
                continue
            if endpoint in app.view_functions:
                continue
            try:
                app.add_url_rule(rule, endpoint, view_func, methods=methods)
                added += 1
            except Exception:
                logger.exception(
                    "register_widget_endpoints: failed to add %s (%s) for %s",
                    endpoint, rule, each_widget_type)
    logger.info("register_widget_endpoints: registered %d widget endpoint(s).", added)


def extension_babel(app):
    def get_locale():
        # Check if a user is logged in and a language is set
        try:
            user = User.query.filter(
                User.id == flask_login.current_user.id).first()
            if user and user.language != '':
                for key in LANGUAGES:
                    if key == user.language:
                        return key
        except AttributeError:  # Bypass endpoint test error "'AnonymousUserMixin' object has no attribute 'id'"
            pass

        # Check the session for a language
        try:
            from flask import session
            if session.get("language") and session['language'] in LANGUAGES:
                return session['language']
        except:
            pass

        # Check for the presence of AoT/.language with a language
        try:
            lang_path = os.path.join(INSTALL_DIRECTORY, ".language")
            if os.path.exists(lang_path):
                with open(lang_path) as f:
                    language = f.read().split(":")[0]
                    if language and language in LANGUAGES:
                        return language
        except:
            pass

        return request.accept_languages.best_match(LANGUAGES.keys())
    
    def get_timezone():
        # Check if a timezone is set in the Misc database
        try:
            from aot.databases.models import Misc
            misc = Misc.query.first()
            if misc and misc.timezone:
                return misc.timezone
        except Exception:
            pass
        return 'UTC'

    babel = Babel(app, locale_selector=get_locale, timezone_selector=get_timezone)
    return app


def extension_compress(app):
    compress = Compress()
    compress.init_app(app)
    return app


def extension_limiter(app):
    def get_key_func():
        """Custom key_func for flask-limiter to handle both logged-in and logged-out requests."""
        if get_ip_address():
            str_return = get_ip_address()
        else:
            str_return = '0.0.0.0'
        if current_user and hasattr(current_user, 'name'):
            str_return += f'/{current_user.name}'
        return str_return

    limiter = Limiter(
        app=app,
        key_func=get_key_func,
        headers_enabled=True,
    )
    limiter.limit("300/hour")(routes_authentication.blueprint)
    # newremote() issues a new RemoteAccessToken per call (rare, sensitive —
    # an admin adding a remote host) — matches the password-reset endpoint's
    # own "rare and sensitive" limit below rather than the blueprint default.
    limiter.limit("20/hour")(routes_authentication.newremote)
    # remote_admin_login/remote_auth are called once per configured remote
    # host on every load of /remote/setup or /remote/input, so the blueprint
    # default is too tight for real multi-host use. The credential itself is
    # now a 256-bit issued token (see RemoteAccessToken), so this limit is
    # defense-in-depth against abuse/DoS, not brute-force protection — no
    # need for the old exempt()-then-3000/hour override.
    limiter.limit("1000/hour")(routes_authentication.remote_admin_login)
    limiter.limit("1000/hour")(routes_authentication.remote_auth)
    limiter.limit("20/hour")(routes_password_reset.blueprint)
    limiter.limit("200/minute")(api_blueprint)

    # Register a user-friendly handler for 429 responses so browsers receive
    # a redirect to the login page instead of a bare 429 body.
    @app.errorhandler(429)
    def too_many_requests(e):
        from flask import request as _req, redirect as _redir, url_for as _url_for, jsonify as _jsonify
        retry_after = getattr(e, 'retry_after', None)
        logger.warning("Rate limit exceeded: %s %s (retry_after=%s)", _req.method, _req.path, retry_after)
        if _req.path.startswith('/api/'):
            resp = _jsonify({'error': 'Too Many Requests', 'retry_after': str(retry_after)})
            resp.status_code = 429
            if retry_after:
                resp.headers['Retry-After'] = str(retry_after)
            return resp
        # For browser requests, redirect to login with a flash message
        from flask import flash as _flash
        _flash("서버 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.", "error")
        return _redir(_url_for('routes_authentication.login_check'))

    return app


# Passing the API key in the query string (?api_key=…) is deprecated: it leaks
# the credential into web-server access logs, reverse-proxy logs and Referer
# headers — the same class of problem the Remote Admin rewrite removed. The
# header forms (X-API-KEY / Authorization: Basic) are unaffected.
#
# It stays supported for now because docs/API.md has advertised it, so removing
# it outright could break integrations we can't see. This records who is still
# using it so the removal can be made on evidence rather than a guess.
_API_KEY_URL_AUDIT_INTERVAL = 3600  # seconds, per (user, ip)
_api_key_url_last_audit = {}


def _warn_api_key_in_url(req, user):
    """Log (and periodically audit) a successful auth via ?api_key=…"""
    try:
        ip = (req.environ.get('HTTP_X_FORWARDED_FOR')
              or req.remote_addr or 'unknown')
        if ',' in ip:
            ip = ip.split(',')[0].strip()

        logger.warning(
            "DEPRECATED: API key supplied in the URL query string "
            "(user=%s ip=%s path=%s agent=%s). Use the X-API-KEY header "
            "instead — query strings end up in access logs and Referer headers.",
            user.name, ip, req.path, req.headers.get('User-Agent', '')[:120])

        # The logger line is per-request; the audit entry is throttled so a
        # polling integration can't fill the audit table with one row per poll.
        import time as _time
        key = (user.id, ip)
        now = _time.monotonic()
        last = _api_key_url_last_audit.get(key, 0)
        if now - last >= _API_KEY_URL_AUDIT_INTERVAL:
            _api_key_url_last_audit[key] = now
            from aot.utils import audit
            from aot.utils.audit import audit_log
            audit_log(audit.API_KEY_URL_AUTH, user_id=user.id,
                      username=user.name, ip_address=ip,
                      detail='deprecated URL query-string auth; path={} agent={}'.format(
                          req.path, req.headers.get('User-Agent', '')[:120]))
    except Exception:
        # Never let deprecation bookkeeping break authentication.
        logger.exception("Failed to record deprecated URL api_key usage")


#: 상태를 바꾸지 않는 HTTP 메서드.
_SAFE_METHODS = frozenset(('GET', 'HEAD', 'OPTIONS'))

#: 메서드는 POST 지만 읽기 전용인 경로. 여기 없는 POST/PUT/PATCH/DELETE 는
#: readonly 키에서 거부된다.
#:
#: `/data_batch` 는 대시보드가 여러 측정을 한 번에 조회하려고 만든 것이라 본문이
#: 필요해 POST 일 뿐, 아무것도 바꾸지 않는다(routes_general.py 참조). 원격 AoT
#: 수집도 이 경로로 값을 받아오므로 여기서 막으면 수집 전용 키가 성립하지 않는다.
#:
#: **경로를 추가할 때는 그 핸들러가 정말 아무것도 쓰지 않는지 본문을 읽고 확인할
#: 것.** 이 목록이 스코프의 유일한 구멍이다.
_READONLY_POST_PATHS = frozenset(('/data_batch',))


def _raw_api_keys_from_request(req):
    """요청이 실어 온 API 키 후보(평문 bytes)를 순서대로 내놓는다.

    `load_user_from_request` 와 스코프 가드가 **같은 규칙**으로 키를 읽어야
    한다. 두 곳이 서로 다른 경로를 보면, 가드가 못 보는 경로로 들어온 키는
    스코프 없이 통과한다.
    """
    candidates = []

    raw = req.args.get('api_key')
    if raw:
        candidates.append(raw.replace(' ', '+'))

    auth = req.headers.get('Authorization') or ''
    if auth.startswith('Basic '):
        candidates.append(auth[len('Basic '):])
    elif auth.startswith('Bearer '):
        candidates.append(auth[len('Bearer '):])

    header = req.headers.get('X-API-KEY')
    if header:
        candidates.append(header)

    for value in candidates:
        try:
            yield base64.b64decode(value)
        except Exception:
            continue


def register_api_key_scope_guard(app):
    """readonly 키로 들어온 요청에서 상태 변경을 막는다.

    **역할(role) 권한 검사보다 앞단에서 막는 이유**: `user_has_permission()` 은
    라우트가 스스로 불러야 효력이 있다. 부르지 않는 라우트가 하나라도 있으면
    그 경로로 스코프가 뚫린다. 게다가 API 키 인증은 `/api/` 뿐 아니라
    `@login_required` 가 붙은 **모든** 라우트에 통하므로 검사 대상이 앱 전체다.
    HTTP 메서드는 라우트가 무엇을 하든 요청 자체에 실려 오므로, 여기서 한 번
    거르는 편이 빠짐없이 막힌다.

    세션(쿠키)으로 로그인한 사용자는 영향을 받지 않는다 — 요청에 API 키가 없으면
    가드는 아무 일도 하지 않는다.
    """
    @app.before_request
    def _enforce_api_key_scope():
        if request.method in _SAFE_METHODS:
            return None
        if request.path in _READONLY_POST_PATHS:
            return None

        try:
            from aot.databases.models.user_api_key import UserAPIKey
            for raw_key in _raw_api_keys_from_request(request):
                row = UserAPIKey.find_active(raw_key)
                if row is None:
                    continue
                if not row.is_readonly:
                    return None          # 정상 권한 키 — 통과
                logger.warning(
                    "Read-only API key '%s' (user_id=%s) attempted %s %s",
                    row.name or row.unique_id[:8], row.user_id,
                    request.method, request.path)
                message = ('This API key is read-only. It cannot perform '
                           '{m} requests.'.format(m=request.method))
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Forbidden', 'message': message}), 403
                return message, 403
        except Exception:
            # 가드가 죽어서 요청이 통과하면 스코프가 없는 것과 같다. 다만 여기서
            # 예외를 올리면 앱 전체가 500 이 되므로, 로그를 남기고 거부한다 —
            # 키를 못 읽었으면 애초에 이 요청은 세션 로그인일 가능성이 높지만,
            # 확신할 수 없을 때 통과시키는 쪽을 택하지 않는다.
            logger.exception("API key scope guard failed; denying the request")
            return jsonify({'error': 'Forbidden'}), 403

        return None

    return app


def _never_share_cache_a_response_that_sets_a_cookie(response):
    """`Set-Cookie` 가 실린 응답은 절대 공유 캐시에 들어가면 안 된다.

    들어가면 그 안에 박힌 **세션 ID 가 모든 클라이언트에게 배포된다.** 뒤에
    오는 사람은 앞사람의 세션을 그대로 물려받아 앞사람 계정으로 로그인된
    상태가 되고, 마지막으로 캐시에 들어간 사람이 전원의 신원이 된다.
    기기도 브라우저도 다른데 신원이 함께 바뀌는 증상이 이것이다.

    실제로 그 상태였다(2026-08-12):
      /favicon.png → `Cache-Control: public, max-age=31536000` + Set-Cookie
      /custom.css  → 앱은 no-store 를 붙였지만 엣지(openresty)의 `expires`
                     규칙이 `max-age=66131` 로 덮어써서 공개 캐시 가능해짐
    둘 다 `/static/` 밖의 Flask 라우트라 세션이 열리고, 렌더 도중 폼
    인스턴스화(CSRF 토큰 생성)로 세션이 수정돼 Set-Cookie 가 붙었다.

    개별 라우트를 하나씩 고치는 것으로는 부족하다 — 새 라우트가 하나만
    어긋나도 같은 사고가 재발하고, 증상이 "가끔 남의 계정으로 보인다" 라
    원인에 도달하기까지 오래 걸린다. 그래서 **출구에서 한 번에** 막는다.
    여기서 강제하는 것은 캐시 공유 금지뿐이고, 캐시 여부 자체는 각 라우트가
    정한 값을 존중한다(private 은 브라우저 개인 캐시는 계속 허용한다).

    **주의: 엣지/nginx 의 `expires` 지시자는 이 헤더를 통째로 덮어쓴다.**
    서버 쪽에서 `.css`/`.png` 에 일괄 `expires` 를 걸어 두면 여기서 무엇을
    붙이든 소용없다 — 그래서 자산 라우트는 애초에 Set-Cookie 를 내보내지
    않도록 `extension_session()` 에서 세션-생략/읽기전용으로 분류한다.
    """
    try:
        if 'Set-Cookie' not in response.headers:
            return response
        cc = response.cache_control
        if cc.public:
            cc.public = False
        if not (cc.private or cc.no_store):
            cc.private = True
    except Exception:
        pass
    return response


def register_response_guards(app):
    """응답 출구 가드 등록 (테스트에서 단독으로 붙일 수 있도록 분리)."""
    app.after_request(_never_share_cache_a_response_that_sets_a_cookie)
    return app


def extension_login_manager(app):
    login_manager = flask_login.LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def user_loader(user_id):
        # `User.get_id()` 가 만든 `<id>|<session_auth_hash>` 를 되푼다.
        raw = str(user_id or '')
        uid, sep, token = raw.partition('|')

        user = User.query.filter(User.id == uid).first()
        if not user:
            return
        # 계정이 꺼지면 이미 열려 있던 세션도 다음 요청에서 끊긴다. 로그인
        # 시점의 검사(routes_authentication.py)만으로는 이미 로그인해 둔
        # 사람이 그대로 남아, 끄는 행위가 즉시 효력을 갖지 못한다.
        if not user.is_enabled:
            return

        # 비밀번호에서 파생된 해시를 대조한다. 비밀번호가 바뀌면 값이 달라져
        # **다른 기기의 세션과 90일 remember 토큰이 그 자리에서 무효가 된다.**
        # (User.session_auth_hash 주석 참조)
        #
        # 해시가 아예 없는 옛 형식(`'1'`)은 **거부한다.** 받아 주면 이 방어가
        # 통째로 무의미해진다 — 무효화하려는 대상인 유출된 옛 remember 쿠키가
        # 정확히 그 옛 형식이기 때문이다. 대신 이 변경을 배포하는 순간
        # **모든 사용자가 한 번 로그아웃된다.**
        if not sep or not user.verify_session_auth_hash(token):
            return
        return user

    @login_manager.request_loader
    def load_user_from_request(req):
        try:  # first, try to login using the api_key url arg (DEPRECATED)
            api_key = req.args.get('api_key').replace(' ', '+')
            api_key = base64.b64decode(api_key)
            user = User.find_by_api_key(api_key)
            if user:
                _warn_api_key_in_url(req, user)
                return user
        except Exception:
            # Overwhelmingly "no api_key on this request at all" (AttributeError
            # on the .replace() above) — expected on almost every request, not
            # worth logging. A narrower except would also work for this reason,
            # but bare `except:` additionally swallows SystemExit/KeyboardInterrupt.
            pass

        try:  # next, try to login using Basic Auth
            api_key = req.headers.get('Authorization')
            api_key = api_key.replace('Basic ', '', 1)
            api_key = base64.b64decode(api_key)
            user = User.find_by_api_key(api_key)
            if user:
                return user
        except Exception:
            pass

        try:  # next, try to login using X-API-KEY
            api_key = req.headers.get('X-API-KEY')
            api_key = base64.b64decode(api_key)
            user = User.find_by_api_key(api_key)
            if user:
                return user
        except Exception:
            pass

        # User unable to be logged in
        return

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith('/api/'):
            response = jsonify({'error': 'Unauthorized'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response, 401
        flash(gettext('Please log in to access this page'), "error")
        return redirect(url_for('routes_authentication.login_check'))

    return app


def extension_session(app):
    app.config['SESSION_TYPE'] = 'filesystem'

    if os.environ.get('DOCKER_CONTAINER'):
        # Under Docker, write sessions to /app/aot/databases/flask_session. On Windows
        # Docker this path is overlaid by a named volume (see docker-compose.yml) that
        # lives on the Linux VM filesystem — the NTFS bind mount's 9p/virtiofs layer does
        # not guarantee atomic rename, so concurrent workers corrupt session pickles,
        # producing empty sessions and "CSRF token missing / tokens do not match".
        session_dir = '/app/aot/databases/flask_session'
    else:
        # Partition session files by UID to prevent PermissionError when
        # running daemon (root) vs UI (normal user)
        uid = os.getuid() if hasattr(os, 'getuid') else os.getpid()
        session_dir = os.path.join(os.getcwd(), f'flask_session_{uid}')
    os.makedirs(session_dir, exist_ok=True)
    app.config['SESSION_FILE_DIR'] = session_dir

    # cachelib 의 기본 threshold 는 500 이다. 세션 파일은 **로그인한 사람 수**가
    # 아니라 **세션 쿠키를 받은 방문 수**만큼 쌓인다 — 로그인 페이지를 열기만 한
    # 브라우저, 봇, 404 한 번도 각자 파일 하나다(실측: 502개 중 로그인 세션은 23개,
    # 나머지 479개가 익명). 파일 수가 threshold 를 넘으면 cachelib 은 세션을 저장할
    # 때마다 `_remove_older()` 로 **만료가 가장 이른 것부터 지운다** — 익명 쓰레기가
    # 다 소진되면 그 다음은 살아 있는 로그인 세션이다. 지워진 사람은 아무 예고 없이
    # 로그아웃된다. 익명 세션 쪽을 줄이는 것이 정공법이지만(로그인 폼의 CSRF 토큰을
    # 담아야 해서 없앨 수는 없다), 우선 실제 사용자가 밀려나지 않을 만큼 올린다.
    # 파일 하나가 100~300B 라 1만 개라도 3MB 수준이다.
    app.config.setdefault('SESSION_FILE_THRESHOLD', 10000)

    Session(app)

    # Defense in depth: purge any session files that fail to unpickle on startup.
    # The named volume prevents new corruption; this clears pre-existing bad files
    # (e.g. left over from before the volume fix) that would otherwise yield empty
    # sessions with no CSRF token.
    _purge_corrupt_session_files(session_dir)

    # Skip the session entirely for /static/ requests. Static assets never need a
    # session, but the filesystem session backend otherwise opens (reads) and
    # saves (writes) a session file — and emits a Set-Cookie — on every single
    # asset request, adding per-request disk I/O on the (single) worker.
    # On the deploy server nginx serves /static directly so these never reach
    # Flask; this also covers local/dev (no nginx) and any nginx fallback.
    from flask import request as _request
    from flask.sessions import SecureCookieSession

    _inner_interface = app.session_interface

    # sid -> 마지막으로 디스크에 쓴 시각(monotonic). 아래 save_session 이 "안 바뀐
    # 세션은 안 쓴다" 로 바뀌면서 파일의 TTL(31일)도 함께 갱신되지 않게 되므로,
    # 읽기만 하는 세션도 주기적으로 한 번은 다시 써 준다. 세션 내용을 건드리지
    # 않고 프로세스 메모리에만 두는 이유는, 갱신용 키를 세션에 심으면 그 쓰기
    # 자체가 아래에서 막으려는 경합에 다시 참여하기 때문이다. (workers=1 이라
    # 프로세스 메모리로 충분하고, 재시작 후 한 번 더 쓰는 것은 무해하다.)
    _session_touch = {}
    _SESSION_TOUCH_INTERVAL = 3600.0  # 1시간

    class _StaticSkippingSessionInterface:
        """Delegates to the real session interface, but treats /static/ requests
        as session-less (null session, no save, no Set-Cookie)."""

        def __getattr__(self, name):
            return getattr(_inner_interface, name)

        # `/static/` 밖에 있지만 세션이 전혀 필요 없는 자산 라우트들.
        #
        # 이들은 Flask 라우트라 세션이 열리고, 렌더 도중 폼 인스턴스화(CSRF 토큰
        # 생성) 같은 부수효과로 세션이 수정돼 **Set-Cookie 가 붙는다.** 그런데
        # 응답 자체는 오래 캐시되는 자산이라(favicon 은 `public, max-age=1년`),
        # 중간 캐시가 저장하는 순간 그 세션 ID 가 모든 사람에게 배포된다.
        # (출구의 `_never_share_cache_a_response_that_sets_a_cookie` 가 그 조합을
        # 막지만, 애초에 세션을 만들지 않는 편이 낫다 — 로그인도 안 한 방문자
        # 때문에 세션 파일이 쌓이는 것도 여기서 함께 줄어든다.)
        #
        # `/custom.css` 는 여기에 **넣지 않는다** — `current_user.theme` 를 읽어야
        # 해서 세션이 필요하다. 대신 그 응답은 `no-store` 로 나간다.
        _SESSIONLESS_PATHS = ('/favicon.png', '/favicon.ico')

        # 세션을 **읽어야 하지만 쓸 일은 없는** 자산 라우트.
        #
        # `/custom.css` 는 `current_user.theme` 로 다크/라이트를 가르므로 세션이
        # 필요하다. 그런데 렌더 중 `SettingsCustomUI()` 를 인스턴스화하면서 CSRF
        # 토큰이 생겨 세션이 수정되고, 그 결과 **CSS 응답에 Set-Cookie 가 붙는다.**
        # 이 응답이 캐시되면 그 세션 ID 가 모두에게 배포된다(2026-08-12 실제로
        # 엣지가 그 상태였다 — 몇 분 전 방문자의 세션 쿠키를 계속 재발행).
        #
        # 앱이 `no-store` 를 붙여도 소용없었다: nginx/openresty 의 `expires` 지시자가
        # Cache-Control 을 통째로 덮어쓴다. **헤더로는 막을 수 없으므로 쿠키를 아예
        # 내보내지 않는다.** 읽기는 그대로 되니 테마 판정은 계속 동작한다.
        _READONLY_SESSION_PATHS = ('/custom.css',)

        @staticmethod
        def _is_static():
            try:
                path = _request.path
                return (path.startswith('/static/') or
                        path in _StaticSkippingSessionInterface._SESSIONLESS_PATHS)
            except Exception:
                return False

        def open_session(self, app, request):
            if self._is_static():
                # A writable, throwaway session — NOT a null session. Missing
                # static files (e.g. the .js.map / .css.map sourcemaps browsers
                # request automatically) 404 into full HTML error-page rendering,
                # whose global context processor instantiates a Flask-WTF form and
                # generates a CSRF token — which writes to the session. A null
                # session raises "no secret key was set" on that write, turning
                # every missing sourcemap into a 500 (and the 500 handler renders
                # the same template, failing again). This session accepts the write
                # in-memory; save_session() below is still a no-op for /static/, so
                # there is no disk I/O and no Set-Cookie — the optimization stands.
                return SecureCookieSession()
            return _inner_interface.open_session(app, request)

        def save_session(self, app, session, response):
            if self._is_static():
                return

            # 읽기 전용 자산 라우트 — 저장도 Set-Cookie 도 하지 않는다.
            # (위 _READONLY_SESSION_PATHS 주석 참조)
            try:
                if _request.path in self._READONLY_SESSION_PATHS:
                    return
            except Exception:
                pass

            # ── 안 바뀐 세션은 다시 쓰지 않는다 (lost update 방지) ──
            #
            # flask-session 0.5.0 의 save_session 은 session.modified 를 보지 않고
            # **매 요청마다** `dict(session)` 전체를 파일에 덮어쓴다. gunicorn 은
            # workers=1 · gthread 다중 스레드라 요청이 겹치는데, 겹친 두 요청은
            # 각자 시작 시점의 스냅샷을 들고 있다가 끝날 때 통째로 되쓴다 —
            # 늦게 끝난 쪽이 먼저 끝난 쪽의 변경을 지운다(전형적인 lost update).
            #
            # 지워지는 것이 CSRF 토큰이면 다음 POST 가 400 으로 떨어져
            # "세션이 만료되었습니다" 가 뜨고, _user_id 면 그 자리에서 로그아웃된다.
            # 새로고침하면 멀쩡한 이유도 여기 있다 — 경합이 없는 요청 하나가
            # 지나가면 세션이 다시 온전해진다.
            #
            # 실측(로컬 도커, /custom.css 10개 동시 + 언어 변경 1개): 3회 중 2회
            # 언어 변경이 유실. 동시 요청이 없으면 3회 3회 모두 저장.
            #
            # 겹치는 요청의 대부분은 세션을 **읽기만** 한다(/custom.css 는
            # current_user.theme 를 보므로 세션이 필요해 /static 처럼 건너뛸 수도
            # 없다). 그 요청들이 쓰지 않게 하면 경합 자체가 사라진다.
            sid = getattr(session, 'sid', None)
            now = time.monotonic()
            if not getattr(session, 'modified', True):
                last = _session_touch.get(sid) if sid else None
                if last is not None and (now - last) < _SESSION_TOUCH_INTERVAL:
                    return  # 최근에 썼다 — 파일 TTL 도 아직 넉넉하다
            if sid:
                if len(_session_touch) > 20000:
                    _session_touch.clear()  # 무한 증가 방지 (재계산은 무해)
                _session_touch[sid] = now
            return _inner_interface.save_session(app, session, response)

    app.session_interface = _StaticSkippingSessionInterface()

    return app


def _purge_corrupt_session_files(session_dir):
    """Remove unreadable/corrupt session files on startup.

    Flask-Session's 'filesystem' backend stores each session via cachelib's
    FileSystemCache, whose on-disk format is a 4-byte little-endian expiry
    timestamp followed by the pickled value. A file is corrupt only if that
    pickle payload fails to load — so the 4-byte header MUST be skipped first.
    Reading from offset 0 mis-parses the expiry header as a pickle opcode and
    flags EVERY valid session as corrupt, deleting all live logins on each
    startup (observed: "invalid load key 'Y'/'\\x00'/..." on healthy files).

    이미 **만료된** 세션 파일도 함께 걷어낸다. 안 걷으면 파일 수가 계속 늘고,
    cachelib 은 threshold 를 넘는 순간 "만료가 이른 것부터" 지우기 시작하는데 그
    대상에는 살아 있는 로그인 세션도 섞인다(사용자 입장에서는 예고 없는 로그아웃).
    만료된 것은 어차피 아무도 못 쓰므로, 그 압력을 미리 없애 두는 편이 낫다.
    """
    import glob
    import pickle
    import struct
    now = time.time()
    removed = 0
    expired = 0
    for fpath in glob.glob(os.path.join(session_dir, '*')):
        try:
            with open(fpath, 'rb') as f:
                header = f.read(4)
                if len(header) < 4:
                    raise ValueError("truncated session file (missing expiry header)")
                pickle.load(f)  # validate the value payload after the 4-byte header
            # cachelib 포맷: 4바이트 리틀엔디언 만료시각(0 = 무기한)
            stamp = struct.unpack('<I', header)[0]
            if stamp and stamp <= now:
                os.remove(fpath)
                expired += 1
        except Exception:
            try:
                os.remove(fpath)
                removed += 1
            except Exception:
                pass
    if removed or expired:
        logger.info(
            f"Purged {removed} corrupt and {expired} expired session file(s) "
            f"from {session_dir}")


def extension_csrf(app):
    """CSRF 보호를 켜고, 면제 대상을 **여기 한 곳에서만** 정한다.

    면제를 흩어 놓으면(뷰마다 데코레이터) 무엇이 보호 밖인지 세어 보려면 레포
    전체를 뒤져야 한다. 목록이 짧게 유지되는 한, 한자리에 모아 두는 편이 감사에
    유리하다.
    """
    from aot.aot_flask.extensions import csrf
    from aot.aot_flask.api import api_blueprint
    csrf.init_app(app)
    csrf.exempt(api_blueprint)

    # `/data_batch` — POST 지만 아무것도 쓰지 않는 조회 전용 엔드포인트다.
    #
    # 왜 면제하나: CSRF 는 브라우저가 **자동으로 딸려 보내는** 자격증명(세션
    # 쿠키)으로 상태가 바뀌는 것을 막는 장치다. 이 경로는 상태를 바꾸지 않고,
    # 교차 출처 공격자는 동일 출처 정책 때문에 응답을 읽을 수도 없다. 반면
    # API 키로 붙는 클라이언트(원격 AoT 수집 — utils/remote_aot_client.py 의
    # `data_batch()`)는 세션이 없어 CSRF 토큰을 만들 방법이 아예 없다.
    # 면제하지 않으면 스코프 가드가 이 경로를 읽기 전용 키에 열어 줘도
    # (app.py `_READONLY_POST_PATHS`) CSRF 가 그 앞에서 막아, "수집 전용 키" 가
    # 성립하지 않는다. 실제로 그 상태였다.
    #
    # **전제: 이 핸들러는 아무것도 쓰지 않는다.** 쓰기가 생기면 이 면제는 즉시
    # 잘못된 것이 된다. 그 전제는 aot/tests/test_data_batch_readonly.py 가
    # 정적으로 고정한다 — 쓰기 호출이 들어오면 테스트가 깨진다.
    from aot.aot_flask.routes_general import data_batch
    csrf.exempt(data_batch)

    # CSRF 검증 실패 시 400 대신 로그인 페이지로 리다이렉트.
    # 서버 재시작 후 세션이 만료/손상되면 브라우저의 기존 CSRF 토큰이 무효화되어
    # 로그인 폼 제출이 400으로 실패하는 문제를 방지한다.
    from flask_wtf.csrf import CSRFError
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        """CSRF 실패를 400 대신 사람이 읽을 수 있는 결과로 바꾼다.

        **로그인 여부로 갈라야 한다.** 예전에는 무조건 로그인 페이지로 보내면서
        "세션이 만료되었습니다" 를 띄웠는데, 로그인한 사람에게 그건 거짓말이다 —
        세션은 멀쩡하고 폼에 실려 온 토큰만 낡은 것이다(탭을 오래 열어 뒀거나,
        서버 재시작으로 토큰이 새로 발급됐거나). 그런데 화면은 "만료됐으니 다시
        로그인하라" 며 로그인 페이지를 보여 주고, 새로고침하면 멀쩡히 들어가진다.
        사용자에게는 로그인 상태가 오락가락하는 것으로 보인다.

        XHR 에는 리다이렉트를 주지 않는다. 302 를 받은 fetch/XHR 은 로그인 HTML
        을 200 으로 받아 성공으로 오해하거나 JSON 파싱에서 죽는다 — 위젯 저장이
        아무 말 없이 안 되는 증상이 이것이었다.
        """
        from flask import (request as _req, redirect as _redir,
                           url_for as _url_for, flash as _flash,
                           jsonify as _jsonify)
        authed = False
        try:
            authed = bool(current_user.is_authenticated)
        except Exception:
            pass

        logger.warning("CSRF validation failed: %s %s (authenticated=%s)",
                       _req.method, _req.path, authed)

        wants_json = (
            _req.accept_mimetypes.best == 'application/json' or
            _req.is_json or
            _req.headers.get('X-Requested-With') == 'XMLHttpRequest')

        if authed:
            msg = gettext(
                "The security token for this page had expired. Nothing was "
                "saved — please try again.")
            if wants_json:
                return _jsonify({'status': 'error', 'error': 'csrf', 'message': msg}), 400
            _flash(msg, "error")
            # 로그인 페이지로 보내지 않는다. 로그인은 유지되고 있다.
            return _redir(_req.referrer or _url_for('routes_general.home'))

        msg = gettext("Your session has expired. Please log in again.")
        if wants_json:
            return _jsonify({'status': 'error', 'error': 'csrf', 'message': msg}), 401
        _flash(msg, "error")
        return _redir(_url_for('routes_authentication.login_check'))

    return app


def extension_cache(app):
    from aot.aot_flask.extensions import cache
    cache.init_app(app)
    return app
