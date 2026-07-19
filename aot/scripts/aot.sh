#!/bin/bash

# AoT System Management Script
# Supports starting, stopping, and checking the status of both the Daemon and Web UI.
# Robust for both macOS and Debian/Raspberry Pi.

# Script lives in aot/scripts; project root is two levels up.
export PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export AOT_ROOT="${PROJECT_DIR}"
PYTHON_BIN="${PROJECT_DIR}/env/bin/python"
VENV_SITEPACKAGES="${PROJECT_DIR}/env/lib/python3.9/site-packages"

# Hybrid Latency Optimization: Use local storage via env var if provided
if [ -n "${AOT_LOCAL_DIR}" ] && [ -f "${AOT_LOCAL_DIR}/env/bin/python3" ]; then
    echo "⚡ Using local high-performance environment from AOT_LOCAL_DIR: ${AOT_LOCAL_DIR}"
    export AOT_LOCAL_DIR="${AOT_LOCAL_DIR}"
    PYTHON_BIN="${AOT_LOCAL_DIR}/env/bin/python3"
    VENV_SITEPACKAGES="${AOT_LOCAL_DIR}/env/lib/python3.9/site-packages"
else
    if [ ! -f "${PYTHON_BIN}" ]; then
        PYTHON_BIN=$(which python3)
        echo "⚠️  Virtual environment not found, falling back to system python: ${PYTHON_BIN}"
    fi
fi

export PYTHONPATH="${VENV_SITEPACKAGES}:${PROJECT_DIR}"
DAEMON_SCRIPT="aot/aot_daemon.py"
UI_SCRIPT="aot/start_flask_ui.py"
UI_PORT=8084

# Function to check status
check_status() {
    DAEMON_PID=$(pgrep -f "${DAEMON_SCRIPT}" | head -n 1)
    UI_PID=$(pgrep -f "${UI_SCRIPT}" | head -n 1)

    if [ -n "${DAEMON_PID}" ]; then
        echo "✅ Daemon is running (PID: ${DAEMON_PID})"
    else
        echo "❌ Daemon is NOT running"
    fi

    if [ -n "${UI_PID}" ]; then
        echo "✅ Web UI is running (PID: ${UI_PID}, Port: ${UI_PORT})"
    else
        echo "❌ Web UI is NOT running"
    fi
}

# Function to stop services
stop_services() {
    echo "Stopping AoT services..."
    # Kill Daemon (sudo might be required if it was started with sudo)
    DAEMON_PID=$(pgrep -f "${DAEMON_SCRIPT}")
    if [ -n "${DAEMON_PID}" ]; then
        sudo kill ${DAEMON_PID} 2>/dev/null || kill ${DAEMON_PID} 2>/dev/null
        echo "Stopped Daemon"
    fi

    # Kill Web UI
    UI_PID=$(pgrep -f "${UI_SCRIPT}")
    if [ -n "${UI_PID}" ]; then
        kill ${UI_PID} 2>/dev/null
        echo "Stopped Web UI"
    fi
    sleep 1
}

# Function to start services
start_services() {
    echo "Starting AoT services..."
    
    # Start Daemon
    if ! pgrep -f "${DAEMON_SCRIPT}" > /dev/null; then
        "${PYTHON_BIN}" "${PROJECT_DIR}/${DAEMON_SCRIPT}" > "/tmp/daemon.log" 2>&1 &
        echo "Daemon started in background"
    else
        echo "Daemon is already running"
    fi

    # Start Web UI
    if ! pgrep -f "${UI_SCRIPT}" > /dev/null; then
        "${PYTHON_BIN}" "${PROJECT_DIR}/${UI_SCRIPT}" --port "${UI_PORT}" > "/tmp/ui.log" 2>&1 &
        echo "Web UI started in background (Port: ${UI_PORT})"
    else
        echo "Web UI is already running"
    fi
}

case "$1" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        start_services
        ;;
    status)
        check_status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac

exit 0
