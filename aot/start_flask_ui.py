# coding=utf-8
"""Starts the aot flask UI."""
import argparse
import sys
import os

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))

from aot.config import ENABLE_FLASK_PROFILER
from aot.aot_flask.app import create_app, warm_start_mcp_servers

app = create_app()  # required by the wsgi config and main()

# Web-only: warm-start MCP subprocesses so the AI has device tools from the first
# query. Kept OUT of create_app() so the daemon (which also calls create_app) does
# not spawn these heavy subprocesses. Skipped under alembic to avoid migration-time
# side effects.
if os.environ.get("ALEMBIC_RUNNING") != "1":
    try:
        warm_start_mcp_servers(app)
    except Exception as _warm_err:  # never block server startup
        import logging
        logging.getLogger(__name__).warning("MCP warm-start scheduling failed: %s", _warm_err)

# Flask profiler
if ENABLE_FLASK_PROFILER:
    import flask_profiler
    flask_profiler.init_app(app)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="AoT Flask HTTP server.")

    options = parser.add_argument_group('Options')
    options.add_argument('-d', '--debug', action='store_true',
                         help="Run Flask with debug=True (Default: False)")
    options.add_argument('-s', '--ssl', action='store_true',
                         help="Run Flask without SSL (Default: Enabled)")

    options.add_argument('-p', '--port', type=int, default=None,
                         help="Port to run on (Default: 443 for SSL, 80 for non-SSL)")

    args = parser.parse_args()

    debug = args.debug

    if args.ssl:
        port = args.port if args.port is not None else 80
        app.run(host='0.0.0.0', port=port, debug=debug)
    else:
        # Locate the SSL certificates for forced-HTTPS
        file_path = os.path.abspath(__file__)
        dir_path = os.path.dirname(file_path)
        cert = os.path.join(dir_path, "aot_flask/ssl_certs/server.crt")
        privkey = os.path.join(dir_path, "aot_flask/ssl_certs/server.key")
        context = (cert, privkey)
        port = args.port if args.port is not None else 443
        app.run(host='0.0.0.0', port=port, ssl_context=context, debug=debug)
