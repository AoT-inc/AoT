# -*- coding: utf-8 -*-
#
# service_control.py - Environment-aware restart/reload of the aot services.
#
# Single entry point for every place that needs to reload the web frontend
# or restart the daemon. Strategy is chosen by runtime environment:
#
#   systemd (Raspberry Pi / Debian):
#       the setuid aot_wrapper binary -> service aotflask reload|restart,
#       service aot restart (unchanged legacy path)
#   Docker:
#       frontend reload   -> SIGHUP to PID 1 (gunicorn master re-reads
#                            install/gunicorn_conf.py and restarts workers)
#       frontend restart  -> SIGTERM to PID 1; the container exits and the
#                            compose restart policy (restart: always) revives
#                            it. Without such a policy the container stays
#                            down — reload is therefore the default action.
#       daemon restart    -> Pyro RPC terminate_daemon(); the daemon
#                            container exits and its restart policy revives it.
#
# All functions return (ok: bool, message: str); the message is suitable
# for flash(). Failures never raise.
#
import logging
import os
import signal
import subprocess
import threading

from aot.utils.system_environment import is_docker

default_logger = logging.getLogger('aot.service_control')


def _install_directory():
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..'))


def _pid1_is_gunicorn():
    try:
        with open('/proc/1/cmdline', 'rb') as f:
            return b'gunicorn' in f.read()
    except OSError:
        return False


def _run_wrapper(action, delay_sec, logger):
    """systemd path: invoke the setuid aot_wrapper binary."""
    sleep_prefix = f"sleep {int(delay_sec)} && " if delay_sec else ""
    cmd = f"{sleep_prefix}{_install_directory()}/aot/scripts/aot_wrapper {action} 2>&1"
    logger.info(f"service_control: executing '{action}' via aot_wrapper")
    subprocess.Popen(cmd, shell=True)


def _deferred(delay_sec, func):
    """Run func after delay_sec so the HTTP response is sent first."""
    timer = threading.Timer(max(0.5, float(delay_sec)), func)
    timer.daemon = True
    timer.start()


def reload_frontend(delay_sec=0, logger=None):
    """Reload the web frontend: re-reads gunicorn_conf.py (thread count,
    new controller/widget modules) without dropping the service for long."""
    logger = logger or default_logger
    if is_docker():
        if not _pid1_is_gunicorn():
            msg = ("Cannot reload: PID 1 is not gunicorn "
                   "(unsupported container layout).")
            logger.error(f"service_control: {msg}")
            return False, msg

        def do_hup():
            logger.info("service_control: SIGHUP to gunicorn master (PID 1)")
            try:
                os.kill(1, signal.SIGHUP)
            except OSError:
                logger.exception("service_control: SIGHUP failed")

        _deferred(delay_sec, do_hup)
        return True, "Web server is reloading."
    _run_wrapper('frontend_reload', delay_sec, logger)
    return True, "Web server is reloading."


def restart_frontend(delay_sec=0, logger=None):
    """Fully restart the web frontend. In Docker this terminates the
    container and relies on the compose restart policy to bring it back."""
    logger = logger or default_logger
    if is_docker():
        if not _pid1_is_gunicorn():
            msg = ("Cannot restart: PID 1 is not gunicorn "
                   "(unsupported container layout).")
            logger.error(f"service_control: {msg}")
            return False, msg

        def do_term():
            logger.info("service_control: SIGTERM to gunicorn master (PID 1)")
            try:
                os.kill(1, signal.SIGTERM)
            except OSError:
                logger.exception("service_control: SIGTERM failed")

        _deferred(delay_sec, do_term)
        return True, "Web server container is restarting."
    _run_wrapper('frontend_restart', delay_sec, logger)
    return True, "Web server is restarting."


def restart_daemon(delay_sec=0, logger=None):
    """Restart the aot daemon (backend). In Docker the daemon terminates
    itself via RPC and its container restart policy revives it."""
    logger = logger or default_logger
    if is_docker():
        def do_terminate():
            logger.info("service_control: terminate_daemon() via Pyro RPC")
            try:
                from aot.aot_client import DaemonControl
                DaemonControl(pyro_timeout=5).terminate_daemon()
            except Exception:
                logger.exception("service_control: terminate_daemon failed")

        _deferred(delay_sec, do_terminate)
        return True, "Daemon is restarting (a few seconds of downtime)."
    _run_wrapper('daemon_restart', delay_sec, logger)
    return True, "Daemon is restarting (a few seconds of downtime)."
