#!/bin/bash
# system_recovery.sh - AoT System Recovery Script
# Purpose: Restore Nginx, fix Python dependencies, and recover services.
# 
# Usage: sudo /bin/bash system_recovery.sh

if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root."
    exit 1
fi

AOT_PATH="/opt/AoT" # Adjust if necessary
ENV_PATH="${AOT_PATH}/env"

echo "### Phase 1: System Level Recovery"
echo "#### Reinstalling Nginx..."
apt-get update
apt-get install -o Dpkg::Options::='--force-confmiss' --reinstall -y nginx nginx-common
apt-get install -y python3-dev

echo "### Phase 2: Virtual Environment Recovery"
if [ ! -d "$ENV_PATH" ]; then
    echo "#### Error: $ENV_PATH not found. Creating a new one..."
    python3 -m venv "$ENV_PATH"
fi

echo "#### Reinstalling Core Python Packages..."
"${ENV_PATH}/bin/pip" install --force-reinstall gunicorn Flask

echo "#### Upgrading SQLAlchemy to 2.0.48 (Python 3.13 compatibility)..."
"${ENV_PATH}/bin/pip" install SQLAlchemy==2.0.48

echo "#### Downgrading setuptools to 70.0.0 (Resolving pkg_resources error)..."
"${ENV_PATH}/bin/pip" install setuptools==70.0.0

echo "#### Installing remaining requirements..."
"${ENV_PATH}/bin/pip" install -r "${AOT_PATH}/install/requirements.txt"

echo "### Phase 3: Service Recovery"
echo "#### Reloading systemd and restarting services..."
systemctl daemon-reload
systemctl restart nginx
systemctl restart aot.service
systemctl restart aotflask.service

echo "### Phase 4: Verification"
echo "#### Nginx Status:"
systemctl is-active nginx
echo "#### AoT Service Status:"
systemctl is-active aot.service
echo "#### AoTFlask Service Status:"
systemctl is-active aotflask.service

echo "### Recovery Complete."
