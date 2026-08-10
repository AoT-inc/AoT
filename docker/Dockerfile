# ---- Build stage -----------------------------------------------------------
# Compiles/collects everything requirements.txt needs. build-essential is a
# safety net for the multi-arch CI build (docker-publish.yml builds arm64 under
# QEMU emulation, where a package that lacks a prebuilt wheel would otherwise
# fail to install) -- measured 2026-08-11: every current dependency already
# installs from a wheel with no compiler present, so this stage typically does
# no compiling at all, it just isn't worth losing multi-arch coverage to save
# the ~450MB this costs. That ~450MB never reaches the final image below.
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
# 베이스 이미지에 딸려오는 pip/setuptools 자체에도 알려진 취약점이 있어 먼저 올린다
# (requirements.txt 에 없는 빌드 도구라 그쪽으로는 통제되지 않는다).
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt

# ---- Runtime stage ----------------------------------------------------------
# Only what the running app actually touches. No compiler, no libpq-dev (no
# package here links against it -- it was never explained by anything in the
# tree, just carried over).
#
# What this means for the on-demand hardware-driver installer
# (routes_admin.install_dependencies -> aot_wrapper -> a fresh venv under
# /app/env): that path is live in Docker -- confirmed 2026-08-11, it really
# does create the venv and pip-install on request -- but every driver it can
# be asked to install (RPi.GPIO, pigpio, bluepy, wiringpi, ...) needs GPIO/
# I2C/SPI/BLE device access that neither docker-compose.yml nor
# docker-compose.prod.yml grants (no `privileged:`, no `devices:`). Those
# installs were already unable to do anything useful before this change; now
# a C-extension driver among them would also fail to compile, which is a
# clearer failure than "installed fine, then couldn't reach hardware that was
# never mounted." If a compose file is ever extended with real device
# passthrough, build-essential belongs back in this stage.
FROM python:3.11-slim

ENV INSTALL_TARGET=docker
WORKDIR /app

# Node.js: genuinely needed at runtime (aot/ai/agents/mcp_*.py shells out to
# `npx` to run several built-in MCP servers). curl only exists to fetch the
# nodesource setup script one line down -- kept rather than stripped after,
# since it costs single-digit MB and a second apt pass to remove it isn't
# worth the extra layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create the 'aot' user/group so set_user_grp() (aot/utils/system_pi.py) can chown
# generated files instead of skipping with a "not found" warning
RUN groupadd -r aot && useradd -r -g aot aot

COPY --from=builder /usr/local /usr/local

# Copy the rest of the application
COPY . .

# Expose the application port (HTTP default)
EXPOSE 80

# Run the application (using start_flask_ui.py without SSL for local dev connectivity)
CMD ["python", "aot/start_flask_ui.py", "-s", "-p", "80"]
