FROM python:3.13-slim

# Create non-root user
RUN addgroup --system appgroup \
 && adduser --system --group --home /app --shell /bin/sh appuser

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

EXPOSE 8000

# Run migrations then start FastAPI
COPY Docker/supervisord.app.conf /etc/supervisord.conf
CMD ["sh","-c",
     "uv run alembic upgrade head && \
      chown -R appuser:appgroup /app/.cache && \
      exec supervisord -c /etc/supervisord.conf"]