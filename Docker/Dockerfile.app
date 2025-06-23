FROM python:3.13-slim

# Install system dependencies and bash (required for su to work)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    supervisor \
    bash \
 && rm -rf /var/lib/apt/lists/*

# Create non-root user with a valid shell and no password
RUN useradd -u 1000 -r -g nogroup -d /app -s /bin/bash appuser \
 && mkdir -p /app && chown appuser:nogroup /app

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy app code
COPY ./web/ .
COPY ./shared/ /shared/

# Fix permissions at build time for copied files
RUN chown -R appuser:nogroup /app /shared

# Ensure necessary dirs exist
RUN mkdir -p /data \
 && mkdir -p /app/app/static/upload \
 && mkdir -p /app/.cache \
 && chown -R appuser:nogroup /data /app/.cache

ENV UV_CACHE_DIR=/app/.cache/uv

# Still run as root (so we can fix volume perms at container startup)
USER root

EXPOSE 8000

# Copy supervisor config
COPY Docker/supervisord.app.conf /etc/supervisord.conf

# Entrypoint: fix volume permissions, then drop to appuser
ENTRYPOINT ["sh", "-c", "chown -R appuser:nogroup /data /app/app/static/upload && su appuser -c 'uv run flask db upgrade && uv run supervisord -c /etc/supervisord.conf'"]