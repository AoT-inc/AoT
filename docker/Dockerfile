# Base image
FROM python:3.11-slim

# 설치 대상 명시 (detect_platform.sh의 자동 감지보다 우선)
ENV INSTALL_TARGET=docker

# Set working directory
WORKDIR /app

# Install system dependencies including Node.js (required for npx-based MCP servers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create the 'aot' user/group so set_user_grp() (aot/utils/system_pi.py) can chown
# generated files instead of skipping with a "not found" warning
RUN groupadd -r aot && useradd -r -g aot aot

# Copy requirements and install
COPY requirements.txt ./requirements.txt
# 베이스 이미지에 딸려오는 pip/setuptools 자체에도 알려진 취약점이 있어 먼저 올린다
# (requirements.txt 에 없는 빌드 도구라 그쪽으로는 통제되지 않는다).
RUN pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the application port (HTTP default)
EXPOSE 80

# Run the application (using start_flask_ui.py without SSL for local dev connectivity)
CMD ["python", "aot/start_flask_ui.py", "-s", "-p", "80"]
