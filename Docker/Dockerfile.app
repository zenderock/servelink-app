FROM python:3.13-slim

# Create non-root user
RUN addgroup appgroup && adduser --ingroup appgroup --home /app --shell /bin/sh --no-create-home appuser

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

# Set UV cache directory to writable location
RUN mkdir -p /app/.cache && chown -R appuser:appgroup /app/.cache
ENV UV_CACHE_DIR=/app/.cache/uv

EXPOSE 8000

# Supervisor process manager
COPY Docker/supervisord.app.conf /etc/supervisord.conf
ENTRYPOINT ["sh","-c","chown -R appuser:appgroup /data /app/app/static/upload && exec su -s /bin/sh appuser -c 'uv run supervisord -c /etc/supervisord.conf'"]