FROM python:3.13-slim

# Create non-root user
RUN addgroup --system appgroup && adduser --system --group appuser

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        sqlite3 \
        supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the project files and install requirements
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

# Set correct permissions
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose Flask port
EXPOSE 8000

# Copy Supervisor configuration
COPY Docker/supervisord.app.conf /etc/supervisord.conf

# Start the Supervisor process manager
CMD ["supervisord", "-c", "/etc/supervisord.conf"]