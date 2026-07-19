#!/bin/bash
# Restart All Services (running from local path to avoid Synology cloud sync conflicts)
cd "$(dirname "$0")/../.." || exit 1
/Applications/Docker.app/Contents/Resources/bin/docker compose -p aot_local -f docker/docker-compose.yml restart
