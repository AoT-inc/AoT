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
# pyrender 0.1.45 는 setup.py 에 PyOpenGL==3.1.0 을 못박아두었지만, 그 버전에는 OSMesa
# 컨텍스트 생성 심볼(OSMesaCreateContextAttribs)이 빠져 있어 헤드리스 렌더링이 항상 실패한다.
# --no-deps 로 pyrender 의 과도한 상한 핀을 우회해 최신 PyOpenGL 로 교체한다.
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps --upgrade "PyOpenGL>=3.1.6"

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
# 이 이미지로 뜬 컨테이너는 (docker-compose 든 단독 `docker run` 이든) 항상
# Docker 컨테이너다 -- 그런데 이 값은 각 docker-compose*.yml 의 `environment:`
# 에서만 켜져 있었다. 그래서 compose 없이 이 이미지를 그대로 실행하면(예:
# Docker Desktop 의 "Run" 버튼) DOCKER_CONTAINER 가 꺼진 채로 뜨고,
# register_extensions()(aot_flask/app.py)의 "Docker 환경이면 강제 HTTPS 끄기"
# 분기가 발동하지 않아 Misc.force_https 기본값(True)이 그대로 적용된다. 그
# 결과 HTTP 만 서빙하는 컨테이너(CMD 의 `-s`)가 모든 요청을 https:// 로
# 302 리다이렉트해 브라우저가 접속하지 못한다(2026-09-28 실측). compose
# 파일들은 이미 같은 값을 명시적으로 주므로 여기서 기본값으로 바꿔도 그쪽
# 동작은 그대로다.
ENV DOCKER_CONTAINER=TRUE
WORKDIR /app

# Node.js: genuinely needed at runtime (aot/ai/agents/mcp_*.py shells out to
# `npx` to run several built-in MCP servers). curl only exists to fetch the
# nodesource setup script one line down -- kept rather than stripped after,
# since it costs single-digit MB and a second apt pass to remove it isn't
# worth the extra layer.
# libgl1/libosmesa6/libx11-6/libxext6/libxrender1: pyrender(trimesh)의 시설 3D 모델(.glb)
# 미리보기 썸네일 헤드리스 렌더링(OSMesa 소프트웨어 렌더러)에 필요. 없으면 `import pyrender`
# 시점에 ImportError가 나서 미리보기가 조용히 회색 placeholder로만 생성된다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libosmesa6 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# GPU/디스플레이 없는 컨테이너이므로 pyrender 오프스크린 렌더러는 OSMesa(소프트웨어) 백엔드로 고정
ENV PYOPENGL_PLATFORM=osmesa

# Create the 'aot' user/group so set_user_grp() (aot/utils/system_pi.py) can chown
# generated files instead of skipping with a "not found" warning
RUN groupadd -r aot && useradd -r -g aot aot

COPY --from=builder /usr/local /usr/local

# Copy the rest of the application
COPY . .

# Expose the application port (HTTP default)
EXPOSE 80

# Runs once per container start (regenerates widget_template_*.html, which
# is never baked into the image -- see install/docker_entrypoint.sh), then
# execs whichever command the service actually wants (CMD below for aot-app,
# or docker-compose.prod.yml's per-service `command:` override for
# aot_daemon/aot_mcp).
ENTRYPOINT ["install/docker_entrypoint.sh"]

# Run the application (using start_flask_ui.py without SSL for local dev connectivity)
CMD ["python", "aot/start_flask_ui.py", "-s", "-p", "80"]
