FROM python:3.13-slim

# Create non-root user
RUN addgroup --gid 1000 appgroup \
    && adduser  --uid 1000 --gid 1000 --system --home /app appuser

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    libpq-dev \
    libffi-dev \
    gcc \
    g++ \
    make \
    autoconf \
    automake \
    libtool \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project
COPY ./app/ .

# Copy entrypoint scripts
COPY Docker/entrypoint.app.sh /entrypoint.app.sh
COPY Docker/entrypoint.worker-arq.sh /entrypoint.worker-arq.sh
COPY Docker/entrypoint.worker-monitor.sh /entrypoint.worker-monitor.sh

# Set permissions
RUN chown -R appuser:appgroup /app && \
    chmod +x /entrypoint.app.sh /entrypoint.worker-arq.sh /entrypoint.worker-monitor.sh

# Set UV cache directory and home
ENV UV_CACHE_DIR=/tmp/uv
ENV HOME=/app

# Switch to non-root user
USER appuser

EXPOSE 8000