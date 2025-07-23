#!/bin/bash
set -e

echo "Running database migrations..."

# Check if containers are running
if ! docker-compose ps app | grep -q "Up"; then
    echo "Error: App container is not running. Start the environment first with ./scripts/local/start.sh"
    exit 1
fi

# Check if database is ready
echo "Checking database connection..."
until docker-compose exec pgsql pg_isready -U devpush-app; do
    echo "Database not ready yet..."
    sleep 2
done

echo "Database is ready. Running migrations..."
docker-compose exec app uv run alembic upgrade head

echo "Migrations completed successfully!" 