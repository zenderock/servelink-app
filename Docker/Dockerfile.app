FROM python:3.13-slim

# Create non-root user
RUN addgroup --gid 1000 appgroup \
    && adduser  --uid 1000 --gid 1000 --system --home /app appuser

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project
COPY ./app/ .

# Set permissions
RUN chown -R appuser:appgroup /app

# Set UV cache directory to writable location
RUN mkdir -p /app/.cache && chown -R appuser:appgroup /app/.cache
ENV UV_CACHE_DIR=/app/.cache/uv

# Switch to non-root user
USER appuser

EXPOSE 8000

# Run migrations then start FastAPI
COPY Docker/supervisord.app.conf /etc/supervisord.conf
CMD ["sh", "-c", "uv run alembic upgrade head && exec supervisord -c /etc/supervisord.conf"]