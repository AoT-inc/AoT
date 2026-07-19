#!/bin/bash
# Restart Flask App
cd "$(dirname "$0")/../.." || exit 1
/Applications/Docker.app/Contents/Resources/bin/docker compose -f docker/docker-compose.yml restart aot-app
