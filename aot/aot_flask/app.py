# coding=utf-8
#
#  app.py - Flask web server for AoT
#
import base64
import logging
import os
import sys

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
    (~400MB) subprocesses. Runs in a daemon thread so it never blocks boot. One
    retry covers the transient 'started but not ready yet' 0-tools race."""
    import threading
    import time as _t

    def _warm():
        try:
            with app.app_context():
                from aot.databases.models.mcp_server import MCPServer
                from aot.ai.services.mcp_bridge_service import MCPBridgeService
                for srv in MCPServer.query.filter_by(is_activated=True).all():
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
            db.create_all()
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


def extension_login_manager(app):
    login_manager = flask_login.LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def user_loader(user_id):
        user = User.query.filter(User.id == user_id).first()
        if not user:
            return
        # 계정이 꺼지면 이미 열려 있던 세션도 다음 요청에서 끊긴다. 로그인
        # 시점의 검사(routes_authentication.py)만으로는 이미 로그인해 둔
        # 사람이 그대로 남아, 끄는 행위가 즉시 효력을 갖지 못한다.
        if not user.is_enabled:
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

    class _StaticSkippingSessionInterface:
        """Delegates to the real session interface, but treats /static/ requests
        as session-less (null session, no save, no Set-Cookie)."""

        def __getattr__(self, name):
            return getattr(_inner_interface, name)

        @staticmethod
        def _is_static():
            try:
                return _request.path.startswith('/static/')
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
    """
    import glob
    import pickle
    removed = 0
    for fpath in glob.glob(os.path.join(session_dir, '*')):
        try:
            with open(fpath, 'rb') as f:
                if len(f.read(4)) < 4:
                    raise ValueError("truncated session file (missing expiry header)")
                pickle.load(f)  # validate the value payload after the 4-byte header
        except Exception:
            try:
                os.remove(fpath)
                removed += 1
            except Exception:
                pass
    if removed:
        logger.info(f"Purged {removed} corrupt session file(s) from {session_dir}")


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
        from flask import request as _req, redirect as _redir, url_for as _url_for, flash as _flash
        logger.warning("CSRF validation failed: %s %s — redirecting to login", _req.method, _req.path)
        _flash("세션이 만료되었습니다. 다시 로그인해주세요.", "error")
        return _redir(_url_for('routes_authentication.login_check'))

    return app


def extension_cache(app):
    from aot.aot_flask.extensions import cache
    cache.init_app(app)
    return app
