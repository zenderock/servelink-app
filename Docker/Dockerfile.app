FROM python:3.13-slim

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

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

# Set permissions
RUN chown -R appuser:appgroup /app

# Create data directory with proper permissions
RUN mkdir -p /data && chown -R appuser:appgroup /data

# Switch to non-root user
USER appuser

EXPOSE 8000

# Supervisor process manager
COPY Docker/supervisord.app.conf /etc/supervisord.conf
ENTRYPOINT ["sh", "-c", "uv run flask db upgrade && uv run supervisord -c /etc/supervisord.conf"]