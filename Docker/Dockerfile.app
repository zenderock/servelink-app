FROM python:3.13-slim

# Create non-root user with a fixed UID and GID
RUN addgroup --system appgroup && adduser --system --group --home /app --shell /bin/bash appuser

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlite3 \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project
COPY ./web/ .
COPY ./shared/ /shared/

# Set permissions
RUN chown -R appuser:appgroup /app /shared

# Make sure data directory exists and set permissions
RUN mkdir -p /data && chown -R appuser:appgroup /data

# Make sure upload directory exists
RUN mkdir -p /app/app/static/upload/

# Set UV cache directory to writable location
RUN mkdir -p /app/.cache && chown -R appuser:appgroup /app/.cache
ENV UV_CACHE_DIR=/app/.cache/uv

# Switch to non-root user
USER root

EXPOSE 8000

# Supervisor process manager
COPY Docker/supervisord.app.conf /etc/supervisord.conf
ENTRYPOINT ["sh", "-c", "chown -R appuser:appgroup /data /app/app/static/upload && su appuser -c 'uv run flask db upgrade && uv run supervisord -c /etc/supervisord.conf'"]